---
name: take-over-resume
status: authored
description: Use when picking work back up after a human has edited the tree directly — a paused task, an operator hand-fix, or a worktree touched between runs. Establishes what actually changed before continuing, so the resumed work builds on the current tree rather than a remembered one.
---

# Take-Over Resume

Resume work on a tree that a human may have changed while you were not looking. The failure mode is
narrow and expensive: work resumes against a remembered state, the operator's manual fix is silently
reverted or duplicated, and the conflict surfaces much later as a mysterious regression.

The controlling assumption is that **the tree is the truth and your memory of it is a hypothesis.**

## When to use
- Resuming a task that was paused for manual intervention.
- Returning to a worktree after an operator hand-fix.
- Any resume where time has passed and the tree was reachable by someone else.
- A task that failed, was repaired by hand, and is being restarted.

## Pausing cleanly
When work is being suspended for someone to intervene:

1. **Stop at a coherent point.** Suspend between steps, not mid-write. A tree caught half way through a
   multi-file edit is one nobody can safely reason about.
2. **Record the resume anchor** — the commit the work was built on, the tree involved, and the step that
   was about to run. This anchor is what makes the resume diff meaningful; without it, the diff has no
   baseline and the whole procedure degrades to guessing.
3. **State what is safe to touch**, so intervention does not collide with in-flight state.
4. **Never remove a worktree with work still in flight.** Removal kills the running work. Re-read
   in-flight status immediately before any cleanup, not from a status read earlier in the session.

## Resuming
1. **Diff against the anchor before reading anything else.** List the changed files, then read the actual
   diff. This is the first action on resume — not a check performed after planning, because a plan built
   on the remembered tree is already wrong.

   **`git diff <anchor>` does not show untracked files, and a new file is the most common human edit.**
   A file the human created is invisible to the diff alone, so the procedure would miss precisely the
   change that triggered it. Enumerate untracked paths separately and read them in full:

   ```
   git diff --stat <anchor>            # tracked changes
   git status --porcelain              # '??' lines are untracked and absent from the diff above
   ```

   Read every `??` path's contents, not just its name. Treat a `.gitignore`d path as intentional
   scratch unless it is obviously a deliverable.
2. **Read the changes as intent.** A human edit is a message: it says the previous approach was wrong,
   incomplete, or heading somewhere unwanted. Work out what the edit is telling you before deciding how
   to proceed.
3. **Reconcile the plan against reality.** Steps the human already completed are done — do not redo them.
   Steps whose premise the edit invalidated need rework, not resumption. Say which is which.
4. **Do not revert a manual change to restore your plan.** If a human edit conflicts with the plan, the
   plan yields, or the conflict is surfaced for a decision. Silently reverting an operator's fix is the
   central failure this procedure exists to prevent, and it is indistinguishable from a bug when it
   surfaces later.
5. **Re-run verification from the current tree.** Prior results describe a tree that no longer exists.
   Establish a fresh baseline before attributing any failure to your own work — a failure that predates
   your changes is not yours to fix, and the only way to tell is to measure.
6. **Carry the change summary into the resumed work** as explicit context: what changed, what it implies,
   and how the plan was adjusted.

## Memory: what maps, and what does not
The source of this procedure re-indexed each changed file into a knowledge graph as a file-snapshot node.

**That has no honest equivalent here, and none is invented.** `chrono-vault` records canonical markdown
notes — `attempt`, `finding`, `learning` — and is not a file-content index. There is no
per-file snapshot upsert, and using `record` to stuff file contents into note bodies would be a misuse
that pollutes recall for every future query. The repository itself, through git, already is the file
index; the diff against the anchor is how it is queried.

What *is* worth recording is the lesson, not the contents:

`record(note_type="learning", fields={"title": "take-over-resume: <task>", "body": "anchor=<commit>; files_changed=<n>; inferred_intent=<...>; plan_adjustment=<what changed and why>", "target": "<component>", "attack_class": "none", "source_task": "<task-id>"})`

Best-effort only — a memory error is logged in one line and never blocks the resume.

## Failure modes
- **Resuming from memory** — continuing without diffing, and reverting the operator's fix.
- **Missing anchor** — no recorded commit at pause, so the resume diff has no baseline.
- **Redoing completed steps** — treating the plan as authoritative over the tree.
- **Stale verification** — trusting results from before the manual edits, and attributing a pre-existing
  failure to your own change.
- **Snapshot-stuffing memory** — pushing file contents into notes because the source pattern indexed
  files and something felt owed.

## Acceptance
- The resume began with a diff against a recorded anchor, and the diff was read rather than just listed.
- Manual changes were interpreted as intent, and no manual change was reverted without surfacing it.
- The plan was reconciled against the tree: completed steps dropped, invalidated steps reworked.
- Verification was re-run from the current tree before any failure was attributed.
- No file contents were pushed into memory; only the transferable lesson was recorded, best-effort.
