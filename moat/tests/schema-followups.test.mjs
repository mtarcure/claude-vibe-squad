import assert from "node:assert/strict";
import test from "node:test";

import { readJson } from "../adapters/filesystem.mjs";
import { loadSchema, validateInstance } from "../schema/validate.mjs";

const validVerdict = () =>
  readJson(new URL("../fixtures/schema/valid/verdict.verdict.json", import.meta.url));

test("Verdict rejects every forged PASS clause", async () => {
  const schema = await loadSchema("Verdict");
  const mutations = [
    (value) => { value.terminus.class = "none"; },
    (value) => { value.privilege_required.level = "user"; },
    (value) => { value.evidence_level.level = "L2"; },
    (value) => { value.documented_by_vendor.value = true; },
    (value) => { value.net_new.value = false; },
  ];

  for (const mutate of mutations) {
    const forged = await validVerdict();
    mutate(forged);
    assert.notDeepEqual(validateInstance(schema, forged), []);
  }
});

test("Verdict accepts a legitimate evidence-referenced L3 PASS", async () => {
  const schema = await loadSchema("Verdict");
  assert.deepEqual(validateInstance(schema, await validVerdict()), []);
});

test("WaveResult rejects impossible reproduction counts and zero-success PASS", async () => {
  const schema = await loadSchema("WaveResult");
  const wave = await readJson(
    new URL("../fixtures/schema/valid/wave.wave.json", import.meta.url),
  );

  wave.reproduction.successes = wave.reproduction.attempts + 1;
  assert.notDeepEqual(validateInstance(schema, wave), []);

  wave.reproduction.successes = 0;
  assert.notDeepEqual(validateInstance(schema, wave), []);
});

test("validator fails closed on every unrecognized schema keyword", () => {
  for (const keyword of [
    "$ref",
    "patternProperties",
    "not",
    "format",
    "$defs",
    "dependentSchemas",
  ]) {
    assert.throws(
      () => validateInstance({ type: "string", [keyword]: {} }, "value"),
      new RegExp(`unrecognized JSON-Schema keyword.*${keyword.replace("$", "\\$")}`, "u"),
    );
  }
});
