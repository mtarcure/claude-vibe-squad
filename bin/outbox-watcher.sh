#!/bin/bash
# Outbox watcher — fires `tmux send-keys` to the chrono (Coordinator) pane the
# moment a model lane writes a response file to a compatibility outbox/. Closes the outbox-poller
# gap: chrono's CLAUDE.md says "scan outboxes at start of every operator turn"
# but that's pull-based and only fires when the operator types. This watcher
# is push-based — when a Lead finishes work, chrono is notified immediately
# and a durable chrono-side queue entry is written for next-session surfacing.
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
STATE_DIR="${VAULT_ROOT}/_state"
FAILOVER_STAGING="${STATE_DIR}/failover/staging"
FAILOVER_CONTROL="${VAULT_ROOT}/bin/failover-control.py"

mkdir -p "${OUTBOX}" "${FAILOVER_STAGING}"
WATCH_PATHS=("${OUTBOX}")
STAGING_OWNER=0
if [[ "$NAMESPACE" == "coding" && ( "${FAILOVER_CONTROL_ENABLED:-0}" == "1" || -f "${STATE_DIR}/failover/ENABLED" ) ]]; then
    WATCH_PATHS+=("${FAILOVER_STAGING}")
    STAGING_OWNER=1
fi

echo "Watching ${OUTBOX}/ for new responses; will nudge squad:chrono pane on each."

if [[ "$NAMESPACE" == "coding" ]]; then
    (
        while true; do
            sleep 900
            if ! "${VAULT_ROOT}/bin/registry-reconciler.sh" >/dev/null 2>&1; then
                echo "[$(date '+%H:%M:%S')] warning: periodic registry reconciliation failed" >&2
            fi
        done
    ) &
    PERIODIC_RECONCILER_PID=$!
    trap 'kill "${PERIODIC_RECONCILER_PID}" 2>/dev/null || true' EXIT INT TERM
fi

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
    [[ "$age" -ge 5 ]] || return 1
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

response_summary() {
    local file="$1"
    awk '
        function emit() {
            gsub(/[|]/, "/", para)
            gsub(/[^ -~]/, "?", para)
            print substr(para, 1, 220)
            printed=1
        }
        NR == 1 && /^---$/ {fm=1; next}
        fm && /^---$/ {fm=0; body=1; next}
        fm {next}
        !body {body=1}
        body {
            if ($0 ~ /^[[:space:]]*$/) {
                if (para != "") { emit(); exit }
                next
            }
            line=$0
            sub(/^#+[[:space:]]*/, "", line)
            gsub(/[[:space:]]+/, " ", line)
            para = para (para ? " " : "") line
        }
        END { if (para != "" && !printed) emit() }
    ' "$file"
}

release_chrono_queue_lock() {
    local lockdir="$1" tmp="$2" lock_acquired="$3"
    rm -f "$tmp"
    if [[ "$lock_acquired" == 1 ]]; then
        rm -f "$lockdir/owner.pid"
        rmdir "$lockdir" 2>/dev/null || true
    fi
}

append_chrono_queue() {
    local task_id="$1" status="$2" file="$3" queue lockdir tmp timestamp summary task_ref lock_acquired owner mtime now age
    queue="${STATE_DIR}/chrono-queue.md"
    lockdir="${queue}.lockdir"
    tmp="${queue}.tmp.$$.$RANDOM"
    lock_acquired=0
    mkdir -p "${STATE_DIR}"
    trap 'release_chrono_queue_lock "$lockdir" "$tmp" "${lock_acquired:-0}"' RETURN
    trap 'release_chrono_queue_lock "$lockdir" "$tmp" "${lock_acquired:-0}"; exit 130' HUP INT TERM
    while ! mkdir "$lockdir" 2>/dev/null; do
        owner="$(cat "$lockdir/owner.pid" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]]; then
            if kill -0 "$owner" 2>/dev/null; then
                sleep 0.1
                continue
            fi
            rm -f "$lockdir/owner.pid" 2>/dev/null || true
            rmdir "$lockdir" 2>/dev/null || true
            continue
        fi
        mtime="$(stat -f %m "$lockdir" 2>/dev/null || stat -c %Y "$lockdir" 2>/dev/null || echo 0)"
        now="$(date +%s)"
        age=$((now - mtime))
        if [[ "$age" -gt 300 ]]; then
            rm -f "$lockdir/owner.pid" 2>/dev/null || true
            rmdir "$lockdir" 2>/dev/null || true
            continue
        fi
        sleep 0.1
    done
    lock_acquired=1
    printf '%s\n' "$$" > "$lockdir/owner.pid"
    timestamp="$(date -u +%FT%TZ)"
    summary="$(response_summary "$file")"
    [[ -n "$summary" ]] || summary="(no response summary)"
    task_ref="${NAMESPACE}/${task_id}"
    {
        if [[ -f "$queue" ]]; then
            cat "$queue"
        else
            echo "# Chrono Queue"
            echo "# timestamp | status | namespace/task-id | summary"
            echo
        fi
        echo "${timestamp} | ${status} | ${task_ref} | ${summary}"
    } > "$tmp" || {
        release_chrono_queue_lock "$lockdir" "$tmp" "$lock_acquired"
        lock_acquired=0
        trap - RETURN HUP INT TERM
        return 1
    }
    sync
    mv "$tmp" "$queue" || {
        release_chrono_queue_lock "$lockdir" "$tmp" "$lock_acquired"
        lock_acquired=0
        trap - RETURN HUP INT TERM
        return 1
    }
    sync
    rm -f "$lockdir/owner.pid"
    rmdir "$lockdir"
    lock_acquired=0
    trap - RETURN HUP INT TERM
}

PROCESSED_PATHS="|"
PENDING_PATHS="|"

handle_response_path() {
    local path="$1" fname ctx status status_prefix task_id NUDGE_MSG state task_file can_nudge
    # Lane-owned files land only in attempt staging. The controller validates
    # schema/ID/hash and generation, then atomically publishes the canonical
    # outbox file. A rejected or partial staging write is never surfaced.
    case "$path" in
        "${FAILOVER_STAGING}"/*/*.md)
            [[ "$STAGING_OWNER" == "1" ]] || return
            if ! response_ready_for_status "$path"; then
                echo "[$(date '+%H:%M:%S')] staging artifact not quiescent/status-ready: $(basename "$path"); scheduling delayed retry"
                case "$PENDING_PATHS" in
                    *"|$path|"*) ;;
                    *)
                        PENDING_PATHS="${PENDING_PATHS}${path}|"
                        (
                            while [[ -f "$path" ]]; do
                                sleep 6
                                if response_ready_for_status "$path"; then
                                    handle_response_path "$path"
                                    break
                                fi
                            done
                        ) &
                        ;;
                esac
                return
            fi
            if python3 "$FAILOVER_CONTROL" publish --artifact "$path"; then
                echo "[$(date '+%H:%M:%S')] fenced staging artifact published: $(basename "$path")"
            else
                echo "[$(date '+%H:%M:%S')] staging artifact rejected or not ready: ${path}" >&2
            fi
            return
            ;;
    esac
    # Only react to actual response files — not partial writes or unrelated edits.
    case "$path" in
        */TASK-*-response.md|*/RESP-*.md) ;;
        *) return ;;
    esac
    case "$PROCESSED_PATHS" in
        *"|$path|"*) return ;;
    esac

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
                    ( sleep 6; handle_response_path "$path" ) &
                    ;;
            esac
            return
        fi
    fi
    PROCESSED_PATHS="${PROCESSED_PATHS}${path}|"
    can_nudge=1
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        can_nudge=0
    elif ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then
        can_nudge=0
    fi
    echo "[$(date '+%H:%M:%S')] new: ${fname} from ${ctx} via ${NAMESPACE} namespace -> queueing chrono status"

    if [[ "$fname" == TASK-*-response.md ]]; then
        if "${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$task_id" >/dev/null 2>&1
        then
            echo "[$(date '+%H:%M:%S')] reconciled active-task registry entry if eligible: ${task_id}"
        else
            echo "[$(date '+%H:%M:%S')] warning: failed registry reconciliation for: ${task_id}" >&2
        fi
        if append_chrono_queue "$task_id" "$status" "$path"; then
            echo "[$(date '+%H:%M:%S')] queued chrono status entry: ${status} ${NAMESPACE}/${task_id}"
        else
            echo "[$(date '+%H:%M:%S')] warning: failed to queue chrono status entry: ${status} ${NAMESPACE}/${task_id}" >&2
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
    else
        NUDGE_MSG="RESP from model lane ${ctx}: ${fname} landed in compatibility mailbox departments/${NAMESPACE}/outbox/. Read and surface to operator per chrono/CLAUDE.md protocol."
    fi
    echo "[$(date '+%H:%M:%S')] nudge: ${NUDGE_MSG}"

    if [[ "$can_nudge" == 1 ]]; then
        # Match inbox-watcher.sh keystroke pattern: literal text, sleep, then Enter.
        # The 0.3s sleep gives the receiving CLI time to settle before Enter is
        # interpreted as submit.
        tmux send-keys -l -t "${SESSION}:chrono" "${NUDGE_MSG}"
        sleep 0.3
        tmux send-keys -t "${SESSION}:chrono" Enter
    else
        echo "[$(date '+%H:%M:%S')] chrono pane unavailable; queued without tmux nudge: ${fname}"
    fi
}

fswatch -0 --event=Created --event=Updated --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${WATCH_PATHS[@]}" \
| while IFS= read -r -d '' path; do
    handle_response_path "$path"
done
