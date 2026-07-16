#!/bin/bash
# Squad health aggregator — counts state across all compatibility namespaces. Outputs a
# single line for tmux status bar consumption (or operator stdout).
#
# Format:  act:N pen:N err:N thru:N/h
#  - act    = tasks currently in any namespace active/ (being processed)
#  - pen    = tasks queued in any namespace inbox/
#  - err    = namespaces whose newest outbox response declares status: failed
#  - thru/h = task responses written in last 60 min

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
# VAULT_ROOT is runtime-configurable.
# shellcheck disable=SC1091
source "${VAULT_ROOT}/shared/namespaces.sh"

active=0; pending=0; err=0; throughput=0
now=$(date +%s)
hour_ago=$((now - 3600))

for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
    dept="${VAULT_ROOT}/departments/${namespace}"
    a=$(ls "${dept}/active" 2>/dev/null | grep -v '\.gitkeep' | wc -l | tr -d ' ')
    p=$(ls "${dept}/inbox" 2>/dev/null | grep -v '\.gitkeep' | wc -l | tr -d ' ')
    active=$((active + a))
    pending=$((pending + p))

    of=$(find "${dept}/outbox" -maxdepth 1 -type f -name 'TASK-*-response.md' 2>/dev/null \
        | xargs -I{} stat -f '%m %N' {} 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -n "$of" ]]; then
        fm=$(awk '/^---$/{c++; if(c==2) exit; next} c==1' "$of" 2>/dev/null)
        if echo "$fm" | grep -qiE '^status:[[:space:]]*(failed|error|blocked)\b'; then
            err=$((err + 1))
        fi
    fi

    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        mt=$(stat -f '%m' "$f" 2>/dev/null || echo 0)
        [[ $mt -gt $hour_ago ]] && throughput=$((throughput + 1))
    done < <(find "${dept}/outbox" "${dept}/archive" -maxdepth 1 -type f -name 'TASK-*-response.md' 2>/dev/null)
done

monitor_count=0
monitor_state="${VAULT_ROOT}/_state/monitor/last-alert-count"
[[ -f "$monitor_state" ]] && monitor_count=$(cat "$monitor_state" 2>/dev/null || echo 0)

printf 'act:%d pen:%d err:%d thru:%d/h mon:%d' \
    "$active" "$pending" "$err" "$throughput" "$monitor_count"
