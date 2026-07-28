#!/bin/bash
# Content processing — invokes the Python implementation.
# Reads _state/new-items-<date>.json, summarizes blog text via kimi, writes
# headline briefs for podcasts. Bounded by --limit (default 5 per run).

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

# Pass through any args (e.g. --limit 10, --blogs-only)
exec uv run --quiet "${VAULT_ROOT}/scripts/python/content_processing.py" "$@"
