---
name: sandbox-provision-discipline
description: Verify authorization, isolation, egress, credentials, persistence, evidence, and cleanup gates before provisioning or using a sandbox for PoCs, untrusted binaries, fuzzing, or other risky tests.
---

# Sandbox Provision Discipline

Use this skill before provisioning or using Docker, a VM, Kubernetes, or any
other environment for exploit PoCs, untrusted binaries, fuzzing, or tests that
could reach systems beyond the authorized target.

## Preflight gate

Record all of the following before execution:

1. The task's explicit authorization and exact target scope.
2. The isolation boundary and whether it is dedicated or shared.
3. Network policy: deny egress by default; enumerate any approved destination.
4. Credential policy: inject no production or unrelated credentials.
5. Filesystem policy: expose only required inputs; keep outputs in the packet's
   write scope; declare persistence and retention in advance.
6. Resource limits for CPU, memory, process count, time, and storage.
7. A harmless containment check showing the sandbox cannot reach an
   unapproved host, credential source, or host path.

If any item is unknown or cannot be verified, stop before payload execution
and report `needs_human` plus the missing guarantee. Do not weaken isolation to
make a test pass.

## Execution discipline

- Use disposable, uniquely labeled resources tied to the task ID.
- Keep host mounts read-only unless a specific write is required and approved.
- Capture the sandbox definition, tool versions, limits, containment-check
  result, and test timestamps without logging secret values.
- Never redirect a failed local test to a live target or another tenant.
- Treat unexpected egress, host access, or cross-tenant data as a hard stop.

## Cleanup and handoff

State the cleanup procedure and rollback before execution. Perform deletion or
destructive cleanup only when the governing task explicitly authorizes it.
Otherwise leave resources stopped, identify them precisely, and request
operator action. Report residual processes, mounts, volumes, network rules,
artifacts, and secrets even when the test succeeds.
