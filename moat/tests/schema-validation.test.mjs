import assert from "node:assert/strict";
import test from "node:test";

import { readJson } from "../adapters/filesystem.mjs";
import { loadSchema, validateInstance } from "../schema/validate.mjs";

const cases = [
  ["InvariantDescriptor", "invariant.invariant.json"],
  ["GuardAnnotation", "guard.guard.json"],
  ["Verdict", "verdict.verdict.json"],
  ["WaveResult", "wave.wave.json"],
];

for (const [schemaName, fixtureName] of cases) {
  test(`${schemaName} accepts its valid example`, async () => {
    const schema = await loadSchema(schemaName);
    const instance = await readJson(
      new URL(`../fixtures/schema/valid/${fixtureName}`, import.meta.url),
    );

    assert.deepEqual(validateInstance(schema, instance), []);
  });

  test(`${schemaName} rejects its invalid example`, async () => {
    const schema = await loadSchema(schemaName);
    const instance = await readJson(
      new URL(`../fixtures/schema/invalid/${fixtureName}`, import.meta.url),
    );

    assert.notDeepEqual(validateInstance(schema, instance), []);
  });
}

test("WaveResult enforces PASS, FAIL, and INCONCLUSIVE state evidence", async () => {
  const schema = await loadSchema("WaveResult");
  const pass = await readJson(
    new URL("../fixtures/schema/valid/wave.wave.json", import.meta.url),
  );
  const fail = structuredClone(pass);
  fail.state = "FAIL";
  fail.ledger.net_new = false;
  fail.candidate_kill_refs = ["kill:synthetic-no-impact"];
  fail.independent_review.confirmed = false;

  const inconclusive = structuredClone(fail);
  inconclusive.state = "INCONCLUSIVE";
  inconclusive.candidate_kill_refs = [];
  inconclusive.missing_requirement_refs = ["missing:coverage-saturation"];
  inconclusive.completeness.coverage_saturated = false;

  assert.deepEqual(validateInstance(schema, fail), []);
  assert.deepEqual(validateInstance(schema, inconclusive), []);

  fail.candidate_kill_refs = [];
  inconclusive.missing_requirement_refs = [];
  assert.notDeepEqual(validateInstance(schema, fail), []);
  assert.notDeepEqual(validateInstance(schema, inconclusive), []);
});

test("Verdict keeps the general bounty gate separate from the no-privilege wave criterion", async () => {
  const schema = await loadSchema("Verdict");
  const verdict = await readJson(
    new URL("../fixtures/schema/valid/verdict.verdict.json", import.meta.url),
  );
  verdict.privilege_required.level = "user";
  verdict.criteria.general_bounty_gate.decision = "PASS";
  verdict.criteria.wave_criterion.decision = "KILL";
  verdict.gate = "HOLD";

  assert.deepEqual(validateInstance(schema, verdict), []);
});
