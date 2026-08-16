#!/bin/bash
# Compatibility wrapper for Chrono's simple dispatch command.
#
# Usage:
#   bash scripts/send-task.sh <source-namespace> <body-file> <specialist> [to-model]
#
# This wrapper generates standard TASK frontmatter, then routes the packet
# through bin/send-task.sh so normal Chrono dispatches get the same safety path
# as prepared task files: write-scope checks, toolkit injection,
# active registry updates, dispatch logging, and board launch.

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
HARDENED_DISPATCH="${VAULT_ROOT}/bin/send-task.sh"
RUNTIME_MAP="${VAULT_ROOT}/shared/specialist-runtime-map.tsv"
source "${VAULT_ROOT}/shared/lead-windows.sh"

if [[ $# -lt 3 ]]; then
    echo "usage: $0 <source-namespace> <body-file> <specialist> [to-model]"
    echo "  source-namespace: ${COMPATIBILITY_NAMESPACES[*]}"
    echo "  body-file: path to markdown file containing task body"
    echo "  specialist: canonical specialist name, or none only when direct_lane_work_allowed is intentionally true"
    exit 1
fi

COMPAT_NAMESPACE="$1"
SOURCE_NAMESPACE="$1"
BODY_FILE="$2"
SPECIALIST="$3"
TO_MODEL="${4:-}"

if [[ ! -f "${BODY_FILE}" ]]; then
    echo "ERROR: body file not found: ${BODY_FILE}"
    exit 1
fi

if ! is_compatibility_namespace "${COMPAT_NAMESPACE}"; then
    echo "ERROR: invalid compatibility namespace: ${COMPAT_NAMESPACE}"
    exit 1
fi

map_field() {
    local specialist="$1" field_index="$2"
    awk -F '\t' -v s="$specialist" -v idx="$field_index" '$1 == s {print $idx; exit}' "${RUNTIME_MAP}"
}

if [[ -z "${TO_MODEL}" ]]; then
    # A namespace selects mailbox storage, never a model. The only valid
    # omitted-model fallback is the specialist's primary lane in the runtime map.
    if [[ "${SPECIALIST}" == "none" ]]; then
        echo "ERROR: omitted to-model requires a canonical specialist"
        exit 1
    fi
    if [[ ! -r "${RUNTIME_MAP}" ]]; then
        echo "ERROR: specialist runtime map is unavailable: ${RUNTIME_MAP}"
        exit 1
    fi
    TO_MODEL="$(map_field "${SPECIALIST}" 7)"
    if [[ -z "${TO_MODEL}" ]]; then
        echo "ERROR: specialist is absent from runtime map: ${SPECIALIST}"
        exit 1
    fi
fi
[[ "${TO_MODEL}" == "codex" ]] && TO_MODEL="gpt-codex"

REVIEW_MODEL="none"
MANDATORY_REVIEW="false"
if [[ "${SPECIALIST}" != "none" && -f "${RUNTIME_MAP}" ]]; then
    # Canonical map fields used here: source_namespace=2 safety_level=4 primary_lane=7 review_lane=14
    mapped_model="$(map_field "${SPECIALIST}" 7)"
    mapped_review="$(map_field "${SPECIALIST}" 14)"
    mapped_namespace="$(map_field "${SPECIALIST}" 2)"
    mapped_safety="$(map_field "${SPECIALIST}" 4)"
    [[ "${mapped_model}" == "codex" ]] && mapped_model="gpt-codex"
    [[ "${mapped_review}" == "codex" ]] && mapped_review="gpt-codex"
    if [[ -n "${mapped_model}" ]]; then
        TO_MODEL="${mapped_model}"
        REVIEW_MODEL="${mapped_review:-none}"
        SOURCE_NAMESPACE="${mapped_namespace:-${SOURCE_NAMESPACE}}"
        [[ "${mapped_safety}" == "high" ]] && MANDATORY_REVIEW="true"
    fi
fi

# This convenience wrapper authors ordinary project packets. Bounty packets use
# the prepared-packet path so their operator-approved contract stays explicit.
MODE="project"

if [[ ! -x "${HARDENED_DISPATCH}" ]]; then
    echo "ERROR: hardened dispatcher not executable: ${HARDENED_DISPATCH}"
    exit 1
fi

TIMESTAMP="$(date +%Y-%m-%d-%H%M)"
TASK_ID="TASK-${TIMESTAMP}-$(uuidgen | head -c 8 | tr '[:upper:]' '[:lower:]')"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/squad-task.XXXXXX")"
TASK_FILE="${STAGING_DIR}/${TASK_ID}.md"
trap 'rm -rf "${STAGING_DIR}"' EXIT

{
    cat <<EOF
---
id: ${TASK_ID}
run_id: none
from: chrono
mode: ${MODE}
phase: none
type: TASK
priority: normal
status: new
created: $(date -u +%FT%TZ)
deadline: none
write_scope: [departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md]
read_context: []
return_artifact: departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md
compatibility_namespace: ${COMPAT_NAMESPACE}
specialist: ${SPECIALIST}
to_model: ${TO_MODEL}
source_namespace: ${SOURCE_NAMESPACE}
review_model: ${REVIEW_MODEL}
mandatory_review: ${MANDATORY_REVIEW}
success_criteria: []
out_of_scope: []
parallel_safe: false
direct_lane_work_allowed: false
operator_approved: true
parent_msg_id: none
---

EOF
    cat "${BODY_FILE}"
} > "${TASK_FILE}"

sync "${TASK_FILE}" 2>/dev/null || true

VAULT_ROOT="${VAULT_ROOT}" "${HARDENED_DISPATCH}" "${TASK_FILE}"

echo "  File: ${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"
echo "  Reply expected at: ${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md"
echo "  Model lane: ${TO_MODEL}"
