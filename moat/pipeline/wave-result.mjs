import { validateNamed } from "../schema/validate.mjs";

const rounded = (value) => Math.max(0, Math.round(value));

function completenessEvidence({ calibration, negativeControl, coverage, transitions,
  guardBranchesExercised, sinkReached, deterministicShrinking }) {
  const required = transitions.required;
  const covered = required.filter((name) => (transitions.counts[name] ?? 0) > 0);
  const transitionsComplete = covered.length === required.length;
  const coverageSaturated = coverage.functionPercent >= coverage.threshold
    && coverage.rangePercent >= coverage.threshold;
  const missing = [];

  if (!calibration.detected) missing.push("missing:calibration-control");
  if (negativeControl.flagged) missing.push("missing:negative-control");
  for (const name of required.filter((transition) => (transitions.counts[transition] ?? 0) === 0)) {
    missing.push(`missing:transition-${name}`);
  }
  if (!coverageSaturated) missing.push("missing:coverage-saturation");
  if (!guardBranchesExercised) missing.push("missing:guard-branches");
  if (!sinkReached) missing.push("missing:sink-reach");
  if (!deterministicShrinking) missing.push("missing:deterministic-shrinking");

  return {
    missing,
    values: {
      calibration_passed: calibration.detected,
      transitions_complete: transitionsComplete,
      guard_branches_exercised: guardBranchesExercised,
      coverage_saturated: coverageSaturated,
      sink_reached: sinkReached,
      deterministic_shrinking: deterministicShrinking,
      evidence_ref: `coverage:synthetic-v8-f${rounded(coverage.functionPercent)}-r${rounded(coverage.rangePercent)}-t${covered.length}-of-${required.length}`,
    },
  };
}

export async function emitWaveResult({
  calibration,
  negativeControl,
  candidate,
  coverage,
  transitions,
  guardBranchesExercised,
  sinkReached,
  deterministicShrinking,
  ledger,
  independentReview,
  seed,
}) {
  const completeness = completenessEvidence({
    calibration,
    negativeControl,
    coverage,
    transitions,
    guardBranchesExercised,
    sinkReached,
    deterministicShrinking,
  });
  const passEvidence = candidate.passed
    && calibration.successes > 0
    && ledger.netNew
    && independentReview.confirmed;
  if (candidate.passed && !ledger.netNew) completeness.missing.push("missing:net-new-review");
  if (candidate.passed && !independentReview.confirmed) completeness.missing.push("missing:independent-review");

  const state = completeness.missing.length > 0
    ? "INCONCLUSIVE"
    : passEvidence ? "PASS" : "FAIL";
  const killRefs = state === "FAIL"
    ? candidate.killRefs?.length ? candidate.killRefs : ["kill:synthetic-no-l3-candidate"]
    : [];

  const wave = {
    schema_version: "1.0.0",
    state,
    preregistration: {
      surface_ref: "surface:synthetic-request-state",
      budget_ref: "budget:synthetic-phase4a",
      configuration_profile_ref: "config:synthetic-in-process",
      intrinsic_canary_ref: "canary:synthetic-protected-handler",
      coverage_criteria_ref: `coverage:synthetic-v8-threshold-${rounded(coverage.threshold)}`,
    },
    revision_ref: "revision:synthetic-phase4a",
    environment_fingerprint_ref: "environment:synthetic-in-process-node",
    attacker: { privilege: "none", request_path_ref: "evidence:synthetic-untrusted-request" },
    intrinsic_canary: {
      class: "integrity",
      observation_ref: "evidence:synthetic-protected-handler-execution",
      outside_attacker_control: true,
    },
    reproduction: {
      successes: candidate.passed ? calibration.successes : 0,
      attempts: calibration.attempts,
      fixed_seed_ref: `replay:synthetic-seed-${seed}`,
    },
    controls: {
      patched_negative_ref: "control:synthetic-trusted-marker-enforced",
      known_vulnerable_calibration_ref: "control:synthetic-trusted-marker-missing",
    },
    excluded_preconditions_ref: "evidence:synthetic-no-disabled-guard-or-privilege",
    ledger: {
      dedup_ref: "ledger:synthetic-phase4a-dedup",
      net_new: ledger.netNew,
      review_ref: "review:synthetic-novelty",
    },
    completeness: completeness.values,
    candidate_kill_refs: killRefs,
    missing_requirement_refs: completeness.missing,
    independent_review: {
      confirmed: independentReview.confirmed,
      impact_ref: "review:synthetic-intrinsic-impact",
      novelty_ref: "review:synthetic-novelty",
    },
  };

  const errors = await validateNamed("WaveResult", wave);
  if (errors.length) throw new Error(`emitted WaveResult is invalid: ${JSON.stringify(errors)}`);
  return wave;
}
