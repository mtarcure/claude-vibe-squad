#!/bin/bash
# Launch the full Claude-Vibe-Squad tmux session with 6 visible windows.
# Each visible window uses a model-led name while keeping compatibility
# Lead folders/mailboxes stable under departments/.
#
# Usage:
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh
#   bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh --safe
#
# After launch:
#   tmux attach -t squad     # attach to the session
#   Ctrl-b + 0  → chrono (Coordinator, your conversation)
#   Ctrl-b + 1  → gpt-codex  (departments/coding)
#   Ctrl-b + 2  → claude     (security + sysmgmt compatibility namespaces)
#   Ctrl-b + 3  → gemini     (departments/content)
#   Ctrl-b + 4  → kimi       (departments/research)
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

if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]]; then
    CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode bypassPermissions --model opus --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --yolo --model gemini-3.1-pro-preview --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --yolo --thinking --agent-file ${VAULT_ROOT}/departments/research/.kimi/agents/main.yaml --add-dir ${VAULT_ROOT}"
else
    CODEX_CMD='codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode acceptEdits --model opus --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --model gemini-3.1-pro-preview --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --thinking --agent-file ${VAULT_ROOT}/departments/research/.kimi/agents/main.yaml --add-dir ${VAULT_ROOT}"
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

CODING_WIN="$(lead_window_name coding)"
SECURITY_WIN="$(lead_window_name security)"
CONTENT_WIN="$(lead_window_name content)"
RESEARCH_WIN="$(lead_window_name research)"

# Window 1: GPT/Codex model lane (compatibility folder: coding)
tmux new-window -t "${SESSION}" -n "${CODING_WIN}" -c "${VAULT_ROOT}/departments/coding"
tmux pipe-pane -t "${SESSION}:${CODING_WIN}" -o "cat >> ${TMUX_LOG_DIR}/coding.log"
tmux send-keys -t "${SESSION}:${CODING_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CODING_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CODING_WIN}" "clear; echo '=== GPT/CODEX MODEL LANE (specialist execution) ==='" C-m
tmux send-keys -t "${SESSION}:${CODING_WIN}" "${CODEX_CMD}" C-m

# Window 2: Claude model lane (compatibility folders: security + sysmgmt)
tmux new-window -t "${SESSION}" -n "${SECURITY_WIN}" -c "${VAULT_ROOT}"
tmux pipe-pane -t "${SESSION}:${SECURITY_WIN}" -o "cat >> ${TMUX_LOG_DIR}/claude.log"
tmux send-keys -t "${SESSION}:${SECURITY_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${SECURITY_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${SECURITY_WIN}" "clear; echo '=== CLAUDE MODEL LANE (security, privacy, sysmgmt, judgment review) ==='" C-m
tmux send-keys -t "${SESSION}:${SECURITY_WIN}" "${CLAUDE_CMD}" C-m

# Window 3: Gemini model lane (compatibility folder: content)
tmux new-window -t "${SESSION}" -n "${CONTENT_WIN}" -c "${VAULT_ROOT}/departments/content"
tmux pipe-pane -t "${SESSION}:${CONTENT_WIN}" -o "cat >> ${TMUX_LOG_DIR}/content.log"
tmux send-keys -t "${SESSION}:${CONTENT_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CONTENT_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CONTENT_WIN}" "clear; echo '=== GEMINI MODEL LANE (content + design + media) ==='" C-m
tmux send-keys -t "${SESSION}:${CONTENT_WIN}" "${CONTENT_CMD}" C-m

# Window 4: Kimi model lane (compatibility folder: research)
tmux new-window -t "${SESSION}" -n "${RESEARCH_WIN}" -c "${VAULT_ROOT}/departments/research"
tmux pipe-pane -t "${SESSION}:${RESEARCH_WIN}" -o "cat >> ${TMUX_LOG_DIR}/research.log"
tmux send-keys -t "${SESSION}:${RESEARCH_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${RESEARCH_WIN}" "${AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${RESEARCH_WIN}" "clear; echo '=== KIMI MODEL LANE (research + long context) ==='" C-m
tmux send-keys -t "${SESSION}:${RESEARCH_WIN}" "echo 'Kimi has no per-cwd auto-load. Once it starts, paste: Read LEAD.md and follow it as your role identity. Then check inbox/.'" C-m
tmux send-keys -t "${SESSION}:${RESEARCH_WIN}" "${RESEARCH_CMD}" C-m

# Window 6: watchers — inbox + outbox watchers per Lead.
# Inbox watchers nudge a Lead's pane when a new TASK-*.md arrives (closing the
# dispatch-time race where send-task.sh's nudge gets eaten by a busy CLI).
# Outbox watchers nudge the chrono pane when a Lead writes a RESP file
# (closing the pull-based polling gap so Chrono surfaces responses to the
# operator without waiting for the operator's next turn).
WATCHERS_WIN="$(lead_window_name watchers)"
tmux new-window -t "${SESSION}" -n "${WATCHERS_WIN}" -c "${VAULT_ROOT}"
tmux send-keys -t "${SESSION}:${WATCHERS_WIN}" "for lead in coding security content sysmgmt research; do bash ${VAULT_ROOT}/bin/inbox-watcher.sh \"\$lead\" & bash ${VAULT_ROOT}/bin/outbox-watcher.sh \"\$lead\" & done; wait" Enter

# Give the Lead CLIs a moment to initialize so the sidebar's first capture
# shows their welcome screens instead of empty shells.
sleep 1

# Sidebar — split chrono window into chrono main + 4 model-lane status tiles.
# Default-on per operator preference. Toggle off with bin/sidebar-off.sh.
bash "${VAULT_ROOT}/bin/sidebar.sh" >/dev/null 2>&1 || true

# Switch back to chrono window for first attachment
tmux select-window -t "${SESSION}:chrono"
tmux select-pane -t "${SESSION}:chrono.0"

echo "✓ Session '${SESSION}' created:"
echo "  0: chrono     (~/Obsidian-Claude-Vibe-Squad/chrono)"
echo "  1: ${CODING_WIN}  (GPT/Codex lane, coding namespace)"
echo "  2: ${SECURITY_WIN}     (Claude lane, security + sysmgmt namespaces)"
echo "  3: ${CONTENT_WIN}     (Gemini lane, content namespace)"
echo "  4: ${RESEARCH_WIN}       (Kimi lane, research namespace)"
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
