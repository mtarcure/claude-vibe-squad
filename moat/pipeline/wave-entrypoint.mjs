// Container entrypoint — runs INSIDE the hardened isolation container.
//
// The container itself is the isolation boundary (`--network none`, non-root,
// read-only rootfs, all caps dropped, canary-gated by the runner BEFORE this
// executes). The synthetic twins stay in-process WITHIN this container (Phase-4a
// requires the in-process twin profile); "isolated" refers to this whole node
// process running inside the container, not the twins spawning subprocesses.
//
// It runs the synthetic wave with reviewed synthetic evidence and prints a
// single JSON object {waveResult, evidence} to stdout for the host to parse.
// Fail-closed: any error exits non-zero with a diagnostic on stderr, and the
// host treats a non-zero exit / unparseable stdout as a failed run (never PASS).

import { runSyntheticWave } from "./synthetic-wave.mjs";

try {
  const result = await runSyntheticWave({
    ledger: { netNew: true },
    independentReview: { confirmed: true },
  });
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(`wave-entrypoint failed: ${error?.stack ?? error}\n`);
  process.exitCode = 1;
}
