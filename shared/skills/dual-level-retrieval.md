---
name: dual-level-retrieval
status: authored
---

# Dual-Level Retrieval

Retrieve twice — once coarsely over the whole corpus to locate candidates, once precisely inside them to read evidence — so breadth never comes at the cost of quoting accurately.

## Steps
1. Run the coarse pass over the entire corpus using cheap, recall-oriented queries: names, symbols, and identifiers rather than concepts. Optimize for missing nothing, and accept false positives.
2. Record the coarse hit set as a list of locations before reading any of them. This list is the denominator for the fine pass.
3. Rank the hit set by expected decisiveness, not by match count — the file that defines a behavior outranks the ten that mention it.
4. Run the fine pass by reading the ranked candidates in full context, wide enough to capture the enclosing definition and its callers.
5. Quote from the fine pass only. Any claim traced to a coarse-pass snippet is unverified, because a grep line is not a reading of the code.
6. Feed fine-pass discoveries back into a new coarse query when they reveal vocabulary you did not know to search for, and iterate until a coarse pass adds no new decisive locations.
7. Report both levels: how many locations the coarse pass found, how many the fine pass read, and what was deliberately left unread.

## Acceptance
- Coarse queries and their exact hit counts are recorded.
- Every quoted line comes from a file read in the fine pass.
- Candidate ranking is justified by decisiveness rather than frequency.
- At least one feedback iteration is attempted, or its absence is justified.
- The gap between locations found and locations read is stated explicitly.
