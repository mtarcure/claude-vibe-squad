import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";
import { readJsonWithin } from "../adapters/filesystem.mjs";

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

test("recall rejects every sub-restricted or misspelled clearance before search", async () => {
  for (const clearance of [undefined, "internal", "restriced"]) {
    let calls = 0;
    const external = createExternalInput({
      environment: {
        CHRONO_VAULT_ROOT: "/synthetic-vault",
        ...(clearance ? { CHRONO_VAULT_CLEARANCE: clearance } : {}),
      },
      recallRunner: () => { calls += 1; },
    });

    assert.deepEqual(await external.recall("synthetic restricted match"), {
      status: "insufficient_clearance",
      reason: "restricted_clearance_required",
    });
    assert.equal(calls, 0);
  }
});

test("recall verifies the bridge's effective clearance instead of trusting env", async () => {
  const external = createExternalInput({
    environment: {
      CHRONO_VAULT_ROOT: "/synthetic-vault",
      CHRONO_VAULT_CLEARANCE: "restricted",
    },
    recallRunner: async () => ({
      status: "ok",
      clearance_effective: "internal",
      recall: { results: [] },
    }),
  });

  assert.deepEqual(await external.recall("synthetic restricted match"), {
    status: "insufficient_clearance",
    reason: "effective_clearance_not_restricted",
  });
});

test("readJsonWithin rejects a symlink whose real path escapes the root", async () => {
  let readCalls = 0;
  await assert.rejects(
    () => readJsonWithin("/synthetic/root", "fixtures/link.json", {
      realpathImpl: async (candidate) =>
        candidate === "/synthetic/root" ? "/real/root" : "/outside/private.json",
      readJsonImpl: async () => { readCalls += 1; },
    }),
    /real path escapes its configured root/u,
  );
  assert.equal(readCalls, 0);
});
