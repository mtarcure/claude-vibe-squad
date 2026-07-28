#!/usr/bin/env bash
# Canonical repo-root resolver for shell entry points.
#
# Source this file to get VAULT_ROOT: the absolute, physical path to this
# repository's root, derived from this file's own location. A clone works from
# any directory under any username, so no wrapper needs a hardcoded default.
#
#   VAULT_ROOT       override the derived root (must already exist)
#   CHRONO_VAULT_ROOT unrelated — the out-of-repo private vault sentinel
#
# Callers resolve their own symlinks BEFORE sourcing, because a wrapper invoked
# through a symlink (bin/squad is documented as `ln -s <repo>/bin/squad
# ~/.local/bin/squad`) has a BASH_SOURCE pointing outside the repo. The standard
# two-line preamble is:
#
#   # shellcheck source=../shared/repo-root.sh
#   source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" \
#       2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# Follow every symlink hop in a path and echo the physical result. Pure bash so
# it does not depend on `readlink -f`, which BSD/macOS only grew in 12.3.
vs_resolve_symlink() {
    local target="$1" link dir hops=0
    while [[ -L "${target}" ]]; do
        hops=$((hops + 1))
        if (( hops > 40 )); then
            printf 'repo-root.sh: symlink loop resolving %s\n' "$1" >&2
            return 1
        fi
        link="$(readlink "${target}")"
        case "${link}" in
            /*) target="${link}" ;;
            *)  target="$(dirname -- "${target}")/${link}" ;;
        esac
    done
    dir="$(cd -- "$(dirname -- "${target}")" && pwd -P)" || return 1
    printf '%s/%s\n' "${dir}" "$(basename -- "${target}")"
}

if [[ -n "${VAULT_ROOT:-}" ]]; then
    # An override is used verbatim, never canonicalised. Callers test whether a
    # path is inside the vault by string prefix, and on macOS `pwd -P` rewrites
    # /var to /private/var -- which would make every such comparison miss.
    if [[ ! -d "${VAULT_ROOT}" ]]; then
        printf 'repo-root.sh: VAULT_ROOT is not a directory: %s\n' "${VAULT_ROOT}" >&2
        return 1
    fi
else
    _vs_self="$(vs_resolve_symlink "${BASH_SOURCE[0]}")" || return 1
    VAULT_ROOT="$(cd -- "$(dirname -- "${_vs_self}")/.." && pwd -P)" || return 1
    unset _vs_self
fi

export VAULT_ROOT
