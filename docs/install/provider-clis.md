# Provider CLIs

`bin/squad up` checks for `claude`, `codex`, `gemini`, and `kimi` and exits 1 if
any is missing:

```text
ERROR: missing required command(s): claude kimi
Fix: install/login the missing CLIs, and install core tools with: brew install jq tmux fswatch
```

All four are required. They use four different installers, which is why "follow
each provider's instructions" was not an actionable step.

Model inference always runs through these native CLIs. Vibe Squad never
substitutes an MCP relay or a direct model API for a model lane.

## Summary

| CLI | Installed via | Package / source | Auth |
|---|---|---|---|
| `claude` | Anthropic native installer | `https://claude.ai/install.sh` | `claude` → `/login` (subscription or managed login) |
| `codex` | npm (global) | `@openai/codex` | `codex login` |
| `gemini` | npm (global) | `@google/gemini-cli` | `GEMINI_API_KEY` (**API key required**) |
| `kimi` | `uv tool` | `kimi-cli` (PyPI) | `kimi` → follow its login prompt |

Package identities were confirmed against the live npm and PyPI registries on
2026-08-13. Version numbers move; the package names are the stable part.

## claude

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

This installs into `~/.local/share/claude/versions/` and links
`~/.local/bin/claude`, so `~/.local/bin` must be on your `PATH`.

Authenticate by starting `claude` and running `/login`. Claude Code uses its
supported subscription or managed-login path; it does not take an API key here.

Check:

```bash
command -v claude && claude --version
```

## codex

```bash
npm install -g @openai/codex
```

Authenticate:

```bash
codex login
```

Check:

```bash
command -v codex && codex --version
```

## gemini

```bash
npm install -g @google/gemini-cli
```

Gemini is the **explicit exception** to subscription login: its native CLI lane
requires an API key.

```bash
export GEMINI_API_KEY="…"
```

Put it in your shell configuration or your local secret store. Do not add it, or
any other credential, to the repository. Treat spend and rate limits as part of
this lane's contract.

Check:

```bash
command -v gemini && gemini --version
[ -n "$GEMINI_API_KEY" ] && echo "GEMINI_API_KEY is set" || echo "GEMINI_API_KEY is NOT set"
```

## kimi

```bash
uv tool install kimi-cli
```

This links `~/.local/bin/kimi`, so `~/.local/bin` must be on your `PATH`.
Authenticate by starting `kimi` and following its login prompt.

Check:

```bash
command -v kimi && kimi --version
```

## Verify all four at once

This is the same list `bin/launch-squad.sh` checks:

```bash
for dep in tmux fswatch jq curl claude codex gemini kimi; do
  command -v "$dep" >/dev/null 2>&1 || echo "MISSING: $dep"
done
```

Silence means `bin/squad up` will get past its dependency gate.

## Authentication is not verified by presence

`command -v` and `--version` prove a binary exists. Neither proves it is logged
in. `bin/squad doctor` deliberately performs no login or inference, so it
reports CLI authentication as **could not determine** rather than guessing.

The cheapest real check is to start each CLI once, interactively, and confirm it
does not prompt you to log in.

## PATH note

Two of the four install outside Homebrew, into `~/.local/bin`. If `claude` or
`kimi` are reported missing right after a successful install, that directory is
almost certainly not on your `PATH`:

```bash
case ":$PATH:" in *":$HOME/.local/bin:"*) echo "on PATH" ;; *) echo "NOT on PATH" ;; esac
```
