---
name: detection-as-code
audience: specialist
description: "Use when a detection engineer must author a Sigma, YARA, KQL, or SPL SIEM/EDR rule for a named TTP—pin the telemetry schema, add must-fire and must-not-fire fixtures, and replay representative history before any gated rollout. Not for incident triage or source-code defect scanning."
---

# Detection as Code

Author a SIEM/EDR detection rule as tested, versioned code (Sigma/YARA/KQL/SPL).

## Steps
1. State the target TTP, detection platform, and platform/schema version; confirm the telemetry prerequisites exist.
2. Write the rule against real field names; keep attacker-TTP modelling strictly in service of detection.
3. Add positive fixtures (must fire) and negative fixtures (must not over-fire); validate syntax.
4. Backtest/replay against representative history; record expected FP/FN surface and rule cost/cardinality.
5. Set rollout mode, owner, version, and rollback; deployment is operator-gated (`production_mutation`).

## Acceptance
- Positive fixture fires and negative fixture does not; syntax validated.
- Replay/backtest evidence present, or an explicit `unvalidated` status.
- Owner, version, and rollback recorded; no live deploy without approval.
