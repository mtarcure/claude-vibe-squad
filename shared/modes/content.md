---
name: content
version: 1.1
primary_mode_namespace: content
status: active
phases: 8
---

# Mode: Content

For writing, editing, design, media, campaigns, and publishing packages.

## Capabilities

`capability_state` is **derived** and machine-checked by `bin/validate-capabilities.sh` (not hand-set), so this index stays honest by construction. Cards live in `shared/capabilities/content/`. Generated/derived assets fire the Rule-6 rights/provenance gate; factual claims fire the conditional Rule-8 truth gate.

| Capability | State | When |
|---|---|---|
| [Editorial / technical longform](../capabilities/content/editorial-longform.md) | `live` | articles, docs, ADRs, technical longform |
| [Marketing campaign](../capabilities/content/marketing-campaign.md) | `live` | landing/product/blog copy + social — creation live, send is `needs_tool` |
| [Search / discoverability](../capabilities/content/search-discoverability.md) | `live` | on-page SEO / schema / growth — measured impact is `needs_tool` |
| [Image asset generation](../capabilities/content/image.md) | `degraded-blueprint` | stills / graphics — `generate_image` wrapper; Higgsfield reconciliation hold |
| [Video / motion asset generation](../capabilities/content/video.md) | `degraded-blueprint` | video / motion — `generate_video` wrapper; Higgsfield reconciliation hold |
| [Audio assets (music · SFX · voice · interactive)](../capabilities/content/audio-assets.md) | `degraded-blueprint` | music/SFX/voice/interactive — wrappers; ElevenLabs is Claude-lane-only |

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Scope and audience | Chrono direct |
| 1 | Brief | `editor`, `brand-voice` |
| 2 | Research pack | `research`, `knowledge-librarian`, `skeptic` |
| 3 | Strategy | `social-strategist`, `brand-voice` |
| 4 | Outline | `editor`, `technical-writer` |
| 5 | Draft or asset creation | by deliverable — see "Phase 5 — asset routing" below |
| 6 | Review and polish | `editor`, `skeptic`, `brand-voice` |
| 7 | Package | `technical-writer`, `vibecoding-check` |

### Phase 5 — asset routing by deliverable

Phase 5 dispatches the real media specialist(s) for the deliverable being produced (this replaces the
former placeholder roles):

| Deliverable | Specialists |
|---|---|
| Text / copy | `copywriter` |
| Image | `image-designer` |
| Video | `video-director`, `video-editor` |
| Music / SFX | `music-composer`, `sound-designer` |
| Voice / narration | `voice-narrator`, `voice-agent-builder` |
| Interactive audio | `interactive-audio-designer` |

Media generation runs through the live `generate_image` / `generate_video` / `generate_audio` wrappers of
the chrono-media-studio plugin — NOT the raw `higgsfield__*` tools (`verified: no` in `shared/api-catalog.md`).
Media specialists stay `tool_gated` to the plugin-host lane (see Dispatch Notes); ElevenLabs child tools
(music/sfx/voice) are Claude-lane-only.

## Dispatch Notes

- `source_namespace: content` only stores content specialists; the model lead comes from `shared/routing.md`, never the namespace.
- **Media-production specialists are `tool_gated`**: they route to the lane hosting the chrono-media-studio plugin (higgsfield/elevenlabs); the model is secondary. Text-content routes on capability — `copywriter`/`social-strategist`/copy-edit on gemini (`gemini-3.5-flash`); developmental `editor` and `brand-voice` governance on claude (`claude-fable-5`).
- Technical docs (`technical-writer`) are claude-primary with codex review for code-derived accuracy.
- Publishing, posting, paid media, and live sends are `operator_gate` (Hard Rule 6).

## Gates

- Operator approval before publish, external send, public release language, paid media, or claims about private work.
- Pre-publication gates: `content-verifier` (Rule 8 truth gate — facts/citations) and `asset-provenance-and-rights-auditor` (Rule 6 rights gate — generated/third-party media). Both emit a machine-readable gate record; a non-PASS or stale-hash gate blocks publish.
- Run `vibecoding-check` before the final package.
