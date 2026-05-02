#!/bin/bash
# Multi-model verify — dispatch writer's output to opposite-family reviewer.
# Wraps Python implementation. See scripts/python/verify.py for full options.
#
# Quick usage:
#   bash bin/verify.sh --writer codex --output draft.md
#   bash bin/verify.sh --writer claude --output finding.md --prompt 'Spec compliance review'

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/verify.py" "$@"
