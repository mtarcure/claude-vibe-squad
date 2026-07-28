---
name: dedup-prior-art-check
status: authored
---

# Dedup / Prior-Art / Novelty Check

Before spending effort on a lead and again immediately before submitting a finding, prove the
vulnerability (and the specific composite chain) is not already known — so the squad never burns a
report on a duplicate. This operationalizes `systematic-attacking` Phase 1 and its pre-submit refresh
into a concrete, evidence-producing gate.

**Source:** corpus B §11 (Cyfrin **Solodit** — 49k+ aggregated real-world smart-contract findings, via
`solodit-mcp` when adopted) and the `chrono-dedup` plugin; corpus A elite-vs-average (narrow-and-deep
continuous prior-art discipline).
**Impact class enabler:** protects report acceptance rate; a `duplicate`/`likely-duplicate` verdict
kills or demotes a lead early.
**Governing method:** the dedup gate of `systematic-attacking` (Phase 1 + pre-submit).

## Method
1. Build the search key from the lead: root-cause class, affected contract/endpoint/component,
   protocol + version, and the specific chain shape (not just the vuln class).
2. Query the prior-art surfaces via the `chrono-dedup` plugin: program disclosure history (HackerOne/
   Immunefi), GHSA/CVE/OSV, and — for web3 — the Solodit corpus (`solodit-mcp` if provisioned; else
   note `needs_tool` and use manual Solodit lookup). Search our own `chrono-vault` for prior squad
   work on the target.
3. Classify: `novel` / `variant-of-known` (cite the closest prior finding + what differs) /
   `likely-duplicate` / `duplicate`. Composite chains get a *separate* verdict — a chain of known
   primitives can still be a novel composition, and a novel-looking chain can be a known composite.
4. Kill/demote duplicates before Phase 4 effort. For `variant-of-known`, document the delta that
   makes it independently submittable.
5. Refresh the check immediately before submission (new disclosures land daily); attach the dated
   query evidence to the report.

## Acceptance
- Every lead carries a dated novelty verdict with the prior-art sources queried named.
- Duplicates are killed/demoted before deep effort; variants document their delta vs. the cited prior art.
- The pre-submit refresh is recorded with its date; if a web3 Solodit route is unavailable it is
  logged as `needs_tool`, not silently skipped.
