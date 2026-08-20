#!/bin/bash
# Compatibility wrapper for Chrono's simple dispatch command.
#
# Usage:
#   REVIEW_TRIGGERS='[blast_radius]' bash scripts/send-task.sh \
#       <source-namespace> <body-file> <specialist> [to-model]
#
#   WRITE_SCOPE="path/a, path/b"  — extra writable paths, appended to the response
#     artifact. Without this the wrapper could only ever author read-only packets,
#     so any packet asking for code changes silently could not apply them.
#
#   REVIEWS=TASK-...  — the task this packet reviews. Required for a review packet:
#     the response envelope is stamped from it, so settlement works without the
#     reviewer having to declare its own subject.
#
#   AUTHORIZED_DELETE_PATHS='"a", "b"'  — JSON-list members of paths the worker may
#     DELETE. Required for any file MOVE; the board refuses worker deletions without it.
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
# An explicit 4th-arg lane must survive the runtime-map lookup below; without
# this the documented [to-model] override was silently discarded (failover
# to a backup lane was impossible from this wrapper).
EXPLICIT_MODEL="${4:-}"

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
MAPPED_REVIEW_MODEL="none"
REVIEW_TRIGGERS="${REVIEW_TRIGGERS:-[]}"
if [[ "$REVIEW_TRIGGERS" == *$'\n'* || "$REVIEW_TRIGGERS" == *$'\r'* ]]; then
    echo "ERROR: REVIEW_TRIGGERS must be one single-line inline list"
    exit 1
fi
MANDATORY_REVIEW="false"
if [[ "${SPECIALIST}" != "none" && -f "${RUNTIME_MAP}" ]]; then
    # Canonical map fields used here: source_namespace=2 primary_lane=7 review_lane=14.
    # safety_level is a specialist quality floor, not a property of this change.
    mapped_model="$(map_field "${SPECIALIST}" 7)"
    mapped_review="$(map_field "${SPECIALIST}" 14)"
    mapped_namespace="$(map_field "${SPECIALIST}" 2)"
    [[ "${mapped_model}" == "codex" ]] && mapped_model="gpt-codex"
    [[ "${mapped_review}" == "codex" ]] && mapped_review="gpt-codex"
    if [[ -n "${mapped_model}" ]]; then
        [[ -z "${EXPLICIT_MODEL}" ]] && TO_MODEL="${mapped_model}"
        MAPPED_REVIEW_MODEL="${mapped_review:-none}"
        SOURCE_NAMESPACE="${mapped_namespace:-${SOURCE_NAMESPACE}}"
    fi
fi

# Review is a property of this packet. The hardened dispatcher validates the
# four-token enum and rejects a flag/list mismatch; this wrapper only derives
# the boolean and mapped reviewer from whether the explicit list is empty.
review_triggers_compact="${REVIEW_TRIGGERS//[[:space:]]/}"
if [[ "$review_triggers_compact" != "[]" ]]; then
    MANDATORY_REVIEW="true"
    REVIEW_MODEL="$MAPPED_REVIEW_MODEL"
fi

# This convenience wrapper authors ordinary project packets. Bounty packets use
# the prepared-packet path so their operator-approved contract stays explicit.
MODE="project"

if [[ ! -x "${HARDENED_DISPATCH}" ]]; then
    echo "ERROR: hardened dispatcher not executable: ${HARDENED_DISPATCH}"
    exit 1
fi

# The hardened dispatcher honours authorized_delete_paths, but this wrapper had no
# way to express it, so any packet needing a file MOVE (retire a skill, relocate a
# doc) was undispatchable from here and had to be hand-authored. Always emitted:
# the dispatcher json.loads it and treats [] as falsy, so an unset value is inert.
DELETE_PATHS_LINE="authorized_delete_paths: [${AUTHORIZED_DELETE_PATHS:-}]"
# A review packet must name the task it reviews. dispatch_context_builder reads this
# packet field and stamps it into the trusted response envelope, so the reviewer never
# has to remember it -- reviewers omitted it on every attempt, including one packet that
# asked explicitly. Without this line the stamp has nothing to copy and the review
# cannot settle, which is what left memory promotion dead.
REVIEWS_LINE=""
if [[ -n "${REVIEWS:-}" ]]; then
    REVIEWS_LINE="reviews: ${REVIEWS}"$'\n'
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
write_scope: [departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md${WRITE_SCOPE:+, ${WRITE_SCOPE}}]
${DELETE_PATHS_LINE}
${REVIEWS_LINE}read_context: []
return_artifact: departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md
compatibility_namespace: ${COMPAT_NAMESPACE}
specialist: ${SPECIALIST}
to_model: ${TO_MODEL}
model_override_reason: ${MODEL_OVERRIDE_REASON:-none}
source_namespace: ${SOURCE_NAMESPACE}
review_model: ${REVIEW_MODEL}
mandatory_review: ${MANDATORY_REVIEW}
review_triggers: ${REVIEW_TRIGGERS}
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
