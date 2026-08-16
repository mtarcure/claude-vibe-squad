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

# Keep executable code rooted beside this wrapper while allowing VAULT_ROOT to
# name a separate data/repository root. Settlement canaries use that split, and
# a caller-provided VAULT_ROOT must never make the wrapper look for its Python
# source inside the data fixture.
#
# The code root is derived AFTER the canonical source line, from the resolver's
# own `vs_resolve_symlink`, so the wrapper carries the same preamble as every
# other converted wrapper and still holds only one copy of the symlink-walking
# rule. Resolution failure is fatal here: this file runs under `set -u` without
# `-e`, so an unchecked empty result would silently root the wrapper at the
# caller's working directory instead.
if ! vibecoding_self="$(vs_resolve_symlink "${BASH_SOURCE[0]}")" \
    || ! vibecoding_code_root="$(cd -- "$(dirname -- "${vibecoding_self}")/.." && pwd -P)"; then
    echo "ERROR: cannot resolve the vibecoding-check code root beside this wrapper." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed (brew install uv)."
    exit 1
fi

# install-routines.sh prewarms /tmp/uv-cache. Honor an explicit caller cache,
# otherwise use that exact prewarmed location; the supervisor's per-attempt
# TMPDIR is intentionally irrelevant here.
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export UV_CACHE_DIR
exec uv run --quiet --cache-dir "${UV_CACHE_DIR}" \
    --no-project python \
    "${vibecoding_code_root}/scripts/python/vibecoding_check.py" "$@"
