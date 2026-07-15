#!/usr/bin/env node

import { externalInput as defaultExternalInput } from "../adapters/external-input.mjs";
import {
  joinSystemPath,
  pathDetails,
  readText,
  toSystemPath,
} from "../adapters/filesystem.mjs";
import {
  commandLineArguments,
  reportCommandError,
  runCommand,
} from "../adapters/process.mjs";
import { analyzeSource } from "./ast-analysis.mjs";

const MOAT_ROOT = new URL("../", import.meta.url);
const REPOSITORY_ROOT = toSystemPath(new URL("../../", import.meta.url));
const DEFAULT_DENYLIST_REF = "descriptor:target-denylist";
const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]);

export const ERROR_CLASSES = Object.freeze({
  DENYLIST_INVALID: "MOAT_BOUNDARY_TIERB_DENYLIST_INVALID",
  DENYLIST_UNAVAILABLE: "MOAT_BOUNDARY_TIERB_DENYLIST_UNAVAILABLE",
  RANGE_UNAVAILABLE: "MOAT_BOUNDARY_TIERB_RANGE_UNAVAILABLE",
  SCAN_UNAVAILABLE: "MOAT_BOUNDARY_TIERB_SCAN_UNAVAILABLE",
  TARGET_MATCH: "MOAT_BOUNDARY_TIERB_TARGET_MATCH",
  USAGE: "MOAT_BOUNDARY_TIERB_USAGE",
});

const finding = (errorClass, file, line, message) => ({ errorClass, file, line, message });
const lineForOffset = (text, offset) => text.slice(0, Math.max(0, offset)).split("\n").length;

function validateDenylist(value) {
  if (
    !value
    || typeof value !== "object"
    || Array.isArray(value)
    || value.schema_version !== "1.0.0"
    || value.content_class !== "restricted"
    || !value.targets
    || typeof value.targets !== "object"
    || Array.isArray(value.targets)
    || Object.keys(value).some((key) => !["schema_version", "content_class", "targets"].includes(key))
    || Object.keys(value.targets).some((key) => !["hostnames", "repositories", "advisory_ids", "paths"].includes(key))
  ) return false;

  const groups = ["hostnames", "repositories", "advisory_ids", "paths"];
  let count = 0;
  for (const group of groups) {
    const entries = value.targets[group];
    if (!Array.isArray(entries)) return false;
    if (
      entries.some((entry) => (
        typeof entry !== "string"
        || entry.length < 3
        || entry.length > 2048
        || !/^[\x20-\x7e]+$/u.test(entry)
      ))
      || new Set(entries).size !== entries.length
    ) return false;
    count += entries.length;
  }
  return count > 0 && count <= 10_000;
}

function denyEntries(denylist) {
  return Object.entries(denylist.targets).flatMap(([kind, values]) => values.map((value) => ({
    caseSensitive: kind === "paths",
    kind,
    value,
  })));
}

async function loadDenylist(externalInput, reference) {
  let value;
  try {
    value = await externalInput.loadJson(reference);
  } catch (error) {
    return {
      errorClass: error instanceof SyntaxError
        ? ERROR_CLASSES.DENYLIST_INVALID
        : ERROR_CLASSES.DENYLIST_UNAVAILABLE,
    };
  }
  return validateDenylist(value)
    ? { entries: denyEntries(value) }
    : { errorClass: ERROR_CLASSES.DENYLIST_INVALID };
}

function encodedStrings(text) {
  const values = [];
  const expression = /(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{4,}={0,2}(?![A-Za-z0-9+/_-])/gu;
  for (const match of text.matchAll(expression)) {
    for (const encoding of ["base64", "base64url"]) {
      try {
        const value = Buffer.from(match[0], encoding).toString("utf8");
        const printable = [...value].filter((character) => (
          character === "\n"
          || character === "\r"
          || character === "\t"
          || (character >= " " && character <= "~")
        )).length;
        if (value.length && printable / value.length > 0.9) {
          values.push({ value, offset: match.index });
        }
      } catch {
        // A malformed candidate is ordinary source text, not a scanner error.
      }
    }
  }
  return values;
}

function comparableStrings(text, details) {
  const values = [{ value: text, offset: 0, mapsOffsets: true }];
  let parseErrors = [];
  if (sourceExtensions.has(details.extension)) {
    const analysis = analyzeSource(text, details.basename);
    values.push(...analysis.evaluatedStrings.map(({ value, offset }) => ({ value, offset })));
    parseErrors = analysis.parseErrors;
  }
  values.push(...encodedStrings(text));
  return { parseErrors, values };
}

function matchPositions(candidate, entry) {
  const haystack = entry.caseSensitive
    ? candidate.value
    : candidate.value.toLocaleLowerCase("en-US");
  const needle = entry.caseSensitive
    ? entry.value
    : entry.value.toLocaleLowerCase("en-US");
  const positions = [];
  let index = haystack.indexOf(needle);
  while (index >= 0) {
    positions.push(candidate.mapsOffsets ? candidate.offset + index : candidate.offset);
    if (!candidate.mapsOffsets) break;
    index = haystack.indexOf(needle, index + Math.max(1, needle.length));
  }
  return positions;
}

function targetFindings(text, details, entries) {
  const displayFile = `moat/${details.relative}`;
  const found = [];
  const seen = new Set();
  const comparable = comparableStrings(text, details);
  if (comparable.parseErrors.length) {
    return [finding(
      ERROR_CLASSES.SCAN_UNAVAILABLE,
      displayFile,
      lineForOffset(text, comparable.parseErrors[0].offset),
      "Layer-1 source could not be parsed",
    )];
  }
  for (const candidate of comparable.values) {
    for (const entry of entries) {
      for (const offset of matchPositions(candidate, entry)) {
        const line = lineForOffset(text, offset);
        const key = `${displayFile}:${line}`;
        if (seen.has(key)) continue;
        seen.add(key);
        found.push(finding(
          ERROR_CLASSES.TARGET_MATCH,
          displayFile,
          line,
          "private target identifier matched",
        ));
      }
    }
  }
  return found;
}

export async function scanTierB(paths, {
  externalInput = defaultExternalInput,
  layer1Root = MOAT_ROOT,
  reference = DEFAULT_DENYLIST_REF,
} = {}) {
  const layerFiles = paths
    .map((file) => pathDetails(file, layer1Root))
    .filter((details) => details.withinRoot && !details.relative.startsWith("node_modules/"));
  if (!layerFiles.length) return { ok: true, findings: [] };

  const loaded = await loadDenylist(externalInput, reference);
  if (loaded.errorClass) {
    return {
      ok: false,
      findings: [finding(
        loaded.errorClass,
        "moat/",
        1,
        loaded.errorClass === ERROR_CLASSES.DENYLIST_INVALID
          ? "private target denylist is malformed"
          : "private target denylist is unavailable",
      )],
    };
  }

  const findings = [];
  for (const details of layerFiles) {
    try {
      const text = await readText(details.absolute);
      findings.push(...targetFindings(text, details, loaded.entries));
    } catch {
      findings.push(finding(
        ERROR_CLASSES.SCAN_UNAVAILABLE,
        `moat/${details.relative}`,
        1,
        "Layer-1 file could not be scanned",
      ));
    }
  }
  return { ok: findings.length === 0, findings };
}

function validRevision(value) {
  return typeof value === "string"
    && !value.startsWith("-")
    && /^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,127}$/u.test(value);
}

export function filesForRange(range, {
  repositoryRoot = REPOSITORY_ROOT,
  runner = runCommand,
} = {}) {
  const parts = range.split("..");
  if (parts.length !== 2 || !parts.every(validRevision)) {
    throw new Error("invalid git range");
  }
  const [base, head] = parts;
  const zeroBase = /^0{40,64}$/u.test(base);
  const args = zeroBase
    ? ["-C", repositoryRoot, "diff-tree", "--root", "--no-commit-id", "-r", "--name-only", "-z", head, "--", "moat/"]
    : ["-C", repositoryRoot, "diff", "--name-only", "-z", "--diff-filter=ACMR", range, "--", "moat/"];
  const result = runner("git", args);
  return result.stdout
    .split("\0")
    .filter(Boolean)
    .map((file) => joinSystemPath(repositoryRoot, file));
}

export function formatFindings(findings) {
  return findings
    .map(({ errorClass, file, line, message }) => `${errorClass} ${file}:${line} ${message}`)
    .join("\n");
}

async function main() {
  const args = commandLineArguments();
  let paths;
  if (args[0] === "--staged") paths = args.slice(1);
  else if (args[0] === "--range" && args.length === 2) {
    try {
      paths = filesForRange(args[1]);
    } catch {
      reportCommandError(formatFindings([
        finding(ERROR_CLASSES.RANGE_UNAVAILABLE, "moat/", 1, "git range could not be scanned"),
      ]));
      return;
    }
  } else {
    reportCommandError(formatFindings([
      finding(ERROR_CLASSES.USAGE, "moat/", 1, "usage: tier-b --staged <file>... | --range <base>..<head>"),
    ]));
    return;
  }

  const result = await scanTierB(paths);
  if (!result.ok) reportCommandError(formatFindings(result.findings));
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
