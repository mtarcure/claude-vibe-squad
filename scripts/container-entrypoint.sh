#!/usr/bin/env bash
# Container entrypoint: load secrets, then PATH, then the image command.
# Compose and the Dockerfile both use this file — one home.

set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export VAULT_ROOT="${VAULT_ROOT:-${ROOT}}"

# shellcheck source=../shared/load-secrets.sh disable=SC1091
source "${VAULT_ROOT}/shared/load-secrets.sh"
# shellcheck source=../shared/host-path.sh disable=SC1091
source "${VAULT_ROOT}/shared/host-path.sh"

if [[ -n "${CHRONO_VAULT_ROOT:-}" ]]; then
    mkdir -p "${CHRONO_VAULT_ROOT}" 2>/dev/null || true
    if [[ ! -f "${CHRONO_VAULT_ROOT}/.chrono-vault" ]]; then
        printf '%s\n' '{"vault_id":"container-vault","schema_version":1}' \
            > "${CHRONO_VAULT_ROOT}/.chrono-vault" 2>/dev/null || true
    fi
fi

# Auth middleware constructs on every request, including /health. A missing
# token is a 500, not a public-path skip. Operator/KeyVault/env still win
# (load-secrets already ran). If nothing set one, mint a process-local token
# so compose healthchecks work without a host .env. Shared across daemon +
# squad via the squad-state volume when that path is writable.
if [[ -z "${VIBESQUAD_DAEMON_TOKEN:-}" ]]; then
    _token_file="${VAULT_ROOT}/_state/runtime/daemon.token"
    mkdir -p "$(dirname -- "${_token_file}")" 2>/dev/null || true
    if [[ -r "${_token_file}" ]]; then
        VIBESQUAD_DAEMON_TOKEN="$(tr -d '\r\n' < "${_token_file}")"
    else
        if command -v python3 >/dev/null 2>&1; then
            VIBESQUAD_DAEMON_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
        else
            VIBESQUAD_DAEMON_TOKEN="container-dev-$(hostname)-$$"
        fi
        if [[ -n "${VIBESQUAD_DAEMON_TOKEN}" ]]; then
            printf '%s\n' "${VIBESQUAD_DAEMON_TOKEN}" > "${_token_file}.tmp" 2>/dev/null \
                && mv "${_token_file}.tmp" "${_token_file}" 2>/dev/null \
                || true
        fi
    fi
    export VIBESQUAD_DAEMON_TOKEN
    unset _token_file
fi

exec "$@"
