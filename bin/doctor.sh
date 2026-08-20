#!/bin/bash
# Claude-Vibe-Squad doctor — health check + token-bleed detection.
# Verifies environment, reports anomalies. Surfaced in morning brief.
#
# Phases:
#   0. Launch dependency parity — every command bin/launch-squad.sh hard-gates
#      on, from the list both programs share (shared/launch-dependencies.sh)
#   1. CLI presence on this HOME's PATH (Claude / Codex / Gemini / Kimi)
#      (presence ONLY; login/auth state is deliberately NOT verified — the
#      program logs in to nothing and says so, see the auth note in Phase 1)
#   2. MCP servers reachable from each CLI
#   3. Secrets sourced
#   4. Private memory vault root + runtime repository accessible (resolves the
#      vault-root sentinel/path; it does NOT probe a live Obsidian REST API)
#   5. Persistent browser session alive
#   6. Disk space (>15% free)
#   7. tmux session present, and its window COMPOSITION — the chrono window and
#      the watchers window, by the names shared/lead-windows.sh gives the
#      launcher (the four persistent model-lane panes were retired at the
#      Phase-3 cutover, so a session count alone says nothing about liveness)
#   7b. Status poller singleton — exactly one vs-lane-status.sh poller for this
#      root, identified by shared/process-identity.sh's exact-positional argv
#      predicate (never pgrep/substring), and tracked by its pidfile
#   8. Token-bleed proxy: LLM-artifact volume vs its 7-day average, plus the
#      24h dispatch-log count (there is NO per-CLI token counter — the per-pane
#      report was retired with the persistent-lane architecture)
#   9. Specialist dispatch volume last 24h
#   9b. Notification-spine liveness: a delivered-nudge receipt newer than the
#      newest chrono-queue entry (a severed spine parks work in silence)
#   10. Process audit (long-running, orphaned)
#   11. Log/transcript volume audit
#
# Every status below has five possible values, not two -- see "Result
# vocabulary". A check that could not run reports COULD NOT DETERMINE and is
# never counted healthy; a check whose input this distribution does not carry
# reports NOT APPLICABLE. Adding a check means choosing all of its states.
#
# Modes:
#   (default)  FAST. What bin/launch-squad.sh gates on, under
#              SQUAD_DOCTOR_TIMEOUT (default 45s). Every check that fits that
#              budget runs; the ones that do not are NAMED as not-measured.
#   --deep     Everything the fast path runs, PLUS the checks whose measured
#              cost exceeds the launch budget. bin/run-nightly.sh uses this.
#
# A pre-flight check nobody can afford to run is worse than none, because
# everyone learns to launch with SQUAD_SKIP_DOCTOR=1 and the guard stops
# guarding. Profiled 2026-08-17 on the maintainer's tree: the whole program
# took 141.3s against that 45s gate, and ONE check -- the public-export
# hygiene gate -- was 127.3s of it (90.1%), of which 120.1s was its gitleaks
# scan of a 4.7GB working tree. Parallelising the other 14.0s could not have
# fixed that, so the slow check moved to --deep rather than being trimmed or
# cached. See DEEP_DEFERRED below for how its absence stays loud.

set -uo pipefail

# launchd's spawn shell doesn't include ~/.local/bin (where claude + kimi live).
# Prepend it so CLI presence checks work the same as in operator's interactive shell.
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# Same interpreter bin/mcp-audit.sh uses: mcp_server.py needs the `mcp`
# package, which lives in the repo venv, not system python3.
CHRONO_PY="${CHRONO_PY:-${VAULT_ROOT}/.venv/bin/python}"

check_private_vault_root() {
    PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" python3 -B - <<'PY'
import sys
from vaultroot import VaultRootError, resolve_vault_root
try:
    resolve_vault_root()
except VaultRootError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PY
}
# --- Mode selection ---------------------------------------------------------
# Parsed as a loop rather than as a single positional test so that adding a
# second flag did not make the first one order-dependent, and so an unknown
# argument is REFUSED. Silently ignoring one would let `doctor.sh --dep` run
# the fast path while its caller believed it had asked for the deep one, which
# is the same "looked healthier than it was" failure this program exists to
# prevent. Exit 64 (EX_USAGE) stays outside doctor's 0/1/2 result contract on
# purpose: it is a caller error, not a finding about the installation, and
# bin/launch-squad.sh already blocks on any code outside that contract.
DOCTOR_DEEP=0
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --check-private-vault-root)
            check_private_vault_root
            exit $?
            ;;
        --deep)
            DOCTOR_DEEP=1
            shift
            ;;
        --help|-h)
            printf 'usage: doctor.sh [--deep] [--check-private-vault-root]\n\n'
            printf '  (no flag)  fast pre-flight; what bin/launch-squad.sh gates on\n'
            printf '  --deep     also run checks costlier than the launch budget\n'
            exit 0
            ;;
        *)
            printf 'doctor.sh: unknown argument: %s\n' "$1" >&2
            printf 'usage: doctor.sh [--deep] [--check-private-vault-root]\n' >&2
            exit 64
            ;;
    esac
done

# root_valid alone is not "recall works": health() (mcp_server.py) also clears
# every query-time prerequisite `recall` itself enforces -- a stale FTS5
# schema or missing BM25 weights can leave root_valid:true while every real
# recall fails (see mcp_server._index_health's docstring). health already
# computes and returns this as recall_ready; this just consumes it. Needs the
# chrono-vault venv (the `mcp` package), not bare python3 -- see CHRONO_PY.
check_vault_recall_ready() {
    "${CHRONO_PY}" -B -c '
import json
import sys
sys.path.insert(0, sys.argv[1])
try:
    from mcp_server import health
    result = health()
except Exception as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
    sys.exit(2)
print(json.dumps(result))
sys.exit(0 if result.get("recall_ready") is True else 1)
' "${VAULT_ROOT}/plugins/chrono-vault"
}

# Spec §11 item 4. "Reachable" (above) is not "still being fed": promotion
# fires as an event handler (Task 8 stamps `verified_at_ns`), and a sweep
# that silently stops is invisible -- curation and usage telemetry both
# stopped 2026-07-25 and nobody noticed for 23 days, by which point 94.6%
# of notes were stuck at `candidate`. This asks whether ANY note reached
# `verified` in the trailing window.
#
# Consumes `memory_metrics.promotion_throughput` rather than reimplementing
# its query: that function counts on `verified_at_ns`, never `mtime_ns` --
# an earlier version counted mtime and reported 99 promotions on a vault
# where promotion had never run, because `index.py` resets mtime on every
# reindex. See its docstring.
#
# Both `vaultroot` and `memory_metrics` are stdlib-only (sqlite3, json, os,
# pathlib), so -- like check_private_vault_root above -- this runs on bare
# python3, not the chrono-vault venv; no `mcp` package needed.
check_promotion_throughput() {
    PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault:${VAULT_ROOT}/scripts/python" python3 -B -c '
import json
import os
from vaultroot import VaultRootError, resolve_vault_root
from memory_metrics import promotion_events, promotion_throughput

DAYS = 30  # keep in step with the DAYS literal in the doctor.sh call site below
try:
    root = resolve_vault_root()
    # The alarm keys on handler EVENTS, never on stamped notes. A note can
    # carry `verified_at` because it was recorded straight to `verified` or
    # because Chrono set the status by hand during curation, so a single
    # hand-verified note used to silence "the handler stopped firing" for a
    # full window. `stamped` is still reported, as context, clearly labelled
    # as the upper bound it is.
    count = promotion_events(os.environ["VAULT_ROOT"], days=DAYS)
    stamped = promotion_throughput(root, days=DAYS)
except VaultRootError as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
    raise SystemExit(2)
except Exception as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
    raise SystemExit(2)
print(json.dumps({"count": count, "stamped_notes": stamped, "days": DAYS}))
raise SystemExit(0 if count > 0 else 1)
'
}

# --- Notification-spine reconciliation --------------------------------------
# Answers one question: of the chrono-queue entries that OWED a delivered nudge
# in the recent window, how many have no receipt?
#
# "Owed" is not "exists". A queue entry with no receipt is CORRECT for most
# entries, because registry_reconciler.emit_event() appends the queue
# unconditionally and only then decides whether to nudge:
#
#     append_chrono_queue(status, task_ref, summary)          # always
#     if not registered_in_canonical_registry(task_id):
#         return False                                        # no nudge, no receipt
#     return nudge_chrono(nudge, notification_event_key(task_ref, status))
#
# So an entry owes a receipt only when BOTH of emit_event's own gates pass. The
# membership gate is IMPORTED, never restated (CLAUDE.md rule 10). Note what it
# actually does on a canonical host: `operating` IS one of the canonical
# registries there, so it short-circuits to True and the gate is a no-op. It
# earns its place on relocated and hermetic trees, where it correctly says the
# host was owed nothing. Measured 2026-08-17 on the operator's tree: it returns
# True even for an invented task id.
#
# The second exclusion is `long-running:` entries. note_long_running() calls
# append_chrono_queue() DIRECTLY and debounces through
# _state/long-running-noted/<task-id>.noted; it never calls nudge_chrono, so it
# never owes a notify receipt. Those entries are a different delivery channel
# that happens to share the queue file. On this tree that is 64 of 242 entries,
# every one of them receiptless and correct.
#
# Matching is on the TASK REF recorded inside each receipt, not on a receipt
# path recomputed from the queue line, because the two producers disagree about
# the STATE half of the key: bin/outbox-watcher.sh writes `needs_review` to the
# queue and then nudges with `review-required` (outbox-watcher.sh, event_state),
# while registry_reconciler uses one string for both. A path recomputed from the
# queue's status would therefore miss every outbox-watcher fallback entry
# permanently. Both writers record the full event key in the receipt body, and
# the key is length-prefixed (`<len>:<task_ref>|<len>:<state>`), so the task ref
# parses out exactly and unambiguously.
#
# "Delivered at least once" is the system's own success criterion, not a
# weakening: nudge_chrono treats an existing receipt for an event key as success
# and deliberately writes nothing new, so a re-recorded event is not a second
# delivery and must not be counted as a missed one.
#
# Why this cannot fire on correct behaviour: the two exclusions are precisely
# the conditions under which the system deliberately does not deliver, and every
# delivery that does happen leaves a receipt naming its task ref. Measured
# across the whole 242-entry queue history on 2026-08-17: 0 missing.
#
# Windowed to the last 24h so this is a LIVENESS check: a historical gap ages
# out, while a spine that is severed now keeps failing as new work lands. Same
# window as the dispatch-volume checks below.
#
# Prints one machine-readable header line, `owed=<N> missing=<M>`, followed by
# up to three example entries. Deliberately not JSON: every other structured
# reader in this file needs jq, and a check that can answer without adding a
# dependency should not acquire one.
check_notification_spine() {
    "${1}" -B - "${VAULT_ROOT}" "${2}" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts" / "python"))
import registry_reconciler as rr  # noqa: E402


def task_ref_of(event_key):
    """The task ref out of a `<len>:<ref>|<len>:<state>` key, or None.

    The length prefix is what makes this exact: a task ref containing the
    separator could not be recovered by splitting, and re-deriving the ref by
    any other route would reintroduce a guess.
    """
    head, sep, rest = event_key.partition(":")
    if not sep or not head.isdigit():
        return None
    size = int(head)
    if len(rest) < size + 1 or rest[size] != "|":
        return None
    return rest[:size]


# Every task ref the spine has ever delivered a nudge for. Both writers record
# the full event key in the receipt body -- the reconciler as JSON, the shell
# watcher as `event_key=...` -- so this reads their answer rather than
# recomputing one.
delivered = set()
for receipt in rr.CHRONO_NOTIFY_RECEIPTS_DIR.glob("*.sent"):
    try:
        body = receipt.read_text(encoding="utf-8")
    except OSError:
        continue
    key = None
    try:
        loaded = json.loads(body)
    except ValueError:
        for line in body.splitlines():
            if line.startswith("event_key="):
                key = line[len("event_key=") :]
                break
    else:
        if isinstance(loaded, dict):
            key = loaded.get("event_key")
    if not isinstance(key, str):
        continue
    ref = task_ref_of(key)
    if ref:
        delivered.add(ref)

cutoff = datetime.now(timezone.utc) - timedelta(hours=int(sys.argv[2]))
# One membership answer per task id: the predicate re-reads the canonical
# registries on every call, and _state/active-tasks.json is multi-megabyte.
registered = lru_cache(maxsize=None)(rr.registered_in_canonical_registry)

owed = 0
missing = []
for line in rr.CHRONO_QUEUE_PATH.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 3:
        continue
    stamp, status, task_ref = parts[0], parts[1], parts[2]
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        continue
    if when < cutoff:
        continue
    if status.startswith("long-running:"):
        continue
    if not registered(task_ref.rsplit("/", 1)[-1]):
        continue
    owed += 1
    if task_ref not in delivered:
        missing.append(f"{stamp} {status} {task_ref}")

print(f"owed={owed} missing={len(missing)}")
for entry in missing[:3]:
    print(entry)
PY
}

# Root-independent durable state. Resolve this from the script's physical home,
# not VAULT_ROOT: the latter may be the broken path this run needs to report.
# shellcheck source-path=SCRIPTDIR source=doctor-log-home.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")" && pwd -P)/doctor-log-home.sh" || exit $?

# Named in the report and in the JSON summary. A reader who cannot tell which
# mode produced a "healthy" verdict cannot tell what that verdict covered.
if [[ "${DOCTOR_DEEP}" -eq 1 ]]; then
    DOCTOR_MODE="deep"
else
    DOCTOR_MODE="fast"
fi

DATE="$(date -u +%Y-%m-%d)"
DOCTOR_LOG="${CHRONO_DOCTOR_LOG_DIR}/${DATE}.md"
SUMMARY="${CHRONO_DOCTOR_LOG_DIR}/${DATE}-summary.json"

mkdir -p "$(dirname "${DOCTOR_LOG}")"

# Initialize report
cat > "${DOCTOR_LOG}" <<EOF
# Doctor Report — ${DATE}

Run at: $(date -u +%FT%TZ)
Mode: ${DOCTOR_MODE}

EOF

# --- Result vocabulary ------------------------------------------------------
# Every status this program prints has more than two possible values. The
# missing ones cost a release rehearsal: the process audit received three
# `/bin/ps: Operation not permitted` errors and printed "No long-running CLI
# processes detected", because a DENIED check and a CLEAN check produce the
# same empty output. Worse, the denied run looked *healthier* than the working
# one -- it lost a warning the working run had raised.
#
#   HEALTHY   the check ran and the thing is good                          OK
#   WARNINGS  the check ran; needs attention, or is simply not configured  WARN
#   ISSUES    the check ran and the thing is broken            ISSUE (gates exit 1)
#   UNKNOWNS  the check COULD NOT RUN. Never healthy, never a pass.        UNKNOWN
#   SKIPPED   the check does not apply to THIS distribution                N/A
#
# UNKNOWN and SKIPPED are different claims and must not be merged. "I could not
# measure this" is a defect in the health report; "this tree never carried the
# input" is a fact about the projection. The split mirrors bin/test's
# PASS/FAIL/BLOCKED/SKIP, which already draws the same line for test suites.
#
# ISSUES gate with exit 1. Most optional UNKNOWNs remain report-only: a first
# run has no secrets file or private vault, and treating setup as failure teaches
# users to ignore the exit code. A small set of mandatory integrity checks use
# GATE_UNKNOWN_LIST instead when an input EXISTS but cannot be read or
# enumerated, so doctor exits 2. A present, readable, empty target is the
# positive clean control and exits 0. An input that its producer has never
# created is the zero-state case below: still unknown and visible, but not a
# launch blocker. That keeps "broken", "clean", "absent", and "unreadable"
# distinct.
#
# ABSENT_INPUTS is the REPORTING split for producer-created inputs that do not
# exist yet (for example a browser keep-alive summary or the first dispatch
# ledger). It routes through note_unknown, stays loud and can never be counted
# healthy, but does not make first launch depend on state only later activity
# can create. Once an input exists, missing jq, malformed data, or a failed find
# uses note_gate_unknown and the exit-2 path.
#
# DEEP_DEFERRED is the second REPORTING split, built the same way and for the
# same reason: a check the FAST path did not run because its measured cost does
# not fit the launch gate's budget. It is not absent (the input is right here),
# it is not skipped (this distribution does carry it), and it is emphatically
# not healthy -- nobody looked. It routes through note_unknown, so it can never
# be counted a pass, and stays non-gating so a healthy install still launches.
# It is named in the console report, in the log, and in the JSON summary, and
# `--deep` runs it. A check that vanished quietly from the fast path would be
# the defect; a check that says "I was not measured, here is the flag that
# measures me" is the whole point of the split.
ISSUES=()
WARNINGS=()
HEALTHY=()
UNKNOWNS=()
SKIPPED=()
ABSENT_INPUTS=()
DEEP_DEFERRED=()
# A count alone could not tell a reader WHICH unknowns were the gating ones, so
# the blocked user had no way to act on the exit code. Keep the list.
GATE_UNKNOWN_LIST=()

# Each helper takes the short summary phrase and, optionally, a longer report
# line. Routing every status through these is what makes the five states
# countable; an inline `echo` into the log is invisible to the summary.
note_ok()      { HEALTHY+=("$1");  printf -- '- \xe2\x9c\x93 %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_warn()    { WARNINGS+=("$1"); printf -- '- \xe2\x9a\xa0\xef\xb8\x8f %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_issue()   { ISSUES+=("$1");   printf -- '- \xf0\x9f\x94\x94 %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_unknown() { UNKNOWNS+=("$1"); printf -- '- ? COULD NOT DETERMINE: %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_gate_unknown() {
    note_unknown "$@"
    GATE_UNKNOWN_LIST+=("$1")
}
# The input this check needs has not been produced yet. Loud, never a pass,
# never healthy -- and never a launch blocker. See the vocabulary note above for
# why this is not a weakened check: the moment the input exists, any failure to
# read it goes back through note_gate_unknown and exits 2.
note_absent_input() {
    note_unknown "$@"
    ABSENT_INPUTS+=("$1")
}
# This check costs more than the launch gate's budget, so the fast path did not
# run it. Loud, never a pass, never a launch blocker -- and it names --deep.
note_deferred_deep() {
    note_unknown "$@"
    DEEP_DEFERRED+=("$1")
}
note_skip()    { SKIPPED+=("$1");  printf -- '- \xe2\x97\x8b not applicable here: %s\n' "${2:-$1}" >> "${DOCTOR_LOG}"; }
note_info()    { printf -- '- \xe2\x84\xb9\xef\xb8\x8f %s\n' "$1" >> "${DOCTOR_LOG}"; }

# --- Tool liveness probes ---------------------------------------------------
# Presence on PATH is not usability. Each probe asks the tool a question whose
# right answer this script already knows, so an installed-but-denied tool
# cannot pass for a working one. A tool that silently failed and a tool that
# found nothing print the same empty output; only a positive control separates
# them.

# ps must be able to name this very process.
PS_USABLE=false
PS_DENIED_REASON=""
if command -v ps >/dev/null 2>&1; then
    if _ps_self="$(ps -o pid= -p "$$" 2>&1)" \
        && [[ "${_ps_self//[[:space:]]/}" == "$$" ]]; then
        PS_USABLE=true
    else
        PS_DENIED_REASON="$(printf '%s' "${_ps_self}" | head -1 | tr -d '\n')"
        [[ -n "${PS_DENIED_REASON}" ]] \
            || PS_DENIED_REASON="ps did not report this process"
    fi
else
    PS_DENIED_REASON="ps is not on PATH"
fi
unset _ps_self

# grep must find a string this script just produced.
GREP_USABLE=false
if command -v grep >/dev/null 2>&1 \
    && printf 'doctor-grep-canary\n' | grep -q 'doctor-grep-canary' 2>/dev/null; then
    GREP_USABLE=true
fi

# git must be able to answer questions about THIS tree, not merely exist.
GIT_USABLE=false
if command -v git >/dev/null 2>&1 \
    && git -C "${VAULT_ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
    GIT_USABLE=true
fi

# Classify a file this program's own checks depend on. The public projection
# deliberately withholds several private inputs (tools/export/policy/
# path-policy.json), so a check needing one of them is NOT APPLICABLE in a
# projected tree. It is not failed, and its subject is certainly not healthy.
#
#   present      the file is here
#   missing      git tracks it in THIS tree, so it should be here and is not
#   unpublished  git does not track it here: this distribution never carried it
#   unknown      git could not answer, so neither of the above is established
#
# Keying on git rather than on a hardcoded list of "public" paths keeps the two
# facts in one home: the policy decides what ships, and this reads back what
# actually shipped. A path can move between distributions without editing here.
classify_dependency() {
    local rel="$1"
    if [[ -e "${VAULT_ROOT}/${rel}" ]]; then
        printf 'present\n'
    elif [[ "${GIT_USABLE}" != true ]]; then
        printf 'unknown\n'
    elif git -C "${VAULT_ROOT}" ls-files --error-unmatch -- "${rel}" \
        >/dev/null 2>&1; then
        printf 'missing\n'
    else
        printf 'unpublished\n'
    fi
}

# macOS ships no coreutils `timeout`, and a lane CLI that hangs on --version
# must not hang the health report. Only the PID this function started is ever
# signalled: the process table is shared with every other lane on this host,
# so a pattern-matched kill would reap siblings.
run_bounded() {
    local seconds="$1" outfile="$2"
    shift 2
    local pid watchdog rc=0
    "$@" >"${outfile}" 2>/dev/null &
    pid=$!
    ( sleep "${seconds}"; kill -TERM "${pid}" 2>/dev/null ) >/dev/null 2>&1 &
    watchdog=$!
    wait "${pid}" 2>/dev/null || rc=$?
    kill -TERM "${watchdog}" 2>/dev/null
    wait "${watchdog}" 2>/dev/null || true
    return "${rc}"
}

# --- 1. CLI presence + login ---
# Resolved on THIS HOME's PATH, which is the only question a health report can
# honestly answer for the person reading it.
#
# The dispatch rail resolves lane executables from the effective-UID passwd
# home (scripts/python/seatbelt_profile.py: HOST_HOME -> LANE_CLI_PATHS). That
# is correct where it lives -- a seatbelt profile has to name a fixed inode,
# and board spawns legitimately run with a $HOME that differs from the account
# home -- and wrong as an answer to "what did YOU install". Under a fresh HOME
# it reported the MAINTAINER's four CLIs as this installation's, while
# bin/mcp-audit.sh, which honours the temporary PATH, reported two of them
# absent: two checks in one program disagreeing about the same machine, with
# the wrong one printing the reassuring answer.
#
# Doctor now answers the HOME question itself, and reports the rail's answer
# below as provenance plus an explicit DISAGREEMENT line, instead of silently
# preferring one of the two.
# --- 0. Launch dependency parity -------------------------------------------
# README's Quickstart runs `squad doctor` immediately before `squad up`, so this
# program IS the documented pre-flight for the launcher's hard gate. Until
# 2026-08-17 it did not contain the strings `fswatch`, `uv` or `curl` even once
# in 1,390 lines, while bin/launch-squad.sh exits 1 without them: a cloner
# missing fswatch read a green health report and then could not launch. The
# list is SHARED with the launcher, never copied -- see
# shared/launch-dependencies.sh for why that matters and what `uv` is doing on
# it.
#
# ISSUE, not WARN, precisely because the launcher's answer is exit 1. A
# pre-flight whose exit code disagrees with the launch it precedes is the
# defect, not a stylistic choice; the per-lane WARN lines below answer a
# different question (which CLI did THIS HOME install, at what version) and keep
# their own severity.
#
# Costs one `command -v` per entry -- no subprocess, no watchdog needed.
echo "## Launch Dependencies" >> "${DOCTOR_LOG}"
LAUNCH_DEPS_FILE="${VAULT_ROOT}/shared/launch-dependencies.sh"
if [[ ! -r "${LAUNCH_DEPS_FILE}" ]]; then
    # Gate-blocking: the launcher's required-command list is a mandatory
    # integrity input of this tree, and without it doctor cannot say whether a
    # launch would start. "I could not check" must not read as "nothing
    # missing".
    note_gate_unknown "launch dependency parity could not be checked: shared/launch-dependencies.sh is unreadable" \
        "${LAUNCH_DEPS_FILE} is absent or unreadable — the commands \`squad up\` requires were NOT checked, so a launch may still refuse to start"
else
    # shellcheck source-path=SCRIPTDIR source=../shared/launch-dependencies.sh disable=SC1091
    source "${LAUNCH_DEPS_FILE}"
    if [[ -z "${SQUAD_REQUIRED_COMMANDS[*]+set}" ]]; then
        note_gate_unknown "launch dependency parity could not be checked: the shared list defined no commands" \
            "${LAUNCH_DEPS_FILE} loaded but defined no SQUAD_REQUIRED_COMMANDS — the launch dependency gate was NOT evaluated"
    else
        MISSING_LAUNCH_DEPS=()
        for _dep in "${SQUAD_REQUIRED_COMMANDS[@]}"; do
            command -v "${_dep}" >/dev/null 2>&1 || MISSING_LAUNCH_DEPS+=("${_dep}")
        done
        unset _dep
        if [[ "${#MISSING_LAUNCH_DEPS[@]}" -eq 0 ]]; then
            note_ok "all ${#SQUAD_REQUIRED_COMMANDS[@]} launch dependencies present" \
                "Every command \`squad up\` requires is on this HOME's PATH: ${SQUAD_REQUIRED_COMMANDS[*]}"
        else
            note_issue "missing launch dependencies: ${MISSING_LAUNCH_DEPS[*]} — \`squad up\` will exit 1" \
                "Missing ${#MISSING_LAUNCH_DEPS[@]} of ${#SQUAD_REQUIRED_COMMANDS[@]} required command(s): ${MISSING_LAUNCH_DEPS[*]}. bin/launch-squad.sh gates on this exact list and will refuse to start. Fix: ${SQUAD_REQUIRED_COMMANDS_HINT:-install the missing commands}"
        fi
    fi
fi

echo "" >> "${DOCTOR_LOG}"
echo "## CLI Status" >> "${DOCTOR_LOG}"
echo "" >> "${DOCTOR_LOG}"
echo "Resolved on this HOME's PATH (HOME=${HOME:-<unset>})." >> "${DOCTOR_LOG}"

# --- Auth probes -------------------------------------------------------------
# For a system whose entire premise is four authenticated native CLIs, doctor
# verified auth for none of them: the single `could-not-run: 1` line below this
# loop was a hardcoded note_unknown, not a check. "Not installed" and "installed
# and logged out" produced the same green CLI section.
#
# Two lanes answer a zero-token status subcommand, verified 2026-08-17 on the
# maintainer's tree at 0.21s and 0.06s:
#
#     claude auth status   -> {"loggedIn": true, "authMethod": ..., "apiKeySource": ...}
#     codex login status   -> Logged in using ChatGPT
#
# `gemini` and `kimi` expose no such subcommand, so they get a credential-at-rest
# check instead -- deliberately reported as a WEAKER claim (see below).
#
# WHY THE PROBE SHAPE IS A TABLE HERE AND THE POLICY IS NOT. The lane inventory
# already carries auth-policy per lane (claude/codex subscription, gemini
# gemini-api-key, kimi managed-login) and doctor must not restate it -- it reads
# it back below and reports any DISAGREEMENT between the declared policy and what
# this probe observed, which is CLAUDE.md rule 9 applied to authentication. What
# the inventory cannot supply is the probe COMMAND: `claude auth status` versus
# `codex login status` is a fact about each vendor's CLI surface, recorded
# nowhere in this repository. That, and only that, is what these four cases name.
#
# Bounded at 5s each, not the 10s the version probe uses: four lanes share one
# 45s launch gate, and an auth endpoint is likelier to hang than `--version`.
# Timeout is UNKNOWN, never "not logged in" -- doctor did not establish either.
LANE_AUTH_OBSERVED=()

# gemini: OAuth credentials at ~/.gemini/oauth_creds.json are what actually
# authenticate this lane. GEMINI_API_KEY is the documented fallback and is
# checked for PRESENCE only, never read.
# kimi: ~/.kimi/credentials/kimi-code.json, written by `kimi login`.
#
# The check is for a REFRESH token, not for freshness, because freshness is the
# wrong question and measuring it would produce a permanent false positive: both
# files carry a short-lived access token beside the refresh token, and on the
# maintainer's tree BOTH access tokens were already expired on a host whose lanes
# work -- gemini's by 36 days, kimi's by 28 hours. Expiry of the access token is
# the design, so only the durable half is evidence of anything.
#
# Key presence only. No value from either file is read, printed, or logged.
lane_credential_file() {
    case "$1" in
        gemini) printf '%s\n' "${HOME}/.gemini/oauth_creds.json" ;;
        kimi)   printf '%s\n' "${HOME}/.kimi/credentials/kimi-code.json" ;;
        *)      return 1 ;;
    esac
}

CLI_PROBE_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-cli.XXXXXXXX" 2>/dev/null)" \
    || CLI_PROBE_OUT=""
AUTH_PROBE_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-auth.XXXXXXXX" 2>/dev/null)" \
    || AUTH_PROBE_OUT=""
for lane in claude codex gemini kimi; do
    lane_path="$(command -v "${lane}" 2>/dev/null || true)"
    if [[ -z "${lane_path}" ]]; then
        # Not installed is a setup step, not a fault: a clean install has none
        # of these yet and must still exit 0.
        note_warn "${lane} CLI not installed for this HOME" \
            "${lane}: not on this HOME's PATH — install it, or put it on PATH"
        continue
    fi
    if [[ -z "${CLI_PROBE_OUT}" ]]; then
        note_unknown "${lane} version probe had nowhere to write" \
            "${lane}: found at ${lane_path}, but no writable temp file for the probe"
        continue
    fi
    if run_bounded 10 "${CLI_PROBE_OUT}" "${lane_path}" --version; then
        lane_version="$(head -1 "${CLI_PROBE_OUT}" 2>/dev/null | tr -d '\r' | cut -c1-120)"
        if [[ -n "${lane_version}" ]]; then
            note_ok "${lane} CLI installed for this HOME" \
                "${lane}: ${lane_path} — ${lane_version}"
        else
            note_unknown "${lane} version probe returned nothing" \
                "${lane}: ${lane_path} ran but printed no version"
        fi
    else
        note_unknown "${lane} version probe failed or timed out" \
            "${lane}: ${lane_path} exists but did not answer --version within 10s"
    fi

    # --- auth, for the lane just resolved ---
    case "${lane}" in
        claude|codex)
            if [[ -z "${AUTH_PROBE_OUT}" ]]; then
                note_unknown "${lane} auth probe had nowhere to write" \
                    "${lane}: no writable temp file for the auth probe — login state is UNKNOWN"
                continue
            fi
            auth_rc=0
            if [[ "${lane}" == claude ]]; then
                # stdout only: the answer is JSON and a merged stderr banner
                # would make it unparseable, which this branch would then have
                # to report as UNKNOWN on a perfectly healthy login.
                run_bounded 5 "${AUTH_PROBE_OUT}" "${lane_path}" auth status || auth_rc=$?
            else
                # `codex login status` writes its answer to STDERR (measured
                # 2026-08-17: stdout empty, stderr "Logged in using ChatGPT",
                # exit 0), and run_bounded discards stderr for the version probe
                # by design. Merge the streams inside the child rather than
                # widening run_bounded for every caller. `exec` keeps this to ONE
                # process, so the watchdog still signals the CLI itself and a
                # timeout cannot leave an orphaned wrapper behind.
                run_bounded 5 "${AUTH_PROBE_OUT}" \
                    bash -c 'exec "$0" login status 2>&1' "${lane_path}" || auth_rc=$?
            fi
            AUTH_RAW="$(head -c 4096 "${AUTH_PROBE_OUT}" 2>/dev/null)"
            AUTH_FIRST_LINE="$(printf '%s\n' "${AUTH_RAW}" | head -1 | tr -d '\r' | cut -c1-160)"
            if [[ "${lane}" == claude ]]; then
                # jq is a launch dependency, but a check that cannot parse must
                # say so rather than fall through to a shape-blind grep.
                if [[ "${auth_rc}" -ne 0 ]]; then
                    note_unknown "claude auth probe failed or timed out (exit ${auth_rc})" \
                        "claude: \`claude auth status\` exited ${auth_rc} within 5s — login state is UNKNOWN, which is not the same as logged out. Output: ${AUTH_FIRST_LINE:-none}"
                elif ! command -v jq >/dev/null 2>&1; then
                    note_unknown "claude auth state could not be parsed: jq is unavailable" \
                        "claude: \`claude auth status\` answered but jq is absent — login state is UNKNOWN"
                elif ! CLAUDE_LOGGED_IN="$(printf '%s' "${AUTH_RAW}" \
                    | jq -er '.loggedIn | tostring' 2>/dev/null)"; then
                    note_unknown "claude auth state could not be parsed" \
                        "claude: \`claude auth status\` returned output without a boolean .loggedIn — login state is UNKNOWN. First line: ${AUTH_FIRST_LINE:-none}"
                elif [[ "${CLAUDE_LOGGED_IN}" == true ]]; then
                    # STEP 3: apiKeySource is the field that has burned this
                    # system -- an API key in the environment is what a headless
                    # run spends instead of the subscription. It is REPORTED, not
                    # warned about, because this repository deliberately produces
                    # the condition and then strips it at the boundary
                    # (bin/launch-squad.sh's MEDIA_AUTH_PREFIX, board-supervisor's
                    # env allowlist, bin/vs-welcome.sh and
                    # bin/dispatch-toolkit-verify.sh all `unset`/`env -u` it). A
                    # warning on a handled condition fires every day and teaches
                    # the reader to skip the section. Making it VISIBLE was the
                    # gap; the cross-check against the declared policy is below.
                    CLAUDE_AUTH_METHOD="$(printf '%s' "${AUTH_RAW}" \
                        | jq -r '.authMethod // "unreported"' 2>/dev/null)"
                    CLAUDE_KEY_SOURCE="$(printf '%s' "${AUTH_RAW}" \
                        | jq -r '.apiKeySource // "none"' 2>/dev/null)"
                    LANE_AUTH_OBSERVED+=("claude=${CLAUDE_AUTH_METHOD// /-}/${CLAUDE_KEY_SOURCE// /-}")
                    note_ok "claude authenticated (${CLAUDE_AUTH_METHOD}, key source: ${CLAUDE_KEY_SOURCE})" \
                        "claude: logged in. authMethod=${CLAUDE_AUTH_METHOD}; apiKeySource=${CLAUDE_KEY_SOURCE}. The key source is the credential THIS environment would hand the CLI; the dispatch rail strips API-key variables before it execs a lane."
                else
                    note_warn "claude is NOT logged in — run: claude auth login" \
                        "claude: \`claude auth status\` reports loggedIn=false. Every claude-lane dispatch will fail until you run \`claude auth login\`."
                fi
            else
                if [[ "${auth_rc}" -ne 0 ]]; then
                    note_warn "codex is NOT logged in — run: codex login" \
                        "codex: \`codex login status\` exited ${auth_rc}. Output: ${AUTH_FIRST_LINE:-none}. Every codex-lane dispatch will fail until you run \`codex login\`."
                elif [[ "${AUTH_FIRST_LINE}" == Logged\ in* ]]; then
                    CODEX_AUTH_METHOD="${AUTH_FIRST_LINE#Logged in using }"
                    LANE_AUTH_OBSERVED+=("codex=${CODEX_AUTH_METHOD// /-}")
                    note_ok "codex authenticated (${AUTH_FIRST_LINE#Logged in using })" \
                        "codex: ${AUTH_FIRST_LINE}"
                else
                    note_unknown "codex auth state could not be read" \
                        "codex: \`codex login status\` exited 0 but its answer was not recognisable as a login state — UNKNOWN, not logged out. First line: ${AUTH_FIRST_LINE:-none}"
                fi
            fi
            ;;
        gemini|kimi)
            LANE_CRED_FILE="$(lane_credential_file "${lane}")"
            LANE_CRED_HINT="run \`${lane} login\`"
            [[ "${lane}" == gemini ]] \
                && LANE_CRED_HINT="run \`gemini\` once and complete the OAuth flow, or set GEMINI_API_KEY"
            if [[ -r "${LANE_CRED_FILE}" ]] \
                && grep -q '"refresh_token"' "${LANE_CRED_FILE}" 2>/dev/null; then
                # A credential at rest is not a login result, and this must not
                # read as one. Loud, never a pass: there is no zero-token status
                # subcommand for this lane, so its login state is UNDETERMINED
                # and the file is the strongest honest evidence doctor has.
                LANE_AUTH_OBSERVED+=("${lane}=credential-file")
                note_unknown "${lane} login state not verifiable (no status subcommand); a refresh credential IS present" \
                    "${lane}: ${LANE_CRED_FILE#"${HOME}/"} exists under \$HOME and carries a refresh token, so this lane has a durable credential at rest. That is NOT a login result — ${lane} exposes no zero-token status subcommand, so whether the credential still works is UNDETERMINED. No value from the file is read or logged."
            elif [[ -e "${LANE_CRED_FILE}" ]]; then
                note_warn "${lane} credential file is present but carries no refresh token — ${LANE_CRED_HINT}" \
                    "${lane}: ${LANE_CRED_FILE#"${HOME}/"} exists but has no refresh token, so the lane cannot re-authenticate unattended. Fix: ${LANE_CRED_HINT}."
            elif [[ "${lane}" == gemini ]] && [[ -n "${GEMINI_API_KEY:-}" ]]; then
                # Presence of the NAME only. The value is never expanded into a
                # message, a log line or a subprocess argument.
                LANE_AUTH_OBSERVED+=("gemini=api-key-env")
                note_unknown "gemini login state not verifiable; GEMINI_API_KEY is set in this environment" \
                    "gemini: no OAuth credential at ${LANE_CRED_FILE#"${HOME}/"}, but GEMINI_API_KEY is set here (presence only — its value is never read). Whether that key is valid is UNDETERMINED."
            else
                note_warn "${lane} has no credential — ${LANE_CRED_HINT}" \
                    "${lane}: no credential at ${LANE_CRED_FILE#"${HOME}/"}, so this lane is not authenticated and every ${lane} dispatch will fail. Fix: ${LANE_CRED_HINT}."
            fi
            ;;
    esac
done
[[ -n "${CLI_PROBE_OUT}" ]] && rm -f "${CLI_PROBE_OUT}"
[[ -n "${AUTH_PROBE_OUT}" ]] && rm -f "${AUTH_PROBE_OUT}"

# What the probes above OBSERVED, keyed by lane, for the declared-vs-actual
# cross-check in the inventory below. Values are stored space-free so the
# lookup can iterate the array without re-splitting a vendor string.
lane_auth_observed_value() {
    local want="$1" entry
    for entry in ${LANE_AUTH_OBSERVED[@]+"${LANE_AUTH_OBSERVED[@]}"}; do
        [[ "${entry%%=*}" == "${want}" ]] || continue
        printf '%s\n' "${entry#*=}"
        return 0
    done
    return 1
}

echo "" >> "${DOCTOR_LOG}"
echo "Dispatch-rail view (authority paths the board will actually exec):" >> "${DOCTOR_LOG}"
DOCTOR_EUID_HOME=""
if command -v python3 >/dev/null 2>&1; then
    DOCTOR_EUID_HOME="$(python3 -B - <<'PY' 2>/dev/null || true
import os
import pwd

print(pwd.getpwuid(os.geteuid()).pw_dir)
PY
)"
fi
if [[ -z "${DOCTOR_EUID_HOME}" ]]; then
    note_unknown "dispatch lane inventory not probed: effective-UID account home is unknown" \
        "the dispatch rail resolves executable authority from the effective-UID account home, but doctor could not resolve that home safely"
elif [[ "${HOME:-}" != "${DOCTOR_EUID_HOME}" ]]; then
    # A clean-room HOME must not gain capabilities from the account that happens
    # to execute the rehearsal. lane-inventory resolves Claude/Kimi from the
    # passwd home, so invoking it here would execute another home's binaries and
    # contaminate the very check doctor is meant to perform.
    note_unknown "dispatch lane inventory not probed: HOME differs from effective-UID account home" \
        "authority-path cross-check NOT RUN because HOME=${HOME:-<unset>} while the effective-UID account home is ${DOCTOR_EUID_HOME}; probing it would import state from outside this HOME"
elif LANE_INVENTORY=$(PYTHONPATH="${VAULT_ROOT}/scripts/python" python3 -B \
    "${VAULT_ROOT}/scripts/python/dispatch_context_builder.py" lane-inventory \
    --repo-root "${VAULT_ROOT}" 2>/dev/null) && [[ -n "${LANE_INVENTORY}" ]]; then
    CLI_DISAGREEMENTS=0
    while IFS=$'\t' read -r lane installed literal resolved version auth selections; do
        [[ -n "${lane}" ]] || continue
        # DECLARED beside OBSERVED, on one line, because that is the comparison
        # CLAUDE.md rule 9 asks for and nothing in this program made before.
        # `auth-policy` is what the inventory says the lane is MEANT to use;
        # `observed` is what the probe above actually found.
        lane_observed_auth="$(lane_auth_observed_value "${lane}" || true)"
        echo "- ${lane}: authority=${literal}; resolves_to=${resolved}; present_there=${installed}; version=${version:-unavailable}; auth-policy=${auth} (policy class, NOT an authentication result); observed-auth=${lane_observed_auth:-not-established}; profiles/models=${selections}" >> "${DOCTOR_LOG}"
        # The one disagreement worth a finding rather than a log line: a lane
        # whose policy is a subscription reporting that it authenticated with an
        # API KEY. That is the burn — a headless run spending credit instead of
        # the plan — and it is the vendor's own word for its method, not doctor's
        # inference. Known limit, in the fail-safe direction: a vendor who spells
        # it differently is a MISS, never a false report. The mere presence of an
        # API key in the environment is NOT this condition and is reported as a
        # fact above; this repository sets those variables deliberately and
        # strips them before it execs a lane.
        if [[ "${auth}" == subscription ]] \
            && [[ "${lane_observed_auth%%/*}" =~ [Aa][Pp][Ii].?[Kk][Ee][Yy] ]]; then
            CLI_DISAGREEMENTS=$((CLI_DISAGREEMENTS + 1))
            note_warn "${lane}: policy is subscription auth but the CLI reports it authenticated with an API key (${lane_observed_auth%%/*})" \
                "  ⚠️ ${lane} declares auth-policy=subscription, and its own status subcommand reports method '${lane_observed_auth%%/*}' — dispatches on this lane will spend API credit rather than the subscription. Unset the lane's API-key variable for subscription runs."
        fi
        here="$(command -v "${lane}" 2>/dev/null || true)"
        if [[ -n "${here}" && "${here}" != "${literal}" ]]; then
            CLI_DISAGREEMENTS=$((CLI_DISAGREEMENTS + 1))
            note_warn "${lane}: this HOME's PATH and the dispatch authority path disagree" \
                "  ⚠️ this HOME resolves ${lane} to ${here}, but dispatch will exec ${literal}"
        elif [[ -z "${here}" && "${installed}" == true ]]; then
            CLI_DISAGREEMENTS=$((CLI_DISAGREEMENTS + 1))
            note_warn "${lane}: dispatch authority sees a CLI this HOME does not" \
                "  ⚠️ ${lane} is absent from this HOME's PATH but present at the authority path ${literal} — that is another account's install, not yours"
        fi
    done <<< "${LANE_INVENTORY}"
    if [[ "${CLI_DISAGREEMENTS}" -eq 0 ]]; then
        note_ok "PATH and dispatch authority agree on every lane"
    fi
else
    # Formerly an ISSUE. A rail inventory that will not run tells us nothing
    # about the lanes; it is an unmeasured cross-check, not a broken install.
    note_unknown "dispatch lane inventory could not be resolved" \
        "the dispatch rail's lane inventory did not return — the authority-path cross-check did not run"
fi
unset DOCTOR_EUID_HOME

# --- 2. MCP reachability — invoke bootstrap-mcps.sh in --status mode ---
echo "" >> "${DOCTOR_LOG}"
echo "## MCP Servers" >> "${DOCTOR_LOG}"
if [[ ! -f "${VAULT_ROOT}/scripts/bootstrap-mcps.sh" ]]; then
    note_unknown "MCP registration status could not be read" \
        "scripts/bootstrap-mcps.sh is absent — MCP registration state is UNKNOWN"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "MCP registration status could not be parsed" \
        "grep is unavailable, so the --status rows could not be read"
else
    mcp_status_rc=0
    mcp_status_raw="$(bash "${VAULT_ROOT}/scripts/bootstrap-mcps.sh" --status 2>/dev/null)" \
        || mcp_status_rc=$?
    mcp_status=$(printf '%s\n' "${mcp_status_raw}" | grep -E '^[[:space:]]+[✓✗]' || true)
    if [[ -z "${mcp_status}" ]]; then
        # Formerly "MCP status indeterminate" as a WARNING, which reads like a
        # finding. It is not a finding; it is the absence of one.
        note_unknown "MCP registration status returned no rows" \
            "bootstrap-mcps.sh --status exited ${mcp_status_rc} and listed no server — registration state is UNKNOWN, not clean"
    else
        missing=$(printf '%s\n' "${mcp_status}" | grep -c '✗' | tr -d ' ')
        total=$(printf '%s\n' "${mcp_status}" | wc -l | tr -d ' ')
        if [[ ${missing} -eq 0 ]]; then
            note_ok "MCPs registered" "All MCPs registered across CLIs (${total} total)"
        else
            note_warn "${missing} MCP registrations missing — run scripts/bootstrap-mcps.sh" \
                "${missing}/${total} MCP registrations missing"
        fi
    fi
fi

# bin/mcp-audit.sh prints exactly one `summary: issues=N warnings=N log=...`
# line when it completes, then exits 0/1 on the issue count. No summary line
# means it did not finish -- which is not the same as finishing with findings,
# and is nothing like passing. Keying on the line rather than on the exit
# status alone is what separates the two.
if [[ ! -x "${VAULT_ROOT}/bin/mcp-audit.sh" ]]; then
    note_unknown "MCP usability audit could not run" \
        "bin/mcp-audit.sh is missing or not executable — MCP usability is UNKNOWN"
else
    mcp_audit_rc=0
    MCP_AUDIT_RAW="$("${VAULT_ROOT}/bin/mcp-audit.sh" 2>/dev/null)" || mcp_audit_rc=$?
    MCP_AUDIT_OUTPUT="$(printf '%s\n' "${MCP_AUDIT_RAW}" | grep -E '^summary: ' | tail -1)"
    if [[ -z "${MCP_AUDIT_OUTPUT}" ]]; then
        note_unknown "MCP usability audit did not complete" \
            "bin/mcp-audit.sh exited ${mcp_audit_rc} without a summary line — usability is UNKNOWN"
    elif [[ "${mcp_audit_rc}" -eq 0 ]]; then
        note_ok "MCP usability audit passed" \
            "MCP usability audit passed (${MCP_AUDIT_OUTPUT})"
    else
        # "reported registered/unusable drift" named no server, no tier and no
        # log, so the only way to act on it was to re-run the audit by hand and
        # read 40 lines. The audit's own per-server rows carry every fact this
        # needs; extracting them costs nothing, because MCP_AUDIT_RAW is already
        # in hand. Tier is what makes the finding legible: a required server
        # that will not initialize is a broken memory layer, an optional one is
        # a feature nobody configured.
        MCP_UNUSABLE_REQUIRED="$(printf '%s\n' "${MCP_AUDIT_RAW}" \
            | awk '/tier=required/ && /usable=false/ {name=$2; sub(/:$/, "", name); print name}' \
            | sort -u | tr '\n' ' ')"
        MCP_UNUSABLE_OPTIONAL="$(printf '%s\n' "${MCP_AUDIT_RAW}" \
            | awk '/tier=optional/ && /usable=false/ {name=$2; sub(/:$/, "", name); print name}' \
            | sort -u | tr '\n' ' ')"
        MCP_UNUSABLE_SUMMARY=""
        [[ -z "${MCP_UNUSABLE_REQUIRED// /}" ]] \
            || MCP_UNUSABLE_SUMMARY="required: ${MCP_UNUSABLE_REQUIRED% }"
        if [[ -n "${MCP_UNUSABLE_OPTIONAL// /}" ]]; then
            [[ -z "${MCP_UNUSABLE_SUMMARY}" ]] || MCP_UNUSABLE_SUMMARY+="; "
            MCP_UNUSABLE_SUMMARY+="optional: ${MCP_UNUSABLE_OPTIONAL% }"
        fi
        note_warn "MCP registered but unusable — ${MCP_UNUSABLE_SUMMARY:-see the audit log}" \
            "MCP usability audit found servers that are registered and answer no useful call (${MCP_UNUSABLE_SUMMARY:-no per-server row parsed}). Re-run bin/mcp-audit.sh for the per-lane rows; ${MCP_AUDIT_OUTPUT} names the log."
    fi
fi

# --- 2b. Product hygiene + memory discipline ---
echo "" >> "${DOCTOR_LOG}"
echo "## Product Hygiene" >> "${DOCTOR_LOG}"
# bin/product-hygiene.sh already distinguishes three outcomes and doctor used
# to collapse two of them: 0 = clean, 1 = real blockers found, 2 = COULD NOT
# RUN (its policy or the private identifier denylist is unavailable). Reporting
# 2 as "hygiene blockers present" turned "we could not scan" into "we scanned
# and found problems" -- and the normal state of a public projection is exactly
# 2, because the denylist is withheld by design.
#
# This is the check that made doctor unaffordable, and the reason --deep exists.
# Measured 2026-08-17 on the maintainer's tree: 127.3s of doctor's 141.3s total,
# against the launcher's 45s gate. Its own stage profile put 120.1s of that in
# `gitleaks dir` over a 4.7GB working tree -- and GITLEAKS_TIMEOUT defaults to
# 120, so the scan is bounded by its own deadline, not by the size of the job.
# There is nothing here to parallelise away and nothing safe to trim: this is a
# PUBLICATION gate (path policy, secret scan, private-identifier scan,
# remote-ref audit), and narrowing what it reads to make a launch faster would
# trade a publication guarantee for startup latency. So the fast path declines
# to run it and says so; --deep runs it unchanged.
#
# The executability probe stays FIRST, in both modes. It costs nothing, and
# "the tool for the deep check is missing" is a stronger and more actionable
# statement than "not measured in fast mode".
if [[ ! -x "${VAULT_ROOT}/bin/product-hygiene.sh" ]]; then
    note_unknown "public export hygiene could not run" \
        "bin/product-hygiene.sh is missing or not executable — export hygiene is UNKNOWN"
elif [[ "${DOCTOR_DEEP}" -ne 1 ]]; then
    note_deferred_deep "public export hygiene NOT MEASURED in fast mode — run: bin/doctor.sh --deep" \
        "Public export hygiene was NOT RUN. It costs ~127s on the maintainer's tree, against the ${SQUAD_DOCTOR_TIMEOUT:-45}s launch gate, so the fast path defers it. This line is NOT a pass: tracked publication blockers, leaked secrets, private identifiers and remote-ref exposure are ALL UNDETERMINED on this run. Run \`bin/doctor.sh --deep\` (bin/run-nightly.sh already does) or \`bin/product-hygiene.sh --public-export\` directly."
else
    hygiene_rc=0
    HYGIENE_RAW="$("${VAULT_ROOT}/bin/product-hygiene.sh" --public-export 2>&1)" \
        || hygiene_rc=$?
    HYGIENE_TAIL="$(printf '%s\n' "${HYGIENE_RAW}" | tail -2 | tr '\n' ' ')"
    case "${hygiene_rc}" in
        0)
            note_ok "public export hygiene clean" \
                "Public export has no tracked runtime/private blockers (${HYGIENE_TAIL})"
            ;;
        1)
            note_warn "public export hygiene blockers present — run bin/product-hygiene.sh --public-export" \
                "Public export hygiene found tracked blockers (${HYGIENE_TAIL})"
            ;;
        2)
            # DECISION (2026-08-11) on the private identifier denylist: it stays
            # PRIVATE, and doctor stops treating its absence as a finding. The
            # file lists the private identifiers the export must strip, so
            # publishing it publishes precisely what it exists to hide. The
            # consequence is that this scan cannot run in a public tree, and
            # the honest report of that is "not applicable", never a warning
            # about blockers nobody looked for.
            if [[ "$(classify_dependency 'tools/export/identifier-denylist.txt')" == unpublished ]]; then
                note_skip "public export hygiene needs the private identifier denylist, which this distribution does not carry" \
                    "Public export hygiene does not apply here: it requires the private identifier denylist, withheld from public projections by design (${HYGIENE_TAIL})"
            else
                note_unknown "public export hygiene could not run (exit 2)" \
                    "Public export hygiene could not run: ${HYGIENE_TAIL}"
            fi
            ;;
        *)
            note_unknown "public export hygiene exited ${hygiene_rc}, outside its 0/1/2 contract" \
                "Public export hygiene exited ${hygiene_rc} (${HYGIENE_TAIL})"
            ;;
    esac
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Instruction Drift" >> "${DOCTOR_LOG}"
# SCOPE, and the rule that decides severity.
#
# Until 2026-08-17 this scan reported one undifferentiated `instruction drift
# hits: 14` warning, unchanged for days, that nobody acted on. All fourteen were
# read: TWELVE were in dated audits, plans, specs and design documents under
# docs/, one was in a file whose own first line says "ARCHIVE, NOT LIVE STATE",
# and the last was a doc quoting the placeholder syntax it exists to explain.
# Zero were defects. A warning that fires forever on correct content is not a
# weak signal, it is a trained-in habit of ignoring the channel.
#
# Two corrections, and both come from rules this file already applies elsewhere:
#
#   SCOPE. The sibling referenced-script scan below deliberately excludes docs/,
#   quoting CLAUDE.md's own rule that old plans and specs are historical, and its
#   comment records why: "Including docs/ made this warning uncleanable, and a
#   warning that cannot reach zero is one people learn to ignore." Two scans in
#   one program asking the same question of different surfaces was the defect;
#   this one now reads the same four LIVE surfaces the runtime itself reads. A
#   dated audit saying "73 specialists" in July is an accurate record, not drift.
#
#   SEVERITY. A hit is a DEFECT when it is (a) on a surface the runtime reads as
#   instruction and (b) checkably false -- a roster count that disagrees with
#   shared/specialist-runtime-map.tsv, or an unfilled <FILL:> template. An agent
#   reading either acts on a false fact. Those are ISSUE. A pointer to a dated
#   handoff/spec/plan is a staleness smell, not a falsehood -- the file may well
#   be there -- so it stays WARN.
#
# Two things were also REMOVED rather than reclassified, each because another
# check owns the fact (CLAUDE.md rule 10):
#
#   * `scripts/send-req.sh` was a hardcoded name for one dead script. The
#     referenced-script scan below reads the same four surfaces and checks the
#     EXISTENCE of every script path in them, which is strictly stronger and
#     cannot go stale when the next script is retired.
#   * `N of M specialists` is an explicitly-partitioned claim ("20 of 73
#     specialists are content specialists"), not a roster total. It was counted
#     as a stale total every time.
#
# A self-declared archive is not a live surface. That is content-derived, not a
# hardcoded exemption list: a file earns it by saying ARCHIVE in its opening
# lines, which chrono/current.md does in its own title, and CLAUDE.md's Session
# Resume section says the same thing about that file from the outside.
drift_hit_is_on_a_live_surface() {
    local path="${1%%:*}"
    head -15 "${path}" 2>/dev/null \
        | grep -qiE '^#[^\n]*\bARCHIVE\b|\bARCHIVE, NOT LIVE\b' && return 1
    return 0
}

DRIFT_DEFECTS=0
DRIFT_SMELLS=0
DRIFT_EXAMPLE=""
DRIFT_SCANNED=false
# A missing grep used to leave the counts at 0 and print the clean line: the
# scan that never happened reported as the scan that found nothing.
if [[ "${GREP_USABLE}" == true ]]; then
    # The four surfaces the runtime reads as instruction, identical to the
    # referenced-script scan's list below.
    DRIFT_PATHS=("${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" \
        "${VAULT_ROOT}/chrono" "${VAULT_ROOT}/shared")
    for _drift_path in "${DRIFT_PATHS[@]}"; do
        [[ -e "${_drift_path}" ]] && DRIFT_SCANNED=true
    done
    unset _drift_path
    SPECIALIST_COUNT=$(awk -F '\t' 'NR > 1 && $1 != "" {count++} END {print count + 0}' \
        "${VAULT_ROOT}/shared/specialist-runtime-map.tsv" 2>/dev/null)
    # DEFECT class 1: a roster total that disagrees with the live registry.
    while IFS= read -r _drift_hit; do
        [[ -n "${_drift_hit}" ]] || continue
        drift_hit_is_on_a_live_surface "${_drift_hit}" || continue
        DRIFT_DEFECTS=$((DRIFT_DEFECTS + 1))
        [[ -n "${DRIFT_EXAMPLE}" ]] || DRIFT_EXAMPLE="${_drift_hit}"
    done < <(grep -RInE '[0-9][0-9]+ specialists' "${DRIFT_PATHS[@]}" 2>/dev/null \
        | awk -v expected="${SPECIALIST_COUNT:-0}" '
            {
                text = $0
                gsub(/[0-9]+ of [0-9]+ specialists/, "", text)
                while (match(text, /[0-9][0-9]+ specialists/)) {
                    value = substr(text, RSTART, RLENGTH)
                    sub(/ specialists$/, "", value)
                    if ((value + 0) != expected) {
                        print $0
                        break
                    }
                    text = substr(text, RSTART + RLENGTH)
                }
            }
        ')
    # DEFECT class 2: an instruction surface still carrying its template markers.
    while IFS= read -r _drift_hit; do
        [[ -n "${_drift_hit}" ]] || continue
        drift_hit_is_on_a_live_surface "${_drift_hit}" || continue
        DRIFT_DEFECTS=$((DRIFT_DEFECTS + 1))
        [[ -n "${DRIFT_EXAMPLE}" ]] || DRIFT_EXAMPLE="${_drift_hit}"
    done < <(grep -RInE 'currently has FILL placeholders|<FILL:' \
        "${DRIFT_PATHS[@]}" 2>/dev/null)
    # SMELL class: a live surface routing a reader to a dated historical doc.
    while IFS= read -r _drift_hit; do
        [[ -n "${_drift_hit}" ]] || continue
        drift_hit_is_on_a_live_surface "${_drift_hit}" || continue
        DRIFT_SMELLS=$((DRIFT_SMELLS + 1))
    done < <(grep -RInE 'docs/handoffs/[0-9]{4}-|docs/specs/spec-[0-9]|docs/plans/[0-9]{4}-' \
        "${DRIFT_PATHS[@]}" 2>/dev/null)
    unset _drift_hit
fi
DRIFT_GREP_HINT="grep -RInE '[0-9][0-9]+ specialists|<FILL:' README.md CLAUDE.md chrono shared"
if [[ "${DRIFT_SCANNED}" != true ]]; then
    note_unknown "instruction drift scan did not run" \
        "no instruction surface was readable (grep usable=${GREP_USABLE}) — drift is UNKNOWN, not clean"
else
    if [[ "${DRIFT_DEFECTS}" -gt 0 ]]; then
        note_issue "instruction drift: ${DRIFT_DEFECTS} live instruction surface(s) state something checkably false" \
            "${DRIFT_DEFECTS} defect(s) on surfaces the runtime reads as instruction — a stale specialist-roster count (live registry: ${SPECIALIST_COUNT:-unknown}) or an unfilled <FILL:> template. Every agent that reads them acts on a false fact. First: ${DRIFT_EXAMPLE#"${VAULT_ROOT}/"}. Reproduce with: ${DRIFT_GREP_HINT}"
    fi
    if [[ "${DRIFT_SMELLS}" -gt 0 ]]; then
        note_warn "instruction drift: ${DRIFT_SMELLS} live surface reference(s) to dated handoffs/specs/plans" \
            "${DRIFT_SMELLS} live instruction surface(s) point a reader at a dated handoff, spec or plan. CLAUDE.md classes those as historical, so the pointer is stale rather than false — warning, not issue."
    fi
    if [[ "${DRIFT_DEFECTS}" -eq 0 && "${DRIFT_SMELLS}" -eq 0 ]]; then
        note_ok "instruction drift clean" \
            "No stale roster count, unfilled template, or dated-doc pointer on the four live instruction surfaces (README.md, CLAUDE.md, chrono/, shared/). Self-declared archives are excluded; historical documents under docs/ are out of scope by the same rule the referenced-script scan uses."
    fi
fi

# The full gate asserts BOTH that the repository's specialist/routing content is
# coherent AND that every capability a specialist claims is live on this host's
# PATH. On a host that has not installed the arsenal -- a fresh clone, or a
# rehearsal under a temporary PATH -- the second half fails hundreds of times
# and says nothing whatever about the repository. Measured 2026-08-11 under a
# temp HOME: full gate exit 1 with 255 `capability claims host-PATH evidence
# but is absent from PATH` diagnostics, while the host-independent subset
# exited 0. Doctor reported that as "specialist/routing validation failed".
#
# SQUAD_CI_HOST_INDEPENDENT=1 is the discriminator the script already exposes:
# when the subset passes and the full gate does not, the difference is host
# evidence, so the live half is UNDETERMINED here and the content half passed.
#
# It also has its own could-not-run code, which doctor used to discard.
# scripts/python/validate_capability_homes.py returns 2 from its configuration
# handler and 1 only when it has real diagnostics, and bin/validate-specialists.sh
# propagates that verbatim. Exit 2 is the normal state of a public projection:
# the gate reads shared/registries/skill-tool-registry.tsv, which is withheld.
#
# DECISION (2026-08-11) on that registry: it stays PRIVATE. Its verified_state,
# lanes, evidence and notes columns are a census of what works on OUR machines
# plus the gotchas that cost us campaigns; publishing it hands over the arsenal
# rather than the method. A published substitute already exists and is generated
# from it -- tools/export/build_public_catalog.py emits
# shared/registries/recommended-toolchain.tsv, which carries name, purpose,
# technique class and target class and no liveness at all. validate_specialists.py
# already downgrades its absence to the non-fatal `registry-not-published`
# warning; doctor now agrees with it instead of reporting a failure.
report_specialist_gate_unavailable() {
    if [[ "$(classify_dependency 'shared/registries/skill-tool-registry.tsv')" == unpublished ]]; then
        note_skip "specialist/routing validation needs the private tool registry, which this distribution does not carry" \
            "Specialist/routing validation does not apply here: it reads shared/registries/skill-tool-registry.tsv, withheld from public projections by design (see shared/registries/recommended-toolchain.tsv)"
    else
        note_unknown "specialist/routing validation could not run (exit 2: configuration)" \
            "Specialist/routing validation could not run — a required input was unavailable"
    fi
}

if [[ ! -x "${VAULT_ROOT}/bin/validate-specialists.sh" ]]; then
    note_unknown "specialist/routing validation could not run" \
        "bin/validate-specialists.sh is missing or not executable — routing validity is UNKNOWN"
else
    specialist_gate_rc=0
    "${VAULT_ROOT}/bin/validate-specialists.sh" >/dev/null 2>&1 || specialist_gate_rc=$?
    case "${specialist_gate_rc}" in
        0)
            note_ok "specialist/routing validation passed" \
                "Specialist, routing, and generated-adapter validation passed"
            ;;
        2)
            report_specialist_gate_unavailable
            ;;
        1)
            # Real diagnostics, or merely this host's PATH. Re-run the subset to
            # tell them apart rather than guessing.
            specialist_subset_rc=0
            SQUAD_CI_HOST_INDEPENDENT=1 "${VAULT_ROOT}/bin/validate-specialists.sh" \
                >/dev/null 2>&1 || specialist_subset_rc=$?
            case "${specialist_subset_rc}" in
                0)
                    note_ok "specialist/routing content validation passed" \
                        "Specialist, routing, and generated-adapter CONTENT validation passed"
                    note_unknown "live capability evidence unavailable on this host" \
                        "The live-capability half of the gate could not be established on this host's PATH; repository content itself validated clean"
                    ;;
                2)
                    report_specialist_gate_unavailable
                    ;;
                *)
                    note_warn "specialist/routing validation failed" \
                        "Specialist/routing validation failed on the host-independent subset too; see bin/validate-specialists.sh output"
                    ;;
            esac
            ;;
        *)
            note_unknown "specialist/routing validation exited ${specialist_gate_rc}, outside its 0/1/2 contract"
            ;;
    esac
fi

# --- Externally-registered entry points ---------------------------------
# Scripts invoked by launchd have NO in-repo caller, so `git grep` calls them
# dead. A 2026-08-06 audit did exactly that for bin/squad-monitor.sh, which runs
# every 120 seconds via com.chrono.squad-monitor. Six repo scripts are bound
# this way; surfacing the mapping here makes it visible from a health run rather
# than only from ~/Library/LaunchAgents. It also catches the inverse -- a
# registered job whose script no longer exists -- which previously appeared only
# as a silent "No such file or directory" in a log nobody reads.
#
# Matched on the repo-relative TAIL, not on an absolute VAULT_ROOT prefix: under
# a git worktree VAULT_ROOT is the worktree, so a prefix match silently reports
# zero and the check quietly stops checking.
REGISTERED_MISSING=0
REGISTERED_COUNT=0
PLIST_COUNT=0
PLIST_UNREADABLE=0
# LOADED versus REGISTERED. Reading a plist establishes that a job was DECLARED
# and that the script it names exists; it says nothing about whether launchd
# ever accepted the job, or what happened the last time it ran. `launchctl` did
# not appear in this file once, which is how a scheduled job that failed on
# every invocation for months stayed invisible: its plist was perfect and its
# script was right there.
#
# READ-ONLY subcommands only. `launchctl print` is the whole of the interaction;
# bootout, load, unload, kickstart and remove are never issued from this program
# under any condition. The operator's live jobs run through launchd.
LAUNCHD_UNLOADED=()
LAUNCHD_FAILING=()
LAUNCHD_PROBED=0
LAUNCHD_UNPROBED=0
LAUNCHCTL_DOMAIN="gui/$(id -u 2>/dev/null || printf '%s' "${UID:-0}")"
for plist in "${HOME}"/Library/LaunchAgents/*.plist; do
    [[ -e "$plist" ]] || continue
    PLIST_COUNT=$((PLIST_COUNT + 1))
    # A plutil that cannot read a plist yields the same empty path list as a
    # plist that registers no repo script. Count the failures separately.
    if ! plist_dump="$(plutil -p "$plist" 2>/dev/null)"; then
        PLIST_UNREADABLE=$((PLIST_UNREADABLE + 1))
        continue
    fi
    plist_repo_scripts=0
    while IFS= read -r abs_path; do
        [[ -n "$abs_path" ]] || continue
        rel="${abs_path##*/Obsidian-Claude-Vibe-Squad/}"
        [[ "$rel" == "$abs_path" ]] && continue
        REGISTERED_COUNT=$((REGISTERED_COUNT + 1))
        plist_repo_scripts=$((plist_repo_scripts + 1))
        if [[ ! -e "${VAULT_ROOT}/${rel}" ]]; then
            REGISTERED_MISSING=$((REGISTERED_MISSING + 1))
            ISSUES+=("launchd job $(basename "$plist") points at a missing script: ${rel}")
        fi
    done < <(printf '%s\n' "${plist_dump}" | grep -oE '/[A-Za-z0-9._/-]+\.(sh|py)' | sort -u)

    # Scoped to jobs that run THIS repository's scripts. Every other agent on
    # the machine belongs to somebody else and is none of this program's
    # business to report on.
    [[ "${plist_repo_scripts}" -gt 0 ]] || continue
    command -v launchctl >/dev/null 2>&1 || { LAUNCHD_UNPROBED=$((LAUNCHD_UNPROBED + 1)); continue; }
    plist_label="$(plutil -extract Label raw "$plist" 2>/dev/null | head -1)"
    if [[ -z "${plist_label}" ]]; then
        # `launchctl print gui/501/` with an empty label succeeds -- it prints
        # the DOMAIN. Probing without a label would report every unlabelled
        # plist as a loaded job, so it is refused rather than guessed.
        LAUNCHD_UNPROBED=$((LAUNCHD_UNPROBED + 1))
        continue
    fi
    LAUNCHD_PROBED=$((LAUNCHD_PROBED + 1))
    if ! launchd_print="$(launchctl print "${LAUNCHCTL_DOMAIN}/${plist_label}" 2>&1)"; then
        LAUNCHD_UNLOADED+=("${plist_label}")
        continue
    fi
    launchd_exit="$(printf '%s\n' "${launchd_print}" \
        | awk -F'= ' '/last exit code = /{print $2; exit}' | tr -d ' \t')"
    # "(never exited)" is a long-running job that has not stopped; 0 is a clean
    # last run. Anything else is a job that ran and FAILED, which is the state
    # nothing in this program could see before.
    case "${launchd_exit}" in
        ""|0|"(neverexited)") ;;
        *) LAUNCHD_FAILING+=("${plist_label} (last exit ${launchd_exit})") ;;
    esac
done
if ! command -v plutil >/dev/null 2>&1; then
    note_unknown "launchd registration audit could not run: plutil is unavailable"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "launchd registration audit could not run: grep is unavailable"
elif [[ "${PLIST_COUNT}" -eq 0 ]]; then
    note_skip "no launchd agents are registered for this HOME" \
        "No ${HOME}/Library/LaunchAgents/*.plist to audit — nothing is scheduled from this HOME"
elif [[ "${PLIST_UNREADABLE}" -gt 0 ]]; then
    note_unknown "${PLIST_UNREADABLE}/${PLIST_COUNT} launchd plist(s) could not be read" \
        "${PLIST_UNREADABLE} of ${PLIST_COUNT} plist(s) were unreadable; the scripts they register were NOT checked"
elif [[ "${REGISTERED_MISSING}" -eq 0 ]]; then
    note_ok "launchd-registered scripts present" \
        "${REGISTERED_COUNT} launchd-registered repo script(s) across ${PLIST_COUNT} plist(s) all present"
else
    note_warn "${REGISTERED_MISSING}/${REGISTERED_COUNT} launchd-registered script(s) missing" \
        "${REGISTERED_MISSING}/${REGISTERED_COUNT} launchd-registered script(s) MISSING"
fi

# The live half: what launchd itself says about the jobs that run this repo's
# scripts. Declared-and-present is not loaded, and loaded is not succeeding.
if [[ "${LAUNCHD_PROBED}" -eq 0 ]] && [[ "${LAUNCHD_UNPROBED}" -eq 0 ]]; then
    note_skip "no launchd job on this HOME runs a script from this repository" \
        "None of the ${PLIST_COUNT} plist(s) in ${HOME}/Library/LaunchAgents names a script under this checkout, so there is no scheduled job of this repository's to probe"
else
    if [[ "${LAUNCHD_UNPROBED}" -gt 0 ]]; then
        note_unknown "${LAUNCHD_UNPROBED} launchd job(s) running repo scripts could not be probed" \
            "${LAUNCHD_UNPROBED} plist(s) that register a repo script carry no readable Label (or launchctl is unavailable), so whether launchd loaded them is UNKNOWN — not loaded, and certainly not running"
    fi
    if [[ "${#LAUNCHD_UNLOADED[@]}" -gt 0 ]]; then
        note_issue "launchd job(s) declared but NOT loaded: ${LAUNCHD_UNLOADED[*]}" \
            "${#LAUNCHD_UNLOADED[@]} of ${LAUNCHD_PROBED} probed job(s) have a plist and a script but launchd does not know them: ${LAUNCHD_UNLOADED[*]}. They are scheduled in name only and will never fire. Fix: bootstrap the plist into ${LAUNCHCTL_DOMAIN} (doctor never mutates launchd)."
    fi
    if [[ "${#LAUNCHD_FAILING[@]}" -gt 0 ]]; then
        note_warn "launchd job(s) whose last run FAILED: ${LAUNCHD_FAILING[*]}" \
            "${#LAUNCHD_FAILING[@]} loaded job(s) exited non-zero on their most recent run: ${LAUNCHD_FAILING[*]}. A scheduled job that fails every time looks identical to one that never runs — check its StandardErrorPath."
    fi
    if [[ "${#LAUNCHD_UNLOADED[@]}" -eq 0 ]] && [[ "${#LAUNCHD_FAILING[@]}" -eq 0 ]] \
        && [[ "${LAUNCHD_PROBED}" -gt 0 ]]; then
        note_ok "all ${LAUNCHD_PROBED} launchd job(s) for this repo are loaded and last exited cleanly" \
            "launchctl print answered for all ${LAUNCHD_PROBED} job(s) running this repository's scripts, and none reported a failing last exit code"
    fi
fi

# DECISION (2026-08-11) on docs/brain-map.md: it stays PRIVATE, and doctor
# stops requiring it.
#
# It is the internal source-of-truth map. Its own tables cite chrono/current.md
# and shared/lifecycle.md, both themselves denied by policy, and it documents
# the staged-versus-live V4 boundary -- internal navigation, not adopter
# documentation. tools/export/policy/path-policy.json denies it alongside
# docs/roadmap.md, docs/lineage.md and docs/design/**; docs/architecture.md is
# the published equivalent an adopter actually needs. Nothing in the runtime
# reads it: doctor's own check was its only non-prose consumer, and it was
# pushing a public install to exit 1 over a file that install was never meant
# to have. The export policy is unchanged.
#
# Tracked-but-absent stays an ISSUE, so deleting it in the private tree is
# still caught. Only "this distribution never carried it" is exempt.
#
# PRESENT is not USABLE. `note_ok "brain map present"` was a stat() standing in
# for a claim about the internal source-of-truth map, and it is one of the few
# checks here that can gate exit 1. What makes this file a map is its Source
# Layers table: a set of canonical paths a reader is sent to. A map whose
# destinations have moved is worse than no map, and existence cannot see that.
#
# The probe resolves every path it names -- globs included -- and reports how
# many. It reads the file's own references rather than a list kept here, so
# adding a layer to the map extends the check for free.
case "$(classify_dependency 'docs/brain-map.md')" in
    present)
        BRAIN_MAP_REFS=0
        BRAIN_MAP_BROKEN=()
        if [[ "${GREP_USABLE}" != true ]]; then
            note_gate_unknown "brain map references could not be resolved: grep is unavailable" \
                "docs/brain-map.md is present but its canonical paths were NOT checked — whether the map still points at anything is UNKNOWN"
        else
            # The resolution runs entirely inside ONE subshell, and both of its
            # two lines matter. `cd` makes the map's repo-relative paths resolve
            # against the repository rather than against whatever directory
            # doctor happened to be invoked from -- from anywhere else, every
            # reference reports broken. `nullglob` is what lets a glob say "no
            # matches": without it bash leaves an unmatched pattern as its own
            # literal text, the array is never empty, and the check cannot fail.
            # Both were wrong in the first draft and both were caught by
            # test_a_path_that_moved_is_a_blocking_issue, which is why the
            # subshell now emits its verdict rather than the parent recomputing.
            while IFS= read -r _map_row; do
                [[ -n "${_map_row}" ]] || continue
                BRAIN_MAP_REFS=$((BRAIN_MAP_REFS + 1))
                [[ "${_map_row}" == broken\ * ]] \
                    && BRAIN_MAP_BROKEN+=("${_map_row#broken }")
            done < <(
                cd "${VAULT_ROOT}" 2>/dev/null || exit 0
                shopt -s nullglob
                while IFS= read -r _ref; do
                    [[ -n "${_ref}" ]] || continue
                    # Word-split on purpose: some of these are globs. nullglob
                    # only speaks for references that CONTAIN a wildcard -- a
                    # plain path with no metacharacter expands to itself whether
                    # or not it exists, so each element is still tested with -e.
                    # Checking the array length alone made every literal path
                    # resolve, which is a check that cannot fail.
                    # shellcheck disable=SC2206
                    _hits=( ${_ref} )
                    _resolved=0
                    for _hit in ${_hits[@]+"${_hits[@]}"}; do
                        [[ -e "${_hit}" ]] && _resolved=$((_resolved + 1))
                    done
                    if [[ "${_resolved}" -gt 0 ]]; then
                        printf 'ok %s\n' "${_ref}"
                    else
                        printf 'broken %s\n' "${_ref}"
                    fi
                done < <(
                    grep -oE '`[A-Za-z_][A-Za-z0-9_*.-]*(/[A-Za-z0-9_*.-]+)+\.(md|tsv|json|sh|py)`' \
                        docs/brain-map.md 2>/dev/null | tr -d '`' | sort -u
                )
            )
            unset _map_row
            if [[ "${BRAIN_MAP_REFS}" -eq 0 ]]; then
                note_gate_unknown "brain map names no canonical path" \
                    "docs/brain-map.md is present but its Source Layers table yielded no path reference at all — the file exists and maps nothing, which is not the same as a map that checks out"
            elif [[ "${#BRAIN_MAP_BROKEN[@]}" -eq 0 ]]; then
                note_ok "brain map resolves: all ${BRAIN_MAP_REFS} canonical path(s) exist" \
                    "Brain map present, and every one of the ${BRAIN_MAP_REFS} canonical path(s) it names resolves in this tree"
            else
                note_issue "brain map points at ${#BRAIN_MAP_BROKEN[@]} path(s) that no longer exist: ${BRAIN_MAP_BROKEN[*]}" \
                    "docs/brain-map.md is the internal source-of-truth map and ${#BRAIN_MAP_BROKEN[@]} of the ${BRAIN_MAP_REFS} canonical path(s) it sends a reader to do not resolve: ${BRAIN_MAP_BROKEN[*]}. Fix the map, or restore what moved."
            fi
        fi
        ;;
    missing)
        note_issue "brain map missing" \
            "docs/brain-map.md is tracked in this tree but absent from the working copy"
        ;;
    unpublished)
        note_skip "brain map is private and not part of this distribution" \
            "docs/brain-map.md is withheld from public projections by policy; not required here (see docs/architecture.md)"
        ;;
    *)
        note_unknown "brain map status could not be determined" \
            "git could not read this tree, so 'absent' cannot be told from 'never shipped'"
        ;;
esac

# Scans LIVE instruction surfaces only. docs/ is excluded by CLAUDE.md's own
# rule -- "old plans/specs are historical unless current state references them"
# -- and a dated design doc naming a since-removed script is an accurate record,
# not drift. Including docs/ made this warning uncleanable, and a warning that
# cannot reach zero is one people learn to ignore.
#
# A reference also counts as resolved when it matches the TAIL of a real tracked
# path: the pattern captures `bin/install-local.sh` out of the genuine
# `tools/radar/bin/install-local.sh`, which is an artifact of the match, not a
# missing file.
MISSING_SCRIPT_REFS=0
SCRIPT_REFS_SEEN=0
if [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "referenced-script scan could not run: grep is unavailable"
elif [[ "${GIT_USABLE}" != true ]]; then
    # The tail-match exemption below needs `git ls-files`. Without it every
    # legitimately-relocated reference counts as missing, so the scan is not
    # merely degraded -- its answer is wrong in both directions.
    note_unknown "referenced-script scan could not run: git cannot read this tree"
else
    while IFS= read -r script_ref; do
        [[ -n "$script_ref" ]] || continue
        SCRIPT_REFS_SEEN=$((SCRIPT_REFS_SEEN + 1))
        [[ -e "${VAULT_ROOT}/${script_ref}" ]] && continue
        if git -C "${VAULT_ROOT}" ls-files 2>/dev/null | grep -qE "(^|/)${script_ref}$"; then
            continue
        fi
        MISSING_SCRIPT_REFS=$((MISSING_SCRIPT_REFS + 1))
    done < <(grep -RhoE '(bin|scripts|shared)/[A-Za-z0-9._/-]+\.(sh|py)' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/shared" 2>/dev/null | sort -u)
    if [[ "${SCRIPT_REFS_SEEN}" -eq 0 ]]; then
        note_unknown "referenced-script scan found no references at all" \
            "not one script reference was read from README/CLAUDE/chrono/shared — the scan found nothing to check, which is not the same as finding nothing wrong"
    elif [[ "${MISSING_SCRIPT_REFS}" -eq 0 ]]; then
        note_ok "referenced scripts exist" \
            "All ${SCRIPT_REFS_SEEN} referenced script path(s) resolve"
    else
        note_warn "missing referenced scripts: ${MISSING_SCRIPT_REFS}" \
            "${MISSING_SCRIPT_REFS}/${SCRIPT_REFS_SEEN} referenced script path(s) are missing"
    fi
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Memory Discipline" >> "${DOCTOR_LOG}"
# Same summary-line contract as the MCP audit: one `summary: issues=N ...` line
# on completion. Its absence used to be indistinguishable from a real finding,
# and the "no summary" fallback text was itself the giveaway that nobody had
# decided what that case meant.
# An absent checker is an unmeasured cross-check, not a broken install -- the
# same call doctor already makes for bin/mcp-audit.sh, bin/product-hygiene.sh,
# bin/validate-specialists.sh and scripts/bootstrap-mcps.sh, all four of which
# use note_unknown here. This one branch was the outlier, and the inconsistency
# was the defect: five sibling checkers, one identical situation, five different
# consequences is not a policy.
if [[ ! -x "${VAULT_ROOT}/bin/memory-audit.sh" ]]; then
    note_unknown "memory audit could not run" \
        "bin/memory-audit.sh is missing or not executable — memory discipline is UNKNOWN"
else
    memory_rc=0
    MEMORY_RAW="$("${VAULT_ROOT}/bin/memory-audit.sh" 2>/dev/null)" || memory_rc=$?
    MEMORY_OUTPUT="$(printf '%s\n' "${MEMORY_RAW}" | grep -E '^summary: ' | tail -1)"
    if [[ -z "${MEMORY_OUTPUT}" ]]; then
        note_gate_unknown "memory audit did not complete" \
            "bin/memory-audit.sh exited ${memory_rc} without a summary line — memory discipline is UNKNOWN"
    else
        case "${memory_rc}" in
            0)
                if [[ "${MEMORY_OUTPUT}" =~ status=clean ]] \
                    && [[ "${MEMORY_OUTPUT}" =~ files_scanned=([1-9][0-9]*) ]]; then
                    note_ok "memory audit passed" "Memory audit passed (${MEMORY_OUTPUT})"
                else
                    note_gate_unknown "memory audit returned an invalid clean summary" \
                        "bin/memory-audit.sh exited 0 without proving files_scanned>0 and status=clean (${MEMORY_OUTPUT})"
                fi
                ;;
            1)
                note_issue "memory audit found missing discipline cite or secret-like pattern" \
                    "Memory audit found issues (${MEMORY_OUTPUT})"
                ;;
            2)
                # bin/memory-audit.sh returns 2 for BOTH "there was nothing to
                # scan" and "I lost a required command mid-scan", and its own
                # summary line already carries the fact that separates them
                # (memory-audit.sh:105-108,118). A tree with no
                # departments/*/memory.md has produced no memory that could be
                # undisciplined; a scan that READ files and still could not
                # conclude is a genuinely unmeasured integrity gate.
                if [[ "${MEMORY_OUTPUT}" =~ files_scanned=0([^0-9]|$) ]]; then
                    note_absent_input "memory audit had no memory file to scan yet" \
                        "Memory audit scanned zero files: no departments/*/memory.md exists yet, so memory discipline is unestablished rather than lost (${MEMORY_OUTPUT})"
                else
                    note_gate_unknown "memory audit could not determine memory discipline" \
                        "Memory audit read files but lost a required command (${MEMORY_OUTPUT})"
                fi
                ;;
            *)
                note_gate_unknown "memory audit failed unexpectedly with exit ${memory_rc}" \
                    "Memory audit returned an undocumented exit code (${MEMORY_OUTPUT})"
                ;;
        esac
    fi
fi

# --- 3. Secrets ---
# DECLARATION versus PROBE, in the shape the MCP section above already uses:
# `bootstrap-mcps.sh --status` says what is REGISTERED and `bin/mcp-audit.sh`
# says what is USABLE, and only the second decides. Until 2026-08-17 this check
# was a bare `[[ -f ]]` -> note_ok "secrets.zsh present": the gate for every
# optional integration was a stat(), the file was never read, and not one key
# name was checked. An empty secrets.zsh passed.
#
# The names come from scripts/bootstrap-mcps.sh, which already declares, per MCP
# server, the environment it needs (`name|command|ENV_NAMES`). Doctor reads that
# rather than carrying a second list of key names that would age separately
# (CLAUDE.md rule 10).
#
# SECRET HANDLING, and why it is shaped this way. The file is sourced in a
# SUBSHELL whose output is a list of NAMES: no value is printed, logged, or
# returned, and nothing it defines survives into doctor's environment, so no
# later probe can inherit a key and pass it to a child process. API keys have
# leaked through terminal titles in this system before, which is why
# scripts/python/tests/test_doctor_declaration_probes.py asserts a planted
# sentinel value reaches neither the report, nor stdout, nor the JSON summary.
# Sourcing is not a new capability: the operator's own .zprofile already sources
# this file at every login.
echo "" >> "${DOCTOR_LOG}"
echo "## Secrets" >> "${DOCTOR_LOG}"
SECRETS_FILE="${HOME}/.config/shell/secrets.zsh"
MCP_BOOTSTRAP="${VAULT_ROOT}/scripts/bootstrap-mcps.sh"
if [[ -f "${SECRETS_FILE}" ]]; then
    note_ok "secrets.zsh present" "secrets.zsh present at ${SECRETS_FILE}"
    SECRETS_EXPECTED=""
    if [[ -r "${MCP_BOOTSTRAP}" ]]; then
        SECRETS_EXPECTED="$(grep -oE '^[[:space:]]*"[a-z-]+\|[^|]*\|[A-Z0-9_ ]+"' \
            "${MCP_BOOTSTRAP}" 2>/dev/null \
            | awk -F'|' '{print $3}' | tr -d '"' | tr ' ' '\n' \
            | grep -E '^[A-Z][A-Z0-9_]+$' | sort -u | tr '\n' ' ')"
    fi
    if [[ -z "${SECRETS_EXPECTED// /}" ]]; then
        note_gate_unknown "secrets.zsh contents were NOT checked: no expected key names could be read" \
            "scripts/bootstrap-mcps.sh did not yield the per-server environment names, so doctor could not tell a configured secrets.zsh from an empty one — the file's presence is NOT evidence that any integration will work"
    else
        # Names out, values never. `set +u` because the file is the operator's,
        # not ours, and an unset reference in it must not abort the probe.
        SECRETS_MISSING="$( (
            set +u
            # shellcheck disable=SC1090
            . "${SECRETS_FILE}" >/dev/null 2>&1
            for _secret_name in ${SECRETS_EXPECTED}; do
                eval "_secret_value=\${${_secret_name}:-}"
                [[ -n "${_secret_value}" ]] || printf '%s ' "${_secret_name}"
            done
        ) 2>/dev/null )"
        SECRETS_EXPECTED_COUNT="$(printf '%s' "${SECRETS_EXPECTED}" | wc -w | tr -d ' ')"
        SECRETS_MISSING_COUNT="$(printf '%s' "${SECRETS_MISSING}" | wc -w | tr -d ' ')"
        if [[ "${SECRETS_MISSING_COUNT}" -eq 0 ]]; then
            note_ok "secrets.zsh defines all ${SECRETS_EXPECTED_COUNT} key names the MCP registry asks for" \
                "Sourced in a subshell: every one of the ${SECRETS_EXPECTED_COUNT} environment names scripts/bootstrap-mcps.sh declares is defined and non-empty. No value was read or logged."
        else
            note_warn "secrets.zsh is missing ${SECRETS_MISSING_COUNT} of ${SECRETS_EXPECTED_COUNT} expected key name(s): ${SECRETS_MISSING% }" \
                "Sourced in a subshell: ${SECRETS_MISSING_COUNT} of the ${SECRETS_EXPECTED_COUNT} environment names scripts/bootstrap-mcps.sh declares are unset or empty — ${SECRETS_MISSING% }. Every MCP server that declares one of those names will register and then fail to do anything useful; grep scripts/bootstrap-mcps.sh for the name to see which. Only names were read; no value was logged."
        fi
    fi
else
    # Demoted from ISSUE. The core markdown dispatch rail runs on subscription
    # CLI auth and needs no secrets file; this gates the OPTIONAL integrations
    # (research arsenal, media studio, recon). A first run on a clean machine
    # has no secrets file, and exiting 1 there teaches a new user that doctor's
    # exit code means nothing. The exit code means "this installation cannot do
    # its job", not "this installation is not finished being set up".
    note_warn "secrets.zsh not configured — optional integrations stay off" \
        "secrets.zsh not present at ${HOME}/.config/shell/secrets.zsh — optional MCP integrations (research arsenal, media studio, recon) stay off; the core markdown rail is unaffected. Setup: docs/getting-started.md § 4. (docs/private-config.md is the do-not-commit policy, not the setup guide.)"
fi

# --- 4. Private memory vault + repository accessibility ---
echo "" >> "${DOCTOR_LOG}"
echo "## Vault" >> "${DOCTOR_LOG}"
# NOT CONFIGURED and CONFIGURED-BUT-BROKEN are different findings and only the
# second is a fault. An unset CHRONO_VAULT_ROOT is the state of every machine
# before the operator points it at a vault; a set-but-invalid one is a
# regression that must stay loud.
if PRIVATE_VAULT_ERROR="$(check_private_vault_root 2>&1)"; then
    note_ok "private memory vault valid" "Private memory vault root is valid"
elif [[ -z "${CHRONO_VAULT_ROOT:-}" ]]; then
    # The pointer used to be docs/private-config.md, which is the do-not-commit
    # POLICY and contains no setup instruction and not one mention of this
    # variable. A warning whose remedy link does not answer the question is one
    # the reader follows once. docs/getting-started.md § 3 has the three commands
    # (export, mkdir, .chrono-vault sentinel) that clear it.
    note_warn "private memory vault not configured (CHRONO_VAULT_ROOT unset) — record/recall are off; see docs/getting-started.md § 3" \
        "Private memory vault is not configured: CHRONO_VAULT_ROOT is unset, so chrono-vault's record/recall are off and this session keeps no durable memory — silently, from the inside. Fix: docs/getting-started.md § 3 (export the path, create it, write the .chrono-vault sentinel)."
else
    note_issue "private memory vault invalid: ${PRIVATE_VAULT_ERROR:-unknown error}" \
        "Private memory vault root is configured but INVALID: ${PRIVATE_VAULT_ERROR:-unknown error}"
fi

# recall-readiness is a strictly stronger, separate signal from root validity
# above (see check_vault_recall_ready). Bounded at 15s -- measured 2026-08-16
# at ~0.2-0.4s against both an empty and a ~2000-note vault.
#
# CHRONO_VAULT_ROOT unset is ABSENT, not BROKEN -- same split the root check
# just above already draws (note_warn vs note_issue), and it matters here too:
# a fresh clone has no vault AND typically no venv yet, and gate-blocking
# (note_gate_unknown -> exit 2) on a vault nobody has configured would fail a
# clean first launch. Once CHRONO_VAULT_ROOT IS set, a missing venv or a
# failing probe means an operator-configured vault the check could not read,
# which stays gate-blocking below.
VAULT_HEALTH_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-vault-health.XXXXXXXX" 2>/dev/null)" \
    || VAULT_HEALTH_OUT=""
if [[ -z "${CHRONO_VAULT_ROOT:-}" ]]; then
    note_absent_input "vault recall-readiness has nothing to probe: CHRONO_VAULT_ROOT unset" \
        "chrono-vault has no configured root yet — recall-readiness was NOT measured (see the private memory vault line above)"
elif [[ ! -x "${CHRONO_PY}" ]]; then
    note_gate_unknown "vault recall-readiness could not run: ${CHRONO_PY} is missing or not executable" \
        "chrono-vault's Python venv (${CHRONO_PY}) is missing — recall-readiness is UNKNOWN"
elif [[ -z "${VAULT_HEALTH_OUT}" ]]; then
    note_unknown "vault recall-readiness probe had nowhere to write" \
        "no writable temp file for the chrono-vault health probe"
else
    vault_health_rc=0
    run_bounded 15 "${VAULT_HEALTH_OUT}" check_vault_recall_ready || vault_health_rc=$?
    VAULT_HEALTH_JSON="$(cat "${VAULT_HEALTH_OUT}" 2>/dev/null)"
    case "${vault_health_rc}" in
        0)
            note_ok "vault recall-ready" \
                "chrono-vault health: recall_ready=true (${VAULT_HEALTH_JSON:-no detail returned})"
            ;;
        1)
            note_issue "vault NOT recall-ready — run rebuild_index() (${VAULT_HEALTH_JSON:-no detail returned})" \
                "chrono-vault health reports recall_ready=false: ${VAULT_HEALTH_JSON:-no detail returned}. The usual cause is an index schema bump: \`recall\` refuses a stale index outright (\"index schema is stale; run rebuild_index\"), so every recall returns nothing until the projection is rebuilt. The index is a rebuildable projection and the markdown is truth, so the remedy is always safe: PYTHONPATH=plugins/chrono-vault python3 -c 'import index; index.rebuild_index()'. This happened live during Task 10 when INDEX_SCHEMA_VERSION went 3 -> 4 and nothing said so."
            ;;
        2)
            note_gate_unknown "vault recall-readiness probe raised an exception" \
                "chrono-vault health probe could not import or run: ${VAULT_HEALTH_JSON:-no detail returned}"
            ;;
        *)
            note_gate_unknown "vault recall-readiness probe timed out or crashed (exit ${vault_health_rc})" \
                "chrono-vault health probe did not complete within 15s: ${VAULT_HEALTH_JSON:-no detail returned}"
            ;;
    esac
fi
[[ -n "${VAULT_HEALTH_OUT}" ]] && rm -f "${VAULT_HEALTH_OUT}"

# Promotion throughput -- separate from recall-readiness above: that answers
# "can chrono-vault query at all", this answers "has the promotion handler
# fired recently". Same absent/gate split as the two vault checks above:
# CHRONO_VAULT_ROOT unset is what a machine that never configured a vault
# looks like (note_absent_input, non-gating); once a vault IS configured, an
# unreadable index is a gate-blocking unknown (note_gate_unknown), same as
# every other mandatory-integrity check in this file.
#
# A MEASURED zero is deliberately WARN, never ISSUE. A quiet promotion
# pipeline is not a broken installation -- most 30-day windows on a fresh
# vault are legitimately zero -- and ISSUE gates `squad up` exit 1
# (SQUAD_UNSAFE_AUTONOMY defaults to 1, so any non-zero doctor exit blocks
# the launcher). An earlier draft of a different check in this plan was
# specified at ISSUE level and blocked `squad up` until demoted; this one
# ships at WARN from the start.
DOCTOR_PROMOTION_WINDOW_DAYS=30
PROMOTION_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-promotion.XXXXXXXX" 2>/dev/null)" \
    || PROMOTION_OUT=""
if [[ -z "${CHRONO_VAULT_ROOT:-}" ]]; then
    note_absent_input "promotion throughput has nothing to probe: CHRONO_VAULT_ROOT unset" \
        "chrono-vault has no configured root yet — promotion throughput was NOT measured (see the private memory vault line above)"
elif [[ -z "${PROMOTION_OUT}" ]]; then
    note_unknown "promotion throughput probe had nowhere to write" \
        "no writable temp file for the promotion-throughput probe"
else
    promotion_rc=0
    run_bounded 15 "${PROMOTION_OUT}" check_promotion_throughput || promotion_rc=$?
    PROMOTION_JSON="$(cat "${PROMOTION_OUT}" 2>/dev/null)"
    case "${promotion_rc}" in
        0)
            note_ok "promotion throughput: the promotion handler fired within the last ${DOCTOR_PROMOTION_WINDOW_DAYS} days (${PROMOTION_JSON:-no detail returned})" \
                "chrono-vault promotion: at least one \`MEMORY-PROMOTION\` settlement event in the last ${DOCTOR_PROMOTION_WINDOW_DAYS} days (${PROMOTION_JSON:-no detail returned})"
            ;;
        1)
            note_warn "promotion throughput is ZERO over the last ${DOCTOR_PROMOTION_WINDOW_DAYS} days — the promotion handler is not firing" \
                "chrono-vault recorded ZERO \`MEMORY-PROMOTION\` settlement events in the last ${DOCTOR_PROMOTION_WINDOW_DAYS} days (${PROMOTION_JSON:-no detail returned}). Zero is expected only on a machine that settled no substantive review with an APPROVE verdict in the window -- it is NOT the normal reading for an active board, and it was permanently zero for the whole life of this feature because promotion joined on a citation key no production recall ever wrote. Check, in order: that reviews are being settled with \`--settle-review\` (\`grep -h REVIEW-SETTLED _state/chrono-queue.md _state/chrono-queue-handled.md\` -- settled lines are archived to the second file by bin/chrono-queue-backfill.sh, and this probe reads both); whether the handler ran but could not promote (\`grep -h MEMORY-PROMOTION- _state/chrono-queue*.md\` shows \`-SKIPPED\` for an unset \$CHRONO_VAULT_ROOT at settlement and \`-FAILED\` with the reason -- neither counts as a promotion, deliberately); and that \`usage\` has \`used\` rows for the settled tasks. \`stamped_notes\` in the JSON above counts notes carrying a \`verified_at\` stamp and is an UPPER BOUND that also includes hand-verified and recorded-straight-to-verified notes -- never read it as the handler firing. See scripts/python/memory_metrics.py:promotion_events."
            ;;
        2)
            note_gate_unknown "promotion throughput probe raised an exception" \
                "chrono-vault promotion-throughput probe could not import or run: ${PROMOTION_JSON:-no detail returned}"
            ;;
        *)
            note_gate_unknown "promotion throughput probe timed out or crashed (exit ${promotion_rc})" \
                "chrono-vault promotion-throughput probe did not complete within 15s: ${PROMOTION_JSON:-no detail returned}"
            ;;
    esac
fi
[[ -n "${PROMOTION_OUT}" ]] && rm -f "${PROMOTION_OUT}"

# Auto-capture write-path health -- the OTHER end of the loop from promotion.
# `autocapture.distill()` shells out to the `gemini` CLI, and a failure there
# means NO semantic note is written: the raw capture survives in the episodic
# tier, but memory stops growing. None of spec §11's four measurements moves,
# because they all describe notes that exist rather than notes never written.
#
# WARN, not ISSUE, for the same reason the promotion check is: a broken
# distillation lane is not a broken installation and must not gate `squad up`.
# No CHRONO_VAULT_ROOT dependency either -- the failure log is a repo artifact,
# and a machine with no vault configured simply has never captured anything.
DOCTOR_AUTOCAPTURE_WINDOW_DAYS=7
AUTOCAPTURE_FAIL_COUNT="$(
    PYTHONPATH="${VAULT_ROOT}/scripts/python" python3 -B -c '
import sys
from memory_metrics import autocapture_write_failures
print(autocapture_write_failures(sys.argv[1], days=int(sys.argv[2])))
' "${VAULT_ROOT}" "${DOCTOR_AUTOCAPTURE_WINDOW_DAYS}" 2>/dev/null
)" || AUTOCAPTURE_FAIL_COUNT=""
if [[ -z "${AUTOCAPTURE_FAIL_COUNT}" ]]; then
    note_unknown "auto-capture write-path probe could not run" \
        "memory_metrics.autocapture_write_failures could not be read; auto-capture health was NOT measured"
elif [[ "${AUTOCAPTURE_FAIL_COUNT}" == "0" ]]; then
    note_ok "auto-capture write path: no distillation failures in the last ${DOCTOR_AUTOCAPTURE_WINDOW_DAYS} days" \
        "chrono-vault auto-capture recorded no write-path failures in the last ${DOCTOR_AUTOCAPTURE_WINDOW_DAYS} days"
else
    note_warn "auto-capture wrote NO note ${AUTOCAPTURE_FAIL_COUNT}x in the last ${DOCTOR_AUTOCAPTURE_WINDOW_DAYS} days — the distillation lane may be down" \
        "chrono-vault auto-capture failed to write a semantic note ${AUTOCAPTURE_FAIL_COUNT} time(s) in the last ${DOCTOR_AUTOCAPTURE_WINDOW_DAYS} days. The raw captures are safe in _state/episodic/, but memory is not growing. Most likely an unauthenticated or unreachable \`gemini\` CLI — this repo has lost three weeks to exactly that before. Read the reasons in _state/autocapture-failures.jsonl; \`CHRONO_AUTOCAPTURE_DISTILL=off\` writes unstripped notes rather than none while the lane is fixed."
fi

# `[[ -w ]]` asks the permission bits a question the filesystem may not agree
# with: a read-only mount, a full disk, an immutable flag and an SIP-protected
# path all pass it and then refuse the write. Every runtime surface this program
# reports on is under this root, so "accessible" has to mean a write that
# actually happened. Dot-prefixed, PID-suffixed, and removed on the same line,
# in both the success and failure paths.
if [[ ! -d "${VAULT_ROOT}" ]]; then
    note_issue "runtime repository not accessible" \
        "Runtime repository is not a directory at ${VAULT_ROOT}"
elif [[ ! -w "${VAULT_ROOT}" ]]; then
    note_issue "runtime repository not writable" \
        "Runtime repository at ${VAULT_ROOT} is not writable"
else
    RUNTIME_WRITE_PROBE="${VAULT_ROOT}/.doctor-write-probe.$$"
    if : > "${RUNTIME_WRITE_PROBE}" 2>/dev/null && [[ -f "${RUNTIME_WRITE_PROBE}" ]]; then
        rm -f "${RUNTIME_WRITE_PROBE}"
        note_ok "runtime repository writable (probe wrote and removed a file)" \
            "Runtime repository accessible at ${VAULT_ROOT}: a probe file was created and removed, so this is a completed write and not a permission-bit reading"
    else
        rm -f "${RUNTIME_WRITE_PROBE}" 2>/dev/null
        note_issue "runtime repository refused a write despite passing the permission check" \
            "${VAULT_ROOT} is a directory whose permission bits allow writing, but creating a file there FAILED — a read-only mount, a full filesystem, or a protected path. Every runtime surface this program reports on is under this root."
    fi
fi

# --- 5. Browser session — LIVE CDP probe, plus the keep-alive summary for detail
echo "" >> "${DOCTOR_LOG}"
echo "## Browser Session" >> "${DOCTOR_LOG}"
BROWSER_SUMMARY="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-browser-summary.json"
# Until 2026-08-17 reachability was read out of `.reachable` in a file another
# process wrote, and this program never touched the port: `curl` did not appear
# in it once. A date-stamped filename was the only bound, so a summary written
# at 00:05 satisfied a 23:59 run -- "Chrome CDP reachable" about a browser that
# had been closed for twenty hours. Task 3 bounded the file's age, which stopped
# the false claim but could only downgrade it to UNKNOWN.
#
# One request settles it. GET /json/version is READ-ONLY: it opens no tab,
# closes none, and navigates nothing, which matters because this Chrome holds
# authenticated bounty sessions. /json/new and /json/close are never touched.
#
# The probe decides reachability; the summary keeps its job as the source of
# per-platform tab detail, which no single request can supply. When the two
# disagree, the summary is simply older -- said plainly rather than resolved
# silently in either direction.
#
# Doubly bounded: curl's own --max-time, inside run_bounded. A health check must
# never block on a socket, and a CDP port that accepts a connection and then
# stops talking is exactly the failure a --max-time alone has to catch.
CDP_PORT="${DOCTOR_CDP_PORT:-9222}"
CDP_HOST="${DOCTOR_CDP_HOST:-127.0.0.1}"
CDP_LIVE=unknown
CDP_BROWSER=""
if ! command -v curl >/dev/null 2>&1; then
    note_unknown "browser reachability could not be probed: curl is unavailable" \
        "curl is not on PATH, so the CDP endpoint at ${CDP_HOST}:${CDP_PORT} was NOT contacted — browser reachability is UNKNOWN"
else
    CDP_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-cdp.XXXXXXXX" 2>/dev/null)" || CDP_OUT=""
    if [[ -z "${CDP_OUT}" ]]; then
        note_unknown "browser reachability probe had nowhere to write" \
            "no writable temp file for the CDP probe — browser reachability is UNKNOWN"
    else
        cdp_rc=0
        run_bounded 6 "${CDP_OUT}" curl -s --max-time 3 \
            "http://${CDP_HOST}:${CDP_PORT}/json/version" || cdp_rc=$?
        if [[ "${cdp_rc}" -eq 0 ]] && grep -q '"Browser"' "${CDP_OUT}" 2>/dev/null; then
            CDP_LIVE=true
            if command -v jq >/dev/null 2>&1; then
                CDP_BROWSER="$(jq -r '.Browser // empty' "${CDP_OUT}" 2>/dev/null)"
            fi
            note_ok "Chrome CDP reachable at ${CDP_HOST}:${CDP_PORT} (${CDP_BROWSER:-build not reported})" \
                "Live probe: GET http://${CDP_HOST}:${CDP_PORT}/json/version answered — ${CDP_BROWSER:-build not reported}. Read-only; no tab was opened, closed or navigated."
        else
            CDP_LIVE=false
            note_warn "Chrome CDP not reachable at ${CDP_HOST}:${CDP_PORT} — bounty browser tools will not work" \
                "Live probe: GET http://${CDP_HOST}:${CDP_PORT}/json/version did not answer (exit ${cdp_rc}). Start Chrome with --remote-debugging-port=${CDP_PORT}, or run bin/browser-keep-alive.sh."
        fi
        rm -f "${CDP_OUT}"
    fi
fi

# bin/browser-keep-alive.sh runs from bin/run-nightly.sh, so the freshest
# possible per-platform detail is already hours old and the bound cannot be
# tight. Six hours keeps a morning launch reading the night's run as evidence
# and refuses to treat an all-day-old file as a statement about now.
BROWSER_SUMMARY_MAX_AGE="${DOCTOR_BROWSER_SUMMARY_MAX_AGE:-21600}"
BROWSER_SUMMARY_AGE=""
if [[ -f "${BROWSER_SUMMARY}" ]]; then
    _browser_mtime="$(stat -f %m "${BROWSER_SUMMARY}" 2>/dev/null \
        || stat -c %Y "${BROWSER_SUMMARY}" 2>/dev/null || true)"
    if [[ "${_browser_mtime}" =~ ^[0-9]+$ ]]; then
        BROWSER_SUMMARY_AGE=$(( $(date +%s) - _browser_mtime ))
    fi
    unset _browser_mtime
fi
if [[ ! -f "${BROWSER_SUMMARY}" ]]; then
    # Today's summary is written by browser-keep-alive.sh. Its absence means
    # that job has not run today -- always true of a fresh install, and
    # routinely true of a live one before the first keep-alive of the morning.
    # An unreadable or malformed summary stays gating below: that file existed
    # and doctor could not read it.
    note_absent_input "per-platform browser tab detail unavailable: no browser summary for today" \
        "no browser-keep-alive summary exists for ${DATE} — which bounty session tabs are open, expired or missing was NOT measured (reachability itself was probed live above)"
elif [[ -z "${BROWSER_SUMMARY_AGE}" ]]; then
    note_gate_unknown "browser summary age could not be read" \
        "${BROWSER_SUMMARY} exists but stat could not date it — whether its per-platform tab detail is current is UNKNOWN"
elif [[ "${BROWSER_SUMMARY_AGE}" -gt "${BROWSER_SUMMARY_MAX_AGE}" ]]; then
    note_unknown "browser tab detail is stale: the only evidence is ${BROWSER_SUMMARY_AGE}s old (limit ${BROWSER_SUMMARY_MAX_AGE}s)" \
        "${BROWSER_SUMMARY} was written ${BROWSER_SUMMARY_AGE}s ago, so its per-platform tab list describes ${BROWSER_SUMMARY_AGE}s ago, not now. Reachability itself was probed live above and does not depend on this file. Re-run bin/browser-keep-alive.sh for current tab detail."
elif ! command -v jq >/dev/null 2>&1; then
    note_gate_unknown "browser session detail could not be parsed: jq is unavailable"
elif ! jq -e '
    (type == "object") and
    ((.reachable | type) == "boolean") and
    (((.platforms_open // 0) | type) == "number") and
    (((.platforms_expired // []) | type) == "array") and
    (((.platforms_missing // []) | type) == "array")
' "${BROWSER_SUMMARY}" >/dev/null 2>&1; then
    note_gate_unknown "browser session detail could not be parsed: invalid summary schema" \
        "${BROWSER_SUMMARY} is unreadable or lacks the typed reachable/platform fields — per-platform tab detail is UNKNOWN"
else
    reachable=$(jq -r '.reachable // false' "${BROWSER_SUMMARY}")
    open=$(jq -r '.platforms_open // 0' "${BROWSER_SUMMARY}")
    expired=$(jq -r '.platforms_expired // [] | length' "${BROWSER_SUMMARY}")
    missing=$(jq -r '.platforms_missing // [] | length' "${BROWSER_SUMMARY}")
    note_info "Browser tab detail from ${BROWSER_SUMMARY##*/} (${BROWSER_SUMMARY_AGE}s old): ${open} session tab(s) open"
    # The summary's own reachability field is now DETAIL, not the verdict. When
    # it disagrees with the live probe the summary is simply older, and saying so
    # is more useful than silently preferring either one.
    if [[ "${CDP_LIVE}" != unknown ]] && [[ "${reachable}" != "${CDP_LIVE}" ]]; then
        note_info "  (the summary recorded reachable=${reachable}; the live probe just found ${CDP_LIVE} — the summary is ${BROWSER_SUMMARY_AGE}s old)"
    fi
    if [[ ${expired} -gt 0 ]]; then
        expired_names=$(jq -r '.platforms_expired // [] | join(", ")' "${BROWSER_SUMMARY}")
        note_warn "browser sessions expired: ${expired_names}" \
            "${expired} session tab(s) need refresh: ${expired_names}"
    fi
    if [[ ${missing} -gt 0 ]]; then
        missing_names=$(jq -r '.platforms_missing // [] | join(", ")' "${BROWSER_SUMMARY}")
        note_warn "browser expected tabs missing: ${missing_names}" \
            "${missing} expected tab(s) missing: ${missing_names}"
    fi
fi

# --- 6. Disk space ---
echo "" >> "${DOCTOR_LOG}"
echo "## Disk Space" >> "${DOCTOR_LOG}"
# A df that returns nothing used to leave disk_free_pct empty, which bash
# evaluates as 0 inside [[ -gt ]], so a FAILED MEASUREMENT fell straight through
# to "Disk: % free (CRITICAL)" -- an issue raised, with the number missing from
# its own sentence. Validate the figure before comparing it.
disk_free_pct=""
if command -v df >/dev/null 2>&1; then
    disk_free_pct=$(df -h "${HOME:-/}" 2>/dev/null \
        | awk 'NR==2 {gsub("%",""); print 100-$5}')
fi
if ! [[ "${disk_free_pct}" =~ ^-?[0-9]+$ ]]; then
    note_unknown "disk free space could not be measured" \
        "df returned no usable free-space figure for ${HOME:-/} — disk headroom is UNKNOWN"
elif [[ "${disk_free_pct}" -gt 15 ]]; then
    note_ok "disk OK" "Disk: ${disk_free_pct}% free"
elif [[ "${disk_free_pct}" -gt 5 ]]; then
    note_warn "disk at ${disk_free_pct}%" "Disk: ${disk_free_pct}% free (getting tight)"
else
    note_issue "disk critical at ${disk_free_pct}%" \
        "Disk: ${disk_free_pct}% free (CRITICAL)"
fi

# --- 7. tmux session + window composition ---
# The session COUNT used to be the whole check, and a count cannot see
# composition. The operator's outbox watcher fleet was dead for EIGHT DAYS
# behind a session that was present the entire time, and doctor said "tmux
# running: 1 session(s)" every morning; `list-windows` did not appear in this
# file once. What bin/launch-squad.sh builds is a session carrying a chrono
# window and a watchers window, so asserting those two BY NAME is the check that
# would have made those eight days visible on day one.
#
# The expected names come from shared/lead-windows.sh -- the same helper the
# launcher uses to CREATE them (WATCHERS_WIN="$(lead_window_name watchers)") --
# so doctor cannot drift into looking for a name the launcher stopped using. If
# that helper cannot be read the expected names are UNKNOWN, and so is the
# verdict; they are never assumed.
#
# Read-only throughout: `tmux ls`, `has-session` and `list-windows -F` only
# query. Matching is `grep -Fxq` on tmux's own window-name field, which is a
# whole-line comparison against a name tmux itself owns -- not a scan of any
# process's argv.
DOCTOR_TMUX_SESSION="${SQUAD_SESSION:-squad}"
echo "" >> "${DOCTOR_LOG}"
echo "## tmux Sessions" >> "${DOCTOR_LOG}"
if ! command -v tmux >/dev/null 2>&1; then
    note_warn "tmux not installed" "tmux not installed"
elif ! tmux ls >/dev/null 2>&1; then
    note_warn "tmux no sessions" "tmux installed but no sessions running"
else
    session_count=$(tmux list-sessions 2>/dev/null | wc -l | tr -d ' ')
    note_ok "tmux running" "tmux running: ${session_count} session(s)"

    WINDOW_LIST_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-windows.XXXXXXXX" 2>/dev/null)" \
        || WINDOW_LIST_OUT=""
    if [[ ! -r "${VAULT_ROOT}/shared/lead-windows.sh" ]]; then
        note_gate_unknown "expected tmux window names could not be resolved" \
            "shared/lead-windows.sh is unreadable, so the window names bin/launch-squad.sh creates are UNKNOWN — session composition was NOT checked"
    elif [[ -z "${WINDOW_LIST_OUT}" ]]; then
        note_unknown "tmux window composition probe had nowhere to write" \
            "no writable temp file for the tmux window listing"
    elif ! tmux has-session -t "${DOCTOR_TMUX_SESSION}" 2>/dev/null; then
        # Section 10 already warns that the squad session is not running; this
        # says the narrower thing, that its composition therefore went
        # unmeasured. Loud, never a pass, and never a launch blocker: the
        # launcher runs this gate BEFORE it creates the session.
        note_absent_input "squad session '${DOCTOR_TMUX_SESSION}' is not running, so its window composition was NOT checked" \
            "tmux has no '${DOCTOR_TMUX_SESSION}' session — the chrono and watchers windows were NOT looked for"
    else
        # shellcheck source-path=SCRIPTDIR source=../shared/lead-windows.sh disable=SC1091
        source "${VAULT_ROOT}/shared/lead-windows.sh"
        window_probe_rc=0
        run_bounded 10 "${WINDOW_LIST_OUT}" \
            tmux list-windows -t "${DOCTOR_TMUX_SESSION}" -F '#{window_name}' \
            || window_probe_rc=$?
        if [[ "${window_probe_rc}" -ne 0 ]] || [[ ! -s "${WINDOW_LIST_OUT}" ]]; then
            note_gate_unknown "tmux window composition could not be listed" \
                "the '${DOCTOR_TMUX_SESSION}' session exists but tmux list-windows returned nothing (exit ${window_probe_rc}) — its composition is UNKNOWN, not healthy"
        else
            for _expected_window in \
                "$(runtime_window_name chrono)" "$(lead_window_name watchers)"; do
                [[ -n "${_expected_window}" ]] || continue
                _window_hits=$(grep -Fxc -- "${_expected_window}" "${WINDOW_LIST_OUT}" \
                    | tr -d ' ')
                [[ "${_window_hits}" =~ ^[0-9]+$ ]] || _window_hits=0
                if [[ "${_window_hits}" -eq 1 ]]; then
                    note_ok "tmux window '${_expected_window}' present" \
                        "'${DOCTOR_TMUX_SESSION}' carries exactly one '${_expected_window}' window"
                elif [[ "${_window_hits}" -eq 0 ]]; then
                    note_issue "tmux window '${_expected_window}' is MISSING from session '${DOCTOR_TMUX_SESSION}'" \
                        "The '${DOCTOR_TMUX_SESSION}' session is running but carries no '${_expected_window}' window. The session being present is not the same as its work being alive — a watcher fleet dead for days sits behind exactly this. Windows found: $(tr '\n' ' ' < "${WINDOW_LIST_OUT}")"
                else
                    note_issue "tmux window '${_expected_window}' appears ${_window_hits} times — expected exactly one" \
                        "The '${DOCTOR_TMUX_SESSION}' session carries ${_window_hits} '${_expected_window}' windows. This name is a singleton by construction; duplicates mean two launches converged on one session. Windows found: $(tr '\n' ' ' < "${WINDOW_LIST_OUT}")"
                fi
            done
            unset _expected_window _window_hits
        fi
    fi
    [[ -n "${WINDOW_LIST_OUT}" ]] && rm -f "${WINDOW_LIST_OUT}"
fi

# --- 7b. Status poller singleton --------------------------------------------
# "Duplicate coordinators" was one of the four 2026-08-16 failures doctor did
# not detect, and it had no singleton detection anywhere. The status poller is
# the singleton this system already knows how to identify EXACTLY, so it is the
# one doctor asserts.
#
# NOT `pgrep -c`, and not any argv substring scan. A specialist's compiled
# prompt is its own argv -- 41,008 bytes measured on a live `codex exec` --
# containing this repository's filenames as ordinary prose, so a substring count
# of the process table counts prompts. That is not a hypothetical: it is how the
# operator's live watcher fleet was killed. Candidates come from the kernel's
# own `comm` (which no argv text can forge) and are confirmed by the exact
# positional predicate in shared/process-identity.sh -- the same function
# bin/launch-squad.sh uses to decide whether it may spawn one, so the launcher
# and the health check can never disagree about what a poller is.
echo "" >> "${DOCTOR_LOG}"
echo "## Status Poller" >> "${DOCTOR_LOG}"
VS_STATUS_DIR="${VIBESQUAD_STATUS_DIR:-/tmp}"
VS_POLLER_PIDFILE="${VS_STATUS_DIR}/vs-lane-status.pid"
LIVE_POLLER_PIDS=()
POLLER_COUNT_KNOWN=false
if [[ ! -r "${VAULT_ROOT}/shared/process-identity.sh" ]]; then
    note_gate_unknown "status poller count could not be established: shared/process-identity.sh is unreadable" \
        "without the exact-positional identity predicate there is no safe way to count pollers — the singleton assertion did NOT run"
elif [[ "${PS_USABLE}" != true ]]; then
    # Same lesson as the process audit below: a denied ps and a clean machine
    # produce the same empty list, and only one of them is evidence.
    note_unknown "status poller count could not be established: ${PS_DENIED_REASON}" \
        "the process table could not be read, so the number of live status pollers is UNKNOWN — not zero, and certainly not one"
else
    # shellcheck source-path=SCRIPTDIR source=../shared/process-identity.sh disable=SC1091
    source "${VAULT_ROOT}/shared/process-identity.sh"
    POLLER_SCAN_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-pollers.XXXXXXXX" 2>/dev/null)" \
        || POLLER_SCAN_OUT=""
    poller_scan_rc=0
    if [[ -z "${POLLER_SCAN_OUT}" ]]; then
        note_unknown "status poller scan had nowhere to write" \
            "no writable temp file for the status poller scan"
    else
        run_bounded 15 "${POLLER_SCAN_OUT}" find_live_vs_lane_status_pollers \
            || poller_scan_rc=$?
        if [[ "${poller_scan_rc}" -ne 0 ]]; then
            note_gate_unknown "status poller scan did not complete (exit ${poller_scan_rc})" \
                "the poller scan timed out or failed — the number of live status pollers is UNKNOWN"
        else
            while read -r _poller_pid; do
                [[ -n "${_poller_pid}" ]] && LIVE_POLLER_PIDS+=("${_poller_pid}")
            done < "${POLLER_SCAN_OUT}"
            unset _poller_pid
            POLLER_COUNT_KNOWN=true
        fi
        rm -f "${POLLER_SCAN_OUT}"
    fi

    if [[ "${POLLER_COUNT_KNOWN}" == true ]]; then
        # The pidfile is what `squad stop` reaps by, so a live poller it does
        # not name is a leak in waiting even when the count is right.
        POLLER_PIDFILE_PID=""
        if [[ -r "${VS_POLLER_PIDFILE}" ]]; then
            POLLER_PIDFILE_PID="$(tr -d '[:space:]' < "${VS_POLLER_PIDFILE}" 2>/dev/null)"
        fi
        case "${#LIVE_POLLER_PIDS[@]}" in
            1)
                note_ok "exactly one status poller running" \
                    "One live vs-lane-status.sh poller for this root (PID ${LIVE_POLLER_PIDS[0]})"
                if [[ "${POLLER_PIDFILE_PID}" != "${LIVE_POLLER_PIDS[0]}" ]]; then
                    note_warn "status poller ${LIVE_POLLER_PIDS[0]} is untracked — 'squad stop' will not reap it" \
                        "${VS_POLLER_PIDFILE} names '${POLLER_PIDFILE_PID:-nothing}' but the live poller is ${LIVE_POLLER_PIDS[0]}; the stopper reaps by pidfile, so this one would be orphaned"
                fi
                ;;
            0)
                if [[ -z "${POLLER_PIDFILE_PID}" ]]; then
                    # Nothing has ever recorded a poller here. That is every
                    # fresh clone, and it is not a fault.
                    note_absent_input "no status poller is running and none was ever recorded" \
                        "no live vs-lane-status.sh poller for this root, and ${VS_POLLER_PIDFILE} names none — the tmux status bar and pane borders have no writer"
                else
                    note_warn "status poller is dead: pidfile names ${POLLER_PIDFILE_PID}, which is not a live poller" \
                        "${VS_POLLER_PIDFILE} names PID ${POLLER_PIDFILE_PID} but no live process for this root passes the poller identity check — the status bar is frozen on whatever it last wrote"
                fi
                ;;
            *)
                note_warn "${#LIVE_POLLER_PIDS[@]} status pollers running — expected exactly 1 (PIDs: ${LIVE_POLLER_PIDS[*]})" \
                    "${#LIVE_POLLER_PIDS[@]} live vs-lane-status.sh pollers for this root: ${LIVE_POLLER_PIDS[*]}. Exactly one is expected; 'squad stop' reaps only the one ${VS_POLLER_PIDFILE} names (${POLLER_PIDFILE_PID:-none}), so the rest are orphans that survive every stop. Kill them by PID."
                ;;
        esac
    fi
fi

# --- 7c. Freshness of the status files the UI renders -----------------------
# `/tmp/vs-` appeared ZERO times in this file before 2026-08-17, and stale
# status files were one of the four failures doctor did not detect. Existence
# cannot detect them: a poller writing every second and a poller dead for seven
# days leave byte-identical files behind, and the tmux status bar renders the
# dead one exactly as confidently as the live one. Only AGE separates them.
#
# These are the files bin/launch-squad.sh wires into status-left, status-right
# and pane-border-format (vs-daemon, vs-swarm, vs-doctor, vs-lane-<window>), and
# bin/vs-lane-status.sh rewrites every one of them on every ~1s tick regardless
# of what it finds -- so age is a clean heartbeat rather than a measure of
# activity.
#
# The bound is VS_LANE_STATUS_FRESHNESS_MAX_AGE, the SAME env var and the same
# default bin/launch-squad.sh's vs_lane_status_poller_alive() uses to decide
# whether a poller is wedged. It is spelled out in both files because the
# launcher's copy lives inside a function doctor cannot source; the launcher is
# the origin, and test_doctor_runtime_liveness.py pins the two defaults equal so
# they cannot drift (CLAUDE.md rule 10).
#
# Both outcomes are WARN, never ISSUE: doctor is the LAUNCH gate and runs before
# the launcher starts the poller, so stale files are the ordinary state of a
# cold machine that is one second away from being fixed. What matters is that
# they are named and aged, not that they block.
echo "" >> "${DOCTOR_LOG}"
echo "## Status File Freshness" >> "${DOCTOR_LOG}"
STATUS_FILE_MAX_AGE="${VS_LANE_STATUS_FRESHNESS_MAX_AGE:-10}"
STATUS_FILES=()
for _status_file in "${VS_STATUS_DIR}"/vs-*.status; do
    [[ -f "${_status_file}" ]] && STATUS_FILES+=("${_status_file}")
done
unset _status_file
if [[ "${#STATUS_FILES[@]}" -eq 0 ]]; then
    note_absent_input "no status files exist yet in ${VS_STATUS_DIR}" \
        "nothing has ever written ${VS_STATUS_DIR}/vs-*.status — the status bar has no input, which is what an installation that has not launched looks like"
else
    STALE_STATUS_FILES=()
    STATUS_AGE_UNREADABLE=()
    OLDEST_STATUS_AGE=0
    _status_now="$(date +%s)"
    for _status_file in "${STATUS_FILES[@]}"; do
        _status_mtime="$(stat -f %m "${_status_file}" 2>/dev/null \
            || stat -c %Y "${_status_file}" 2>/dev/null || true)"
        if ! [[ "${_status_mtime}" =~ ^[0-9]+$ ]]; then
            STATUS_AGE_UNREADABLE+=("$(basename -- "${_status_file}")")
            continue
        fi
        _status_age=$(( _status_now - _status_mtime ))
        if [[ "${_status_age}" -gt "${STATUS_FILE_MAX_AGE}" ]]; then
            STALE_STATUS_FILES+=("$(basename -- "${_status_file}") (${_status_age}s)")
            [[ "${_status_age}" -gt "${OLDEST_STATUS_AGE}" ]] \
                && OLDEST_STATUS_AGE="${_status_age}"
        fi
    done
    unset _status_file _status_mtime _status_age _status_now

    if [[ "${#STATUS_AGE_UNREADABLE[@]}" -gt 0 ]]; then
        # The files are right here and their age could not be read: that is an
        # input present and unreadable, which is the exit-2 case.
        note_gate_unknown "status file age could not be read for ${#STATUS_AGE_UNREADABLE[@]} file(s)" \
            "stat could not date ${STATUS_AGE_UNREADABLE[*]} — whether the status bar is rendering live or stale values is UNKNOWN"
    fi
    if [[ "${#STALE_STATUS_FILES[@]}" -eq 0 ]]; then
        note_ok "all ${#STATUS_FILES[@]} status files fresh" \
            "Every ${VS_STATUS_DIR}/vs-*.status file was written within ${STATUS_FILE_MAX_AGE}s (${#STATUS_FILES[@]} file(s))"
    elif [[ "${POLLER_COUNT_KNOWN}" == true && "${#LIVE_POLLER_PIDS[@]}" -gt 0 ]]; then
        # A live writer with dead output is the worst of the three states: every
        # liveness check says "running" while the status bar is frozen.
        note_warn "status poller is alive but its output is stale (oldest ${OLDEST_STATUS_AGE}s, limit ${STATUS_FILE_MAX_AGE}s)" \
            "A live poller (PID ${LIVE_POLLER_PIDS[0]}) has not refreshed ${#STALE_STATUS_FILES[@]} of ${#STATUS_FILES[@]} status file(s): ${STALE_STATUS_FILES[*]}. The status bar is rendering values nothing is updating while every PID check says the poller is running."
    else
        note_warn "${#STALE_STATUS_FILES[@]} stale status file(s) with no live writer (oldest ${OLDEST_STATUS_AGE}s)" \
            "${#STALE_STATUS_FILES[@]} of ${#STATUS_FILES[@]} ${VS_STATUS_DIR}/vs-*.status file(s) are older than ${STATUS_FILE_MAX_AGE}s and no live poller is writing them: ${STALE_STATUS_FILES[*]}. The tmux status bar renders these verbatim, so it is showing state from a poller that is gone."
    fi
fi

# --- 8. Token usage proxy (squad-driven LLM artifact volume) ---
# We don't have direct token counters per CLI, but we know the squad's own
# scripts produce one artifact per LLM call. Counting today's vs the trailing
# 7-day average gives an anomaly signal.
echo "" >> "${DOCTOR_LOG}"
echo "## Token Usage (proxy via artifact count)" >> "${DOCTOR_LOG}"
ARTIFACT_DIRS=()
for sub in blog-summaries podcast-briefs dream-logs; do
    [[ -d "${VAULT_ROOT}/_state/${sub}" ]] && ARTIFACT_DIRS+=("${VAULT_ROOT}/_state/${sub}")
done
if [[ "${#ARTIFACT_DIRS[@]}" -eq 0 ]]; then
    # An absent target set is not evidence of a clean artifact volume, but it
    # is normal before any artifact producer has run. Keep it loud and separate
    # from a present target that find could not enumerate.
    note_absent_input "token-bleed artifact scan has no source directories" \
        "none of _state/{blog-summaries,podcast-briefs,dream-logs} exists — artifact volume was NOT measured"
else
    artifact_scan_rc=0
    TODAY_ARTIFACTS=$(find "${ARTIFACT_DIRS[@]}" -name "${DATE}-*" -type f 2>/dev/null \
        | wc -l | tr -d ' ') || artifact_scan_rc=$?
    WEEKLY_ARTIFACTS=$(find "${ARTIFACT_DIRS[@]}" -name '*.md' -mtime -7 -type f 2>/dev/null \
        | wc -l | tr -d ' ') || artifact_scan_rc=$?
    if [[ "${artifact_scan_rc}" -ne 0 \
        || ! "${TODAY_ARTIFACTS}" =~ ^[0-9]+$ \
        || ! "${WEEKLY_ARTIFACTS}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "token-bleed artifact scan failed" \
            "find could not enumerate the artifact sources — artifact volume is UNKNOWN"
    else
        WEEKLY_AVG=$(( WEEKLY_ARTIFACTS / 7 ))
        note_info "Today: ${TODAY_ARTIFACTS} artifacts"
        note_info "7d total: ${WEEKLY_ARTIFACTS} (avg/day: ${WEEKLY_AVG})"
        # Flag if today is 3x the weekly average AND average isn't trivial.
        if [[ ${WEEKLY_AVG} -ge 3 ]] && [[ ${TODAY_ARTIFACTS} -gt $((WEEKLY_AVG * 3)) ]]; then
            note_issue "token-bleed suspect: today=${TODAY_ARTIFACTS} vs weekly_avg=${WEEKLY_AVG}" \
                "Anomaly: today's volume is >3x weekly average — possible token-bleed"
        else
            note_ok "token-bleed artifact volume within threshold" \
                "Artifact volume is within threshold (today=${TODAY_ARTIFACTS}, weekly_avg=${WEEKLY_AVG})"
        fi
    fi
fi

# Primary token-spend signal: dispatch count from dispatch-log.jsonl (last 24h).
# Catches retry loops with single-artifact output (which the artifact-count
# proxy above misses). This is a high-water-mark check, not a cost breakdown --
# the per-pane report that once complemented it belonged to the retired
# persistent-lane architecture and was removed with it.
if [[ ! -f "${VAULT_ROOT}/_state/dispatch-log.jsonl" ]]; then
    # No ledger is not a measured zero. A present empty ledger is the clean
    # control; an absent ledger is the loud, non-gating zero-state. A present
    # ledger that cannot be parsed remains gate-blocking below.
    note_absent_input "dispatch-log token-spend scan has no input" \
        "_state/dispatch-log.jsonl is absent — dispatch volume was NOT measured"
elif ! command -v jq >/dev/null 2>&1; then
    note_gate_unknown "dispatch-log token-spend scan could not parse input: jq is unavailable"
else
    yesterday_iso=$(date -u -v-1d +%FT%TZ 2>/dev/null \
        || date -u -d '1 day ago' +%FT%TZ 2>/dev/null || true)
    dispatch_scan_rc=0
    DISPATCHES_LAST_24H=$(jq -r --arg t "$yesterday_iso" \
        'if (type == "object") and ((.ts | type) == "string")
         then select(.ts > $t) | (.model_lane // .to_model // "?")
         else error("dispatch row lacks a string ts")
         end' \
        "${VAULT_ROOT}/_state/dispatch-log.jsonl" 2>/dev/null \
        | wc -l | tr -d ' ') || dispatch_scan_rc=$?
    if [[ -z "${yesterday_iso}" || "${dispatch_scan_rc}" -ne 0 \
        || ! "${DISPATCHES_LAST_24H}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "dispatch-log token-spend scan failed" \
            "the 24-hour cutoff or dispatch log could not be parsed — dispatch volume is UNKNOWN"
    elif [[ ${DISPATCHES_LAST_24H} -gt 200 ]]; then
        note_issue "dispatch volume ${DISPATCHES_LAST_24H} exceeds 200/24h baseline" \
            "High dispatch volume (>200/day) — possible runaway loop"
    else
        note_ok "dispatch volume within threshold" \
            "Total dispatches last 24h: ${DISPATCHES_LAST_24H} (threshold: 200)"
    fi
fi

# --- 9. Specialist dispatch volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Dispatch Activity (last 24h)" >> "${DOCTOR_LOG}"
ARCHIVE_DIRS=()
INBOX_DIRS=()
for dir in "${VAULT_ROOT}/departments"/*/archive; do
    [[ -d "${dir}" ]] && ARCHIVE_DIRS+=("${dir}")
done
for dir in "${VAULT_ROOT}/departments"/*/inbox; do
    [[ -d "${dir}" ]] && INBOX_DIRS+=("${dir}")
done
if [[ "${#ARCHIVE_DIRS[@]}" -eq 0 ]]; then
    note_absent_input "dispatch completion scan has no archive targets" \
        "found no departments/*/archive directory — completed dispatch activity is UNKNOWN"
else
    archive_scan_rc=0
    DISPATCHES_24H=$(find "${ARCHIVE_DIRS[@]}" -name 'TASK-*-response.md' -mtime -1 -type f 2>/dev/null \
        | wc -l | tr -d ' ') || archive_scan_rc=$?
    if [[ "${archive_scan_rc}" -ne 0 || ! "${DISPATCHES_24H}" =~ ^[0-9]+$ ]]; then
        note_gate_unknown "dispatch completion scan failed" \
            "find could not enumerate archive targets — completed dispatch activity is UNKNOWN"
    else
        note_info "Tasks completed (last 24h): ${DISPATCHES_24H}"
    fi
fi

# Count backlog independently. Before the first completed task there can be an
# inbox but no archive; coupling the two target sets made exactly that backlog
# invisible. A missing inbox is still indeterminate, not a measured zero, but
# is normal before the first launch creates mailbox state.
#
# DEPTH IS NOT THE SIGNAL; AGE IS. Until 2026-08-17 the whole check was
# `INBOX_BACKLOG -gt 10 -> note_issue "model leads may be stuck"`, which cannot
# tell eleven packets queued thirty seconds ago from eleven queued since
# Tuesday. Both readings were wrong in the same direction:
#
#   * A burst of eleven fresh dispatches is NORMAL -- send-task.sh publishes to
#     the inbox and immediately launches the CLI that will answer -- and the
#     depth gate called that a broken installation and exited 1.
#   * Ten packets rotting for eleven days scored 10 and PASSED. Measured on the
#     maintainer's tree 2026-08-17: exactly that state, reported "inbox backlog
#     within threshold".
#
# Nothing drains an inbox on a timer. There is no inbox watcher any more
# (bin/launch-squad.sh:282 records its retirement); a packet leaves the inbox
# only when bin/outbox-watcher.sh sees the RESPONSE its dispatched CLI wrote. So
# a packet older than a few days is not "queued", it is a dispatch whose CLI
# died without answering, and no amount of waiting will move it.
#
# AN INBOX COPY IS NOT PROOF THE TASK IS UNDONE. The first version of this check
# measured age over every file in every inbox, and the oldest of them --
# therefore the headline finding -- was a packet that had been COMPLETED and
# ARCHIVED, whose inbox copy is residue. On the maintainer's tree the archived
# copy was even in a different namespace (shared/inbox, security/archive), so the
# only reliable test is the packet's BASENAME against every departments/*/archive
# directory. Measured 2026-08-17: 10 inbox files, 1 residue, 9 genuinely
# unacknowledged. Residue is real cleanup and gets its own finding; calling it an
# abandoned dispatch was simply false.
#
# EVERY OUTCOME HERE IS A WARNING, and the reasoning is worth keeping because the
# first version got it wrong. SQUAD_UNSAFE_AUTONOMY defaults to 1
# (bin/launch-squad.sh:258, bin/squad:107), so a normal `squad up` runs this gate
# and ANY non-zero exit blocks the launch. An unacknowledged work item is QUEUE
# STATE, not installation breakage -- and this program's own issue vocabulary
# reads "measured breakage (exit 1) ... this installation is broken; fix them
# before launching". A stale inbox does not make the installation broken.
#
# There is deliberately NO age at which this escalates to ISSUE. Queue depth and
# install health are different axes, so no threshold on one can establish the
# other: a ninety-day-old packet is a bigger cleanup job than a four-day-old one,
# not a broken installation. Blocking would also invert the remedy, because
# doctor gates the very launch the operator would use to work the queue.
if [[ "${#INBOX_DIRS[@]}" -eq 0 ]]; then
    note_absent_input "inbox backlog scan has no inbox targets" \
        "found no departments/*/inbox directory — inbox backlog is UNKNOWN"
else
    INBOX_DEPTH_LIMIT="${DOCTOR_INBOX_DEPTH_LIMIT:-10}"
    INBOX_MAX_AGE_DAYS="${DOCTOR_INBOX_MAX_AGE_DAYS:-3}"
    INBOX_MAX_AGE_SECONDS=$(( INBOX_MAX_AGE_DAYS * 86400 ))
    # One glob per inbox packet, rather than enumerating the archive: there are
    # 1,089 archived packets on the maintainer's tree and ten in the inboxes.
    # An unmatched glob with no wildcard survives as its own literal text, which
    # `-e` then correctly reports absent -- no nullglob needed, and none assumed.
    inbox_packet_is_archived() {
        local base="$1" candidate
        for candidate in "${VAULT_ROOT}"/departments/*/archive/"${base}"; do
            [[ -e "${candidate}" ]] && return 0
        done
        return 1
    }
    # find's exit status is read in THIS shell, so the listing goes through a
    # temp file rather than a process substitution: `rc=1` assigned inside
    # `< <(...)` is assigned in a subshell and never reaches the branch below,
    # which would leave the scan-failed case permanently unreachable.
    inbox_scan_rc=0
    INBOX_UNACKED=()
    INBOX_RESIDUE=()
    INBOX_LIST="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-inbox.XXXXXXXX" 2>/dev/null)" \
        || INBOX_LIST=""
    if [[ -z "${INBOX_LIST}" ]]; then
        inbox_scan_rc=1
    else
        find "${INBOX_DIRS[@]}" -name 'TASK-*.md' -type f > "${INBOX_LIST}" 2>/dev/null \
            || inbox_scan_rc=$?
        while IFS= read -r _inbox_file; do
            [[ -n "${_inbox_file}" ]] || continue
            _inbox_base="$(basename -- "${_inbox_file}")"
            if inbox_packet_is_archived "${_inbox_base}"; then
                INBOX_RESIDUE+=("${_inbox_base}")
            else
                INBOX_UNACKED+=("${_inbox_file}")
            fi
        done < "${INBOX_LIST}"
        unset _inbox_file _inbox_base
        rm -f "${INBOX_LIST}"
    fi
    INBOX_BACKLOG="${#INBOX_UNACKED[@]}"
    INBOX_RESIDUE_NOTE=""
    [[ "${#INBOX_RESIDUE[@]}" -eq 0 ]] \
        || INBOX_RESIDUE_NOTE=" (${#INBOX_RESIDUE[@]} archived residue file(s) excluded)"
    # BSD and GNU stat spell mtime differently and neither accepts the other's
    # spelling. Probe once on a path that certainly exists rather than running
    # both and merging their output: a failed GNU `stat -f` still prints
    # filesystem rows, which would sort in among the timestamps.
    INBOX_STAT_FMT=()
    if stat -f '%m' "${VAULT_ROOT}" >/dev/null 2>&1; then
        INBOX_STAT_FMT=(-f '%m %N')
    elif stat -c '%Y' "${VAULT_ROOT}" >/dev/null 2>&1; then
        INBOX_STAT_FMT=(-c '%Y %n')
    fi
    INBOX_OLDEST_ROW=""
    if [[ "${INBOX_BACKLOG}" -gt 0 ]] && [[ "${#INBOX_STAT_FMT[@]}" -gt 0 ]]; then
        INBOX_OLDEST_ROW="$(stat "${INBOX_STAT_FMT[@]}" "${INBOX_UNACKED[@]}" \
            2>/dev/null | sort -n | head -1)"
    fi
    INBOX_OLDEST_MTIME="${INBOX_OLDEST_ROW%% *}"
    INBOX_OLDEST_PATH="${INBOX_OLDEST_ROW#* }"

    # Residue is reported whatever the abandonment measure concludes: it is a
    # separate fact about a separate directory, and it is what made the old
    # measure lie.
    if [[ "${#INBOX_RESIDUE[@]}" -gt 0 ]]; then
        note_warn "${#INBOX_RESIDUE[@]} handled task(s) still have an inbox copy: ${INBOX_RESIDUE[*]}" \
            "${#INBOX_RESIDUE[@]} inbox packet(s) have a completed copy under departments/*/archive/, so the work is done and the inbox file is residue: ${INBOX_RESIDUE[*]}. It is cleanup, not a lost dispatch — but until it is removed it inflates the backlog and can be the oldest thing in it. Fix: remove the inbox copy."
    fi

    if [[ "${inbox_scan_rc}" -ne 0 ]]; then
        # Non-gating, like every other outcome of this check: an unmeasured
        # queue must not block a launch harder than a measured one would.
        note_unknown "inbox backlog scan failed" \
            "find could not enumerate inbox targets — inbox backlog is UNKNOWN"
    elif [[ "${INBOX_BACKLOG}" -eq 0 ]]; then
        note_ok "no unacknowledged inbox task(s)" \
            "Inbox backlog: 0 unacknowledged task(s)${INBOX_RESIDUE_NOTE}"
    elif [[ ! "${INBOX_OLDEST_MTIME}" =~ ^[0-9]+$ ]]; then
        note_unknown "inbox backlog age could not be measured" \
            "${INBOX_BACKLOG} unacknowledged inbox packet(s) exist but stat could not date them — whether any dispatch has been waiting past its limit is UNKNOWN, which is not the same as within it"
    else
        INBOX_OLDEST_AGE=$(( $(date +%s) - INBOX_OLDEST_MTIME ))
        INBOX_OLDEST_DAYS=$(( INBOX_OLDEST_AGE / 86400 ))
        INBOX_FINDINGS=0
        if [[ "${INBOX_OLDEST_AGE}" -gt "${INBOX_MAX_AGE_SECONDS}" ]]; then
            INBOX_FINDINGS=1
            note_warn "abandoned dispatch: $(basename -- "${INBOX_OLDEST_PATH}") has waited ${INBOX_OLDEST_DAYS}d unacknowledged (limit ${INBOX_MAX_AGE_DAYS}d)" \
                "Oldest unacknowledged inbox packet is ${INBOX_OLDEST_DAYS}d old: ${INBOX_OLDEST_PATH#"${VAULT_ROOT}/"}. It has no copy under any departments/*/archive/, so it was never completed. Nothing drains an inbox on a timer — a packet leaves only when bin/outbox-watcher.sh sees the response its CLI wrote — so this dispatch is not queued, it was lost. ${INBOX_BACKLOG} unacknowledged packet(s) in total. Fix: re-dispatch it with bin/send-task.sh, or move it to the namespace's archive/ if it is dead."
        fi
        if [[ "${INBOX_BACKLOG}" -gt "${INBOX_DEPTH_LIMIT}" ]]; then
            INBOX_FINDINGS=1
            note_warn "inbox backlog: ${INBOX_BACKLOG} unacknowledged task(s) (depth limit ${INBOX_DEPTH_LIMIT})" \
                "Inbox backlog is ${INBOX_BACKLOG}, over the depth limit of ${INBOX_DEPTH_LIMIT}. Depth alone is not evidence of a fault — a wide fan-out looks exactly like this — so this reports the number and claims no cause; the oldest packet's age above is the finding with a diagnosis attached."
        fi
        if [[ "${INBOX_FINDINGS}" -eq 0 ]]; then
            note_ok "inbox backlog within depth and age limits" \
                "Inbox backlog: ${INBOX_BACKLOG} unacknowledged (depth limit ${INBOX_DEPTH_LIMIT}); oldest packet ${INBOX_OLDEST_AGE}s old (age limit ${INBOX_MAX_AGE_SECONDS}s)"
        fi
    fi
fi

# --- 9b. Notification spine liveness ----------------------------------------
# The queue records what needs Chrono's attention; the receipts record what was
# actually delivered to the chrono pane. When a delivery the spine OWED does not
# arrive, work parks and nothing else in this program notices: the queue keeps
# growing, every process looks alive. That is the state that left 165 tasks
# waiting and that Plan A repaired.
#
# What counts as owed -- and why an entry without a receipt is usually correct
# -- is settled in check_notification_spine() above, which imports the
# reconciler's own gates rather than restating them.
#
# WARN, not ISSUE. The one way a genuinely owed nudge goes undelivered on a
# healthy installation is the chrono window being unavailable when it lands
# (nudge_chrono returns False without writing a receipt). The queue is the
# durable recovery record for exactly that -- Chrono reads it at resume -- so
# this is degraded-and-recoverable, not a broken install. It is also the state a
# machine is in after any downtime, and doctor gates the very launch that ends
# it: exiting 1 here would block the fix.
echo "" >> "${DOCTOR_LOG}"
echo "## Notification Spine" >> "${DOCTOR_LOG}"
CHRONO_QUEUE_FILE="${VAULT_ROOT}/_state/chrono-queue.md"
CHRONO_RECEIPTS_DIR="${VAULT_ROOT}/_state/chrono-notify-receipts"
SPINE_WINDOW_HOURS="${DOCTOR_SPINE_WINDOW_HOURS:-24}"
SPINE_PY="$(command -v python3 2>/dev/null || true)"
if [[ ! -f "${CHRONO_QUEUE_FILE}" ]]; then
    note_absent_input "notification spine has no queue to reconcile" \
        "_state/chrono-queue.md does not exist — nothing has been queued for Chrono, so spine delivery was NOT measured"
elif [[ ! -d "${CHRONO_RECEIPTS_DIR}" ]]; then
    note_absent_input "notification spine has never written a receipt" \
        "_state/chrono-notify-receipts/ does not exist — no nudge has ever been delivered, which is the state of an installation whose watchers have not run"
elif [[ "$(classify_dependency 'scripts/python/registry_reconciler.py')" == unpublished ]]; then
    # The reconciler owns the definition of an owed delivery. A projection that
    # does not carry it cannot answer this question, and must not guess.
    note_skip "notification spine reconciliation needs scripts/python/registry_reconciler.py, which this distribution does not carry" \
        "Spine reconciliation does not apply here: the rules for which queue entries owe a receipt live in the reconciler, which is not part of this projection"
elif [[ ! -f "${VAULT_ROOT}/scripts/python/registry_reconciler.py" ]]; then
    note_gate_unknown "notification spine reconciliation could not run: scripts/python/registry_reconciler.py is missing" \
        "the reconciler defines which queue entries owe a receipt and is absent — whether the spine is delivering is UNKNOWN"
elif [[ -z "${SPINE_PY}" ]]; then
    note_gate_unknown "notification spine reconciliation could not run: python3 is unavailable"
else
    SPINE_OUT="$(mktemp "${TMPDIR:-/tmp}/vs-doctor-spine.XXXXXXXX" 2>/dev/null)" \
        || SPINE_OUT=""
    spine_rc=0
    if [[ -z "${SPINE_OUT}" ]]; then
        note_unknown "notification spine probe had nowhere to write" \
            "no writable temp file for the spine reconciliation"
    else
        run_bounded 20 "${SPINE_OUT}" \
            check_notification_spine "${SPINE_PY}" "${SPINE_WINDOW_HOURS}" \
            || spine_rc=$?
        SPINE_HEAD="$(head -1 "${SPINE_OUT}" 2>/dev/null)"
        SPINE_OWED=""
        SPINE_MISSING=""
        if [[ "${SPINE_HEAD}" =~ ^owed=([0-9]+)[[:space:]]missing=([0-9]+)$ ]]; then
            SPINE_OWED="${BASH_REMATCH[1]}"
            SPINE_MISSING="${BASH_REMATCH[2]}"
        fi
        if [[ "${spine_rc}" -ne 0 || -z "${SPINE_OWED}" ]]; then
            note_gate_unknown "notification spine reconciliation did not complete" \
                "the reconciliation exited ${spine_rc} and its first line was '${SPINE_HEAD:-nothing}' — whether owed nudges were delivered is UNKNOWN"
        elif [[ "${SPINE_OWED}" -eq 0 ]]; then
            # Nothing was owed in the window, so nothing was proven. Loud, never
            # a pass. This is the ordinary state of a quiet day and MUST NOT read
            # as divergence: for most queue entries, having no receipt is correct.
            note_absent_input "notification spine owed no delivery in the last ${SPINE_WINDOW_HOURS}h" \
                "No chrono-queue entry in the last ${SPINE_WINDOW_HOURS}h both belonged to a canonically-registered task and was outside the long-running channel, so no nudge was owed and spine delivery was NOT exercised"
        elif [[ "${SPINE_MISSING}" -eq 0 ]]; then
            note_ok "notification spine delivered all ${SPINE_OWED} owed nudge(s)" \
                "Every one of the ${SPINE_OWED} chrono-queue entries that owed a delivered nudge in the last ${SPINE_WINDOW_HOURS}h has its receipt"
        else
            SPINE_EXAMPLES="$(tail -n +2 "${SPINE_OUT}" 2>/dev/null | tr '\n' ';')"
            note_warn "notification spine: ${SPINE_MISSING} of ${SPINE_OWED} owed nudge(s) never delivered in the last ${SPINE_WINDOW_HOURS}h" \
                "${SPINE_MISSING} of ${SPINE_OWED} chrono-queue entries that owed a delivered nudge have no receipt: ${SPINE_EXAMPLES:-none listed}. These are canonically-registered tasks, so registry_reconciler.emit_event() did call nudge_chrono for them and no receipt was written — the chrono pane was unreachable, or the spine is severed. The queue is the durable recovery record; Chrono picks these up at resume. Check that the watchers window is running bin/outbox-watcher.sh."
            unset SPINE_EXAMPLES
        fi
        rm -f "${SPINE_OUT}"
    fi
fi

# --- 10. Process audit (with pathology detection) ---
echo "" >> "${DOCTOR_LOG}"
echo "## Process Audit" >> "${DOCTOR_LOG}"
SQUAD_PIDS=""
if command -v tmux >/dev/null 2>&1 && tmux has-session -t squad 2>/dev/null; then
    SQUAD_PIDS=$(tmux list-panes -a -F '#{pane_pid}' 2>/dev/null | tr '\n' ' ')
    note_ok "squad tmux session present" \
        "squad tmux session is running with pane roots: ${SQUAD_PIDS}"
else
    note_warn "squad tmux session not running" "squad tmux session is not running"
fi

# THE defect this whole vocabulary exists for. On 2026-08-11 a rehearsal fed
# these three checks a ps that answered `/bin/ps: Operation not permitted` every
# time, and doctor printed "No long-running CLI processes detected" -- and
# dropped the "extra non-squad CLI roots" warning the working run had raised, so
# the machine it could not see looked HEALTHIER than the machine it could.
#
# The fix is not to make ps work. It is that a check which could not run must be
# distinguishable from one that passed. PS_USABLE is established by a positive
# control at the top of this file: ps must name this very process.
if [[ "${PS_USABLE}" != true ]]; then
    note_unknown "process audit could not run: ${PS_DENIED_REASON}" \
        "Process audit COULD NOT RUN — ${PS_DENIED_REASON}. Long-running CLI processes, extra non-squad CLI roots, and runaway-CPU processes are ALL UNDETERMINED. None of them were found absent; none of them were looked for."
else
    # Long-running claude/codex/gemini/kimi processes are expected for the daily
    # driver, but extra interactive CLIs outside the squad pane roots can leave
    # MCP children around. Report them separately; never kill them here.
    long_procs=$(ps -eo pid,ppid,etime,pcpu,comm | awk '$5 ~ /(claude|codex|gemini|kimi)/ && $3 ~ /^[0-9]+-[0-9]+/ {print}' | head -10)
    if [[ -n "${long_procs}" ]]; then
        note_info "Long-running CLI processes (>1 day; may be active non-squad sessions):"
        echo "${long_procs}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
        HEALTHY+=("persistent CLI processes present")
    else
        note_ok "no long-running CLI processes" "No long-running CLI processes detected"
    fi

    # WHY THIS CHANGED (2026-08-17). The old check matched
    # /(claude|codex|gemini|kimi)( |$)/ against the WHOLE command line: exactly
    # the unanchored argv substring matching shared/process-identity.sh exists
    # to forbid, and it produced the failure that file predicts. Measured on the
    # maintainer's tree, its four "extra non-squad CLI sessions" were three
    # bin/send-task.sh processes that merely had a lane name somewhere in their
    # arguments, plus the operator's own attached terminal. Nothing was wrong.
    #
    # The finding was unactionable in SHAPE as well as content: the console line
    # named no PID and no count, while its own log line said "informational; may
    # be active terminals". It fired on every day the operator had a terminal
    # open, which is every day, and the brief for this task cites it as the model
    # of a bad warning.
    #
    # It is split into the two claims it conflated, rather than deleted:
    #
    #   ORPHANED (ppid 1) -- a lane CLI whose parent is gone. Nothing reaps it:
    #     `squad stop` knows only the pane roots, so it holds its MCP children
    #     and its context until someone kills it BY PID. That is a real leak, and
    #     it is reported in the shape the poller warning already uses -- name the
    #     PID, name the consequence. Measured on the maintainer's tree: one
    #     `codex exec` orphan, up 7 days, that the old check reported in a line
    #     naming neither it nor anything else.
    #   ATTACHED (any other parent) -- an interactive session the operator is
    #     using. Not a finding. Stays in the log as info.
    #
    # Matching is POSITIONAL: argv[0], and argv[1] when argv[0] is an interpreter
    # (codex ships as `node /opt/homebrew/bin/codex`, so its kernel comm is
    # `node`). A 41KB prompt in argv[2..n] cannot match. Two known limits, both
    # of which can only cause a MISS, never a false report: argv[0] is weaker
    # identity than `ps -o comm=` -- accepted here because the consequence is a
    # printed warning, not a kill, and reading comm per candidate would cost one
    # extra ps per interpreter process (39 on this host) -- and an executable
    # path containing a space splits into two fields.
    ORPHANED_CLIS=()
    ATTACHED_CLIS=()
    while IFS= read -r _cli_row; do
        [[ -n "${_cli_row}" ]] || continue
        if [[ "${_cli_row}" == orphan* ]]; then
            ORPHANED_CLIS+=("${_cli_row#orphan }")
        else
            ATTACHED_CLIS+=("${_cli_row#attached }")
        fi
    done < <(ps -eo pid=,ppid=,etime=,args= 2>/dev/null \
        | awk -v squad_pids=" ${SQUAD_PIDS} " '
            function is_squad(pid) { return index(squad_pids, " " pid " ") > 0 }
            function leaf(path,   parts, n) { n = split(path, parts, "/"); return parts[n] }
            function is_lane(name) {
                return name == "claude" || name == "codex" \
                    || name == "gemini" || name == "kimi"
            }
            function is_interpreter(name) {
                return name == "node" || name == "python" || name == "python3" \
                    || name == "bash"
            }
            {
                lane = leaf($4)
                if (!is_lane(lane)) {
                    if (!is_interpreter(lane) || NF < 5) next
                    lane = leaf($5)
                    if (!is_lane(lane)) next
                }
                if (is_squad($1) || is_squad($2)) next
                printf "%s %s PID %s (parent %s, up %s)\n", \
                    ($2 == 1 ? "orphan" : "attached"), lane, $1, $2, $3
            }
        ' | head -20)
    unset _cli_row
    if [[ "${#ORPHANED_CLIS[@]}" -gt 0 ]]; then
        note_warn "${#ORPHANED_CLIS[@]} orphaned lane CLI process(es) — no parent, 'squad stop' will not reap them: ${ORPHANED_CLIS[*]}" \
            "🟡 Orphaned lane CLI processes (parent exited; not a squad pane root). Nothing will reap these — kill them by PID when you have confirmed they are stale:"
        printf -- '  %s\n' "${ORPHANED_CLIS[@]}" >> "${DOCTOR_LOG}"
    fi
    if [[ "${#ATTACHED_CLIS[@]}" -gt 0 ]]; then
        note_info "Attached non-squad CLI sessions (a live parent owns each of these — informational):"
        printf -- '  %s\n' "${ATTACHED_CLIS[@]}" >> "${DOCTOR_LOG}"
    fi

    # Pathology: high-CPU CLI processes (likely retry storm or runaway loop)
    runaway=$(ps -eo pid,etime,pcpu,comm | awk '$4 ~ /(claude|codex|gemini|kimi)/ && $3+0 > 80 {print}' | head -3)
    if [[ -n "${runaway}" ]]; then
        note_issue "CLI process consuming >80% CPU — kill if stuck in retry loop" \
            "High-CPU CLI processes (>80% CPU — possible runaway):"
        echo "${runaway}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    fi
fi

# Pathology: MCP retry storms — search recent CLI stdout for connection-failure patterns.
# tmux-logs are pane stdout (where CLIs actually log connection issues), not
# cleanup-logs (which are short structured docs that don't reflect real retry
# spam). Time-windowed to last hour; pattern targets MCP-specific failures.
# Read only the recent TAIL of each log (default 8MB), not the whole file:
# these are append-only pane-stdout captures that can reach many GB (a runaway
# gemini TUI log hit 11.6GB), and grepping them in full took ~40s and blew past
# the doctor gate. A retry storm is an ONGOING pathology, so the recent tail is
# the right — and bounded — signal.
# "0 connection-failure lines" came out identical whether the logs were clean,
# the directory did not exist, or no pane had written in the last hour. Only the
# first of those is evidence of anything, and a zero-state install is always one
# of the other two.
RETRY_STORM_FILES=0
if [[ ! -d "${VAULT_ROOT}/_state/tmux-logs" ]]; then
    note_skip "retry-storm scan: this tree has no tmux log directory" \
        "No _state/tmux-logs to scan — MCP retry behaviour is not observable here"
elif [[ "${GREP_USABLE}" != true ]]; then
    note_unknown "retry-storm scan could not run: grep is unavailable"
else
    RETRY_STORM_FILES=$(find "${VAULT_ROOT}/_state/tmux-logs" -name '*.log' -mmin -60 2>/dev/null \
        | wc -l | tr -d ' ')
    RETRY_STORM_LOG=$(find "${VAULT_ROOT}/_state/tmux-logs" -name '*.log' -mmin -60 2>/dev/null \
        | while IFS= read -r _logf; do
            tail -c "${DOCTOR_LOG_SCAN_BYTES:-8000000}" "$_logf" 2>/dev/null \
                | grep -cE 'Failed to connect|connection refused|retrying.*MCP|MCP.*timeout|reconnect attempt'
          done \
        | awk '{sum+=$1} END {print sum+0}')
    if [[ "${RETRY_STORM_FILES}" -eq 0 ]]; then
        note_skip "retry-storm scan: no pane wrote in the last hour" \
            "No tmux log was modified in the last hour — there was no recent output to scan, so a quiet hour reads as quiet, not as clean"
    elif [[ ${RETRY_STORM_LOG} -gt 100 ]]; then
        note_warn "MCP retry storm suspect — ${RETRY_STORM_LOG} connection failures in last hour" \
            "Possible MCP retry storm: ${RETRY_STORM_LOG} connection-failure lines in last hour of ${RETRY_STORM_FILES} tmux-log(s)"
    elif [[ ${RETRY_STORM_LOG} -gt 30 ]]; then
        note_info "🟡 Elevated MCP retry activity: ${RETRY_STORM_LOG} connection-failure lines in last hour"
    else
        note_ok "no retry-storm pattern" \
            "No retry-storm pattern detected (${RETRY_STORM_LOG} connection-failure lines across ${RETRY_STORM_FILES} recently-written log(s))"
    fi
fi

# Pathology: stale tmp files in _state (signal of crashed atomic writes). This
# used to pass in silence, which is the one outcome a reader cannot audit.
if [[ ! -d "${VAULT_ROOT}/_state" ]]; then
    note_skip "stale atomic-write fragment scan: this tree has no _state directory"
else
    STALE_TMPS=$(find "${VAULT_ROOT}/_state" -name '*.tmp.*' -type f -mmin +30 2>/dev/null | wc -l | tr -d ' ')
    if [[ ${STALE_TMPS} -gt 0 ]]; then
        note_warn "${STALE_TMPS} stale temp-file fragments in _state" \
            "${STALE_TMPS} stale .tmp.* files in _state (atomic-write fragments — crash residue?)"
    else
        note_ok "no stale atomic-write fragments" \
            "No stale .tmp.* fragments in _state"
    fi
fi

# --- 11. Log volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Log Volume" >> "${DOCTOR_LOG}"
state_size=$(du -sh "${VAULT_ROOT}/_state" 2>/dev/null | cut -f1)
echo "- _state/ size: ${state_size}" >> "${DOCTOR_LOG}"

# --- Summary ---
echo "" >> "${DOCTOR_LOG}"
echo "## Summary" >> "${DOCTOR_LOG}"
echo "- Mode: ${DOCTOR_MODE}" >> "${DOCTOR_LOG}"
echo "- Healthy: ${#HEALTHY[@]}" >> "${DOCTOR_LOG}"
echo "- Warnings: ${#WARNINGS[@]}" >> "${DOCTOR_LOG}"
echo "- Issues: ${#ISSUES[@]}" >> "${DOCTOR_LOG}"
echo "- Could not determine: ${#UNKNOWNS[@]}" >> "${DOCTOR_LOG}"
echo "- Gate-blocking unknowns: ${#GATE_UNKNOWN_LIST[@]}" >> "${DOCTOR_LOG}"
echo "- Inputs not produced yet (loud, non-gating): ${#ABSENT_INPUTS[@]}" >> "${DOCTOR_LOG}"
echo "- Not measured in fast mode (loud, non-gating): ${#DEEP_DEFERRED[@]}" >> "${DOCTOR_LOG}"
echo "- Not applicable to this install: ${#SKIPPED[@]}" >> "${DOCTOR_LOG}"

# Listed under their own heading because a count alone lets an unmeasured
# subsystem hide behind a healthy-looking total.
if [[ "${#UNKNOWNS[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Could not determine — these are NOT passes" >> "${DOCTOR_LOG}"
    for _unknown in "${UNKNOWNS[@]}"; do
        echo "- ? ${_unknown}" >> "${DOCTOR_LOG}"
    done
    unset _unknown
fi
if [[ "${#ABSENT_INPUTS[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Inputs not produced yet — these do not block a launch" >> "${DOCTOR_LOG}"
    echo "" >> "${DOCTOR_LOG}"
    echo "Each of these checks ran and found its input had never been written." \
        "That is the normal state of an installation that has not been used" \
        "yet. They are counted above as could-not-determine, never as passes." >> "${DOCTOR_LOG}"
    for _absent in "${ABSENT_INPUTS[@]}"; do
        echo "- ? ${_absent}" >> "${DOCTOR_LOG}"
    done
    unset _absent
fi
if [[ "${#DEEP_DEFERRED[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Not measured in fast mode — re-run with --deep" >> "${DOCTOR_LOG}"
    echo "" >> "${DOCTOR_LOG}"
    echo "Each of these checks costs more than the launch gate's budget, so this" \
        "run did not perform it. Its subject is UNDETERMINED, not clean. They are" \
        "counted above as could-not-determine, never as passes." >> "${DOCTOR_LOG}"
    for _deferred in "${DEEP_DEFERRED[@]}"; do
        echo "- ? ${_deferred}" >> "${DOCTOR_LOG}"
    done
    unset _deferred
fi
if [[ "${#SKIPPED[@]}" -gt 0 ]]; then
    echo "" >> "${DOCTOR_LOG}"
    echo "### Not applicable to this install" >> "${DOCTOR_LOG}"
    for _skipped in "${SKIPPED[@]}"; do
        echo "- ○ ${_skipped}" >> "${DOCTOR_LOG}"
    done
    unset _skipped
fi

# Write JSON summary for morning-brief.sh to consume
# Build arrays as proper JSON
json_array() {
    local arr=("$@")
    if [[ "${#arr[@]}" -eq 0 ]]; then
        echo "[]"
    else
        local out="["
        local first=1
        for item in "${arr[@]}"; do
            # Escape backslashes and double-quotes for JSON
            local esc="${item//\\/\\\\}"
            esc="${esc//\"/\\\"}"
            # ...and control characters, which are illegal RAW inside a JSON
            # string. A multi-line value used to emit a summary jq could not
            # parse, and every consumer reads it with a `// 0` fallback -- so
            # bin/morning-brief.sh printed "0 issues" for a run that had just
            # exited 1. Measured against HEAD 2026-08-11: a `vaultroot`
            # ModuleNotFoundError traceback landed in .issues verbatim and the
            # whole file stopped being JSON. A health report whose machine-
            # readable half fails open is worse than none.
            esc="$(printf '%s' "${esc}" | tr -d '\000-\010\013\014\016-\037')"
            esc="${esc//$'\t'/\\t}"
            esc="${esc//$'\r'/\\r}"
            esc="${esc//$'\n'/\\n}"
            if [[ ${first} -eq 1 ]]; then
                out+="\"${esc}\""
                first=0
            else
                out+=",\"${esc}\""
            fi
        done
        out+="]"
        echo "${out}"
    fi
}

# Bash empty-array under set -u needs the +expansion guard
WARNINGS_JSON=$(json_array ${WARNINGS[@]+"${WARNINGS[@]}"})
ISSUES_JSON=$(json_array ${ISSUES[@]+"${ISSUES[@]}"})
UNKNOWNS_JSON=$(json_array ${UNKNOWNS[@]+"${UNKNOWNS[@]}"})
SKIPPED_JSON=$(json_array ${SKIPPED[@]+"${SKIPPED[@]}"})
# Both are SUBSETS of unknowns, published so a consumer can gate on either
# without re-deriving the split from prose. gate_unknowns is what exit 2 means;
# absent_inputs is what a never-run installation looks like.
GATE_UNKNOWNS_JSON=$(json_array ${GATE_UNKNOWN_LIST[@]+"${GATE_UNKNOWN_LIST[@]}"})
ABSENT_INPUTS_JSON=$(json_array ${ABSENT_INPUTS[@]+"${ABSENT_INPUTS[@]}"})
# Third subset, same contract: what THIS run declined to measure. Published so a
# consumer can tell a fast-mode "healthy" from a deep-mode one without parsing
# prose, which is the only way a status line can stop over-claiming.
DEEP_DEFERRED_JSON=$(json_array ${DEEP_DEFERRED[@]+"${DEEP_DEFERRED[@]}"})

# unknown_* and skipped_* are ADDITIVE: bin/morning-brief.sh,
# bin/where-are-we.sh and bin/chrono-status-segment.sh all read the three
# original counts with `// 0` defaults, so they keep working unchanged. They do
# not yet SHOW the unknown count, which means a status line can still read
# "healthy" while subsystems went unmeasured -- those files are outside this
# change's write scope and are flagged for follow-up.
cat > "${SUMMARY}" <<EOF
{
  "date": "${DATE}",
  "mode": "${DOCTOR_MODE}",
  "healthy_count": ${#HEALTHY[@]},
  "warning_count": ${#WARNINGS[@]},
  "issue_count": ${#ISSUES[@]},
  "unknown_count": ${#UNKNOWNS[@]},
  "gate_unknown_count": ${#GATE_UNKNOWN_LIST[@]},
  "absent_input_count": ${#ABSENT_INPUTS[@]},
  "deep_deferred_count": ${#DEEP_DEFERRED[@]},
  "skipped_count": ${#SKIPPED[@]},
  "warnings": ${WARNINGS_JSON},
  "issues": ${ISSUES_JSON},
  "unknowns": ${UNKNOWNS_JSON},
  "gate_unknowns": ${GATE_UNKNOWNS_JSON},
  "absent_inputs": ${ABSENT_INPUTS_JSON},
  "deep_deferred": ${DEEP_DEFERRED_JSON},
  "skipped": ${SKIPPED_JSON}
}
EOF

# --- Console report ---------------------------------------------------------
# Until 2026-08-14 this program wrote every one of its ~35 findings to
# ${DOCTOR_LOG} and printed NOTHING to stdout. README.md:50 and
# docs/getting-started.md:127 both tell a new user to run `bin/squad doctor`, so
# the documented health check answered with a blank line and a failed exit
# status, and never named the file where the report it had just written landed.
# A health tool that prints nothing and fails is worse than no health tool: the
# reader cannot tell a broken install from a broken health check.
#
# This prints the summary, every actionable list, and the log paths. It does not
# re-measure anything and it does not change any exit code -- presentation was
# the whole defect. ASCII markers only: the report is legible under LANG=C,
# which is what a sealed/CI environment gives you.
print_list() {
    local heading="$1" marker="$2"
    shift 2
    [[ "$#" -gt 0 ]] || return 0
    printf '\n%s\n' "${heading}"
    # One printf per item, not `printf FMT "${marker}" "$@"`: printf recycles
    # its format over the remaining arguments, so a two-slot format would pair
    # item 2 with item 3 on a single line and drop every marker after the first.
    local item
    for item in "$@"; do
        printf '  %s %s\n' "${marker}" "${item}"
    done
}

printf '\nVibe Squad doctor — %s (mode: %s)\n' "${DATE}" "${DOCTOR_MODE}"
printf '  HEALTHY ................. %d\n' "${#HEALTHY[@]}"
printf '  WARNINGS ................ %d\n' "${#WARNINGS[@]}"
printf '  ISSUES .................. %d\n' "${#ISSUES[@]}"
printf '  COULD NOT DETERMINE ..... %d  (%d gate-blocking, %d not produced yet, %d not measured in fast mode)\n' \
    "${#UNKNOWNS[@]}" "${#GATE_UNKNOWN_LIST[@]}" "${#ABSENT_INPUTS[@]}" \
    "${#DEEP_DEFERRED[@]}"
printf '  NOT APPLICABLE HERE ..... %d\n' "${#SKIPPED[@]}"

print_list "ISSUES — measured breakage (exit 1):" "!" \
    ${ISSUES[@]+"${ISSUES[@]}"}
print_list "GATE-BLOCKING UNKNOWNS — input was there and could not be read (exit 2):" "x" \
    ${GATE_UNKNOWN_LIST[@]+"${GATE_UNKNOWN_LIST[@]}"}
print_list "COULD NOT DETERMINE — not passes, but nothing here blocks a launch:" "?" \
    ${ABSENT_INPUTS[@]+"${ABSENT_INPUTS[@]}"}
print_list "NOT MEASURED IN FAST MODE — costlier than the launch budget; re-run with --deep:" "~" \
    ${DEEP_DEFERRED[@]+"${DEEP_DEFERRED[@]}"}
print_list "WARNINGS — works, but wants attention or is simply not set up:" "-" \
    ${WARNINGS[@]+"${WARNINGS[@]}"}
print_list "NOT APPLICABLE — this distribution never carried the input:" "o" \
    ${SKIPPED[@]+"${SKIPPED[@]}"}

printf '\nFull report:       %s\n' "${DOCTOR_LOG}"
printf 'Machine-readable:  %s\n' "${SUMMARY}"

# Exit 1 for a measured issue; exit 2 when a mandatory gate could not determine
# its result. Optional UNKNOWNs remain loud but non-gating.
if [[ "${#ISSUES[@]}" -gt 0 ]]; then
    printf '\nVERDICT: %d issue(s) found. This installation is broken; fix them before launching. (exit 1)\n' \
        "${#ISSUES[@]}"
    exit 1
fi
if [[ "${#GATE_UNKNOWN_LIST[@]}" -gt 0 ]]; then
    printf '\nVERDICT: %d mandatory check(s) could not read an input that was present. Not proven broken, not proven healthy. (exit 2)\n' \
        "${#GATE_UNKNOWN_LIST[@]}"
    exit 2
fi
# A "healthy" verdict has to disclose what it did NOT cover, or the fast path
# buys its speed by quietly narrowing the claim.
DEFERRED_NOTE=""
if [[ "${#DEEP_DEFERRED[@]}" -gt 0 ]]; then
    DEFERRED_NOTE="$(printf ' %d check(s) were NOT measured in this fast run and are listed above; bin/doctor.sh --deep runs them.' "${#DEEP_DEFERRED[@]}")"
fi
if [[ "${#ABSENT_INPUTS[@]}" -gt 0 ]]; then
    printf '\nVERDICT: healthy. %d check(s) had no input to read yet, which is what a fresh install looks like — they are reported above, not counted as passes. (exit 0)%s\n' \
        "${#ABSENT_INPUTS[@]}" "${DEFERRED_NOTE}"
    exit 0
fi
printf '\nVERDICT: healthy. (exit 0)%s\n' "${DEFERRED_NOTE}"
exit 0
