---
name: session-rotation
status: authored
description: Use when a long session is approaching its context ceiling and work will continue past it — bring live state up to date so the next session can resume from the repo rather than from a summary of a conversation it cannot see.
---

# Session Rotation

Hand a long-running session over to its successor without losing the state that only exists in the
current context. The failure this prevents is specific: a session runs to its ceiling, everything
in-flight is known only to the conversation, and the next session starts from a repo that describes a
world several hours stale.

Rotation is a **state-synchronisation** step, not a filing step. The goal is that the next session,
reading only live state, reaches the same understanding — not that a document was produced.

## Where the state goes — read this before writing anything
This repo deliberately **retired the standalone handoff-document pattern**. Do not write to
`docs/handoffs/`; it is historical, the shutdown path explicitly instructs against it, and a new file
there is a document nobody reads. Live state is:

1. `_state/chrono/resume.md` — the bounded resume capsule the controller reads **first**, regenerated
   from the decision-authority record.
2. The live registry **partition** — `registry_view()` in `scripts/python/chrono_state/registry.py`,
   which reads `_state/active-tasks.json`. This is what is genuinely in flight. Query it, do not read
   the file: see the settled winner below.
3. `departments/*/current.md` — live mailbox state per namespace.
4. Response files, but only for task IDs still pending or in-flight.
5. `_state/chrono-queue.md`, if present — response-completion records from the watcher.

**`chrono/current.md` is an ARCHIVE, not the resume source.** `chrono/CLAUDE.md` says so directly and
forbids bulk-reading it; open it only for a specific prior turn or task the operator names.

## The winning path for liveness — settled

**Winner: `chrono_state.registry.registry_view()`.** Anything that needs to know what is live —
this skill, the resume capsule, the operator status pane — asks the partition. Nothing reads a task
file to decide liveness, because *neither file on disk encodes it*:

| path | what it actually is | may it answer "what is live?" |
|---|---|---|
| `_state/active-tasks.json` | the registry the board feeds, retaining **every** terminal record (1,668 terminal of 1,737 total, measured 2026-08-13) | only **through** `registry_view()`, never by reading it |
| `_state/tasks/active.json` | a frozen snapshot from the 2026-07-24 one-shot migration, fed by nothing since (`registry.py:18-20`) | **no** — it held 1 record while the board held 14 |

The live/terminal/unclassified distinction is *computed*, and `registry_view()` is the only place it
is computed. That is why there is no correct precedence between the two files: preferring one over
the other only chooses which way to be wrong.

`_state/tasks/active.json` stays on disk because deleting it is a held category requiring an
operator decision, not a side effect of this rule. Do not read it. Its module-level lifecycle
owners, `write_active` and `archive_terminal`, have no production callers today — tests only
(verified 2026-08-13). Its one remaining live consumer is `load_active()` in
`plugins/chrono-vault/skills/compact-now/SKILL.md`, which is a further instance of this same
defect and is flagged for repair, not a counter-example to this rule.

The direct query, when you need it outside the capsule:

```bash
python3 -c "import sys;sys.path.insert(0,'scripts/python')
from chrono_state.registry import registry_view
v=registry_view();print(len(v['live']),'live',len(v['deferred']),'deferred',v['unclassified'] or 'none')"
```

Always read `v['unclassified']`. A status classified nowhere is otherwise invisible: it is neither
live nor terminal, so those tasks vanish from every count with no error at all.

> **Previously flagged as unresolved; now settled.** This section used to record a contradiction
> between root `CLAUDE.md` and `chrono/CLAUDE.md` over the resume ordering and decline to pick a
> side. Root `CLAUDE.md` § Session Resume no longer carries the disputed
> `_state/active-tasks.json` → `chrono/current.md` ordering — verified 2026-08-13 — so the two files
> agree today and `chrono/CLAUDE.md` § Start Of Session remains the operational authority. The
> settlement above extends that agreement to the one question neither file answered: *which path
> encodes liveness.* Background, including the two cross-family REJECTs the same root cause cost in
> `resume.py`, is in `chrono/resume-contract-decision-record.md`.

Durable cross-session learning goes to `chrono-vault` via `record`, not into a file. Old plans, specs,
and prior reports are historical unless current state points at them.

Writing the rotation into these files rather than into a new document is the whole adaptation: the next
session already reads them on resume, so state placed there is *found*, and state placed anywhere else is
merely *stored*.

## Steps
1. **Rotate on a threshold, not on exhaustion.** Around four-fifths of the context ceiling, start the
   handover. Waiting until the window is nearly full leaves no room to *perform* the handover — which is
   itself context-expensive — and that is how sessions end mid-thought.
2. **Reconcile what is actually in flight before writing anything.** Sweep for work that has finished but
   has not been settled. **A stopped lane does not by itself prove completion**, and a registry entry does
   not clear merely because a process exited — so never infer state from a missing process or a file
   mtime. (The board *does* validate, publish and settle landed responses automatically; the gap is
   between "the lane stopped" and "a response landed and settled", not an absence of automation.) An
   in-flight list that is wrong is worse than none, because the next session will trust it.
3. **Never rotate away from a lane that is still running.** A successor session inherits neither the
   watchers nor the notifications of the current one. Either settle the in-flight work first, or record
   precisely what is running, where its output will land, and how to check it.
4. **Update live state in place.** Bring `chrono/current.md` and each affected `departments/*/current.md`
   to the truth as of now. Edit them to be *currently accurate* rather than appending a log entry —
   a current-state file that has become an append-only history no longer answers the question it exists
   to answer.
5. **Record what the repo cannot re-derive.** Decisions taken and their reasons, approaches ruled out and
   why, and anything an operator said that changes how the work should proceed. Skip what the repo already
   records: code structure, git history, and file contents do not need restating. If the next session can
   read it, do not copy it.
6. **Capture durable lessons to `chrono-vault`.** Anything true beyond this task — a gotcha, a tool
   behaviour, a technique — belongs in memory rather than in a state file. Best-effort: a memory error is
   noted in one line and never blocks the rotation.
7. **Write shared state atomically.** Temp file, sync, rename (Hard Rule 7). A half-written state file
   read by the next session is worse than a stale one, because it looks current.
8. **Name the next action explicitly.** End with the single thing the successor should do first. A
   handover that describes a situation without naming an action makes the next session re-derive the
   decision that was already made.

## Failure modes
- **Handoff-document reflex** — writing a new file under `docs/handoffs/` because that is what the pattern
  used to be. Nobody reads it; the resume path does not open it.
- **Rotating too late** — no context left to perform the handover.
- **Stale in-flight list** — carrying forward work that already finished, or dropping work that has not.
- **Reading a task file for liveness** — asking `_state/tasks/active.json` or `_state/active-tasks.json`
  what is in flight instead of asking `registry_view()`. Neither file encodes it, so the answer is
  confidently wrong rather than missing, and it *looks* like a clean read. This has now cost three
  call sites (`resume.py`, `bin/chrono-status-segment.sh`, `compact-now`).
- **Transcript restatement** — summarising the conversation instead of updating state. The next session
  needs the current world, not this session's narrative.
- **Duplicating the repo** — restating code and structure the successor can simply read.

## Acceptance
- Live state files are accurate as of the rotation; nothing was written to the retired handoff path.
- In-flight work was reconciled first, and anything still running is recorded with where its result lands.
- Non-re-derivable context — decisions, rejected approaches, operator direction — is captured; re-derivable
  content is not.
- Durable lessons went to `chrono-vault`, and any memory failure was noted without blocking the rotation.
- Shared state was written atomically.
- The successor's first action is stated explicitly.
