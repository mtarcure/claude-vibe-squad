---
name: accessible-media-authoring
status: authored
---

# Accessible Media Authoring

Author alt-text, captions, and transcripts for generated or third-party media to accessibility standards.

## Steps
1. Perceive the asset (multimodal ingest); if it can't be perceived, request it or report `capability_gap` — never invent content.
2. Write alt-text that conveys function/meaning, not a literal pixel description; keep decorative assets marked decorative.
3. Author captions with timing, speaker labels, and non-speech sound cues.
4. Author a complete transcript covering all spoken and meaningful non-speech audio.
5. Verify each artifact against the source asset.

## Acceptance
- Missing alt-text/captions/transcript is a PASS-blocker, not a warning.
- Captions are timed and complete; transcript covers all audio.
- No transcript/alt content invented for media that could not be perceived.
