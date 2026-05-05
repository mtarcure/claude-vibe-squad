# Capability Manifest: media-producer

Status: current-system capability
Owner: content namespace
Canonical current specialist: `departments/content/specialists/media-producer.md`
Related tool surface: `chrono-content-engineer`

## Role Contract

`media-producer` owns image, video, audio, voiceover, music, and media-editing assets. It also owns provider provenance, cost gates, and safe handoff of generated assets.

## Required Tools

- `chrono-content-engineer` for provider routing when verified.
- `shared/api-catalog.md` for provider status.
- Asset path/provenance log.
- Cost/credit and approval tracking.

## Safety Boundaries

- No real-person likeness, real-person voice cloning, copyrighted/trademarked generation, or paid generation without operator approval.
- No external publish/send action.
- No claim that Higgsfield, ElevenLabs, Sora, Veo, Imagen, Lyria, or any provider is live unless the catalog marks the active route verified.

## Live Dispatch Proof

1. Chrono dispatches a safe sample asset task to content namespace with `specialist: media-producer`.
2. content namespace dispatches `media-producer`.
3. Specialist either produces an asset/provenance log or returns a structured missing-provider/auth report.
4. Active registry closes.
