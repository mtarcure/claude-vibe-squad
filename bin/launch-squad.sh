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
        echo "        bar, and the /summarize endpoint the weekly-review routine calls."
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
    bash -c 'while true; do bash "$1" all; rc=$?; echo "watcher supervisor restart: kind=outbox namespace=all rc=$rc" >&2; sleep 2; done' \
        "watcher-supervisor:outbox:all" "${VAULT_ROOT}/bin/outbox-watcher.sh" &
    watcher_children+=("$!")
    bash -c 'while true; do python3 "$1" reconcile-sweep; rc=$?; echo "watcher supervisor restart: kind=reconcile-sweep rc=$rc" >&2; sleep 2; done' \
        'watcher-supervisor:reconcile-sweep' "${VAULT_ROOT}/scripts/python/swarm_runtime.py" &
    watcher_children+=("$!")
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

# Verify tmux is installed
missing=()
for dep in tmux fswatch jq curl claude codex gemini kimi; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
done
if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "ERROR: missing required command(s): ${missing[*]}"
    echo "Fix: install/login the missing CLIs, and install core tools with: brew install jq tmux fswatch"
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
    doctor_rc=0
    doctor_report="$(timeout "${SQUAD_DOCTOR_TIMEOUT:-45}" \
        "${VAULT_ROOT}/bin/doctor.sh" 2>&1)" || doctor_rc=$?
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
# it's running. pgrep-guarded so we never spawn duplicate pollers.
if ! pgrep -f 'vs-lane-status.sh' >/dev/null 2>&1; then
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

    # --- Claude-Code-grade status bar (locked palette, poller-fed) ---------
    # Live data comes from /tmp/vs-*.status (poller), so tmux does ZERO network
    # work per render even at status-interval 1. Palette: colour74 cyan accent,
    # colour252 near-white, colour240 dim, colour214 amber, colour234/233 bg.
    tmux set-option -g status on
    tmux set-option -g status-position bottom
    tmux set-option -g status 2                       # two rows: live data + hints
    tmux set-option -g status-interval 1
    tmux set-option -g status-style      'fg=colour252,bg=colour234'
    tmux set-option -g status-left-length 60
    tmux set-option -g status-right-length 180
    tmux set-option -g status-left "#[fg=colour74,bold] vibesquad #[fg=colour240]· #(cat /tmp/vs-daemon.status 2>/dev/null) "
    tmux set-option -g status-right "#(cat /tmp/vs-swarm.status 2>/dev/null) #[fg=colour240]· #[fg=colour214]#(jq -r '\"pass:\"+((.healthy_count // 0)|tostring)+\" failure:\"+((.issue_count // 0)|tostring)+\" could-not-run:\"+((.unknown_count // 0)|tostring)+\" not-applicable:\"+((.skipped_count // 0)|tostring)+\" warnings:\"+((.warning_count // 0)|tostring)' ${CHRONO_DOCTOR_LOG_DIR_SHELL}/\$(date +%%Y-%%m-%%d)-summary.json 2>/dev/null || echo 'doctor:could-not-run') #[fg=colour240]· #[fg=colour252]%H:%M "
    tmux set-option -g "status-format[1]" "#[bg=colour233,fg=colour240] Tab / C-b <n>: lanes · C-b 0: chrono · C-b z: zoom · C-b Space: reset · C-b [: scroll · C-b d: detach "

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
WATCHER_FLEET_LOCK="${SESSION}-watcher-fleet-launch"
WATCHER_FLEET_LOCK_HELD=0

watcher_script_count() {
    local kind="$1" script="$2" namespace="$3" marker
    marker="watcher-supervisor:${kind}:${namespace}"
    ps -axo pid=,ppid=,command= | awk -v script="$script" -v namespace="$namespace" -v marker="$marker" '
        {
            pid=$1
            parent[pid]=$2
            $1=""; $2=""
            sub(/^[[:space:]]+/, "", $0)
            command[pid]=$0
        }
        END {
            for (pid in command) {
                executable=command[pid]
                sub(/[[:space:]].*$/, "", executable)
                sub(/^.*\//, "", executable)
                arguments=command[pid]
                sub(/^[^[:space:]]+[[:space:]]+/, "", arguments)
                if (executable == "bash" && arguments == script " " namespace \
                    && index(command[parent[pid]], marker) > 0) count++
            }
            print count + 0
        }
    '
}

watcher_supervisor_count() {
    local marker="$1"
    ps -axo command= | python3 -c '
import os
import shlex
import sys

marker = sys.argv[1]
count = 0
for raw in sys.stdin:
    try:
        argv = shlex.split(raw.strip())
    except ValueError:
        continue
    if len(argv) >= 4 and os.path.basename(argv[0]) == "bash" \
            and argv[1] == "-c" and marker in argv[2:]:
        count += 1
print(count)
' "$marker"
}

watcher_fleet_report() {
    printf 'outbox[all]=%s/%s (root/supervisor)\n' \
        "$(watcher_script_count outbox "${VAULT_ROOT}/bin/outbox-watcher.sh" all)" \
        "$(watcher_supervisor_count "watcher-supervisor:outbox:all")"
    printf 'reconcile-sweep=%s\n' \
        "$(watcher_supervisor_count watcher-supervisor:reconcile-sweep)"
}

watcher_fleet_healthy() {
    local index5_name
    index5_name="$(tmux list-windows -t "$SESSION" -F '#{window_index}|#{window_name}' 2>/dev/null | awk -F'|' '$1 == 5 {print $2}')"
    [[ "$index5_name" == "$WATCHERS_WIN" ]] || return 1
    # No aggregate "watcher-supervisor:" count here. watcher_supervisor_count
    # matches the marker as an EXACT argv element (`marker in argv[2:]`), and the
    # spawned markers are "watcher-supervisor:outbox:all" and
    # "watcher-supervisor:reconcile-sweep" -- so a bare "watcher-supervisor:"
    # prefix matches nothing and the aggregate clause could never be satisfied.
    #
    # That bug predates the consolidation (it compared against
    # ${#COMPATIBILITY_NAMESPACES[@]} + 1, equally unreachable) and is why the
    # fleet never converged: health returned 1, the deterministic repair killed
    # and respawned, and each cycle leaked processes until 43 were running.
    # The two exact-marker checks below fully determine fleet health on their own.
    [[ "$(watcher_supervisor_count "watcher-supervisor:outbox:all")" == 1 ]] || return 1
    [[ "$(watcher_script_count outbox "${VAULT_ROOT}/bin/outbox-watcher.sh" all)" == 1 ]] || return 1
    [[ "$(watcher_supervisor_count watcher-supervisor:reconcile-sweep)" == 1 ]] || return 1
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

def watcher_seed(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = os.path.basename(tokens[0])
    outbox_script = f"{root}/bin/outbox-watcher.sh"
    runtime_script = f"{root}/scripts/python/swarm_runtime.py"
    mailbox_leaf = any(
        token.startswith(f"{root}/departments/")
        and (token.endswith("/inbox") or token.endswith("/outbox"))
        for token in tokens
    )
    return (
        any(token.startswith("watcher-supervisor:") for token in tokens)
        or (executable in {"bash", "sh", "zsh"} and outbox_script in tokens)
        or (
            executable.startswith("python")
            and runtime_script in tokens
            and "reconcile-sweep" in tokens
        )
        or (executable == "fswatch" and mailbox_leaf)
    )

targets = watcher_roots | {
    pid for pid, (_ppid, command) in processes.items() if watcher_seed(command)
}

# A named seed owns all descendants. Ascend only through shell ancestors that
# are not protected lane/coordinator roots; this catches bare historical loops.
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
        if executable not in {"bash", "zsh", "sh"} and "watcher-supervisor:" not in command:
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
    tmux wait-for -L "$WATCHER_FLEET_LOCK"
    WATCHER_FLEET_LOCK_HELD=1
    trap 'if [[ "$WATCHER_FLEET_LOCK_HELD" == 1 ]]; then tmux wait-for -U "$WATCHER_FLEET_LOCK" 2>/dev/null || true; WATCHER_FLEET_LOCK_HELD=0; fi' EXIT
    trap 'if [[ "$WATCHER_FLEET_LOCK_HELD" == 1 ]]; then tmux wait-for -U "$WATCHER_FLEET_LOCK" 2>/dev/null || true; WATCHER_FLEET_LOCK_HELD=0; fi; exit 130' HUP INT TERM
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
        tmux wait-for -U "$WATCHER_FLEET_LOCK"
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
    tmux wait-for -U "$WATCHER_FLEET_LOCK"
    WATCHER_FLEET_LOCK_HELD=0
    trap - EXIT HUP INT TERM
    return "$rc"
)

# If the session already exists, re-assert globals (the server is up) and attach.
# Only attach when we actually have a terminal — otherwise `tmux attach` hangs
# forever with no tty, which is exactly what breaks automated restarts.
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    if ! ensure_watcher_fleet; then
        echo "ERROR: watcher fleet repair failed; coordinator and lane panes were left untouched" >&2
        exit 1
    fi
    apply_squad_globals
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
tmux new-session -d -s "${SESSION}" -n "chrono" -c "${VAULT_ROOT}/chrono"
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

echo "✓ Session '${SESSION}' created:"
echo "  0: chrono     (Coordinator + live dashboard sidebar)"
echo "  5: ${WATCHERS_WIN} (1 consolidated outbox watcher, all ${#COMPATIBILITY_NAMESPACES[@]} namespaces + reconciliation sweep)"
echo "  (per-model lane windows retired — specialists run as fresh board-spawned CLIs per task)"
echo ""
echo "Board dispatch is the default: specialists spawn as fresh capability-scoped CLIs per task."
echo "Chrono window has the live dashboard sidebar. Toggle off: bin/sidebar-off.sh"
if [[ "${DAEMON_PRESENT}" == "0" ]]; then
    echo "Running WITHOUT the optional daemon: the status bar reads '● daemon offline' and the"
    echo "weekly-review summary is unavailable. Everything above is unaffected."
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
