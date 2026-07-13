#!/bin/bash
# Sidebar — splits the chrono window so Chrono takes the left side and a
# right column shows clean status for each visible model lane.
#
# The sidebar is one dashboard pane, not four shell panes. It draws four
# model-lane cards itself, avoiding pane labels like "bash" and keeping the
# right column visually balanced.
#
# Toggle off with `bin/sidebar-off.sh`.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
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

WATCH="bash ${VAULT_ROOT}/bin/watch-lane.sh all"

# Main-left layout: Chrono stays large on the left; the four model-lane tiles
# stack at equal height on the right. This keeps the visual grid stable across
# terminal resizes.
tmux split-window -h -p 42 -t "${SESSION}:chrono"
sleep 0.2
tmux select-pane -t "${SESSION}:chrono.0" -T "CHRONO · coordinator" >/dev/null
tmux select-pane -t "${SESSION}:chrono.1" -T "MODEL LANES · live status" >/dev/null
tmux send-keys -t "${SESSION}:chrono.1" "${WATCH}" Enter

window_width=$(tmux display-message -p -t "${SESSION}:chrono" '#{window_width}' 2>/dev/null || echo 120)
main_width=$(( window_width * 58 / 100 ))
[[ "$main_width" -lt 72 ]] && main_width=72
tmux set-window-option -t "${SESSION}:chrono" main-pane-width "$main_width" >/dev/null
tmux select-layout -t "${SESSION}:chrono" main-vertical >/dev/null

tmux set-window-option -t "${SESSION}:chrono" pane-border-status top >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-border-format '#{?#{==:#{pane_index},0},#(VAULT_ROOT='"${VAULT_ROOT}"' bash '"${VAULT_ROOT}"'/bin/chrono-status-segment.sh),#[bg=colour141,fg=colour16,bold] MODEL LANES live #[bg=default,fg=colour238]}─' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-border-style 'fg=colour238' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" pane-active-border-style 'fg=colour51,bold' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" window-style 'fg=colour250,bg=colour235' >/dev/null
tmux set-window-option -t "${SESSION}:chrono" window-active-style 'fg=colour255,bg=colour233' >/dev/null

# Keep the sidebar from collapsing on window resize. tmux's layout pins the main
# (chrono) pane and squeezes the sidebar when a smaller client attaches or the
# terminal shrinks — we've seen it drop to ~10 cols. This hook re-asserts the
# sidebar width (~42%) on every window resize.
tmux set-hook -t "${SESSION}" window-resized "run-shell 'bash ${VAULT_ROOT}/bin/sidebar-resize.sh'" 2>/dev/null || true

# --- Clickable lane cards -------------------------------------------------------
# Single-click a card  → toggle an in-place live preview of that lane.
# Double-click a card  → jump to that lane's full window.
# Guarded by pane id so ONLY the sidebar reacts; every other pane keeps tmux's
# default mouse behavior. MouseUp1Pane has no tmux default (safe to bind, and it
# fires on a plain click but not during a drag-select). See bin/vs-sidebar-click.sh.
SIDEBAR_PANE="$(tmux display-message -p -t "${SESSION}:chrono.1" '#{pane_id}' 2>/dev/null)"
if [[ -n "${SIDEBAR_PANE}" ]]; then
    tmux bind-key -T root MouseUp1Pane if-shell -F "#{==:#{mouse_pane},${SIDEBAR_PANE}}" \
        "run-shell \"bash ${VAULT_ROOT}/bin/vs-sidebar-click.sh single #{mouse_y} #{pane_height}\"" 2>/dev/null || true
    tmux bind-key -T root DoubleClick1Pane if-shell -F "#{==:#{mouse_pane},${SIDEBAR_PANE}}" \
        "run-shell \"bash ${VAULT_ROOT}/bin/vs-sidebar-click.sh double #{mouse_y} #{pane_height}\"" \
        "select-pane -t = ; send-keys -M" 2>/dev/null || true
fi

# Focus stays on chrono main pane
tmux select-pane -t "${SESSION}:chrono.0"

echo "✓ Sidebar enabled with model-lane dashboard."
echo "  Type to Chrono in the main left pane."
echo "  Dashboard: gpt-codex, claude, gemini, kimi."
echo "  Refresh: 2s default. To toggle off: bash ${VAULT_ROOT}/bin/sidebar-off.sh"
