#!/bin/bash
# Print a tmux-formatted Chrono controller badge.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# shellcheck source=doctor-log-home.sh disable=SC1091
source "${VAULT_ROOT}/bin/doctor-log-home.sh" || exit $?

doctor_state() {
    local today summary issues warnings
    today="$(date -u +%Y-%m-%d)"
    summary="${CHRONO_DOCTOR_LOG_DIR}/${today}-summary.json"
    [[ -f "$summary" ]] || return 0
    issues="$(jq -r '.issue_count // 0' "$summary" 2>/dev/null || echo 0)"
    warnings="$(jq -r '.warning_count // 0' "$summary" 2>/dev/null || echo 0)"
    if [[ "$issues" =~ ^[0-9]+$ ]] && [[ "$issues" -gt 0 ]]; then
        echo "issues:${issues}"
        return 0
    fi
    if [[ "$warnings" =~ ^[0-9]+$ ]] && [[ "$warnings" -gt 0 ]]; then
        echo "warn:${warnings}"
        return 0
    fi
    echo "healthy"
}

# Every task count in this badge comes from ONE live source: the registry
# partition in scripts/python/chrono_state/registry.py.
#
# Why not a file read, and why no file precedence is correct. Neither task file
# on disk encodes liveness:
#
#   _state/tasks/active.json  — frozen by the 2026-07-24 one-shot migration and
#     fed by nothing since (registry.py:18-20 says so). It answers "what was
#     live three weeks ago"; measured 2026-08-13 it held 1 record while the
#     board held 14.
#   _state/active-tasks.json  — the registry the board does feed, but it retains
#     every terminal record (1,668 terminal of 1,737 total, measured
#     2026-08-13), so a raw status filter over it has no notion of live at all.
#
# Preferring one file over the other only chooses which way to be wrong. The
# live/deferred/unknown distinction exists ONLY in registry_view(), so that is
# what this reads. Same root cause as the resume.py defect written up in
# chrono/resume-contract-decision-record.md — this was the second call site that
# repair never reached.
#
# The status vocabulary is DERIVED from registry.py rather than restated here
# (Hard Rule 10: one fact, one home). A status added there is counted here
# automatically, and a status classified nowhere is reported as `unknown`
# instead of silently vanishing out of all three counts — the previous jq
# hardcoded `failed`, which the board has never once emitted, while missing
# needs_rework / timed_out / work-done-no-envelope, which it does.
#
# Prints "<active> <queued> <blocked> <unknown>", or "unavailable" if the
# partition cannot be computed. `unavailable` is deliberately NOT folded into
# zeros: a counter reading 0 because it is broken is indistinguishable from one
# reading 0 because nothing is wrong, which is the whole defect being fixed.
live_counts() {
    VAULT_ROOT="${VAULT_ROOT}" python3 - <<'PY' 2>/dev/null || echo unavailable
import os
import sys

root = os.environ["VAULT_ROOT"]
sys.path.insert(0, os.path.join(root, "scripts", "python"))
from chrono_state.registry import LIVE_REGISTRY, LIVE_STATUSES, registry_view

# registry_view() returns an empty partition for a missing registry, which reads
# as "nothing is happening". Distinguish absence from emptiness before counting.
if not LIVE_REGISTRY.exists():
    print("unavailable")
    raise SystemExit(0)

QUEUED = {"queued", "pending"}         # accepted, awaiting dispatch
ACTIVE = set(LIVE_STATUSES) - QUEUED   # dispatched / executing / awaiting settle
BLOCKED = {"blocked", "failed", "needs_human"}  # unchanged from the file-read version

view = registry_view()
live = [task["state"] for task in view["live"]]
deferred = [task["state"] for task in view["deferred"]]
unclassified = view["unclassified"]

blocked = sum(1 for state in deferred if state in BLOCKED)
# `failed` is not a status the live board emits, so it would arrive as an
# unclassified status rather than a deferred one. Counting BLOCKED out of both
# buckets keeps the meaning of "blocked" identical to the count this replaced.
blocked += sum(n for state, n in unclassified.items() if state in BLOCKED)

print(
    sum(1 for state in live if state in ACTIVE),
    sum(1 for state in live if state in QUEUED),
    blocked,
    sum(unclassified.values()),
)
PY
}

counts="$(live_counts)"
if [[ "$counts" =~ ^([0-9]+)\ ([0-9]+)\ ([0-9]+)\ ([0-9]+)$ ]]; then
    active="${BASH_REMATCH[1]}"
    queued="${BASH_REMATCH[2]}"
    blocked="${BASH_REMATCH[3]}"
    unknown="${BASH_REMATCH[4]}"
    registry_ok=1
else
    active=0
    queued=0
    blocked=0
    unknown=0
    registry_ok=0
fi
doctor="$(doctor_state)"

# Attention ladder, most urgent first. `registry:?` sits ABOVE active/queued/
# healthy on purpose: without a partition every count above it is a false zero,
# so the badge must never be able to read "healthy" merely because its source
# was unreadable. It sits below `issues:` only because a doctor issue count is
# measured independently of the registry and is equally loud and actionable.
if [[ "$blocked" -gt 0 ]]; then
    bg="colour203"
    fg="colour16"
    label="CHRONO blocked:${blocked}"
    if [[ "$unknown" -gt 0 ]]; then
        label="${label} unknown:${unknown}"
    fi
elif [[ "$doctor" == issues:* ]]; then
    bg="colour203"
    fg="colour16"
    label="CHRONO ${doctor}"
elif [[ "$registry_ok" -eq 0 ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO registry:?"
elif [[ "$unknown" -gt 0 ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO unknown:${unknown}"
elif [[ "$doctor" == warn:* ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO ${doctor}"
elif [[ "$active" -gt 0 ]]; then
    bg="colour118"
    fg="colour16"
    label="CHRONO active:${active}"
elif [[ "$queued" -gt 0 ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO queued:${queued}"
else
    bg="colour45"
    fg="colour16"
    label="CHRONO healthy"
fi

printf '#[bg=%s,fg=%s,bold] %s #[bg=default,fg=colour238]' "$bg" "$fg" "$label"
