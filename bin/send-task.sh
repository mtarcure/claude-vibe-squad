#!/bin/bash
# bin/send-task.sh — Dispatch a TASK file to a source namespace inbox.
#
# Usage:
#   bin/send-task.sh <task-file> [--dry-run]
#       [--panel a,b,c] [--panel-policy evidence-synthesis]
#       [--panel-quorum all|N] [--panel-timeout SECONDS]
#       [--fanout --panel-assignment TEXT --panel-assignment TEXT]
#       [--swarm claude,gpt-codex,gemini,kimi] [--swarm-timeout SECONDS]
#   bin/send-task.sh --close-task <TASK-ID>  # evidence-gated reconciliation
#
# Required frontmatter in task file:
#   id: TASK-YYYY-MM-DD-HHMM-<hash>
#   to_model: gpt-codex | claude | gemini | kimi
#   specialist: <canonical specialist>
#   source_namespace: coding | security | content | sysmgmt | research | shared
#
# Optional frontmatter:
#   write_scope: [path1, path2]     — conflict-checked against active tasks
#   review_triggers: [blast_radius, adversarial_claim, deciding_measurement, architecture]
#                                    — explicit reasons this change needs review
#   per_task_versioning: true       — rewrites return_artifact to include TASK-ID subdir
#   memory_aperture: rich|focused|default|cold|pool_blind|none (default: default since 2026-08-17 — an omitted field is no longer blind; say cold/pool_blind/none for that)
#   memory_focus: <exact note target> — required only for focused
#
# Exit codes:
#   0  — dispatched successfully
#   1  — blocked (scope conflict, missing fields)
#   2  — dry-run mode (no writes; print what would happen)

set -euo pipefail
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# SQUAD_CODE_ROOT holds shipped code; ACTIVE_REGISTRY stays on mutable VAULT_ROOT.
# Builder/supervisor preserve fixture overrides; otherwise the builder uses
# shipped code so an operated-on vault need not itself be a checkout.
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
SQUAD_CODE_ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)"
ACTIVE_REGISTRY="${VAULT_ROOT}/_state/active-tasks.json"

# Dispatch only from the main checkout. Invoked from a linked worktree this
# script is silently wrong in two independent ways, both measured 2026-08-15:
#
#   1. `_state/` is gitignored, so the worktree has no registry. This script
#      CREATES a stub holding only the task being dispatched, and the write_scope
#      conflict check then compares against ~1 entry instead of the real ~1900 --
#      reporting "no conflicts" because it can no longer see any. A check whose
#      failure is indistinguishable from its success.
#   2. The base branch derives from the checkout this script lives in, so lanes
#      branch off Chrono's working branch. Chrono rebases that branch; the lane's
#      base is then rewritten mid-flight and integration dies with "target branch
#      no longer descends from the worktree base" -- discarding the finished work.
#      Lane 6100 was lost exactly this way.
#
# The main checkout's branch only ever moves forward (board integration appends),
# so it is the one safe base. Nothing legitimate dispatches from a worktree:
# board-supervisor never re-invokes this script, and workers do not dispatch.
if [[ "$(git -C "$VAULT_ROOT" rev-parse --git-dir 2>/dev/null)" \
   != "$(git -C "$VAULT_ROOT" rev-parse --git-common-dir 2>/dev/null)" ]]; then
    _vs_main_checkout="$(cd "$(git -C "$VAULT_ROOT" rev-parse --git-common-dir)/.." && pwd -P)"
    echo "ERROR: refusing to dispatch from a linked worktree (${VAULT_ROOT})." >&2
    echo "  The task registry here is a stub, so write_scope conflict detection would" >&2
    echo "  silently pass, and lanes would branch off a branch that gets rebased." >&2
    echo "  Run from the main checkout instead: ${_vs_main_checkout}" >&2
    exit 1
fi
TOOLKIT="${SQUAD_CODE_ROOT}/shared/dispatch-toolkit.sh"
RUNTIME_MAP="${SQUAD_CODE_ROOT}/shared/specialist-runtime-map.tsv"
CAPABILITY_DISPATCH="${SQUAD_CODE_ROOT}/scripts/python/capability_dispatch.py"
VERIFICATION_CONTRACT_HELPER="${SQUAD_CODE_ROOT}/scripts/python/verification_contract.py"
DISPATCH_CONTEXT_BUILDER="${SQUAD_CODE_ROOT}/scripts/python/dispatch_context_builder.py"
if [[ -f "${VAULT_ROOT}/scripts/python/dispatch_context_builder.py" && ! "${VAULT_ROOT}/scripts/python/dispatch_context_builder.py" -ef "$DISPATCH_CONTEXT_BUILDER" ]]; then
    DISPATCH_CONTEXT_BUILDER="${VAULT_ROOT}/scripts/python/dispatch_context_builder.py"
fi
PLAN_ITEM_BINDING="${SQUAD_CODE_ROOT}/scripts/python/plan_item_binding.py"
DISPATCH_PREFLIGHT="${SQUAD_CODE_ROOT}/scripts/python/dispatch_preflight.py"
if [[ -f "${VAULT_ROOT}/scripts/python/dispatch_preflight.py" && ! "${VAULT_ROOT}/scripts/python/dispatch_preflight.py" -ef "$DISPATCH_PREFLIGHT" ]]; then
    DISPATCH_PREFLIGHT="${VAULT_ROOT}/scripts/python/dispatch_preflight.py"
fi
BOARD_SUPERVISOR="${VAULT_ROOT}/bin/board-supervisor.sh"
SQUAD_DISPATCH_MODE="${SQUAD_DISPATCH_MODE:-board}"
BOARD_PRE_REGISTERED=0 BOARD_BATCH_ADMITTED=0 BOARD_PACKET_FINAL=0 BOARD_PREPARE_TARGET="" BOARD_ADMITTED_INDEX=0
BOARD_ADMITTED_PATHS=() BOARD_ADMITTED_TASK_IDS=() BOARD_ADMITTED_HASHES=()
# SQUAD_BASE_BRANCH derives from the checkout's current branch (on any
# branch, e.g. consolidation, not just a hardcoded v2). A caller-set override
# always wins; only derive when unset. `git branch --show-current` prints
# empty and exits 0 on detached HEAD, and the non-repo case lands here too --
# there is no second signal to fall back on, git already gave its
# authoritative answer. Die rather than guess v2: board-supervisor.sh's own
# detached-HEAD refusal (see its comment below) never fires when reached
# through this script, because this export already leaves it non-empty --
# this is the one place the refusal must actually happen.
if [[ -z "${SQUAD_BASE_BRANCH:-}" ]]; then
    SQUAD_BASE_BRANCH="$(git -C "$VAULT_ROOT" branch --show-current 2>/dev/null || true)"
    if [[ -z "$SQUAD_BASE_BRANCH" ]]; then
        echo "ERROR: SQUAD_BASE_BRANCH is unset and could not be derived from the checkout (detached HEAD or non-repo); refusing to guess a base branch." >&2
        exit 1
    fi
fi
export SQUAD_BASE_BRANCH

# ── helpers ──────────────────────────────────────────────────────────────────

# Armed after registry insertion; the settle helper fails closed unless it can
# prove either queued/no-attempt or an exact descriptor-absent detach abort.
TASK_REGISTERED=0
BOARD_ABORT_PROVEN=0

settle_registered_task_cancelled() {
    [[ "$TASK_REGISTERED" == "1" ]] || return 0
    TASK_REGISTERED=0
    SETTLE_REASON_VALUE="$1" BOARD_ABORT_PROVEN_VALUE="${BOARD_ABORT_PROVEN:-0}" \
        BOARD_ATTEMPT_VALUE="${DELIVERY_ATTEMPT_ID:-}" BOARD_GENERATION_VALUE="${DELIVERY_GENERATION:-0}" \
        python3 - "$VAULT_ROOT" "$TASK_ID" <<'PYEOF' >&2 || true
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
task_id = sys.argv[2]
sys.path.insert(0, str(root / "scripts" / "python"))
import registry_reconciler as rr

now = datetime.now(timezone.utc)
reason = " ".join(os.environ.get("SETTLE_REASON_VALUE", "").split())[:2000]
with rr.locked_registry():
    registry = rr.load_registry()
    entry = registry.get(task_id)
    if not isinstance(entry, dict):
        raise SystemExit(0)
    queued = entry.get("delivery_state") == "queued" and int(entry.get("delivery_attempt_count") or 0) == 0 \
        and not entry.get("claimed_at") and not entry.get("started_at")
    attempt = os.environ.get("BOARD_ATTEMPT_VALUE", "")
    generation = int(os.environ.get("BOARD_GENERATION_VALUE") or 0)
    safe_attempt = attempt.isascii() and 0 < len(attempt) <= 200 and all(char.isalnum() or char in "._-" for char in attempt)
    base = root / "_state" / "board-dispatch" / f"{task_id}.{attempt}"
    history = entry.get("delivery_history")
    exact_board_marker = isinstance(history, list) and any(isinstance(item, dict)
        and item.get("event") == "in-progress" and item.get("transport") == "board-supervisor"
        and item.get("attempt_id") == attempt and type(item.get("generation")) is int
        and item.get("generation") == generation for item in history)
    detach_abort = os.environ.get("BOARD_ABORT_PROVEN_VALUE") == "1" and safe_attempt \
        and entry.get("delivery_state") == "in-progress" and entry.get("delivery_attempt_id") == attempt \
        and type(entry.get("delivery_generation")) is int and entry.get("delivery_generation") == generation \
        and entry.get("claimed_at") \
        and entry.get("started_at") and exact_board_marker and not entry.get("delivery_worker_id") \
        and not any(os.path.lexists(f"{base}{suffix}") for suffix in (".dispatch.json", ".receipt.json"))
    if entry.get("status") != "in-flight" or not (queued or detach_abort):
        raise SystemExit(0)
    rr.mark_delivery_terminal(task_id, entry, now, "never-launched")
    entry["status"] = "cancelled"
    entry["never_launched_reason"] = (
        f"dispatcher aborted before launch: {reason}" if reason
        else "dispatcher aborted before launch"
    )
    entry["completed_at"] = now.isoformat()
    entry["reconciled_at"] = now.isoformat()
    entry["auto_reconciled_at"] = now.isoformat()
    rr.atomic_write(
        rr.REGISTRY_PATH,
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
    )
print(f"  → Released write_scope for {task_id} (cancelled; never launched)")
PYEOF
}

die()  { settle_registered_task_cancelled "$*"; [[ -z "${WORKING_COPY:-}" || ! -f "$WORKING_COPY" || -L "$WORKING_COPY" ]] || rm -f -- "$WORKING_COPY"; echo "ERROR: $*" >&2; exit 1; }
info() { echo "  → $*"; }

# Normalize only an in-vault absolute artifact for blocked settlement.
board_settlement_artifact() {
    local artifact="$1" logical physical
    [[ "$artifact" == /* ]] || { printf '%s\n' "$artifact"; return 0; }
    logical="${VAULT_ROOT%/}"
    physical="$(cd "$VAULT_ROOT" 2>/dev/null && pwd -P)" || physical="$logical"
    case "$artifact" in
        "${logical}/"*)  printf '%s\n' "${artifact#"${logical}/"}" ;;
        "${physical}/"*) printf '%s\n' "${artifact#"${physical}/"}" ;;
        *)               printf '%s\n' "$artifact" ;;
    esac
}

board_host_admit() {
    local packet physical task_id decision digest vector_sha admitted_vector preflight preflight_hash
    local -a admission_args=(--repo-root "$VAULT_ROOT") vector_fields=()
    BOARD_ADMITTED_PATHS=() BOARD_ADMITTED_TASK_IDS=() BOARD_ADMITTED_HASHES=()
    (( $# > 0 )) || die "board host admission requires a candidate vector"
    [[ -f "$DISPATCH_PREFLIGHT" ]] || die "missing dispatch preflight: ${DISPATCH_PREFLIGHT}"
    for packet in "$@"; do
        physical="$(cd "$(dirname "$packet")" && pwd -P)/$(basename "$packet")" || die "cannot resolve admission packet"
        task_id="$(frontmatter_field "$physical" "id")" || die "cannot read admission task id"
        # Stdout is the machine channel consumed below; leave stderr inherited
        # so warnings and refusal diagnostics remain visible without corrupting
        # the single JSON verdict.
        if ! preflight="$(python3 "$DISPATCH_PREFLIGHT" --repo-root "$VAULT_ROOT" --packet "$physical")"; then die "dispatch preflight refused: ${preflight}"; fi
        preflight_hash="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("packet_sha256", ""))' <<<"$preflight")" || die "dispatch preflight returned invalid JSON"
        digest="$(shasum -a 256 "$physical" | awk '{print $1}')" || die "cannot hash admission packet"
        [[ "$digest" == "$preflight_hash" ]] || die "dispatch preflight packet binding changed before host admission"
        info "Dispatch preflight: ${preflight}"
        BOARD_ADMITTED_PATHS+=("$physical") BOARD_ADMITTED_TASK_IDS+=("$task_id") BOARD_ADMITTED_HASHES+=("$digest")
        vector_fields+=("$physical" "$task_id" "$digest")
        admission_args+=(--candidate "$physical" "$task_id" "$digest")
    done
    vector_sha="$(printf '%s\0' "${vector_fields[@]}" | shasum -a 256 | awk '{print $1}')" || die "cannot hash admission vector"
    admission_args+=(--vector-sha256 "$vector_sha")
    if ! decision="$(python3 "${VAULT_ROOT}/scripts/python/host_admission.py" "${admission_args[@]}")"; then die "board host admission queued candidate vector: ${decision}"; fi
    admitted_vector="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("candidate_vector_sha256", ""))' <<<"$decision")" || die "board host admission returned invalid JSON"
    [[ "$admitted_vector" == "$vector_sha" ]] || die "candidate vector binding mismatch"
    info "Board host admission: ${decision}"
}

admitted_packet_bytes() {
    local file="$1" index="${2:-$BOARD_ADMITTED_INDEX}" digest task_id
    [[ "$index" =~ ^[0-9]+$ && -n "${BOARD_ADMITTED_HASHES[$index]+x}" ]] || return 1
    digest="$(shasum -a 256 "$file" | awk '{print $1}')" || return 1; task_id="$(frontmatter_field "$file" "id")" || return 1
    [[ "$digest" == "${BOARD_ADMITTED_HASHES[$index]}" && "$task_id" == "${BOARD_ADMITTED_TASK_IDS[$index]}" ]]
}

dispatch_admitted_child() (
    local pre_registered="$1" packet="$2"
    BOARD_ADMITTED_INDEX="$3" BOARD_BATCH_ADMITTED=1 BOARD_PACKET_FINAL=1 BOARD_PRE_REGISTERED="$pre_registered"
    send_task_main "$packet"
)

prepare_admission_child() (
    BOARD_PREPARE_TARGET="$1"
    send_task_main "$1"
)

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

parse_task_frontmatter() {
    local file="$1"
    python3 - "$file" <<'PYEOF'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    raw = path.read_bytes()
except OSError as exc:
    raise SystemExit(f"cannot read task file: {exc}") from exc
if b"\0" in raw:
    raise SystemExit("task file contains a NUL byte")
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError as exc:
    raise SystemExit("task file is not valid UTF-8") from exc

# Reject every non-newline separator that could split parser interpretations.
LINE_SPLIT_LOOKALIKES = {
    "\v": "\\v",
    "\f": "\\f",
    "\r": "\\r",
    "\x1c": "\\x1c",
    "\x1d": "\\x1d",
    "\x1e": "\\x1e",
    "\x85": "\\x85",
    "\u2028": "U+2028",
    "\u2029": "U+2029",
}


def reject_line_split_lookalikes(region: str) -> None:
    for character, label in LINE_SPLIT_LOOKALIKES.items():
        if character in region:
            raise SystemExit(
                "task frontmatter contains a non-newline line separator "
                f"({label}); frontmatter lines must be separated by \\n only"
            )


lines = text.split("\n")
if not lines or lines[0] != "---":
    raise SystemExit("task file must begin with an exact '---' delimiter")
try:
    close = lines.index("---", 1)
except ValueError as exc:
    # Unterminated either way; naming the separator first keeps the diagnosis
    # honest for a region whose only terminator is a lookalike-prefixed "---".
    reject_line_split_lookalikes(text)
    raise SystemExit("task frontmatter is unterminated") from exc
reject_line_split_lookalikes("\n".join(lines[: close + 1]))

key_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
fields = {}
for line_number, line in enumerate(lines[1:close], start=2):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if line[0].isspace():
        raise SystemExit(
            f"frontmatter line {line_number} must be one top-level key/value pair"
        )
    key, separator, raw_value = line.partition(":")
    if not separator or not key_pattern.fullmatch(key):
        raise SystemExit(f"frontmatter line {line_number} has an invalid key/value shape")
    if key in fields:
        raise SystemExit(f"frontmatter field '{key}' is duplicated")
    if any(ord(character) < 0x20 for character in raw_value):
        raise SystemExit(f"frontmatter field '{key}' contains a control character")
    fields[key] = raw_value.strip()

print(json.dumps(
    {"schema": "send-task-frontmatter/v1", "fields": fields},
    ensure_ascii=False,
    separators=(",", ":"),
))
PYEOF
}

task_frontmatter_field() {
    local field="$1"
    TASK_FRONTMATTER_JSON_VALUE="$TASK_FRONTMATTER_JSON" \
        python3 - "$field" <<'PYEOF'
import json
import os
import sys

snapshot = json.loads(os.environ["TASK_FRONTMATTER_JSON_VALUE"])
value = snapshot["fields"].get(sys.argv[1], "")
if not isinstance(value, str):
    raise SystemExit("task frontmatter snapshot contains a non-string field")
print(value, end="")
PYEOF
}

task_frontmatter_has_field() {
    local field="$1"
    TASK_FRONTMATTER_JSON_VALUE="$TASK_FRONTMATTER_JSON" \
        python3 - "$field" <<'PYEOF'
import json
import os
import sys

snapshot = json.loads(os.environ["TASK_FRONTMATTER_JSON_VALUE"])
raise SystemExit(0 if sys.argv[1] in snapshot["fields"] else 1)
PYEOF
}

# One inline-list parser for every path list a packet may carry (write_scope and
# authorized_delete_paths). A second parser would be a parser differential -- the
# exact class CC-04 removed -- so the field name travels as a message label only.
parse_inline_path_list() {
    local scope_raw="$1" field_label="${2:-write_scope}"
    WRITE_SCOPE_RAW_VALUE="$scope_raw" INLINE_LIST_FIELD_VALUE="$field_label" \
        python3 - <<'PYEOF'
import json
import os

field = os.environ.get("INLINE_LIST_FIELD_VALUE", "write_scope")
raw = os.environ.get("WRITE_SCOPE_RAW_VALUE", "").strip()
if not raw:
    print("[]")
    raise SystemExit(0)
if not (raw.startswith("[") and raw.endswith("]")):
    raise SystemExit("expected a single-line YAML inline list")

items = []
token = []
quote = None
quoted = False
closed_quote = False
escaped = False
for character in raw[1:-1]:
    if quote is not None:
        if escaped:
            token.append(character)
            escaped = False
        elif quote == '"' and character == "\\":
            escaped = True
        elif character == quote:
            quote = None
            closed_quote = True
        else:
            token.append(character)
        continue
    if character in {"'", '"'}:
        if "".join(token).strip() or closed_quote:
            raise SystemExit(f"quotes must wrap an entire {field} item")
        quote = character
        quoted = True
    elif character == ",":
        value = "".join(token).strip()
        if not value and not quoted:
            raise SystemExit(f"{field} contains an empty item")
        items.append(value)
        token = []
        quoted = False
        closed_quote = False
    elif closed_quote:
        if not character.isspace():
            raise SystemExit(f"unexpected data after a quoted {field} item")
    elif ord(character) < 0x20:
        raise SystemExit(f"{field} contains a control character")
    else:
        token.append(character)
if quote is not None or escaped:
    raise SystemExit(f"{field} contains an unterminated quoted item")
value = "".join(token).strip()
if value or quoted:
    items.append(value)
elif items:
    raise SystemExit(f"{field} contains an empty item")
if any(not item for item in items):
    raise SystemExit(f"{field} items must be non-empty")
print(json.dumps(items, ensure_ascii=False, separators=(",", ":")))
PYEOF
}

parse_review_triggers() {
    local raw="$1" parsed
    parsed="$(parse_inline_path_list "$raw" review_triggers)" || return 1
    REVIEW_TRIGGERS_JSON_VALUE="$parsed" python3 - <<'PYEOF'
import json
import os

allowed = {
    "blast_radius",
    "adversarial_claim",
    "deciding_measurement",
    "architecture",
}
items = json.loads(os.environ["REVIEW_TRIGGERS_JSON_VALUE"])
unknown = sorted(set(items) - allowed)
if unknown:
    raise SystemExit(
        "review_triggers contains unknown value(s): " + ", ".join(unknown)
    )
if len(items) != len(set(items)):
    raise SystemExit("review_triggers contains duplicate values")
print(json.dumps(items, separators=(",", ":")))
PYEOF
}

add_review_trigger() {
    local trigger="$1"
    REVIEW_TRIGGERS_JSON_VALUE="$REVIEW_TRIGGERS_JSON" REVIEW_TRIGGER_VALUE="$trigger" \
        python3 - <<'PYEOF'
import json
import os

items = json.loads(os.environ["REVIEW_TRIGGERS_JSON_VALUE"])
trigger = os.environ["REVIEW_TRIGGER_VALUE"]
if trigger not in items:
    items.append(trigger)
print(json.dumps(items, separators=(",", ":")))
PYEOF
}

derive_verification_contract_snapshot() {
    [[ -f "$VERIFICATION_CONTRACT_HELPER" ]] \
        || die "missing verification contract helper: ${VERIFICATION_CONTRACT_HELPER}"
    local admission_json result
    admission_json="$(
        TASK_ID_VALUE="$TASK_ID" RUN_ID_VALUE="$RUN_ID" MODE_VALUE="$MODE" \
        RESULT_TYPE_VALUE="$RESULT_TYPE" TO_MODEL_VALUE="$TO_MODEL" \
        PANEL_ENABLED_VALUE="$PANEL_ENABLED" SWARM_ENABLED_VALUE="$SWARM_ENABLED" CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" \
        AUTHORIZED_DELETE_PATHS_VALUE="$AUTHORIZED_DELETE_PATHS_JSON" \
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

admission = {
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
}

# Present iff non-empty, mirroring the rule the contract enforces: an admission
# carrying an explicit [] re-derives to a contract without the key, so omitting
# it here keeps every no-deletion admission byte-identical to before.
# NOTE: bash lexes this heredoc inside a command substitution, so the count of
# the ASCII apostrophe character in this body must stay EVEN or the whole file
# fails to parse. Avoid contractions here.
authorized_delete_paths = json.loads(
    os.environ.get("AUTHORIZED_DELETE_PATHS_VALUE", "") or "[]"
)
if authorized_delete_paths:
    admission["authorized_delete_paths"] = authorized_delete_paths

print(json.dumps(admission, separators=(",", ":")))
PYEOF
    )" || die "failed to build verification contract admission"
    # Preserve the helper's typed field-level reason on the single failure line.
    if ! result="$(python3 "$VERIFICATION_CONTRACT_HELPER" derive --admission-json "$admission_json" 2>&1)"; then
        die "typed verification contract admission failed: $(
            printf '%s' "$result" | tr '\n' ' ' | sed 's/  */ /g; s/ *$//'
        )"
    fi
    VERIFICATION_CONTRACT_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["verification_contract"], separators=(",",":"), ensure_ascii=False))' <<<"$result")"
    VERIFICATION_CONTRACT_SHA256="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verification_contract_sha256"])' <<<"$result")"
    AUTHOR_FAMILY="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["verification_contract"]["author_family"])' <<<"$result")"
}

inject_verification_contract() {
    local contract_copy
    contract_copy=$(mktemp "${TASK_FILE%.md}.verification.md.XXXXXX")
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

send_task_main() {
TASK_FILE=""
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --nudge-pane|--nudge-unavailable) die "pane nudge options are unsupported" ;;
        --panel) PANEL_ENABLED=true; PANEL_MEMBERS_RAW="$2"; shift 2 ;;
        --panel-policy) PANEL_POLICY="$2"; shift 2 ;;
        --panel-quorum) PANEL_QUORUM="$2"; shift 2 ;;
        --panel-timeout) PANEL_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --fanout) FANOUT_ENABLED=true; shift ;;
        --panel-assignment) PANEL_ASSIGNMENTS+=("$2"); shift 2 ;;
        --swarm) SWARM_ENABLED=true; SWARM_LANES_RAW="$2"; shift 2 ;;
        --swarm-timeout) SWARM_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --subswarm-directive|--subswarm-assignment) \
            die "subswarm dispatch is unsupported; use board swarm or fan-out" ;;
        --dry-run)    DRY_RUN=true; shift ;;
        *)            TASK_FILE="$1"; shift ;;
    esac
done

[[ -z "$TASK_FILE" ]] && die "Usage: $0 <task-file> [--dry-run] [--panel ... | --swarm lanes]"
[[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"
[[ "$SQUAD_DISPATCH_MODE" == "board" ]] \
    || die "pane transport is unsupported; expected SQUAD_DISPATCH_MODE=board"
[[ "$BOARD_PRE_REGISTERED" == "0" || "$BOARD_PRE_REGISTERED" == "1" ]] \
    || die "BOARD_PRE_REGISTERED is an internal boolean"
[[ "$BOARD_PACKET_FINAL" == "0" || "$BOARD_PACKET_FINAL" == "1" ]] \
    || die "BOARD_PACKET_FINAL is an internal boolean"

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
if $PANEL_ENABLED && ! $FANOUT_ENABLED; then
    die "board dispatch supports single, swarm, and fan-out packets; review panels remain lane-native"
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

if ! TASK_FRONTMATTER_JSON="$(parse_task_frontmatter "$TASK_FILE" 2>&1)"; then
    die "invalid task frontmatter: ${TASK_FRONTMATTER_JSON}"
fi

TASK_ID=$(task_frontmatter_field "id")
TO_LEAD=$(task_frontmatter_field "to_lead")
COMPAT_NAMESPACE=$(task_frontmatter_field "compatibility_namespace")
# shellcheck disable=SC2034  # retained compatibility metadata for legacy packets
RUN_ID=$(task_frontmatter_field "run_id")
RESULT_TYPE=$(task_frontmatter_field "result_type")
WRITE_SCOPE_RAW=$(task_frontmatter_field "write_scope")
AUTHORIZED_DELETE_PATHS_RAW=$(task_frontmatter_field "authorized_delete_paths")
PER_TASK_VERSIONING=$(task_frontmatter_field "per_task_versioning")
OWNING_LEAD=$(task_frontmatter_field "owning_lead")
SPECIALIST=$(task_frontmatter_field "specialist")
PRIMARY_RUNTIME=$(task_frontmatter_field "primary_runtime")
TO_MODEL=$(task_frontmatter_field "to_model")
SOURCE_NAMESPACE=$(task_frontmatter_field "source_namespace")
REVIEW_MODEL=$(task_frontmatter_field "review_model")
MANDATORY_REVIEW=$(task_frontmatter_field "mandatory_review")
REVIEW_TRIGGERS_RAW=$(task_frontmatter_field "review_triggers")
REVIEW_TRIGGERS_PRESENT=false
task_frontmatter_has_field "review_triggers" && REVIEW_TRIGGERS_PRESENT=true
REVIEW_CLASS=$(task_frontmatter_field "review_class")
MODEL_OVERRIDE_REASON=$(task_frontmatter_field "model_override_reason")
DIRECT_LANE_WORK_ALLOWED=$(task_frontmatter_field "direct_lane_work_allowed")
LEGACY_LEAD_DIRECT_ALLOWED=$(task_frontmatter_field "lead_direct_allowed")
PARALLEL_SAFE=$(task_frontmatter_field "parallel_safe")
PANEL_MEMBER_WRITE_SCOPE=$(task_frontmatter_field "panel_member_write_scope")
RETURN_ARTIFACT=$(task_frontmatter_field "return_artifact")
PLAN_ITEM_IDS_RAW=$(task_frontmatter_field "plan_item_ids") PHASE=$(task_frontmatter_field "phase")
MODE=$(task_frontmatter_field "mode")
CAPABILITY=$(task_frontmatter_field "capability")
CAPABILITY_DEGRADATION_ACK=$(task_frontmatter_field "capability_degradation_ack")
MEMORY_APERTURE=$(task_frontmatter_field "memory_aperture")
MEMORY_FOCUS=$(task_frontmatter_field "memory_focus")
CAPABILITY_SNAPSHOT_JSON=""
CAPABILITY_PRESENT=false
AUTHOR_FAMILY=""
VERIFICATION_CONTRACT_JSON=""
VERIFICATION_CONTRACT_SHA256=""
PRESERVE_DISPATCHED_CONTRACT=false
task_frontmatter_has_field "capability" && CAPABILITY_PRESENT=true
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
if [[ "$BOARD_PACKET_FINAL" != "1" ]]; then
    for RESERVED_CAPABILITY_FIELD in \
        capability_id capability_card_path capability_card_sha256 \
        capability_derived_state capability_gates \
        author_family verification_contract verification_contract_sha256 \
        dispatch_kind swarm_parent_id swarm_spec swarm_spec_sha256 swarm_role \
        swarm_member_result swarm_diff_path; do
        ! task_frontmatter_has_field "$RESERVED_CAPABILITY_FIELD" \
            || die "task packet may not pre-populate dispatcher-owned field '${RESERVED_CAPABILITY_FIELD}'"
    done
else
    [[ "$BOARD_BATCH_ADMITTED" == "1" ]] \
        || die "final board packet lacks batch admission"
    if [[ "$BOARD_PRE_REGISTERED" == "1" ]]; then
        [[ "$(task_frontmatter_field "dispatch_kind")" == "swarm" \
            && "$(task_frontmatter_field "swarm_role")" == "member" ]] \
            || die "pre-registered admitted child is not a swarm member"
    else
        [[ -n "$(task_frontmatter_field "fanout_parent_id")" \
            && -n "$(task_frontmatter_field "fanout_member_id")" ]] \
            || die "admitted final child is not a fan-out member"
    fi
    AUTHOR_FAMILY="$(task_frontmatter_field "author_family")"
    VERIFICATION_CONTRACT_JSON="$(task_frontmatter_field "verification_contract")"
    VERIFICATION_CONTRACT_SHA256="$(task_frontmatter_field "verification_contract_sha256")"
    [[ -n "$AUTHOR_FAMILY" && -n "$VERIFICATION_CONTRACT_JSON" \
        && "$VERIFICATION_CONTRACT_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || die "pre-registered swarm child contract is incomplete"
    PRESERVE_DISPATCHED_CONTRACT=true
fi
if $CAPABILITY_PRESENT && [[ -z "$CAPABILITY" ]]; then
    die "task packet carries an empty capability field; use a valid slug or 'none'"
fi
# A5 mode consolidation (10 → 2): resolve a legacy domain-mode capability id
# (content/outreach/research/maintenance) to its canonical folded project id up
# front, so a retired-mode packet dispatches through the project lifecycle with
# its re-anchored gates intact. capability_dispatch.py resolves too, so this is
# fail-open: on any resolver error the originals are kept and the callee still
# canonicalizes. The single source of truth is validate_capabilities.CAPABILITY_ALIASES.
if $CAPABILITY_PRESENT && [[ -n "$CAPABILITY" && "$CAPABILITY" != "none" ]]; then
    CAP_ALIAS_LINE="$(
        VAULT_ROOT="$VAULT_ROOT" ALIAS_MODE="$MODE" ALIAS_CAP="$CAPABILITY" python3 - <<'PYEOF' 2>/dev/null || true
import os, sys
sys.path.insert(0, os.path.join(os.environ["VAULT_ROOT"], "scripts", "python"))
try:
    from validate_capabilities import resolve_capability_alias
    mode, ref, aliased = resolve_capability_alias(
        os.environ.get("ALIAS_MODE", ""), os.environ.get("ALIAS_CAP", "")
    )
    if aliased:
        print(f"{mode}\t{ref}")
except Exception:
    pass
PYEOF
    )"
    if [[ -n "$CAP_ALIAS_LINE" ]]; then
        CANON_MODE="${CAP_ALIAS_LINE%%$'\t'*}"
        CANON_CAP="${CAP_ALIAS_LINE#*$'\t'}"
        info "legacy capability id resolved: mode=${MODE} capability=${CAPABILITY} -> mode=${CANON_MODE} capability=${CANON_CAP}"
        MODE="$CANON_MODE"
        CAPABILITY="$CANON_CAP"
    fi
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
if $REVIEW_TRIGGERS_PRESENT && [[ -z "$REVIEW_TRIGGERS_RAW" ]]; then
    die "review_triggers must be an explicit inline list; use [] for none"
elif [[ -z "$REVIEW_TRIGGERS_RAW" ]]; then
    REVIEW_TRIGGERS_RAW="[]"
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
# Legacy modes remain warnings here; the typed contract/launch boundary decides.
case "$MODE" in
    bounty|project) ;;
    "") printf 'WARNING: task packet has no mode; expected bounty|project. No verification contract will be derived and the launch will fail.\n' >&2 ;;
    *) printf 'WARNING: mode %s is not bounty|project. If no verification contract is derived, the launch fails with a misleading "missing verification_contract" error.\n' "$MODE" >&2 ;;
esac
[[ -n "$MEMORY_APERTURE" ]] || MEMORY_APERTURE="default" # validation-only mirror of resolve_memory_aperture() in scripts/python/dispatch_context_builder.py; pinned by scripts/python/tests/test_dispatch_memory_default.py
case "$MEMORY_APERTURE" in
    rich|focused|default|cold|pool_blind|none) ;;
    *) die "invalid memory_aperture '${MEMORY_APERTURE}'" ;;
esac
if [[ "$MEMORY_APERTURE" == "focused" ]]; then
    [[ -n "$MEMORY_FOCUS" && "$MEMORY_FOCUS" != *$'\n'* && "$MEMORY_FOCUS" != *$'\r'* ]] \
        || die "focused memory requires one exact memory_focus"
elif [[ -n "$MEMORY_FOCUS" ]]; then
    die "memory_focus is valid only with memory_aperture focused"
fi
case "$SOURCE_NAMESPACE" in
    coding|security|content|sysmgmt|research|shared|chrono) ;;
    *) die "invalid source_namespace '${SOURCE_NAMESPACE}'." ;;
esac
# compatibility_namespace is interpolated into the mailbox path. Shared/Chrono
# coordinator packets may choose a different mailbox, but it must still be one
# of the real compatibility mailboxes — never an arbitrary path component.
case "$COMPAT_NAMESPACE" in
    coding|security|content|sysmgmt|research) ;;
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
if ! REVIEW_TRIGGERS_JSON="$(parse_review_triggers "$REVIEW_TRIGGERS_RAW" 2>&1)"; then
    die "invalid review_triggers: ${REVIEW_TRIGGERS_JSON}"
fi
# Typed review classes already state why review is required, so preserve their
# stronger existing gates while recording them in the four-trigger vocabulary.
if [[ "$REVIEW_CLASS" == "security-finding" ]]; then
    REVIEW_TRIGGERS_JSON="$(add_review_trigger adversarial_claim)"
elif [[ "$REVIEW_CLASS" == "factual" ]]; then
    REVIEW_TRIGGERS_JSON="$(add_review_trigger deciding_measurement)"
elif ! $REVIEW_TRIGGERS_PRESENT && [[ "$MANDATORY_REVIEW" == "true" ]]; then
    # Compatibility for old prepared packets is loud and conservative. New
    # wrapper-authored packets always carry the explicit field.
    printf 'WARNING: legacy mandatory_review:true packet lacks review_triggers; treating it as adversarial_claim. Add the explicit field.\n' >&2
    REVIEW_TRIGGERS_JSON="$(add_review_trigger adversarial_claim)"
elif ! $REVIEW_TRIGGERS_PRESENT; then
    printf 'WARNING: legacy packet lacks review_triggers; treating it as an explicit empty list.\n' >&2
fi
REVIEW_TRIGGER_COUNT="$(REVIEW_TRIGGERS_JSON_VALUE="$REVIEW_TRIGGERS_JSON" python3 -c 'import json,os; print(len(json.loads(os.environ["REVIEW_TRIGGERS_JSON_VALUE"])))')"
if [[ "$REVIEW_TRIGGER_COUNT" != "0" && "$MANDATORY_REVIEW" != "true" ]]; then
    die "review_triggers requires mandatory_review:true"
fi
if [[ "$REVIEW_TRIGGER_COUNT" == "0" && "$MANDATORY_REVIEW" == "true" && "$SWARM_ENABLED" == "false" ]]; then
    die "mandatory_review:true requires at least one review_triggers value"
fi
if [[ "$MANDATORY_REVIEW" == "true" ]]; then
    [[ "$REVIEW_MODEL" != "none" ]] \
        || die "mandatory_review:true requires a distinct-family review_model"
    [[ "$REVIEW_MODEL" != "$TO_MODEL" ]] \
        || die "mandatory_review:true requires review_model to differ from to_model"
fi
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

if ! WRITE_SCOPE_JSON="$(parse_inline_path_list "$WRITE_SCOPE_RAW" write_scope 2>&1)"; then
    die "invalid write_scope: ${WRITE_SCOPE_JSON}"
fi

# Refuse a structural path HERE rather than after the worker has done the work.
# worktree_isolation refuses any worker commit touching a structural segment
# (.git, .githooks) regardless of write_scope -- and that refusal discards the
# ENTIRE lane's output, not just the offending file. Granting the path in
# write_scope therefore reads as authorization and behaves as a guaranteed total
# loss. Measured 2026-08-15: lane 6200 lost a full documentation pass this way.
# The segment set is imported, never restated, so this cannot drift from the
# enforcer it is predicting.
if ! STRUCTURAL_SCOPE_ERR="$(
    SEND_TASK_WRITE_SCOPE_JSON="$WRITE_SCOPE_JSON" \
    SEND_TASK_CODE_ROOT="$SQUAD_CODE_ROOT" python3 - <<'PYEOF' 2>&1
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["SEND_TASK_CODE_ROOT"]) / "scripts" / "python"))
from worktree_isolation import _CBSE_STRUCTURAL_SEGMENTS  # single home for this fact

offenders = sorted(
    {
        f"{entry} (segment: {part})"
        for entry in json.loads(os.environ["SEND_TASK_WRITE_SCOPE_JSON"])
        for part in Path(entry).parts
        if part in _CBSE_STRUCTURAL_SEGMENTS
    }
)
if offenders:
    print("; ".join(offenders), end="")
    sys.exit(1)
PYEOF
)"; then
    die "write_scope names a structural path a worker can never commit: ${STRUCTURAL_SCOPE_ERR}. \
The isolation layer refuses ANY worker commit touching these segments regardless of scope, and the \
refusal discards the whole lane's work. Make the change Chrono-side and drop the path from write_scope."
fi

# Carry deletion authorization as data; verification_contract owns every path rule.
if ! AUTHORIZED_DELETE_PATHS_JSON="$(
    parse_inline_path_list "$AUTHORIZED_DELETE_PATHS_RAW" authorized_delete_paths 2>&1
)"; then
    die "invalid authorized_delete_paths: ${AUTHORIZED_DELETE_PATHS_JSON}"
fi

# Resolve one binding fact: an explicit field wins by presence; otherwise a
# detailed phase is derived. The canonical validator rejects free-form phases,
# while bare phase groupings stay admitted but unbound.
declare -a PLAN_ITEM_PHASE_ARGS=(); task_frontmatter_has_field "plan_item_ids" || PLAN_ITEM_PHASE_ARGS=(--phase="$PHASE")
if ! PLAN_ITEM_IDS_JSON="$(parse_inline_path_list "$PLAN_ITEM_IDS_RAW" plan_item_ids 2>&1)" \
    || ! PLAN_ITEM_IDS_JSON="$(python3 "$PLAN_ITEM_BINDING" declare --json "$PLAN_ITEM_IDS_JSON" "${PLAN_ITEM_PHASE_ARGS[@]}" 2>&1)"; then
    die "invalid plan_item_ids: ${PLAN_ITEM_IDS_JSON}"
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
    [[ "$WRITE_SCOPE_JSON" == "[]" ]] \
        || die "swarm-v1 is read-only: packet write_scope must be []"
    [[ "$SWARM_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] \
        || die "swarm timeout must be a positive integer"
    (( SWARM_TIMEOUT_SECONDS <= 86400 )) || die "swarm timeout exceeds 86400 seconds"
    [[ -z "$(task_frontmatter_field "dispatch_kind")" ]] \
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
    REVIEW_TRIGGERS_JSON='["adversarial_claim"]'
    SWARM_LANES_CSV="$(IFS=,; echo "${SWARM_LANES[*]}")"
    SWARM_CHILD_IDS_CSV="$(IFS=,; echo "${SWARM_CHILD_IDS[*]}")"
    SWARM_MEMBER_ROLES_CSV="$(IFS=,; echo "${SWARM_MEMBER_ROLES[*]}")"
    SWARM_SPEC_JSON="$(TASK_SHA="$(shasum -a 256 "$TASK_FILE" | awk '{print $1}')" \
        TASK_ID_VALUE="$TASK_ID" SPECIALIST_VALUE="$SPECIALIST" \
        SWARM_LANES_VALUE="$SWARM_LANES_CSV" SWARM_ROLES_VALUE="$SWARM_MEMBER_ROLES_CSV" \
        SWARM_TIMEOUT_SECONDS_VALUE="$SWARM_TIMEOUT_SECONDS" python3 - <<'PYEOF'
import json
import os

print(json.dumps({
    "schema_version": "swarm-spec/v1",
    "parent_task_id": os.environ["TASK_ID_VALUE"],
    "specialist": os.environ["SPECIALIST_VALUE"],
    "lanes": os.environ["SWARM_LANES_VALUE"].split(","),
    "member_roles": os.environ["SWARM_ROLES_VALUE"].split(","),
    "quorum": "all",
    "timeout_seconds": int(os.environ["SWARM_TIMEOUT_SECONDS_VALUE"]),
    "write_scope": [],
    "task_packet_sha256": os.environ["TASK_SHA"],
    "mandatory_review": True,
    "review_triggers": ["adversarial_claim"],
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
    [[ -z "$(task_frontmatter_field "dispatch_kind")" ]] \
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
    PANEL_LIMIT=3
    $FANOUT_ENABLED && PANEL_LIMIT=12
    (( PANEL_COUNT >= 2 && PANEL_COUNT <= PANEL_LIMIT )) \
        || die "panel-v1 requires 2-${PANEL_LIMIT} members for this transport, got ${PANEL_COUNT}"

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
    if [[ "$PANEL_MEMBER_WRITE_SCOPE" =~ departments/.*/outbox ]]; then
        die "panel member write scope may not include outbox: ${PANEL_MEMBER_WRITE_SCOPE}"
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
    [[ -n "$MAP_OPERATOR_GATE" ]] || die "specialist '${SPECIALIST}' has no operator_gate in shared/specialist-runtime-map.tsv"
    MAP_NAMESPACE="$(map_field "$SPECIALIST" 2 || true)"
    MAP_SAFETY="$(map_field "$SPECIALIST" 4 || true)"

    [[ -z "$MAP_MODEL" ]] && die "specialist '${SPECIALIST}' is missing from shared/specialist-runtime-map.tsv"
    [[ -z "$MAP_SAFETY" ]] && die "specialist '${SPECIALIST}' has no safety_level in shared/specialist-runtime-map.tsv"

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
    if [[ "$MANDATORY_REVIEW" == "true" ]]; then
        info "cross-family review required by ${REVIEW_TRIGGERS_JSON}: ${SPECIALIST} (${TO_MODEL}) will stay review-required until a ${REVIEW_MODEL} review response lands."
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

if [[ "$BOARD_PACKET_FINAL" == "1" ]]; then
    : # The exact source packet was validated before final controller injection.
elif $SWARM_ENABLED; then
    for lane in "${SWARM_LANES[@]}"; do
        validate_task_capabilities "$TASK_FILE" "$lane" \
            || die "task references unavailable or unverified live capability for swarm lane ${lane}"
    done
else
    validate_task_capabilities "$TASK_FILE" "$TO_MODEL" || die "task references unavailable or unverified live capability"
fi

# Warn when declared writes other than the return artifact will not be promoted.
# stderr not discarded (was 2>/dev/null): this is the warner about silent
# write-scope omissions, and a swallowed crash here would BE that outcome.
warn_unpromoted_write_scope() {
    python3 - "$TASK_FILE" "$VAULT_ROOT" <<'PYWARN' || true
import re, subprocess, sys
from pathlib import Path
task, root = Path(sys.argv[1]), sys.argv[2]
try:
    text = task.read_text()
except Exception:
    sys.exit(0)
def field(name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""
ret = field("return_artifact")
ws  = field("write_scope").strip("[]")
paths = [p.strip().strip("'\"") for p in ws.split(",") if p.strip()]
extra = [p for p in paths if p and p != ret]
if not extra:
    sys.exit(0)
ignored = []
for p in extra:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=root, capture_output=True)
        if r.returncode == 0:
            ignored.append(p)
    except Exception:
        pass
print(
    "predispatch notice: only `return_artifact` is promoted from the worktree. "
    f"{len(extra)} other write_scope path(s) will NOT be promoted automatically"
    + (f" and {len(ignored)} of them are gitignored so the omission is silent" if ignored else "")
    + ": " + ", ".join(extra)
    + ". Sweep the attempt worktree before settling this task.",
)
PYWARN
}
# Warn before low disk produces unrelated toolchain failures.
warn_low_disk() {
    local free_mb
    free_mb=$(df -Pm "$VAULT_ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
    [[ "$free_mb" =~ ^[0-9]+$ ]] || return 0   # fail-open: unreadable df never blocks a dispatch
    if (( free_mb < 2048 )); then
        printf 'predispatch notice: only %s MB free on the volume holding %s. Toolchains that link binaries (go test, forge, cargo) fail silently below ~2 GB and the lane will report UNDETERMINED for an unrelated reason. Reclaim before dispatching.\n' \
            "$free_mb" "$VAULT_ROOT"
    fi
}

warn_low_disk
warn_unpromoted_write_scope

if $PRESERVE_DISPATCHED_CONTRACT; then
    info "Using dispatcher-pinned final packet verification contract"
elif [[ ( "$MODE" == "project" || "$MODE" == "bounty" || "$MODE" == "advisory" ) && "$SWARM_ENABLED" == "false" ]]; then
    derive_verification_contract_snapshot
    info "Verification contract: version=verification-contract/v1 sha256=${VERIFICATION_CONTRACT_SHA256}"
    if [[ "$AUTHORIZED_DELETE_PATHS_JSON" != "[]" ]]; then
        info "Deletion authorization pinned into the contract: ${AUTHORIZED_DELETE_PATHS_JSON}"
    fi
elif [[ "$AUTHORIZED_DELETE_PATHS_JSON" != "[]" ]]; then
    # No contract is derived on this path, so the authorization has nowhere to
    # land. Dispatching anyway would deliver a packet that reads as authorized
    # and carries no deletion authority at all -- refuse instead of silently
    # dropping an operator approval. (advisory mode reaches the builder above
    # and is refused there: advisory work cannot authorize deletions.)
    die "authorized_delete_paths requires a typed non-swarm packet (mode: project or bounty); got mode='${MODE}' swarm=${SWARM_ENABLED}"
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

if [[ "$WRITE_SCOPE_JSON" != "[]" && -f "$ACTIVE_REGISTRY" ]]; then
    info "Checking write_scope for conflicts..."
    if ! CONFLICT_RESULT=$(
        BOARD_PRE_REGISTERED_VALUE="$BOARD_PRE_REGISTERED" \
        WRITE_SCOPE_JSON_VALUE="$WRITE_SCOPE_JSON" \
        python3 - "$ACTIVE_REGISTRY" "$TASK_ID" <<'PYEOF'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    registry = json.load(f)

scope_paths = json.loads(os.environ["WRITE_SCOPE_JSON_VALUE"])
task_id = sys.argv[2]

conflicts = []
for active_id, active in registry.items():
    if os.environ.get("BOARD_PRE_REGISTERED_VALUE") == "1" and active_id == task_id:
        continue
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

# Board-native fan-out lowers every advisory assignment into an independent
# ordinary board packet. The parent remains the sole coordinator/outbox owner.
BOARD_FANOUT_CHILD_IDS_CSV=""
if $PANEL_ENABLED && $FANOUT_ENABLED; then
    BOARD_FANOUT_ROOT="${VAULT_ROOT}/_state/board-dispatch"
    mkdir -p "$BOARD_FANOUT_ROOT"
    BOARD_FANOUT_BUILD_DIR="$(mktemp -d "${BOARD_FANOUT_ROOT}/${TASK_ID}.fanout.XXXXXX")"
    BOARD_FANOUT_BUILD_ARGS=()
    for assignment in "${PANEL_ASSIGNMENTS[@]}"; do
        BOARD_FANOUT_BUILD_ARGS+=(--assignment "$assignment")
    done
    BOARD_FANOUT_PACKETS_JSON="$(
        python3 "$DISPATCH_CONTEXT_BUILDER" build-fanout \
            --repo-root "$VAULT_ROOT" \
            --parent-task-file "$TASK_FILE" \
            --output-dir "$BOARD_FANOUT_BUILD_DIR" \
            --verification-contract "$VERIFICATION_CONTRACT_JSON" \
            "${BOARD_FANOUT_BUILD_ARGS[@]}"
    )" || die "board fan-out member packet construction failed"
    declare -a BOARD_FANOUT_PACKETS=()
    while IFS= read -r member_packet; do
        [[ -n "$member_packet" ]] && BOARD_FANOUT_PACKETS+=("$member_packet")
    done < <(
        python3 -c 'import json,sys; print(*json.load(sys.stdin), sep="\n")' \
            <<<"$BOARD_FANOUT_PACKETS_JSON"
    )
    (( ${#BOARD_FANOUT_PACKETS[@]} == PANEL_COUNT )) \
        || die "board fan-out member packet count changed"
    for member_packet in "${BOARD_FANOUT_PACKETS[@]}"; do
        prepare_admission_child "$member_packet" \
            || die "board fan-out final packet preparation failed"
    done
    BOARD_BATCH_ARGS=()
    for member_packet in "${BOARD_FANOUT_PACKETS[@]}"; do
        BOARD_BATCH_ARGS+=(--task-file "$member_packet")
    done
    BOARD_BATCH_RESULT="$(
        python3 "$DISPATCH_CONTEXT_BUILDER" schedule-batch \
            --repo-root "$VAULT_ROOT" \
            --concurrency "$PANEL_COUNT" \
            "${BOARD_BATCH_ARGS[@]}"
    )" || die "board fan-out scheduler preflight failed"
    BOARD_BATCH_WAIT="$(
        python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["must_wait"]))' \
            <<<"$BOARD_BATCH_RESULT"
    )"
    [[ -z "$BOARD_BATCH_WAIT" ]] \
        || die "board fan-out scheduler rejected unsafe assignments: ${BOARD_BATCH_WAIT}"
    board_host_admit "${BOARD_FANOUT_PACKETS[@]}"
    declare -a BOARD_FANOUT_CHILD_IDS=()
    for fanout_index in "${!BOARD_FANOUT_PACKETS[@]}"; do
        member_packet="${BOARD_FANOUT_PACKETS[$fanout_index]}"
        child_id="$(frontmatter_field "$member_packet" "id")"
        BOARD_FANOUT_CHILD_IDS+=("$child_id")
        dispatch_admitted_child 0 "$member_packet" "$fanout_index" \
            || die "board fan-out child launch failed: ${child_id}"
    done
    BOARD_FANOUT_CHILD_IDS_CSV="$(IFS=,; echo "${BOARD_FANOUT_CHILD_IDS[*]}")"
    info "Board fan-out detached ${PANEL_COUNT} fresh advisory CLIs after scheduler admission"
    BOARD_FANOUT_DEADLINE=$(( $(date +%s) + PANEL_TIMEOUT_SECONDS ))
    while true; do
        BOARD_FANOUT_TERMINAL_COUNT="$(
            CHILD_IDS_VALUE="$BOARD_FANOUT_CHILD_IDS_CSV" python3 - "$ACTIVE_REGISTRY" <<'PYEOF'
import json
import os
import sys

children = [item for item in os.environ["CHILD_IDS_VALUE"].split(",") if item]
with open(sys.argv[1], encoding="utf-8") as stream:
    registry = json.load(stream)
terminal = 0
for child in children:
    entry = registry.get(child)
    if isinstance(entry, dict) and entry.get("delivery_state") == "terminal":
        terminal += 1
print(terminal)
PYEOF
        )"
        (( BOARD_FANOUT_TERMINAL_COUNT == PANEL_COUNT )) && break
        (( $(date +%s) < BOARD_FANOUT_DEADLINE )) \
            || die "board fan-out children exceeded the ${PANEL_TIMEOUT_SECONDS}s collection deadline"
        sleep 2
    done
    BOARD_FANOUT_RESULT_BUNDLE="${BOARD_FANOUT_BUILD_DIR}/member-results.md"
    CHILD_PACKETS_VALUE="$(printf '%s\n' "${BOARD_FANOUT_PACKETS[@]}")" \
        python3 - "$VAULT_ROOT" "$BOARD_FANOUT_RESULT_BUNDLE" <<'PYEOF'
import os
from pathlib import Path
import re
import sys

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
sections = ["## Board-native fan-out settled member bundle\n"]
for raw_packet in os.environ["CHILD_PACKETS_VALUE"].splitlines():
    packet = Path(raw_packet)
    text = packet.read_text(encoding="utf-8")
    task_id = re.search(r"(?m)^id:\s*(\S+)\s*$", text).group(1)
    artifact_relative = re.search(
        r"(?m)^return_artifact:\s*(\S+)\s*$", text
    ).group(1)
    artifact = root / artifact_relative
    sections.append(f"### {task_id}\n")
    if artifact.is_file() and not artifact.is_symlink():
        data = artifact.read_text(encoding="utf-8")
        if len(data.encode("utf-8")) > 256 * 1024:
            raise SystemExit(f"fan-out artifact exceeds bundle limit: {task_id}")
        sections.append(data.rstrip() + "\n")
    else:
        sections.append("No bridged artifact was available; treat this member as a gap.\n")
payload = "\n".join(sections)
if len(payload.encode("utf-8")) > 2 * 1024 * 1024:
    raise SystemExit("fan-out result bundle exceeds aggregate limit")
descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
PYEOF
    info "Board fan-out collected ${PANEL_COUNT} terminal child results for parent handoff"
fi

# Swarm-v1 publishes independent child packets and one controller ledger record.
# The preflight above validates the complete lane/adapter set before this branch.
if $SWARM_ENABLED; then
    mkdir -p "${VAULT_ROOT}/_state/board-dispatch"
    SWARM_BUILD_DIR="$(mktemp -d "${VAULT_ROOT}/_state/board-dispatch/${TASK_ID}.swarm.XXXXXX")"
    SWARM_BUILD_DIR_VALUE="$SWARM_BUILD_DIR" SWARM_SPEC_VALUE="$SWARM_SPEC_JSON" \
    SWARM_SPEC_SHA_VALUE="$SWARM_SPEC_SHA256" SWARM_LANES_VALUE="$SWARM_LANES_CSV" \
    SWARM_ROLES_VALUE="$SWARM_MEMBER_ROLES_CSV" CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" \
    MAP_OPERATOR_GATE_VALUE="$MAP_OPERATOR_GATE" COMPAT_NAMESPACE_VALUE="$COMPAT_NAMESPACE" \
    REVIEW_CLASS_VALUE="$REVIEW_CLASS" \
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
sys.path.insert(0, str(helper_path.parent))
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
    "mandatory_review", "review_triggers", "review_model", "model_override_reason", "compatibility_namespace",
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
            f"write_scope: [{artifact.rsplit('/', 1)[0]}/]",
            f"return_artifact: {artifact}",
            "mandatory_review: true",
            "review_triggers: [adversarial_claim]",
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
        "review_triggers": ["adversarial_claim"],
        "review_class": os.environ["REVIEW_CLASS_VALUE"],
        "parallel_safe": parallel_safe,
        "direct_lane_work_allowed": direct_allowed,
        "dispatched_at": now.isoformat(),
        "return_artifact": artifact,
        "write_scope": [artifact.rsplit("/", 1)[0] + "/"],
        "status": "in-flight",
        "delivery_state": "queued",
        "delivery_attempt_id": attempt_id,
        "delivery_generation": 1,
        "delivery_lane": lane,
        "delivery_attempt_count": 0,
        "delivery_last_attempt_at": None,
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
    "review_triggers": ["adversarial_claim"],
    "review_class": os.environ["REVIEW_CLASS_VALUE"],
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
        bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$lane" "$MODE" "$SPECIALIST" >> "${SWARM_BUILD_DIR}/${child_id}.md"
    done

    BOARD_BATCH_ARGS=()
    BOARD_BATCH_TASKS=()
    for child_id in "${SWARM_CHILD_IDS[@]}"; do
        batch_task="${SWARM_BUILD_DIR}/${child_id}.md"
        BOARD_BATCH_TASKS+=("$batch_task")
        BOARD_BATCH_ARGS+=(--task-file "$batch_task")
    done
    BOARD_BATCH_RESULT="$(
        python3 "$DISPATCH_CONTEXT_BUILDER" schedule-batch \
            --repo-root "$VAULT_ROOT" \
            --concurrency "$SWARM_COUNT" \
            "${BOARD_BATCH_ARGS[@]}"
    )" || die "board swarm scheduler preflight failed"
    BOARD_BATCH_WAIT="$(
        python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["must_wait"]))' \
            <<<"$BOARD_BATCH_RESULT"
    )"
    [[ -z "$BOARD_BATCH_WAIT" ]] \
        || die "board swarm scheduler rejected unsafe children: ${BOARD_BATCH_WAIT}"
    board_host_admit "${BOARD_BATCH_TASKS[@]}"
    info "Board swarm scheduler admitted ${SWARM_COUNT} isolated children"

    # Publish the complete admitted packet vector before registering it. There is
    # no specialist inbox consumer: fresh CLIs are launched explicitly below, so
    # an unregistered packet is inert. Hard-linking a synced inbox temp gives us
    # no-clobber publication; an exact prior packet is a safe crash/restart replay.
    for swarm_publish_index in "${!SWARM_CHILD_IDS[@]}"; do
        child_id="${SWARM_CHILD_IDS[$swarm_publish_index]}"
        child_source="${SWARM_BUILD_DIR}/${child_id}.md"
        child_dest="${INBOX}/${child_id}.md"
        if [[ -e "$child_dest" || -L "$child_dest" ]]; then
            [[ -f "$child_dest" && ! -L "$child_dest" ]] \
                && cmp -s "$child_source" "$child_dest" \
                && admitted_packet_bytes "$child_dest" "$swarm_publish_index" \
                || die "refusing to replace conflicting swarm child packet: ${child_id}"
            info "Reused exact swarm child ${COMPAT_NAMESPACE}/inbox/${child_id}.md"
            continue
        fi
        child_temp="$(mktemp "${INBOX}/.${child_id}.tmp.XXXXXX")"
        if ! cp "$child_source" "$child_temp" \
            || ! cmp -s "$child_source" "$child_temp" \
            || ! admitted_packet_bytes "$child_temp" "$swarm_publish_index" \
            || ! python3 - "$child_temp" <<'PYEOF'
import os
import sys

with open(sys.argv[1], "rb") as stream:
    os.fsync(stream.fileno())
PYEOF
        then
            rm -f "$child_temp"
            die "failed to stage swarm child ${child_id}"
        fi
        if ! ln "$child_temp" "$child_dest"; then
            [[ -f "$child_dest" && ! -L "$child_dest" ]] \
                && cmp -s "$child_source" "$child_dest" \
                && admitted_packet_bytes "$child_dest" "$swarm_publish_index" \
                || { rm -f "$child_temp"; die "refusing to replace conflicting swarm child packet: ${child_id}"; }
        fi
        rm -f "$child_temp"
        python3 - "$INBOX" <<'PYEOF' \
            || die "failed to sync inbox after publishing swarm child ${child_id}"
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PYEOF
        [[ -f "$child_dest" && ! -L "$child_dest" ]] \
            && cmp -s "$child_source" "$child_dest" \
            && admitted_packet_bytes "$child_dest" "$swarm_publish_index" \
            || die "published swarm child changed before registration: ${child_id}"
        info "Published swarm child ${COMPAT_NAMESPACE}/inbox/${child_id}.md"
    done
    for admission_index in "${!SWARM_CHILD_IDS[@]}"; do
        admitted_packet_bytes "${INBOX}/${SWARM_CHILD_IDS[$admission_index]}.md" "$admission_index" \
            || die "swarm candidate vector changed before registry publication"
    done
    PARENT_ENTRY_JSON="$(<"${SWARM_BUILD_DIR}/parent-entry.json")"
    MEMBER_ENTRIES_JSON="$(<"${SWARM_BUILD_DIR}/member-entries.json")"
    "${VAULT_ROOT}/bin/registry-reconciler.sh" --register-swarm "$TASK_ID" \
        --parent-entry-json "$PARENT_ENTRY_JSON" --member-entries-json "$MEMBER_ENTRIES_JSON" \
        || die "atomic swarm registry registration failed"
    SWARM_LAUNCH_FAILURES=()
    for swarm_child_index in "${!SWARM_CHILD_IDS[@]}"; do
        child_id="${SWARM_CHILD_IDS[$swarm_child_index]}"
        if ! child_launch_state="$(python3 - "$VAULT_ROOT" "$TASK_ID" "$child_id" <<'PYEOF'
import os
import sys

root, parent_id, child_id = sys.argv[1:]
os.environ["VAULT_ROOT"] = root
sys.path.insert(0, os.path.join(root, "scripts", "python"))
import registry_reconciler as rr

with rr.locked_registry():
    entry = rr.load_registry().get(child_id)
if not isinstance(entry, dict) or entry.get("swarm_role") != "member" or entry.get("swarm_parent_id") != parent_id:
    raise SystemExit("swarm child registry identity is invalid")
status, state = entry.get("status"), entry.get("delivery_state")
if status == "in-flight" and state == "queued":
    print("launch")
elif status == "in-flight" and state == "in-progress":
    print("in-progress")
elif state == "terminal" or status != "in-flight":
    print(f"terminal:{status}")
else:
    raise SystemExit("swarm child delivery state is invalid")
PYEOF
        )"; then
            SWARM_LAUNCH_FAILURES+=("${child_id}:invalid-state")
            continue
        fi
        case "$child_launch_state" in
            launch)
                dispatch_admitted_child 1 "${INBOX}/${child_id}.md" "$swarm_child_index" \
                    || SWARM_LAUNCH_FAILURES+=("${child_id}:launch")
                ;;
            in-progress)
                info "Skipping already-started swarm child ${child_id}"
                ;;
            terminal:*)
                info "Skipping settled swarm child ${child_id} (${child_launch_state#terminal:})"
                ;;
            *)
                SWARM_LAUNCH_FAILURES+=("${child_id}:invalid-state")
                ;;
        esac
    done
    (( ${#SWARM_LAUNCH_FAILURES[@]} == 0 )) \
        || die "board swarm child launch/replay failures: $(IFS=,; echo "${SWARM_LAUNCH_FAILURES[*]}")"
    for build_file in "${SWARM_BUILD_DIR}"/*; do rm -f "$build_file"; done
    rmdir "$SWARM_BUILD_DIR"
        echo "✓ Board swarm ${TASK_ID} → ${SWARM_LANES_CSV} (${SWARM_COUNT} children launched or already settled; review required)"
    exit 0
fi

# ── ITEM 4: inject toolkit + no-delete rule ───────────────────────────────────
# shared/dispatch-toolkit.sh emits per-namespace tool/specialist roster AND the
# hard no-delete rule block. Append to a working copy of the task file.

if [[ "$BOARD_PACKET_FINAL" == "1" ]]; then
    ACTUAL_TASK_FILE="$TASK_FILE"
else
WORKING_COPY=$(mktemp "${TASK_FILE%.md}.working.md.XXXXXX")
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

This is an opt-in panel dispatch. Panel is a dispatch shape, not a mode (`shared/routing.md` § Dispatch shapes); its coordinator protocol is these instructions, in full. Follow them as written — do not go looking for a separate panel mode file.

1. Validate every named member and create `_state/runtime/lane-activity/<task-id>.json` with `bin/panel-activity.sh create` before spawning; add `--fanout` when `panel_mode: fanout`. Review-panel member IDs are specialist names; fan-out member IDs are the injected `member-N` values and MUST be used for activity updates and result attribution.
2. Spawn all members in parallel, never serially. Reserve the coordinator as the fourth thread.
3. Members may use only the packet's read/write scope and MUST NEVER write `departments/*/outbox/`.
4. Claude requires coordinator-pull plus deterministic `_state/scratch/<task-id>/<member-id>.md` file return. Codex uses native parent-message return primarily; a scratch file is optional for oversized results.
5. Normalize only returns already available to the coordinator; never make a blocking receive. Update activity state on spawn, return, failure, refusal, and timeout.
6. Run the mandatory bounded collection loop exactly as specified in this step: drain immediately available returns, then call `timeout 5 bin/panel-activity.sh poll --task-id <id> --quorum <panel_quorum> --timeout <panel_timeout_seconds>` exactly once per iteration. For `outcome: waiting`, use only a bounded short sleep (`timeout 2 sleep 1`) before repeating. Stop immediately on `quorum_met` or `timed_out`. The first poll persists a monotonic deadline; deadline expiry atomically marks every queued/running member `timed_out`. Numeric quorum closure also atomically marks any remaining queued/running members `timed_out` as explicit gaps. Guard the complete shell-side collection phase with `timeout` no greater than `panel_timeout_seconds + 15`, and guard every potentially blocking step with at most two minutes. A late, failed, refused, or timed-out member is a coverage gap and never blocks the outbox.
7. Aggregate by deterministic collation followed by evidence synthesis. Preserve attribution, unique findings, contradictions, refusals, failures, and limitations. Never majority-vote or fake unanimity.
8. The coordinator alone writes exactly one canonical outbox. Close/archive the activity record in a finally path. One parent task remains one delivery attempt and one artifact.

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
    if $FANOUT_ENABLED; then
        cat >> "$WORKING_COPY" <<EOF

## Board-native fan-out coordinator override

The controller already scheduler-gated, registered, and detached these fresh board children:
\`${BOARD_FANOUT_CHILD_IDS_CSV}\`.

Do not spawn lane-native panel members, create pane nudges, or poll paths outside this
worktree. The non-model controller waited for terminal child states and embedded the bounded,
deterministically ordered member bundle below. Synthesize from that evidence, treating a
missing artifact as an explicit coverage gap. You remain the sole writer of the parent
response envelope.
EOF
        cat "$BOARD_FANOUT_RESULT_BUNDLE" >> "$WORKING_COPY"
    fi
else
    cp "$TASK_FILE" "$WORKING_COPY"
fi


if [[ -n "$CAPABILITY_SNAPSHOT_JSON" ]]; then
    CAPABILITY_CARD_PATH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["capability_card_path"])' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    CAPABILITY_GATES="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["capability_gates"], separators=(",",":")))' <<<"$CAPABILITY_SNAPSHOT_JSON")"
    if ! $PRESERVE_DISPATCHED_CONTRACT; then
    SNAPSHOT_COPY=$(mktemp "${TASK_FILE%.md}.capability.md.XXXXXX")
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
fi

if [[ -n "$VERIFICATION_CONTRACT_SHA256" ]] && ! $PRESERVE_DISPATCHED_CONTRACT; then
    inject_verification_contract
fi

if [[ -x "$TOOLKIT" ]]; then
    bash "$TOOLKIT" "$COMPAT_NAMESPACE" "$TO_MODEL" "$MODE" "$SPECIALIST" >> "$WORKING_COPY"
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
        VERSIONED_COPY=$(mktemp "${TASK_FILE%.md}.versioned.md.XXXXXX")
        sed "s|return_artifact:.*|return_artifact: ${NEW_ART}|" "$WORKING_COPY" > "$VERSIONED_COPY"
        ACTUAL_TASK_FILE="$VERSIONED_COPY"
        RETURN_ARTIFACT="$NEW_ART"
        info "Per-task versioning: return_artifact → ${NEW_ART}"
    fi
fi
fi

if [[ -n "$BOARD_PREPARE_TARGET" ]]; then
    [[ "$BOARD_PREPARE_TARGET" == "$TASK_FILE" \
        && "$(cd "$(dirname "$TASK_FILE")" && pwd -P)" == "$(cd "$BOARD_FANOUT_BUILD_DIR" && pwd -P)" ]] \
        || die "fan-out preparation target is outside its build directory"
    PREPARED_TEMP=$(mktemp "${TASK_FILE}.final.XXXXXX")
    cp "$ACTUAL_TASK_FILE" "$PREPARED_TEMP" \
        && mv -f "$PREPARED_TEMP" "$TASK_FILE" \
        || die "failed to materialize final fan-out packet"
    rm -f "$WORKING_COPY"
    [[ "$ACTUAL_TASK_FILE" != "$WORKING_COPY" ]] && rm -f "$ACTUAL_TASK_FILE"
    return 0
fi

if [[ "$BOARD_PACKET_FINAL" != "1" ]]; then
    board_host_admit "$ACTUAL_TASK_FILE"
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
if [[ "$BOARD_PRE_REGISTERED" == "1" ]]; then
    TASK_FILE_PHYS="$(cd "$(dirname "$TASK_FILE")" && pwd -P)/$(basename "$TASK_FILE")"
    DEST_PHYS="$(cd "$(dirname "$DEST")" && pwd -P)/$(basename "$DEST")"
    [[ "$TASK_FILE_PHYS" == "$DEST_PHYS" && -f "$DEST" ]] \
        || die "pre-registered board child must already be the canonical inbox packet"
    admitted_packet_bytes "$TASK_FILE" || die "pre-registered packet bytes were not admitted"
elif ! INBOX_TEMP=$(mktemp "${INBOX}/.${TASK_ID}.tmp.XXXXXX") \
    || ! cp "$ACTUAL_TASK_FILE" "$INBOX_TEMP" \
    || ! cmp -s "$ACTUAL_TASK_FILE" "$INBOX_TEMP" \
    || ! admitted_packet_bytes "$INBOX_TEMP" \
    || ! python3 - "$INBOX_TEMP" <<'PYEOF'
import os
import sys

with open(sys.argv[1], "rb") as inbox_temp:
    os.fsync(inbox_temp.fileno())
PYEOF
then
    die "failed to deliver ${TASK_ID} to ${INBOX}"
fi
if [[ "$BOARD_PRE_REGISTERED" != "1" ]] && ! mv -f "$INBOX_TEMP" "$DEST"; then
    die "failed to deliver ${TASK_ID} to ${INBOX}"
fi
if [[ "$BOARD_PRE_REGISTERED" != "1" ]] && ! python3 - "$INBOX" <<'PYEOF'
import os
import sys

directory_fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PYEOF
then
    die "failed to sync inbox directory after delivering ${TASK_ID}"
fi
if [[ "$BOARD_PACKET_FINAL" != "1" ]]; then
    rm -f "$WORKING_COPY"
    [[ "$ACTUAL_TASK_FILE" != "$WORKING_COPY" ]] && rm -f "$ACTUAL_TASK_FILE"
fi
if [[ "$BOARD_PRE_REGISTERED" == "1" ]]; then
    info "Using pre-registered board child ${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"
else
    info "Copied to ${COMPAT_NAMESPACE}/inbox/${TASK_ID}.md"
fi

# ── ITEM 7: active-task registry ─────────────────────────────────────────────
# Build the entry here, then register it through the shared reconciler so entry
# creation and response reconciliation use the same flock + atomic rename.

if [[ "$BOARD_PRE_REGISTERED" == "1" ]]; then
    REGISTRY_ENTRY_JSON="$(python3 - "$ACTIVE_REGISTRY" "$TASK_ID" "$RETURN_ARTIFACT" "$TO_MODEL" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    entry = json.load(stream).get(sys.argv[2])
if (
    not isinstance(entry, dict)
    or entry.get("return_artifact") != sys.argv[3]
    or entry.get("to_model") != sys.argv[4]
    or entry.get("delivery_state") != "queued"
    or not entry.get("delivery_attempt_id")
    or int(entry.get("delivery_generation") or 0) <= 0
):
    raise SystemExit("pre-registered board child identity or state is invalid")
print(json.dumps(entry, separators=(",", ":")))
PYEOF
    )" || die "pre-registered board child lookup failed"
    TASK_REGISTERED=1
    info "Pre-registered board child validated"
elif REGISTRY_ENTRY_JSON="$(
    WRITE_SCOPE_JSON_VALUE="$WRITE_SCOPE_JSON" \
    COMPAT_NAMESPACE_VALUE="$COMPAT_NAMESPACE" SPECIALIST_VALUE="$SPECIALIST" \
    TO_MODEL_VALUE="$TO_MODEL" SOURCE_NAMESPACE_VALUE="$SOURCE_NAMESPACE" \
    REVIEW_MODEL_VALUE="$REVIEW_MODEL" MANDATORY_REVIEW_VALUE="$MANDATORY_REVIEW" \
    REVIEW_TRIGGERS_VALUE="$REVIEW_TRIGGERS_JSON" \
    REVIEW_CLASS_VALUE="$REVIEW_CLASS" PARALLEL_SAFE_VALUE="$PARALLEL_SAFE" \
    DIRECT_LANE_WORK_ALLOWED_VALUE="$DIRECT_LANE_WORK_ALLOWED" \
    RETURN_ARTIFACT_VALUE="$RETURN_ARTIFACT" \
    PANEL_ENABLED_VALUE="$PANEL_ENABLED" PANEL_MEMBERS_CSV_VALUE="$PANEL_MEMBERS_CSV" \
    PANEL_MEMBER_IDS_CSV_VALUE="$PANEL_MEMBER_IDS_CSV" FANOUT_ENABLED_VALUE="$FANOUT_ENABLED" \
    CAPABILITY_SNAPSHOT_VALUE="$CAPABILITY_SNAPSHOT_JSON" \
    AUTHOR_FAMILY_VALUE="$AUTHOR_FAMILY" VERIFICATION_CONTRACT_VALUE="$VERIFICATION_CONTRACT_JSON" \
    VERIFICATION_CONTRACT_SHA256_VALUE="$VERIFICATION_CONTRACT_SHA256" \
    python3 - <<'PYEOF'
import json
import os
import uuid
from datetime import datetime, timezone

scope = json.loads(os.environ["WRITE_SCOPE_JSON_VALUE"])

dispatched_at = datetime.now(timezone.utc).isoformat()
delivery_attempt_id = f"d-{uuid.uuid4().hex}"
entry = {
    "compatibility_namespace": os.environ["COMPAT_NAMESPACE_VALUE"],
    "specialist": os.environ["SPECIALIST_VALUE"],
    "to_model": os.environ["TO_MODEL_VALUE"],
    "source_namespace": os.environ["SOURCE_NAMESPACE_VALUE"],
    "review_model": os.environ["REVIEW_MODEL_VALUE"],
    "mandatory_review": os.environ["MANDATORY_REVIEW_VALUE"],
    "review_triggers": json.loads(os.environ["REVIEW_TRIGGERS_VALUE"]),
    "review_class": os.environ["REVIEW_CLASS_VALUE"],
    "parallel_safe": os.environ["PARALLEL_SAFE_VALUE"],
    "direct_lane_work_allowed": os.environ["DIRECT_LANE_WORK_ALLOWED_VALUE"],
    "dispatched_at": dispatched_at,
    "return_artifact": os.environ.get("RETURN_ARTIFACT_VALUE", ""),
    "write_scope": scope,
    "status": "in-flight",
    "delivery_state": "queued",
    "delivery_attempt_id": delivery_attempt_id,
    "delivery_generation": 1,
    "delivery_lane": os.environ["TO_MODEL_VALUE"],
    "delivery_attempt_count": 0,
    "delivery_last_attempt_at": None,
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
        "lane": os.environ["TO_MODEL_VALUE"],
    }],
    "dispatch_kind": (
        "panel" if os.environ["PANEL_ENABLED_VALUE"] == "true" else "single"
    ),
    "panel_members": [
        member
        for member in os.environ["PANEL_MEMBERS_CSV_VALUE"].split(",")
        if member
    ],
    "panel_member_ids": [
        member_id
        for member_id in os.environ["PANEL_MEMBER_IDS_CSV_VALUE"].split(",")
        if member_id
    ],
    "panel_mode": (
        "fanout" if os.environ["FANOUT_ENABLED_VALUE"] == "true" else "review"
    ) if os.environ["PANEL_ENABLED_VALUE"] == "true" else "single",
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
print(json.dumps(entry, separators=(",", ":")))
PYEOF
)" && "${VAULT_ROOT}/bin/registry-reconciler.sh" \
    --register-task "$TASK_ID" --entry-json "$REGISTRY_ENTRY_JSON"; then
    # The task now holds its write_scope: arm synchronous release on any die.
    TASK_REGISTERED=1
    info "Active-task registry updated under shared lock"
else
    die "active-task registry update failed; refusing unreceipted delivery"
fi
DELIVERY_ATTEMPT_ID=""
DELIVERY_GENERATION=""
    DELIVERY_ATTEMPT_ID="$(
        python3 -c 'import json,sys; print(json.load(sys.stdin)["delivery_attempt_id"])' \
            <<<"$REGISTRY_ENTRY_JSON"
    )"
    DELIVERY_GENERATION="$(
        python3 -c 'import json,sys; print(json.load(sys.stdin)["delivery_generation"])' \
            <<<"$REGISTRY_ENTRY_JSON"
    )"

# ── central dispatch log ─────────────────────────────────────────────────────

DISPATCH_LOG="${VAULT_ROOT}/_state/dispatch-log.jsonl"
mkdir -p "$(dirname "${DISPATCH_LOG}")"
printf '{"ts":"%s","task_id":"%s","model_lane":"%s","source_namespace":"%s","compatibility_namespace":"%s","specialist":"%s","review_model":"%s","mandatory_review":"%s","return_artifact":"%s"}\n' \
    "$(date -u +%FT%TZ)" "${TASK_ID}" "${TO_MODEL}" "${SOURCE_NAMESPACE}" "${COMPAT_NAMESPACE}" "${SPECIALIST}" "${REVIEW_MODEL}" "${MANDATORY_REVIEW}" \
    "${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md" \
    >> "${DISPATCH_LOG}"
info "Dispatch log updated"

# ── dispatch through selected reversible rail ─────────────────────────────────

    [[ -f "$DISPATCH_CONTEXT_BUILDER" ]] \
        || die "missing board context builder: ${DISPATCH_CONTEXT_BUILDER}"
    [[ -x "$BOARD_SUPERVISOR" ]] \
        || die "missing board supervisor: ${BOARD_SUPERVISOR}"
    BOARD_STATE_DIR="${VAULT_ROOT}/_state/board-dispatch"
    mkdir -p "$BOARD_STATE_DIR"
    BOARD_CONTEXT="${BOARD_STATE_DIR}/${TASK_ID}.${DELIVERY_ATTEMPT_ID}.context.json"
    BOARD_LOG="${BOARD_STATE_DIR}/${TASK_ID}.${DELIVERY_ATTEMPT_ID}.log"
    BOARD_RECEIPT="${BOARD_STATE_DIR}/${TASK_ID}.${DELIVERY_ATTEMPT_ID}.receipt.json"
    BOARD_METADATA="${BOARD_STATE_DIR}/${TASK_ID}.${DELIVERY_ATTEMPT_ID}.dispatch.json"
    # Every settlement consumer below (here and inside the detached supervisor)
    # passes this to `dispatch_context_builder blocked`, which takes only a
    # repo-relative path.
    BOARD_SETTLEMENT_ARTIFACT="$(board_settlement_artifact "$RETURN_ARTIFACT")"
    if ! BOARD_BUILD_ERROR="$(
        python3 "$DISPATCH_CONTEXT_BUILDER" build \
            --repo-root "$VAULT_ROOT" \
            --task-file "$DEST" \
            --attempt-id "$DELIVERY_ATTEMPT_ID" \
            --generation "$DELIVERY_GENERATION" \
            --output "$BOARD_CONTEXT" 2>&1
    )"; then
        BOARD_LANE="${TO_MODEL/gpt-codex/codex}"
        BOARD_FAILURE_ARGS=()
        if [[ "$BOARD_BUILD_ERROR" == *"error: trusted lane executable is unavailable: "* ]]; then
            BOARD_FAILURE_ARGS=(--failure-class cli_missing)
        fi
        if ! python3 "$DISPATCH_CONTEXT_BUILDER" blocked \
            --repo-root "$VAULT_ROOT" \
            --task-id "$TASK_ID" \
            --lane "$BOARD_LANE" \
            --return-artifact "$BOARD_SETTLEMENT_ARTIFACT" \
            --compatibility-namespace "$COMPAT_NAMESPACE" \
            ${BOARD_FAILURE_ARGS[@]+"${BOARD_FAILURE_ARGS[@]}"} \
            --attempt-id "$DELIVERY_ATTEMPT_ID" \
            --generation "$DELIVERY_GENERATION" \
            --reason "context builder failed: ${BOARD_BUILD_ERROR}" >/dev/null; then
            die "board context build and blocked settlement both failed: ${BOARD_BUILD_ERROR}"
        fi
        RESPONSE_MIN_AGE_SECONDS=0 \
            "${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$TASK_ID" \
            >/dev/null || true
        die "board context builder failed: ${BOARD_BUILD_ERROR}"
    fi
    ( set -o noclobber; : > "$BOARD_LOG" ) \
        || die "refusing to overwrite existing board log"
    [[ ! -e "$BOARD_RECEIPT" && ! -L "$BOARD_RECEIPT" ]] \
        || die "refusing to overwrite existing board receipt"
    BOARD_FAILURE_MARKER="${BOARD_STATE_DIR}/${TASK_ID}.${DELIVERY_ATTEMPT_ID}.settlement-error"
    if ! BOARD_START_ERROR="$(
        python3 - "$VAULT_ROOT" "$TASK_ID" "$DELIVERY_ATTEMPT_ID" \
            "$DELIVERY_GENERATION" <<'PYEOF' 2>&1
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

root = Path(sys.argv[1])
task_id = sys.argv[2]
attempt_id = sys.argv[3]
generation = int(sys.argv[4])
sys.path.insert(0, str(root / "scripts" / "python"))
import registry_reconciler as rr

now = datetime.now(timezone.utc).isoformat()
with rr.locked_registry():
    registry = rr.load_registry()
    entry = registry.get(task_id)
    if not isinstance(entry, dict):
        raise RuntimeError("board task is absent from the active registry")
    if (
        entry.get("status") != "in-flight"
        or entry.get("delivery_state") != "queued"
        or entry.get("delivery_attempt_id") != attempt_id
        or int(entry.get("delivery_generation") or 0) != generation
    ):
        raise RuntimeError("board task registry identity or queued state changed")
    entry["delivery_state"] = "in-progress"
    entry["delivery_attempt_count"] = int(entry.get("delivery_attempt_count") or 0) + 1
    entry["delivery_last_attempt_at"] = now
    entry["claimed_at"] = entry.get("claimed_at") or now
    entry["started_at"] = entry.get("started_at") or now
    history = entry.setdefault("delivery_history", [])
    history.extend(
        (
            {
                "event": "board-claimed",
                "at": now,
                "attempt_id": attempt_id,
                "generation": generation,
            },
            {
                "event": "in-progress",
                "at": now,
                "attempt_id": attempt_id,
                "generation": generation,
                "transport": "board-supervisor",
            },
        )
    )
    rr.atomic_write(
        rr.REGISTRY_PATH,
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
    )
PYEOF
    )"; then
        BOARD_LANE="${TO_MODEL/gpt-codex/codex}"
        if ! python3 "$DISPATCH_CONTEXT_BUILDER" blocked \
            --repo-root "$VAULT_ROOT" \
            --task-id "$TASK_ID" \
            --lane "$BOARD_LANE" \
            --return-artifact "$BOARD_SETTLEMENT_ARTIFACT" \
            --compatibility-namespace "$COMPAT_NAMESPACE" \
            --reason "board delivery start failed: ${BOARD_START_ERROR}" >/dev/null; then
            die "board delivery start and blocked settlement both failed: ${BOARD_START_ERROR}"
        fi
        RESPONSE_MIN_AGE_SECONDS=0 \
            "${VAULT_ROOT}/bin/registry-reconciler.sh" --task-id "$TASK_ID" \
            >/dev/null || true
        die "board delivery start failed: ${BOARD_START_ERROR}"
    fi
    BOARD_LANE="${TO_MODEL/gpt-codex/codex}"
    BOARD_PID="$(
        BOARD_PLAN_ITEM_IDS_JSON="$PLAN_ITEM_IDS_JSON" \
        python3 - "$BOARD_SUPERVISOR" "${VAULT_ROOT}/scripts/python" \
            "$BOARD_METADATA" "$TASK_ID" "$DELIVERY_ATTEMPT_ID" \
            "$DELIVERY_GENERATION" "$BOARD_CONTEXT" "$BOARD_LOG" \
            "$BOARD_RECEIPT" "$BOARD_FAILURE_MARKER" "$DISPATCH_CONTEXT_BUILDER" \
            "$VAULT_ROOT" "$TASK_ID" "$BOARD_LANE" "$BOARD_SETTLEMENT_ARTIFACT" \
            "$COMPAT_NAMESPACE" "${VAULT_ROOT}/bin/registry-reconciler.sh" <<'PYEOF'
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, sys.argv[2])
from board_process_truth import atomic_write_json, observe_process, utc_now

metadata_path = sys.argv[3]
environment = os.environ.copy()
environment["BOARD_DISPATCH_DESCRIPTOR_PATH"] = metadata_path
child = None
try:
    with open("/dev/null", "rb") as stdin, open("/dev/null", "ab") as output:
        child = subprocess.Popen(
            ["/bin/bash", sys.argv[1], "detached-launch", *sys.argv[7:]],
            stdin=stdin, stdout=output, stderr=output, close_fds=True,
            start_new_session=True, env=environment,
        )
    identity = None
    for _ in range(100):
        identity = observe_process(child.pid)
        if identity is not None:
            break
        if child.poll() is not None:
            raise RuntimeError("detached board supervisor exited before identity capture")
        time.sleep(0.01)
    if identity is None or identity["pgid"] != child.pid:
        raise RuntimeError("detached board supervisor process identity is unavailable")
    payload = {
        "schema": "board-dispatch-process/v2",
        "task_id": sys.argv[4],
        "attempt_id": sys.argv[5],
        "generation": int(sys.argv[6]),
        "created_at": utc_now(),
        **identity,
        "context_path": sys.argv[7],
        "log_path": sys.argv[8],
        "receipt_path": sys.argv[9],
    }
    # By environment, not argv: sys.argv[7:] is the exact detached-supervisor
    # argument list, and a slot inserted ahead of it would shift every parameter.
    declared = json.loads(os.environ.get("BOARD_PLAN_ITEM_IDS_JSON") or "[]")
    if declared:
        payload["plan_item_ids"] = declared
    if not atomic_write_json(metadata_path, payload, exclusive=True):
        raise RuntimeError("board dispatch descriptor already exists")
except Exception:
    if child is not None:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    if not os.path.lexists(metadata_path):
        print("BOARD_DETACH_ABORT_PROVEN")
    raise
print(child.pid)
PYEOF
    )" || { [[ "$BOARD_PID" != "BOARD_DETACH_ABORT_PROVEN" ]] || BOARD_ABORT_PROVEN=1; die "failed to detach board supervisor"; }
    [[ "$BOARD_PID" =~ ^[0-9]+$ ]] \
        || die "detached board supervisor returned an invalid PID"
    info "Board dispatch detached pid=${BOARD_PID} context=${BOARD_CONTEXT} log=${BOARD_LOG}"

echo "✓ Dispatched ${TASK_ID} → ${TO_MODEL}/${SPECIALIST} (${COMPAT_NAMESPACE} mailbox)"

# Print the watcher command required by sessions without a board alert.
cat <<WATCHER
  ATTACH A WATCHER — this session gets no board alert when the lane lands:
    OUT=${VAULT_ROOT}/departments/${COMPAT_NAMESPACE}/outbox/${TASK_ID}-response.md
    for i in \$(seq 1 200); do
      [ -f "\$OUT" ] && { echo LANDED; exit 0; }
      s=\$(python3 -c "import json;print(json.load(open('${VAULT_ROOT}/_state/active-tasks.json')).get('${TASK_ID}',{}).get('status','READ_FAILED'))" 2>/dev/null || echo READ_FAILED)
      case "\$s" in
        READ_FAILED|"") : ;;            # unreadable registry is NOT a verdict — keep waiting
        in-flight)      : ;;
        *)              echo "TERMINAL status=\$s"; exit 0 ;;
      esac
      sleep 20
    done; echo TIMEOUT; exit 3
  Run it BACKGROUNDED so its exit re-invokes the session. One watcher per batch is enough.
WATCHER
}

send_task_main "$@"
