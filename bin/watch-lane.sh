#!/bin/bash
# Watch a model lane by aggregating all namespace mailboxes whose TASK
# frontmatter names this lane in `to_model`.

set -uo pipefail

LANE="${1:-}"
WIDTH="${2:-}"
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"

case "${LANE}" in
    gpt-codex|claude|gemini|kimi) ;;
    *) echo "usage: $0 <gpt-codex|claude|gemini|kimi> [width]"; exit 1 ;;
esac

[[ -z "${WIDTH}" ]] && WIDTH=$(tput cols 2>/dev/null || echo 42)
[[ ${WIDTH} -lt 30 ]] && WIDTH=30

count_lane_tasks() {
    local dir="$1" count=0 f to_model
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/${dir}"/TASK-*.md; do
            [[ -f "$f" ]] || continue
            to_model="$(awk '/^---$/{p=!p; next} p && /^to_model:/ {sub(/^to_model:[[:space:]]*/, ""); print; exit}' "$f")"
            [[ "$to_model" == "$LANE" ]] && count=$((count + 1))
        done
    done
    echo "$count"
}

latest_result() {
    local best="" best_ts=0 f ts ns to_model line
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            if [[ -n "$task_file" ]]; then
                to_model="$(awk '/^---$/{p=!p; next} p && /^to_model:/ {sub(/^to_model:[[:space:]]*/, ""); print; exit}' "$task_file")"
                [[ "$to_model" != "$LANE" ]] && continue
            fi
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            if [[ "$ts" -gt "$best_ts" ]]; then
                best_ts="$ts"
                line=$(awk '/^---$/{c++; if(c==2){body=1; next}} body && /^# /{sub(/^# */,""); print; exit}' "$f")
                [[ -z "$line" ]] && line="$(basename "$f")"
                best="$line"
            fi
        done
    done
    echo "$best"
}

while true; do
    inbox=$(count_lane_tasks inbox)
    active=$(count_lane_tasks active)
    outbox=$(count_lane_tasks outbox)
    last="$(latest_result)"
    clear
    printf '%s\n' "$(runtime_display_name "$LANE")"
    printf 'mailbox: inbox=%s active=%s outbox=%s\n' "$inbox" "$active" "$outbox"
    if [[ "$active" -gt 0 ]]; then
        echo "state: working"
    elif [[ "$inbox" -gt 0 ]]; then
        echo "state: pending"
    else
        echo "state: idle"
    fi
    printf 'last: %s\n' "${last:-none}"
    sleep 2
done
