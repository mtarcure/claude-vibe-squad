#!/usr/bin/env bash
# tools/wsguard/repro.sh — reproduce the reported "write_scope guard will not fire"
# failure against bin/send-task.sh.
#
# The report claimed a bash block inserted above `case "$MODE" in` (said to sit at
# top level near line 983) never printed. This harness tests that claim directly:
# it locates the anchor, inserts the block VERBATIM into a COPY of the dispatcher,
# and runs the copy against a fixture whose write_scope names a gitignored path.
#
# bin/send-task.sh is never modified. The copy lives under tools/wsguard/out/.
#
# ONE adaptation is made to the copy, and only to the copy: bin/send-task.sh line 39
# bootstraps VAULT_ROOT by sourcing "<dir of this script>/../shared/repo-root.sh".
# A copy parked three directories deep cannot resolve that relative path, so the
# harness rewrites that single bootstrap line to an absolute source of the REAL
# shared/repo-root.sh. Nothing else in the file is touched, and in particular the
# block under test is inserted byte-for-byte as reported.
#
# Usage: bash tools/wsguard/repro.sh

set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "${HERE}/../.." && pwd -P)"
OUT="${HERE}/out"
SRC="${ROOT}/bin/send-task.sh"
COPY="${OUT}/send-task-with-bash-block.sh"
FIXTURE="${HERE}/fixtures/negative-control-gitignored.md"

mkdir -p "$OUT"

hr() { printf '\n========== %s ==========\n' "$*"; }

hr "E1: does the reported anchor exist at all?"
printf 'occurrences of the reported anchor `case "$MODE" in`: '
grep -c 'case "\$MODE" in' "$SRC" || true
printf 'what actually sits at line 983: '
sed -n '983p' "$SRC"
echo 'every top-level case statement in the file:'
grep -n '^case .* in$' "$SRC"

hr "E2: git check-ignore on the fixture path, from the repo root"
echo '+ git -C "$ROOT" check-ignore -v _state/bounty/rigs/newthing/'
git -C "$ROOT" check-ignore -v '_state/bounty/rigs/newthing/'
echo "exit=$?"

hr "E3: build the patched copy (block VERBATIM, above line 983)"
python3 - "$SRC" "$COPY" "$ROOT" <<'PYEOF'
import sys
src, dst, root = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(src, encoding="utf-8").read().splitlines(keepends=True)

# Adaptation 1 (harness-only): make the VAULT_ROOT bootstrap work from a copy
# that does not sit in <repo>/bin. This does not touch the block under test.
for i, line in enumerate(lines):
    if line.startswith('source "$(cd -- "$(dirname'):
        lines[i] = f'source "{root}/shared/repo-root.sh"\n'
        print(f"bootstrap line {i+1} repointed to {root}/shared/repo-root.sh")
        break

# The block exactly as reported, unmodified.
block = '''if [[ -n "${WRITE_SCOPE_RAW:-}" ]]; then
    while IFS= read -r _ws_path; do
        [[ -z "$_ws_path" ]] && continue
        case "$_ws_path" in departments/*) continue ;; esac
        if git -C "$VAULT_ROOT" check-ignore -q "$_ws_path" </dev/null 2>/dev/null; then
            printf 'WARNING: write_scope path is gitignored and will not be promoted: %s\\n' "$_ws_path" >&2
        fi
    done < <(printf '%s' "$WRITE_SCOPE_RAW" | tr -d '[]' | tr ',' '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
fi
'''
lines.insert(982, block)   # immediately above original line 983
open(dst, "w", encoding="utf-8").write("".join(lines))
print(f"wrote {dst}; block inserted above original line 983")
PYEOF

echo "+ bash -n (syntax check)"
bash -n "$COPY" && echo "syntax OK"

hr "E4: run the PATCHED COPY on the gitignored fixture"
echo "+ bash $COPY <negative-control fixture> --dry-run"
bash "$COPY" "$FIXTURE" --dry-run 2>&1
echo "[exit=$?]"

hr "E5: same copy under bash -x, tracing the inserted loop only"
bash -x "$COPY" "$FIXTURE" --dry-run 2>&1 \
    | grep -E '_ws_path|check-ignore' | head -20
echo "(trace lines mentioning _ws_path / check-ignore)"

hr "E6: the split pipeline in isolation (byte-exact, \$ marks end of line)"
WS='[departments/shared/outbox/TASK-2026-08-04-1100-wsgneg-response.md, _state/bounty/rigs/newthing/]'
printf '%s' "$WS" | tr -d '[]' | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | cat -e

hr "DONE"
