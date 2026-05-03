#!/usr/bin/env bash
# Spawn a specialist subprocess and log the call.
# Usage: bin/spawn-specialist.sh <lead> <specialist> <task_id> <task_body_path> [engagement_id]
#
# Logs to:
#   _state/specialist-log.jsonl  (per-spawn metadata — high fidelity)
#   _state/tool-calls.jsonl      (per-MCP-tool-call from stdout — BEST-EFFORT,
#                                 in-process MCP calls may not be captured)
#   _state/patterns.jsonl        (routine_signature for MCP graduation tracking)

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
mkdir -p "${VAULT}/_state"

LOG_SPECIALIST="${VAULT}/_state/specialist-log.jsonl"
LOG_TOOLCALLS="${VAULT}/_state/tool-calls.jsonl"
LOG_PATTERNS="${VAULT}/_state/patterns.jsonl"

if [[ $# -lt 4 ]]; then
    echo "usage: $0 <lead> <specialist> <task_id> <task_body_path> [engagement_id]" >&2
    echo "  lead: coding | security | content | sysmgmt | research" >&2
    exit 1
fi

LEAD="$1"; SPECIALIST="$2"; TASK_ID="$3"; TASK_BODY="$4"; ENGAGEMENT_ID="${5:-unknown}"

if [[ ! -f "${TASK_BODY}" ]]; then
    echo "ERROR: task body not found: ${TASK_BODY}" >&2
    exit 1
fi

# CLI per Lead (per dispatch-toolkit.sh table)
case "${LEAD}" in
    coding)   CLI=codex ;;
    security) CLI=claude ;;
    content)  CLI=gemini ;;
    sysmgmt)  CLI=claude ;;
    research) CLI=kimi ;;
    *) echo "ERROR: invalid lead: ${LEAD}" >&2; exit 1 ;;
esac

IDENTITY_FILE="${VAULT}/departments/${LEAD}/specialists/${SPECIALIST}.md"
if [[ ! -f "${IDENTITY_FILE}" ]]; then
    echo "WARNING: identity file not found: ${IDENTITY_FILE} — proceeding without --append-system-prompt" >&2
    IDENTITY_FILE=""
fi

START_TS=$(date -u +%FT%TZ)
START_NS=$(date +%s%N)

# Drop API-key envs (subscription auth)
DROP_KEYS="env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY"

# Spawn per CLI
case "${CLI}" in
    claude)
        if [[ -n "${IDENTITY_FILE}" ]]; then
            OUT=$(${DROP_KEYS} claude -p --append-system-prompt "$(cat "${IDENTITY_FILE}")" "$(cat "${TASK_BODY}")" 2>&1)
        else
            OUT=$(${DROP_KEYS} claude -p "$(cat "${TASK_BODY}")" 2>&1)
        fi
        EXIT_CODE=$?
        ;;
    codex)
        OUT=$(${DROP_KEYS} codex exec --sandbox workspace-write "$(cat "${TASK_BODY}")" 2>&1)
        EXIT_CODE=$?
        ;;
    gemini)
        OUT=$(${DROP_KEYS} gemini -p "$(cat "${TASK_BODY}")" 2>&1)
        EXIT_CODE=$?
        ;;
    kimi)
        OUT=$(${DROP_KEYS} kimi --print --quiet "$(cat "${TASK_BODY}")" 2>&1)
        EXIT_CODE=$?
        ;;
esac

END_NS=$(date +%s%N)
DURATION_MS=$(( (END_NS - START_NS) / 1000000 ))
STDOUT_BYTES=${#OUT}

# === Log 1: specialist-log.jsonl (high fidelity) ===
ALLOWED_TOOLS_HASH=$(echo -n "${LEAD}|${SPECIALIST}" | shasum -a 256 | cut -c1-12)
printf '{"ts":"%s","lead":"%s","specialist":"%s","cli":"%s","task_id":"%s","engagement_id":"%s","exit_code":%d,"duration_ms":%d,"stdout_bytes":%d,"identity_hash":"%s"}\n' \
    "${START_TS}" "${LEAD}" "${SPECIALIST}" "${CLI}" "${TASK_ID}" "${ENGAGEMENT_ID}" "${EXIT_CODE}" "${DURATION_MS}" "${STDOUT_BYTES}" "${ALLOWED_TOOLS_HASH}" \
    >> "${LOG_SPECIALIST}"

# === Log 2: tool-calls.jsonl (best-effort, stdout-grep) ===
# CAVEAT: in-process MCP calls within the CLI itself may not appear in stdout
echo "${OUT}" | grep -oE 'mcp__[a-z_-]+__[a-z_-]+|chrono-[a-z-]+|chrono-vault|sequential-thinking|chrome-devtools|playwright|context7' | sort -u | while IFS= read -r tool; do
    [[ -z "${tool}" ]] && continue
    printf '{"ts":"%s","specialist":"%s","tool_call_seen":"%s","capture_method":"stdout-grep-best-effort","task_id":"%s"}\n' \
        "${START_TS}" "${SPECIALIST}" "${tool}" "${TASK_ID}" \
        >> "${LOG_TOOLCALLS}"
done

# === Log 3: patterns.jsonl (routine_signature for graduation) ===
# Routine signature = hash of (specialist + task-body-fingerprint)
# Fingerprint: top 3 words of task body, lowercase, sorted (proxy for task shape)
TASK_FINGERPRINT=$(head -c 1000 "${TASK_BODY}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z' '\n' | sort -u | grep -E '^[a-z]{4,}$' | head -3 | sort | tr '\n' '_' | sed 's/_$//')
ROUTINE_SIG=$(echo -n "${SPECIALIST}|${TASK_FINGERPRINT}" | shasum -a 256 | cut -c1-12)

printf '{"ts":"%s","routine_signature":"%s","specialist":"%s","lead":"%s","engagement_id":"%s","task_id":"%s","fingerprint":"%s"}\n' \
    "${START_TS}" "${ROUTINE_SIG}" "${SPECIALIST}" "${LEAD}" "${ENGAGEMENT_ID}" "${TASK_ID}" "${TASK_FINGERPRINT}" \
    >> "${LOG_PATTERNS}"

# Echo specialist output to stdout (for caller to capture/forward)
echo "${OUT}"
exit "${EXIT_CODE}"
