#!/usr/bin/env bash
# vs-lane-status.sh — background poller that writes tmux-consumable status
# files. Runs once as a daemon (spawned by launch-squad.sh); tmux reads the
# files via #(cat /tmp/vs-lane-*.status) in pane-border-format.
#
# Why a poller instead of per-render #() calls:
#   Fable 5 flagged this: tmux runs #() once per pane per status-interval.
#   With 5 panes × 1s refresh that's 5 req/s against the daemon. This poller
#   fetches ONCE per second and writes cached files, so tmux does zero
#   network work on each render.
set -u

: "${VIBESQUAD_DAEMON_TOKEN:?VIBESQUAD_DAEMON_TOKEN must be exported}"

FRAMES='⣷⣯⣟⡿⢿⣻⣽⣾'
FRAME_COUNT=${#FRAMES}
STATE_DIR="${VIBESQUAD_STATE_DIR:-/tmp}"

# Colors — match Claude Code palette (colour74 cyan accent, colour252 text,
# colour240 dim, colour214 amber, colour167 red).
esc() { printf '\033[38;5;%sm' "$1"; }
CYAN=$(esc 74)
TEXT=$(esc 252)
DIM=$(esc 240)
AMBER=$(esc 214)
RED=$(esc 167)
RESET=$'\033[0m'

i=0
while :; do
    i=$(( (i + 1) % FRAME_COUNT ))
    spin="${FRAMES:$i:1}"

    json=$(curl -sfm 3 \
        -H "Authorization: Bearer $VIBESQUAD_DAEMON_TOKEN" \
        http://127.0.0.1:9876/tasks 2>/dev/null) || {
        printf '%s● daemon offline%s' "$RED" "$RESET" > /tmp/vs-daemon.status
        sleep 2
        continue
    }
    printf '%s● daemon%s' "$CYAN" "$RESET" > /tmp/vs-daemon.status

    now=$(date +%s)

    for lane in chrono gpt-codex claude gemini kimi; do
        # Extract this lane's most-recent state via python (portable JSON parse).
        # Token counts are intentionally NOT surfaced — the model CLIs show their
        # own usage; a squad-level counter would just be redundant chrome.
        read state started <<<"$(printf '%s' "$json" | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
lane_tasks = [t for t in d.get('tasks', []) if t.get('lane') == '$lane']
if not lane_tasks:
    print('idle 0')
else:
    # Prefer running > queued > done
    order = {'running': 0, 'queued': 1, 'done': 2}
    lane_tasks.sort(key=lambda t: order.get(t.get('state', 'idle'), 3))
    t = lane_tasks[0]
    print(t.get('state', 'idle'), t.get('started_at_epoch', 0))
" 2>/dev/null || echo "idle 0")"

        case "$state" in
            running)
                if [ "$started" -gt 0 ]; then
                    elapsed=$(( now - started ))
                    (( elapsed < 0 )) && elapsed=0
                    mmss=$(printf '%02d:%02d' $((elapsed / 60)) $((elapsed % 60)))
                else
                    mmss='--:--'
                fi
                printf '%s%s %s%s%s' \
                    "$CYAN" "$spin" "$TEXT" "$mmss" "$RESET" \
                    > "/tmp/vs-lane-${lane}.status"
                ;;
            queued)
                printf '%s◐ queued%s' "$AMBER" "$RESET" \
                    > "/tmp/vs-lane-${lane}.status"
                ;;
            done)
                printf '%s● done%s' "$CYAN" "$RESET" \
                    > "/tmp/vs-lane-${lane}.status"
                ;;
            *)
                printf '%s· idle%s' "$DIM" "$RESET" \
                    > "/tmp/vs-lane-${lane}.status"
                ;;
        esac
    done

    sleep 1
done
