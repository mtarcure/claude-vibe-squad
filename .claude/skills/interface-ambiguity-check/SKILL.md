---
name: interface-ambiguity-check
audience: specialist
description: "Use before implementing against an API, schema, file format, or contract you did not author, especially when units, null/empty/absent behavior, ordering, errors, retries, or idempotency are unstated—pin each load-bearing assumption with documentation, observed producer/consumer behavior, or a probe. Use requirements elicitation for an unclear stakeholder goal; this check resolves a concrete boundary’s semantics."
---

# Interface Ambiguity Check

Two parties meeting at a boundary each hold a private interpretation of it. Before writing code against an interface, make every load-bearing assumption explicit, classify it as documented, observed, or guessed — and eliminate the guesses.

## When to use
- Implementing against an API, schema, TSV/JSON format, function signature, or protocol authored by someone else (including a past task).
- Two independently-built components are about to integrate.
- A packet says "integrate with X" or "consume Y's output" without a contract document.

## Inputs
- The interface artifact: schema, header row, signature, endpoint doc, example payload.
- Real producer/consumer behavior: actual payloads, actual call sites, the parser's source.

## Steps
1. List every element crossing the boundary: each field, parameter, return value, status code, file, and side effect.
2. Run each element through the ambiguity battery: type and units; required vs optional; null vs empty vs absent; ordering and uniqueness guarantees; case, encoding, and delimiter rules; error signaling (exception, code, sentinel, silence); idempotency and retry semantics; which side validates; versioning and evolution rules.
3. Classify each answer: **documented** (cite where), **observed** (cite the real payload, call site, or parser line you inspected), or **assumed** (unpinned).
4. Pin every load-bearing assumption: read the counterpart's source, inspect a real sample, or run a cheap probe. When the boundary's owner must decide — surface the question (in a packet context: `## NEEDS FROM CHRONO`, or `blocked` per specialist rules) instead of implementing a guess whose wrong answer is expensive to unwind.
5. When documentation and observed behavior disagree, the observed behavior wins for implementation — and the disagreement itself is a finding to report, not to silently absorb.
6. Encode pinned answers where the machine can hold them: a strict parser, an assertion, a test that uses a real captured sample rather than a hand-invented one.
7. Record deliberately unpinned residuals as named risks in the artifact, with the trigger that would surface each.

## Outputs
- A boundary table: element → answer → evidence class → citation.
- Enforcement in code or tests for the answers that matter.
- An explicit residual list; an empty one is a claim, not a default.

## Failure modes
- **Happy-path sampling** — pinning semantics from one well-formed example; the ambiguity lives in the edge rows.
- **Doc trust over behavior** — implementing what the doc says while the parser does otherwise; drift between them is common and directional.
- **Convenient interpretation** — resolving ambiguity toward whichever reading is easiest to implement, silently.
- **Symmetric-serialization assumption** — assuming what one side writes is exactly what the other side accepts.
- **Over-asking** — escalating questions the artifact itself answers; questions spend operator attention, so exhaust steps 4–5's evidence paths first.

## Worked example
A task must add rows to a lane-scoped TSV registry. Ambiguity battery on the `lanes` column: is the delimiter comma, pipe, or either? Is `all` a literal lane name or a wildcard? Documentation is silent. Observed: the consuming parser splits with `re.split(r"[|,]", ...)` and expands `all` to the full lane set — both cited by file:line in the artifact. The answers are enforced by running the downstream validator over the new rows rather than trusting the reading. Residual recorded: unknown lane tokens are silently dropped by the intersection with the known-lane set, so a typo in `lanes` fails open — flagged as a risk, not fixed, since the parser is out of scope.

## Acceptance
- Every boundary element appears in the table with an evidence class.
- No load-bearing element remains classified **assumed**.
- Doc-vs-behavior disagreements are surfaced explicitly.
- Pinned answers are machine-enforced where feasible; residuals are named with triggers.
