#!/bin/bash
# Launch the full Claude-Vibe-Squad tmux session with 6 visible windows.
# Each visible window is a model lead. Department folders are source
# namespaces and mailbox storage only.
#
# Usage:
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh --safe
#
# After launch:
#   tmux attach -t squad     # attach to the session
#   Ctrl-b + 0  → chrono (Coordinator, your conversation)
#   Ctrl-b + 1  → gpt-codex
#   Ctrl-b + 2  → claude
#   Ctrl-b + 3  → gemini
#   Ctrl-b + 4  → kimi
#   Ctrl-b + 5  → watchers/status
#   Ctrl-b + d  → detach (panes keep running)
#
# Re-run this script to re-attach if the session was killed; if a session
# already exists, it just reattaches without spawning duplicate panes.

set -uo pipefail

SESSION="${SQUAD_SESSION:-squad}"
VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"
for arg in "$@"; do
    case "$arg" in
        --safe) SQUAD_UNSAFE_AUTONOMY=0 ;;
        --autonomous|--unsafe) SQUAD_UNSAFE_AUTONOMY=1 ;;
        --help|-h)
            sed -n '2,18p' "$0"
            exit 0
            ;;
    esac
done

SQUAD_UNSAFE_AUTONOMY="${SQUAD_UNSAFE_AUTONOMY:-1}"
SQUAD_TRUST_CODEX_MCPS="${SQUAD_TRUST_CODEX_MCPS:-0}"

FIRST_RUN_SENTINEL="${VAULT_ROOT}/_state/.autonomous-launch-ack"
if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]]; then
    mkdir -p "${VAULT_ROOT}/_state"
    if [[ ! -f "${FIRST_RUN_SENTINEL}" ]]; then
        echo "WARNING: launching autonomous daily-driver profile."
        echo "This uses bypass/yolo-style permissions for model-lane panes. Use 'squad up --safe' for conservative permissions."
        echo "Run 'squad doctor' first if this is a fresh install."
        date -u +%FT%TZ > "${FIRST_RUN_SENTINEL}"
        echo ""
    fi
fi

# Verify tmux is installed
missing=()
for dep in tmux fswatch jq claude codex gemini kimi; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
done
if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "ERROR: missing required command(s): ${missing[*]}"
    echo "Fix: install/login the missing CLIs, and install core tools with: brew install jq tmux fswatch"
    exit 1
fi

if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]] && [[ -x "${VAULT_ROOT}/bin/doctor.sh" ]]; then
    if ! "${VAULT_ROOT}/bin/doctor.sh" >/dev/null 2>&1; then
        if [[ "${SQUAD_SKIP_DOCTOR:-0}" != "1" ]]; then
            echo "ERROR: doctor reported issues; autonomous launch blocked."
            echo "Run: squad doctor"
            echo "Override only after reviewing with: SQUAD_SKIP_DOCTOR=1 squad up"
            exit 1
        fi
        echo "WARNING: doctor reported issues; continuing because SQUAD_SKIP_DOCTOR=1."
    fi
fi

# Ensure tmux server is up before any `set-option -g` calls. Without this,
# global options silently fail when the server isn't yet running (e.g. just
# after `kill-server`), leaving status bar + mouse mode at tmux defaults.
tmux start-server

# Tmux server config — keep 50k scrollback (default 2k truncates active sessions),
# enable mouse for trackpad scrolling, refresh status every 5s.
# Applied BEFORE the has-session early-return so reattaches re-assert these
# globals — otherwise the server can drift back to defaults (mouse off,
# history-limit 2000) after a kill-server / external session recreate, and
# subsequent attaches via this script silently leave them at defaults.
tmux set-option -g history-limit 50000
tmux set-option -g mouse on

# If session already exists, attach to it (after re-asserting globals above)
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    echo "Session '${SESSION}' already exists. Attaching..."
    tmux attach -t "${SESSION}"
    exit 0
fi

echo "Creating tmux session: ${SESSION}"
echo ""

# One-key recovery: Ctrl-b SPACE refreshes the client display AND parks you
# back on the chrono coordinator pane. Cures any stale-frame visual issue and
# restores focus to the place you actually want to type.
tmux bind-key Space run-shell "tmux refresh-client \; tmux select-window -t ${SESSION}:chrono \; tmux select-pane -t ${SESSION}:chrono.0"
# Push tmux selections to the macOS clipboard automatically so you can ⌘V into
# Slack, Twitter, browser, etc. without bouncing through `tmux save-buffer`.
tmux set-option -g set-clipboard on
# When dragging to select: on release, copy to pbcopy and exit copy-mode.
# Also: ⌥ Option-drag in iTerm/Terminal bypasses tmux entirely for native selection.
tmux bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux bind-key -T copy-mode Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux bind-key -T copy-mode-vi y send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
tmux set-option -g status-interval 5
tmux set-option -g status-left-length 40
tmux set-option -g status-right-length 110

# Status bar shows squad state at a glance from any pane: doctor verdict +
# inbox backlog + clock. Doctor verdict is read from today's summary JSON.
tmux set-option -g status-left "#[fg=cyan,bold]squad #[fg=white]│ "
tmux set-option -g status-right-length 140
tmux set-option -g status-style 'bg=colour235,fg=colour252'
tmux set-option -g window-status-current-style 'bg=colour39,fg=colour16,bold'
tmux set-option -g window-status-style 'bg=colour235,fg=colour250'
tmux set-option -g window-status-format ' #[fg=colour245]#I #[fg=colour250]#W '
tmux set-option -g window-status-current-format ' #[fg=colour16,bold]#I #[fg=colour16,bold]#W '
tmux set-option -g pane-border-style 'fg=colour238'
tmux set-option -g pane-active-border-style 'fg=colour51,bold'
tmux set-option -g pane-border-status top
tmux set-option -g pane-border-format '#[bg=colour51,fg=colour16,bold] #{pane_title} #[bg=default,fg=colour238]─'
tmux set-option -g status-left "#[bg=colour39,fg=colour16,bold] squad #[bg=colour235,fg=colour250] "
tmux set-option -g status-right "#[fg=colour214]#(cat ${VAULT_ROOT}/_state/doctor-logs/\$(date +%%Y-%%m-%%d)-summary.json 2>/dev/null | jq -r 'if .issue_count>0 then \"issues:\"+(.issue_count|tostring) elif .warning_count>0 then \"warn:\"+(.warning_count|tostring) else \"healthy\" end' 2>/dev/null || echo 'doctor:?') #[fg=colour245]| #[fg=colour45]#(bash ${VAULT_ROOT}/bin/squad-health.sh) #[fg=colour245]| #[fg=colour118]%H:%M"

# Per-pane log dir — pipe-pane writes pane stdout here for grep-able audit
TMUX_LOG_DIR="${VAULT_ROOT}/_state/tmux-logs"
mkdir -p "${TMUX_LOG_DIR}"
for ns in coding security content sysmgmt research; do
    mkdir -p "${VAULT_ROOT}/departments/${ns}/inbox" \
             "${VAULT_ROOT}/departments/${ns}/active" \
             "${VAULT_ROOT}/departments/${ns}/outbox" \
             "${VAULT_ROOT}/departments/${ns}/archive"
done

# Ensure ~/.local/bin is on PATH inside every tmux pane (claude + kimi live there)
PATH_PREFIX='export PATH="$HOME/.local/bin:$PATH"'

# Drop API-key env vars so each CLI falls back to its OAuth/subscription auth
# (Max plan, ChatGPT login, Gemini personal OAuth, Kimi login). Without this,
# headless calls bill against potentially-empty API keys instead of subscriptions.
# Interactive launches typically prefer OAuth anyway, but this is belt-and-suspenders.
AUTH_PREFIX='unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY'

if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]]; then
    CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode bypassPermissions --model opus --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --yolo --model gemini-3.1-pro-preview --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --yolo --thinking --agent-file ${VAULT_ROOT}/model-lanes/kimi/main.yaml --add-dir ${VAULT_ROOT}"
else
    CODEX_CMD='codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode acceptEdits --model opus --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --model gemini-3.1-pro-preview --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --thinking --agent-file ${VAULT_ROOT}/model-lanes/kimi/main.yaml --add-dir ${VAULT_ROOT}"
fi

# Window 0: chrono (Coordinator — Claude Code, auto-loads chrono/CLAUDE.md)
tmux new-session -d -s "${SESSION}" -n "chrono" -c "${VAULT_ROOT}/chrono"
tmux pipe-pane -t "${SESSION}:chrono" -o "cat >> ${TMUX_LOG_DIR}/chrono.log"
tmux send-keys -t "${SESSION}:chrono" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" "clear; echo '=== CHRONO COORDINATOR (Claude Code) ==='" C-m
tmux send-keys -t "${SESSION}:chrono" "claude --permission-mode acceptEdits --model opus --effort xhigh --add-dir ${VAULT_ROOT}" C-m

# Optional local convenience: pre-trust chrono MCP servers in Codex config so
# the coding pane does not prompt for MCP approval mid-task. This mutates
# ~/.codex/config.toml, so public/default launches never do it implicitly.
if [[ "${SQUAD_TRUST_CODEX_MCPS}" == "1" ]]; then
    if python3 "${VAULT_ROOT}/bin/patch-codex-mcp-trust.py" 2>&1; then
        true  # patch logged its own status
    else
        echo "WARNING: codex-mcp-trust patch failed — coding pane may prompt for MCP approvals"
        echo "Fix manually: python3 ${VAULT_ROOT}/bin/patch-codex-mcp-trust.py"
    fi
fi

GPT_CODEX_WIN="$(runtime_window_name gpt-codex)"
CLAUDE_WIN="$(runtime_window_name claude)"
GEMINI_WIN="$(runtime_window_name gemini)"
KIMI_WIN="$(runtime_window_name kimi)"

# Window 1: GPT/Codex model lead
tmux new-window -t "${SESSION}" -n "${GPT_CODEX_WIN}" -c "${VAULT_ROOT}/model-lanes/gpt-codex"
tmux pipe-pane -t "${SESSION}:${GPT_CODEX_WIN}" -o "cat >> ${TMUX_LOG_DIR}/gpt-codex.log"
tmux send-keys -t "${SESSION}:${GPT_CODEX_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${GPT_CODEX_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${GPT_CODEX_WIN}" "clear; echo '=== GPT/CODEX MODEL LEAD (implementation, tests, PoC mechanics) ==='" C-m
tmux send-keys -t "${SESSION}:${GPT_CODEX_WIN}" "${CODEX_CMD}" C-m

# Window 2: Claude model lead
tmux new-window -t "${SESSION}" -n "${CLAUDE_WIN}" -c "${VAULT_ROOT}/model-lanes/claude"
tmux pipe-pane -t "${SESSION}:${CLAUDE_WIN}" -o "cat >> ${TMUX_LOG_DIR}/claude.log"
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "clear; echo '=== CLAUDE MODEL LEAD (judgment, safety review, careful reasoning) ==='" C-m
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "${CLAUDE_CMD}" C-m

# Window 3: Gemini model lead
tmux new-window -t "${SESSION}" -n "${GEMINI_WIN}" -c "${VAULT_ROOT}/model-lanes/gemini"
tmux pipe-pane -t "${SESSION}:${GEMINI_WIN}" -o "cat >> ${TMUX_LOG_DIR}/gemini.log"
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "clear; echo '=== GEMINI MODEL LEAD (multimodal, media, grounded content) ==='" C-m
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "${CONTENT_CMD}" C-m

# Window 4: Kimi model lead
tmux new-window -t "${SESSION}" -n "${KIMI_WIN}" -c "${VAULT_ROOT}/model-lanes/kimi"
tmux pipe-pane -t "${SESSION}:${KIMI_WIN}" -o "cat >> ${TMUX_LOG_DIR}/kimi.log"
tmux send-keys -t "${SESSION}:${KIMI_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${KIMI_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${KIMI_WIN}" "clear; echo '=== KIMI MODEL LEAD (long context, source-heavy analysis) ==='" C-m
tmux send-keys -t "${SESSION}:${KIMI_WIN}" "echo 'Kimi model lead prompt: model-lanes/kimi/KIMI.md. Process TASK packets where to_model: kimi.'" C-m
tmux send-keys -t "${SESSION}:${KIMI_WIN}" "${RESEARCH_CMD}" C-m

# Window 5: watchers — inbox + outbox watchers per source namespace.
# Inbox watchers nudge the assigned model pane when a new TASK-*.md arrives (closing the
# dispatch-time race where send-task.sh's nudge gets eaten by a busy CLI).
# Outbox watchers nudge the chrono pane when a response lands
# (closing the pull-based polling gap so Chrono surfaces responses to the
# operator without waiting for the operator's next turn).
WATCHERS_WIN="$(lead_window_name watchers)"
tmux new-window -t "${SESSION}" -n "${WATCHERS_WIN}" -c "${VAULT_ROOT}"
tmux pipe-pane -t "${SESSION}:${WATCHERS_WIN}" -o "cat >> ${TMUX_LOG_DIR}/watchers-status.log"
tmux send-keys -t "${SESSION}:${WATCHERS_WIN}" "export SQUAD_SESSION=${SESSION}; for lead in coding security content sysmgmt research; do bash ${VAULT_ROOT}/bin/inbox-watcher.sh \"\$lead\" & bash ${VAULT_ROOT}/bin/outbox-watcher.sh \"\$lead\" & done; wait" Enter

# Give the model CLIs a moment to initialize so the sidebar's first capture
# shows their welcome screens instead of empty shells.
sleep 1

# Sidebar — split chrono window into chrono main + 4 model-lane status tiles.
# Default-on per operator preference. Toggle off with bin/sidebar-off.sh.
bash "${VAULT_ROOT}/bin/sidebar.sh" >/dev/null 2>&1 || true

# Switch back to chrono window for first attachment
tmux select-window -t "${SESSION}:chrono"
tmux select-pane -t "${SESSION}:chrono.0"

echo "✓ Session '${SESSION}' created:"
echo "  0: chrono     (Coordinator)"
echo "  1: ${GPT_CODEX_WIN}  (GPT/Codex model lead)"
echo "  2: ${CLAUDE_WIN}     (Claude model lead)"
echo "  3: ${GEMINI_WIN}     (Gemini model lead)"
echo "  4: ${KIMI_WIN}       (Kimi model lead)"
echo "  5: ${WATCHERS_WIN} (10 fswatch processes — inbox + outbox per namespace)"
echo ""
echo "Each window auto-started its CLI. Switch with Ctrl-b + <num>."
echo "Chrono window has a 4-lane sidebar. Toggle off: bin/sidebar-off.sh"
echo ""
echo "To attach now:           tmux attach -t ${SESSION}"
echo "To detach (keep alive):  Ctrl-b + d"
echo "To kill the session:     tmux kill-session -t ${SESSION}"
echo "Unsafe autonomous mode:  SQUAD_UNSAFE_AUTONOMY=1 bash bin/launch-squad.sh"
echo "Pre-trust Codex MCPs:    SQUAD_TRUST_CODEX_MCPS=1 bash bin/launch-squad.sh"
echo ""
read -p "Attach now? (y/n) " -n 1 -r
echo ""
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    tmux attach -t "${SESSION}"
fi
