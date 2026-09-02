#!/bin/bash
# Sidebar — splits the chrono window so Chrono takes the left side and a
# right column shows clean status for live specialist work.
#
# The sidebar is one dashboard pane, not a set of standing lane shells. It
# draws live specialist-task cards and keeps the right column visually balanced.
#
# Toggle off with `bin/sidebar-off.sh`.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
SESSION="squad"

if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "ERROR: squad session not running. Run bin/launch-squad.sh first."
    exit 1
fi

# Already on?
n=$(tmux list-panes -t "${SESSION}:chrono" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${n}" -gt 1 ]]; then
    echo "Chrono window already has ${n} panes — sidebar is on."
    echo "To remove: bash ${VAULT_ROOT}/bin/sidebar-off.sh"
    exit 0
fi

WATCH="VS_DASH_CAPACITY=${VS_DASH_CAPACITY:-10} bash ${VAULT_ROOT}/bin/vs-dashboard-loop.sh"

# Main-left layout: Chrono stays large on the left and the specialist swarm
# dashboard stays on the right. This keeps the visual grid stable across
# terminal resizes.
tmux split-window -h -p 42 -t "${SESSION}:chrono"
sleep 0.2
tmux select-pane -t "${SESSION}:chrono.0" -T "CHRONO · coordinator" >/dev/null
tmux select-pane -t "${SESSION}:chrono.1" -T "SPECIALIST SWARM · live" >/dev/null
tmux send-keys -t "${SESSION}:chrono.1" "${WATCH}" Enter

window_width=$(tmux display-message -p -t "${SESSION}:chrono" '#{window_width}' 2>/dev/null || echo 120)
main_width=$(( window_width * 52 / 100 ))  # dashboard gets ~48% so the swarm scales up
[[ "$main_width" -lt 72 ]] && main_width=72
tmux set-window-option -t "${SESSION}:chrono" main-pane-width "$main_width" >/dev/null
tmux select-layout -t "${SESSION}:chrono" main-vertical >/dev/null

tmux set-window-option -t "${SESSION}:chrono" pane-border-status top >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-border-format '#{?#{==:#{pane_index},0},#(VAULT_ROOT='"${VAULT_ROOT}"' bash '"${VAULT_ROOT}"'/bin/chrono-status-segment.sh),#[bg=colour141,fg=colour16,bold] SPECIALIST SWARM live #[bg=default,fg=colour238]}─' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-border-style 'fg=colour238' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-active-border-style 'fg=colour51,bold' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" window-style 'fg=colour250,bg=colour235' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" window-active-style 'fg=colour255,bg=colour233' >/dev/null

# Keep the sidebar from collapsing on window resize. tmux's layout pins the main
# (chrono) pane and squeezes the sidebar when a smaller client attaches or the
# terminal shrinks — we've seen it drop to ~10 cols. This hook re-asserts the
# sidebar width (~42%) on every window resize.
tmux set-hook -t "${SESSION}" window-resized "run-shell 'bash ${VAULT_ROOT}/bin/sidebar-resize.sh'" 2>/dev/null || true

# --- Clickable specialist cards -------------------------------------------------
# Double-click a live specialist card → open that spawn's streaming CLI log in a new
# window (board spawns are detached, so "open the CLI" == tail the live log).
# Guarded by pane id so ONLY the swarm pane reacts; every other pane keeps tmux's
# default double-click (word select) via the if-shell else-branch. The handler maps
# the click to a card through the per-frame hit-map. See bin/vs-open-spawn.sh.
# Bindings live in one place so a live session can repair them without a restart.
bash "${VAULT_ROOT}/bin/vs-ensure-bindings.sh" "${SESSION}" >/dev/null 2>&1 || true

# Focus stays on chrono main pane
tmux select-pane -t "${SESSION}:chrono.0"

echo "✓ Sidebar enabled with specialist-swarm dashboard."
echo "  Type to Chrono in the main left pane."
echo "  Dashboard: live specialist swarm."
echo "  Refresh: 2s default. To toggle off: bash ${VAULT_ROOT}/bin/sidebar-off.sh"
