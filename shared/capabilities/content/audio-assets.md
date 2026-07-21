---
id: content/audio-assets
mode: content
title: Audio assets (music · SFX · voice/narration · interactive-audio)
capability_state: live
state_reason: The core audio generation pipeline is served by two live routes — the governed `generate_audio` wrapper (chrono-media-studio plugin) across all lanes, and the `ElevenLabs API` (music/SFX/voice) on the Claude lane. No unverified tool is load-bearing on the canonical path.
state_evidence: registry rows — generate_audio = `all·lane-live·metered` (verified: yes); ElevenLabs API = `claude·lane-live·metered` (verified: yes).
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release, credential_change, live_outreach]
cost_note: S3 generation uses the metered `generate_audio` wrapper and the metered `ElevenLabs API` (both provider-billed) — each needs a budget/rate-limit guard; a hit limit is a typed `needs_tool`/degraded result. `chrono-vault` is subscription. Raw `higgsfield__*` is `verified: no` and is not used.
---

**When to use:** produce music, sound effects, voice/narration (TTS), or interactive-audio design as a content
deliverable. Media specialists are `tool_gated` to the lane hosting the content-engineer / ElevenLabs plugins
(ElevenLabs is Claude-lane-only). Interactive-audio design routes rendering to the music/sound/voice roles.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall); brief |
| **S1** Frame (brief + audio-event map) | `interactive-audio-designer`, `brand-voice` | — | `interactive-audio-design` (authored), `audio-event-map-authoring` (authored) | — |
| **S3** Produce (music / SFX / voice) | `music-composer`, `sound-designer`, `voice-narrator`, `voice-agent-builder` | `generate_audio` (all · lane-live · metered), `ElevenLabs API` (claude · lane-live · metered) | `audio-event-map-authoring` (authored), `voice-consistency-audit` (stub) | `credential_change` (voice agent); `live_outreach` (agent outbound) |
| **S4** Verify (rights/likeness + conditional truth) | `skeptic`, `sound-designer`, `asset-provenance-and-rights-auditor`, `content-verifier` | `chrono-research-arsenal` (all · lane-live · subscription) | `rights-and-provenance-gate` (authored), `consent-and-likeness-check` (authored), `claim-verification` (authored) | truth-rights overlay — **Rule-6** rights gate (machine record) AND independent voice/likeness → consent check (both mandatory); **conditional Rule-8** truth gate — factual narration carrying factual/product/efficacy claims requires `content-verifier` grounding (unverifiable load-bearing claim ⇒ `needs_tool`/non-PASS before release); privacy if a real person |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release`, `credential_change` |
| **S6** Ship/Deliver (package) | `sound-designer` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** `generate_audio` (Higgsfield-backed) and `ElevenLabs API` are the governed, live routes. Raw
`higgsfield__generate_audio` remains `verified: no` and must never be used. **ElevenLabs is
Claude-lane-only** — on a non-Claude lane the ElevenLabs route is unavailable and the all-lane `generate_audio`
route serves the core pipeline. Voice-likeness / real-person resemblance routes to `asset-provenance-and-rights-auditor`
(never self-cleared). Factual voice narration carrying factual/product/efficacy claims additionally fires the S4
conditional Rule-8 truth gate.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for factual claims made in audio narration.
2. **Higgsfield voice (`create_voice`/`dubbing`):** Non-generation Higgsfield voice utility actions are available via the `Higgsfield non-generation surface` (`partial` state, metered) as an optional prose-only profile. It requires the S4 voice-likeness/consent-likeness check (Rule-6 rights gate) and `get_cost:true` preflight.
