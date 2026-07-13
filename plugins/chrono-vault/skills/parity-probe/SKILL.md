---
name: parity-probe
description: Probe each provider (Claude / Codex / Gemini / Kimi) to verify chrono MCPs are reachable and responding. Catches config drift before high-stakes fan-out. Operator-runnable; output goes to vault.
type: skill
---

# Provider parity probe

A scripted check that asks each provider whether it can see + invoke chrono MCPs. Run before fan-out work where MCP wiring matters (Stage 3 hypothesis exploration, Stage 5/6 multi-voice review). Catches config drift between `~/.codex/config.toml`, `~/.gemini/settings.json`, `~/.kimi/mcp.json` and the chrono v1.3 plugin set.

## When to run

- Before any bounty-class fan-out
- After editing any provider's MCP config
- After upgrading codex / gemini / kimi CLIs
- When a previous fan-out reported "user cancelled MCP tool call" or similar — the probe localizes the broken provider

## What it checks

For each provider, the probe asks:

1. Can you see `chrono-vault`? (Tests primary plugin reachability.)
2. Can you call `mcp__chrono_vault__obsidian_health_check()`? (Tests MCP server startup + Obsidian REST liveness.)
3. Can you see the namespace aliases (`chrono-kg`, `chrono-obsidian`, `chrono-catalog`)? (Tests Path B reach.)
4. Can you see `chrono-research-arsenal` + perplexity sibling? (Tests research surface.)

Result captured to `~/Obsidian-Chrono/chrono/_state/parity-probe/<YYYY-MM-DD>.md` per the auto-capture pattern.

## How to run (operator-driven)

The probe is a sequence of one-shot dispatches. Brain (you, in Claude Code session) runs each, captures the result, then composes a summary.

### Probe — Claude (brain main context)

Just call the MCP directly:

```
mcp__chrono_vault__obsidian_health_check()
```

If this returns `{ok: true, ...}`, Claude main context sees chrono-vault. If error, the chrono-vault plugin isn't loaded — check `~/.claude/settings.json` `enabledPlugins`.

### Probe — Codex (`~/.codex/config.toml`)

```bash
cat <<'EOF' | codex exec --skip-git-repo-check --model gpt-5.5 -
List the MCP servers you have access to. Then call
mcp__chrono_vault__obsidian_health_check and report the result verbatim.
EOF
```

Expected output should mention `chrono-vault` plus namespace aliases. If codex reports no chrono MCPs, check `~/.codex/config.toml` `[mcp_servers.chrono-vault]` block.

### Probe — Gemini (`~/.gemini/settings.json`)

```bash
gemini -m gemini-3.1-pro-preview -p "List MCP servers available to you. Then call mcp__chrono_vault__obsidian_health_check and report the result."
```

Expected: same shape as Codex. If missing, check `~/.gemini/settings.json` `mcpServers` block.

### Probe — Kimi (`~/.kimi/mcp.json`)

```bash
kimi -m kimi-code/kimi-for-coding -p "List MCP servers available to you. Then call mcp__chrono_vault__obsidian_health_check and report the result." --quiet
```

If kimi fails with `LLM not set`: run `kimi login` first (Moonshot subscription auth).

If kimi sees chrono-vault but NOT chrono-kg / chrono-obsidian / chrono-catalog: those namespace aliases need adding (see README QuickStart §4 kimi block).

## Synthesis

After all 4 probes return, brain composes a parity table and writes it to vault:

```markdown
| Provider | chrono-vault | chrono-kg | chrono-obsidian | chrono-catalog | chrono-research-arsenal | obsidian-health-check |
|---|---|---|---|---|---|---|
| Claude (brain) | ✅ | (via vault) | (via vault) | (via vault) | ✅ | ok |
| Codex | ✅ | ✅ | ✅ | ✅ | ✅ | ok |
| Gemini | ✅ | ✅ | ✅ | ✅ | ✅ | ok |
| Kimi | ✅ | ❌ missing | ❌ missing | ❌ missing | ✅ | ok |
```

Capture path: `~/Obsidian-Chrono/chrono/_state/parity-probe/<YYYY-MM-DD>.md`

## When to act on probe failure

- **Single-provider gap (e.g. kimi missing aliases):** drop that provider from fan-out for the current pass; queue config fix for after
- **Cross-provider gap (multiple providers can't see chrono-vault):** suspect chrono-vault MCP server itself; run `.venv/bin/python plugins/chrono-vault/mcp_server.py --help` from the repo root to verify the server loads
- **obsidian-health-check returns error:** Obsidian REST plugin isn't running, or `OBSIDIAN_REST_API_KEY` is wrong/missing — check `~/.config/shell/secrets.zsh`

## Cross-references

- CLI dispatchers used by codex/gemini/kimi probes live outside this vendored MCP plugin.
- `~/.claude/settings.json` `enabledPlugins` — where Claude main loads chrono plugins
- `docs/phase9-cleanup-2026-04-30.md` — MCP wiring audit table from Phase 9 (snapshot of as-of-2026-04-30 wiring)
- README QuickStart §4 "Cross-provider configs" — the canonical setup the probe verifies
