#!/usr/bin/env bash
# Unified secret loader. First set wins.
#
#   1. Process environment (Compose `environment:`, Key Vault env injection)
#   2. SQUAD_SECRETS_DIR (default /run/secrets) — one file per name
#   3. SQUAD_ENV_FILE (default /config/.env, then $VAULT_ROOT/.env)
#   4. Legacy ~/.config/shell/secrets.zsh (Mac host unchanged)
#
# Names are not listed here. Research keys stay owned by RESEARCH_API_KEY_NAMES
# in scripts/python/lane_capability_enforcement.py; MCP env names stay owned by
# MCPS=(...) in scripts/bootstrap-mcps.sh. This file only applies sources.
#
# Sourced, never executed. No `set -e` / `set -u` of its own.

_squad_env_is_set() {
    eval "[[ -n \"\${${1}+x}\" ]]"
}

_squad_set_if_unset() {
    local _name="$1" _value="$2"
    if _squad_env_is_set "${_name}"; then
        return 0
    fi
    # assignment form keeps bash 3.2 (macOS /bin/bash) happy
    eval "export ${_name}=\"\${_value}\""
}

_squad_load_secrets_dir() {
    local _dir="$1" _file _name _value
    [[ -d "${_dir}" ]] || return 0
    for _file in "${_dir}"/*; do
        [[ -f "${_file}" && -r "${_file}" ]] || continue
        _name="$(basename -- "${_file}")"
        case "${_name}" in
            *[!A-Za-z0-9_]* | [0-9]* | "") continue ;;
        esac
        if _squad_env_is_set "${_name}"; then
            continue
        fi
        _value="$(cat -- "${_file}")"
        _value="${_value%$'\r'}"
        _value="${_value%$'\n'}"
        _squad_set_if_unset "${_name}" "${_value}"
    done
}

_squad_load_env_file() {
    local _file="$1" _line _name _value
    [[ -f "${_file}" && -r "${_file}" ]] || return 0
    while IFS= read -r _line || [[ -n "${_line}" ]]; do
        _line="${_line%$'\r'}"
        case "${_line}" in
            "" | \#*) continue ;;
            export\ *) _line="${_line#export }" ;;
        esac
        case "${_line}" in
            *=*) ;;
            *) continue ;;
        esac
        _name="${_line%%=*}"
        _value="${_line#*=}"
        case "${_name}" in
            *[!A-Za-z0-9_]* | [0-9]* | "") continue ;;
        esac
        if _squad_env_is_set "${_name}"; then
            continue
        fi
        case "${_value}" in
            \"*\") _value="${_value#\"}"; _value="${_value%\"}" ;;
            \'*\') _value="${_value#\'}"; _value="${_value%\'}" ;;
        esac
        _squad_set_if_unset "${_name}" "${_value}"
    done < "${_file}"
}

# 1. Process env is already in this shell.

# 2. Docker secrets / Key Vault CSI — one file per name.
_squad_load_secrets_dir "${SQUAD_SECRETS_DIR:-/run/secrets}"

# 3. env file. An explicit SQUAD_ENV_FILE is the only file tried; otherwise
#    /config/.env then the checkout .env (first set still wins).
if [[ -n "${SQUAD_ENV_FILE:-}" ]]; then
    _squad_load_env_file "${SQUAD_ENV_FILE}"
else
    _squad_load_env_file "/config/.env"
    if [[ -n "${VAULT_ROOT:-}" ]]; then
        _squad_load_env_file "${VAULT_ROOT}/.env"
    fi
fi

# 4. Legacy Mac host store. Source it, then restore every name that was already
#    set so a secrets.zsh `export` cannot beat process env / earlier sources.
if [[ -n "${HOME:-}" && -r "${HOME}/.config/shell/secrets.zsh" ]]; then
    _squad_prev_exports="$(export -p)"
    _squad_had_nounset=0
    case "$-" in *u*) _squad_had_nounset=1; set +u ;; esac
    # shellcheck disable=SC1090
    source "${HOME}/.config/shell/secrets.zsh" >/dev/null 2>&1 || true
    eval "${_squad_prev_exports}"
    unset _squad_prev_exports
    if [[ "${_squad_had_nounset}" -eq 1 ]]; then
        set -u
    fi
    unset _squad_had_nounset
fi

unset -f _squad_env_is_set _squad_set_if_unset _squad_load_secrets_dir _squad_load_env_file
