import assert from "node:assert/strict";
import test from "node:test";

import { check, validateManifest } from "../ledger/ledger.mjs";

const manifest = {
  schema_version: "1.0.0",
  content_class: "public-safe",
  entries: [
    {
      id: "advisory:synthetic-documented",
      classification: "documented",
      surface_keys: ["synthetic-documented-surface"],
      source_ref: "public:synthetic-design-note",
    },
    {
      id: "advisory:synthetic-cve",
      classification: "known_cve",
      surface_keys: ["synthetic-known-surface"],
      source_ref: "public:synthetic-advisory",
    },
  ],
};

test("public advisory manifest is normalized and distinguishes documented/CVE", () => {
  assert.deepEqual(validateManifest(manifest), []);
});

test("ledger resolves normalized public classifications before private recall", async () => {
  let recallCalls = 0;
  const externalInput = { recall: async () => { recallCalls += 1; } };
  const documented = await check(
    { key: "synthetic-documented-surface", recall_query: "synthetic documented" },
    { manifest, externalInput },
  );
  const knownCve = await check(
    { key: "synthetic-known-surface", recall_query: "synthetic known" },
    { manifest, externalInput },
  );

  assert.deepEqual(documented, {
    status: "documented",
    refs: ["public:synthetic-design-note"],
  });
  assert.deepEqual(knownCve, {
    status: "known_cve",
    refs: ["public:synthetic-advisory"],
  });
  assert.equal(recallCalls, 0);
});

test("ledger returns prior_kill for private recall hits", async () => {
  const result = await check(
    { key: "synthetic-private-surface", recall_query: "synthetic prior kill" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          recall: { results: [{ note_link: "notes/findings/synthetic.md" }] },
        }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "prior_kill",
    refs: ["vault:notes/findings/synthetic.md"],
  });
});

test("ledger returns net_new only after an available empty recall", async () => {
  const result = await check(
    { key: "synthetic-new-surface", recall_query: "synthetic new surface" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({ status: "ok", recall: { results: [] } }),
      },
    },
  );

  assert.deepEqual(result, { status: "net_new", refs: [] });
});

test("ledger propagates recall_unavailable instead of silently passing", async () => {
  const result = await check(
    { key: "synthetic-unknown-surface", recall_query: "synthetic unknown" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({ status: "recall_unavailable", reason: "vault_root_unset" }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "recall_unavailable",
    refs: [],
    reason: "vault_root_unset",
  });
});

test("ledger treats a recall query error as unavailable, never net_new", async () => {
  const result = await check(
    { key: "synthetic-invalid-query", recall_query: "synthetic invalid" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          recall: { query_error: "invalid_fts_query", results: [] },
        }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "recall_unavailable",
    refs: [],
    reason: "invalid_fts_query",
  });
});
