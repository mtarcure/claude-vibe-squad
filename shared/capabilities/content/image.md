---
id: content/image
mode: content
title: Image asset generation
capability_state: live
state_reason: The core image generation path is served by the live, governed `generate_image` wrapper (chrono-media-studio plugin) across all lanes. No unverified tool is load-bearing on the canonical pipeline.
state_evidence: registry rows — generate_image = `all·lane-live·metered` (verified: yes).
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
cost_note: S3 generation uses the metered `generate_image` wrapper (provider-billed) and needs a budget or rate-limit guard. S0/S7 archiving via `chrono-vault` and S4 verification are subscription-tier.
---

**When to use:** produce still images / graphics as a content deliverable. Media specialists are
`tool_gated` to the lane hosting the content-engineer plugin. Steps S1–S2 collapse (short capability).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (concept) | `image-designer`, `brand-voice` | — | `terminology-memory` (authored) | — |
| **S3** Produce (generate) | `image-designer` | `generate_image` (all · lane-live · metered) | — | paid_media |
| **S4** Verify (+ rights) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor` | `view_image` (codex · yes · subscription), `claude native vision` (claude · yes · subscription) | `rights-and-provenance-gate` (authored), `consent-and-likeness-check` (authored) | truth-rights overlay — Rule-6 rights gate (machine record; non-PASS/stale subject-hash blocks); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `image-designer` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `generate_image` is the governed, live route. Raw `higgsfield__generate_image` remains `verified: no` and must never be used; pure image generation is restricted to the wrapper. A backup lane without the wrapper produces a TBASF blueprint and terminates `capability_gap` — never a false success. Real-person resemblance routes to `asset-provenance-and-rights-auditor` (never self-cleared).

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Design Systems & Text-to-Design (Stitch):** If layout generation or visual system updates are required, the `Stitch` extension on the Gemini lane is available (`partial` state, subscription-tier, backend may meter). Since its design write capabilities remain un-smoked, any automated design writes route through the `needs_tool` pre-approval profile.
2. **Post-Production Image Manipulation (Higgsfield):** Non-generation utility actions are approved for exploratory discovery via `models_explore` (`partial`, free), and metered manipulation via `higgsfield__upscale_image`, `higgsfield__outpaint_image`, and `higgsfield__remove_background` (`partial`, metered). Executing any paid manipulation routes through a `needs_tool:paid_media` profile requiring the `paid_media` gate and `get_cost:true` preflight.
3. **Local vision alternative (nanobanana):** `nanobanana` is installed on the Gemini lane as a `partial`, metered image model. Because it overlaps the governed `generate_image` wrapper, its usage is restricted to opt-in exploration and does not replace the wrapper.
4. **Visual Evidence Verification:** S4 visual verification utilizes `claude native vision` (yes, subscription) on the Claude lane for high-fidelity inspect-element evidence review.
5. **Figma design retrieval:** Smoked read-only figma design connector is available on the Chrono lane for visual design context. Automated lane write access is pending.
