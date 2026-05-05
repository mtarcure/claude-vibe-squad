# Claude-Vibe-Squad Protocol — How Model-Lane Messages Work

Every dispatch message is a markdown file in the recipient compatibility namespace. Async by default. Atomic writes (temp+fsync+rename).

## Message file format

Filename: `<TYPE>-<YYYY-MM-DD>-<HHmm>-<topic-slug>.md`

Examples:
- `TASK-2026-05-02-1432-refactor-auth.md`
- `REQ-2026-05-02-1504-poc-harness.md`
- `RESP-2026-05-02-1612-poc-harness.md`

Required frontmatter (YAML):

```yaml
---
id: <unique slug, often filename-derived>
run_id: <mode run ID if applicable, or "none">
from: chrono | <model-lane>/<specialist>
to_model: gpt-codex | claude | gemini | kimi | none
specialist: <canonical specialist name, or "none" only for coordinator-only work>
source_namespace: coding | security | content | sysmgmt | research | shared | chrono
compatibility_namespace: coding | security | content | sysmgmt | research | chrono # temporary mailbox bridge
review_model: gpt-codex | claude | gemini | kimi | none
mandatory_review: true | false
mode: bounty | project | content | maintenance | incident | research | triage | none
phase: <phase name if applicable, or "none">
type: TASK | REQ | RESP | NOTIFY | NUDGE
priority: low | normal | high | urgent
status: new | claimed | in-progress | done | blocked
created: 2026-05-02T14:32:00Z
deadline: <ISO timestamp or "none">
write_scope: [list of paths the recipient is allowed to write to]
read_context: [list of files the recipient should consult]
return_artifact: <path where response should land, or "none" if no response needed>
success_criteria: [short checks that define done]
out_of_scope: [things the recipient must not do]
parallel_safe: true | false
lead_direct_allowed: true | false
operator_approved: true | false
model_override_reason: <required when to_model differs from shared/specialist-runtime-map.tsv, or "none">
parent_msg_id: <previous message id if this is a reply, or "none">
---
```

`lead_direct_allowed` defaults to `false`. Chrono plans, selects the specialist, assigns the model lane, serializes write ownership, gathers results, and speaks to the operator. Model lanes execute assigned specialist briefs. Compatibility namespaces store mailbox state while department-shaped folders are retired. A lane may only do lightweight task pickup, state updates, clarification, and response assembly unless the packet explicitly sets `lead_direct_allowed: true` with a reason in the body.

`write_scope` is exclusive for write work. If two active tasks overlap the same file or directory, the later task must be blocked, serialized, or changed to read-only review.

`shared/specialist-runtime-map.tsv` is authoritative for `specialist -> to_model`. Folder location and compatibility namespace do not determine model choice. Reviewers are read-only unless Chrono serializes a later write pass.

## Message types

| Type | Meaning | Reply expected? |
|------|---------|------------------|
| `TASK` | New work assigned by Coordinator | Yes (RESP) |
| `REQ` | Lane-to-lane request for help, visible to Chrono when decisions or approvals are involved | Yes (RESP) |
| `RESP` | Reply to a TASK or REQ | No |
| `NOTIFY` | FYI, no action required | No |
| `NUDGE` | "Hey, please check inbox" | No |

## Lifecycle

```
1. Sender writes file to shared/mailbox/<from>-to-<to>/<filename>.md (atomic)
2. Receiver's idle loop polls its inbox folders periodically (or fswatch)
3. Receiver claims oldest unblocked task → moves file from inbox/ to active/
   (or sets status: claimed in frontmatter)
4. Receiver works the task — may dispatch specialists
5. Receiver writes RESP file to outbox or to sender's inbox
6. Receiver moves original file from active/ to archive/ with status: done
```

## Async = sender doesn't block

After writing a REQ, the sending lane continues with non-dependent work. When the RESP arrives in the sender's inbox, the sender picks it up on its next idle cycle. NEVER spin-wait on a file appearing.

## Writing safely

```bash
# Pseudo-pattern, language-agnostic:
write_message() {
    tmp="${target}.tmp"
    cat > "$tmp"   # write content
    sync "$tmp"    # fsync
    mv "$tmp" "$target"  # atomic rename
}
```

Never `>` directly into the destination path. Power loss / SIGTERM / kill mid-write corrupts the file.

## Templates

Use `scripts/send-task.sh` for Coordinator-to-lane TASK messages — it handles atomic write, ID assignment, status logging, model-map lookup, review requirements, and compatibility namespace delivery.

For lane-to-lane REQs, write the mailbox file directly with the same frontmatter pattern and add a one-line CC summary to `chrono/inbox/` when Chrono needs visibility. Operator-facing decisions, live sends, destructive actions, public-release changes, credential changes, and scope changes must go through Chrono first.

## Body format

Below the frontmatter, free-form markdown. Suggested structure:

```markdown
# <one-line task description>

## Context
What you need to know to do this.

## Deliverable
What success looks like — what file gets produced, what answer is expected.

## Dispatch Contract
- Compatibility namespace:
- Specialist:
- To model:
- Source namespace:
- Review model:
- Write owner:
- Parallel safety:
- Direct lane work allowed:

## Constraints
- What NOT to do
- Out-of-scope items
- Things that need cross-lane coordination

## Reference
- Related files: [path1, path2]
- Related runs: runs/<id>
```
