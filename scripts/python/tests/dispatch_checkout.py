"""One home for "a checkout ``bin/send-task.sh`` will actually dispatch from".

``send-task.sh`` refuses to dispatch from a linked git worktree: there the task
registry is a per-worktree stub, so its ``write_scope`` conflict check compares
against ~1 entry instead of the real ~1900 and reports "no conflicts" because it
can no longer see any; and lanes would branch off a branch the coordinator
rebases, which killed a finished lane at integration on 2026-08-15.

That refusal is correct in production, but it runs *before* every other guard in
the script. So any suite that drives the real ``send-task.sh`` becomes red or
green depending only on where the repository happens to be checked out --
a result that depends on the environment rather than on the behaviour under
test. Three suites were affected: ``test_reviewer_dispatch_recursion`` (7
failures), ``test_board_dispatch`` (1) and ``test_host_admission`` (1).

The fix is not to weaken the guard or to special-case it in each suite, but to
give the tests the shape production actually has: a normal checkout. This module
builds one throwaway normal repo per process, from the tree under test, and
hands the same path to every caller.

Use it as::

    from dispatch_checkout import normal_checkout_root
    ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])
"""

from __future__ import annotations

import atexit
import subprocess
import tempfile
from pathlib import Path

_CACHE: dict[Path, Path] = {}
_TMPDIRS: list[tempfile.TemporaryDirectory] = []


def _is_linked_worktree(root: Path) -> bool:
    """True when ``root`` is a linked worktree rather than a main checkout.

    A main checkout has ``--git-dir`` == ``--git-common-dir``; a linked worktree
    points its git-dir at ``.git/worktrees/<name>`` while the common dir stays
    at the parent. This is the same predicate ``send-task.sh`` applies.
    """
    def _rev_parse(flag: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", flag],
            capture_output=True, text=True, check=False,
        ).stdout.strip()

    git_dir = _rev_parse("--git-dir")
    common_dir = _rev_parse("--git-common-dir")
    # An empty result means "not a git repo at all" -- not a worktree, so leave
    # the caller's root alone rather than silently substituting a copy.
    return bool(git_dir) and bool(common_dir) and git_dir != common_dir


def normal_checkout_root(root: Path) -> Path:
    """Return ``root`` if it is already a main checkout, else a copy that is one.

    The copy is built from ``git archive HEAD``, so it carries exactly the
    committed tree under test -- never the working-tree state, which would make
    the tests depend on uncommitted edits.
    """
    root = Path(root).resolve()
    if root in _CACHE:
        return _CACHE[root]
    if not _is_linked_worktree(root):
        _CACHE[root] = root
        return root

    tmp = tempfile.TemporaryDirectory(prefix="vs-normal-checkout-")
    _TMPDIRS.append(tmp)
    repo = Path(tmp.name) / "repo"
    repo.mkdir()
    archive = Path(tmp.name) / "tree.tar"
    subprocess.run(
        ["git", "-C", str(root), "archive", "HEAD", "-o", str(archive)],
        check=True, capture_output=True,
    )
    subprocess.run(["tar", "-xf", str(archive), "-C", str(repo)], check=True)
    for cmd in (
        ["git", "init", "-q", "."],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=tests@vibesquad.local", "-c", "user.name=tests",
         "commit", "-q", "-m", "test checkout"],
    ):
        subprocess.run(cmd, cwd=str(repo), check=False, capture_output=True)
    _CACHE[root] = repo
    return repo


@atexit.register
def _cleanup() -> None:
    for tmp in _TMPDIRS:
        try:
            tmp.cleanup()
        except OSError:
            pass
    _TMPDIRS.clear()
