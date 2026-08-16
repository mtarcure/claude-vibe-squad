#!/usr/bin/env bash
# Atomically claim one delivery generation before executing its task packet.

set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
TASK_ID="${1:-}"
ATTEMPT_ID="${2:-}"

if [[ -z "$TASK_ID" || -z "$ATTEMPT_ID" || ( $# -ne 2 && $# -ne 6 ) ]]; then
    echo "usage: $0 TASK-ID ATTEMPT-ID [WORKER-ID WORKER-EPOCH LEASE-GENERATION WORKER-LANE]" >&2
    exit 2
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

echo "CLAIMED: ${claim}"
