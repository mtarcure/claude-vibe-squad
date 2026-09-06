#!/usr/bin/env bash
# Portable PATH prefix for squad entry points.
#
# ONE home for one fact (CLAUDE.md rule 10). Nightlies, doctor, MCP bootstrap,
# and the monitor used to each prepend `~/.local/bin` plus Homebrew. A copied
# prefix ages independently: Linux/container would keep looking in
# /opt/homebrew, and a new user-local CLI directory would have to be added in
# nine files. This file is the only prefix; callers source it.
#
# Order (first match wins):
#   1. ~/.local/bin          user-local CLIs (claude, kimi, uv)
#   2. ~/.grok/bin           grok's documented install location
#   3. $VAULT_ROOT/bin       checkout wrappers (squad-watch) without a second install
#   4. Homebrew              Darwin only — never on Linux/container
#
# Sourced, never executed. Deliberately declares no `set -e` / `set -u` of its
# own: those would mutate the CALLER's shell (see shared/launch-dependencies.sh).

_squad_host_path_add() {
    local dir="$1"
    [[ -n "${dir}" ]] || return 0
    case ":${_SQUAD_HOST_PATH_PREFIX}:${PATH}:" in
        *":${dir}:"*) ;;
        *)
            if [[ -n "${_SQUAD_HOST_PATH_PREFIX}" ]]; then
                _SQUAD_HOST_PATH_PREFIX="${_SQUAD_HOST_PATH_PREFIX}:${dir}"
            else
                _SQUAD_HOST_PATH_PREFIX="${dir}"
            fi
            ;;
    esac
}

_SQUAD_HOST_PATH_PREFIX=""
_squad_host_path_add "${HOME}/.local/bin"
if [[ -d "${HOME}/.grok/bin" ]]; then
    _squad_host_path_add "${HOME}/.grok/bin"
fi
if [[ -n "${VAULT_ROOT:-}" && -d "${VAULT_ROOT}/bin" ]]; then
    _squad_host_path_add "${VAULT_ROOT}/bin"
fi

_SQUAD_HOST_UNAME="$(uname -s 2>/dev/null || true)"
if [[ "${_SQUAD_HOST_UNAME}" == "Darwin" ]]; then
    _squad_host_path_add "/opt/homebrew/bin"
    _squad_host_path_add "/opt/homebrew/sbin"
fi
unset _SQUAD_HOST_UNAME

if [[ -n "${_SQUAD_HOST_PATH_PREFIX}" ]]; then
    PATH="${_SQUAD_HOST_PATH_PREFIX}:${PATH}"
fi
unset _SQUAD_HOST_PATH_PREFIX
unset -f _squad_host_path_add
export PATH
