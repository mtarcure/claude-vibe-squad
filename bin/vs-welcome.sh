#!/usr/bin/env bash
# vs-welcome.sh — Chrono greeting, printed before Claude Code launches in the
# chrono pane. Establishes "you are talking to the coordinator" context so the
# operator lands on the squad's identity, and Claude Code's own banner reads as
# "engine started" beneath it.
#
# Auth policy (matches launch-squad.sh MEDIA_AUTH_PREFIX): unset the Anthropic /
# Gemini / Google API keys so Claude falls back to the Max-plan OAuth session,
# but KEEP OPENAI_API_KEY — the chrono pane hosts the chrono-media-studio
# plugin, and Sora needs that key. Do NOT unset all four here (the handoff
# shorthand did; it would silently break media generation in this pane).
set -u

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# shellcheck source=../shared/lead-windows.sh disable=SC1091
source "${VAULT_ROOT}/shared/lead-windows.sh"

# Operator-facing lane facts come from the two routing authorities, never from
# a copied count or list in this banner. If the authorities disagree, print no
# guessed roster; validate-specialists/doctor will name the underlying defect.
routed_lanes_from_map() {
    awk -F '\t' '
        NR == 1 {
            for (i = 1; i <= NF; i++) if ($i ~ /_lane$/) lane_column[i] = 1
            next
        }
        {
            for (i in lane_column) if ($i != "" && $i != "none") lanes[$i] = 1
        }
        END { for (lane in lanes) print lane }
    ' "${VAULT_ROOT}/shared/specialist-runtime-map.tsv" 2>/dev/null | sort
}

routed_lanes_from_profiles() {
    awk -F '\t' '
        NR == 1 {
            for (i = 1; i <= NF; i++) if ($i == "lane") lane_column = i
            next
        }
        lane_column && $lane_column != "" && $lane_column != "none" {
            lanes[$lane_column] = 1
        }
        END { for (lane in lanes) print lane }
    ' "${VAULT_ROOT}/shared/registries/profiles.tsv" 2>/dev/null | sort
}

ROUTED_LANE_IDS="$(routed_lanes_from_map)"
PROFILE_LANE_IDS="$(routed_lanes_from_profiles)"
ROUTED_LANE_NAMES=()
if [[ -n "${ROUTED_LANE_IDS}" && "${ROUTED_LANE_IDS}" == "${PROFILE_LANE_IDS}" ]]; then
    while IFS= read -r _lane; do
        [[ -n "${_lane}" ]] && ROUTED_LANE_NAMES+=("$(runtime_window_name "${_lane}")")
    done <<< "${ROUTED_LANE_IDS}"
fi
ROUTED_LANE_COUNT="${#ROUTED_LANE_NAMES[@]}"
ROUTED_LANE_LIST=""
for _lane in ${ROUTED_LANE_NAMES[@]+"${ROUTED_LANE_NAMES[@]}"}; do
    [[ -n "${ROUTED_LANE_LIST}" ]] && ROUTED_LANE_LIST+=" · "
    ROUTED_LANE_LIST+="${_lane}"
done
CHRONO_WINDOW="$(lead_window_name chrono)"
WATCHERS_WINDOW="$(lead_window_name watchers)"
unset _lane

# --- Chrono coordinator pidfile (coordinator-side, LIFE-01) -----------------
# Record WHO and WHERE the live coordinator is, so bin/squad-stop.sh DISCOVERS
# it instead of assuming the pane. This is the ONE writer (CLAUDE.md rule 10),
# and it lives HERE because this is the only place that knows the coordinator's
# real identity: the `exec ... claude` at the end of this script replaces THIS
# process image with claude, so $$ (this bash) IS the PID claude will run as and
# its kernel start time is claude's own. bin/launch-squad.sh used to plant this
# from outside with the pane's SHELL pid, which squad-stop's */claude* reader
# then rejected -- written then disbelieved; a cross-family review rejected that.
#
# Shape follows the environment: inside tmux ($TMUX set) this is the nudgeable
# PANE at ${SESSION}:chrono; started as a background job (e.g. `claude daemon`,
# no tmux) it is the un-nudgeable BACKGROUND-JOB shape (no pane). squad-stop
# routes its three outcomes off that shape.
#
# The start-time fingerprint uses the SAME `ps -o lstart=` normalization as
# bin/squad-stop.sh's pid_start_time(), so writer and reader agree on identity;
# the CoordinatorPidfile semantic round-trip test drives this writer into that
# reader on a live process to prove it. Atomic mktemp+rename so a concurrent
# squad-stop reads a whole file, never a half-written one. Best-effort: on
# failure squad-stop falls back to inspecting the pane directly.
if [[ -n "${TMUX:-}" ]]; then
    _vs_session="$(tmux display-message -p '#S' 2>/dev/null || true)"
    [[ -n "${_vs_session}" ]] || _vs_session="${SQUAD_SESSION:-squad}"
    _vs_shape="pane"
    _vs_target="${_vs_session}:chrono"
else
    _vs_session="${SQUAD_SESSION:-squad}"
    _vs_shape="background-job"
    _vs_target=""
fi
CHRONO_COORDINATOR_PIDFILE="${CHRONO_COORDINATOR_PIDFILE:-${VAULT_ROOT}/_state/runtime/chrono-coordinator/${_vs_session}.pid}"
write_chrono_coordinator_pidfile() {
    local pid="$1" shape="$2" target="$3" dir staged start
    dir="$(dirname -- "${CHRONO_COORDINATOR_PIDFILE}")"
    mkdir -p "${dir}" || return 1
    # Same normalization as bin/squad-stop.sh pid_start_time() -- one home.
    start="$(ps -o lstart= -p "${pid}" 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')"
    staged="$(mktemp "${CHRONO_COORDINATOR_PIDFILE}.XXXXXX")" || return 1
    {
        printf 'pid %s\n' "${pid}"
        printf 'shape %s\n' "${shape}"
        printf 'target %s\n' "${target}"
        printf 'start %s\n' "${start}"
    } > "${staged}" || { rm -f "${staged}"; return 1; }
    mv -f "${staged}" "${CHRONO_COORDINATOR_PIDFILE}" || { rm -f "${staged}"; return 1; }
}
if ! write_chrono_coordinator_pidfile "$$" "${_vs_shape}" "${_vs_target}"; then
    echo "WARNING: could not write the Chrono coordinator pidfile ${CHRONO_COORDINATOR_PIDFILE}; 'squad stop' will fall back to inspecting the ${_vs_session}:chrono pane directly." >&2
fi

# --- Coordinator crash capture (LIFE-03) ------------------------------------
# The operator reported a crash on EXIT of this coordinator that a prior
# six-sink search (TASK-2026-08-30-1020) could not find recorded ANYWHERE
# durable -- and it named, as an unclosed gap, that the operator's interactive
# terminal (where a dying stack trace prints) is persisted by no sink. So make
# the coordinator record its own last breath: below, claude's stderr is teed
# into a per-session file created here, under a header that timestamps and
# identifies the session.
#
# prepare_coordinator_exit_log <session> <shape> <target> <pid>: echo the path
# of a freshly-created capture file carrying that header, or nothing (rc1) if
# the durable dir cannot be prepared. Pure filesystem + header write -- no
# claude, no exec, no signalling -- so scripts/python/tests/test_squad_stop_reaping.py
# drives it directly with synthetic args (the LIFE-03 hard boundary forbids
# running vs-welcome.sh itself, which execs claude). Best-effort and FAIL-SAFE:
# every failure returns rc1 so the caller falls back to the bare, unteed exec --
# a capture failure can never touch the coordinator's own launch or exit.
#
# What it deliberately does NOT capture, and why: claude stays the pane shell's
# DIRECT exec child (the tee becomes claude's child, never its parent), so the
# `pgrep -P` coordinator test in shared/chrono-pane.sh -- and thus squad-stop /
# outbox-watcher / squad-monitor discovery -- is byte-for-byte unchanged. A
# direct-child exec has no waiting parent, so the numeric exit CODE/signal is
# not recordable here; claude's own dying stderr and the session boundary are.
# The exit code is owned by claude's real parent, the pane shell that runs this
# script (bin/launch-squad.sh); see the LIFE-03 response for that follow-up.
CHRONO_COORDINATOR_EXIT_DIR="${CHRONO_COORDINATOR_EXIT_DIR:-${VAULT_ROOT}/_state/runtime/chrono-coordinator/exit}"
prepare_coordinator_exit_log() {
    local session="$1" shape="$2" target="$3" pid="$4" dir stamp candidate start
    dir="${CHRONO_COORDINATOR_EXIT_DIR:-${VAULT_ROOT}/_state/runtime/chrono-coordinator/exit}"
    mkdir -p "${dir}" 2>/dev/null || return 1
    stamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || printf 'nodate')"
    candidate="${dir}/${session}-${stamp}-${pid}.log"
    # Same `ps -o lstart=` normalization as the pidfile writer / squad-stop's
    # pid_start_time(), so a reader can tie this record to that identity.
    start="$(ps -o lstart= -p "${pid}" 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')"
    {
        printf 'coordinator-session-start %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf 'nodate')"
        printf 'pid %s\n' "${pid}"
        printf 'shape %s\n' "${shape}"
        printf 'target %s\n' "${target:-<none>}"
        printf 'start %s\n' "${start:--}"
        printf 'claude-stderr-follows ----------\n'
    } > "${candidate}" 2>/dev/null || return 1
    printf '%s\n' "${candidate}"
}

# Locked palette — colour74 cyan accent, colour252 near-white, colour240 dim.
c() { printf '\033[38;5;%sm' "$1"; }
CYAN=$(c 74); TEXT=$(c 252); DIM=$(c 240); R=$'\033[0m'; B=$'\033[1m'

clear
printf '\n'
if [[ "${ROUTED_LANE_COUNT}" -gt 0 ]]; then
    printf '  %s%s▎ vibe-squad%s  %s· %s lanes standing by%s\n\n' "$CYAN" "$B" "$R" "$DIM" "${ROUTED_LANE_COUNT}" "$R"
else
    printf '  %s%s▎ vibe-squad%s  %s· lane roster unavailable%s\n\n' "$CYAN" "$B" "$R" "$DIM" "$R"
fi
printf '  %sYou are talking to %s%schrono%s%s — the coordinator.%s\n' "$TEXT" "$R" "$CYAN" "$R" "$TEXT" "$R"
if [[ "${ROUTED_LANE_COUNT}" -gt 0 ]]; then
    printf '  %sPeers (%s) carry routed specialist work.%s\n\n' "$DIM" "${ROUTED_LANE_LIST}" "$R"
fi
printf '  %s──────────────────────────────────────────────%s\n' "$DIM" "$R"
printf '  %sfan-out%s  %s"send this to every lane"%s\n'    "$TEXT" "$R" "$DIM" "$R"
printf '  %sroute%s    %s"ask gemini about X"%s\n'         "$TEXT" "$R" "$DIM" "$R"
printf '  %sstatus%s   %s"what is each lane on?"%s\n'      "$TEXT" "$R" "$DIM" "$R"
printf '  %speek%s     %sC-b g key guide (%s / %s) · C-b Space reset · C-b d detach%s\n' "$TEXT" "$R" "$DIM" "${CHRONO_WINDOW}" "${WATCHERS_WINDOW}" "$R"
printf '  %s/stop%s    %sinterrupt the active dispatch%s\n' "$TEXT" "$R" "$DIM" "$R"
printf '  %s──────────────────────────────────────────────%s\n\n' "$DIM" "$R"

sleep 1

# Launch Claude Code as the coordinator. acceptEdits (not bypass) because the
# operator watches this pane directly; --add-dir grants the vault. Keep
# OPENAI_API_KEY (media), drop the rest so Claude uses the Max-plan session.
#
# LIFE-03: when a per-session capture file was prepared, tee claude's stderr
# into it so the next crash-on-exit leaves a durable trace; the trailing `>&2`
# keeps that stderr visible to the operator exactly as before. claude is STILL
# `exec`ed (direct child; the tee is ITS child), so detection, the pidfile
# identity, stdin, the controlling terminal and the process group are all
# unchanged. If no capture file was prepared, the bare exec in the else branch
# is the unchanged, pre-LIFE-03 launch -- the fail-safe path a broken capture
# falls back to, so instrumentation can never break the normal launch or exit.
_vs_exit_log="$(prepare_coordinator_exit_log "${_vs_session}" "${_vs_shape}" "${_vs_target}" "$$" 2>/dev/null || true)"
if [[ -n "${_vs_exit_log}" ]]; then
    exec env -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
        "${HOME}/.local/bin/claude" \
            --permission-mode acceptEdits \
            --model opus \
            --effort xhigh \
            --add-dir "${VAULT_ROOT}" \
        2> >(tee -a "${_vs_exit_log}" >&2)
else
    exec env -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
        "${HOME}/.local/bin/claude" \
            --permission-mode acceptEdits \
            --model opus \
            --effort xhigh \
            --add-dir "${VAULT_ROOT}"
fi
