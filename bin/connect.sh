#!/bin/bash
# connect.sh — single-command entry into the squad. Drops you straight into
# the chrono pane ready to talk to the Coordinator. No tmux keystrokes needed.
#
# Behavior:
#   1. If the squad session doesn't exist → launch it
#   2. Force a full client refresh (cures stale buffer drift)
#   3. Select window 0 (chrono) and pane 0 (chrono main, not sidebar)
#   4. Attach
#
# Usage (local or SSH):
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/connect.sh
#
# Recommended shell alias:
#   alias vs='bash ~/Obsidian-Claude-Vibe-Squad/bin/connect.sh'
#
# Remote one-liner (run from any other machine via SSH to Mac mini):
#   ssh chronos-mini -t 'bash ~/Obsidian-Claude-Vibe-Squad/bin/connect.sh'

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="squad"

if ! command -v tmux >/dev/null 2>&1; then
    echo "ERROR: tmux not installed. Run: brew install tmux"
    exit 1
fi

# 1. Launch session if not present
if ! tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "Squad session not running — launching..."
    bash "${VAULT_ROOT}/bin/launch-squad.sh" </dev/null >/dev/null 2>&1
    sleep 2
fi

# 2. Refresh the tmux client (clears stale rendering on any client connected)
tmux refresh-client -t "${SESSION}" 2>/dev/null || true

# 3. Park focus on chrono pane (window 0, pane 0)
tmux select-window -t "${SESSION}:chrono" 2>/dev/null
tmux select-pane -t "${SESSION}:chrono.0" 2>/dev/null

# 4. Attach
exec tmux attach-session -t "${SESSION}"
