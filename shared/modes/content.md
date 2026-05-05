---
name: content
version: 1.0
primary_lead: content
status: active
phases: 9
---

# Mode: Content

For creating writing, design, media, campaigns. Primary Lead: Content (Gemini).

## Phase ownership at a glance

| Phase | Name | Lead | Specialists / dispatch |
|---|---|---|---|
| 0 | Strategy Fit + Scope Audit | Chrono direct + operator | none |
| 1 | Brief | Content / Gemini | `editor` |
| 2 | Research | Content + Research/SysMgmt | Research `research`, SysMgmt `knowledge-librarian` |
| 3 | Strategy | Content / Gemini | `brand-voice`, `social-strategist` |
| 4 | Outline | Content / Gemini | `editor`, `technical-writer` if technical |
| 5 | Draft | Content / Gemini | `content-creator`, `media-producer`, `designer` |
| 6 | Review | Content / Gemini | `brand-voice`; cross-cutting skeptic through owning Lead |
| 7 | Polish | Content / Gemini | `editor`, `designer`, `media-producer` if assets are involved |
| 8 | Publish Package | Content | Gemini lead-owned packaging; operator approval before publish |

## Triggers

```yaml
intent_phrases: ["write", "draft", "campaign", "social posts", "blog post", "create", "design"]
file_types: []
negative_triggers: ["explain how to write", "what's a campaign"]
```

Engagement: explicit yes or `/content`.

## Phases (8 + Phase 0 audit)

### Phase 0: Strategy Fit + Scope Audit
Owner: Chrono direct + operator.
Specialists: none.
Activity: confirm Content Mode is the right mode, identify audience, channel, deadline, desired asset types, source sensitivity, and whether Research / Project / Triage would be a better first mode.
Output: `content-scope-card.md`.
Operator gate: SOFT.
Advance when: mode fit, audience, channel, artifact class, and approval path are explicit.

### Phase 1: Brief
Owner: content namespace. Specialist: editor (intake).
Output: `brief.md` (goal, audience, format, deadline, tone).
Operator gate: SOFT.
Advance when: brief captures audience, format, deadline, tone, source requirements, and operator constraints.

### Phase 2: Research
Owner: content namespace. Specialists: research (cross-Lead Research), knowledge-librarian (cross-Lead SysMgmt).
Output: `research-pack.md` (sources, key facts, angles).
Multi-model: yes (Claude + Gemini for source diversity).
Advance when: sourced facts, citations, audience-relevant angles, and forbidden claims are recorded.

### Phase 3: Strategy
Owner: content namespace. Specialists: brand-voice, social-strategist.
Output: `strategy.md` (positioning, hooks, distribution channels, calendar fit).
Advance when: positioning, hook family, channel plan, and voice constraints are selected.

### Phase 4: Outline
Owner: content namespace. Specialists: editor + technical-writer (if technical).
Output: `outline.md` (structure, key beats, citations needed).
Operator gate: HARD (approve outline before draft).
Advance when: outline has operator approval and all required citations/assets are identified.

### Phase 5: Draft
Owner: content namespace. Specialists: content-creator (text), media-producer (media), designer (visual).
Multi-model: no (single creative voice while drafting).
Output: `draft.md`, `draft-assets/`.
Advance when: complete first-pass text/media exists for every channel promised in the brief.

### Phase 6: Review
Owner: content namespace. Specialists: skeptic (cross-cutting, fact-check), brand-voice (tone alignment).
Multi-model: yes (Claude + Gemini for critique).
Output: `review-notes.md`.
Advance when: factual, brand, channel-fit, and accessibility findings are recorded with fixes assigned.

### Phase 7: Polish
Owner: content namespace. Specialists: editor (final polish), designer (visual polish).
Output: `final.md`, `final-assets/`.
Advance when: review findings are resolved or explicitly waived, and final assets match channel specs.

### Phase 8: Publish Package
Owner: content namespace.
Output: per-channel deliverables (Twitter thread, LinkedIn, blog HTML, social images at correct dimensions).
Operator gate: HARD before publishing.
Pre-publish: vibecoding-check (universal + content-extension).
KG writes: `vault/content/<title>/`.
Advance when: operator approves final package, publish/send action is completed or intentionally held, and durable artifacts are written.

## Hard gates

```yaml
- phase_outline_to_draft_gate: HARD (outline approval)
- phase_publish_gate: HARD (final approval before going live)
```

## Cleanup declarations

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Content Mode defaults.

```yaml
durable_artifacts:
  - final approved pieces
  - final approved assets
  - voice anchors learned
  - audience-pattern updates
  - brand-voice refinements

ephemeral_artifacts:
  - draft iterations
  - dead-end variants
  - scratch outlines
  - rough generated assets

operator_decision_artifacts:
  - drafts marked maybe-later by operator
```

## Termination

```yaml
completion: "published OR operator says ready-to-publish-on-own-time"
explicit_stop: "operator says stop"
```
