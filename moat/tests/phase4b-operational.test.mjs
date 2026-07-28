import assert from "node:assert/strict";
import test from "node:test";

import {
  createDockerRuntime,
  createIsolationRunner,
  IsolationCanaryError,
  runIsolated,
} from "../isolation/runner.mjs";
import { runSyntheticWave } from "../pipeline/synthetic-wave.mjs";
import { validateNamed } from "../schema/validate.mjs";

const reviewedWave = (options) => runSyntheticWave({
  ...options,
  ledger: { netNew: true },
  independentReview: { confirmed: true },
});

const syntheticProfile = {
  single_process: { network_mode: "none" },
  hardening: {
    docker_socket: "forbidden",
    run_as_non_root: true,
    read_only_rootfs: true,
    capabilities: { drop: ["ALL"], add: [] },
    resource_limits: { pids: 16, memory_mb: 64, cpu_count: 1, file_size_mb: 8 },
  },
};

const syntheticCanarySuite = {
  abort_on_unexpected_success: true,
  require_loopback_control_success: true,
  probes: ["ipv4", "ipv6", "dns", "proxy_environment", "host_gateway", "tcp_tls", "loopback_control"]
    .map((probeClass) => ({ id: `canary:${probeClass}`, class: probeClass })),
};

test("runIsolated hard-aborts before target execution when any canary fails", async () => {
  const events = [];
  const runtime = {
    async start() {
      events.push("start");
      return { id: "synthetic-container" };
    },
    async exec() {
      events.push("target");
      return { status: 0, stdout: "must-not-run", stderr: "" };
    },
    async remove() {
      events.push("remove");
    },
  };
  const runner = createIsolationRunner({
    runtime,
    profile: syntheticProfile,
    canarySuite: syntheticCanarySuite,
    canaryExecutor: async () => ({
      ok: true,
      probes: [{ id: "canary:synthetic-failure", passed: false }],
    }),
  });

  await assert.rejects(
    () => runner({ image: "synthetic:image", command: ["synthetic-target"] }),
    (error) => error instanceof IsolationCanaryError && error.code === "MOAT_ISOLATION_CANARY_FAILED",
  );
  assert.deepEqual(events, ["start", "remove"]);
});

test("Docker runtime enforces hardening before the image and overrides image startup", async () => {
  const calls = [];
  const runtime = createDockerRuntime({
    commandRunner(command, args) {
      calls.push({ command, args });
      return { status: 0, stdout: "synthetic-container-id\n", stderr: "" };
    },
  });

  await runtime.start({ image: "synthetic:image" }, syntheticProfile);
  const args = calls[0].args;
  assert.equal(calls[0].command, "docker");
  for (const expected of [
    "--network", "none", "--read-only", "--user", "65534:65534",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--no-healthcheck",
    "--entrypoint", "sh",
  ]) {
    assert.ok(args.includes(expected), `missing ${expected}`);
  }
  assert.equal(args.includes("--volume"), false);
  assert.ok(args.indexOf("--entrypoint") < args.indexOf("synthetic:image"));
});

test("real Colima container blocks every external canary and permits loopback", {
  timeout: 60_000,
}, async () => {
  const result = await runIsolated({
    image: "python:3.11",
    command: ["python", "-c", "print('synthetic-target-ran')"],
  });

  assert.equal(result.ok, true);
  assert.equal(result.execution.stdout.trim(), "synthetic-target-ran");
  assert.equal(result.canary.ok, true);
  for (const required of ["ipv4", "ipv6", "dns", "proxy_environment", "host_gateway"] ) {
    const probe = result.canary.probes.find((entry) => entry.class === required);
    assert.ok(probe, `missing ${required}`);
    assert.equal(probe.observed, "blocked", `${required} unexpectedly reached out`);
    assert.equal(probe.passed, true);
  }
  const loopback = result.canary.probes.find((entry) => entry.class === "loopback_control");
  assert.equal(loopback.observed, "reachable");
  assert.equal(loopback.passed, true);
  assert.equal(result.containerRemoved, true);
});

test("Jazzer escalation resolves an otherwise incomplete synthetic slice", async () => {
  const baseline = await reviewedWave({ seed: 31337, numRuns: 2, omitTransitions: ["redirect"] });
  assert.equal(baseline.waveResult.state, "INCONCLUSIVE");

  const escalated = await reviewedWave({
    seed: 31337,
    numRuns: 2,
    omitTransitions: ["redirect"],
    escalation: { enabled: true, maxRuns: 64 },
  });

  assert.equal(escalated.evidence.escalation.driver, "jazzer.js");
  assert.equal(escalated.evidence.escalation.invoked, true);
  assert.ok(escalated.evidence.transitions.counts.redirect > 0);
  assert.ok(escalated.evidence.escalation.coverage.covered > 0);
  assert.equal(escalated.waveResult.state, "PASS");
  assert.deepEqual(await validateNamed("WaveResult", escalated.waveResult), []);
});

test("disabled Jazzer escalation leaves the default fast-check path untouched", async () => {
  const result = await reviewedWave({
    seed: 19,
    numRuns: 2,
    omitTransitions: ["redirect"],
    escalation: { enabled: false },
  });

  assert.equal(result.waveResult.state, "INCONCLUSIVE");
  assert.equal(result.evidence.escalation.invoked, false);
  assert.equal(result.evidence.escalation.driver, "fast-check");
  assert.equal(result.evidence.transitions.counts.redirect, 0);
});
