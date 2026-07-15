import { validateManifest } from "./ledger.mjs";

const advisoryIdPattern = /^[A-Za-z0-9._/-]+$/u;
const sourceRefPattern = /^public:[A-Za-z0-9._/-]+$/u;
const surfacePattern = /^[a-z0-9][a-z0-9._/-]+$/u;

function normalizeRecord(record) {
  const classification = record?.classification === "cve"
    ? "known_cve"
    : record?.classification;
  const surfaces = record?.surface_keys;
  if (
    !record
    || typeof record !== "object"
    || !advisoryIdPattern.test(record.advisory_id ?? "")
    || !["documented", "known_cve"].includes(classification)
    || !sourceRefPattern.test(record.source_ref ?? "")
    || !Array.isArray(surfaces)
    || surfaces.length === 0
    || surfaces.some((surface) => !surfacePattern.test(surface))
    || new Set(surfaces).size !== surfaces.length
  ) {
    throw new Error("malformed public advisory record");
  }

  return {
    id: `advisory:${record.advisory_id}`,
    classification,
    surface_keys: [...surfaces],
    source_ref: record.source_ref,
  };
}

export function normalizePublicAdvisories(records) {
  if (!Array.isArray(records)) throw new Error("malformed public advisory record set");
  const entries = records.map(normalizeRecord);
  if (new Set(entries.map(({ id }) => id)).size !== entries.length) {
    throw new Error("duplicate public advisory record");
  }
  const manifest = {
    schema_version: "1.0.0",
    content_class: "public-safe",
    entries,
  };
  if (validateManifest(manifest).length) {
    throw new Error("normalized public advisory manifest is invalid");
  }
  return manifest;
}
