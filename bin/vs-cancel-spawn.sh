#!/usr/bin/env bash
# Cancel one exact board attempt after verifying its v2 OS process identity.
set -u

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
wrapper_path="$(vs_resolve_symlink "${BASH_SOURCE[0]}")" || exit 1
implementation_root="$(cd -- "$(dirname -- "$wrapper_path")/.." && pwd -P)" || exit 1

# Cancel and reap both preserve the attempt's committed work onto a private
# branch, and preservation needs the checkout's base branch to derive its
# comparison base. Neither entrypoint is reached through send-task.sh or
# board-supervisor.sh, which are the two places that already derive and export
# this, so before 2026-08-29 preservation fell through to a hardcoded "v2" and
# failed on every repo not literally named that.
#
# Unlike send-task.sh, an underivable value does NOT abort here. Dispatching off
# the wrong base silently hands a worker somebody else's code, so send-task.sh
# must die; cancelling is the emergency stop for a live worker and must not be
# blocked by a detached HEAD. worktree_isolation refuses to guess instead, which
# surfaces a loud preservation error and keeps the work in the retained worktree.
if [[ -z "${SQUAD_BASE_BRANCH:-}" ]]; then
    SQUAD_BASE_BRANCH="$(git -C "$VAULT_ROOT" branch --show-current 2>/dev/null || true)"
    if [[ -n "$SQUAD_BASE_BRANCH" ]]; then
        export SQUAD_BASE_BRANCH
    else
        # Leave it genuinely unset rather than exporting "": worktree_isolation
        # treats a blank value as no answer and derives from the checkout, and an
        # exported empty string would be indistinguishable from a real one.
        unset SQUAD_BASE_BRANCH
    fi
fi

if [[ "$#" -eq 1 && "$1" == *.log ]]; then
    exec /usr/bin/python3 "$implementation_root/scripts/python/board_process_truth.py" \
        cancel "$VAULT_ROOT" "$@"
fi

# `--reap` clears an attempt whose process is gone and which published no receipt.
# It exists because cancel REFUSES exactly the case that most needs clearing: when
# the process identity changed, cancel raises "process identity changed before
# signal" and stops, which is correct -- signalling a possibly-recycled PID could
# kill an unrelated process. But that left the documented tool unable to resolve a
# stranded descriptor at all, and on 2026-08-09 the only exit was SIGKILL by hand.
#
# reap signals nothing. It admits only `process_not_live` and refuses a `mismatch`,
# so a recycled PID still stays an operator decision rather than being papered over.
if [[ "$#" -eq 2 && "$1" == "--reap" && "$2" == *.log ]]; then
    exec /usr/bin/python3 "$implementation_root/scripts/python/board_process_truth.py" \
        reap "$VAULT_ROOT" "$2"
fi

cat >&2 <<'USAGE'
usage: vs-cancel-spawn.sh <exact-log-path>          # cancel a live attempt
       vs-cancel-spawn.sh --reap <exact-log-path>   # clear a dead attempt that left no receipt

  cancel  signals an exact, verified live process and refuses if its identity changed.
  --reap  signals nothing; it terminalises an attempt whose process is already gone.
          Use it when cancel refuses with "process identity changed before signal".
USAGE
exit 2
