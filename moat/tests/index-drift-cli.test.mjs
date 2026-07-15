import assert from "node:assert/strict";
import test from "node:test";

import {
  createTemporaryDirectory,
  joinSystemPath,
  toSystemPath,
  writeText,
} from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";

const moatRoot = toSystemPath(new URL("..", import.meta.url));
const cli = joinSystemPath(moatRoot, "pipeline", "check-invariant-index.mjs");
const descriptor = joinSystemPath(moatRoot, "fixtures", "schema", "valid", "invariant.invariant.json");
const currentIndex = joinSystemPath(moatRoot, "invariants", "index.json");

test("index drift CLI passes current state and fails drift", async () => {
  const current = runCommand("node", [cli, "--index", currentIndex, descriptor], {
    allowExitCodes: [0],
  });
  assert.equal(current.status, 0);

  const root = await createTemporaryDirectory("moat-index-drift-");
  const drifted = joinSystemPath(root, "index.json");
  await writeText(drifted, JSON.stringify({
    schema_version: "1.0.0",
    content_class: "public-safe",
    invariants: [],
  }));
  const failure = runCommand("node", [cli, "--index", drifted, descriptor], {
    allowExitCodes: [1],
  });
  assert.equal(failure.status, 1);
  assert.match(failure.stderr, /invariant index drift detected/u);
});
