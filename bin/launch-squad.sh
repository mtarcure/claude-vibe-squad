#!/bin/bash
# Launch the Claude-Vibe-Squad tmux session: Chrono coordinator + live dashboard sidebar
# + a watchers window. Specialists run as fresh, board-spawned capability-scoped CLIs per
# task (no persistent per-model lane windows since the Phase-3 cutover). Department folders
# are source namespaces and mailbox storage only.
#
# Usage:
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh --safe  # suppress warning + skip doctor; permissions unchanged
#
# After launch:
#   tmux attach -t squad     # attach to the session
#   Ctrl-b + 0  → chrono (conversation + live four-lane status sidebar)
#   Ctrl-b + 5  → watchers/status (outbox notifications + reconciliation)
#   Ctrl-b + z  → zoom the current pane
#   Ctrl-b + d  → detach (panes keep running)
#   Ctrl-b + g  → key cheat-sheet popup (Ctrl-b + ? for every tmux binding)
#   Specialists have no persistent windows; each board task starts a fresh CLI.
#
# Re-run this script to re-attach if the session was killed; if a session
# already exists, it just reattaches without spawning duplicate panes.

set -uo pipefail

SESSION="${SQUAD_SESSION:-squad}"
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
source "${VAULT_ROOT}/shared/lead-windows.sh"

# Canonical value: launchd/com.vibesquad.daemon.plist. The lifecycle regression
# test enforces this local shell copy because the launcher cannot import plist XML.
DAEMON_LABEL="com.vibesquad.daemon"
# Test seam, spelled exactly as in bin/install-routines.sh so both entry points
# can be aimed at one throwaway LaunchAgents directory. Defaults to real behavior.
LAUNCHAGENTS_DIR="${SQUAD_LAUNCHAGENTS_DIR:-${HOME}/Library/LaunchAgents}"
DAEMON_PLIST="${LAUNCHAGENTS_DIR}/${DAEMON_LABEL}.plist"

# ensure_daemon_loaded() exit vocabulary. The daemon is an OPTIONAL enhancement,
# so "nobody installed one" is an ordinary answer rather than a failure -- it is
# the state every fresh clone is in, and refusing to launch there made a
# background launchd job a precondition for running the product at all.
#
#   0                  loaded and verified against the plist this checkout owns
#   DAEMON_ABSENT_RC   no daemon is installed; the launch continues without it
#   anything else      a fault, and the launch still stops
#
# The faults stay fatal on purpose. Each of them -- a foreign plist, an
# unrendered template, a plist that fails plutil, a bootstrap that did not take
# -- can only be reached by someone who DID install a daemon, and who therefore
# needs to be told theirs is broken rather than quietly run without it.
DAEMON_ABSENT_RC=3

# Resolve symlinks in a path's directory so two spellings of one file compare
# equal: launchd reports the physical path (/private/tmp/...) while a path built
# from $HOME may traverse a symlink (/tmp/...), and comparing the raw strings
# would call a correctly-installed daemon foreign. Mirrors resolve_path() in
# bin/install-routines.sh.
resolve_daemon_path() {
    local p="$1" dir base
    dir="$(dirname -- "${p}")"
    base="$(basename -- "${p}")"
    ( cd -- "${dir}" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "${base}" ) || printf '%s\n' "${p}"
}

# Echo the plist path launchd actually loaded DAEMON_LABEL from, or nothing when
# the label is not registered.
#
# The exit code of `launchctl print` is NOT a liveness signal for this daemon.
# launchd is addressed by label over IPC, never through the filesystem, so it
# answers for whichever session owns this uid regardless of which plist that
# session was booted from -- and regardless of whether DAEMON_PLIST still exists
# at all. Asking only "is the label known?" therefore returns rc=0, and a green
# "already loaded", for a daemon whose plist has been removed or which belongs to
# a different installation. Bind the answer to identity instead: compare the path
# launchd reports against the plist this launch intends to run.
#
# "Not registered" is an ordinary answer, not a failure: launchctl exits 113 for
# it, so absorb the status and let an empty string mean "not loaded".
daemon_loaded_plist_path() {
    local service="$1" out
    out="$(launchctl print "${service}" 2>/dev/null || true)"
    printf '%s\n' "${out}" | sed -n 's/^[[:space:]]*path = //p' | head -1
}

ensure_daemon_loaded() {
    local launchd_domain service_target bootstrap_rc attempt live want
    local verify_attempts="${SQUAD_DAEMON_VERIFY_ATTEMPTS:-20}"
    local verify_delay="${SQUAD_DAEMON_VERIFY_DELAY:-0.1}"

    if ! [[ "${verify_attempts}" =~ ^[1-9][0-9]*$ ]]; then
        echo "ERROR: SQUAD_DAEMON_VERIFY_ATTEMPTS must be a positive integer." >&2
        return 64
    fi
    if ! [[ "${verify_delay}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "ERROR: SQUAD_DAEMON_VERIFY_DELAY must be a non-negative number." >&2
        return 64
    fi
    if ! command -v launchctl >/dev/null 2>&1; then
        echo "ERROR: launchctl is unavailable; cannot start or verify the daemon." >&2
        return 127
    fi

    launchd_domain="gui/$(id -u)"
    service_target="${launchd_domain}/${DAEMON_LABEL}"
    want="$(resolve_daemon_path "${DAEMON_PLIST}")"

    live="$(daemon_loaded_plist_path "${service_target}")"
    if [[ -n "${live}" ]]; then
        if [[ "$(resolve_daemon_path "${live}")" == "${want}" ]]; then
            echo "✓ Daemon already loaded in launchd: ${service_target}"
            return 0
        fi
        # Same label, different file. The job launchd is running is not the one
        # this checkout manages, so counting it as ours would credit this launch
        # with another installation's state -- and bootstrapping over it would
        # silently displace a daemon this launch does not own.
        echo "ERROR: ${DAEMON_LABEL} is loaded from a DIFFERENT plist than this launch expects." >&2
        echo "         loaded: ${live}" >&2
        echo "         wanted: ${DAEMON_PLIST}" >&2
        echo "Unload the other one first:  launchctl bootout ${service_target}" >&2
        return 1
    fi

    if [[ ! -f "${DAEMON_PLIST}" ]]; then
        # Not an error. Said once, here, and nowhere else: no other squad
        # subcommand reaches this function, so an operator who never wants the
        # daemon is not nagged by `squad status`, `squad doctor` or `squad attach`.
        echo "NOTICE: the optional launchd daemon is not installed — continuing without it."
        echo "        It adds two things: the live daemon/lane segment in the tmux status"
        echo "        bar, and the documented POST /mcp/<server>/<tool> HTTP bridge."
        echo "        Board dispatch, the outbox watcher, the reconciliation sweep and the"
        echo "        Chrono coordinator do not use it. See docs/install/daemon.md."
        echo "        Add it whenever you want it:  bash bin/install-routines.sh --daemon-only"
        return "${DAEMON_ABSENT_RC}"
    fi
    if LC_ALL=C grep -Eq '__[A-Z][A-Z0-9_]*__' "${DAEMON_PLIST}"; then
        echo "ERROR: installed daemon plist still contains a template token: ${DAEMON_PLIST}" >&2
        echo "Refusing to bootstrap it; use the rendered-template restore procedure." >&2
        return 1
    fi
    if ! plutil -lint "${DAEMON_PLIST}" >/dev/null; then
        echo "ERROR: installed daemon plist failed plutil validation: ${DAEMON_PLIST}" >&2
        return 1
    fi

    echo "Starting launchd daemon '${DAEMON_LABEL}' from its installed plist..."
    bootstrap_rc=0
    launchctl bootstrap "${launchd_domain}" "${DAEMON_PLIST}" || bootstrap_rc=$?

    # Verify by observation rather than by the bootstrap exit code: bootstrap
    # returns non-zero for "already loaded" races, and a zero exit is not by
    # itself proof the job is registered from the plist just installed.
    attempt=1
    while [[ "${attempt}" -le "${verify_attempts}" ]]; do
        live="$(daemon_loaded_plist_path "${service_target}")"
        if [[ -n "${live}" ]] && [[ "$(resolve_daemon_path "${live}")" == "${want}" ]]; then
            if [[ "${bootstrap_rc}" -ne 0 ]]; then
                echo "WARNING: launchctl bootstrap returned ${bootstrap_rc}, but the daemon is loaded." >&2
            fi
            echo "✓ Daemon loaded and verified in launchd: ${service_target}"
            return 0
        fi
        if [[ "${attempt}" -lt "${verify_attempts}" ]]; then
            sleep "${verify_delay}"
        fi
        attempt=$((attempt + 1))
    done

    echo "ERROR: daemon is still absent after launchctl bootstrap (rc=${bootstrap_rc}): ${service_target}" >&2
    if [[ -n "${live}" ]]; then
        echo "       launchd reports ${DAEMON_LABEL} loaded from ${live}, not ${DAEMON_PLIST}." >&2
    fi
    return 1
}

# Hermetic regression seam: exercises only launchd lifecycle code. Production
# launches never set this; it prevents tests from reaching doctor/tmux/processes.
if [[ "${SQUAD_DAEMON_ENSURE_ONLY:-0}" == "1" ]]; then
    ensure_daemon_loaded
    exit $?
fi

WATCHER_FLEET_CHILD=0
for arg in "$@"; do
    case "$arg" in
        --safe) SQUAD_UNSAFE_AUTONOMY=0 ;;
        --autonomous|--unsafe) SQUAD_UNSAFE_AUTONOMY=1 ;;
        --watcher-fleet-child) WATCHER_FLEET_CHILD=1 ;;
        --help|-h)
            sed -n '2,18p' "$0"
            exit 0
            ;;
    esac
done

# Watcher-fleet pidfiles -- scoped by BOTH VAULT_ROOT (it's a path under
# VAULT_ROOT) and SQUAD_SESSION (a subdirectory named after it), so a launcher
# for one checkout/session can never read or act on another's PID. This is
# the primary liveness mechanism for the watcher fleet (Plan B Task 8):
# kill -0 on a PID *this launcher itself wrote here* on spawn, never a scan of
# global `ps` output for a matching name or marker string. That old approach
# is what let a 41KB specialist prompt (measured on a live `codex exec`,
# containing the literal text "outbox-watcher.sh") register as a false
# positive, and -- far worse -- let the real watcher-supervisor marker match
# ANY process system-wide with no VAULT_ROOT/SQUAD_SESSION scoping at all,
# which is the defect that killed the operator's live fleet from an isolated
# regression test earlier in this remediation.
#
# The scoping claim above is about THESE PIDFILES, and only them. The fleet has
# a second mechanism with deliberately weaker scoping -- watcher_seed()'s
# orphan sweep is VAULT_ROOT-scoped but ROOT-WIDE across sessions, on purpose.
# Read the "Scope of the sweep" note above watcher_cleanup_pids() before
# assuming the two are interchangeable; they answer different questions.
WATCHER_FLEET_RUNTIME_DIR="${VAULT_ROOT}/_state/runtime/watcher-fleet/${SESSION}"
OUTBOX_SUPERVISOR_PIDFILE="${WATCHER_FLEET_RUNTIME_DIR}/outbox-supervisor.pid"
RECONCILE_SUPERVISOR_PIDFILE="${WATCHER_FLEET_RUNTIME_DIR}/reconcile-sweep-supervisor.pid"

# Args: $1 pidfile path. True only if the file names a PID this kernel still
# schedules. Used for the watcher fleet (self-written pidfiles above) and
# nowhere else in this file matches a process by name/argv for a liveness
# question -- see watcher_seed() further down for why argv matching, where it
# remains genuinely unavoidable (orphan cleanup, not liveness), is scoped and
# exact-positional instead.
pidfile_alive() {
    local pidfile="$1" pid
    [[ -f "$pidfile" ]] || return 1
    pid="$(cat "$pidfile" 2>/dev/null)"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null
}

# Print one numeric Unix mtime for a file or directory, accepting either BSD
# or GNU stat. Each probe captures into its own assignment so GNU stat's
# `-f %m PATH` behaviour cannot leak a partial filesystem report into the GNU
# fallback's epoch: GNU treats `%m` as another path, prints information for the
# real path, and still exits non-zero. The old `cmd || cmd` substitution joined
# both outputs and fed prose to Bash arithmetic.
#
# No synthetic timestamp on failure. Callers have different safety contracts:
# freshness becomes indeterminate (do not replace a possibly healthy poller),
# while an unreadable lock age must never authorize breaking the lock.
file_mtime_epoch() {
    local target="$1" value
    if value="$(stat -f %m "$target" 2>/dev/null)" \
        && [[ "$value" =~ ^-?[0-9]+$ ]]; then
        printf '%s\n' "$value"
        return 0
    fi
    if value="$(stat -c %Y "$target" 2>/dev/null)" \
        && [[ "$value" =~ ^-?[0-9]+$ ]]; then
        printf '%s\n' "$value"
        return 0
    fi
    return 1
}

# Stable local state, deliberately outside the checkout and independent of
# VAULT_ROOT/CHRONO_VAULT_ROOT.  board-supervisor.sh carries the same default so
# a dispatch reached from a plain shell cannot lose the trail; the regression
# test named there enforces that the two entry points stay identical.
export CHRONO_VAULT_AUDIT_DIR="${CHRONO_VAULT_AUDIT_DIR:-${HOME:-/var/tmp/chrono-vault-${EUID}}/.local/state/chrono-vault/audit}"
printf -v CHRONO_VAULT_AUDIT_DIR_SHELL '%q' "${CHRONO_VAULT_AUDIT_DIR}"

# Doctor evidence shares the vault audit trail's root-independent local-state
# pattern. The resolver is the single source for launch, nightly, and readers.
# shellcheck source=doctor-log-home.sh disable=SC1091
source "${VAULT_ROOT}/bin/doctor-log-home.sh" || exit $?
export CHRONO_DOCTOR_LOG_DIR
printf -v CHRONO_DOCTOR_LOG_DIR_SHELL '%q' "${CHRONO_DOCTOR_LOG_DIR}"

export CHRONO_VAULT_ROOT="${CHRONO_VAULT_ROOT:-${HOME}/Obsidian-Chrono}"
if ! bash "${VAULT_ROOT}/bin/doctor.sh" --check-private-vault-root; then
    echo "ERROR: private memory vault root is invalid; squad startup blocked." >&2
    exit 1
fi
if ! CHRONO_VAULT_ROOT="$(cd -- "${CHRONO_VAULT_ROOT}" && pwd -P)"; then
    echo "ERROR: validated private memory vault root became unavailable." >&2
    exit 1
fi
export CHRONO_VAULT_ROOT
printf -v CHRONO_VAULT_ROOT_SHELL '%q' "${CHRONO_VAULT_ROOT}"

SQUAD_UNSAFE_AUTONOMY="${SQUAD_UNSAFE_AUTONOMY:-1}"
SQUAD_TRUST_CODEX_MCPS="${SQUAD_TRUST_CODEX_MCPS:-0}"

# Internal short-command entry point for window 5. Keeping the tmux injection
# tiny avoids terminal input-buffer truncation/garbling; this process owns and
# reaps every named supervisor child.
if [[ "$WATCHER_FLEET_CHILD" == 1 ]]; then
    watcher_children=()
    stop_watcher_children() {
        local child
        trap - EXIT HUP INT TERM
        for child in "${watcher_children[@]}"; do
            kill -TERM "$child" 2>/dev/null || true
        done
        wait 2>/dev/null || true
    }
    trap 'stop_watcher_children; exit 0' EXIT HUP INT TERM
    export SQUAD_SESSION="$SESSION"
    # ONE consolidated watcher, not one per namespace. outbox-watcher.sh "all"
    # derives the namespace per event from the path; measured 2026-08-08 as four
    # simultaneous writes -> four detections in 31-48 ms, so the fan-in costs
    # nothing in latency. The per-namespace fleet cost six supervisors plus six
    # fswatch children, and because nothing reaped them across restarts it had
    # grown to 43 stale processes by 2026-08-09 -- 25 of them still executing the
    # retired inbox watcher script, which no longer exists in the repo. (Naming
    # that script literally here would trip the guard asserting it never appears
    # in this file.)
    mkdir -p "$WATCHER_FLEET_RUNTIME_DIR"
    bash -c 'while true; do bash "$1" all; rc=$?; echo "watcher supervisor restart: kind=outbox namespace=all rc=$rc" >&2; sleep 2; done' \
        "watcher-supervisor:outbox:all" "${VAULT_ROOT}/bin/outbox-watcher.sh" &
    watcher_children+=("$!")
    printf '%s\n' "$!" > "$OUTBOX_SUPERVISOR_PIDFILE"
    bash -c 'while true; do python3 "$1" reconcile-sweep; rc=$?; echo "watcher supervisor restart: kind=reconcile-sweep rc=$rc" >&2; sleep 2; done' \
        'watcher-supervisor:reconcile-sweep' "${VAULT_ROOT}/scripts/python/swarm_runtime.py" &
    watcher_children+=("$!")
    printf '%s\n' "$!" > "$RECONCILE_SUPERVISOR_PIDFILE"
    wait
    exit 0
fi

# Show the first-run autonomous warning here, but do NOT write its sentinel here.
# The sentinel attests that a first autonomous launch was acknowledged AND made
# it through every pre-flight gate below. Written at this point it would attest a
# success that has not happened yet: a launch that then failed its dependency,
# daemon, or doctor check would still leave a sentinel behind, and the warning
# would be suppressed on every later run on the strength of a launch that never
# worked. The write is deferred to just past the doctor gate.
FIRST_RUN_SENTINEL="${VAULT_ROOT}/_state/.autonomous-launch-ack"
FIRST_RUN_ACK_PENDING=0
if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]] && [[ ! -f "${FIRST_RUN_SENTINEL}" ]]; then
    FIRST_RUN_ACK_PENDING=1
    echo "WARNING: launching autonomous daily-driver profile."
    echo "Board-spawned CLI permissions are fixed by the controller ABI; --safe does not change them."
    echo "Use 'squad up --safe' only to suppress this warning and skip the pre-flight doctor check."
    echo "Run 'squad doctor' first if this is a fresh install."
    echo ""
fi

# Verify the external commands this launch cannot proceed without.
#
# The list itself lives in shared/launch-dependencies.sh because bin/doctor.sh
# gates on the SAME list, and README's Quickstart puts `squad doctor`
# immediately before `squad up`. A copy here would let the documented
# pre-flight go green for a launch this loop then refuses.
#
# Fail loudly if it cannot be loaded: this script runs `set -uo pipefail`
# without -e, so a failed source would leave SQUAD_REQUIRED_COMMANDS unset and
# the loop below would verify nothing while printing nothing.
# shellcheck source=../shared/launch-dependencies.sh disable=SC1091
source "${VAULT_ROOT}/shared/launch-dependencies.sh" || {
    echo "FATAL: cannot load ${VAULT_ROOT}/shared/launch-dependencies.sh; the required-command gate would verify nothing. Refusing to launch." >&2
    exit 1
}
if [[ -z "${SQUAD_REQUIRED_COMMANDS[*]+set}" ]]; then
    echo "FATAL: ${VAULT_ROOT}/shared/launch-dependencies.sh defined no SQUAD_REQUIRED_COMMANDS; the required-command gate would verify nothing. Refusing to launch." >&2
    exit 1
fi
missing=()
for dep in "${SQUAD_REQUIRED_COMMANDS[@]}"; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
done
if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "ERROR: missing required command(s): ${missing[*]}"
    echo "Fix: ${SQUAD_REQUIRED_COMMANDS_HINT}"
    exit 1
fi

# `squad down` removes the KeepAlive job from the user domain. Reverse that
# exact operation before any daemon-dependent health check. Only the installed,
# already-rendered plist is accepted; the repository copy is a template.
#
# An absent daemon is not a failed launch (see DAEMON_ABSENT_RC). Every other
# non-zero status still is, so a broken or foreign install stops here exactly as
# it did before. DAEMON_PRESENT carries the answer forward to the closing
# summary, so the last thing printed does not imply a subsystem that is not
# running. (The status poller below decides for itself: it reports whatever it
# can actually reach, which is the stronger signal.)
DAEMON_PRESENT=1
ensure_daemon_loaded || {
    daemon_rc=$?
    if [[ "${daemon_rc}" -ne "${DAEMON_ABSENT_RC}" ]]; then
        exit "${daemon_rc}"
    fi
    DAEMON_PRESENT=0
}

# Pre-flight health gate. SQUAD_SKIP_DOCTOR=1 skips it ENTIRELY (doctor is never
# even run) — important because a hung/slow doctor must never be able to freeze a
# launch or restart. When it does run, hard-cap it with a timeout: a doctor that
# hangs is treated as a failed check, not an infinite wait.
if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]] \
   && [[ "${SQUAD_SKIP_DOCTOR:-0}" != "1" ]] \
   && [[ -x "${VAULT_ROOT}/bin/doctor.sh" ]]; then
    # Doctor's exit code is a THREE-valued contract (bin/doctor.sh, "Result
    # vocabulary"), not a boolean: 1 = measured breakage, 2 = a mandatory check
    # had its input present and could not read it, 0 = healthy. Collapsing all
    # of them into "doctor reported issues" told a blocked user nothing about
    # which of those had happened, and doctor's own report was sent to
    # /dev/null, so there was nowhere to find out either.
    #
    # Every non-zero rc still blocks. What changes is that the reason is named
    # and doctor's findings are shown. Relaxing the gate itself would let a
    # genuinely broken install launch, which is the opposite of the fix.
    # macOS ships no coreutils `timeout`, so calling it here made `squad up`
    # die on a stock Mac: 127 fell through to the "outside its documented
    # 0/1/2 contract" branch and blocked launch with a message that never
    # mentioned coreutils. doctor.sh already solved this for itself
    # (`run_bounded`); this is the same watchdog shape, inline, because the
    # launcher must not source doctor to start doctor.
    #
    # Only the PID started here is ever signalled -- the process table is
    # shared with every other lane on this host, so a pattern-matched kill
    # would reap siblings.
    doctor_rc=0
    _doctor_out="$(mktemp -t squad-doctor-gate 2>/dev/null || true)"
    if [[ -z "${_doctor_out}" ]]; then
        # No temp file: run unbounded rather than refuse to launch. A hung
        # doctor is a worse outcome than no watchdog, but a false block on a
        # healthy install is worse than both.
        doctor_report="$("${VAULT_ROOT}/bin/doctor.sh" 2>&1)" || doctor_rc=$?
    else
        "${VAULT_ROOT}/bin/doctor.sh" >"${_doctor_out}" 2>&1 &
        _doctor_pid=$!
        ( sleep "${SQUAD_DOCTOR_TIMEOUT:-45}"; kill -TERM "${_doctor_pid}" 2>/dev/null ) >/dev/null 2>&1 &
        _doctor_watchdog=$!
        wait "${_doctor_pid}" 2>/dev/null || doctor_rc=$?
        # Our own watchdog's SIGTERM surfaces as 143; report it as the 124 the
        # case arm below already documents, so the contract is unchanged.
        [[ "${doctor_rc}" -eq 143 ]] && doctor_rc=124
        kill -TERM "${_doctor_watchdog}" 2>/dev/null
        wait "${_doctor_watchdog}" 2>/dev/null || true
        doctor_report="$(cat "${_doctor_out}" 2>/dev/null)"
        rm -f "${_doctor_out}"
    fi
    if [[ "${doctor_rc}" -ne 0 ]]; then
        case "${doctor_rc}" in
            1)  echo "ERROR: doctor found measured problems with this installation; autonomous launch blocked." ;;
            2)  echo "ERROR: doctor found a mandatory input that exists but could not be read; autonomous launch blocked." ;;
            124) echo "ERROR: doctor timed out (>${SQUAD_DOCTOR_TIMEOUT:-45}s) — autonomous launch blocked." ;;
            *)  echo "ERROR: doctor exited ${doctor_rc}, outside its documented 0/1/2 contract; autonomous launch blocked." ;;
        esac
        if [[ "${doctor_rc}" -ne 124 ]] && [[ -n "${doctor_report}" ]]; then
            echo ""
            printf '%s\n' "${doctor_report}" | tail -40
            echo ""
        fi
        echo "Investigate: squad doctor   |   Override: SQUAD_SKIP_DOCTOR=1 squad up"
        exit 1
    fi
fi

# Every pre-flight gate above passed, so the first-run acknowledgement now
# attests something that actually happened. See FIRST_RUN_SENTINEL above for why
# this is not written at the point the warning is printed.
if [[ "${FIRST_RUN_ACK_PENDING}" == "1" ]]; then
    mkdir -p "${VAULT_ROOT}/_state"
    date -u +%FT%TZ > "${FIRST_RUN_SENTINEL}"
fi

# Hermetic regression seam: stops immediately after the pre-flight gates, so the
# gate ordering above can be exercised without reaching tmux or spawning
# anything. Production launches never set this.
if [[ "${SQUAD_PREFLIGHT_ONLY:-0}" == "1" ]]; then
    exit 0
fi

# --- Live status poller ----------------------------------------------------
# Background job: polls the daemon once/sec and writes /tmp/vs-*.status files
# that the tmux status bar + pane borders read (see vs-lane-status.sh). Started
# here — before the has-session reattach guard — so a reattach also re-ensures
# it's running.
#
# Was `pgrep -f 'vs-lane-status.sh'` (Plan B Task 8): an unanchored argv
# substring scan, satisfied by any process whose command line merely contains
# that text -- including a week-old corpse that never got reaped, which let a
# fresh poller silently never start. Replaced with a pidfile this launcher
# itself wrote at spawn time, plus an output-freshness check: vs-daemon.status
# is written unconditionally every ~1s tick regardless of daemon reachability,
# so its age is a clean heartbeat that a merely-alive-but-hung poller fails.
#
# The pidfile alone was unsound in the OPPOSITE direction (Plan B Task 12,
# measured live: pidfile named 75269, dead; the actual poller was 71022, alive
# for 2h49m and writing every ~1s). A live poller this pidfile does not name was
# invisible, so the block below spawned a second one and overwrote the pidfile
# with the new PID -- orphaning the first beyond the reach of every future
# `squad up` AND `squad stop`, once per cycle. So: a dead-or-wrong pidfile
# alongside fresh output means the poller is UNTRACKED, not absent. Find it and
# adopt it. Fresh output on its own is not proof (the last tick of a poller that
# died two seconds ago is still fresh), which is why liveness is settled by
# finding the real process, never by the mtime alone.
VS_LANE_STATUS_STATUS_DIR="${VIBESQUAD_STATUS_DIR:-/tmp}"
VS_LANE_STATUS_PIDFILE="${VS_LANE_STATUS_STATUS_DIR}/vs-lane-status.pid"
# pid_is_vs_lane_status_poller(): the exact positional argv check, shared with
# bin/squad-stop.sh's reaper so the launcher can never adopt a process the
# stopper would then refuse to kill.
#
# Fail loudly. This script runs `set -uo pipefail` without -e on purpose, so a
# failed `source` would otherwise just continue with the predicate undefined:
# every identity call would return 127, every real poller would read as "not
# ours", and the launcher would spawn a duplicate on every launch while
# reporting nothing wrong.
# shellcheck source=../shared/process-identity.sh disable=SC1091
source "${VAULT_ROOT}/shared/process-identity.sh" || {
    echo "FATAL: cannot load ${VAULT_ROOT}/shared/process-identity.sh; the status poller's identity check is unavailable and launch would leak a duplicate poller. Refusing to launch." >&2
    exit 1
}

# find_live_vs_lane_status_pollers() moved to shared/process-identity.sh, which
# this file already sources above: bin/doctor.sh now asks the same question
# (is there exactly one poller?) and a second copy of a process-selection scan
# is the last thing this system should own two of.

# The ONE writer of this pidfile -- used both when adopting a poller we found
# and when recording one we just spawned. Staged in the destination directory so
# the move is a same-filesystem rename: a concurrent `squad stop` reading this
# file sees the old PID or the new one, never a half-written line.
#
# A truncating `> "$pidfile"` redirect here would be a real leak, not a
# theoretical one: `squad stop` reads this file between the truncate and the
# write, fails its `^[0-9]+$` guard, removes the pidfile, and the poller it was
# supposed to reap is orphaned -- exactly the state Task 12 exists to prevent.
# The window is reachable because the poller guard is deliberately outside
# LAUNCH_LOCK, so two near-simultaneous launches can both reach the spawn.
write_vs_lane_status_pidfile() {
    local pid="$1" staged
    mkdir -p "$VS_LANE_STATUS_STATUS_DIR" || return 1
    staged="$(mktemp "${VS_LANE_STATUS_PIDFILE}.XXXXXX")" || return 1
    printf '%s\n' "$pid" > "$staged" || { rm -f "$staged"; return 1; }
    mv -f "$staged" "$VS_LANE_STATUS_PIDFILE" || { rm -f "$staged"; return 1; }
}

# True only when the pidfile names a process that IS this root's live poller.
# Identity, not bare liveness -- this pidfile can sit stale for days, so the PID
# it names may since have been recycled onto something unrelated, which would
# otherwise read as "poller running" while the real one runs untracked.
vs_lane_status_pidfile_names_live_poller() {
    local tracked_pid
    pidfile_alive "$VS_LANE_STATUS_PIDFILE" || return 1
    tracked_pid="$(cat "$VS_LANE_STATUS_PIDFILE" 2>/dev/null)"
    pid_is_vs_lane_status_poller "$tracked_pid"
}

# Called on the paths that spawn a replacement anyway (no output yet, or stale
# output from a wedged poller). The spawn takes the pidfile over, so EVERY live
# poller of this root -- the one the pidfile currently names and any that were
# already untracked -- is about to become an unnamed orphan. Diagnosing exactly
# that state is what Task 12 cost by hand, so name them all, at the moment it
# happens. Asking the finder rather than only the pidfile is what covers the
# untracked ones; a tracked live poller is in its output too, so there is no
# separate case. Reporting only: a launcher does not kill.
vs_lane_status_warn_stranded_pollers() {
    local reason="$1" p
    local -a stranded=()
    while read -r p; do
        [[ -n "$p" ]] && stranded+=("$p")
    done < <(find_live_vs_lane_status_pollers)
    [[ "${#stranded[@]}" -gt 0 ]] || return 0
    echo "WARNING: ${#stranded[@]} live status poller(s) (${stranded[*]}) are being replaced (${reason}); they stay running and UNTRACKED, so 'squad stop' will not reap them. Kill them by PID: kill ${stranded[*]}" >&2
}

vs_lane_status_poller_alive() {
    local freshness_file mtime now age max_age p
    local -a live_pollers=()
    freshness_file="${VS_LANE_STATUS_STATUS_DIR}/vs-daemon.status"
    if [[ ! -f "$freshness_file" ]]; then
        vs_lane_status_warn_stranded_pollers "it has never written ${freshness_file}"
        return 1
    fi
    if ! mtime="$(file_mtime_epoch "$freshness_file")"; then
        echo "ERROR: cannot read a numeric mtime for ${freshness_file} with BSD or GNU stat; status-poller freshness is indeterminate." >&2
        return 2
    fi
    now=$(date +%s)
    age=$(( now - mtime ))
    max_age="${VS_LANE_STATUS_FRESHNESS_MAX_AGE:-10}"
    # A hung-but-alive poller freezes the status bar while every liveness check
    # says "running", so stale output means not-alive no matter what any PID or
    # pidfile says. Checked before the pidfile arms so adoption can never
    # resurrect a wedged poller.
    if [[ "$age" -gt "$max_age" ]]; then
        vs_lane_status_warn_stranded_pollers "its output is ${age}s old, limit ${max_age}s"
        return 1
    fi

    # The ordinary case: the pidfile names this root's live poller.
    vs_lane_status_pidfile_names_live_poller && return 0

    while read -r p; do
        [[ -n "$p" ]] && live_pollers+=("$p")
    done < <(find_live_vs_lane_status_pollers)
    # Fresh output but no live poller: it died within the freshness window.
    # Spawning is correct, and the spawn writes a pidfile that names it.
    [[ "${#live_pollers[@]}" -gt 0 ]] || return 1

    if [[ "${#live_pollers[@]}" -gt 1 ]]; then
        echo "WARNING: ${#live_pollers[@]} live vs-lane-status.sh pollers found (${live_pollers[*]}); adopting ${live_pollers[0]}. The others predate this check and are untracked -- kill them by PID." >&2
    fi
    echo "Adopting untracked live status poller (PID ${live_pollers[0]}) instead of spawning a duplicate." >&2
    if ! write_vs_lane_status_pidfile "${live_pollers[0]}"; then
        # Could not record it, but it is provably alive, so a second one would
        # still be a duplicate. Report alive and name the PID: an untrackable
        # poller is the operator's to reap, not a reason to leak another.
        echo "WARNING: could not write ${VS_LANE_STATUS_PIDFILE}; live poller ${live_pollers[0]} stays untracked and 'squad stop' will not reap it." >&2
    fi
    return 0
}
vs_lane_status_poller_rc=0
vs_lane_status_poller_alive || vs_lane_status_poller_rc=$?
if [[ "$vs_lane_status_poller_rc" -gt 1 ]]; then
    echo "FATAL: refusing to replace or adopt a status poller without a trustworthy freshness timestamp." >&2
    exit 1
fi
if [[ "$vs_lane_status_poller_rc" -eq 1 ]]; then
    # The poller needs one of two sources, and picking the wrong one is silent.
    # Its HTTP mode opens with `: "${VIBESQUAD_DAEMON_TOKEN:?...}"`, so with no
    # token it exits at that guard the instant it starts -- under `nohup
    # >/dev/null`, where nobody sees it -- and /tmp/vs-daemon.status is never
    # written, leaving the status bar's daemon segment BLANK. Blank reads as
    # "fine". A fresh clone has no secrets file and therefore no token, so that
    # is the default a new user would have got.
    #
    # Ask whether the token exists WITHOUT capturing it, then, only on the HTTP
    # branch, extract it in a second subshell. That preserves the original
    # property exactly: the token is scoped by an inline command prefix to the
    # poller process, and never enters this launcher's memory or env, let alone
    # the panes that inherit it -- API keys have leaked into terminal titles
    # through that path before. NEVER source the whole secrets file here.
    if zsh -c 'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; [[ -n "${VIBESQUAD_DAEMON_TOKEN:-}" ]]'; then
        VIBESQUAD_DAEMON_TOKEN="$(zsh -c 'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; printf %s "${VIBESQUAD_DAEMON_TOKEN:-}"')" \
            nohup bash "${VAULT_ROOT}/bin/vs-lane-status.sh" >/dev/null 2>&1 &
    else
        # File mode instead, aimed at a path that is deliberately not there. The
        # poller needs no token for it, reports `● daemon offline` every tick,
        # and keeps rendering the panel/lane capsules it derives from local
        # files -- which never depended on the daemon. The absence is now shown
        # rather than hidden behind an empty status segment.
        VS_DAEMON_TASKS_FILE="${VAULT_ROOT}/_state/runtime/no-daemon-tasks.json" \
            nohup bash "${VAULT_ROOT}/bin/vs-lane-status.sh" >/dev/null 2>&1 &
    fi
    # nohup execs its target directly rather than forking a child, so $! here
    # is the actual poller process's PID, not a nohup wrapper's.
    #
    # Through the same atomic writer the adoption path uses -- one file, one
    # writer, one guarantee. This is the far more frequent write (every cold
    # start and every respawn), so a truncating redirect here would reopen the
    # orphan window on the common path while the rare path was safe.
    VS_LANE_STATUS_SPAWNED_PID=$!
    if ! write_vs_lane_status_pidfile "$VS_LANE_STATUS_SPAWNED_PID"; then
        echo "WARNING: spawned status poller ${VS_LANE_STATUS_SPAWNED_PID} could not be recorded in ${VS_LANE_STATUS_PIDFILE}; it is running UNTRACKED and 'squad stop' will not reap it. Kill it by PID: kill ${VS_LANE_STATUS_SPAWNED_PID}" >&2
    fi
    disown 2>/dev/null || true
fi

# apply_squad_globals — all server-global tmux options + key bindings.
#
# ORDER MATTERS: global `set-option -g` requires a running server, and
# `tmux start-server` does NOT create a queryable server on a cold start — the
# server only comes into existence once the first session is created. So this
# MUST run AFTER new-session (fresh launch) or when a session already exists
# (reattach). Calling it before a session exists silently drops every option and
# the session comes up with default green tmux chrome. It is idempotent, so
# reattaches re-assert it (curing drift back to defaults after a kill-server /
# external recreate).
apply_squad_globals() {
    # 50k scrollback (default 2k truncates active sessions) + mouse for trackpad.
    tmux set-option -g history-limit 50000
    tmux set-option -g mouse on

    # One-key recovery: Ctrl-b SPACE refreshes the client display AND parks you
    # back on the chrono coordinator pane. Cures any stale-frame visual issue.
    tmux bind-key Space run-shell "tmux refresh-client \; tmux select-window -t ${SESSION}:chrono \; tmux select-pane -t ${SESSION}:chrono.0"
    # Push tmux selections to the macOS clipboard automatically (⌘V elsewhere).
    tmux set-option -g set-clipboard on
    tmux bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi y send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true

    # Key cheat-sheet, on demand rather than always-on.
    #
    # It used to be a permanent second status row (`status 2` plus a static
    # `status-format[1]`): an entire terminal row spent, for the life of every
    # session, on text that never changes. And the text was WRONG. It advertised
    # `Tab / C-b <n>: lanes`, but this session has no lane windows -- lanes are
    # PANES inside the chrono window (bin/sidebar.sh), and specialists are
    # board-spawned CLIs with no window at all, which this script's own header
    # has said since the Phase-3 cutover. `C-b 1` landed on a stray shell.
    #
    # `g` for guide: not a default tmux prefix binding, so nothing is shadowed.
    # `?` is deliberately left alone -- that is tmux's own list-keys, which is
    # the complete answer this is only a summary of.
    #
    # Each line is a separate single-quoted argument to one `printf '%s\n'`, so
    # the popup command stays POSIX-shell-clean: no $'...' escapes, which
    # display-popup would hand to whatever `default-shell` happens to be.
    local keys_cmd
    keys_cmd="printf '%s\n'"
    keys_cmd+=" ' vibesquad — keys'"
    keys_cmd+=" ''"
    keys_cmd+=" '  C-b 0      chrono window: Chrono pane + swarm sidebar pane'"
    keys_cmd+=" '  C-b 5      watchers/status window'"
    keys_cmd+=" '  C-b o      next pane in this window'"
    keys_cmd+=" '  C-b q      show pane numbers, then a digit to jump'"
    keys_cmd+=" '  C-b z      zoom / unzoom the focused pane'"
    keys_cmd+=" '  C-b Space  refresh the display, return to the Chrono pane'"
    keys_cmd+=" '  C-b [      scrollback (q leaves)'"
    keys_cmd+=" '  C-b d      detach; every pane keeps running'"
    keys_cmd+=" '  C-b ?      every binding tmux knows'"
    keys_cmd+=" '  C-b g      this list'"
    keys_cmd+=" ''"
    keys_cmd+=" '  Model lanes are PANES in the chrono window, not windows.'"
    keys_cmd+=" '  Specialists are board-spawned CLIs with no window at all.'"
    keys_cmd+=" ''"
    keys_cmd+=" '  Enter closes.'"
    keys_cmd+="; read -r _"
    # display-popup needs tmux >= 3.2. bind-key parses its command at bind time,
    # so an older server fails HERE rather than leaving `g` bound to something
    # that errors on every press; the fallback keeps the information reachable.
    tmux bind-key g display-popup -E -w 74 -h 20 "${keys_cmd}" 2>/dev/null \
        || tmux bind-key g display-message "C-b 0 chrono · C-b 5 watchers · C-b o next pane · C-b z zoom · C-b Space reset · C-b [ scroll · C-b d detach · C-b ? all keys"

    # --- Claude-Code-grade status bar (locked palette, poller-fed) ---------
    # Every `#()` here is a plain `cat` of a file the poller already wrote, so
    # tmux does zero network work per render. That was true before too -- and
    # beside the point, because the cost was never network, it was PROCESS
    # CREATION. tmux forks a shell per `#()` per render: one for status-left,
    # one for status-right (which additionally forked `jq` AND a `date`
    # subshell), and one per pane border. At `status-interval 1` that is roughly
    # seven processes every second for the life of the session, forever.
    #
    # So: the doctor summary is parsed once per second by the poller that was
    # already running (bin/vs-lane-status.sh, in the Python it already spawns)
    # instead of by a jq the status bar forks; and the interval drops to 5. The
    # remaining `#()` calls are all `cat`, at a fifth of the rate.
    #
    # 5s is a display interval, not a data interval: the poller still refreshes
    # its files every ~1s, so nothing shown here is more than 5s stale, and the
    # things that actually move second-to-second -- the spinner and the elapsed
    # clock -- were never readable at 1s anyway.
    #
    # Palette: colour74 cyan accent, colour252 near-white, colour240 dim,
    # colour214 amber, colour234/233 bg.
    tmux set-option -g status on
    tmux set-option -g status-position bottom
    tmux set-option -g status 1                       # one row; the hints moved to C-b g
    tmux set-option -g status-interval 5
    tmux set-option -g status-style      'fg=colour252,bg=colour234'
    tmux set-option -g status-left-length 60
    tmux set-option -g status-right-length 180
    # Narrow clients degrade on purpose instead of being cut mid-token.
    #
    # The lengths above are ceilings, not targets: what actually fits is the
    # CLIENT's width, and tmux resolves an overlong bar by squeezing out the
    # window list first and then hard-cutting the right segment wherever it runs
    # out -- mid-word, mid-escape, with no indication that anything was dropped.
    # Below roughly 118 columns the window list disappeared; below roughly 101
    # the right segment was cut in the middle of a token.
    #
    # So each segment names its own least-valuable part and drops it under 120
    # columns: the brand word on the left, and the swarm capsule on the right
    # (which is the long, variable one, and whose per-lane detail is already on
    # the pane borders).
    #
    # NOT VERIFIED: whether tmux skips the `#()` in an untaken branch, which
    # would make the narrow form cheaper as well as shorter. An earlier version
    # of this comment asserted it as fact. `display-message -p` cannot settle it
    # -- it returns `#()` empty because tmux populates those asynchronously and
    # caches them, so both branches measure as "did not run" -- and confirming it
    # needs an attached client at two widths, which nobody has run. The layout
    # benefit above holds either way; only the spawn-count bonus is unproven.
    #
    # Two things about tmux formats that this comparison gets wrong if written
    # the obvious way, both straight out of tmux(1):
    #
    #   - `#{>=:a,b}` is a STRING comparison. `#{>=:80,120}` is TRUE, because
    #     "8" sorts after "1" -- so the plain form hands an 80-column terminal
    #     the wide layout, which is precisely backwards. The numeric operators
    #     live behind `e`: `#{e|>=:a,b}`.
    #   - `#{?a,b,c}` splits on top-level commas and makes NO exception for the
    #     comma inside a `#[fg=x,bold]` style; the manual's own example escapes
    #     it as `#[fg=white#,bg=red]`. Rather than rely on that escape, every
    #     branch below is comma-free and the styles stay outside them.
    tmux set-option -g status-left "#[fg=colour74,bold]#{?#{e|>=:#{client_width},120}, vibesquad , vs }#[fg=colour240]· #(cat /tmp/vs-daemon.status 2>/dev/null) "
    # No colour prefix on the doctor segment: the poller writes its own, and it
    # is the ONLY thing on the bar allowed to use amber (see bin/doctor-state.sh).
    tmux set-option -g status-right "#{?#{e|>=:#{client_width},120},#(cat /tmp/vs-swarm.status 2>/dev/null) #[fg=colour240]· ,}#(cat /tmp/vs-doctor.status 2>/dev/null) #[fg=colour240]· #[fg=colour252]%H:%M "
    # Row 1 is gone, but a server configured by an OLDER launch still carries the
    # value. This function is the thing that cures drift on reattach, so unset it
    # explicitly instead of relying on `status 1` to merely stop rendering it.
    tmux set-option -gu "status-format[1]" 2>/dev/null || true

    # Window tabs — accent the current lane, dim the rest.
    tmux set-option -g window-status-style         'bg=colour234,fg=colour240'
    tmux set-option -g window-status-current-style 'bg=colour234,fg=colour252,bold'
    tmux set-option -g window-status-format         ' #[fg=colour240]#I #[fg=colour250]#W '
    tmux set-option -g window-status-current-format ' #[fg=colour74,bold]#I #W '

    # Pane borders — hairline accent on the active pane; the lane's live status
    # rides the border top. Lane windows are named gpt-codex/claude/gemini/kimi,
    # matching the poller's /tmp/vs-lane-<name>.status files, so #{window_name}
    # keys them directly. (The chrono window overrides this in sidebar.sh.)
    tmux set-option -g pane-border-style        'fg=colour238'
    tmux set-option -g pane-active-border-style 'fg=colour74'
    tmux set-option -g pane-border-status top
    tmux set-option -g pane-border-format "#[fg=colour240] #{?pane_active,#[fg=colour74]▎,#[fg=colour238]│} #[fg=colour252,bold]#{window_name}#[fg=colour240] #(cat /tmp/vs-lane-#{window_name}.status 2>/dev/null) "
}

WATCHERS_WIN="$(lead_window_name watchers)"
# A filesystem lock directory, not a tmux wait-for channel name -- see
# acquire_dir_lock below for why. Named the same as before for continuity.
#
# Anchored under VAULT_ROOT/_state, NOT ${TMPDIR:-/tmp} (fix round 1 on Plan
# B Task 1/2). TMPDIR varies by invocation context -- a login/terminal shell
# typically has it set to a per-user /var/folders/.../T/ path, while a
# launchd-like or `env -i` context (ssh, a background job) has it unset and
# falls to plain /tmp. Two launches from DIFFERENT contexts would each
# compute a DIFFERENT lock directory and both proceed, silently degrading
# mutual exclusion to none -- strictly weaker than the tmux wait-for channel
# this replaced, which was scoped to one tmux SERVER regardless of caller
# context. VAULT_ROOT is derived identically everywhere (repo-root.sh
# resolves it from the script's own on-disk location), so anchoring here
# closes that gap. It also avoids a second problem plain /tmp has on a
# shared host: /tmp is world-writable, so a local user could pre-create this
# exact directory name and permanently deny `squad up` (mkdir would never
# succeed, and the "owner" would never look like a live PID we can wait
# out). ${VAULT_ROOT}/_state is only writable by whoever owns the checkout.
WATCHER_FLEET_LOCK="${VAULT_ROOT}/_state/runtime/vibesquad-watcher-fleet-${SESSION}.lockdir"
WATCHER_FLEET_LOCK_HELD=0
WATCHER_FLEET_LOCK_TIMEOUT="${SQUAD_WATCHER_FLEET_LOCK_TIMEOUT:-60}"

# --- Generic mkdir-based lock ------------------------------------------------
# Same protocol as registry_reconciler.py's lockdir() and
# bin/chrono-queue-backfill.sh's inline lock: atomic mkdir is the acquire, an
# owner.pid file is written immediately after so a waiter can tell whether the
# current holder is still alive. A confirmed-dead owner (kill -0 fails) breaks
# the lock immediately; an owner.pid that cannot be read/parsed is treated as
# abandoned once the lock directory's mtime is older than 300s. Neither of
# those paths waits out the timeout below -- they are the "dead or absent
# owner" case, and are safe to break right away.
#
# What is new here relative to those two: an overall wall-clock timeout. A
# CONFIRMED-LIVE owner is never broken early no matter how long the wait --
# on timeout this fails loudly instead, naming the owner PID and lock age, per
# "never silently proceed, never silently break a live owner's lock."
#
# Args: $1 lock directory   $2 overall timeout in seconds   $3 label for messages
#
# Every path through the loop body reaches the timeout check below -- there is
# deliberately no `continue` past it. Both lock-breaking branches used to
# `continue` on the assumption that the break had worked, which jumped over
# BOTH the timeout check and the sleep. When the break cannot succeed (parent
# directory unwritable or read-only, lock directory owned by another user, a
# leftover file inside it, a full disk) that was an unbounded busy spin at
# 100% CPU with no timeout and no sleep: `squad up` hanging forever instead of
# failing loudly, which is the precise outcome Plan B Task 2 exists to remove.
# Newly reachable because this lock moved out of always-writable /tmp and
# under ${VAULT_ROOT}/_state, which one `sudo squad up` leaves root-owned.
# registry_reconciler.py's _lockdir_wait_or_timeout() already gets this right;
# this is the same protocol, now bounded in both languages.
acquire_dir_lock() {
    local lock_dir="$1" timeout_s="$2" label="$3"
    local start_ts now waited owner_pid mtime age broke_lock
    start_ts=$(date +%s)
    mkdir -p "$(dirname -- "$lock_dir")" 2>/dev/null || true
    while ! mkdir "$lock_dir" 2>/dev/null; do
        broke_lock=0
        owner_pid="$(cat "${lock_dir}/owner.pid" 2>/dev/null || true)"
        if [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
            if ! kill -0 "$owner_pid" 2>/dev/null; then
                rm -f "${lock_dir}/owner.pid" 2>/dev/null || true
                rmdir "$lock_dir" 2>/dev/null && broke_lock=1
            fi
        else
            if mtime="$(file_mtime_epoch "$lock_dir")"; then
                age=$(( $(date +%s) - mtime ))
                if [[ "$age" -gt 300 ]]; then
                    rm -f "${lock_dir}/owner.pid" 2>/dev/null || true
                    rmdir "$lock_dir" 2>/dev/null && broke_lock=1
                fi
            elif [[ ! -d "$lock_dir" ]]; then
                # The holder released between mkdir's failure and this probe.
                # Retry immediately; there is no unreadable lock left to judge.
                broke_lock=1
            else
                # Indeterminate is not stale. Keep the lock intact and stay in
                # the existing bounded wait: its owner may still publish
                # owner.pid, and on timeout the diagnostic below reports an
                # unknown age instead of inventing epoch zero.
                :
            fi
        fi
        now=$(date +%s)
        waited=$((now - start_ts))
        if [[ "$waited" -ge "$timeout_s" ]]; then
            # A lock directory that does not exist was never "held" -- mkdir
            # itself is failing, and reporting a phantom owner and a 0s lock
            # age would send the operator hunting a process that isn't there.
            if [[ ! -d "$lock_dir" ]]; then
                echo "ERROR: ${label} (${lock_dir}) could not be CREATED after ${waited}s: mkdir keeps failing and the directory does not exist." >&2
                echo "This is not a held lock. Check that $(dirname -- "$lock_dir") is writable by this user (one 'sudo squad up' is enough to leave it root-owned) and that the disk is not full." >&2
                return 1
            fi
            if mtime="$(file_mtime_epoch "$lock_dir")"; then
                age="$(( now - mtime ))s"
            else
                age="unknown (mtime unreadable)"
            fi
            echo "ERROR: ${label} (${lock_dir}) still held after ${waited}s by PID ${owner_pid:-unknown} (lock age ${age}); refusing to wait longer." >&2
            echo "Never broken automatically -- if PID ${owner_pid:-unknown} is confirmed gone, remove manually: rm -rf ${lock_dir}" >&2
            return 1
        fi
        # A break that actually succeeded retries immediately (nothing to wait
        # for); every other path backs off, so a break that keeps failing
        # cannot burn a core while it waits out the timeout above.
        [[ "$broke_lock" == 1 ]] || sleep 0.1
    done
    printf '%s\n' "$$" > "${lock_dir}/owner.pid"
    return 0
}

release_dir_lock() {
    local lock_dir="$1"
    rm -f "${lock_dir}/owner.pid" 2>/dev/null || true
    rmdir "$lock_dir" 2>/dev/null || true
}

# --- Pidfile-based fleet accounting (Plan B Task 8) -------------------------
# watcher_script_count()/watcher_supervisor_count() used to answer "how many
# supervisors/root watchers are running" by scanning EVERY process on the
# host (`ps -axo command=`) and shlex-parsing its full command line, then
# substring/token-matching against a plain "watcher-supervisor:..." marker
# with NO VAULT_ROOT or SQUAD_SESSION scoping. Two independent failure modes
# followed from that: (1) `shlex.split()` on a 41KB specialist prompt (a
# measured real argv size, containing plain-English apostrophes) can raise
# ValueError; the row was silently `continue`d, undercounting supervisors --
# watcher_fleet_healthy then read unhealthy on a HEALTHY fleet and triggered a
# needless kill-and-respawn cycle, which is how six intended watchers leaked
# to 43 running. (2) The marker match itself had no owner scoping at all, so
# it could -- and once did -- match another checkout/session's real
# watcher-supervisor processes and get them killed by this one's repair cycle.
#
# Replaced with pidfile_alive() (declared near the top of this file, by
# WATCHER_FLEET_RUNTIME_DIR): the two supervisors write their own PID to a
# VAULT_ROOT+SQUAD_SESSION-scoped file the instant they're spawned. No global
# `ps` scan, no argv parsing of anything this launcher did not itself write.
watcher_fleet_report() {
    local outbox_pid reconcile_pid outbox_children
    outbox_pid="$(cat "$OUTBOX_SUPERVISOR_PIDFILE" 2>/dev/null || echo none)"
    reconcile_pid="$(cat "$RECONCILE_SUPERVISOR_PIDFILE" 2>/dev/null || echo none)"
    outbox_children=0
    if [[ "$outbox_pid" =~ ^[0-9]+$ ]]; then
        outbox_children="$(pgrep -P "$outbox_pid" 2>/dev/null | wc -l | tr -d '[:space:]')"
    fi
    printf 'outbox[all]=supervisor-pid:%s live-children:%s\n' "$outbox_pid" "$outbox_children"
    printf 'reconcile-sweep=supervisor-pid:%s\n' "$reconcile_pid"
}

watcher_fleet_healthy() {
    local index5_name outbox_pid
    index5_name="$(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}' 2>/dev/null | awk -F'|' '$1 == 5 {print $2}')"
    [[ "$index5_name" == "$WATCHERS_WIN" ]] || return 1
    pidfile_alive "$OUTBOX_SUPERVISOR_PIDFILE" || return 1
    pidfile_alive "$RECONCILE_SUPERVISOR_PIDFILE" || return 1
    # A live supervisor with no live child is a hung or crash-looping wrapper,
    # not a working watcher. `pgrep -P` is a kernel PPID lookup -- a process
    # relationship, not a name or argv scan -- so it cannot be confused by an
    # unrelated process's command line the way the old marker match was.
    outbox_pid="$(cat "$OUTBOX_SUPERVISOR_PIDFILE" 2>/dev/null)"
    [[ -n "$(pgrep -P "$outbox_pid" 2>/dev/null)" ]] || return 1
}

watcher_cleanup_pids() {
    local protected_pids watcher_pane_pids
    protected_pids="$(tmux list-panes -a -F '#{session_name}|#{window_index}|#{pane_pid}' 2>/dev/null \
        | awk -F'|' -v session="$SESSION" '$1 == session && $2 >= 0 && $2 <= 4 {print $3}' \
        | paste -sd, -)"
    watcher_pane_pids="$(tmux list-panes -a -F '#{session_name}|#{window_name}|#{pane_pid}' 2>/dev/null \
        | awk -F'|' -v session="$SESSION" -v window="$WATCHERS_WIN" '$1 == session && $2 == window {print $3}' \
        | paste -sd, -)"
    python3 - "$VAULT_ROOT" "$protected_pids" "$watcher_pane_pids" <<'PY'
import os
import shlex
import subprocess
import sys
from collections import defaultdict

root, protected_raw, watcher_roots_raw = sys.argv[1:]
protected = {int(v) for v in protected_raw.split(",") if v.isdigit()}
watcher_roots = {int(v) for v in watcher_roots_raw.split(",") if v.isdigit()}
rows = subprocess.check_output(
    ["ps", "-axo", "pid=,ppid=,command="], text=True
).splitlines()
processes = {}
children = defaultdict(set)
for row in rows:
    parts = row.strip().split(None, 2)
    if len(parts) < 3:
        continue
    pid, ppid = int(parts[0]), int(parts[1])
    processes[pid] = (ppid, parts[2])
    children[ppid].add(pid)

# Protect this helper, launch-squad, and their complete ancestry.
cursor = os.getpid()
while cursor in processes and cursor > 1:
    protected.add(cursor)
    cursor = processes[cursor][0]

# watcher_seed() finds ORPHANS from before pidfile tracking existed (Plan B
# Task 8) -- the current supervisors are identified precisely via
# OUTBOX_SUPERVISOR_PIDFILE/RECONCILE_SUPERVISOR_PIDFILE (pidfile_alive() in
# the parent shell) and don't need this at all. This is the fallback for
# whatever this launcher did NOT itself spawn and track: a stray
# watcher-supervisor loop or fswatch process left over from a crash, an old
# per-namespace fleet, etc.
#
# SCOPE OF THE SWEEP -- VAULT_ROOT-scoped, deliberately ROOT-WIDE across
# sessions. This is NOT the same scoping as the pidfiles above (VAULT_ROOT AND
# SQUAD_SESSION), and the difference is intentional, not an oversight:
#
#   1. An orphan has no recoverable session. It was spawned by a session that
#      has since died, possibly under a name nothing on this host still uses.
#      Scoping the sweep to the CURRENT session would make it structurally
#      unable to clean the exact thing it exists for -- and cross-restart
#      accumulation is what the "43 running" history in this file's header is
#      made of.
#   2. Only the two supervisor wrappers could take a session token for free.
#      This launcher composes their argv itself, right here. The other three
#      seed shapes -- `outbox-watcher.sh all`, `swarm_runtime.py
#      reconcile-sweep`, `fswatch <mailbox leaves>` -- are settled CLI
#      contracts, and each is an INDEPENDENT seed. Scoping the wrappers alone
#      would leave every child unscoped while letting this comment claim the
#      sweep is session-scoped: a partial guarantee stated as a complete one,
#      which is the defect class this whole plan exists to remove.
#
#      Scoping all of them is possible but not free. Two of the three ARE ours
#      to change -- bin/outbox-watcher.sh and scripts/python/swarm_runtime.py,
#      invoked by the loop bodies at the spawn site above, which are ours too
#      -- so it means new argument handling in two scripts plus three changed
#      spawn shapes, bought to gain a guarantee item 1 says we do not want.
#      Only `fswatch` is third-party and genuinely could not carry one.
#
# The residual, stated rather than papered over: two squad sessions running
# concurrently on ONE checkout cross-kill each other's watchers (and, via the
# shell-ancestor ascent below, each other's window-5 pane shell). Same family
# as the 2026-08-16 incident, narrower blast radius -- it cannot cross a
# VAULT_ROOT boundary, which is what that incident did. Two concurrent
# sessions on one checkout is unsupported; use separate checkouts. Tests that
# need a throwaway session on a live checkout set SQUAD_SKIP_WATCHER_FLEET=1,
# which is why that seam still exists.
#
# Exact positional matching only -- never substring, never token-membership
# ("is this string present ANYWHERE in the tokenized command"). A specialist's
# entire compiled prompt is its argv (measured 41,008 bytes on a live
# `codex exec`, containing the literal text "outbox-watcher.sh" as plain
# prose): a predicate testing "does some token merely CONTAIN or EQUAL this
# text" will eventually fire on prose that happens to reproduce it, and a
# predicate with no VAULT_ROOT scoping will fire on a DIFFERENT checkout's
# real, live, legitimate watcher processes too -- the exact defect that
# killed the operator's live fleet from an isolated regression test.
def watcher_seed(command: str) -> bool:
    # `ps -axo command=` prints the kernel's argv SPACE-JOINED WITH NO QUOTING
    # RE-ADDED. It is not a shell command line and cannot be tokenized back
    # into argv unambiguously, so every fixed shape below is matched against
    # that raw text at a FIXED POSITION -- the head, or the tail -- never
    # "does this text appear somewhere in it".
    #
    # This corrects the clause that shipped with Plan B Task 8, which required
    # `len(shlex.split(command)) == 5` for the supervisor wrapper. A real
    # supervisor can never satisfy that: the `bash -c` body is ONE argv
    # element full of spaces, so `ps` renders the whole invocation as 17
    # space-separated words. Measured against the live fleet, both supervisors
    # came back tokens=17 / no match, and the two positive-control tests
    # passed only because they hand-built a single-quoted string `ps` cannot
    # emit -- they would have passed with the clause deleted. Matching the
    # tail rather than a token COUNT also drops the hidden dependency on the
    # loop body's own length, which is free to change.
    command = command.strip()
    if not command:
        return False
    executable, _sep, rest = command.partition(" ")
    executable = os.path.basename(executable)
    outbox_script = f"{root}/bin/outbox-watcher.sh"
    runtime_script = f"{root}/scripts/python/swarm_runtime.py"

    # A watcher-supervisor wrapper is spawned as EXACTLY
    #   bash -c '<loop body>' '<marker>' '<vault-root-scoped script>'
    # (see the spawn site near WATCHER_FLEET_CHILD above). argv[0] and argv[1]
    # are pinned at the head, and the marker and script path are pinned as the
    # LAST TWO argv elements. Both scoping properties of the previous clause
    # survive intact: the marker is compared as an EXACT string (never a
    # prefix/substring/"token starts with" test), and the script path is
    # VAULT_ROOT-anchored, so this root's marker sitting next to a DIFFERENT
    # root's script path -- the only way a real foreign supervisor could ever
    # present here -- does not match. For 41KB of specialist prose to reach
    # this it would have to BEGIN `bash -c ` and END with this exact
    # marker-then-path pair.
    if executable == "bash" and rest.startswith("-c "):
        for marker, script in (
            ("watcher-supervisor:outbox:all", outbox_script),
            ("watcher-supervisor:reconcile-sweep", runtime_script),
        ):
            if rest.endswith(f" {marker} {script}"):
                return True

    # The root watchers those wrappers exec. Compared as the whole argv tail
    # rather than token-by-token so that a VAULT_ROOT containing a space (an
    # ordinary macOS clone location: "~/Google Drive/...", "~/Obsidian
    # Vaults/...") still matches -- shlex would split such a path into two
    # tokens and silently stop matching, the same class of false negative as
    # the token-count bug above.
    if executable == "bash" and rest == f"{outbox_script} all":
        return True
    # `.lower()` is load-bearing: macOS Homebrew's framework build execs
    # .../Python.app/Contents/MacOS/Python, so argv[0]'s basename is `Python`
    # and the case-sensitive `startswith("python")` this replaces never
    # matched the live reconcile-sweep child at all.
    if executable.lower().startswith("python") and rest == f"{runtime_script} reconcile-sweep":
        return True

    # fswatch is the one shape with no fixed argv length -- the watcher passes
    # one mailbox path per directory it monitors -- so "some argv element is a
    # VAULT_ROOT-scoped mailbox leaf" is the only available test and
    # tokenizing is unavoidable. It is gated behind the `fswatch` executable
    # name so a specialist's prose argv can never reach it, and every accepted
    # token is still VAULT_ROOT-anchored.
    if executable == "fswatch":
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        return any(
            token.startswith(f"{root}/departments/")
            and (token.endswith("/inbox") or token.endswith("/outbox"))
            for token in tokens
        )
    return False

targets = watcher_roots | {
    pid for pid, (_ppid, command) in processes.items() if watcher_seed(command)
}

# A named seed owns all descendants. Ascend only through shell ancestors that
# are not protected lane/coordinator roots; this catches bare historical loops.
# (Previously also continued past a non-shell ancestor if its command
# happened to contain "watcher-supervisor:" anywhere -- an unscoped substring
# check that contradicted this comment's own "only through shell ancestors"
# and is exactly the class of match this whole function exists to eliminate.
# A genuine supervisor ancestor is already its own seed via watcher_seed()
# above, so dropping that clause loses nothing.)
queue = list(targets)
while queue:
    pid = queue.pop()
    for child in children.get(pid, ()):
        if child not in targets:
            targets.add(child)
            queue.append(child)
for seed in list(targets):
    parent = processes.get(seed, (1, ""))[0]
    while parent > 1 and parent in processes and parent not in protected:
        command = processes[parent][1]
        executable = os.path.basename(command.split(None, 1)[0])
        if executable not in {"bash", "zsh", "sh"}:
            break
        targets.add(parent)
        parent = processes[parent][0]

targets.difference_update(protected)
targets.discard(1)

def depth(pid: int) -> int:
    seen = set()
    value = 0
    while pid in processes and pid not in seen and pid > 1:
        seen.add(pid)
        pid = processes[pid][0]
        value += 1
    return value

for pid in sorted(targets, key=lambda value: (depth(value), value), reverse=True):
    print(pid)
PY
}

stop_watcher_fleet() {
    local pids pid protected
    pids="$(watcher_cleanup_pids)"
    protected="$(tmux list-panes -a -F '#{session_name}|#{window_index}|#{pane_pid}' 2>/dev/null \
        | awk -F'|' -v session="$SESSION" '$1 == session && $2 >= 0 && $2 <= 4 {print $3}')"
    for pid in $pids; do
        if grep -qx "$pid" <<<"$protected"; then
            echo "ERROR: watcher cleanup selected protected squad:0..4 pane PID $pid" >&2
            return 75
        fi
    done
    if [[ -n "$pids" ]]; then
        echo "Stopping watcher process tree: $(tr '\n' ' ' <<<"$pids")"
        kill -TERM $pids 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            local alive=""
            for pid in $pids; do
                kill -0 "$pid" 2>/dev/null && alive="${alive} ${pid}"
            done
            [[ -z "$alive" ]] && break
            sleep 0.2
        done
        for pid in $pids; do
            kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    if tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$WATCHERS_WIN"; then
        tmux kill-window -t "${SESSION}:${WATCHERS_WIN}"
    fi
}

start_watcher_fleet() {
    local index5_name child_command
    [[ "${#COMPATIBILITY_NAMESPACES[@]}" -gt 0 ]] || {
        echo "ERROR: compatibility namespace inventory is empty; watcher repair refused" >&2
        return 76
    }
    index5_name="$(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}' 2>/dev/null | awk -F'|' '$1 == 5 {print $2}')"
    if [[ -n "$index5_name" && "$index5_name" != "$WATCHERS_WIN" ]]; then
        echo "ERROR: squad:5 is occupied by non-watcher window '$index5_name'; repair refused" >&2
        return 77
    fi
    tmux new-window -d -t "${SESSION}:5" -n "$WATCHERS_WIN" -c "$VAULT_ROOT"
    mkdir -p "${VAULT_ROOT}/_state/tmux-logs"
    tmux pipe-pane -t "${SESSION}:${WATCHERS_WIN}" -o "cat >> ${VAULT_ROOT}/_state/tmux-logs/watchers-status.log"
    child_command="exec env CHRONO_VAULT_ROOT=${CHRONO_VAULT_ROOT_SHELL} CHRONO_VAULT_AUDIT_DIR=${CHRONO_VAULT_AUDIT_DIR_SHELL} CHRONO_DOCTOR_LOG_DIR=${CHRONO_DOCTOR_LOG_DIR_SHELL} SQUAD_SESSION=${SESSION} bash ${VAULT_ROOT}/bin/launch-squad.sh --watcher-fleet-child"
    tmux send-keys -l -t "${SESSION}:${WATCHERS_WIN}" "$child_command"
    tmux send-keys -t "${SESSION}:${WATCHERS_WIN}" Enter
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        watcher_fleet_healthy && return 0
        sleep 0.25
    done
    echo "ERROR: watcher fleet failed health convergence" >&2
    watcher_fleet_report >&2
    return 78
}

ensure_watcher_fleet() (
    local rc=0 index5_name
    # Hermetic regression seam, same spirit as SQUAD_PREFLIGHT_ONLY /
    # SQUAD_DAEMON_ENSURE_ONLY above: skips watcher-fleet management entirely.
    # Production launches never set this.
    #
    # It was added when watcher_cleanup_pids()/watcher_seed() matched the
    # "watcher-supervisor:" marker across ALL processes on the host with no
    # VAULT_ROOT scoping whatsoever -- a throwaway session's
    # `watcher_fleet_healthy()` is unconditionally false the first time (no
    # window 5 yet), so it always reaches stop_watcher_fleet(), which then
    # killed this HOST'S real live fleet for whatever OTHER checkout happened
    # to be running. Confirmed the hard way while writing this file's own
    # regression test.
    #
    # VAULT_ROOT scoping landed with Plan B Task 8, so that cross-CHECKOUT
    # blast radius is closed: an isolated test with its own VAULT_ROOT can no
    # longer select this checkout's processes. The seam remains necessary
    # because the sweep is deliberately root-wide across SESSIONS -- see
    # "SCOPE OF THE SWEEP" above watcher_cleanup_pids() for why, and for the
    # residual it accepts. A test using a throwaway SQUAD_SESSION on the LIVE
    # checkout is exactly that residual, so it must keep setting this.
    if [[ "${SQUAD_SKIP_WATCHER_FLEET:-0}" == "1" ]]; then
        echo "Watcher fleet management skipped (SQUAD_SKIP_WATCHER_FLEET=1)."
        return 0
    fi
    # Was `tmux wait-for -L "$WATCHER_FLEET_LOCK"`, released only in the traps
    # below. That lock has no owner introspection (no PID, no age) and no
    # timeout: if the holder was SIGKILLed before reaching its own
    # `wait-for -U`, tmux never releases it (a wait-for lock is not tied to
    # the holding process's lifetime the way an flock/mkdir lock is), so every
    # later `squad up` would block here silently forever. The mkdir-based
    # acquire_dir_lock below is the same bounded, owner-tracked protocol used
    # for LAUNCH_LOCK above and for chrono-queue.md's writers: a confirmed-dead
    # owner breaks the lock immediately, a live owner is never broken early,
    # and a wait that outlasts the timeout fails loudly with the owner PID and
    # lock age instead of hanging.
    if ! acquire_dir_lock "$WATCHER_FLEET_LOCK" "$WATCHER_FLEET_LOCK_TIMEOUT" "watcher-fleet lock"; then
        return 79
    fi
    WATCHER_FLEET_LOCK_HELD=1
    trap 'if [[ "$WATCHER_FLEET_LOCK_HELD" == 1 ]]; then release_dir_lock "$WATCHER_FLEET_LOCK"; WATCHER_FLEET_LOCK_HELD=0; fi' EXIT
    trap 'if [[ "$WATCHER_FLEET_LOCK_HELD" == 1 ]]; then release_dir_lock "$WATCHER_FLEET_LOCK"; WATCHER_FLEET_LOCK_HELD=0; fi; exit 130' HUP INT TERM
    if [[ "${#COMPATIBILITY_NAMESPACES[@]}" -eq 0 ]]; then
        echo "ERROR: compatibility namespace inventory is empty; watcher cleanup refused" >&2
        rc=76
    fi
    index5_name="$(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}' 2>/dev/null | awk -F'|' '$1 == 5 {print $2}')"
    if [[ "$rc" -eq 0 && -n "$index5_name" && "$index5_name" != "$WATCHERS_WIN" ]]; then
        echo "ERROR: squad:5 is occupied by non-watcher window '$index5_name'; watcher cleanup refused" >&2
        rc=77
    fi
    if [[ "$rc" -ne 0 ]]; then
        release_dir_lock "$WATCHER_FLEET_LOCK"
        WATCHER_FLEET_LOCK_HELD=0
        trap - EXIT HUP INT TERM
        return "$rc"
    fi
    if watcher_fleet_healthy; then
        echo "Watcher fleet already healthy; no restart needed."
        watcher_fleet_report
    else
        echo "Watcher fleet unhealthy; performing deterministic watcher-only repair."
        stop_watcher_fleet || rc=$?
        if [[ "$rc" -eq 0 ]]; then
            start_watcher_fleet || rc=$?
        fi
        if [[ "$rc" -eq 0 ]]; then
            watcher_fleet_report
        else
            echo "ERROR: watcher fleet repair stopped with status ${rc}" >&2
            # Convergence is all-or-nothing. Remove a partial watcher-only set
            # so the next idempotent launch starts from a known empty state.
            stop_watcher_fleet || true
        fi
    fi
    release_dir_lock "$WATCHER_FLEET_LOCK"
    WATCHER_FLEET_LOCK_HELD=0
    trap - EXIT HUP INT TERM
    return "$rc"
)

# --- LAUNCH_LOCK: serialize the has-session decision + session creation ----
# This is the actual fix for the duplicate-Chrono race: without it, two
# concurrent `squad up` runs both observe "no session yet" from `has-session`
# below and both attempt to create one (the unchecked-`tmux new-session`
# backstop above then only decides which one errors out). With the lock, the
# loser blocks here until the winner has *finished* creating the session, then
# re-reads has-session for itself and takes the reattach branch below instead.
#
# Lock ordering (written contract, checked by adversarial review as the
# highest-risk item in this remediation): LAUNCH_LOCK is always acquired
# BEFORE WATCHER_FLEET_LOCK (below, inside ensure_watcher_fleet) and is always
# released before this process can block on anything interactive --
# `tmux attach` or the "Attach now?" prompt at the very end of a fresh launch.
# Holding it through an attached operator's whole terminal session would
# strand every other concurrent `squad up` for as long as that terminal stays
# open. Never acquire WATCHER_FLEET_LOCK first and then try for LAUNCH_LOCK --
# that reverses this order and can deadlock against a concurrent launch's
# forward-ordered acquisition.
#
# The `--watcher-fleet-child` re-invocation (see WATCHER_FLEET_CHILD near the
# top of this script) NEVER reaches this line: it takes its own fast-path
# `exit 0` long before LAUNCH_LOCK is even declared. That is what makes this
# safe against the deadlock flagged in review: a *literally* launch-wide lock
# that also caught the watcher-fleet child would let the parent (holding
# LAUNCH_LOCK, polling the child's health inside ensure_watcher_fleet) and the
# child (blocked forever acquiring the very lock its own parent holds) wait on
# each other forever, and no fresh startup would ever converge again. The
# `WATCHER_FLEET_CHILD != 1` guard below is a second, explicit line against
# exactly that failure mode, in case this code is ever reordered.
# Anchored under VAULT_ROOT/_state, NOT ${TMPDIR:-/tmp} -- see the identical
# reasoning at WATCHER_FLEET_LOCK's declaration above (fix round 1 on Plan B
# Task 1/2): TMPDIR varies by invocation context, so a plain-/tmp lock path
# silently degrades mutual exclusion to none between two launches from
# different contexts, and world-writable /tmp lets a local user pre-create
# the directory and permanently deny `squad up`.
LAUNCH_LOCK="${VAULT_ROOT}/_state/runtime/vibesquad-launch-${SESSION}.lockdir"
LAUNCH_LOCK_HELD=0
# Must exceed WATCHER_FLEET_LOCK_TIMEOUT with real margin, not just be
# "different": LAUNCH_LOCK is held across the entire ensure_watcher_fleet()
# call below (both branches), which itself first waits up to
# WATCHER_FLEET_LOCK_TIMEOUT to acquire WATCHER_FLEET_LOCK, and can then
# spend further real time inside stop_watcher_fleet()/start_watcher_fleet()
# actually tearing down and respawning the fleet. Two EQUAL timeouts (both
# defaulted to 60s until this fix) let a LAUNCH_LOCK waiter time out and
# fail loudly while its own holder is still legitimately mid-repair -- not a
# hung holder, just a slower one than the outer bound accounted for. The
# margin below is deliberately generous (not "+1s"): stop_watcher_fleet's
# own TERM-then-KILL wait loop alone can take up to ~4s, and a cold
# watcher-fleet-child spawn can reasonably take several more.
LAUNCH_LOCK_TIMEOUT="${SQUAD_LAUNCH_LOCK_TIMEOUT:-$((WATCHER_FLEET_LOCK_TIMEOUT + 60))}"
if [[ "$LAUNCH_LOCK_TIMEOUT" -le "$WATCHER_FLEET_LOCK_TIMEOUT" ]]; then
    echo "ERROR: SQUAD_LAUNCH_LOCK_TIMEOUT (${LAUNCH_LOCK_TIMEOUT}s) must exceed" >&2
    echo "SQUAD_WATCHER_FLEET_LOCK_TIMEOUT (${WATCHER_FLEET_LOCK_TIMEOUT}s) -- LAUNCH_LOCK is held" >&2
    echo "across ensure_watcher_fleet(), which itself waits up to the watcher-fleet" >&2
    echo "timeout; an outer timeout that is not strictly longer can fire while its own" >&2
    echo "holder is still legitimately working, not hung." >&2
    exit 1
fi

release_launch_lock() {
    if [[ "$LAUNCH_LOCK_HELD" == 1 ]]; then
        release_dir_lock "$LAUNCH_LOCK"
        LAUNCH_LOCK_HELD=0
    fi
}
trap release_launch_lock EXIT
trap 'release_launch_lock; exit 130' HUP INT TERM

# Hermetic regression seam (fix round 1 on Plan B Task 1/2): when set, block
# here until a second file appears, after first touching a marker file to
# announce arrival. Lets a test force two concurrent launches to be
# PROVABLY racing through the LAUNCH_LOCK/has-session decision at the exact
# same instant, rather than merely started around the same time -- a test
# with no such barrier cannot distinguish "the race is closed" from "the
# race never actually happened" (e.g. one process finishing before the
# other even reaches this point, which "passes" either way). Production
# launches never set this.
if [[ -n "${SQUAD_TEST_RACE_BARRIER:-}" ]]; then
    touch "${SQUAD_TEST_RACE_BARRIER}.ready.$$"
    while [[ ! -f "${SQUAD_TEST_RACE_BARRIER}.go" ]]; do
        sleep 0.05
    done
fi

if [[ "$WATCHER_FLEET_CHILD" != 1 ]]; then
    if ! acquire_dir_lock "$LAUNCH_LOCK" "$LAUNCH_LOCK_TIMEOUT" "squad launch lock"; then
        exit 1
    fi
    LAUNCH_LOCK_HELD=1
fi

# Reattach-path session health check (Plan B Task 7 addition). Before this,
# the reattach branch verified nothing beyond the watcher window (via
# ensure_watcher_fleet, which only looks at window 5) -- window 0 could be
# missing, its coordinator pane could be dead, or unrelated stray windows
# could accumulate, and `squad up` would attach anyway, silently. Measured:
# the operator's live session sat for eight days with no watcher window at
# all and a stray, un-managed "zsh" window at index 1 -- `squad up` attached
# to it without repairing or complaining every time, and it took two manual
# launcher runs to actually fix.
#
# Contract: repair what can be repaired (stray default-named windows are
# reaped inline, matching "repair silently, never attach silently to a
# malformed session" without stopping the launch over something harmless);
# fail loudly (refuse to attach, non-zero exit) for anything that cannot be
# repaired here -- a coordinator window that is missing, misnamed, or whose
# pane process is actually gone. This does not attempt deep coordinator
# liveness (no heartbeat exists for "is Claude still responsive" the way
# Task 8 built one for the watcher fleet) -- it catches the concrete
# failure this guards against: window/pane composition, not conversational
# health.
verify_session_windows() {
    local index0_name chrono_pane_pids pane_pid pane_alive=0
    local idx name auto_rename pane_count

    index0_name="$(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}' 2>/dev/null | awk -F'|' '$1 == 0 {print $2}')"
    if [[ "$index0_name" != "chrono" ]]; then
        echo "ERROR: squad:0 is not the chrono coordinator window (found '${index0_name:-<absent>}'); refusing to attach to a malformed session." >&2
        return 1
    fi

    chrono_pane_pids="$(tmux list-panes -t "${SESSION}:chrono" -F '#{pane_pid}' 2>/dev/null)"
    if [[ -z "$chrono_pane_pids" ]]; then
        echo "ERROR: squad:chrono has no panes; refusing to attach to a malformed session." >&2
        return 1
    fi
    for pane_pid in $chrono_pane_pids; do
        kill -0 "$pane_pid" 2>/dev/null && pane_alive=1
    done
    if [[ "$pane_alive" != 1 ]]; then
        echo "ERROR: squad:chrono's pane process is gone (checked PID(s): ${chrono_pane_pids}); refusing to attach to a malformed session." >&2
        return 1
    fi

    # Reap stray default-named windows: not the coordinator (0) or the
    # watchers window, a single pane, and still on tmux's own
    # automatic-rename for that window (queried via the #{automatic-rename}
    # format variable, which resolves tmux's real session/global-default
    # inheritance itself rather than this script trying to reimplement it).
    # Both windows this launcher creates are given an explicit `-n` name at
    # creation, which is what turns automatic-rename off for them -- a
    # window still on automatic-rename was never named by this script, and
    # tmux renames a window after whatever its active foreground command
    # is, so "zsh"/"bash"/"sh" with automatic-rename still on means the
    # bare shell itself -- not something the operator is running inside
    # it -- is what's sitting in that pane.
    while IFS='|' read -r idx name auto_rename pane_count; do
        [[ -z "$idx" ]] && continue
        [[ "$idx" == "0" ]] && continue
        [[ "$name" == "$WATCHERS_WIN" ]] && continue
        [[ "$auto_rename" == "1" ]] || continue
        [[ "$pane_count" == "1" ]] || continue
        case "$name" in
            zsh|bash|sh) ;;
            *) continue ;;
        esac
        echo "Reaping stray default-named window ${idx} ('${name}') -- not the coordinator or watcher window, still auto-renamed, single idle pane."
        tmux kill-window -t "${SESSION}:${idx}" 2>/dev/null || true
    done < <(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}|#{automatic-rename}|#{window_panes}' 2>/dev/null)

    return 0
}

# If the session already exists, re-assert globals (the server is up) and attach.
# Only attach when we actually have a terminal — otherwise `tmux attach` hangs
# forever with no tty, which is exactly what breaks automated restarts.
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    if ! ensure_watcher_fleet; then
        echo "ERROR: watcher fleet repair failed; coordinator and lane panes were left untouched" >&2
        exit 1
    fi
    if ! verify_session_windows; then
        release_launch_lock
        exit 1
    fi
    apply_squad_globals
    release_launch_lock
    if [[ -t 0 && -t 1 ]]; then
        echo "Session '${SESSION}' already exists. Attaching..."
        tmux attach -t "${SESSION}"
    else
        echo "Session '${SESSION}' already exists. Attach with: tmux attach -t ${SESSION}"
    fi
    exit 0
fi

echo "Creating tmux session: ${SESSION}"
echo ""

# Regenerate the resume capsule BEFORE the chrono pane exists, so the first thing
# Chrono reads at session start is derived from the live registry rather than from
# whenever it was last written. Non-fatal: a stale capsule must never block a launch.
if ! "${VAULT_ROOT}/bin/chrono-resume-capsule.sh" >/dev/null 2>&1; then
    echo "WARNING: resume capsule regeneration failed; chrono/resume.md may be stale" >&2
fi

# Create the coordinator session FIRST so the tmux server exists, THEN style.
# (The chrono pane is populated further below, once PATH/AUTH prefixes are set.)
#
# The exit status is load-bearing: `set -uo pipefail` has no `-e`, so an
# unchecked failure here used to fall straight through to the pane setup
# below, and `tmux send-keys ... vs-welcome.sh` (which execs claude) landed in
# whatever session already held that name -- the duplicate-Chrono bug. Two
# concurrent `squad up` runs both pass the `has-session` check above (neither
# session exists yet), then both reach this line; only one `tmux new-session`
# actually creates it, and the loser must abort here rather than silently
# continue into a live session it does not own.
if ! tmux new-session -d -s "${SESSION}" -n "chrono" -c "${VAULT_ROOT}/chrono"; then
    echo "ERROR: failed to create tmux session '${SESSION}' -- it likely already exists (a concurrent launch may have won the race)." >&2
    echo "Attach to the live session instead:  tmux attach -t ${SESSION}" >&2
    exit 1
fi
apply_squad_globals

# Per-pane log dir — pipe-pane writes pane stdout here for grep-able audit
TMUX_LOG_DIR="${VAULT_ROOT}/_state/tmux-logs"
mkdir -p "${TMUX_LOG_DIR}"
for ns in "${COMPATIBILITY_NAMESPACES[@]}"; do
    mkdir -p "${VAULT_ROOT}/departments/${ns}/inbox" \
             "${VAULT_ROOT}/departments/${ns}/active" \
             "${VAULT_ROOT}/departments/${ns}/outbox" \
             "${VAULT_ROOT}/departments/${ns}/archive"
done

# Ensure ~/.local/bin is on PATH inside every tmux pane (claude + kimi live there)
PATH_PREFIX='export PATH="$HOME/.local/bin:$HOME/go/bin:$PATH"'

# Claude panes host Claude plugins, including chrono-media-studio. Keep the
# OpenAI key only there so Sora can authenticate without exposing media creds to
# model workers. Quote the validated canonical root for the Chrono pane because
# an existing tmux server does not necessarily inherit the launcher's environment.
MEDIA_AUTH_PREFIX="export CHRONO_VAULT_ROOT=${CHRONO_VAULT_ROOT_SHELL} CHRONO_VAULT_AUDIT_DIR=${CHRONO_VAULT_AUDIT_DIR_SHELL} CHRONO_DOCTOR_LOG_DIR=${CHRONO_DOCTOR_LOG_DIR_SHELL}; unset ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY"

acknowledge_gemini_agents() {
    python3 - "$VAULT_ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
project_root = root / "model-lanes" / "gemini"
agents_dir = project_root / ".gemini" / "agents"
if not agents_dir.exists():
    raise SystemExit(0)

ack_path = Path.home() / ".gemini" / "acknowledgments" / "agents.json"
try:
    data = json.loads(ack_path.read_text()) if ack_path.exists() else {}
except json.JSONDecodeError:
    data = {}

project = str(project_root)
data.setdefault(project, {})
for path in sorted(agents_dir.glob("*.md")):
    if path.name.startswith("_"):
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data[project][path.stem] = digest

ack_path.parent.mkdir(parents=True, exist_ok=True)
tmp = ack_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.replace(ack_path)
PY
}

# (Phase 3) acknowledge_gemini_agents no longer called at startup — board-supervisor.sh
# handles the Gemini agent-file acknowledgement per fresh spawn now.

# (Phase 3 cutover) The per-lane CLI command strings that used to live here were
# DELETED 2026-08-05, not disabled. They assigned CODEX_CMD/CLAUDE_CMD/CONTENT_CMD/
# RESEARCH_CMD and nothing read them -- persistent per-model lane windows are retired
# and board-supervisor.sh spawns each lane fresh per task. The dead block manufactured
# two opposite misreadings for anyone grepping this file: that the stack launches four
# CLIs with all gates off by default (harsher than the truth), and that --safe is
# load-bearing over what workers may do (it is not; see README). Worker permissions
# now live in scripts/python/dispatch_context_builder.py, which is where to look.

# Window 0: chrono (Coordinator — Claude Code, auto-loads chrono/CLAUDE.md).
# The session + chrono window were already created above (before styling); here
# we just wire up logging and launch the coordinator.
tmux pipe-pane -t "${SESSION}:chrono" -o "cat >> ${TMUX_LOG_DIR}/chrono.log"
tmux send-keys -t "${SESSION}:chrono" "${PATH_PREFIX}" C-m
# The coordinator keeps restricted clearance. Fresh board workers remain
# fail-safe internal for sensitivity while board-supervisor projects their
# engagement-specific aperture separately.
tmux send-keys -t "${SESSION}:chrono" "${MEDIA_AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" 'export CHRONO_VAULT_CLEARANCE=restricted' C-m
# vs-welcome.sh clears, prints the coordinator greeting, then execs claude with
# acceptEdits + opus + effort xhigh + --add-dir (keeps OPENAI_API_KEY for media).
tmux send-keys -t "${SESSION}:chrono" "bash ${VAULT_ROOT}/bin/vs-welcome.sh" C-m

# Optional local convenience: pre-trust chrono MCP servers in Codex config so
# the coding pane does not prompt for MCP approval mid-task. This mutates
# ~/.codex/config.toml, so public/default launches never do it implicitly.
if [[ "${SQUAD_TRUST_CODEX_MCPS}" == "1" ]]; then
    if python3 "${VAULT_ROOT}/bin/patch-codex-mcp-trust.py" 2>&1; then
        true  # patch logged its own status
    else
        echo "WARNING: codex-mcp-trust patch failed — coding pane may prompt for MCP approvals"
        echo "Fix manually: python3 ${VAULT_ROOT}/bin/patch-codex-mcp-trust.py"
    fi
fi

# (Phase 3 cutover) Persistent per-model lane windows RETIRED. Specialists now run as
# fresh, capability-scoped CLIs spawned per task by the board (SQUAD_DISPATCH_MODE=board,
# the default since 2d51612). No model-lead windows are launched at startup. The provider
# CLI binaries are still required (the board execs codex/claude/gemini/kimi per spawn) —
# see the dependency check above. Rollback: revert the cutover commits + relaunch.

# Window 5: watchers — outbox watchers per source namespace plus reconciliation.
# Outbox watchers nudge the chrono pane when a response lands
# (closing the pull-based polling gap so Chrono surfaces responses to the
# operator without waiting for the operator's next turn).
if ! ensure_watcher_fleet; then
    echo "ERROR: initial watcher fleet failed to start; coordinator and lane panes remain available" >&2
    exit 1
fi

# Give the model CLIs a moment to initialize so the sidebar's first capture
# shows their welcome screens instead of empty shells.
sleep 1

# Sidebar — split chrono window into chrono main + 4 model-lane status tiles.
# Default-on per operator preference. Toggle off with bin/sidebar-off.sh.
bash "${VAULT_ROOT}/bin/sidebar.sh" >/dev/null 2>&1 || true

# Switch back to chrono window for first attachment
tmux select-window -t "${SESSION}:chrono"
tmux select-pane -t "${SESSION}:chrono.0"

# Session creation is fully converged -- release LAUNCH_LOCK now, before the
# interactive "Attach now?" prompt / `tmux attach` below, so a waiting
# concurrent `squad up` is freed as soon as it is safe to do so rather than
# for the rest of this operator's terminal session.
release_launch_lock

echo "✓ Session '${SESSION}' created:"
echo "  0: chrono     (Coordinator + live dashboard sidebar)"
echo "  5: ${WATCHERS_WIN} (1 consolidated outbox watcher, all ${#COMPATIBILITY_NAMESPACES[@]} namespaces + reconciliation sweep)"
echo "  (per-model lane windows retired — specialists run as fresh board-spawned CLIs per task)"
echo ""
echo "Board dispatch is the default: specialists spawn as fresh capability-scoped CLIs per task."
echo "Chrono window has the live dashboard sidebar. Toggle off: bin/sidebar-off.sh"
if [[ "${DAEMON_PRESENT}" == "0" ]]; then
    echo "Running WITHOUT the optional daemon: the status bar reads '● daemon offline' and the"
    echo "documented HTTP tool bridge is unavailable. Everything above is unaffected."
fi
echo ""
echo "To attach now:           tmux attach -t ${SESSION}"
echo "To detach (keep alive):  Ctrl-b + d"
echo "To stop daemon + session: bin/squad down"
echo "To kill only the session: tmux kill-session -t ${SESSION}  (daemon keeps running)"
echo "Unsafe autonomous mode:  SQUAD_UNSAFE_AUTONOMY=1 bash bin/launch-squad.sh"
echo "Pre-trust Codex MCPs:    SQUAD_TRUST_CODEX_MCPS=1 bash bin/launch-squad.sh"
echo ""
# Only prompt when run interactively. Without a tty (automated restart via
# `squad stop && squad up`, a background/detached launch), `read` blocks forever
# and the launcher never returns — the classic "restart didn't restart" hang.
if [[ -t 0 ]]; then
    read -p "Attach now? (y/n) " -n 1 -r
    echo ""
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        tmux attach -t "${SESSION}"
    fi
fi
