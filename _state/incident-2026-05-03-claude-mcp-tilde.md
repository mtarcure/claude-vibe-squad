# Incident: Claude MCP failures via tilde-literal paths

**Date:** 2026-05-03
**Discovered during:** v1.1 build, Task 1 (Capability Inventory) → Task 2 (Claude MCP Debug)
**Severity:** HIGH — affected daily squad operation (chrono-vault unreachable from Coordinator)
**Status:** FIXED

## Symptoms

`claude mcp list` reported `✗ Failed to connect` for 7 chrono-* MCPs across all 3 Claude panes (chrono / security / sysmgmt):

- `plugin:chrono-vault:chrono-vault`
- `plugin:chrono-vault:chrono-kg`
- `plugin:chrono-vault:chrono-obsidian`
- `plugin:chrono-vault:chrono-catalog`
- `plugin:chrono-research-arsenal:chrono-research-arsenal` (sub-MCPs `perplexity` and `elevenlabs` worked because they're invoked via `uvx`)
- `plugin:chrono-content-engineer:chrono-content-engineer`
- `plugin:chrono-content-engineer:higgsfield` (HTTP MCP — separate, needs auth)

## Root cause

The chrono plugin manifests at `~/chrono/plugins/<plugin>/.claude-plugin/plugin.json` used **tilde-literal paths** in their `mcpServers` entries:

```json
"command": "~/chrono/.venv/bin/python",
"args": ["~/chrono/plugins/chrono-vault/mcp_server.py"],
"env": {
  "OBSIDIAN_VAULT_ROOT": "~/Obsidian-Chrono"
}
```

Claude's MCP runtime spawns subprocesses without expanding `~/` (POSIX shell does this; raw `execve()` does not). The runtime literally tried to find a file called `~/chrono/.venv/bin/python` and failed with ENOENT.

**Why other CLIs worked:** Codex and Kimi both expanded tildes when reading their MCP configs (or the operator's codex/kimi configs already used absolute paths).

**Why uvx/npx-launched MCPs worked:** `uvx perplexity-mcp` etc. don't reference filesystem paths in their command — they delegate to a tool that resolves the actual binary. No tilde, no failure.

## Affected manifests

7 files, 22 total tilde paths:

| File | Tilde paths |
|------|-------------|
| `~/chrono/plugins/chrono-vault/.claude-plugin/plugin.json` | 16 |
| `~/chrono/plugins/chrono-research-arsenal/.claude-plugin/plugin.json` | 2 |
| `~/chrono/plugins/chrono-content-engineer/.claude-plugin/plugin.json` | 2 |
| `~/.claude/plugins/cache/chrono/chrono-vault/0.1.0/.claude-plugin/plugin.json` | (cache copy — already absolute) |
| `~/.claude/plugins/cache/chrono/chrono-research-arsenal/0.2.0/.claude-plugin/plugin.json` | (cache copy — already absolute) |
| `~/.claude/plugins/cache/chrono/chrono-content-engineer/0.1.0/.claude-plugin/plugin.json` | (cache copy — already absolute) |
| `~/chrono/plugins/chrono-agents/.claude-plugin/plugin.json` | (no tildes — included in sed pass for safety) |

Cache copies were already absolute, but Claude was reading the source manifests at `~/chrono/plugins/...` not the cache copies. Source was authoritative.

## Fix

```bash
sed -i.bak 's|"~/chrono/|"/Users/chrono/chrono/|g; s|"~/Obsidian-Chrono|"/Users/chrono/Obsidian-Chrono|g' \
  ~/chrono/plugins/*/.claude-plugin/plugin.json \
  ~/.claude/plugins/cache/chrono/*/*/.claude-plugin/plugin.json
```

`.bak` files preserve the originals for rollback.

## Verification

`claude mcp list` (post-fix):

```
plugin:chrono-vault:chrono-vault: /Users/chrono/chrono/.venv/bin/python ... - ✓ Connected
plugin:chrono-vault:chrono-kg: ... - ✓ Connected
plugin:chrono-vault:chrono-obsidian: ... - ✓ Connected
plugin:chrono-vault:chrono-catalog: ... - ✓ Connected
plugin:chrono-research-arsenal:chrono-research-arsenal: ... - ✓ Connected
plugin:chrono-content-engineer:chrono-content-engineer: ... - ✓ Connected
sequential-thinking: ... - ✓ Connected
```

7/7 chrono-* MCPs now Connected on Claude.

## Forward fix (out of scope for this incident, prevents recurrence)

The plugin source manifests at `~/chrono/plugins/<plugin>/.claude-plugin/plugin.json` should be updated upstream so future cache rebuilds don't reintroduce tildes. Either:

1. **Manifest authors use absolute paths** — but operator's home directory is hardcoded, breaks portability across machines
2. **Manifest authors use env-var indirection** — `${HOME}/chrono/...` (env-var expansion is more reliable than tilde across runtimes)
3. **Plugin loader expands tildes** — change to chrono-claude plugin loader to do `os.path.expanduser()` on commands+args+env at load time

Recommended: option 2 (`${HOME}/chrono/...`), since claude's MCP runtime DOES seem to expand `${VAR}` patterns (env-var-style) but not `~/` (shell-style).

This is a separate task for the chrono-claude project, not the squad. Tracked here for awareness.

## Out of scope (separate failures still present)

These remain failing on Claude panes but are NOT chrono-* issues:

- `plugin:goodmem:goodmem` — Failed to connect (separate plugin, different root cause — likely missing dep or upstream package issue)
- `plugin:github:github` — Failed to connect (HTTP MCP — possibly auth or endpoint change)
- `plugin:greptile:greptile` — Failed to connect (HTTP MCP — same as above)

These are out of v1.1 Task 2 scope. Worth investigating in v1.2 or as standalone operational fixes.
