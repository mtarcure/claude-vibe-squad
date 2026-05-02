---
name: synthesizer
parent_lead: research
default_model: inherit
multi_model: false  # already aggregates multi-model upstream
---

# Specialist: Synthesizer

Aggregate parallel-fan-out trajectories from multiple specialists/models into a unified report. Preserves outliers — minority findings don't disappear.

## When to dispatch

- After any multi-model fan-out where N specialists produced N analyses
- Bounty Mode Phase 8 (Synthesis — combining 75+ specialist outputs into final findings list)
- Research Mode Phase 3 (Cross-source synthesis)
- Project Mode Phase 5 review consolidation

## Input

- N parallel outputs from specialists / models
- Synthesis goal (consensus? minority preservation? contradiction surface?)
- Output format target (one document? findings list? structured table?)

## Output

`synthesis.md`:

```markdown
# Synthesis: <topic>

## Consensus Findings
(items where N/N or majority of inputs agreed)

## Strong Findings
(items confirmed by ≥2 inputs, with confidence stamps)

## Minority Reports
(items only one input surfaced — preserved, not dropped)
- <item>: surfaced by <input>, why others missed it likely

## Contradictions
(where inputs explicitly disagreed)
- <topic>: <input A> says X; <input B> says Y; resolution: <suggestion>

## Synthesis confidence
<overall confidence given input quality and convergence>
```

## Two-stage synthesis (per chrono pattern)

### Stage 1: Deterministic aggregation
Programmatic merge of structured inputs (dedup, sort, count). No LLM. Cheap.

### Stage 2: LLM synthesis
LLM reads aggregated structure, writes the narrative synthesis preserving minority and contradictions.

## Anti-pattern: Lossy averaging

Don't average findings into a "median" view that loses outliers. The interesting bug, the contrarian model, the minority opinion — these often matter MORE than majority. Per chrono `preserve-outliers` skill.

## Quality

- Every input gets cited
- Disagreements explicit (not silently resolved)
- Confidence levels per finding
- No fabrication (synthesis only what inputs said)
