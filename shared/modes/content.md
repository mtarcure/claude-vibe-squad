---
name: content
version: 1.1
primary_mode_namespace: content
status: active
phases: 8
---

# Mode: Content

For writing, editing, design, media, campaigns, and publishing packages.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Scope and audience | Chrono direct |
| 1 | Brief | `editor`, `brand-voice` |
| 2 | Research pack | `research`, `knowledge-librarian`, `skeptic` |
| 3 | Strategy | `social-strategist`, `brand-voice` |
| 4 | Outline | `editor`, `technical-writer` |
| 5 | Draft or asset creation | `content-creator`, `media-producer`, `designer` |
| 6 | Review and polish | `editor`, `skeptic`, `brand-voice` |
| 7 | Package | `technical-writer`, `vibecoding-check` |

## Dispatch Notes

- `source_namespace: content` only stores content specialists; the model lead comes from `shared/routing.md`, never the namespace.
- **Media-production specialists are `tool_gated`**: they route to the lane hosting the content-engineer plugin (higgsfield/elevenlabs); the model is secondary. Text-content routes on capability — `copywriter`/`social-strategist`/copy-edit on gemini (`gemini-3.5-flash`); developmental `editor` and `brand-voice` governance on claude (`claude-fable-5`).
- Technical docs (`technical-writer`) are claude-primary with codex review for code-derived accuracy.
- Publishing, posting, paid media, and live sends are `operator_gate` (Hard Rule 6).

## Gates

- Operator approval before publish, external send, public release language, paid media, or claims about private work.
- Pre-publication gates: `content-verifier` (Rule 8 truth gate — facts/citations) and `asset-provenance-and-rights-auditor` (Rule 6 rights gate — generated/third-party media). Both emit a machine-readable gate record; a non-PASS or stale-hash gate blocks publish.
- Run `vibecoding-check` before the final package.
