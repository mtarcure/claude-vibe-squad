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
#       [--swarm claude,gpt-codex,gemini,kimi] [--swarm-timeout SECONDS]
#       [--subswarm-directive PATH]
#       [--subswarm-assignment '<lane>:subNN=TEXT' ...]
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
CAPABILITY_DISPATCH="${VAULT_ROOT}/scripts/python/capability_dispatch.py"
VERIFICATION_CONTRACT_HELPER="${VAULT_ROOT}/scripts/python/verification_contract.py"

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

frontmatter_has_field() {
    local file="$1" field="$2"
    awk -v field="$field" '
        NR == 1 && $0 == "---" { in_frontmatter=1; next }
        in_frontmatter && $0 == "---" { exit(found ? 0 : 1) }
        in_frontmatter {
            key=$0
            sub(/:.*/, "", key)
            if (key == field) found=1
        }
        END { if (in_frontmatter) exit(found ? 0 : 1) }
    ' "$file"
}

derive_verification_contract_snapshot() {
    [[ -f "$VERIFICATION_CONTRACT_HELPER" ]] \
        || die "missing verification contract helper: ${VERIFICATION_CONTRACT_HELPER}"
    local admission_json result
    admission_json="$(
        TASK_ID_VALUE="$TASK_ID" RUN_ID_VALUE="$RUN_ID" MODE_VALUE="$MODE" \
        RESULT_TYPE_VALUE="$RESULT_TYPE" TO_MODEL_VALUE="$TO_MODEL" \
        PANEL_ENABLED_VALUE="$PANEL_ENABLED" SWARM_ENABLED_VALUE="$SWARM_ENABLED" CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" \
        MAP_OPERATOR_GATE_VALUE="$MAP_OPERATOR_GATE" python3 - <<'PYEOF'
import json
import os

capability_raw = os.environ.get("CAPABILITY_SNAPSHOT_VALUE", "")
capability = None
if capability_raw:
    snapshot = json.loads(capability_raw)
    capability = {
        "id": snapshot.get("capability_id"),
        "card_sha256": snapshot.get("capability_card_sha256"),
        "derived_state": snapshot.get("capability_derived_state"),
        "expected_gates": snapshot.get("capability_gates") or [],
    }

runtime_raw = os.environ.get("MAP_OPERATOR_GATE_VALUE", "")
try:
    runtime_gates = json.loads(runtime_raw) if runtime_raw else []
except json.JSONDecodeError:
    runtime_gates = [
        item.strip().strip("[]\"'")
        for item in runtime_raw.split(",")
        if item.strip().strip("[]\"'")
    ]
if runtime_gates in (None, "none"):
    runtime_gates = []
elif isinstance(runtime_gates, str):
    runtime_gates = [runtime_gates]

print(json.dumps({
    "task_id": os.environ["TASK_ID_VALUE"],
    "run_id": os.environ.get("RUN_ID_VALUE", ""),
    "mode": os.environ["MODE_VALUE"],
    "result_type": os.environ.get("RESULT_TYPE_VALUE", "") or "normal",
    "to_model": os.environ["TO_MODEL_VALUE"],
    "dispatch_kind": (
        "swarm" if os.environ["SWARM_ENABLED_VALUE"] == "true"
        else "panel" if os.environ["PANEL_ENABLED_VALUE"] == "true"
        else "single"
    ),
    "capability": capability,
    "runtime_map_gates": runtime_gates,
}, separators=(",", ":")))
PYEOF
    )" || die "failed to build verification contract admission"
    result="$(python3 "$VERIFICATION_CONTRACT_HELPER" derive --admission-json "$admission_json")" \
        || die "typed verification contract admission failed"
    VERIFICATION_CONTRACT_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["verification_contract"], separators=(",",":"), ensure_ascii=False))' <<<"$result")"
    VERIFICATION_CONTRACT_SHA256="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verification_contract_sha256"])' <<<"$result")"
    AUTHOR_FAMILY="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verification_contract"]["author_family"])' <<<"$result")"
}

inject_verification_contract() {
    local contract_copy
    contract_copy=$(mktemp "${TASK_FILE%.md}.verification.XXXXXX.md")
    awk \
        -v author_family="$AUTHOR_FAMILY" \
        -v contract="$VERIFICATION_CONTRACT_JSON" \
        -v contract_sha="$VERIFICATION_CONTRACT_SHA256" '
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 == "---" && !inserted {
            print "author_family: " author_family
            print "verification_contract: " contract
            print "verification_contract_sha256: " contract_sha
            inserted=1
            in_frontmatter=0
        }
        { print }
        END { if (!inserted) exit 42 }
    ' "$WORKING_COPY" > "$contract_copy" \
        || die "failed to inject verification contract frontmatter"
    mv "$contract_copy" "$WORKING_COPY"
}

map_field() {
    local specialist="$1" field_index="$2"
    [[ -f "$RUNTIME_MAP" ]] || return 1
    awk -F '\t' -v s="$specialist" -v idx="$field_index" '$1 == s {print $idx; exit}' "$RUNTIME_MAP"
}

compat_namespace_for_model() {
    case "$1" in
        gpt-codex) printf '%s\n' coding ;;
        claude) printf '%s\n' security ;;
        gemini) printf '%s\n' content ;;
        kimi) printf '%s\n' research ;;
        *) return 1 ;;
    esac
}

validate_native_adapter() {
    local model="$1" specialist="$2" adapter agent_name
    [[ "$specialist" == "none" ]] && return 0
    [[ "$model" == "none" ]] && return 0
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
    python3 "${VAULT_ROOT}/scripts/python/lane_adapter_registry.py" \
        --repo-root "$VAULT_ROOT" --lane "$model" --validate-adapter "$adapter" >/dev/null \
        || die "predispatch blocked: adapter violates the ${model} lane capability registry for specialist '${specialist}'"
}

validate_task_capabilities() {
    local task_file="$1" target_model="$2" latest_audit
    latest_audit="$(find "${VAULT_ROOT}/_state/audit-logs" -maxdepth 1 -name '*-mcp-audit.md' -type f -print 2>/dev/null | sort | tail -1 || true)"
    python3 - "$task_file" "$latest_audit" \
        "${VAULT_ROOT}/shared/registries/skill-tool-registry.tsv" "$target_model" <<'PYEOF'
import csv
import re
import sys
from pathlib import Path

task_path = Path(sys.argv[1])
audit_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
registry_path = Path(sys.argv[3])
target_lane = {"gpt-codex": "codex"}.get(sys.argv[4], sys.argv[4])
text = task_path.read_text(errors="replace")

legacy_aliases = {
    "brave_search": "Brave Search",
    "apify_search": "Apify",
    "serper_search": "Serper",
}
blocked_states = {"no", "needs-research", "catalog-absent", "needs_tool"}
registry: dict[str, dict[str, str]] = {}
if registry_path.exists():
    with registry_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("record_kind") == "tool":
                registry[row["name"]] = row

def explicit_registry_references() -> set[str]:
    references = {
        canonical
        for alias, canonical in legacy_aliases.items()
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", text)
    }
    for quoted in re.findall(r"`([^`]+)`", text):
        if quoted in registry:
            references.add(quoted)
    return references

issues = []
warnings = []
if not registry and any(
    re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", text)
    for alias in legacy_aliases
):
    issues.append("tool-registry-unavailable:cannot verify referenced registry tool")
for name in sorted(explicit_registry_references()):
    row = registry.get(name)
    if row is None:
        issues.append(f"unregistered-tool:{name}")
        continue
    state = row["verified_state"]
    lanes = {lane.strip() for lane in re.split(r"[,|+]", row["lanes"]) if lane.strip()}
    if state in blocked_states:
        issues.append(f"unavailable-tool:{name} (registry-state:{state})")
    elif target_lane not in lanes and "all" not in lanes and "direct-api" not in lanes:
        warnings.append(
            f"tool-lane-mismatch:{name} (registry-lanes:{','.join(sorted(lanes))}; target:{target_lane})"
        )

# This child-tool spelling is a runtime-schema claim, not a registry tool name.
# Keep it fail-closed until a registry row or tools/list proof makes it citable.
if re.search(r"(?<![A-Za-z0-9_])elevenlabs__check_subscription(?![A-Za-z0-9_])", text):
    issues.append("unavailable-tool:elevenlabs__check_subscription (absent from governed wrapper schema)")

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

if warnings:
    print("predispatch capability warning: " + "; ".join(sorted(set(warnings))), file=sys.stderr)
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
SWARM_ENABLED=false
SWARM_LANES_RAW=""
SWARM_TIMEOUT_SECONDS="900"
SUBSWARM_ENABLED=false
SUBSWARM_DIRECTIVE=""
declare -a SUBSWARM_ASSIGNMENTS=()

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
        --swarm) SWARM_ENABLED=true; SWARM_LANES_RAW="$2"; shift 2 ;;
        --swarm-timeout) SWARM_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --subswarm-directive) SUBSWARM_ENABLED=true; SUBSWARM_DIRECTIVE="$2"; shift 2 ;;
        --subswarm-assignment) SUBSWARM_ASSIGNMENTS+=("$2"); shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        *)            TASK_FILE="$1"; shift ;;
    esac
done

[[ -z "$TASK_FILE" ]] && die "Usage: $0 <task-file> [--nudge-pane <target>] [--dry-run] [--panel ... | --swarm lanes]"
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
$PANEL_ENABLED && $SWARM_ENABLED && die "--panel and --swarm are distinct dispatch kinds and cannot be combined"
$SUBSWARM_ENABLED && $PANEL_ENABLED && die "--subswarm-directive and --panel are distinct dispatch modes and cannot be combined"
$SUBSWARM_ENABLED && $SWARM_ENABLED && die "--subswarm-directive and --swarm are distinct dispatch modes and cannot be combined"
if ! $SUBSWARM_ENABLED; then
    (( ${#SUBSWARM_ASSIGNMENTS[@]} == 0 )) || die "--subswarm-assignment requires --subswarm-directive"
fi
if ! $SWARM_ENABLED; then
    [[ "$SWARM_TIMEOUT_SECONDS" == "900" ]] || die "--swarm-timeout requires --swarm"
fi

# ── read task metadata ────────────────────────────────────────────────────────

# MED5 (wave-2): command substitution silently strips NUL bytes, so a raw NUL in
# the id frontmatter would collide to a different valid id instead of being
# rejected (overwrite / identity ambiguity). A task packet must never contain a
# NUL byte — validate the raw file bytes before parsing/trusting any frontmatter
# field, because $(frontmatter_field ...) can no longer reveal an embedded NUL.
# Both references are read-only: tr filters stdin and cmp compares that stream
# with the original bytes. ShellCheck cannot infer that cmp never writes it.
# shellcheck disable=SC2094
if [[ -f "$TASK_FILE" ]] && ! LC_ALL=C tr -d '\000' < "$TASK_FILE" | cmp -s - "$TASK_FILE"; then
    die "invalid task file (contains a NUL byte): $TASK_FILE"
fi

TASK_ID=$(frontmatter_field "$TASK_FILE" "id")
TO_LEAD=$(frontmatter_field "$TASK_FILE" "to_lead")
COMPAT_NAMESPACE=$(frontmatter_field "$TASK_FILE" "compatibility_namespace")
# shellcheck disable=SC2034  # retained compatibility metadata for legacy packets
RUN_ID=$(frontmatter_field "$TASK_FILE" "run_id")
RESULT_TYPE=$(frontmatter_field "$TASK_FILE" "result_type")
WRITE_SCOPE_RAW=$(frontmatter_field "$TASK_FILE" "write_scope")
PER_TASK_VERSIONING=$(frontmatter_field "$TASK_FILE" "per_task_versioning")
OWNING_LEAD=$(frontmatter_field "$TASK_FILE" "owning_lead")
SPECIALIST=$(frontmatter_field "$TASK_FILE" "specialist")
PRIMARY_RUNTIME=$(frontmatter_field "$TASK_FILE" "primary_runtime")
TO_MODEL=$(frontmatter_field "$TASK_FILE" "to_model")
SOURCE_NAMESPACE=$(frontmatter_field "$TASK_FILE" "source_namespace")
REVIEW_MODEL=$(frontmatter_field "$TASK_FILE" "review_model")
MANDATORY_REVIEW=$(frontmatter_field "$TASK_FILE" "mandatory_review")
REVIEW_CLASS=$(frontmatter_field "$TASK_FILE" "review_class")
MODEL_OVERRIDE_REASON=$(frontmatter_field "$TASK_FILE" "model_override_reason")
DIRECT_LANE_WORK_ALLOWED=$(frontmatter_field "$TASK_FILE" "direct_lane_work_allowed")
LEGACY_LEAD_DIRECT_ALLOWED=$(frontmatter_field "$TASK_FILE" "lead_direct_allowed")
PARALLEL_SAFE=$(frontmatter_field "$TASK_FILE" "parallel_safe")
PANEL_MEMBER_WRITE_SCOPE=$(frontmatter_field "$TASK_FILE" "panel_member_write_scope")
RETURN_ARTIFACT=$(frontmatter_field "$TASK_FILE" "return_artifact")
MODE=$(frontmatter_field "$TASK_FILE" "mode")
CAPABILITY=$(frontmatter_field "$TASK_FILE" "capability")
CAPABILITY_DEGRADATION_ACK=$(frontmatter_field "$TASK_FILE" "capability_degradation_ack")
CAPABILITY_SNAPSHOT_JSON=""
CAPABILITY_PRESENT=false
AUTHOR_FAMILY=""
VERIFICATION_CONTRACT_JSON=""
VERIFICATION_CONTRACT_SHA256=""
frontmatter_has_field "$TASK_FILE" "capability" && CAPABILITY_PRESENT=true
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

# Snapshot fields are dispatcher-owned. Accepting author-provided values would
# let a packet forge the immutable contract recorded in the active-task ledger.
for RESERVED_CAPABILITY_FIELD in \
    capability_id capability_card_path capability_card_sha256 \
    capability_derived_state capability_gates \
    author_family verification_contract verification_contract_sha256 \
    dispatch_kind swarm_parent_id swarm_spec swarm_spec_sha256 swarm_role \
    swarm_member_result swarm_diff_path \
    subswarm_directive_sha256 subswarm_dispatch_sha256 \
    subswarm_member_bundle subswarm_max_concurrency; do
    ! frontmatter_has_field "$TASK_FILE" "$RESERVED_CAPABILITY_FIELD" \
        || die "task packet may not pre-populate dispatcher-owned field '${RESERVED_CAPABILITY_FIELD}'"
done
if $CAPABILITY_PRESENT && [[ -z "$CAPABILITY" ]]; then
    die "task packet carries an empty capability field; use a valid slug or 'none'"
fi

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
if [[ -z "$REVIEW_CLASS" ]]; then
    REVIEW_CLASS="standard"
fi
if [[ -z "$PRIMARY_RUNTIME" ]]; then
    PRIMARY_RUNTIME="$TO_MODEL"
fi
if [[ -z "$SOURCE_NAMESPACE" ]]; then
    SOURCE_NAMESPACE="${TO_LEAD:-$OWNING_LEAD}"
fi
if [[ -z "$COMPAT_NAMESPACE" ]]; then
    if [[ "$SOURCE_NAMESPACE" == "shared" || "$SOURCE_NAMESPACE" == "chrono" ]]; then
        COMPAT_NAMESPACE="$(compat_namespace_for_model "$TO_MODEL")" \
            || die "cannot derive compatibility namespace for to_model '${TO_MODEL}'"
    else
        COMPAT_NAMESPACE="${TO_LEAD:-$SOURCE_NAMESPACE}"
    fi
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
case "$REVIEW_CLASS" in
    standard|factual|security-finding) ;;
    *) die "review_class must be standard, factual, or security-finding, got '${REVIEW_CLASS}'." ;;
esac
if [[ "$REVIEW_CLASS" == "security-finding" ]]; then
    [[ "$MANDATORY_REVIEW" == "true" ]] \
        || die "review_class: security-finding requires mandatory_review:true"
    [[ "$REVIEW_MODEL" != "none" && "$REVIEW_MODEL" != "$TO_MODEL" ]] \
        || die "review_class: security-finding requires a distinct review_model lane"
elif [[ "$REVIEW_CLASS" == "factual" ]]; then
    [[ "$MANDATORY_REVIEW" == "true" ]] \
        || die "review_class: factual requires mandatory_review:true"
    [[ "$REVIEW_MODEL" != "none" && "$REVIEW_MODEL" != "$TO_MODEL" ]] \
        || die "review_class: factual requires a distinct review_model lane"
fi

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
SWARM_LANES_CSV=""
SWARM_CHILD_IDS_CSV=""
SWARM_MEMBER_ROLES_CSV=""
SWARM_SPEC_JSON=""
SWARM_SPEC_SHA256=""
SWARM_COUNT=0
declare -a SWARM_LANES=()
declare -a SWARM_CHILD_IDS=()
declare -a SWARM_MEMBER_ROLES=()

if $SWARM_ENABLED; then
    [[ "$MODE" == "project" || "$MODE" == "bounty" ]] \
        || die "swarm-v1 requires typed mode project or bounty"
    [[ "$WRITE_SCOPE_RAW" == "[]" ]] \
        || die "swarm-v1 is read-only: packet write_scope must be []"
    [[ "$SWARM_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] \
        || die "swarm timeout must be a positive integer"
    (( SWARM_TIMEOUT_SECONDS <= 86400 )) || die "swarm timeout exceeds 86400 seconds"
    [[ -z "$(frontmatter_field "$TASK_FILE" "dispatch_kind")" ]] \
        || die "task already contains dispatch_kind; do not combine with --swarm"
    [[ -n "$SWARM_LANES_RAW" ]] || die "--swarm requires a comma-separated lane list"
    IFS=',' read -r -a SWARM_INPUT <<<"$SWARM_LANES_RAW"
    for raw_lane in "${SWARM_INPUT[@]}"; do
        lane="${raw_lane//[[:space:]]/}"
        [[ "$lane" == "codex" ]] && lane="gpt-codex"
        case "$lane" in gpt-codex|claude|gemini|kimi) ;; *) die "invalid swarm lane '${raw_lane}'" ;; esac
        for existing_lane in "${SWARM_LANES[@]:-}"; do
            [[ "$existing_lane" != "$lane" ]] || die "duplicate swarm lane '${lane}'"
        done
        member_role="$SPECIALIST"
        child_id="${TASK_ID}-swarm-${lane}"
        SWARM_LANES+=("$lane")
        SWARM_MEMBER_ROLES+=("$member_role")
        SWARM_CHILD_IDS+=("$child_id")
        SWARM_COUNT=$((SWARM_COUNT + 1))
    done
    (( SWARM_COUNT >= 2 && SWARM_COUNT <= 4 )) \
        || die "swarm-v1 requires 2-4 distinct lanes"
    for (( swarm_index=0; swarm_index<SWARM_COUNT; swarm_index++ )); do
        lane="${SWARM_LANES[$swarm_index]}"
        member_role="${SWARM_MEMBER_ROLES[$swarm_index]}"
        if ! {
            find "$VAULT_ROOT/departments" -path "*/specialists/${member_role}.md" -type f -print -quit
            find "$VAULT_ROOT/shared/specialists" -maxdepth 1 -name "${member_role}.md" -type f -print -quit 2>/dev/null
        } | grep -q .; then
            die "unknown swarm member role '${member_role}' for lane '${lane}'"
        fi
        validate_native_adapter "$lane" "$member_role"
    done
    MANDATORY_REVIEW="true"
    SWARM_LANES_CSV="$(IFS=,; echo "${SWARM_LANES[*]}")"
    SWARM_CHILD_IDS_CSV="$(IFS=,; echo "${SWARM_CHILD_IDS[*]}")"
    SWARM_MEMBER_ROLES_CSV="$(IFS=,; echo "${SWARM_MEMBER_ROLES[*]}")"
    SWARM_SPEC_JSON="$(TASK_SHA="$(shasum -a 256 "$TASK_FILE" | awk '{print $1}')" \
        SWARM_LANES_VALUE="$SWARM_LANES_CSV" SWARM_ROLES_VALUE="$SWARM_MEMBER_ROLES_CSV" \
        python3 - <<PYEOF
import json, os
print(json.dumps({
    "schema_version": "swarm-spec/v1",
    "parent_task_id": "${TASK_ID}",
    "specialist": "${SPECIALIST}",
    "lanes": os.environ["SWARM_LANES_VALUE"].split(","),
    "member_roles": os.environ["SWARM_ROLES_VALUE"].split(","),
    "quorum": "all",
    "timeout_seconds": int("${SWARM_TIMEOUT_SECONDS}"),
    "write_scope": [],
    "task_packet_sha256": os.environ["TASK_SHA"],
    "mandatory_review": True,
}, sort_keys=True, separators=(",", ":")))
PYEOF
    )"
    SWARM_SPEC_SHA256="$(printf '%s' "$SWARM_SPEC_JSON" | shasum -a 256 | awk '{print $1}')"
    info "Swarm preflight: lanes=${SWARM_LANES_CSV} quorum=all spec=${SWARM_SPEC_SHA256}"
fi

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

    if $SWARM_ENABLED; then
        declare -a SWARM_RANKED_LANES=("$MAP_MODEL")
        for route_index in 9 11 14 17; do
            route_lane="$(map_field "$SPECIALIST" "$route_index" || true)"
            [[ "$route_lane" == "codex" ]] && route_lane="gpt-codex"
            [[ -n "$route_lane" && "$route_lane" != "none" ]] && SWARM_RANKED_LANES+=("$route_lane")
        done
        for lane in "${SWARM_LANES[@]}"; do
            ranked=false
            for route_lane in "${SWARM_RANKED_LANES[@]}"; do
                [[ "$lane" == "$route_lane" ]] && ranked=true
            done
            $ranked || die "swarm lane '${lane}' is not a ranked runtime route for specialist '${SPECIALIST}'"
        done
    fi

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

if $CAPABILITY_PRESENT && [[ "$CAPABILITY" != "none" ]]; then
    [[ -f "$CAPABILITY_DISPATCH" ]] \
        || die "missing capability dispatch validator: ${CAPABILITY_DISPATCH}"
    if ! CAPABILITY_SNAPSHOT_JSON="$(
        python3 "$CAPABILITY_DISPATCH" \
            --root "$VAULT_ROOT" \
            --mode "$MODE" \
            --capability "$CAPABILITY" \
            --ack "$CAPABILITY_DEGRADATION_ACK"
    )"; then
        die "task capability pointer is invalid"
    fi
    CAPABILITY_DECISION="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["dispatch_decision"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    CAPABILITY_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["capability_id"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    CAPABILITY_STATE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["capability_derived_state"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    CAPABILITY_HASH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["capability_card_sha256"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    if [[ "$CAPABILITY_DECISION" == "hold" ]]; then
        CAPABILITY_HOLD_REASON="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["hold_reason"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
        echo "WARNING: capability dispatch HOLD: ${CAPABILITY_HOLD_REASON}" >&2
        die "typed capability degradation acknowledgement required"
    fi
    info "Capability snapshot: id=${CAPABILITY_ID} state=${CAPABILITY_STATE} sha256=${CAPABILITY_HASH}"
fi

# Validate only the author-authored packet here. The registry-derived toolkit is
# intentionally appended later and may backtick cross-lane status rows. State
# failures remain hard gates above; a `yes` lane mismatch is only a warning, so a
# future ordering change cannot make the toolkit falsely block its own packet.
if $SWARM_ENABLED; then
    for lane in "${SWARM_LANES[@]}"; do
        validate_task_capabilities "$TASK_FILE" "$lane" \
            || die "task references unavailable or unverified live capability for swarm lane ${lane}"
    done
else
    validate_task_capabilities "$TASK_FILE" "$TO_MODEL" || die "task references unavailable or unverified live capability"
fi

if [[ ( "$MODE" == "project" || "$MODE" == "bounty" ) && "$SWARM_ENABLED" == "false" ]]; then
    derive_verification_contract_snapshot
    info "Verification contract: version=verification-contract/v1 sha256=${VERIFICATION_CONTRACT_SHA256}"
fi

# Lead-internal sub-swarms are an explicit single-dispatch prompt contract. They
# do not use mailbox workers, leases, panel member-N identities, or cross-lane
# swarm children. Seal the P2 directive and bind every objective hash to the
# exact assignment text before anything is published.
SUBSWARM_DIRECTIVE_SHA256=""
SUBSWARM_DISPATCH_SHA256=""
SUBSWARM_MAX_CONCURRENCY=""
SUBSWARM_MEMBER_BUNDLE=""
SUBSWARM_BRIEF_MARKDOWN=""
SUBSWARM_ASSIGNMENT_MARKDOWN=""
if $SUBSWARM_ENABLED; then
    [[ -f "$SUBSWARM_DIRECTIVE" ]] \
        || die "subswarm directive file not found: ${SUBSWARM_DIRECTIVE}"
    (( ${#SUBSWARM_ASSIGNMENTS[@]} >= 2 )) \
        || die "subswarm dispatch requires at least two --subswarm-assignment values"
    [[ -n "$RETURN_ARTIFACT" ]] \
        || die "subswarm dispatch requires return_artifact"
    case "$RETURN_ARTIFACT" in
        *.*) SUBSWARM_MEMBER_BUNDLE="${RETURN_ARTIFACT%.*}-member-bundle.json" ;;
        *) SUBSWARM_MEMBER_BUNDLE="${RETURN_ARTIFACT}-member-bundle.json" ;;
    esac
    if ! SUBSWARM_ENVELOPE_JSON="$(
        SQUAD_SUBSWARM_ORCHESTRATION_ENABLED=1 \
        python3 - "$VAULT_ROOT" "$SUBSWARM_DIRECTIVE" "$TASK_ID" "$TO_MODEL" \
            "$WRITE_SCOPE_RAW" "${SUBSWARM_ASSIGNMENTS[@]}" <<'PYEOF'
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1])
directive_path = Path(sys.argv[2])
task_id = sys.argv[3]
lane = sys.argv[4]
write_scope_raw = sys.argv[5]
assignment_args = sys.argv[6:]
sys.path.insert(0, str(root / "scripts/python"))
from swarm_diff import SwarmDiffError, build_orchestration_dispatch

try:
    raw = json.loads(directive_path.read_text(encoding="utf-8"))
    dispatch = build_orchestration_dispatch(raw)
except (OSError, json.JSONDecodeError, SwarmDiffError) as exc:
    raise SystemExit(f"invalid subswarm directive: {exc}") from exc
directive = dispatch["directive"]
if directive["parent_task_id"] != task_id:
    raise SystemExit("subswarm directive parent_task_id does not match task id")
if directive["lane"] != lane:
    raise SystemExit("subswarm directive lane does not match task to_model")

def parse_inline_scope(raw):
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        raise SystemExit("subswarm write_scope must be a YAML inline list")
    values = []
    for token in raw[1:-1].split(","):
        token = token.strip().strip("'\"").rstrip("/")
        if token:
            values.append(PurePosixPath(token))
    return values

write_scope = parse_inline_scope(write_scope_raw)
declared = {member["member_id"]: member for member in directive["members"]}
for member_id, member in declared.items():
    output_path = PurePosixPath(member["output_path"])
    if not any(scope == output_path or scope in output_path.parents for scope in write_scope):
        raise SystemExit(
            f"subswarm output_path is outside packet write_scope: {member_id} -> {output_path}"
        )
assignments = {}
for raw_assignment in assignment_args:
    member_id, separator, text = raw_assignment.partition("=")
    text = text.strip()
    if not separator or not member_id or not text or "\n" in text or "\r" in text:
        raise SystemExit("subswarm assignments must be '<lane>:subNN=single-line text'")
    if member_id in assignments:
        raise SystemExit(f"duplicate subswarm assignment: {member_id}")
    assignments[member_id] = text
if set(assignments) != set(declared):
    raise SystemExit("subswarm assignments must cover every directive member exactly once")
for member_id, text in assignments.items():
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != declared[member_id]["objective_sha256"]:
        raise SystemExit(f"subswarm assignment objective hash mismatch: {member_id}")
assignment_markdown = "\n## Bound native-subagent assignments\n\n"
for member_id in sorted(assignments):
    assignment_markdown += f"### {member_id}\n\n{assignments[member_id]}\n\n"
    assignment_markdown += f"Machine output: `{declared[member_id]['output_path']}`\n\n"
assignment_markdown += (
    "Use `scripts/python/swarm_runtime.py subswarm-run` with real native runtime "
    "subagents for these assignments so dependencies, live host admission, and "
    "replica output isolation are machine-enforced. Do not create member "
    "mailbox tasks, claims, leases, or outboxes. Preserve each raw child return and "
    "its SHA-256; a malformed or missing return becomes a typed gap. The lead alone "
    "seals the declared swarm-member-bundle/v1 at the dispatcher-provided path, "
    "decomposes it exhaustively, and publishes the single task response.\n"
)
print(json.dumps({
    "dispatch": dispatch,
    "assignment_markdown": assignment_markdown,
}, separators=(",", ":"), ensure_ascii=False))
PYEOF
    )"; then
        die "subswarm directive/assignment validation failed"
    fi
    SUBSWARM_DIRECTIVE_SHA256="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["dispatch"]["directive"]["directive_sha256"])' <<<"$SUBSWARM_ENVELOPE_JSON")"
    SUBSWARM_DISPATCH_SHA256="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["dispatch"]["dispatch_sha256"])' <<<"$SUBSWARM_ENVELOPE_JSON")"
    SUBSWARM_MAX_CONCURRENCY="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["dispatch"]["directive"]["max_concurrency"])' <<<"$SUBSWARM_ENVELOPE_JSON")"
    SUBSWARM_BRIEF_MARKDOWN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["dispatch"]["brief_markdown"], end="")' <<<"$SUBSWARM_ENVELOPE_JSON")"
    SUBSWARM_ASSIGNMENT_MARKDOWN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["assignment_markdown"], end="")' <<<"$SUBSWARM_ENVELOPE_JSON")"
    info "Subswarm directive: sha256=${SUBSWARM_DIRECTIVE_SHA256} members=${#SUBSWARM_ASSIGNMENTS[@]} cap=${SUBSWARM_MAX_CONCURRENCY}"
fi

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
echo "  Compatibility mailbox: ${COMPAT_NAMESPACE}"

if $DRY_RUN; then
    echo "[DRY RUN] Would validate, inject toolkit, copy to inbox, update registry"
    echo "[DRY RUN] per_task_versioning=${PER_TASK_VERSIONING:-false}"
    echo "[DRY RUN] write_scope=${WRITE_SCOPE_RAW:-[]}"
    if $PANEL_ENABLED; then
        PANEL_MODE="review"
        $FANOUT_ENABLED && PANEL_MODE="fanout"
        echo "[DRY RUN] dispatch_kind=panel mode=${PANEL_MODE} members=${PANEL_MEMBERS_CSV} member_ids=${PANEL_MEMBER_IDS_CSV} policy=${PANEL_POLICY} quorum=${PANEL_QUORUM} timeout=${PANEL_TIMEOUT_SECONDS} assignments=${#PANEL_ASSIGNMENTS[@]}"
    fi
    if $SWARM_ENABLED; then
        echo "[DRY RUN] dispatch_kind=swarm lanes=${SWARM_LANES_CSV} child_ids=${SWARM_CHILD_IDS_CSV} roles=${SWARM_MEMBER_ROLES_CSV} quorum=all timeout=${SWARM_TIMEOUT_SECONDS} write_scope=[]"
        echo "[DRY RUN] swarm_spec_sha256=${SWARM_SPEC_SHA256} mandatory_review=true"
    fi
    if $SUBSWARM_ENABLED; then
        echo "[DRY RUN] dispatch_kind=single subswarm_directive_sha256=${SUBSWARM_DIRECTIVE_SHA256} dispatch_sha256=${SUBSWARM_DISPATCH_SHA256} members=${#SUBSWARM_ASSIGNMENTS[@]} cap=${SUBSWARM_MAX_CONCURRENCY} bundle=${SUBSWARM_MEMBER_BUNDLE}"
    fi
    if [[ -n "$VERIFICATION_CONTRACT_SHA256" ]]; then
        echo "[DRY RUN] verification_contract=verification-contract/v1 sha256=${VERIFICATION_CONTRACT_SHA256}"
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

# Swarm-v1 publishes independent child packets and one controller ledger record.
# The preflight above validates the complete lane/adapter set before this branch.
if $SWARM_ENABLED; then
    SWARM_BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/swarm-dispatch.XXXXXX")"
    SWARM_BUILD_DIR_VALUE="$SWARM_BUILD_DIR" SWARM_SPEC_VALUE="$SWARM_SPEC_JSON" \
    SWARM_SPEC_SHA_VALUE="$SWARM_SPEC_SHA256" SWARM_LANES_VALUE="$SWARM_LANES_CSV" \
    SWARM_ROLES_VALUE="$SWARM_MEMBER_ROLES_CSV" CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" \
    MAP_OPERATOR_GATE_VALUE="$MAP_OPERATOR_GATE" COMPAT_NAMESPACE_VALUE="$COMPAT_NAMESPACE" \
    python3 - "$TASK_FILE" "$VERIFICATION_CONTRACT_HELPER" <<'PYEOF'
import hashlib
import importlib.util
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

source = Path(sys.argv[1])
helper_path = Path(sys.argv[2])
build = Path(os.environ["SWARM_BUILD_DIR_VALUE"])
spec = json.loads(os.environ["SWARM_SPEC_VALUE"])
spec_sha = os.environ["SWARM_SPEC_SHA_VALUE"]
lanes = os.environ["SWARM_LANES_VALUE"].split(",")
roles = os.environ["SWARM_ROLES_VALUE"].split(",")
capability_raw = os.environ.get("CAPABILITY_SNAPSHOT_VALUE", "")
capability_snapshot = json.loads(capability_raw) if capability_raw else None

module_spec = importlib.util.spec_from_file_location("verification_contract", helper_path)
module = importlib.util.module_from_spec(module_spec)
assert module_spec and module_spec.loader
module_spec.loader.exec_module(module)

text = source.read_text(encoding="utf-8")
match = re.match(r"^---\n(.*?)\n---\s*\n?(.*)$", text, re.S)
if not match:
    raise SystemExit("swarm packet requires YAML frontmatter")
frontmatter_lines = match.group(1).splitlines()
body = match.group(2)

def field(name: str) -> str:
    prefix = name + ":"
    for line in frontmatter_lines:
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""

parent_id = field("id")
mode = field("mode")
run_id = field("run_id")
result_type = field("result_type") or "normal"
namespace = os.environ["COMPAT_NAMESPACE_VALUE"]
source_namespace = field("source_namespace")
parallel_safe = field("parallel_safe")
direct_allowed = field("direct_lane_work_allowed") or field("lead_direct_allowed")
runtime_raw = os.environ.get("MAP_OPERATOR_GATE_VALUE", "")
try:
    runtime_gates = json.loads(runtime_raw) if runtime_raw else []
except json.JSONDecodeError:
    runtime_gates = [item.strip().strip("[]\"'") for item in runtime_raw.split(",") if item.strip()]
if runtime_gates in (None, "none"):
    runtime_gates = []

replace_fields = {
    "id", "to_model", "specialist", "return_artifact", "write_scope",
    "mandatory_review", "review_model", "model_override_reason", "compatibility_namespace",
}
base_lines = [line for line in frontmatter_lines if line.split(":", 1)[0] not in replace_fields]
now = datetime.now(timezone.utc)
children = []
members = {}
member_result_paths = {}

for lane, role in zip(lanes, roles):
    child_id = f"{parent_id}-swarm-{lane}"
    artifact = f"_state/swarm/{parent_id}/{lane}/artifact.md"
    member_result = f"_state/swarm/{parent_id}/{lane}/member-result.json"
    admission = {
        "task_id": child_id,
        "run_id": run_id,
        "mode": mode,
        "result_type": result_type,
        "to_model": lane,
        "dispatch_kind": "swarm",
        "capability": None,
        "runtime_map_gates": runtime_gates,
    }
    if capability_snapshot:
        admission["capability"] = {
            "id": capability_snapshot.get("capability_id"),
            "card_sha256": capability_snapshot.get("capability_card_sha256"),
            "derived_state": capability_snapshot.get("capability_derived_state"),
            "expected_gates": capability_snapshot.get("capability_gates") or [],
        }
    contract = module.derive_verification_contract(admission)
    contract_sha = module.verification_contract_sha256(contract)
    injected = list(base_lines)
    injected.extend(
        [
            f"id: {child_id}",
            f"to_model: {lane}",
            f"specialist: {role}",
            f"compatibility_namespace: {namespace}",
            f"swarm_specialist: {field('specialist')}",
            "write_scope: []",
            f"return_artifact: {artifact}",
            "mandatory_review: true",
            f"review_model: {'claude' if lane == 'gpt-codex' else 'gpt-codex'}",
            "model_override_reason: swarm-v1 lane member",
            "dispatch_kind: swarm",
            "swarm_role: member",
            f"swarm_parent_id: {parent_id}",
            f"swarm_spec: {json.dumps(spec, sort_keys=True, separators=(',', ':'))}",
            f"swarm_spec_sha256: {spec_sha}",
            f"swarm_member_result: {member_result}",
            f"author_family: {contract['author_family']}",
            f"verification_contract: {json.dumps(contract, sort_keys=True, separators=(',', ':'))}",
            f"verification_contract_sha256: {contract_sha}",
        ]
    )
    if capability_snapshot:
        injected.extend(
            [
                f"capability_id: {capability_snapshot['capability_id']}",
                f"capability_card_path: {capability_snapshot['capability_card_path']}",
                f"capability_card_sha256: {capability_snapshot['capability_card_sha256']}",
                f"capability_derived_state: {capability_snapshot['capability_derived_state']}",
                f"capability_gates: {json.dumps(capability_snapshot['capability_gates'], separators=(',', ':'))}",
            ]
        )
    instruction = f"""

## Swarm-v1 member contract

This is the independent `{lane}` child of `{parent_id}`. Work from the shared objective without reading other member results. The packet is read-only (`write_scope: []`) except for the lane-isolated return artifact, sidecar, and response envelope named here. Write `{member_result}` as strict `swarm-member-result/v1`; echo `swarm_spec_sha256: {spec_sha}` in both that sidecar and your response. Agreement is corroboration only. Do not synthesize, majority-vote, or mutate the parent diff.
"""
    packet = "---\n" + "\n".join(injected) + "\n---\n\n" + body.rstrip() + instruction
    (build / f"{child_id}.md").write_text(packet, encoding="utf-8")

    attempt_id = f"d-{uuid.uuid4().hex}"
    entry = {
        "compatibility_namespace": namespace,
        "specialist": role,
        "swarm_specialist": field("specialist"),
        "to_model": lane,
        "source_namespace": source_namespace,
        "review_model": "claude" if lane == "gpt-codex" else "gpt-codex",
        "mandatory_review": "true",
        "parallel_safe": parallel_safe,
        "direct_lane_work_allowed": direct_allowed,
        "dispatched_at": now.isoformat(),
        "return_artifact": artifact,
        "write_scope": [],
        "status": "in-flight",
        "delivery_state": "queued",
        "delivery_attempt_id": attempt_id,
        "delivery_generation": 1,
        "delivery_lane": lane,
        "delivery_attempt_count": 0,
        "delivery_retry_count": 0,
        "delivery_max_attempts": 5,
        "delivery_first_attempt_at": None,
        "delivery_last_attempt_at": None,
        "delivery_next_attempt_at": now.isoformat(),
        "claimed_at": None,
        "started_at": None,
        "delivery_terminal_at": None,
        "delivery_worker_id": None,
        "worker_epoch": None,
        "lease_generation": 0,
        "lease_expires_at": None,
        "heartbeat_observed_at": None,
        "member_id": None,
        "replica_index": None,
        "priority_class": "normal",
        "enqueued_at": now.isoformat(),
        "delivery_history": [{"event": "queued", "at": now.isoformat(), "attempt_id": attempt_id, "generation": 1, "lane": lane}],
        "dispatch_kind": "swarm",
        "swarm_role": "member",
        "swarm_parent_id": parent_id,
        "swarm_spec_sha256": spec_sha,
        "swarm_member_result": member_result,
        "author_family": contract["author_family"],
        "verification_contract": contract,
        "verification_contract_sha256": contract_sha,
    }
    if capability_snapshot:
        entry.update(capability_snapshot)
    children.append(child_id)
    members[child_id] = entry
    member_result_paths[lane] = member_result

parent = {
    "compatibility_namespace": namespace,
    "specialist": field("specialist"),
    "source_namespace": source_namespace,
    "dispatch_kind": "swarm",
    "swarm_role": "parent",
    "swarm_spec": spec,
    "swarm_spec_sha256": spec_sha,
    "swarm_children": children,
    "swarm_lanes": lanes,
    "swarm_member_results": member_result_paths,
    "swarm_diff_path": f"_state/swarm/{parent_id}/swarm-diff.json",
    "swarm_taxonomy_path": "shared/finding-taxonomy.md",
    "swarm_deadline_at": (now + timedelta(seconds=int(spec["timeout_seconds"]))).isoformat(),
    "mandatory_review": "true",
    "return_artifact": field("return_artifact"),
    "expected_response_path": f"departments/{namespace}/outbox/{parent_id}-response.md",
    "write_scope": [],
    "status": "in-flight",
    "dispatched_at": now.isoformat(),
}
(build / "parent-entry.json").write_text(json.dumps(parent, separators=(",", ":")), encoding="utf-8")
(build / "member-entries.json").write_text(json.dumps(members, separators=(",", ":")), encoding="utf-8")
PYEOF

    for (( swarm_index=0; swarm_index<SWARM_COUNT; swarm_index++ )); do
        lane="${SWARM_LANES[$swarm_index]}"
        child_id="${SWARM_CHILD_IDS[$swarm_index]}"
        bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$lane" >> "${SWARM_BUILD_DIR}/${child_id}.md"
    done

    PARENT_ENTRY_JSON="$(<"${SWARM_BUILD_DIR}/parent-entry.json")"
    MEMBER_ENTRIES_JSON="$(<"${SWARM_BUILD_DIR}/member-entries.json")"
    "${VAULT_ROOT}/bin/registry-reconciler.sh" --register-swarm "$TASK_ID" \
        --parent-entry-json "$PARENT_ENTRY_JSON" --member-entries-json "$MEMBER_ENTRIES_JSON" \
        || die "atomic swarm registry registration failed"

    for child_id in "${SWARM_CHILD_IDS[@]}"; do
        swarm_publish_index=0
        for (( lookup_index=0; lookup_index<SWARM_COUNT; lookup_index++ )); do
            [[ "${SWARM_CHILD_IDS[$lookup_index]}" == "$child_id" ]] && swarm_publish_index=$lookup_index
        done
        child_source="${SWARM_BUILD_DIR}/${child_id}.md"
        child_temp="$(mktemp "${INBOX}/.${child_id}.tmp.XXXXXX")"
        if ! cp "$child_source" "$child_temp" || ! mv -f "$child_temp" "${INBOX}/${child_id}.md"; then
            unpublished_csv="$(IFS=,; echo "${SWARM_CHILD_IDS[*]:$swarm_publish_index}")"
            unpublished_json="$(UNPUBLISHED_CSV="$unpublished_csv" python3 - <<'PYEOF'
import json, os
print(json.dumps([item for item in os.environ["UNPUBLISHED_CSV"].split(",") if item]))
PYEOF
            )"
            "${VAULT_ROOT}/bin/registry-reconciler.sh" \
                --mark-swarm-publication-failed "$TASK_ID" \
                --unpublished-children-json "$unpublished_json" \
                --failure-detail "mailbox publication failed at ${child_id}" \
                || echo "WARNING: could not mark swarm publication failure" >&2
            die "failed to publish swarm child ${child_id}; partial batch preserved in registry"
        fi
        info "Published swarm child ${COMPAT_NAMESPACE}/inbox/${child_id}.md"
    done
    for build_file in "${SWARM_BUILD_DIR}"/*; do rm -f "$build_file"; done
    rmdir "$SWARM_BUILD_DIR"
    echo "✓ Dispatched swarm ${TASK_ID} → ${SWARM_LANES_CSV} (${SWARM_COUNT} independent children; review required)"
    exit 0
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

if $SUBSWARM_ENABLED; then
    SUBSWARM_COPY=$(mktemp "${TASK_FILE%.md}.subswarm.XXXXXX.md")
    awk \
        -v directive_sha="$SUBSWARM_DIRECTIVE_SHA256" \
        -v dispatch_sha="$SUBSWARM_DISPATCH_SHA256" \
        -v bundle="$SUBSWARM_MEMBER_BUNDLE" \
        -v cap="$SUBSWARM_MAX_CONCURRENCY" '
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 == "---" && !inserted {
            print "subswarm_directive_sha256: " directive_sha
            print "subswarm_dispatch_sha256: " dispatch_sha
            print "subswarm_member_bundle: " bundle
            print "subswarm_max_concurrency: " cap
            inserted=1
            in_frontmatter=0
        }
        { print }
        END { if (!inserted) exit 42 }
    ' "$WORKING_COPY" > "$SUBSWARM_COPY" \
        || die "failed to inject subswarm frontmatter"
    mv "$SUBSWARM_COPY" "$WORKING_COPY"
    printf '\n%s\n%s\n' "$SUBSWARM_BRIEF_MARKDOWN" "$SUBSWARM_ASSIGNMENT_MARKDOWN" >> "$WORKING_COPY"
fi

if [[ -n "$CAPABILITY_SNAPSHOT_JSON" ]]; then
    CAPABILITY_CARD_PATH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["capability_card_path"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    CAPABILITY_GATES="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["capability_gates"], separators=(",",":")))' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    SNAPSHOT_COPY=$(mktemp "${TASK_FILE%.md}.capability.XXXXXX.md")
    awk \
        -v capability_id="$CAPABILITY_ID" \
        -v capability_path="$CAPABILITY_CARD_PATH" \
        -v capability_sha="$CAPABILITY_HASH" \
        -v capability_state="$CAPABILITY_STATE" \
        -v capability_gates="$CAPABILITY_GATES" '
        NR == 1 && $0 == "---" { in_frontmatter=1; print; next }
        in_frontmatter && $0 == "---" && !inserted {
            print "capability_id: " capability_id
            print "capability_card_path: " capability_path
            print "capability_card_sha256: " capability_sha
            print "capability_derived_state: " capability_state
            print "capability_gates: " capability_gates
            inserted=1
            in_frontmatter=0
        }
        { print }
        END { if (!inserted) exit 42 }
    ' "$WORKING_COPY" > "$SNAPSHOT_COPY" \
        || die "failed to inject capability snapshot frontmatter"
    mv "$SNAPSHOT_COPY" "$WORKING_COPY"
fi

if [[ -n "$VERIFICATION_CONTRACT_SHA256" ]]; then
    inject_verification_contract
fi

if [[ -x "$TOOLKIT" ]]; then
    bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$TO_MODEL" >> "$WORKING_COPY"
    info "Toolkit injected for ${COMPAT_NAMESPACE}/${TO_MODEL}"
fi

if [[ -n "$CAPABILITY_SNAPSHOT_JSON" ]]; then
    cat >> "$WORKING_COPY" <<EOF

## Dispatched Capability Snapshot — immutable completion contract

- Capability ID: \`${CAPABILITY_ID}\`
- Card SHA-256 at dispatch: \`${CAPABILITY_HASH}\`
- Validator-derived state at dispatch: \`${CAPABILITY_STATE}\`
- Gates at dispatch: \`${CAPABILITY_GATES}\`

The active-task registry evaluates this dispatched snapshot, not a later version of the card. Your response envelope MUST echo this exact frontmatter field:

\`\`\`yaml
capability_card_sha256: ${CAPABILITY_HASH}
\`\`\`

If the current card changes while this task is running, reconciliation reports that drift separately; it does not silently rewrite this task's contract.
EOF
fi

if [[ -n "$VERIFICATION_CONTRACT_SHA256" ]]; then
    cat >> "$WORKING_COPY" <<EOF

## Dispatcher-pinned Verification Contract v1

- Author family: \`${AUTHOR_FAMILY}\`
- Contract SHA-256: \`${VERIFICATION_CONTRACT_SHA256}\`

The run manifest MUST echo both \`verification_contract\` and \`verification_contract_sha256\` exactly. These fields are dispatcher-owned and immutable for this task.
EOF
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

if REGISTRY_ENTRY_JSON="$(RETURN_ARTIFACT_VALUE="$RETURN_ARTIFACT" CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" CONTROL_ATTEMPT_VALUE="$CONTROL_ATTEMPT_ID" AUTHOR_FAMILY_VALUE="$AUTHOR_FAMILY" VERIFICATION_CONTRACT_VALUE="$VERIFICATION_CONTRACT_JSON" VERIFICATION_CONTRACT_SHA256_VALUE="$VERIFICATION_CONTRACT_SHA256" SUBSWARM_DIRECTIVE_SHA256_VALUE="$SUBSWARM_DIRECTIVE_SHA256" SUBSWARM_DISPATCH_SHA256_VALUE="$SUBSWARM_DISPATCH_SHA256" SUBSWARM_MEMBER_BUNDLE_VALUE="$SUBSWARM_MEMBER_BUNDLE" SUBSWARM_MAX_CONCURRENCY_VALUE="$SUBSWARM_MAX_CONCURRENCY" python3 - <<PYEOF
import json, os, re, uuid
from datetime import datetime, timezone

scope_raw = """${WRITE_SCOPE_RAW}"""
scope = [s.strip().strip('"').strip("'")
         for s in re.sub(r'[\[\]]', '', scope_raw).split(',')
         if s.strip()]

dispatched_at = datetime.now(timezone.utc).isoformat()
delivery_attempt_id = os.environ.get("CONTROL_ATTEMPT_VALUE") or f"d-{uuid.uuid4().hex}"
entry = {
    "compatibility_namespace": "${COMPAT_NAMESPACE}",
    "specialist": "${SPECIALIST}",
    "to_model": "${TO_MODEL}",
    "source_namespace": "${SOURCE_NAMESPACE}",
    "review_model": "${REVIEW_MODEL}",
    "mandatory_review": "${MANDATORY_REVIEW}",
    "review_class": "${REVIEW_CLASS}",
    "parallel_safe": "${PARALLEL_SAFE}",
    "direct_lane_work_allowed": "${DIRECT_LANE_WORK_ALLOWED}",
    "dispatched_at": dispatched_at,
    "return_artifact": os.environ.get("RETURN_ARTIFACT_VALUE", ""),
    "write_scope": scope,
    "status": "in-flight",
    "delivery_state": "queued",
    "delivery_attempt_id": delivery_attempt_id,
    "delivery_generation": 1,
    "delivery_lane": "${TO_MODEL}",
    "delivery_attempt_count": 0,
    "delivery_retry_count": 0,
    "delivery_max_attempts": 5,
    "delivery_first_attempt_at": None,
    "delivery_last_attempt_at": None,
    "delivery_next_attempt_at": dispatched_at,
    "claimed_at": None,
    "started_at": None,
    "delivery_terminal_at": None,
    "delivery_worker_id": None,
    "worker_epoch": None,
    "lease_generation": 0,
    "lease_expires_at": None,
    "heartbeat_observed_at": None,
    "member_id": None,
    "replica_index": None,
    "priority_class": "normal",
    "enqueued_at": dispatched_at,
    "delivery_history": [{
        "event": "queued",
        "at": dispatched_at,
        "attempt_id": delivery_attempt_id,
        "generation": 1,
        "lane": "${TO_MODEL}",
    }],
    "dispatch_kind": "panel" if "${PANEL_ENABLED}" == "true" else "single",
    "panel_members": [m for m in "${PANEL_MEMBERS_CSV}".split(",") if m],
    "panel_member_ids": [m for m in "${PANEL_MEMBER_IDS_CSV}".split(",") if m],
    "panel_mode": ("fanout" if "${FANOUT_ENABLED}" == "true" else "review") if "${PANEL_ENABLED}" == "true" else "single",
}
snapshot_raw = os.environ.get("CAPABILITY_SNAPSHOT_VALUE", "")
if snapshot_raw:
    snapshot = json.loads(snapshot_raw)
    for key in (
        "capability_id",
        "capability_card_path",
        "capability_card_sha256",
        "capability_derived_state",
        "capability_gates",
        "capability_degradation_ack",
    ):
        entry[key] = snapshot[key]
contract_raw = os.environ.get("VERIFICATION_CONTRACT_VALUE", "")
if contract_raw:
    entry["author_family"] = os.environ["AUTHOR_FAMILY_VALUE"]
    entry["verification_contract"] = json.loads(contract_raw)
    entry["verification_contract_sha256"] = os.environ["VERIFICATION_CONTRACT_SHA256_VALUE"]
subswarm_directive_sha256 = os.environ.get("SUBSWARM_DIRECTIVE_SHA256_VALUE", "")
if subswarm_directive_sha256:
    entry["subswarm_directive_sha256"] = subswarm_directive_sha256
    entry["subswarm_dispatch_sha256"] = os.environ["SUBSWARM_DISPATCH_SHA256_VALUE"]
    entry["subswarm_member_bundle"] = os.environ["SUBSWARM_MEMBER_BUNDLE_VALUE"]
    entry["subswarm_max_concurrency"] = int(os.environ["SUBSWARM_MAX_CONCURRENCY_VALUE"])
print(json.dumps(entry, separators=(",", ":")))
PYEOF
)" && "${VAULT_ROOT}/bin/registry-reconciler.sh" \
    --register-task "$TASK_ID" --entry-json "$REGISTRY_ENTRY_JSON"; then
    info "Active-task registry updated under shared lock"
else
    die "active-task registry update failed; refusing unreceipted delivery"
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
    set +e
    env VAULT_ROOT="$VAULT_ROOT" bash "${VAULT_ROOT}/bin/nudge-task.sh" "$DEST"
    NUDGE_RC=$?
    set -e
    if [[ "$NUDGE_RC" -eq 0 ]]; then
        info "Nudged pane ${NUDGE_PANE}"
        if [[ "$CONTROL_ACTIVE" == "1" ]]; then
            "${CONTROL_RUN[@]}" event \
                --task-id "$TASK_ID" \
                --attempt-id "$CONTROL_ATTEMPT_ID" \
                --event pane_delivery_attempted \
                --detail "send-task-direct-nudge" >/dev/null \
                || die "pane delivery succeeded but could not be recorded for ${TASK_ID}"
        fi
    elif [[ "$NUDGE_RC" -eq 3 ]]; then
        info "Delivery deferred by the locked per-lane queue for ${TASK_ID}"
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
