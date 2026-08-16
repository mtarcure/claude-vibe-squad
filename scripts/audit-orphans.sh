#!/usr/bin/env bash

set -euo pipefail

ROOT="${ORPHAN_AUDIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
failures=0

declare -a live_contracts=()

add_if_file() {
    [[ -f "$1" ]] && live_contracts+=("$1")
}

add_if_file "${ROOT}/shared/tool-catalog.md"
add_if_file "${ROOT}/shared/specialist-runtime-map.tsv"

while IFS= read -r path; do
    live_contracts+=("$path")
done < <(
    find "${ROOT}/departments" "${ROOT}/shared/specialists" \
        -path '*/specialists/*.md' -type f -print 2>/dev/null | sort
)

report_matches() {
    local label="$1"
    local pattern="$2"
    shift 2
    local output
    local status=0

    (( $# > 0 )) || return 0
    # grep exits 0 = matched, 1 = no match, >=2 = ERROR (unreadable file, bad
    # pattern, missing operand). The old `2>/dev/null || true` folded >=2 into the
    # no-match branch, so a scan that never read the files reported a clean tree.
    # stderr is captured instead of discarded, and any error status fails the audit.
    output="$(grep -nH -E "$pattern" "$@" 2>&1)" || status=$?
    if (( status >= 2 )); then
        echo "SCAN ERROR: ${label}: grep exited ${status} (scan did not complete)" >&2
        if [[ -n "$output" ]]; then
            echo "$output" >&2
        fi
        failures=$((failures + 1))
        return 0
    fi
    if (( status == 0 )); then
        echo "ORPHAN: ${label}" >&2
        echo "$output" >&2
        failures=$((failures + 1))
    fi
}

report_matches \
    "removed MCP/tool reference" \
    'kg_query|list_skills|read_specialist|write_specialist|obsidian_search|chrono-catalog|chrono_catalog|chrono-vault.*(KG|knowledge graph)' \
    "${live_contracts[@]}"

server="${ROOT}/plugins/chrono-vault/mcp_server.py"
if [[ -f "$server" ]]; then
    report_matches \
        "removed split-SQL or LIKE recall path" \
        'def[[:space:]]+_vault_root\(|_init_kg_schema|def[[:space:]]+_connect\(|def[[:space:]]+list_attempts\(|_kg_alias_list_attempts|SELECT.*LIKE' \
        "$server"
    report_matches \
        "eager optional HTTP client import" \
        '^import[[:space:]]+httpx([[:space:]]|$)' \
        "$server"
fi

if (( failures > 0 )); then
    echo "No-orphans audit failed: ${failures} orphan class(es) and/or scan error(s)." >&2
    exit 1
fi

echo "No-orphans audit passed."
