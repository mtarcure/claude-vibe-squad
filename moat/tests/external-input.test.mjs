import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";

test("external-input adapter is the sole resolver for logical Layer-2 refs", async () => {
  const loads = [];
  const external = createExternalInput({
    environment: { CHRONO_BOUNTY_ROOT: "/synthetic-layer2" },
    jsonLoader: async (root, relativePath) => {
      loads.push({ root, relativePath });
      return { marker: "synthetic" };
    },
  });

  assert.deepEqual(await external.loadJson("fixture:positive"), { marker: "synthetic" });
  assert.deepEqual(loads, [{ root: "/synthetic-layer2", relativePath: "fixtures/positive.json" }]);
  await assert.rejects(() => external.loadJson("fixture:../escape"), /invalid external reference/u);
});

test("recall is explicitly unavailable when CHRONO_VAULT_ROOT is unset", async () => {
  let calls = 0;
  const external = createExternalInput({
    environment: {},
    recallRunner: () => { calls += 1; },
  });

  assert.deepEqual(await external.recall("synthetic surface"), {
    status: "recall_unavailable",
    reason: "vault_root_unset",
  });
  assert.equal(calls, 0);
});

test("recall is explicitly unavailable when vault clearance is unset", async () => {
  let calls = 0;
  const external = createExternalInput({
    environment: { CHRONO_VAULT_ROOT: "/synthetic-vault" },
    recallRunner: () => { calls += 1; },
  });

  assert.deepEqual(await external.recall("synthetic surface"), {
    status: "recall_unavailable",
    reason: "vault_clearance_unset",
  });
  assert.equal(calls, 0);
});
