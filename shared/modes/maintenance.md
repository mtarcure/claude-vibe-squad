---
name: maintenance
version: 1.0
primary_lead: sysmgmt
status: active
phases: 5
---

# Mode: Maintenance

For environment health, dep upgrades, repo cleanup, system sweeps. Primary Lead: SysMgmt (Claude).

## Phase ownership at a glance

| Phase | Name | Lead | Specialists / dispatch |
|---|---|---|---|
| 1 | Doctor / Inventory | SysMgmt / Claude | `mac-ops`, `agentops` |
| 2 | Risk Grouping | SysMgmt / Claude | `skeptic`, `harness-optimizer` when squad config is touched |
| 3 | Plan + Approval | SysMgmt / Claude | `planner` when multi-step changes are needed |
| 4 | Execute | SysMgmt + cross-Lead as needed | Coding implementation specialists for code changes; Security `privacy-steward` for permission impact |
| 5 | Regression Test + Changelog | SysMgmt + Coding if code touched | Coding `test-engineer` if code touched |

## Triggers

```yaml
intent_phrases: ["clean up", "audit env", "upgrade deps", "patch CVEs", "things feel stale", "Mac feels weird", "weekly cleanup", "monthly audit"]
file_types: []
negative_triggers: ["explain maintenance", "what should I clean"]
```

## Phases (5)

### Phase 1: Doctor / Inventory
Owner: sysmgmt namespace. Specialist: mac-ops (runs the doctor.sh equivalent for current state).
Output: `inventory.md` (what's installed, versions, pending updates, anomalies).
Advance when: inventory covers current versions, pending updates, anomalies, and any resource/process risks.

### Phase 2: Risk Grouping
Owner: sysmgmt namespace. Specialist: skeptic (cross-cutting) for risk assessment.
Output: `risk-groups.md` — bucket pending changes by risk (low/medium/high).
Operator gate: SOFT.
Advance when: every proposed change is grouped by risk, reversibility, and whether operator approval is required.

### Phase 3: Plan + Approval
Owner: sysmgmt namespace.
Output: `plan.md` — ordered batches of changes.
Operator gate: HARD before any destructive action (deletions, force-pushes, schema migrations).
Advance when: operator approves the batch plan and each destructive batch has an explicit approval marker.

### Phase 4: Execute
Owner: sysmgmt namespace. Cross-Lead: Coding for code changes during refactors, Security for permission-impacting changes.
Output: per-batch result logs.
In-phase checkpoints: after each batch, stop if any error rate exceeds threshold.
Advance when: approved batches complete, failures are logged, and rollback is either unnecessary or performed.

### Phase 5: Regression Test + Changelog
Owner: sysmgmt namespace. Specialist: test-engineer (Coding cross-Lead) if code touched.
Output: `regression-test-results.md`, `changelog.md`.
Pre-completion: vibecoding-check.
Advance when: regression checks pass or failures are documented as pre-existing, and the changelog names all operator-visible changes.

## Hard gates

```yaml
- phase_plan_to_execute_gate: HARD (operator approves plan before any destructive action)
- phase_destructive_batch_gate: HARD before each destructive batch
```

## Cleanup declarations

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Maintenance Mode defaults.

```yaml
durable_artifacts:
  - doctor logs
  - cleanup proposals
  - dependency-update records
  - system-snapshot diffs
  - regression-test-results.md
  - changelog.md

ephemeral_artifacts:
  - temp diff files
  - before/after captures
  - scratch script tests
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
