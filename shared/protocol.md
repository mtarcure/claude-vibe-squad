# Claude-Vibe-Squad Protocol — How Cross-Lead Messages Work

Every cross-Lead message is a markdown file in `shared/mailbox/<from>-to-<to>/`. Async by default. Atomic writes (temp+fsync+rename).

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
from_lead: coding | security | content | sysmgmt | research | chrono
to_lead: coding | security | content | sysmgmt | research | chrono
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
operator_approved: true | false
parent_msg_id: <previous message id if this is a reply, or "none">
---
```

## Message types

| Type | Meaning | Reply expected? |
|------|---------|------------------|
| `TASK` | New work assigned by Coordinator | Yes (RESP) |
| `REQ` | Lead-to-Lead request for help | Yes (RESP) |
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

After writing a REQ, the sending Lead continues with non-dependent work. When the RESP arrives in the sender's inbox, the sender picks it up on its next idle cycle. NEVER spin-wait on a file appearing.

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

Use `scripts/send-task.sh` for Coordinator-to-Lead TASK messages — it handles atomic write, ID assignment, status logging.

Use `scripts/send-req.sh` for Lead-to-Lead REQs — same pattern.

## Body format

Below the frontmatter, free-form markdown. Suggested structure:

```markdown
# <one-line task description>

## Context
What you need to know to do this.

## Deliverable
What success looks like — what file gets produced, what answer is expected.

## Constraints
- What NOT to do
- Out-of-scope items
- Things that need cross-Lead coordination

## Reference
- Related files: [path1, path2]
- Related runs: runs/<id>
```
