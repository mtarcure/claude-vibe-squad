#!/bin/bash
# Watch model-lane status. Use `all` for the Chrono sidebar dashboard or pass
# a single lane for a focused tile.

set -uo pipefail

LANE="${1:-all}"
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="${SQUAD_SESSION:-squad}"
SQUAD_WATCH_COMPACT="${SQUAD_WATCH_COMPACT:-0}"
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

pane_cols() {
    local cols
    if [[ -n "${TMUX_PANE:-}" ]] && command -v tmux >/dev/null 2>&1; then
        cols="$(tmux display-message -p -t "${TMUX_PANE}" '#{pane_width}' 2>/dev/null || true)"
        [[ "$cols" =~ ^[0-9]+$ ]] && { echo "$cols"; return; }
    fi
    cols="${COLUMNS:-}"
    [[ "$cols" =~ ^[0-9]+$ ]] && { echo "$cols"; return; }
    tput cols 2>/dev/null || echo 70
}

pane_rows() {
    local rows
    if [[ -n "${TMUX_PANE:-}" ]] && command -v tmux >/dev/null 2>&1; then
        rows="$(tmux display-message -p -t "${TMUX_PANE}" '#{pane_height}' 2>/dev/null || true)"
        [[ "$rows" =~ ^[0-9]+$ ]] && { echo "$rows"; return; }
    fi
    rows="${LINES:-}"
    [[ "$rows" =~ ^[0-9]+$ ]] && { echo "$rows"; return; }
    tput lines 2>/dev/null || echo 40
}

repeat_char() {
    local ch="$1" n="$2" out=""
    while [[ ${#out} -lt $n ]]; do out="${out}${ch}"; done
    printf '%s' "${out:0:$n}"
}

fit() {
    # Fit text to a fixed DISPLAY width. Pad by character count (not bytes): in a
    # UTF-8 locale ${#text} and string slicing count characters, but printf's
    # '%-*s' pads by bytes — so multibyte glyphs (· ▸ — …, all single-column)
    # would under-pad and drift the right border. Pad with explicit ASCII spaces.
    local text="$1" max="$2"
    local len=${#text}
    if (( len <= max )); then
        printf '%s%*s' "$text" "$((max - len))" ""
    elif (( max <= 3 )); then
        printf '%s' "${text:0:max}"
    else
        printf '%s...' "${text:0:max - 3}"
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

# Specialist of the lane's most recently completed task — gives idle lanes some
# specialist context ("who ran last") instead of going blank.
last_specialist() {
    local lane="$1" best_file="" best_ts=0 f ts ns to_model task_id task_file d
    for ns in "${SOURCE_NAMESPACES[@]}"; do
        for f in "${VAULT_ROOT}/departments/${ns}/outbox"/TASK-*-response.md; do
            [[ -f "$f" ]] || continue
            task_id="$(basename "$f" | sed 's/-response.md$//')"
            task_file=""
            for d in inbox active archive; do
                [[ -f "${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md" ]] && task_file="${VAULT_ROOT}/departments/${ns}/${d}/${task_id}.md"
            done
            [[ -z "$task_file" ]] && continue
            to_model="$(frontmatter_field "$task_file" to_model)"
            [[ "$to_model" != "$lane" ]] && continue
            ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
            if [[ "$ts" -gt "$best_ts" ]]; then best_ts="$ts"; best_file="$task_file"; fi
        done
    done
    [[ -n "$best_file" ]] && frontmatter_field "$best_file" specialist
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

# Tools a specialist is configured to use, from specialist-runtime-map.tsv
# (col 5 required_tools_mcp_api + col 7 preferred_tools), joined with ' · '.
# Empty when the specialist is unmapped or "none".
tools_for_specialist() {
    local spec="$1" row req pref out
    [[ -z "$spec" || "$spec" == "none" ]] && return 0
    row=$(awk -F'\t' -v s="$spec" '$1==s{print; exit}' "${VAULT_ROOT}/shared/specialist-runtime-map.tsv" 2>/dev/null)
    [[ -z "$row" ]] && return 0
    req=$(printf '%s' "$row" | cut -f5)
    pref=$(printf '%s' "$row" | cut -f7)
    out="$req"
    [[ -n "$pref" && "$pref" != "none" ]] && out="${out:+${out},}${pref}"
    printf '%s' "${out//,/ · }"
}

# Path of the newest task packet routed to this lane, searching the given dirs
# in order (active/ first, then inbox/ — so a queued PENDING task still resolves).
_newest_lane_task() {  # _newest_lane_task LANE DIR...
    local lane="$1"; shift
    local dir ns f to_model ts best="" best_ts=0
    for dir in "$@"; do
        for ns in "${SOURCE_NAMESPACES[@]}"; do
            for f in "${VAULT_ROOT}/departments/${ns}/${dir}"/TASK-*.md; do
                [[ -f "$f" ]] || continue
                to_model="$(frontmatter_field "$f" to_model)"
                [[ "$to_model" != "$lane" ]] && continue
                ts=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
                if [[ "$ts" -gt "$best_ts" ]]; then best_ts="$ts"; best="$f"; fi
            done
        done
    done
    printf '%s' "$best"
}

# Specialist assigned to the lane's current (active, else queued) task.
lane_specialist() {
    local f; f="$(_newest_lane_task "$1" active inbox)"
    [[ -z "$f" ]] && return 0
    frontmatter_field "$f" specialist
}

# H1 title of the lane's current (active, else queued) task — a short
# natural-language "what is this lane working on". Empty if none.
active_task_objective() {
    local f; f="$(_newest_lane_task "$1" active inbox)"
    [[ -z "$f" ]] && return 0
    awk '/^---$/{c++; next} c>=2 && /^# /{sub(/^# */,""); print; exit}' "$f"
}

# Best-effort "what is the lane doing right now": scrape the pane, find the most
# recent activity marker (Claude ✻ / ⏺, Codex "Working/Worked for"), clean the
# line and return it. Empty when no marker is visible — we never guess, so the
# caller simply omits the line. Deliberately CLI-agnostic (approach A).
live_now_line() {
    local lane="$1" raw line
    command -v tmux >/dev/null 2>&1 || return 0
    raw=$(tmux capture-pane -t "${SESSION}:${lane}" -p 2>/dev/null) || return 0
    line=$(printf '%s\n' "$raw" | grep -nE '✻|⏺|─ Work(ing|ed) for' | tail -1 | cut -d: -f2-)
    [[ -z "$line" ]] && return 0
    # Strip ANSI, box-drawing chars, and leading spinner/prompt glyphs; collapse.
    line=$(printf '%s' "$line" \
        | sed -E $'s/\033\\[[0-9;]*m//g' \
        | tr -d '─│╭╮╰╯▄▀' \
        | sed -E 's/^[[:space:]✻⏺❯›▸*•]+//; s/[[:space:]]+/ /g; s/^ //; s/ $//')
    printf '%s' "$line"
}

# One labeled interior line, echoed (not printed) so the caller can collect rows
# into an array and count them for height-fill. Value is fit/truncated to width.
fmt_row() {  # fmt_row INNER LABEL VALUE
    local inner="$1" label="$2" value="$3"
    printf '│ \033[38;5;250m%-5s\033[0m %s │' "$label" "$(fit "$value" "$((inner - 6))")"
}

# Full-width state-colored line (used for the idle tagline row).
fmt_tagline() {  # fmt_tagline INNER STATE_COLOR TEXT
    local inner="$1" sc="$2" text="$3"
    printf '│ \033[%sm%s\033[0m │' "$sc" "$(fit "$text" "$inner")"
}

# Emoji-labeled row: "│ <emoji> <value> │". Our label emojis are single-codepoint
# but render TWO display columns, so we fit the value to width-7 (interior width-2
# minus: leading space, emoji=2 cols, space, trailing space) to keep the right
# rail aligned. Value must be single-width text (no emoji) — it's padded by chars.
fmt_erow() {  # fmt_erow WIDTH EMOJI VALUE
    local width="$1" emoji="$2" value="$3"
    printf '│ %s %s │' "$emoji" "$(fit "$value" "$((width - 7))")"
}

draw_card() {
    local lane="$1" width="$2" height="${3:-0}"
    local accent term_accent short tagline inbox active outbox blocked specialist last state state_color inner title pad
    accent="$(runtime_accent_color "$lane")"
    term_accent="$(runtime_terminal_color "$lane")"
    short="$(runtime_short_name "$lane")"
    tagline="$(runtime_tagline "$lane")"
    inbox=$(count_lane_tasks "$lane" inbox)
    active=$(count_lane_tasks "$lane" active)
    outbox=$(count_lane_tasks "$lane" outbox)
    blocked=$(blocked_count "$lane")
    specialist="$(lane_specialist "$lane")"
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

    # State → emoji (single-codepoint, 2-column wide glyphs) + lowercase labels.
    local state_emoji name_lc state_lc
    case "$state" in
        WORKING) state_emoji='🟢' ;;
        PENDING) state_emoji='🟡' ;;
        BLOCKED) state_emoji='🔴' ;;
        *)       state_emoji='⚪' ;;
    esac
    name_lc=$(printf '%s' "$short" | tr '[:upper:]' '[:lower:]')
    state_lc=$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]')

    # Collect interior rows into an array so we can count them for height-fill.
    # Active lanes (WORKING/PENDING) get spec/task/tools/now; idle/blocked keep
    # tagline + queue + last (prefixed with the last specialist for context).
    # Emoji labels; empty rows omitted.
    local -a body=()
    if [[ "$state" == "WORKING" || "$state" == "PENDING" ]]; then
        local objective tools_line now_line
        objective="$(active_task_objective "$lane")"
        tools_line="$(tools_for_specialist "$specialist")"
        now_line="$(live_now_line "$lane")"
        body+=("$(fmt_erow "$width" 🧑 "${specialist:-none}")")
        [[ -n "$objective" ]]  && body+=("$(fmt_erow "$width" 📋 "$objective")")
        [[ -n "$tools_line" ]] && body+=("$(fmt_erow "$width" 🔧 "$tools_line")")
        [[ -n "$now_line" ]]   && body+=("$(fmt_erow "$width" ⚡ "$now_line")")
        body+=("$(fmt_erow "$width" 📥 "${inbox} queued · ${active} active · ${outbox} done")")
    else
        # Idle/blocked: quiet view, but still surface the LAST specialist + result
        # so there's always specialist context at a glance. No `now` line — a
        # finished lane's pane still shows its last-turn marker, which would read
        # as misleadingly "live".
        local last_spec last_line
        last_spec="$(last_specialist "$lane")"
        if [[ -n "$last_spec" && "$last_spec" != "none" && -n "$last" ]]; then
            last_line="${last_spec} · ${last}"
        else
            last_line="${last:-none}"
        fi
        body+=("$(fmt_tagline "$inner" "38;5;240" "$tagline")")
        body+=("$(fmt_erow "$width" 📥 "${inbox} queued · ${active} active · ${outbox} done · ${blocked} blk")")
        body+=("$(fmt_erow "$width" 🕐 "$last_line")")
    fi

    # Top border: ╭ <state emoji> <lane name (accent)> · <state (dim)> <fill> ╮
    local hpad=$(( width - 10 - ${#name_lc} - ${#state_lc} ))
    [[ "$hpad" -lt 1 ]] && hpad=1
    c256 "$accent" "╭ "
    printf '%s ' "$state_emoji"
    printf '\033[1;38;5;%sm%s\033[0m' "$accent" "$name_lc"
    printf '\033[38;5;240m · %s \033[0m' "$state_lc"
    c256 "$accent" "$(repeat_char '─' "$hpad")╮"
    printf '\n'

    # Body rows.
    printf '%s\n' "${body[@]}"

    # Fill to target height: box = 1 (top) + #body + 1 (bottom). Pad the interior
    # with accent-tinted blank rails so cards keep an equal slice of the sidebar.
    local total=$(( ${#body[@]} + 2 ))
    if [[ "$height" -gt "$total" ]]; then
        local i
        for ((i = 0; i < height - total; i++)); do
            c256 "$accent" "│"
            printf '%*s' "$((width - 2))" ""
            c256 "$accent" "│"
            printf '\n'
        done
    fi

    # Bottom border.
    c256 "$accent" "╰$(repeat_char '─' "$((width - 2))")╯"
    printf '\n'
}

draw_compact_card() {
    local lane="$1" width="$2"
    local accent short inbox active outbox blocked specialist last state state_color line max_last rule
    accent="$(runtime_accent_color "$lane")"
    short="$(runtime_short_name "$lane")"
    inbox=$(count_lane_tasks "$lane" inbox)
    active=$(count_lane_tasks "$lane" active)
    outbox=$(count_lane_tasks "$lane" outbox)
    blocked=$(blocked_count "$lane")
    specialist="$(lane_specialist "$lane")"
    last="$(latest_result "$lane")"

    if [[ "$active" -gt 0 ]]; then
        state="WORK"; state_color="38;5;118"
    elif [[ "$inbox" -gt 0 ]]; then
        state="PEND"; state_color="38;5;214"
    elif [[ "$blocked" -gt 0 ]]; then
        state="BLCK"; state_color="38;5;203"
    else
        state="IDLE"; state_color="38;5;245"
    fi

    max_last=$((width - 30))
    [[ "$max_last" -lt 8 ]] && max_last=8
    rule="$(repeat_char '─' "$width")"
    c256 "$accent" "$rule"
    printf '\n'
    printf '\033[38;5;%sm●\033[0m ' "$accent"
    printf '\033[1;38;5;%sm%-6s\033[0m ' "$accent" "$short"
    color "$state_color" "$(fit "$state" 4)"
    printf ' q:%s/%s b:%s ' "$inbox" "$active" "$blocked"
    line="${specialist:-none}"
    color "38;5;250" "$(fit "$line" "$max_last")"
    printf '\n'
    printf '  '
    color "38;5;245" "last "
    color "38;5;250" "$(fit "${last:-none}" "$((width - 7))")"
    printf '\n'
}

trap 'show_cursor; printf "\n"; exit 0' INT TERM EXIT
hide_cursor
printf '\033[2J'

while true; do
    cols=$(pane_cols)
    rows=$(pane_rows)
    width=$((cols - 1))
    [[ "$width" -lt 34 ]] && width=34
    [[ "$width" -gt 78 ]] && width=78

    home
    compact=false
    [[ "$SQUAD_WATCH_COMPACT" == "1" || "$cols" -lt 60 ]] && compact=true

    if [[ "$LANE" == "all" ]]; then
        printf '\033[48;5;236;38;5;45;1m MODEL LANES \033[0m'
        printf '  '
        if [[ "$compact" == "true" ]]; then
            color "38;5;245" "mouse scroll / copy-mode"
        else
            color "38;5;245" "scroll: mouse / copy: drag or copy-mode"
        fi
        printf '\n\n'
        # Give each of the 4 lanes an equal slice of the remaining height so the
        # cards fill the sidebar instead of hugging the top. Header above uses 2
        # rows; leave a 1-row gap between cards.
        card_h=$(( (rows - 2) / 4 - 1 ))
        [[ "$card_h" -lt 6 ]] && card_h=6
        for lane in "${MODEL_LANES[@]}"; do
            if [[ "$compact" == "true" ]]; then
                draw_compact_card "$lane" "$width"
            else
                draw_card "$lane" "$width" "$card_h"
                printf '\n'
            fi
        done
    else
        draw_card "$LANE" "$width"
    fi
    clear_to_end
    sleep 2
done
