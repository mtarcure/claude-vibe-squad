#!/bin/bash
# bin/send-task.sh — Dispatch a TASK file to a source namespace inbox.
#
# Spec 1.5 safety features baked in:
#   Item 1: auto-git-snapshot before dispatch
#   Item 3: per-task version dirs (opt-in via per_task_versioning: true)
#   Item 4: no-delete rule injection (via shared/dispatch-toolkit.sh)
#   Item 5: write_scope conflict detection against active-tasks.json
#   Item 7: active-task registry update (_state/active-tasks.json)
#
# Usage:
#   bin/send-task.sh <task-file> [--nudge-pane <tmux-target>] [--dry-run]
#       [--panel a,b,c] [--panel-policy evidence-synthesis]
#       [--panel-quorum all|N] [--panel-timeout SECONDS]
#   bin/send-task.sh --close-task <TASK-ID>
#
# Required frontmatter in task file:
#   id: TASK-YYYY-MM-DD-HHMM-<hash>
#   to_model: gpt-codex | claude | gemini | kimi
#   specialist: <canonical specialist>
#   source_namespace: coding | security | content | sysmgmt | research | shared
#
# Optional frontmatter:
#   write_scope: [path1, path2]     — conflict-checked against active tasks
#   per_task_versioning: true       — rewrites return_artifact to include TASK-ID subdir
#
# Exit codes:
#   0  — dispatched successfully
#   1  — blocked (scope conflict, snapshot failure, missing fields)
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
            adapter="${VAULT_ROOT}/model-lanes/kimi/subagents/${specialist}.yaml"
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

# ── sub-command: close task on response landing ───────────────────────────────
# Called by response-landing hook when a lane writes TASK-*-response.md.

if [[ "${1:-}" == "--close-task" ]]; then
    CLOSE_ID="${2:-}"
    [[ -z "$CLOSE_ID" ]] && die "Usage: $0 --close-task <TASK-ID>"
    python3 - <<PYEOF
import json, os
from datetime import datetime, timezone
from pathlib import Path

registry_path = Path("${ACTIVE_REGISTRY}")
if not registry_path.exists():
    raise SystemExit(0)

try:
    registry = json.loads(registry_path.read_text())
except json.JSONDecodeError:
    raise SystemExit("ERROR: active-task registry is not valid JSON")

if "${CLOSE_ID}" in registry:
    registry["${CLOSE_ID}"]["status"] = "complete"
    registry["${CLOSE_ID}"]["completed_at"] = datetime.now(timezone.utc).isoformat()
    tmp = str(registry_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=2)
    os.rename(tmp, str(registry_path))
    print(f"Closed ${CLOSE_ID} in active-task registry")
PYEOF
    exit $?
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --nudge-pane) NUDGE_PANE="$2"; shift 2 ;;
        --nudge-unavailable) NUDGE_UNAVAILABLE_REASON="$2"; shift 2 ;;
        --panel) PANEL_ENABLED=true; PANEL_MEMBERS_RAW="$2"; shift 2 ;;
        --panel-policy) PANEL_POLICY="$2"; shift 2 ;;
        --panel-quorum) PANEL_QUORUM="$2"; shift 2 ;;
        --panel-timeout) PANEL_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        *)            TASK_FILE="$1"; shift ;;
    esac
done

[[ -z "$TASK_FILE" ]] && die "Usage: $0 <task-file> [--nudge-pane <target>] [--dry-run] [--panel a,b,c] [--panel-policy evidence-synthesis] [--panel-quorum all|N] [--panel-timeout SECONDS]"
[[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

if ! $PANEL_ENABLED; then
    [[ "$PANEL_POLICY" == "evidence-synthesis" ]] || die "--panel-policy requires --panel"
    [[ "$PANEL_QUORUM" == "all" ]] || die "--panel-quorum requires --panel"
    [[ "$PANEL_TIMEOUT_SECONDS" == "900" ]] || die "--panel-timeout requires --panel"
fi

# ── read task metadata ────────────────────────────────────────────────────────

TASK_ID=$(frontmatter_field "$TASK_FILE" "id")
TO_LEAD=$(frontmatter_field "$TASK_FILE" "to_lead")
COMPAT_NAMESPACE=$(frontmatter_field "$TASK_FILE" "compatibility_namespace")
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
MAP_BACKUP="none"
MAP_OPERATOR_GATE="[]"
MAP_SAFETY=""

[[ -z "$TASK_ID" ]]  && die "Task file missing 'id' frontmatter: $TASK_FILE"
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
    coding|security|content|sysmgmt|research|shared|chrono) ;;
    *) die "invalid source_namespace '${SOURCE_NAMESPACE}'." ;;
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
                [[ "$existing_member" != "$member" ]] \
                    || die "duplicate panel member '${member}'"
            done
        fi
        PANEL_MEMBERS[PANEL_COUNT]="$member"
        PANEL_COUNT=$((PANEL_COUNT + 1))
    done
    (( PANEL_COUNT >= 2 && PANEL_COUNT <= 3 )) \
        || die "panel-v1 requires 2-3 members (3 members + coordinator = 4-thread cap), got ${PANEL_COUNT}"

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
fi

validate_native_adapter "$TO_MODEL" "$SPECIALIST"
validate_task_capabilities "$TASK_FILE" || die "task references unavailable or unverified live capability"

MAILBOX_ROOT="${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}"
mkdir -p "${MAILBOX_ROOT}/inbox" "${MAILBOX_ROOT}/active" "${MAILBOX_ROOT}/outbox" "${MAILBOX_ROOT}/archive"
INBOX="${MAILBOX_ROOT}/inbox"

echo "Dispatching ${TASK_ID} → ${TO_MODEL}/${SPECIALIST}"
echo "  Model lane: ${TO_MODEL}  Specialist: ${SPECIALIST}  Source namespace: ${SOURCE_NAMESPACE}"

if $DRY_RUN; then
    echo "[DRY RUN] Would snapshot, inject toolkit, copy to inbox, update registry"
    echo "[DRY RUN] per_task_versioning=${PER_TASK_VERSIONING:-false}"
    echo "[DRY RUN] write_scope=${WRITE_SCOPE_RAW:-[]}"
    if $PANEL_ENABLED; then
        echo "[DRY RUN] dispatch_kind=panel members=${PANEL_MEMBERS_CSV} policy=${PANEL_POLICY} quorum=${PANEL_QUORUM} timeout=${PANEL_TIMEOUT_SECONDS}"
    fi
    exit 2
fi

# ── ITEM 1: auto-git-snapshot ─────────────────────────────────────────────────
# Commit the current tree before any dispatch. --allow-empty fires even when
# tree is clean (re-dispatch, already-staged changes). Failures abort dispatch
# so an unrecoverable state is never dispatched.

info "Auto-snapshot: before dispatch"
(
    cd "${VAULT_ROOT}"
    git add -A
    if [[ -n "${RUN_ID}" && "${RUN_ID}" != "none" ]]; then
        git commit -m "auto-snapshot: before ${TASK_ID} dispatch for ${RUN_ID}" --allow-empty -q
    else
        git commit -m "auto-snapshot: before ${TASK_ID} dispatch" --allow-empty -q
    fi
) || die "Git snapshot failed. Check repo state (locked index? detached HEAD?) before dispatching."

# ── ITEM 5: write_scope conflict detection ────────────────────────────────────
# Parse write_scope (YAML inline list or empty). Scan active-tasks.json for
# any in-flight task claiming an overlapping path. Refuse dispatch on conflict.
# Brief authors who leave write_scope: [] skip conflict check (no scope declared).

if [[ -f "$ACTIVE_REGISTRY" ]]; then
    info "Reconciling active-task registry with landed responses..."
    python3 - <<PYEOF || echo "WARNING: Active-task registry reconciliation failed (non-blocking)" >&2
import json, os
from datetime import datetime, timezone
from pathlib import Path

vault = Path("${VAULT_ROOT}")
registry_path = Path("${ACTIVE_REGISTRY}")

try:
    registry = json.loads(registry_path.read_text())
except json.JSONDecodeError:
    raise SystemExit(1)

changed = False
for task_id, entry in registry.items():
    if entry.get("status") != "in-flight":
        continue
    namespace = entry.get("compatibility_namespace") or entry.get("source_namespace") or entry.get("to_lead")
    if not namespace:
        continue
    response = vault / "departments" / namespace / "outbox" / f"{task_id}-response.md"
    if response.exists():
        entry["status"] = "complete"
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        changed = True

if changed:
    tmp = str(registry_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=2)
    os.rename(tmp, str(registry_path))
PYEOF
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
    awk \
        -v panel_id="PANEL-${TASK_ID#TASK-}" \
        -v members="$PANEL_MEMBERS_YAML" \
        -v policy="$PANEL_POLICY" \
        -v quorum="$PANEL_QUORUM" \
        -v timeout="$PANEL_TIMEOUT_SECONDS" \
        -v member_scope="$PANEL_MEMBER_WRITE_SCOPE" '
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && /^panel_member_write_scope:/ { next }
        in_frontmatter && $0 == "---" && !inserted {
            print "dispatch_kind: panel"
            print "panel_id: " panel_id
            print "panel_members: " members
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

1. Validate every named member and create `_state/runtime/lane-activity/<task-id>.json` with `bin/panel-activity.sh create` before spawning.
2. Spawn all members in parallel, never serially. Reserve the coordinator as the fourth thread.
3. Members may use only the packet's read/write scope and MUST NEVER write `departments/*/outbox/` or `_state/failover/staging/`.
4. Claude requires coordinator-pull plus deterministic `_state/scratch/<task-id>/<member>.md` file return. Codex uses native parent-message return primarily; a scratch file is optional for oversized results.
5. Normalize only returns already available to the coordinator; never make a blocking receive. Update activity state on spawn, return, failure, refusal, and timeout.
6. Run the mandatory bounded collection loop from `shared/modes/panel.md`: drain immediately available returns, then call `timeout 5 bin/panel-activity.sh poll --task-id <id> --quorum <panel_quorum> --timeout <panel_timeout_seconds>` exactly once per iteration. For `outcome: waiting`, use only a bounded short sleep (`timeout 2 sleep 1`) before repeating. Stop immediately on `quorum_met` or `timed_out`. The first poll persists a monotonic deadline; deadline expiry atomically marks every queued/running member `timed_out`. Numeric quorum closure also atomically marks any remaining queued/running members `timed_out` as explicit gaps. Guard the complete shell-side collection phase with `timeout` no greater than `panel_timeout_seconds + 15`, and guard every potentially blocking step with at most two minutes. A late, failed, refused, or timed-out member is a coverage gap and never blocks the outbox.
7. Aggregate by deterministic collation followed by evidence synthesis. Preserve attribution, unique findings, contradictions, refusals, failures, and limitations. Never majority-vote or fake unanimity.
8. The coordinator alone writes exactly one canonical outbox. Close/archive the activity record in a finally path. One parent task remains one failover attempt and one artifact.

### Required member-result schema

```yaml
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
        for member in "${PANEL_MEMBERS[@]}"; do
            # shellcheck disable=SC2016  # backticks are intentional literal markdown in the output
            printf '\n#### %s\n\nApply the canonical `%s` specialist brief to the parent objective. Return only the required member-result schema to the coordinator.\n' "$member" "$member"
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
    RETURN_ART=$(frontmatter_field "$TASK_FILE" "return_artifact")
    if [[ -n "$RETURN_ART" ]]; then
        ART_DIR=$(dirname "$RETURN_ART")
        ART_FILE=$(basename "$RETURN_ART")
        NEW_ART="${ART_DIR}/${TASK_ID}/${ART_FILE}"
        VERSIONED_COPY=$(mktemp "${TASK_FILE%.md}.versioned.XXXXXX.md")
        sed "s|return_artifact:.*|return_artifact: ${NEW_ART}|" "$WORKING_COPY" > "$VERSIONED_COPY"
        ACTUAL_TASK_FILE="$VERSIONED_COPY"
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
if ! cp "$ACTUAL_TASK_FILE" "$DEST"; then
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
# Atomic write (temp+rename). Remove entry when this task's response lands —
# the response-landing hook calls: send-task.sh --close-task <TASK-ID>

python3 - <<PYEOF || echo "WARNING: Active-task registry update failed (non-blocking)"
import json, os, re
from datetime import datetime, timezone
from pathlib import Path

registry_path = Path("${ACTIVE_REGISTRY}")
try:
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
except json.JSONDecodeError:
    registry = {}

scope_raw = """${WRITE_SCOPE_RAW}"""
scope = [s.strip().strip('"').strip("'")
         for s in re.sub(r'[\[\]]', '', scope_raw).split(',')
         if s.strip()]

registry["${TASK_ID}"] = {
    "compatibility_namespace": "${COMPAT_NAMESPACE}",
    "specialist": "${SPECIALIST}",
    "to_model": "${TO_MODEL}",
    "source_namespace": "${SOURCE_NAMESPACE}",
    "review_model": "${REVIEW_MODEL}",
    "mandatory_review": "${MANDATORY_REVIEW}",
    "parallel_safe": "${PARALLEL_SAFE}",
    "direct_lane_work_allowed": "${DIRECT_LANE_WORK_ALLOWED}",
    "dispatched_at": datetime.now(timezone.utc).isoformat(),
    "write_scope": scope,
    "status": "in-flight",
    "dispatch_kind": "panel" if "${PANEL_ENABLED}" == "true" else "single",
    "panel_members": [m for m in "${PANEL_MEMBERS_CSV}".split(",") if m],
}

tmp = str(registry_path) + ".tmp"
with open(tmp, "w") as f:
    json.dump(registry, f, indent=2)
os.rename(tmp, str(registry_path))
PYEOF

info "Active-task registry updated"

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
