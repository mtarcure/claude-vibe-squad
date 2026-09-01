#!/usr/bin/env bash
# Smoke bench for the EVM audit toolchain.
#
# WHAT THIS PROVES: slither, semgrep and forge run, are wired to each other, and
# still detect bug classes we already know how to detect.
#
# WHAT IT DOES NOT PROVE: that we would find a NOVEL bug. Every bug here is planted
# and every detector is told where to look. Read a green run as "the pipeline is
# alive", never as "the pipeline is good".
#
#   ./scripts/run-known-bug-bench.sh                     # expect every planted bug found
#   ./scripts/run-known-bug-bench.sh --negative-control  # repair the bugs, expect the bench to fail
#
# Exit codes:
#   0  the bench behaved as expected for the mode it ran in
#   1  BENCH FAIL   -- every engine ran, but an expectation came out wrong
#   2  bad usage
#   3  PREFLIGHT    -- an engine or fixture is missing before anything ran
#   4  ENGINE FAIL  -- an engine ran but did not produce a usable result
#
# Exit 4 is the one that matters. "Found nothing" and "could not run" are different
# facts about the world, and a bench that conflates them will certify a dead
# toolchain: the same engine crash scores once as a satisfied negative control and
# once as a quiet, discriminating rule. Every engine invocation below is therefore
# judged on THREE outcomes -- found, not-found, and FAILED -- and a failure aborts
# with exit 4 naming the engine, in both modes, instead of being counted as a miss.
#
# THE SCORING RULE: a status is not a verdict unless it can be attributed to the
# exact question being scored. Three rounds of fixes here each rejected the wrong
# SHAPE and were each defeated by the next shape, because a perfectly-shaped result
# can still answer a different question: a test that shares a name prefix with the
# one we own, or an exact-name failure caused by a setup revert rather than by the
# assertion the expectation is about. Both read as "the exploit stopped reproducing"
# and certify a negative control. So every expectation declares what it OWNS -- an
# exact test identity, and the exact assertion messages it is allowed to fail on --
# and an observation the runner cannot attribute to that owned question is FAILED.
# Unanswered is not answered.

set -uo pipefail

RC_BENCH=1
RC_USAGE=2
RC_PREFLIGHT=3
RC_ENGINE=4

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BENCH_DIR="$REPO_ROOT/bench/known-bugs"
NEGATIVE_CONTROL=0
KEEP_TMP=0
TMP_DIR=""

# The fixtures every engine is asserted to have actually looked at. An engine that
# reports nothing without having read these has not produced a negative result.
EXPECTED_SRC=("src/ReentrantBank.sol" "src/RoundingVault.sol")
EXPECTED_CTRL=("negative-control/ReentrantBank.sol" "negative-control/RoundingVault.sol")

# The forge expectation ledger: for each planted-bug question, the observation that
# question OWNS. Both fields are the attribution, and neither is optional.
#
#   test     the EXACT key forge emits, signature included. Not a prefix: a sibling
#            named test_Exploit_..._Shadow() shares every prefix character and is a
#            different test, and a prefix match scored it as this one.
#   markers  every assertion message in test/ that THIS expectation is allowed to
#            fail on. A `Failure` is evidence that the exploit stopped reproducing
#            only when forge attributes it to one of these; a failure for any other
#            reason -- a setup revert, a harness error, another expectation's
#            assertion -- is unusable, because it answers a different question.
#            These strings are asserted to exist in the test sources before forge
#            runs, so a marker that could never be emitted fails loudly by name
#            instead of silently making every negative control uninterpretable.
FORGE_LEDGER="$(cat <<'LEDGER'
[
  {"id": "E3",
   "test": "test_Exploit_ReentrancyDrainsOtherDepositors()",
   "markers": ["EXPECTATION MISSED: withdraw() did not re-enter",
               "EXPECTATION MISSED: attacker took no net ether",
               "EXPECTATION MISSED: attacker did not reach into another depositor's funds"]},
  {"id": "E4",
   "test": "test_Exploit_FreeAssetsAtZeroShareCost()",
   "markers": ["EXPECTATION MISSED: withdrawals burned shares",
               "EXPECTATION MISSED: attacker received no free assets"]},
  {"id": "E5",
   "test": "testFuzz_BurnIsShortOfWhatIsOwed(uint96)",
   "markers": ["EXPECTATION MISSED: burn path already rounds up"]}
]
LEDGER
)"

# The slither detector IDs the expectations below score BY NAME. Checked against
# what this slither build actually registers, for the reason given at the probe.
EXPECTED_SLITHER_CHECKS=("reentrancy-eth")

# Print the header block as help, without hardcoding line numbers that drift.
usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --negative-control) NEGATIVE_CONTROL=1; shift ;;
        --bench-dir) BENCH_DIR="$2"; shift 2 ;;
        --keep-tmp) KEEP_TMP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit $RC_USAGE ;;
    esac
done

cleanup() {
    if [[ -n "$TMP_DIR" && $KEEP_TMP -eq 0 && "$TMP_DIR" == /tmp/* ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

TMP_DIR="$(mktemp -d /tmp/known-bug-bench-XXXXXX)"

# Runner-owned scratch for semgrep's log and settings. Without this, semgrep writes
# to $HOME/.semgrep and dies with a PermissionError on any host that denies it --
# which is exactly how this bench previously scored a dead engine as a clean pass
# on one machine while passing on another. State the engine needs, the runner owns.
export SEMGREP_LOG_FILE="$TMP_DIR/semgrep.log"
export SEMGREP_SETTINGS_FILE="$TMP_DIR/semgrep-settings.yml"
SEMGREP_FLAGS=(--metrics=off --quiet --json --disable-version-check)

# ---------------------------------------------------------------------------
# Failure reporting
# ---------------------------------------------------------------------------
engine_fail() {  # <engine> <reason> [diagnostic]
    local engine="$1" reason="$2" diag="${3:-}"
    echo
    echo "ENGINE FAILURE: $engine -- $reason"
    if [[ -n "$diag" ]]; then
        printf '%s\n' "$diag" | sed 's/^/    | /'
    fi
    echo
    echo "  This is NOT an expectation miss and NOT a quiet rule. The bench cannot"
    echo "  judge a toolchain when one of its engines did not run. Nothing below this"
    echo "  point was scored. Fix $engine, then rerun."
    exit $RC_ENGINE
}

# ---------------------------------------------------------------------------
# Preflight: engines on PATH, fixtures on disk.
# ---------------------------------------------------------------------------
missing=()
for tool in forge slither semgrep solc python3; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "PREFLIGHT FAIL: not on PATH: ${missing[*]}"
    echo "  A missing engine is not a passing bench. Install it or fix PATH, then rerun."
    exit $RC_PREFLIGHT
fi
[[ -d "$BENCH_DIR" ]] || { echo "PREFLIGHT FAIL: no bench at $BENCH_DIR"; exit $RC_PREFLIGHT; }
for f in "${EXPECTED_SRC[@]}" "${EXPECTED_CTRL[@]}"; do
    [[ -f "$BENCH_DIR/$f" ]] || { echo "PREFLIGHT FAIL: missing fixture $BENCH_DIR/$f"; exit $RC_PREFLIGHT; }
done

# ---------------------------------------------------------------------------
# Environment banner. Resolved path AND version for every engine, each probe's
# exit status checked. Two hosts disagreeing about this bench must be able to
# diff these lines; a probe that cannot even report its version is exit 4, not a
# blank field. (No numeric version floor is asserted: the runner depends on
# specific JSON shapes and flags, not on version strings, and those are checked
# directly below -- an engine too old to satisfy them fails there, by name.)
# ---------------------------------------------------------------------------
# Result lands in a global on purpose. `V=$(probe ...)` would run this in a
# subshell, where engine_fail's `exit 4` kills only that subshell -- the run would
# carry on and print the abort message as the engine's "version". Measured: under a
# read-only $HOME the solc probe died and the banner cheerfully printed its stack
# trace in the version column. An abort has to happen in the shell that can abort.
VERSION_LINE=""
probe_version() {  # <engine> <cmd...>  -> sets VERSION_LINE
    local engine="$1"; shift
    local out rc
    out="$("$@" 2>&1)"; rc=$?
    if [[ $rc -ne 0 ]]; then
        engine_fail "$engine" "version probe exited $rc -- the engine is on PATH but cannot run" \
            "\$ $*
$out"
    fi
    # Each engine buries its version somewhere different (forge on the first of four
    # lines, solc on the second, slither and semgrep alone on one). The first line
    # carrying a dotted number is the version line for all four.
    VERSION_LINE="$(printf '%s\n' "$out" | grep -m1 -E '[0-9]+\.[0-9]+' || printf '%s\n' "$out" | head -1)"
}

probe_version forge   forge   --version                        ; FORGE_V="$VERSION_LINE"
probe_version slither slither --version                        ; SLITHER_V="$VERSION_LINE"
probe_version semgrep semgrep --version --disable-version-check ; SEMGREP_V="$VERSION_LINE"
probe_version solc    solc    --version                        ; SOLC_V="$VERSION_LINE"

echo "bench      : $BENCH_DIR"
echo "mode       : $([[ $NEGATIVE_CONTROL -eq 1 ]] && echo 'NEGATIVE CONTROL (bugs repaired; every expectation must MISS)' || echo 'normal (every planted bug must be FOUND)')"
echo "environment:"
printf '  %-8s %s\n             %s\n' "forge"   "$(command -v forge)"   "$FORGE_V"
printf '  %-8s %s\n             %s\n' "slither" "$(command -v slither)" "$SLITHER_V"
printf '  %-8s %s\n             %s\n' "semgrep" "$(command -v semgrep)" "$SEMGREP_V"
printf '  %-8s %s\n             %s\n' "solc"    "$(command -v solc)"    "$SOLC_V"
printf '  %-8s %s\n' "scratch" "$TMP_DIR"
echo

# ---------------------------------------------------------------------------
# In negative-control mode, work on a throwaway copy with the repaired sources
# swapped in. The tracked tree is never modified.
# ---------------------------------------------------------------------------
TARGET="$BENCH_DIR"
if [[ $NEGATIVE_CONTROL -eq 1 ]]; then
    NC_DIR="$TMP_DIR/nc"
    mkdir -p "$NC_DIR"
    cp -R "$BENCH_DIR/." "$NC_DIR/"
    rm -rf "$NC_DIR/out" "$NC_DIR/cache"
    for f in "$NC_DIR"/negative-control/*.sol; do
        cp "$f" "$NC_DIR/src/$(basename "$f")"
    done
    TARGET="$NC_DIR"
    echo "repaired sources staged in $NC_DIR/src"
    echo
fi

# ---------------------------------------------------------------------------
# Engine acquisition. Each engine runs ONCE; its exit status is captured on the
# line immediately after the call and its output is validated for shape and
# coverage BEFORE any expectation is evaluated. Anything that is not a usable
# result aborts here, so no expectation can ever be scored against a dead engine.
# ---------------------------------------------------------------------------

# Shape/coverage validators. Each prints a reason and exits 1 when the output is
# not a usable result. They are deliberately strict about "did the engine read the
# files we think it read", because a scan of nothing also returns nothing -- and
# equally strict about the FIELDS AND TYPES the expectation predicates below
# dereference, because coverage-bearing JSON that omits one of them is the second
# way a dead engine gets scored as a clean result: it parses, it proves coverage,
# it satisfies a presence-only check, and then it raises inside a predicate, where
# the exception is indistinguishable from "the finding is absent".
#
# Each validator also catches its own exceptions. A validator that crashes has
# validated nothing, and must say so rather than let a traceback fall through.
validate_slither() {  # stdin: slither json ; args: expected files...
    python3 -c '
import json, sys

def fail(msg):
    print(msg)
    sys.exit(1)

def need(cond, msg):
    if not cond:
        fail(msg)

def tname(v):
    return type(v).__name__

try:
    raw = sys.stdin.read()
    if not raw.strip():
        fail("produced no output at all")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        fail("output is not valid JSON: %s" % e)
    need(isinstance(d, dict), "top level is %s, not an object" % tname(d))
    if d.get("success") is not True:
        fail("slither reported success=%r error=%r" % (d.get("success"), d.get("error")))
    results = d.get("results")
    need(isinstance(results, dict), "results is %s, not an object" % tname(results))
    detectors = results.get("detectors")
    need(isinstance(detectors, list), "results.detectors is %s, not a list" % tname(detectors))
    seen = set()
    for i, r in enumerate(detectors):
        where = "results.detectors[%d]" % i
        need(isinstance(r, dict), "%s is %s, not an object" % (where, tname(r)))
        for key in ("check", "description"):
            need(key in r, "%s has no %s -- the expectation predicates dereference it" % (where, key))
            need(isinstance(r[key], str), "%s.%s is %s, not a string" % (where, key, tname(r[key])))
        elements = r.get("elements", [])
        need(isinstance(elements, list), "%s.elements is %s, not a list" % (where, tname(elements)))
        for j, el in enumerate(elements):
            need(isinstance(el, dict), "%s.elements[%d] is %s, not an object" % (where, j, tname(el)))
            sm = el.get("source_mapping", {})
            need(isinstance(sm, dict), "%s.elements[%d].source_mapping is %s, not an object" % (where, j, tname(sm)))
            f = sm.get("filename_relative")
            if isinstance(f, str) and f:
                seen.add(f)
    # Positive control that slither actually compiled and read the fixtures: both of
    # them contain a value-bearing low-level call in EVERY variant, repaired or not,
    # so slither has something to say about each file in both modes. A slither that
    # stops referencing them has changed under us and the bench must say so loudly
    # rather than quietly grade an analysis of nothing.
    absent = [f for f in sys.argv[1:] if f not in seen]
    if absent:
        fail("analysed no code in: %s (referenced: %s)" % (", ".join(absent), ", ".join(sorted(seen)) or "nothing"))
except SystemExit:
    raise
except Exception as e:
    print("validator crashed reading the output: %s: %s" % (type(e).__name__, e))
    sys.exit(1)
' "$@" 2>&1
}

validate_slither_checks() {  # stdin: slither --list-detectors-json ; args: detector ids...
    python3 -c '
import json, sys

def fail(msg):
    print(msg)
    sys.exit(1)

try:
    raw = sys.stdin.read()
    if not raw.strip():
        fail("listed no detectors at all")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        fail("detector list is not valid JSON: %s" % e)
    if not isinstance(d, list):
        fail("detector list is %s, not a list" % type(d).__name__)
    registered = set()
    for e in d:
        if isinstance(e, dict) and isinstance(e.get("check"), str):
            registered.add(e["check"])
    if not registered:
        fail("detector list carries no check ids")
    absent = [c for c in sys.argv[1:] if c not in registered]
    if absent:
        fail("does not register the detector(s) this bench scores by name: %s (%d detectors registered)"
             % (", ".join(absent), len(registered)))
except SystemExit:
    raise
except Exception as e:
    print("validator crashed reading the detector list: %s: %s" % (type(e).__name__, e))
    sys.exit(1)
' "$@" 2>&1
}

validate_semgrep() {  # stdin: semgrep json ; args: expected scanned files...
    python3 -c '
import json, sys

def fail(msg):
    print(msg)
    sys.exit(1)

def need(cond, msg):
    if not cond:
        fail(msg)

def tname(v):
    return type(v).__name__

try:
    raw = sys.stdin.read()
    if not raw.strip():
        fail("produced no output at all")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        fail("output is not valid JSON: %s" % e)
    need(isinstance(d, dict), "top level is %s, not an object" % tname(d))
    errs = d.get("errors")
    if errs is None:
        fail("output has no errors[] key -- not a semgrep scan result")
    need(isinstance(errs, list), "errors is %s, not a list" % tname(errs))
    if errs:
        parts = []
        for e in errs:
            parts.append(str(e.get("message", e))[:200] if isinstance(e, dict) else str(e)[:200])
        fail("scan reported %d error(s): %s" % (len(errs), "; ".join(parts)))
    # A rule semgrep declined to run is the semgrep-shaped version of a forge test
    # that was never evaluated: the scan exits 0, reports no errors, proves it read
    # every fixture, and returns nothing -- because nothing was ever asked. Scored
    # as a miss that would make E2 fail loudly in normal mode but read as "the rule
    # correctly went quiet" in negative-control mode. Absence of the key is treated
    # as a shape failure on purpose; the whole runner is written to fail by name
    # rather than let a check disappear silently under a version change.
    skipped_rules = d.get("skipped_rules")
    if skipped_rules is None:
        fail("output has no skipped_rules[] key -- cannot tell whether the rule this bench "
             "asks about was actually evaluated")
    need(isinstance(skipped_rules, list), "skipped_rules is %s, not a list" % tname(skipped_rules))
    if skipped_rules:
        ids = []
        for r in skipped_rules:
            ids.append(str(r.get("rule_id", r))[:120] if isinstance(r, dict) else str(r)[:120])
        fail("skipped %d rule(s): %s -- a rule that did not run cannot have found nothing"
             % (len(skipped_rules), "; ".join(ids)))
    results = d.get("results")
    need(isinstance(results, list), "results is %s, not a list" % tname(results))
    for i, r in enumerate(results):
        where = "results[%d]" % i
        need(isinstance(r, dict), "%s is %s, not an object" % (where, tname(r)))
        for key in ("check_id", "path"):
            need(key in r, "%s has no %s -- the expectation predicates dereference it" % (where, key))
            need(isinstance(r[key], str), "%s.%s is %s, not a string" % (where, key, tname(r[key])))
    paths = d.get("paths", {})
    need(isinstance(paths, dict), "paths is %s, not an object" % tname(paths))
    scanned_raw = paths.get("scanned") or []
    need(isinstance(scanned_raw, list), "paths.scanned is %s, not a list" % tname(scanned_raw))
    scanned = set(p for p in scanned_raw if isinstance(p, str))
    absent = [f for f in sys.argv[1:] if f not in scanned]
    if absent:
        fail("did not scan: %s (scanned: %s)" % (", ".join(absent), ", ".join(sorted(scanned)) or "nothing"))
    # Some semgrep versions report a file as skipped (timeout, parse error, size)
    # rather than as an error. Silence about a file it declined to read is not a
    # negative result about that file. Absent in the version measured here, so this
    # is a forward guard rather than a reproduced defect.
    skipped_paths = paths.get("skipped") or []
    need(isinstance(skipped_paths, list), "paths.skipped is %s, not a list" % tname(skipped_paths))
    skipped_names = set()
    for e in skipped_paths:
        if isinstance(e, dict) and isinstance(e.get("path"), str):
            skipped_names.add(e["path"])
        elif isinstance(e, str):
            skipped_names.add(e)
    hit = [f for f in sys.argv[1:] if f in skipped_names]
    if hit:
        fail("skipped rather than analysed: %s -- silence about a file it declined to read "
             "is not a negative result" % ", ".join(hit))
except SystemExit:
    raise
except Exception as e:
    print("validator crashed reading the output: %s: %s" % (type(e).__name__, e))
    sys.exit(1)
' "$@" 2>&1
}

# Positive control for the ATTRIBUTION, the way validate_slither_checks is a positive
# control for the detector name. A marker the harness cannot emit makes every Failure
# unattributable and every negative control an ENGINE FAILURE forever; a marker shared
# between two expectations attributes a failure to neither. Both are silent
# mis-declarations that would otherwise only ever surface as a confusing exit 4, so
# they are checked by name, against the actual test sources, before forge runs.
validate_forge_ledger() {  # args: <ledger json> <test source files...>
    python3 -c '
import json, os, sys

def fail(msg):
    print(msg)
    sys.exit(1)

try:
    ledger = json.loads(sys.argv[1])
    sources = {}
    for p in sys.argv[2:]:
        with open(p, encoding="utf-8") as fh:
            sources[p] = fh.read()
    if not sources:
        fail("found no test sources to check the declared assertion markers against")
    where = ", ".join(sorted(os.path.basename(p) for p in sources))
    owner = {}
    for exp in ledger:
        if not exp["markers"]:
            fail("%s declares no owned assertion marker, so no failure could ever be "
                 "attributed to it" % exp["id"])
        for m in exp["markers"]:
            claimed = owner.setdefault(m, exp["id"])
            if claimed != exp["id"]:
                fail("assertion marker %r is claimed by both %s and %s -- a marker two "
                     "expectations share cannot attribute a failure to either"
                     % (m, claimed, exp["id"]))
            if not any(m in body for body in sources.values()):
                fail("%s owns the assertion marker %r, which appears in none of the test "
                     "sources (%s) -- no forge failure could ever be attributed to it"
                     % (exp["id"], m, where))
except SystemExit:
    raise
except Exception as e:
    print("ledger check crashed: %s: %s" % (type(e).__name__, e))
    sys.exit(1)
' "$@" 2>&1
}

validate_forge() {  # stdin: forge json ; args: <ledger json>
    python3 -c '
import json, sys

def fail(msg):
    print(msg)
    sys.exit(1)

def need(cond, msg):
    if not cond:
        fail(msg)

def tname(v):
    return type(v).__name__

try:
    ledger = json.loads(sys.argv[1])
    raw = sys.stdin.read()
    if not raw.strip():
        fail("produced no output at all (a compile failure looks exactly like this)")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        fail("output is not valid JSON: %s" % e)
    need(isinstance(d, dict), "top level is %s, not an object" % tname(d))
    # The forge TestStatus enum is closed, and only two of its members are a
    # JUDGEMENT about the test: Success and Failure. "Skipped" means the test was
    # never evaluated; anything outside the enum is output forge could not have
    # serialised at all. Neither is evidence about the bug, yet both used to reach
    # scoring, where every non-Success string became an ordinary miss -- which
    # reads as "the exploit stopped reproducing" and certifies a negative control
    # against a test that never ran. Presence and type are not enough here: the
    # VALUE is what carries the meaning, so the value is what gets whitelisted.
    EVALUATED = ("Success", "Failure")
    names = []
    occurrences = {}
    for suite_name, suite in d.items():
        where = "suite %s" % suite_name
        # The predicates iterate EVERY top-level value and call .get on it, so a
        # non-object suite is not something to skip past -- it is a result they
        # cannot read. Fail here rather than let them raise.
        need(isinstance(suite, dict), "%s is %s, not an object" % (where, tname(suite)))
        tr = suite.get("test_results", {})
        need(isinstance(tr, dict), "%s.test_results is %s, not an object" % (where, tname(tr)))
        for name, res in tr.items():
            need(isinstance(name, str), "%s.test_results has a non-string test name %r" % (where, name))
            need(isinstance(res, dict), "%s.test_results[%s] is %s, not an object" % (where, name, tname(res)))
            need("status" in res, "%s.test_results[%s] has no status -- the expectation predicates dereference it" % (where, name))
            need(isinstance(res["status"], str), "%s.test_results[%s].status is %s, not a string" % (where, name, tname(res["status"])))
            need(res["status"] in EVALUATED,
                 "%s.test_results[%s].status is %r, not one of %s -- that test was not evaluated, "
                 "so its result is unusable rather than negative"
                 % (where, name, res["status"], "/".join(EVALUATED)))
            names.append(name)
            occurrences.setdefault(name, []).append((suite_name, res))
    if not names:
        fail("ran no tests")
    # Attribution. Everything above establishes that the output is READABLE; none of
    # it establishes that any of it is ABOUT the questions being scored. A legal,
    # unanimous, exact-name Failure is still only evidence that the exploit stopped
    # reproducing if forge blames the assertion this expectation owns.
    for exp in ledger:
        eid, want, owned = exp["id"], exp["test"], exp["markers"]
        got = occurrences.get(want, [])
        if not got:
            # Exact identity, deliberately. Report near-misses, because a sibling
            # sharing the prefix is exactly how a renamed test used to be scored as
            # this one, and the reader needs to see the name that DID run.
            stem = want.split("(")[0]
            near = sorted(n for n in names if n != want and n.startswith(stem))
            fail("%s owns %s and forge did not run it%s (ran: %s) -- an expectation that "
                 "was never evaluated is unusable, not negative"
                 % (eid, want, " (nearest name that did run: %s)" % ", ".join(near) if near else "",
                    ", ".join(sorted(names))))
        verdicts = {}
        for suite_name, res in got:
            if res["status"] == "Success":
                verdicts.setdefault("found", []).append(suite_name)
                continue
            reason = res.get("reason")
            if not isinstance(reason, str):
                fail("%s: %s failed in %s with reason %r, which is not a string -- forge "
                     "did not say what failed, so the failure cannot be attributed to the "
                     "assertion %s owns" % (eid, want, suite_name, reason, eid))
            if reason not in owned:
                fail("%s: %s failed in %s with reason %r, which is not one of the "
                     "assertions %s owns (%s) -- that failure answers a different "
                     "question, so it is unusable rather than negative"
                     % (eid, want, suite_name, reason, eid, "; ".join(repr(m) for m in owned)))
            verdicts.setdefault("not_found", []).append(suite_name)
        if len(verdicts) > 1:
            fail("%s: %s came back %s -- the result is ambiguous, not negative"
                 % (eid, want, " and ".join("%s from %s" % (k, ", ".join(v))
                                            for k, v in sorted(verdicts.items()))))
except SystemExit:
    raise
except Exception as e:
    print("validator crashed reading the output: %s: %s" % (type(e).__name__, e))
    sys.exit(1)
' "$@" 2>&1
}

# --- forge -----------------------------------------------------------------
# forge runs FIRST and this order is load-bearing. In a Foundry project slither
# compiles THROUGH forge, so a broken forge kills slither too -- and if slither is
# checked first the bench aborts naming slither, sending whoever reads it after the
# wrong engine. Validating the compiler before its dependants keeps the blame
# accurate. (Measured: a stubbed forge produced "ENGINE FAILURE: slither".)
#
# forge's exit status is NOT an engine-health signal: it returns 1 both when a
# test legitimately fails (the whole point of negative-control mode) and when the
# build collapses. The discriminator is the output -- valid JSON naming every test
# we expect to have run. A compile failure yields empty stdout and is caught.
FORGE_TEST_SRC=()
while IFS= read -r f; do FORGE_TEST_SRC+=("$f"); done < <(find "$TARGET/test" -name '*.sol' -type f 2>/dev/null | sort)
reason="$(validate_forge_ledger "$FORGE_LEDGER" "${FORGE_TEST_SRC[@]+"${FORGE_TEST_SRC[@]}"}")" \
    || engine_fail "forge" "the expectation ledger cannot attribute a failure: $reason"

FORGE_JSON="$(cd "$TARGET" && forge test --json 2>"$TMP_DIR/forge.err")"
reason="$(validate_forge "$FORGE_LEDGER" <<<"$FORGE_JSON")" \
    || engine_fail "forge" "$reason" "$(tail -8 "$TMP_DIR/forge.err")"

# --- slither detector registration -----------------------------------------
# A positive control for the QUESTION, not for the answer. Slither detector ids
# are an open, versioned vocabulary, so E1 naming "reentrancy-eth" is a bet that
# this build still registers it. Retire or rename that detector and E1 can never
# fire: normal mode calls the miss a bench failure, but NEGATIVE-CONTROL MODE
# SCORES IT AS THE BUG BEING REPAIRED and prints NEGATIVE CONTROL PASS. That is
# the same silent wrong answer an unevaluated forge status produces, reached
# through a different door -- an expectation that could never have come out true
# is not an expectation that came out false. Cheap to close: ask slither which
# detectors it registers before scoring one by name. (Run before the scan so a
# vocabulary drift is not reported as a scan failure.)
DETECTORS_JSON="$(slither --list-detectors-json 2>"$TMP_DIR/slither-detectors.err")"
rc=$?
[[ $rc -eq 0 ]] || engine_fail "slither" "could not list its detectors (exited $rc) -- the bench cannot confirm the detector it scores by name exists" "$(tail -5 "$TMP_DIR/slither-detectors.err")"
reason="$(validate_slither_checks "${EXPECTED_SLITHER_CHECKS[@]}" <<<"$DETECTORS_JSON")" \
    || engine_fail "slither" "$reason" "$(tail -5 "$TMP_DIR/slither-detectors.err")"

# --- slither ---------------------------------------------------------------
# --fail-none normalises the exit status: without it slither returns 255 merely
# for HAVING findings, which is a success, so the raw status cannot distinguish
# "found bugs" from "crashed". With it, nonzero means the run itself failed.
SLITHER_JSON="$(cd "$TARGET" && slither src --solc-disable-warnings --fail-none --json - 2>"$TMP_DIR/slither.err")"
rc=$?
[[ $rc -eq 0 ]] || engine_fail "slither" "exited $rc scanning src/ (it compiles through forge and solc -- check those first if the error below is a build error)" "$(tail -5 "$TMP_DIR/slither.err")"
reason="$(validate_slither "${EXPECTED_SRC[@]}" <<<"$SLITHER_JSON")" \
    || engine_fail "slither" "$reason" "$(tail -5 "$TMP_DIR/slither.err")"

# --- semgrep (src) ---------------------------------------------------------
SEMGREP_JSON="$(cd "$TARGET" && semgrep --config semgrep/cei-violation.yaml src "${SEMGREP_FLAGS[@]}" 2>"$TMP_DIR/semgrep.err")"
rc=$?
[[ $rc -eq 0 ]] || engine_fail "semgrep" "exited $rc scanning src/" "$(tail -5 "$TMP_DIR/semgrep.err")"
reason="$(validate_semgrep "${EXPECTED_SRC[@]}" <<<"$SEMGREP_JSON")" \
    || engine_fail "semgrep" "src/ scan: $reason" "$(tail -5 "$TMP_DIR/semgrep.err")"

# --- semgrep (repaired controls) -------------------------------------------
SEMGREP_CTRL_JSON="$(cd "$TARGET" && semgrep --config semgrep/cei-violation.yaml negative-control "${SEMGREP_FLAGS[@]}" 2>"$TMP_DIR/semgrep-ctrl.err")"
rc=$?
[[ $rc -eq 0 ]] || engine_fail "semgrep" "exited $rc scanning negative-control/" "$(tail -5 "$TMP_DIR/semgrep-ctrl.err")"
reason="$(validate_semgrep "${EXPECTED_CTRL[@]}" <<<"$SEMGREP_CTRL_JSON")" \
    || engine_fail "semgrep" "negative-control/ scan: $reason" "$(tail -5 "$TMP_DIR/semgrep-ctrl.err")"

# --- semgrep (live sources, negative-control mode only) --------------------
# In negative-control mode every source semgrep sees is repaired, so "the rule
# matched nothing" has no positive control inside that run: a rule deleted down
# to nothing would look identical. Scan the untouched tracked sources as well and
# require a match, so the silence in that mode is attributable to the repair.
SEMGREP_LIVE_JSON=""
if [[ $NEGATIVE_CONTROL -eq 1 ]]; then
    SEMGREP_LIVE_JSON="$(cd "$BENCH_DIR" && semgrep --config semgrep/cei-violation.yaml src "${SEMGREP_FLAGS[@]}" 2>"$TMP_DIR/semgrep-live.err")"
    rc=$?
    [[ $rc -eq 0 ]] || engine_fail "semgrep" "exited $rc scanning the tracked src/ positive control" "$(tail -5 "$TMP_DIR/semgrep-live.err")"
    reason="$(validate_semgrep "${EXPECTED_SRC[@]}" <<<"$SEMGREP_LIVE_JSON")" \
        || engine_fail "semgrep" "positive-control scan: $reason" "$(tail -5 "$TMP_DIR/semgrep-live.err")"
fi

# ---------------------------------------------------------------------------
# Expectation predicates. Past this line every engine has been proven to have run,
# to have read the fixtures, and to have emitted every field and type these
# predicates dereference -- so a nonzero result here means exactly one thing: the
# finding is not present.
#
# Belt and braces: each predicate still catches its own exceptions and exits
# RC_PREDICATE_ERROR, which guard_predicate turns into an ENGINE FAILURE. The
# validators above are meant to make that unreachable. If it ever fires, a shape
# got past them, and the honest answer is "unusable", never "not found" -- an
# expectation you could not EVALUATE is not an expectation that came out false,
# and scoring it as a miss is how a dead engine certifies a negative control.
# ---------------------------------------------------------------------------
RC_PREDICATE_ERROR=9
PREDICATE_ERR=""

guard_predicate() {  # <engine> <expectation label> <rc>
    local engine="$1" label="$2" rc="$3"
    [[ $rc -eq $RC_PREDICATE_ERROR ]] || return 0
    engine_fail "$engine" \
        "expectation $label could not be evaluated against the output it emitted -- that result is unusable, not negative" \
        "$PREDICATE_ERR"
}

# slither_has <check> <substring of description>
slither_has() {
    PREDICATE_ERR="$(python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for r in d.get("results", {}).get("detectors", []):
        if r["check"] == sys.argv[1] and sys.argv[2] in r["description"]:
            sys.exit(0)
    sys.exit(1)
except SystemExit:
    raise
except Exception as e:
    print("%s: %s" % (type(e).__name__, e), file=sys.stderr)
    sys.exit(9)
' "$1" "$2" <<<"$SLITHER_JSON" 2>&1 >/dev/null)"
    return $?
}

# semgrep_has <json> <rule id> <path substring>
semgrep_has() {
    PREDICATE_ERR="$(python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for r in d.get("results", []):
        if r["check_id"].endswith(sys.argv[1]) and sys.argv[2] in r["path"]:
            sys.exit(0)
    sys.exit(1)
except SystemExit:
    raise
except Exception as e:
    print("%s: %s" % (type(e).__name__, e), file=sys.stderr)
    sys.exit(9)
' "$2" "$3" <<<"$1" 2>&1 >/dev/null)"
    return $?
}

# forge_outcome <expectation id>  -> 0 found, 1 not-found, 9 unusable
#
# Second layer behind validate_forge, deliberately re-deriving the same rule from
# the ledger rather than trusting it. Note what is NOT here: any path from an
# unrecognised observation to rc 1. Zero occurrences, a status outside the enum, a
# failure this expectation does not own, and two occurrences that disagree all end
# at rc 9, which guard_predicate turns into ENGINE FAILURE. "Could not evaluate" is
# never allowed to degrade into "did not find" -- that degradation is the whole
# family of bugs this bench keeps rediscovering.
forge_outcome() {
    PREDICATE_ERR="$(python3 -c '
import json, sys
try:
    exp = next(e for e in json.loads(sys.argv[1]) if e["id"] == sys.argv[2])
    want, owned = exp["test"], set(exp["markers"])
    d = json.loads(sys.stdin.read())
    verdicts = set()
    for suite in d.values():
        for name, res in suite.get("test_results", {}).items():
            if name != want:  # exact identity: a sibling sharing a prefix is another test
                continue
            if res["status"] == "Success":
                verdicts.add("found")
            elif res["status"] == "Failure" and res.get("reason") in owned:
                verdicts.add("not_found")
            else:
                raise ValueError("%s reported status %r reason %r, which does not answer %s"
                                 % (want, res["status"], res.get("reason"), sys.argv[2]))
    if not verdicts:
        raise ValueError("%s never ran, so %s was never answered" % (want, sys.argv[2]))
    if len(verdicts) > 1:
        raise ValueError("%s reported both %s at once" % (want, " and ".join(sorted(verdicts))))
    sys.exit(0 if verdicts == {"found"} else 1)
except SystemExit:
    raise
except Exception as e:
    print("%s: %s" % (type(e).__name__, e), file=sys.stderr)
    sys.exit(9)
' "$FORGE_LEDGER" "$1" <<<"$FORGE_JSON" 2>&1 >/dev/null)"
    return $?
}

# Detail helpers. These only decorate a line that has already been decided, so
# they degrade to a printed reason instead of aborting -- but they must never
# spray a traceback into the scoreboard either.
forge_reason() {  # <expectation id>
    python3 -c '
import json, sys
try:
    exp = next(e for e in json.loads(sys.argv[1]) if e["id"] == sys.argv[2])
    d = json.loads(sys.stdin.read())
    for suite in d.values():
        for name, res in suite.get("test_results", {}).items():
            if name == exp["test"]:
                print(res.get("reason") or res["status"])
                sys.exit(0)
    print("no such test in the output")
except SystemExit:
    raise
except Exception as e:
    print("could not be read: %s: %s" % (type(e).__name__, e))
' "$FORGE_LEDGER" "$1" <<<"$FORGE_JSON" 2>&1
}

slither_checks() {
    python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(sorted({r["check"] for r in d.get("results", {}).get("detectors", [])}) or "no detectors reported")
except Exception as e:
    print("could not be read: %s: %s" % (type(e).__name__, e))
' <<<"$SLITHER_JSON" 2>&1
}

semgrep_count() {
    python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(len(d.get("results", [])))
except Exception as e:
    print("could not be read: %s: %s" % (type(e).__name__, e))
' <<<"$1" 2>&1
}

# ---------------------------------------------------------------------------
# Scoring. Every expectation and guard is EVALUATED first and printed afterwards.
# Nothing scores until all of it can be scored: an engine failure discovered while
# evaluating E5 must not leave E1..E4 already printed as MET above the abort. A
# partial scoreboard sitting above "nothing below this point was scored" is a
# half-verdict on a toolchain the bench just said it could not judge.
# ---------------------------------------------------------------------------
MET=0
MISSED=0
VACUOUS=0
SCORE_LINES=()
VACUITY_LINES=()

# record <id> <description> <rc> [detail]
#
# rc is passed explicitly and captured by the caller on the line immediately after
# the probe. Do NOT inline `$?` alongside a `$(...)` argument: the command
# substitution runs during argument expansion and overwrites `$?`, which silently
# made every expectation report MET while this was being written.
record() {
    local id="$1" desc="$2" rc="$3" detail="${4:-}"
    if [[ $rc -eq 0 ]]; then
        MET=$((MET + 1))
        SCORE_LINES+=("  MET    $id  $desc")
    else
        MISSED=$((MISSED + 1))
        SCORE_LINES+=("  MISSED $id  $desc")
        [[ -n "$detail" ]] && SCORE_LINES+=("           -> $detail")
    fi
    return 0
}

slither_has "reentrancy-eth" "ReentrantBank.withdraw"; rc=$?
guard_predicate slither "E1" "$rc"
detail=""; [[ $rc -eq 0 ]] || detail="slither reported: $(slither_checks)"
record "E1" "slither reports reentrancy-eth in ReentrantBank.withdraw" "$rc" "$detail"

semgrep_has "$SEMGREP_JSON" "state-write-after-external-call" "ReentrantBank.sol"; rc=$?
guard_predicate semgrep "E2" "$rc"
detail=""; [[ $rc -eq 0 ]] || detail="semgrep matched $(semgrep_count "$SEMGREP_JSON") location(s) under src/"
record "E2" "semgrep rule state-write-after-external-call hits src/ReentrantBank.sol" "$rc" "$detail"

forge_outcome "E3"; rc=$?
guard_predicate forge "E3" "$rc"
detail=""; [[ $rc -eq 0 ]] || detail="forge said: $(forge_reason E3)"
record "E3" "forge reproduces the reentrancy drain" "$rc" "$detail"

forge_outcome "E4"; rc=$?
guard_predicate forge "E4" "$rc"
detail=""; [[ $rc -eq 0 ]] || detail="forge said: $(forge_reason E4)"
record "E4" "forge reproduces the zero-share-cost withdrawal" "$rc" "$detail"

forge_outcome "E5"; rc=$?
guard_predicate forge "E5" "$rc"
detail=""; [[ $rc -eq 0 ]] || detail="forge said: $(forge_reason E5)"
record "E5" "forge fuzz confirms the burn path is short across the input space" "$rc" "$detail"

# Rule vacuity guard. E2 would also be "met" by a rule that matched every file, so
# check the rule stays silent on the repaired contracts. This runs in BOTH modes
# and is judged the same way in both: it is a property of the rule, not of src/.
#
# The silence is only meaningful because the scan behind it was validated above:
# it exited 0, reported no errors, is confirmed to have read both repaired files,
# and every match it did report carries the fields this predicate reads. Before
# that validation existed, a crashed semgrep printed OK here -- and so did a
# semgrep whose results omitted check_id, because the resulting exception looked
# exactly like a rule that matched nothing.
semgrep_has "$SEMGREP_CTRL_JSON" "state-write-after-external-call" "negative-control"; rc=$?
guard_predicate semgrep "V1 (rule vacuity guard)" "$rc"
if [[ $rc -eq 0 ]]; then
    VACUITY_LINES+=("  BROKEN V1  semgrep rule also fires on the repaired contracts -- it is not discriminating")
    VACUOUS=1
else
    VACUITY_LINES+=("  OK     V1  semgrep rule read ${#EXPECTED_CTRL[@]} repaired contract(s) and matched none of them")
fi

if [[ $NEGATIVE_CONTROL -eq 1 ]]; then
    semgrep_has "$SEMGREP_LIVE_JSON" "state-write-after-external-call" "ReentrantBank.sol"; rc=$?
    guard_predicate semgrep "V2 (rule vacuity positive control)" "$rc"
    if [[ $rc -eq 0 ]]; then
        VACUITY_LINES+=("  OK     V2  the same rule still fires on the tracked unrepaired src/ -- the silence above is the repair, not a dead rule")
    else
        VACUITY_LINES+=("  BROKEN V2  the rule matches nothing even on the tracked unrepaired src/ -- every miss this run is uninterpretable")
        VACUOUS=1
    fi
fi

# Everything is decided; only now does anything get published.
echo "Expectations (each planted bug against the engine that should catch it):"
printf '%s\n' "${SCORE_LINES[@]}"
echo
echo "Rule vacuity guard (must hold in both modes):"
printf '%s\n' "${VACUITY_LINES[@]}"

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
echo
if [[ $NEGATIVE_CONTROL -eq 1 ]]; then
    echo "NEGATIVE CONTROL: $MISSED of $((MET + MISSED)) expectations missed on repaired sources."
    if [[ $MET -ne 0 ]]; then
        echo "BENCH BROKEN: $MET expectation(s) still met after the bugs were repaired."
        echo "  Those checks cannot fail, so they prove nothing about the toolchain."
        exit $RC_BENCH
    fi
    if [[ $VACUOUS -eq 1 ]]; then
        echo "BENCH BROKEN: the semgrep rule is vacuous."
        exit $RC_BENCH
    fi
    echo "NEGATIVE CONTROL PASS: every expectation stopped firing when its bug was repaired."
    echo "  Every engine above was verified to have run and read the fixtures first, so"
    echo "  these are real misses and not a silent toolchain."
    exit 0
fi

echo "RESULT: $MET met, $MISSED missed."
if [[ $MISSED -ne 0 || $VACUOUS -eq 1 ]]; then
    echo "BENCH FAIL: an engine ran but did not find the bug it is responsible for (see MISSED lines above)."
    echo "  Treat any 'nothing found' hunt result as unreliable until this is green."
    exit $RC_BENCH
fi
echo "BENCH PASS: every planted bug was found by its expected engine."
echo "  Reminder: this proves the pipeline runs, not that it would find a novel bug."
exit 0
