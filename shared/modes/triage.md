---
name: triage
version: 1.0
primary_lead: chrono  # Coordinator-only — no Lead engaged
status: active
phases: 3
---

# Mode: Triage

For ambiguous incoming work — classify and route, no Lead engaged unless decision lands on one. Coordinator-only mode.

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

### Phase 2: Duplicate Check
Owner: Coordinator. Specialist: triage (continued).
Activity: search Linear / Sentry / GitHub Issues / KG for prior similar.
Output: `dedup-result.md` — duplicate found (link) OR confirmed novel.

### Phase 3: Routing Decision
Owner: Coordinator.
Activity: name the suggested mode + Lead. If recommendation is clear, surface to operator with one-tap "engage X mode?" If unclear, surface low-confidence recommendation.
Output: `routing-decision.md`.
Operator gate: HARD (operator confirms route or redirects).

## No Lead engaged by default

This is the key property: Triage Mode classifies and recommends. It does NOT auto-engage another mode. Operator decides whether to escalate to Bounty / Project / Incident / Research / Maintenance based on triage recommendation.

## Termination

```yaml
completion: "routing decision recorded + operator confirms or redirects"
explicit_stop: "operator says skip"
```

## Output

Triage Mode is fast — typical run: 2-5 minutes. Single deliverable: a routing recommendation in `runs/<id>/routing-decision.md` that includes:
- Type + severity + domain
- Suggested mode + Lead
- Confidence
- Duplicate check result
- "Engage X mode?" call-to-action for operator
