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

function importSpecifiers(text) {
  const specifiers = [];
  const expression = /(?:\bimport\s*(?:\([^)]*?\)|[^;\n]*?\sfrom\s*)|\bexport\s+[^;\n]*?\sfrom\s*|\brequire\s*\()\s*["']([^"']+)["']/gu;
  for (const match of text.matchAll(expression)) specifiers.push({ value: match[1], offset: match.index });
  return specifiers;
}

function decodeEscapes(text) {
  return text
    .replace(/\\u\{([0-9a-f]{1,6})\}/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/\\u([0-9a-f]{4})/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/\\x([0-9a-f]{2})/giu, (_, hex) => String.fromCodePoint(Number.parseInt(hex, 16)));
}

function collapseSplitLiterals(text) {
  let current = text;
  const expression = /(["'])([^"'\n]*)\1\s*\+\s*(["'])([^"'\n]*)\3/gu;
  for (let pass = 0; pass < 8; pass += 1) {
    const next = current.replace(expression, (_, _leftQuote, left, rightQuote, right) => `${rightQuote}${left}${right}${rightQuote}`);
    if (next === current) break;
    current = next;
  }
  return current;
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

function externalIdentifiers(text, policy) {
  const results = [];
  const seen = new Set();
  const candidates = [text, decodeEscapes(text), collapseSplitLiterals(decodeEscapes(text))];

  for (const candidate of candidates) {
    for (const match of candidate.matchAll(/\bhttps?:\/\/([^\s/"'<>]+)/giu)) {
      const host = match[1].replace(/:\d+$/u, "");
      if (!hostAllowed(host, policy)) {
        const key = `${match.index}:${host}`;
        if (!seen.has(key)) results.push({ offset: match.index, kind: "external URL host" });
        seen.add(key);
      }
    }

    for (const match of candidate.matchAll(/\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|dev|app|cloud|ai|corp|internal)\b/giu)) {
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
  }

  return results;
}

function encodedIdentifiers(text, policy) {
  const results = [];
  for (const match of text.matchAll(/(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/])/gu)) {
    try {
      const decoded = Buffer.from(match[0], "base64").toString("utf8");
      const printable = [...decoded].filter((character) => character === "\n" || character === "\r" || character === "\t" || (character >= " " && character <= "~")).length;
      if (decoded.length && printable / decoded.length > 0.9 && externalIdentifiers(decoded, policy).length) {
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

function inspectStructured(value, file, findings, path = "$") {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => inspectStructured(entry, file, findings, `${path}[${index}]`));
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
    inspectStructured(child, file, findings, childPath);
  }
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
  const isSource = sourceExtensions.has(details.extension);
  const inspectionModule = policy.inspection_implementation_modules.includes(details.relative);

  if (isSource) {
    for (const specifier of importSpecifiers(text)) {
      if (policy.forbidden_import_fragments.some((fragment) => specifier.value.includes(fragment))) {
        findings.push(finding(ERROR_CLASSES.FORBIDDEN_IMPORT, displayFile, lineForOffset(text, specifier.offset), "forbidden target-data import"));
      }
      if (policy.restricted_node_modules.includes(specifier.value) && !policy.approved_capability_modules.includes(details.relative)) {
        findings.push(finding(ERROR_CLASSES.CAPABILITY_IMPORT, displayFile, lineForOffset(text, specifier.offset), "capability import must be isolated in a declared adapter"));
      }
    }

    const directRootRead = /\bprocess\s*\.\s*env\s*(?:\.\s*CHRONO_BOUNTY_ROOT|\[\s*["']CHRONO_BOUNTY_ROOT["']\s*\])/gu;
    if (!inspectionModule && details.relative !== policy.approved_external_input_adapter) {
      for (const match of text.matchAll(directRootRead)) {
        findings.push(finding(ERROR_CLASSES.DIRECT_PRIVATE_READ, displayFile, lineForOffset(text, match.index), "private root access must use the external-input adapter"));
      }
    }
  }

  for (const item of externalIdentifiers(text, policy)) {
    findings.push(finding(ERROR_CLASSES.EXTERNAL_IDENTIFIER, displayFile, lineForOffset(text, item.offset), `${item.kind} is not public-safe or reserved`));
  }
  for (const item of encodedIdentifiers(text, policy)) {
    findings.push(finding(ERROR_CLASSES.ENCODED_IDENTIFIER, displayFile, lineForOffset(text, item.offset), "encoded external identifier is not public-safe"));
  }
  for (const offset of secretOffsets(text)) {
    findings.push(finding(ERROR_CLASSES.SECRET, displayFile, lineForOffset(text, offset), "credential-shaped or high-entropy material is not allowed"));
  }
  const establishedSecretScan = scanSecretsWithGitleaks(text);
  if (!establishedSecretScan.available) {
    findings.push(finding(ERROR_CLASSES.TOOL_UNAVAILABLE, displayFile, 1, "gitleaks is required for calibrated secret scanning"));
  } else {
    for (const item of establishedSecretScan.findings) {
      findings.push(finding(ERROR_CLASSES.SECRET, displayFile, item.line, `gitleaks rule ${item.ruleId} matched redacted material`));
    }
  }

  if (details.extension === ".json") {
    try {
      const value = JSON.parse(text);
      inspectStructured(value, displayFile, findings);
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
  const requested = selfCheck ? await listFiles(MOAT_ROOT) : args;
  if (!requested.length) {
    console.error("usage: node boundary/tier-a.mjs [--self-check | <staged-file> ...]");
    process.exitCode = 2;
    return;
  }
  const result = await scanPaths(requested, { honorReviewedFixtureAllowlist: selfCheck });
  if (!result.ok) {
    console.error(formatFindings(result.findings));
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
