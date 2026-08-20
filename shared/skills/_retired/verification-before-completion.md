---
name: verification-before-completion
retired: "retired — straight duplicate of the loaded superpowers plugin skill of the same name; plugin is the survivor. Repo-specific worked example kept here; flagged in the task report."
status: authored
description: Use when about to claim work is complete, fixed, or passing — run the check that would falsify each claim and read its output before emitting the claim; evidence precedes assertion (Hard Rule 8).
---

# Verification Before Completion

A claim of done is a prediction until the verifying command has run and its output has been read. Verify in the same session, after the last edit, and attach the evidence next to the claim — or downgrade the status honestly.

## When to use
- About to write `status: complete` in a response envelope, or "fixed"/"passing"/"green" in any artifact or report.
- About to hand off work whose packet lists success criteria, validators, or a test floor.
- Tempted to reason "the edit is small, it should work" or to reuse a check result from before a subsequent edit.

## Inputs
- The exact claims the completion message will make (tests pass, N rows changed, validator green, file exists).
- The packet's success criteria and verification contract, including any known-failure baseline.
- The commands or observations that can falsify each claim.

## Steps
1. Enumerate every claim the completion message will make. A claim you cannot list is a claim you cannot verify.
2. For each claim, name the cheapest check that would falsify it. If no falsifying check exists, weaken the claim to what is observable ("wrote the config" not "the config works").
3. Run each check now, in the current state. Evidence gathered before the most recent edit is stale — an edit invalidates every earlier run that touched its blast radius.
4. Read the full output, not the exit code. Count the counts: a suite that passes with fewer tests than the baseline is a regression wearing green. Read failure names, not just failure totals.
5. Compare against the stated baseline. A pre-existing failure is acceptable only if it is the same failure, by name — "1 fail" matching "1 fail" is not equivalence.
6. Paste the evidence into the artifact adjacent to the claim it supports, trimmed to the decisive lines.
7. If any check fails or cannot be run: the status is not `complete`. Fix and re-verify, or return `needs_review`/`blocked` with the exact failing output. A downgraded honest status costs one round-trip; a false `complete` costs the operator's trust in every future `complete`.

## Outputs
- A completion message in which every claim is paired with fresh, pasted evidence.
- A status that matches the evidence, including downgrades when it doesn't.

## Failure modes
- **Exit-code verification** — `$? == 0` read as "passing" while the output says "0 tests collected".
- **Stale evidence** — checks run before the final edit, presented as if they cover it.
- **Proxy verification** — "the file exists" standing in for "the content is correct"; "it compiles" for "it works".
- **Baseline drift** — a new failure accepted because the old baseline also had "a failure".
- **Summary inflation** — writing "29/29" when the terminal said 28/29; the reviewer will run it, and the delta is now a credibility incident, not a typo.
- **Should-work reasoning** — shipping a prediction dressed as an observation.

## Worked example
A registry change claims: "validators green, test floor held." Enumerated claims: (1) `bin/validate-capabilities.sh` reports 29/29; (2) `bin/test` matches the measured floor of 6 pass / 1 fail / 3 skip; (3) the 1 fail is the pre-existing `dispatch enforcement` failure. All three re-run after the final TSV edit. Output for (2) shows 6/1/3 — but step 5 requires checking the failure's name, and it reads `dispatch enforcement`, matching the baseline. All three outputs pasted into the artifact under their claims. Had the failing test been any other name, the correct emission was `blocked` with that output — not `complete` with a matching count.

## Acceptance
- Every claim in the completion message names the check that could have falsified it.
- Every check ran after the last edit to anything in its blast radius.
- Output is pasted, and counts/names in the prose match the pasted output exactly.
- Any unverifiable or failed claim downgraded the status rather than shading the summary.
