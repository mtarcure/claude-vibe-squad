---
id: content/editorial-longform
mode: content
title: Editorial / technical longform (articles · docs · ADRs)
capability_state: live
state_reason: Longform authoring is text work backed by live tools — `chrono-research-arsenal` and `Google Search grounding` are live grounding pathways, and `chrono-obsidian` / `chrono-vault` are fully live. No unverified or metered tool is load-bearing on the canonical path.
state_evidence: registry rows — chrono-research-arsenal = `all·lane-live·subscription`, Google Search grounding = `gemini·yes·subscription`, chrono-obsidian/chrono-vault = `all·yes·subscription`.
overlays: [review, truth-rights, memory]
gates: [public_release]
cost_note: subscription lane-native — `chrono-obsidian`/`chrono-vault` and the Google Search grounding tools. No paid media provider is on the path; no metered tool is required for the core deliverable.
---

**When to use:** write an article, technical doc, ADR, or other longform text deliverable. Load-bearing
factual claims must be grounded (truth-rights / Rule-8); a model cutoff is never verification evidence.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (outline + audience) | `editor`, `technical-writer`, `brand-voice` | — | `brainstorming` (SKILL.md), `terminology-memory` (authored), `scope-decomposition` (stub) | — |
| **S3** Produce (draft) | `technical-writer`, `editor` | `chrono-research-arsenal` (all · lane-live · subscription), `chrono-obsidian` (all · yes · subscription), `codex --search` (codex · yes · subscription) | `terminology-memory` (authored), `structured-data-authoring` (authored) | — |
| **S4** Verify (truth + edit) | `editor`, `skeptic`, `content-verifier` | `chrono-research-arsenal` (all · lane-live · subscription), `Google Search grounding` (gemini · yes · subscription) | `claim-verification` (authored), `citation-audit` (authored) | truth-rights overlay — Rule-8 truth gate (factual claims grounded; unverifiable ⇒ `needs_tool`, not PASS) |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; `public_release` |
| **S6** Ship/Deliver (publish) | `technical-writer` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored) | `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Truth grounding is a first-class S4 stage, not review-lane alone: a load-bearing web/factual claim
without a grounding-tool evidence bundle is `needs_tool`/unverifiable — the primary must NOT PASS and hope the
reviewer supplies evidence later (`content-verifier` owns the Rule-8 gate). No media generation here (that is
`content/image`/`video`/`audio-assets`). Localization and accessibility are overlays/handoffs, not this card.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Perplexity Sonar Alternative:** For structured + recency search checks on the Codex lane, `Perplexity Sonar structured+recency` is available (`partial` state, metered). When activated via a `needs_tool` profile, it enforces strict truth-gate filters (`claim_to_citation=true`, `date_window=7d`, `reject_unsupported=true`) ensuring all claims map to returned citation sources.
