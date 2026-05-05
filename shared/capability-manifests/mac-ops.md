# Capability Manifest: mac-ops

Status: draft, current-system capability
Owner: sysmgmt namespace
Canonical current specialist: `departments/sysmgmt/specialists/mac-ops.md`
Old plugin source: none direct in old `claude-chrono`; related surfaces are launch/runtime scripts and shared common tools.

## Role Contract

`mac-ops` owns local macOS machine health and automation that Vibe Squad depends on: Homebrew/package status, disk/memory/network health, tmux/launchd/fswatch, Chrome/CDP prerequisites, Hammerspoon/Shortcuts/osascript automation, and local process/runtime checks.

## Preserved Current Behavior

- Performs routine read-only inventory and machine health checks.
- Surfaces permission-touching changes for approval.
- Coordinates with Coding for non-trivial scripts/configs.
- Coordinates with Security for suspicious processes/listeners.
- Owns tmux/launchd drift investigation, including scrollback/history config problems.

## Old Plugin Capabilities To Preserve

No direct old plugin existed for `mac-ops`. Preserve current-system capability and runtime requirements:

- launch/stop/restart prerequisites
- tmux pane/window/session health
- fswatch/watchers
- launchd agents and logs
- Chrome CDP/browser session readiness
- disk/cache/log growth checks

## Required Tools

- `tmux` inspection path.
- `launchctl` and LaunchAgent log inspection path.
- `fswatch` availability/status path.
- Disk/process/network read-only audit commands.
- Homebrew/package manager status commands.
- Chrome/CDP readiness check when browser/bounty mode is enabled.

## Optional Tools

- Hammerspoon.
- Shortcuts.
- osascript/JXA automation.
- htop/iftop/iotop.
- package update checkers.

## MCPs

- `chrono-kg`: record machine/runtime incidents and recurring fixes.
- `chrono-catalog`: discover tool availability and verification status.
- `chrono-vault` / `chrono-obsidian`: runbook and report references.
- `sequential-thinking`: root-cause analysis for launchd/tmux/runtime drift.

## Skills

Current or required skills:

- `mac-runtime-inventory`
- `launchd-drift-audit`
- `tmux-health-check`
- `browser-session-health`
- `reversible-change-protocol`
- `mcp-reachability-audit`

## Adaptive Operating Mode

Start read-only, inventory current state, compare against expected launch/runtime config, identify drift and owner, propose exact fix commands or config diffs, escalate permission/security changes, record the incident and runbook, and verify after approved changes.

## Output Contract

Expected return shape:

- `inventory_path`
- `runtime_status`
- `tmux_status`
- `launchd_status`
- `watcher_status`
- `browser_cdp_status`
- `issues`
- `proposed_fixes`
- `approval_required`
- `kg_finding_id`

## KG And Memory Behavior

- Record runtime incidents, fixes, and recurrence patterns.
- Do not store secrets, raw env, browser cookies, or private session artifacts.
- Route repeated launch/tmux drift to `harness-optimizer` or product launch tasks.

## Safety Boundaries

- No keychain modification.
- No installs/updates without approval.
- No secret path deletion.
- No hard-kill of squad/runtime processes unless requested or covered by `squad stop`.
- No suspicious process cleanup before Security review.

## Live Dispatch Proof

Required proof path before marking complete:

1. Chrono dispatches local machine/runtime check to sysmgmt namespace.
2. sysmgmt namespace dispatches `mac-ops`.
3. Specialist runs read-only tmux/launchd/fswatch/disk checks or reports missing tools.
4. Specialist identifies any drift and proposes fixes without applying destructive changes.
5. Outbox includes exact evidence and approval gates.
6. Active registry closes through watcher, sweep, or manual close.

## Public/Private Disposition

Public repo may ship role prompt, manifest, setup checks, and runbooks. Local machine logs, browser sessions, LaunchAgent private paths, and operator-specific automation stay local.

## Cleanup Disposition

Do not delete launch/runtime/mac automation scripts until `mac-ops` ownership, setup checks, and live read-only proof cover the behavior.
