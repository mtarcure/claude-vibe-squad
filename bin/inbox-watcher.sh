#!/bin/bash
# Inbox watcher — fires `tmux send-keys` to a Lead's pane the moment a new
# TASK-*.md lands in its inbox/. Closes the inbox-poller gap that the squad
# noticed during testing: send-task.sh nudges the pane at dispatch time, but
# if the Lead's CLI was busy at that exact moment the keystrokes don't trigger
# processing. This watcher fires the nudge whenever a NEW file appears,
# independent of dispatch timing.
#
# Usage:  bash bin/inbox-watcher.sh <lead-name>
# Typically launched by launch-squad.sh as a background pane (window 6).

set -uo pipefail

LEAD="${1:-}"
if [[ -z "${LEAD}" ]]; then
    echo "usage: $0 <coding|security|content|sysmgmt|research>"
    exit 1
fi

if ! command -v fswatch >/dev/null 2>&1; then
    echo "fswatch not installed — install with: brew install fswatch"
    exit 1
fi

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
INBOX="${VAULT_ROOT}/departments/${LEAD}/inbox"
NUDGE_MSG="A new task has arrived in inbox/. Pick up the oldest TASK-*.md and process it per protocol."

mkdir -p "${INBOX}"

echo "Watching ${INBOX}/ for new tasks; will nudge squad:${LEAD} pane on each."

fswatch -0 --event=Created --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${INBOX}" \
| while IFS= read -r -d '' path; do
    case "$path" in
        */TASK-*.md) ;;
        *) continue ;;
    esac
    if ! tmux has-session -t squad 2>/dev/null; then continue; fi
    if ! tmux list-windows -t squad -F '#{window_name}' 2>/dev/null | grep -qx "${LEAD}"; then continue; fi
    echo "[$(date '+%H:%M:%S')] new: $(basename "$path") → nudging squad:${LEAD}"
    tmux send-keys -l -t "squad:${LEAD}" "${NUDGE_MSG}"
    sleep 0.3
    tmux send-keys -t "squad:${LEAD}" Enter
done
