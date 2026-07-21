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

PUBLISH_ONCE_PATH=""
NOTIFY_ONCE_EVENT_KEY=""
NOTIFY_ONCE_MESSAGE=""
NOTIFY_ONCE_MODE=0
if [[ "${1:-}" == "--publish-once" ]]; then
    NAMESPACE="coding"
    PUBLISH_ONCE_PATH="${2:-}"
elif [[ "${1:-}" == "--notify-once" ]]; then
    NAMESPACE="coding"
    NOTIFY_ONCE_MODE=1
    NOTIFY_ONCE_EVENT_KEY="${2:-}"
    NOTIFY_ONCE_MESSAGE="${3:-}"
else
    NAMESPACE="${1:-}"
fi
if [[ -z "${NAMESPACE}" ]]; then
    echo "usage: $0 <coding|security|content|sysmgmt|research>"
    exit 1
fi

if [[ -z "$PUBLISH_ONCE_PATH" && "$NOTIFY_ONCE_MODE" == 0 ]] \
    && ! command -v fswatch >/dev/null 2>&1; then
    echo "fswatch not installed — install with: brew install fswatch"
    exit 1
fi

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="${SQUAD_SESSION:-squad}"
TMUX_BIN="${TMUX_BIN:-tmux}"
RESPONSE_MIN_AGE_SECONDS="${RESPONSE_MIN_AGE_SECONDS:-5}"
if [[ ! "$RESPONSE_MIN_AGE_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "RESPONSE_MIN_AGE_SECONDS must be a non-negative integer" >&2
    exit 1
fi
OUTBOX="${VAULT_ROOT}/departments/${NAMESPACE}/outbox"
STATE_DIR="${VAULT_ROOT}/_state"
FAILOVER_STAGING="${STATE_DIR}/failover/staging"
FAILOVER_CONTROL="${VAULT_ROOT}/bin/failover-control.py"
DAEMON_REQUIREMENTS="${VAULT_ROOT}/daemon/requirements.txt"
CHRONO_NOTIFY_LOCKDIR="${STATE_DIR}/chrono-notify.lockdir"
CHRONO_NOTIFY_RECEIPTS_DIR="${STATE_DIR}/chrono-notify-receipts"

notification_event_key() {
    local task_ref="$1" state="$2"
    printf '%d:%s|%d:%s' "${#task_ref}" "$task_ref" "${#state}" "$state"
}

release_chrono_notify_lock() {
    local owner
    owner="$(cat "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" 2>/dev/null || true)"
    [[ "$owner" == "$$" ]] || {
        echo "chrono notify lock ownership mismatch: owner=${owner:-missing} self=$$" >&2
        return 1
    }
    rm -f "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" || return 1
    rmdir "${CHRONO_NOTIFY_LOCKDIR}" || return 1
}

acquire_chrono_notify_lock() {
    local owner attempts=0 max_attempts=600 lock_mtime now
    mkdir -p "${STATE_DIR}" "${CHRONO_NOTIFY_RECEIPTS_DIR}"
    while ! mkdir "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null; do
        attempts=$((attempts + 1))
        if [[ "$attempts" -ge "$max_attempts" ]]; then
            echo "timed out acquiring chrono notify lock after 30s" >&2
            return 75
        fi
        owner="$(cat "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then
            sleep 0.05
            continue
        fi
        if [[ "$owner" =~ ^[0-9]+$ ]]; then
            # A well-formed owner that no longer exists is safe to recover.
            rm -f "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" 2>/dev/null || true
            rmdir "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null || true
            sleep 0.05
            continue
        fi
        # mkdir and owner.pid creation cannot be one filesystem transaction.
        # Never break a fresh ownerless/malformed directory: it may belong to
        # a contender between those two operations. Match Python's five-minute
        # stale grace; the local 30-second bound fails closed before then.
        lock_mtime="$(stat -f %m "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null \
            || stat -c %Y "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null || true)"
        now="$(date +%s)"
        if [[ "$lock_mtime" =~ ^[0-9]+$ ]] && (( now - lock_mtime > 300 )); then
            rm -f "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" 2>/dev/null || true
            rmdir "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null || true
        fi
        sleep 0.05
    done
    printf '%s\n' "$$" > "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" || return 1
    owner="$(cat "${CHRONO_NOTIFY_LOCKDIR}/owner.pid" 2>/dev/null || true)"
    [[ -d "${CHRONO_NOTIFY_LOCKDIR}" && "$owner" == "$$" ]] || {
        echo "failed to establish chrono notify lock ownership" >&2
        return 1
    }
}

send_chrono_notification_once() {
    local event_key="$1" message="$2" receipt_hash receipt tmp
    acquire_chrono_notify_lock || return $?
    receipt_hash="$(printf '%s' "$event_key" | shasum -a 256 | awk '{print $1}')"
    receipt="${CHRONO_NOTIFY_RECEIPTS_DIR}/${receipt_hash}.sent"
    tmp="${receipt}.tmp.$$.$RANDOM"
    if [[ -f "$receipt" ]]; then
        release_chrono_notify_lock || return 1
        echo "[$(date '+%H:%M:%S')] duplicate chrono nudge suppressed: ${event_key}"
        return 0
    fi
    if ! "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null \
        || ! "$TMUX_BIN" list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then
        release_chrono_notify_lock || return 1
        return 2
    fi
    if ! "$TMUX_BIN" send-keys -l -t "${SESSION}:chrono" "$message"; then
        release_chrono_notify_lock || return 1
        return 1
    fi
    sleep 0.3
    if ! "$TMUX_BIN" send-keys -t "${SESSION}:chrono" Enter; then
        release_chrono_notify_lock || return 1
        return 1
    fi
    if ! printf 'event_key=%s\nmessage_sha256=%s\nsent_at=%s\ntarget=%s\n' \
        "$event_key" \
        "$(printf '%s' "$message" | shasum -a 256 | awk '{print $1}')" \
        "$(date -u +%FT%TZ)" \
        "${SESSION}:chrono" > "$tmp" \
        || ! mv "$tmp" "$receipt"; then
        rm -f "$tmp" 2>/dev/null || true
        release_chrono_notify_lock || true
        return 1
    fi
    release_chrono_notify_lock || return 1
    return 0
}

if [[ "$NOTIFY_ONCE_MODE" == 1 ]]; then
    [[ -n "$NOTIFY_ONCE_MESSAGE" ]] || {
        echo "usage: $0 --notify-once <event-key> <message>" >&2
        exit 64
    }
    send_chrono_notification_once "$NOTIFY_ONCE_EVENT_KEY" "$NOTIFY_ONCE_MESSAGE"
    exit $?
fi

publish_runtime_alert() {
    local message="$1" event_key
    echo "[$(date '+%H:%M:%S')] CRITICAL FAILOVER PUBLISH RUNTIME: ${message}" >&2
    event_key="$(notification_event_key "runtime-alert" "$(printf '%s' "$message" | shasum -a 256 | awk '{print $1}')")"
    send_chrono_notification_once "$event_key" "🚨 FAILOVER PUBLISH RUNTIME ERROR: ${message}" || true
}

publish_staging_artifact() {
    local artifact="$1" output rc
    if ! command -v uv >/dev/null 2>&1; then
        publish_runtime_alert "uv is unavailable; cannot publish $(basename "$artifact")"
        return 70
    fi
    output="$(uv run --with-requirements "$DAEMON_REQUIREMENTS" \
        python "$FAILOVER_CONTROL" publish --artifact "$artifact" 2>&1)"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        return 0
    fi
    if [[ "$rc" -eq 2 && "$output" == *'"status": "rejected"'* ]]; then
        echo "[$(date '+%H:%M:%S')] staging artifact rejected by controller: ${artifact}: ${output}" >&2
        return 2
    fi
    publish_runtime_alert "interpreter/dependency failure for ${artifact} (exit ${rc}): ${output}"
    return 70
}

if [[ -n "$PUBLISH_ONCE_PATH" ]]; then
    [[ -f "$PUBLISH_ONCE_PATH" ]] || {
        echo "publish artifact not found: ${PUBLISH_ONCE_PATH}" >&2
        exit 64
    }
    if publish_staging_artifact "$PUBLISH_ONCE_PATH"; then
        echo "fenced staging artifact published: $(basename "$PUBLISH_ONCE_PATH")"
        exit 0
    else
        rc=$?
        exit "$rc"
    fi
fi

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
    mtime="$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age=$((now - mtime))
    # Keep this gate synchronized with registry_reconciler.py so the watcher
    # never hands off an envelope before the shared reconciler considers it ready.
    [[ "$age" -ge "$RESPONSE_MIN_AGE_SECONDS" ]] || return 1
    awk '/^---$/{p=!p; next} p && /^status:[[:space:]]*/ {found=1; exit} END{exit found ? 0 : 1}' "$file"
}

# FIX 3 (wave-2): this mapping is DISPLAY-ONLY (it only chooses the nudge prefix).
# It never settles a task — settlement is delegated to registry_reconciler.py via
# `registry-reconciler.sh --task-id` below, and that module's SETTLEABLE_STATUSES
# is the single canonical settle vocabulary. A status this function does not
# recognize maps to 'unknown' (informational) and cannot settle anything here.
response_status() {
    local file="$1" raw
    raw="$(frontmatter_field "$file" status | tr -d '"' | tr -d "'" | xargs)"
    case "$raw" in
        completed|complete) printf 'complete' ;;
        completed_with_partials) printf 'completed_with_partials' ;;
        completed_with_notes) printf 'completed_with_notes' ;;
        needs_review) printf 'needs_review' ;;
        needs_human) printf 'needs_human' ;;
        BLOCKED|blocked) printf 'blocked' ;;
        cancelled|canceled) printf 'cancelled' ;;
        failed|refused|timed_out) printf '%s' "$raw" ;;
        *) printf 'unknown' ;;
    esac
}

status_nudge_prefix() {
    case "$1" in
        completed|complete) printf '✅ DONE' ;;
        completed_with_partials|completed_with_notes) printf '⚠️ PARTIAL' ;;
        needs_review) printf '🔎 NEEDS REVIEW' ;;
        needs_human) printf '🚨 NEEDS HUMAN' ;;
        blocked|failed|refused|timed_out) printf '❌ BLOCKED' ;;
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

autocapture_response_best_effort() {
    local path="$1"
    [[ -n "${CHRONO_VAULT_ROOT:-}" ]] || return 0
    command -v python3 >/dev/null 2>&1 || {
        echo "[$(date '+%H:%M:%S')] warning: python3 unavailable; response auto-capture skipped" >&2
        return 0
    }
    if ! PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" python3 -c \
        'from vaultroot import resolve_vault_root; resolve_vault_root()' \
        >/dev/null 2>&1; then
        return 0
    fi
    if ! PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" python3 \
        "${VAULT_ROOT}/plugins/chrono-vault/autocapture.py" "$path" \
        >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] warning: response auto-capture failed: $(basename "$path")" >&2
    fi
    return 0
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
        mtime="$(stat -c %Y "$lockdir" 2>/dev/null || stat -f %m "$lockdir" 2>/dev/null || echo 0)"
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
    local path="$1" fname ctx status status_prefix task_id NUDGE_MSG state task_file can_nudge dept reconciler_handled reconcile_output event_state event_key
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
            if publish_staging_artifact "$path"; then
                echo "[$(date '+%H:%M:%S')] fenced staging artifact published: $(basename "$path")"
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
    reconciler_handled=0
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
                        (
                            while [[ -f "$path" ]]; do
                                sleep 1
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
    fi
    PROCESSED_PATHS="${PROCESSED_PATHS}${path}|"
    if [[ "$fname" == TASK-*-response.md ]]; then
        autocapture_response_best_effort "$path" &
    fi
    can_nudge=1
    if ! "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
        can_nudge=0
    elif ! "$TMUX_BIN" list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then
        can_nudge=0
    fi
    echo "[$(date '+%H:%M:%S')] new: ${fname} from ${ctx} via ${NAMESPACE} namespace -> queueing chrono status"

    if [[ "$fname" == TASK-*-response.md ]]; then
        if reconcile_output="$("${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$task_id" 2>&1)"; then
            if grep -Fq "reconciled ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "already-settled ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "review-required ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "review-held ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "swarm-review-required ${task_id} ->" <<<"$reconcile_output"; then
                reconciler_handled=1
                echo "[$(date '+%H:%M:%S')] shared reconciler handled registry entry: ${task_id}"
            else
                echo "[$(date '+%H:%M:%S')] shared reconciler found no settled registry entry; using notification fallback: ${task_id}"
            fi
        else
            echo "[$(date '+%H:%M:%S')] warning: failed registry reconciliation for ${task_id}: ${reconcile_output}" >&2
        fi
        if [[ "$reconciler_handled" == 0 ]]; then
            if append_chrono_queue "$task_id" "$status" "$path"; then
                echo "[$(date '+%H:%M:%S')] fallback queued chrono status entry: ${status} ${NAMESPACE}/${task_id}"
            else
                echo "[$(date '+%H:%M:%S')] warning: failed to queue chrono status entry: ${status} ${NAMESPACE}/${task_id}" >&2
            fi
        fi
        # Archive after the shared reconciler confirms either final settlement OR a
        # delivery-terminal review hold. Review-required work is complete lane-side;
        # leaving its packet in the live inbox makes the inbox watcher repeatedly try
        # to deliver work that only Chrono can settle. Invalid/failed reconciliation
        # remains open and is not archived.
        if [[ "$reconciler_handled" == 1 ]]; then
            # A response may land in a non-dispatch namespace. Archive the matching
            # task packet by id wherever it actually lives.
            for dept in "${VAULT_ROOT}"/departments/*; do
                [[ -d "$dept" ]] || continue
                for state in inbox active; do
                    task_file="${dept}/${state}/${task_id}.md"
                    if [[ -f "$task_file" ]]; then
                        mkdir -p "${dept}/archive"
                        mv "$task_file" "${dept}/archive/${task_id}.md"
                        echo "[$(date '+%H:%M:%S')] archived landed task packet: $(basename "$dept")/${state}/${task_id}.md"
                    fi
                done
            done
        else
            echo "[$(date '+%H:%M:%S')] not archiving ${task_id}: registry not canonically settled (kept in active mailbox)"
        fi
    fi

    # TASK responses are queued and nudged by the shared reconciler. Keep this
    # legacy path only for RESP-* replies or as a reconciler-failure fallback.
    if [[ "$fname" == TASK-*-response.md && "$reconciler_handled" == 1 ]]; then
        return
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
        event_state="$status"
        [[ "$event_state" == "needs_review" ]] && event_state="review-required"
        event_key="$(notification_event_key "${NAMESPACE}/${task_id:-$fname}" "$event_state")"
        if ! send_chrono_notification_once "$event_key" "$NUDGE_MSG"; then
            echo "[$(date '+%H:%M:%S')] chrono pane nudge failed; durable queue retained: ${fname}" >&2
        fi
    else
        echo "[$(date '+%H:%M:%S')] chrono pane unavailable; queued without tmux nudge: ${fname}"
    fi
}

# fswatch reports changes that happen after its stream is established. Replay
# already-landed responses first so a watcher restart cannot strand files that
# arrived while the watcher was down. Process substitution keeps the handler in
# this shell, preserving its per-process duplicate suppression for the live
# fswatch stream that follows.
scan_existing_responses() {
    local path
    while IFS= read -r -d '' path; do
        handle_response_path "$path"
    done < <(
        find "${WATCH_PATHS[@]}" -type f \
            \( -name 'TASK-*-response.md' -o -name 'RESP-*.md' -o -path "${FAILOVER_STAGING}/*/*.md" \) \
            -print0 2>/dev/null
    )
}

scan_existing_responses

fswatch -0 --event=Created --event=Updated --event=Renamed --event=MovedTo \
        -e '\.tmp$' -e '\.swp$' -e '\.lock$' -e '\.gitkeep$' \
        "${WATCH_PATHS[@]}" \
| while IFS= read -r -d '' path; do
    handle_response_path "$path"
done
