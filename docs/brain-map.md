# Brain Map

Status: canonical
Owner: Chrono / sysmgmt namespace

Vibe Squad is markdown-first. Scripts are rails and validators; they do not own role logic, routing judgment, memory policy, or specialist behavior.

## Naming Glossary

Use these names consistently:

| Term | Meaning |
|---|---|
| **Chrono** | Vibe Squad's Claude-based Coordinator/controller role. Use bare `Chrono` only for this role. |
| **Vibe Squad `chrono/` directory** | This repo's directory for Chrono prompts, identity, routing index, and live Coordinator state. |
| **legacy Chrono repo** | Private/local `~/chrono` dependency for MCP/plugin implementation. |
| **operator account** | Local macOS account `~`. |
| **Chrono Vault** | Obsidian knowledge/memory vault dependency. |
| **Chrono MCPs** | MCP namespace/tool family used by the squad. |

Rule: do not use bare `Chrono` for a folder, repo, account, vault, or MCP. Say `Vibe Squad chrono/ directory`, `legacy Chrono repo`, `operator account`, `Chrono Vault`, or `Chrono MCPs`.

## Brain Stack

| Layer | Canonical files | Purpose |
|---|---|---|
| Operator-facing controller | `chrono/SOUL.md`, `chrono/CLAUDE.md`, `chrono/current.md`, `chrono/SPECIALIST-INDEX.md` | Chrono identity, Coordinator behavior, live state, and dispatch map. |
| Global instruction layer | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` | Auto-loaded CLI adapters and squad-wide hard rules. Keep these filenames because CLIs discover them automatically. |
| Lead brains | `departments/*/LEAD.md` plus `departments/*/{AGENTS,CLAUDE,GEMINI}.md` symlink/adapters | Department responsibility, specialist dispatch policy, and CLI-specific identity loading. |
| Specialist brains | `departments/*/specialists/*.md`, `shared/specialists/*.md` | Work-shape ownership, tools, fan-out rules, escalation rules, and explicit non-goals. |
| Mode brain | `shared/routing.md`, `shared/modes/*.md`, `shared/mode-profiles/**/*.md` | Operator-consented workflows and target-type profiles. |
| Memory policy | `shared/memory-discipline.md`, `departments/*/memory.md` | Durable learning, citation rules, and Lead-owned memory surfaces. |
| Tool catalog | `shared/api-catalog.md`, `shared/skills/*.md`, `shared/capability-manifests/*.md` | Verified tool availability and reusable mechanical skills. |

## State And Artifacts

Runtime truth order:

1. `_state/active-tasks.json`
2. `chrono/current.md`
3. `departments/*/current.md`
4. Matching `departments/*/outbox/TASK-*-response.md` files

Generated/runtime artifacts:

- `_state/*` runtime logs, registries, summaries, and task data are operator-local unless explicitly unignored as curated product examples or config.
- `departments/*/inbox/`, `active/`, `outbox/`, and `archive/` are runtime mailboxes; public repos keep only `.gitkeep`.
- Generated Kimi/Codex prompt adapters under per-CLI folders are derived surfaces. Validate them against source markdown; do not hand-edit them as primary truth unless the source markdown is updated too.

Public docs:

- `README.md`, `docs/state-model.md`, `docs/private-config.md`, `docs/production-readiness.md`, and this file describe current product behavior.
- Completed specs, plans, and handoffs are cleanup debt after their durable decisions are folded into canonical docs.
