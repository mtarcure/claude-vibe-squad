# Private Config

Do not commit local secrets, browser state, raw logs, or live task outputs.

Private/local:

- API keys and OAuth tokens
- `~/.claude`, `~/.codex`, `~/.gemini`, `~/.kimi` auth state
- legacy Chrono repo at `~/chrono`
- Chrono Vault / Obsidian knowledge vault contents when they include private operator memory
- Chrome profiles and CDP session state
- `_state/tmux-logs/`
- `_state/active-tasks.json`
- Department inbox, active, outbox, and archive task files
- Doctor, cleanup, morning brief, and nightly logs

Public/product:

- `bin/`, `scripts/`, and `shared/` source files
- `departments/*/LEAD.md`
- `departments/*/specialists/*.md`
- `shared/modes/`, `shared/mode-profiles/`, `shared/skills/`
- Curated examples under `examples/`
- CI workflows and validation docs
- Public references to Chrono MCPs as optional integrations, without private implementation paths or credentials

Use `examples/active-tasks.sample.json` when documenting task registry shape.
