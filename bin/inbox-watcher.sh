#!/bin/bash
# Inbox watcher — fires `tmux send-keys` to a model lane pane the moment a new
# TASK-*.md lands in its inbox/. Closes the inbox-poller gap that the squad
# noticed during testing: send-task.sh nudges the pane at dispatch time, but
# if the model CLI was busy at that exact moment the keystrokes don't trigger
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
SESSION="${SQUAD_SESSION:-squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"
INBOX="${VAULT_ROOT}/departments/${LEAD}/inbox"
mkdir -p "${INBOX}"
echo "Watching ${INBOX}/ for new tasks; will nudge the assigned model-lane pane on each."

fswatch -0 --event=Created --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${INBOX}" \
| while IFS= read -r -d '' path; do
    case "$path" in
        */TASK-*.md) ;;
        *) continue ;;
    esac
    to_model="$(awk '/^---$/{p=!p; next} p && /^to_model:/ {sub(/^to_model:[[:space:]]*/, ""); print; exit}' "$path")"
    [[ -z "$to_model" ]] && to_model="$(namespace_default_model "${LEAD}")"
    TARGET_WIN="$(runtime_window_name "${to_model}")"
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then continue; fi
    if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "${TARGET_WIN}"; then continue; fi
    echo "[$(date '+%H:%M:%S')] new: $(basename "$path") → nudging ${SESSION}:${TARGET_WIN}"
    env VAULT_ROOT="$VAULT_ROOT" SQUAD_SESSION="$SESSION" bash "${VAULT_ROOT}/bin/nudge-task.sh" "$path" || true
done
