#!/usr/bin/env bash
# Atomically claim one delivery generation before executing its task packet.

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
TASK_ID="${1:-}"
ATTEMPT_ID="${2:-}"

if [[ -z "$TASK_ID" || -z "$ATTEMPT_ID" || ( $# -ne 2 && $# -ne 6 ) ]]; then
    echo "usage: $0 TASK-ID ATTEMPT-ID [WORKER-ID WORKER-EPOCH LEASE-GENERATION WORKER-LANE]" >&2
    exit 2
fi

CONTROL_STATE="${VIBESQUAD_CONTROL_STATE:-${VAULT_ROOT}/_state/failover}"
CONTROL_LEDGER="${CONTROL_STATE}/ledgers/${TASK_ID}.json"
CONTROL=(uv run --with-requirements "${VAULT_ROOT}/daemon/requirements.txt" python "${VAULT_ROOT}/bin/failover-control.py")
[[ -n "${VIBESQUAD_CONTROL_STATE:-}" ]] && CONTROL+=(--state-root "$VIBESQUAD_CONTROL_STATE")

# If the conservative failover ledger exists, fence stale generations before
# touching the active registry. The active-registry claim remains the first
# authoritative mutation; the failover mirror is idempotently repairable.
if [[ -f "$CONTROL_LEDGER" ]]; then
    command -v uv >/dev/null 2>&1 || {
        echo "CLAIM REJECTED: uv is required to mirror the failover receipt" >&2
        exit 1
    }
    ledger="$("${CONTROL[@]}" inspect --task-id "$TASK_ID")"
    current_attempt="$(LEDGER_JSON="$ledger" python3 -c 'import json,os; print(json.loads(os.environ["LEDGER_JSON"])["current_attempt_id"])')"
    if [[ "$current_attempt" != "$ATTEMPT_ID" ]]; then
        echo "CLAIM REJECTED: stale failover attempt ${ATTEMPT_ID}; current is ${current_attempt}" >&2
        exit 3
    fi
fi

claim_args=(--claim-task "$TASK_ID" --attempt-id "$ATTEMPT_ID")
if [[ $# -eq 6 ]]; then
    claim_args+=(
        --worker-id "$3"
        --worker-epoch "$4"
        --lease-generation "$5"
        --worker-lane "$6"
    )
fi
[[ -n "${DELIVERY_NOW:-}" ]] && claim_args+=(--now "$DELIVERY_NOW")
claim="$("${VAULT_ROOT}/bin/registry-reconciler.sh" "${claim_args[@]}")"

if [[ -f "$CONTROL_LEDGER" ]]; then
    "${CONTROL[@]}" claim --task-id "$TASK_ID" --attempt-id "$ATTEMPT_ID" >/dev/null
fi

echo "CLAIMED: ${claim}"
