import assert from "node:assert/strict";
import test from "node:test";

import { readJson } from "../adapters/filesystem.mjs";

test("Mac isolation profile encodes the required static hardening", async () => {
  const profile = await readJson(
    new URL("../isolation/mac-container-vm.profile.json", import.meta.url),
  );

  assert.deepEqual(profile.backends, ["colima", "lima", "docker-desktop"]);
  assert.equal(profile.single_process.network_mode, "none");
  assert.equal(profile.multi_process.network_internal, true);
  assert.equal(profile.hardening.run_as_non_root, true);
  assert.equal(profile.hardening.read_only_rootfs, true);
  assert.equal(profile.hardening.docker_socket, "forbidden");
  assert.deepEqual(profile.hardening.capabilities, { drop: ["ALL"], add: [] });
  assert.ok(profile.hardening.resource_limits.pids > 0);
  assert.ok(profile.hardening.resource_limits.memory_mb > 0);
  assert.ok(profile.hardening.resource_limits.cpu_count > 0);
  assert.ok(profile.hardening.resource_limits.file_size_mb > 0);
});

test("negative canaries cover every required Mac egress path", async () => {
  const probes = await readJson(
    new URL("../isolation/negative-canaries.json", import.meta.url),
  );
  const classes = new Set(probes.probes.map((probe) => probe.class));

  for (const required of [
    "ipv4",
    "ipv6",
    "dns",
    "proxy_environment",
    "host_gateway",
    "tcp_tls",
  ]) {
    assert.ok(classes.has(required), `missing ${required} negative probe`);
  }
  assert.equal(probes.abort_on_unexpected_success, true);
  assert.equal(probes.require_loopback_control_success, true);
});
