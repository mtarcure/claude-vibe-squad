#!/bin/bash
# Print a tmux-formatted Chrono controller badge.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

count_glob() {
    local pattern="$1" count=0 f
    for f in $pattern; do
        [[ -e "$f" ]] || continue
        count=$((count + 1))
    done
    echo "$count"
}

doctor_state() {
    local today summary issues warnings
    today="$(date -u +%Y-%m-%d)"
    summary="${VAULT_ROOT}/_state/doctor-logs/${today}-summary.json"
    [[ -f "$summary" ]] || return 0
    issues="$(jq -r '.issue_count // 0' "$summary" 2>/dev/null || echo 0)"
    warnings="$(jq -r '.warning_count // 0' "$summary" 2>/dev/null || echo 0)"
    if [[ "$issues" =~ ^[0-9]+$ ]] && [[ "$issues" -gt 0 ]]; then
        echo "issues:${issues}"
        return 0
    fi
    if [[ "$warnings" =~ ^[0-9]+$ ]] && [[ "$warnings" -gt 0 ]]; then
        echo "warn:${warnings}"
        return 0
    fi
    echo "healthy"
}

active="$(count_glob "${VAULT_ROOT}/departments"/*/active/TASK-*.md)"
inbox="$(count_glob "${VAULT_ROOT}/departments"/*/inbox/TASK-*.md)"
blocked="$(grep -RilE '^status:[[:space:]]*(failed|error|blocked|needs_human)' "${VAULT_ROOT}/departments"/*/outbox/TASK-*-response.md 2>/dev/null | wc -l | tr -d ' ')"
doctor="$(doctor_state)"

if [[ "$blocked" =~ ^[0-9]+$ ]] && [[ "$blocked" -gt 0 ]]; then
    bg="colour203"
    fg="colour16"
    label="CHRONO blocked:${blocked}"
elif [[ "$doctor" == issues:* ]]; then
    bg="colour203"
    fg="colour16"
    label="CHRONO ${doctor}"
elif [[ "$doctor" == warn:* ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO ${doctor}"
elif [[ "$active" =~ ^[0-9]+$ ]] && [[ "$active" -gt 0 ]]; then
    bg="colour118"
    fg="colour16"
    label="CHRONO active:${active}"
elif [[ "$inbox" =~ ^[0-9]+$ ]] && [[ "$inbox" -gt 0 ]]; then
    bg="colour214"
    fg="colour16"
    label="CHRONO queued:${inbox}"
else
    bg="colour45"
    fg="colour16"
    label="CHRONO healthy"
fi

printf '#[bg=%s,fg=%s,bold] %s #[bg=default,fg=colour238]' "$bg" "$fg" "$label"
