# Swarm finding taxonomy

This document defines the closed vocabulary used by `swarm-member-result/v1`. Code enforces the schema and exact-key comparison; this markdown defines the words. A taxonomy change is a reviewed policy change.

The fenced object below is the machine-readable source of truth.

```json swarm-finding-taxonomy/v1
{
  "schema_version": "swarm-finding-taxonomy/v1",
  "weakness_classes": ["access-control", "authentication", "authorization", "business-logic", "cryptography", "data-integrity", "denial-of-service", "injection", "oracle-consumption", "privacy", "race-condition", "reentrancy", "resource-accounting", "supply-chain", "unsafe-deserialization", "validation", "other"],
  "impact_classes": ["account-takeover", "asset-loss", "availability-loss", "confidentiality-loss", "integrity-loss", "privilege-escalation", "unauthorized-action", "none", "other"],
  "dispositions": ["confirmed", "rejected", "inconclusive"],
  "severities": ["critical", "high", "medium", "low", "info", "none"],
  "confidences": ["high", "medium", "low"],
  "affected_surface_pattern": "^(?!\\.{1,2}(?:/|$))(?:[A-Za-z0-9_.-]+/(?!\\.{1,2}(?:/|$)))*(?!\\.{1,2}(?:::|$))[A-Za-z0-9_.-]+(?:::[A-Za-z_][A-Za-z0-9_.$<>-]*)?$",
  "finding_key_fields": ["target", "weakness_class", "affected_surface", "impact_class"]
}
```

## Canonical key

`finding_key` is the lowercase SHA-256 of the four UTF-8 fields in `finding_key_fields`, joined by a single ASCII unit separator (`0x1f`) after trimming outer whitespace. `affected_surface` is the exact repository-relative POSIX path, with repository case preserved, optionally followed by the source declaration's exact `::symbol`. Emit no `./`, `../`, backslashes, URL/query/fragment syntax, line numbers, ranges, or prose; do not alias equivalent paths or symbols. If a finding spans several symbols, use the closest stable containing declaration shared by the evidence and list narrower locations only in evidence. `target` is the exact scoped target identifier from the task.

Exact key equality is the only automatic merge in v1. Near matches remain lane-only findings for review. A model-authored key is evidence metadata, not semantic proof; malformed vocabulary or a key mismatch is a coverage gap.
