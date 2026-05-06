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
    "brave_search": "chrono-research-arsenal currently exposes arxiv_search,xai_search,perplexity_search_web only",
    "serper_search": "chrono-research-arsenal currently exposes arxiv_search,xai_search,perplexity_search_web only",
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
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --nudge-pane) NUDGE_PANE="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        *)            TASK_FILE="$1"; shift ;;
    esac
done

[[ -z "$TASK_FILE" ]] && die "Usage: $0 <task-file> [--nudge-pane <target>] [--dry-run]"
[[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

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

if [[ "$SPECIALIST" != "none" ]]; then
    if ! {
        find "$VAULT_ROOT/departments" -path "*/specialists/${SPECIALIST}.md" -type f -print -quit
        find "$VAULT_ROOT/shared/specialists" -maxdepth 1 -name "${SPECIALIST}.md" -type f -print -quit 2>/dev/null
    } | grep -q .; then
        die "unknown specialist '${SPECIALIST}'. Use chrono/SPECIALIST-INDEX.md and canonical markdown names."
    fi

    MAP_MODEL="$(map_field "$SPECIALIST" 2 || true)"
    MAP_NAMESPACE="$(map_field "$SPECIALIST" 4 || true)"
    MAP_SAFETY="$(map_field "$SPECIALIST" 6 || true)"

    [[ -z "$MAP_MODEL" ]] && die "specialist '${SPECIALIST}' is missing from shared/specialist-runtime-map.tsv"

    if [[ "$TO_MODEL" != "$MAP_MODEL" ]]; then
        if [[ -z "$MODEL_OVERRIDE_REASON" ]]; then
            die "unsafe model override for '${SPECIALIST}': to_model=${TO_MODEL}, map=${MAP_MODEL}. Add model_override_reason."
        fi
    fi
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
cp "$TASK_FILE" "$WORKING_COPY"

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

# ── copy to source namespace inbox ────────────────────────────────────────────

DEST="${INBOX}/${TASK_ID}.md"
cp "$ACTUAL_TASK_FILE" "$DEST"
rm -f "$WORKING_COPY"
[[ "$ACTUAL_TASK_FILE" != "$WORKING_COPY" ]] && rm -f "$ACTUAL_TASK_FILE"
info "Copied to ${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"

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
    env VAULT_ROOT="$VAULT_ROOT" bash "${VAULT_ROOT}/bin/nudge-task.sh" "$DEST" \
        && info "Nudged pane ${NUDGE_PANE}" \
        || echo "WARNING: Failed to nudge pane ${NUDGE_PANE} (dispatch already recorded)" >&2
fi

echo "✓ Dispatched ${TASK_ID} → ${TO_MODEL}/${SPECIALIST} (${COMPAT_NAMESPACE} mailbox)"
