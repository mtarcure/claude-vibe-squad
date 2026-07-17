---
name: maintenance
version: 1.1
primary_mode_namespace: sysmgmt
status: active
phases: 5
---

# Mode: Maintenance

For environment health, dependency upgrades, repo cleanup, routine audits, and system sweeps.

## Capabilities

Part of the **Operations** nav-family (incident · maintenance · triage) — a display grouping over three canonical modes, **not** a 7th `ops` mode; maintenance keeps `mode: maintenance`. `capability_state` is **derived** and machine-checked by `bin/validate-capabilities.sh` (not hand-set). Cards live in `shared/capabilities/maintenance/`.

| Capability | State | When |
|---|---|---|
| [Environment / repo health](../capabilities/maintenance/environment-repo-health.md) | `live` | repo/env hygiene, cleanup, upgrades, refactors |
| [Dependency / release integrity](../capabilities/maintenance/dependency-release-integrity.md) | `live` | dep trust / supply-chain / advisory — signing/attestation is `needs_tool` |
| [Memory / vault hygiene](../capabilities/maintenance/memory-vault-hygiene.md) | `live` | durable-knowledge curation — legacy `chrono-kg` retired |
| [Harness audit / compatibility](../capabilities/maintenance/harness-audit-compatibility.md) | `live` | prompt/tool/script drift + MCP reachability (audit-only) |
| [Personal operations](../capabilities/maintenance/personal-operations.md) | `live` | routines / reminders / draft — send + calendar-write are `needs_tool` |

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 1 | Inventory | `mac-ops`, `agentops`, `finance-analyst` when spend/quota-related |
| 2 | Risk grouping | `skeptic`, `harness-optimizer`, `privacy-steward` |
| 3 | Plan and approval | `planner` |
| 4 | Execute approved batch | relevant implementation or ops specialist |
| 5 | Regression and changelog | `test-engineer`, `technical-writer`, `vibecoding-check` |

## Dispatch Notes

- Cleanup proposals are not cleanup approval.
- One writer owns each path during execution.
- Keep private/runtime artifacts out of public release.

## Memory Curation Sweep

- **Owner:** `memory-curator` (link-integrity support: `knowledge-librarian`). Chrono schedules it; the operator approves the housekeeping dispatch. NOT run inline by Chrono.
- **Cadence:** one general pass on the first operator session past a 30-day mark, reviewing at most the 100 oldest `candidate` notes that are ≥30 days old. Not per-task.
- **Actions per candidate (evidence-based, via `record_usage` signal):** promote to `verified` only when reusable, current, source-backed, and review provenance exists; `invalidated` when contradicted; `superseded` (linked) when duplicate; `archived` when task-local/stale/non-reusable. **Never delete; never promote or invalidate from age, confidence, or usage-count alone.**
- **Capacity gate:** each pass reports total note count, candidate count, and vault/index bytes. At **10,000 notes or 250 MiB**, stop and surface to the operator before any capture-pause or physical-retention change — never silent purge, never silent disable.
- Note that archived/invalidated/superseded notes leave the default recall tier, which bounds both recall noise and the active set.

## Gates

- Operator approval before deletes, credential changes, cleanup actions, public release changes, force pushes, or dependency trust changes.
- Mandatory review for high-blast-radius runtime changes.
- Run `vibecoding-check` before closing.
