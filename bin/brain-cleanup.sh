#!/bin/bash
# Brain cleanup — light KG sweep nightly. Wraps Python implementation.
# Per chrono memory rule: REMOVE invalidated knowledge in place; this script
# proposes only — operator approves actual removals.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/brain_cleanup.py"
