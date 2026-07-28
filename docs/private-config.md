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
- `_state/board-worktrees/` — per-attempt specialist worktrees created by the board
- `_state/task-registry/` — board attempt/generation bookkeeping
- Department inbox, active, outbox, and archive task files
- Doctor, cleanup, morning brief, and nightly logs

`_state/**` is blanket-ignored, so these are already untracked; the list above is what that rule is protecting.

Public/product:

- `bin/`, `scripts/`, and `shared/` source files
- `model-lanes/*/*` and `departments/*/NAMESPACE.md` shims
- `departments/*/specialists/*.md`
- `shared/modes/`, `shared/mode-profiles/`, `shared/skills/`
- Curated examples under `examples/`
- CI workflows and validation docs
- Public references to Chrono MCPs as optional integrations, without private implementation paths or credentials

Use `examples/active-tasks.sample.json` when documenting task registry shape.
