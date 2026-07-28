---
name: data-flow-trace
status: authored
---

# Data Flow Trace

Trace sensitive data through collection, storage, processing, sharing, retention, and deletion paths for privacy review.

## Inputs

- System boundaries, actors, data stores, processors, and trust zones.
- Data classes, purposes, legal or policy constraints, and retention promises.
- Evidence from code, configuration, schemas, logs, and operator-provided diagrams.

## Method

1. Enumerate data sources and classify each field by sensitivity and subject.
2. Trace every transformation and transfer across trust or jurisdiction boundaries.
3. Record purpose, access principal, encryption state, retention, and deletion behavior at each hop.
4. Mark inferred edges separately and identify the evidence needed to confirm them.
5. Compare observed flows with stated notice, consent, minimization, and deletion commitments.

## Acceptance

- Every source has a terminal store, processor, recipient, or explicit unknown edge.
- Cross-boundary transfers identify sender, receiver, protocol, and protection state.
- Retention and deletion paths are included, not just collection and use.
- Findings distinguish verified evidence from assumptions and rank remediation by exposure.
