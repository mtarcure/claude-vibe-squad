# Vibe Squad

Markdown-first multi-model orchestration in a tmux session. **Chrono** — a Claude Code coordinator running `claude --model opus` — is the only operator-facing voice. It routes scoped markdown task packets to four subscription-CLI model lanes (Claude, Codex, Gemini, Kimi), which execute the work as 53 role-based specialists.

## Quick start

```bash
bin/vibe-squad          # thin passthrough to `bin/squad`; alias: `squad up`
```

Starts (or re-attaches) a tmux session named `squad` with six windows: `chrono` (the coordinator you talk to), the four model lanes, and a watchers/status window. Talk to Chrono in window 0; Chrono routes work to specialists and model lanes.

```
Ctrl-b 0 → chrono      Ctrl-b 3 → gemini
Ctrl-b 1 → gpt-codex   Ctrl-b 4 → kimi
Ctrl-b 2 → claude      Ctrl-b 5 → watchers/status
Ctrl-b d → detach (lanes keep running)
```

Other subcommands (see `bin/squad`): `squad stop`, `squad status`, `squad doctor`, `squad attach`, `squad detach`.

Prerequisites: macOS, tmux, logged-in Claude Code / Codex / Gemini / Kimi CLIs, Python 3.11+ (for the MCP servers and the optional daemon).

## Architecture

See `docs/architecture.md`.

Chrono is the only controller and operator-facing voice. Model leads execute scoped markdown packets. Specialists define the work shape. Dispatch is a **markdown mailbox** (`departments/<namespace>/inbox|outbox/`), not a network service.

## Dispatch

Chrono dispatches with `scripts/send-task.sh`, which generates task-packet frontmatter from the routing map and hands off to the hardened `bin/send-task.sh` (auto-snapshot, write-scope checks, dispatch logging, tmux pane nudge):

```bash
scripts/send-task.sh <source-namespace> <body-file> <specialist> [to-model]
```

It writes a markdown packet to `departments/<compatibility_namespace>/inbox/TASK-*.md`; the target model lane processes it and writes a response to `departments/<compatibility_namespace>/outbox/TASK-*-response.md`. Packet fields are defined in `shared/protocol.md`. There is no HTTP dispatch endpoint in the shipped flow.

## Adding a specialist

See `docs/adding-a-specialist.md`.

A specialist is a routing row in `shared/specialist-runtime-map.tsv` plus a markdown brief under `departments/<namespace>/specialists/` (or `shared/specialists/`). Validate with `bin/validate-specialists.sh`.

## Specialist runtime map

`shared/specialist-runtime-map.tsv` is the canonical source of truth for routing. Each row maps a specialist to `best_model_lane`, `review_model`, `source_namespace`, `required_tools`, `safety_level`, `preferred_tools`, and `notes`.

**53 specialists across 7 source namespaces** (counts generated from the TSV):

- **coding** (14): ai-engineer, architect, backend-engineer, code-reviewer, devops-engineer, frontend-engineer, performance-optimizer, product-manager, refactor-cleaner, scraping-engineer, smart-contract-engineer, systems-engineer, test-engineer, ui-engineer
- **content-engineer** (10): copywriter, voice-narrator, music-composer, sound-designer, video-director, video-editor, image-designer, web-builder, game-designer, voice-agent-builder
- **sysmgmt** (8): agentops, finance-analyst, harness-optimizer, knowledge-librarian, loop-operator, mac-ops, memory-curator, personal-ops
- **security** (6): exploit-developer, impact-validator, privacy-steward, scout, security-analyst, threat-modeler
- **shared** (6): planner, prompt-engineer, skeptic, summarizer, triage, vibecoding-check
- **research** (5): data-extraction-engineer, large-context-analyst, learning-coach, research, synthesizer
- **content** (4): brand-voice, editor, social-strategist, technical-writer

`model-lanes/ROSTER.md` is a generated, per-lane view of the same map.

## Protocol

Every dispatch is a markdown file with the frontmatter schema in `shared/protocol.md`. `source_namespace` selects the specialist markdown; `compatibility_namespace` selects the mailbox folder; `to_model` selects the runtime lane.

## Tool catalog

`shared/api-catalog.md` is the capability catalog that specialist briefs bind to: MCP servers, native CLI features, and the local toolchain, each with a `verified:` state. A specialist may only cite `verified: yes` entries.

## MCP servers

MCPs are registered **directly per CLI**, not through a proxy: `~/.claude/settings.json` (`enabledPlugins`), `~/.codex/config.toml`, `~/.kimi/mcp.json`, and `~/.gemini/settings.json`. Each lane connects to its own MCP servers.

## Lifecycle rules

`shared/lifecycle.md` and `shared/memory-discipline.md` codify persistent panes, session management, context discipline, memory hygiene, browser attach rules, and mode cleanup.

## Redesign spec (planned, not built)

`docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` describes a proposed Ink-TUI + FastAPI-daemon redesign that was **not** built. It is retained for design history only; the shipped system is the tmux + markdown-mailbox architecture described above.

## License

AGPL-3.0. See [LICENSE](./LICENSE).
