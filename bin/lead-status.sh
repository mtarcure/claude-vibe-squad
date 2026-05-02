#!/bin/bash
# Lead status — print a stable, no-flash status line for one Lead.
# Designed to live in a small sidebar pane that refreshes periodically.
# Usage:  bin/lead-status.sh <lead-name>   (e.g. coding | security | content | sysmgmt | research)
# Loops every 5 seconds with `clear` between iterations — no scroll, no ANSI noise.

set -uo pipefail

LEAD="${1:-}"
if [[ -z "${LEAD}" ]]; then
    echo "usage: $0 <coding|security|content|sysmgmt|research>"
    exit 1
fi

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DEPT="${VAULT_ROOT}/departments/${LEAD}"

human_age() {
    local mtime="$1"
    local now=$(date +%s)
    local age=$((now - mtime))
    if   [[ ${age} -lt 60 ]];     then printf '%ds' "${age}"
    elif [[ ${age} -lt 3600 ]];   then printf '%dm' $((age / 60))
    elif [[ ${age} -lt 86400 ]];  then printf '%dh' $((age / 3600))
    else                               printf '%dd' $((age / 86400))
    fi
}

while true; do
    clear
    case "${LEAD}" in
        coding)   cli="Codex"  ;;
        security) cli="Claude" ;;
        content)  cli="Gemini" ;;
        sysmgmt)  cli="Claude" ;;
        research) cli="Kimi"   ;;
        *)        cli="?"      ;;
    esac
    echo "━━━ $(echo "${LEAD}" | tr '[:lower:]' '[:upper:]') (${cli}) ━━━"

    in=$(ls "${DEPT}/inbox" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    act=$(ls "${DEPT}/active" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    out=$(ls "${DEPT}/outbox" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    arc=$(ls "${DEPT}/archive" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
    echo "in:${in} act:${act} out:${out} arc:${arc}"

    if [[ ${act} -gt 0 ]]; then
        echo "● working"
    elif [[ ${in} -gt 0 ]]; then
        echo "○ pending"
    else
        echo "✓ idle"
    fi

    latest=$(find "${DEPT}/inbox" "${DEPT}/active" "${DEPT}/outbox" "${DEPT}/archive" \
                  -type f -name 'TASK-*' 2>/dev/null \
                  | xargs -I{} stat -f '%m %N' {} 2>/dev/null \
                  | sort -rn | head -1)
    if [[ -n "${latest}" ]]; then
        last_mtime=$(echo "${latest}" | awk '{print $1}')
        echo "last: $(human_age "${last_mtime}") ago"
    else
        echo "last: —"
    fi

    echo ""
    echo "$(date '+%H:%M:%S')"

    sleep 5
done
