#!/bin/bash
# Nudge a model-lane CLI with a concrete task packet path.

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
SESSION="${SQUAD_SESSION:-squad}"
source "${VAULT_ROOT}/shared/lead-windows.sh"

frontmatter_field() {
    local file="$1" field="$2"
    awk -v key="$field" '/^---$/{p=!p; next} p && index($0, key ":") == 1 {sub("^[^:]+:[[:space:]]*", ""); print; exit}' "$file"
}

TASK_PATH="${1:-}"
[[ -z "$TASK_PATH" ]] && { echo "usage: $0 /abs/path/to/TASK-*.md" >&2; exit 1; }
[[ "$TASK_PATH" = /* ]] || TASK_PATH="${PWD}/${TASK_PATH}"
[[ -f "$TASK_PATH" ]] || { echo "ERROR: task file not found: $TASK_PATH" >&2; exit 1; }

to_model="$(frontmatter_field "$TASK_PATH" to_model)"
specialist="$(frontmatter_field "$TASK_PATH" specialist)"
return_artifact="$(frontmatter_field "$TASK_PATH" return_artifact)"
[[ -z "$to_model" ]] && { echo "ERROR: missing to_model in $TASK_PATH" >&2; exit 1; }
[[ -z "$specialist" ]] && specialist="unknown"
[[ -z "$return_artifact" ]] && return_artifact="<return_artifact in frontmatter>"

target_win="$(runtime_window_name "$to_model")"
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "ERROR: tmux session '$SESSION' is not running" >&2
    exit 1
fi
if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$target_win"; then
    echo "ERROR: tmux window not found for model lane '$to_model' ($target_win)" >&2
    exit 1
fi

agent_prefix=""
if [[ "$to_model" == "gemini" && "$specialist" != "none" && "$specialist" != "unknown" ]]; then
    agent_prefix="@${specialist} "
fi

msg="${agent_prefix}TASK READY: open and process this exact task packet: ${TASK_PATH}. You are the ${to_model} model lead executing specialist ${specialist}. Use your native specialist/subagent adapter for ${specialist} if it is registered in this lane; otherwise execute inline and report the capability gap. Do not create another Chrono/mailbox task unless the packet explicitly asks for cross-lane review or parallel work. Read only the files named in the packet unless it explicitly allows more. Write the final response to: ${return_artifact}."

tmux send-keys -l -t "${SESSION}:${target_win}" "$msg"
sleep 0.3
tmux send-keys -t "${SESSION}:${target_win}" Enter
echo "Nudged ${SESSION}:${target_win} with $(basename "$TASK_PATH")"
