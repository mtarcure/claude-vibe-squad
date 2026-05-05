# Coding Department — Durable Memory

This is the coding namespace's long-term memory. Distilled knowledge, not transcripts.

Governed by `shared/memory-discipline.md`.

## Repo Conventions

(Populate as you work on actual repos. Examples to follow:)

- *(per-repo conventions go here once coding namespace has worked on real repos)*

## Known Sharp Edges

- `bin/vibecoding-check.sh` uses `uv` and may need network/cache access to fetch `httpx`/`pyyaml`; sandboxed runs can fail on `~/.cache/uv` permissions or DNS if dependencies are not already cached.
- Ad hoc mailbox tasks with `run_id: none` do not have `_state/runs/<run-id>/manifest.yaml`, so `vibecoding-check.sh --run-id <task-id>` cannot evaluate them unless a run manifest is created upstream.
- Coding pane `workspace-write` can write under `departments/coding/` but not vault-root `_state/`; draft-only tasks requesting `_state/<name>/...` may need outputs staged under `departments/coding/_state/` and explicitly reported for Chrono relocation.
- Codex project custom agents in `.codex/agents/*.toml` are invoked by TOML `name`; `refactor-cleaner.toml` with `name = "refactor_cleaner"` spawned via `agent_type: refactor_cleaner`, while `agent_type: refactor-cleaner` was rejected. Current `spawn_agent`/`wait_agent` output does not expose a numeric `tool_uses` telemetry field.
- Codex custom agent TOMLs require only `name`, `description`, and `developer_instructions`; omitted `mcp_servers` and `skills.config` inherit from the parent session. Add per-agent blocks only to restrict, enable/disable, or override inherited config. Verified on 2026-05-04 via official Codex docs plus `refactor_cleaner` API and `codex exec` smoke probes.

## Decisions That Stuck

- *(architectural decisions worth remembering)*

## Tools and Commands

- `codex features list` shows local Codex feature maturity/enabled state. On 2026-05-03 in Coding pane: `multi_agent stable true`, `multi_agent_v2 under development false`, `child_agents_md under development false`, `enable_fanout under development false`.

---

*Memory is curated, not appended. When something turns out wrong, REMOVE — don't add a contradicting line.*

## Tool-catalog update — 2026-05-03

The squad shipped explicit tool catalogs in every specialist file,
per-pane effort/thinking tier defaults, capability inventory, and Topology B
direct-with-CC patterns. When dispatching a specialist now, trust that its
identity.md enumerates available MCPs / native CLI features / skills / APIs
— no need to remind it. Lead-to-Lead direct-with-CC patterns are documented
in this LEAD.md. See shared/lifecycle.md for lifecycle rules.
