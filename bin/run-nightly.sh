#!/bin/bash
# Claude-Vibe-Squad nightly routine — invoked by launchd LaunchAgent.
# Runs while operator is asleep / away.
#
# Phases:
#   0. Vault snapshot (FIRST — the only copy of squad memory; must predate any cleanup)
#   1. Doctor (CLI/MCP/browser/disk/usage health + bleed detection)
#   2. Registry reconciler (close landed responses and log drift)
#   3. Browser session keep-alive (refresh the persistent CDP browser session)
#   4. System cleanup (light)
#   5. Brain cleanup (KG contradiction sweep)
#   6. Feed sweep with cadence audit (vendor/practitioner/research/podcasts)
#   7. Content triage (score new items into depth / skim / drop)
#   8. Content processing (summarize depth items, headline-skim the rest)
#   9. Content synthesis (cluster depth summaries)
#   10. Daily morning brief generator (synthesizes everything)
#   11. Cross-day context (continuity for downstream)
#   Email brief is retained as a manual fallback, no longer invoked by default.
#   DEPRECATED: dream-light, improvement-extractor, newsletter-format, podcast-script, newsletter-tts, telegram-deliver.
#
# Each phase logs separately. Failures don't block subsequent phases.
# All output ends up in _state/morning-briefs/<date>.md as the unified brief.

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

mkdir -p "${LOG_DIR}" "${STATE_DIR}/morning-briefs" "${CHRONO_DOCTOR_LOG_DIR}" \
         "${STATE_DIR}/cleanup-logs" "${STATE_DIR}/dream-logs" \
         "${STATE_DIR}/blog-summaries" "${STATE_DIR}/podcast-briefs"

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
        fi
    else
        log "=== SKIP  phase: ${phase_name} (script not yet implemented: ${phase_script}) ==="
    fi
}

log "=== Claude-Vibe-Squad nightly start: ${DATE} ==="

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

run_phase "doctor"               "${VAULT_ROOT}/bin/doctor.sh"
run_phase "registry-reconciler"  "${VAULT_ROOT}/bin/registry-reconciler.sh"
run_phase "product-hygiene"      "${VAULT_ROOT}/bin/product-hygiene.sh"
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
run_phase "system-cleanup"       "${VAULT_ROOT}/bin/system-cleanup.sh"
run_phase "brain-cleanup"        "${VAULT_ROOT}/bin/brain-cleanup.sh"
run_phase "feed-sweep"           "${VAULT_ROOT}/bin/feed-sweep.sh"
run_phase "content-triage"       "${VAULT_ROOT}/bin/content-triage.sh"
run_phase "content-processing"   "${VAULT_ROOT}/bin/content-processing.sh"
run_phase "content-synthesis"    "${VAULT_ROOT}/bin/content-synthesis.sh"
run_phase "morning-brief"        "${VAULT_ROOT}/bin/morning-brief.sh"
# Email fallback retained but retired from default nightly delivery.

# Sunday: also run weekly deep
if [[ "$(date +%u)" == "7" ]]; then
    log "=== Sunday: running weekly deep run ==="
    run_phase "weekly-deep" "${VAULT_ROOT}/bin/run-weekly.sh"
fi

log "=== Claude-Vibe-Squad nightly complete: ${DATE} ==="
