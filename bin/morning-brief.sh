#!/bin/bash
# Morning brief generator — synthesizes everything from earlier nightly phases.
# This is what the operator reads first thing in the morning.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# shellcheck source=doctor-log-home.sh disable=SC1091
source "${VAULT_ROOT}/bin/doctor-log-home.sh" || exit $?
DATE="$(date -u +%Y-%m-%d)"
DAY_OF_WEEK="$(date -u +%A)"
BRIEF="${VAULT_ROOT}/_state/morning-briefs/${DATE}.md"
DAILY_LOG="${VAULT_ROOT}/_state/nightly-failures/${DATE}.log"

mkdir -p "$(dirname "${BRIEF}")"

# This script is the operator-facing reader of run-nightly.sh's phase verdict.
# It must run after every other nightly phase: the latest-run slice below resets
# at the last START marker so a clean same-day retry cannot inherit an earlier
# attempt's failures. If no START exists, absence is loud rather than rendered
# as the same clean status as a run with no findings.
NIGHTLY_STARTED=0
NIGHTLY_FAILED_PHASES=""
NIGHTLY_SKIPPED_PHASES=""
if [[ -f "${DAILY_LOG}" ]]; then
    NIGHTLY_STARTED="$(awk '
        /=== Claude-Vibe-Squad nightly start:/ { seen=1 }
        END { print seen ? 1 : 0 }
    ' "${DAILY_LOG}")"
    NIGHTLY_FAILED_PHASES="$(awk '
        /=== Claude-Vibe-Squad nightly start:/ { failures=""; seen=1; next }
        seen && /=== FAIL  phase:/ {
            phase=$0
            sub(/^.*=== FAIL  phase: /, "", phase)
            sub(/ .*/, "", phase)
            failures=failures (failures ? " " : "") phase
        }
        END { print failures }
    ' "${DAILY_LOG}")"
    NIGHTLY_SKIPPED_PHASES="$(awk '
        /=== Claude-Vibe-Squad nightly start:/ { skipped=""; seen=1; next }
        seen && /=== SKIP  phase:/ {
            phase=$0
            sub(/^.*=== SKIP  phase: /, "", phase)
            sub(/ .*/, "", phase)
            skipped=skipped (skipped ? " " : "") phase
        }
        END { print skipped }
    ' "${DAILY_LOG}")"
fi

# Pull info from earlier phase logs
DOCTOR_SUMMARY="${CHRONO_DOCTOR_LOG_DIR}/${DATE}-summary.json"
DOCTOR_REPORT="${CHRONO_DOCTOR_LOG_DIR}/${DATE}.md"
# The dream journal is written by the separate chrono repo (~/chrono, via
# `chrono dream run` at 05:00), which publishes into the vault under chrono/:
# the machine log is chrono/_state/dream-logs/<date>.log and the readable
# markdown view is chrono/dreams/<date>.md. This pointed at
# ${VAULT_ROOT}/_state/dream-logs/<date>.md -- wrong path segment and wrong
# extension -- so the brief silently showed no dream insight from the day the
# dream system moved. The stale in-repo _state/dream-logs/ stops at 2026-06-26,
# which dates the break. Fall back to the old path so an older vault still renders.
#
# 2026-08-16: the path segment was fixed above but the ROOT was not. "the vault"
# is CHRONO_VAULT_ROOT (~/Obsidian-Chrono), not VAULT_ROOT (this repo). Measured:
# ${CHRONO_VAULT_ROOT}/chrono/dreams holds 182 entries incl. today's, while
# ${VAULT_ROOT}/chrono/dreams holds 0 -- so every brief since the move printed
# "(no dream pass yet)" while the pass was running nightly and being discarded.
# run-nightly.sh:55 exports CHRONO_VAULT_ROOT with a default, so this is safe
# under launchd, which passes only PATH.
DREAM_LOG="${CHRONO_VAULT_ROOT}/chrono/dreams/${DATE}.md"
if [[ ! -f "${DREAM_LOG}" && -f "${VAULT_ROOT}/_state/dream-logs/${DATE}.md" ]]; then
    DREAM_LOG="${VAULT_ROOT}/_state/dream-logs/${DATE}.md"
fi

# Compute simple stats
ISSUES_COUNT=0
WARNINGS_COUNT=0
HEALTHY_COUNT=0
UNKNOWN_COUNT=0
SKIPPED_COUNT=0
ISSUES_LIST=""
WARNINGS_LIST=""
UNKNOWNS_LIST=""
SKIPPED_LIST=""
if [[ -f "${DOCTOR_SUMMARY}" ]]; then
    if command -v jq >/dev/null 2>&1; then
        ISSUES_COUNT=$(jq -r '.issue_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        WARNINGS_COUNT=$(jq -r '.warning_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        HEALTHY_COUNT=$(jq -r '.healthy_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        UNKNOWN_COUNT=$(jq -r '.unknown_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        SKIPPED_COUNT=$(jq -r '.skipped_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        ISSUES_LIST=$(jq -r '.issues[]? | "- 🔔 " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
        WARNINGS_LIST=$(jq -r '.warnings[]? | "- ⚠️ " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
        UNKNOWNS_LIST=$(jq -r '.unknowns[]? | "- ? COULD NOT RUN: " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
        SKIPPED_LIST=$(jq -r '.skipped[]? | "- ○ NOT APPLICABLE: " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
    fi
fi

# Build the brief
cat > "${BRIEF}" <<EOF
# Daily Brief — ${DAY_OF_WEEK} ${DATE}

EOF

echo "## Nightly automation" >> "${BRIEF}"
if [[ -n "${NIGHTLY_FAILED_PHASES}${NIGHTLY_SKIPPED_PHASES}" ]]; then
    echo "🔴 **NIGHTLY PHASE FAILURE** — the run completed, but maintenance was incomplete." >> "${BRIEF}"
    [[ -n "${NIGHTLY_FAILED_PHASES}" ]] \
        && echo "- Failed phases:${NIGHTLY_FAILED_PHASES}" >> "${BRIEF}"
    [[ -n "${NIGHTLY_SKIPPED_PHASES}" ]] \
        && echo "- Skipped phases:${NIGHTLY_SKIPPED_PHASES}" >> "${BRIEF}"
elif [[ "${NIGHTLY_STARTED}" -eq 1 ]]; then
    echo "🟢 **NIGHTLY CLEAN** — every scheduled maintenance phase ran successfully." >> "${BRIEF}"
else
    echo "🔴 **NIGHTLY NOT RUN** — no nightly start was recorded for ${DATE}." >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Status section
echo "## Status" >> "${BRIEF}"
echo "${HEALTHY_COUNT} pass / ${ISSUES_COUNT} failure / ${UNKNOWN_COUNT} could-not-run / ${SKIPPED_COUNT} not-applicable / ${WARNINGS_COUNT} warnings" >> "${BRIEF}"
if [[ "${ISSUES_COUNT}" -eq 0 ]] && [[ "${WARNINGS_COUNT}" -eq 0 ]] && [[ "${UNKNOWN_COUNT}" -eq 0 ]]; then
    echo "✓ No measured failures or indeterminate checks" >> "${BRIEF}"
else
    echo "" >> "${BRIEF}"
    if [[ -n "${ISSUES_LIST}" ]]; then
        echo "### Issues" >> "${BRIEF}"
        echo "${ISSUES_LIST}" >> "${BRIEF}"
        echo "" >> "${BRIEF}"
    fi
    if [[ -n "${WARNINGS_LIST}" ]]; then
        echo "### Warnings" >> "${BRIEF}"
        echo "${WARNINGS_LIST}" >> "${BRIEF}"
        echo "" >> "${BRIEF}"
    fi
    if [[ -n "${UNKNOWNS_LIST}" ]]; then
        echo "### Could not run — these are not passes" >> "${BRIEF}"
        echo "${UNKNOWNS_LIST}" >> "${BRIEF}"
        echo "" >> "${BRIEF}"
    fi
fi
if [[ -n "${SKIPPED_LIST}" ]]; then
    echo "" >> "${BRIEF}"
    echo "### Not applicable to this install" >> "${BRIEF}"
    echo "${SKIPPED_LIST}" >> "${BRIEF}"
    echo "" >> "${BRIEF}"
fi
if [[ "${ISSUES_COUNT}" -gt 0 ]] || [[ "${WARNINGS_COUNT}" -gt 0 ]] \
   || [[ "${UNKNOWN_COUNT}" -gt 0 ]] || [[ "${SKIPPED_COUNT}" -gt 0 ]]; then
    echo "Full report: [doctor log](<file://${DOCTOR_REPORT}>)" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Dream insights — surface gemini's notable patterns + reviewer verdict
echo "## 💭 Dream insights" >> "${BRIEF}"
if [[ -f "${DREAM_LOG}" ]]; then
    # Pull the journaler's "Notable Patterns" section (3-5 bullets)
    awk '
        /^## Notable Patterns/ { in_section=1; next }
        in_section && /^## / { exit }
        in_section { print }
    ' "${DREAM_LOG}" | head -10 >> "${BRIEF}"
    # Pull reviewer verdict
    verdict=$(awk '/^## Verdict/ {getline; print; exit}' "${DREAM_LOG}" | head -1)
    if [[ -n "${verdict}" ]]; then
        echo "" >> "${BRIEF}"
        echo "*Reviewer verdict: ${verdict} — see [full dream log](../dream-logs/${DATE}.md)*" >> "${BRIEF}"
    fi
else
    echo "*(no dream pass yet)*" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Active modes section (read from chrono/current.md or each namespace current.md)
echo "## 🔵 Active modes" >> "${BRIEF}"
active_count=0
for current_file in "${VAULT_ROOT}/chrono/current.md" "${VAULT_ROOT}/departments/"*/current.md; do
    [[ -f "${current_file}" ]] || continue
    # Look for Active Tasks section with non-"None" content (skip the header itself)
    if awk '/^## Active Tasks/{flag=1; next} /^## /{flag=0} flag' "${current_file}" 2>/dev/null \
        | grep -vqiE '^(none|$|---|none yet)' ; then
        rel="${current_file#"${VAULT_ROOT}/"}"
        owner=$(dirname "${rel}" | xargs basename)
        active_count=$((active_count + 1))
        echo "- **${owner}**: see [\`${rel}\`](../../${rel})" >> "${BRIEF}"
    fi
done
if [[ ${active_count} -eq 0 ]]; then
    echo "*(none - all model lanes idle)*" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Suggestions
echo "## Suggestions" >> "${BRIEF}"
echo "- Review status above" >> "${BRIEF}"
echo "- Type 'where are we' for full state summary" >> "${BRIEF}"
echo "" >> "${BRIEF}"

# Footer
cat >> "${BRIEF}" <<EOF
---
*Generated by morning-brief.sh at $(date -u +%FT%TZ)*
EOF

echo "Morning brief: ${BRIEF}"
exit 0
