#!/usr/bin/env python3
"""Phase 0: the reaper must not destroy untracked work.

`bin/prune-board-worktrees.sh` classifies a terminal worktree as `prunable` when
its DECLARED return_artifact was promoted, then force-removes it. Preservation
runs only over the `rescue` list -- so a prunable worktree is deleted without
anyone ever looking for untracked residue inside it.

That residue is exactly where bounty proof-of-concept material lives: untracked,
often not markdown, and the only copy. The operator has lost PoCs this way.

Two further defects compound it:
  - the rescue copier walks `wt.rglob("*.md")` and skips anything whose path
    lacks an `_state` part, so a non-markdown PoC is never copied even when a
    worktree IS rescued;
  - a failed `git worktree remove` falls through to `shutil.rmtree(...,
    ignore_errors=True)`, converting a refusal to delete into a deletion.

These tests drive the script in `--preserve` mode, which stops before any
removal, so they can assert the preservation contract without destroying
anything.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "bin" / "prune-board-worktrees.sh"
ATTEMPT = "d-00000000000000000000000000000001"
TASK = "TASK-2026-09-01-0000-preservetest"


class PrunePreservesUntrackedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="prune-preserve-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        # A REAL git repo with a REAL worktree: the preservation census is
        # `git status --porcelain`, so a plain directory would fail the census
        # and (correctly) be retained rather than preserved -- which would test
        # the fail-safe path instead of the one that matters.
        def git(*args, cwd=None):
            subprocess.run(["git", *args], cwd=cwd or self.root, check=True,
                           capture_output=True)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@t"); git("config", "user.name", "t")
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        # A real ignore rule: without one, the collapsed-ignored-directory case
        # -- the bug that deleted whole directories while reporting success --
        # is unreachable and the test proves nothing about it.
        (self.root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
        git("add", "seed.txt", ".gitignore"); git("commit", "-qm", "seed")
        self._git = git

        # The script resolves everything from cwd and imports dispatch_log from
        # <cwd>/scripts/python, so the fixture mirrors that shape.
        (self.root / "scripts").mkdir(parents=True)
        os.symlink(REPO_ROOT / "scripts" / "python", self.root / "scripts" / "python")

        self.state = self.root / "_state"
        (self.state / "board-dispatch").mkdir(parents=True)
        self.worktree = self.state / "board-worktrees" / ATTEMPT
        (self.state / "board-worktrees").mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-q", "-b", ATTEMPT, str(self.worktree))
        self.rescue_dir = self.state / "rescued-worker-artifacts"

        # A promoted declared artifact: this is what makes the worktree
        # "prunable" and therefore eligible for silent removal.
        artifact = self.root / "departments" / "coding" / "outbox"
        artifact.mkdir(parents=True)
        (artifact / f"{TASK}-response.md").write_text("real result\n", encoding="utf-8")

        (self.state / "board-dispatch" / f"{TASK}.{ATTEMPT}.dispatch.json").write_text(
            json.dumps({"task_id": TASK}), encoding="utf-8"
        )
        (self.state / "active-tasks.json").write_text(
            json.dumps(
                {
                    TASK: {
                        "status": "complete",
                        "return_artifact": f"departments/coding/outbox/{TASK}-response.md",
                    }
                }
            ),
            encoding="utf-8",
        )

    def _run_preserve(self) -> subprocess.CompletedProcess:
        env = dict(os.environ, VAULT_ROOT=str(self.root))
        return subprocess.run(
            ["bash", str(SCRIPT), "--preserve"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _preserved_names(self) -> set[str]:
        if not self.rescue_dir.exists():
            return set()
        return {p.name for p in self.rescue_dir.rglob("*") if p.is_file()}

    def _preserved_bytes(self, relative: str) -> bytes | None:
        """Bytes at the exact preserved PATH, not merely a matching basename."""
        hit = list(self.rescue_dir.rglob(relative))
        return hit[0].read_bytes() if hit else None

    def _run_apply(self) -> subprocess.CompletedProcess:
        env = dict(os.environ, VAULT_ROOT=str(self.root))
        return subprocess.run(
            ["bash", str(SCRIPT), "--apply"],
            cwd=self.root, env=env, capture_output=True, text=True, check=False,
        )

    def test_untracked_non_markdown_poc_is_preserved(self) -> None:
        """The failure that costs real work: a PoC in a promoted worktree."""
        (self.worktree / "poc.py").write_text("# exploit\n", encoding="utf-8")
        result = self._run_preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "poc.py",
            self._preserved_names(),
            "an untracked non-markdown file in a PRUNABLE worktree was not "
            f"preserved; the worktree is force-removed next.\n{result.stdout}",
        )

    def test_in_tree_markdown_outside_state_is_preserved(self) -> None:
        """The rescue filter skips any path without an `_state` part."""
        p = self.worktree / "departments" / "coding" / "outbox"
        p.mkdir(parents=True)
        (p / f"{TASK}-response.md").write_text("worker output\n", encoding="utf-8")
        result = self._run_preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"{TASK}-response.md",
            self._preserved_names(),
            f"in-tree markdown outside _state was not preserved.\n{result.stdout}",
        )

    def test_contents_of_an_ignored_directory_are_preserved(self) -> None:
        """Guards the `--ignored=matching` -> `traditional` change.

        `matching` collapses an ignored directory to one `scratch/` entry and
        omits its contents; `traditional` lists the files. Mutating the flag
        back makes this fail.
        """
        scratch = self.worktree / "scratch"
        scratch.mkdir()
        (scratch / "payload.bin").write_bytes(b"\x00PAYLOAD\xff")
        result = self._run_preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._preserved_bytes("payload.bin"), b"\x00PAYLOAD\xff",
            f"ignored-directory contents were not preserved.\n{result.stdout}",
        )

    def test_contents_of_a_nested_repository_are_preserved(self) -> None:
        """A submodule/nested repo reports as a bare `nested/` DIRECTORY entry.

        Measured: even under --ignored=traditional, git emits `?? nested/`
        rather than its files. Without directory expansion, is_file() discards
        that entry, the census reports success, and --force deletes the repo
        and everything in it. This is the case expansion exists for -- an
        earlier version of this test used an ignored directory instead and
        passed with expansion disabled, proving nothing.
        """
        nested = self.worktree / "nested"
        nested.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=nested,
                       check=True, capture_output=True)
        (nested / "poc.py").write_bytes(b"NESTED-POC")
        result = self._run_preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._preserved_bytes("poc.py"), b"NESTED-POC",
            "contents of a nested repository were not preserved; the whole "
            f"directory is deleted next.\n{result.stdout}",
        )

    def test_preserved_copy_is_byte_exact_at_its_relative_path(self) -> None:
        body = b"line1\nline2\n\x00binary\n"
        (self.worktree / "poc.py").write_bytes(body)
        result = self._run_preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._preserved_bytes("poc.py"), body,
            f"preserved copy differs from the source.\n{result.stdout}",
        )

    def test_apply_retains_a_worktree_whose_residue_cannot_be_preserved(self) -> None:
        """A destination holding DIFFERENT bytes must block removal.

        The previous version treated `dest.exists()` as success without reading
        it, so a copy truncated by a full disk was skipped on the next run and
        the intact source deleted.
        """
        (self.worktree / "poc.py").write_bytes(b"REAL")
        planted = self.rescue_dir / TASK / ATTEMPT / "poc.py"
        planted.parent.mkdir(parents=True)
        planted.write_bytes(b"TRUNCATED")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            self.worktree.exists(),
            f"worktree was removed despite unpreservable residue.\n{result.stdout}",
        )
        self.assertEqual(planted.read_bytes(), b"TRUNCATED",
                         "the mismatched destination was silently overwritten")

    def test_removal_never_falls_back_to_rmtree(self) -> None:
        """A refused `git worktree remove` must retain, never path-delete."""
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("for wt, _, _ in prunable:")
        end = source.index("git\", \"worktree\", \"prune\"", start)
        # Strip comments before scanning. The removal block deliberately NAMES
        # the old fallback in a comment explaining why it was removed, and a
        # substring check would match that explanation -- the same trap as
        # test_lane_agy_repoint.py:83, which pins a function by counting
        # occurrences in source text and is satisfied by the `def` line alone.
        removal_block = "\n".join(
            line for line in source[start:end].splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn(
            "shutil.rmtree",
            removal_block,
            "the rmtree fallback converts a failed git removal into an "
            "unconditional deletion of the worktree and everything in it. "
            "(The scratch/codex-home sweep may use rmtree -- that is build "
            "cache by construction; this assertion covers only worktrees.)",
        )


if __name__ == "__main__":
    unittest.main()


class BlindCensusIsNotAnEmptyCensusTests(PrunePreservesUntrackedTests):
    """git reports "I could not look here" as a WARNING with exit 0.

    Measured:

        $ git status --porcelain=v1 -z -uall --ignored=traditional
        warning: could not open directory 'locked/': Permission denied
        rc=0                          # and NO entry emitted for locked/

    So `residue()` returned a list with the whole subtree missing, `preserve()`
    reported (True, 0) -- "safe, nothing to preserve" -- and the worktree went
    to removal with a green receipt saying `preserved 0 residue file(s)`.

    A census that ran BLIND over a subtree is the same fact as a census that
    did not run, wearing a success code. The only reason this has not cost a
    PoC is that a mode-000 directory also blocks `git worktree remove` -- the
    data survived by accident of POSIX, not by design. Any cause where git
    cannot readdir at census time but the tree is removable moments later
    (transient EIO, fd exhaustion, a mount that reappears) loses it silently.

    Catches: reverting to `if r.returncode != 0` alone.
    """

    def test_an_unreadable_subtree_makes_the_census_untrusted(self) -> None:
        locked = self.worktree / "locked"
        locked.mkdir()
        (locked / "poc.py").write_bytes(b"SECRET-POC")
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o755)
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Assert on WHY it was retained, not merely THAT it was. A mode-000
        # directory also blocks `git worktree remove`, so the worktree survives
        # either way and an existence check passes against the unfixed code --
        # which is exactly the accident this test exists to stop relying on.
        # "preservation incomplete" is the by-design path; "git refused
        # removal" is the accident.
        self.assertIn(
            "RETAINED (preservation incomplete)", result.stdout,
            "the census read past an unreadable subtree and reported the "
            "worktree safe to remove; it survived only because POSIX also "
            f"blocked the delete.\n{result.stdout}",
        )

    def test_a_readable_worktree_is_still_prunable(self) -> None:
        """Control: the fix must not retain every worktree.

        Without this, 'return None on any stderr' would look correct while
        making the reaper useless -- the over-tight-gate failure.
        """
        (self.worktree / "poc.py").write_bytes(b"REAL")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._preserved_bytes("poc.py"), b"REAL",
            f"a clean worktree was not preserved+pruned normally.\n{result.stdout}",
        )
