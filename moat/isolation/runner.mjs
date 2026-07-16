import { randomUUID } from "node:crypto";
import path from "node:path";

import { readJson } from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";

const ALL_EXIT_CODES = Object.freeze(Array.from({ length: 256 }, (_, code) => code));

const PATH_PROBE_PROGRAM = String.raw`
import { realpathSync, statSync } from "node:fs";
try {
  const canonical = realpathSync(process.argv[1]);
  const details = statSync(canonical);
  const kind = details.isFile() ? "file"
    : details.isDirectory() ? "directory"
      : details.isSocket() ? "socket"
        : details.isBlockDevice() ? "block-device"
          : details.isCharacterDevice() ? "character-device"
            : details.isFIFO() ? "fifo"
              : "other";
  process.stdout.write(JSON.stringify({ canonical, kind }));
} catch {
  process.exitCode = 1;
}
`;

const RUNTIME_ENDPOINT_PATTERNS = Object.freeze([
  /^\/(?:var\/)?run\/docker\.sock$/u,
  /^\/(?:var\/)?run\/containerd(?:\/|$)/u,
  /^\/(?:var\/)?run\/podman(?:\/|$)/u,
  /^\/run\/user\/[^/]+\/podman(?:\/|$)/u,
  /^\/(?:var\/)?run\/crio(?:\/|$)/u,
  /\/\.colima(?:\/[^/]+)?\/docker\.sock$/u,
  /\/\.docker\/run\/docker\.sock$/u,
]);

function isRuntimeEndpoint(candidate) {
  return RUNTIME_ENDPOINT_PATTERNS.some((pattern) => pattern.test(candidate));
}

function isWithinRoot(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`)
    && relative !== ".." && !path.isAbsolute(relative));
}

function probePath(candidate) {
  try {
    const result = runCommand("node", ["--input-type=module", "--eval", PATH_PROBE_PROGRAM, candidate]);
    const details = JSON.parse(result.stdout);
    if (typeof details?.canonical !== "string" || typeof details?.kind !== "string") {
      throw new TypeError("invalid path probe response");
    }
    return details;
  } catch {
    throw new TypeError("path cannot be canonicalized");
  }
}

function canonicalizeApprovedRoots(roots) {
  if (!Array.isArray(roots)) throw new TypeError("approved mount roots must be an array");
  return roots.map((root) => {
    if (typeof root !== "string" || !path.isAbsolute(root)) {
      throw new TypeError("approved mount roots must be absolute paths");
    }
    const details = probePath(root);
    if (details.kind !== "directory") {
      throw new TypeError("approved mount root must be a directory");
    }
    return details.canonical;
  });
}

function assertMount(mount, approvedRoots) {
  if (typeof mount?.source !== "string" || !path.isAbsolute(mount.source)
    || typeof mount?.target !== "string" || !path.posix.isAbsolute(mount.target)) {
    throw new TypeError("each mount requires an absolute string source and target");
  }
  if (mount.readOnly === false) throw new TypeError("isolation mounts are read-only");
  if (/[\0\r\n,]/u.test(mount.source) || /[\0\r\n,]/u.test(mount.target)) {
    throw new TypeError("mount paths contain forbidden characters");
  }

  const normalizedSource = path.normalize(mount.source);
  const canonicalTarget = path.posix.normalize(mount.target);
  if (isRuntimeEndpoint(normalizedSource) || isRuntimeEndpoint(canonicalTarget)) {
    throw new TypeError("container runtime endpoints cannot be mounted");
  }

  const sourceDetails = probePath(normalizedSource);
  const canonicalSource = sourceDetails.canonical;
  if (canonicalSource !== normalizedSource) {
    throw new TypeError("mount source must use its canonical real path");
  }
  if (isRuntimeEndpoint(canonicalSource)) {
    throw new TypeError("container runtime endpoints cannot be mounted");
  }
  if (sourceDetails.kind !== "file" && sourceDetails.kind !== "directory") {
    throw new TypeError("mount source must be a regular file or directory");
  }
  if (!approvedRoots.some((root) => isWithinRoot(canonicalSource, root))) {
    throw new TypeError("mount source resolves outside approved roots");
  }
  if (mount.target !== canonicalTarget) {
    throw new TypeError("mount target must use its normalized absolute path");
  }
}

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

function assertSpec(spec, approvedMountRoots) {
  if (typeof spec?.image !== "string" || !spec.image) throw new TypeError("container image is required");
  if (!Array.isArray(spec.command) || spec.command.length === 0
    || spec.command.some((part) => typeof part !== "string")) {
    throw new TypeError("target command must be a non-empty string array");
  }
  // Optional read-only source mounts (profile.hardening.mounts.source = "read-only").
  // Mounts are the ONLY way to make target code available inside the isolated
  // container; they are constrained read-only so they cannot weaken isolation.
  if (spec.mounts !== undefined) {
    if (!Array.isArray(spec.mounts)) throw new TypeError("spec.mounts must be an array");
    for (const mount of spec.mounts) assertMount(mount, approvedMountRoots);
  }
  if (spec.workdir !== undefined
    && (typeof spec.workdir !== "string" || !spec.workdir.startsWith("/"))) {
    throw new TypeError("spec.workdir must be an absolute path");
  }
  return { ...spec, mounts: [...(spec.mounts ?? [])] };
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

function containerArguments({ image, name, mounts = [], workdir }, profile) {
  const limits = profile.hardening.resource_limits;
  // Additive, read-only-only mount + workdir args. These never relax any
  // hardening flag below; every bind mount is forced `readonly`.
  const mountArgs = mounts.flatMap(({ source, target }) => [
    "--mount", `type=bind,src=${source},dst=${target},readonly`,
  ]);
  const workdirArgs = workdir ? ["--workdir", workdir] : [];
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
    ...mountArgs,
    ...workdirArgs,
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

export class IsolationSpecError extends Error {
  constructor(cause) {
    super(`isolation specification rejected: ${cause?.message ?? "invalid specification"}`, { cause });
    this.name = "IsolationSpecError";
    this.code = "MOAT_ISOLATION_SPEC_REJECTED";
  }
}

export function createIsolationRunner({
  runtime,
  profile,
  canarySuite,
  canaryExecutor = executeCanarySuite,
  approvedMountRoots = [],
}) {
  assertProfile(profile);
  assertCanarySuite(canarySuite);
  const canonicalMountRoots = canonicalizeApprovedRoots(approvedMountRoots);
  if (!runtime || typeof runtime.start !== "function"
    || typeof runtime.exec !== "function" || typeof runtime.remove !== "function") {
    throw new TypeError("container runtime contract is incomplete");
  }

  return async function isolatedRun(spec) {
    let validatedSpec;
    try {
      validatedSpec = assertSpec(spec, canonicalMountRoots);
    } catch (error) {
      throw new IsolationSpecError(error);
    }
    const container = await runtime.start(validatedSpec, profile);
    const result = { ok: false, canary: null, execution: null, containerRemoved: false };
    try {
      result.canary = await canaryExecutor({ runtime, container, canarySuite });
      if (!canaryPassed(result.canary, canarySuite)) throw new IsolationCanaryError(result.canary);
      result.execution = await runtime.exec(container, validatedSpec.command);
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
