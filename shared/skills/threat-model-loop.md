---
name: threat-model-loop
status: authored
---

# Threat Model Loop

Iteratively connect assets, trust boundaries, attacker goals, abuse paths, mitigations, and verification evidence.

## Inputs

- System scope, architecture, identities, assets, and trust boundaries.
- Attacker capabilities and goals appropriate to the assessed environment.
- Existing controls, known incidents, tests, and unresolved assumptions.

## Method

1. Establish scope and enumerate assets, entry points, and privileged transitions.
2. Describe concrete abuse paths from attacker precondition to asset impact.
3. Rank paths by feasibility and impact, including control bypass assumptions.
4. Select a prevention, detection, or recovery control for each material path.
5. Define a test or observable that can falsify the control claim.
6. Feed failed tests and newly discovered boundaries back into the model until material unknowns are explicit.

## Acceptance

- Each material threat has an asset, actor, precondition, path, impact, and owner.
- Every claimed mitigation maps to a verification method or documented evidence gap.
- Residual risk and accepted assumptions are explicit.
- The final model records what changed during the loop and why it converged.
