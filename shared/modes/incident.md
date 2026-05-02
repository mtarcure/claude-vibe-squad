---
name: incident
version: 1.0
primary_lead: sysmgmt
status: active
phases: 4
---

# Mode: Incident

For urgent reactive triage when something is broken. Primary Lead: SysMgmt. Time-bounded with checkpoint, but no hard wall-clock termination.

## Triggers

```yaml
intent_phrases: ["X is broken", "urgent", "production down", "this is on fire", "help", "panic"]
artifact_signals:
  - stack trace + "broken" / "down"
  - PagerDuty / Sentry alert URL with active error
file_types: []
```

## Phases (4)

### Phase 1: Stabilize
Owner: SysMgmt Lead. Specialist: mac-ops or whoever owns the affected system.
Activity: capture state (don't lose evidence), identify safe state to retreat to, snapshot anything volatile.
Output: `incident-state.md`.
Multi-model: no (speed > consensus).

### Phase 2: Diagnose
Owner: SysMgmt Lead. Specialists: relevant Lead's diagnosis specialist + skeptic (multi-model for hypothesis diversity).
Activity: systematic-debugging workflow, root-cause hypotheses, evidence gathering.
Output: `diagnosis.md` with ranked hypotheses.
Multi-model: YES (root-cause disagreement matters).
Cross-Lead: Security Lead auto-paged if incident touches auth/secrets/network.

### Phase 3: Patch
Owner: SysMgmt Lead. Specialists: relevant fix-developer (Coding cross-Lead if code).
Activity: minimal-change fix first; root-cause perfection second.
Output: patch + verification of fix.
Operator gate: HARD before patch applied.
Multi-model: yes for code review (code-reviewer cross-cutting).

### Phase 4: Postmortem (mandatory)
Owner: SysMgmt Lead. Specialist: technical-writer (Content cross-Lead).
Activity: timeline, root cause, contributing factors, mitigations applied, follow-up actions.
Output: `postmortem.md` saved to vault — feeds the dreaming system as instinct entries.

Even tiny incidents get a postmortem. Per chrono memory: insight capture is first-class learning.

## Hard gates

```yaml
- phase_3_to_4: HARD before applying patch (operator confirms fix is right)
```

## Time

NO wall-clock timeout. The phase 1 (Stabilize) might be 5 minutes; complex root-cause might take hours. Mode pauses if pathology detected (loop, repeat, retry-spike) or operator says pause.

## Termination

```yaml
completion: "patch applied + verified + postmortem written"
explicit_stop: "operator says stop"
```

## Cross-mode escalation

If during diagnosis we find this is actually a security event (RCE, credentials exposed), Coordinator suggests transitioning to Bounty Mode for proper handling. Operator confirms switch.
