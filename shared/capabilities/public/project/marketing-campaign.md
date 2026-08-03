---
id: project/marketing-campaign
mode: project
title: Marketing campaign (landing/product/blog copy + multi-channel social)
overlays: [review, truth-rights, memory]
gates: [public_release, paid_media, live_outreach]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** produce marketing copy — landing/product/blog pages and multi-channel social — as a content
deliverable. Live scope is copy CREATION; distribution/send is operator-gated (see Notes). Product/efficacy
claims route through the Rule-8 truth gate.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall); brief |
| **S1** Frame (offer + channels + audience) | `copywriter`, `brand-voice`, `social-strategist` | `firecrawl`, `chrono-research-arsenal`, `codex --search` | `keyword-clustering`, `technical-seo-audit` | — |
| **S3** Produce (copy + social variants) | `copywriter`, `brand-voice`, `growth-and-search-analyst` | `chrono-research-arsenal` | `keyword-clustering`, `technical-seo-audit` | — |
| **S4** Verify (truth + brand) | `brand-voice`, `skeptic`, `content-verifier` | `chrono-research-arsenal` | `claim-verification`, `citation-audit` | truth-rights overlay — Rule-8 truth gate for product/efficacy claims |
| **S5** Review/Gate | `skeptic`, `cross-family-reviewer`, `operator` | — | — | review overlay; `public_release`, `paid_media`, `live_outreach` (per-message send approval) |
| **S6** Ship/Deliver (packaged copy) | `copywriter`, `social-strategist` | `chrono-obsidian` | — | `public_release`; send is operator-gated (`needs_tool`) |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** **The live scope is copy creation, not sending.** Actual multi-channel distribution / email send is
`needs_tool` and operator-gated: `Gmail` is `partial` and the outreach bridge is dry-run only, so a live send
is not claimed here — the `live_outreach` gate is per-message operator approval. `paid_media` (any paid
distribution) is operator-gated. Product/efficacy claims fire the Rule-8 truth gate (`content-verifier`).
Media assets (image/video/audio) are separate content cards.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for product and campaign copy verification.
2. **Visual Layout Generation (Stitch):** Stitch layout edits are available on the Gemini lane (`partial` state, subscription) as an optional visual enhancement profile.
3. **Higgsfield Utilities:** approved for exploratory discovery via `models_explore` (`partial`, free) and campaign engagement score preflighting via `virality_predictor` (`partial`, metered), requiring the `paid_media` gate and `get_cost:true` preflight.
