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
WIDTH=$((WIDTH - 2))
[[ ${WIDTH} -lt 30 ]] && WIDTH=30
[[ ${WIDTH} -gt 70 ]] && WIDTH=70

accent="$(runtime_terminal_color "$LANE")"
short="$(runtime_short_name "$LANE")"
display="$(runtime_display_name "$LANE")"

color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
bar() {
    local ch="${1:-=}" n="$WIDTH" out=""
    while [[ ${#out} -lt $n ]]; do out="${out}${ch}"; done
    printf '%s\n' "${out:0:$n}"
}
fit() {
    local text="$1" max="$2"
    if [[ ${#text} -le $max ]]; then
        printf '%s' "$text"
    elif [[ $max -le 3 ]]; then
        printf '%s' "${text:0:$max}"
    else
        printf '%s...' "${text:0:$((max - 3))}"
    fi
}

frontmatter_field() {
    local file="$1" field="$2"
    awk -v key="$field" '/^---$/{p=!p; next} p && index($0, key ":") == 1 {sub("^[^:]+:[[:space:]]*", ""); print; exit}' "$file"
}

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

active_specialist() {
    local f to_model specialist best="" best_ts=0 ts
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/active"/TASK-*.md; do
            [[ -f "$f" ]] || continue
            to_model="$(frontmatter_field "$f" to_model)"
            [[ "$to_model" != "$LANE" ]] && continue
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            if [[ "$ts" -gt "$best_ts" ]]; then
                best_ts="$ts"
                specialist="$(frontmatter_field "$f" specialist)"
                best="${specialist:-unknown}"
            fi
        done
    done
    echo "$best"
}

blocked_count() {
    local count=0 f task_id task_file to_model status
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            if [[ -n "$task_file" ]]; then
                to_model="$(frontmatter_field "$task_file" to_model)"
                [[ "$to_model" != "$LANE" ]] && continue
            fi
            status="$(frontmatter_field "$f" status)"
            echo "$status" | grep -qiE 'failed|error|blocked|needs_human' && count=$((count + 1))
        done
    done
    echo "$count"
}

while true; do
    WIDTH=$(tput cols 2>/dev/null || echo 42)
    WIDTH=$((WIDTH - 2))
    [[ ${WIDTH} -lt 30 ]] && WIDTH=30
    [[ ${WIDTH} -gt 70 ]] && WIDTH=70

    inbox=$(count_lane_tasks inbox)
    active=$(count_lane_tasks active)
    outbox=$(count_lane_tasks outbox)
    blocked=$(blocked_count)
    specialist="$(active_specialist)"
    last="$(latest_result)"
    if [[ "$active" -gt 0 ]]; then
        state="WORKING"
        state_color="32"
    elif [[ "$inbox" -gt 0 ]]; then
        state="PENDING"
        state_color="33"
    elif [[ "$blocked" -gt 0 ]]; then
        state="BLOCKED"
        state_color="31"
    else
        state="IDLE"
        state_color="90"
    fi

    clear
    color "1;${accent}" "$(bar '=')"
    printf '\n'
    color "1;${accent}" "${short}"
    printf '  %s  ' "$display"
    color "1;${state_color}" "$state"
    printf '\n'
    printf 'active: %s\n' "$(fit "${specialist:-none}" "$((WIDTH - 8))")"
    printf 'queue : in=%s act=%s out=%s block=%s\n' "$inbox" "$active" "$outbox" "$blocked"
    printf 'last  : %s\n' "$(fit "${last:-none}" "$((WIDTH - 8))")"
    color "1;${accent}" "$(bar '=')"
    printf '\n'
    sleep 2
done
