#!/bin/bash
# bin/squad-monitor.sh — Squad pathology detector.
#
# Three detectors (run every 2 min via launchd/cron):
#   1. Stuck pane    — pane output hash unchanged >5m with unread inbox
#   2. Stale active  — namespace active task has no response in >30m
#   3. Loop/thrash   — same namespace received duplicate task bodies in 30m
#
# Alerts go to chrono pane via tmux send-keys (same shape as send-task.sh nudges).
# State stored in _state/monitor/ (hash snapshots + alert dedup flags).
# No new deps: bash + tmux + stat + sha256sum + jq.
#
# Usage:
#   bash bin/squad-monitor.sh            # normal cron mode
#   bash bin/squad-monitor.sh --test     # simulate stuck pane (coding) for demo

set -uo pipefail
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"
STATE_DIR="${VAULT_ROOT}/_state/monitor"
DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
SESSION="squad"
CHRONO_PANE="${SESSION}:chrono"
NAMESPACES=(coding security content sysmgmt research)

STUCK_THRESHOLD=300    # 5 min in seconds
STALE_THRESHOLD=1800   # 30 min in seconds
THRASH_WINDOW=1800     # 30 min in seconds
THRASH_COUNT=2         # >N dispatches to same lead in window = thrash

TEST_MODE=false
[[ "${1:-}" == "--test" ]] && TEST_MODE=true

mkdir -p "${STATE_DIR}"

now=$(date +%s)
alerts=0

# ── helper: send alert to chrono pane ────────────────────────────────────────

send_alert() {
    local msg="$1"
    # tmux send-keys with -l (literal) to avoid special-char interpretation
    tmux send-keys -l -t "${CHRONO_PANE}" "MONITOR: ${msg}" 2>/dev/null
    tmux send-keys    -t "${CHRONO_PANE}" "" Enter           2>/dev/null
    echo "[$(date -u +%H:%M:%SZ)] ALERT: ${msg}"
    alerts=$((alerts + 1))
}

# ── PRE-CLEAN: archive completed inbox packets ────────────────────────────────
# If an inbox packet already has a matching outbox response, it is complete
# even if the watcher missed the archive event. Archive before stuck detection
# so completed work does not produce false pending alerts.

archive_completed_inbox() {
    local namespace="$1"
    local inbox_dir="${VAULT_ROOT}/departments/${namespace}/inbox"
    local outbox_dir="${VAULT_ROOT}/departments/${namespace}/outbox"
    local archive_dir="${VAULT_ROOT}/departments/${namespace}/archive"

    while IFS= read -r task_file; do
        [[ -z "$task_file" ]] && continue
        local task_name task_id response
        task_name=$(basename "$task_file")
        task_id="${task_name%.md}"
        response="${outbox_dir}/${task_id}-response.md"
        [[ -f "$response" ]] || continue

        mkdir -p "$archive_dir"
        mv "$task_file" "${archive_dir}/${task_name}"
        echo "[$(date -u +%H:%M:%SZ)] AUTO-ARCHIVED: ${namespace}/inbox/${task_name} (response exists)"
        rm -f "${STATE_DIR}/${namespace}-stuck-alerted"
    done < <(find "${inbox_dir}" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null)
}

# ── DETECTOR 1: stuck pane ────────────────────────────────────────────────────
# Hash last 50 lines of each model-lane pane. If hash is unchanged since last
# check AND its source namespace has unread inbox tasks, alert once per stuck episode.

detect_stuck() {
    local namespace="$1"
    local pane="${SESSION}:$(lead_window_name "${namespace}")"
    local hash_file="${STATE_DIR}/${namespace}-pane.hash"
    local ts_file="${STATE_DIR}/${namespace}-pane.ts"
    local alerted_file="${STATE_DIR}/${namespace}-stuck-alerted"

    # Capture pane (last 50 lines), compute hash
    local current_hash
    if $TEST_MODE && [[ "$namespace" == "coding" ]]; then
        current_hash="deadbeef00000000deadbeef00000000deadbeef00000000deadbeef00000000  -"
    else
        current_hash=$(tmux capture-pane -t "${pane}" -p 2>/dev/null | tail -50 | shasum -a 256 || echo "")
    fi

    [[ -z "$current_hash" ]] && return  # pane not running

    local stored_hash=""
    [[ -f "$hash_file" ]] && stored_hash=$(cat "$hash_file")

    if [[ "$current_hash" != "$stored_hash" ]]; then
        # Pane output changed — reset
        echo "$current_hash" > "${hash_file}"
        echo "$now"          > "${ts_file}"
        rm -f "${alerted_file}"
        return
    fi

    # Hash unchanged — check how long
    local last_moved
    last_moved=$(cat "${ts_file}" 2>/dev/null || echo "$now")
    local stale_secs=$(( now - last_moved ))

    [[ $stale_secs -lt $STUCK_THRESHOLD ]] && return

    # Check inbox for unread tasks
    local inbox_tasks
    inbox_tasks=$(find "${VAULT_ROOT}/departments/${namespace}/inbox" \
        -maxdepth 1 -name 'TASK-*.md' 2>/dev/null | head -1)

    [[ -z "$inbox_tasks" ]] && return  # pane idle — no work pending, not a problem

    # Already alerted this episode?
    [[ -f "$alerted_file" ]] && return

    local task_name
    task_name=$(basename "$inbox_tasks")
    local stale_min=$(( stale_secs / 60 ))
    send_alert "${namespace} namespace routed to $(lead_display_name "${namespace}") is stuck >${stale_min}m with unread inbox (${task_name})"
    touch "${alerted_file}"
}

# ── DETECTOR 2: stale active ─────────────────────────────────────────────────
# Namespace task moved to active/ but has no response in >30m.

detect_stale_active() {
    local namespace="$1"
    local active_dir="${VAULT_ROOT}/departments/${namespace}/active"

    while IFS= read -r task_file; do
        [[ -z "$task_file" ]] && continue

        local task_name
        task_name=$(basename "$task_file")
        local mtime
        mtime=$(stat -f '%m' "$task_file" 2>/dev/null || echo "$now")
        local age=$(( now - mtime ))

        [[ $age -lt $STALE_THRESHOLD ]] && continue

        local alerted_file="${STATE_DIR}/${namespace}-stale-${task_name}-alerted"
        [[ -f "$alerted_file" ]] && continue

        local age_min=$(( age / 60 ))
        send_alert "${namespace} namespace has stale active task (${task_name}, ${age_min}m old)"
        touch "${alerted_file}"
    done < <(find "${active_dir}" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null)
}

# ── DETECTOR 3: loop / thrash ─────────────────────────────────────────────────
# Content-hash dedup: hash each task body (frontmatter stripped) for every
# dispatch to this lead in the last THRASH_WINDOW seconds.  Alert only when
# the *same* hash appears >1 time — different briefs do not trigger.

detect_thrash() {
    [[ ! -f "$DISPATCH_LOG" ]] && return

    local window_start=$(( now - THRASH_WINDOW ))

    for namespace in "${NAMESPACES[@]}"; do
        # Collect body hashes for all tasks dispatched to this namespace in window
        local hash_list=""
        while IFS= read -r task_id; do
            [[ -z "$task_id" ]] && continue
            local task_file=""
            for dir in inbox active archive; do
                local f="${VAULT_ROOT}/departments/${namespace}/${dir}/${task_id}.md"
                [[ -f "$f" ]] && { task_file="$f"; break; }
            done
            [[ -z "$task_file" ]] && continue
            # Hash body only — strip YAML frontmatter (everything up to 2nd ---)
            local h
            h=$(awk 'BEGIN{n=0} /^---/{n++; next} n>=2{print}' "$task_file" \
                | shasum -a 256 | cut -d' ' -f1)
            hash_list="${hash_list}${h}"$'\n'
        done < <(jq -r --argjson ws "$window_start" --arg namespace "$namespace" '
            select(.ts != null) |
            select((.ts | fromdateiso8601) >= $ws) |
            select((.source_namespace // .compatibility_namespace // .to_lead) == $namespace) |
            .task_id
        ' "$DISPATCH_LOG" 2>/dev/null)

        [[ -z "$hash_list" ]] && continue

        # Max repeat count for any single hash — >1 means real thrash
        local max_repeats
        max_repeats=$(printf '%s' "$hash_list" | sort | uniq -c | sort -rn \
            | head -1 | awk '{print $1}')
        [[ -z "$max_repeats" || "$max_repeats" -le 1 ]] && continue

        # Bucket dedup: stable key within each THRASH_WINDOW interval
        local bucket=$(( now / THRASH_WINDOW ))
        local alerted_file="${STATE_DIR}/${namespace}-thrash-${bucket}-alerted"
        [[ -f "$alerted_file" ]] && continue

        local window_min=$(( THRASH_WINDOW / 60 ))
        send_alert "${namespace} namespace received same task ${max_repeats}x in ${window_min}m - real thrash (duplicate body)"
        touch "${alerted_file}"
    done
}

# ── BONUS: auto-archive completed active/ stubs ───────────────────────────────
# If a task in active/ has a corresponding outbox response AND the active file
# is >2h old, the Lead returned and time has passed — safe to archive the stub.
# Simpler than needs_human ack-tracking; covers the common "Lead returned, stub
# left behind" case without requiring Chrono coordination.

COMPLETED_ACTIVE_THRESHOLD=7200  # 2 hours

auto_archive_completed() {
    local namespace="$1"
    local active_dir="${VAULT_ROOT}/departments/${namespace}/active"
    local outbox_dir="${VAULT_ROOT}/departments/${namespace}/outbox"
    local archive_dir="${VAULT_ROOT}/departments/${namespace}/archive"

    while IFS= read -r task_file; do
        [[ -z "$task_file" ]] && continue
        local task_name
        task_name=$(basename "$task_file")
        local task_id="${task_name%.md}"

        # Check mtime
        local mtime
        mtime=$(stat -f '%m' "$task_file" 2>/dev/null || echo "$now")
        local age=$(( now - mtime ))
        [[ $age -lt $COMPLETED_ACTIVE_THRESHOLD ]] && continue

        # Check if response exists in outbox
        local response="${outbox_dir}/${task_id}-response.md"
        [[ ! -f "$response" ]] && continue

        # Response exists + stub is old → archive the active stub
        mkdir -p "$archive_dir"
        mv "$task_file" "${archive_dir}/${task_name}"
        echo "[$(date -u +%H:%M:%SZ)] AUTO-ARCHIVED: ${namespace}/active/${task_name} (response exists, ${age}s old)"
        # Clear any stale-alerted flag for this task (it's resolved)
        rm -f "${STATE_DIR}/${namespace}-stale-${task_name}-alerted"
    done < <(find "${active_dir}" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null)
}

# ── run all detectors ─────────────────────────────────────────────────────────

for namespace in "${NAMESPACES[@]}"; do
    archive_completed_inbox "$namespace"
    detect_stuck         "$namespace"
    detect_stale_active  "$namespace"
    auto_archive_completed "$namespace"
done
detect_thrash

# ── write monitor state for status bar ───────────────────────────────────────
# squad-health.sh picks up _state/monitor/alert-count for its mon: field.
echo "$alerts" > "${STATE_DIR}/last-alert-count"

if [[ $alerts -eq 0 ]]; then
    : # silent — no output on clean pass
else
    echo "[$(date -u +%H:%M:%SZ)] ${alerts} alert(s) sent to chrono pane."
fi
