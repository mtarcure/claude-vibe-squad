---
name: forensic-timeline-authoring
audience: specialist
description: "Use when reconstructing an incident from logs, images, records, or other artifacts and the chronology must preserve provenance—normalize clocks, hash and cite each source, label fact versus inference, and leave evidentiary gaps unknown."
---

# Forensic Timeline Authoring

Reconstruct an evidence-preserving incident timeline that separates observed fact from inference.

## Steps
1. Collect artifacts with metadata: source, collection time, collector, hash, sensitivity.
2. Normalize clocks and time zones; note any clock skew or unsynced sources.
3. Order events on a single timeline; cite the source (and hash) for each entry.
4. Label every line as observed fact, inference, recommendation, or executed action.
5. Mark chain-of-custody gaps and unrecoverable periods as `unknown` — never fill with plausible guesses.

## Acceptance
- Every entry cites a source and hash; fact vs inference is labeled per line.
- Clock skew is noted; gaps are marked unknown.
- No fabricated or interpolated events.
