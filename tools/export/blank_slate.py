#!/usr/bin/env python3
"""Rehearse the blank-slate public-root cutover locally. Never pushes.

Design spec §2.5 settles what this procedure is allowed to be:

- **Public repo only.** The operator requirement is "same repo, fresh start", to
  keep the stars — stars attach to a repository, not to its contents, so
  replacing content is safe where replacing the repo is not.
- **The export gate is not bypassed.** This tool consumes a candidate tree the
  projector already built and gated; it never re-derives or relaxes that.
- **Deletion is scoped to tracked files only.** Untracked content in the public
  clone is left alone, and nothing outside the throwaway clone is touched at all.
- **`v3-final` is tagged before cutover** so rollback is `git checkout v3-final`.

The three surfaces must not be conflated. Conflating them produces one of three
failures: destroying the private working history, publishing private evidence, or
wiping local state that exists nowhere else.

`--workdir` is deleted outright (`shutil.rmtree`) before the clone is made, so
the protection that matters is on that argument, and it must not depend on the
caller's environment. What this tool refuses, and on what evidence:

- **The private repository** -- derived from this file's own location
  (`tools/export/blank_slate.py` -> repository root) and, when git is available,
  from the shared git directory as well, so a linked worktree also protects the
  primary checkout and vice versa. This derivation cannot be switched off.
- **Any existing git checkout.** `--workdir` is a scratch directory this tool
  creates; a directory that already holds a `.git` is somebody's working copy,
  and deleting it is never the intended operation. This is the backstop for a
  repository the derivation above does not know about.
- **The memory vault** -- best effort, from `$CHRONO_VAULT_ROOT`/`$VAULT_ROOT`
  when set, plus the conventional vault directory under the invoking account's
  home. The vault root is environment-defined by design (see
  `plugins/chrono-vault/vaultroot.py`, which raises without it), so unlike the
  repository this one cannot be derived with certainty. It is therefore an
  ADDITIONAL root, never the only one.

Environment variables can only ADD protected roots here. Before 2026-08-11 the
private repository was guarded through `$VAULT_ROOT` alone, which a plain shell
does not export -- `bin/product-hygiene.sh:12` shows why: every script derives it
locally as a default rather than inheriting it. The docstring claimed a blanket
refusal that, run from an ordinary terminal, protected nothing.

P11.6 asks for implementation AND rehearsal without push. The push is deliberately
not implemented here: the final mutation is an operator-gated `public_release`
action, and a script that can perform it is a script that can perform it by
accident.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path


class BlankSlateError(RuntimeError):
    """A precondition failed. Nothing has been mutated outside the clone."""


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise BlankSlateError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}"
        )
    return result


#: Conventional memory-vault directory names, looked for under the invoking
#: account's home. The vault root is environment-defined by design, so this is a
#: best-effort ADDITION to the derived roots below, never a replacement for one.
VAULT_DIRECTORY_NAMES = ("Obsidian-Chrono",)


def _repository_roots() -> list[tuple[Path, str]]:
    """The private repository, derived from this file rather than the environment.

    `__file__` is the one input a caller cannot forget to set. `parents[2]` walks
    `tools/export/blank_slate.py` back to the repository root.

    The git lookup adds the PRIMARY checkout when this copy is running from a
    linked worktree (and every linked worktree shares that same git directory),
    so the protection does not depend on which checkout the operator happened to
    invoke. It is additive: if git is absent or this is not a repository, the
    `__file__` root above still stands.
    """
    here = Path(__file__).resolve()
    roots = [(here.parents[2], "repository containing this tool")]
    try:
        completed = subprocess.run(
            ["git", "-C", str(here.parent), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return roots
    if completed.returncode == 0:
        common = Path(completed.stdout.strip())
        if common.name == ".git":
            roots.append((common.parent, "primary checkout of this repository"))
    return roots


def _home_directories() -> list[Path]:
    """Both notions of "home", because under a sandbox they disagree.

    `Path.home()` honours `$HOME`; the passwd database is keyed on the effective
    uid and ignores it. A board worker runs with a `$HOME` that is not the
    operator's, so consulting only one of these looks in the wrong place.
    """
    homes: list[Path] = []
    try:
        homes.append(Path(pwd.getpwuid(os.geteuid()).pw_dir))
    except (KeyError, OSError):
        pass
    try:
        homes.append(Path.home())
    except (RuntimeError, OSError):
        pass
    return homes


def _forbidden_roots() -> list[tuple[Path, str]]:
    """Paths this tool must never delete or write into, regardless of arguments.

    Ordered derived-first so a refusal names the strongest reason it has.
    """
    candidates: list[tuple[Path, str]] = list(_repository_roots())
    for home in _home_directories():
        for name in VAULT_DIRECTORY_NAMES:
            candidates.append((home / name, "conventional memory vault"))
    for variable in ("CHRONO_VAULT_ROOT", "VAULT_ROOT"):
        value = os.environ.get(variable)
        if value:
            candidates.append((Path(value), f"${variable}"))

    resolved: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root, reason in candidates:
        try:
            real = root.resolve()
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        resolved.append((real, reason))
    return resolved


def _assert_safe_workdir(workdir: Path) -> None:
    target = workdir.resolve()
    for forbidden, reason in _forbidden_roots():
        if target == forbidden or forbidden in target.parents or target in forbidden.parents:
            raise BlankSlateError(
                f"refusing to use a workdir that overlaps a protected root "
                f"({reason}): {target} vs {forbidden}"
            )
    # Backstop for a repository no derivation above knows about. `--workdir` is
    # scratch space this tool creates and deletes; a directory that already holds
    # a `.git` is somebody's working copy, and `shutil.rmtree` on it is never the
    # operation that was wanted.
    if (target / ".git").exists():
        raise BlankSlateError(
            f"refusing to use a workdir that is already a git checkout: {target}"
        )


def _tracked_files(repo: Path) -> list[str]:
    listing = _run(["git", "ls-files", "-z"], repo).stdout
    return [name for name in listing.split("\0") if name]


def rehearse(
    *,
    candidate: Path,
    public_url: str,
    workdir: Path,
    public_branch: str = "main",
    rollback_tag: str = "v3-final",
) -> dict:
    """Build the cutover commit in a throwaway clone. Returns a receipt. No push."""
    candidate = candidate.resolve()
    if not (candidate / "README.md").is_file():
        raise BlankSlateError(
            f"candidate does not look like a projected tree (no README.md): {candidate}"
        )
    _assert_safe_workdir(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.parent.mkdir(parents=True, exist_ok=True)

    clone = workdir / "public"
    _run(["git", "clone", "--quiet", public_url, str(clone)], workdir.parent)
    _run(["git", "checkout", "--quiet", public_branch], clone)
    before_tip = _run(["git", "rev-parse", "HEAD"], clone).stdout.strip()
    before_files = _tracked_files(clone)

    # Rollback anchor first. If anything later fails, the operator still has a tag
    # sitting on the pre-cutover tip in this rehearsal clone.
    _run(["git", "tag", "-f", rollback_tag, before_tip], clone)

    # Scoped deletion: remove TRACKED files only, one explicit list, never a
    # recursive filesystem wipe. Untracked content in the clone survives, which is
    # what "scoped to tracked files" means and what makes this reversible.
    if before_files:
        _run(["git", "rm", "-r", "--quiet", "--cached", "."], clone)
        for name in before_files:
            path = clone / name
            if path.is_file() or path.is_symlink():
                path.unlink()

    # Copy the gated candidate in. dirs_exist_ok because .git must survive.
    shutil.copytree(candidate, clone, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git"))

    _run(["git", "add", "-A"], clone)
    status = _run(["git", "status", "--porcelain"], clone).stdout
    after_files = sorted(
        name for name in _run(["git", "ls-files", "-z", "--cached"], clone)
        .stdout.split("\0") if name
    )

    receipt = {
        "schema": "blank-slate-rehearsal/v1",
        "pushed": False,
        "public_url": public_url,
        "public_branch": public_branch,
        "rollback_tag": rollback_tag,
        "before_tip": before_tip,
        "before_tracked": len(before_files),
        "after_tracked": len(after_files),
        "removed": sorted(set(before_files) - set(after_files)),
        "added": sorted(set(after_files) - set(before_files)),
        "changed_entries": len([line for line in status.splitlines() if line.strip()]),
        "clone": str(clone),
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse the blank-slate public-root cutover. Never pushes."
    )
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--public-branch", default="main")
    parser.add_argument("--rollback-tag", default="v3-final")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    try:
        receipt = rehearse(
            candidate=args.candidate,
            public_url=args.public_url,
            workdir=args.workdir,
            public_branch=args.public_branch,
            rollback_tag=args.rollback_tag,
        )
    except BlankSlateError as error:
        print(f"blank-slate error: {error}", file=sys.stderr)
        return 1

    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(
        "\nREHEARSAL ONLY — nothing was pushed. The cutover commit is staged in "
        f"{receipt['clone']}.\nPushing is a separate operator-gated public_release action.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
