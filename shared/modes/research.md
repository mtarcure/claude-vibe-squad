---
name: research
version: 1.0
primary_lead: research
status: active
phases: 5
---

# Mode: Research

For deep investigation, comparison studies, "state of the field" surveys. Primary Lead: Research (Kimi).

## Triggers

```yaml
intent_phrases: ["research X", "investigate", "compare", "state of", "literature on", "find papers", "how does X actually work"]
file_types: []
negative_triggers: ["just curious", "quick question"]
```

Engagement: explicit yes or `/research`.

## Phases (5)

### Phase 1: Scope Estimation
Owner: Research Lead. Specialist: large-context-analyst (chrono's `scope-estimation` skill).
Output: `scope-card.md` (what's the question, what's in/out of scope, estimated source count, time budget).

### Phase 2: Source Gathering
Owner: Research Lead. Specialists: research, scout (for OSINT), data-extraction-engineer (for non-web sources).
Multi-model: yes (Claude + Gemini + Kimi for divergent retrieval — different models surface different sources).
Output: `sources.md` (annotated bibliography).

### Phase 3: Cross-Reference Synthesis
Owner: Research Lead. Specialists: synthesizer, large-context-analyst.
Multi-model: yes (Claude + Codex for contradiction detection — different reasoning patterns spot different gaps).
Output: `synthesis-draft.md`.

### Phase 4: Integrity Gate
Owner: Research Lead. Specialists: skeptic (cross-cutting, multi-model — all 4 providers).
Activity: chrono's `research-integrity-gate` (7-mode blocking checklist), citation validation, source triangulation, claim-confidence assignment.
Output: `integrity-report.md`.
Operator gate: SOFT (operator can see what passed/failed, choose to ship anyway).

### Phase 5: Deliverable
Owner: Research Lead. Specialist: technical-writer (Content cross-Lead) for final polish.
Output: `vault/research/<topic>.md` (the curated research note operator reads).
Operator gate: HARD (approve final note).
Pre-deliverable: vibecoding-check (citations resolve, no fabricated sources).

## Hard gates

```yaml
- phase_5_to_deliverable: HARD (operator approves final note)
```

## Multi-model usage (heavy)

This is the most multi-model-heavy mode. Per Anthropic's research-system pattern (LeadResearcher + parallel subagents + CitationAgent), Research Mode benefits from divergent perspectives at every phase except Scope Estimation.

## Termination

```yaml
completion: "research note delivered + operator approves"
explicit_stop: "operator says stop"
```

## KG writes

```yaml
- vault/research/<topic>/main.md
- vault/research/<topic>/sources.md
- vault/research/<topic>/synthesis.md
- vault/research/<topic>/integrity-report.md
- vault/instincts/research-insights.jsonl
```
