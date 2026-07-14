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
for dep in tmux fswatch jq curl claude codex gemini kimi; do
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

# --- Live status poller ----------------------------------------------------
# Background job: polls the daemon once/sec and writes /tmp/vs-*.status files
# that the tmux status bar + pane borders read (see vs-lane-status.sh). Started
# here — before the has-session reattach guard — so a reattach also re-ensures
# it's running. pgrep-guarded so we never spawn duplicate pollers.
if ! pgrep -f 'vs-lane-status.sh' >/dev/null 2>&1; then
    # Surgically extract ONLY the daemon token in a subshell. NEVER source the
    # full secrets file into this launcher's env — every tmux pane inherits the
    # launcher env, and API keys have leaked into terminal titles via exactly
    # that path before. The inline command-prefix assignment scopes the token
    # to the poller process alone; it never enters the launcher (or pane) env.
    VIBESQUAD_DAEMON_TOKEN="$(zsh -c 'source "$HOME/.config/shell/secrets.zsh" 2>/dev/null; printf %s "${VIBESQUAD_DAEMON_TOKEN:-}"')" \
        nohup bash "${VAULT_ROOT}/bin/vs-lane-status.sh" >/dev/null 2>&1 &
    disown 2>/dev/null || true
fi

# apply_squad_globals — all server-global tmux options + key bindings.
#
# ORDER MATTERS: global `set-option -g` requires a running server, and
# `tmux start-server` does NOT create a queryable server on a cold start — the
# server only comes into existence once the first session is created. So this
# MUST run AFTER new-session (fresh launch) or when a session already exists
# (reattach). Calling it before a session exists silently drops every option and
# the session comes up with default green tmux chrome. It is idempotent, so
# reattaches re-assert it (curing drift back to defaults after a kill-server /
# external recreate).
apply_squad_globals() {
    # 50k scrollback (default 2k truncates active sessions) + mouse for trackpad.
    tmux set-option -g history-limit 50000
    tmux set-option -g mouse on

    # One-key recovery: Ctrl-b SPACE refreshes the client display AND parks you
    # back on the chrono coordinator pane. Cures any stale-frame visual issue.
    tmux bind-key Space run-shell "tmux refresh-client \; tmux select-window -t ${SESSION}:chrono \; tmux select-pane -t ${SESSION}:chrono.0"
    # Push tmux selections to the macOS clipboard automatically (⌘V elsewhere).
    tmux set-option -g set-clipboard on
    tmux bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true
    tmux bind-key -T copy-mode-vi y send-keys -X copy-pipe-and-cancel "pbcopy" 2>/dev/null || true

    # --- Claude-Code-grade status bar (locked palette, poller-fed) ---------
    # Live data comes from /tmp/vs-*.status (poller), so tmux does ZERO network
    # work per render even at status-interval 1. Palette: colour74 cyan accent,
    # colour252 near-white, colour240 dim, colour214 amber, colour234/233 bg.
    tmux set-option -g status on
    tmux set-option -g status-position bottom
    tmux set-option -g status 2                       # two rows: live data + hints
    tmux set-option -g status-interval 1
    tmux set-option -g status-style      'fg=colour252,bg=colour234'
    tmux set-option -g status-left-length 60
    tmux set-option -g status-right-length 180
    tmux set-option -g status-left "#[fg=colour74,bold] squad #[fg=colour240]· #[fg=colour252]#S #[fg=colour240]· #(cat /tmp/vs-daemon.status 2>/dev/null) "
    tmux set-option -g status-right "#(cat /tmp/vs-swarm.status 2>/dev/null) #[fg=colour240]· #[fg=colour214]#(cat ${VAULT_ROOT}/_state/doctor-logs/\$(date +%%Y-%%m-%%d)-summary.json 2>/dev/null | jq -r 'if .issue_count>0 then \"issues:\"+(.issue_count|tostring) elif .warning_count>0 then \"warn:\"+(.warning_count|tostring) else \"healthy\" end' 2>/dev/null || echo 'doctor:?') #[fg=colour240]· #[fg=colour252]%H:%M "
    tmux set-option -g "status-format[1]" "#[bg=colour233,fg=colour240] Tab / C-b <n>: lanes · C-b 0: chrono · C-b z: zoom · C-b Space: reset · C-b [: scroll · C-b d: detach "

    # Window tabs — accent the current lane, dim the rest.
    tmux set-option -g window-status-style         'bg=colour234,fg=colour240'
    tmux set-option -g window-status-current-style 'bg=colour234,fg=colour252,bold'
    tmux set-option -g window-status-format         ' #[fg=colour240]#I #[fg=colour250]#W '
    tmux set-option -g window-status-current-format ' #[fg=colour74,bold]#I #W '

    # Pane borders — hairline accent on the active pane; the lane's live status
    # rides the border top. Lane windows are named gpt-codex/claude/gemini/kimi,
    # matching the poller's /tmp/vs-lane-<name>.status files, so #{window_name}
    # keys them directly. (The chrono window overrides this in sidebar.sh.)
    tmux set-option -g pane-border-style        'fg=colour238'
    tmux set-option -g pane-active-border-style 'fg=colour74'
    tmux set-option -g pane-border-status top
    tmux set-option -g pane-border-format "#[fg=colour240] #{?pane_active,#[fg=colour74]▎,#[fg=colour238]│} #[fg=colour252,bold]#{window_name}#[fg=colour240] #(cat /tmp/vs-lane-#{window_name}.status 2>/dev/null) "
}

# If the session already exists, re-assert globals (the server is up) and attach.
if tmux has-session -t "${SESSION}" 2>/dev/null; then
    apply_squad_globals
    echo "Session '${SESSION}' already exists. Attaching..."
    tmux attach -t "${SESSION}"
    exit 0
fi

echo "Creating tmux session: ${SESSION}"
echo ""

# Create the coordinator session FIRST so the tmux server exists, THEN style.
# (The chrono pane is populated further below, once PATH/AUTH prefixes are set.)
tmux new-session -d -s "${SESSION}" -n "chrono" -c "${VAULT_ROOT}/chrono"
apply_squad_globals

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
PATH_PREFIX='export PATH="$HOME/.local/bin:$HOME/go/bin:$PATH"'

# Drop API-key env vars so each CLI falls back to its OAuth/subscription auth
# (Max plan, ChatGPT login, Gemini personal OAuth, Kimi login). Without this,
# headless calls bill against potentially-empty API keys instead of subscriptions.
# Interactive launches typically prefer OAuth anyway, but this is belt-and-suspenders.
# Private knowledge-vault root — chrono-vault MCP fail-closes without this (P0-8 fix).
AUTH_PREFIX='export CHRONO_VAULT_ROOT="$HOME/Obsidian-Chrono"; unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY'

# Claude panes host Claude plugins, including chrono-content-engineer. Keep the
# OpenAI key only there so Sora can authenticate without exposing media creds to
# non-media model lanes.
MEDIA_AUTH_PREFIX='export CHRONO_VAULT_ROOT="$HOME/Obsidian-Chrono"; unset ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY'

# Gemini lane is the exception: Google deprecated the individual Code Assist
# OAuth client (2026-07), so the gemini CLI can no longer log in via
# subscription and MUST authenticate with GEMINI_API_KEY (settings.json auth
# selectedType: gemini-api-key). Source secrets to guarantee the key is present,
# but still unset GOOGLE_API_KEY — the secrets.zsh note warns gemini-cli grabbing
# the GCP project key routes Gemini calls through the wrong project (403).
GEMINI_AUTH_PREFIX='source ~/.config/shell/secrets.zsh 2>/dev/null; export CHRONO_VAULT_ROOT="$HOME/Obsidian-Chrono"; unset ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY'

acknowledge_gemini_agents() {
    python3 - "$VAULT_ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
project_root = root / "model-lanes" / "gemini"
agents_dir = project_root / ".gemini" / "agents"
if not agents_dir.exists():
    raise SystemExit(0)

ack_path = Path.home() / ".gemini" / "acknowledgments" / "agents.json"
try:
    data = json.loads(ack_path.read_text()) if ack_path.exists() else {}
except json.JSONDecodeError:
    data = {}

project = str(project_root)
data.setdefault(project, {})
for path in sorted(agents_dir.glob("*.md")):
    if path.name.startswith("_"):
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data[project][path.stem] = digest

ack_path.parent.mkdir(parents=True, exist_ok=True)
tmp = ack_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.replace(ack_path)
PY
}

acknowledge_gemini_agents

if [[ "${SQUAD_UNSAFE_AUTONOMY}" == "1" ]]; then
    CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode bypassPermissions --model claude-fable-5 --fallback-model claude-opus-4-8,claude-sonnet-5 --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --yolo --skip-trust --model gemini-3.5-flash --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --yolo --thinking --model kimi-k2.7-code --agent-file ${VAULT_ROOT}/model-lanes/kimi/main.yaml --add-dir ${VAULT_ROOT}"
else
    CODEX_CMD='codex --sandbox workspace-write --ask-for-approval never -c model_reasoning_effort=high'
    CLAUDE_CMD="claude --permission-mode manual --model claude-fable-5 --fallback-model claude-opus-4-8,claude-sonnet-5 --effort xhigh --add-dir ${VAULT_ROOT}"
    CONTENT_CMD="gemini --skip-trust --model gemini-3.5-flash --include-directories ${VAULT_ROOT}"
    RESEARCH_CMD="kimi --thinking --model kimi-k2.7-code --agent-file ${VAULT_ROOT}/model-lanes/kimi/main.yaml --add-dir ${VAULT_ROOT}"
fi

# Window 0: chrono (Coordinator — Claude Code, auto-loads chrono/CLAUDE.md).
# The session + chrono window were already created above (before styling); here
# we just wire up logging and launch the coordinator.
tmux pipe-pane -t "${SESSION}:chrono" -o "cat >> ${TMUX_LOG_DIR}/chrono.log"
tmux send-keys -t "${SESSION}:chrono" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:chrono" "${MEDIA_AUTH_PREFIX}" C-m
# vs-welcome.sh clears, prints the coordinator greeting, then execs claude with
# acceptEdits + opus + effort xhigh + --add-dir (keeps OPENAI_API_KEY for media).
tmux send-keys -t "${SESSION}:chrono" "bash ${VAULT_ROOT}/bin/vs-welcome.sh" C-m

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
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "${MEDIA_AUTH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "clear; echo '=== CLAUDE MODEL LEAD (judgment, safety review, careful reasoning) ==='" C-m
tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" "${CLAUDE_CMD}" C-m

# Window 3: Gemini model lead
tmux new-window -t "${SESSION}" -n "${GEMINI_WIN}" -c "${VAULT_ROOT}/model-lanes/gemini"
tmux pipe-pane -t "${SESSION}:${GEMINI_WIN}" -o "cat >> ${TMUX_LOG_DIR}/gemini.log"
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "${PATH_PREFIX}" C-m
tmux send-keys -t "${SESSION}:${GEMINI_WIN}" "${GEMINI_AUTH_PREFIX}" C-m
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
