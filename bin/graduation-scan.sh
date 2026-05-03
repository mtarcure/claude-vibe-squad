#!/usr/bin/env bash
# Weekly: scan _state/patterns.jsonl for routine_signatures hitting N=3
# distinct engagement_ids. Surface candidates in
# _state/mcp-graduation-candidates.md.
#
# Run by harness-optimizer's weekly review (extending existing weekly-briefs
# routine).

set -euo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
PATTERNS="${VAULT}/_state/patterns.jsonl"
CANDIDATES="${VAULT}/_state/mcp-graduation-candidates.md"

mkdir -p "$(dirname "${CANDIDATES}")"

if [[ ! -f "${PATTERNS}" ]]; then
    echo "No patterns log yet at ${PATTERNS}; writing empty candidates file." >&2
    {
        echo "# MCP Graduation Candidates — $(date -u +%F)"
        echo
        echo "_No patterns log yet at ${PATTERNS} — graduation scan skipped. Run after at least one specialist spawn has logged patterns._"
    } > "${CANDIDATES}"
    echo "Wrote ${CANDIDATES} (0 candidates, no patterns log)"
    exit 0
fi

THRESHOLD_DATE=$(date -u -v-30d +%FT%TZ 2>/dev/null || date -u -d '30 days ago' +%FT%TZ)

# Find routine_signatures with ≥3 distinct engagement_ids in past 30 days
{
    echo "# MCP Graduation Candidates — $(date -u +%F)"
    echo
    echo "Routines that have fired across ≥3 distinct engagements in the past 30 days. Candidates for custom MCP creation per spec Item 11 (track-and-surface only — operator decides whether to build)."
    echo

    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: jq not installed; cannot scan patterns.jsonl" >&2
        echo "(jq not available)" >> "${CANDIDATES}"
        exit 0
    fi

    # Group by routine_signature, count distinct engagement_ids, filter to ≥3
    candidates=$(jq -s --arg threshold "${THRESHOLD_DATE}" '
        [.[] | select(.ts >= $threshold)] |
        group_by(.routine_signature) |
        map({
            sig: .[0].routine_signature,
            specialist: .[0].specialist,
            lead: .[0].lead,
            engagements: ([.[].engagement_id] | unique | length),
            calls: length,
            sample_fingerprint: .[0].fingerprint
        }) |
        map(select(.engagements >= 3)) |
        sort_by(-.calls)
    ' "${PATTERNS}" 2>/dev/null || echo '[]')

    count=$(echo "${candidates}" | jq 'length')

    if [[ "${count}" == "0" ]]; then
        echo "_No graduation candidates this week — no routine has fired across ≥3 distinct engagements in the past 30 days._"
    else
        echo "${candidates}" | jq -r '.[] | "- **\(.specialist)** routine `\(.sig)` (fingerprint: \(.sample_fingerprint)) — \(.calls) calls across \(.engagements) engagements"'
        echo
        echo "## Operator action"
        echo
        echo "For each candidate above, decide: APPROVE (dispatch Coding/ai-engineer + plugin-dev + skill-creator to scaffold custom MCP) OR REJECT (log rationale; the routine stays as skill chain)."
    fi
} > "${CANDIDATES}"

echo "Wrote ${CANDIDATES} (${count} candidates)"
