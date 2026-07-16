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

## Completion Contract

Lifecycle step 6 has **two** required outputs, not one. On finishing a task the model lead writes both:

1. the **`return_artifact`** named in the packet, and
2. the **outbox completion envelope** at `departments/<compatibility_namespace>/outbox/<id>-response.md`.

`bin/outbox-watcher.sh` watches for `<id>-response.md` and `scripts/python/registry_reconciler.py` reconciles the active-task registry and nudges Chrono from it. Writing only the `return_artifact` leaves the task `in-flight`: the reconciler's `work-done-no-envelope` path is a **backstop** (it flags settled-but-unenveloped work after a grace period once the lane goes idle), not the primary path. Emitting the envelope is what makes reconciliation instant and deterministic.

The lane derives `<id>` from the packet's `id` field and `<compatibility_namespace>` from the packet's own mailbox path (`departments/<X>/inbox/<id>.md` → `<X>`), which is present for every packet even when the `compatibility_namespace` frontmatter field is omitted.

Envelope schema — frontmatter, then a summary body whose first paragraph the reconciler surfaces:

```
id: <id>-response
in_response_to: <id>
from: gpt-codex | claude | gemini | kimi
to: chrono
type: RESULT
status: complete | needs_review | blocked
return_artifact: <the return_artifact path>
```

The reconciler keys on the `<id>-response.md` filename and reads `status` (canonicalizing `completed`→`complete`) plus the summary body; the other fields are provenance it tolerates. Use `needs_review` when the packet sets `mandatory_review: true`, and `blocked` if the work could not be finished. **Panel/fan-out members never write the envelope — the coordinator is the sole outbox writer for the parent task.**

## Memory Apply Citations

When recalled memory materially informs a task, cite each consumed note by its stable `mem-…` ID in the response (for example, `Memory applied: mem-a1b2c3d4e5f6`) and retain the associated `recall_id`. Close the apply loop with `record_usage(recall_id, note_id, outcome, source_task)`, using `used`, `not_useful`, or `incorrect` to distinguish memory that helped from memory that did not; never copy private note text or sensitive evidence into public packets.

## Async Rule

Senders do not block on lane-to-lane work. If a response is required, track the task ID and check/surface the outbox result later.

## Mandatory Review Behavior

`mandatory_review: true` is a contract enforced at dispatch time, not auto-firing automation. Specifically:

- **At dispatch:** `bin/send-task.sh` validates that `review_model` is set when `mandatory_review: true`, and rejects high-safety specialists (per `shared/specialist-runtime-map.tsv`) that don't carry `mandatory_review: true`.
- **Same-family review (specialist's primary lane and reviewer's lane share a model family — e.g., gpt-codex specialist with claude reviewer where the specialist already has Claude available as an in-lane tool):** the specialist is expected to run the review IN-LANE before declaring done. Most current `mandatory_review: true` packets land this way (e.g., gpt-codex/ai-engineer responses commonly include "Mandatory Claude review completed twice").
- **Cross-family review (specialist and reviewer don't share lane access — e.g., claude/architect with gpt-codex reviewer where claude has no native gpt-codex tool):** Chrono dispatches the reviewer manually after the specialist's response lands. There is no auto-fire from the watcher today; Chrono reads the response and decides whether to follow up with a reviewer dispatch.

Operators / specialists writing packets should:

1. Always pair `mandatory_review: true` with a `review_model` that the specialist's lane can actually invoke in-lane. If the lanes don't share a family, expect a follow-up dispatch.
2. Treat `mandatory_review: true` as "Chrono guarantees a reviewer will see this before operator-facing surfacing happens" — not as automation.
3. If a high-safety specialist's response lands without evidence of in-lane review, Chrono is expected to dispatch a reviewer follow-up before treating the response as final.

A future enhancement could make cross-family reviews auto-fire from `bin/outbox-watcher.sh` (detect response landing + `mandatory_review: true` + lane mismatch → auto-dispatch reviewer). Not implemented; tracked as a parked architectural item.
