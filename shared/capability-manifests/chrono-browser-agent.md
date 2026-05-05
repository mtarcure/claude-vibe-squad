# Capability Manifest: chrono-browser-agent

Status: draft, optional/private-enhanced runtime
Owner: sysmgmt namespace with Security/Coding/Content
Canonical current surface: `shared/lifecycle.md`, `bin/browser-keep-alive.sh`, `scripts/python/browser_keep_alive.py`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-_shared-chrono-browser-agent/0.1.0/`

## Role Contract

`chrono-browser-agent` owns shared browser session behavior: CDP attach, tab/session coordination, snapshots, tab locks, and keep-alive for authorized browser workflows.

## Preserved Current Behavior

- Uses operator's running Chrome/CDP session when session state is needed.
- Avoids spawning fresh browsers for sensitive logged-in workflows.
- Keeps browser/session artifacts local/private.

## Old Plugin Capabilities To Preserve

Old wrapper surface:

- `browser_agent`
- `session`
- `snapshot`
- `tab_lock`

## Required Tools

- CDP readiness check when browser mode enabled.
- Session path/private boundary.
- Snapshot/log path.
- Tab locking or coordination policy.

## Optional Tools

- Browser-use/computer-use integration.
- Screenshot/video capture.

## MCPs

- Optional browser-agent MCP.
- `chrono-kg` for incidents.
- `chrono-catalog` for tool status.

## Skills

- `browser-session-health`
- `rate-limit-respect`
- `tos-compliance-check`

## Adaptive Operating Mode

Check authorization and CDP readiness, attach to existing session, coordinate tabs, snapshot evidence, avoid credential leakage, and stop on ToS/auth ambiguity.

## Output Contract

- `cdp_status`
- `session_path`
- `snapshot_path`
- `tab_lock_status`
- `approval_required`

## KG And Memory Behavior

- Record only sanitized browser findings.
- Do not store cookies/tokens/session dumps in repo.

## Safety Boundaries

- No credential/session artifact commits.
- No ToS-restricted automation without approval.
- No fresh browser for lifecycle-restricted flows.

## Live Dispatch Proof

Browser-enabled smoke tests must prove CDP readiness or structured disabled/missing-tool status.

## Public/Private Disposition

Public: docs and sample config. Private: sessions, cookies, browser logs/screenshots unless sanitized.

## Cleanup Disposition

Do not delete old browser-agent assets or keep-alive scripts until browser lifecycle and private boundaries are tested.
