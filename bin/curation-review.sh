#!/usr/bin/env bash
# Curation review: render _state/curation-queue.jsonl (Task 9's demotion
# queue) for Chrono to read at a session boundary.
#
# This is a RENDERER ONLY. It never sets `invalidated` -- flagging a note
# `not_useful`/`incorrect` is a 5-sample signal from one worker, nothing
# re-validates it, and this design deliberately adds no time-based decay
# (spec §9), so `invalidated` would be terminal if set here. That judgment is
# reserved for a human: see shared/curation-protocol.md for what Chrono does
# with each row (merge, repair attribution, supersede, or invalidate).
#
# Exit 0 for every completed render, whether the queue has rows, is present
# but empty, or is entirely absent -- each of those prints an explicit line so
# silence is never mistaken for breakage (the same lesson bin/doctor.sh's
# `note_absent_input` encodes for probe output). Exit 2 only when the queue
# exists and cannot be parsed -- that is real breakage, not an empty queue.
#
# If curation stalls again -- historically it does -- the result is a growing
# queue and a noisier ranking, not an outage. That is the point of keeping
# promotion out of this script entirely: do not "helpfully" wire it back in.

set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
VAULT="${VAULT_ROOT}"
QUEUE="${CURATION_QUEUE_UNDER_TEST:-${VAULT}/_state/curation-queue.jsonl}"
JQ_BIN="${CURATION_JQ_UNDER_TEST:-jq}"

# --since <ISO-8601 UTC>: render only flags recorded at or after this moment.
#
# The queue has no acknowledgement, no cursor and no archive, and
# curation-protocol.md §3 says a dismissed flag "stays in the queue's
# history" -- so without this every session boundary re-renders every flag
# ever recorded, with no way to tell a new one from one seen ten sessions
# ago. §5 claims the stall mode is "a growing queue and a correspondingly
# noisier ranking"; an undifferentiated queue does not degrade, it becomes
# unreadable, and an unreadable queue is an ignored queue. This is what
# makes the claimed stall mode the real one.
#
# Rows written before `ts` existed carry no timestamp. They are KEPT under
# --since, never dropped: a row whose age is unknown is not a row that is
# known to be old, and silently hiding it would lose exactly the backlog
# this flag exists to make navigable.
SINCE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --since)
            [[ $# -ge 2 ]] || { echo "ERROR: --since needs a value" >&2; exit 2; }
            SINCE="$2"
            shift 2
            ;;
        --since=*)
            SINCE="${1#--since=}"
            shift
            ;;
        -h|--help)
            echo "usage: curation-review.sh [--since <ISO-8601 UTC, e.g. 2026-08-17T00:00:00Z>]"
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done
if [[ -n "${SINCE}" ]] \
    && [[ ! "${SINCE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z?)?$ ]]; then
    echo "ERROR: --since must be an ISO-8601 UTC timestamp or date, not '${SINCE}'" >&2
    exit 2
fi

if ! command -v "${JQ_BIN}" >/dev/null 2>&1; then
    echo "ERROR: curation-review could not run: jq parser is unavailable (${JQ_BIN})" >&2
    exit 2
fi

if [[ ! -s "${QUEUE}" ]]; then
    echo "Curation queue empty -- nothing to review (${QUEUE})"
    exit 0
fi

jq_error="${QUEUE}.jq-error.$$"
report=""
if ! report=$("${JQ_BIN}" -s --raw-output --arg since "${SINCE}" '
    map(
        if (type == "object") and ((.note_id | type) == "string") and ((.reason | type) == "string")
        then .
        else error("curation queue row lacks typed note_id/reason")
        end
    ) |
    # A row with no `ts` predates the field and is kept: unknown age is not
    # known-old, and dropping it would hide the backlog --since exists to
    # make navigable. String comparison is exact for ISO-8601 UTC, which is
    # the only shape flag_for_curation writes and the only shape --since
    # accepts.
    map(select($since == "" or ((.ts | type) != "string") or (.ts >= $since))) |
    group_by(.note_id) |
    map({
        note_id: .[0].note_id,
        count: length,
        reasons: ([.[].reason] | group_by(.) | map("\(.[0]) x\(length)") | join(", ")),
        source_tasks: ([.[].source_task | select(. != null)] | unique | join(", ")),
        last_seen: ([.[].ts | select(type == "string")] | max // "")
    }) |
    sort_by(-.count) |
    .[] |
    "- **\(.note_id)** -- \(.count) flag" + (if .count == 1 then "" else "s" end)
        + " (\(.reasons))"
        + (if .source_tasks == "" then "" else " -- from \(.source_tasks)" end)
        + (if .last_seen == "" then " -- undated (predates `ts`)" else " -- last \(.last_seen)" end)
' "${QUEUE}" 2>"${jq_error}"); then
    jq_reason=$(head -1 "${jq_error}" 2>/dev/null || true)
    rm -f "${jq_error}"
    echo "ERROR: curation-review could not parse ${QUEUE}: ${jq_reason:-jq failed}" >&2
    exit 2
fi
rm -f "${jq_error}"

if [[ -z "${report}" ]]; then
    if [[ -n "${SINCE}" ]]; then
        # Distinct from an empty queue on purpose: "nothing new" and "nothing
        # at all" are different facts, and collapsing them is how a backlog
        # goes unnoticed.
        echo "No curation flags recorded since ${SINCE} -- nothing new to review (${QUEUE})"
    else
        echo "Curation queue empty -- nothing to review (${QUEUE})"
    fi
    exit 0
fi

echo "# Curation Review -- $(date -u +%F)"
echo
if [[ -n "${SINCE}" ]]; then
    echo "Flagged notes awaiting review (recorded since ${SINCE}), grouped by note_id. This is a renderer only -- it has not changed and will not change any note's status. See shared/curation-protocol.md for what to do with each row."
else
    echo "Flagged notes awaiting review, grouped by note_id. This is a renderer only -- it has not changed and will not change any note's status. See shared/curation-protocol.md for what to do with each row."
fi
echo
printf '%s\n' "${report}"
exit 0
