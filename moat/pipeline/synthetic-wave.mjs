import { exerciseRequestModel, DECLARED_TRANSITIONS, shrinkViolationSequence } from "../fuzz/request-model.mjs";
import { collectV8Coverage } from "../fuzz/v8-coverage.mjs";
import { createLoopbackOracleKit } from "../oracle/loopback-oracle.mjs";
import { createSyntheticAppTemplate } from "../twinlab/synthetic-app.mjs";
import { provision } from "../twinlab/provision.mjs";
import { emitWaveResult } from "./wave-result.mjs";

const isolationProfile = Object.freeze({ kind: "in-process", network: "disabled" });

function guardBranches(vulnerable, patched) {
  return vulnerable.oracle.guards.some((entry) => entry.allowed === true)
    && patched.oracle.guards.some((entry) => entry.allowed === false);
}

export async function runSyntheticWave({
  seed = 20260715,
  numRuns = 10,
  omitTransitions = [],
  coverageThreshold = 70,
  ledger,
  independentReview,
} = {}) {
  if (typeof ledger?.netNew !== "boolean") {
    throw new TypeError("reviewed ledger evidence is required");
  }
  if (typeof independentReview?.confirmed !== "boolean") {
    throw new TypeError("independent review evidence is required");
  }
  const activeTransitions = DECLARED_TRANSITIONS.filter((name) => !omitTransitions.includes(name));
  const vulnerableOracle = createLoopbackOracleKit();
  const patchedOracle = createLoopbackOracleKit();
  const vulnerableLab = provision(
    createSyntheticAppTemplate({ id: "synthetic-known-vulnerable", enforceTrustedMarker: false }),
    vulnerableOracle,
    isolationProfile,
  );
  const patchedLab = provision(
    createSyntheticAppTemplate({ id: "synthetic-patched", enforceTrustedMarker: true }),
    patchedOracle,
    isolationProfile,
  );

  const measured = await collectV8Coverage(async () => {
    const vulnerable = await vulnerableLab.start();
    const patched = await patchedLab.start();
    try {
      const calibrationRun = await exerciseRequestModel({
        dispatch: vulnerable.dispatch,
        seed,
        numRuns,
        transitions: activeTransitions,
      });
      const negativeRun = await exerciseRequestModel({
        dispatch: patched.dispatch,
        seed,
        numRuns,
        transitions: activeTransitions,
      });
      return { calibrationRun, negativeRun };
    } finally {
      await Promise.all([vulnerableLab.stop(), patchedLab.stop()]);
    }
  });

  const vulnerableObservation = vulnerableLab.observe();
  const patchedObservation = patchedLab.observe();
  const firstShrink = shrinkViolationSequence({ seed });
  const replayShrink = shrinkViolationSequence({ seed });
  const deterministicShrinking = JSON.stringify(firstShrink) === JSON.stringify(replayShrink);
  const calibration = {
    detected: vulnerableObservation.oracle.violations.length > 0,
    successes: measured.value.calibrationRun.successes,
    attempts: measured.value.calibrationRun.attempts,
  };
  const negativeControl = {
    flagged: patchedObservation.oracle.violations.length > 0
      || measured.value.negativeRun.successes > 0,
  };
  const coverage = { ...measured.coverage, threshold: coverageThreshold };
  const transitions = {
    counts: measured.value.calibrationRun.counts,
    edges: measured.value.calibrationRun.edges,
    required: [...DECLARED_TRANSITIONS],
  };
  const sinkReached = vulnerableObservation.oracle.protectedAccesses.length > 0
    || vulnerableObservation.oracle.actions.length > 0;
  const guardBranchesExercised = guardBranches(vulnerableObservation, patchedObservation);

  const waveResult = await emitWaveResult({
    calibration,
    negativeControl,
    candidate: { passed: calibration.detected && !negativeControl.flagged, killRefs: [] },
    coverage,
    transitions,
    guardBranchesExercised,
    sinkReached,
    deterministicShrinking,
    ledger,
    independentReview,
    seed,
  });

  return {
    waveResult,
    evidence: {
      calibration,
      negativeControl,
      coverage,
      transitions,
      controls: {
        vulnerable: vulnerableObservation,
        patched: patchedObservation,
      },
      replay: {
        seed,
        sequences: measured.value.calibrationRun.sequences,
        shrunkCounterexample: firstShrink,
        deterministicShrinking,
      },
    },
  };
}
