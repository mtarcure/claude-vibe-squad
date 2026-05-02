#!/bin/bash
# Mailbox helper — send a TASK message to a Lead's inbox.
#
# Usage:
#   bash scripts/send-task.sh <to-lead> <body-file>
#   bash scripts/send-task.sh coding /tmp/refactor-task.md
#
# Reads body from <body-file>. Generates frontmatter automatically.
# Does atomic write (temp + rename) to be safe against partial-write corruption.

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <to-lead> <body-file>"
    echo "  to-lead: coding | security | content | sysmgmt | research"
    echo "  body-file: path to markdown file containing task body"
    exit 1
fi

TO_LEAD="$1"
BODY_FILE="$2"

if [[ ! -f "${BODY_FILE}" ]]; then
    echo "ERROR: body file not found: ${BODY_FILE}"
    exit 1
fi

case "${TO_LEAD}" in
    coding|security|content|sysmgmt|research) ;;
    *) echo "ERROR: invalid to-lead: ${TO_LEAD}"; exit 1 ;;
esac

# Generate ID
TIMESTAMP="$(date +%Y-%m-%d-%H%M)"
TASK_ID="TASK-${TIMESTAMP}-$(uuidgen | head -c 8 | tr 'A-Z' 'a-z')"
INBOX_DIR="${VAULT_ROOT}/departments/${TO_LEAD}/inbox"
TARGET="${INBOX_DIR}/${TASK_ID}.md"
TMP="${TARGET}.tmp"

mkdir -p "${INBOX_DIR}"

# Atomic write
{
    cat <<EOF
---
id: ${TASK_ID}
run_id: none
from_lead: chrono
to_lead: ${TO_LEAD}
mode: none
phase: none
type: TASK
priority: normal
status: new
created: $(date -u +%FT%TZ)
deadline: none
write_scope: []
read_context: []
return_artifact: ${VAULT_ROOT}/departments/${TO_LEAD}/outbox/${TASK_ID}-response.md
operator_approved: true
parent_msg_id: none
---

EOF
    cat "${BODY_FILE}"
} > "${TMP}"

# Sync + rename (atomic on POSIX)
sync "${TMP}" 2>/dev/null || true
mv "${TMP}" "${TARGET}"

# Central dispatch log — every send-task.sh invocation appends one JSON line.
# Easy to grep across days: jq 'select(.to_lead=="security")' < dispatch-log.jsonl
DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
mkdir -p "$(dirname "${DISPATCH_LOG}")"
printf '{"ts":"%s","task_id":"%s","to_lead":"%s","return_artifact":"%s"}\n' \
    "$(date -u +%FT%TZ)" "${TASK_ID}" "${TO_LEAD}" \
    "${VAULT_ROOT}/departments/${TO_LEAD}/outbox/${TASK_ID}-response.md" \
    >> "${DISPATCH_LOG}"

# Nudge the target Lead's tmux pane so Chrono doesn't have to switch panes.
# Each Lead's idle CLI receives "check inbox" as new user input → processes the
# task → writes to outbox. Chrono polls outbox for the response.
NUDGE_MSG="${NUDGE_MSG:-A new task has arrived in inbox/. Pick up the oldest TASK-*.md and process it per protocol.}"
if [[ -z "${SKIP_NUDGE:-}" ]] && command -v tmux >/dev/null 2>&1 && tmux has-session -t squad 2>/dev/null; then
    if tmux list-windows -t squad -F '#{window_name}' 2>/dev/null | grep -q "^${TO_LEAD}\$"; then
        # -l (literal): disables key-name lookup so any special chars in NUDGE_MSG
        # are sent as raw input rather than interpreted as keys. Then a brief
        # pause before Enter — some TUIs (Codex, Gemini) need the text fully
        # buffered before the submit registers.
        tmux send-keys -l -t "squad:${TO_LEAD}" "${NUDGE_MSG}"
        sleep 0.3
        tmux send-keys -t "squad:${TO_LEAD}" Enter
        echo "  Nudged squad:${TO_LEAD} pane"
    fi
fi

echo "✓ Sent ${TASK_ID} to ${TO_LEAD}'s inbox"
echo "  File: ${TARGET}"
echo "  Reply expected at: ${VAULT_ROOT}/departments/${TO_LEAD}/outbox/${TASK_ID}-response.md"
