---
name: claim-verification
audience: specialist
description: "Use to fact-check a finished deliverable's stated facts — its statistics, quotations, named sources, dates, and forecasts — by decomposing them into load-bearing factual claims and matching each to the exact source span that confirms or refutes it (Hard Rule 8 truth gate). Scope is whether what the text asserts as fact is accurate — the truth of the content itself, not whether a task's tooling actually ran. Route web facts to a grounding worker."
---

# Claim Verification

Decompose content into load-bearing claims and verify each against evidence (Hard Rule 8 truth gate).

## Steps
1. Decompose the content into discrete load-bearing claims.
2. Classify each claim: `fact | quote | calculation | forecast | opinion | inference`.
3. Map each claim to the exact evidence span that would confirm it.
4. Verify against sources; for web claims, route a grounding worker (Gemini grounding or research handoff) that returns a typed evidence bundle, then adjudicate it.
5. Reproduce any arithmetic and check units/internal consistency.
6. Return a per-claim verdict: `supported | unsupported | unverifiable`.

## Acceptance
- Every load-bearing claim is classified and mapped to evidence.
- "Unverifiable" is distinguished from "false"; a model cutoff is never treated as verification.
- No PASS while a load-bearing claim remains unverifiable.
