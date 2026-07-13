---
name: incident-response-runbook
status: authored
---

# Incident Response Runbook

Drive a suspected/active security incident through triage → contain → eradicate → recover → review without destroying evidence.

## Steps
1. Triage: establish scope, severity, and whether compromise is suspected (vs a reliability fault → `site-reliability-engineer`).
2. Preserve volatile evidence before changing any state; record collection metadata and hashes.
3. Propose containment; map every live action (isolate, block, rotate, wipe) to its `operator_gate` and hold for approval.
4. Eradicate root cause; hand the observed TTP to `detection-engineer`.
5. Recover and validate against explicit recovery-criteria with user-facing signals.
6. Run a post-incident review: root cause, lessons, hardening.

## Acceptance
- Evidence captured before any state change; chain of custody preserved.
- Every live action is operator-approved before execution; unknowns preserved, not guessed.
- Recovery is validated by a user-facing indicator, not assumed.
