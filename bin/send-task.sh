#!/bin/bash
# bin/send-task.sh — Dispatch a TASK file to a source namespace inbox.
#
# Spec 1.5 safety features baked in:
#   Item 3: per-task version dirs (opt-in via per_task_versioning: true)
#   Item 4: no-delete rule injection (via shared/dispatch-toolkit.sh)
#   Item 5: write_scope conflict detection against active-tasks.json
#   Item 7: active-task registry update (_state/active-tasks.json)
#
# Usage:
#   bin/send-task.sh <task-file> [--nudge-pane <tmux-target>] [--dry-run]
#       [--panel a,b,c] [--panel-policy evidence-synthesis]
#       [--panel-quorum all|N] [--panel-timeout SECONDS]
#       [--fanout --panel-assignment TEXT --panel-assignment TEXT]
#   bin/send-task.sh --close-task <TASK-ID>  # evidence-gated reconciliation
#
# Required frontmatter in task file:
#   id: TASK-YYYY-MM-DD-HHMM-<hash>
#   to_model: gpt-codex | claude | gemini | kimi
#   specialist: <canonical specialist>
#   source_namespace: coding | security | content | content-engineer | sysmgmt | research | shared
#
# Optional frontmatter:
#   write_scope: [path1, path2]     — conflict-checked against active tasks
#   per_task_versioning: true       — rewrites return_artifact to include TASK-ID subdir
#
# Exit codes:
#   0  — dispatched successfully
#   1  — blocked (scope conflict, missing fields)
#   2  — dry-run mode (no writes; print what would happen)

set -euo pipefail
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
ACTIVE_REGISTRY="${VAULT_ROOT}/_state/active-tasks.json"
TOOLKIT="${VAULT_ROOT}/shared/dispatch-toolkit.sh"
RUNTIME_MAP="${VAULT_ROOT}/shared/specialist-runtime-map.tsv"
FAILOVER_CONTROL="${VAULT_ROOT}/bin/failover-control.py"
DAEMON_REQUIREMENTS="${VAULT_ROOT}/daemon/requirements.txt"

# ── helpers ──────────────────────────────────────────────────────────────────

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  → $*"; }

frontmatter_field() {
    local file="$1" field="$2"
    awk "
        /^---/{p=!p; next}
        p && /^${field}:/ {
            sub(/^${field}: */, \"\")
            print
            exit
        }
    " "$file"
}

map_field() {
    local specialist="$1" field_index="$2"
    [[ -f "$RUNTIME_MAP" ]] || return 1
    awk -F '\t' -v s="$specialist" -v idx="$field_index" '$1 == s {print $idx; exit}' "$RUNTIME_MAP"
}

validate_native_adapter() {
    local model="$1" specialist="$2" adapter agent_name
    [[ "$specialist" == "none" ]] && return 0
    case "$model" in
        gpt-codex)
            adapter="${VAULT_ROOT}/model-lanes/gpt-codex/.codex/agents/${specialist}.toml"
            agent_name="${specialist//-/_}"
            [[ -f "$adapter" ]] || die "predispatch blocked: missing Codex adapter for specialist '${specialist}'"
            grep -q "name = \"${agent_name}\"" "$adapter" || die "predispatch blocked: Codex adapter name mismatch for specialist '${specialist}'"
            ;;
        claude)
            adapter="${VAULT_ROOT}/model-lanes/claude/.claude/agents/${specialist}.md"
            [[ -f "$adapter" ]] || die "predispatch blocked: missing Claude adapter for specialist '${specialist}'"
            [[ "$(head -n 1 "$adapter")" == "---" ]] || die "predispatch blocked: Claude adapter missing YAML frontmatter for specialist '${specialist}'"
            ;;
        gemini)
            adapter="${VAULT_ROOT}/model-lanes/gemini/.gemini/agents/${specialist}.md"
            [[ -f "$adapter" ]] || die "predispatch blocked: missing Gemini adapter for specialist '${specialist}'"
            [[ "$(head -n 1 "$adapter")" == "---" ]] || die "predispatch blocked: Gemini adapter missing YAML frontmatter for specialist '${specialist}'"
            grep -q "^name: ${specialist}$" "$adapter" || die "predispatch blocked: Gemini adapter name mismatch for specialist '${specialist}'"
            ;;
        kimi)
            adapter="${VAULT_ROOT}/model-lanes/kimi/.kimi/agents/${specialist}.yaml"
            [[ -f "$adapter" ]] || die "predispatch blocked: missing Kimi adapter for specialist '${specialist}'"
            grep -q "^[[:space:]]*${specialist}:" "${VAULT_ROOT}/model-lanes/kimi/main.yaml" || die "predispatch blocked: Kimi main.yaml missing subagent '${specialist}'"
            ;;
    esac
}

validate_task_capabilities() {
    local task_file="$1" latest_audit
    latest_audit="$(find "${VAULT_ROOT}/_state/audit-logs" -maxdepth 1 -name '*-mcp-audit.md' -type f -print 2>/dev/null | sort | tail -1 || true)"
    python3 - "$task_file" "$latest_audit" <<'PYEOF'
import re
import sys
from pathlib import Path

task_path = Path(sys.argv[1])
audit_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
text = task_path.read_text(errors="replace")

blocked_names = {
    "brave_search": "live research tools are perplexity_search_web,xai_search,arxiv_search; Brave/Apify/Serper are planned/unverified",
    "apify_search": "live research tools are perplexity_search_web,xai_search,arxiv_search; Brave/Apify/Serper are planned/unverified",
    "serper_search": "live research tools are perplexity_search_web,xai_search,arxiv_search; Brave/Apify/Serper are planned/unverified",
    "elevenlabs__check_subscription": "chrono-content-engineer currently exposes generate_audio,generate_image,generate_video only",
}
issues = []
for name, reason in blocked_names.items():
    if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
        issues.append(f"unavailable-tool:{name} ({reason})")

tools_by_server: dict[str, set[str]] = {}
if audit_path and audit_path.exists():
    for line in audit_path.read_text(errors="replace").splitlines():
        match = re.match(r"- (chrono-[a-z-]+): .* tools=([^ ]+)", line)
        if not match:
            continue
        server, tools_csv = match.groups()
        tools = {tool for tool in tools_csv.split(",") if tool and tool != "none"}
        tools_by_server.setdefault(server, set()).update(tools)

patterns = [
    re.compile(r"`?(chrono-[a-z-]+)`?\s+MCP server's\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s+tool", re.I),
    re.compile(r"`?(chrono-[a-z-]+)`?\s+MCP\s+tool\s+`?([A-Za-z_][A-Za-z0-9_]*)`?", re.I),
]
for pattern in patterns:
    for server, tool in pattern.findall(text):
        if server not in tools_by_server:
            issues.append(f"unverified-mcp-server:{server} has no tools/list proof in latest audit")
            continue
        if tool not in tools_by_server[server]:
            available = ",".join(sorted(tools_by_server[server])) or "none"
            issues.append(f"unavailable-tool:{server}.{tool} (available:{available})")

if issues:
    print("predispatch capability validation failed: " + "; ".join(sorted(set(issues))), file=sys.stderr)
    raise SystemExit(1)
PYEOF
}

# ── sub-command: reconcile task on response landing ──────────────────────────
# Called by the response-landing hook when a lane writes TASK-*-response.md.
# This is evidence-gated: it reconciles from a valid landed envelope (or the
# guarded return-artifact safety net) and never force-promotes a task.

if [[ "${1:-}" == "--close-task" ]]; then
    CLOSE_ID="${2:-}"
    [[ -z "$CLOSE_ID" ]] && die "Usage: $0 --close-task <TASK-ID>"
    exec "${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$CLOSE_ID"
fi

# ── arg parse ─────────────────────────────────────────────────────────────────

TASK_FILE=""
NUDGE_PANE=""
NUDGE_UNAVAILABLE_REASON=""
DRY_RUN=false
PANEL_ENABLED=false
PANEL_MEMBERS_RAW=""
PANEL_POLICY="evidence-synthesis"
PANEL_QUORUM="all"
PANEL_TIMEOUT_SECONDS="900"
FANOUT_ENABLED=false
declare -a PANEL_ASSIGNMENTS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --nudge-pane) NUDGE_PANE="$2"; shift 2 ;;
        --nudge-unavailable) NUDGE_UNAVAILABLE_REASON="$2"; shift 2 ;;
        --panel) PANEL_ENABLED=true; PANEL_MEMBERS_RAW="$2"; shift 2 ;;
        --panel-policy) PANEL_POLICY="$2"; shift 2 ;;
        --panel-quorum) PANEL_QUORUM="$2"; shift 2 ;;
        --panel-timeout) PANEL_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --fanout) FANOUT_ENABLED=true; shift ;;
        --panel-assignment) PANEL_ASSIGNMENTS+=("$2"); shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        *)            TASK_FILE="$1"; shift ;;
    esac
done

[[ -z "$TASK_FILE" ]] && die "Usage: $0 <task-file> [--nudge-pane <target>] [--dry-run] [--panel a,b,c] [--panel-policy evidence-synthesis] [--panel-quorum all|N] [--panel-timeout SECONDS] [--fanout --panel-assignment TEXT ...]"
[[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

if ! $PANEL_ENABLED; then
    [[ "$PANEL_POLICY" == "evidence-synthesis" ]] || die "--panel-policy requires --panel"
    [[ "$PANEL_QUORUM" == "all" ]] || die "--panel-quorum requires --panel"
    [[ "$PANEL_TIMEOUT_SECONDS" == "900" ]] || die "--panel-timeout requires --panel"
    ! $FANOUT_ENABLED || die "--fanout requires --panel"
    (( ${#PANEL_ASSIGNMENTS[@]} == 0 )) || die "--panel-assignment requires --panel and --fanout"
elif ! $FANOUT_ENABLED && (( ${#PANEL_ASSIGNMENTS[@]} > 0 )); then
    die "--panel-assignment requires --fanout"
fi

# ── read task metadata ────────────────────────────────────────────────────────

# MED5 (wave-2): command substitution silently strips NUL bytes, so a raw NUL in
# the id frontmatter would collide to a different valid id instead of being
# rejected (overwrite / identity ambiguity). A task packet must never contain a
# NUL byte — validate the raw file bytes before parsing/trusting any frontmatter
# field, because $(frontmatter_field ...) can no longer reveal an embedded NUL.
if [[ -f "$TASK_FILE" ]] && ! LC_ALL=C tr -d '\000' < "$TASK_FILE" | cmp -s - "$TASK_FILE"; then
    die "invalid task file (contains a NUL byte): $TASK_FILE"
fi

TASK_ID=$(frontmatter_field "$TASK_FILE" "id")
TO_LEAD=$(frontmatter_field "$TASK_FILE" "to_lead")
COMPAT_NAMESPACE=$(frontmatter_field "$TASK_FILE" "compatibility_namespace")
# shellcheck disable=SC2034  # retained compatibility metadata for legacy packets
RUN_ID=$(frontmatter_field "$TASK_FILE" "run_id")
WRITE_SCOPE_RAW=$(frontmatter_field "$TASK_FILE" "write_scope")
PER_TASK_VERSIONING=$(frontmatter_field "$TASK_FILE" "per_task_versioning")
OWNING_LEAD=$(frontmatter_field "$TASK_FILE" "owning_lead")
SPECIALIST=$(frontmatter_field "$TASK_FILE" "specialist")
PRIMARY_RUNTIME=$(frontmatter_field "$TASK_FILE" "primary_runtime")
TO_MODEL=$(frontmatter_field "$TASK_FILE" "to_model")
SOURCE_NAMESPACE=$(frontmatter_field "$TASK_FILE" "source_namespace")
REVIEW_MODEL=$(frontmatter_field "$TASK_FILE" "review_model")
MANDATORY_REVIEW=$(frontmatter_field "$TASK_FILE" "mandatory_review")
MODEL_OVERRIDE_REASON=$(frontmatter_field "$TASK_FILE" "model_override_reason")
DIRECT_LANE_WORK_ALLOWED=$(frontmatter_field "$TASK_FILE" "direct_lane_work_allowed")
LEGACY_LEAD_DIRECT_ALLOWED=$(frontmatter_field "$TASK_FILE" "lead_direct_allowed")
PARALLEL_SAFE=$(frontmatter_field "$TASK_FILE" "parallel_safe")
PANEL_MEMBER_WRITE_SCOPE=$(frontmatter_field "$TASK_FILE" "panel_member_write_scope")
RETURN_ARTIFACT=$(frontmatter_field "$TASK_FILE" "return_artifact")
MAP_BACKUP="none"
MAP_OPERATOR_GATE="[]"
MAP_SAFETY=""

[[ -z "$TASK_ID" ]]  && die "Task file missing 'id' frontmatter: $TASK_FILE"
# FIX 1 (wave-2): TASK_ID becomes a path component for inbox/temp/outbox files.
# Require the exact canonical task-id format so it cannot contain a path
# separator, '.', '..', NUL, or whitespace and redirect a write outside the inbox.
if [[ ! "$TASK_ID" =~ ^TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[A-Za-z0-9][A-Za-z0-9-]*$ ]]; then
    die "invalid task id '${TASK_ID}': must match TASK-YYYY-MM-DD-HHMM-<suffix> (alphanumeric/hyphen)"
fi
[[ -z "$SPECIALIST" ]] && die "Task file missing 'specialist' frontmatter: $TASK_FILE"
[[ -z "$PARALLEL_SAFE" ]] && die "Task file missing 'parallel_safe' frontmatter: $TASK_FILE"
if [[ -z "$DIRECT_LANE_WORK_ALLOWED" ]]; then
    DIRECT_LANE_WORK_ALLOWED="$LEGACY_LEAD_DIRECT_ALLOWED"
fi
[[ -z "$DIRECT_LANE_WORK_ALLOWED" ]] && die "Task file missing 'direct_lane_work_allowed' frontmatter: $TASK_FILE"

# Temporary bridge: older prepared packets may still carry to_lead,
# owning_lead, or primary_runtime. New packets use model-lane fields and let
# this dispatcher choose the compatibility mailbox namespace.
if [[ -z "$TO_MODEL" ]]; then
    TO_MODEL="$PRIMARY_RUNTIME"
fi
if [[ -z "$REVIEW_MODEL" ]]; then
    REVIEW_MODEL="none"
fi
if [[ -z "$MANDATORY_REVIEW" ]]; then
    MANDATORY_REVIEW="false"
fi
if [[ -z "$PRIMARY_RUNTIME" ]]; then
    PRIMARY_RUNTIME="$TO_MODEL"
fi
if [[ -z "$SOURCE_NAMESPACE" ]]; then
    SOURCE_NAMESPACE="${TO_LEAD:-$OWNING_LEAD}"
fi
if [[ -z "$COMPAT_NAMESPACE" ]]; then
    COMPAT_NAMESPACE="${TO_LEAD:-$SOURCE_NAMESPACE}"
fi
if [[ -z "$TO_LEAD" ]]; then
    TO_LEAD="$COMPAT_NAMESPACE"
fi
if [[ -z "$OWNING_LEAD" ]]; then
    OWNING_LEAD="$SOURCE_NAMESPACE"
fi

[[ -z "$TO_MODEL" ]] && die "Task file missing 'to_model' frontmatter: $TASK_FILE"
[[ -z "$SOURCE_NAMESPACE" ]] && die "Task file missing 'source_namespace' frontmatter: $TASK_FILE"
[[ -z "$COMPAT_NAMESPACE" ]] && die "Task file missing compatibility namespace; set source_namespace or compatibility_namespace"

case "$TO_MODEL" in
    gpt-codex|claude|gemini|kimi|none) ;;
    *) die "invalid to_model '${TO_MODEL}'. Expected gpt-codex|claude|gemini|kimi|none." ;;
esac
case "$REVIEW_MODEL" in
    gpt-codex|claude|gemini|kimi|none) ;;
    *) die "invalid review_model '${REVIEW_MODEL}'. Expected gpt-codex|claude|gemini|kimi|none." ;;
esac
case "$SOURCE_NAMESPACE" in
    coding|security|content|content-engineer|sysmgmt|research|shared|chrono) ;;
    *) die "invalid source_namespace '${SOURCE_NAMESPACE}'." ;;
esac
# compatibility_namespace is interpolated into the mailbox path. Shared/Chrono
# coordinator packets may choose a different mailbox, but it must still be one
# of the real compatibility mailboxes — never an arbitrary path component.
case "$COMPAT_NAMESPACE" in
    coding|security|content|content-engineer|sysmgmt|research) ;;
    *) die "invalid compatibility_namespace '${COMPAT_NAMESPACE}'." ;;
esac
case "$MANDATORY_REVIEW" in
    true|false) ;;
    *) die "mandatory_review must be true or false, got '${MANDATORY_REVIEW}'." ;;
esac

if [[ "$COMPAT_NAMESPACE" != "$SOURCE_NAMESPACE" && "$SOURCE_NAMESPACE" != "shared" && "$SOURCE_NAMESPACE" != "chrono" ]]; then
    die "compatibility namespace (${COMPAT_NAMESPACE}) must match source_namespace (${SOURCE_NAMESPACE}) except shared/chrono coordinator work"
fi

if [[ "$SPECIALIST" == "none" && "$DIRECT_LANE_WORK_ALLOWED" != "true" ]]; then
    die "specialist:none requires direct_lane_work_allowed:true with an explicit body rationale"
fi

PANEL_MEMBERS_CSV=""
PANEL_MEMBERS_YAML="[]"
PANEL_MEMBER_IDS_CSV=""
PANEL_MEMBER_IDS_YAML="[]"
PANEL_COUNT=0
if $PANEL_ENABLED; then
    [[ "$TO_MODEL" == "claude" || "$TO_MODEL" == "gpt-codex" ]] \
        || die "panel-v1 supports only claude and gpt-codex lanes, got '${TO_MODEL}'"
    [[ "$PANEL_POLICY" == "evidence-synthesis" ]] \
        || die "panel-v1 policy must be evidence-synthesis, got '${PANEL_POLICY}'"
    [[ "$PANEL_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] \
        || die "panel timeout must be a positive integer, got '${PANEL_TIMEOUT_SECONDS}'"
    (( PANEL_TIMEOUT_SECONDS <= 86400 )) \
        || die "panel timeout exceeds 86400 seconds"
    if $FANOUT_ENABLED; then
        if [[ "$TO_MODEL" == "gpt-codex" ]]; then
            die "fan-out on gpt-codex is gated pending a live proof of concurrent native subagents, MCP inheritance, and structured parent-message return"
        fi
        [[ "$TO_MODEL" == "claude" ]] \
            || die "fan-out supports only the claude lane; gpt-codex is gated and gemini/kimi are disabled"
    fi

    [[ -z "$(frontmatter_field "$TASK_FILE" "dispatch_kind")" ]] \
        || die "task already contains dispatch_kind; do not combine a pre-panelized packet with --panel"
    [[ -n "$PANEL_MEMBERS_RAW" ]] || die "--panel requires a comma-separated member list"

    declare -a PANEL_MEMBERS=()
    IFS=',' read -r -a PANEL_INPUT <<<"$PANEL_MEMBERS_RAW"
    for raw_member in "${PANEL_INPUT[@]}"; do
        member="${raw_member//[[:space:]]/}"
        [[ "$member" =~ ^[a-z0-9][a-z0-9-]*$ ]] \
            || die "invalid panel member '${raw_member}'"
        if (( PANEL_COUNT > 0 )); then
            for existing_member in "${PANEL_MEMBERS[@]}"; do
                $FANOUT_ENABLED || [[ "$existing_member" != "$member" ]] \
                    || die "duplicate panel member '${member}'"
            done
        fi
        PANEL_MEMBERS[PANEL_COUNT]="$member"
        PANEL_COUNT=$((PANEL_COUNT + 1))
    done
    (( PANEL_COUNT >= 2 && PANEL_COUNT <= 3 )) \
        || die "panel-v1 requires 2-3 members (3 members + coordinator = 4-thread cap), got ${PANEL_COUNT}"

    declare -a PANEL_MEMBER_IDS=()
    if $FANOUT_ENABLED; then
        for member in "${PANEL_MEMBERS[@]}"; do
            [[ "$member" == "${PANEL_MEMBERS[0]}" ]] \
                || die "fan-out requires every panel member to name the same specialist"
        done
        (( ${#PANEL_ASSIGNMENTS[@]} == PANEL_COUNT )) \
            || die "fan-out requires one non-empty --panel-assignment per member: got ${#PANEL_ASSIGNMENTS[@]} for ${PANEL_COUNT}"
        declare -a NORMALIZED_ASSIGNMENTS=()
        for (( assignment_index=0; assignment_index<PANEL_COUNT; assignment_index++ )); do
            assignment="${PANEL_ASSIGNMENTS[$assignment_index]}"
            [[ "$assignment" != *$'\n'* && "$assignment" != *$'\r'* ]] \
                || die "fan-out assignments must be single-line text"
            normalized_assignment="$(printf '%s' "$assignment" | awk '{$1=$1; print}')"
            [[ -n "$normalized_assignment" ]] \
                || die "fan-out assignment $((assignment_index + 1)) is missing"
            for existing_assignment in "${NORMALIZED_ASSIGNMENTS[@]:-}"; do
                [[ "$existing_assignment" != "$normalized_assignment" ]] \
                    || die "fan-out assignments must be distinct; duplicate assignment: '${normalized_assignment}'"
            done
            NORMALIZED_ASSIGNMENTS+=("$normalized_assignment")
            PANEL_MEMBER_IDS+=("member-$((assignment_index + 1))")
        done
    else
        PANEL_MEMBER_IDS=("${PANEL_MEMBERS[@]}")
    fi

    if [[ "$PANEL_QUORUM" != "all" ]]; then
        [[ "$PANEL_QUORUM" =~ ^[1-9][0-9]*$ ]] \
            || die "panel quorum must be 'all' or a positive integer"
        (( PANEL_QUORUM <= PANEL_COUNT )) \
            || die "panel quorum ${PANEL_QUORUM} exceeds member count ${PANEL_COUNT}"
    fi

    PANEL_MEMBER_WRITE_SCOPE="${PANEL_MEMBER_WRITE_SCOPE:-[]}"
    if [[ "$PANEL_MEMBER_WRITE_SCOPE" =~ departments/.*/outbox \
        || "$PANEL_MEMBER_WRITE_SCOPE" =~ _state/failover/staging ]]; then
        die "panel member write scope may not include outbox or failover staging: ${PANEL_MEMBER_WRITE_SCOPE}"
    fi

    for member in "${PANEL_MEMBERS[@]}"; do
        if ! {
            find "$VAULT_ROOT/departments" -path "*/specialists/${member}.md" -type f -print -quit
            find "$VAULT_ROOT/shared/specialists" -maxdepth 1 -name "${member}.md" -type f -print -quit 2>/dev/null
        } | grep -q .; then
            die "unknown panel member '${member}'"
        fi
        validate_native_adapter "$TO_MODEL" "$member"
    done

    PANEL_MEMBERS_CSV="$(IFS=,; echo "${PANEL_MEMBERS[*]}")"
    PANEL_MEMBERS_YAML="[$(IFS=', '; echo "${PANEL_MEMBERS[*]}")]"
    PANEL_MEMBER_IDS_CSV="$(IFS=,; echo "${PANEL_MEMBER_IDS[*]}")"
    PANEL_MEMBER_IDS_YAML="[$(IFS=', '; echo "${PANEL_MEMBER_IDS[*]}")]"
fi

if [[ "$SPECIALIST" != "none" ]]; then
    if ! {
        find "$VAULT_ROOT/departments" -path "*/specialists/${SPECIALIST}.md" -type f -print -quit
        find "$VAULT_ROOT/shared/specialists" -maxdepth 1 -name "${SPECIALIST}.md" -type f -print -quit 2>/dev/null
    } | grep -q .; then
        die "unknown specialist '${SPECIALIST}'. Use chrono/SPECIALIST-INDEX.md and canonical markdown names."
    fi

    # New 28-col schema (2026-07-13): source_namespace=2 safety_level=4 primary_lane=7
    MAP_MODEL="$(map_field "$SPECIALIST" 7 || true)"
    [[ "$MAP_MODEL" == "codex" ]] && MAP_MODEL="gpt-codex"
    MAP_BACKUP="$(map_field "$SPECIALIST" 9 || true)"
    [[ "$MAP_BACKUP" == "codex" ]] && MAP_BACKUP="gpt-codex"
    [[ -n "$MAP_BACKUP" ]] || MAP_BACKUP="none"
    MAP_OPERATOR_GATE="$(map_field "$SPECIALIST" 21 || true)"
    [[ -n "$MAP_OPERATOR_GATE" ]] || MAP_OPERATOR_GATE="[]"
    MAP_NAMESPACE="$(map_field "$SPECIALIST" 2 || true)"
    MAP_SAFETY="$(map_field "$SPECIALIST" 4 || true)"

    [[ -z "$MAP_MODEL" ]] && die "specialist '${SPECIALIST}' is missing from shared/specialist-runtime-map.tsv"

    if [[ "$TO_MODEL" != "$MAP_MODEL" ]]; then
        if [[ -z "$MODEL_OVERRIDE_REASON" ]]; then
            die "unsafe model override for '${SPECIALIST}': to_model=${TO_MODEL}, map=${MAP_MODEL}. Add model_override_reason."
        fi
    fi
    # A sanctioned override may intentionally target the mapped backup. There
    # is then no distinct cross-family hop left, so degrade to backup:none.
    [[ "$TO_MODEL" == "$MAP_BACKUP" ]] && MAP_BACKUP="none"
    if [[ "$SOURCE_NAMESPACE" != "$MAP_NAMESPACE" && "$MAP_NAMESPACE" != "shared" ]]; then
        die "source_namespace '${SOURCE_NAMESPACE}' does not match model map (${MAP_NAMESPACE})"
    fi
    if [[ "$MANDATORY_REVIEW" == "true" && "$REVIEW_MODEL" == "none" ]]; then
        die "mandatory_review:true requires review_model"
    fi
    if [[ "$MAP_SAFETY" == "high" && "$MANDATORY_REVIEW" != "true" ]]; then
        die "high-safety specialist '${SPECIALIST}' requires mandatory_review:true"
    fi
    # Non-blocking heads-up: a genuine cross-family mandatory_review task will NOT
    # auto-settle to complete until a separate reviewer-lane response lands
    # (enforced by scripts/python/registry_reconciler.py). gpt-codex->claude runs
    # in-lane, so it is exempt; every other cross-lane pair needs the follow-up.
    if [[ "$MANDATORY_REVIEW" == "true" && "$REVIEW_MODEL" != "none" \
        && "$MAP_MODEL" != "$REVIEW_MODEL" \
        && ! ( "$MAP_MODEL" == "gpt-codex" && "$REVIEW_MODEL" == "claude" ) ]]; then
        info "cross-family review required: ${SPECIALIST} (${MAP_MODEL}) will stay review-required until a ${REVIEW_MODEL} review response lands."
    fi
fi

validate_native_adapter "$TO_MODEL" "$SPECIALIST"
validate_task_capabilities "$TASK_FILE" || die "task references unavailable or unverified live capability"

DEPARTMENTS_ROOT="${VAULT_ROOT}/departments"
MAILBOX_ROOT="${DEPARTMENTS_ROOT}/${COMPAT_NAMESPACE}"
INBOX="${MAILBOX_ROOT}/inbox"

# Basic path hardening must happen before mailbox creation: otherwise a malformed
# compatibility namespace or an existing symlinked component could redirect the
# mkdir itself. VAULT_ROOT may have a benign symlinked prefix (macOS /tmp ->
# /private/tmp), so resolve the configured root and reject symlinks only inside
# the squad-owned mailbox hierarchy.
VAULT_PHYS="$(cd "$VAULT_ROOT" 2>/dev/null && pwd -P)" || VAULT_PHYS=""
[[ -n "$VAULT_PHYS" ]] || die "cannot resolve VAULT_ROOT: ${VAULT_ROOT}"
for MAILBOX_COMPONENT in \
    "$DEPARTMENTS_ROOT" "$MAILBOX_ROOT" \
    "$INBOX" "${MAILBOX_ROOT}/active" "${MAILBOX_ROOT}/outbox" "${MAILBOX_ROOT}/archive"; do
    [[ ! -L "$MAILBOX_COMPONENT" ]] \
        || die "refusing to create or publish through a symlinked mailbox path component: ${MAILBOX_COMPONENT}"
done

mkdir -p "$INBOX" "${MAILBOX_ROOT}/active" "${MAILBOX_ROOT}/outbox" "${MAILBOX_ROOT}/archive"
INBOX_PHYS="$(cd "$INBOX" 2>/dev/null && pwd -P)" || INBOX_PHYS=""
EXPECTED_INBOX="${VAULT_PHYS}/departments/${COMPAT_NAMESPACE}/inbox"
[[ -n "$INBOX_PHYS" && "$INBOX_PHYS" == "$EXPECTED_INBOX" ]] \
    || die "refusing to use mailbox outside the expected physical directory under VAULT_ROOT: ${INBOX}"

echo "Dispatching ${TASK_ID} → ${TO_MODEL}/${SPECIALIST}"
echo "  Model lane: ${TO_MODEL}  Specialist: ${SPECIALIST}  Source namespace: ${SOURCE_NAMESPACE}"

if $DRY_RUN; then
    echo "[DRY RUN] Would validate, inject toolkit, copy to inbox, update registry"
    echo "[DRY RUN] per_task_versioning=${PER_TASK_VERSIONING:-false}"
    echo "[DRY RUN] write_scope=${WRITE_SCOPE_RAW:-[]}"
    if $PANEL_ENABLED; then
        PANEL_MODE="review"
        $FANOUT_ENABLED && PANEL_MODE="fanout"
        echo "[DRY RUN] dispatch_kind=panel mode=${PANEL_MODE} members=${PANEL_MEMBERS_CSV} member_ids=${PANEL_MEMBER_IDS_CSV} policy=${PANEL_POLICY} quorum=${PANEL_QUORUM} timeout=${PANEL_TIMEOUT_SECONDS} assignments=${#PANEL_ASSIGNMENTS[@]}"
    fi
    exit 2
fi

# ── ITEM 5: write_scope conflict detection ────────────────────────────────────
# Parse write_scope (YAML inline list or empty). Scan active-tasks.json for
# any in-flight task claiming an overlapping path. Refuse dispatch on conflict.
# Brief authors who leave write_scope: [] skip conflict check (no scope declared).

if [[ -f "$ACTIVE_REGISTRY" ]]; then
    info "Reconciling active-task registry with landed responses..."
    "${VAULT_ROOT}/bin/registry-reconciler.sh" \
        || echo "WARNING: Active-task registry reconciliation failed (non-blocking)" >&2
fi

if [[ -n "$WRITE_SCOPE_RAW" && "$WRITE_SCOPE_RAW" != "[]" && -f "$ACTIVE_REGISTRY" ]]; then
    info "Checking write_scope for conflicts..."
    if ! CONFLICT_RESULT=$(python3 - <<PYEOF
import json, sys, re

with open("${ACTIVE_REGISTRY}") as f:
    registry = json.load(f)

# Parse YAML inline list from frontmatter value
scope_raw = """${WRITE_SCOPE_RAW}"""
scope_paths = [s.strip().strip('"').strip("'")
               for s in re.sub(r'[\[\]]', '', scope_raw).split(',')
               if s.strip()]

conflicts = []
for active_id, active in registry.items():
    if active.get("status") != "in-flight":
        continue
    for active_scope in active.get("write_scope", []):
        for new_scope in scope_paths:
            if (new_scope == active_scope
                    or new_scope.startswith(active_scope.rstrip("/") + "/")
                    or active_scope.startswith(new_scope.rstrip("/") + "/")):
                conflicts.append(f"{new_scope} overlaps {active_id} scope {active_scope}")

if conflicts:
    print("CONFLICT: " + "; ".join(conflicts))
    sys.exit(1)
print("CLEAR")
sys.exit(0)
PYEOF
    ); then
        die "write_scope blocked: ${CONFLICT_RESULT}. Resolve in-flight tasks first or adjust scope."
    fi

    if [[ "$CONFLICT_RESULT" != "CLEAR" ]]; then
        die "write_scope blocked: ${CONFLICT_RESULT}. Resolve in-flight tasks first or adjust scope."
    fi
    info "write_scope: no conflicts"
fi

# ── ITEM 4: inject toolkit + no-delete rule ───────────────────────────────────
# shared/dispatch-toolkit.sh emits per-namespace tool/specialist roster AND the
# hard no-delete rule block. Append to a working copy of the task file.

WORKING_COPY=$(mktemp "${TASK_FILE%.md}.XXXXXX.md")
if $PANEL_ENABLED; then
    PANEL_MODE="review"
    $FANOUT_ENABLED && PANEL_MODE="fanout"
    awk \
        -v panel_id="PANEL-${TASK_ID#TASK-}" \
        -v members="$PANEL_MEMBERS_YAML" \
        -v member_ids="$PANEL_MEMBER_IDS_YAML" \
        -v panel_mode="$PANEL_MODE" \
        -v policy="$PANEL_POLICY" \
        -v quorum="$PANEL_QUORUM" \
        -v timeout="$PANEL_TIMEOUT_SECONDS" \
        -v member_scope="$PANEL_MEMBER_WRITE_SCOPE" '
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && /^panel_member_write_scope:/ { next }
        in_frontmatter && $0 == "---" && !inserted {
            print "dispatch_kind: panel"
            print "panel_id: " panel_id
            print "panel_mode: " panel_mode
            print "panel_members: " members
            print "panel_member_ids: " member_ids
            print "panel_policy: " policy
            print "panel_quorum: " quorum
            print "panel_timeout_seconds: " timeout
            print "panel_max_parallel: 3"
            print "panel_return_contract: lane-native-v1"
            print "panel_member_write_scope: " member_scope
            print
            inserted=1
            in_frontmatter=0
            next
        }
        { print }
        END { if (!inserted) exit 42 }
    ' "$TASK_FILE" > "$WORKING_COPY" \
        || die "failed to inject panel-v1 frontmatter"

    {
        cat <<'PANEL_EOF'

## Panel-v1 coordinator instructions

This is an opt-in panel dispatch governed by `shared/modes/panel.md`.

1. Validate every named member and create `_state/runtime/lane-activity/<task-id>.json` with `bin/panel-activity.sh create` before spawning; add `--fanout` when `panel_mode: fanout`. Review-panel member IDs are specialist names; fan-out member IDs are the injected `member-N` values and MUST be used for activity updates and result attribution.
2. Spawn all members in parallel, never serially. Reserve the coordinator as the fourth thread.
3. Members may use only the packet's read/write scope and MUST NEVER write `departments/*/outbox/` or `_state/failover/staging/`.
4. Claude requires coordinator-pull plus deterministic `_state/scratch/<task-id>/<member-id>.md` file return. Codex uses native parent-message return primarily; a scratch file is optional for oversized results.
5. Normalize only returns already available to the coordinator; never make a blocking receive. Update activity state on spawn, return, failure, refusal, and timeout.
6. Run the mandatory bounded collection loop from `shared/modes/panel.md`: drain immediately available returns, then call `timeout 5 bin/panel-activity.sh poll --task-id <id> --quorum <panel_quorum> --timeout <panel_timeout_seconds>` exactly once per iteration. For `outcome: waiting`, use only a bounded short sleep (`timeout 2 sleep 1`) before repeating. Stop immediately on `quorum_met` or `timed_out`. The first poll persists a monotonic deadline; deadline expiry atomically marks every queued/running member `timed_out`. Numeric quorum closure also atomically marks any remaining queued/running members `timed_out` as explicit gaps. Guard the complete shell-side collection phase with `timeout` no greater than `panel_timeout_seconds + 15`, and guard every potentially blocking step with at most two minutes. A late, failed, refused, or timed-out member is a coverage gap and never blocks the outbox.
7. Aggregate by deterministic collation followed by evidence synthesis. Preserve attribution, unique findings, contradictions, refusals, failures, and limitations. Never majority-vote or fake unanimity.
8. The coordinator alone writes exactly one canonical outbox. Close/archive the activity record in a finally path. One parent task remains one failover attempt and one artifact.

### Required member-result schema

```yaml
member_id: <specialist-name or member-N>
specialist: <canonical-name>
status: completed # completed | failed | refused | timed_out
summary: <bounded summary>
claims:
  - finding: <claim>
    severity: <critical|high|medium|low|info|none>
    evidence: [<source reference>]
    confidence: <high|medium|low>
disagreements: []
tools_used: []
artifacts: []
limitations: []
```

### Panel assignments
PANEL_EOF
        for (( member_index=0; member_index<PANEL_COUNT; member_index++ )); do
            member="${PANEL_MEMBERS[$member_index]}"
            member_id="${PANEL_MEMBER_IDS[$member_index]}"
            # shellcheck disable=SC2016  # backticks are intentional literal markdown in the output
            if $FANOUT_ENABLED; then
                printf '\n#### %s (%s)\n\nAssignment: %s\n\nApply the canonical `%s` specialist brief only to this assignment. Return only the required member-result schema to the coordinator, with `member_id: %s`.\n' "$member_id" "$member" "${PANEL_ASSIGNMENTS[$member_index]}" "$member" "$member_id"
            else
                printf '\n#### %s\n\nApply the canonical `%s` specialist brief to the parent objective. Return only the required member-result schema to the coordinator, with `member_id: %s`.\n' "$member" "$member" "$member_id"
            fi
        done
    } >> "$WORKING_COPY"
else
    cp "$TASK_FILE" "$WORKING_COPY"
fi

if [[ -x "$TOOLKIT" ]]; then
    bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$TO_MODEL" >> "$WORKING_COPY"
    info "Toolkit injected for ${COMPAT_NAMESPACE}/${TO_MODEL}"
fi

# ── ITEM 3: per-task version dirs ─────────────────────────────────────────────
# If per_task_versioning: true, rewrite return_artifact path to embed TASK-ID
# as a subdirectory. Prevents output collisions across SUPP dispatches.

ACTUAL_TASK_FILE="$WORKING_COPY"
if [[ "$PER_TASK_VERSIONING" == "true" ]]; then
    if [[ -n "$RETURN_ARTIFACT" ]]; then
        ART_DIR=$(dirname "$RETURN_ARTIFACT")
        ART_FILE=$(basename "$RETURN_ARTIFACT")
        NEW_ART="${ART_DIR}/${TASK_ID}/${ART_FILE}"
        VERSIONED_COPY=$(mktemp "${TASK_FILE%.md}.versioned.XXXXXX.md")
        sed "s|return_artifact:.*|return_artifact: ${NEW_ART}|" "$WORKING_COPY" > "$VERSIONED_COPY"
        ACTUAL_TASK_FILE="$VERSIONED_COPY"
        RETURN_ARTIFACT="$NEW_ART"
        info "Per-task versioning: return_artifact → ${NEW_ART}"
    fi
fi

# ── conservative failover control ────────────────────────────────────────────
# The packet given to a lane names an attempt-specific staging artifact.  The
# durable ledger retains the canonical path, and only failover-control may CAS
# publish it.  This removes direct multi-lane writes to the shared outbox path.

# GATED (F1, 2026-07-13 Fable review): the conservative failover control plane is
# OPT-IN and defaults OFF pending mandatory re-review and a controlled activation
# (watcher restart + canary). Flag OFF = legacy behavior: canonical
# return_artifact, no ledger, direct outbox — the proven rail. Enable with
# FAILOVER_CONTROL_ENABLED=1 or by creating _state/failover/ENABLED.
CONTROL_ACTIVE=0
CONTROL_ATTEMPT_ID=""
if [[ "${FAILOVER_CONTROL_ENABLED:-0}" == "1" || -f "${VAULT_ROOT}/_state/failover/ENABLED" ]]; then
    [[ -f "$FAILOVER_CONTROL" ]] || die "missing conservative failover controller: ${FAILOVER_CONTROL}"
    command -v uv >/dev/null 2>&1 || die "uv is required by the conservative failover controller"
    CONTROL_RUN=(uv run --with-requirements "$DAEMON_REQUIREMENTS" python "$FAILOVER_CONTROL")
    CONTROL_ARGS=(
        init-dispatch
        --task-file "$ACTUAL_TASK_FILE"
        --primary-lane "$TO_MODEL"
        --backup-lane "$MAP_BACKUP"
        --lease-owner "dispatch:${TO_MODEL}:$$"
        --effective-model "$TO_MODEL"
        --redispatch-path "${INBOX}/${TASK_ID}.md"
    )
    # Gate authority is durable ledger state, never a publish-call choice.
    # Explicit packet frontmatter is also consumed by failover-control.py.
    if [[ "$SPECIALIST" == "content-verifier" \
        || "$SPECIALIST" == "asset-provenance-and-rights-auditor" \
        || ( "$MAP_SAFETY" == "high" && "$MAP_OPERATOR_GATE" =~ (public_release|paid_media) ) ]]; then
        CONTROL_ARGS+=(--gate-required)
    fi
    CONTROL_RESULT="$("${CONTROL_RUN[@]}" "${CONTROL_ARGS[@]}")" \
        || die "failed to initialize durable attempt ledger for ${TASK_ID}"
    CONTROL_ATTEMPT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("attempt_id", ""))' <<<"$CONTROL_RESULT")"
    [[ -n "$CONTROL_ATTEMPT_ID" ]] && CONTROL_ACTIVE=1
    info "Attempt ledger initialized: ${CONTROL_RESULT}"
fi

# ── copy to source namespace inbox ────────────────────────────────────────────

DEST="${INBOX}/${TASK_ID}.md"
# Re-check immediately before publish so accidental mailbox drift fails closed.
# This is pathname hardening for the trusted single-user squad filesystem, not an
# atomic defense against a concurrent local process replacing directories between
# this check and mktemp; shared/protocol.md documents that explicit boundary.
INBOX_PHYS="$(cd "$INBOX" 2>/dev/null && pwd -P)" || INBOX_PHYS=""
EXPECTED_INBOX="${VAULT_PHYS}/departments/${COMPAT_NAMESPACE}/inbox"
[[ -n "$VAULT_PHYS" && -n "$INBOX_PHYS" && "$INBOX_PHYS" == "$EXPECTED_INBOX" ]] \
    || die "refusing to publish: inbox is not the expected physical directory under VAULT_ROOT: ${INBOX}"
if [[ -L "$INBOX" || -L "$MAILBOX_ROOT" ]]; then
    die "refusing to publish through a symlinked mailbox path component: ${INBOX}"
fi
INBOX_TEMP=""
if ! INBOX_TEMP=$(mktemp "${INBOX}/.${TASK_ID}.tmp.XXXXXX") \
    || ! cp "$ACTUAL_TASK_FILE" "$INBOX_TEMP" \
    || ! python3 - "$INBOX_TEMP" <<'PYEOF'
import os
import sys

with open(sys.argv[1], "rb") as inbox_temp:
    os.fsync(inbox_temp.fileno())
PYEOF
then
    if [[ "$CONTROL_ACTIVE" == "1" ]]; then
        "${CONTROL_RUN[@]}" signal \
            --task-id "$TASK_ID" \
            --attempt-id "$CONTROL_ATTEMPT_ID" \
            --signal dispatch_ack_failure >/dev/null \
            || echo "WARNING: failed to record inbox delivery failure for ${TASK_ID}" >&2
    fi
    die "failed to deliver ${TASK_ID} to ${INBOX}"
fi
if ! mv -f "$INBOX_TEMP" "$DEST"; then
    if [[ "$CONTROL_ACTIVE" == "1" ]]; then
        "${CONTROL_RUN[@]}" signal \
            --task-id "$TASK_ID" \
            --attempt-id "$CONTROL_ATTEMPT_ID" \
            --signal dispatch_ack_failure >/dev/null \
            || echo "WARNING: failed to record inbox delivery failure for ${TASK_ID}" >&2
    fi
    die "failed to deliver ${TASK_ID} to ${INBOX}"
fi
rm -f "$WORKING_COPY"
[[ "$ACTUAL_TASK_FILE" != "$WORKING_COPY" ]] && rm -f "$ACTUAL_TASK_FILE"
info "Copied to ${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"

if [[ "$CONTROL_ACTIVE" == "1" ]]; then
    "${CONTROL_RUN[@]}" event \
        --task-id "$TASK_ID" \
        --attempt-id "$CONTROL_ATTEMPT_ID" \
        --event inbox_delivered \
        --detail "$DEST" >/dev/null \
        || die "inbox delivery succeeded but could not be recorded for ${TASK_ID}"
    if [[ -z "$NUDGE_PANE" ]]; then
        "${CONTROL_RUN[@]}" event \
            --task-id "$TASK_ID" \
            --attempt-id "$CONTROL_ATTEMPT_ID" \
            --event dispatch_nudge_unavailable \
            --detail "${NUDGE_UNAVAILABLE_REASON:-not-requested}" >/dev/null \
            || die "failed to record deferred inbox pickup for ${TASK_ID}"
    fi
fi

# ── ITEM 7: active-task registry ─────────────────────────────────────────────
# Build the entry here, then register it through the shared reconciler so entry
# creation and response reconciliation use the same flock + atomic rename.

if REGISTRY_ENTRY_JSON="$(RETURN_ARTIFACT_VALUE="$RETURN_ARTIFACT" python3 - <<PYEOF
import json, os, re
from datetime import datetime, timezone

scope_raw = """${WRITE_SCOPE_RAW}"""
scope = [s.strip().strip('"').strip("'")
         for s in re.sub(r'[\[\]]', '', scope_raw).split(',')
         if s.strip()]

entry = {
    "compatibility_namespace": "${COMPAT_NAMESPACE}",
    "specialist": "${SPECIALIST}",
    "to_model": "${TO_MODEL}",
    "source_namespace": "${SOURCE_NAMESPACE}",
    "review_model": "${REVIEW_MODEL}",
    "mandatory_review": "${MANDATORY_REVIEW}",
    "parallel_safe": "${PARALLEL_SAFE}",
    "direct_lane_work_allowed": "${DIRECT_LANE_WORK_ALLOWED}",
    "dispatched_at": datetime.now(timezone.utc).isoformat(),
    "return_artifact": os.environ.get("RETURN_ARTIFACT_VALUE", ""),
    "write_scope": scope,
    "status": "in-flight",
    "dispatch_kind": "panel" if "${PANEL_ENABLED}" == "true" else "single",
    "panel_members": [m for m in "${PANEL_MEMBERS_CSV}".split(",") if m],
    "panel_member_ids": [m for m in "${PANEL_MEMBER_IDS_CSV}".split(",") if m],
    "panel_mode": ("fanout" if "${FANOUT_ENABLED}" == "true" else "review") if "${PANEL_ENABLED}" == "true" else "single",
}
print(json.dumps(entry, separators=(",", ":")))
PYEOF
)" && "${VAULT_ROOT}/bin/registry-reconciler.sh" \
    --register-task "$TASK_ID" --entry-json "$REGISTRY_ENTRY_JSON"; then
    info "Active-task registry updated under shared lock"
else
    echo "WARNING: Active-task registry update failed (non-blocking)" >&2
fi

# ── central dispatch log ─────────────────────────────────────────────────────

DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
mkdir -p "$(dirname "${DISPATCH_LOG}")"
printf '{"ts":"%s","task_id":"%s","model_lane":"%s","source_namespace":"%s","compatibility_namespace":"%s","specialist":"%s","review_model":"%s","mandatory_review":"%s","return_artifact":"%s"}\n' \
    "$(date -u +%FT%TZ)" "${TASK_ID}" "${TO_MODEL}" "${SOURCE_NAMESPACE}" "${COMPAT_NAMESPACE}" "${SPECIALIST}" "${REVIEW_MODEL}" "${MANDATORY_REVIEW}" \
    "${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md" \
    >> "${DISPATCH_LOG}"
info "Dispatch log updated"

# ── nudge model lane pane ─────────────────────────────────────────────────────

if [[ -n "$NUDGE_PANE" ]]; then
    if env VAULT_ROOT="$VAULT_ROOT" bash "${VAULT_ROOT}/bin/nudge-task.sh" "$DEST"; then
        info "Nudged pane ${NUDGE_PANE}"
    else
        if [[ "$CONTROL_ACTIVE" == "1" ]]; then
            "${CONTROL_RUN[@]}" event \
                --task-id "$TASK_ID" \
                --attempt-id "$CONTROL_ATTEMPT_ID" \
                --event dispatch_nudge_failed \
                --detail "$NUDGE_PANE" >/dev/null \
                || die "failed to record dispatch nudge failure for ${TASK_ID}"
        fi
        echo "WARNING: Failed to nudge pane ${NUDGE_PANE}; inbox watcher pickup remains authoritative" >&2
    fi
fi

echo "✓ Dispatched ${TASK_ID} → ${TO_MODEL}/${SPECIALIST} (${COMPAT_NAMESPACE} mailbox)"
