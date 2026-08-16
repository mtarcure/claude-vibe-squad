---
id: __TASK_ID__
from: chrono
to_model: claude
specialist: memory-curator
source_namespace: sysmgmt
compatibility_namespace: sysmgmt
review_model: gpt-codex
mandatory_review: true
review_class: standard
mode: project
result_type: normal
memory_aperture: none
type: TASK
priority: normal
status: new
write_scope: [__JOURNAL_PATH__]
read_scope: [shared/dreaming, departments/coding/outbox, departments/content/outbox, departments/research/outbox, departments/security/outbox, departments/shared/outbox, departments/sysmgmt/outbox, _state/dispatch-log.jsonl, _state/active-tasks.json, _state/cleanup-logs, _state/nightly-failures, _state/morning-briefs]
return_artifact: __JOURNAL_PATH__
parallel_safe: true
direct_lane_work_allowed: true
operator_approved: true
success_criteria: [journal written to the return_artifact path with the exact headings in the protocol, every observation cites a path or id, no repository change published outside the exact journal path]
out_of_scope: [applying any change the journal suggests, editing specialist briefs or routing tables, writing proposal files]
---

# Dream pass — __PASS__ (shadow)

Read `shared/dreaming/protocol.md` and execute it. That file is the whole brief;
this packet only tells you which pass to run and where to write.

- **Pass:** `__PASS__`
- **Journal:** `__JOURNAL_PATH__`

The protocol gives the exact headings to write. `## Notable Patterns`
and `## Verdict` are parsed by `bin/morning-brief.sh` — do not rename them.

Your write scope is the exact journal path and nothing else. If the pass turns
up something that needs doing, name it in `## Candidates` and stop there.

If an input directory does not exist on this host, record it as `0 (not present)`
and continue. That is an ordinary result, not a blocker.
