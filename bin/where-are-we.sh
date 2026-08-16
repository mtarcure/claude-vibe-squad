#!/bin/bash
# Quick state aggregator. Answers "where are we?" without diving through dirs.
# Run from anywhere; reads filesystem state and prints a one-screen summary.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
# shellcheck source=doctor-log-home.sh disable=SC1091
source "${VAULT_ROOT}/bin/doctor-log-home.sh" || exit $?
source "${VAULT_ROOT}/shared/lead-windows.sh"
DATE="$(date -u +%Y-%m-%d)"

color() { echo -e "\033[${1}m${2}\033[0m"; }
hr()    { color '0;36' '─────────────────────────────────────────────────────────────'; }

color '1;36' "═════════════════════════════════════════════════════════════"
color '1;36' "  Claude-Vibe-Squad — where are we?  ($(date '+%Y-%m-%d %H:%M'))"
color '1;36' "═════════════════════════════════════════════════════════════"
echo ""

# Doctor verdict (today)
hr
color '1;33' '## DOCTOR'
SUM="${CHRONO_DOCTOR_LOG_DIR}/${DATE}-summary.json"
if [[ -f "${SUM}" ]] && command -v jq >/dev/null 2>&1; then
    jq -r '"  pass: \(.healthy_count // 0) │ failure: \(.issue_count // 0) │ could-not-run: \(.unknown_count // 0) │ not-applicable: \(.skipped_count // 0) │ warnings: \(.warning_count // 0)"' "${SUM}"
    jq -r '.warnings[]? | "  ⚠ " + .' "${SUM}"
    jq -r '.issues[]? | "  🔔 " + .' "${SUM}"
    jq -r '.unknowns[]? | "  ? COULD NOT RUN: " + .' "${SUM}"
    jq -r '.skipped[]? | "  ○ NOT APPLICABLE: " + .' "${SUM}"
else
    echo "  (no doctor run today — bash bin/doctor.sh to refresh)"
fi
echo ""

# Active-task registry. Status classification belongs to registry_view(); this
# surface only renders its live/deferred/unclassified partition. Keeping the
# one computed result for both this section and RESPONSE DRIFT prevents the two
# panes from disagreeing about which tasks are live.
registry_view_rows() {
    if ! command -v python3 >/dev/null 2>&1; then
        printf 'UNAVAILABLE\tpython3 is unavailable\n'
        return 0
    fi
    VAULT_ROOT="${VAULT_ROOT}" PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY' 2>/dev/null || printf 'UNAVAILABLE\tregistry_view failed\n'
import os
import sys

root = os.environ["VAULT_ROOT"]
sys.path.insert(0, os.path.join(root, "scripts", "python"))
from chrono_state.registry import LIVE_REGISTRY, registry_view

if not LIVE_REGISTRY.is_file():
    print("UNAVAILABLE\tlive registry is absent")
    raise SystemExit(0)

view = registry_view()

def clean(value):
    return str(value if value not in (None, "") else "?").replace("\t", " ").replace("\n", " ")

lines = [
    "\t".join(
        (
            "SUMMARY",
            str(len(view["live"])),
            str(len(view["deferred"])),
            str(sum(view["unclassified"].values())),
        )
    )
]
for kind in ("live", "deferred"):
    for task in view[kind]:
        lines.append(
            "\t".join(
                (
                    kind.upper(),
                    clean(task.get("id")),
                    clean(task.get("state")),
                    clean(task.get("to_model")),
                    clean(task.get("specialist")),
                    clean(task.get("next_action")),
                )
            )
        )
for status, count in sorted(view["unclassified"].items(), key=lambda item: clean(item[0])):
    lines.append("\t".join(("UNCLASSIFIED", clean(status), str(count))))
print("\n".join(lines))
PY
}

REGISTRY_VIEW_ROWS="$(registry_view_rows)"
hr
color '1;33' '## ACTIVE REGISTRY'
while IFS=$'\t' read -r kind first second third fourth fifth; do
    case "${kind}" in
        SUMMARY)
            echo "  live: ${first} │ deferred: ${second} │ could-not-determine status: ${third}"
            ;;
        LIVE)
            echo "  ${first} [${second}] -> ${third} / ${fourth} — ${fifth}"
            ;;
        DEFERRED)
            color '0;35' "  DEFERRED: ${first} [${second}] -> ${third} / ${fourth} — ${fifth}"
            ;;
        UNCLASSIFIED)
            color '1;31' "  COULD NOT DETERMINE: ${second} task(s) have unclassified status '${first}'"
            ;;
        UNAVAILABLE)
            color '1;31' "  COULD NOT DETERMINE registry status: ${first}"
            ;;
    esac
done <<< "${REGISTRY_VIEW_ROWS}"
echo ""

# Active state
hr
color '1;33' '## CURRENT STATE'
for f in "${VAULT_ROOT}/chrono/current.md" "${VAULT_ROOT}/departments"/*/current.md; do
    [[ -f "$f" ]] || continue
    role=$(dirname "$f" | xargs basename)
    line=$(awk '/^\*\(/{print; exit}; /^Updated:/{print; exit}' "$f" | head -1)
    color '0;36' "  ${role}: ${line}"
done
echo ""

# Mailbox state by source namespace
hr
color '1;33' '## MAILBOX'
for lead in "${COMPATIBILITY_NAMESPACES[@]}"; do
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
for lead in "${COMPATIBILITY_NAMESPACES[@]}"; do
    outbox_dir="${VAULT_ROOT}/departments/${lead}/outbox"
    pending=$(find "${outbox_dir}" -maxdepth 1 -name 'TASK-*-response.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    [[ "${pending}" -gt 0 ]] && color '0;35' "  ${lead}: ${pending} response file(s) awaiting Chrono surfacing"
done
while IFS=$'\t' read -r kind task_id _state _model _specialist next_action; do
    [[ "${kind}" == "LIVE" && -n "${task_id}" \
       && "${next_action}" == "await completion / verify" ]] || continue
    for response in "${VAULT_ROOT}"/departments/*/outbox/"${task_id}-response.md"; do
        [[ -f "${response}" ]] || continue
        namespace="$(basename -- "$(dirname -- "$(dirname -- "${response}")")")"
        color '1;31' "  CONTRADICTION: ${task_id} is live in registry but response exists in ${namespace}/outbox"
    done
done <<< "${REGISTRY_VIEW_ROWS}"
echo ""

# Recent dispatches
hr
color '1;33' '## RECENT DISPATCH (last 10)'
DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
if [[ -f "${DISPATCH_LOG}" ]]; then
    tail -10 "${DISPATCH_LOG}" 2>/dev/null | while read -r line; do
        if command -v jq >/dev/null 2>&1; then
            echo "$line" | jq -r '"  \(.ts) -> \(.model_lane // .to_model // "?") / \(.specialist // "?"): \(.task_id)"'
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
    for lane in chrono gpt-codex claude gemini kimi watchers; do
        w="$(runtime_window_name "$lane")"
        if ! tmux list-windows -t squad -F '#{window_name}' 2>/dev/null | grep -qx "$w"; then
            color '1;31' "    ${w}: missing window"
            continue
        fi
        last=$(tmux capture-pane -t "squad:${w}" -p 2>/dev/null | grep -v '^$' | tail -1 | tr -d '\r' | cut -c1-70)
        echo "    $(runtime_display_name "$lane") [${w}]: ${last}"
    done
else
    color '1;31' '  ✗ session "squad" is NOT running — bash bin/launch-squad.sh'
fi
echo ""

color '1;36' "═════════════════════════════════════════════════════════════"
echo "  Per-pane scrollback log: ${VAULT_ROOT}/_state/tmux-logs/<model-lane>.log"
echo "  Full dispatch history:   ${VAULT_ROOT}/_state/dispatch-log.jsonl"
echo "  Morning brief:           ${VAULT_ROOT}/_state/morning-briefs/${DATE}.md"
color '1;36' "═════════════════════════════════════════════════════════════"
