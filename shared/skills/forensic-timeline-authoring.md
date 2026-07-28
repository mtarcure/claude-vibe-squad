---
name: forensic-timeline-authoring
status: authored
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
