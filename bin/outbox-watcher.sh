#!/bin/bash
# Outbox watcher — fires `tmux send-keys` to the chrono (Coordinator) pane the
# moment a model lane writes a response file to a compatibility outbox/. Closes the outbox-poller
# gap: chrono's CLAUDE.md says "scan outboxes at start of every operator turn"
# but that's pull-based and only fires when the operator types. This watcher
# is push-based — when a Lead finishes work, chrono is notified immediately
# and can surface to operator (or queue for Telegram via a separate layer).
#
# Architectural symmetry with inbox-watcher.sh:
#   - inbox-watcher: outside-world (Chrono) -> namespace inbox -> nudge model lane pane
#   - outbox-watcher: namespace outbox -> nudge Chrono pane -> Chrono surfaces to operator
#
# Per `shared/protocol.md`: response files land in `departments/<namespace>/outbox/`
# matching `*-response.md` (the convention used by send-task.sh's reply path)
# or `RESP-<id>.md` (legacy peer replies).
#
# Usage:  bash bin/outbox-watcher.sh <source-namespace>
# Typically launched by launch-squad.sh as a background pane alongside
# inbox-watchers (window 6).

set -uo pipefail

NAMESPACE="${1:-}"
if [[ -z "${NAMESPACE}" ]]; then
    echo "usage: $0 <coding|security|content|sysmgmt|research>"
    exit 1
fi

if ! command -v fswatch >/dev/null 2>&1; then
    echo "fswatch not installed — install with: brew install fswatch"
    exit 1
fi

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="${SQUAD_SESSION:-squad}"
OUTBOX="${VAULT_ROOT}/departments/${NAMESPACE}/outbox"

mkdir -p "${OUTBOX}"

echo "Watching ${OUTBOX}/ for new responses; will nudge squad:chrono pane on each."

frontmatter_field() {
    local file="$1" field="$2"
    awk -v key="$field" '/^---$/{p=!p; next} p && index($0, key ":") == 1 {sub("^[^:]+:[[:space:]]*", ""); print; exit}' "$file"
}

response_context() {
    local fname="$1" task_id task_file state to_model specialist
    if [[ "$fname" == TASK-*-response.md ]]; then
        task_id="${fname%-response.md}"
        for state in inbox active archive; do
            task_file="${VAULT_ROOT}/departments/${NAMESPACE}/${state}/${task_id}.md"
            if [[ -f "$task_file" ]]; then
                to_model="$(frontmatter_field "$task_file" to_model)"
                specialist="$(frontmatter_field "$task_file" specialist)"
                [[ -n "$to_model" ]] || to_model="unknown-model"
                [[ -n "$specialist" ]] || specialist="unknown-specialist"
                printf '%s/%s' "$to_model" "$specialist"
                return
            fi
        done
    fi
    printf 'unknown-model/unknown-specialist'
}

fswatch -0 --event=Created --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${OUTBOX}" \
| while IFS= read -r -d '' path; do
    # Only react to actual response files — not partial writes or unrelated edits.
    case "$path" in
        */TASK-*-response.md) ;;
        */RESP-*.md) ;;
        *) continue ;;
    esac

    # Only nudge if the squad session and chrono window are alive.
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then continue; fi
    if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then continue; fi

    fname="$(basename "$path")"
    ctx="$(response_context "$fname")"
    echo "[$(date '+%H:%M:%S')] new: ${fname} from ${ctx} via ${NAMESPACE} namespace -> nudging squad:chrono"

    if [[ "$fname" == TASK-*-response.md ]]; then
        task_id="${fname%-response.md}"
        if python3 - "$VAULT_ROOT" "$task_id" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

vault = Path(sys.argv[1])
task_id = sys.argv[2]
registry_path = vault / "_state" / "active-tasks.json"
if not registry_path.exists():
    raise SystemExit(0)
registry = json.loads(registry_path.read_text())
if task_id in registry:
    registry[task_id]["status"] = "complete"
    registry[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
    tmp = str(registry_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=2)
    os.rename(tmp, str(registry_path))
PYEOF
        then
            echo "[$(date '+%H:%M:%S')] closed active-task registry entry: ${task_id}"
        else
            echo "[$(date '+%H:%M:%S')] warning: failed to close active-task registry entry: ${task_id}" >&2
        fi
        for state in inbox active; do
            task_file="${VAULT_ROOT}/departments/${NAMESPACE}/${state}/${task_id}.md"
            if [[ -f "$task_file" ]]; then
                mkdir -p "${VAULT_ROOT}/departments/${NAMESPACE}/archive"
                mv "$task_file" "${VAULT_ROOT}/departments/${NAMESPACE}/archive/${task_id}.md"
                echo "[$(date '+%H:%M:%S')] archived completed task packet: ${state}/${task_id}.md"
            fi
        done
    fi

    # Compose the nudge. Chrono receives this in its conversation as if the
    # operator typed it, then chooses to read + surface per its own protocol.
    NUDGE_MSG="RESP from model lane ${ctx}: ${fname} landed in compatibility mailbox departments/${NAMESPACE}/outbox/. Read and surface to operator per chrono/CLAUDE.md protocol."

    # Match inbox-watcher.sh keystroke pattern: literal text, sleep, then Enter.
    # The 0.3s sleep gives the receiving CLI time to settle before Enter is
    # interpreted as submit.
    tmux send-keys -l -t "${SESSION}:chrono" "${NUDGE_MSG}"
    sleep 0.3
    tmux send-keys -t "${SESSION}:chrono" Enter
done
