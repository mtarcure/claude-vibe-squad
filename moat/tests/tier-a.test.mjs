import assert from "node:assert/strict";
import test from "node:test";

import { listFiles, readJson, toSystemPath } from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";
import {
  ERROR_CLASSES,
  scanPaths,
} from "../boundary/tier-a.mjs";

const fixture = (group, name) =>
  new URL(`../fixtures/purity/${group}/${name}`, import.meta.url);

const denied = [
  ["comment-leak.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["split-literal.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["json-leak.json", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["yaml-leak.yaml", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["unicode-leak.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["base64-leak.txt", ERROR_CLASSES.ENCODED_IDENTIFIER],
  ["fixture-ref.json", ERROR_CLASSES.PATH_ROOT],
  ["forbidden-import.mjs", ERROR_CLASSES.FORBIDDEN_IMPORT],
  ["direct-read.mjs", ERROR_CLASSES.DIRECT_PRIVATE_READ],
  ["capability-import.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["credential.mjs", ERROR_CLASSES.SECRET],
  ["template-host.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["computed-import.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["variable-require.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["unresolved-require.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["create-require.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["char-code-import.mjs", ERROR_CLASSES.CAPABILITY_IMPORT],
  ["ipv6-fetch.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["bare-ipv6-fetch.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["base64url-target.mjs", ERROR_CLASSES.ENCODED_IDENTIFIER],
  ["sink-host.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["e2-concat-fetch.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["e7-map-join-fetch.mjs", ERROR_CLASSES.UNRESOLVED_SINK],
  ["e8-atob-fetch.mjs", ERROR_CLASSES.ENCODED_IDENTIFIER],
  ["e9-replace-fetch.mjs", ERROR_CLASSES.EXTERNAL_IDENTIFIER],
  ["bare-variable-fetch.mjs", ERROR_CLASSES.UNRESOLVED_SINK],
];

for (const [name, expectedClass] of denied) {
  test(`Tier-A blocks ${name}`, async () => {
    const result = await scanPaths([fixture("deny", name)], {
      honorReviewedFixtureAllowlist: false,
    });

    assert.equal(result.ok, false);
    assert.ok(
      result.findings.some((finding) => finding.errorClass === expectedClass),
      `expected ${expectedClass}, got ${result.findings.map((item) => item.errorClass).join(", ")}`,
    );
  });
}

test("Tier-A passes the legitimate generic-source corpus and records FP rate", async (context) => {
  const paths = [
    fixture("allow", "generic-constants.mjs"),
    fixture("allow", "protocol-vectors.json"),
    fixture("allow", "package-metadata.json"),
    fixture("allow", "public-docs.ts"),
    fixture("allow", "public-component.tsx"),
    fixture("allow", "real-world-vectors.json"),
    fixture("allow", "constant-sink-folding.mjs"),
  ];
  const result = await scanPaths(paths, {
    honorReviewedFixtureAllowlist: false,
  });
  const falsePositives = new Set(result.findings.map((item) => item.file)).size;
  const rate = falsePositives / paths.length;

  context.diagnostic(
    `Tier-A legitimate corpus FP rate: ${falsePositives}/${paths.length} = ${(rate * 100).toFixed(2)}%`,
  );
  assert.equal(result.ok, true);
  assert.equal(rate, 0);
});

test("Tier-A converts a forced per-file scanner exception into a finding", async () => {
  const result = await scanPaths([fixture("allow", "public-docs.ts")], {
    honorReviewedFixtureAllowlist: false,
    secretScanner() {
      throw new Error("forced scanner failure");
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.findings[0].errorClass, ERROR_CLASSES.SCAN_FAILURE);
  assert.match(result.findings[0].file, /public-docs\.ts$/u);
  assert.match(result.findings[0].message, /forced scanner failure/u);
});

test("Tier-A reports a simulated missing TypeScript parser without throwing", async () => {
  const result = await scanPaths([fixture("allow", "public-docs.ts")], {
    honorReviewedFixtureAllowlist: false,
    parserAvailable: () => false,
  });
  assert.equal(result.ok, false);
  assert.equal(result.findings[0].errorClass, ERROR_CLASSES.TOOL_UNAVAILABLE);
  assert.match(result.findings[0].message, /TypeScript parser is unavailable/u);
  assert.doesNotMatch(result.findings[0].message, /ERR_MODULE_NOT_FOUND/u);
});

test("Tier-A parser is a production dependency", async () => {
  const packageJson = await readJson(new URL("../package.json", import.meta.url));
  assert.equal(packageJson.dependencies?.typescript, "5.9.3");
  assert.equal(packageJson.devDependencies?.typescript, undefined);
});

test("Tier-A staged mode accepts an explicit staged-file list", () => {
  const cli = toSystemPath(new URL("../boundary/tier-a.mjs", import.meta.url));
  const allowed = runCommand("node", [cli, "--staged", toSystemPath(fixture("allow", "public-docs.ts"))], {
    allowExitCodes: [0],
  });
  assert.equal(allowed.status, 0);

  const reviewedDeny = runCommand("node", [cli, "--staged", toSystemPath(fixture("deny", "computed-import.mjs"))], {
    allowExitCodes: [0],
  });
  assert.equal(reviewedDeny.status, 0);

  const empty = runCommand("node", [cli, "--staged"], { allowExitCodes: [0] });
  assert.equal(empty.status, 0);
});

test("Tier-A passes its own Layer-1 tree with reviewed synthetic fixtures", async () => {
  const root = new URL("../", import.meta.url);
  const paths = await listFiles(root);
  const result = await scanPaths(paths, {
    honorReviewedFixtureAllowlist: true,
  });

  assert.deepEqual(result.findings, []);
  assert.equal(result.ok, true);
});
