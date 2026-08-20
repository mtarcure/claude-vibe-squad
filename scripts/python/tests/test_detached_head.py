#!/usr/bin/env python3
"""Detached-HEAD behavior for CI imports and branch-identity safety gates."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import launch_hygiene as hygiene  # noqa: E402
import worktree_isolation as wti  # noqa: E402
from scripts.python.tests import test_trusted_launch as trusted_launch  # noqa: E402


GIT_ENV = {
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
}


def _git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=GIT_ENV,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"git {args!r} failed: rc={completed.returncode} "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    return completed


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "v2"], cwd=repo)
    _git(["config", "user.email", "detached-head@example.com"], cwd=repo)
    _git(["config", "user.name", "Detached Head Test"], cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-q", "-m", "detached fixture"], cwd=repo)
    return repo


def _detach(repo: Path) -> None:
    _git(["checkout", "--detach"], cwd=repo)
    symbolic = _git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=repo,
        check=False,
    )
    if symbolic.returncode == 0:
        raise AssertionError(f"fixture did not detach HEAD: {symbolic.stdout!r}")


def _provision(root: Path, *, discriminator: str) -> tuple[Path, wti.WorktreeHandle]:
    repo = _init_repo(root)
    pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
    handle = pool.provision(
        f"TASK-2026-08-20-detached-{discriminator}",
        "d-" + discriminator * 32,
    )
    return repo, handle


def _clone_detached_checkout(root: Path) -> Path:
    """Clone committed context, overlay the files under test, and detach it."""

    repo = root / "repo"
    source_head = _git(["rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    _git(
        ["clone", "--no-local", "--quiet", str(ROOT), str(repo)],
        cwd=root,
    )
    _git(["config", "user.email", "detached-head@example.com"], cwd=repo)
    _git(["config", "user.name", "Detached Head Test"], cwd=repo)
    _git(["checkout", "--quiet", "--detach", source_head], cwd=repo)
    overlay_paths = (
        Path("scripts/python/tests/test_trusted_launch.py"),
        Path("scripts/python/tests/test_golive_integration.py"),
    )
    for relative in overlay_paths:
        shutil.copy2(ROOT / relative, repo / relative)
    _git(["add", *(str(path) for path in overlay_paths)], cwd=repo)
    staged = _git(["diff", "--cached", "--quiet"], cwd=repo, check=False)
    if staged.returncode == 1:
        _git(["commit", "-q", "-m", "overlay detached test inputs"], cwd=repo)
    elif staged.returncode != 0:
        raise AssertionError(f"cannot inspect detached overlay: {staged.stderr!r}")
    _detach(repo)
    return repo


class DetachedHeadSuiteTests(unittest.TestCase):
    def test_trusted_launch_and_golive_pass_in_a_real_detached_checkout(self) -> None:
        """The regression reproducer: committed code and a real detached HEAD."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = _clone_detached_checkout(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "-v",
                    "scripts.python.tests.test_trusted_launch",
                    "scripts.python.tests.test_golive_integration",
                ],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env={
                    **GIT_ENV,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(repo),
                    "SQUAD_CI_HOST_INDEPENDENT": "1",
                },
            )

            self.assertEqual(
                completed.returncode,
                0,
                f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )

    def test_fixture_branch_discovery_treats_detached_head_as_no_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = _init_repo(Path(directory).resolve())
            _detach(repo)

            with mock.patch.dict(os.environ, {"SQUAD_BASE_BRANCH": "v2"}):
                self.assertEqual(trusted_launch._fixture_base_branch(repo), "v2")

    def test_fixture_branch_discovery_does_not_mask_other_git_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            not_a_repo = Path(directory).resolve()

            with self.assertRaisesRegex(RuntimeError, "cannot determine fixture"):
                trusted_launch._fixture_base_branch(not_a_repo)


class DetachedHeadSafetyGateTests(unittest.TestCase):
    def test_launch_request_validation_refuses_a_detached_control_repo(self) -> None:
        """launch_hygiene.py:861 needs the controller's named base branch."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo = _init_repo(root)
            _detach(repo)
            task_root = root / "task-root"
            task_root.mkdir()
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "task_id": "TASK-2026-08-20-detached-launch",
                        "attempt_id": "d-" + "a" * 32,
                        "generation": 1,
                        "branch": "v2",
                        "task_root": str(task_root),
                        "write_paths": [str(task_root)],
                        "profile_bundle_sha256": hygiene.SETTLED_T1P1_BUNDLE_SHA256,
                    }
                ),
                encoding="utf-8",
            )
            synthetic_module_path = repo / "scripts" / "python" / "launch_hygiene.py"

            with (
                mock.patch.object(hygiene, "__file__", str(synthetic_module_path)),
                mock.patch.dict(os.environ, {"SQUAD_BASE_BRANCH": "v2"}),
                self.assertRaisesRegex(
                    hygiene.HygieneError,
                    "repository branch is not v2",
                ),
            ):
                hygiene._load_task_request(request)

    def test_detached_worker_refuses_each_branch_bound_operation(self) -> None:
        """Sites 1002, 1349, 1474, and 1815 must all remain fail closed."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _repo, handle = _provision(root, discriminator="b")
            _detach(handle.worktree_root)

            cases = (
                (
                    "worktree_isolation.py:1002 preserve terminal evidence",
                    lambda: wti._preserve_attempt_evidence(handle, ("README.md",)),
                    "terminal evidence worktree branch identity changed",
                ),
                (
                    "worktree_isolation.py:1349 commit worker residue",
                    lambda: wti.commit_worker_residue(handle, ("README.md",)),
                    "worker worktree is detached or changed branches",
                ),
                (
                    "worktree_isolation.py:1474 integrate worker history",
                    lambda: wti.integrate_worktree_commits(handle, ("README.md",)),
                    "worker worktree is detached or changed branches",
                ),
                (
                    "worktree_isolation.py:1815 derive commit write directories",
                    lambda: wti.linked_worktree_commit_write_dirs(handle),
                    "linked worktree branch identity changed",
                ),
            )
            with mock.patch.dict(os.environ, {"SQUAD_BASE_BRANCH": "v2"}):
                for site, operation, message in cases:
                    with self.subTest(site=site), self.assertRaisesRegex(
                        wti.WorktreeIsolationError,
                        message,
                    ):
                        operation()

    def test_integration_refuses_a_detached_target_repo_without_moving_v2(self) -> None:
        """worktree_isolation.py:1496 must prove the checked-out target branch."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repo, handle = _provision(root, discriminator="c")
            target_before = _git(["rev-parse", "refs/heads/v2"], cwd=repo).stdout.strip()
            _detach(repo)

            with (
                mock.patch.dict(os.environ, {"SQUAD_BASE_BRANCH": "v2"}),
                self.assertRaisesRegex(
                    wti.WorktreeIsolationError,
                    "integration repo is not checked out on v2",
                ),
            ):
                wti.integrate_worktree_commits(handle, ("README.md",))

            target_after = _git(["rev-parse", "refs/heads/v2"], cwd=repo).stdout.strip()
            self.assertEqual(target_after, target_before)


if __name__ == "__main__":
    unittest.main()
