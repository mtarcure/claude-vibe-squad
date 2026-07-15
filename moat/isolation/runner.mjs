import { randomUUID } from "node:crypto";

import { readJson } from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";

const ALL_EXIT_CODES = Object.freeze(Array.from({ length: 256 }, (_, code) => code));

const CANARY_PROGRAM = String.raw`
import http.server
import json
import os
import socket
import ssl
import sys
import threading
import urllib.request

suite = json.load(sys.stdin)

class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args):
        pass

server = http.server.HTTPServer(("127.0.0.1", 8080), Health)
threading.Thread(target=server.serve_forever, daemon=True).start()

def external_socket(destination, family, port):
    addresses = socket.getaddrinfo(destination, port, family, socket.SOCK_STREAM)
    sock = socket.socket(addresses[0][0], socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect(addresses[0][4])
    finally:
        sock.close()

def probe(entry):
    probe_class = entry["class"]
    destination = entry["destination"]
    if probe_class == "proxy_environment":
        leaked = [name for name in entry.get("environment_variables", []) if os.environ.get(name)]
        if leaked:
            return {
                "id": entry["id"],
                "class": probe_class,
                "observed": "configuration-failed",
                "passed": False,
                "detail": "proxy environment leaked into isolated container",
            }
    try:
        if probe_class == "loopback_control":
            with urllib.request.urlopen(destination, timeout=2) as response:
                if response.status != 204:
                    raise RuntimeError("unexpected loopback status")
        elif probe_class == "ipv4":
            external_socket(destination, socket.AF_INET, 80)
        elif probe_class == "ipv6":
            external_socket(destination, socket.AF_INET6, 80)
        elif probe_class == "dns":
            socket.getaddrinfo(destination, 80)
        elif probe_class == "proxy_environment":
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(destination, timeout=2):
                pass
        elif probe_class == "host_gateway":
            external_socket(destination, socket.AF_UNSPEC, 80)
        elif probe_class == "tcp_tls":
            host, port = destination.rsplit(":", 1)
            raw = socket.create_connection((host, int(port)), timeout=2)
            try:
                ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            finally:
                raw.close()
        else:
            raise RuntimeError("unsupported canary class")
        reached = True
        detail = "operation succeeded"
    except Exception as error:
        reached = False
        detail = type(error).__name__

    expects_reachable = probe_class == "loopback_control"
    passed = reached if expects_reachable else not reached
    return {
        "id": entry["id"],
        "class": probe_class,
        "observed": "reachable" if reached else "blocked",
        "passed": passed,
        "detail": detail,
    }

results = [probe(entry) for entry in suite["probes"]]
server.shutdown()
print(json.dumps({"ok": all(item["passed"] for item in results), "probes": results}))
`;

function assertProfile(profile) {
  const hardening = profile?.hardening;
  if (profile?.single_process?.network_mode !== "none") {
    throw new TypeError("single-process isolation requires network mode none");
  }
  if (hardening?.docker_socket !== "forbidden"
    || hardening.run_as_non_root !== true
    || hardening.read_only_rootfs !== true
    || !hardening.capabilities?.drop?.includes("ALL")
    || hardening.capabilities?.add?.length !== 0) {
    throw new TypeError("isolation hardening profile is incomplete");
  }
}

function assertSpec(spec) {
  if (typeof spec?.image !== "string" || !spec.image) throw new TypeError("container image is required");
  if (!Array.isArray(spec.command) || spec.command.length === 0
    || spec.command.some((part) => typeof part !== "string")) {
    throw new TypeError("target command must be a non-empty string array");
  }
}

const REQUIRED_CANARY_CLASSES = Object.freeze([
  "ipv4",
  "ipv6",
  "dns",
  "proxy_environment",
  "host_gateway",
  "tcp_tls",
  "loopback_control",
]);

function assertCanarySuite(canarySuite) {
  if (canarySuite?.abort_on_unexpected_success !== true
    || canarySuite.require_loopback_control_success !== true
    || !Array.isArray(canarySuite.probes)) {
    throw new TypeError("canary suite must fail closed and require loopback control");
  }
  const classes = new Set(canarySuite.probes.map((probe) => probe.class));
  const ids = new Set(canarySuite.probes.map((probe) => probe.id));
  if (ids.size !== canarySuite.probes.length) throw new TypeError("canary ids must be unique");
  for (const required of REQUIRED_CANARY_CLASSES) {
    if (!classes.has(required)) throw new TypeError(`canary suite is missing ${required}`);
  }
}

function canaryPassed(canary, canarySuite) {
  if (canary?.ok !== true || !Array.isArray(canary.probes)
    || canary.probes.length !== canarySuite.probes.length) return false;
  const observed = new Map(canary.probes.map((probe) => [probe.id, probe]));
  return canarySuite.probes.every((expected) => {
    const actual = observed.get(expected.id);
    if (!actual || actual.class !== expected.class || actual.passed !== true) return false;
    return expected.class === "loopback_control"
      ? actual.observed === "reachable"
      : actual.observed === "blocked";
  });
}

function containerArguments({ image, name }, profile) {
  const limits = profile.hardening.resource_limits;
  return [
    "run",
    "--detach",
    "--name", name,
    "--label", "moat.phase=4b",
    "--network", "none",
    "--read-only",
    "--user", "65534:65534",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--no-healthcheck",
    "--pids-limit", String(limits.pids),
    "--memory", `${limits.memory_mb}m`,
    "--cpus", String(limits.cpu_count),
    "--ulimit", `fsize=${limits.file_size_mb * 1024}:${limits.file_size_mb * 1024}`,
    "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
    "--env", "HTTP_PROXY=",
    "--env", "HTTPS_PROXY=",
    "--env", "ALL_PROXY=",
    "--env", "NO_PROXY=",
    "--entrypoint", "sh",
    image,
    "-c", "while :; do sleep 3600; done",
  ];
}

export function createDockerRuntime({ engine = "docker", commandRunner = runCommand } = {}) {
  return Object.freeze({
    async start(spec, profile) {
      const name = spec.name ?? `moat-phase4b-${randomUUID()}`;
      const result = commandRunner(engine, containerArguments({ ...spec, name }, profile));
      return { id: result.stdout.trim(), name };
    },
    async exec(container, command, { input } = {}) {
      return commandRunner(engine, ["exec", "--interactive", container.id, ...command], {
        allowExitCodes: ALL_EXIT_CODES,
        input,
      });
    },
    async remove(container) {
      commandRunner(engine, ["rm", "--force", container.id]);
    },
  });
}

async function executeCanarySuite({ runtime, container, canarySuite }) {
  const result = await runtime.exec(container, ["python", "-c", CANARY_PROGRAM], {
    input: JSON.stringify(canarySuite),
  });
  if (result.status !== 0) {
    return {
      ok: false,
      probes: [],
      diagnostic: `canary process failed with status ${result.status}`,
    };
  }
  try {
    return JSON.parse(result.stdout);
  } catch {
    return { ok: false, probes: [], diagnostic: "canary process returned invalid JSON" };
  }
}

export class IsolationCanaryError extends Error {
  constructor(canary) {
    super("isolation canary failed; target execution aborted");
    this.name = "IsolationCanaryError";
    this.code = "MOAT_ISOLATION_CANARY_FAILED";
    this.canary = canary;
  }
}

export function createIsolationRunner({
  runtime,
  profile,
  canarySuite,
  canaryExecutor = executeCanarySuite,
}) {
  assertProfile(profile);
  assertCanarySuite(canarySuite);
  if (!runtime || typeof runtime.start !== "function"
    || typeof runtime.exec !== "function" || typeof runtime.remove !== "function") {
    throw new TypeError("container runtime contract is incomplete");
  }

  return async function isolatedRun(spec) {
    assertSpec(spec);
    const container = await runtime.start(spec, profile);
    const result = { ok: false, canary: null, execution: null, containerRemoved: false };
    try {
      result.canary = await canaryExecutor({ runtime, container, canarySuite });
      if (!canaryPassed(result.canary, canarySuite)) throw new IsolationCanaryError(result.canary);
      result.execution = await runtime.exec(container, spec.command);
      result.ok = result.execution.status === 0;
      return result;
    } finally {
      await runtime.remove(container);
      result.containerRemoved = true;
    }
  };
}

export async function runIsolated(spec) {
  const [profile, canarySuite] = await Promise.all([
    readJson(new URL("./mac-container-vm.profile.json", import.meta.url)),
    readJson(new URL("./negative-canaries.json", import.meta.url)),
  ]);
  return createIsolationRunner({
    runtime: createDockerRuntime(),
    profile,
    canarySuite,
  })(spec);
}
