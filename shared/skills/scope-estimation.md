---
name: scope-estimation
status: authored
---

# Scope Estimation

Measure the corpus before analyzing it, so the retrieval plan and the confidence claims are sized to what was actually read rather than to what was sampled.

## Steps
1. Count the corpus before opening it: number of files, total bytes, and the largest single file. An analysis plan written before this count is a guess.
2. Convert size to a budget in the units that actually bind — context window, tool calls, and wall-clock — and state which one binds first.
3. Classify the corpus into read-fully, sample, and index-only tiers. Record the rule used to assign each tier, not just the assignment.
4. Declare the sampling fraction per tier as a number. "Reviewed the codebase" is not a scope statement; "read 34 of 210 files, all 9 entry points" is.
5. Identify what the chosen tiers structurally cannot answer, and say so before the analysis rather than after a reader asks.
6. Re-measure when the corpus grows mid-task. A scope claim inherited from an earlier, smaller corpus is stale and silently overstates coverage.
7. Carry the final numbers into the deliverable so every conclusion inherits an explicit denominator.

## Acceptance
- File count, total size, and largest-file size are stated as measured numbers.
- The binding budget is named, and the tier assignment rule is written down.
- Sampling fractions appear as counts with denominators, never as adjectives.
- The deliverable names at least one question the chosen scope cannot answer.
- No coverage claim exceeds the measured read set.
