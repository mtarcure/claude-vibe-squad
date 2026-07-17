#!/bin/bash
# Product hygiene audit and optional cleanup.
#
# Default is read-only and strict for local daily-driver hygiene. Use
# --public-export for the fail-closed publication gate. Use --apply with
# SQUAD_CLEAN_CONFIRM=1 to remove operator-local runtime debris from the product
# repo working tree.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VAULT_ROOT="${VAULT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd -P)}"
APPLY=0
PUBLIC_EXPORT=0
REPORT_PATH=""
POLICY_PATH=""
IDENTIFIER_DENYLIST=""
GITLEAKS_BIN="${GITLEAKS_BIN:-gitleaks}"
GITLEAKS_TIMEOUT="${GITLEAKS_TIMEOUT:-120}"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --apply)
            APPLY=1
            shift
            ;;
        --public-export)
            PUBLIC_EXPORT=1
            shift
            ;;
        --root|--report|--policy|--identifier-denylist)
            option="$1"
            [[ "$#" -ge 2 ]] || { echo "Missing value for ${option}." >&2; exit 2; }
            case "$option" in
                --root) VAULT_ROOT="$2" ;;
                --report) REPORT_PATH="$2" ;;
                --policy) POLICY_PATH="$2" ;;
                --identifier-denylist) IDENTIFIER_DENYLIST="$2" ;;
            esac
            shift 2
            ;;
        --help|-h)
            sed -n '2,28p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if ! VAULT_ROOT="$(cd "${VAULT_ROOT}" 2>/dev/null && pwd -P)"; then
    echo "Scan root does not exist or is not accessible." >&2
    exit 2
fi
DATE="$(date -u +%Y-%m-%d)"
POLICY_PATH="${POLICY_PATH:-${VAULT_ROOT}/tools/export/policy/path-policy.json}"
IDENTIFIER_DENYLIST="${IDENTIFIER_DENYLIST:-${VAULT_ROOT}/_state/repo-split-2026-07-16/identifier-denylist.txt}"
echo "Canonical root scanned: ${VAULT_ROOT}"

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

if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
    if [[ -n "$REPORT_PATH" ]]; then
        report_parent="$(dirname "$REPORT_PATH")"
        report_name="$(basename "$REPORT_PATH")"
        if ! report_parent="$(cd "$report_parent" 2>/dev/null && pwd -P)"; then
            echo "Report parent must already exist: $(dirname "$REPORT_PATH")" >&2
            exit 2
        fi
        LOG="${report_parent}/${report_name}"
    else
        LOG="${TMP_DIR}/product-hygiene-public-export.md"
    fi
    case "$LOG" in
        "$VAULT_ROOT"|"$VAULT_ROOT"/*)
            echo "Public-export report must be outside the certified tree: ${LOG}" >&2
            exit 2
            ;;
    esac
else
    LOG="${REPORT_PATH:-${VAULT_ROOT}/_state/cleanup-logs/${DATE}-product-hygiene.md}"
fi

runtime_file="${TMP_DIR}/runtime.txt"
task_file="${TMP_DIR}/tasks.txt"
draft_file="${TMP_DIR}/drafts.txt"
tracked_file="${TMP_DIR}/tracked-blockers.txt"
drift_file="${TMP_DIR}/instruction-drift.txt"
tracked_nul="${TMP_DIR}/tracked-paths.nul"
gitleaks_raw_report="${TMP_DIR}/gitleaks-raw.json"
gitleaks_report="${TMP_DIR}/gitleaks-sanitized.json"
gitleaks_output="${TMP_DIR}/gitleaks-output.txt"
content_report="${TMP_DIR}/content-scan.txt"
content_error="${TMP_DIR}/content-scan-error.txt"
policy_error="${TMP_DIR}/path-policy-error.txt"
policy_status=0
gitleaks_status=0
content_status=0

collect_matches "${runtime_patterns[@]}" | sort -u > "$runtime_file"
collect_matches "${task_patterns[@]}" | sort -u > "$task_file"
collect_matches "${draft_patterns[@]}" | sort -u > "$draft_file"
if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
    policy_matcher="${VAULT_ROOT}/tools/export/path_policy.py"
    content_scanner="${VAULT_ROOT}/tools/export/content_scan.py"
    gitleaks_filter="${VAULT_ROOT}/tools/export/gitleaks_filter.py"
    gitleaks_allowlist="${VAULT_ROOT}/tools/export/policy/gitleaks-fingerprints.json"
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Required scanner runtime unavailable: python3" >&2
        exit 2
    fi
    if [[ ! -r "$policy_matcher" || ! -r "$content_scanner" || ! -r "$gitleaks_filter" || ! -r "$gitleaks_allowlist" ]]; then
        echo "Required policy/content scanner is unavailable under tools/export/." >&2
        exit 2
    fi
    if ! command -v "$GITLEAKS_BIN" >/dev/null 2>&1; then
        echo "Required maintained secret scanner unavailable: ${GITLEAKS_BIN}" >&2
        exit 2
    fi
    if [[ ! "$GITLEAKS_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
        echo "GITLEAKS_TIMEOUT must be a positive integer." >&2
        exit 2
    fi
    if [[ ! -r "$POLICY_PATH" || ! -r "$IDENTIFIER_DENYLIST" ]]; then
        echo "Policy or private identifier denylist is unavailable." >&2
        exit 2
    fi
    if ! git -C "${VAULT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "Public-export root is not a Git work tree: ${VAULT_ROOT}" >&2
        exit 2
    fi
    if ! git -C "${VAULT_ROOT}" ls-files -z > "$tracked_nul"; then
        echo "Unable to enumerate tracked paths." >&2
        exit 2
    fi
    python3 "$policy_matcher" audit --policy "$POLICY_PATH" --tracked-nul "$tracked_nul" \
        > "$tracked_file" 2> "$policy_error"
    policy_status=$?
    if [[ "$policy_status" -eq 0 ]]; then
        "$GITLEAKS_BIN" dir "$VAULT_ROOT" --no-banner --no-color --redact=0 \
            --timeout "$GITLEAKS_TIMEOUT" --report-format json --report-path "$gitleaks_raw_report" \
            > "$gitleaks_output" 2>&1
        gitleaks_raw_status=$?
        if [[ "$gitleaks_raw_status" -eq 0 || "$gitleaks_raw_status" -eq 1 ]]; then
            python3 "$gitleaks_filter" --root "$VAULT_ROOT" --report "$gitleaks_raw_report" \
                --allowlist "$gitleaks_allowlist" --output "$gitleaks_report" \
                >> "$gitleaks_output" 2>&1
            gitleaks_status=$?
        else
            gitleaks_status="$gitleaks_raw_status"
            echo "[]" > "$gitleaks_report"
            echo "Gitleaks scanner error; exact-fingerprint filter not run." >> "$gitleaks_output"
        fi
        python3 "$content_scanner" --root "$VAULT_ROOT" --tracked-nul "$tracked_nul" \
            --identifier-denylist "$IDENTIFIER_DENYLIST" --report "$content_report" \
            2> "$content_error"
        content_status=$?
    else
        gitleaks_status=3
        content_status=3
        echo "Skipped because the tracked-path policy failed closed." > "$gitleaks_output"
        echo "- Skipped because the tracked-path policy failed closed." > "$content_report"
    fi
elif git -C "${VAULT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
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
        | grep -v 'bin/upgrade-specialists.py' \
        | grep -vE "docs/adding-a-specialist\\.md:.*no \`<FILL:\\.\\.\\.>\` placeholders remain"; then
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
    if grep -RInE 'elevenlabs__check_subscription|brave_search|serper_search' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" "${VAULT_ROOT}/model-lanes" \
        "${VAULT_ROOT}/departments"/*/specialists 2>/dev/null; then
        :
    fi
} | sort -u > "$drift_file"

runtime_count=$(grep -c . "$runtime_file" 2>/dev/null || true)
task_count=$(grep -c . "$task_file" 2>/dev/null || true)
draft_count=$(grep -c . "$draft_file" 2>/dev/null || true)
if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
    tracked_count=$(grep -c '^- ' "$tracked_file" 2>/dev/null || true)
else
    tracked_count=$(grep -c . "$tracked_file" 2>/dev/null || true)
fi
drift_count=$(grep -c . "$drift_file" 2>/dev/null || true)
runtime_count=${runtime_count:-0}
task_count=${task_count:-0}
draft_count=${draft_count:-0}
tracked_count=${tracked_count:-0}
drift_count=${drift_count:-0}

if [[ "$PUBLIC_EXPORT" -eq 0 ]]; then
    mkdir -p "$(dirname "$LOG")"
fi

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
    if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
        echo "## Path-policy audit"
        cat "$tracked_file"
        if [[ -s "$policy_error" ]]; then sed 's/^/- error: /' "$policy_error"; fi
        echo ""
        echo "## Maintained secret scan (gitleaks)"
        echo "- Exit status: ${gitleaks_status}"
        if [[ -s "$gitleaks_report" ]]; then sed 's/^/- /' "$gitleaks_report"; else echo "- (no findings report)"; fi
        if [[ -s "$gitleaks_output" ]]; then sed 's/^/- scanner: /' "$gitleaks_output"; fi
        echo ""
        echo "## Independent entropy/token and private-identifier scan"
        echo "- Exit status: ${content_status}"
        if [[ -s "$content_report" ]]; then cat "$content_report"; else echo "- (no scan report)"; fi
        if [[ -s "$content_error" ]]; then sed 's/^/- error: /' "$content_error"; fi
        echo ""
    fi
    echo "## Instruction drift"
    if [[ "$drift_count" -gt 0 ]]; then sed 's/^/- /' "$drift_file"; else echo "- (none)"; fi
    echo ""
    echo "## Summary"
    echo "- Runtime paths: ${runtime_count}"
    echo "- Mailbox task files: ${task_count}"
    echo "- Draft/spec/handoff paths: ${draft_count}"
    echo "- Tracked public-release blockers: ${tracked_count}"
    echo "- Instruction drift hits: ${drift_count}"
    if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
        echo "- Path-policy status: ${policy_status}"
        echo "- Gitleaks status: ${gitleaks_status}"
        echo "- Entropy/identifier status: ${content_status}"
    fi
} > "$LOG"

echo "Product hygiene audit: runtime=${runtime_count} mailbox=${task_count} drafts=${draft_count} tracked_blockers=${tracked_count} drift=${drift_count}"
echo "Log: ${LOG}"

if [[ "$APPLY" -eq 0 ]]; then
    if [[ "$PUBLIC_EXPORT" -eq 1 ]]; then
        [[ "$policy_status" -eq 0 && "$gitleaks_status" -eq 0 && "$content_status" -eq 0 && "$drift_count" -eq 0 ]] || exit 1
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
