# Vibe Squad

Multi-model relay TUI. Chrono (Claude Fable 5) coordinates 4 subscription CLIs (Claude, Codex, Gemini, Kimi) to work on tasks in parallel, with 56 role-based specialists and a Python sidecar daemon for orchestration.

## Quick start

```bash
bin/vibe-squad
```

Starts the Ink-based TUI with Chrono in the main pane and 4 model-lane subprocesses. Talk to Chrono; Chrono routes work to specialists and model lanes in parallel.

Prerequisites: macOS, tmux (optional), logged-in Claude Code / Codex / Gemini / Kimi CLIs, Python 3.11+.

## Architecture

See `docs/architecture.md`.

Chrono + daemon own the control plane. Model leads execute. Specialists define the work shape.

## Adding a specialist

See `docs/adding-a-specialist.md`.

Structure: frontmatter contract + body prose. Frontmatter declares lane, model_key, required_tools, preferred_tools. Test via `curl -X POST http://127.0.0.1:9876/task ...`.

## Design spec

See `docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` for the full redesign (runtime architecture, task lifecycle, circuit breaker logic, specialist enforcement, model roster).

## Specialist runtime map

`shared/specialist-runtime-map.tsv` is the canonical source-of-truth for routing. Maps each specialist to best_model_lane, review_model, source_namespace, required_tools, safety_level, preferred_tools, and notes.

56 specialists across 5 departments:
- **coding** (15): backend-engineer, frontend-engineer, refactor-cleaner, etc.
- **content** (4): brand-voice, editor, social-strategist, technical-writer
- **content-engineer** (10): copywriter, voice-narrator, music-composer, video-director, etc.
- **research** (6): scout, research, synthesizer, large-context-analyst, etc.
- **security** (8): security-analyst, exploit-developer, impact-validator, privacy-steward, etc.
- **shared** (9): planner, vibecoding-check, skeptic, triage, memory-curator, etc.
- **sysmgmt** (7): mac-ops, agentops, harness-optimizer, finance-analyst, etc.

## Protocol

Dispatch via `POST http://127.0.0.1:9876/task` with task packet:

```yaml
specialist: <canonical-specialist>
lane: claude | codex | gemini | kimi
model_key: default | hard | deep | etc.
required_tools: [list of MCP:tool]
prompt: <task body>
project: <context>
```

See `shared/protocol.md` for full schema.

## Tool catalog

`shared/tool-catalog.md` lists all MCP servers, tools, and availability per lane.

## Lifecycle rules

`shared/lifecycle.md` and `shared/memory-discipline.md` codify persistent panes, session management, context discipline, memory hygiene, browser attach rules, and mode cleanup.

## License

AGPL-3.0. See [LICENSE](./LICENSE).
