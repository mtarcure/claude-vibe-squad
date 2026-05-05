# Capability Manifest: chrono-observability

Status: draft, required local runtime, public docs/sample only
Owner: sysmgmt namespace
Canonical current surface: `agentops`, `_state/audit-logs/`, `bin/where-are-we.sh`, `bin/doctor.sh`
Old plugin source: no standalone old plugin found; referenced by old harness/loop plugins as shared event surface.

## Role Contract

`chrono-observability` is the telemetry/reporting surface for loop checkpoints, dispatch volume, MCP failures, stale panes, runtime warnings, and before/after harness metrics.

## Preserved Current Behavior

- AgentOps reports quantitative runtime health.
- Loop/harness roles expect checkpoint and delta evidence.
- Doctor/status commands expose warnings instead of hiding them.

## Old Plugin Capabilities To Preserve

Old roles referenced `mcp__chrono_observability__emit_event` for loop checkpoints and harness deltas. Preserve event/report semantics even if implementation is logs/status files.

## Required Tools

- Audit log path.
- Status command path.
- Dispatch/active-task visibility.
- MCP/startup issue reporting.

## Optional Tools

- Event emitter MCP.
- Dashboard.
- Usage/cost charting.

## MCPs

- Optional `chrono-observability` if implemented.
- `chrono-kg` for incident records.
- `chrono-catalog` for status metadata.

## Skills

- `mcp-reachability-audit`
- `prompt-cache-hit-monitoring`
- `stall-detection`

## Adaptive Operating Mode

Prefer read-only telemetry, record anomalies with evidence, route fixes to owners, and never silently discard warnings.

## Output Contract

- `status_report`
- `events`
- `warnings`
- `issues`
- `owner_recommendations`

## KG And Memory Behavior

- Record recurring anomalies.
- Keep live logs local/private.

## Safety Boundaries

- No secret/env dumping.
- No unbounded logs in public repo.
- No automatic kill/restart as observability action.

## Live Dispatch Proof

`where-are-we`, doctor, and AgentOps live proof must show runtime state and warnings; loop proof must include checkpoint evidence.

## Public/Private Disposition

Public: schemas, sanitized samples. Private: live logs, transcripts, usage data.

## Cleanup Disposition

Do not delete audit/status logs or scripts until product hygiene defines retention/quarantine and replacement observability exists.
