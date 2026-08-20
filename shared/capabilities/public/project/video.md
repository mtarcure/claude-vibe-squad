---
id: project/video
mode: project
title: Video / motion asset generation
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release]
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

**When to use:** produce a video / motion asset as a content deliverable. Media specialists are `tool_gated`
to the lane hosting the chrono-media-studio plugin. S1–S2 collapse (short capability).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); brief |
| **S1** Frame (concept + storyboard) | `video-director`, `brand-voice` | — | `locale-adaptation` | — |
| **S3** Produce (generate + edit) | `video-director`, `video-editor` | `generate_video` | — | paid_media |
| **S4** Verify (rights + conditional truth) | `skeptic`, `brand-voice`, `asset-provenance-and-rights-auditor`, `content-verifier` | `chrono-research-arsenal`, `view_image` | `rule6-rights-gate`, `claim-verification` | truth-rights overlay — **Rule-6** rights/provenance gate (machine record; non-PASS/stale subject-hash blocks) AND independent likeness/consent check (both mandatory); **conditional Rule-8** truth gate — a video carrying factual/product/efficacy claims requires `content-verifier` grounding (unverifiable load-bearing claim ⇒ `needs_tool`/non-PASS before release); `view_image` covers extracted stills / poster frames / animated-GIF evidence only — NOT temporal / full-video review (no verified video-viewing route); privacy overlay if a real person's likeness |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release` |
| **S6** Ship/Deliver (package) | `video-editor` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `generate_video` is the governed, live route. Raw `higgsfield__generate_video` remains `verified: no` and must never be used. Pure video generation is restricted to the wrapper. A backup lane without the wrapper produces a TBASF blueprint and terminates `capability_gap` — never a false success. Recognizable voice or face resemblance routes to `asset-provenance-and-rights-auditor` (never self-cleared). Purely aesthetic/non-factual assets skip S4 verification; factual claims require `content-verifier` grounding. Still-frame inspection on S4 (`view_image`) is for static poster frames or extracted GIFs and does NOT substitute for full, temporal video review. S1's terminology gate remains mandatory: `locale-adaptation` enforces the operator-supplied glossary and do-not-translate list, and does not invent a durable glossary store.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for factual, product, or efficacy claims made in videos.
2. **Post-Production Video Manipulation (Higgsfield):** Non-generation utility actions are approved for exploratory discovery via `models_explore` (`partial`, free), and metered manipulation via `higgsfield__motion_control`, `higgsfield__reframe`, and `higgsfield__upscale_video` (`partial`, metered). Executing any paid manipulation routes through a `needs_tool:paid_media` profile requiring the `paid_media` gate and `get_cost:true` preflight.
3. **Engagement and Retention Analysis:** S4 pre-ship engagement scoring can utilize `higgsfield__virality_predictor` (`partial`, metered) via a `needs_tool:paid_media` profile with mandatory `get_cost:true` preflight.
