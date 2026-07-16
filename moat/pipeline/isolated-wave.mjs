// Isolated synthetic wave — runs the synthetic-twin wave END-TO-END inside the
// hardened, canary-gated isolation container (moat/isolation/runner.mjs).
//
// Design: reuse `createIsolationRunner` unchanged, so every invariant it enforces
// still holds — mandatory pre-flight canary (loopback reachable while every
// external class is blocked; abort-on-unexpected-success; no canary, no
// execution), `--network none`, non-root, read-only rootfs, all caps dropped,
// no-new-privileges, pid/mem/cpu/file limits, noexec tmpfs, cleared proxy env,
// docker socket forbidden. The moat tree is bind-mounted READ-ONLY at /moat so
// the wave code + node_modules are available; the container is the boundary and
// the twins stay in-process within it.
//
// Fail-closed: a canary failure propagates (never swallowed); an unavailable
// container runtime surfaces an explicit `container_runtime_unavailable` state
// and NEVER silently falls back to in-process. The in-process path remains
// available only as an explicitly-labeled, non-isolated dev mode.

import { fileURLToPath } from "node:url";

import { readJson } from "../adapters/filesystem.mjs";
import { createDockerRuntime, createIsolationRunner } from "../isolation/runner.mjs";
import { runSyntheticWave } from "./synthetic-wave.mjs";

const MOAT_DIR = fileURLToPath(new URL("..", import.meta.url)).replace(/\/$/u, "");
const CONTAINER_MOAT = "/moat";
// A combined node + python image is required: the runner's canary probe is a
// python program, and the wave is node. Override with MOAT_WAVE_IMAGE.
const DEFAULT_IMAGE = process.env.MOAT_WAVE_IMAGE || "node:22-bookworm";

function inProcessMarker() {
  return {
    mode: "in-process",
    isolated: false,
    note: "NON-ISOLATED dev mode — no container and no canary; do not treat as an isolated result",
  };
}

export async function runIsolatedSyntheticWave({
  mode = "container",
  image = DEFAULT_IMAGE,
  moatDir = MOAT_DIR,
  runnerFactory,
  ledger = { netNew: true },
  independentReview = { confirmed: true },
  ...waveParams
} = {}) {
  if (mode === "in-process") {
    const result = await runSyntheticWave({ ...waveParams, ledger, independentReview });
    return { ...result, isolation: inProcessMarker() };
  }
  if (mode !== "container") {
    throw new TypeError(`unknown wave isolation mode: ${mode}`);
  }

  const [profile, canarySuite] = await Promise.all([
    readJson(new URL("../isolation/mac-container-vm.profile.json", import.meta.url)),
    readJson(new URL("../isolation/negative-canaries.json", import.meta.url)),
  ]);

  // Injectable for tests; production uses the real Docker runtime + runner so
  // the hardened container arguments and canary gate are exercised.
  const isolatedRun = runnerFactory
    ? runnerFactory({ profile, canarySuite })
    : createIsolationRunner({ runtime: createDockerRuntime(), profile, canarySuite });

  const spec = {
    image,
    command: ["node", `${CONTAINER_MOAT}/pipeline/wave-entrypoint.mjs`],
    mounts: [{ source: moatDir, target: CONTAINER_MOAT, readOnly: true }],
    workdir: CONTAINER_MOAT,
  };

  let run;
  try {
    run = await isolatedRun(spec);
  } catch (error) {
    // Fail-closed: a canary failure is NEVER swallowed or downgraded.
    if (error?.code === "MOAT_ISOLATION_CANARY_FAILED") throw error;
    // Genuine runtime unavailability — surface explicitly; never fall back to
    // in-process and call it isolated.
    return {
      waveResult: null,
      isolation: {
        mode: "container",
        isolated: false,
        state: "container_runtime_unavailable",
        reason: String(error?.message ?? error),
      },
    };
  }

  if (!run.execution || run.execution.status !== 0) {
    return {
      waveResult: null,
      isolation: {
        mode: "container",
        isolated: true,
        state: "wave_execution_failed",
        canary: run.canary,
        exit_status: run.execution?.status ?? null,
        stderr: String(run.execution?.stderr ?? "").slice(0, 2000),
      },
    };
  }

  let parsed;
  try {
    parsed = JSON.parse(run.execution.stdout);
  } catch {
    return {
      waveResult: null,
      isolation: { mode: "container", isolated: true, state: "wave_output_unparseable", canary: run.canary },
    };
  }

  return {
    waveResult: parsed.waveResult,
    evidence: parsed.evidence,
    isolation: { mode: "container", isolated: true, state: "ok", canary: run.canary },
  };
}
