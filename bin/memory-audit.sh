#!/bin/bash
# Audit memory.md discipline: source citations, discipline references, and
# obvious secret/token patterns.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
DATE="$(date -u +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/audit-logs/${DATE}-memory-audit.md"

mkdir -p "$(dirname "$LOG")"

secret_re='(sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'

issues=0
warnings=0
unknowns=0
files_scanned=0

{
    echo "# Memory Audit - ${DATE}"
    echo ""
    echo "Run at: $(date -u +%FT%TZ)"
    echo ""
} > "$LOG"

tools_usable=true
for tool in grep awk sed; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "- could_not_determine: required command '${tool}' is unavailable" >> "$LOG"
        unknowns=$((unknowns + 1))
        tools_usable=false
    fi
done

for file in "${VAULT_ROOT}/departments"/*/memory.md; do
    [[ -f "$file" ]] || continue
    files_scanned=$((files_scanned + 1))
    rel="${file#"${VAULT_ROOT}/"}"
    echo "## ${rel}" >> "$LOG"

    if [[ "${tools_usable}" != true ]]; then
        echo "- scan_status=could-not-determine (required command unavailable)" >> "$LOG"
        echo "" >> "$LOG"
        continue
    fi

    grep_rc=0
    grep -q 'shared/memory-discipline.md' "$file" 2>/dev/null || grep_rc=$?
    case "${grep_rc}" in
        0)
            echo "- discipline_cite=true" >> "$LOG"
            ;;
        1)
            echo "- discipline_cite=false" >> "$LOG"
            issues=$((issues + 1))
            ;;
        *)
            echo "- discipline_cite=could-not-determine (grep exit ${grep_rc})" >> "$LOG"
            unknowns=$((unknowns + 1))
            ;;
    esac

    secret_hits=""
    secret_rc=0
    secret_hits=$(grep -En "$secret_re" "$file" 2>/dev/null) || secret_rc=$?
    case "${secret_rc}" in
        0)
            echo "- secret_pattern_hits:" >> "$LOG"
            echo "$secret_hits" | sed 's/^/  - line /' >> "$LOG"
            issues=$((issues + 1))
            ;;
        1)
            echo "- secret_pattern_hits=0" >> "$LOG"
            ;;
        *)
            echo "- secret_pattern_hits=could-not-determine (grep exit ${secret_rc})" >> "$LOG"
            unknowns=$((unknowns + 1))
            ;;
    esac

    no_source=""
    source_rc=0
    no_source=$(awk '
        /^-[[:space:]]/ {
            if ($0 !~ /(source:|Source:|TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}|https?:\/\/|file:|path:)/) {
                print NR ":" $0
            }
        }
    ' "$file" 2>/dev/null) || source_rc=$?
    if [[ "${source_rc}" -ne 0 ]]; then
        echo "- entries_missing_source=could-not-determine (awk exit ${source_rc})" >> "$LOG"
        unknowns=$((unknowns + 1))
    elif [[ -n "$no_source" ]]; then
        echo "- entries_missing_source:" >> "$LOG"
        echo "$no_source" | sed 's/^/  - line /' >> "$LOG"
        warnings=$((warnings + 1))
    else
        echo "- entries_missing_source=0" >> "$LOG"
    fi
    echo "" >> "$LOG"
done

if [[ "${files_scanned}" -eq 0 ]]; then
    echo "- could_not_determine: no departments/*/memory.md file exists; zero files were scanned" >> "$LOG"
    unknowns=$((unknowns + 1))
fi

if [[ "${unknowns}" -gt 0 ]]; then
    status="could-not-determine"
elif [[ "${issues}" -gt 0 ]]; then
    status="issues"
else
    status="clean"
fi

summary="summary: status=${status} issues=${issues} warnings=${warnings} unknowns=${unknowns} files_scanned=${files_scanned} log=${LOG}"
echo "${summary}" >> "$LOG"
echo "${summary}"

if [[ "${unknowns}" -gt 0 ]]; then
    exit 2
elif [[ "${issues}" -gt 0 ]]; then
    exit 1
fi
exit 0
