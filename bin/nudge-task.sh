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

# Completion envelope the outbox-watcher keys on:
# departments/<compat_ns>/outbox/<id>-response.md. <id> is the packet's id;
# <compat_ns> is the department mailbox the packet was read from
# (departments/<ns>/inbox/<id>.md) — authoritative even when a hand-authored
# packet omits the compatibility_namespace frontmatter field.
task_id="$(frontmatter_field "$TASK_PATH" id)"
[[ -z "$task_id" ]] && task_id="$(basename "$TASK_PATH" .md)"
compat_ns="$(printf '%s\n' "$TASK_PATH" | sed -n 's#.*/departments/\([^/]*\)/.*#\1#p')"
if [[ -n "$compat_ns" ]]; then
    envelope="${VAULT_ROOT}/departments/${compat_ns}/outbox/${task_id}-response.md"
else
    envelope="departments/<compatibility_namespace>/outbox/${task_id}-response.md"
fi

target_win="$(runtime_window_name "$to_model")"
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "ERROR: tmux session '$SESSION' is not running" >&2
    exit 1
fi
if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$target_win"; then
    echo "ERROR: tmux window not found for model lane '$to_model' ($target_win)" >&2
    exit 1
fi

native_hint="Use your native specialist/subagent adapter for ${specialist} if it is registered in this lane; otherwise execute inline and report the capability gap."
if [[ "$to_model" == "gemini" && "$specialist" != "none" && "$specialist" != "unknown" ]]; then
    native_hint="Use Gemini invoke_agent with agent_name '${specialist}' if it is registered in this lane; do not treat @${specialist} context loading as subagent dispatch. If invoke_agent is unavailable, execute inline and report the capability gap."
fi

msg="TASK READY: open and process this exact task packet: ${TASK_PATH}. You are the ${to_model} model lead executing specialist ${specialist}. ${native_hint} Do not create another Chrono/mailbox task unless the packet explicitly asks for cross-lane review or parallel work. Read only the files named in the packet unless it explicitly allows more. ON COMPLETION WRITE BOTH: (1) your work to the return_artifact: ${return_artifact} ; AND (2) the outbox completion envelope: ${envelope} — markdown with frontmatter [id: ${task_id}-response | in_response_to: ${task_id} | from: ${to_model} | to: chrono | type: RESULT | status: complete|needs_review|blocked | return_artifact: ${return_artifact}] then a one-paragraph summary. The outbox-watcher keys on this envelope to auto-reconcile; without it your finished work sits in-flight. If you are a panel MEMBER, do not write the envelope — only the coordinator does."

tmux send-keys -l -t "${SESSION}:${target_win}" "$msg"
sleep 0.3
tmux send-keys -t "${SESSION}:${target_win}" Enter
echo "Nudged ${SESSION}:${target_win} with $(basename "$TASK_PATH")"
