---
name: maintenance
version: 1.0
primary_lead: sysmgmt
status: active
phases: 5
---

# Mode: Maintenance

For environment health, dep upgrades, repo cleanup, system sweeps. Primary Lead: SysMgmt (Claude).

## Triggers

```yaml
intent_phrases: ["clean up", "audit env", "upgrade deps", "patch CVEs", "things feel stale", "Mac feels weird", "weekly cleanup", "monthly audit"]
file_types: []
negative_triggers: ["explain maintenance", "what should I clean"]
```

## Phases (5)

### Phase 1: Doctor / Inventory
Owner: SysMgmt Lead. Specialist: mac-ops (runs the doctor.sh equivalent for current state).
Output: `inventory.md` (what's installed, versions, pending updates, anomalies).

### Phase 2: Risk Grouping
Owner: SysMgmt Lead. Specialist: skeptic (cross-cutting) for risk assessment.
Output: `risk-groups.md` — bucket pending changes by risk (low/medium/high).
Operator gate: SOFT.

### Phase 3: Plan + Approval
Owner: SysMgmt Lead.
Output: `plan.md` — ordered batches of changes.
Operator gate: HARD before any destructive action (deletions, force-pushes, schema migrations).

### Phase 4: Execute
Owner: SysMgmt Lead. Cross-Lead: Coding for code changes during refactors, Security for permission-impacting changes.
Output: per-batch result logs.
In-phase checkpoints: after each batch, stop if any error rate exceeds threshold.

### Phase 5: Regression Test + Changelog
Owner: SysMgmt Lead. Specialist: test-engineer (Coding cross-Lead) if code touched.
Output: `regression-test-results.md`, `changelog.md`.
Pre-completion: vibecoding-check.

## Hard gates

```yaml
- phase_3_to_4: HARD (operator approves plan before any destructive action)
- phase_4_destructive: HARD before each destructive batch
```

## Termination

```yaml
completion: "all batches executed + regression green"
explicit_stop: "operator says stop"
```

## Recurring auto-trigger

Some Maintenance tasks fire from the nightly routine (light cleanup). Full Maintenance Mode engages when:
- Operator explicitly invokes
- Nightly routine surfaces multiple accumulated issues
- Weekly Sunday brief recommends full sweep
