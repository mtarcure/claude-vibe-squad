#!/bin/bash
# Sidebar — splits the chrono window so Chrono takes the left side and a
# right column shows clean status for each visible model lane.
#
# Each sidebar pane runs `bin/watch-lead.sh <namespace>` which periodically:
#   1. Prints a 2-line status header (mailbox counts + state + last-activity age)
#   2. Shows focus/last-result for that compatibility namespace.
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

WATCH="bash ${VAULT_ROOT}/bin/watch-lead.sh"

# split + send-keys with a brief settle — fresh shells sometimes drop keys
# typed too quickly after their split. 0.2s is plenty.
split_and_run() {
    local target="$1"; local pct="$2"
    tmux split-window -v -p "${pct}" -t "${target}"
    sleep 0.2
}

# 50/50 split: chrono main pane gets the same width as the sidebar.
# Operator preference 2026-05-02 — narrower tiles felt cluttered earlier.
tmux split-window -h -p 50 -t "${SESSION}:chrono"
sleep 0.2
tmux send-keys -t "${SESSION}:chrono.1" "${WATCH} coding" Enter

split_and_run "${SESSION}:chrono.1" 80 security
tmux send-keys -t "${SESSION}:chrono.2" "${WATCH} security" Enter

split_and_run "${SESSION}:chrono.2" 75 content
tmux send-keys -t "${SESSION}:chrono.3" "${WATCH} content" Enter

split_and_run "${SESSION}:chrono.3" 66 research
tmux send-keys -t "${SESSION}:chrono.4" "${WATCH} research" Enter

# Focus stays on chrono main pane
tmux select-pane -t "${SESSION}:chrono.0"

echo "✓ Sidebar enabled with model-lane status tiles."
echo "  Type to Chrono in the main left pane."
echo "  Tiles: gpt-codex, claude, gemini, kimi."
echo "  Refresh: 2s default. To toggle off: bash ${VAULT_ROOT}/bin/sidebar-off.sh"
