---
name: findings-filter
status: authored
---

# Findings Filter

Filter a candidate finding set down to what is real, reachable, and worth someone's attention — before it reaches a report.

## Steps
1. Reproduce first. A finding that has not been reproduced from a clean state is a hypothesis; label it so or drop it.
2. Apply the reachability gate: name the entry point, the actor, the privilege level, and the concrete input that reaches the defect. No path, no finding.
3. Apply the impact gate: state what an attacker gains that they did not already have. Findings whose only outcome is disclosure of already-public information, or self-inflicted harm by a privileged user, do not survive.
4. Apply the precondition gate: list every assumption the finding needs. If the preconditions are individually unlikely and jointly required, say so and rank accordingly.
5. Deduplicate by root cause, not by symptom. Ten call sites of one unsafe helper are one finding with ten instances.
6. Separate defects from hardening suggestions. Hardening is legitimate output but must not be presented at defect severity.
7. Check each survivor against the intended audience's bar — a program's scope, an operator's threat model, a reviewer's severity floor — and drop what is out of scope rather than padding.
8. For every dropped finding, record the gate it failed. The dropped list is evidence of thoroughness and prevents the same candidate being re-raised next pass.

## Acceptance
- Every retained finding was reproduced, with the reproduction recorded.
- Each retained finding names entry point, actor, privilege, and reaching input.
- Each states the attacker's concrete gain, not just the anomaly.
- Findings are deduplicated by root cause, with instances listed underneath.
- Hardening is separated from defects, and every drop records which gate it failed.
