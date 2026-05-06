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

response_ready_for_status() {
    local file="$1" mtime now age
    [[ -f "$file" ]] || return 1
    mtime="$(stat -f %m "$file" 2>/dev/null || stat -c %Y "$file" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age=$((now - mtime))
    [[ "$age" -ge 60 ]] || return 1
    awk '/^---$/{p=!p; next} p && /^status:[[:space:]]*/ {found=1; exit} END{exit found ? 0 : 1}' "$file"
}

response_status() {
    local file="$1" raw
    raw="$(frontmatter_field "$file" status | tr -d '"' | tr -d "'" | xargs)"
    case "$raw" in
        completed|complete) printf 'completed' ;;
        completed_with_partials) printf 'completed_with_partials' ;;
        completed_with_notes) printf 'completed_with_notes' ;;
        needs_human) printf 'needs_human' ;;
        BLOCKED|blocked) printf 'BLOCKED' ;;
        cancelled|canceled) printf 'cancelled' ;;
        *) printf 'unknown' ;;
    esac
}

status_nudge_prefix() {
    case "$1" in
        completed) printf '✅ DONE' ;;
        completed_with_partials|completed_with_notes) printf '⚠️ PARTIAL' ;;
        needs_human) printf '🚨 NEEDS HUMAN' ;;
        BLOCKED) printf '❌ BLOCKED' ;;
        cancelled) printf '🚫 CANCELLED' ;;
        *) printf '❓ UNKNOWN STATUS' ;;
    esac
}

PROCESSED_PATHS="|"
PENDING_PATHS="|"

handle_response_path() {
    local path="$1" fname ctx status status_prefix task_id scope_output NUDGE_MSG state task_file
    # Only react to actual response files — not partial writes or unrelated edits.
    case "$path" in
        */TASK-*-response.md|*/RESP-*.md) ;;
        *) return ;;
    esac
    case "$PROCESSED_PATHS" in
        *"|$path|"*) return ;;
    esac

    # Only nudge if the squad session and chrono window are alive.
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then return; fi
    if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then return; fi

    fname="$(basename "$path")"
    ctx="$(response_context "$fname")"
    status="unknown"
    status_prefix="❓ UNKNOWN STATUS"
    task_id=""
    if [[ "$fname" == TASK-*-response.md ]]; then
        task_id="${fname%-response.md}"
        if response_ready_for_status "$path"; then
            status="$(response_status "$path")"
            status_prefix="$(status_nudge_prefix "$status")"
        else
            echo "[$(date '+%H:%M:%S')] response not status-ready yet: ${fname}; scheduling delayed retry"
            case "$PENDING_PATHS" in
                *"|$path|"*) ;;
                *)
                    PENDING_PATHS="${PENDING_PATHS}${path}|"
                    ( sleep 65; handle_response_path "$path" ) &
                    ;;
            esac
            return
        fi
    fi
    PROCESSED_PATHS="${PROCESSED_PATHS}${path}|"
    echo "[$(date '+%H:%M:%S')] new: ${fname} from ${ctx} via ${NAMESPACE} namespace -> nudging squad:chrono"

    if [[ "$fname" == TASK-*-response.md ]]; then
        if "${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$task_id" >/dev/null 2>&1
        then
            echo "[$(date '+%H:%M:%S')] reconciled active-task registry entry if eligible: ${task_id}"
        else
            echo "[$(date '+%H:%M:%S')] warning: failed registry reconciliation for: ${task_id}" >&2
        fi
        scope_output="$("${VAULT_ROOT}/scripts/python/scope_validator.py" "$task_id" "$NAMESPACE" 2>/dev/null || true)"
        if [[ -n "$scope_output" ]]; then
            echo "[$(date '+%H:%M:%S')] ${scope_output}"
        fi
        if [[ "$status" == "needs_human" || "$status" == "BLOCKED" ]]; then
            "${VAULT_ROOT}/bin/notify-blocker.sh" "$task_id" "$NAMESPACE" >/dev/null 2>&1 &
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
    if [[ -n "${task_id}" ]]; then
        NUDGE_MSG="${status_prefix}: ${task_id} — RESP from model lane ${ctx}: ${fname} landed in compatibility mailbox departments/${NAMESPACE}/outbox/. Read and surface to operator per chrono/CLAUDE.md protocol."
        if [[ -n "${scope_output:-}" ]]; then
            NUDGE_MSG="${NUDGE_MSG} ${scope_output}"
        fi
    else
        NUDGE_MSG="RESP from model lane ${ctx}: ${fname} landed in compatibility mailbox departments/${NAMESPACE}/outbox/. Read and surface to operator per chrono/CLAUDE.md protocol."
    fi
    echo "[$(date '+%H:%M:%S')] nudge: ${NUDGE_MSG}"

    # Match inbox-watcher.sh keystroke pattern: literal text, sleep, then Enter.
    # The 0.3s sleep gives the receiving CLI time to settle before Enter is
    # interpreted as submit.
    tmux send-keys -l -t "${SESSION}:chrono" "${NUDGE_MSG}"
    sleep 0.3
    tmux send-keys -t "${SESSION}:chrono" Enter
}

fswatch -0 --event=Created --event=Updated --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${OUTBOX}" \
| while IFS= read -r -d '' path; do
    handle_response_path "$path"
done
