import assert from "node:assert/strict";
import test from "node:test";

import {
  createDockerRuntime,
  createIsolationRunner,
  IsolationCanaryError,
} from "../isolation/runner.mjs";
import { runIsolatedSyntheticWave } from "../pipeline/isolated-wave.mjs";
import { runSyntheticWave } from "../pipeline/synthetic-wave.mjs";

const MOAT_ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/u, "");

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
    .map((canaryClass) => ({ id: `canary:${canaryClass}`, class: canaryClass })),
};

let validPayloadPromise;
function validPayload() {
  validPayloadPromise ??= runSyntheticWave({
    ledger: { netNew: true },
    independentReview: { confirmed: true },
  });
  return validPayloadPromise;
}

// A canary result that satisfies the runner's real canaryPassed() for a suite:
// loopback reachable, every external class blocked, all probes passed.
function passingCanary(suite) {
  return {
    ok: true,
    probes: suite.probes.map((probe) => ({
      id: probe.id,
      class: probe.class,
      passed: true,
      observed: probe.class === "loopback_control" ? "reachable" : "blocked",
    })),
  };
}

// Build a runnerFactory that plugs a fake runtime + injected canary into the
// REAL createIsolationRunner, so the genuine canary gate + hardening asserts run.
function factory(fakeRuntime, canaryResult) {
  return ({ profile, canarySuite, approvedMountRoots }) =>
    createIsolationRunner({
      runtime: fakeRuntime,
      profile,
      canarySuite,
      canaryExecutor: async () => canaryResult ?? passingCanary(canarySuite),
      approvedMountRoots,
    });
}

async function runWithStdout(stdout) {
  const fakeRuntime = {
    async start() { return { id: "c" }; },
    async exec() { return { status: 0, stdout, stderr: "" }; },
    async remove() {},
  };
  return runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime) });
}

test("container mode: canary passes → schema-valid WaveResult is parsed", async () => {
  const execCalls = [];
  const payload = await validPayload();
  const fakeRuntime = {
    async start() { return { id: "test-container" }; },
    async exec(_container, command) {
      execCalls.push(command);
      return { status: 0, stdout: JSON.stringify(payload), stderr: "" };
    },
    async remove() {},
  };

  const result = await runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime) });

  assert.equal(result.isolation.isolated, true);
  assert.equal(result.isolation.state, "ok");
  assert.equal(result.waveResult.schema_version, "1.0.0");
  assert.ok(["PASS", "FAIL", "INCONCLUSIVE"].includes(result.waveResult.state));
  assert.ok(result.evidence.coverage);
  // The wave command executed inside the container (after the canary gate).
  assert.deepEqual(execCalls, [["node", "/moat/pipeline/wave-entrypoint.mjs"]]);
  assert.equal(result.isolation.canary.ok, true);
});

test("fail-closed: a failing canary aborts BEFORE the wave runs and propagates the canary error", async () => {
  const execCalls = [];
  const fakeRuntime = {
    async start() { return { id: "test-container" }; },
    async exec(_container, command) { execCalls.push(command); return { status: 0, stdout: "must-not-run", stderr: "" }; },
    async remove() {},
  };
  const failingCanary = { ok: true, probes: [{ id: "canary:ipv4-direct", class: "ipv4", passed: false, observed: "reachable" }] };

  await assert.rejects(
    () => runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime, failingCanary) }),
    (error) => error instanceof IsolationCanaryError && error.code === "MOAT_ISOLATION_CANARY_FAILED",
  );
  // The wave command was NEVER executed — no canary, no execution.
  assert.deepEqual(execCalls, []);
});

test("graceful-unavailable: runtime that cannot start surfaces container_runtime_unavailable, no in-process fallback", async () => {
  const fakeRuntime = {
    async start() { throw new Error("Cannot connect to the Docker daemon at unix:///var/run/docker.sock"); },
    async exec() { throw new Error("must not exec"); },
    async remove() {},
  };

  const result = await runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime) });

  assert.equal(result.isolation.mode, "container");
  assert.equal(result.isolation.isolated, false);
  assert.equal(result.isolation.state, "container_runtime_unavailable");
  assert.equal(result.waveResult, null); // did NOT silently run in-process (that would return a waveResult)
  assert.match(result.isolation.reason, /Docker daemon/);
});

test("mount-policy rejection is fail-closed and never mislabeled runtime-unavailable", async () => {
  let startCalls = 0;
  let execCalls = 0;
  const fakeRuntime = {
    async start() { startCalls += 1; return { id: "must-not-start" }; },
    async exec() { execCalls += 1; return { status: 0, stdout: "{}" }; },
    async remove() {},
  };
  const result = await runIsolatedSyntheticWave({
    moatDir: "/var/run/docker.sock",
    runnerFactory: factory(fakeRuntime),
  });
  assert.equal(result.isolation.state, "isolation_spec_invalid");
  assert.notEqual(result.isolation.state, "container_runtime_unavailable");
  assert.equal(result.waveResult, null);
  assert.equal(startCalls, 0);
  assert.equal(execCalls, 0);
});

test("in-process mode is available but explicitly labeled NON-ISOLATED", async () => {
  const result = await runIsolatedSyntheticWave({ mode: "in-process" });
  assert.equal(result.isolation.mode, "in-process");
  assert.equal(result.isolation.isolated, false);
  assert.match(result.isolation.note, /NON-ISOLATED/);
  assert.ok(["PASS", "FAIL", "INCONCLUSIVE"].includes(result.waveResult.state));
});

test("container run with non-zero exit is a labeled failure, never a WaveResult", async () => {
  const fakeRuntime = {
    async start() { return { id: "c" }; },
    async exec() { return { status: 1, stdout: "", stderr: "wave-entrypoint failed" }; },
    async remove() {},
  };
  const result = await runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime) });
  assert.equal(result.isolation.state, "wave_execution_failed");
  assert.equal(result.isolation.isolated, true);
  assert.equal(result.waveResult, null);
});

test("container run with unparseable stdout is a labeled failure", async () => {
  const fakeRuntime = {
    async start() { return { id: "c" }; },
    async exec() { return { status: 0, stdout: "not json", stderr: "" }; },
    async remove() {},
  };
  const result = await runIsolatedSyntheticWave({ runnerFactory: factory(fakeRuntime) });
  assert.equal(result.isolation.state, "wave_output_unparseable");
  assert.equal(result.waveResult, null);
});

const invalidEnvelopeCases = [
  ["empty object", async () => ({})],
  ["null", async () => null],
  ["array", async () => []],
  ["incomplete WaveResult", async () => ({ waveResult: { state: "FAIL" }, evidence: {} })],
  ["fabricated PASS", async () => ({ waveResult: { state: "PASS" }, evidence: {} })],
  ["unexpected envelope field", async () => ({ ...(await validPayload()), unexpected: true })],
];

for (const [label, payload] of invalidEnvelopeCases) {
  test(`container output fails closed for ${label}`, async () => {
    const result = await runWithStdout(JSON.stringify(await payload()));
    assert.equal(result.isolation.state, "wave_output_unparseable");
    assert.notEqual(result.isolation.state, "ok");
    assert.equal(result.waveResult, null);
  });
}

test("read-only mount + workdir are additive; every hardening flag stays intact", async () => {
  const captured = [];
  const runtime = createDockerRuntime({
    commandRunner: (_engine, args) => { captured.push(args); return { stdout: "cid\n", status: 0 }; },
  });
  await runtime.start(
    { image: "img", command: ["node"], mounts: [{ source: "/abs/moat", target: "/moat", readOnly: true }], workdir: "/moat" },
    syntheticProfile,
  );
  const args = captured[0];
  const flagValue = (flag) => args[args.indexOf(flag) + 1];
  assert.equal(flagValue("--network"), "none");
  assert.ok(args.includes("--read-only"));
  assert.equal(flagValue("--user"), "65534:65534");
  assert.equal(flagValue("--cap-drop"), "ALL");
  assert.equal(flagValue("--security-opt"), "no-new-privileges");
  // the mount is present and forced read-only
  assert.equal(flagValue("--mount"), "type=bind,src=/abs/moat,dst=/moat,readonly");
  assert.equal(flagValue("--workdir"), "/moat");
  // and the mount is inserted BEFORE the image (not after the command)
  assert.ok(args.indexOf("--mount") < args.indexOf("img"));
});

test("assertSpec rejects a writable mount and a relative mount source", async () => {
  const runtime = { async start() { return { id: "c" }; }, async exec() { return { status: 0, stdout: "{}" }; }, async remove() {} };
  const suite = {
    abort_on_unexpected_success: true,
    require_loopback_control_success: true,
    probes: ["ipv4", "ipv6", "dns", "proxy_environment", "host_gateway", "tcp_tls", "loopback_control"]
      .map((c) => ({ id: `canary:${c}`, class: c })),
  };
  const runner = createIsolationRunner({ runtime, profile: syntheticProfile, canarySuite: suite, canaryExecutor: async () => passingCanary(suite) });
  await assert.rejects(
    () => runner({ image: "img", command: ["node"], mounts: [{ source: "/abs", target: "/moat", readOnly: false }] }),
    /read-only/,
  );
  await assert.rejects(
    () => runner({ image: "img", command: ["node"], mounts: [{ source: "relative/path", target: "/moat" }] }),
    /absolute string source/,
  );
});

test("mount policy rejects runtime sockets, devices, and out-of-scope paths before start", async () => {
  let startCalls = 0;
  let execCalls = 0;
  const runtime = {
    async start() { startCalls += 1; return { id: "must-not-start" }; },
    async exec() { execCalls += 1; return { status: 0, stdout: "{}" }; },
    async remove() {},
  };
  const runner = createIsolationRunner({
    runtime,
    profile: syntheticProfile,
    canarySuite: syntheticCanarySuite,
    canaryExecutor: async () => passingCanary(syntheticCanarySuite),
    approvedMountRoots: [MOAT_ROOT],
  });

  await assert.rejects(
    () => runner({
      image: "img",
      command: ["node"],
      mounts: [{ source: "/var/run/docker.sock", target: "/var/run/docker.sock", readOnly: true }],
    }),
    /runtime endpoints/,
  );
  await assert.rejects(
    () => runner({ image: "img", command: ["node"], mounts: [{ source: "/", target: "/host" }] }),
    /outside approved roots/,
  );
  await assert.rejects(
    () => runner({ image: "img", command: ["node"], mounts: [{ source: "/dev/null", target: "/moat/device" }] }),
    /regular file or directory/,
  );
  await assert.rejects(
    () => runner({
      image: "img",
      command: ["node"],
      mounts: [{ source: MOAT_ROOT, target: "/run/containerd/containerd.sock" }],
    }),
    /runtime endpoints/,
  );
  assert.equal(startCalls, 0);
  assert.equal(execCalls, 0);
});
