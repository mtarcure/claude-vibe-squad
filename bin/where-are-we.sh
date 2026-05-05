#!/bin/bash
# Quick state aggregator. Answers "where are we?" without diving through dirs.
# Run from anywhere; reads filesystem state and prints a one-screen summary.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"
DATE="$(date +%Y-%m-%d)"

color() { echo -e "\033[${1}m${2}\033[0m"; }
hr()    { color '0;36' '─────────────────────────────────────────────────────────────'; }

color '1;36' "═════════════════════════════════════════════════════════════"
color '1;36' "  Claude-Vibe-Squad — where are we?  ($(date '+%Y-%m-%d %H:%M'))"
color '1;36' "═════════════════════════════════════════════════════════════"
echo ""

# Doctor verdict (today)
hr
color '1;33' '## DOCTOR'
SUM="${VAULT_ROOT}/_state/doctor-logs/${DATE}-summary.json"
if [[ -f "${SUM}" ]] && command -v jq >/dev/null 2>&1; then
    jq -r '"  healthy: \(.healthy_count) │ warnings: \(.warning_count) │ issues: \(.issue_count)"' "${SUM}"
    jq -r '.warnings[]? | "  ⚠ " + .' "${SUM}"
    jq -r '.issues[]? | "  🔔 " + .' "${SUM}"
else
    echo "  (no doctor run today — bash bin/doctor.sh to refresh)"
fi
echo ""

# Active-task registry
hr
color '1;33' '## ACTIVE REGISTRY'
REGISTRY="${VAULT_ROOT}/_state/active-tasks.json"
if [[ -f "${REGISTRY}" ]] && command -v jq >/dev/null 2>&1; then
    in_flight=$(jq '[to_entries[] | select(.value.status == "in-flight")] | length' "${REGISTRY}" 2>/dev/null || echo 0)
    complete=$(jq '[to_entries[] | select(.value.status == "complete")] | length' "${REGISTRY}" 2>/dev/null || echo 0)
    echo "  in-flight: ${in_flight} │ complete: ${complete}"
    jq -r 'to_entries[] | select(.value.status == "in-flight") | "  " + .key + " → " + (.value.to_lead // "?") + " scope=" + ((.value.write_scope // []) | join(","))' "${REGISTRY}" 2>/dev/null
elif [[ -f "${REGISTRY}" ]]; then
    echo "  ${REGISTRY} exists; install jq for structured summary"
else
    echo "  (no active-task registry yet)"
fi
echo ""

# Active state per Lead
hr
color '1;33' '## LEAD STATE'
for f in "${VAULT_ROOT}/chrono/current.md" "${VAULT_ROOT}/departments"/*/current.md; do
    [[ -f "$f" ]] || continue
    role=$(dirname "$f" | xargs basename)
    line=$(awk '/^\*\(/{print; exit}; /^Updated:/{print; exit}' "$f" | head -1)
    color '0;36' "  ${role}: ${line}"
done
echo ""

# Mailbox state
hr
color '1;33' '## MAILBOX'
for lead in coding security content sysmgmt research; do
    in=$(ls "${VAULT_ROOT}/departments/${lead}/inbox/" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    act=$(ls "${VAULT_ROOT}/departments/${lead}/active/" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    out=$(ls "${VAULT_ROOT}/departments/${lead}/outbox/" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    arc=$(ls "${VAULT_ROOT}/departments/${lead}/archive/" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    if [[ ${in} -gt 0 || ${act} -gt 0 || ${out} -gt 0 ]]; then
        color '0;35' "  ${lead}: inbox=${in} active=${act} outbox=${out} (archive: ${arc})"
    else
        echo "  ${lead}: idle (archive: ${arc})"
    fi
done
echo ""

# Pending replies and contradictions
hr
color '1;33' '## RESPONSE DRIFT'
for lead in coding security content sysmgmt research; do
    outbox_dir="${VAULT_ROOT}/departments/${lead}/outbox"
    pending=$(find "${outbox_dir}" -maxdepth 1 -name 'TASK-*-response.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    [[ "${pending}" -gt 0 ]] && color '0;35' "  ${lead}: ${pending} response file(s) awaiting Chrono surfacing"
done
if [[ -f "${REGISTRY}" ]] && command -v jq >/dev/null 2>&1; then
    while IFS=$'\t' read -r task_id lead; do
        [[ -n "${task_id}" && -n "${lead}" ]] || continue
        if [[ -f "${VAULT_ROOT}/departments/${lead}/outbox/${task_id}-response.md" ]]; then
            color '1;31' "  CONTRADICTION: ${task_id} is in-flight in registry but response exists in ${lead}/outbox"
        fi
    done < <(jq -r 'to_entries[] | select(.value.status == "in-flight") | [.key, .value.to_lead] | @tsv' "${REGISTRY}" 2>/dev/null)
fi
echo ""

# Recent dispatches
hr
color '1;33' '## RECENT DISPATCH (last 10)'
DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
if [[ -f "${DISPATCH_LOG}" ]]; then
    tail -10 "${DISPATCH_LOG}" 2>/dev/null | while read -r line; do
        if command -v jq >/dev/null 2>&1; then
            echo "$line" | jq -r '"  \(.ts) → \(.to_lead): \(.task_id)"'
        else
            echo "  $line"
        fi
    done
else
    echo "  (no dispatches yet)"
fi
echo ""

# Today's content
hr
color '1;33' '## NEW SINCE YESTERDAY'
blogs=$(ls "${VAULT_ROOT}/_state/blog-summaries/${DATE}-"*.md 2>/dev/null | wc -l | tr -d ' ')
pods=$(ls "${VAULT_ROOT}/_state/podcast-briefs/${DATE}-"*.md 2>/dev/null | wc -l | tr -d ' ')
echo "  blog summaries: ${blogs}"
echo "  podcast briefs: ${pods}"
brief="${VAULT_ROOT}/_state/morning-briefs/${DATE}.md"
[[ -f "${brief}" ]] && echo "  morning brief:  ${brief}" || echo "  morning brief:  (not yet generated)"
echo ""

# Pending dream proposals
hr
color '1;33' '## PENDING DREAM PROPOSALS'
proposals_dir="${VAULT_ROOT}/_state/dream-proposals"
if [[ -d "${proposals_dir}" ]]; then
    pending=0
    for p in "${proposals_dir}"/*.md; do
        [[ -f "$p" ]] || continue
        if grep -q '^status: pending' "$p" 2>/dev/null; then
            pending=$((pending + 1))
            title=$(awk '/^# /{sub(/^# /, ""); print; exit}' "$p")
            echo "  • ${title}"
        fi
    done
    [[ ${pending} -eq 0 ]] && echo "  (none pending)"
else
    echo "  (none — dream is in shadow mode)"
fi
echo ""

# Tmux pane state
hr
color '1;33' '## SQUAD TMUX'
if tmux has-session -t squad 2>/dev/null; then
    color '0;32' '  ✓ session "squad" is up'
    for lead in chrono coding security content sysmgmt research watchers; do
        w="$(lead_window_name "$lead")"
        if ! tmux list-windows -t squad -F '#{window_name}' 2>/dev/null | grep -qx "$w"; then
            color '1;31' "    ${w}: missing window"
            continue
        fi
        last=$(tmux capture-pane -t "squad:${w}" -p 2>/dev/null | grep -v '^$' | tail -1 | tr -d '\r' | cut -c1-70)
        echo "    $(lead_display_name "$lead") [${w}]: ${last}"
    done
else
    color '1;31' '  ✗ session "squad" is NOT running — bash bin/launch-squad.sh'
fi
echo ""

color '1;36' "═════════════════════════════════════════════════════════════"
echo "  Per-pane scrollback log: ${VAULT_ROOT}/_state/tmux-logs/<lead>.log"
echo "  Full dispatch history:   ${VAULT_ROOT}/_state/dispatch-log.jsonl"
echo "  Morning brief:           ${VAULT_ROOT}/_state/morning-briefs/${DATE}.md"
color '1;36' "═════════════════════════════════════════════════════════════"
