#!/bin/bash
# Dashboard — creates a separate window in the squad session showing all 5 Leads
# at once in a tiled grid, each pane live-tailing that Lead's pipe-pane log.
# Operator switches to it with `Ctrl-b m` (or `:select-window -t squad:monitor`).
#
# This is read-only — typing anywhere in the dashboard does nothing useful.
# To actually drive a Lead, switch to its dedicated window (Ctrl-b 1..5).
# Or just talk to Chrono — Chrono dispatches via send-task.sh, the Lead works,
# you watch progress on the dashboard. No pane-switching needed for normal work.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
LOG_DIR="${VAULT_ROOT}/_state/tmux-logs"
SESSION="squad"

if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "ERROR: squad session not running. Run bin/launch-squad.sh first."
    exit 1
fi

if ! [[ -d "${LOG_DIR}" ]] || ! ls "${LOG_DIR}"/*.log >/dev/null 2>&1; then
    echo "ERROR: tmux pipe-pane logs not found at ${LOG_DIR}"
    echo "Re-run launch-squad.sh to wire pipe-pane logging."
    exit 1
fi

# If dashboard window already exists, just switch to it
if tmux list-windows -t "${SESSION}" -F '#{window_name}' 2>/dev/null | grep -q '^monitor$'; then
    echo "Monitor window already exists; switching to it."
    tmux select-window -t "${SESSION}:monitor"
    exit 0
fi

# Create new window in the same session, named "monitor"
tmux new-window -t "${SESSION}" -n "monitor"

# First pane (auto-created with the new window): coding
tmux send-keys -t "${SESSION}:monitor" "clear; echo '═══ CODING (Codex) ═══'; echo; tail -f ${LOG_DIR}/coding.log" Enter

# Split for security (right side, vertical split)
tmux split-window -h -t "${SESSION}:monitor"
tmux send-keys -t "${SESSION}:monitor" "clear; echo '═══ SECURITY (Claude) ═══'; echo; tail -f ${LOG_DIR}/security.log" Enter

# Split coding pane vertically for content (top-bottom)
tmux split-window -v -t "${SESSION}:monitor.0"
tmux send-keys -t "${SESSION}:monitor" "clear; echo '═══ CONTENT (Gemini) ═══'; echo; tail -f ${LOG_DIR}/content.log" Enter

# Split security pane vertically for sysmgmt
tmux split-window -v -t "${SESSION}:monitor.2"
tmux send-keys -t "${SESSION}:monitor" "clear; echo '═══ SYSMGMT (Claude) ═══'; echo; tail -f ${LOG_DIR}/sysmgmt.log" Enter

# One more split for research
tmux split-window -v -t "${SESSION}:monitor.0"
tmux send-keys -t "${SESSION}:monitor" "clear; echo '═══ RESEARCH (Kimi) ═══'; echo; tail -f ${LOG_DIR}/research.log" Enter

# Even tiling for the 5 panes
tmux select-layout -t "${SESSION}:monitor" tiled

# Bind Ctrl-b m as a quick switcher to this window (server-wide binding)
tmux bind-key m select-window -t "${SESSION}:monitor"
tmux bind-key M select-window -t "${SESSION}:chrono"

tmux select-window -t "${SESSION}:monitor"
echo "✓ Dashboard window 'monitor' created."
echo "  Switch back to chrono: Ctrl-b 0  (or Ctrl-b M for capital-M shortcut)"
echo "  Switch to monitor:     Ctrl-b m"
