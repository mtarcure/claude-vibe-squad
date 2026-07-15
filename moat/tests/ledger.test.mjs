import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";
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

test("ledger returns prior_kill for reviewer-confirmed recall hits", async () => {
  const result = await check(
    {
      key: "synthetic-private-surface",
      recall_query: "synthetic prior kill",
      reviewer_confirmed: true,
    },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          clearance_effective: "restricted",
          recall: {
            results: [{ note_link: "notes/findings/synthetic.md", score: 0.1 }],
          },
        }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "prior_kill",
    refs: ["vault:notes/findings/synthetic.md"],
  });
});

test("ledger returns net_new only after a restricted-clearance empty recall", async () => {
  const result = await check(
    { key: "synthetic-new-surface", recall_query: "synthetic new surface" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          clearance_effective: "restricted",
          recall: { results: [] },
        }),
      },
    },
  );

  assert.deepEqual(result, { status: "net_new", refs: [] });
});

test("restricted-blind empty recall is unavailable, never net_new", async () => {
  const result = await check(
    { key: "synthetic-restricted-match", recall_query: "synthetic restricted match" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          clearance_effective: "internal",
          recall: { results: [] },
        }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "recall_unavailable",
    refs: [],
    reason: "insufficient_clearance",
  });
  assert.notEqual(result.status, "net_new");
});

test("internal-clearance adapter plus a hidden restricted match cannot become net_new", async () => {
  let recallCalls = 0;
  const externalInput = createExternalInput({
    environment: {
      CHRONO_VAULT_ROOT: "/synthetic-vault",
      CHRONO_VAULT_CLEARANCE: "internal",
    },
    recallRunner: async () => {
      recallCalls += 1;
      return {
        status: "ok",
        clearance_effective: "restricted",
        recall: {
          results: [{ note_link: "notes/findings/hidden.md", score: 9 }],
        },
      };
    },
  });
  const result = await check(
    { key: "synthetic-hidden-match", recall_query: "synthetic hidden match" },
    { manifest: { ...manifest, entries: [] }, externalInput },
  );

  assert.deepEqual(result, {
    status: "recall_unavailable",
    refs: [],
    reason: "insufficient_clearance",
  });
  assert.equal(recallCalls, 0);
  assert.notEqual(result.status, "net_new");
});

test("low-score unstructured hit requires review instead of prior_kill", async () => {
  const result = await check(
    { key: "synthetic-broad-surface", recall_query: "synthetic" },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async () => ({
          status: "ok",
          clearance_effective: "restricted",
          recall: {
            results: [{ note_link: "notes/findings/synthetic.md", score: 0.2 }],
          },
        }),
      },
    },
  );

  assert.deepEqual(result, {
    status: "needs_review",
    refs: ["vault:notes/findings/synthetic.md"],
    max_score: 0.2,
    reason: "recall_hit_below_auto_threshold",
  });
});

test("high-score structured hit may auto-classify as prior_kill", async () => {
  let receivedFilters;
  const result = await check(
    {
      key: "synthetic-structured-surface",
      recall_query: "synthetic structured query",
      recall_filters: { component: "synthetic-component" },
    },
    {
      manifest: { ...manifest, entries: [] },
      externalInput: {
        recall: async (_query, filters) => {
          receivedFilters = filters;
          return {
            status: "ok",
            clearance_effective: "restricted",
            recall: {
              results: [{ note_link: "notes/findings/synthetic.md", score: 2.5 }],
            },
          };
        },
      },
    },
  );

  assert.equal(receivedFilters.component, "synthetic-component");
  assert.deepEqual(result, {
    status: "prior_kill",
    refs: ["vault:notes/findings/synthetic.md"],
  });
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
          clearance_effective: "restricted",
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
