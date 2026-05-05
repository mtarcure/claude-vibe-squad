#!/bin/bash
# Product hygiene audit and optional cleanup.
#
# Default is read-only and strict for local daily-driver hygiene. Use
# --public-export to fail only on tracked public-release blockers. Use --apply
# with SQUAD_CLEAN_CONFIRM=1 to remove operator-local runtime debris from the
# product repo working tree.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-product-hygiene.md"
APPLY=0
PUBLIC_EXPORT=0

for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --public-export) PUBLIC_EXPORT=1 ;;
        --help|-h)
            sed -n '2,16p' "$0"
            exit 0
            ;;
    esac
done

runtime_patterns=(
    "_state/active-tasks.json"
    "_state/audit-logs"
    "_state/blog-summaries"
    "_state/bounty-survey"
    "_state/cleanup-logs"
    "_state/dispatch-log.jsonl"
    "_state/doctor-logs"
    "_state/dream-logs"
    "_state/finance-daily"
    "_state/monitor"
    "_state/morning-briefs"
    "_state/nightly-failures"
    "_state/podcast-briefs"
    "_state/processed-content.json"
    "_state/processed-ids.json"
    "_state/recalled-tasks"
    "_state/tmux-logs"
    "_state/weekly-briefs"
    "departments/coding/_state"
    "departments/coding/tmp-write-check"
)

task_patterns=(
    "departments/*/inbox/*.md"
    "departments/*/active/*.md"
    "departments/*/outbox/*.md"
    "departments/*/archive/*.md"
)

draft_patterns=(
    "_state/spec-*-drafts"
    "_state/phase-*-drafts"
    "_state/spec-*-research"
    "docs/handoffs/*.md"
    "docs/plans/*.md"
    "docs/specs/spec-*.md"
)

collect_matches() {
    local pattern
    for pattern in "$@"; do
        find "${VAULT_ROOT}" -path "${VAULT_ROOT}/${pattern}" -print 2>/dev/null
    done
}

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/product-hygiene.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

runtime_file="${TMP_DIR}/runtime.txt"
task_file="${TMP_DIR}/tasks.txt"
draft_file="${TMP_DIR}/drafts.txt"
tracked_file="${TMP_DIR}/tracked-blockers.txt"
drift_file="${TMP_DIR}/instruction-drift.txt"

collect_matches "${runtime_patterns[@]}" | sort -u > "$runtime_file"
collect_matches "${task_patterns[@]}" | sort -u > "$task_file"
collect_matches "${draft_patterns[@]}" | sort -u > "$draft_file"
if git -C "${VAULT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${VAULT_ROOT}" ls-files | grep -E '(^_state/(active-tasks\.json|audit-logs|blog-summaries|bounty-survey|cleanup-logs|dispatch-log\.jsonl|doctor-logs|dream-logs|finance-daily|monitor|morning-briefs|nightly-failures|podcast-briefs|processed-content\.json|processed-ids\.json|recalled-tasks|tmux-logs|weekly-briefs)|^departments/[^/]+/(inbox|active|outbox)/.+\.md$|^departments/[^/]+/archive/.+\.md$|^docs/handoffs/.*v1\.1|^docs/(plans|specs)/.*v1\.1)' | while IFS= read -r tracked_path; do
        [[ -e "${VAULT_ROOT}/${tracked_path}" ]] && echo "$tracked_path"
    done > "$tracked_file" || true
else
    : > "$tracked_file"
fi

{
    if grep -RInE '45 specialists|all 45 specialists|scripts/send-req\.sh|currently has FILL placeholders|<FILL:|Department Lead|Security Lead|Research Lead|Content Lead|SysMgmt Lead|Claude Security|Claude Ops|claude-sec|claude-ops|5 compatibility Lead|5-tile sidebar|Lead coordinates specialist execution|Leads coordinate|Lead'\''s job|Lead does NOT|Claude-Lead' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" 2>/dev/null \
        | grep -v 'bin/upgrade-specialists.py'; then
        :
    fi
    if grep -RInE '^[[:space:]]*["'\'']?(to_lead|owning_lead|primary_lead|lead_direct_allowed)["'\'']?[[:space:]]*:' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared/protocol.md" "${VAULT_ROOT}/shared/modes" \
        "${VAULT_ROOT}/examples" 2>/dev/null; then
        :
    fi
    if grep -RInE 'docs/handoffs/[0-9]{4}-|docs/specs/spec-[0-9]|docs/plans/[0-9]{4}-' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" 2>/dev/null; then
        :
    fi
    if grep -RInE 'perplexity_search_web|elevenlabs__check_subscription|brave_search|serper_search' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" "${VAULT_ROOT}/model-lanes" \
        "${VAULT_ROOT}/departments"/*/specialists 2>/dev/null; then
        :
    fi
} | sort -u > "$drift_file"

runtime_count=$(grep -c . "$runtime_file" 2>/dev/null || true)
task_count=$(grep -c . "$task_file" 2>/dev/null || true)
draft_count=$(grep -c . "$draft_file" 2>/dev/null || true)
tracked_count=$(grep -c . "$tracked_file" 2>/dev/null || true)
drift_count=$(grep -c . "$drift_file" 2>/dev/null || true)
runtime_count=${runtime_count:-0}
task_count=${task_count:-0}
draft_count=${draft_count:-0}
tracked_count=${tracked_count:-0}
drift_count=${drift_count:-0}

mkdir -p "$(dirname "$LOG")"

{
    echo "# Product Hygiene - ${DATE}"
    echo ""
    echo "Run at: $(date -u +%FT%TZ)"
    echo ""
    echo "## Runtime debris"
    if [[ "$runtime_count" -gt 0 ]]; then sed 's/^/- /' "$runtime_file"; else echo "- (none)"; fi
    echo ""
    echo "## Mailbox task debris"
    if [[ "$task_count" -gt 0 ]]; then sed 's/^/- /' "$task_file"; else echo "- (none)"; fi
    echo ""
    echo "## Draft/spec/handoff material to curate"
    if [[ "$draft_count" -gt 0 ]]; then sed 's/^/- /' "$draft_file"; else echo "- (none)"; fi
    echo ""
    echo "## Tracked public-release blockers"
    if [[ "$tracked_count" -gt 0 ]]; then sed 's/^/- /' "$tracked_file"; else echo "- (none)"; fi
    echo ""
    echo "## Instruction drift"
    if [[ "$drift_count" -gt 0 ]]; then sed 's/^/- /' "$drift_file"; else echo "- (none)"; fi
    echo ""
    echo "## Summary"
    echo "- Runtime paths: ${runtime_count}"
    echo "- Mailbox task files: ${task_count}"
    echo "- Draft/spec/handoff paths: ${draft_count}"
    echo "- Tracked public-release blockers: ${tracked_count}"
    echo "- Instruction drift hits: ${drift_count}"
} > "$LOG"

echo "Product hygiene audit: runtime=${runtime_count} mailbox=${task_count} drafts=${draft_count} tracked_blockers=${tracked_count} drift=${drift_count}"
echo "Log: ${LOG}"

if [[ "$APPLY" -eq 0 ]]; then
    if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
        [[ "$tracked_count" -eq 0 && "$drift_count" -eq 0 ]] || exit 1
        exit 0
    fi
    [[ "$runtime_count" -eq 0 && "$task_count" -eq 0 && "$tracked_count" -eq 0 && "$drift_count" -eq 0 ]] || exit 1
    exit 0
fi

if [[ "${SQUAD_CLEAN_CONFIRM:-0}" != "1" ]]; then
    echo "Refusing cleanup without SQUAD_CLEAN_CONFIRM=1."
    echo "Review ${LOG}, then run: SQUAD_CLEAN_CONFIRM=1 bash bin/product-hygiene.sh --apply"
    exit 2
fi

while IFS= read -r path; do
    [[ -e "$path" ]] || continue
    case "$path" in
        */.gitkeep) continue ;;
    esac
    rm -rf "$path"
done < <(cat "$runtime_file" "$task_file")

for lead in coding security content sysmgmt research; do
    mkdir -p "${VAULT_ROOT}/departments/${lead}/inbox" \
             "${VAULT_ROOT}/departments/${lead}/active" \
             "${VAULT_ROOT}/departments/${lead}/outbox" \
             "${VAULT_ROOT}/departments/${lead}/archive"
done

echo "Cleanup applied. Draft/spec/handoff material was only reported, not deleted."
