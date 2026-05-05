---
name: maintenance
version: 1.1
primary_mode_namespace: sysmgmt
status: active
phases: 5
---

# Mode: Maintenance

For environment health, dependency upgrades, repo cleanup, routine audits, and system sweeps.

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

## Gates

- Operator approval before deletes, credential changes, cleanup actions, public release changes, force pushes, or dependency trust changes.
- Mandatory review for high-blast-radius runtime changes.
- Run `vibecoding-check` before closing.
