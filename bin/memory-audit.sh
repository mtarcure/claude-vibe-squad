#!/bin/bash
# Audit memory.md discipline: source citations, discipline references, and
# obvious secret/token patterns.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/audit-logs/${DATE}-memory-audit.md"

mkdir -p "$(dirname "$LOG")"

secret_re='(sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'

issues=0
warnings=0

{
    echo "# Memory Audit - ${DATE}"
    echo ""
    echo "Run at: $(date -u +%FT%TZ)"
    echo ""
} > "$LOG"

for file in "${VAULT_ROOT}/departments"/*/memory.md; do
    [[ -f "$file" ]] || continue
    rel="${file#${VAULT_ROOT}/}"
    echo "## ${rel}" >> "$LOG"

    if grep -q 'shared/memory-discipline.md' "$file"; then
        echo "- discipline_cite=true" >> "$LOG"
    else
        echo "- discipline_cite=false" >> "$LOG"
        issues=$((issues + 1))
    fi

    secret_hits=$(grep -En "$secret_re" "$file" 2>/dev/null || true)
    if [[ -n "$secret_hits" ]]; then
        echo "- secret_pattern_hits:" >> "$LOG"
        echo "$secret_hits" | sed 's/^/  - line /' >> "$LOG"
        issues=$((issues + 1))
    else
        echo "- secret_pattern_hits=0" >> "$LOG"
    fi

    no_source=$(awk '
        /^-[[:space:]]/ {
            if ($0 !~ /(source:|Source:|TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}|https?:\/\/|file:|path:)/) {
                print NR ":" $0
            }
        }
    ' "$file")
    if [[ -n "$no_source" ]]; then
        echo "- entries_missing_source:" >> "$LOG"
        echo "$no_source" | sed 's/^/  - line /' >> "$LOG"
        warnings=$((warnings + 1))
    else
        echo "- entries_missing_source=0" >> "$LOG"
    fi
    echo "" >> "$LOG"
done

echo "summary: issues=${issues} warnings=${warnings} log=${LOG}"
[[ "$issues" -eq 0 ]]
