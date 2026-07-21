---
id: content/video
mode: content
title: Video / motion asset generation
capability_state: live
state_reason: The core video generation path is served by the live, governed `generate_video` wrapper (chrono-media-studio plugin) across all lanes. No unverified tool is load-bearing on the canonical pipeline.
state_evidence: registry rows — generate_video = `all·lane-live·metered` (verified: yes).
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
cost_note: S3 generation uses the metered `generate_video` wrapper (provider-billed) and needs a budget or rate-limit guard — a hit limit is a typed `needs_tool`/degraded result. `chrono-vault` is subscription lane-native. Raw `higgsfield__*` is `verified: no` and is not used.
---

**When to use:** produce a video / motion asset as a content deliverable. Media specialists are `tool_gated`
to the lane hosting the content-engineer plugin. S1–S2 collapse (short capability).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (concept + storyboard) | `video-director`, `brand-voice` | — | `terminology-memory` (authored) | — |
| **S3** Produce (generate + edit) | `video-director`, `video-editor` | `generate_video` (all · lane-live · metered) | — | paid_media |
| **S4** Verify (rights + conditional truth) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor`, `content-verifier` | `chrono-research-arsenal` (all · lane-live · subscription), `view_image` (codex · yes · subscription) | `rights-and-provenance-gate` (authored), `consent-and-likeness-check` (authored), `claim-verification` (authored) | truth-rights overlay — **Rule-6** rights/provenance gate (machine record; non-PASS/stale subject-hash blocks) AND independent likeness/consent check (both mandatory); **conditional Rule-8** truth gate — a video carrying factual/product/efficacy claims requires `content-verifier` grounding (unverifiable load-bearing claim ⇒ `needs_tool`/non-PASS before release); `view_image` covers extracted stills / poster frames / animated-GIF evidence only — NOT temporal / full-video review (no verified video-viewing route); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `video-editor` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `generate_video` is the governed, live route. Raw `higgsfield__generate_video` remains `verified: no` and must never be used. Pure video generation is restricted to the wrapper. A backup lane without the wrapper produces a TBASF blueprint and terminates `capability_gap` — never a false success. Recognizable voice or face resemblance routes to `asset-provenance-and-rights-auditor` (never self-cleared). Purely aesthetic/non-factual assets skip S4 verification; factual claims require `content-verifier` grounding. Still-frame inspection on S4 (`view_image`) is for static poster frames or extracted GIFs and does NOT substitute for full, temporal video review.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for factual, product, or efficacy claims made in videos.
2. **Post-Production Video Manipulation (Higgsfield):** Non-generation utility actions are approved for exploratory discovery via `models_explore` (`partial`, free), and metered manipulation via `higgsfield__motion_control`, `higgsfield__reframe`, and `higgsfield__upscale_video` (`partial`, metered). Executing any paid manipulation routes through a `needs_tool:paid_media` profile requiring the `paid_media` gate and `get_cost:true` preflight.
3. **Engagement and Retention Analysis:** S4 pre-ship engagement scoring can utilize `higgsfield__virality_predictor` (`partial`, metered) via a `needs_tool:paid_media` profile with mandatory `get_cost:true` preflight.
