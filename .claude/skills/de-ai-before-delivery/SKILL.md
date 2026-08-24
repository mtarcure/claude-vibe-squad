---
name: de-ai-before-delivery
audience: chrono
description: Use right before anything leaves the house—a bounty submission, PR, published doc, or client deliverable—to strip internal process tells (phase names, task IDs, `_state/`/worktree paths, specialist names) and AI-cadence tells while keeping every technical claim and its evidence intact. A register change at the boundary, not `copy-refinement`'s in-house voice revision.
---

# De-AI Before Delivery

House procedure for the last pass before a deliverable reaches an external reader. Two kinds of tell
leak: our internal process, and the machine cadence. Strip both without touching a single technical
claim. This runs on the finished artifact at the boundary — not during authoring.

## Strip the process tells
- Remove internal phase references (`Phase 3`, `L5`, `S2`, `lane`), task IDs, run IDs, `_state/` and
  `/tmp/` paths, worktree paths, and specialist names. A triager who reads "dispatched to
  exploit-developer in Phase 4" learns about our pipeline, not their bug.
- Remove anything that only makes sense inside the squad: mode names, reviewer routing, registry
  vocabulary, internal file layout, model-lane names.

## Strip the AI tells
- Cut the openers and filler: "I'll help you", "Certainly", "Let me", "Great question". Cut hedging
  stacks ("it may be possible that this could potentially").
- Match the destination's register. Heavy em-dash cadence and symmetrical "not X, but Y" phrasing
  read as machine-written where the destination is terse; adjust to the register a person who works
  on that problem actually writes in.

## De-AI is a register change, NOT a content reduction
- Keep every technical claim and all of its evidence — reproduction steps, addresses, line numbers,
  CVSS, PoC. A stripped report that loses the repro is worse than an unstripped one; a triager cannot
  act on register.
- Do not "clean up" by summarizing away detail. The only things removed are the provenance of how WE
  work and the cadence of a machine — never what was found or how to reproduce it.

## When a campaign ships more than one report, they must not look like a batch

The register pass above works inside one document. A second tell lives *across* documents, and it is
the one that costs most: several reports from one researcher, landing together, sharing a section
skeleton, each citing `file:line` and carrying a local harness with no live-service crash. Read at
volume that shape says "automated scan output" before anyone reads the finding, and it shifts the
reader's prior from trust to suspicion on every report in the set — including the good ones.

So, before sibling reports ship:

- **Break the skeleton.** Do not send two reports whose sections appear in the same order with the
  same headings. Let each be shaped by its own defect.
- **Lead with its own observable.** Each report opens on the concrete thing that happened in *that*
  finding — the balance that moved, the entry that can never be re-added — not a shared template
  opener.
- **Stagger the send** where the program's timing allows. Same-hour arrival is part of the pattern.
- **Never make the harness result the headline.** "N/N tests pass" is the harness grading itself. Put
  the state change first and let the suite corroborate it.

None of this touches the technical content. It changes only what the set looks like from outside.

## The acceptance test
- Read the result cold: would this pass as written by a person who works on this problem, for this
  audience? If a sentence reveals our process or reads as generated, it fails.
- Distinct from `copy-refinement`, which revises an in-house draft for voice and structure; here the
  content is final and the only job is removing tells at the boundary before it ships.
