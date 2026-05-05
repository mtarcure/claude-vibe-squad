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

- `source_namespace: content` stores content specialists; model lead choice still comes from the specialist map.
- Gemini is preferred for media and multimodal work when access is verified.
- Technical docs can require code-derived review by GPT/Codex or Claude.
- Publishing, posting, and live sends are approval-gated.

## Gates

- Operator approval before publish, external send, public release language, paid media, or claims about private work.
- Citation check for factual content.
- Run `vibecoding-check` before the final package.
