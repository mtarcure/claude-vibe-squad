#!/usr/bin/env bash
set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# A quiet clone has no evidence and needs no token. Source the operator's
# optional environment when present, but do not make a private shell file or a
# gitignored virtualenv prerequisites for reaching the runner's empty-evidence
# guard.
SECRETS_FILE="${HOME}/.config/shell/secrets.zsh"
if [[ -r "${SECRETS_FILE}" ]]; then
    # shellcheck disable=SC1090
    if ! source "${SECRETS_FILE}"; then
        echo "COULD NOT DETERMINE: failed to source ${SECRETS_FILE}" >&2
        exit 2
    fi
fi

UV_BIN="${WEEKLY_UV_UNDER_TEST:-uv}"
if ! command -v "${UV_BIN}" >/dev/null 2>&1; then
    echo "COULD NOT DETERMINE: uv is required to run the committed Python environment (${UV_BIN})" >&2
    exit 2
fi

exec "${UV_BIN}" run --quiet --locked --project "${VAULT_ROOT}" \
    python "${VAULT_ROOT}/scripts/python/weekly_review_runner.py" "$@"
