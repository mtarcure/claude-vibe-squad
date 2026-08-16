#!/usr/bin/env bash
# Cancel one exact board attempt after verifying its v2 OS process identity.
set -u

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
wrapper_path="$(vs_resolve_symlink "${BASH_SOURCE[0]}")" || exit 1
implementation_root="$(cd -- "$(dirname -- "$wrapper_path")/.." && pwd -P)" || exit 1

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
