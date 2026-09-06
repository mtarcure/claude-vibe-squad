#!/bin/bash
# Browser keep-alive — verify the CDP-attached Chrome session is alive with its working tabs.
# Wraps Python implementation. Read-only — never opens or modifies tabs.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# shellcheck source=../shared/host-path.sh disable=SC1091
source "${VAULT_ROOT}/shared/host-path.sh"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/browser_keep_alive.py"
