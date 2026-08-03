---
name: wirework-preflight
status: authored
description: Use before starting an expensive or long-running task — probe that the MCPs, credentials, model lane, and worktree the task depends on are actually usable, and surface the blockers now instead of discovering them half way through.
---

# Wirework Preflight

Check that everything a task depends on is genuinely usable *before* the task starts. A readiness gate is
cheap; discovering a dead MCP or a missing credential at the point of use is expensive, because by then
the work is half-done, the context is spent, and the partial state has to be reconciled.

This is a **read-only** gate. It reports; it does not fix, install, authenticate, or mutate.

## When to use
- Before dispatching or beginning a task with a long runtime, a large context cost, or an external dependency.
- Before a run that needs a credential, a specific MCP, or a specific model lane.
- After any change to lane configuration, plugin wiring, or credentials — where the question is
  "did that actually take effect?"

## The rule this gate exists to enforce
Hard Rule 9: **capability is proven by a live probe, never by a config file.** Declared, delivered, and
actual are three different things and only *actual* counts. A preflight that reads configuration and
reports "ready" has confirmed nothing — it has re-read the same claim in a new location. Agreement
between two documents that share an origin is not corroboration.

Every check below is therefore a *call*, not a *lookup*.

## Steps
1. **Enumerate the dependencies from the task, not from habit.** List the MCPs, credentials, model lane,
   tools, and working tree the task will actually touch. A generic checklist passes while the one thing
   this task needed is missing.
2. **Probe each MCP with a real bounded call.** Enumerate the live tool list, then make one cheap real
   call against the server. A successful handshake is **not** functional liveness: a server can list
   tools and fail every one of them, and an empty environment value can shadow inherited auth so the
   connection succeeds while the operation is unauthorized. Record the literal command and its literal
   result.
3. **Check credentials by name, never by value.** Confirm the required names are present in the operator
   secrets convention (`~/.config/shell/secrets.zsh`). Never read, echo, log, or carry a value. Presence
   in the operator's file does **not** mean the value reaches the process that needs it — board workers do
   not inherit the operator's ambient environment — so where the credential is load-bearing, prove it with
   a bounded authenticated call from the runtime that will use it. See `secrets-provisioning` for the
   full inventory-and-pause procedure.
4. **Confirm the model lane is reachable and past its startup gate.** CLIs boot onto interactive gates
   (login prompts, upgrade nags, auth flows) that silently swallow the first input. A lane that has not
   been observed to answer is unproven, not ready.
5. **Check the working tree.** Confirm the tree is the one the task should write to and that its state is
   what you expect — uncommitted work from another task is a collision, not a curiosity. Worker fixes only
   reach a board worktree once **committed**; an uncommitted change to a brief or to repo code is inert
   from the worktree's point of view.
6. **Report a single verdict plus a blocker list.** Ready only when every check passed on a real call.
   Each blocker names the dependency, the literal probe, its literal result, and who can clear it.
7. **Never let the gate itself become the failure.** A probe that errors is a recorded blocker, not a
   crash and not a reason to abandon the task. If the task can proceed usefully without the missing
   dependency, say so in the same report — "not ready" and "cannot start" are different findings.

## Anti-patterns
- **Config-as-proof** — reading a JSON/TSV/YAML file and reporting the capability as present. Measured
  failure: three configuration sources agreed a lane had no shell; the probe found a shell and 42 working
  tools.
- **Handshake-as-liveness** — treating a successful `tools/list` as proof the tools work.
- **Credential-value handling** — reading or logging a secret's value to prove it is set. The name is
  sufficient and the value is a liability.
- **Generic checklist** — probing a standard set of dependencies rather than the ones this task needs.
- **Fix-during-preflight** — installing, authenticating, or repairing mid-gate. That is a separate,
  approved action; a read-only gate that mutates is no longer trustworthy as a gate.

## Acceptance
- Every dependency checked was checked with a real call, and the literal command and result are recorded.
- Credentials were verified by name only; no value was read, logged, or carried.
- Any capability reported ready is backed by an observed success, never by a configuration file.
- Blockers name the dependency, the evidence, and the party who can clear them.
- The gate performed no installs, no authentication, and no writes.
