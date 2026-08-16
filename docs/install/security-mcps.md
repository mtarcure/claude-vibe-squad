# Guarded security MCPs

`guarded-semgrep`, `guarded-slither`, and `guarded-solodit` do not run directly.
Each runs as a **child process of the Trail of Bits `mcp-context-protector`
wrapper**, schema-pinned and fail-closed. No wrapper, no guarded servers.

This is optional. If you skip it, exactly those three servers are unavailable
and every other MCP, specialist, and lane keeps working.

## Why it is not vendored

`mcp-context-protector` is a separate Apache-2.0 project
([trailofbits/mcp-context-protector](https://github.com/trailofbits/mcp-context-protector)).
It is an **install-time dependency and is never committed to this repository**.

Its source is small (~2 MB). What makes the installed directory large is the
Python environment built inside it — on the maintainer machine, 702 MB of a
704 MB total. That environment is machine-specific and must be built locally,
which is the reason it cannot be shipped in a clone.

## Install

```bash
# Pick any stable location outside the clone.
export CONTEXT_PROTECTOR_DIR="$HOME/.local/share/mcp-context-protector"

git clone https://github.com/trailofbits/mcp-context-protector.git "$CONTEXT_PROTECTOR_DIR"
cd "$CONTEXT_PROTECTOR_DIR"
uv sync
```

`uv sync` builds `.venv` and creates `.venv/bin/mcp-context-protector`, the
console script declared in the project's `pyproject.toml`. The shipped
`mcp-context-protector.sh` wrapper `exec`s exactly that path and exits **127** if
it is absent, so the checkout alone is not enough — the venv must be built.

## Check

```bash
CONTEXT_PROTECTOR="$CONTEXT_PROTECTOR_DIR/mcp-context-protector.sh" \
  bash scripts/bootstrap-mcps.sh --status
```

Installed correctly:

```text
## Guarded security MCPs (mcp-context-protector)
  ✓ mcp-context-protector: …/mcp-context-protector.sh
    ✓ guarded-semgrep (wrapper present)
    ✓ guarded-slither (wrapper present)
    ✓ guarded-solodit (wrapper present)
```

Not installed:

```text
  ✗ mcp-context-protector not installed at: …
    — guarded-semgrep: UNAVAILABLE (its wrapper is absent)
    — guarded-slither: UNAVAILABLE (its wrapper is absent)
    — guarded-solodit: UNAVAILABLE (its wrapper is absent)
  This disables those three servers and nothing else.
```

Cloned but not built — reported separately, because a present wrapper that would
exit 127 is not an install:

```text
  ✗ mcp-context-protector wrapper found, but its entry point is missing:
      …/.venv/bin/mcp-context-protector
    The wrapper would exit 127. Its venv is not built.
```

## Wiring it into the lanes

Installing the wrapper does not by itself make the three servers reachable. They
are declared per-lane in `model-lanes/claude/.mcp.json` and
`model-lanes/gpt-codex/.codex/config.toml`, and **those files currently hold an
absolute path into the maintainer's home directory**. On any other machine that
path does not resolve, so after installing the wrapper you must point those
declarations at your own `CONTEXT_PROTECTOR_DIR`.

Find them with:

```bash
grep -rn 'mcp-context-protector' model-lanes/
```

Each entry also names a pinned `--server-config-file`. Review the pinned schema
before approving it; the guard is only meaningful if you have looked at what it
pins.

## Presence is not liveness

A config entry and an installed file prove neither that a server starts nor that
its tools are callable. A guarded server counts as live only when a bounded real
call succeeds **from the CLI that will use it** — `tools/list` plus a read-only
call on a fixture. Board-spawned specialists do not automatically inherit an
operator's CLI configuration, so confirm the surface from inside the process
that will use it rather than from the file.

See [../tooling/security-arsenal-guide.md](../tooling/security-arsenal-guide.md)
for the arsenal these servers belong to.
