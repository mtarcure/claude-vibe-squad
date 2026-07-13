---
name: attack-coverage-map
status: authored
---

# Attack Coverage Map

Analyze detection coverage against a known TTP matrix and surface the gaps that matter.

## Steps
1. Choose the reference matrix (e.g. ATT&CK) or the program-specified technique set.
2. Map each existing detection rule to the technique(s) it covers.
3. Mark every technique covered / partial / gap.
4. For each gap, name the specific telemetry or log source it would require.
5. Prioritize gaps by risk × feasibility; hand telemetry-architecture gaps up as a `needs_human` decision.

## Acceptance
- Every rule maps to at least one technique; every technique has a coverage status.
- Each gap names its missing telemetry.
- Priorities are justified by risk and feasibility.
