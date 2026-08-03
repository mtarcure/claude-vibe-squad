---
id: TASK-2026-08-04-1100-wsgneg
to_model: claude
specialist: harness-optimizer
source_namespace: sysmgmt
mode: project
result_type: normal
run_id: wsguard-repro
parallel_safe: true
direct_lane_work_allowed: true
write_scope: [departments/shared/outbox/TASK-2026-08-04-1100-wsgneg-response.md, _state/bounty/rigs/newthing/]
return_artifact: departments/shared/outbox/TASK-2026-08-04-1100-wsgneg-response.md
---

# NEGATIVE CONTROL — a guard that does not fire on this input is broken

`write_scope` names `_state/bounty/rigs/newthing/`, which `.gitignore` matches via
`_state/**`. Only `return_artifact` is promoted out of the attempt worktree, so this
rig is destroyed at cleanup. The guard MUST warn on this packet.
