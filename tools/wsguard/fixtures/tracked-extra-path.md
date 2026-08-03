---
id: TASK-2026-08-04-1102-wsgtrk
to_model: claude
specialist: harness-optimizer
source_namespace: sysmgmt
mode: project
result_type: normal
run_id: wsguard-repro
parallel_safe: true
direct_lane_work_allowed: true
write_scope: [departments/shared/outbox/TASK-2026-08-04-1102-wsgtrk-response.md, shared/modes/bounty.md]
return_artifact: departments/shared/outbox/TASK-2026-08-04-1102-wsgtrk-response.md
---

# DISCRIMINATION CONTROL — unpromoted but NOT gitignored

`write_scope` names `shared/modes/bounty.md`, a tracked path that git does not ignore.
It is still not promoted (only `return_artifact` is), so the guard should say so, but it
must NOT claim the omission is silent. This separates the two halves of the message.
