---
id: project/editorial-longform
mode: project
title: Editorial / technical longform (articles · docs · ADRs)
overlays: [review, truth-rights, memory]
gates: [public_release]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** write an article, technical doc, ADR, or other longform text deliverable. Load-bearing
factual claims must be grounded (truth-rights / Rule-8); a model cutoff is never verification evidence.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); brief |
| **S1** Frame (outline + audience) | `editor`, `technical-writer`, `brand-voice` | — | `brainstorming`, `locale-adaptation`, `scope-decomposition` | — |
| **S3** Produce (draft) | `technical-writer`, `editor` | `chrono-research-arsenal`, `chrono-obsidian`, `codex --search` | `copy-refinement`, `structured-data-authoring` | — |
| **S4** Verify (truth + edit) | `editor`, `skeptic`, `content-verifier` | `chrono-research-arsenal`, `Google Search grounding` | `claim-verification`, `citation-audit` | truth-rights overlay — Rule-8 truth gate (factual claims grounded; unverifiable ⇒ `needs_tool`, not PASS) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; `public_release` |
| **S6** Ship/Deliver (publish) | `technical-writer` | `chrono-obsidian` | `citation-audit` | `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Truth grounding is a first-class S4 stage, not review-lane alone: a load-bearing web/factual claim
without a grounding-tool evidence bundle is `needs_tool`/unverifiable — the primary must NOT PASS and hope the
reviewer supplies evidence later (`content-verifier` owns the Rule-8 gate). No media generation here (that is
`content/image`/`video`/`audio-assets`). Localization and accessibility are overlays/handoffs, not this card.
The terminology gate remains mandatory: S1 applies supplied glossary/do-not-translate constraints through
`locale-adaptation`, and S3 checks approved terminology through `copy-refinement`; neither assumes a
durable glossary exists, and missing authority stops the terminology-specific work.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Perplexity Sonar Alternative:** For structured + recency search checks on the Codex lane, `Perplexity Sonar structured+recency` is available (`partial` state, metered). When activated via a `needs_tool` profile, it enforces strict truth-gate filters (`claim_to_citation=true`, `date_window=7d`, `reject_unsupported=true`) ensuring all claims map to returned citation sources.
