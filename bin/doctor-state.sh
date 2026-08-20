#!/usr/bin/env bash
# One home for one fact (CLAUDE.md rule 10): how a doctor summary collapses to
# a single status token.
#
# THIS FILE IS THE WINNER. Two renderers need the same token and cannot share a
# process:
#
#   bin/chrono-status-segment.sh  sources this file and calls doctor_state().
#   bin/vs-lane-status.sh         carries a PYTHON MIRROR of doctor_state()
#                                 inside its poller heredoc, because that heredoc
#                                 runs once a second and calling out to a shell
#                                 (plus jq) per tick would re-add the process
#                                 spawns Plan C Task 6.3 exists to remove.
#
# The mirror is legitimate only because scripts/python/tests/test_doctor_status_token.py
# runs BOTH against the same fixtures and fails if they ever disagree. If you
# change the vocabulary here, that test tells you the mirror is stale.
#
# Requires CHRONO_DOCTOR_LOG_DIR (bin/doctor-log-home.sh) to be set by the
# sourcing script. This file is sourced, never executed, so it declares no
# `set -e` / `set -u` / `set -o pipefail` of its own -- those would mutate the
# CALLER's shell. Same position as bin/doctor-log-home.sh and
# shared/process-identity.sh, and the same reason it resolves no repo root of
# its own: a sourced library inherits its caller's.

# Print the doctor token for today's summary, or nothing at all.
#
#   issues:N   at least one doctor ISSUE  -- the only state that earns amber
#   warn:N     no issues, at least one warning
#   healthy    a summary exists and reports neither
#   <empty>    NO READING: no summary for today, or one that cannot be parsed
#
# Empty is deliberately not folded into `healthy`. A summary that jq cannot read
# is not evidence of health, and the caller can render the difference (the poller
# prints `doctor:?`). The date is UTC because bin/doctor.sh names the file with
# UTC (`date -u +%Y-%m-%d`); a local-time lookup asks for a filename that does
# not exist for part of every day west of Greenwich.
doctor_state() {
    local today summary counts issues warnings
    today="$(date -u +%Y-%m-%d)"
    summary="${CHRONO_DOCTOR_LOG_DIR}/${today}-summary.json"
    [[ -f "$summary" ]] || return 0
    # One jq invocation for both counts, not two: this runs on a render path.
    # A missing jq, an unreadable file, or malformed JSON all land here and all
    # mean the same thing -- no reading.
    counts="$(jq -r '((.issue_count // 0)|tostring) + " " + ((.warning_count // 0)|tostring)' \
        "$summary" 2>/dev/null)" || return 0
    # jq exits 0 with NO output on an empty file. Without this, an empty summary
    # read as two empty counts and rendered `healthy` -- a broken measurement
    # reported as good news, which is the whole class of bug being removed here.
    [[ -n "$counts" ]] || return 0
    read -r issues warnings <<<"$counts"
    # `10#` forces base 10. Without it `$((008))` is a syntax error and
    # `$((010))` is 8, so a zero-padded count would disagree with the Python
    # mirror -- which is exactly the drift this file exists to prevent.
    if [[ "$issues" =~ ^[0-9]+$ ]] && (( 10#$issues > 0 )); then
        echo "issues:$((10#$issues))"
        return 0
    fi
    if [[ "$warnings" =~ ^[0-9]+$ ]] && (( 10#$warnings > 0 )); then
        echo "warn:$((10#$warnings))"
        return 0
    fi
    echo "healthy"
}
