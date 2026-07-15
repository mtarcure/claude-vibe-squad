import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";
import {
  createTemporaryDirectory,
  ensureDirectory,
  joinSystemPath,
  writeText,
} from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";
import { normalizePublicAdvisories } from "../ledger/advisory-normalizer.mjs";
import { validateManifest } from "../ledger/ledger.mjs";
import { emitInvariant } from "../pipeline/emit-invariant.mjs";
import {
  extractGuardCandidates,
  findSyntacticSiblings,
  ingestFix,
  inspectFullHistoryMirror,
} from "../patchgraph/patch-graph.mjs";

const run = (command, args, options = {}) => runCommand(command, args, options).stdout.trim();

async function syntheticRepository() {
  const root = await createTemporaryDirectory("moat-phase3-");
  const repo = joinSystemPath(root, "mirrors", "synthetic-history");
  await ensureDirectory(joinSystemPath(repo, "src"));
  await writeText(joinSystemPath(repo, "src", "routes.js"), [
    "export function guarded(request) {",
    "  return dispatchAction(request);",
    "}",
    "",
    "export function uncovered(request) {",
    "  return dispatchAction(request);",
    "}",
    "",
  ].join("\n"));
  run("git", ["init", "-q", repo]);
  run("git", ["-C", repo, "config", "user.name", "Synthetic Test"]);
  run("git", ["-C", repo, "config", "user.email", "synthetic@example.invalid"]);
  run("git", ["-C", repo, "add", "src/routes.js"]);
  run("git", ["-C", repo, "commit", "-q", "-m", "synthetic base"]);

  await writeText(joinSystemPath(repo, "src", "routes.js"), [
    "export function guarded(request) {",
    "  if (!hasTrustedMarker(request)) return deny();",
    "  return dispatchAction(request);",
    "}",
    "",
    "export function uncovered(request) {",
    "  return dispatchAction(request);",
    "}",
    "",
  ].join("\n"));
  run("git", ["-C", repo, "add", "src/routes.js"]);
  run("git", ["-C", repo, "commit", "-q", "-m", "add synthetic guard"]);
  return { root, repo, commit: run("git", ["-C", repo, "rev-parse", "HEAD"]) };
}

test("public advisory records normalize into a schema-valid manifest", () => {
  const manifest = normalizePublicAdvisories([
    {
      advisory_id: "SYN-2026-0001",
      classification: "documented",
      source_ref: "public:recorded-synthetic-feed",
      surface_keys: ["synthetic.router.state"],
    },
    {
      advisory_id: "SYN-2026-0002",
      classification: "cve",
      source_ref: "public:recorded-synthetic-feed",
      surface_keys: ["synthetic.parser.edge"],
    },
  ]);

  assert.deepEqual(validateManifest(manifest), []);
  assert.equal(manifest.entries[1].classification, "known_cve");
  assert.throws(
    () => normalizePublicAdvisories([{ advisory_id: "broken" }]),
    /malformed public advisory record/u,
  );
});

test("full-history mirror ingestion, candidate extraction, and reviewed sibling search", async () => {
  const fixture = await syntheticRepository();
  const externalInput = createExternalInput({
    environment: { CHRONO_BOUNTY_ROOT: fixture.root },
  });
  const mirrorPath = await externalInput.resolvePath("mirror:synthetic-history");
  assert.ok(mirrorPath.endsWith("/mirrors/synthetic-history"));

  const mirror = inspectFullHistoryMirror(mirrorPath);
  assert.equal(mirror.full_history, true);

  const fix = ingestFix(mirrorPath, {
    ref: "fix:synthetic-guard",
    commit: fixture.commit,
  });
  assert.equal(fix.ref, "fix:synthetic-guard");
  assert.match(fix.diff, /hasTrustedMarker/u);

  const candidates = extractGuardCandidates(fix);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].review_state, "candidate");
  assert.ok(candidates[0].confidence > 0 && candidates[0].confidence < 1);
  assert.equal(candidates[0].tooling.tree_sitter.available, true);
  assert.equal(candidates[0].tooling.difftastic.available, true);
  assert.throws(
    () => emitInvariant(candidates[0], { fixRef: fix.ref }),
    /human-reviewed/u,
  );

  const reviewed = {
    id: "guard:synthetic-route-state",
    schema_version: "1.0.0",
    before_predicate: "dispatchAction(request) without a trusted marker",
    after_predicate: "hasTrustedMarker(request) before dispatchAction(request)",
    sources: ["request"],
    barriers: ["call:hasTrustedMarker"],
    sinks: ["call:dispatchAction"],
    scope_callsites: ["call:dispatchAction"],
    positive_fixture_ref: "fixture:synthetic-uncovered",
    negative_fixture_ref: "fixture:synthetic-guarded",
    candidate: { confidence: 0.85, location_ref: "location:src/routes.js" },
    review: { state: "reviewed", reviewer_ref: "review:synthetic-human" },
  };
  const siblings = findSyntacticSiblings(mirrorPath, fixture.commit, reviewed);
  assert.deepEqual(siblings.map(({ function_name }) => function_name), ["uncovered"]);
});
