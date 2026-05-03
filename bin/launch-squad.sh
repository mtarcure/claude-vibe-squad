#!/bin/bash
# Launch the full Claude-Vibe-Squad tmux session with 6 windows.
# Each window runs one Lead's CLI in its dedicated working directory.
#
# Usage:
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh
#
# After launch:
#   tmux attach -t squad     # attach to the session
#   Ctrl-b + 0  → chrono (Coordinator, your conversation)
#   Ctrl-b + 1  → coding (Codex CLI)
#   Ctrl-b + 2  → security (Claude Code)
#   Ctrl-b + 3  → content (Gemini CLI)
#   Ctrl-b + 4  → sysmgmt (Claude Code)
#   Ctrl-b + 5  → research (Kimi CLI)
#   Ctrl-b + d  → detach (panes keep running)
#
# Re-run this script to re-attach if the session was killed; if a session
# already exists, it just reattaches without spawning duplicate panes.

set -uo pipefail

SESSION="squad"
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

# Verify tmux is installed
if ! command -v tmux >/dev/null 2>&1; then
    echo "ERROR: tmux not installed. Run: brew install tmux"
    exit 1
fi

# If session already exists, attach to it
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "Session '${SESSION}' already exists. Attaching..."
    tmux attach -t "${SESSION}"
    exit 0
fi

echo "Creating tmux session: ${SESSION}"
echo ""

# Ensure tmux server is up before any `set-option -g` calls. Without this,
# global options silently fail when the server isn't yet running (e.g. just
# after `kill-server`), leaving status bar + mouse mode at tmux defaults.
tmux start-server

# Tmux server config — keep 50k scrollback (default 2k truncates active sessions),
# enable mouse for trackpad scrolling, refresh status every 5s.
tmux set-option -g history-limit 50000
tmux set-option -g mouse on

# One-key recovery: Ctrl-b SPACE refreshes the client display AND parks you
# back on the chrono coordinator pane. Cures any stale-frame visual issue and
# restores focus to the place you actually want to type.
tmux bind-key Space run-shell 'tmux refresh-client \; tmux select-window -t squad:chrono \; tmux select-pane -t squad:chrono.0'
# Push tmux selections to the macOS clipboard automatically so you can ⌘V into
# Slack, Twitter, browser, etc. without bouncing through `tmux save-buffer`.
tmux set-option -g set-clipboard on
# When dragging to select: on release, copy to pbcopy and exit copy-mode.
# Also: ⌥ Option-drag in iTerm/Terminal bypasses tmux entirely for native selection.
tmux bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux set-option -g status-interval 5
tmux set-option -g status-left-length 40
tmux set-option -g status-right-length 110

# Status bar shows squad state at a glance from any pane: doctor verdict +
# inbox backlog + clock. Doctor verdict is read from today's summary JSON.
tmux set-option -g status-left "#[fg=cyan,bold]squad #[fg=white]│ "
tmux set-option -g status-right-length 140
tmux set-option -g status-right "#[fg=yellow]#(cat ${VAULT_ROOT}/_state/doctor-logs/\$(date +%%Y-%%m-%%d)-summary.json 2>/dev/null | jq -r 'if .issue_count>0 then \"🔔 \"+(.issue_count|tostring)+\" issues\" elif .warning_count>0 then \"⚠ \"+(.warning_count|tostring)+\" warn\" else \"✓ healthy\" end' 2>/dev/null || echo '? doctor') #[fg=white]│ #[fg=cyan]#(bash ${VAULT_ROOT}/bin/squad-health.sh) #[fg=white]│ #[fg=green]%H:%M"

# Per-pane log dir — pipe-pane writes pane stdout here for grep-able audit
TMUX_LOG_DIR="${VAULT_ROOT}/_state/tmux-logs"
mkdir -p "${TMUX_LOG_DIR}"

# Ensure ~/.local/bin is on PATH inside every tmux pane (claude + kimi live there)
PATH_PREFIX='export PATH="$HOME/.local/bin:$PATH"'

# Drop API-key env vars so each CLI falls back to its OAuth/subscription auth
# (Max plan, ChatGPT login, Gemini personal OAuth, Kimi login). Without this,
# headless calls bill against potentially-empty API keys instead of subscriptions.
# Interactive launches typically prefer OAuth anyway, but this is belt-and-suspenders.
AUTH_PREFIX='unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY'

# Window 0: chrono (Coordinator — Claude Code, auto-loads chrono/CLAUDE.md)
tmux new-session -d -s "${SESSION}" -n "chrono" -c "${VAULT_ROOT}/chrono"
tmux pipe-pane -t "${SESSION}:chrono" -o "cat >> ${TMUX_LOG_DIR}/chrono.log"
tmux send-keys -t "${SESSION}:chrono" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" "clear; echo '=== CHRONO COORDINATOR (Claude Code) ==='" C-m
tmux send-keys -t "${SESSION}:chrono" "claude --permission-mode acceptEdits --model opus --effort xhigh --add-dir ${VAULT_ROOT}" C-m

# Window 1: coding (Codex — auto-loads AGENTS.md)
tmux new-window -t "${SESSION}" -n "coding" -c "${VAULT_ROOT}/departments/coding"
tmux pipe-pane -t "${SESSION}:coding" -o "cat >> ${TMUX_LOG_DIR}/coding.log"
tmux send-keys -t "${SESSION}:coding" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:coding" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:coding" "clear; echo '=== CODING LEAD (Codex) ==='" C-m
tmux send-keys -t "${SESSION}:coding" "codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high" C-m

# Window 2: security (Claude Code — auto-loads CLAUDE.md)
tmux new-window -t "${SESSION}" -n "security" -c "${VAULT_ROOT}/departments/security"
tmux pipe-pane -t "${SESSION}:security" -o "cat >> ${TMUX_LOG_DIR}/security.log"
tmux send-keys -t "${SESSION}:security" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:security" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:security" "clear; echo '=== SECURITY LEAD (Claude) ==='" C-m
tmux send-keys -t "${SESSION}:security" "claude --permission-mode bypassPermissions --model opus --effort xhigh --add-dir ${VAULT_ROOT}" C-m

# Window 3: content (Gemini — auto-loads GEMINI.md)
tmux new-window -t "${SESSION}" -n "content" -c "${VAULT_ROOT}/departments/content"
tmux pipe-pane -t "${SESSION}:content" -o "cat >> ${TMUX_LOG_DIR}/content.log"
tmux send-keys -t "${SESSION}:content" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:content" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:content" "clear; echo '=== CONTENT LEAD (Gemini) ==='" C-m
tmux send-keys -t "${SESSION}:content" "gemini --yolo --model gemini-3.1-pro-preview --include-directories ${VAULT_ROOT}" C-m

# Window 4: sysmgmt (Claude Code — auto-loads CLAUDE.md)
tmux new-window -t "${SESSION}" -n "sysmgmt" -c "${VAULT_ROOT}/departments/sysmgmt"
tmux pipe-pane -t "${SESSION}:sysmgmt" -o "cat >> ${TMUX_LOG_DIR}/sysmgmt.log"
tmux send-keys -t "${SESSION}:sysmgmt" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:sysmgmt" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:sysmgmt" "clear; echo '=== SYSMGMT LEAD (Claude) ==='" C-m
tmux send-keys -t "${SESSION}:sysmgmt" "claude --permission-mode bypassPermissions --model sonnet --effort high --add-dir ${VAULT_ROOT}" C-m

# Window 5: research (Kimi — NO per-cwd auto-load convention)
tmux new-window -t "${SESSION}" -n "research" -c "${VAULT_ROOT}/departments/research"
tmux pipe-pane -t "${SESSION}:research" -o "cat >> ${TMUX_LOG_DIR}/research.log"
tmux send-keys -t "${SESSION}:research" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:research" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:research" "clear; echo '=== RESEARCH LEAD (Kimi) ==='" C-m
tmux send-keys -t "${SESSION}:research" "echo 'Kimi has no per-cwd auto-load. Once it starts, paste: Read LEAD.md and follow it as your role identity. Then check inbox/.'" C-m
tmux send-keys -t "${SESSION}:research" "kimi --yolo --thinking --add-dir ${VAULT_ROOT}" C-m

# Window 6: watchers — one inbox-watcher.sh process per Lead, tiled.
# These fire `tmux send-keys` to the corresponding Lead pane the moment a new
# TASK-*.md lands in its inbox/. Closes the gap where the dispatch-time nudge
# from send-task.sh races with a busy CLI and gets eaten.
if command -v fswatch >/dev/null 2>&1; then
    tmux new-window -t "${SESSION}" -n "watchers" -c "${VAULT_ROOT}"
    sleep 0.3
    tmux send-keys -t "${SESSION}:watchers" "bash ${VAULT_ROOT}/bin/inbox-watcher.sh coding" Enter
    sleep 0.3
    for next_lead in security content sysmgmt research; do
        tmux split-window -v -t "${SESSION}:watchers"
        sleep 0.3
        tmux send-keys -t "${SESSION}:watchers" "bash ${VAULT_ROOT}/bin/inbox-watcher.sh ${next_lead}" Enter
        sleep 0.3
    done
    tmux select-layout -t "${SESSION}:watchers" tiled
else
    echo "(fswatch not installed — skipping inbox-watchers window. Install with: brew install fswatch)"
fi

# Switch back to chrono window for first attachment
tmux select-window -t "${SESSION}:chrono"

echo "✓ Session '${SESSION}' created:"
echo "  0: chrono     (~/Obsidian-Claude-Vibe-Squad/chrono)"
echo "  1: coding     (departments/coding)"
echo "  2: security   (departments/security)"
echo "  3: content    (departments/content)"
echo "  4: sysmgmt    (departments/sysmgmt)"
echo "  5: research   (departments/research)"
echo "  6: watchers   (5 fswatch processes — one per Lead's inbox)"
echo ""
echo "Each window auto-started its CLI. Switch between them with Ctrl-b + <num>."
echo ""
echo "To attach now:           tmux attach -t squad"
echo "To detach (keep alive):  Ctrl-b + d"
echo "To kill the session:     tmux kill-session -t squad"
echo ""
read -p "Attach now? (y/n) " -n 1 -r
echo ""
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    tmux attach -t "${SESSION}"
fi
