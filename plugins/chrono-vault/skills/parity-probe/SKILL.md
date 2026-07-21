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
2. Can you call `health()`? (Tests MCP server startup and private-root resolution without mutation.)
3. Can you `record` a uniquely-tokened synthetic learning and `recall` that token? (Tests the durable memory write/read loop.)
4. Does the recalled note ID match the `record` result? (Tests that the provider reached the intended backing vault.)

The record step is a durable mutation and each one-shot provider prompt may consume provider quota. Run the round trip only after the task/operator has authorized those gates. Static config inspection alone is never reported as a successful live round trip.

Result captured to `~/Obsidian-Chrono/chrono/_state/parity-probe/<YYYY-MM-DD>.md` per the auto-capture pattern.

## How to run (operator-driven)

The probe is a sequence of one-shot dispatches. Brain (you, in Claude Code session) runs each, captures the result, then composes a summary.

### Probe — Claude (brain main context)

After the lane restart, call the MCP directly:

```
health()
record("learning", {"title":"provider parity <unique-token>","body":"Synthetic post-restart chrono-vault activation probe.","target":"chrono-vault","attack_class":"provider-parity","source_task":"<task-id>"})
recall("<unique-token>", {"type":"learning"}, 3)
```

Pass only when `health` reports `root_valid: true`, `record` returns a note ID/path, and `recall` returns that same note ID. If the tools are absent, the running process has not loaded chrono-vault even if `claude mcp list` shows persisted configuration.

### Probe — Codex (`~/.codex/config.toml`)

```bash
cat <<'EOF' | codex exec --skip-git-repo-check -
Use chrono-vault to call health. Then record a learning with a unique token in
the title and body, target "chrono-vault", attack_class "provider-parity", and
the supplied task ID. Recall that exact token. Return only root_valid, the
recorded note ID, the recalled note IDs, and any tool error; do not print env.
EOF
```

If Codex reports no chrono-vault tools, distinguish the already-running tool surface from `codex mcp list`: check the persisted block, restart the lane, and retry once rather than claiming a config-list pass as callable memory.

### Probe — Gemini (`~/.gemini/settings.json`)

```bash
gemini -p "Use chrono-vault health, record a uniquely-tokened provider-parity learning, then recall the exact token. Return only root_valid, recorded note ID, recalled note IDs, and tool errors; do not print env."
```

Expected: the same three-part evidence as Claude. If missing, check the lane-local and home `mcpServers` blocks plus the inherited `CHRONO_VAULT_ROOT`; never copy credential values into probe output.

### Probe — Kimi (`~/.kimi/mcp.json`)

```bash
kimi -m kimi-code/kimi-for-coding -p "Use chrono-vault health, record a uniquely-tokened provider-parity learning, then recall the exact token. Return only root_valid, recorded note ID, recalled note IDs, and tool errors; do not print env." --quiet
```

If kimi fails with `LLM not set`: run `kimi login` first (Moonshot subscription auth).

Pass only when Kimi returns the recorded note through recall. Historical KG/catalog aliases are not parity requirements.

## Synthesis

After all 4 probes return, brain composes a parity table and writes it to vault:

```markdown
| Provider | persisted config | process callable | root valid | record note ID | recall matched | status |
|---|---|---|---|---|---|---|
| Claude | yes/no | yes/no | yes/no | ID/error | yes/no | pass/fail |
| Codex | yes/no | yes/no | yes/no | ID/error | yes/no | pass/fail |
| Gemini | yes/no | yes/no | yes/no | ID/error | yes/no | pass/fail |
| Kimi | yes/no | yes/no | yes/no | ID/error | yes/no | pass/fail |
```

Capture path: `~/Obsidian-Chrono/chrono/_state/parity-probe/<YYYY-MM-DD>.md`

## When to act on probe failure

- **Single-provider gap (e.g. kimi missing aliases):** drop that provider from fan-out for the current pass; queue config fix for after
- **Cross-provider gap (multiple providers can't see chrono-vault):** suspect chrono-vault MCP server itself; run `.venv/bin/python plugins/chrono-vault/mcp_server.py --help` from the repo root to verify the server loads
- **`health` reports an invalid root:** stop before writing; verify the inherited/configured absolute root and `.chrono-vault` sentinel without printing credentials.
- **`record` errors or `recall` does not return the recorded ID:** fail activation for that provider and preserve the redacted tool error plus note IDs for review; do not treat server visibility as a pass.

## Cross-references

- CLI dispatchers used by codex/gemini/kimi probes live outside this vendored MCP plugin.
- `~/.claude/settings.json` `enabledPlugins` — where Claude main loads chrono plugins
- `docs/phase9-cleanup-2026-04-30.md` — MCP wiring audit table from Phase 9 (snapshot of as-of-2026-04-30 wiring)
- README QuickStart §4 "Cross-provider configs" — the canonical setup the probe verifies
