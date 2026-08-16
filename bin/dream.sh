#!/bin/bash
# bin/dream.sh — dispatch one shadow journal through the existing board rail.
#
# This runner does not dream. It renders shared/dreaming/packet-template.md and
# hands the result to bin/send-task.sh. All of the judgment — what to read, what
# counts as a pattern, what a journal looks like — lives in
# shared/dreaming/protocol.md, which the dispatched worker reads.
#
# Pass defaults to deep on Sunday and light otherwise. Set SQUAD_DREAM_PASS to
# override it; pass --dry-run to validate the rendered packet without dispatch.
# SQUAD_DREAM_STATE_DIR is a validated, _state-relative test/audit seam.
#
# Exit codes: 0 dispatched · 1 bad usage or render failure · 2 dry run.

set -euo pipefail
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

PASS="${SQUAD_DREAM_PASS:-}"
STATE_REL="${SQUAD_DREAM_STATE_DIR:-_state}"

die() { echo "dream: $*" >&2; exit 1; }

[[ $# -eq 0 || ( $# -eq 1 && "${1:-}" == "--dry-run" ) ]] || die "only --dry-run is supported; use SQUAD_DREAM_PASS to choose a pass"
DRY_RUN=$#

# Sunday (%u == 7) is the deep pass; every other night is a light skim.
[[ -n "${PASS}" ]] || { PASS="light"; [[ "$(date +%u)" == "7" ]] && PASS="deep"; }
[[ "${PASS}" =~ ^(light|deep)$ && "${STATE_REL}" =~ ^_state(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$ ]] || die "pass must be light/deep and state dir must stay under _state"

DATE="$(date +%Y-%m-%d)"

mkdir -p "${VAULT_ROOT}/${STATE_REL}/dream-packets"
# bin/send-task.sh:784 requires TASK-YYYY-MM-DD-HHMM-<alnum/hyphen>.
TASK_ID="TASK-$(date +%Y-%m-%d-%H%M)-dream-${PASS}"
PACKET="${VAULT_ROOT}/${STATE_REL}/dream-packets/${TASK_ID}.md"

sed -e "s|__TASK_ID__|${TASK_ID}|g" \
    -e "s|__PASS__|${PASS}|g" \
    -e "s|__JOURNAL_PATH__|${STATE_REL}/dream-logs/${DATE}.md|g" \
    "${VAULT_ROOT}/shared/dreaming/packet-template.md" \
    | PACKET_PATH="${PACKET}" PYTHONPATH="${VAULT_ROOT}/scripts/python" python3 -c 'import os,sys; from pathlib import Path; from registry_reconciler import atomic_write; atomic_write(Path(os.environ["PACKET_PATH"]), sys.stdin.read())'

# Same residual check bin/install-routines.sh applies to plists. This is the one
# validation worth doing here: send-task.sh checks the frontmatter fields itself
# and dies by name, but an unsubstituted token in the packet BODY would sail past
# it and reach the worker as literal text.
! grep -qE '__[A-Z][A-Z0-9_]*__' "${PACKET}" || die "unresolved template token in ${PACKET}"

[[ "${DRY_RUN}" == "0" ]] || exec "${VAULT_ROOT}/bin/send-task.sh" "${PACKET}" --dry-run
exec "${VAULT_ROOT}/bin/send-task.sh" "${PACKET}"
