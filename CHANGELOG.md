# Changelog

## Unreleased

- Rebuilt routing around `Operator -> Chrono -> 4 model leads -> specialists`.
- Added model lead prompts under `model-lanes/`.
- Made `to_model` the runtime selector and `source_namespace` the mailbox/specialist storage selector.
- Removed generated adapter trees and duplicate capability manifests from the public source of truth.
- Simplified public docs around the current v1 model-lane architecture.

## v1.0.0

Initial public release target for the local Vibe Squad command center:

- Chrono coordinator.
- Four model leads: GPT/Codex, Claude, Gemini, Kimi.
- Markdown-first modes, specialist briefs, model lead prompts, task packets, and memory surfaces.
- Filesystem mailbox dispatch with tmux windows.
- Safety gates for review, public release, live sends, credentials, cleanup, and high-blast-radius work.
