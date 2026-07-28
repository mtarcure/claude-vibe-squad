#!/bin/bash
# Feed sweep — invokes the Python implementation.
# Reads _state/feed-config.yaml, fetches RSS, dedups, tags cadence,
# writes _state/new-items-<date>.json for content-processing.sh.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv). feed-sweep can't run."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/feed_sweep.py"
