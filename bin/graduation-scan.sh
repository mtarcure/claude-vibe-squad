#!/usr/bin/env bash
# Weekly: scan _state/patterns.jsonl for routine_signatures hitting N=3
# distinct engagement_ids. Surface candidates in
# _state/mcp-graduation-candidates.md.
#
# Exit 0 after a completed scan with no candidate, 1 when a threshold candidate
# is found, and 2 when the ledger cannot be measured. Run by harness-optimizer's
# weekly review (extending the existing weekly-briefs routine).

set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
VAULT="${VAULT_ROOT}"
PATTERNS="${GRADUATION_PATTERNS_UNDER_TEST:-${VAULT}/_state/patterns.jsonl}"
CANDIDATES="${GRADUATION_CANDIDATES_UNDER_TEST:-${VAULT}/_state/mcp-graduation-candidates.md}"
JQ_BIN="${GRADUATION_JQ_UNDER_TEST:-jq}"

mkdir -p "$(dirname "${CANDIDATES}")"

if [[ ! -f "${PATTERNS}" ]]; then
    echo "COULD NOT DETERMINE: patterns log is absent at ${PATTERNS}" >&2
    {
        echo "# MCP Graduation Candidates — $(date -u +%F)"
        echo
        echo "_COULD NOT DETERMINE: no patterns ledger exists, so no empty-result claim was made._"
    } > "${CANDIDATES}"
    exit 2
fi

THRESHOLD_DATE=$(date -u -v-30d +%FT%TZ 2>/dev/null || date -u -d '30 days ago' +%FT%TZ)

# A missing parser or malformed ledger is not an empty result. Exit 2 and write
# an explicit indeterminate report; exit 0 is reserved for a completed scan.
if ! command -v "${JQ_BIN}" >/dev/null 2>&1; then
    echo "COULD NOT DETERMINE: jq parser is unavailable (${JQ_BIN})" >&2
    {
        echo "# MCP Graduation Candidates — $(date -u +%F)"
        echo
        echo "_COULD NOT DETERMINE: jq is unavailable; patterns.jsonl was not scanned._"
    } > "${CANDIDATES}"
    exit 2
fi

# Group by routine_signature, count distinct engagement_ids, filter to ≥3.
jq_error="${CANDIDATES}.jq-error.$$"
candidates=""
if ! candidates=$("${JQ_BIN}" -s --arg threshold "${THRESHOLD_DATE}" '
    map(
        if (type == "object") and
           ((.ts | type) == "string") and
           ((.routine_signature | type) == "string") and
           ((.engagement_id | type) == "string")
        then .
        else error("pattern row lacks typed ts/routine_signature/engagement_id")
        end
    ) |
    map(select(.ts >= $threshold)) |
    group_by(.routine_signature) |
    map({
        sig: .[0].routine_signature,
        specialist: (.[0].specialist // "unknown"),
        lead: (.[0].lead // "unknown"),
        engagements: ([.[].engagement_id] | unique | length),
        calls: length,
        sample_fingerprint: (.[0].fingerprint // "unknown")
    }) |
    map(select(.engagements >= 3)) |
    sort_by(-.calls)
' "${PATTERNS}" 2>"${jq_error}"); then
    jq_reason=$(head -1 "${jq_error}" 2>/dev/null || true)
    rm -f "${jq_error}"
    echo "ERROR: graduation scan could not parse ${PATTERNS}: ${jq_reason:-jq failed}" >&2
    {
        echo "# MCP Graduation Candidates — $(date -u +%F)"
        echo
        echo "_COULD NOT DETERMINE: patterns.jsonl could not be parsed; no empty-result claim was made._"
    } > "${CANDIDATES}"
    exit 2
fi
rm -f "${jq_error}"

if ! count=$(printf '%s\n' "${candidates}" | "${JQ_BIN}" -e 'if type == "array" then length else error("result is not an array") end'); then
    echo "ERROR: graduation scan produced an invalid result" >&2
    exit 2
fi

{
    echo "# MCP Graduation Candidates — $(date -u +%F)"
    echo
    echo "Routines that have fired across ≥3 distinct engagements in the past 30 days. Candidates for custom MCP creation per spec Item 11 (track-and-surface only — operator decides whether to build)."
    echo
    if [[ "${count}" == "0" ]]; then
        echo "_No graduation candidates this week — no routine has fired across ≥3 distinct engagements in the past 30 days._"
    else
        printf '%s\n' "${candidates}" | "${JQ_BIN}" -r '.[] | "- **\(.specialist)** routine `\(.sig)` (fingerprint: \(.sample_fingerprint)) — \(.calls) calls across \(.engagements) engagements"'
        echo
        echo "## Operator action"
        echo
        echo "For each candidate above, decide: APPROVE (dispatch Coding/ai-engineer + plugin-dev + skill-creator to scaffold custom MCP) OR REJECT (log rationale; the routine stays as skill chain)."
    fi
} > "${CANDIDATES}"

if [[ "${count}" -gt 0 ]]; then
    echo "FAIL: wrote ${CANDIDATES}; found ${count} graduation candidate(s)" >&2
    exit 1
fi

echo "PASS: wrote ${CANDIDATES}; found no graduation candidates"
exit 0
