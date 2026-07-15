import assert from "node:assert/strict";
import test from "node:test";

import { createExternalInput } from "../adapters/external-input.mjs";
import {
  createTemporaryDirectory,
  ensureDirectory,
  joinSystemPath,
  toSystemPath,
  writeText,
} from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";
import {
  ERROR_CLASSES,
  filesForRange,
  formatFindings,
  scanTierB,
} from "../boundary/tier-b.mjs";

const run = (command, args, options = {}) => runCommand(command, args, options).stdout.trim();

async function syntheticLayer({ descriptor = "valid" } = {}) {
  const root = await createTemporaryDirectory("moat-tier-b-");
  const bountyRoot = joinSystemPath(root, "bounty");
  const layer1Root = joinSystemPath(root, "workspace", "moat");
  const descriptorDirectory = joinSystemPath(bountyRoot, "descriptors");
  await ensureDirectory(descriptorDirectory);
  await ensureDirectory(layer1Root);

  const suffix = root.split("-").at(-1).toLowerCase();
  const privateToken = `${suffix}.invalid`;
  const denylist = {
    schema_version: "1.0.0",
    content_class: "restricted",
    targets: {
      hostnames: [privateToken],
      repositories: [`repository/${suffix}`],
      advisory_ids: [`ADV-${suffix}`],
      paths: [`services/${suffix}/route`],
    },
  };
  const descriptorPath = joinSystemPath(descriptorDirectory, "target-denylist.json");
  if (descriptor === "valid") await writeText(descriptorPath, JSON.stringify(denylist));
  if (descriptor === "malformed-json") await writeText(descriptorPath, "{not-json");
  if (descriptor === "invalid-schema") await writeText(descriptorPath, JSON.stringify({ targets: [] }));

  const midpoint = Math.floor(privateToken.length / 2);
  const files = {
    plain: joinSystemPath(layer1Root, "plain.mjs"),
    split: joinSystemPath(layer1Root, "split.mjs"),
    encoded: joinSystemPath(layer1Root, "encoded.mjs"),
    categories: joinSystemPath(layer1Root, "categories.txt"),
    clean: joinSystemPath(layer1Root, "clean.mjs"),
    broken: joinSystemPath(layer1Root, "broken.mjs"),
    outside: joinSystemPath(root, "documentation.md"),
  };
  await writeText(
    files.plain,
    `export const safe = "synthetic";\nexport const value = ${JSON.stringify(privateToken)};\n`,
  );
  await writeText(
    files.split,
    `export const value = ${JSON.stringify(privateToken.slice(0, midpoint))} + ${JSON.stringify(privateToken.slice(midpoint))};\n`,
  );
  await writeText(
    files.encoded,
    `export const value = ${JSON.stringify(Buffer.from(privateToken).toString("base64"))};\n`,
  );
  await writeText(files.clean, "export const value = 'synthetic-clean-value';\n");
  await writeText(files.categories, [
    denylist.targets.repositories[0].toUpperCase(),
    denylist.targets.advisory_ids[0].toLowerCase(),
    denylist.targets.paths[0],
    "",
  ].join("\n"));
  await writeText(files.broken, "export const value = `unterminated;\n");
  await writeText(files.outside, "Documentation-only change.\n");

  return {
    bountyRoot,
    externalInput: createExternalInput({ environment: { CHRONO_BOUNTY_ROOT: bountyRoot } }),
    files,
    layer1Root,
    denylist,
    privateToken,
  };
}

test("Tier-B blocks plain, split, and base64 private targets without disclosing the token", async () => {
  const fixture = await syntheticLayer();
  for (const name of ["plain", "split", "encoded"]) {
    const result = await scanTierB([fixture.files[name]], {
      externalInput: fixture.externalInput,
      layer1Root: fixture.layer1Root,
    });
    const output = formatFindings(result.findings);
    assert.equal(result.ok, false);
    assert.ok(result.findings.some(({ errorClass }) => errorClass === ERROR_CLASSES.TARGET_MATCH));
    assert.equal(output.includes(fixture.privateToken), false);
    assert.equal(JSON.stringify(result).includes(fixture.privateToken), false);
    if (name === "plain") assert.equal(result.findings[0].line, 2);
  }
});

test("Tier-B matches repository, advisory, and path denylist categories", async () => {
  const fixture = await syntheticLayer();
  const result = await scanTierB([fixture.files.categories], {
    externalInput: fixture.externalInput,
    layer1Root: fixture.layer1Root,
  });
  assert.equal(result.ok, false);
  assert.deepEqual(result.findings.map(({ line }) => line), [1, 2, 3]);
  const serialized = JSON.stringify(result);
  for (const values of Object.values(fixture.denylist.targets)) {
    for (const value of values) assert.equal(serialized.includes(value), false);
  }
});

test("Tier-B fails closed for root-unset, missing, malformed, and invalid denylists", async () => {
  const valid = await syntheticLayer();
  const rootUnset = await scanTierB([valid.files.clean], {
    externalInput: createExternalInput({ environment: {} }),
    layer1Root: valid.layer1Root,
  });
  assert.equal(rootUnset.ok, false);
  assert.equal(rootUnset.findings[0].errorClass, ERROR_CLASSES.DENYLIST_UNAVAILABLE);

  const missing = await syntheticLayer({ descriptor: "missing" });
  const missingResult = await scanTierB([missing.files.clean], {
    externalInput: missing.externalInput,
    layer1Root: missing.layer1Root,
  });
  assert.equal(missingResult.ok, false);
  assert.equal(missingResult.findings[0].errorClass, ERROR_CLASSES.DENYLIST_UNAVAILABLE);

  const malformed = await syntheticLayer({ descriptor: "malformed-json" });
  const malformedResult = await scanTierB([malformed.files.clean], {
    externalInput: malformed.externalInput,
    layer1Root: malformed.layer1Root,
  });
  assert.equal(malformedResult.ok, false);
  assert.equal(malformedResult.findings[0].errorClass, ERROR_CLASSES.DENYLIST_INVALID);

  const invalid = await syntheticLayer({ descriptor: "invalid-schema" });
  const invalidResult = await scanTierB([invalid.files.clean], {
    externalInput: invalid.externalInput,
    layer1Root: invalid.layer1Root,
  });
  assert.equal(invalidResult.ok, false);
  assert.equal(invalidResult.findings[0].errorClass, ERROR_CLASSES.DENYLIST_INVALID);
});

test("Tier-B passes a clean Layer-1 file and ignores non-Layer-1-only changes", async () => {
  const fixture = await syntheticLayer();
  const clean = await scanTierB([fixture.files.clean], {
    externalInput: fixture.externalInput,
    layer1Root: fixture.layer1Root,
  });
  assert.deepEqual(clean, { ok: true, findings: [] });

  const outside = await scanTierB([fixture.files.outside], {
    externalInput: createExternalInput({ environment: {} }),
    layer1Root: fixture.layer1Root,
  });
  assert.deepEqual(outside, { ok: true, findings: [] });
});

test("Tier-B fails closed when a Layer-1 source cannot be parsed", async () => {
  const fixture = await syntheticLayer();
  const result = await scanTierB([fixture.files.broken], {
    externalInput: fixture.externalInput,
    layer1Root: fixture.layer1Root,
  });
  assert.equal(result.ok, false);
  assert.equal(result.findings[0].errorClass, ERROR_CLASSES.SCAN_UNAVAILABLE);
});

test("Tier-B range mode resolves changed Layer-1 files from a local git history", async () => {
  const root = await createTemporaryDirectory("moat-tier-b-range-");
  const repository = joinSystemPath(root, "repository");
  await ensureDirectory(joinSystemPath(repository, "moat"));
  await ensureDirectory(joinSystemPath(repository, "docs"));
  await writeText(joinSystemPath(repository, "moat", "value.mjs"), "export const value = 1;\n");
  await writeText(joinSystemPath(repository, "docs", "notes.md"), "Initial.\n");
  run("git", ["init", "-q", repository]);
  run("git", ["-C", repository, "config", "user.name", "Synthetic Test"]);
  run("git", ["-C", repository, "config", "user.email", "synthetic@example.invalid"]);
  run("git", ["-C", repository, "add", "."]);
  run("git", ["-C", repository, "commit", "-q", "-m", "synthetic base"]);
  const base = run("git", ["-C", repository, "rev-parse", "HEAD"]);
  await writeText(joinSystemPath(repository, "moat", "value.mjs"), "export const value = 2;\n");
  await writeText(joinSystemPath(repository, "docs", "notes.md"), "Updated.\n");
  run("git", ["-C", repository, "add", "."]);
  run("git", ["-C", repository, "commit", "-q", "-m", "synthetic update"]);
  const head = run("git", ["-C", repository, "rev-parse", "HEAD"]);

  const changed = filesForRange(`${base}..${head}`, { repositoryRoot: repository });
  assert.deepEqual(changed, [joinSystemPath(repository, "moat", "value.mjs")]);

  const initialPush = filesForRange(`${"0".repeat(40)}..${base}`, {
    repositoryRoot: repository,
  });
  assert.deepEqual(initialPush, [joinSystemPath(repository, "moat", "value.mjs")]);
});

test("Tier-B CLI staged mode blocks Layer-1 changes when the private root is unset", () => {
  const cli = toSystemPath(new URL("../boundary/tier-b.mjs", import.meta.url));
  const layerFile = toSystemPath(new URL("../boundary/README.md", import.meta.url));
  const result = runCommand("node", [cli, "--staged", layerFile], {
    allowExitCodes: [1],
    environment: { ...process.env, CHRONO_BOUNTY_ROOT: "" },
  });
  assert.match(result.stderr, /MOAT_BOUNDARY_TIERB_DENYLIST_UNAVAILABLE/u);
});
