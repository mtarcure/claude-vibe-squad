#!/usr/bin/env node

import {
  listFiles,
  pathDetails,
  readJson,
  readText,
  sha256,
} from "../adapters/filesystem.mjs";
import { scanSecretsWithGitleaks } from "../adapters/process.mjs";
import { validateNamed } from "../schema/validate.mjs";
import { analyzeSource } from "./ast-analysis.mjs";

const MOAT_ROOT = new URL("../", import.meta.url);

export const ERROR_CLASSES = Object.freeze({
  CAPABILITY_IMPORT: "MOAT_BOUNDARY_CAPABILITY_IMPORT",
  CONTENT_CLASS: "MOAT_BOUNDARY_CONTENT_CLASS",
  DIRECT_PRIVATE_READ: "MOAT_BOUNDARY_DIRECT_PRIVATE_READ",
  ENCODED_IDENTIFIER: "MOAT_BOUNDARY_ENCODED_IDENTIFIER",
  EXTERNAL_IDENTIFIER: "MOAT_BOUNDARY_EXTERNAL_IDENTIFIER",
  FORBIDDEN_IMPORT: "MOAT_BOUNDARY_FORBIDDEN_IMPORT",
  PATH_ROOT: "MOAT_BOUNDARY_PATH_ROOT",
  SCHEMA_INVALID: "MOAT_BOUNDARY_SCHEMA_INVALID",
  SECRET: "MOAT_BOUNDARY_SECRET",
  SOURCE_PARSE: "MOAT_BOUNDARY_SOURCE_PARSE",
  TOOL_UNAVAILABLE: "MOAT_BOUNDARY_TOOL_UNAVAILABLE",
});

const schemaBySuffix = new Map([
  [".invariant.json", "InvariantDescriptor"],
  [".guard.json", "GuardAnnotation"],
  [".verdict.json", "Verdict"],
  [".wave.json", "WaveResult"],
]);

const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]);

const finding = (errorClass, file, line, message) => ({ errorClass, file, line, message });

const lineForOffset = (text, offset) => text.slice(0, offset).split("\n").length;

function decodeEscapes(text) {
  return text
    .replace(/\\u\{([0-9a-f]{1,6})\}/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/\\u([0-9a-f]{4})/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/\\x([0-9a-f]{2})/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)));
}

function entropy(value) {
  const counts = new Map();
  for (const character of value) counts.set(character, (counts.get(character) ?? 0) + 1);
  return [...counts.values()].reduce((total, count) => {
    const probability = count / value.length;
    return total - probability * Math.log2(probability);
  }, 0);
}

function ipv4Allowed(value) {
  const parts = value.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  return parts[0] === 127
    || (parts[0] === 192 && parts[1] === 0 && parts[2] === 2)
    || (parts[0] === 198 && parts[1] === 51 && parts[2] === 100)
    || (parts[0] === 203 && parts[1] === 0 && parts[2] === 113);
}

function hostAllowed(host, policy) {
  const normalized = host.toLowerCase().replace(/^\[|\]$/gu, "").replace(/\.$/u, "");
  if (normalized === "::1" || ipv4Allowed(normalized)) return true;
  if (policy.allowed_hosts.includes(normalized)) return true;
  return policy.allowed_host_suffixes.some((suffix) => normalized.endsWith(suffix));
}

function ipv6Allowed(value, policy) {
  const normalized = value.toLowerCase().replace(/^\[|\]$/gu, "");
  if (policy.allowed_ipv6.includes(normalized)) return true;
  if (!/^[0-9a-f:]+$/u.test(normalized) || !normalized.includes(":")) return true;
  if ((normalized.match(/::/gu) ?? []).length > 1) return true;
  const parts = normalized.split(":");
  const nonempty = parts.filter(Boolean);
  if (nonempty.some((part) => part.length > 4)) return true;
  const valid = normalized.includes("::") ? nonempty.length < 8 : nonempty.length === 8;
  return !valid;
}

function externalIdentifiers(text, policy) {
  const results = [];
  const seen = new Set();
  const candidates = [String(text), decodeEscapes(String(text))];

  for (const candidate of candidates) {
    const urlRanges = [];
    for (const match of candidate.matchAll(/\bhttps?:\/\/[^\s"'`<>]+/giu)) {
      urlRanges.push([match.index, match.index + match[0].length]);
      let host;
      try { host = new URL(match[0]).hostname; } catch { host = undefined; }
      if (host && !hostAllowed(host, policy)) {
        const key = `${match.index}:${host}`;
        if (!seen.has(key)) results.push({ offset: match.index, kind: host.includes(":") ? "external IPv6 address" : "external URL host" });
        seen.add(key);
      }
    }

    for (const match of candidate.matchAll(/\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|dev|app|cloud|ai|corp|internal)\b/giu)) {
      if (urlRanges.some(([start, end]) => match.index >= start && match.index < end)) continue;
      if (!hostAllowed(match[0], policy)) {
        const key = `${match.index}:${match[0]}`;
        if (!seen.has(key)) results.push({ offset: match.index, kind: "external hostname" });
        seen.add(key);
      }
    }

    for (const match of candidate.matchAll(/(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])/gu)) {
      if (!ipv4Allowed(match[0])) {
        const key = `${match.index}:${match[0]}`;
        if (!seen.has(key)) results.push({ offset: match.index, kind: "non-reserved IP address" });
        seen.add(key);
      }
    }

    for (const match of candidate.matchAll(/(?<![0-9a-f:])(?=[0-9a-f:]*:[0-9a-f:]*:)[0-9a-f:]{3,}(?![0-9a-f:])/giu)) {
      if (urlRanges.some(([start, end]) => match.index >= start && match.index < end)) continue;
      if (!ipv6Allowed(match[0], policy)) {
        const key = `${match.index}:${match[0]}`;
        if (!seen.has(key)) results.push({ offset: match.index, kind: "external IPv6 address" });
        seen.add(key);
      }
    }
  }

  return results;
}

function encodedIdentifiers(text, policy) {
  const results = [];
  for (const match of text.matchAll(/(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/_-])/gu)) {
    try {
      const decoded = Buffer.from(match[0], "base64url").toString("utf8");
      const printable = [...decoded].filter((character) => character === "\n" || character === "\r" || character === "\t" || (character >= " " && character <= "~")).length;
      if (
        decoded.length
        && printable / decoded.length > 0.9
        && policy.synthetic_deny_markers.some((marker) => decoded.includes(marker))
      ) {
        results.push({ offset: match.index });
      }
    } catch {
      // Invalid base64 is not treated as encoded target material.
    }
  }
  return results;
}

function secretOffsets(text) {
  const offsets = [];
  const credentialPatterns = [
    /\bAKIA[A-Z0-9]{16}\b/gu,
    /\bgh[pousr]_[A-Za-z0-9]{30,}\b/gu,
    /\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*["']?[^\s"']{16,}/giu,
  ];
  for (const expression of credentialPatterns) {
    for (const match of text.matchAll(expression)) offsets.push(match.index);
  }

  for (const match of text.matchAll(/["']([A-Za-z0-9+/_=-]{32,})["']/gu)) {
    const value = match[1];
    if (/^[a-f0-9]{32,}$/iu.test(value) || /^[0-9a-f]{8}-[0-9a-f-]{27}$/iu.test(value)) continue;
    let decoded = "";
    try { decoded = Buffer.from(value, "base64").toString("utf8"); } catch { decoded = ""; }
    if (/synthetic|protocol|example/iu.test(decoded)) continue;
    if (/[a-z]/u.test(value) && /[A-Z]/u.test(value) && /\d/u.test(value) && entropy(value) >= 4.5) offsets.push(match.index);
  }
  return [...new Set(offsets)];
}

function inspectStructured(value, file, findings, policy, path = "$") {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => inspectStructured(entry, file, findings, policy, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;

  for (const [key, child] of Object.entries(value)) {
    const childPath = `${path}.${key}`;
    if (key === "content_class" && typeof child === "string" && child !== "public-safe") {
      findings.push(finding(ERROR_CLASSES.CONTENT_CLASS, file, 1, `${childPath} must be public-safe in Layer 1`));
    }
    if (key.endsWith("_ref") && typeof child === "string") {
      const isLogicalRef = /^[a-z][a-z0-9_-]*:[A-Za-z0-9._/-]+$/u.test(child);
      if (!isLogicalRef || child.includes("..") || child.includes("_state/bounty") || child.startsWith("/")) {
        findings.push(finding(ERROR_CLASSES.PATH_ROOT, file, 1, `${childPath} must be a logical external reference`));
      }
    }
    if (
      typeof child === "string"
      && ["endpoint", "fixture_path", "host", "hostname", "path", "target", "target_host", "target_url", "url"].includes(key)
    ) {
      for (const item of externalIdentifiers(child, policy)) {
        findings.push(finding(ERROR_CLASSES.EXTERNAL_IDENTIFIER, file, 1, `${childPath} contains an ${item.kind}`));
      }
    }
    inspectStructured(child, file, findings, policy, childPath);
  }
}

function syntheticMarkerOffsets(text, policy) {
  const decoded = decodeEscapes(text);
  return policy.synthetic_deny_markers.flatMap((marker) => {
    const offset = decoded.indexOf(marker);
    return offset < 0 ? [] : [offset];
  });
}

async function reviewedFixtureMap() {
  const manifest = await readJson(new URL("./reviewed-fixtures.json", import.meta.url));
  return new Map(manifest.files.map((entry) => [entry.path, entry.sha256]));
}

async function isReviewedFixture(details, allowlist) {
  const expected = allowlist.get(details.relative);
  return expected ? (await sha256(details.absolute)) === expected : false;
}

async function scanFile(file, options, policy, allowlist) {
  const details = pathDetails(file, MOAT_ROOT);
  const findings = [];
  if (!details.withinRoot) {
    return [finding(ERROR_CLASSES.PATH_ROOT, details.absolute, 1, "staged path is outside the Layer-1 root")];
  }
  if (options.honorReviewedFixtureAllowlist && await isReviewedFixture(details, allowlist)) return [];

  const text = await readText(details.absolute);
  const displayFile = `moat/${details.relative}`;
  if (details.relative.startsWith("node_modules/")) return [];
  const isSource = sourceExtensions.has(details.extension);
  const inspectionModule = policy.inspection_implementation_modules.includes(details.relative);

  if (isSource) {
    const analysis = analyzeSource(text, details.basename, {
      restrictedModules: policy.restricted_node_modules,
    });
    for (const parseError of analysis.parseErrors) {
      findings.push(finding(ERROR_CLASSES.SOURCE_PARSE, displayFile, lineForOffset(text, parseError.offset), parseError.message));
    }
    for (const specifier of analysis.imports) {
      if (policy.forbidden_import_fragments.some((fragment) => specifier.value.includes(fragment))) {
        findings.push(finding(ERROR_CLASSES.FORBIDDEN_IMPORT, displayFile, lineForOffset(text, specifier.offset), "forbidden target-data import"));
      }
      if (policy.restricted_node_modules.includes(specifier.value) && !policy.approved_capability_modules.includes(details.relative)) {
        findings.push(finding(ERROR_CLASSES.CAPABILITY_IMPORT, displayFile, lineForOffset(text, specifier.offset), "capability import must be isolated in a declared adapter"));
      }
    }
    for (const unresolved of analysis.unresolvedImports) {
      findings.push(finding(ERROR_CLASSES.CAPABILITY_IMPORT, displayFile, lineForOffset(text, unresolved.offset), "dynamic module specifier must resolve to a bounded constant"));
    }

    if (!inspectionModule && details.relative !== policy.approved_external_input_adapter) {
      for (const offset of analysis.directPrivateReads) {
        findings.push(finding(ERROR_CLASSES.DIRECT_PRIVATE_READ, displayFile, lineForOffset(text, offset), "private root access must use the external-input adapter"));
      }
    }

    for (const flow of analysis.flows) {
      for (const item of externalIdentifiers(flow.value, policy)) {
        const errorClass = flow.encoded ? ERROR_CLASSES.ENCODED_IDENTIFIER : ERROR_CLASSES.EXTERNAL_IDENTIFIER;
        findings.push(finding(errorClass, displayFile, lineForOffset(text, flow.offset), `${item.kind} flows into capability sink ${flow.sink}`));
      }
    }
    for (const constant of analysis.constantValues) {
      if (policy.synthetic_deny_markers.some((marker) => constant.value.includes(marker))) {
        findings.push(finding(ERROR_CLASSES.EXTERNAL_IDENTIFIER, displayFile, lineForOffset(text, constant.offset), "synthetic red-team identifier is not public-safe"));
      }
    }
  }
  if (details.relative !== "boundary/policy.json") {
    for (const offset of syntheticMarkerOffsets(text, policy)) {
      findings.push(finding(ERROR_CLASSES.EXTERNAL_IDENTIFIER, displayFile, lineForOffset(text, offset), "synthetic red-team identifier is not public-safe"));
    }
  }
  for (const item of encodedIdentifiers(text, policy)) {
    findings.push(finding(ERROR_CLASSES.ENCODED_IDENTIFIER, displayFile, lineForOffset(text, item.offset), "encoded external identifier is not public-safe"));
  }
  if (details.basename !== "package-lock.json") {
    for (const offset of secretOffsets(text)) {
      findings.push(finding(ERROR_CLASSES.SECRET, displayFile, lineForOffset(text, offset), "credential-shaped or high-entropy material is not allowed"));
    }
  }
  const establishedSecretScan = scanSecretsWithGitleaks(text);
  if (!establishedSecretScan.available) {
    findings.push(finding(ERROR_CLASSES.TOOL_UNAVAILABLE, displayFile, 1, "gitleaks is required for calibrated secret scanning"));
  } else {
    const secretAllowance = policy.secret_scan_allowlist?.find((entry) => entry.path === details.relative);
    const allowedSecretRules = new Set(
      secretAllowance && await sha256(details.absolute) === secretAllowance.sha256
        ? secretAllowance.rule_ids
        : [],
    );
    for (const item of establishedSecretScan.findings.filter((item) => !allowedSecretRules.has(item.ruleId))) {
      findings.push(finding(ERROR_CLASSES.SECRET, displayFile, item.line, `gitleaks rule ${item.ruleId} matched redacted material`));
    }
  }

  if (details.extension === ".json") {
    try {
      const value = JSON.parse(text);
      inspectStructured(value, displayFile, findings, policy);
      const schemaEntry = [...schemaBySuffix].find(([suffix]) => details.basename.endsWith(suffix));
      if (schemaEntry) {
        const errors = await validateNamed(schemaEntry[1], value);
        for (const error of errors) {
          findings.push(finding(ERROR_CLASSES.SCHEMA_INVALID, displayFile, 1, `${error.instancePath || "$"}: ${error.message}`));
        }
      }
    } catch (error) {
      findings.push(finding(ERROR_CLASSES.SCHEMA_INVALID, displayFile, 1, `invalid JSON: ${error.message}`));
    }
  }

  return findings;
}

export async function scanPaths(paths, options = {}) {
  const policy = await readJson(new URL("./policy.json", import.meta.url));
  const allowlist = await reviewedFixtureMap();
  const findings = [];
  for (const path of paths) findings.push(...await scanFile(path, options, policy, allowlist));
  return { ok: findings.length === 0, findings };
}

export function formatFindings(findings) {
  return findings.map((item) => `${item.errorClass} ${item.file}:${item.line} ${item.message}`).join("\n");
}

async function main() {
  const args = process.argv.slice(2);
  const selfCheck = args[0] === "--self-check";
  const staged = args[0] === "--staged";
  const requested = selfCheck ? await listFiles(MOAT_ROOT) : staged ? args.slice(1) : args;
  if (staged && !requested.length) return;
  if (!requested.length) {
    console.error("usage: node boundary/tier-a.mjs [--self-check | --staged <file>... | <file>...]");
    process.exitCode = 2;
    return;
  }
  const result = await scanPaths(requested, {
    honorReviewedFixtureAllowlist: selfCheck || staged,
  });
  if (!result.ok) {
    console.error(formatFindings(result.findings));
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
