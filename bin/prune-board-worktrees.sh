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

python3 - "$MODE" "_state/rescued-worker-artifacts" <<'PY'
import json, pathlib, re, shutil, subprocess, sys

mode, rescue_dir = sys.argv[1], sys.argv[2]
TERMINAL = {"complete", "closed", "superseded", "settled", "cancelled"}
BLOCKED_STUB = "board dispatch blocked"

registry = json.load(open("_state/active-tasks.json"))
dispatch = pathlib.Path("_state/board-dispatch")
worktrees = pathlib.Path("_state/board-worktrees")

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

saved = 0
out = pathlib.Path(rescue_dir)
for wt, task, _ in rescue:
    for f in wt.rglob("*.md"):
        if "_state" not in f.parts:
            continue
        dest = out / task / f.relative_to(wt)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(f, dest)
            saved += 1
print(f"preserved {saved} artifact file(s) under {rescue_dir}/")

if mode == "preserve":
    sys.exit(0)

removed = 0
for wt, _, _ in prunable:
    r = subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(wt, ignore_errors=True)
    removed += 1
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
for label, root, unit in (
    ("scratch", pathlib.Path("/tmp/vs"), 2**30),
    ("codex-homes", pathlib.Path("_state/board-codex-homes"), 2**20),
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
    suffix = "GiB" if unit == 2**30 else "MiB"
    print(f"{label}: swept {swept} orphaned attempt root(s), {swept_bytes / unit:.1f} {suffix}")
PY
