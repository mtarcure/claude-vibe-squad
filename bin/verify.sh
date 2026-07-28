#!/bin/bash
# Multi-model verify — dispatch writer's output to opposite-family reviewer.
# Wraps Python implementation. See scripts/python/verify.py for full options.
#
# Quick usage:
#   bash bin/verify.sh --writer codex --output draft.md
#   bash bin/verify.sh --writer claude --output finding.md --prompt 'Spec compliance review'

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

exec uv run --quiet "${VAULT_ROOT}/scripts/python/verify.py" "$@"
