---
name: knowledge-base-integration
status: authored
---

# Knowledge Base Integration

Wire an agent to a retrieval knowledge base so answers are grounded in sources, with honest coverage and no hallucinated citations.

## Steps
1. Define the corpus, its authority, and its freshness; state what the KB does and does not cover.
2. Design chunking, metadata, and retrieval so a query returns the right passages; measure retrieval quality, don't assume it.
3. Ground generation in retrieved passages and require citations to real returned sources — never invent a citation.
4. Define behavior on low-confidence/no-hit: say "not covered" or escalate, rather than guessing.
5. Set a re-index/refresh cadence and a check that answers still trace to current sources.

## Acceptance
- Retrieval quality is measured against representative queries, not assumed.
- Every answer cites real retrieved sources; no fabricated citations.
- No-hit/low-confidence behavior is defined (say-so or escalate, never guess).
