---
name: differential-review
status: authored
---

# Differential Review

Review a change by comparing behavior before and after, rather than by reading the new code in isolation.

## Steps
1. Build the two states: base and head. Anything that cannot be built in both states cannot be differentially reviewed — say so instead of guessing.
2. Enumerate observable surfaces the change could move: return values, persisted rows, emitted events, logs, exit codes, wire formats, timing, and error text.
3. For each surface, predict the intended delta from the change's stated intent, then measure the actual delta.
4. Treat every unpredicted delta as a finding until explained. Silent behavior changes are the class this method exists to catch.
5. Pay special attention to the unchanged-looking paths: refactors that preserve the happy path frequently move error, empty, and boundary behavior.
6. Where a surface cannot be measured, construct the smallest differential test that would measure it, and note the gap if the test is out of scope.
7. Compare against a scalar or previous reference implementation where one exists — vectorized, cached, or rewritten code is unverified without it.
8. Record deltas that are intended-but-breaking separately from deltas that are unintended; they need different decisions from the operator.

## Acceptance
- Base and head were both built or run; if not, the review states that it is analysis-only.
- Every moved surface is listed with predicted versus observed behavior.
- Unpredicted deltas are reported as findings or explicitly explained.
- Error, empty, and boundary paths are covered, not just the happy path.
- Intended-breaking and unintended changes are distinguished.
