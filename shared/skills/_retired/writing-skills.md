---
name: writing-skills
retired: "retired — near-duplicate of the loaded superpowers plugin skill of the same name; plugin is the survivor. Repo-specific wiring step kept here; flagged in the task report."
status: authored
description: Use when creating or revising a skill doc — how to author a methodology that changes behavior: earn its existence, write a trigger-precise description, one stepwise workflow with a concrete worked example, and an acceptance list a reviewer can grade against.
---

# Writing Skills

A skill is a compressed method, not an essay about a topic. It earns its place by changing what a competent practitioner does at a specific recurring moment — and it fails silently when its description never fires or its steps cannot be graded.

## When to use
- Creating a new `shared/skills/*.md` doc or promoting a stub to authored.
- Distilling a repeated lesson, incident, or review finding into a reusable method.
- A reviewer reports that an existing skill was read but did not change the work.

## Inputs
- The recurring task shape the skill governs, with at least one real instance in hand.
- The failure that happens without the skill — a skill with no counterfactual is documentation, not method.

## Steps
1. Confirm the skill deserves to exist: the situation recurs, the method is non-obvious, and it is reusable beyond one target. One-time, target-specific procedure belongs in the task artifact, not the skill library.
2. Name it in kebab-case after the action or decision it governs, not the domain it lives in — `interface-ambiguity-check`, not `integration-tips`.
3. Write the `description:` as a recognition trigger, not a summary (method in `skill-description-trigger-authoring`): the first clause names the moment the reader should reach for it.
4. Structure the body in the house shape: one-sentence thesis; When to use; Inputs; Steps; Outputs; Failure modes; Worked example; Acceptance.
5. Write steps at the altitude of decisions. Each step is imperative, ordered, and carries its own completion test; a step obvious to any competent practitioner is noise, and a step that cannot fail is not a step.
6. Write failure modes as compressed incidents — the specific ways this method actually goes wrong in practice, not generic cautions. If you cannot name a real failure mode, you have not used the method enough to author it.
7. Make the worked example a real run: concrete inputs, concrete decisions, the actual output. A template with placeholders teaches the shape but not the judgment.
8. Test the doc cold: give only the doc, without your context, to a model or colleague against a fresh instance of the task. Every stall or deviation marks an under-specified step — fix the doc, not the reader.
9. Wire it: registry row, capability-source assignment, adapter regeneration — whatever the repo's mechanics require so the doc actually reaches its consumers. An authored skill nobody's lane projects is a stub with better prose.

## Outputs
- A skill doc in the house shape whose description triggers, whose steps are gradeable, and whose example is real.
- The wiring that delivers it to the specialists who need it.

## Failure modes
- **Essay-shaped skill** — background and philosophy, no executable method; reads well, changes nothing.
- **Scope sprawl** — two workflows sharing one doc; each dilutes the other's trigger. Split them.
- **Untestable steps** — "consider carefully", "ensure quality"; a reviewer cannot grade consideration.
- **Placeholder example** — `<your-component-here>` worked examples that skip every judgment call the method exists for.
- **Description that describes** — a summary of the content instead of the firing situation; the skill exists and never loads.
- **Authored-but-unwired** — the doc lands in the tree while the registry still says stub; consumers keep working without it.

## Worked example
This library's `verification-before-completion`: the recurring moment is emitting `complete`; the counterfactual failure is false-done reports (a real, recurring review finding). Its description leads with the moment ("about to claim work is complete, fixed, or passing"). Steps each carry a completion test (claims enumerated, checks run post-edit, output pasted). Failure modes are named incidents (summary inflation: prose says 29/29, terminal said 28/29). The worked example is a real validator run with the squad's actual test floor, including the judgment call the method exists for — checking the failing test's *name* against baseline, not just the count. Wiring followed authoring: registry row flipped to authored, capability source updated, adapters regenerated.

## Acceptance
- The description fires on the intended situations when tested against real past tasks (see `skill-description-trigger-authoring`).
- Every step is imperative and checkable; the failure modes are specific enough to recognize mid-mistake.
- The worked example contains real inputs and at least one visible judgment call.
- The skill is wired end-to-end: a consumer lane actually projects it.
