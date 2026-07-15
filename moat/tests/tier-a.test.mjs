import assert from "node:assert/strict";
import test from "node:test";

import { listFiles } from "../adapters/filesystem.mjs";
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

test("Tier-A passes its own Layer-1 tree with reviewed synthetic fixtures", async () => {
  const root = new URL("../", import.meta.url);
  const paths = await listFiles(root);
  const result = await scanPaths(paths, {
    honorReviewedFixtureAllowlist: true,
  });

  assert.deepEqual(result.findings, []);
  assert.equal(result.ok, true);
});
