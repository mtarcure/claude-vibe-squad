#!/bin/bash
# bin/squad-monitor.sh — Squad pathology detector.
#
# Three detectors (run every 2 min via launchd/cron):
#   1. Stuck task    — a pending task's to_model executing-lane pane is idle >5m
#                      with no response yet. Task-aware: binds to the packet's
#                      `to_model` (not the namespace default lead), reports age
#                      from the registry `dispatched_at`, keys dedup by task+lane.
#                      ALERT-ONLY by design — there is NO automated re-nudge;
#                      recovery is Chrono-in-the-loop after it verifies pane activity.
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

# Task-aware stall watchdog (Fix 1 + Fix 2). detect_stuck binds to the packet's
# to_model executing lane, not the namespace default lead.
REGISTRY="${VAULT_ROOT}/_state/active-tasks.json"
MODEL_LANES_LIST=(gpt-codex claude gemini kimi)
STALL_DIAG_LOG="${STATE_DIR}/stall-diagnostics.log"   # Fix 3: on-stall stop_reason capture
# The watchdog is ALERT-ONLY: there is no auto-nudge path and no env toggle. A
# robust "pane is idle, safe to nudge" classifier proved unattainable (it can
# misread active work as idle — gpt-codex review TASK-2026-07-12-1854-93b52a53),
# so recovery is Chrono-in-the-loop: it verifies pane activity, then decides.

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

# ── watchdog helpers (Fix 1 / Fix 2 / Fix 3) ─────────────────────────────────

# Read a packet's to_model frontmatter (same awk as bin/inbox-watcher.sh:41).
packet_to_model() {
    awk '/^---$/{p=!p; next} p && /^to_model:/ {sub(/^to_model:[[:space:]]*/, ""); print; exit}' "$1" 2>/dev/null
}

# Robust ISO-8601 → epoch (handles fractional seconds + +00:00 / Z offsets).
iso_to_epoch() {
    python3 -c 'import sys,datetime as dt
s=sys.argv[1].strip().replace("Z","+00:00")
try:
    print(int(dt.datetime.fromisoformat(s).timestamp()))
except Exception:
    sys.exit(1)' "$1" 2>/dev/null
}

# Task age source of truth: registry dispatched_at, else packet created.
task_dispatched_epoch() {
    [[ -f "$REGISTRY" ]] || return
    local iso
    iso=$(jq -r --arg t "$1" '.[$t].dispatched_at // empty' "$REGISTRY" 2>/dev/null)
    [[ -n "$iso" ]] && iso_to_epoch "$iso"
}
packet_created_epoch() {
    local iso
    iso=$(awk '/^---$/{p=!p; next} p && /^created:/ {sub(/^created:[[:space:]]*/, ""); print; exit}' "$1" 2>/dev/null)
    [[ -n "$iso" && "$iso" != "none" ]] && iso_to_epoch "$iso"
}

# Idle seconds for a lane's pane, keyed by canonical window name. Empty = untracked.
lane_idle_secs() {
    local key ts_file ts
    key=$(runtime_window_name "$1")
    ts_file="${STATE_DIR}/lane-${key}-pane.ts"
    [[ -f "$ts_file" ]] || { echo ""; return; }
    ts=$(cat "$ts_file" 2>/dev/null)
    [[ -z "$ts" ]] && { echo ""; return; }
    echo $(( now - ts ))
}

# Hash all 4 model-lane panes once per run; reset the idle timestamp on change.
# Keyed by lane (not namespace) so a to_model override is tracked on the real
# executing pane, not the namespace default lead.
update_lane_hashes() {
    local lane key pane current_hash hash_file ts_file stored_hash
    for lane in "${MODEL_LANES_LIST[@]}"; do
        key=$(runtime_window_name "$lane")
        pane="${SESSION}:${key}"
        if $TEST_MODE && [[ "$key" == "claude" ]]; then
            current_hash="deadbeef00000000deadbeef00000000deadbeef00000000deadbeef00000000  -"
        else
            current_hash=$(tmux capture-pane -t "${pane}" -p 2>/dev/null | tail -50 | shasum -a 256 || echo "")
        fi
        [[ -z "$current_hash" ]] && continue   # pane not running
        hash_file="${STATE_DIR}/lane-${key}-pane.hash"
        ts_file="${STATE_DIR}/lane-${key}-pane.ts"
        stored_hash=""
        [[ -f "$hash_file" ]] && stored_hash=$(cat "$hash_file")
        if [[ "$current_hash" != "$stored_hash" ]]; then
            echo "$current_hash" > "$hash_file"
            echo "$now"          > "$ts_file"
        fi
    done
}

# (No positive-idle classifier: the auto-nudge path was removed. A finite negative
# regex plus "any prompt-like line in a pane tail" cannot guarantee a pane is idle
# rather than actively working, so the watchdog only ALERTS — see the top comment.)

# Fix 3: on a claude-lane stall, record the last turn's stop_reason from the lane's
# Claude Code session jsonl so a genuine mid-task turn-end is diagnosable. Read-only.
capture_stop_reason() {
    local to_model="$1" task_id="$2" stamp
    stamp="[$(date -u +%FT%TZ)]"
    if [[ "$(runtime_window_name "$to_model")" != "claude" ]]; then
        echo "${stamp} ${task_id} lane=${to_model}: stop_reason capture only wired for the claude lane" >> "$STALL_DIAG_LOG"
        return
    fi
    local proj jsonl sr
    proj="${HOME}/.claude/projects/$(printf '%s' "${VAULT_ROOT}/model-lanes/claude" | sed 's#/#-#g')"
    jsonl=$(ls -t "${proj}"/*.jsonl 2>/dev/null | head -1)
    if [[ -z "$jsonl" ]]; then
        echo "${stamp} ${task_id}: no session jsonl under ${proj}" >> "$STALL_DIAG_LOG"
        return
    fi
    sr=$(tail -80 "$jsonl" | jq -rs 'map(select(.type=="assistant")) | (last // {}) | "stop_reason=\(.message.stop_reason // "null") at=\(.timestamp // "null")"' 2>/dev/null)
    echo "${stamp} STALL ${task_id} lane=${to_model} session=$(basename "$jsonl") ${sr}" >> "$STALL_DIAG_LOG"
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
        rm -f "${STATE_DIR}/stuck-task-${task_id}"-*-alerted   # clear the task+lane marker for any lane
    done < <(find "${inbox_dir}" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null)
}

# ── DETECTOR 1: stuck pane ────────────────────────────────────────────────────
# Hash last 50 lines of each model-lane pane. If hash is unchanged since last
# check AND its source namespace has unread inbox tasks, alert once per stuck episode.

detect_stuck() {
    # Task-aware stall detector. For each pending inbox packet in this namespace,
    # bind to the packet's to_model executing lane (NOT the namespace default lead)
    # and alert when that lane's pane has been idle >= STUCK_THRESHOLD with the task
    # still un-responded. Age is reported from the registry dispatched_at.
    local namespace="$1"
    local inbox_dir="${VAULT_ROOT}/departments/${namespace}/inbox"
    local outbox_dir="${VAULT_ROOT}/departments/${namespace}/outbox"

    while IFS= read -r task_file; do
        [[ -z "$task_file" ]] && continue
        local task_name task_id response
        task_name=$(basename "$task_file")
        task_id="${task_name%.md}"
        response="${outbox_dir}/${task_id}-response.md"
        [[ -f "$response" ]] && continue          # already complete — not stuck

        # Fix 1: executing lane comes from the packet, not the namespace default.
        local to_model lane pane
        to_model=$(packet_to_model "$task_file")
        [[ -z "$to_model" ]] && to_model=$(namespace_default_model "$namespace")  # legacy fallback
        lane=$(runtime_window_name "$to_model")
        pane="${SESSION}:${lane}"

        # Is that lane's pane idle long enough? (idle time is tracked per lane.)
        local idle_secs
        idle_secs=$(lane_idle_secs "$to_model")
        [[ -z "$idle_secs" ]] && continue                 # lane pane not running/tracked
        [[ $idle_secs -lt $STUCK_THRESHOLD ]] && continue # lane still actively moving

        # Dedup: at most one alert per task+lane episode (cleared on completion).
        local alerted_file="${STATE_DIR}/stuck-task-${task_id}-${lane}-alerted"
        [[ -f "$alerted_file" ]] && continue

        # Liveness guard 1: a subagent is writing artifacts to /tmp/cdp_dumps (<90s ago).
        if find /tmp/cdp_dumps -mindepth 2 -maxdepth 4 -type f -newermt '90 seconds ago' 2>/dev/null \
            | head -1 | grep -q .; then
            continue
        fi
        # Liveness guard 2: the executing pane shows an active-subagent indicator.
        if tmux capture-pane -t "${pane}" -p 2>/dev/null | tail -10 \
            | grep -qE 'local agent.*running|✻ (Working|Brewed|Baked|Manifesting|Crunched|Musing|Churned|Cooking) for|⏵⏵.*esc to interrupt'; then
            continue
        fi

        # Age from the registry dispatched_at (fallback: packet created), NOT a pane ts.
        local disp_epoch age_min="?"
        disp_epoch=$(task_dispatched_epoch "$task_id")
        [[ -z "$disp_epoch" ]] && disp_epoch=$(packet_created_epoch "$task_file")
        [[ -n "$disp_epoch" ]] && age_min=$(( ( now - disp_epoch ) / 60 ))
        local idle_min=$(( idle_secs / 60 ))

        # ALERT-FIRST (always): correct lane + correct age, keyed by task id + lane.
        send_alert "task ${task_id} → ${to_model} lane ($(runtime_display_name "$to_model")) idle ${idle_min}m, no response yet (dispatched ${age_min}m ago); pending in ${namespace}/inbox"
        touch "${alerted_file}"

        # Fix 3: capture the lane's last-turn stop_reason for post-hoc diagnosis.
        capture_stop_reason "$to_model" "$task_id"

        # Recovery is Chrono-in-the-loop by design: the watchdog does NOT re-nudge.
        # An automated idle-classifier cannot guarantee it won't interrupt active
        # work (gpt-codex review TASK-2026-07-12-1854-93b52a53), so we only ALERT —
        # Chrono verifies the lane's real state and decides whether to re-nudge.
    done < <(find "${inbox_dir}" -maxdepth 1 -name 'TASK-*.md' 2>/dev/null | sort)
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

# The failover watchdog shares the controller's dormant-by-default gate. It
# consumes only hard typed sensors automatically; the existing pane/staleness
# detectors below remain alert-only for ambiguous liveness observations.
if [[ "${FAILOVER_CONTROL_ENABLED:-0}" == "1" || -f "${VAULT_ROOT}/_state/failover/ENABLED" ]]; then
    if command -v uv >/dev/null 2>&1; then
        uv run --with-requirements "${VAULT_ROOT}/daemon/requirements.txt" \
            python "${VAULT_ROOT}/daemon/failover_watchdog.py" --once \
            || send_alert "conservative failover watchdog failed; operator inspection required"
    else
        send_alert "conservative failover watchdog requires uv; operator inspection required"
    fi
fi

# Track per-lane pane idle time once up front, so detect_stuck can bind each
# pending task to its real to_model executing pane (not the namespace default).
update_lane_hashes

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
