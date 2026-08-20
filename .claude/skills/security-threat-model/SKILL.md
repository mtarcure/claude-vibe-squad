---
name: security-threat-model
audience: specialist
description: "Use before designing or reviewing a system whose assets, adversary, trust zones, and residual risks are not yet explicit: enumerate reachable STRIDE threats at each boundary, distinguish observed controls from assumptions, and terminate at a declared reporting floor."
---

# Security Threat Model

Build a threat model that is right-sized to the system and that terminates, rather than one that expands until every mechanism looks unsafe.

## Steps
1. State the asset: what is actually worth protecting here — data, funds, availability, integrity of a decision — and what its loss would cost.
2. State the adversary: capability, position, and motivation. An unbounded adversary produces an unbounded model and no decisions.
3. Draw the system as trust zones and the flows that cross them. Every trust-zone crossing is where the model does its work; flows inside a zone rarely are.
4. For each crossing, enumerate threats systematically — spoofing, tampering, repudiation, disclosure, denial, elevation — and keep only those the stated adversary can reach.
5. Record the existing control for each retained threat and whether it was observed working or merely assumed to exist. Assumed controls are gaps.
6. Rank residual risk by asset loss × adversary reach, using `review-severity-ladder`, and stop enumerating below the agreed floor.
7. Decide per residual: mitigate, bound the mechanism, remove the mechanism, or accept with a documented rationale and a revisit condition.
8. When the model keeps producing unmitigable criticals on one mechanism, remove or bound that mechanism — chasing an airtight control is the wrong response.
9. Write the assumptions down as first-class output; the assumptions are what will be wrong later, and they are what a reviewer should attack.

## Acceptance
- Asset, adversary capability, and trust zones are stated before any threat is listed.
- Threats are enumerated per trust-zone crossing and filtered to the stated adversary.
- Every control is marked observed or assumed; assumed controls are treated as gaps.
- Residuals carry an explicit decision — mitigate, bound, remove, or accept with rationale and revisit condition.
- Assumptions are recorded as their own section, and the model terminates at a stated floor.
