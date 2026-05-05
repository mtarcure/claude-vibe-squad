# Capability Manifest: chrono-dispatch

Status: draft, required core runtime
Owner: Chrono / sysmgmt namespace
Canonical current surface: `bin/send-task.sh`, `scripts/send-task.sh`, `shared/dispatch-toolkit.sh`, `_state/active-tasks.json`
Old plugin source: no standalone old plugin found; old roles referenced `chrono-dispatch` peer/specialist invocation.

## Role Contract

`chrono-dispatch` owns task handoff, active-task registry, inbox/outbox naming, conflict checks, response closure, watcher reconciliation, and dispatch logs.

## Preserved Current Behavior

- Chrono is the user-facing interface.
- Real dispatch goes through `bin/send-task.sh`.
- Compatibility wrapper stays at `scripts/send-task.sh`.
- Active task truth lives in `_state/active-tasks.json`.
- Completed responses close via watcher, preflight sweep, or manual close.

## Old Plugin Capabilities To Preserve

Old role prompts expected dispatch run/parallel semantics. Preserve peer/specialist invocation semantics in the markdown-first mailbox model and future MCP/tool wrappers.

## Required Tools

- Dispatch command.
- Active registry update/close.
- Write-scope conflict check.
- Inbox/outbox file naming.
- Dispatch log append.
- Sweep/reconcile path.

## Optional Tools

- Native MCP dispatch server.
- Parallel fan-out coordinator.

## MCPs

- `chrono-kg` for dispatch findings.
- `chrono-catalog` for role availability.
- Optional future dispatch MCP.

## Skills

- `dispatch-vs-inline`
- `scope-decomposition`
- `stall-detection`

## Adaptive Operating Mode

Snapshot before dispatch, reconcile completed responses, check conflicts, write deterministic inbox file, update registry, append log, and close completed work reliably.

## Output Contract

- `task_id`
- `lead`
- `inbox_path`
- `registry_updated`
- `conflicts`
- `snapshot`
- `close_status`

## KG And Memory Behavior

- Dispatch logs are runtime state, local by default.
- Durable lessons flow through KG/memory after review.

## Safety Boundaries

- No dispatch that hides conflicts.
- No live truth from stale handoffs.
- No deletion of active registry entries without response/proof.

## Live Dispatch Proof

Temp-vault and live dispatch tests must prove inbox naming, registry entry, response closure, and Chrono summary.

## Public/Private Disposition

Public: scripts, schemas, sample state. Private: live inbox/outbox/task contents.

## Cleanup Disposition

Do not consolidate dispatch scripts until caller search and smoke tests prove compatibility wrapper and low-level command still work.
