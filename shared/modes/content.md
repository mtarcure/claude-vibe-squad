---
name: content
version: 1.0
primary_lead: content
status: active
phases: 8
---

# Mode: Content

For creating writing, design, media, campaigns. Primary Lead: Content (Gemini).

## Triggers

```yaml
intent_phrases: ["write", "draft", "campaign", "social posts", "blog post", "create", "design"]
file_types: []
negative_triggers: ["explain how to write", "what's a campaign"]
```

Engagement: explicit yes or `/content`.

## Phases (8)

### Phase 1: Brief
Owner: Content Lead. Specialist: editor (intake).
Output: `brief.md` (goal, audience, format, deadline, tone).
Operator gate: SOFT.

### Phase 2: Research
Owner: Content Lead. Specialists: research (cross-Lead Research), knowledge-librarian (cross-Lead SysMgmt).
Output: `research-pack.md` (sources, key facts, angles).
Multi-model: yes (Claude + Gemini for source diversity).

### Phase 3: Strategy
Owner: Content Lead. Specialists: brand-voice, social-strategist.
Output: `strategy.md` (positioning, hooks, distribution channels, calendar fit).

### Phase 4: Outline
Owner: Content Lead. Specialists: editor + technical-writer (if technical).
Output: `outline.md` (structure, key beats, citations needed).
Operator gate: HARD (approve outline before draft).

### Phase 5: Draft
Owner: Content Lead. Specialists: editor (text), content-creator (media), designer (visual).
Multi-model: no (single creative voice while drafting).
Output: `draft.md`, `draft-assets/`.

### Phase 6: Review
Owner: Content Lead. Specialists: skeptic (cross-cutting, fact-check), brand-voice (tone alignment).
Multi-model: yes (Claude + Gemini for critique).
Output: `review-notes.md`.

### Phase 7: Polish
Owner: Content Lead. Specialists: editor (final polish), designer (visual polish).
Output: `final.md`, `final-assets/`.

### Phase 8: Publish Package
Owner: Content Lead.
Output: per-channel deliverables (Twitter thread, LinkedIn, blog HTML, social images at correct dimensions).
Operator gate: HARD before publishing.
Pre-publish: vibecoding-check (universal + content-extension).
KG writes: `vault/content/<title>/`.

## Hard gates

```yaml
- phase_4_to_5: HARD (outline approval)
- phase_8_to_publish: HARD (final approval before going live)
```

## Termination

```yaml
completion: "published OR operator says ready-to-publish-on-own-time"
explicit_stop: "operator says stop"
```
