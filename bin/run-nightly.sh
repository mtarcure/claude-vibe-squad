#!/bin/bash
# Claude-Vibe-Squad nightly routine — invoked by launchd LaunchAgent.
# Runs while operator is asleep / away.
#
# Phases:
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

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
STATE_DIR="${VAULT_ROOT}/_state"
DATE="$(date -u +%Y-%m-%d)"
LOG_DIR="${STATE_DIR}/nightly-failures"
DAILY_LOG="${LOG_DIR}/${DATE}.log"

mkdir -p "${LOG_DIR}" "${STATE_DIR}/morning-briefs" "${STATE_DIR}/doctor-logs" \
         "${STATE_DIR}/cleanup-logs" "${STATE_DIR}/dream-logs" \
         "${STATE_DIR}/blog-summaries" "${STATE_DIR}/podcast-briefs"

# Source operator secrets
if [[ -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    set +u
    # shellcheck disable=SC1091
    source "${HOME}/.config/shell/secrets.zsh"
    set -u
fi

export VAULT_ROOT
export STATE_DIR

log() {
    echo "[$(date -u +%FT%TZ)] $*" | tee -a "${DAILY_LOG}"
}

run_phase() {
    local phase_name="$1"
    local phase_script="$2"
    log "=== START phase: ${phase_name} ==="
    if [[ -x "${phase_script}" ]]; then
        if "${phase_script}"; then
            log "=== OK    phase: ${phase_name} ==="
        else
            log "=== FAIL  phase: ${phase_name} (continuing) ==="
        fi
    else
        log "=== SKIP  phase: ${phase_name} (script not yet implemented: ${phase_script}) ==="
    fi
}

log "=== Claude-Vibe-Squad nightly start: ${DATE} ==="

run_phase "doctor"               "${VAULT_ROOT}/bin/doctor.sh"
run_phase "registry-reconciler"  "${VAULT_ROOT}/bin/registry-reconciler.sh"
run_phase "product-hygiene"      "${VAULT_ROOT}/bin/product-hygiene.sh"
run_phase "memory-audit"         "${VAULT_ROOT}/bin/memory-audit.sh"
run_phase "sweep-active"         "${VAULT_ROOT}/bin/sweep-active.sh"
run_phase "browser-keep-alive"   "${VAULT_ROOT}/bin/browser-keep-alive.sh"
run_phase "system-cleanup"       "${VAULT_ROOT}/bin/system-cleanup.sh"
run_phase "brain-cleanup"        "${VAULT_ROOT}/bin/brain-cleanup.sh"
run_phase "feed-sweep"           "${VAULT_ROOT}/bin/feed-sweep.sh"
run_phase "content-triage"       "${VAULT_ROOT}/bin/content-triage.sh"
run_phase "content-processing"   "${VAULT_ROOT}/bin/content-processing.sh"
run_phase "content-synthesis"    "${VAULT_ROOT}/bin/content-synthesis.sh"
run_phase "morning-brief"        "${VAULT_ROOT}/bin/morning-brief.sh"
run_phase "cross-day-context"    "${VAULT_ROOT}/bin/cross-day-context.sh"
# Email fallback retained but retired from default nightly delivery.
# Manual fallback: bash bin/email-brief.sh

# Sunday: also run weekly deep
if [[ "$(date +%u)" == "7" ]]; then
    log "=== Sunday: running weekly deep run ==="
    run_phase "weekly-deep" "${VAULT_ROOT}/bin/run-weekly.sh"
fi

log "=== Claude-Vibe-Squad nightly complete: ${DATE} ==="
