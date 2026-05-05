# File Disposition Manifest

Status: active
Started: 2026-05-04
Owner: Chrono / sysmgmt namespace

This manifest is the approval layer for cleanup. Nothing listed here should be deleted, moved, or untracked until it has a disposition and any needed replacement location.

## Rules

- Preserve features before cleanup.
- Runtime truth stays local and ignored.
- Public v1 ships product files, examples, docs, and curated manifests only.
- Handoffs are archival, not runtime truth.
- Private operator details, auth state, live tasks, logs, completed bounty/client artifacts, and raw mailbox responses do not ship.

## Current Hygiene Gate

Command:

```bash
bash bin/product-hygiene.sh
```

Latest result:

- Runtime paths: 20
- Mailbox task files: 141
- Draft/spec/handoff paths: 15
- Tracked public-release blockers: 0

## Tracked Public-Release Blockers

| Path | Current role | Disposition | Reason |
|---|---|---|---|
| local finance daily report | Local token/spend runtime report | Do not ship; replace with example if needed | Contains local operational usage summary, not product docs. |
| historical handoff pair | Historical local handoffs | Do not ship as public v1 | Contains local session state and operator-specific details; superseded by current docs. |
| old implementation plan | Completed implementation plan | Supersede with current production-readiness plan | Public v1 should not present old implementation scaffolding as active release planning. |
| old implementation spec | Completed implementation spec | Supersede with current product docs | Preserve lessons only in current docs where still valid. |

## Local Runtime Debris

The following classes are local-only by default:

- `_state/active-tasks.json`
- `_state/audit-logs/`
- `_state/cleanup-logs/`
- `_state/dispatch-log.jsonl`
- `_state/doctor-logs/`
- `_state/dream-logs/`
- `_state/finance-daily/`
- `_state/morning-briefs/`
- `_state/tmux-logs/`
- `_state/weekly-briefs/`
- `departments/*/inbox/*.md`
- `departments/*/active/*.md`
- `departments/*/outbox/*.md`
- `departments/*/archive/*.md`
- `departments/coding/_state/`
- `departments/coding/tmp-write-check/`

## Draft And Handoff Material

Drafts, specs, and handoffs require curation before public release:

- Keep as product docs only when they describe the current v1 product.
- Move reusable examples to `examples/`.
- Keep private/local history out of public v1.
- Do not treat `docs/handoffs/` as live truth.

## Script Classification

Scripts stay only when they perform mechanical work that markdown cannot do. Operator-facing behavior should be reachable through `squad` where practical.

| Class | Paths |
|---|---|
| Public command | `bin/squad`, `bin/launch-squad.sh`, `bin/squad-stop.sh`, `bin/where-are-we.sh`, `bin/doctor.sh`, `bin/send-task.sh` |
| Runtime rail | `bin/inbox-watcher.sh`, `bin/outbox-watcher.sh`, `bin/sweep-active.sh`, `bin/spawn-specialist.sh`, `bin/sidebar.sh`, `bin/sidebar-off.sh`, `bin/squad-monitor.sh`, `bin/watch-lead.sh`, `bin/lead-status.sh`, `bin/connect.sh`, `scripts/send-task.sh`, `shared/dispatch-toolkit.sh` |
| Validator/audit | `bin/validate-specialists.sh`, `bin/product-hygiene.sh`, `bin/memory-audit.sh`, `bin/mcp-audit.sh`, `bin/verify.sh`, `bin/vibecoding-check.sh`, `bin/dispatch-toolkit-verify.sh`, `scripts/python/verify.py`, `scripts/python/vibecoding_check.py`, `scripts/python/mcp_probe.py` |
| Optional routine | `bin/run-nightly.sh`, `bin/run-weekly.sh`, `bin/install-routines.sh`, `bin/morning-brief.sh`, `bin/feed-sweep.sh`, `bin/content-processing.sh`, `bin/dream-light.sh`, `bin/brain-cleanup.sh`, `bin/browser-keep-alive.sh`, `bin/system-cleanup.sh`, `bin/finance-daily.sh`, `bin/graduation-scan.sh`, `bin/aggregate-errors.sh`, `scripts/python/run_weekly.py`, `scripts/python/feed_sweep.py`, `scripts/python/content_processing.py`, `scripts/python/dream_light.py`, `scripts/python/brain_cleanup.py`, `scripts/python/browser_keep_alive.py` |
| Migration/helper | `scripts/bootstrap-mcps.sh`, `bin/patch-codex-mcp-trust.py`, `bin/upgrade-specialists.py`, `bin/dashboard.sh`, `bin/squad-health.sh` |
| Delete/quarantine | none until references and replacement command surfaces are verified |

## Next Cleanup Gate

Public-export state separation passes when:

- `bash bin/product-hygiene.sh --public-export` exits 0.
- `bash bin/product-hygiene.sh` may still report local runtime/mailbox debris for daily-driver cleanup.
- Local runtime/mailbox debris has either been safely cleaned after operator approval or remains ignored and outside the public export.
- Any replacement examples/docs exist before old local files are removed from public tracking.
