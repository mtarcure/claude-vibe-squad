#!/bin/bash
# Nightly cleanup census. Intentionally report-only: age is an observation,
# never authority to move or delete an artifact.

set -euo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

# Tests may point this read-only census at a disposable tree. There is no
# corresponding apply variable or mutation path.
TMP_SCAN_ROOT="${VIBESQUAD_CLEANUP_TMP_ROOT:-/tmp}"
SAMPLE_LIMIT=20
SCAN_RESULTS=""
trap '[[ -z "${SCAN_RESULTS}" ]] || rm -f -- "${SCAN_RESULTS}"' EXIT

cat <<EOF
# System Cleanup Census — $(date -u +%Y-%m-%d)

Run at: $(date -u +%FT%TZ)

- cleanup_mode: report-only
- age_basis: mtime observation only; non-authoritative
- storage_class: unknown
- effective_storage_class: DURABLE
- cleanup_eligible: false

No apply mode exists. Cleanup flags and command-line arguments are ignored.
Package cache mutations: 0.

## Temporary-file observations
EOF

TMP_CANDIDATES=0
TMP_SCAN_COMPLETE=true
if [[ -d "${TMP_SCAN_ROOT}" ]]; then
    SCAN_RESULTS="$(mktemp "${TMPDIR:-/tmp}/vibesquad-cleanup-census.XXXXXX")"
    if ! find "${TMP_SCAN_ROOT}" -type f -mtime +7 -print0 >"${SCAN_RESULTS}" 2>/dev/null; then
        TMP_SCAN_COMPLETE=false
    fi
    while IFS= read -r -d '' candidate; do
        TMP_CANDIDATES=$((TMP_CANDIDATES + 1))
        if [[ ${TMP_CANDIDATES} -le ${SAMPLE_LIMIT} ]]; then
            printable="${candidate//$'\n'/\\n}"
            printable="${printable//$'\r'/\\r}"
            printf -- '- sample: %s; effective_storage_class: DURABLE; cleanup_eligible: false\n' "${printable}"
        fi
    done < "${SCAN_RESULTS}"
    rm -f -- "${SCAN_RESULTS}"
    SCAN_RESULTS=""
fi

printf '\n## Run-folder observations\n'
RUN_CANDIDATES=0
RUN_SCAN_COMPLETE=true
if [[ -d "${VAULT_ROOT}/runs" ]]; then
    for run in "${VAULT_ROOT}"/runs/*/; do
        [[ -d "${run}" ]] || continue
        run_name="$(basename "${run%/}")"
        [[ "${run_name}" == _* ]] && continue
        if ! old_run="$(find "${run}" -maxdepth 0 -mtime +30 -print -quit 2>/dev/null)"; then
            RUN_SCAN_COMPLETE=false
            continue
        fi
        if [[ -n "${old_run}" ]]; then
            RUN_CANDIDATES=$((RUN_CANDIDATES + 1))
            if [[ ${RUN_CANDIDATES} -le ${SAMPLE_LIMIT} ]]; then
                printable="runs/${run_name//$'\n'/\\n}"
                printable="${printable//$'\r'/\\r}"
                printf -- '- sample: %s; effective_storage_class: DURABLE; cleanup_eligible: false\n' "${printable}"
            fi
        fi
    done
fi

cat <<EOF

## Summary

- temporary-file candidates observed: ${TMP_CANDIDATES}
- run-folder candidates observed: ${RUN_CANDIDATES}
- temporary scan complete: ${TMP_SCAN_COMPLETE}
- run scan complete: ${RUN_SCAN_COMPLETE}
- samples per category: at most ${SAMPLE_LIMIT}
- package cache mutations: 0
- files deleted: 0
- run folders moved: 0
EOF

if [[ "${TMP_SCAN_COMPLETE}" != true || "${RUN_SCAN_COMPLETE}" != true ]]; then
    echo "system-cleanup: census incomplete; no cleanup decision was made" >&2
    exit 1
fi
