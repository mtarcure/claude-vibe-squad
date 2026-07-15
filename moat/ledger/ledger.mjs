import { readJson } from "../adapters/filesystem.mjs";
import { validateInstance } from "../schema/validate.mjs";

const manifestSchema = await readJson(
  new URL("./public-advisory-manifest.schema.json", import.meta.url),
);

export const AUTO_PRIOR_KILL_MIN_SCORE = 2;

export function validateManifest(manifest) {
  return validateInstance(manifestSchema, manifest);
}

export async function loadManifest(externalInput, reference = "manifest:public-advisories") {
  const manifest = await externalInput.loadJson(reference);
  const errors = validateManifest(manifest);
  if (errors.length) throw new Error("external public advisory manifest is invalid");
  return manifest;
}

function publicMatch(surface, manifest) {
  return manifest.entries.find((entry) => entry.surface_keys.includes(surface.key));
}

export async function check(surface, { manifest, externalInput }) {
  const manifestErrors = validateManifest(manifest);
  if (manifestErrors.length) throw new Error("public advisory manifest is invalid");
  if (!surface || typeof surface.key !== "string" || !surface.key) {
    throw new TypeError("surface.key is required");
  }
  if (typeof surface.recall_query !== "string" || !surface.recall_query.trim()) {
    throw new TypeError("surface.recall_query is required");
  }

  const known = publicMatch(surface, manifest);
  if (known) {
    return { status: known.classification, refs: [known.source_ref] };
  }

  const structuredFilters = {};
  for (const field of ["target", "attack_class", "component"]) {
    const value = surface.recall_filters?.[field];
    if (typeof value === "string" && value.trim()) structuredFilters[field] = value;
  }
  const privateRecall = await externalInput.recall(surface.recall_query, {
    type: "finding",
    status: ["candidate", "verified", "superseded", "invalidated", "archived"],
    ...structuredFilters,
  });
  if (privateRecall.status === "insufficient_clearance") {
    return {
      status: "recall_unavailable",
      refs: [],
      reason: "insufficient_clearance",
    };
  }
  if (privateRecall.status !== "ok") {
    return {
      status: "recall_unavailable",
      refs: [],
      reason: privateRecall.reason ?? "unknown",
    };
  }

  // An empty restricted-blind search is not evidence of an empty vault.
  // `net_new` is valid only after the bridge confirms effective restricted clearance.
  if (privateRecall.clearance_effective !== "restricted") {
    return {
      status: "recall_unavailable",
      refs: [],
      reason: "insufficient_clearance",
    };
  }

  const results = privateRecall.recall?.results;
  if (privateRecall.recall?.query_error) {
    return {
      status: "recall_unavailable",
      refs: [],
      reason: privateRecall.recall.query_error,
    };
  }
  if (!Array.isArray(results)) {
    return { status: "recall_unavailable", refs: [], reason: "malformed_recall" };
  }
  if (!results.length) return { status: "net_new", refs: [] };

  const refs = [...new Set(results
    .map((result) => result.note_link)
    .filter((link) => typeof link === "string" && link.length)
    .map((link) => `vault:${link}`))];
  if (!refs.length) {
    return { status: "recall_unavailable", refs: [], reason: "malformed_recall" };
  }

  const maxScore = results.reduce(
    (maximum, result) => typeof result.score === "number"
      ? Math.max(maximum, result.score)
      : maximum,
    0,
  );
  const autoThresholdMet = Object.keys(structuredFilters).length > 0
    && maxScore >= AUTO_PRIOR_KILL_MIN_SCORE;
  if (surface.reviewer_confirmed !== true && !autoThresholdMet) {
    return {
      status: "needs_review",
      refs,
      max_score: maxScore,
      reason: "recall_hit_below_auto_threshold",
    };
  }
  return { status: "prior_kill", refs };
}
