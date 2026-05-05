#!/bin/bash
# Watch model-lane status. Use `all` for the Chrono sidebar dashboard or pass
# a single lane for a focused tile.

set -uo pipefail

LANE="${1:-all}"
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"

case "${LANE}" in
    all|gpt-codex|claude|gemini|kimi) ;;
    *) echo "usage: $0 all|gpt-codex|claude|gemini|kimi"; exit 1 ;;
esac

color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
c256() { printf '\033[38;5;%sm%s\033[0m' "$1" "$2"; }
hide_cursor() { printf '\033[?25l'; }
show_cursor() { printf '\033[?25h'; }
home() { printf '\033[H'; }
clear_to_end() { printf '\033[J'; }

repeat_char() {
    local ch="$1" n="$2" out=""
    while [[ ${#out} -lt $n ]]; do out="${out}${ch}"; done
    printf '%s' "${out:0:$n}"
}

fit() {
    local text="$1" max="$2"
    if [[ ${#text} -le $max ]]; then
        printf '%-*s' "$max" "$text"
    elif [[ $max -le 3 ]]; then
        printf '%s' "${text:0:$max}"
    else
        printf '%s%-*s' "${text:0:$((max - 3))}..." 0 ""
    fi
}

frontmatter_field() {
    local file="$1" field="$2"
    awk -v key="$field" '/^---$/{p=!p; next} p && index($0, key ":") == 1 {sub("^[^:]+:[[:space:]]*", ""); print; exit}' "$file"
}

count_lane_tasks() {
    local lane="$1" dir="$2" count=0 f to_model task_id response ns_for_response
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/${dir}"/TASK-*.md; do
            [[ -f "$f" ]] || continue
            if [[ "$dir" == "inbox" ]]; then
                task_id="$(basename "$f" .md)"
                response="${VAULT_ROOT}/departments/${ns}/outbox/${task_id}-response.md"
                [[ -f "$response" ]] && continue
            fi
            to_model="$(frontmatter_field "$f" to_model)"
            [[ "$to_model" == "$lane" ]] && count=$((count + 1))
        done
    done
    echo "$count"
}

latest_result() {
    local lane="$1" best="" best_ts=0 f ts ns to_model line task_id task_file d
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
                [[ "$to_model" != "$lane" ]] && continue
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
    local lane="$1" f to_model specialist best="" best_ts=0 ts
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/active"/TASK-*.md; do
            [[ -f "$f" ]] || continue
            to_model="$(frontmatter_field "$f" to_model)"
            [[ "$to_model" != "$lane" ]] && continue
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
    local lane="$1" count=0 f task_id task_file to_model status ns d
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
                [[ "$to_model" != "$lane" ]] && continue
            fi
            status="$(frontmatter_field "$f" status)"
            echo "$status" | grep -qiE 'failed|error|blocked|needs_human' && count=$((count + 1))
        done
    done
    echo "$count"
}

draw_card() {
    local lane="$1" width="$2"
    local accent term_accent short tagline inbox active outbox blocked specialist last state state_color inner title pad
    accent="$(runtime_accent_color "$lane")"
    term_accent="$(runtime_terminal_color "$lane")"
    short="$(runtime_short_name "$lane")"
    tagline="$(runtime_tagline "$lane")"
    inbox=$(count_lane_tasks "$lane" inbox)
    active=$(count_lane_tasks "$lane" active)
    outbox=$(count_lane_tasks "$lane" outbox)
    blocked=$(blocked_count "$lane")
    specialist="$(active_specialist "$lane")"
    last="$(latest_result "$lane")"

    if [[ "$active" -gt 0 ]]; then
        state="WORKING"; state_color="38;5;118"
    elif [[ "$inbox" -gt 0 ]]; then
        state="PENDING"; state_color="38;5;214"
    elif [[ "$blocked" -gt 0 ]]; then
        state="BLOCKED"; state_color="38;5;203"
    else
        state="IDLE"; state_color="38;5;245"
    fi

    inner=$((width - 4))
    [[ "$inner" -lt 24 ]] && inner=24
    title="[${short}] ${state}"
    pad=$((inner - ${#title}))
    [[ "$pad" -lt 1 ]] && pad=1

    c256 "$accent" "╭─ "
    printf '\033[1;38;5;%sm%s\033[0m' "$accent" "$title"
    c256 "$accent" " $(repeat_char '─' "$pad")╮"
    printf '\n'

    printf '│ '
    color "${state_color}" "$(fit "$tagline" "$inner")"
    printf ' │\n'

    printf '│ '
    color "38;5;250" "work "
    printf ' %s │\n' "$(fit "${specialist:-none}" "$((inner - 6))")"
    printf '│ '
    color "38;5;250" "queue"
    printf ' %s │\n' "$(fit "in ${inbox}  active ${active}  out ${outbox}  blocked ${blocked}" "$((inner - 6))")"
    printf '│ '
    color "38;5;250" "last "
    printf ' %s │\n' "$(fit "${last:-none}" "$((inner - 6))")"

    c256 "$accent" "╰$(repeat_char '─' "$((width - 2))")╯"
    printf '\n'
}

trap 'show_cursor; printf "\n"; exit 0' INT TERM EXIT
hide_cursor
printf '\033[2J'

while true; do
    cols=$(tput cols 2>/dev/null || echo 70)
    width=$((cols - 1))
    [[ "$width" -lt 34 ]] && width=34
    [[ "$width" -gt 78 ]] && width=78

    home
    if [[ "$LANE" == "all" ]]; then
        printf '\033[48;5;236;38;5;45;1m MODEL LANES \033[0m'
        printf '  '
        color "38;5;245" "scroll: mouse / copy: drag or copy-mode"
        printf '\n\n'
        for lane in "${MODEL_LANES[@]}"; do
            draw_card "$lane" "$width"
            printf '\n'
        done
    else
        draw_card "$LANE" "$width"
    fi
    clear_to_end
    sleep 2
done
