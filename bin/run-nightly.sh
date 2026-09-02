#!/bin/bash
# Claude-Vibe-Squad nightly routine — invoked by launchd LaunchAgent.
# Runs while operator is asleep / away.
#
# The phase list is the `run_phase` calls below, read top to bottom; each one
# carries its own reason and its own ordering constraint. A numbered copy of
# that list used to live here and had to be hand-synced, which it was not: it
# named four content phases deleted 2026-08-16 and omitted four that do run. A
# summary that can disagree with the thing it summarises is worse than no
# summary (CLAUDE.md hard rule 10: one fact, one home).
#   Sunday only: the weekly deep run (bin/run-weekly.sh).
#   Email brief is retained as a manual fallback, no longer invoked by default.
#   DEPRECATED: dream-light, improvement-extractor, newsletter-format, podcast-script, newsletter-tts, telegram-deliver.
#
# Each phase logs separately. Failures don't block subsequent phases, but they
# DO deny the run a zero exit: see the phase-outcome accounting above run_phase.
# The operator verdict lands in _state/morning-briefs/<date>.md. Correction to
# 2600f02e's commit body: that change claimed the brief repeated launchd's
# verdict, but the brief did not read this log and ran before the summary. The
# claim was not true until the reader and ordering below were added.

set -uo pipefail  # NOT -e — we want phases to continue even if one fails

# launchd's spawn shell needs ~/.local/bin (claude, kimi) + brew paths.
# Child phase scripts inherit this PATH.
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# shellcheck source=doctor-log-home.sh disable=SC1091
source "${VAULT_ROOT}/bin/doctor-log-home.sh" || exit $?
STATE_DIR="${VAULT_ROOT}/_state"
DATE="$(date -u +%Y-%m-%d)"
LOG_DIR="${STATE_DIR}/nightly-failures"
DAILY_LOG="${LOG_DIR}/${DATE}.log"

# blog-summaries and podcast-briefs are deliberately absent: their producer went
# with the feed pipeline on 2026-08-16, and re-creating them every night would
# turn bin/doctor.sh's honest "artifact volume was NOT measured" into a silent
# measurement of zero.
mkdir -p "${LOG_DIR}" "${STATE_DIR}/morning-briefs" "${CHRONO_DOCTOR_LOG_DIR}" \
         "${STATE_DIR}/cleanup-logs" "${STATE_DIR}/dream-logs"

# Source operator secrets
if [[ -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    set +u
    # shellcheck disable=SC1091
    source "${HOME}/.config/shell/secrets.zsh"
    set -u
fi
export CHRONO_VAULT_ROOT="${CHRONO_VAULT_ROOT:-${HOME}/Obsidian-Chrono}"

export VAULT_ROOT
export STATE_DIR

log() {
    echo "[$(date -u +%FT%TZ)] $*" | tee -a "${DAILY_LOG}"
}

# Phase outcomes are accumulated rather than acted on where they happen, because
# the two halves of "did the night go well" have different answers. Whether to
# KEEP GOING: yes -- the phases are independent maintenance jobs, so a failed
# vault snapshot must not cost the night its log rotation, hence no `set -e`
# above, and that stays. Whether to REPORT SUCCESS: no. Until 2026-08-31 this
# script exited 0 unconditionally, so launchd recorded a successful run while
# product-hygiene had failed at 10:02:50 (_state/nightly-failures/2026-08-31.log).
# A nightly that cannot report failure manufactures evidence of health, and the
# morning brief previously had no reader that could correct it.
FAILED_PHASES=""
SKIPPED_PHASES=""
MORNING_BRIEF_FAILED=0

# A missing pushed artifact cannot distinguish "nothing happened" from "all
# clear." Leave the next dated brief in an explicit NOT RUN state; tomorrow's
# invocation replaces it with RUNNING before doing work and morning-brief.sh
# replaces that with the final reader view. The write is atomic because this is
# shared operator state, not an incidental log.
write_brief_placeholder() {
    local brief_date="$1"
    local verdict="$2"
    local explanation="$3"
    local brief_path="${STATE_DIR}/morning-briefs/${brief_date}.md"
    local temporary

    temporary="$(mktemp "${brief_path}.tmp.XXXXXX")" || return 1
    if ! {
        printf '# Daily Brief — %s\n\n' "${brief_date}"
        printf '## Nightly automation\n'
        printf '%s\n' "${verdict}"
        printf '%s\n' "${explanation}"
    } > "${temporary}"; then
        rm -f -- "${temporary}"
        return 1
    fi
    sync "${temporary}" 2>/dev/null || sync
    mv -f "${temporary}" "${brief_path}"
}

run_phase() {
    local phase_name="$1"
    local phase_script="$2"
    # Extra arguments pass through to the phase script. Needed because some
    # phases are no-ops in their default mode -- prune-board-worktrees.sh
    # defaults to a dry-run report and reclaims nothing without --apply, so
    # wiring it argument-less would have scheduled a phase that could never do
    # its job while logging OK every night.
    shift 2 || true
    log "=== START phase: ${phase_name} ==="
    if [[ -x "${phase_script}" ]]; then
        if "${phase_script}" "$@"; then
            log "=== OK    phase: ${phase_name} ==="
        else
            log "=== FAIL  phase: ${phase_name} (continuing) ==="
            FAILED_PHASES="${FAILED_PHASES} ${phase_name}"
            [[ "${phase_name}" == "morning-brief" ]] && MORNING_BRIEF_FAILED=1
        fi
    else
        log "=== SKIP  phase: ${phase_name} (script not yet implemented: ${phase_script}) ==="
        SKIPPED_PHASES="${SKIPPED_PHASES} ${phase_name}"
        [[ "${phase_name}" == "morning-brief" ]] && MORNING_BRIEF_FAILED=1
    fi
}

log "=== Claude-Vibe-Squad nightly start: ${DATE} ==="
if ! write_brief_placeholder \
    "${DATE}" \
    '🟡 **NIGHTLY RUNNING** — the scheduled run started but has no final verdict yet.' \
    'If this remains after the run window, the nightly started but did not finish.'; then
    log "=== FAIL  phase: nightly-verdict-writer (continuing) ==="
    FAILED_PHASES="${FAILED_PHASES} nightly-verdict-writer"
fi

if NEXT_DATE="$(date -u -v+1d +%Y-%m-%d 2>/dev/null)"; then
    :
else
    NEXT_DATE="$(date -u -d 'tomorrow' +%Y-%m-%d)"
fi
NEXT_BRIEF="${STATE_DIR}/morning-briefs/${NEXT_DATE}.md"
if [[ ! -e "${NEXT_BRIEF}" ]] && ! write_brief_placeholder \
    "${NEXT_DATE}" \
    '🔴 **NIGHTLY NOT RUN** — no scheduled run has started for this date.' \
    'This dead-man placeholder is replaced when the next nightly starts.'; then
    log "=== FAIL  phase: nightly-verdict-writer (continuing) ==="
    FAILED_PHASES="${FAILED_PHASES} nightly-verdict-writer"
fi

# FIRST, before anything that mutates or cleans: the vault is the only copy of
# squad memory and had no backup at all until 2026-08-09. A snapshot taken after
# system-cleanup or brain-cleanup would preserve whatever those phases did to it.
run_phase "vault-snapshot"       "${VAULT_ROOT}/bin/vault-snapshot.sh"

# The snapshot tool never deletes an older archive on purpose -- "the cleanup
# deleted the backups" is the failure it exists to prevent -- so growth is
# reported here rather than silently reclaimed. Each archive is ~273 MB.
snapshot_dir="${VAULT_SNAPSHOT_DEST:-${HOME}/vault-snapshots}"
if [[ -d "${snapshot_dir}" ]]; then
    snapshot_count="$(find "${snapshot_dir}" -name 'chrono-vault-*.tar.gz' | wc -l | tr -d ' ')"
    snapshot_size="$(du -sh "${snapshot_dir}" 2>/dev/null | cut -f1)"
    log "vault snapshots: ${snapshot_count} archive(s), ${snapshot_size} total in ${snapshot_dir}"
    if [[ "${snapshot_count}" -gt 30 ]]; then
        log "WARNING: over 30 vault snapshots retained. Pruning is an operator decision; nothing here deletes them."
    fi
fi

# --deep, because this is the run that can afford it. bin/launch-squad.sh gates
# on doctor under SQUAD_DOCTOR_TIMEOUT (45s) and therefore runs the fast path,
# which declines the ~127s public-export hygiene gate and says so. Nightly is
# unattended and untimed, so it is where that check keeps running daily instead
# of becoming a flag nobody passes. run_phase already forwards extra arguments.
run_phase "doctor"               "${VAULT_ROOT}/bin/doctor.sh" --deep
run_phase "registry-reconciler"  "${VAULT_ROOT}/bin/registry-reconciler.sh"
# doctor --deep above already runs and reports the publication audit. Do not
# invoke product-hygiene a second time here: its default mode is the operator's
# strict local cleanup-decision gate, while --public-export certifies the
# projector's candidate tree rather than this private daily-driver checkout.
run_phase "memory-audit"         "${VAULT_ROOT}/bin/memory-audit.sh"
run_phase "sweep-active"         "${VAULT_ROOT}/bin/sweep-active.sh"
run_phase "browser-keep-alive"   "${VAULT_ROOT}/bin/browser-keep-alive.sh"
# Board scratch and settled worktrees. The reaper existed but nothing invoked
# it -- measured 2026-08-15: 430 orphaned attempt roots and 4.2 GiB in /tmp/vs,
# because the create path and the teardown path are not the same path (a lane
# that times out, is killed, or blocks never tears down, so precisely the failed
# attempts leak). Its own guard keeps live attempts and rescues unpromoted
# artifacts, so it is safe to run unattended alongside in-flight lanes.
run_phase "prune-board-scratch"  "${VAULT_ROOT}/bin/prune-board-worktrees.sh" --apply
# Append-only logs with no other bound: the daemon's launchd stdout/stderr and
# the tmux pane captures. Measured 2026-08-17 at 34 MB, 31 MB and 81 MB, all
# still growing; _state/monitor/monitor-err.log already records "No space left
# on device" from 2026-07-31.
#
# Deliberately AFTER doctor, not before. doctor.sh's retry-storm scan reads the
# last hour of each tmux log; rotating first would hand it a freshly emptied
# file carrying a fresh mtime, and it would count zero failures and call that a
# clean hour. Rotation is also report-only without --apply.
run_phase "rotate-logs"          "${VAULT_ROOT}/bin/rotate-logs.sh" --apply
run_phase "system-cleanup"       "${VAULT_ROOT}/bin/system-cleanup.sh"
run_phase "brain-cleanup"        "${VAULT_ROOT}/bin/brain-cleanup.sh"
# The feed/triage/processing/synthesis pipeline was removed 2026-08-16. It was
# ~3,000 lines encoding a content workflow -- fetch feeds, rank items against
# operator interests, then "run a Claude analysis pass" (its own words). That is
# judgment expressed as a program, and judgment belongs in a specialist brief
# under project mode, which already covers content work. Nothing referenced it
# from any mode or specialist brief; it was parallel machinery.
# Sunday: also run weekly deep
if [[ "$(date +%u)" == "7" ]]; then
    log "=== Sunday: running weekly deep run ==="
    run_phase "weekly-deep" "${VAULT_ROOT}/bin/run-weekly.sh"
fi

# This is deliberately the LAST phase. A reader placed at its old position
# could not see weekly-deep or the final phase set and therefore could still
# print a clean night while later work failed. The brief reads this run's FAIL
# and SKIP records directly; run-nightly supplies a minimal fallback only when
# the reader itself is the failed phase.
run_phase "morning-brief"        "${VAULT_ROOT}/bin/morning-brief.sh"
# Email fallback retained but retired from default nightly delivery.

if [[ "${MORNING_BRIEF_FAILED}" -eq 1 ]]; then
    write_brief_placeholder \
        "${DATE}" \
        '🔴 **NIGHTLY PHASE FAILURE** — the run completed, but maintenance was incomplete.' \
        "Failed or skipped phases:${FAILED_PHASES}${SKIPPED_PHASES}" || true
fi

log "=== Claude-Vibe-Squad nightly complete: ${DATE} ==="

# A failed phase and a phase that never ran are both maintenance that did not
# happen, so both deny the run a zero exit. Separate lines because they need
# different fixes: FAIL is a broken phase, SKIP a missing or non-executable
# script -- the quieter of the two failures. All 13 phase scripts exist and are
# executable, so counting SKIP costs a healthy run nothing. Space-joined strings
# rather than arrays: phase names never contain spaces, and macOS ships bash 3.2
# where "${empty[*]}" is an unbound-variable error under `set -u`.
[[ -n "${FAILED_PHASES}" ]] && log "=== FAILED phases:${FAILED_PHASES} ==="
[[ -n "${SKIPPED_PHASES}" ]] && log "=== SKIPPED phases:${SKIPPED_PHASES} ==="
[[ -z "${FAILED_PHASES}${SKIPPED_PHASES}" ]] || exit 1
exit 0
