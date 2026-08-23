#!/bin/bash
# bin/squad-monitor.sh — Squad pathology detector.
#
# Three detectors (run every 2 min via launchd/cron):
#   1. Stuck task    — a pending task has no registry activity for >5m and no
#                      response yet. Task-aware: binds to the packet's `to_model`
#                      for diagnostics, but computes idle and age from that task's
#                      registry timestamps and keys dedup by task+lane.
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

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
source "${VAULT_ROOT}/shared/lead-windows.sh"
source "${VAULT_ROOT}/shared/chrono-pane.sh"
STATE_DIR="${VAULT_ROOT}/_state/monitor"
DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
SESSION="squad"
CHRONO_PANE="${SESSION}:chrono"

STUCK_THRESHOLD=300    # 5 min in seconds
STALE_THRESHOLD=1800   # 30 min in seconds
THRASH_WINDOW=1800     # 30 min in seconds

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
    local msg="$1" pane_cmd=""
    # Only type into the pane when Chrono is actually the thing listening.
    # Without this check the alert is delivered to whatever process holds the
    # pane -- and when Chrono has exited, that is a bare shell, which EXECUTES
    # the alert. Observed on the maintainer host: board notices became
    # "zsh: command not found: git", "zsh: no such file or directory: _state/",
    # "zsh: no matches found: (26418 bytes)". The operator saw a pane that was
    # not Chrono; the alerts were not merely lost, they were run.
    #
    # bin/outbox-watcher.sh already guards its own send this way. This is the
    # same check, spelled the same, because the two notifiers had drifted and
    # only one of them was safe.
    pane_cmd="$(chrono_pane_observed_command "${CHRONO_PANE}")"
    if chrono_pane_has_coordinator "${CHRONO_PANE}"; then
        # -l (literal) so special characters are not interpreted by tmux.
        tmux send-keys -l -t "${CHRONO_PANE}" "MONITOR: ${msg}" 2>/dev/null
        tmux send-keys    -t "${CHRONO_PANE}" "" Enter           2>/dev/null
    else
        # Not lost: the line below is the durable record, and bin/board-notify.sh
        # serves headless readers. Say which command was there, so a wrong pane
        # is diagnosable instead of silent.
        echo "[$(date -u +%H:%M:%SZ)] pane nudge skipped: ${CHRONO_PANE} runs '${pane_cmd:-unavailable}', expected 'claude'"
    fi
    echo "[$(date -u +%H:%M:%SZ)] ALERT: ${msg}"
    alerts=$((alerts + 1))
}

# ── watchdog helpers (Fix 1 / Fix 2 / Fix 3) ─────────────────────────────────

# Read a packet's to_model frontmatter.
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

# Idle seconds for one task, measured from its newest registry activity field.
# dispatched_at is always a candidate, so idle can never exceed task age.
task_idle_secs() {
    [[ -f "$REGISTRY" ]] || return
    local field iso epoch latest=""
    for field in \
        last_activity_at heartbeat_observed_at started_at claimed_at \
        delivery_last_attempt_at enqueued_at dispatched_at
    do
        iso=$(jq -r --arg t "$1" --arg f "$field" '.[$t][$f] // empty' "$REGISTRY" 2>/dev/null)
        [[ -n "$iso" ]] || continue
        epoch=$(iso_to_epoch "$iso") || continue
        if [[ -z "$latest" || $epoch -gt $latest ]]; then
            latest="$epoch"
        fi
    done
    [[ -n "$latest" ]] || return
    [[ $latest -gt $now ]] && latest="$now"
    echo $(( now - latest ))
}

# Registry lifecycle status for stale/awaiting-review classification.
task_registry_status() {
    [[ -f "$REGISTRY" ]] || return
    jq -r --arg t "$1" '.[$t].status // empty' "$REGISTRY" 2>/dev/null
}

# Completion evidence must match the live reconciliation rail, not an inferred
# mailbox state. A terminal registry status, a promoted response (including the
# V1 cross-namespace compatibility search), or an identity-fenced terminal board
# receipt all falsify "no response yet". This helper is deliberately re-run at
# the alert boundary because completion can land after detect_stuck starts.
task_has_completion_evidence() {
    local task_id="$1" status evidence_path state candidate
    status=$(task_registry_status "$task_id")
    case "$status" in
        complete|completed|blocked|needs_review|needs_human|cancelled|closed|superseded|work-done-no-envelope|review-required)
            return 0
            ;;
    esac

    # Reconciliation records either the selected response or its canonical
    # expected path. Presence is enough to falsify this monitor's literal claim;
    # status/schema validation remains the reconciler's responsibility.
    evidence_path=$(jq -r --arg t "$task_id" \
        '.[$t].response_path // .[$t].expected_response_path // empty' \
        "$REGISTRY" 2>/dev/null)
    if [[ -n "$evidence_path" && -f "${VAULT_ROOT}/${evidence_path}" ]]; then
        return 0
    fi

    # Live V3 response discovery searches every mailbox outbox/archive. This
    # also prevents source/compatibility namespace splits from becoming a stall.
    for state in outbox archive; do
        for candidate in \
            "${VAULT_ROOT}"/departments/*/"${state}"/"${task_id}-response.md"
        do
            [[ -f "$candidate" ]] && return 0
        done
    done

    # The board receipt is the completion path's safety net when response
    # promotion has not happened yet. Accept it only when task, attempt, and
    # generation match the registry fence.
    local attempt_id generation receipt receipt_status
    attempt_id=$(jq -r --arg t "$task_id" \
        '.[$t].delivery_attempt_id // empty' "$REGISTRY" 2>/dev/null)
    generation=$(jq -r --arg t "$task_id" \
        '.[$t].delivery_generation // 1' "$REGISTRY" 2>/dev/null)
    [[ "$attempt_id" =~ ^[A-Za-z0-9._-]+$ ]] || return 1
    [[ "$generation" =~ ^[1-9][0-9]*$ ]] || return 1
    receipt="${VAULT_ROOT}/_state/board-dispatch/${task_id}.${attempt_id}.receipt.json"
    [[ -f "$receipt" ]] || return 1
    receipt_status=$(jq -r \
        --arg task "$task_id" --arg attempt "$attempt_id" \
        --argjson generation "$generation" '
        if .task_id == $task and .attempt_id == $attempt
           and ((.generation == null and $generation == 1)
                or .generation == $generation)
        then (.status // empty) else empty end
        ' "$receipt" 2>/dev/null)
    case "$receipt_status" in
        complete|completed|blocked|failed|denied|needs_review|needs_human|cancelled)
            return 0
            ;;
    esac
    return 1
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

# Identity, not bare liveness. Args: $1 a *.dispatch.json path. True only when
# the process at the descriptor's PID is still the SAME process the dispatcher
# recorded there.
#
# Was `kill -0 "$pid"` on a PID read straight out of the descriptor. Those
# files outlive their process by days, and this predicate is only ever reached
# for dispatches with NO terminal receipt -- i.e. exactly the stalled ones. A
# recycled PID therefore read as "the board is supervising this", detect_stuck
# returned early forever, and the task never alerted: a guard satisfied by an
# unrelated process, suppressing the alarm that exists to notice it. Same
# defect class as the two liveness checks rewritten below it.
#
# The board spawn has no fixed argv shape -- it is whatever specialist CLI the
# packet routed to -- so shared/process-identity.sh's exact-argv approach does
# not apply. board_process_truth.process_truth() is the established mechanism
# for this exact question and its home: the descriptor already carries
# `process_start_token` (the kernel start-time fingerprint) and `argv_sha256`,
# written by observe_process() at spawn, and process_truth() re-observes and
# compares them plus session leadership. Reusing it rather than restating the
# comparison here keeps one answer to "is this dispatch's process alive".
#
# A descriptor too old to carry that identity (schema v1) reads as NOT live,
# which is the safe direction: the monitor alerts on a task it cannot vouch
# for rather than silently suppressing it.
board_dispatch_process_is_live() {
    python3 - "${VAULT_ROOT}" "$1" <<'PY' 2>/dev/null
import sys
from pathlib import Path

vault, dispatch = sys.argv[1], sys.argv[2]
sys.path.insert(0, str(Path(vault) / "scripts" / "python"))
from board_process_truth import load_json, process_truth  # noqa: E402

descriptor = load_json(dispatch)
if not isinstance(descriptor, dict):
    raise SystemExit(1)
truth = process_truth(dispatch, descriptor)
# A SIGSTOPped supervisor keeps a matching identity, so `state == "live"` alone
# read it as healthy and this monitor stayed silent -- measured 2026-08-22, one
# sat stopped for 9h30m. Identity answers "is it the same process"; it cannot
# answer "is it still doing anything". Require both, and treat an unknown run
# state as NOT live, matching the schema-v1 reasoning above: alert on what
# cannot be vouched for rather than silently suppress it.
raise SystemExit(
    0
    if truth["state"] == "live" and truth.get("run_state") == "running"
    else 1
)
PY
}

# Board-native liveness: a task that is running as a DETACHED board spawn (a live
# supervisor pid with no terminal receipt) is NOT stuck in a pane inbox — the board
# supervises it. Returns 0 when a live board spawn exists for the task id.
board_spawn_live() {
    local tid="$1" d base status
    for d in "${VAULT_ROOT}/_state/board-dispatch/${tid}."*.dispatch.json; do
        [[ -f "$d" ]] || continue
        base="${d%.dispatch.json}"
        if [[ -s "${base}.receipt.json" ]]; then
            status=$(python3 -c "import json;print(json.load(open('${base}.receipt.json')).get('status',''))" 2>/dev/null)
            case "$status" in complete|completed|blocked|needs_review|launched|failed) continue ;; esac
        fi
        board_dispatch_process_is_live "$d" && return 0
    done
    return 1
}

detect_stuck() {
    # Task-aware stall detector. For each pending inbox packet in this namespace,
    # bind to the packet's to_model executing lane (NOT the namespace default lead)
    # for diagnostics and alert when the task's own registry activity has been idle
    # >= STUCK_THRESHOLD with the task still un-responded.
    local namespace="$1"
    local inbox_dir="${VAULT_ROOT}/departments/${namespace}/inbox"

    while IFS= read -r task_file; do
        [[ -z "$task_file" ]] && continue
        local task_name task_id
        task_name=$(basename "$task_file")
        task_id="${task_name%.md}"
        task_has_completion_evidence "$task_id" && continue

        # Fix 1: executing lane comes from the packet, not the namespace default.
        local to_model lane pane
        to_model=$(packet_to_model "$task_file")
        [[ -z "$to_model" ]] && to_model=$(namespace_default_model "$namespace")  # legacy fallback
        lane=$(runtime_window_name "$to_model")
        pane="${SESSION}:${lane}"

        # Has this task's own registry record been inactive long enough?
        local idle_secs
        idle_secs=$(task_idle_secs "$task_id")
        [[ -z "$idle_secs" ]] && continue                 # task has no usable timestamp
        [[ $idle_secs -lt $STUCK_THRESHOLD ]] && continue # task still actively moving

        # Dedup: at most one alert per task+lane episode (cleared on completion).
        local alerted_file="${STATE_DIR}/stuck-task-${task_id}-${lane}-alerted"
        [[ -f "$alerted_file" ]] && continue

        # Board-native guard: the task is running as a live DETACHED board spawn, not a
        # stuck pane task — the board supervises it (and the dashboard shows live/idle).
        # Skip the pane-era "idle N min / pending in inbox" false alert.
        if board_spawn_live "$task_id"; then
            continue
        fi

        # Liveness guard 1: a subagent working THIS task is writing artifacts to
        # /tmp/cdp_dumps (<90s ago). Scoped to this task's id in the dump path --
        # unscoped, any unrelated subagent's browser dumps suppressed the stall
        # alert for every task in every namespace, and /tmp is world-writable.
        if find /tmp/cdp_dumps -mindepth 2 -maxdepth 4 -type f -newermt '90 seconds ago' 2>/dev/null \
            | grep -qF -- "${task_id}"; then
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
        [[ -n "$disp_epoch" && $disp_epoch -gt $now ]] && disp_epoch="$now"
        [[ -n "$disp_epoch" ]] && age_min=$(( ( now - disp_epoch ) / 60 ))
        local idle_min=$(( idle_secs / 60 ))

        # Completion can race every check above. Re-read the same authoritative
        # evidence immediately before making the falsifiable "no response" claim.
        task_has_completion_evidence "$task_id" && continue

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

        local task_name task_id status
        task_name=$(basename "$task_file")
        task_id="${task_name%.md}"
        local mtime
        # Portable idiom (same as bin/outbox-watcher.sh): -f is BSD-only, so on
        # Linux this always fell through to the fallback -- and echo "$now" made
        # a failed stat read as "just touched", never stale. echo 0 fails toward
        # alerting instead.
        mtime=$(stat -c '%Y' "$task_file" 2>/dev/null || stat -f '%m' "$task_file" 2>/dev/null || echo 0)
        local age=$(( now - mtime ))

        [[ $age -lt $STALE_THRESHOLD ]] && continue

        status=$(task_registry_status "$task_id")
        case "$status" in
            needs_review|review-required)
                echo "[$(date -u +%H:%M:%SZ)] INFO: ${namespace}/${task_name} awaiting review (${status}); not stale"
                continue
                ;;
        esac

        local alerted_file="${STATE_DIR}/${namespace}-stale-${task_name}-alerted"
        [[ -f "$alerted_file" ]] && continue

        # Board-native guard: don't flag a task that's a live detached board spawn.
        board_spawn_live "$task_id" && continue

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

    for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
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

        # Check mtime. Portable idiom (same as bin/outbox-watcher.sh); echo 0
        # fails toward archiving, not away from it, on a failed stat.
        local mtime
        mtime=$(stat -c '%Y' "$task_file" 2>/dev/null || stat -f '%m' "$task_file" 2>/dev/null || echo 0)
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

# Keep per-lane pane snapshots for diagnostics; task idle comes from the registry.
update_lane_hashes

for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
    archive_completed_inbox "$namespace"
    detect_stuck         "$namespace"
    detect_stale_active  "$namespace"
    auto_archive_completed "$namespace"
done
detect_thrash

# ── write monitor state for status bar ───────────────────────────────────────
# bin/chrono-status-segment.sh picks up _state/monitor/alert-count for its mon: field.
echo "$alerts" > "${STATE_DIR}/last-alert-count"

if [[ $alerts -eq 0 ]]; then
    : # silent — no output on clean pass
else
    echo "[$(date -u +%H:%M:%SZ)] ${alerts} alert(s) sent to chrono pane."
fi
