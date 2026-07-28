export function emitInvariant(guard, {
  fixRef,
  language = "typescript",
  versionRange = ">=1.0.0",
  trustBoundary = "request-state",
  detectorEngine = "semgrep",
  detectorRef = "rule:synthetic-routing",
  oracleRef = "oracle:synthetic-counter",
} = {}) {
  if (guard.review?.state !== "reviewed") {
    throw new Error("guard annotation must be human-reviewed before emission");
  }
  if (typeof fixRef !== "string" || !fixRef.startsWith("fix:")) {
    throw new Error("an explicit logical fix reference is required");
  }

  return {
    id: guard.id.replace(/^guard:/u, "invariant:"),
    schema_version: "1.0.0",
    source_fix_ref: fixRef,
    applicability: { language, version_range: versionRange },
    confidence: guard.candidate.confidence,
    review_state: "reviewed",
    trust_boundary: trustBoundary,
    model: {
      sources: [...guard.sources],
      barriers: [...guard.barriers],
      sinks: [...guard.sinks],
    },
    expected_observations: ["oracle records no unauthorized transition"],
    detector: { engine: detectorEngine, rule_ref: detectorRef },
    fixture_refs: {
      positive: guard.positive_fixture_ref,
      negative: guard.negative_fixture_ref,
      content_class: "public-safe",
    },
    dynamic_oracle_ref: oracleRef,
  };
}
