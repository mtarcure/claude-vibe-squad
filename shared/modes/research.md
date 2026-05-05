---
name: research
version: 1.0
primary_lead: research
status: active
phases: 5
---

# Mode: Research

For deep investigation, comparison studies, "state of the field" surveys. Primary Lead: Research (Kimi).

## Phase ownership at a glance

| Phase | Name | Lead | Specialists / dispatch |
|---|---|---|---|
| 1 | Scope Estimation | Research / Kimi | `large-context-analyst` |
| 2 | Source Gathering | Research / Kimi | `research`, `data-extraction-engineer`; Security `scout` only for security/OSINT handoff |
| 3 | Cross-Reference Synthesis | Research / Kimi | `synthesizer`, `large-context-analyst` |
| 4 | Integrity Gate | Research | Cross-cutting skeptic through research namespace; citation validation |
| 5 | Deliverable | Research + Content | Content `technical-writer` for final polish if needed |

## Triggers

```yaml
intent_phrases: ["research X", "investigate", "compare", "state of", "literature on", "find papers", "how does X actually work"]
file_types: []
negative_triggers: ["just curious", "quick question"]
```

Engagement: explicit yes or `/research`.

## Phases (5)

### Phase 1: Scope Estimation
Owner: research namespace. Specialist: large-context-analyst (chrono's `scope-estimation` skill).
Output: `scope-card.md` (what's the question, what's in/out of scope, estimated source count, time budget).
Advance when: research question, exclusions, source classes, time budget, and confidence target are explicit.

### Phase 2: Source Gathering
Owner: research namespace. Specialists: research, data-extraction-engineer. Security/scout is a cross-Lead handoff only when the research question is security/OSINT-scoped.
Multi-model: yes (Claude + Gemini + Kimi for divergent retrieval — different models surface different sources).
Output: `sources.md` (annotated bibliography).
Advance when: sources cover the declared source classes, weak/low-trust sources are labeled, and citation metadata is captured.

### Phase 3: Cross-Reference Synthesis
Owner: research namespace. Specialists: synthesizer, large-context-analyst.
Multi-model: yes (Claude + Codex for contradiction detection — different reasoning patterns spot different gaps).
Output: `synthesis-draft.md`.
Advance when: claims are grouped, contradictions/gaps are named, and confidence levels are attached to major conclusions.

### Phase 4: Integrity Gate
Owner: research namespace. Specialists: skeptic (cross-cutting, multi-model — all 4 providers).
Activity: chrono's `research-integrity-gate` (7-mode blocking checklist), citation validation, source triangulation, claim-confidence assignment.
Output: `integrity-report.md`.
Operator gate: SOFT (operator can see what passed/failed, choose to ship anyway).
Advance when: citations resolve, high-impact claims are triangulated or caveated, and integrity findings are resolved or explicitly waived.

### Phase 5: Deliverable
Owner: research namespace. Specialist: technical-writer (Content cross-Lead) for final polish.
Output: `vault/research/<topic>.md` (the curated research note operator reads).
Operator gate: HARD (approve final note).
Pre-deliverable: vibecoding-check (citations resolve, no fabricated sources).
Advance when: final note is approved, durable research artifacts are written, and ephemeral source dumps are declared for cleanup.

## Hard gates

```yaml
- phase_deliverable_approval_gate: HARD (operator approves final note)
```

## Cleanup declarations

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Research Mode defaults.

```yaml
durable_artifacts:
  - final synthesis
  - source-tier learnings
  - topic-map updates
  - citation chains
  - integrity-report.md

ephemeral_artifacts:
  - raw fetched source dumps
  - intermediate synthesis drafts
  - exploration scratch
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
