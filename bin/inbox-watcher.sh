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

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="${SQUAD_SESSION:-squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"
INBOX="${VAULT_ROOT}/departments/${LEAD}/inbox"
FAILOVER_CONTROL="${VAULT_ROOT}/bin/failover-control.py"
DAEMON_REQUIREMENTS="${VAULT_ROOT}/daemon/requirements.txt"
mkdir -p "${INBOX}"
POLL_SECONDS="${DELIVERY_POLL_SECONDS:-1}"
echo "Watching ${INBOX}/ for queued tasks; bounded delivery replay interval=${POLL_SECONDS}s."

record_pane_delivery() {
    local path="$1"
    if [[ "${FAILOVER_CONTROL_ENABLED:-0}" == "1" || -f "${VAULT_ROOT}/_state/failover/ENABLED" ]]; then
        if command -v uv >/dev/null 2>&1; then
            uv run --with-requirements "$DAEMON_REQUIREMENTS" \
                python "$FAILOVER_CONTROL" pane-delivery-attempted --task-file "$path" \
                || echo "WARNING: failed to record pane delivery for $(basename "$path")" >&2
        else
            echo "WARNING: uv unavailable; cannot record pane delivery for $(basename "$path")" >&2
        fi
    fi
}

nudge_path() {
    local path="$1" to_model target_win rc
    case "$path" in
        */TASK-*.md) ;;
        *) return 0 ;;
    esac
    [[ -f "$path" ]] || return 0
    to_model="$(awk '/^---$/{p=!p; next} p && /^to_model:/ {sub(/^to_model:[[:space:]]*/, ""); print; exit}' "$path")"
    [[ -z "$to_model" ]] && to_model="$(namespace_default_model "${LEAD}")"
    target_win="$(runtime_window_name "${to_model}")"
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then return 0; fi
    if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "${target_win}"; then return 0; fi
    env VAULT_ROOT="$VAULT_ROOT" SQUAD_SESSION="$SESSION" DELIVERY_QUIET=1 \
        bash "${VAULT_ROOT}/bin/nudge-task.sh" "$path"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        echo "[$(date '+%H:%M:%S')] delivered: $(basename "$path") → ${SESSION}:${target_win}"
        record_pane_delivery "$path"
    elif [[ "$rc" -ne 3 ]]; then
        echo "WARNING: inbox watcher could not nudge ${SESSION}:${target_win} for $(basename "$path")" >&2
        return "$rc"
    fi
}

scan_inbox() {
    local path
    for path in "${INBOX}"/TASK-*.md; do
        [[ -e "$path" ]] || continue
        nudge_path "$path" || true
    done
}

poll_loop() {
    while true; do
        scan_inbox
        sleep "$POLL_SECONDS"
    done
}

# Startup replay is what makes a watcher crash/restart safe. The locked
# authorization in nudge-task makes concurrent fswatch/poll observations benign.
scan_inbox
if command -v fswatch >/dev/null 2>&1; then
    poll_loop &
    POLL_PID=$!
    trap 'kill "$POLL_PID" 2>/dev/null || true' EXIT INT TERM
    fswatch -0 --event=Created --event=Renamed --event=MovedTo \
            -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
            "${INBOX}" \
    | while IFS= read -r -d '' path; do
        nudge_path "$path" || true
    done
else
    echo "fswatch unavailable; running restart-safe polling worker only."
    poll_loop
fi
