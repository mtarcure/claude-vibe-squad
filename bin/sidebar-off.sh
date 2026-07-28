#!/bin/bash
# Remove the sidebar panes from the chrono window, restoring it to a single
# full-window pane (where Chrono runs).

set -uo pipefail

SESSION="squad"

if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "ERROR: squad session not running."
    exit 1
fi

n=$(tmux list-panes -t "${SESSION}:chrono" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${n}" -le 1 ]]; then
    echo "Sidebar is already off (${n} pane in chrono window)."
    exit 0
fi

# Kill all panes except pane 0 (chrono itself)
for pane_idx in $(tmux list-panes -t "${SESSION}:chrono" -F '#{pane_index}' | grep -v '^0$' | sort -rn); do
    tmux kill-pane -t "${SESSION}:chrono.${pane_idx}"
done

echo "✓ Sidebar removed; chrono is full-window again."
