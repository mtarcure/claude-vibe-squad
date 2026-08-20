---
name: rule8-truth-gate
audience: specialist
description: "Use at S4 before an investigation, article, campaign, narration, or screen production with external-world assertions may advance: require returned source bundles, enforce the requested recency interval for every decision-critical premise, reject unmapped items, and emit the mandated PASS/needs_tool truth record."
type: skill
---

# Rule-8 Truth Gate

Combines the release-gate portions of `claim-verification` + `citation-audit` into one invokable check. Given a
deliverable's claims plus a returned citation / grounding-result set, it decides whether each load-bearing claim
is supported by a returned citation within the requested recency window, and emits a machine-checkable gate
record. A model cutoff is never verification evidence; grounding is a first-class stage, not a hope that the
reviewer supplies evidence later.

## Procedure
1. **Decompose** the content into discrete claims and mark each **load-bearing** (a conclusion the deliverable
   depends on) or **non-load-bearing / backgrounded**. Classify each: `fact | quote | calculation | forecast |
   opinion | inference`. **Every load-bearing claim is gated — INCLUDING a load-bearing inference** (a reasoned
   conclusion the deliverable rests on): an inference is NOT exempt because it is framed as reasoning rather than
   quoted — its supporting premises/evidence must map to returned citations, or it is `unverifiable` →
   `needs_tool`. Only a genuine opinion, or non-load-bearing / backgrounded reasoning, passes ungated.
2. **Ground** each load-bearing web/factual claim: route a grounding worker (Gemini `Google Search grounding`
   or a research-namespace handoff) that returns a typed evidence bundle of citations/search results. If no
   grounding tool is available for a load-bearing claim, that claim is `unverifiable` → the gate is `needs_tool`.
3. **Map claim → citation** (`claim_to_citation`): each load-bearing claim — AND each load-bearing inference, via
   the evidence for its premises — must map to a specific returned citation, not to model prose. Read the source
   and confirm it SUPPORTS the claim/premise (not merely mentions the topic); for an inference, also confirm the
   reasoning is valid over the mapped premises. Preserve quote context.
4. **Resolve + date-check every citation** (`date_window`): resolve each citation, record accessed-at; a
   citation that 404s or was invented is unverifiable. Confirm publication/event dates fall inside the requested
   `date_window`, and check for retractions/corrections. A claim supported only by a citation outside the window
   is not fresh-supported.
5. **Reproduce arithmetic**; check units and internal consistency. Label vendor/provider performance claims as
   vendor claims unless reproduced on a Vibe-Squad benchmark.
6. **Reject unsupported** (`reject_unsupported`): any load-bearing claim OR load-bearing inference that does not
   map to an in-window returned citation is dropped or the gate fails — never PASS on prose or on unbacked
   reasoning.
7. **Emit the gate record** (see below).

## Machine gate record (emit this)
```
rule8_truth_gate:
  result: PASS | needs_tool          # PASS only if `unverifiable` is empty; needs_tool if ANY load-bearing claim OR load-bearing inference is unmapped/unsupported/unverifiable
  claim_to_citation: true            # policy applied: every load-bearing claim AND load-bearing inference (via its premises) mapped to a returned citation
  date_window: <explicit interval>   # e.g. 24h / 7d / 90d / task-scoped — never true/false
  reject_unsupported: true           # unsupported/out-of-window load-bearing items were dropped or failed the gate
  claims_checked: <n>
  load_bearing_inferences_checked: <n>
  citations_resolved: <n> / <n>
  unverifiable: [<load-bearing claim/inference ids>]   # MUST be empty for a PASS; if non-empty, result MUST be needs_tool
```

## When to invoke
- The S4 Verify (Rule-8) step of `research/investigation-synthesis`, `content/editorial-longform`,
  `content/marketing-campaign`, `content/audio-assets`, `content/video`.
- Any deliverable asserting factual / product / efficacy claims before publish.

## When NOT to invoke
- Pure opinion / creative pieces with no load-bearing factual claims or load-bearing inferences.
- As a substitute for the independent cross-family reviewer — this is the primary's self-gate, not the review.

## Acceptance
- Every load-bearing claim AND every load-bearing inference is classified and mapped to a returned in-window
  citation (an inference via the evidence for its premises), or the gate is `needs_tool` (not PASS) — the emitted
  `result` is PASS only when `unverifiable` is empty. A load-bearing inference never PASSes on reasoning alone.
  "Unverifiable" is distinguished from "false"; a model cutoff is never verification.
- Vendor claims are labeled; no corroboration is fabricated. Quotes keep their context.

## Notes — source boundary + cross-lane home
- **Partial fusion:** this gate owns the aggregate S4 release decision and citation-recency policy from
  `shared/skills/claim-verification.md` + `shared/skills/citation-audit.md`. It does not emit the exact evidence
  span and `supported | unsupported | unverifiable` verdict for every individual statement; invoke
  `claim-verification` when that statement-level adjudication is required.
- **Canonical home:** `.claude/skills/rule8-truth-gate/SKILL.md`. Because its audience is `specialist`,
  `model-lanes/SKILL-HOMES.md` requires `.agents/skills/rule8-truth-gate/SKILL.md` to be a byte-identical regular
  file mirror.
