---
name: skill-description-trigger-authoring
audience: specialist
description: "Use when a description frontmatter field must become an accurate activation trigger, especially because its skill stays dormant or is confused with a sibling—encode recognizable workflow cues and replay-test positive and negative tasks. Scope is trigger metadata, not instruction-body or resource design."
---

# Skill Description Trigger Authoring

A skill's description is its activation surface: it is matched against the task at hand by a reader who does not yet know the method. A description that summarizes content instead of naming the firing situation produces a skill that is technically available and practically never loaded.

## When to use
- Authoring or revising the `description:` frontmatter of any skill.
- A postmortem shows a task where an existing skill should have fired and didn't.
- Two adjacent skills keep being confused for each other.

## Inputs
- The moments in real workflows when the skill must load ("about to emit `complete`", "about to implement against a foreign schema").
- Real past tasks: several where the skill should have fired, several adjacent ones where it should not.

## Steps
1. Enumerate the firing situations: what is the practitioner *doing or about to do* when this skill must load? Situations, not topics — "about to claim done", not "quality assurance".
2. Write from the reader's pre-skill state. They can recognize their situation; they cannot recognize the method's vocabulary. "Use when about to X" beats "a methodology for X-ing".
3. Front-load the trigger. Descriptions are scanned under time pressure; the first clause decides whether the rest is read.
4. Include the concrete cue words and symptoms as they appear in real tasks — the phrases in packets, the moment in the workflow, the observable temptation ("it should work"). Matching happens against the task's own language.
5. Add anti-triggers where siblings overlap: when NOT to use this skill, and which sibling handles that case. Disambiguation in the description is cheaper than a wrong load.
6. Keep it to one or two sentences. A trigger buried in a paragraph fires never; completeness belongs in the body's When-to-use, not the description.
7. Replay-test: take three real past tasks where the skill should have fired and two adjacent ones where it shouldn't. Reading the description alone — no body — check it routes all five correctly. A miss is a description bug; fix the description, not the tasks.

## Outputs
- A one-to-two-sentence description whose first clause names the firing situation, containing real cue language, and disambiguated from siblings.
- A recorded replay-test result.

## Failure modes
- **Summary-not-trigger** — "Guidance on verification best practices": describes the content, names no moment, never fires.
- **Method leakage** — the description teaches steps instead of naming situations, wasting its only job on content the body already carries.
- **Over-broad trigger** — fires on everything, reader learns to ignore it; a trigger that always matches carries no information.
- **Post-skill vocabulary** — jargon the method itself introduces; the pre-skill reader can't match terms they haven't learned yet.
- **Missing anti-trigger** — two siblings with overlapping triggers, so the wrong one loads and both lose trust.

## Worked example
Bad: `description: Describes the verification methodology for completed work.` — a summary; no practitioner mid-task self-identifies as "needing verification methodology". Good: `description: Use when about to claim work is complete, fixed, or passing — run the check that would falsify each claim and read its output before emitting the claim.` The first clause names the exact workflow moment (emitting a completion claim); "complete, fixed, or passing" are the literal words that appear in the task's own language; the em-dash clause states the obligation compactly without teaching the method. Replay-test: fires on "flip the registry rows and confirm validators green" (should), fires on "report the fix upstream" (should), stays silent on "estimate the refactor scope" (correctly — that's `scope-decomposition`'s trigger).

## Acceptance
- The replay test routes all sampled tasks correctly from the description alone.
- The first clause states a situation the pre-skill reader can recognize.
- Length is at most two sentences; cue phrases are real task language, not method jargon.
- Overlapping siblings are explicitly disambiguated.
