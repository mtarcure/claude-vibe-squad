---
name: triage
version: 1.0
primary_lead: chrono  # Coordinator-only — no Lead engaged
status: active
phases: 3
---

# Mode: Triage

For ambiguous incoming work — classify and route, no Lead engaged unless decision lands on one. Coordinator-only mode.

## Phase ownership at a glance

Triage is intentionally short and Coordinator-owned, so this table stays compact rather than expanding into Lead handoffs.

| Phase | Name | Lead | Specialists / dispatch |
|---|---|---|---|
| 1 | Classification | Chrono | cross-cutting `triage` only if needed |
| 2 | Duplicate Check | Chrono | cross-cutting `triage` continued if needed |
| 3 | Routing Decision | Chrono + operator | none until operator confirms escalation |

## Triggers

```yaml
artifact_signals:
  - Sentry / GitHub Issue / similar URL paste
  - Forwarded email or message paste
  - "what's this" / "is this important" / "should I worry about this"
intent_phrases: ["look at this", "what about this", "should we"]
```

## Phases (3)

### Phase 1: Classification
Owner: Coordinator (Chrono). Specialist: triage (cross-cutting).
Activity: type, severity, domain. Per chrono `routing-heuristics`.
Multi-model: no (speed > consensus).
Output: `triage-classification.md`.
Advance when: type, severity, domain, likely mode, and uncertainty level are recorded.

### Phase 2: Duplicate Check
Owner: Coordinator. Specialist: triage (continued).
Activity: search Linear / Sentry / GitHub Issues / KG for prior similar.
Output: `dedup-result.md` — duplicate found (link) OR confirmed novel.
Advance when: prior related artifacts are linked or novelty is explicitly stated.

### Phase 3: Routing Decision
Owner: Coordinator.
Activity: name the suggested mode + Lead. If recommendation is clear, surface to operator with one-tap "engage X mode?" If unclear, surface low-confidence recommendation.
Output: `routing-decision.md`.
Operator gate: HARD (operator confirms route or redirects).
Advance when: operator confirms the route, redirects, or declines escalation.

## No Lead engaged by default

This is the key property: Triage Mode classifies and recommends. It does NOT auto-engage another mode. Operator decides whether to escalate to Bounty / Project / Incident / Research / Maintenance based on triage recommendation.

## Termination

```yaml
completion: "routing decision recorded + operator confirms or redirects"
explicit_stop: "operator says skip"
pre_completion: "vibecoding-check universal + triage extension"
```

## Hard gates

```yaml
- phase_route_confirmation_gate: HARD (operator confirms route or redirects)
```

## Cleanup declarations

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Triage Mode defaults.

```yaml
durable_artifacts:
  - triage decision log entry
  - routing-decision.md

ephemeral_artifacts: []
```

## Output

Triage Mode is fast — typical run: 2-5 minutes. Single deliverable: a routing recommendation in `runs/<id>/routing-decision.md` that includes:
- Type + severity + domain
- Suggested mode + Lead
- Confidence
- Duplicate check result
- "Engage X mode?" call-to-action for operator
