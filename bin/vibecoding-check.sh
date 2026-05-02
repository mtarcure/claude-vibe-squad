#!/bin/bash
# Vibecoding-check — Layer 2 mode-exit verifier wrapper.
# Modes invoke this before declaring "done". See specialists/vibecoding-check.md.
#
# Usage:
#   bash bin/vibecoding-check.sh --run-id <id>
#
# Exit codes:
#   0 — pass; mode may advance
#   1 — pass-after-autofix
#   2 — retry tier; mode should re-run failing phase
#   3 — operator surface; mode pauses, state in _state/vibecoding-check/<id>.md

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/vibecoding_check.py" "$@"
