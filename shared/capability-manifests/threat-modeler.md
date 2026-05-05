# Capability Manifest: threat-modeler

Status: draft, current-system capability
Owner: security namespace
Canonical current specialist: `departments/security/specialists/threat-modeler.md`
Old plugin source: none direct; maps from old security/challenger reasoning surfaces.

## Role Contract

`threat-modeler` owns repository/system threat modeling: assets, trust boundaries, abuse cases, attacker profiles, mitigations, and ranked hypotheses. It hypothesizes and prioritizes; it does not confirm exploitability.

## Preserved Current Behavior

- Multi-model threat scenario generation.
- Bounty Mode Phase 4 and security-touching Project Mode design support.
- Concrete abuse cases with preconditions, steps, and impact.
- Handoff to `security-analyst` / `exploit-developer` for confirmation.

## Old Plugin Capabilities To Preserve

No direct old plugin existed. Preserve security-analyst/scout/challenger adjacent behavior: adversarial scenario generation, boundary review, and hypothesis ranking.

## Required Tools

- Code/config read path.
- Trust-boundary diagram or markdown path.
- KG/catalog recall.
- Cross-model review for high-stakes scenarios.

## Optional Tools

- Diagram rendering.
- Threat-model templates/attack tree helpers.

## MCPs

- `chrono-kg`
- `chrono-catalog`
- `chrono-vault` / `chrono-obsidian`
- `sequential-thinking`

## Skills

- `security-threat-model`
- `pre-audit-threat-model`
- `agentic-safety-audit`
- `interface-ambiguity-check`
- `security-ownership-map`

## Adaptive Operating Mode

Identify assets and trust boundaries, enumerate concrete abuse cases, rank hypotheses, cite evidence, and dispatch confirmation to security specialists rather than claiming exploitability.

## Output Contract

- `threat_model_path`
- `hypotheses_path`
- `assets`
- `trust_boundaries`
- `abuse_cases`
- `mitigations`
- `handoff_recommendations`

## KG And Memory Behavior

- Record durable threat hypotheses and design risks.
- Keep client/private system details local.

## Safety Boundaries

- No live exploits.
- No exploitability confirmation.
- No scope expansion without operator approval.

## Live Dispatch Proof

Chrono -> security namespace -> `threat-modeler` must produce a harmless sample threat model with ranked hypotheses and handoff recommendations, then close active registry.

## Public/Private Disposition

Public: role prompt, manifest, sample threat models. Private: client/system-specific threat models.

## Cleanup Disposition

Keep as current-system capability; do not remove threat-modeling files without explicit merge into security-analyst and live proof.
