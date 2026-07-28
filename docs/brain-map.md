# Brain Map

Status: canonical

Vibe Squad is markdown-first. Scripts launch, watch, validate, and dispatch; markdown owns role behavior and workflow instructions.

## Naming

| Term | Meaning |
|---|---|
| Chrono | The only controller and operator-facing coordinator. |
| CLI vehicle | One of `codex`, `claude`, `gemini`, or `kimi`. The board spawns one fresh per task to execute an assigned specialist brief; it is not a standing process. |
| Specialist | Canonical role selected by Chrono and mapped in `shared/specialist-runtime-map.tsv`. Each specialist binds its own model. |
| Source namespace | Compatibility storage folder for specialist markdown, memory, and mailbox files. |
| Mode | Operator-approved workflow under `shared/modes/` — exactly two: `project` and `bounty`. |

Do not describe source namespaces as model ownership. Kimi does not own research, Claude does not own security, and Codex is not the coding department. Model choice comes from the specialist map, per specialist.

## Source Layers

| Layer | Canonical files |
|---|---|
| Chrono brain | `chrono/SOUL.md`, `chrono/CLAUDE.md`, `chrono/current.md` |
| Per-CLI instructions | `model-lanes/gpt-codex/AGENTS.md`, `model-lanes/claude/CLAUDE.md`, `model-lanes/gemini/GEMINI.md`, `model-lanes/kimi/KIMI.md` |
| Specialist map | `shared/specialist-runtime-map.tsv`, `model-lanes/ROSTER.md` |
| Specialist briefs | `departments/*/specialists/*.md`, `shared/specialists/*.md` |
| Mode workflows | `shared/routing.md`, `shared/modes/*.md`, `shared/mode-profiles/**/*.md` |
| Safety and lifecycle | `shared/protocol.md`, `shared/lifecycle.md`, `shared/memory-discipline.md` |

## Runtime Truth

1. `_state/active-tasks.json`
2. `chrono/current.md`
3. `departments/*/current.md`
4. Matching `departments/*/outbox/TASK-*-response.md` files

`departments/*/inbox/`, `active/`, `outbox/`, `archive/`, `_state/`, and private memory artifacts are runtime surfaces and should remain untracked unless intentionally curated as public examples.
