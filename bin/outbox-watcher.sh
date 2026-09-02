#!/bin/bash
# Outbox watcher — observes compatibility-outbox responses and asks the shared
# reconciler to settle TASK-* envelopes. Its live notification path is narrower:
# `tmux send-keys` targets only the Chrono (Coordinator) window.
#
# A successful tmux call proves keystrokes reached that pane, not that a human or
# controller read them. An absent or unattended pane has no live recipient. TASK
# events retain file/registry state, and reconciler-emitted events also retain a
# Chrono-queue record for a later reader; RESP-* replies retain only their file plus
# a best-effort pane nudge.
#
# This is settlement/notification glue, not headless broadcast. A polling controller
# must start bin/board-notify.sh as a best-effort target-state observer and consume
# its stdout; launch-squad starts this outbox watcher, not that registry watcher.
#
# Usage:  bash bin/outbox-watcher.sh <source-namespace>
# Typically launched by launch-squad.sh in the watcher/status window.

set -uo pipefail

NOTIFY_ONCE_EVENT_KEY=""
NOTIFY_ONCE_MESSAGE=""
NOTIFY_ONCE_MODE=0
if [[ "${1:-}" == "--notify-once" ]]; then
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

if [[ "$NOTIFY_ONCE_MODE" == 0 ]] && ! command -v fswatch >/dev/null 2>&1; then
    echo "fswatch not installed — install with: brew install fswatch"
    exit 1
fi

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
SESSION="${SQUAD_SESSION:-squad}"
TMUX_BIN="${TMUX_BIN:-tmux}"
source "${VAULT_ROOT}/shared/chrono-pane.sh"
CHRONO_TMUX_TARGET="${SESSION}:chrono.0"
# Kept only for the skip message. It is NOT the test any more: the live pane
# reports the versioned executable ("2.1.233"), so comparing to this literal
# skipped every nudge while Chrono was running. See shared/chrono-pane.sh.
EXPECTED_CHRONO_PANE_COMMAND="the coordinator CLI"
RESPONSE_MIN_AGE_SECONDS="${RESPONSE_MIN_AGE_SECONDS:-5}"
if [[ ! "$RESPONSE_MIN_AGE_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "RESPONSE_MIN_AGE_SECONDS must be a non-negative integer" >&2
    exit 1
fi
# "all" consolidates every namespace into ONE watcher. Measured 2026-08-08:
# six per-namespace watchers cost 22 MB and 0% CPU, so this is not a
# performance change -- it removes a reliability failure. Each namespace ran
# its own supervisor->watcher->child chain that leaked children over time
# (coding reached 5 processes, security 4), and every extra copy fired its own
# duplicate notification for the same response file. One process cannot
# duplicate itself across namespaces. A single fswatch over all six outboxes
# was measured at 31-48 ms detection for simultaneous writes, faster than the
# 0.3 s loop it replaces.
ALL_NAMESPACES=0
if [[ "${NAMESPACE}" == "all" ]]; then
    ALL_NAMESPACES=1
fi
OUTBOX="${VAULT_ROOT}/departments/${NAMESPACE}/outbox"
STATE_DIR="${VAULT_ROOT}/_state"
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
        # GNU-first: `stat -c` is a clean no-op on macOS (empty stdout, rc=1),
        # but GNU `stat -f` means --file-system and writes filesystem rows to
        # STDOUT, which concatenate with the fallback and fail the guard below.
        lock_mtime="$(stat -c %Y "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null \
            || stat -f %m "${CHRONO_NOTIFY_LOCKDIR}" 2>/dev/null || true)"
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
    local event_key="$1" message="$2" receipt_hash receipt tmp pane_current_command
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
        echo "[$(date '+%H:%M:%S')] chrono pane nudge skipped: target=${CHRONO_TMUX_TARGET} unavailable; no notification lost: registry/outbox records persist and bin/board-notify.sh serves headless registry readers" >&2
        release_chrono_notify_lock || return 1
        return 2
    fi
    pane_current_command="$(chrono_pane_observed_command "$CHRONO_TMUX_TARGET")"
    if ! chrono_pane_has_coordinator "$CHRONO_TMUX_TARGET"; then
        printf "[%s] chrono pane nudge skipped: target=%s expected_command=%q actual_command=%q; no notification lost: registry/outbox records persist and bin/board-notify.sh serves headless registry readers\n" \
            "$(date '+%H:%M:%S')" "$CHRONO_TMUX_TARGET" "$EXPECTED_CHRONO_PANE_COMMAND" "${pane_current_command:-unavailable}" >&2
        release_chrono_notify_lock || return 1
        return 2
    fi
    if ! "$TMUX_BIN" send-keys -l -t "$CHRONO_TMUX_TARGET" "$message"; then
        release_chrono_notify_lock || return 1
        return 1
    fi
    sleep 0.3
    if ! "$TMUX_BIN" send-keys -t "$CHRONO_TMUX_TARGET" Enter; then
        release_chrono_notify_lock || return 1
        return 1
    fi
    if ! printf 'event_key=%s\nmessage_sha256=%s\nsent_at=%s\ntarget=%s\n' \
        "$event_key" \
        "$(printf '%s' "$message" | shasum -a 256 | awk '{print $1}')" \
        "$(date -u +%FT%TZ)" \
        "$CHRONO_TMUX_TARGET" > "$tmp" \
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

if [[ "$ALL_NAMESPACES" != "1" ]]; then mkdir -p "${OUTBOX}"; fi
if [[ "$ALL_NAMESPACES" == "1" ]]; then
    WATCH_PATHS=()
    for _ns_dir in "${VAULT_ROOT}"/departments/*/; do
        [[ -d "${_ns_dir}outbox" ]] || mkdir -p "${_ns_dir}outbox"
        WATCH_PATHS+=("${_ns_dir}outbox")
    done
    unset _ns_dir
else
    WATCH_PATHS=("${OUTBOX}")
fi

if [[ "$ALL_NAMESPACES" == "1" ]]; then
    echo "Watching ${#WATCH_PATHS[@]} namespace outboxes (consolidated) for new responses; will nudge squad:chrono pane on each."
else
    echo "Watching ${OUTBOX}/ for new responses; will nudge squad:chrono pane on each."
fi

if [[ "$NAMESPACE" == "coding" || "$ALL_NAMESPACES" == "1" ]]; then
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
    awk -v key="$field" -v source="$file" '
        function reject(message) {
            print source ": " message > "/dev/stderr"
            invalid=1
            exit 65
        }

        NR == 1 {
            started=1
            if ($0 != "---") {
                reject("frontmatter must begin with an exact --- delimiter at line 1")
            }
            parsing=1
            next
        }

        parsing && $0 == "---" {
            closed=1
            parsing=0
            exit
        }

        parsing {
            # Blank and comment lines do not end an empty-key lookahead: an
            # indented child after either still belongs to that empty key.
            if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*#/) {
                next
            }
            if ($0 ~ /^[[:space:]]/) {
                if (empty_key != "") {
                    reject(sprintf("frontmatter key %c%s%c at line %d has nested content at line %d; flat scalar values are required", 39, empty_key, 39, empty_line, NR))
                }
                reject(sprintf("frontmatter line %d is indented; top-level flat scalar key/value pairs are required", NR))
            }

            separator=index($0, ":")
            if (separator == 0) {
                reject(sprintf("frontmatter line %d is not a top-level key/value pair; flat scalar values are required", NR))
            }
            parsed_key=substr($0, 1, separator - 1)
            if (parsed_key !~ /^[A-Za-z_][A-Za-z0-9_-]*$/) {
                reject(sprintf("frontmatter line %d has an invalid key", NR))
            }
            if (parsed_key in first_line) {
                reject(sprintf("frontmatter key %c%s%c is duplicated at line %d (first declared at line %d); one flat scalar per key is required", 39, parsed_key, 39, NR, first_line[parsed_key]))
            }

            raw_value=substr($0, separator + 1)
            first_line[parsed_key]=NR
            value[parsed_key]=raw_value
            sub(/^[[:space:]]*/, "", value[parsed_key])

            empty_key=""
            empty_line=0
            scalar_probe=raw_value
            gsub(/[[:space:]]/, "", scalar_probe)
            if (scalar_probe == "") {
                empty_key=parsed_key
                empty_line=NR
            }
            next
        }

        END {
            if (invalid) {
                exit 65
            }
            if (!started) {
                print source ": frontmatter is empty; an exact --- delimiter is required at line 1" > "/dev/stderr"
                exit 65
            }
            if (!closed) {
                print source ": frontmatter is unclosed; an exact --- delimiter is required" > "/dev/stderr"
                exit 65
            }
            if (key in first_line) {
                print value[key]
            }
        }
    ' "$file"
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

legacy_response_ready_for_status() {
    local file="$1" mtime now age
    [[ -f "$file" ]] || return 1
    mtime="$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age=$((now - mtime))
    # Legacy quiescence/display only. V2 settlement reaches the reconciler first.
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
    # stderr is KEPT, not discarded. It used to go to /dev/null, so the only
    # thing that reached the log was "auto-capture failed: <file>" -- never
    # WHY. A distillation failure writes no semantic note at all, and its
    # cause (an unauthenticated agy-backed `gemini` lane, a timeout, or an
    # unparseable reply) is
    # the entire content of the alert. Bounded to one line so a runaway
    # traceback cannot flood the watcher log; the full reason is also counted
    # in _state/autocapture-failures.jsonl, which outlives the log.
    local capture_error
    capture_error="$(
        PYTHONPATH="${VAULT_ROOT}/plugins/chrono-vault" python3 \
            "${VAULT_ROOT}/plugins/chrono-vault/autocapture.py" "$path" \
            2>&1 >/dev/null
    )" || echo "[$(date '+%H:%M:%S')] warning: response auto-capture failed: $(basename "$path"): ${capture_error%%$'\n'*}" >&2
    return 0
}

record_skill_telemetry_best_effort() {
    local task_id="$1" telemetry_error
    telemetry_error="$(
        python3 "${VAULT_ROOT}/scripts/python/dispatch_log.py" record-skills \
            --repo-root "${VAULT_ROOT}" --task-id "$task_id" \
            2>&1 >/dev/null
    )" || echo "[$(date '+%H:%M:%S')] warning: skill telemetry failed for ${task_id}: ${telemetry_error%%$'\n'*}" >&2
    return 0
}

# Bound the auto-capture fan-out. `scan_existing_responses` below replays
# every response file in every outbox on every watcher start -- 1,571 of them
# when this bound was added -- and each one forks two python3 processes. A
# replayed response now returns `duplicate` before any model call
# (`autocapture.capture_response`), but 1,571 CONCURRENT forks is still a
# thundering herd on the operator's live machine, and the fresh-response path
# genuinely does spawn a model subprocess per capture.
#
# Oldest-first: launch, then block on the oldest outstanding job once the
# window is full. `wait -n` would express this directly and does not exist in
# bash 3.2, which is what `#!/bin/bash` resolves to on macOS. A plain `wait`
# is wrong here too: this shell also backgrounds the long-lived legacy
# response pollers, and waiting on those would stall the watcher.
#
# The knob is VALIDATED, because two ordinary values used to hang the whole
# watcher. `[[ "$#" -ge 0 ]]` is always true and `shift` on an empty list
# cannot advance, so a bound of 0 spun the loop below forever; a non-numeric
# value hit the same spin, since `[[ -ge ]]` evaluates an unparseable operand
# as 0. `0` is exactly what an operator reaches for to turn auto-capture off,
# so this was a live hang waiting for an ordinary config edit -- verified
# under /bin/bash 3.2, where both `0` and `bogus` ran until a 5s timeout
# killed them. The two cases resolve differently on purpose:
#
#   0            OFF. Nothing is dispatched and no model subprocess is
#                forked. This is the reading the value invites, and turning
#                auto-capture off is a thing an operator may legitimately
#                want -- silently reinterpreting it as "unbounded" would fork
#                a process per response on a machine asking for none.
#   not a count  The DEFAULT, loudly. A typo must never be able to switch
#                memory capture off by accident: the failure direction for a
#                malformed throttle is "keep capturing, keep the bound",
#                announced on stderr so the operator can see the value did
#                not take.
AUTOCAPTURE_MAX_INFLIGHT_DEFAULT=8
AUTOCAPTURE_MAX_INFLIGHT="${CHRONO_AUTOCAPTURE_MAX_INFLIGHT:-${AUTOCAPTURE_MAX_INFLIGHT_DEFAULT}}"
if [[ ! "${AUTOCAPTURE_MAX_INFLIGHT}" =~ ^[0-9]+$ ]]; then
    echo "[$(date '+%H:%M:%S')] warning: CHRONO_AUTOCAPTURE_MAX_INFLIGHT='${AUTOCAPTURE_MAX_INFLIGHT}' is not a whole number; using ${AUTOCAPTURE_MAX_INFLIGHT_DEFAULT}. Set it to 0 to disable response auto-capture." >&2
    AUTOCAPTURE_MAX_INFLIGHT="${AUTOCAPTURE_MAX_INFLIGHT_DEFAULT}"
fi
AUTOCAPTURE_PIDS=""

autocapture_dispatch() {
    local path="$1" pid
    if [[ "${AUTOCAPTURE_MAX_INFLIGHT}" -eq 0 ]]; then
        return 0
    fi
    autocapture_response_best_effort "$path" &
    AUTOCAPTURE_PIDS="${AUTOCAPTURE_PIDS}$! "
    # shellcheck disable=SC2086  # deliberate word-splitting of the pid list
    set -- ${AUTOCAPTURE_PIDS}
    while [[ "$#" -ge "${AUTOCAPTURE_MAX_INFLIGHT}" ]]; do
        wait "$1" 2>/dev/null || true
        shift
    done
    AUTOCAPTURE_PIDS=""
    for pid in "$@"; do
        AUTOCAPTURE_PIDS="${AUTOCAPTURE_PIDS}${pid} "
    done
}

release_chrono_queue_lock() {
    local lockdir="$1" tmp="$2" lock_acquired="$3"
    rm -f "$tmp"
    if [[ "$lock_acquired" == 1 ]]; then
        rm -f "$lockdir/owner.pid"
        rmdir "$lockdir" 2>/dev/null || true
    fi
}

# scan_existing_responses() replays every response file on each watcher start
# so no delivery that landed while the watcher was down is stranded. But
# chrono-queue-backfill.sh separately archives settled entries out of
# chrono-queue.md into chrono-queue-handled.md, and by the time a task's
# response is replayed the registry entry that would make
# registry-reconciler.sh report "already-settled" may itself have been
# pruned -- so the replay falls into the reconciler_handled==0 fallback below
# and would silently undo the backfill's archival on every restart. Both
# writers use the identical " ${ts} | ${status} | ${task_ref} | ${summary}"
# line shape (registry_reconciler.py:244, append_chrono_queue below), so a
# literal `-F` match on " | ${task_ref} | " is exact -- task_ref is a bare
# namespace/task-id with no pipe characters. Reading chrono-queue-handled.md
# here is lock-free by design: its only writer (chrono-queue-backfill.sh)
# replaces it via tempfile+os.replace, an atomic rename, so a concurrent
# reader always sees a fully-old or fully-new file, never a torn one.
task_already_handled() {
    local task_ref="$1" handled="${STATE_DIR}/chrono-queue-handled.md"
    [[ -f "$handled" ]] || return 1
    grep -Fq " | ${task_ref} | " "$handled" 2>/dev/null
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
    local path="$1" fname ctx status status_prefix task_id NUDGE_MSG state task_file can_nudge dept reconciler_handled reconcile_output event_state event_key nudge_status
    # In consolidated mode the namespace differs per event, so derive it from
    # the path rather than a launch-time global. Every message, task lookup and
    # reconciler call below reads NAMESPACE/OUTBOX, and the loop is
    # single-threaded, so setting them per event is safe.
    if [[ "$ALL_NAMESPACES" == "1" ]]; then
        NAMESPACE="${path#"${VAULT_ROOT}/departments/"}"
        NAMESPACE="${NAMESPACE%%/*}"
        OUTBOX="${VAULT_ROOT}/departments/${NAMESPACE}/outbox"
    fi
    # Only react to actual response files — not partial writes or unrelated edits.
    case "$path" in
        */TASK-*-response.md|*/RESP-*.md) ;;
        *) return ;;
    esac
    case "$PROCESSED_PATHS" in
        *"|$path|"*) return ;;
    esac

    fname="$(basename "$path")"
    # Validate the whole frontmatter region before asking the reconciler to
    # consume it. The field helper scans every row, so a malformed optional key
    # cannot hide behind a valid status field. A held file is deliberately not
    # added to PROCESSED_PATHS: correcting it in place produces a new fswatch
    # event and retries the same response without discarding the deliverable.
    if ! frontmatter_field "$path" status >/dev/null; then
        echo "[$(date '+%H:%M:%S')] response envelope held in outbox: ${fname}; correct the named frontmatter error and republish"
        return
    fi
    ctx="$(response_context "$fname")"
    status="unknown"
    status_prefix="❓ UNKNOWN STATUS"
    task_id=""
    reconciler_handled=0
    if [[ "$fname" == TASK-*-response.md ]]; then
        task_id="${fname%-response.md}"
        # V2 envelopes are atomically published commit markers. Reconcile before
        # consulting the V1 mtime quiescence/display fallback below.
        if reconcile_output="$("${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$task_id" 2>&1)"; then
            if grep -Fq "reconciled ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "already-settled ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "review-required ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "review-held ${task_id} ->" <<<"$reconcile_output" \
                || grep -Fq "auto-closed ${task_id} from" <<<"$reconcile_output"; then
                reconciler_handled=1
                echo "[$(date '+%H:%M:%S')] shared reconciler handled registry entry: ${task_id}"
            fi
            if [[ "$reconciler_handled" == 0 ]] \
                && grep -Fq "v2-settlement-hold ${task_id} ->" <<<"$reconcile_output"; then
                echo "[$(date '+%H:%M:%S')] authoritative V2 settlement hold: ${task_id}"
                return
            fi
        else
            echo "[$(date '+%H:%M:%S')] warning: failed registry reconciliation for ${task_id}: ${reconcile_output}" >&2
            return
        fi
        if [[ "$reconciler_handled" == 1 ]] || legacy_response_ready_for_status "$path"; then
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
                                if legacy_response_ready_for_status "$path"; then
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
        autocapture_dispatch "$path"
        # A handled V2 settlement proves the descriptor and completed worker
        # transcript are stable. Record the count before any later cleanup can
        # age that transcript out; replay is idempotent and backfills missed
        # watcher windows.
        if [[ "$reconciler_handled" == 1 ]]; then
            record_skill_telemetry_best_effort "$task_id"
        fi
    fi
    can_nudge=1
    if ! "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
        can_nudge=0
    elif ! "$TMUX_BIN" list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "chrono"; then
        can_nudge=0
    fi
    echo "[$(date '+%H:%M:%S')] new: ${fname} from ${ctx} via ${NAMESPACE} namespace -> queueing chrono status"

    if [[ "$fname" == TASK-*-response.md ]]; then
        if [[ "$reconciler_handled" == 0 ]]; then
            if task_already_handled "${NAMESPACE}/${task_id}"; then
                echo "[$(date '+%H:%M:%S')] skipping fallback queue: ${NAMESPACE}/${task_id} already archived in chrono-queue-handled.md"
            else
                echo "[$(date '+%H:%M:%S')] shared reconciler found no settled registry entry; using notification fallback: ${task_id}"
                if append_chrono_queue "$task_id" "$status" "$path"; then
                    echo "[$(date '+%H:%M:%S')] fallback queued chrono status entry: ${status} ${NAMESPACE}/${task_id}"
                else
                    echo "[$(date '+%H:%M:%S')] warning: failed to queue chrono status entry: ${status} ${NAMESPACE}/${task_id}" >&2
                fi
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
    # legacy path for RESP-* replies or successful, unhandled V1 reconciliation.
    if [[ "$fname" == TASK-*-response.md && "$reconciler_handled" == 1 ]]; then
        return
    fi

    # Compose a best-effort pane nudge. tmux acceptance is not evidence that a
    # human or controller attended, read, or acted on the injected text.
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
        if send_chrono_notification_once "$event_key" "$NUDGE_MSG"; then
            true
        else
            nudge_status=$?
            if [[ "$nudge_status" -ne 2 ]]; then
                echo "[$(date '+%H:%M:%S')] chrono pane nudge failed; no receipt-backed tmux delivery: ${fname}" >&2
            fi
        fi
    else
        echo "[$(date '+%H:%M:%S')] chrono pane unavailable; no tmux recipient: ${fname}"
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
            \( -name 'TASK-*-response.md' -o -name 'RESP-*.md' \) \
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
