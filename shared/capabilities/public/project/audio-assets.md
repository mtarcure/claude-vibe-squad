---
id: project/audio-assets
mode: project
title: Audio assets (music · SFX · voice/narration · interactive-audio)
overlays: [truth-rights, review, privacy, memory]
gates: [paid_media, public_release, credential_change, live_outreach]
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

**When to use:** produce music, sound effects, voice/narration (TTS), or interactive-audio design as a content
deliverable. Media specialists are `tool_gated` to the lane hosting the chrono-media-studio / ElevenLabs plugins
(ElevenLabs is Claude-lane-only). Interactive-audio design routes rendering to the music/sound/voice roles.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | — | memory overlay (recall); brief |
| **S1** Frame (brief + audio-event map) | `interactive-audio-designer`, `brand-voice` | — | `interactive-audio-design`, `audio-event-map-authoring` | — |
| **S3** Produce (music / SFX / voice) | `music-composer`, `sound-designer`, `voice-narrator`, `voice-agent-builder` | `generate_audio`, `ElevenLabs API` | `audio-event-map-authoring`, `voice-consistency-audit` | TBASF blueprint unless the exact route has a current receipt; `credential_change` (voice agent); `live_outreach` (agent outbound) |
| **S4** Verify (rights/likeness + conditional truth) | `skeptic`, `sound-designer`, `asset-provenance-and-rights-auditor`, `content-verifier` | `chrono-research-arsenal` | `rule6-rights-gate`, `claim-verification` | truth-rights overlay — **Rule-6** rights gate (machine record) AND independent voice/likeness → consent check (both mandatory); **conditional Rule-8** truth gate — factual narration carrying factual/product/efficacy claims requires `content-verifier` grounding (unverifiable load-bearing claim ⇒ `needs_tool`/non-PASS before release); privacy if a real person |
| **S5** Review/Gate | `skeptic`, `operator` | — | — | review overlay; `paid_media`, `public_release`, `credential_change` |
| **S6** Ship/Deliver (package) | `sound-designer` | — | — | — |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** `generate_audio` is Gemini/Lyria music only; it is not Higgsfield-backed and does not imply TTS,
voice cloning, SFX, or agent creation. Those operations belong to the separate Claude ElevenLabs sibling MCP,
which remains available-gated/unproven until role-scoped credential and semantic receipts exist. Voice-likeness
/ real-person resemblance routes to `asset-provenance-and-rights-auditor`
(never self-cleared). Factual voice narration carrying factual/product/efficacy claims additionally fires the S4
conditional Rule-8 truth gate.

**Optional Enhancement Profiles (prose-only `needs_tool`):**
1. **Google Search Grounding:** Live on the Gemini lane as a first-class, subscription-tier truth-gate verifier for factual claims made in audio narration.
2. **Higgsfield voice (`create_voice`/`dubbing`):** Non-generation Higgsfield voice utility actions are available via the `Higgsfield non-generation surface` (`partial` state, metered) as an optional prose-only profile. It requires the S4 voice-likeness/consent-likeness check (Rule-6 rights gate) and `get_cost:true` preflight.
