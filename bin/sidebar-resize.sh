#!/usr/bin/env bash
# Re-assert the Chrono sidebar width. The main-vertical layout lets the sidebar
# pane collapse when the window shrinks (tmux pins the main pane and squeezes the
# rest — we've seen it drop to ~10 cols), so this pins the sidebar to ~42% of the
# current window width. Wired to the window-resized hook by sidebar.sh so the
# dashboard survives client attach/detach and terminal resizes.
set -uo pipefail

SESSION="${SQUAD_SESSION:-squad}"
tmux has-session -t "$SESSION" 2>/dev/null || exit 0

# Only act when the chrono window actually has the sidebar split (2+ panes).
n=$(tmux list-panes -t "${SESSION}:chrono" 2>/dev/null | wc -l | tr -d ' ')
[[ "$n" -lt 2 ]] && exit 0

w=$(tmux display-message -p -t "${SESSION}:chrono" '#{window_width}' 2>/dev/null || echo 0)
[[ "$w" =~ ^[0-9]+$ ]] || exit 0

target=$(( w * 42 / 100 ))
[[ "$target" -lt 40 ]] && target=40
# Never starve the chrono pane: leave it at least 40 cols.
(( target > w - 40 )) && target=$(( w - 40 ))
(( target < 20 )) && target=20

tmux resize-pane -t "${SESSION}:chrono.1" -x "$target" 2>/dev/null || true
