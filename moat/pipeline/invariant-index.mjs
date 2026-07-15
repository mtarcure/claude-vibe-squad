function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
  );
}

const stableJson = (value) => JSON.stringify(canonicalize(value));

export function generateIndex(descriptors) {
  return {
    schema_version: "1.0.0",
    content_class: "public-safe",
    invariants: [...descriptors]
      .sort((left, right) => left.id.localeCompare(right.id))
      .map((descriptor) => ({
        id: descriptor.id,
        schema_version: descriptor.schema_version,
        source_fix_ref: descriptor.source_fix_ref,
        language: descriptor.applicability.language,
        detector_engine: descriptor.detector.engine,
        trust_boundary: descriptor.trust_boundary,
        descriptor_ref: descriptor.id.replace(/^invariant:/u, "descriptor:"),
        detector_ref: descriptor.detector.rule_ref,
        fixture_refs: {
          positive: descriptor.fixture_refs.positive,
          negative: descriptor.fixture_refs.negative,
        },
        oracle_ref: descriptor.dynamic_oracle_ref,
        applicability_version_range: descriptor.applicability.version_range,
        lifecycle: descriptor.review_state,
        last_validation: "valid",
      })),
  };
}

export function assertIndexCurrent(descriptors, index) {
  if (stableJson(generateIndex(descriptors)) !== stableJson(index)) {
    throw new Error("invariant index drift detected");
  }
}
