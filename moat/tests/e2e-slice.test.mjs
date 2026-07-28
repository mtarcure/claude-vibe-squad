import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";
import { readJson } from "../adapters/filesystem.mjs";
import { assertIndexCurrent } from "../pipeline/invariant-index.mjs";
import { runManualSlice } from "../pipeline/manual-slice.mjs";

test("manual slice composes reviewed guard through evidence-referenced Verdict", async () => {
  const guard = await readJson(
    new URL("../fixtures/schema/valid/guard.guard.json", import.meta.url),
  );
  const externalFixtures = new Map([
    ["fixtures/synthetic-known-bad.json", {
      observation: { protected_transition: true, trusted_marker: false },
      expected_violation: true,
    }],
    ["fixtures/synthetic-fixed.json", {
      observation: { protected_transition: true, trusted_marker: true },
      expected_violation: false,
    }],
  ]);
  const externalInput = createExternalInput({
    environment: { CHRONO_BOUNTY_ROOT: "/synthetic-layer2" },
    jsonLoader: async (_root, relativePath) => externalFixtures.get(relativePath),
  });

  const result = await runManualSlice({
    guard,
    fixRef: "fix:synthetic-change",
    externalInput,
    ledgerResult: { status: "net_new", refs: [] },
  });

  assert.deepEqual(result.validation.guard, []);
  assert.deepEqual(result.validation.invariant, []);
  assert.deepEqual(result.validation.verdict, []);
  assert.deepEqual(
    result.invariant,
    await readJson(new URL("../fixtures/schema/valid/invariant.invariant.json", import.meta.url)),
  );
  assert.equal(result.oracle.positive.violation, true);
  assert.equal(result.oracle.negative.violation, false);
  assert.equal(result.verdict.gate, "PASS");
  assert.doesNotThrow(() => assertIndexCurrent([result.invariant], result.index));

  const drifted = structuredClone(result.index);
  drifted.invariants[0].last_validation = "stale";
  assert.throws(
    () => assertIndexCurrent([result.invariant], drifted),
    /invariant index drift detected/u,
  );
});

test("committed thin index is derived from the canonical synthetic descriptor", async () => {
  const descriptor = await readJson(
    new URL("../fixtures/schema/valid/invariant.invariant.json", import.meta.url),
  );
  const index = await readJson(new URL("../invariants/index.json", import.meta.url));

  assert.doesNotThrow(() => assertIndexCurrent([descriptor], index));
});
