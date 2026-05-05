# Vibe Squad Protocol

Every dispatch is a markdown file. Scripts validate, route, and deliver; they do not replace markdown instructions.

## Task Packet Frontmatter

```yaml
---
id: TASK-YYYY-MM-DD-HHMM-<hash>
run_id: none
from: chrono
to_model: gpt-codex | claude | gemini | kimi
specialist: <canonical-specialist>
source_namespace: coding | security | content | sysmgmt | research | shared
compatibility_namespace: coding | security | content | sysmgmt | research
review_model: gpt-codex | claude | gemini | kimi | none
mandatory_review: true | false
mode: bounty | project | content | maintenance | incident | research | triage | outreach | none
phase: <phase or none>
type: TASK
priority: low | normal | high | urgent
status: new | claimed | in-progress | done | blocked
created: <ISO timestamp>
deadline: <ISO timestamp or none>
write_scope: []
read_context: []
return_artifact: <path>
success_criteria: []
out_of_scope: []
parallel_safe: true | false
direct_lane_work_allowed: false
operator_approved: true | false
model_override_reason: none
parent_msg_id: none
---
```

The dispatcher contains a temporary compatibility bridge for older local packets, but new markdown must use the fields above.

## Lifecycle

1. Chrono writes a task body.
2. `scripts/send-task.sh` adds frontmatter from the model map.
3. `bin/send-task.sh` validates safety and writes to `departments/<compatibility_namespace>/inbox/`.
4. Inbox watchers nudge the `to_model` window with the absolute task packet path.
5. The model lead reads the packet and named specialist markdown.
6. The model lead writes the response to the return artifact/outbox.
7. Chrono surfaces the result to the operator.

`source_namespace` selects the specialist markdown. `compatibility_namespace`
selects the mailbox folder. Shared specialists do not have a `departments/shared`
mailbox; Chrono chooses the mailbox namespace that matches the active workflow.

## Async Rule

Senders do not block on lane-to-lane work. If a response is required, track the task ID and check/surface the outbox result later.
