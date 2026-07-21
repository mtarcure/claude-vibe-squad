---
id: content/marketing-campaign
mode: content
title: Marketing campaign (landing/product/blog copy + multi-channel social)
capability_state: live
state_reason: Campaign copy authoring (landing/product/blog + social variants) is text work backed by live tools — `firecrawl` (competitor/reference scrape, claude·lane-live) and `chrono-research-arsenal` (all·lane-live). No catalog-absent tool is load-bearing on the core authoring path.
state_evidence: registry rows — firecrawl = `claude·lane-live·metered`, chrono-research-arsenal = `all·lane-live·subscription`, chrono-vault = `all·yes·subscription`.
overlays: [review, truth-rights, memory]
gates: [public_release, paid_media, live_outreach]
cost_note: `firecrawl` scraping is `metered` (API-key billed) and needs a budget/rate-limit guard — a hit limit is a typed `needs_tool`/degraded result. The research-arsenal + chrono-* MCPs are subscription. Paid-media distribution and per-message sends are operator-gated, not billed on the authoring path.
---

**When to use:** produce marketing copy — landing/product/blog pages and multi-channel social — as a content
deliverable. Live scope is copy CREATION; distribution/send is operator-gated (see Notes). Product/efficacy
claims route through the Rule-8 truth gate.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (offer + channels + audience) | `copywriter`, `brand-voice`, `social-strategist` | `firecrawl` (claude · lane-live · metered), `chrono-research-arsenal` (all · lane-live · subscription), `codex --search` (codex · yes · subscription) | `keyword-clustering` (authored), `technical-seo-audit` (authored) | — |
| **S3** Produce (copy + social variants) | `copywriter`, `brand-voice`, `growth-and-search-analyst` | `chrono-research-arsenal` (all · lane-live · subscription) | `keyword-clustering` (authored), `technical-seo-audit` (authored) | — |
| **S4** Verify (truth + brand) | `brand-voice`, `skeptic`, `content-verifier` | `chrono-research-arsenal` (all · lane-live · subscription) | `claim-verification` (authored), `citation-audit` (authored) | truth-rights overlay — Rule-8 truth gate for product/efficacy claims |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; `public_release`, `paid_media`, `live_outreach` (per-message send approval) |
| **S6** Ship/Deliver (packaged copy) | `copywriter`, `social-strategist` | `chrono-obsidian` (all · yes · subscription) | — | `public_release`; send is operator-gated (`needs_tool`) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** **The live scope is copy creation, not sending.** Actual multi-channel distribution / email send is
`needs_tool` and operator-gated: `Gmail` is `partial` and the outreach bridge is dry-run only, so a live send
is not claimed here — the `live_outreach` gate is per-message operator approval. `paid_media` (any paid
distribution) is operator-gated. Product/efficacy claims fire the Rule-8 truth gate (`content-verifier`).
Media assets (image/video/audio) are separate content cards.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for product and campaign copy verification.
2. **Visual Layout Generation (Stitch):** Stitch layout edits are available on the Gemini lane (`partial` state, subscription) as an optional visual enhancement profile.
3. **Higgsfield Utilities:** approved for exploratory discovery via `models_explore` (`partial`, free) and campaign engagement score preflighting via `virality_predictor` (`partial`, metered), requiring the `paid_media` gate and `get_cost:true` preflight.
