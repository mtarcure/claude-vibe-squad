#!/bin/bash
# Feed sweep — invokes the Python implementation.
# Reads _state/feed-config.yaml, fetches RSS, dedups, tags cadence,
# writes _state/new-items-<date>.json for content-processing.sh.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv). feed-sweep can't run."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/feed_sweep.py"
