#!/usr/bin/env python3
"""Cancel preserves a worker's work on a checkout whose branch is not "v2".

Every pre-existing evidence test renames its fixture repo to `v2`
(`test_evidence_promotion.py` setUp: `git branch -M v2`), which is precisely why
this defect survived a green suite: the hardcoded `"v2"` fallback in
`worktree_isolation.preserve_terminal_evidence` always resolved under test and
never on the real checkout, whose branch is `main`. These tests deliberately use
`main` and never rename.

Coverage:
  * end to end through the real `bin/vs-cancel-spawn.sh` against a live process,
  * the inverted control -- pinning the old `"v2"` default reproduces the exact
    `cannot resolve commit 'refs/heads/v2'` failure,
  * the negative control -- an unresolvable base REFUSES instead of guessing,
    and the worktree-retention fallback still fires.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
CANCEL = ROOT / "bin" / "vs-cancel-spawn.sh"
sys.path.insert(0, str(ROOT / "scripts" / "python"))

import board_process_truth as bpt  # noqa: E402
import worktree_isolation as wti  # noqa: E402

TASK_ID = "TASK-2026-08-29-1110-m2"
ATTEMPT_ID = "d-ee9d62d375554964a968021889c0727d"


def _git(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    )
    if completed.returncode:
        raise AssertionError(
            f"git {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


class CancelPreservationBaseBranchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # The vault IS the checkout in production, so the fixture keeps that
        # identity: vs-cancel-spawn.sh derives the base branch from VAULT_ROOT.
        self.vault = Path(self.temporary.name).resolve() / "vault"
        self.pool_root = self.vault / "_state" / "board-worktrees"
        (self.vault / "_state" / "board-dispatch").mkdir(parents=True)
        (self.vault / "scripts" / "python").mkdir(parents=True)
        (self.vault / "bin").mkdir(parents=True)

        _git(["init", "-q", "-b", "main"], cwd=self.vault)
        _git(["config", "user.name", "Base Branch Test"], cwd=self.vault)
        _git(["config", "user.email", "base-branch@example.test"], cwd=self.vault)
        (self.vault / ".gitignore").write_text(
            "_state/\ndepartments/*/outbox/\n__pycache__/\n*.pyc\n", encoding="utf-8"
        )
        (self.vault / "scripts" / "python" / "base.py").write_text(
            "BASE = True\n", encoding="utf-8"
        )
        _git(["add", "."], cwd=self.vault)
        _git(["commit", "-q", "-m", "base"], cwd=self.vault)
        self.assertEqual(_git(["branch", "--show-current"], cwd=self.vault), "main")

        # main() refuses without an executable reconciler; a stub keeps the
        # end-to-end run about preservation rather than about registry closure.
        reconciler = self.vault / "bin" / "registry-reconciler.sh"
        reconciler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        reconciler.chmod(0o755)

        self.authority: dict[str, object] = {
            "task_id": TASK_ID,
            "attempt_id": ATTEMPT_ID,
            "generation": 1,
            "repo_root": str(self.vault),
            "pool_root": str(self.pool_root),
            "write_paths": ["scripts/python"],
        }
        pool = wti.WorktreePool(self.vault, self.pool_root, base_branch="main")
        self.handle = pool.provision(TASK_ID, ATTEMPT_ID)

    # -- fixture helpers ----------------------------------------------------

    def _worker_commits_work(self) -> str:
        """A worker that committed its code, plus one uncommitted in-scope edit."""
        worktree = self.handle.worktree_root
        (worktree / "scripts" / "python" / "committed_work.py").write_text(
            "COMMITTED_BY_A_CANCELLED_WORKER = True\n", encoding="utf-8"
        )
        _git(["add", "scripts/python/committed_work.py"], cwd=worktree)
        _git(["commit", "-q", "-m", "worker: real committed work"], cwd=worktree)
        (worktree / "scripts" / "python" / "uncommitted_work.py").write_text(
            "UNCOMMITTED_RESIDUE = True\n", encoding="utf-8"
        )
        return _git(["rev-parse", "HEAD"], cwd=worktree)

    def _write_descriptor(self, pid: int) -> dict[str, Path]:
        board = self.vault / "_state" / "board-dispatch"
        base = board / f"{TASK_ID}.{ATTEMPT_ID}"
        paths = {
            "dispatch": Path(f"{base}.dispatch.json"),
            "context": Path(f"{base}.context.json"),
            "log": Path(f"{base}.log"),
            "receipt": Path(f"{base}.receipt.json"),
        }
        identity = bpt.observe_process(pid)
        self.assertIsNotNone(identity, "fixture process must be observable")
        paths["log"].touch()
        paths["context"].write_text(
            json.dumps({"authority": self.authority}) + "\n", encoding="utf-8"
        )
        paths["dispatch"].write_text(
            json.dumps(
                {
                    "schema": bpt.DESCRIPTOR_V2,
                    "task_id": TASK_ID,
                    "attempt_id": ATTEMPT_ID,
                    "generation": 1,
                    "created_at": bpt.utc_now(),
                    **identity,
                    "context_path": str(paths["context"]),
                    "log_path": str(paths["log"]),
                    "receipt_path": str(paths["receipt"]),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return paths

    def _run_cancel(self, **extra_env: str) -> tuple[subprocess.CompletedProcess, dict]:
        """Cancel a genuinely live process through the real shell entrypoint."""
        live = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
        self.addCleanup(live.wait)
        self.addCleanup(lambda: live.poll() is None and live.kill())
        paths = self._write_descriptor(live.pid)
        environment = {
            key: value
            for key, value in os.environ.items()
            # Unset so the derivation under test is what supplies the value.
            if key != "SQUAD_BASE_BRANCH"
        }
        environment.update({"VAULT_ROOT": str(self.vault), **extra_env})
        completed = subprocess.run(
            ["bash", str(CANCEL), str(paths["log"])],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        receipt = (
            json.loads(paths["receipt"].read_text(encoding="utf-8"))
            if paths["receipt"].exists()
            else {}
        )
        return completed, receipt

    # -- the defect ---------------------------------------------------------

    def test_cancel_preserves_committed_work_on_a_non_v2_checkout(self) -> None:
        worker_head = self._worker_commits_work()

        completed, receipt = self._run_cancel()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(receipt.get("terminal_outcome"), "cancelled")
        evidence = receipt["evidence_preservation"]
        self.assertIn(
            evidence["status"],
            {"preserved", "preserved_existing"},
            f"preservation failed: {evidence.get('reason')}",
        )
        # A real, named branch -- not "retained in the attempt worktree".
        self.assertEqual(
            evidence["evidence_ref"], f"refs/heads/worktree/{TASK_ID}/{ATTEMPT_ID}"
        )
        self.assertTrue(evidence["evidence_commit"])
        self.assertEqual(
            evidence["evidence_location"],
            f"{evidence['evidence_ref']}@{evidence['evidence_commit']}",
        )
        # The ref resolves in the REPO, so it survives worktree reclamation.
        self.assertEqual(
            _git(["rev-parse", "--verify", evidence["evidence_ref"]], cwd=self.vault),
            evidence["evidence_commit"],
        )
        # The worker's own commit is reachable from the preserved commit, and
        # the uncommitted in-scope residue rode along in the snapshot.
        self.assertEqual(
            _git(
                ["merge-base", "--is-ancestor", worker_head, evidence["evidence_commit"]],
                cwd=self.vault,
            ),
            "",
        )
        self.assertEqual(
            _git(
                ["show", f"{evidence['evidence_commit']}:scripts/python/committed_work.py"],
                cwd=self.vault,
            ),
            "COMMITTED_BY_A_CANCELLED_WORKER = True",
        )
        self.assertIn(
            "scripts/python/uncommitted_work.py", evidence["untracked_residue_paths"]
        )

    def test_pinning_the_old_v2_default_reproduces_the_measured_failure(self) -> None:
        """Inverted control: the literal "v2" default is what broke preservation."""
        self._worker_commits_work()

        completed, receipt = self._run_cancel(SQUAD_BASE_BRANCH="v2")

        # Cancel still terminalises the attempt; only preservation degrades.
        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "error")
        self.assertIn("cannot resolve commit 'refs/heads/v2'", evidence["reason"])
        self.assertTrue(evidence["worktree_retained_required"])
        self.assertEqual(evidence["worktree_location"], str(self.handle.worktree_root))
        self.assertIn("RETAINED ONLY IN", completed.stderr)

    def test_unresolvable_base_refuses_and_still_retains_the_worktree(self) -> None:
        """Negative control: no branch to derive means REFUSE, never guess."""
        self._worker_commits_work()
        _git(["checkout", "-q", "--detach"], cwd=self.vault)

        with self.assertRaises(wti.WorktreeIsolationError) as raised:
            wti.preserve_terminal_evidence(self.authority)
        self.assertIn("refusing to guess", str(raised.exception))

        completed, receipt = self._run_cancel()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "error")
        self.assertIn("refusing to guess", evidence["reason"])
        # The last line of defence is intact: the work is still on disk and the
        # receipt says so loudly rather than reporting a clean cancel.
        self.assertTrue(evidence["worktree_retained_required"])
        self.assertTrue(self.handle.worktree_root.is_dir())
        self.assertIn("RETAINED ONLY IN", completed.stderr)

    # -- the resolver itself ------------------------------------------------

    def test_resolver_precedence_and_refusal(self) -> None:
        previous = os.environ.pop("SQUAD_BASE_BRANCH", None)
        self.addCleanup(
            lambda: os.environ.__setitem__("SQUAD_BASE_BRANCH", previous)
            if previous is not None
            else os.environ.pop("SQUAD_BASE_BRANCH", None)
        )

        # Derived from the checkout when nothing else names it -- never "v2".
        self.assertEqual(wti._resolve_base_branch(self.vault), "main")

        os.environ["SQUAD_BASE_BRANCH"] = "consolidation"
        self.assertEqual(wti._resolve_base_branch(self.vault), "consolidation")
        # A trusted caller argument outranks the environment.
        self.assertEqual(wti._resolve_base_branch(self.vault, "explicit"), "explicit")
        # Blank is not an answer; fall through rather than resolve "".
        os.environ["SQUAD_BASE_BRANCH"] = "   "
        self.assertEqual(wti._resolve_base_branch(self.vault), "main")

        del os.environ["SQUAD_BASE_BRANCH"]
        _git(["checkout", "-q", "--detach"], cwd=self.vault)
        with self.assertRaises(wti.WorktreeIsolationError):
            wti._resolve_base_branch(self.vault)


if __name__ == "__main__":
    unittest.main()
