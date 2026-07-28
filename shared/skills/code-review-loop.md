---
name: code-review-loop
status: authored
---

# Code Review Loop

Run a review as a bounded, converging loop instead of an open-ended critique, so it terminates on evidence rather than exhaustion.

## Steps
1. Establish the subject: the exact diff, base ref, and stated intent. A review without a fixed base is not reproducible.
2. Read the intent first, the diff second. Findings are deviations from stated intent or from invariants the surrounding code relies on — not deviations from personal preference.
3. Pass one — correctness: trace each changed path for wrong results, unhandled states, broken invariants, and concurrency or lifetime errors.
4. Pass two — blast radius: find callers, persisted data, and public contracts the change touches; a locally-correct change can still be globally wrong.
5. Pass three — quality: naming, duplication, and dead code, reported only when they impede future correctness. Never let this pass outrank pass one.
6. Rank findings with `review-severity-ladder`, and validate each against `claim-validation-gate` before writing it down.
7. Emit a verdict, not a mood: approve, or request changes with a specific, checkable list. Every requested change names the file, the line, and the failing scenario.
8. On the next iteration, re-review only the delta plus anything the delta invalidates. Close findings explicitly as fixed, disputed, or accepted-as-residual.
9. Stop when no finding above the agreed severity floor survives verification. Escalating the threat model to keep finding issues is a failure of the loop, not diligence.

## Acceptance
- The review names its base ref and the intent it reviewed against.
- Every finding states a concrete failing scenario, not a general concern.
- Findings are severity-ranked and the verdict follows from the ranking.
- Each iteration closes prior findings explicitly; none are silently dropped.
- The loop terminates on a stated floor rather than on reviewer fatigue.
