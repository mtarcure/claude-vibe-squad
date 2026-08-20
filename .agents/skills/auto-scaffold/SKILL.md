---
name: auto-scaffold
audience: specialist
description: "Use during Project Phase 6 “Local deliver” when the verified repo still lacks one or more standard handoff files—README, CHANGELOG, LICENSE, or the agent-context file. Generate only approved missing files from what the work actually produced; never overwrite an existing file."
---

# Auto-Scaffold

Generate the standard repository files at delivery so a project arrives usable rather than as a bare tree
of source. This runs during **Phase 6 “Local deliver”** of the S0–S7 project lifecycle, after verification
and before local handoff. The reciprocal missing-standard-files trigger lives in `shared/modes/project.md`;
that mode contract decides when this skill is loaded.

This skill **writes files**. That makes it a gated action, and the gate is not a formality — see
Approval below.

## The overwrite rule
**Never overwrite a file that already exists.** Skip it, and report the skip.

This is the rule that matters most, because every file this skill generates is a file a human is likely
to have written by hand and cared about. A generated README replacing a hand-written one destroys work
that generally is not recoverable from the branch, and the loss is silent — a scaffold step that reports
success while having replaced the project's documentation. Detect by checking each target before writing.
Overwriting requires explicit operator instruction naming the specific file.

## What gets generated
- **README.md** — title, one-line description, what it does, how to run it, and the tech stack. Derive
  from the project scope and from what the repo actually contains, not from what the plan intended.
- **CHANGELOG.md** — derived from the commit history of the work. Group by change type. Where there is no
  meaningful history, write a minimal initial entry rather than fabricating a release narrative.
- **LICENSE** — only with an operator-confirmed choice. See Approval.
- **CLAUDE.md** — the agent-context file, so a future session in that repo starts oriented: what the
  project is, its conventions, how to build and test it, and the constraints that are not visible in the
  code. Note that `CLAUDE.md` is this repo's convention; the source pattern's companion context files have
  no counterpart here and are not created.

## Steps
1. **Confirm the stage and read the tree first.** Establish the work is verified and delivery is the next
   step, then enumerate which of the target files already exist. This list decides everything that follows.
2. **Gather the source material.** Project scope, tech stack, entry points, build and test commands, and
   the commit history for the change log. Derive from the repository as it stands — a scaffold describing
   an intended project rather than the delivered one is actively misleading.
3. **Obtain operator approval before writing.** Present the exact list of files to be created and the
   files being skipped because they exist. See Approval.
4. **Write only the missing files.** Each existing target is skipped and reported by name.
5. **Verify the instructions you just wrote.** Run the build and test commands exactly as the README
   states them. A scaffold's commands are its only load-bearing claim, and an untested command block is
   the most common defect in a generated README — it is written from the plan rather than from a run.
6. **Report what was created, what was skipped and why, and what remains for a human.** Placeholders left
   for the operator are listed explicitly, never left to be discovered.

## Approval
Two distinct gates apply, and they are not the same gate:

- **Writing the files** mutates the target repository. Confirm the file list with the operator before
  writing.
- **The LICENSE, and anything that constitutes publishing,** is a separate operator decision under Hard
  Rule 6 — public release changes require explicit operator approval. Do **not** default a license.
  Choosing a license is a legal decision about the operator's work, an inferred default is
  indistinguishable in the tree from a deliberate one, and it is materially harder to walk back after
  publication than before. Ask; if unanswered, skip the LICENSE and report it as outstanding.

If the operator declines, exit cleanly with no writes. Declining the scaffold does not fail the delivery.

## Failure modes
- **Silent overwrite** — the failure this skill is most able to cause, and the least likely to be noticed
  in a diff review of a "routine" scaffold commit.
- **Defaulted license** — a license chosen by the tool rather than the operator.
- **Aspirational README** — documenting the plan rather than the delivered repo.
- **Untested commands** — build and run instructions that were written but never executed.
- **Invented history** — a change log narrative constructed where no commit history supports it.

## Acceptance
- Every existing target file was detected before writing and left untouched; skips are reported by name.
- The operator approved the file list before any write occurred.
- No LICENSE was created without an explicit operator choice.
- Content describes the delivered repository, and every build/run command in the README was executed as written.
- Remaining placeholders and outstanding decisions are listed explicitly in the report.
