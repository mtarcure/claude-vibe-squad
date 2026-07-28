#!/bin/bash
# Print a tmux-formatted Chrono controller badge.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

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

blocked_count() {
    # Count LIVE stuck tasks from the registry — not historical outbox response
    # files. Grepping outbox/*-response.md by status string counted every settled
    # task whose response text still says "blocked"/"needs_human" (was showing 21
    # while live blocked was 1). The registry is the source of truth for live state.
    # Read the LIVE bounded registry (source of truth, ~17 records), not the 2.24MB
    # active-tasks.json monolith (a stale compatibility projection full of old terminal
    # tasks that made this count read ~23 while live-blocked was 1).
    local registry="${VAULT_ROOT}/_state/tasks/active.json"
    [[ -f "$registry" ]] || registry="${VAULT_ROOT}/_state/active-tasks.json"
    [[ -f "$registry" ]] || { echo 0; return 0; }
    jq '[.[] | select((.state // .status) == "blocked" or (.state // .status) == "failed" or (.state // .status) == "needs_human")] | length' "$registry" 2>/dev/null || echo 0
}

active="$(count_glob "${VAULT_ROOT}/departments"/*/active/TASK-*.md)"
inbox="$(count_glob "${VAULT_ROOT}/departments"/*/inbox/TASK-*.md)"
blocked="$(blocked_count)"
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
