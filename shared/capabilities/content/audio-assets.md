---
id: content/audio-assets
mode: content
title: Audio assets (music · SFX · voice/narration · interactive-audio)
capability_state: degraded-blueprint
state_reason: Two routes exist — the `generate_audio` wrapper (`all·lane-live·metered`, Higgsfield-backed) inherits the SAME honest hold as `content/image` (raw `higgsfield__*` is `verified: no`, reconciliation pending), and `ElevenLabs API` (music/SFX/voice) is genuinely `lane-live` but **Claude-lane-only**. Because the all-lane route is held and the live route is lane-caveated, the conservative card default is `degraded-blueprint` until reconciliation confirms end-to-end.
state_evidence: registry rows — generate_audio = `all·lane-live·metered` (wrapper `verified: yes`); ElevenLabs API = `claude·lane-live·metered`; Higgsfield API = `none·no` (raw prohibited, wrapper only). chrono-vault = `all·yes·subscription`.
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release, credential_change, live_outreach]
cost_note: S3 generation uses the `metered` `generate_audio` wrapper and the `metered` `ElevenLabs API` (both provider-billed) — each needs a budget/rate-limit guard; a hit limit is a typed `needs_tool`/degraded result. `chrono-vault` is subscription. Raw `higgsfield__*` is `verified: no` and is not used.
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

**Notes.** `generate_audio` (Higgsfield-backed) and `ElevenLabs API` are the honest routes; the raw
`higgsfield__*` provider tools are `verified: no` and must never be cited as live. **ElevenLabs is
Claude-lane-only** — on a non-Claude lane the ElevenLabs route is unavailable and the all-lane `generate_audio`
route remains under the reconciliation hold, hence the conservative `degraded-blueprint` default.
Voice-likeness / real-person resemblance routes to `asset-provenance-and-rights-auditor` (never self-cleared).
**Factual voice narration** carrying factual / product / efficacy claims additionally fires the **conditional
Rule-8 truth gate** at S4 (`content-verifier` grounds the claims via `chrono-research-arsenal`; a load-bearing
unverifiable claim ⇒ `needs_tool`/non-PASS before `public_release`) — additive to, not a replacement for, the
independent Rule-6 rights + likeness/consent gates; purely musical / SFX / aesthetic assets skip it. A voice
agent (`create_agent`, outbound calls) fires `credential_change` + `live_outreach`. Interactive-audio design is
tool-free — rendering is a handoff to the music/sound/voice roles.
