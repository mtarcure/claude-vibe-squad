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

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

UV_CACHE_DIR="${TMPDIR:-/tmp}/uv-cache-vibecoding"
export UV_CACHE_DIR
exec uv run --quiet --cache-dir "${UV_CACHE_DIR}" \
    "${VAULT_ROOT}/scripts/python/vibecoding_check.py" "$@"
