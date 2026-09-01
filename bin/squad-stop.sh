#!/bin/bash
# Squad-stop — graceful close with transient shutdown summary.
#
# Two-phase:
#   1. Request Chrono update live current.md state and write a transient summary
#      (60s timeout)
#   2. If Chrono didn't respond, synthesize a baseline summary mechanically
#      from filesystem state (current.md files + recent dispatch log + outboxes)
#   3. Kill the squad session
#
# Result: every squad close may produce an ignored runtime summary at:
#   _state/shutdown-summaries/YYYY-MM-DD-HHMM-session-end.md
#
# Resume on next launch uses _state/active-tasks.json and current.md files.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# VAULT_ROOT is runtime-configurable.
# shellcheck disable=SC1091
source "${VAULT_ROOT}/shared/namespaces.sh"
# bin/launch-squad.sh honours SQUAD_SESSION for the session it creates; this
# script used to hardcode the literal "squad" at every tmux call site, so
# under a custom session name it silently reported "No squad session
# running" and exited 0 -- a no-op that left the whole custom-named session
# (and everything it owns) running. Plan B Task 7.
SESSION="${SQUAD_SESSION:-squad}"
SUMMARY_DIR="${VAULT_ROOT}/_state/shutdown-summaries"
DATESTAMP="$(date -u +%Y-%m-%d-%H%M)"
SUMMARY_FILE="${SUMMARY_DIR}/${DATESTAMP}-session-end.md"

mkdir -p "${SUMMARY_DIR}"

# If no squad session, nothing to do
if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "No squad session '${SESSION}' running. Nothing to stop."
    exit 0
fi

# --- Discover the live orchestrator (Phase 1 no longer assumes the pane) ----
# LIFE-01. This stop used to send its Phase-1 nudge blindly to the fixed
# squad:chrono pane and wait 60s -- assuming the orchestrator IS that pane. That
# is the normal shape, not the only one: a coordinator started as a background
# job (parented by `claude daemon`, TMUX unset) has no pane, so the nudge lands
# in whatever holds squad:chrono (an idle shell, or nothing), times out, and
# reports `chrono_responded: false` -- which reads exactly like "Chrono was
# there and stayed silent". Discovery replaces that assumption and, crucially,
# tells "found but not nudgeable" and "nothing to nudge" APART from a real
# timeout.
#
# Discovery AUTHORITY is a coordinator pidfile (LIFE-01 option (a): discover,
# don't assume). bin/vs-welcome.sh -- the coordinator's OWN startup, which execs
# claude, so its $$ becomes the claude process -- writes it, recording the real
# coordinator PID, a start-time fingerprint, and the shape it is: the nudgeable
# PANE (${SESSION}:chrono) when it runs inside tmux, or the un-nudgeable
# BACKGROUND-JOB shape (no pane) when it does not. Recording the coordinator's
# own PID+fingerprint -- not the pane's shell observed from outside, which this
# reader's */claude* test then rejected -- is what makes the record one this
# reader BELIEVES. Checked before adding a new file: the job dir (CLAUDE_JOB_DIR)
# is a harness env var this repo never reads, and the launchd daemon
# (com.vibesquad.daemon) is separate infra that does not track Chrono -- neither
# is an existing authority. This reader is shape-independent: the same three
# outcomes fall out of it whichever shape the coordinator recorded.
CHRONO_COORDINATOR_PIDFILE="${CHRONO_COORDINATOR_PIDFILE:-${VAULT_ROOT}/_state/runtime/chrono-coordinator/${SESSION}.pid}"

# chrono_pane_has_coordinator() lives in shared/chrono-pane.sh, the one home for
# "is the coordinator the live foreground process in that pane?" -- version
# independent, so a Claude release cannot silently break it. bin/outbox-watcher.sh
# and bin/squad-monitor.sh already source it; this stop was the last lifecycle
# path still ASSUMING the pane rather than asking it.
CHRONO_PANE_READY=1
# shellcheck source=../shared/chrono-pane.sh disable=SC1091
source "${VAULT_ROOT}/shared/chrono-pane.sh" || CHRONO_PANE_READY=0
if [[ "${CHRONO_PANE_READY}" != "1" ]]; then
    # set -uo pipefail without -e: a failed source would leave the function
    # undefined and every call returning 127, indistinguishable from "no
    # coordinator there". Define an explicit refusal so discovery leans on the
    # pidfile alone and says so.
    chrono_pane_has_coordinator() { return 1; }
    echo "  WARNING: ${VAULT_ROOT}/shared/chrono-pane.sh failed to load; cannot inspect the ${SESSION}:chrono pane for a live coordinator. Orchestrator discovery relies on the coordinator pidfile only." >&2
fi

# parse_coordinator_pidfile <pidfile>: echo "<shape> <pid> <target> <start>" on
# one line for a well-formed file, nothing (rc1) otherwise. Pure file parse -- no
# process inspection -- so scripts/python/tests/test_squad_stop_reaping.py drives
# it with synthetic files. Format (written by bin/vs-welcome.sh): "key value"
# lines pid/shape/target/start, order-independent, unknown keys ignored, a bad
# pid or shape rejected. `target` may be empty (a background job has no pane) and
# `start` may be empty (a synthetic/legacy file with no fingerprint); both are
# emitted as a "-" sentinel so the four space-separated fields stay positionally
# unambiguous even though `start` (a kernel lstart string) itself contains
# spaces. discover_orchestrator reads it back as `shape pid target start` -- the
# multi-word start lands in the last field -- and restores "" from "-".
parse_coordinator_pidfile() {
    local pidfile="$1" key val pid="" shape="" target="" start=""
    [[ -f "${pidfile}" ]] || return 1
    while read -r key val; do
        case "${key}" in
            pid) pid="${val}" ;;
            shape) shape="${val}" ;;
            target) target="${val}" ;;
            start) start="${val}" ;;
        esac
    done < "${pidfile}"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    [[ "${shape}" == "pane" || "${shape}" == "background-job" ]] || return 1
    printf '%s %s %s %s\n' "${shape}" "${pid}" "${target:--}" "${start:--}"
}

# coordinator_pid_is_live_claude <pid>: true only if $1 is alive AND its
# executable path looks like the claude CLI -- the SAME `*/claude*` test
# shared/chrono-pane.sh applies to a pane child, identical on purpose so "what
# counts as the coordinator process" has one answer (CLAUDE.md rule 10). By
# itself this is NOT sufficient identity: a PID recycled onto an unrelated
# `claude` (a board worker on the claude lane is `claude` too) passes it. That
# gap is closed by discover_orchestrator, which pairs this with
# pid_identity_still_matches() against the recorded start-time fingerprint -- the
# recycled worker started at a different moment, so the pair rejects it. This
# reader never KILLS on the strength of it -- it only chooses nudge-vs-report --
# so even a bare match misreports, it does not destroy.
coordinator_pid_is_live_claude() {
    local pid="$1" cmd
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    kill -0 "${pid}" 2>/dev/null || return 1
    cmd="$(ps -o command= -p "${pid}" 2>/dev/null)"
    [[ "${cmd}" == */claude* ]] || return 1
    return 0
}

# --- process-identity fingerprint (used by BOTH discover_orchestrator below and
# the descendant reaping in Phase 5) --------------------------------------------
# Records $1's kernel start time as a single normalized string. Used as a
# cheap process-identity fingerprint (Plan B Task 7 fix round 1): a PID
# alone does not identify a process across time -- it can be recycled by an
# unrelated process between when it was snapshotted and when it is acted
# on. `lstart` (not `etime`) because it is an absolute wall-clock value, so
# two queries of the SAME process always agree regardless of how much time
# passed between them, while a different process reusing the same PID
# almost certainly started at a different moment. bin/vs-welcome.sh records the
# coordinator's start with the SAME `ps -o lstart=` normalization so the writer
# and this reader agree (CLAUDE.md rule 10; the CoordinatorPidfile semantic
# round-trip test drives writer into reader on a live process to prove it).
pid_start_time() {
    ps -o lstart= -p "$1" 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//'
}

# True only if $1 is BOTH currently alive AND its start time still matches
# $2, the value recorded for it. A mismatch (or an empty recorded value,
# e.g. a PID this record never actually saw) means $1 is no longer -- or
# never was -- the specific process that was recorded, so it must never be
# treated as the recorded coordinator (or as a survivor of the Phase 5 kill).
#
# LIFE-03c: this file is the ONE home for the coordinator identity check. The
# coordinator exit recorder in bin/launch-squad.sh carries a byte-faithful copy
# of pid_start_time / pid_identity_still_matches inside the single-line command
# it sends to the chrono pane (a fresh shell cannot source this script -- doing
# so would run the whole stop), and uses it to decide whether to clear a stale
# squad.pid on exit. It reuses THIS scheme rather than inventing a second one;
# test_squad_stop_reaping.py drives both and asserts they reach the same verdict.
pid_identity_still_matches() {
    local pid="$1" recorded_start="$2" current_start
    kill -0 "${pid}" 2>/dev/null || return 1
    [[ -n "${recorded_start}" ]] || return 1
    current_start="$(pid_start_time "${pid}")"
    [[ -n "${current_start}" ]] || return 1
    [[ "${current_start}" == "${recorded_start}" ]]
}

# discover_orchestrator: echo exactly one of
#   "pane <tmux-target>"    a live coordinator is nudgeable in that pane
#   "background-job <pid>"  a live coordinator with no pane (NOT nudgeable)
#   "none"                  no live orchestrator found anywhere we can look
# Depends only on parse_coordinator_pidfile, coordinator_pid_is_live_claude,
# pid_identity_still_matches and chrono_pane_has_coordinator (all injectable),
# plus CHRONO_COORDINATOR_PIDFILE, CHRONO_PANE_READY and SESSION -- so the routing
# is driven directly by the test with stubs, the same way reap_pidfile_process()
# takes an injected identity check.
discover_orchestrator() {
    local parsed shape pid target start
    if parsed="$(parse_coordinator_pidfile "${CHRONO_COORDINATOR_PIDFILE}")"; then
        read -r shape pid target start <<<"${parsed}"
        [[ "${target}" == "-" ]] && target=""
        [[ "${start}" == "-" ]] && start=""
        # Trust the recorded PID only when it is BOTH a live claude AND the SAME
        # process instance the coordinator recorded at startup -- verified by the
        # start-time fingerprint. A PID recycled onto an unrelated claude board
        # worker is live-and-claude but started at a different moment, so identity
        # fails and it is NOT reported as the coordinator: this is the recycled-PID
        # false positive the cross-family review found. An empty recorded start
        # (synthetic/legacy file) fails closed here.
        if coordinator_pid_is_live_claude "${pid}" && pid_identity_still_matches "${pid}" "${start}"; then
            case "${shape}" in
                pane)
                    # The recorded pane target counts only if the coordinator is
                    # STILL the live foreground process there -- it may have exited
                    # or moved since launch. When shared/chrono-pane.sh LOADED, it
                    # is that authority and a stale target falls through, never
                    # nudged. When it FAILED to load (CHRONO_PANE_READY != 1), the
                    # identity-matched live claude above is itself an independent
                    # authority -- the whole reason the coordinator records its
                    # real PID+fingerprint -- so trust the recorded target rather
                    # than collapsing a live coordinator into `none` (review P1).
                    if [[ -n "${target}" ]]; then
                        if chrono_pane_has_coordinator "${target}"; then
                            printf 'pane %s\n' "${target}"
                            return 0
                        elif [[ "${CHRONO_PANE_READY:-1}" != "1" ]]; then
                            printf 'pane %s\n' "${target}"
                            return 0
                        fi
                    fi
                    ;;
                background-job)
                    printf 'background-job %s\n' "${pid}"
                    return 0
                    ;;
            esac
        fi
    fi
    # No usable pidfile -- the backward-compatible path for a session launched
    # before this pidfile existed. Ask the pane directly, the exact question the
    # old code assumed the answer to.
    if chrono_pane_has_coordinator "${SESSION}:chrono"; then
        printf 'pane %s\n' "${SESSION}:chrono"
        return 0
    fi
    printf 'none\n'
    return 0
}

# orchestrator_report_line <shape> <ref>: the operator-facing one-liner for each
# outcome. Factored out so the test can assert the three DIFFER -- the LIFE-01
# proof that "no orchestrator" no longer reads like a nudge timeout.
orchestrator_report_line() {
    case "$1" in
        pane) printf 'Live orchestrator found in tmux pane %s; requesting a live-state update.\n' "$2" ;;
        background-job) printf 'Live orchestrator found as a BACKGROUND JOB (PID %s) with no tmux pane; it cannot be nudged via tmux, so NO live-state update was requested. Synthesizing the baseline summary from filesystem state instead.\n' "$2" ;;
        none) printf 'NO live orchestrator found: no coordinator pidfile names a live claude process and the %s:chrono pane does not host the coordinator. This is NOT a nudge timeout -- nothing was nudged. Synthesizing the baseline summary from filesystem state.\n' "${SESSION}" ;;
        *) printf 'Orchestrator discovery returned an unrecognized shape %s.\n' "$1" ;;
    esac
}

# Phase 1 — discover the live orchestrator, then (only if it is a nudgeable
# pane) ask it to update canonical live state and optionally write a summary.
discovered="$(discover_orchestrator)"
read -r orch_shape orch_ref <<<"${discovered}"
echo "Squad close initiated (session: ${SESSION}). $(orchestrator_report_line "${orch_shape}" "${orch_ref}")"

chrono_responded=0
if [[ "${orch_shape}" == "pane" ]]; then
    NUDGE_MSG="Operator is closing the squad session. Update chrono/current.md and any affected departments/*/current.md so live state is accurate. Do not write docs/handoffs. If useful, write a transient shutdown summary to ${SUMMARY_FILE} with in-flight task IDs, queued work, and anything next launch should see after reading current.md. Confirm by appending 'SHUTDOWN SUMMARY DONE' to that file. After confirming, the operator will close the session."

    tmux send-keys -l -t "${orch_ref}" "${NUDGE_MSG}"
    sleep 0.3
    tmux send-keys -t "${orch_ref}" Enter

    # Poll for summary file with marker — up to 60s
    echo "Waiting up to 60s for Chrono to update state..."
    deadline=$(( $(date +%s) + 60 ))
    while [[ $(date +%s) -lt ${deadline} ]]; do
        if [[ -f "${SUMMARY_FILE}" ]] && grep -q "SHUTDOWN SUMMARY DONE" "${SUMMARY_FILE}" 2>/dev/null; then
            chrono_responded=1
            break
        fi
        sleep 2
    done
else
    # background-job or none: nothing to nudge. Repeat the specific reason on
    # stderr so it survives in an operator's error stream, not only stdout.
    orchestrator_report_line "${orch_shape}" "${orch_ref}" >&2
fi

# Frontmatter for the mechanical summary depends on WHY Chrono did not write its
# own: a real 60s timeout (pane, nudged, silent) is a different fact from "not
# nudgeable" or "no orchestrator", and the file must not blur them.
case "${orch_shape}" in
    pane)
        summary_status="transient-session-closed-via-fallback"
        summary_responded="false"
        summary_orchestrator="pane ${orch_ref} (nudged; no response in 60s)"
        summary_reason="Chrono did not respond to the shutdown request within 60s"
        ;;
    background-job)
        summary_status="transient-session-closed-orchestrator-unreachable-by-nudge"
        summary_responded="n/a"
        summary_orchestrator="background-job PID ${orch_ref} (no tmux pane; not reachable by nudge)"
        summary_reason="the live orchestrator is a background job with no tmux pane, so it was never nudged"
        ;;
    *)
        summary_status="transient-session-closed-no-orchestrator"
        summary_responded="n/a"
        summary_orchestrator="none-found"
        summary_reason="no live orchestrator was found, so nothing was nudged"
        ;;
esac

# Phase 2 — fallback: synthesize mechanically if Chrono did not write its own.
if [[ ${chrono_responded} -eq 0 ]]; then
    echo "Synthesizing baseline summary from filesystem state (${summary_reason})..."

    {
        echo "---"
        echo "date: $(date '+%Y-%m-%d %H:%M %Z')"
        echo "status: ${summary_status}"
        echo "chrono_responded: ${summary_responded}"
        echo "orchestrator: ${summary_orchestrator}"
        echo "---"
        echo ""
        echo "# Session-end shutdown summary (auto-synthesized)"
        echo ""
        echo "Generated by \`bin/squad-stop.sh\` because ${summary_reason}. This file is ignored runtime context, not durable product truth. Resume from \`_state/active-tasks.json\`, \`chrono/current.md\`, and each source namespace's \`current.md\`."
        echo ""
        echo "## Coordinator state (\`chrono/current.md\`)"
        echo ""
        echo '```markdown'
        cat "${VAULT_ROOT}/chrono/current.md" 2>/dev/null || echo "(missing)"
        echo '```'
        echo ""
        echo "## Per-namespace current state"
        for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
            echo ""
            echo "### ${namespace}"
            echo '```markdown'
            cat "${VAULT_ROOT}/departments/${namespace}/current.md" 2>/dev/null || echo "(missing)"
            echo '```'
        done
        echo ""
        echo "## Recent dispatch log (last 20)"
        echo ""
        echo '```'
        tail -20 "${VAULT_ROOT}/_state/dispatch-log.jsonl" 2>/dev/null || echo "(no dispatch log)"
        echo '```'
        echo ""
        echo "## In-flight outboxes (today's responses awaiting Chrono surfacing)"
        echo ""
        for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
            today=$(date -u +%Y-%m-%d)
            files=$(ls -1 "${VAULT_ROOT}/departments/${namespace}/outbox/" 2>/dev/null | grep "${today}" || true)
            if [[ -n "${files}" ]]; then
                echo "- **${namespace}**: ${files}"
            fi
        done
        echo ""
        echo "## Active mailbox state"
        bash "${VAULT_ROOT}/bin/where-are-we.sh" 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' || echo "(where-are-we.sh failed)"
        echo ""
        echo "---"
        echo ""
        echo "**SHUTDOWN SUMMARY DONE** (mechanical fallback)"
    } > "${SUMMARY_FILE}"
fi

echo "Shutdown summary: ${SUMMARY_FILE}"

# Phase 3 — clean up mode-spawned external resources before kill
# Per shared/lifecycle.md rule 13 (mode-close cleanup), kill orphan Chrome
# profiles spawned by Playwright MCP / chrome-devtools-mcp during this session.
# NEVER kill the operator's main Chrome at port 9222 -- that invariant is
# stated once, just below this phase, and enforced by BOTH this phase and
# Phase 5's process-group reap.
#
# Was `pgrep -f "user-data-dir=${profile}"` (Plan B Task 8): an unanchored
# argv substring scan feeding `xargs kill` directly -- ANY process on the
# host whose command line happens to contain this text anywhere (a
# specialist's compiled prompt discussing Playwright/chrome-devtools-mcp
# setup is plain-text argv too, measured at tens of KB) would be killed.
# These profiles are spawned by third-party MCP tooling, not by this repo, so
# there is no pidfile of our own to check -- argv matching is genuinely
# unavoidable here. Replaced with an executable-name gate (must look like an
# actual Chrome/Chromium binary; a specialist process never is one) plus an
# exact-token match on the real `--user-data-dir=<profile>` flag as its own
# shlex token, never "does this text appear somewhere in the raw command
# string" -- the browser always emits this as one discrete argv element, so
# real matches are unaffected and unstructured prose cannot forge one.
echo ""
echo "Cleaning up mode-spawned Chrome profiles..."

# Args: $1 profile path prefix. Prints "<pid> <pgid>" for every live process
# that really is a Chrome/Chromium launched with --user-data-dir=<profile>...
#
# One predicate, one home (CLAUDE.md rule 10). This same function answers both
# questions this script asks about a browser: "which mode-spawned profiles do I
# kill" (immediately below) and "which process groups must Phase 5 never reap"
# (the operator's persistent CDP Chrome, right after). Two phases of this file
# previously held OPPOSITE policies on the same browser because each answered
# in its own way -- see the stated policy below Phase 3.
chrome_profile_processes() {
    python3 - "$1" <<'PY'
import shlex
import subprocess
import sys


IDENTITY_TOKEN_LIMIT = 6  # generous even for "Google Chrome.app/.../Google Chrome"


def is_mode_spawned_chrome_profile(command: str, profile: str) -> bool:
    """True only for a real Chrome/Chromium process actually launched with
    --user-data-dir=<profile>... as its own argv token -- never for a
    process whose command line merely CONTAINS that text somewhere (a
    specialist's compiled prompt is plain-text argv too, and can run to tens
    of KB). Extracted as a standalone function so it can be driven directly
    by scripts/python/tests/test_argv_guard_false_positive.py without
    invoking this whole script or a real `ps`.

    Real Chrome/Chromium binary paths can contain spaces ("Google Chrome.app/
    Contents/MacOS/Google Chrome"), and `ps`'s plain command-line text does
    not preserve the original shell quoting that would let a space-joined
    display string be split back into "argv[0]" unambiguously. So instead of
    trying to isolate exactly one "executable" token, the identity check
    collects tokens up to (not including) the first one that looks like a
    flag ("-..."), capped at IDENTITY_TOKEN_LIMIT either way. Stopping at the
    first flag excludes the --user-data-dir value itself from the identity
    scan -- that value is a path under a directory literally named
    "chrome-devtools-mcp"/"mcp-chrome-", so scanning it too would make the
    executable-name gate nearly meaningless. The hard cap on top is what
    keeps a multi-KB blob of prose with no leading flag at all (so nothing
    would otherwise stop the scan) from ever reaching this gate's "chrome"
    check with the whole blob.
    """
    flag_prefix = f"--user-data-dir={profile}"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    identity_tokens = []
    for token in tokens[:IDENTITY_TOKEN_LIMIT]:
        if token.startswith("-"):
            break
        identity_tokens.append(token)
    identity = " ".join(identity_tokens).lower()
    if "chrome" not in identity and "chromium" not in identity:
        return False
    return any(token.startswith(flag_prefix) for token in tokens)


profile = sys.argv[1]
rows = subprocess.check_output(["ps", "-axo", "pid=,pgid=,command="], text=True).splitlines()
for row in rows:
    parts = row.strip().split(None, 2)
    if len(parts) < 3:
        continue
    pid, pgid, command = parts
    if is_mode_spawned_chrome_profile(command, profile):
        print(pid, pgid)
PY
}

for profile in \
    "${HOME}/Library/Caches/ms-playwright/mcp-chrome-" \
    "${HOME}/.cache/chrome-devtools-mcp/chrome-profile"
do
    pids=$(chrome_profile_processes "${profile}" | awk '{print $1}') || true
    if [[ -n "${pids}" ]]; then
        echo "  Killing ${profile}* processes: ${pids}"
        echo "${pids}" | xargs kill 2>/dev/null || true
    fi
done

# --- The persistent CDP Chrome: ONE policy, honoured by every phase --------
# NEVER kill the operator's main Chrome at port 9222
# (--user-data-dir=~/.chrono/chrome-persistent-profile, launched by
# bin/chrome-bootstrap.sh). It holds authenticated bounty sessions; losing it
# is the most expensive thing this script could do, and it is not
# mode-spawned state this stop is responsible for.
#
# Phase 3 above honours that by construction: it only ever selects the two MCP
# profile prefixes, and neither is a prefix of the persistent one. Phase 5
# below did NOT. It TERMs and then KILLs the process GROUP of every surviving
# descendant of every pane in the session, and bin/chrome-bootstrap.sh `exec`s
# Chrome directly -- which is how the script is meant to be run -- so a Chrome
# started from inside a squad pane IS a pane descendant. If it survived
# kill-session's SIGHUP (started under nohup, disown, or its own session), its
# whole group was reaped. Two phases of one file, added in the same task, with
# opposite policies on the same process; the exclusion below is what keeps
# them from drifting apart again.
#
# Recorded as process GROUPS, not PIDs: Chrome's helper processes share the
# main browser's pgid (verified on this host: a Helper (Renderer) at pid 23378
# carries pgid 51149, the browser's), so a group kill aimed at any one helper
# takes the browser with it. Captured BEFORE the session kill for the same
# reason Phase 3c captures its descendants there: afterwards the processes may
# be gone and the link used to find them is lost.
PERSISTENT_CHROME_PROFILE="${HOME}/.chrono/chrome-persistent-profile"
PROTECTED_CHROME_PGIDS=""
PROTECTED_CHROME_SCAN_OK=0

# Populates PROTECTED_CHROME_PGIDS and PROTECTED_CHROME_SCAN_OK, keeping the
# three states apart: scan succeeded and found the browser, scan succeeded and
# found none, and the scan ITSELF failed.
#
# The scan's exit status has to be captured, because "" is otherwise
# indistinguishable from "the persistent Chrome is not running". This script
# runs `set -uo pipefail` without -e, so an unchecked pipeline whose `python3`
# is off PATH, or whose inner `ps` raises, yields an empty string, every group
# then reads as unprotected, and Phase 5 silently reverts to exactly the
# pre-fix behaviour -- a guard reporting success while doing nothing, which is
# the defect this whole plan is named after.
#
# Note the asymmetry that makes this worth the branch: Phase 3 runs the same
# scan and a failure there fails SAFE (it kills nothing). Here a failure fails
# UNSAFE (it protects nothing), and the cost is the operator's authenticated
# bounty sessions.
#
# `local scanned` is deliberately its own statement: `local scanned="$(...)"`
# would report `local`'s exit status, not the pipeline's, and swallow the very
# failure this function exists to notice.
capture_protected_chrome_pgids() {
    local scanned
    if scanned="$(chrome_profile_processes "${PERSISTENT_CHROME_PROFILE}" | awk '{print $2}' | sort -u | tr '\n' ' ')"; then
        PROTECTED_CHROME_PGIDS="${scanned% }"
        PROTECTED_CHROME_SCAN_OK=1
        if [[ -n "${PROTECTED_CHROME_PGIDS}" ]]; then
            echo "  Protecting the operator's persistent CDP Chrome (process group(s): ${PROTECTED_CHROME_PGIDS})"
        else
            echo "  No persistent CDP Chrome is running; no process group to protect."
        fi
        return 0
    fi
    PROTECTED_CHROME_PGIDS=""
    PROTECTED_CHROME_SCAN_OK=0
    echo "  WARNING: could not scan for the operator's persistent CDP Chrome (${PERSISTENT_CHROME_PROFILE}); the scan itself failed rather than finding nothing." >&2
    echo "  Phase 5 will therefore reap NOTHING: without that scan this script cannot tell which process groups would take the operator's authenticated browser with them, and leaving orphans is recoverable where killing that browser is not. Any survivors are named individually below." >&2
    return 1
}
capture_protected_chrome_pgids || true

# True if $1 is a process group this script has promised never to kill.
#
# Consulted both when Phase 5 SELECTS survivors and again inside
# reap_survivor_group() immediately before it signals, so neither the
# announcement nor the kill can go out for a protected group.
#
# A failed scan answers "protected" for EVERY group, deliberately. This is the
# enforcement point, and an enforcement point must not be able to fail open:
# if the Phase 5 skip above it were ever reordered or removed, the refusal
# still holds here.
pgid_is_protected_chrome() {
    local candidate="$1" protected
    [[ "${PROTECTED_CHROME_SCAN_OK:-0}" == "1" ]] || return 0
    [[ -n "${candidate}" ]] || return 1
    for protected in ${PROTECTED_CHROME_PGIDS:-}; do
        [[ "${candidate}" == "${protected}" ]] && return 0
    done
    return 1
}

# Phase 3b — reap the live-status poller.
# bin/launch-squad.sh starts vs-lane-status.sh with `nohup ... & disown`
# specifically so it survives the *launcher's own* exit -- but that also
# means it is never a pane child, so the tmux kill-session below cannot
# reach it. Proof this is real: a 7-day-old orphaned poller was found on
# this host, writing status files every ~1s the entire time. Read the SAME
# pidfile launch-squad.sh writes at spawn (see its "Live status poller"
# section) and kill by pidfile, never by scanning `ps` for the script name
# (Plan B Task 8 is why that would be unsound). Plan B Task 7.
echo ""
echo "Reaping live-status poller..."
VS_LANE_STATUS_STATUS_DIR="${VIBESQUAD_STATUS_DIR:-/tmp}"
VS_LANE_STATUS_PIDFILE="${VS_LANE_STATUS_STATUS_DIR}/vs-lane-status.pid"

# pid_is_vs_lane_status_poller() verifies the live process at $1 is still,
# structurally, the vs-lane-status.sh poller this pidfile named at spawn time --
# not merely "some process is alive at this PID". Plan B Task 7 fix round 1:
# this pidfile can go stale for days (from whenever the poller last crashed
# until the next `squad stop`), unlike the Phase 3c/5 board-specialist
# window below (sub-second to low seconds), so PID reuse here is a real
# risk, not a theoretical one -- a script whose whole job is killing
# processes must not kill by bare recycled PID.
#
# The predicate itself lives in shared/process-identity.sh because
# bin/launch-squad.sh asks the same question from the other side (Plan B Task
# 12: is a live poller running that my pidfile does not name?), and the two
# answers must never disagree.
#
# This script runs `set -uo pipefail` without -e on purpose, so a failed
# `source` would otherwise continue with the predicate undefined: the identity
# call below returns 127, and reap_pidfile_process() reports "alive but no
# longer identifies as ... (stale/recycled PID)" about a process that IS the
# poller, then deletes the only record of it. A confident, specific, wrong
# reason for leaking the exact process this file exists to reap. Record the
# failure instead and let the reap decide what to do about it.
VS_LANE_STATUS_IDENTITY_READY=1
# shellcheck source=../shared/process-identity.sh disable=SC1091
source "${VAULT_ROOT}/shared/process-identity.sh" || VS_LANE_STATUS_IDENTITY_READY=0

reap_pidfile_process() {
    local pidfile="$1" label="$2" identity_check="$3" pid
    [[ -f "${pidfile}" ]] || return 0
    pid="$(cat "${pidfile}" 2>/dev/null)"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
        if "${identity_check}" "${pid}"; then
            echo "  Killing ${label}: ${pid}"
            kill "${pid}" 2>/dev/null || true
        else
            echo "  NOT killing ${label} pidfile PID ${pid}: alive but no longer identifies as ${label} (stale/recycled PID). Removing the pidfile only." >&2
        fi
    fi
    rm -f "${pidfile}"
}
# Refuse only the identity-dependent step, rather than exiting: the rest of this
# stop (the tmux session, the board specialists, the Chrome profiles) does not
# need the predicate, and a stopper that aborts here would leave far more
# running than it reaped. The pidfile is deliberately LEFT IN PLACE -- it names
# the poller, and it is the only record of it, so deleting it while unable to
# check the PID would destroy the operator's one lead.
if [[ "${VS_LANE_STATUS_IDENTITY_READY}" == "1" ]]; then
    reap_pidfile_process "${VS_LANE_STATUS_PIDFILE}" "vs-lane-status.sh poller" pid_is_vs_lane_status_poller
else
    echo "  NOT reaping the vs-lane-status.sh poller: ${VAULT_ROOT}/shared/process-identity.sh failed to load, so its PID cannot be verified and killing by bare PID is unsafe. ${VS_LANE_STATUS_PIDFILE} is left intact -- read it and kill by PID after checking \`ps -o args= -p <pid>\`. Every other phase of this stop continues." >&2
fi

# Phase 3c — snapshot this session's process tree before the kill.
# Board specialists are spawned by board-supervisor.sh via
# `subprocess.Popen(..., start_new_session=True)` (board-supervisor.sh:2664)
# so each one becomes its own process-group/session leader. A process with
# no controlling-terminal relationship to the pane never receives the SIGHUP
# tmux kill-session delivers to ordinary pane children, so it survives the
# session close outright. Proof this is real: a live specialist was found
# orphaned for 7 days. There is no pidfile for these (ProcessGroupReaper in
# board-supervisor.sh's own Python process tracks them only in memory, and
# is lost the instant that process dies) so the only sound way to find them
# is a structural walk of real kernel PID/PPID links rooted at this
# session's OWN live pane PIDs (queried from tmux itself, right now) --
# never a name/argv scan across the whole host (Plan B Task 8 is why that
# would be unsound and dangerous). This only reaches descendants of THIS
# session's panes, so it cannot touch another session's processes, and it
# cannot touch anything dispatched through the daemon (a separate
# launchd-managed process, not a descendant of any pane, and not started or
# stopped by this script). Captured BEFORE the kill below: once the pane
# process is gone, the orphan's PPID is reparented away and the link used to
# find it is lost. Plan B Task 7.
pane_pids="$(tmux list-panes -s -t "${SESSION}" -F '#{pane_pid}' 2>/dev/null || true)"
descendant_pids=""
if [[ -n "${pane_pids}" ]]; then
    # shellcheck disable=SC2086
    descendant_pids="$(python3 - ${pane_pids} <<'PY'
import subprocess
import sys


def descendants_of(roots, pid_ppid_pairs):
    """Every PID transitively parented by one of `roots`, per the given
    (pid, ppid) pairs. Pure and dependency-free so it can be driven directly
    by scripts/python/tests/*.py with synthetic rows -- no real `ps`, no
    real processes required to test the walk itself.
    """
    children = {}
    for pid, ppid in pid_ppid_pairs:
        children.setdefault(ppid, []).append(pid)
    seen = set()
    stack = list(roots)
    while stack:
        parent = stack.pop()
        for child in children.get(parent, []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _live_pid_ppid_pairs():
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True).splitlines()
    pairs = []
    for row in rows:
        parts = row.split()
        if len(parts) != 2:
            continue
        try:
            pairs.append((int(parts[0]), int(parts[1])))
        except ValueError:
            continue
    return pairs


roots = [int(arg) for arg in sys.argv[1:]]
for pid in sorted(descendants_of(roots, _live_pid_ppid_pairs())):
    print(pid)
PY
)" || true
fi

# Fingerprint every descendant NOW, in the same pre-kill snapshot window as
# the PID list itself, so Phase 5 below can tell a genuine survivor from a
# PID that got recycled by something else entirely during/after the kill.
#
# macOS runs this file with /bin/bash 3.2, which has no associative arrays.
# PIDs are non-negative integers, so a sparse indexed array is the exact map
# needed here and keeps the existing pid-keyed reads unchanged.
declare -a descendant_start_time=()
if [[ -n "${descendant_pids}" ]]; then
    for pid in ${descendant_pids}; do
        descendant_start_time["${pid}"]="$(pid_start_time "${pid}")"
    done
fi

# Phase 4 — kill the tmux session
echo ""
echo "Killing tmux session '${SESSION}'..."
tmux kill-session -t "${SESSION}" 2>/dev/null
kill_rc=$?

# Was `tmux kill-session -t squad 2>/dev/null` with its exit status
# discarded, followed by an unconditional "Squad closed." -- if the session
# survived (a stuck pane process refusing SIGHUP, a wrong session name) the
# operator was told it closed regardless. Verify the session is actually
# gone before claiming so. Plan B Task 7 (deferred from Task 6).
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    session_closed=0
else
    session_closed=1
fi

# Phase 5 — reap any survivors from the Phase 3c snapshot.
# Anything still alive here escaped the session kill by having its own
# process group/session (the board-specialist case Phase 3c documents).
# Ordinary pane children are already gone by this point, so this loop
# naturally only ever acts on real orphans -- nothing to special-case.
# kill by process group (not bare PID) so a specialist's own subprocess
# tree goes with it, mirroring launch_hygiene.ProcessGroupReaper's
# pgid-based teardown elsewhere in this repo. TERM first, KILL only if a
# process ignores it.
#
# A kill-by-process-group primitive must never be able to reach pgid 0
# (unqualified = the caller's own group), pgid 1 (init/launchd --
# catastrophic system-wide blast radius), or this very script's own
# process group (self-inflicted). None of these are reachable given this
# function's only real caller below (fed exclusively by descendants_of(),
# rooted at this session's own tmux pane PIDs, which can never resolve to
# pgid 0/1/self) but a function whose whole job is "kill this group" should
# refuse them unconditionally rather than lean on caller discipline. Plan B
# Task 7 fix round 1.
# $3 (optional) is a previously-recorded pid_start_time() value. When
# given, it is re-checked via pid_identity_still_matches() immediately
# before THIS call's own kill, not just once by an earlier caller -- Phase
# 5 below invokes this function twice per survivor (TERM, then KILL after a
# 1s grace period), and re-verifying at both call sites, not only the
# initial survivor-selection pass, closes the window between them too. When
# omitted, falls back to a plain liveness check (used by direct callers/
# tests that have no recorded identity to compare against).
SQUAD_STOP_OWN_PGID="$(ps -o pgid= -p $$ 2>/dev/null | tr -d '[:space:]')"
reap_survivor_group() {
    local pid="$1" signal="$2" recorded_start="${3:-}" pgid
    if [[ -n "${recorded_start}" ]]; then
        pid_identity_still_matches "${pid}" "${recorded_start}" || return 0
    else
        kill -0 "${pid}" 2>/dev/null || return 0
    fi
    pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
    if [[ "${pgid}" =~ ^[0-9]+$ ]]; then
        if [[ "${pgid}" -le 1 ]] || [[ -n "${SQUAD_STOP_OWN_PGID:-}" && "${pgid}" == "${SQUAD_STOP_OWN_PGID:-}" ]]; then
            echo "  Refusing to kill process group ${pgid} (pid ${pid}): unsafe target (0/1/self)" >&2
            return 1
        fi
        # The stated persistent-CDP-Chrome policy, enforced at the point of
        # the signal itself and not only at survivor selection: this function
        # is the one thing here that actually kills, and it is called twice
        # per survivor (TERM, then KILL).
        if pgid_is_protected_chrome "${pgid}"; then
            if [[ "${PROTECTED_CHROME_SCAN_OK:-0}" == "1" ]]; then
                echo "  Refusing to kill process group ${pgid} (pid ${pid}): it is the operator's persistent CDP Chrome at port 9222, which this script never kills." >&2
            else
                echo "  Refusing to kill process group ${pgid} (pid ${pid}): the persistent-CDP-Chrome scan failed, so no group can be shown NOT to be the operator's authenticated browser." >&2
            fi
            return 1
        fi
        kill "-${signal}" "-${pgid}" 2>/dev/null || true
    else
        kill "-${signal}" "${pid}" 2>/dev/null || true
    fi
}
if [[ -n "${descendant_pids}" ]]; then
    survivors=""
    for pid in ${descendant_pids}; do
        # Re-verify identity immediately before treating this PID as a
        # survivor: the Phase 3c snapshot and this check are separated by
        # tmux's own session-teardown time, and a PID that got recycled by
        # something unrelated in that window must never be killed just
        # because it happens to still be alive.
        if pid_identity_still_matches "${pid}" "${descendant_start_time[${pid}]:-}"; then
            # Excluded here as well as at the signal, so the "Reaping orphaned
            # process group(s)" line below never names a group this script has
            # promised not to touch.
            survivor_pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
            if pgid_is_protected_chrome "${survivor_pgid}"; then
                if [[ "${PROTECTED_CHROME_SCAN_OK}" == "1" ]]; then
                    echo "  Skipping pid ${pid}: it is in the operator's persistent CDP Chrome's process group (${survivor_pgid}), which this script never kills." >&2
                else
                    echo "  NOT reaping pid ${pid} (process group ${survivor_pgid:-unknown}): the persistent-CDP-Chrome scan failed, so this script cannot tell whether killing this group would take the operator's authenticated browser with it. Reap it by hand after checking: ps -o pgid=,command= -p ${pid}" >&2
                fi
                continue
            fi
            survivors="${survivors} ${pid}"
        elif kill -0 "${pid}" 2>/dev/null; then
            echo "  Skipping pid ${pid}: alive but its start time no longer matches the pre-kill snapshot (recycled PID, not our survivor)." >&2
        fi
    done
    if [[ -n "${survivors}" ]]; then
        echo ""
        echo "Reaping orphaned process group(s) that outlived the session:${survivors}"
        for pid in ${survivors}; do
            reap_survivor_group "${pid}" TERM "${descendant_start_time[${pid}]:-}"
        done
        sleep 1
        for pid in ${survivors}; do
            reap_survivor_group "${pid}" KILL "${descendant_start_time[${pid}]:-}"
        done
    fi
fi

# The coordinator pidfile named the pane this stop just tore down (or was stale/
# absent). Remove it so a later stop cannot rediscover a coordinator that no
# longer exists -- EXCEPT when discovery found a live BACKGROUND JOB: this stop
# does not (and must not) kill that, so its pidfile still names a live
# coordinator and must stay. Matches reap_pidfile_process()'s own `rm -f` on the
# runtime pidfiles it owns; this is gitignored _state/runtime, not tracked state.
if [[ "${orch_shape}" != "background-job" ]]; then
    rm -f "${CHRONO_COORDINATOR_PIDFILE}" 2>/dev/null || true
fi

echo ""
if [[ "${session_closed}" -eq 1 ]]; then
    echo "✓ Squad closed. Resume next time with: squad"
    echo "✓ Resume state: _state/active-tasks.json + chrono/current.md + departments/*/current.md"
else
    echo "✗ tmux session '${SESSION}' is still running after kill-session (exit ${kill_rc})." >&2
    echo "✗ Squad NOT closed. Investigate before assuming a clean restart." >&2
    exit 1
fi
