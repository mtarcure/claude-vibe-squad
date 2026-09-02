#!/bin/bash
# Audit memory.md discipline: the per-department census, source citations,
# discipline references, and obvious secret/token patterns.
#
# Three things this check learned to do on 2026-09-01, after a sweep found
# seven shapes of broken memory store that all exited 0:
#
#   1. COUNT WHAT SHOULD BE THERE, not what happens to be there. The scan
#      globbed departments/*/memory.md and audited whatever came back, so a
#      deleted file simply left the glob. One department wiped while four
#      stayed healthy scored `status=clean`; only a TOTAL wipe was reported.
#      Partial loss is precisely when this audit matters most.
#   2. PROVE IT WROTE ITS LOG. Every write went to "$LOG" unchecked. With the
#      log directory unwritable the run emitted 30+ "Permission denied" lines,
#      wrote nothing, and still exited 0. A check that cannot record that it
#      ran has no evidence it ran.
#   3. READ THE FILE, NOT A SUBSTRING OF IT. The only condition that could
#      raise an issue was `grep -q 'shared/memory-discipline.md'`, so any file
#      containing those bytes passed -- a one-line file, the line inside an
#      HTML comment, the line buried in unrelated prose.
#
# Exit 0 clean, 1 issues, 2 could-not-determine. bin/doctor.sh keys on the
# `summary: status=... files_scanned=N` line and on that tri-state, including
# files_scanned=0 meaning "no memory established yet" rather than "lost".

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
DATE="$(date -u +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/audit-logs/${DATE}-memory-audit.md"

secret_re='(sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'

issues=0
warnings=0
unknowns=0
files_scanned=0

# --- the log is this check's evidence ---------------------------------------
# Probe once, then route every write through log_note/log_block so a failure is
# recorded as a fact instead of scrolling past as a permission-denied line.
log_usable=true
if ! mkdir -p "$(dirname "$LOG")" 2>/dev/null; then
    log_usable=false
elif ! {
    printf '# Memory Audit - %s\n\n' "${DATE}"
    printf 'Run at: %s\n\n' "$(date -u +%FT%TZ)"
} 2>/dev/null > "$LOG"; then
    log_usable=false
fi

log_note() {
    [[ "${log_usable}" == true ]] || return 0
    printf '%s\n' "$1" 2>/dev/null >> "$LOG" || log_usable=false
}

# Returns non-zero when the append fails; it runs as the last stage of a
# pipeline, so it cannot set log_usable itself -- that happens in a subshell and
# is lost. Every caller pairs it with `|| log_usable=false`.
log_block() {
    if [[ "${log_usable}" != true ]]; then
        cat >/dev/null
        return 0
    fi
    cat 2>/dev/null >> "$LOG"
}

# Strip HTML comments, which are markdown's way of saying "this text is off".
# A discipline citation inside one is not a citation: every department file
# replaced by `<!-- shared/memory-discipline.md -->` used to score clean. Runs
# as a state machine so a comment spanning lines is stripped too, and emits one
# output line per input line so reported line numbers stay accurate.
strip_html_comments() {
    awk '
        function strip(line,   out, idx) {
            out = ""
            while (length(line) > 0) {
                if (in_comment) {
                    idx = index(line, "-->")
                    if (idx == 0) return out
                    line = substr(line, idx + 3)
                    in_comment = 0
                } else {
                    idx = index(line, "<!--")
                    if (idx == 0) return out line
                    out = out substr(line, 1, idx - 1)
                    line = substr(line, idx + 4)
                    in_comment = 1
                }
            }
            return out
        }
        { print strip($0) }
    ' "$1"
}

for file in "${VAULT_ROOT}/departments"/*/memory.md; do
    [[ -f "$file" ]] || continue
    files_scanned=$((files_scanned + 1))
    rel="${file#"${VAULT_ROOT}/"}"
    log_note "## ${rel}"

    # Every check below tri-states on its tool's exit status, so a missing or
    # broken grep/awk lands as could-not-determine on its own (measured: with
    # awk off PATH this exits 2). A `command -v` pre-flight was a second,
    # weaker copy of that guard and is gone.
    visible=""
    visible_rc=0
    visible="$(strip_html_comments "$file" 2>/dev/null)" || visible_rc=$?
    if [[ "${visible_rc}" -ne 0 ]]; then
        log_note "- scan_status=could-not-determine (awk exit ${visible_rc} stripping comments)"
        unknowns=$((unknowns + 1))
        log_note ""
        continue
    fi

    grep_rc=0
    grep -q 'shared/memory-discipline.md' <<< "$visible" 2>/dev/null || grep_rc=$?
    case "${grep_rc}" in
        0)
            log_note "- discipline_cite=true"
            ;;
        1)
            log_note "- discipline_cite=false"
            issues=$((issues + 1))
            ;;
        *)
            log_note "- discipline_cite=could-not-determine (grep exit ${grep_rc})"
            unknowns=$((unknowns + 1))
            ;;
    esac

    # A memory file with no entries is not a memory store, however many of the
    # right words it contains. shared/memory-discipline.md rule 1 writes every
    # memory as a top-level `- ` entry, so that is what gets counted.
    entries=0
    entries="$(grep -cE '^-[[:space:]]' <<< "$visible" 2>/dev/null)"
    entries_rc=$?
    if [[ "${entries_rc}" -gt 1 ]]; then
        log_note "- entries=could-not-determine (grep exit ${entries_rc})"
        unknowns=$((unknowns + 1))
    elif [[ "${entries}" -eq 0 ]]; then
        log_note "- entries=0 (no memory entries: the file cites the discipline but records nothing)"
        issues=$((issues + 1))
    else
        log_note "- entries=${entries}"
    fi

    # The secret scan reads the RAW file: a credential inside an HTML comment
    # is still a credential.
    secret_hits=""
    secret_rc=0
    secret_hits=$(grep -En "$secret_re" "$file" 2>/dev/null) || secret_rc=$?
    case "${secret_rc}" in
        0)
            log_note "- secret_pattern_hits:"
            printf '%s\n' "$secret_hits" | sed 's/^/  - line /' | log_block \
                || log_usable=false
            issues=$((issues + 1))
            ;;
        1)
            log_note "- secret_pattern_hits=0"
            ;;
        *)
            log_note "- secret_pattern_hits=could-not-determine (grep exit ${secret_rc})"
            unknowns=$((unknowns + 1))
            ;;
    esac

    # Provenance stays a WARNING, not an issue. Measured 2026-09-01: this
    # repo's own coding/ has 0 of 8 entries cited and sysmgmt/ 0 of 14, so
    # promoting it would fail a healthy store -- a worse gate than no gate.
    no_source=""
    source_rc=0
    no_source=$(awk '
        /^-[[:space:]]/ {
            if ($0 !~ /(source:|Source:|TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}|https?:\/\/|file:|path:)/) {
                print NR ":" $0
            }
        }
    ' <<< "$visible" 2>/dev/null) || source_rc=$?
    if [[ "${source_rc}" -ne 0 ]]; then
        log_note "- entries_missing_source=could-not-determine (awk exit ${source_rc})"
        unknowns=$((unknowns + 1))
    elif [[ -n "$no_source" ]]; then
        log_note "- entries_missing_source:"
        printf '%s\n' "$no_source" | sed 's/^/  - line /' | log_block \
            || log_usable=false
        warnings=$((warnings + 1))
    else
        log_note "- entries_missing_source=0"
    fi
    log_note ""
done

# --- census -----------------------------------------------------------------
# departments/*/NAMESPACE.md is the department's own declaration that it
# exists, and it is tracked in git. departments/*/memory.md is gitignored
# (.gitignore:86), which is exactly why it can vanish with nothing else in the
# tree changing and nothing noticing.
#
# shared/memory-discipline.md is explicit that this layer may legitimately not
# exist yet, so a store where NOTHING has been written stays the existing
# files_scanned=0 "unestablished" case that bin/doctor.sh reports as absent
# input. The census only speaks once memory exists: a department that declares
# itself while its siblings carry memory and it does not is partial LOSS.
if [[ "${files_scanned}" -gt 0 ]]; then
    declared=0
    for namespace_file in "${VAULT_ROOT}/departments"/*/NAMESPACE.md; do
        [[ -f "$namespace_file" ]] || continue
        declared=$((declared + 1))
        department="$(dirname "$namespace_file")"
        rel_department="${department#"${VAULT_ROOT}/"}"
        if [[ -f "${department}/memory.md" ]]; then
            continue
        fi
        if [[ -L "${department}/memory.md" ]]; then
            log_note "- missing_memory_file: ${rel_department}/memory.md is a symlink that resolves to nothing"
        else
            log_note "- missing_memory_file: ${rel_department} declares itself in NAMESPACE.md but has no memory.md"
        fi
        issues=$((issues + 1))
    done
    if [[ "${declared}" -eq 0 ]]; then
        log_note "- census=could-not-determine: ${files_scanned} memory file(s) scanned but no departments/*/NAMESPACE.md declares a department, so completeness is unknown"
        unknowns=$((unknowns + 1))
    else
        log_note "- census: ${declared} declared department(s), ${files_scanned} with memory.md"
    fi
fi

if [[ "${files_scanned}" -eq 0 ]]; then
    log_note "- could_not_determine: no departments/*/memory.md file exists; zero files were scanned"
    unknowns=$((unknowns + 1))
fi

# A run with no durable record cannot claim a verdict, whatever it measured.
if [[ "${log_usable}" != true ]]; then
    unknowns=$((unknowns + 1))
    printf 'memory-audit: could not write the audit log at %s; this run left no durable record\n' \
        "$LOG" >&2
fi

if [[ "${unknowns}" -gt 0 ]]; then
    status="could-not-determine"
elif [[ "${issues}" -gt 0 ]]; then
    status="issues"
else
    status="clean"
fi

summary="summary: status=${status} issues=${issues} warnings=${warnings} unknowns=${unknowns} files_scanned=${files_scanned} log=${LOG}"
log_note "${summary}"
echo "${summary}"

# The summary landing in the log is the log's own proof the run completed. If
# the write failed only here, the counters above never saw it.
if [[ "${log_usable}" != true ]]; then
    exit 2
fi

if [[ "${unknowns}" -gt 0 ]]; then
    exit 2
elif [[ "${issues}" -gt 0 ]]; then
    exit 1
fi
exit 0
