#!/bin/bash
# Compatibility wrapper for Chrono's simple dispatch command.
#
# Usage:
#   REVIEW_TRIGGERS='[blast_radius]' bash scripts/send-task.sh \
#       <source-namespace> <body-file> <specialist> [to-model] \
#       --mode <project|bounty|modeless> [--dry-run]
#
#   --mode is required. The wrapper writes that exact operator-approved value
#     into packet frontmatter and never supplies a default.
#
#   WRITE_SCOPE="path/a, path/b"  — extra writable paths, appended to the response
#     artifact. Without this the wrapper could only ever author read-only packets,
#     so any packet asking for code changes silently could not apply them.
#
#   REVIEWS=none | REVIEWS=TASK-...  — required review-provenance declaration.
#     `none` deliberately marks ordinary work; a canonical task id marks a review
#     and is stamped into the response envelope for settlement.
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
AUTHORING_PREFLIGHT="${VAULT_ROOT}/scripts/python/dispatch_preflight.py"
RUNTIME_MAP="${VAULT_ROOT}/shared/specialist-runtime-map.tsv"
source "${VAULT_ROOT}/shared/lead-windows.sh"

if [[ $# -lt 3 ]]; then
    echo "usage: $0 <source-namespace> <body-file> <specialist> [to-model] --mode <project|bounty|modeless> [--dry-run]"
    echo "  source-namespace: ${COMPATIBILITY_NAMESPACES[*]}"
    echo "  body-file: path to markdown file containing task body"
    echo "  specialist: canonical specialist name, or none only when direct_lane_work_allowed is intentionally true"
    echo "  --mode: required operator-approved packet mode; no default is supplied"
    exit 1
fi

COMPAT_NAMESPACE="$1"
SOURCE_NAMESPACE="$1"
BODY_FILE="$2"
SPECIALIST="$3"
shift 3

TO_MODEL=""
MODE=""
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            [[ $# -ge 2 ]] || {
                echo "ERROR: --mode requires project, bounty, or modeless"
                exit 1
            }
            [[ -z "${MODE}" ]] || {
                echo "ERROR: --mode may be specified only once"
                exit 1
            }
            MODE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --*)
            echo "ERROR: unknown option: $1"
            exit 1
            ;;
        *)
            [[ -z "${TO_MODEL}" ]] || {
                echo "ERROR: unexpected argument: $1"
                exit 1
            }
            TO_MODEL="$1"
            shift
            ;;
    esac
done

if [[ -z "${MODE}" ]]; then
    echo "ERROR: missing required --mode <project|bounty|modeless>; the wrapper will not invent packet field 'mode'"
    exit 1
fi
case "${MODE}" in
    project|bounty|modeless) ;;
    *)
        echo "ERROR: invalid --mode '${MODE}'; expected project, bounty, or modeless"
        exit 1
        ;;
esac

# Review intent is an explicit admission-time union. An omitted variable used to
# be indistinguishable from deliberate ordinary work, and a missing review target
# cannot be reconstructed after launch. Validate before TASK_ID/UUID creation or
# packet staging so omission cannot leave any dispatch residue.
if [[ -z "${REVIEWS+x}" ]]; then
    echo "ERROR: missing required REVIEWS declaration; set REVIEWS=none for ordinary work or REVIEWS=TASK-YYYY-MM-DD-HHMM-<suffix> for a review"
    exit 1
fi
if [[ -z "${REVIEWS}" ]]; then
    echo "ERROR: empty REVIEWS declaration; set REVIEWS=none for ordinary work or REVIEWS=TASK-YYYY-MM-DD-HHMM-<suffix> for a review"
    exit 1
fi
if [[ "${REVIEWS}" != "none" && ! "${REVIEWS}" =~ ^TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[A-Za-z0-9][A-Za-z0-9-]*$ ]]; then
    echo "ERROR: invalid REVIEWS declaration '${REVIEWS}'; expected exactly none or a canonical TASK-YYYY-MM-DD-HHMM-<suffix> id"
    exit 1
fi

# An explicit 4th-arg lane must survive the runtime-map lookup below; without
# this the documented [to-model] override was silently discarded (failover
# to a backup lane was impossible from this wrapper).
EXPLICIT_MODEL="${TO_MODEL}"

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

if [[ ! -x "${HARDENED_DISPATCH}" ]]; then
    echo "ERROR: hardened dispatcher not executable: ${HARDENED_DISPATCH}"
    exit 1
fi

# The hardened dispatcher honours authorized_delete_paths, but this wrapper had no
# way to express it, so any packet needing a file MOVE (retire a skill, relocate a
# doc) was undispatchable from here and had to be hand-authored. Always emitted:
# the dispatcher json.loads it and treats [] as falsy, so an unset value is inert.
DELETE_PATHS_LINE="authorized_delete_paths: [${AUTHORIZED_DELETE_PATHS:-}]"
# Every generated packet carries the typed declaration. The hardened dispatcher
# independently validates prepared packets, then projects only a real task target.
REVIEWS_LINE="reviews: ${REVIEWS}"$'\n'

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

# The hardened live path runs the packet-bound preflight immediately before host
# admission. Its dry-run exits earlier through the context-builder validator, so
# emit the same authoring advisories here for generated dry-runs. This diagnostic
# path is intentionally fail-open: neither a warning nor a broken warning check
# may change what the hardened dispatcher admits.
if [[ "${DRY_RUN}" == "true" && -f "${AUTHORING_PREFLIGHT}" ]]; then
    python3 "${AUTHORING_PREFLIGHT}" \
        --repo-root "${VAULT_ROOT}" \
        --packet "${TASK_FILE}" \
        --authoring-warnings-only >/dev/null || true
fi

echo "  Packet mode: ${MODE}"
DISPATCH_ARGS=("${TASK_FILE}")
if [[ "${DRY_RUN}" == "true" ]]; then
    DISPATCH_ARGS+=(--dry-run)
fi
VAULT_ROOT="${VAULT_ROOT}" "${HARDENED_DISPATCH}" "${DISPATCH_ARGS[@]}"

echo "  File: ${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"
echo "  Reply expected at: ${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md"
echo "  Model lane: ${TO_MODEL}"
