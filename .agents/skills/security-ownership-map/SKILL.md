---
name: security-ownership-map
audience: specialist
description: "Use when security findings or incident responsibilities are stalling because component ownership and decision rights are unclear—derive an evidence-backed map from code ownership, commit, deploy, and on-call records; record patch, shutdown, and credential-rotation authority; and flag unowned, departed, shared, vendor, or powerless owners. This routes remediation; it is not a system threat model."
---

# Security Ownership Map

Establish who owns each security-relevant component, so findings route to someone who can act and no surface is left unowned.

## Steps
1. Enumerate security-relevant components: authentication, authorization, secrets handling, data stores holding sensitive data, external integrations, deployment and CI, and the network edge.
2. For each component, derive candidate owners from evidence — code ownership files, commit history concentration, deploy configuration, and on-call rotations — rather than from an org chart.
3. Record for each component: owning team or person, escalation path, and the decision rights they actually hold (can they patch, can they take it offline, can they rotate its credentials).
4. Flag every component with no owner, a departed owner, or an owner who lacks the rights to remediate. Unowned security surface is itself a finding.
5. Flag shared-ownership components where responsibility is genuinely ambiguous; these are where findings stall longest.
6. Map each finding class to the owner who can remediate it, distinguishing the owner of the code from the owner of the deployment where these differ.
7. Note cross-boundary components — vendor-managed, contractor-built, or inherited — and record the contractual or practical limit on what can be changed.
8. Date the map and name its evidence sources; ownership decays and an undated map silently misroutes.

## Acceptance
- Every security-relevant component has a named owner, escalation path, and stated decision rights, or is explicitly flagged unowned.
- Ownership is derived from observable evidence, with the source cited per component.
- Components whose owner cannot remediate are called out separately from unowned ones.
- Finding classes are routed to the owner able to act on them.
- The map carries a date and its evidence sources.
