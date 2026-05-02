#!/bin/bash
# Weekly deep run (Sunday 04:00) — wraps Python implementation.
# Phases: deep KG cleanup, 7-day dream, subscription audit, mode archival,
# cross-source synthesis, weekly brief.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/run_weekly.py"
