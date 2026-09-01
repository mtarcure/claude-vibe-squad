#!/usr/bin/env bash
# bin/validate-specialists.sh — Validate specialist schema and routing references.
# - Required sections present
# - Cited MCPs are in api-catalog verified-yes entries
# - Model-lane native agent adapters exist for every runtime-map specialist
# - Cited skills exist in local catalog
# - Peer-specialist refs resolve

# The maintained schema engine is a single cached Python parse; the capability-
# home semantic gate runs immediately after it. A 460-line historical shell
# implementation used to sit below the exit at the foot of this file, where it
# could never execute; it was removed 2026-08-06.
#
# No `set -e`: each python call's $? is captured to decide the exit code, and
# -e would abort before the capture.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VALIDATION_ROOT="${VAULT_ROOT:-${REPO_ROOT}}"

# Name the interpreter that will actually run. The 2026-08-31 settlement outage
# cost five tasks partly because nothing said WHICH python3 ran, so a failure
# that was really "the caller gave us macOS 3.9" read as "the repository is
# unhealthy". One line, and it makes that class of failure self-describing.
_vs_python="$(command -v python3 2>/dev/null || echo '<none>')"
echo "INFO: python3 -> ${_vs_python} ($("${_vs_python}" -V 2>&1))" >&2

python3 "${REPO_ROOT}/scripts/python/validate_specialists.py" \
    --root "${VALIDATION_ROOT}" "$@"
specialist_status=$?

capability_args=()
if [[ "${SQUAD_CI_HOST_INDEPENDENT:-0}" == "1" ]]; then
    capability_args=(--only boundary,parity,index,source,required)
    echo "INFO: capability-home gate is using the host-independent CI subset; live existence remains enforced by the local pre-commit hook." >&2
elif [[ ! -f "${VALIDATION_ROOT}/shared/registries/skill-tool-registry.tsv" ]]; then
    # Published candidate: the private registry is deliberately withheld, and so
    # is the pre-strip baseline commit that `boundary` and `parity` read. Those
    # two checks cannot establish anything here, and `require_baseline_commit`
    # is configuration-fatal by design -- correctly, because on the maintainer
    # tree an absent baseline means real corruption. Select them out rather than
    # weakening that refusal, so a contributor in a public clone can still
    # commit. Everything else, including the leak guard, still runs.
    capability_args=(--only index,source,required,existence)
    echo "INFO: private registry not published in this tree — running the public subset of the capability-home gate (boundary/parity need the withheld baseline commit)." >&2
fi

# `"${capability_args[@]}"` on an EMPTY array is an unbound-variable error under
# `set -u` in bash 3.2, which is what macOS ships. The `+` form expands to
# nothing when unset and to the elements otherwise.
python3 "${REPO_ROOT}/scripts/python/validate_capability_homes.py" \
    --repo-root "${VALIDATION_ROOT}" ${capability_args[@]+"${capability_args[@]}"}
capability_status=$?

if (( specialist_status != 0 )); then
    exit "$specialist_status"
fi
exit "$capability_status"
