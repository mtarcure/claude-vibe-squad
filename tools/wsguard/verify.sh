#!/usr/bin/env bash
# tools/wsguard/verify.sh — control suite for the write_scope promotion guard.
#
# The guard under test is warn_unpromoted_write_scope() in bin/send-task.sh
# (added by 0e636b8). This suite asserts it fires on bad input, stays silent on
# good input, and distinguishes "unpromoted" from "unpromoted AND invisible".
#
# C4 is a non-vacuity gate. A suite that only ever runs the working guard cannot
# tell "the guard fired" from "the detector is broken and everything looks fine",
# so C4 runs a deliberately defective variant (the bash block from the incident
# report) and REQUIRES it to fail. If C4 ever passes, the detector is lying and
# every other result here is void.
#
# bin/send-task.sh is never modified; every run is --dry-run, which exits 2 at
# send-task.sh:1559 before any registry write, inbox copy, or lane launch.
#
# Usage: bash tools/wsguard/verify.sh     (exit 0 = all controls held)

set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "${HERE}/../.." && pwd -P)"
FIX="${HERE}/fixtures"
DISPATCH="${ROOT}/bin/send-task.sh"
REPRO="${WSGUARD_REPRO_UNDER_TEST:-${HERE}/repro.sh}"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/vibesquad-wsguard-verify.XXXXXX")" || {
    echo "ERROR: could not create temporary wsguard directory" >&2
    exit 1
}
REPRO_LOG="${WORK_DIR}/repro.log"

cleanup() {
    rm -f -- "$REPRO_LOG"
    rmdir -- "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

PASS=0
FAIL=0
UNKNOWN=0

# Run a fixture through the real dispatcher and echo only the guard's notice.
guard_output() {
    bash "$DISPATCH" "$1" --dry-run 2>&1 | grep -E 'predispatch notice|predispatch WARNING' || true
}

check_unknown() {
    local label="$1" got="$2"
    printf '  BLOCKED %s\n' "$label"
    printf '          COULD NOT DETERMINE: %s\n' "$got"
    UNKNOWN=$((UNKNOWN + 1))
}

check() {
    local label="$1" expectation="$2" got="$3" ok="$4"
    if [[ "$ok" == "yes" ]]; then
        printf '  PASS  %s\n' "$label"; PASS=$((PASS + 1))
    else
        printf '  FAIL  %s\n' "$label"
        printf '        expected: %s\n' "$expectation"
        printf '        got:      %s\n' "${got:-<no output>}"
        FAIL=$((FAIL + 1))
    fi
}

printf '\n=== C1  NEGATIVE CONTROL — gitignored write_scope path MUST warn ===\n'
printf '+ bash bin/send-task.sh %s --dry-run\n' "fixtures/negative-control-gitignored.md"
OUT="$(guard_output "${FIX}/negative-control-gitignored.md")"
printf '%s\n' "${OUT:-<no output>}"
[[ "$OUT" == *gitignored* ]] && ok=yes || ok=no
check "guard names the gitignored path" "a notice containing 'gitignored'" "$OUT" "$ok"

printf '\n=== C2  POSITIVE CONTROL — clean write_scope MUST stay silent ===\n'
printf '+ bash bin/send-task.sh %s --dry-run\n' "fixtures/positive-control-clean.md"
OUT="$(guard_output "${FIX}/positive-control-clean.md")"
printf '%s\n' "${OUT:-<no output>}"
[[ -z "$OUT" ]] && ok=yes || ok=no
check "guard is silent on a fully-promoted packet" "no notice at all" "$OUT" "$ok"

printf '\n=== C3  DISCRIMINATION — unpromoted but tracked: warn, but not "silent" ===\n'
printf '+ bash bin/send-task.sh %s --dry-run\n' "fixtures/tracked-extra-path.md"
OUT="$(guard_output "${FIX}/tracked-extra-path.md")"
printf '%s\n' "${OUT:-<no output>}"
{ [[ -n "$OUT" ]] && [[ "$OUT" != *gitignored* ]]; } && ok=yes || ok=no
check "guard warns without claiming invisibility" "a notice NOT containing 'gitignored'" "$OUT" "$ok"

printf '\n=== C4  NON-VACUITY / FALSE TWIN — the reported bash block MUST fail ===\n'
printf 'Builds a copy of the dispatcher carrying the incident-report bash block and\n'
printf 'runs the same negative control. The block drops the LAST write_scope entry,\n'
printf 'so it prints nothing. If this control ever passes, the detector is broken.\n'
REPRO_RC=0
bash "$REPRO" >"$REPRO_LOG" 2>&1 || REPRO_RC=$?
TWIN="$(grep -c 'WARNING: write_scope path is gitignored' "$REPRO_LOG" || true)"
COMPLETE="$(grep -c '^WSGUARD_REPRO_COMPLETE$' "$REPRO_LOG" || true)"
printf '+ bash %s\nexit=%s\n' "$REPRO" "$REPRO_RC"
printf '+ grep -c "WARNING: write_scope path is gitignored" <temporary repro log>\n%s\n' "$TWIN"
printf '+ grep -c "^WSGUARD_REPRO_COMPLETE$" <temporary repro log>\n%s\n' "$COMPLETE"
if [[ "$REPRO_RC" != "0" || "$COMPLETE" != "1" ]]; then
    tail -20 "$REPRO_LOG" | sed 's/^/        repro: /'
    check_unknown "defective dispatcher twin did not complete" \
        "exit=${REPRO_RC}, completion markers=${COMPLETE}"
elif [[ "$TWIN" == "0" ]]; then
    check "defective bash block ran to completion and emitted no warning" \
        "exit=0, one completion marker, and 0 warnings from the twin" \
        "exit=${REPRO_RC}, complete=${COMPLETE}, warnings=${TWIN}" "yes"
else
    check "defective bash block ran to completion and emitted no warning" \
        "exit=0, one completion marker, and 0 warnings from the twin" \
        "exit=${REPRO_RC}, complete=${COMPLETE}, warnings=${TWIN}" "no"
fi

printf '\n=== C5  EXEMPTION IS CORRECT — a gitignored return_artifact must NOT warn ===\n'
printf 'The standard artifact path is gitignored for every board task (.gitignore:26,\n'
printf '`departments/*/outbox/*.md`), so warning here would fire on every packet. The\n'
printf 'artifact is bridged out rather than committed, so its ignore status is moot.\n'
printf '+ bash bin/send-task.sh %s --dry-run\n' "fixtures/gitignored-return-artifact.md"
OUT="$(guard_output "${FIX}/gitignored-return-artifact.md")"
printf '%s\n' "${OUT:-<no output>}"
[[ -z "$OUT" ]] && ok=yes || ok=no
check "no warning on a gitignored return_artifact" "silence — the exemption is by design" "$OUT" "$ok"

printf '\n=== C6  THE REASON, PINNED — artifact+envelope excluded from git promotion ===\n'
printf 'C5 is only correct while the supervisor keeps bridging the outputs instead of\n'
printf 'committing them. Pin that fact so C5 fails loudly if it ever changes.\n'
printf '+ grep -c "expected_result_path" (as exclude_paths) in bin/board-supervisor.sh\n'
EXCL="$(grep -c 'authority\["expected_result_path"\],' "${ROOT}/bin/board-supervisor.sh")"
BRIDGE="$(grep -c 'publish_prepared_worktree_outputs' "${ROOT}/bin/board-supervisor.sh")"
printf 'exclude_paths occurrences=%s   bridge-call occurrences=%s\n' "$EXCL" "$BRIDGE"
{ [[ "$EXCL" -ge 2 ]] && [[ "$BRIDGE" -ge 1 ]]; } && ok=yes || ok=no
check "outputs are bridged, not git-promoted" ">=2 exclude_paths and >=1 bridge call" "$EXCL/$BRIDGE" "$ok"

printf '\n=== C7  THE ORIGINAL DEFECT, ISOLATED — unterminated final line ===\n'
printf 'The reported block split write_scope with `printf %%s` (no trailing newline).\n'
printf '`read` returns non-zero at EOF on an unterminated line, so the loop body never\n'
printf 'runs for the LAST entry even though it was assigned. Both halves shown.\n'
BROKEN="$(printf 'alpha\nbravo' | { c=0; while IFS= read -r x; do c=$((c+1)); done; echo "$c"; })"
FIXED="$(printf 'alpha\nbravo\n' | { c=0; while IFS= read -r x; do c=$((c+1)); done; echo "$c"; })"
printf "printf 'alpha\\\\nbravo'   -> body ran %s time(s)\n" "$BROKEN"
printf "printf 'alpha\\\\nbravo\\\\n' -> body ran %s time(s)\n" "$FIXED"
{ [[ "$BROKEN" == "1" ]] && [[ "$FIXED" == "2" ]]; } && ok=yes || ok=no
check "unterminated input drops the last element" "1 then 2" "$BROKEN/$FIXED" "$ok"

printf '\n=== RESULT: %d passed, %d failed, %d blocked ===\n' "$PASS" "$FAIL" "$UNKNOWN"
[[ "$FAIL" -eq 0 ]] || exit 1
[[ "$UNKNOWN" -eq 0 ]] || exit 2
