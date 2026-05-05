# Capability Manifest: agentops

Status: draft, current-system capability
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/agentops.md`
Old plugin source: none direct in old `claude-chrono`; related surfaces are shared observability, catalog, KG, and harness plugins.

## Role Contract

`agentops` owns operational observability for Vibe Squad itself: MCP health, dispatch volume, stuck panes, runaway signatures, token/cache usage, CLI subscription health, cost/rate-limit anomalies, and local runtime telemetry. It detects system bleeding early and routes repair to the right owner.

## Preserved Current Behavior

- Watches MCP reachability and cross-pane startup failures.
- Tracks dispatch volume by Lead and detects spikes.
- Tracks prompt-cache/token/subscription usage where CLI surfaces allow it.
- Reports quantitative anomalies instead of vague status.
- Coordinates with `harness-optimizer`, `loop-operator`, `mac-ops`, and `finance-analyst`.

## Old Plugin Capabilities To Preserve

No direct old plugin existed for `agentops`. Preserve current-system capability by mapping it to:

- old harness observability expectations
- old loop checkpoint/stall telemetry expectations
- shared KG/catalog health expectations
- current `bin/mcp-audit.sh`, `bin/doctor.sh`, `bin/where-are-we.sh`, and nightly/weekly routines

## Required Tools

- MCP audit/status path.
- Tmux pane/session inspection.
- Process and file-size audit path.
- Dispatch log and active registry inspection.
- Usage/cost/token summary path when available without secret leakage.

## Optional Tools

- CLI-specific usage export parsers.
- Observability event emitter.
- Dashboard/report generator.

## MCPs

- `chrono-kg`: record incidents, anomalies, and recurring operational findings.
- `chrono-catalog`: tool/MCP availability and verification state.
- `chrono-vault` / `chrono-obsidian`: report references.
- `sequential-thinking`: root-cause analysis for multi-surface failures.

## Skills

Current or required skills:

- `kg-vault-health-check`
- `harness-baseline-audit`
- `prompt-cache-hit-monitoring`
- `mcp-reachability-audit`
- `stall-detection`
- `reversible-change-protocol`

## Adaptive Operating Mode

Collect quantitative runtime state, compare against baselines, identify anomalies, classify owner and severity, write a report with evidence, open/dispatch repair work instead of silently fixing high-blast-radius config, and record recurring incidents to KG.

## Output Contract

Expected return shape:

- `agentops_report_path`
- `mcp_status`
- `dispatch_volume`
- `stale_panes`
- `usage_summary`
- `anomalies`
- `owner_recommendations`
- `kg_finding_id`
- `awaiting_operator_approval`

## KG And Memory Behavior

- Record operational incidents and resolutions.
- Promote recurring patterns to `harness-optimizer` or `memory-curator`.
- Never record raw secrets, raw env dumps, full financial account data, or private customer content.

## Safety Boundaries

- No automatic MCP config rewrites without diagnosis and approval.
- No secret/env dumping.
- No hard-killing processes unless explicitly approved or already covered by stop command policy.
- No financial transaction authority.
- No silent deletion of logs or runtime artifacts; quarantine/disposition first.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches a runtime health task to sysmgmt namespace.
2. sysmgmt namespace dispatches `agentops`.
3. Specialist runs read-only MCP/tmux/registry checks or structured missing-tool reports.
4. Outbox includes quantitative state, anomalies, and owner recommendations.
5. Any cleanup/fix is proposed, not silently applied.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship manifest, role prompt, schemas, audit scripts, and sanitized sample reports. Private usage data, local logs, tokens, transcripts, and subscription details stay local.

## Cleanup Disposition

Do not remove AgentOps-related scripts or docs until caller search confirms ownership, reports are covered by the manifest, and live read-only proof passes.
