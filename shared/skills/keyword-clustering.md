---
name: keyword-clustering
status: authored
---

# Keyword Clustering

Group supplied or grounded search queries by intent and topic, and map each reproducible cluster to a page.

## Required evidence table

Produce one row per normalized query with these fields: source, collection date, locale, device, raw query,
normalized query, intent label, intent confidence, similarity/split-merge rule applied, cluster ID, target page,
and exception rationale. Pin the similarity method and split/merge threshold before clustering; if judgment
overrides that rule, the row's exception rationale makes the override reviewable.

## Steps
1. Record the query source, collection date, locale, and device; never invent query or volume evidence.
2. Normalize each raw query with a stated rule while preserving the raw value in the table.
3. Tag intent as informational / navigational / transactional / commercial, with a confidence value and
   an explicit multi-intent exception where one label would misrepresent the query.
4. Apply the pinned similarity and split/merge rule so one cluster expresses one reviewable user need.
5. Map each cluster to one target page/content piece and record why any mapping exception is necessary.
6. Flag cannibalization wherever existing or proposed pages compete for the same cluster.

## Acceptance
- Every query has complete source/date/locale/device provenance and an intent confidence.
- The normalization, similarity, and split/merge rules are fixed and replayable; exceptions carry reasons.
- Each cluster maps to exactly one page (no two pages target the same cluster).
- Queries/volumes are grounded, not fabricated, and the required evidence table accompanies the map.
