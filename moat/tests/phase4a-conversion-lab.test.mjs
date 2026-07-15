import assert from "node:assert/strict";
import test from "node:test";

import { runSyntheticWave } from "../pipeline/synthetic-wave.mjs";
import { emitWaveResult } from "../pipeline/wave-result.mjs";
import { validateNamed } from "../schema/validate.mjs";
import { createLoopbackOracleKit } from "../oracle/loopback-oracle.mjs";
import { createSyntheticAppTemplate } from "../twinlab/synthetic-app.mjs";
import { provision } from "../twinlab/provision.mjs";

const profile = Object.freeze({ kind: "in-process", network: "disabled" });
const reviewedWave = (options) => runSyntheticWave({
  ...options,
  ledger: { netNew: true },
  independentReview: { confirmed: true },
});

test("twin lab exposes the generic lifecycle and records unauthorized synthetic access", async () => {
  const oracle = createLoopbackOracleKit();
  const lab = provision(
    createSyntheticAppTemplate({ id: "synthetic-known-bad", enforceTrustedMarker: false }),
    oracle,
    profile,
  );

  assert.deepEqual(Object.keys(lab).sort(), ["observe", "start", "stop"]);
  const subject = await lab.start();
  assert.equal((await subject.dispatch({ kind: "path", path: "/protected", headers: {} })).status, 200);

  const observation = lab.observe();
  assert.equal(observation.lifecycle, "started");
  assert.equal(observation.oracle.violations.length, 1);
  assert.equal(observation.oracle.violations[0].class, "protected-access");

  await lab.stop();
  await assert.rejects(() => subject.dispatch({ kind: "normal", path: "/", headers: {} }), /not running/u);
});

test("loopback oracle records HTTP, redirects, actions, and attempted egress in process", () => {
  const oracle = createLoopbackOracleKit();
  oracle.recordHttp({ method: "GET", path: "/start" });
  oracle.recordRedirect({ from: "/start", to: "/finish", status: 302 });
  oracle.recordAction({ action: "harmless", authorized: false });
  oracle.recordEgress({ destination: "loopback", allowed: true });

  const observation = oracle.observe();
  assert.equal(observation.http.length, 1);
  assert.equal(observation.redirects.length, 1);
  assert.equal(observation.actions.length, 1);
  assert.equal(observation.egress.length, 1);
  assert.equal(observation.violations[0].class, "unauthorized-action");
});

test("synthetic wave detects calibration, keeps the patched control clean, and records completeness", async () => {
  const result = await reviewedWave({ seed: 424242, numRuns: 4 });

  assert.equal(result.waveResult.state, "PASS");
  assert.equal(result.evidence.calibration.detected, true);
  assert.equal(result.evidence.calibration.successes, 4);
  assert.equal(result.evidence.negativeControl.flagged, false);
  assert.equal(result.evidence.coverage.engine, "v8");
  assert.ok(result.evidence.coverage.functionPercent > 0);
  assert.match(result.waveResult.completeness.evidence_ref, /v8-f\d+-r\d+-t8-of-8/u);
  assert.deepEqual(await validateNamed("WaveResult", result.waveResult), []);

  for (const transition of [
    "normal", "prefetch", "rsc", "action", "rewrite", "redirect", "header", "path",
  ]) {
    assert.ok(result.evidence.transitions.counts[transition] > 0, `missing ${transition}`);
  }
});

test("fixed-seed model replay is deterministic", async () => {
  const first = await reviewedWave({ seed: 99, numRuns: 2 });
  const second = await reviewedWave({ seed: 99, numRuns: 2 });

  assert.deepEqual(first.evidence.transitions, second.evidence.transitions);
  assert.deepEqual(first.evidence.replay.sequences, second.evidence.replay.sequences);
});

test("synthetic pipeline refuses to manufacture ledger or review evidence", async () => {
  await assert.rejects(
    () => runSyntheticWave({ seed: 1, numRuns: 1 }),
    /reviewed ledger evidence is required/u,
  );
  await assert.rejects(
    () => runSyntheticWave({ seed: 1, numRuns: 1, ledger: { netNew: true } }),
    /independent review evidence is required/u,
  );
});

test("incomplete transitions classify INCONCLUSIVE rather than false FAIL", async () => {
  const result = await reviewedWave({
    seed: 7,
    numRuns: 2,
    omitTransitions: ["redirect"],
    coverageThreshold: 101,
  });

  assert.equal(result.waveResult.state, "INCONCLUSIVE");
  assert.equal(result.waveResult.completeness.transitions_complete, false);
  assert.equal(result.waveResult.completeness.coverage_saturated, false);
  assert.ok(result.waveResult.missing_requirement_refs.includes("missing:transition-redirect"));
  assert.ok(result.waveResult.missing_requirement_refs.includes("missing:coverage-saturation"));
  assert.deepEqual(await validateNamed("WaveResult", result.waveResult), []);
});

test("coverage-complete null candidate classifies FAIL with a recorded kill", async () => {
  const wave = await emitWaveResult({
    calibration: { detected: true, successes: 1, attempts: 1 },
    negativeControl: { flagged: false },
    candidate: { passed: false, killRefs: ["kill:synthetic-no-l3-impact"] },
    coverage: { engine: "v8", functionPercent: 100, rangePercent: 100, threshold: 80 },
    transitions: {
      counts: Object.fromEntries([
        "normal", "prefetch", "rsc", "action", "rewrite", "redirect", "header", "path",
      ].map((name) => [name, 1])),
      required: ["normal", "prefetch", "rsc", "action", "rewrite", "redirect", "header", "path"],
    },
    guardBranchesExercised: true,
    sinkReached: true,
    deterministicShrinking: true,
    ledger: { netNew: false },
    independentReview: { confirmed: false },
    seed: 1,
  });

  assert.equal(wave.state, "FAIL");
  assert.deepEqual(wave.candidate_kill_refs, ["kill:synthetic-no-l3-impact"]);
  assert.deepEqual(await validateNamed("WaveResult", wave), []);
});
