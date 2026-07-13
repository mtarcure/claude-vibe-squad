---
name: rights-and-provenance-gate
status: authored
---

# Rights and Provenance Gate

Run the pre-publication rights gate (Hard Rule 6) over a generated or third-party asset and emit a machine-readable gate record.

## Steps
1. Bind the decision to an immutable `subject_id`/`subject_hash`/`subject_version` and a versioned checklist; a modified asset needs a new record.
2. Check, each with evidence: license/provenance, usage-terms fit (channel/territory/duration), consent/likeness, trademark, watermark/C2PA markers, and music match.
3. Use non-legal language — record "identified match/similarity" and available evidence; do NOT decide de-minimis or fair use.
4. Any material unresolved check (e.g. a lookup tool is not wired) → `HOLD`; never PASS on uncertainty.
5. Emit the gate record (`PASS|HOLD|FAIL`, evidence refs, assurance level, unresolved items, reviewer, timestamp, override fields).

## Acceptance
- Decision is hash-bound; every checklist item is evidenced or HELD.
- No PASS on a material unresolved check; no infringement asserted from similarity alone.
- Legal uncertainty is surfaced for human/counsel, not adjudicated here.
