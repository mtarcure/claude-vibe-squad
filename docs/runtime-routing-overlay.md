# Runtime Routing Overlay

Status: draft decision gate
Owner: Chrono / sysmgmt namespace

This document records the proposed routing adjustment before Vibe Squad changes specialist ownership or dispatch behavior.

## Decision

Vibe Squad should move toward capability-first specialists with model/runtime routing, but it should not reorganize folders or duplicate specialists yet.

Use an overlay:

- specialists remain one canonical markdown capability
- each specialist declares preferred runtime behavior
- Chrono selects swarm template plus runtime Lead
- Leads still execute and own local state for their runtime
- multi-model execution is explicit and tested, not the default

## Why

Departments are too rigid when the real routing question is which model/runtime is best for the task. Some content work is best for Gemini, some code-derived docs are best for Codex, some research-heavy content is best for Kimi, and high-judgment review is best through Claude or multi-model review.

The overlay preserves the current product shape while making routing smarter.

## Non-Negotiables

- Chrono remains the only operator-facing interface.
- No five drifting specialist copies.
- Canonical behavior remains markdown-first.
- Leads remain runtime/state owners.
- A multi-runtime invocation has one task owner and one final synthesis path.
- Independent parallel runs are read-only unless a single implementation owner is assigned.
- Cleanup and file moves wait until routing tests pass.

## Specialist Metadata Target

Future specialist files or manifests should support these fields:

```yaml
canonical_specialist: code-reviewer
primary_runtime: codex
secondary_runtimes: [claude, gemini]
multi_model_capable: true
multi_model_modes:
  - independent_parallel
  - primary_plus_review
writer_family_excluded: true
state_owner: initiating_lead
handoff_merge: synthesizer_or_skeptic
```

This is metadata for Chrono routing. It does not require moving the specialist file.

## Runtime Leads

| Runtime Lead | Best for |
|---|---|
| Codex | implementation, repo edits, tests, refactors, mechanical code review |
| Claude | judgment, security, safety, coordination-heavy ops, adversarial review |
| Kimi | long context, large corpora, research synthesis, source-heavy work |
| Gemini | multimodal, design/content, visual/PDF/video workflows, Google grounding |

## Multi-Model Modes

### Independent Parallel

Same specialist capability runs through multiple runtimes independently, then a synthesis/verdict role merges outputs.

Use for:

- `skeptic`
- `code-reviewer`
- `impact-validator`
- `threat-modeler`
- `privacy-steward`
- `research`
- `planner`
- `smart-contract-engineer`
- `exploit-developer`
- `architect`

### Primary Plus Review

One runtime owns the work; another runtime reviews it.

Use for:

- code implementation
- docs
- design implementation
- scraping/extraction
- local ops changes
- cleanup/config changes

### Council

Escalation mode for high-stakes decisions, no-majority disputes, or explicit operator request. Minority opinions must be preserved.

Use for:

- high-impact security findings
- privacy/data-retention decisions
- architecture decisions with large blast radius
- product direction disputes
- unresolved specialist disagreement

## Initial Roster

### Multi-Model Capable By Default

- `skeptic`
- `code-reviewer`
- `impact-validator`
- `threat-modeler`
- `privacy-steward`
- `research`
- `planner`
- `smart-contract-engineer`
- `exploit-developer`
- `architect`

### Optional Multi-Model

- `ai-engineer`
- `designer`
- `technical-writer`
- `editor`
- `summarizer`
- `vibecoding-check`

### Usually Single Owner Plus Review

- `backend-engineer`
- `frontend-engineer`
- `ui-engineer`
- `devops-engineer`
- `refactor-cleaner`
- `systems-engineer`
- `performance-optimizer`
- `scraping-engineer`
- `data-extraction-engineer`
- `content-creator`
- `brand-voice`
- `social-strategist`
- `memory-curator`
- `knowledge-librarian`
- `loop-operator`
- `agentops`
- `mac-ops`
- `finance-analyst`
- `personal-ops`

## Test Gate

Before changing specialist files or dispatch behavior, run one small multi-runtime smoke test:

1. Chrono creates one test task.
2. Task selects one multi-model-capable specialist.
3. At least two runtime Leads run the same capability independently.
4. Outputs include provenance and no file edits unless assigned to one owner.
5. `synthesizer` or `skeptic` merges/verdicts the outputs.
6. Active registry closes cleanly.
7. Chrono summarizes result and routing lessons.

Preferred first tests:

- `planner`: Claude + Codex on a harmless planning fixture.
- `skeptic`: Claude + Codex + Gemini on a factual claim with supplied evidence.
- `code-reviewer`: Codex + Claude on a tiny read-only diff fixture.

Current test status:

- Stage A single-runtime startup results are recorded in `docs/runtime-routing-test-results.md`.
- Stage B planner fixture ran on Codex, Gemini, and Kimi.
- Direct shell Claude test was invalid because API-key env vars forced the wrong billing/auth path. A signed-in `squad:4.0` Claude Max pane smoke passed with `Reply exactly: ok`.
- Stage C constraint-collision fixture ran on Codex, Gemini, and Kimi.
- The tested runtimes preserved the state/public-release contradiction and converged on the same blocker: state separation must be proven before routing changes.
- Stage D state-separation smoke test currently fails: `bin/product-hygiene.sh` reports runtime/mailbox debris and 5 tracked public-release blockers.
- Next required work is cleanup/disposition for the tracked blockers and local runtime debris, then rerun the state-separation smoke test until it passes.

## Migration Rule

If the test passes, update in this order:

1. `docs/model-runtime-map.md`
2. `shared/routing.md`
3. `chrono/SPECIALIST-INDEX.md`
4. selected specialist frontmatter/model notes
5. validation rules
6. live dispatch tests

Do not move files or delete department structure until the overlay works in live routing.
