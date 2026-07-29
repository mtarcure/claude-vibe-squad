"""Fail-closed audit of a remote's advertised refs against a clean baseline.

A public export can be pristine on ``main`` yet still leak history through a
retained, disjoint ref. GitHub keeps ``refs/pull/N/head`` across a force-push /
clean-slate, so an export projector that only pushes ``main`` can leave the old
lineage publicly fetchable. This audit enumerates every advertised ref and flags
any whose commit is not reachable from the clean baseline ref.

Standalone module (``tools/export`` is not a package): run as
``python3 tools/export/remote_ref_audit.py --remote public``.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def audit_refs(repo_dir, remote: str, clean_ref: str, allow=()) -> list[dict]:
    """Return one record per advertised ref on ``remote``.

    Each record is ``{"ref", "sha", "status"}`` where status is one of
    ``clean-equal`` (== baseline), ``clean-ancestor`` (reachable from baseline),
    ``allowlisted`` (matches an ``allow`` glob), or ``LEAK`` (disjoint from the
    baseline — a retained/unexpected lineage).
    """
    repo = Path(repo_dir)
    _git(repo, "fetch", "--quiet", remote)
    clean_sha = _git(repo, "rev-parse", clean_ref).strip()
    records: list[dict] = []
    for line in _git(repo, "ls-remote", remote).splitlines():
        sha, _, ref = line.partition("\t")
        ref = ref.strip()
        if not ref or ref == "HEAD":
            continue
        if sha == clean_sha:
            status = "clean-equal"
        elif any(fnmatch.fnmatch(ref, glob) for glob in allow):
            status = "allowlisted"
        else:
            is_ancestor = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, clean_sha]
            ).returncode == 0
            status = "clean-ancestor" if is_ancestor else "LEAK"
        records.append({"ref": ref, "sha": sha, "status": status})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="public")
    parser.add_argument("--clean-ref", default="refs/remotes/public/main")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--allow", nargs="*", default=[])
    args = parser.parse_args()

    records = audit_refs(args.repo, args.remote, args.clean_ref, tuple(args.allow))
    leaks = [r for r in records if r["status"] == "LEAK"]
    for record in records:
        print(f"{record['sha']}  {record['ref']}  {record['status']}")
    if leaks:
        print(
            f"FAIL: {len(leaks)} advertised ref(s) not reachable from {args.clean_ref}",
            file=sys.stderr,
        )
        return 1
    print("PASS: every advertised ref is clean vs the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
