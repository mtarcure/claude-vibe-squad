#!/usr/bin/env bash
# prune-board-worktrees.sh — reclaim disk from settled board worktrees WITHOUT
# destroying unpromoted worker artifacts.
#
# Why the guard exists (2026-07-30): a naive prune that deleted every worktree
# whose task had reached a terminal status permanently destroyed a 577-line
# Phase-4 chaining analysis and a 488-line economic audit. The reason is subtle
# and worth stating plainly: a `blocked` task is one whose completion envelope
# never promoted — which is exactly why its artifact still lives ONLY inside the
# worktree. Terminal-status pruning therefore targets precisely the worktrees
# whose artifacts exist nowhere else. Worker residue is not always committed, so
# `git fsck` could not recover them either. The loss was total.
#
# This script preserves first and deletes second. Deletes are operator-gated.
#
# Usage:
#   bin/prune-board-worktrees.sh            # dry run: report only
#   bin/prune-board-worktrees.sh --preserve # copy unpromoted artifacts out
#   bin/prune-board-worktrees.sh --apply    # preserve, then prune (destructive)

set -euo pipefail
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
cd "$VAULT_ROOT"

MODE="report"
case "${1:-}" in
  --apply)    MODE="apply" ;;
  --preserve) MODE="preserve" ;;
  ""|--dry-run|--report) MODE="report" ;;
  *) echo "unknown flag: $1" >&2; exit 2 ;;
esac

python3 - "$MODE" <<'PY'
import hashlib, json, os, pathlib, re, shutil, stat, subprocess, sys

mode = sys.argv[1]  # the only input; the rest are this program's constants
RESCUE_DIR = "_state/rescued-worker-artifacts"
TRANSCRIPT_RETENTION_DAYS = 30
TERMINAL = {"complete", "closed", "superseded", "settled", "cancelled"}
BLOCKED_STUB = "board dispatch blocked"

registry = json.load(open("_state/active-tasks.json"))
dispatch = pathlib.Path("_state/board-dispatch")
worktrees = pathlib.Path("_state/board-worktrees")

# Worker session transcripts are descriptor-owned state, not disposable
# worktree/Codex-home residue. Keep every live transcript and every settled
# transcript younger than 30 days; only the explicit --apply path expires older
# settled logs. The durable `skills` count has already been written to
# dispatch-log.jsonl by outbox-watcher before normal settlement cleanup reaches
# this script, so the aggregate survives the bounded raw-transcript window.
# Importing and planning this policy before any worktree removal makes the
# carve-out executable: a missing/broken telemetry module fails before cleanup.
sys.path.insert(0, str(pathlib.Path.cwd() / "scripts" / "python"))
from dispatch_log import DispatchLogError, enforce_transcript_retention

try:
    transcript_summary = enforce_transcript_retention(
        pathlib.Path.cwd(),
        retention_days=TRANSCRIPT_RETENTION_DAYS,
        apply=mode == "apply",
    )
except DispatchLogError as exc:
    raise SystemExit(f"transcript retention policy failed closed: {exc}")
print(
    "transcripts: "
    f"retention={transcript_summary.retention_days}d "
    f"live={transcript_summary.retained_live} "
    f"recent={transcript_summary.retained_recent} "
    f"expired={transcript_summary.expired} "
    f"removed={transcript_summary.removed} "
    f"missing={transcript_summary.missing} "
    f"invalid={transcript_summary.invalid}"
)

owner = {}
for d in dispatch.glob("*.dispatch.json"):
    m = re.match(r"(TASK-.+?)\.(d-[0-9a-f]+)\.dispatch\.json", d.name)
    if m:
        owner[m.group(2)] = m.group(1)

def promoted(task_id):
    """True only if the declared return_artifact is real at the canonical path.

    A 'board dispatch blocked' placeholder counts as NOT promoted: that stub is
    what the supervisor writes when promotion failed, and treating it as real is
    exactly how the 2026-07-30 loss happened."""
    entry = registry.get(task_id) or {}
    rel = (entry.get("return_artifact") or "").strip()
    if not rel:
        return True, "no declared artifact"
    p = pathlib.Path(rel)
    if not p.is_file():
        return False, f"missing at {rel}"
    if BLOCKED_STUB in p.read_text(errors="ignore")[:400].lower():
        return False, f"stub at {rel}"
    return True, rel

prunable, keep, rescue = [], [], []
for wt in sorted(worktrees.glob("d-*")):
    task = owner.get(wt.name)
    if task is None or registry.get(task, {}).get("status") not in TERMINAL:
        keep.append(wt)
        continue
    ok, why = promoted(task)
    (prunable if ok else rescue).append((wt, task, why))

print(f"worktrees: {len(prunable)+len(keep)+len(rescue)}  prunable={len(prunable)}  "
      f"keep-live={len(keep)}  NEEDS-RESCUE={len(rescue)}")
for wt, task, why in rescue:
    print(f"  RESCUE  {wt.name}  {task}  ({why})")

if mode == "report":
    print("\nreport only — rerun with --preserve or --apply")
    sys.exit(0)

def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def residue(wt):
    """Every path git reports as changed, untracked, or ignored-but-present.

    Returns a list of (path, kind) or None. None means the census itself could
    not be trusted, and the caller must RETAIN rather than remove -- a census
    that did not run is not evidence of an empty worktree.

    Three details are load-bearing, each one a way this silently lost data in
    review before it ever ran a night:

    `-z`. Porcelain v1 quotes and C-escapes any path containing a quote,
    backslash, tab or newline, and a naive `.strip('"')` produces a path that
    does not exist -- which then looks like "nothing to preserve". `-z` emits
    raw NUL-delimited names with no quoting, and also removes the need to guess
    at ` -> ` in rename lines, which an ordinary filename can contain.

    `--ignored=traditional`, not `matching`. Measured: `matching` reports an
    ignored directory as a single collapsed `scratch/` entry and omits its
    contents, so testing `is_file()` on it discards the entry, the census
    returns success, and `--force` deletes the directory whole -- taking build
    output, scratch, and any PoC inside it. `traditional` lists the individual
    files (`scratch/payload.bin`), which is what preservation needs.

    Directory expansion is still required, for a different case: a nested git
    repository or submodule reports as a bare `nested/` entry even under
    `traditional` (measured), and its contents would otherwise go uncopied.
    Mutation-tested: disabling expansion fails the nested-repo test. Reverting
    the flag to `matching` does NOT fail, because expansion then walks the
    collapsed `scratch/` entry too -- the two guards overlap deliberately, so
    losing either one alone still preserves the residue.

    Non-regular entries. A submodule appears as a directory; FIFOs and sockets
    cannot be copied at all. Skipping them silently would report a successful
    preservation of something that was never preserved, so an entry that cannot
    be captured makes the whole census untrusted.
    """
    r = subprocess.run(
        ["git", "-C", str(wt), "status", "--porcelain=v1", "-z",
         "--untracked-files=all", "--ignored=traditional"],
        capture_output=True,
    )
    # git reports "I could not look here" as a WARNING with exit 0, and emits
    # NO entry for the subtree it could not read. Measured:
    #     warning: could not open directory 'locked/': Permission denied
    #     rc=0
    # So exit-code-only made a census that ran BLIND over a subtree
    # indistinguishable from one that found the subtree empty, and the caller
    # then removed the worktree with a green "preserved 0 residue file(s)"
    # receipt. Until now that never cost a PoC only because a mode-000
    # directory also blocks `git worktree remove` -- the data survived by
    # accident of POSIX, not by design. Any cause where git cannot readdir at
    # census time but the tree is removable moments later (transient EIO, fd
    # exhaustion, a mount that reappears) loses it silently.
    if r.returncode != 0 or r.stderr.strip():
        return None

    entries, fields = [], r.stdout.split(b"\0")
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        code, raw = field[:2], field[3:]
        # A rename/copy carries its ORIGIN as the next NUL field; the name we
        # must preserve is the destination, already in this field.
        if code[:1] in (b"R", b"C") or code[1:2] in (b"R", b"C"):
            i += 1
        try:
            rel = raw.decode("utf-8", "surrogateescape")
        except Exception:
            return None
        entries.append(wt / rel)

    out = []
    for entry in entries:
        try:
            st = entry.lstat()
        except FileNotFoundError:
            # Vanished between census and read: the worktree is changing under
            # us, so nothing here can be proven safe.
            return None
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            out.append((entry, "symlink"))
        elif stat.S_ISDIR(st.st_mode):
            # Collapsed ignored directory, or a submodule. Walk it: every file
            # under it is residue that would otherwise be deleted unrecorded.
            for sub in entry.rglob("*"):
                try:
                    sst = sub.lstat()
                except OSError:
                    return None
                if stat.S_ISLNK(sst.st_mode):
                    out.append((sub, "symlink"))
                elif stat.S_ISREG(sst.st_mode):
                    out.append((sub, "file"))
                elif not stat.S_ISDIR(sst.st_mode):
                    return None
        elif stat.S_ISREG(st.st_mode):
            out.append((entry, "file"))
        else:
            # FIFO, socket, device: not copyable, so not preservable.
            return None
    return out


def preserve(wt, task, attempt, out):
    """Copy every residue path out. Returns (ok, count).

    ok is False when the census failed, a copy failed, or an existing
    destination holds DIFFERENT bytes. The caller must then retain the
    worktree: partial preservation is not preservation.

    Destinations are keyed by task AND attempt. Keying on task alone made two
    attempts at one task collide, so the second silently "preserved" nothing
    and the source was deleted.

    An existing destination is verified by digest rather than trusted. The
    previous version treated `dest.exists()` as success without reading it, so
    a copy truncated by a full disk was skipped on the next run and the intact
    source removed.
    """
    found = residue(wt)
    if found is None:
        return False, 0
    n = 0
    for src, kind in found:
        dest = out / task / attempt / src.relative_to(wt)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if kind == "symlink":
                target = os.readlink(src)
                if dest.is_symlink():
                    if os.readlink(dest) != target:
                        return False, n
                else:
                    if dest.exists():
                        return False, n
                    os.symlink(target, dest)
            else:
                if dest.exists():
                    if dest.stat().st_size != src.stat().st_size or \
                            _digest(dest) != _digest(src):
                        return False, n
                else:
                    shutil.copy2(src, dest, follow_symlinks=False)
            n += 1
        except OSError:
            return False, n
    return True, n


# Preservation covers EVERY terminal worktree, not just the rescue list.
#
# The previous version preserved only `rescue` -- worktrees whose declared
# artifact was missing -- and then force-removed every `prunable` one without
# ever looking inside it. But `promoted()` proves one declared path exists; it
# proves nothing about untracked residue beside it. A promoted worktree holding
# the only copy of a PoC was deleted with no census and no copy. That is the
# 2026-07-30 loss shape the header warns about, still live on the other branch
# of the same function.
# ONE loop over both lists, deliberately. The defect above was preservation
# living on one branch of this fork and not the other, and two loops doing the
# same thing is how they drifted apart in the first place. Iterating the union
# makes that divergence unwriteable: a worktree cannot reach removal without
# having been through the same census as a rescued one.
saved = 0
out = pathlib.Path(RESCUE_DIR)
unsafe = []
for wt, task, _ in rescue + prunable:
    ok, n = preserve(wt, task, wt.name, out)
    saved += n
    if not ok:
        unsafe.append(wt.name)
# Incomplete preservation withdraws the worktree from pruning. (Names are the
# worktree directory names from one glob, so they are unique across both lists.)
prunable = [row for row in prunable if row[0].name not in set(unsafe)]
print(f"preserved {saved} residue file(s) under {RESCUE_DIR}/")
if unsafe:
    print(f"RETAINED (preservation incomplete): {', '.join(sorted(set(unsafe)))}")

if mode == "preserve":
    sys.exit(0)

removed = 0
refused = []
for wt, _, _ in prunable:
    r = subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # RETAIN, never path-delete. The previous fallback here was
        # `shutil.rmtree(wt, ignore_errors=True)`, which turned git's refusal
        # into an unconditional recursive delete -- and git refuses precisely
        # when it sees state it will not discard. Suppressing that refusal
        # removed the last thing standing between a surprised worktree and
        # permanent loss. A retained worktree costs disk; a deleted one can
        # cost work that exists nowhere else.
        refused.append((wt.name, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "unknown"))
        continue
    removed += 1
if refused:
    for name, why in refused:
        print(f"  RETAINED (git refused removal)  {name}  ({why})")
subprocess.run(["git", "worktree", "prune"], check=False)
print(f"pruned {removed}; rescued-and-retained {len(rescue)}; live retained {len(keep)}")

# Sweep orphaned per-attempt build scratch (/tmp/vs/<attempt>).
#
# board-supervisor.sh points TMPDIR, GOCACHE and CARGO_TARGET_DIR at this root so
# build caches die with their attempt. The sweep exists because the create path
# and the cleanup path are not the same path: a lane that times out, is killed,
# or blocks never runs an orderly teardown, so hooking removal onto a single exit
# would leak exactly the attempts that fail. Keying on "no worktree" is
# self-healing regardless of how the attempt ended.
#
# Unlike a worktree, scratch NEVER holds an unpromoted artifact -- it is build
# cache by construction -- so the preserve-first rule that governs worktrees
# above does not apply, and an orphan is unconditionally safe to remove.
#
# board-codex-homes is swept by the same rule and for the same reason: it is also
# created per attempt (board-supervisor.sh, _prepare_codex_home) and also had no
# reclaim path, leaving 63 orphans. It is small -- config.toml unions, not caches
# -- so this is tidiness rather than disk, but it is the identical defect and
# fixing only the expensive instance would leave the pattern alive.
live_attempts = {p.name for p in worktrees.iterdir() if p.is_dir()}
for label, root, unit, suffix in (
    ("scratch", pathlib.Path("/tmp/vs"), 2**30, "GiB"),
    ("codex-homes", pathlib.Path("_state/board-codex-homes"), 2**20, "MiB"),
):
    if not root.is_dir():
        continue
    swept = swept_bytes = 0
    for d in root.iterdir():
        if not d.is_dir() or d.name in live_attempts:
            continue
        try:
            swept_bytes += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        except OSError:
            pass
        shutil.rmtree(d, ignore_errors=True)
        swept += 1
    print(f"{label}: swept {swept} orphaned attempt root(s), {swept_bytes / unit:.1f} {suffix}")
PY
