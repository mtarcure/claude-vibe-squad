# Brain Map

Status: canonical

Vibe Squad is markdown-first. Scripts launch, watch, validate, and dispatch; markdown owns role behavior and workflow instructions.

## Naming

| Term | Meaning |
|---|---|
| Chrono | The only controller and operator-facing coordinator. |
| Model lead | One of `gpt-codex`, `claude`, `gemini`, or `kimi`. Executes assigned specialist briefs. |
| Specialist | Canonical role selected by Chrono and mapped in `shared/specialist-runtime-map.tsv`. |
| Source namespace | Compatibility storage folder for specialist markdown, memory, and mailbox files. |
| Mode | Operator-approved workflow under `shared/modes/`. |

Do not describe source namespaces as model ownership. Kimi is not the research lead, Claude is not the security lead, and Codex is not the coding department. Model choice comes from the specialist map.

## Source Layers

| Layer | Canonical files |
|---|---|
| Chrono brain | `chrono/SOUL.md`, `chrono/CLAUDE.md`, `chrono/current.md` |
| Model lead prompts | `model-lanes/gpt-codex/AGENTS.md`, `model-lanes/claude/CLAUDE.md`, `model-lanes/gemini/GEMINI.md`, `model-lanes/kimi/KIMI.md` |
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
