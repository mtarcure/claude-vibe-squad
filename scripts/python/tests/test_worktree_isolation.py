#!/usr/bin/env python3
"""Invariant tests for V2 worktree-per-instance isolation and F4 .git denials."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import worktree_isolation as wti  # noqa: E402
import board_router  # noqa: E402


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {args} failed: {completed.stderr}")
    return completed


def _init_repo(root: Path, *, integration_branch: str = "v2") -> Path:
    """Real git repo with an integration branch, a second shared branch, and a fake remote."""

    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", integration_branch], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    _git(["branch", "main"], cwd=repo)
    remote_repo = root / "remote.git"
    _git(["init", "-q", "--bare", str(remote_repo)], cwd=root)
    _git(["remote", "add", "origin", str(remote_repo)], cwd=repo)
    _git(["push", "-q", "origin", f"{integration_branch}:{integration_branch}"], cwd=repo)
    _git(["update-ref", f"refs/remotes/origin/{integration_branch}", integration_branch], cwd=repo)
    return repo


def _add_worktree(repo: Path, worktree_root: Path, branch: str, base: str) -> None:
    _git(["worktree", "add", "-q", "-b", branch, str(worktree_root), base], cwd=repo)


class GitCommonDirTests(unittest.TestCase):
    def test_common_dir_is_the_same_from_main_repo_and_a_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            worktree_root = root / "wt-a"
            _add_worktree(repo, worktree_root, "task/a", "v2")

            from_main = wti.git_common_dir(repo)
            from_worktree = wti.git_common_dir(worktree_root)

            self.assertEqual(from_main, from_worktree)
            self.assertTrue(from_main.is_dir())
            self.assertEqual(from_main, Path(os.path.realpath(repo / ".git")))

    def test_common_dir_rejects_a_non_canonical_or_non_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(wti.WorktreeIsolationError):
                wti.git_common_dir(root / "not-a-repo")
            with self.assertRaises(wti.WorktreeIsolationError):
                wti.git_common_dir(Path("relative/path"))


class WriteScopeValidationTests(unittest.TestCase):
    def test_worktree_root_is_accepted_as_its_own_write_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            worktree_root = root / "wt-a"
            _add_worktree(repo, worktree_root, "task/a", "v2")

            scope = wti.worktree_write_scope_paths(worktree_root, repo)

            self.assertEqual(scope, (Path(os.path.realpath(worktree_root)),))

    def test_the_shared_git_common_dir_itself_is_rejected_as_a_worktree_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "shared git"):
                wti.worktree_write_scope_paths(repo / ".git", repo)

    def test_a_path_inside_the_shared_git_common_dir_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "shared git"):
                wti.worktree_write_scope_paths(repo / ".git" / "hooks", repo)

    def test_a_path_that_is_not_a_registered_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            impostor = root / "not-a-worktree"
            impostor.mkdir()

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "not a registered"):
                wti.worktree_write_scope_paths(impostor, repo)

    def test_a_symlink_to_a_real_registered_worktree_resolves_to_the_same_safe_scope(self) -> None:
        # A symlink whose realpath IS a genuinely registered worktree is not a bypass:
        # both this function and seatbelt_profile.compile_profile realpath before
        # granting, so the alias and the real path always yield the identical,
        # correctly-scoped grant. Rejecting it would just be security theater.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            worktree_root = root / "wt-a"
            _add_worktree(repo, worktree_root, "task/a", "v2")
            alias = root / "wt-a-alias"
            alias.symlink_to(worktree_root)

            scope = wti.worktree_write_scope_paths(alias, repo)

            self.assertEqual(scope, (Path(os.path.realpath(worktree_root)),))

    def test_a_symlink_to_a_non_worktree_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            impostor = root / "not-a-worktree"
            impostor.mkdir()
            alias = root / "impostor-alias"
            alias.symlink_to(impostor)

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "not a registered"):
                wti.worktree_write_scope_paths(alias, repo)


class ScopeGlobRefusalTests(unittest.TestCase):
    """A glob in a scope is refused, because it would match nothing silently.

    Scopes are prefix paths compared on path components, so `dir/**` is a
    literal component that contains no file. Accepting it reads as a granted
    scope and behaves as an empty one -- measured 2026-08-31, when every edit
    of an otherwise-correct task was flagged out-of-scope.
    """

    def test_glob_scope_is_refused_with_the_prefix_form_named(self):
        for value in ("scripts/python/tests/**", "_state/scratch/**", "a/*", "a/f?le", "a/[ab]"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(wti.WorktreeIsolationError, "never glob-expanded"):
                    wti._normalized_relative(value, label="write_scope entry")

    def test_the_prefix_form_the_error_recommends_is_accepted_and_contains_its_subtree(self):
        scope = wti._normalized_relative("scripts/python/tests", label="write_scope entry")
        member = wti.PurePosixPath("scripts/python/tests/test_dryrun_parity.py")
        self.assertTrue(wti._is_contained(member, [scope]))
        # The glob form would have been vacuous, which is the whole bug.
        self.assertFalse(
            wti._is_contained(member, [wti.PurePosixPath("scripts/python/tests/**")])
        )


class WorktreePoolTests(unittest.TestCase):
    def test_two_concurrent_provisions_get_disjoint_worktree_roots_on_disjoint_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")

            handle_a = pool.provision("TASK-2026-07-22-0001-alpha", "d-" + "a" * 32)
            handle_b = pool.provision("TASK-2026-07-22-0002-beta", "d-" + "b" * 32)

            self.assertNotEqual(handle_a.worktree_root, handle_b.worktree_root)
            self.assertNotEqual(handle_a.branch, handle_b.branch)
            self.assertNotEqual(handle_a.branch, "v2")
            self.assertNotEqual(handle_b.branch, "v2")
            self.assertTrue(handle_a.worktree_root.is_dir())
            self.assertTrue(handle_b.worktree_root.is_dir())
            self.assertEqual(set(h.task_id for h in pool.active()), {handle_a.task_id, handle_b.task_id})

    def test_provisioning_the_same_task_and_attempt_twice_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            attempt = "d-" + "c" * 32
            pool.provision("TASK-2026-07-22-0003-gamma", attempt)

            with self.assertRaises(wti.WorktreeIsolationError):
                pool.provision("TASK-2026-07-22-0003-gamma", attempt)

    def test_release_removes_the_worktree_and_it_is_no_longer_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0004-delta", "d-" + "d" * 32)
            worktree_path = handle.worktree_root

            pool.release(handle)

            self.assertEqual(pool.active(), ())
            self.assertFalse(worktree_path.exists())
            listed = _git(["worktree", "list", "--porcelain"], cwd=repo).stdout
            self.assertNotIn(str(worktree_path), listed)

    def test_release_sweeps_ignored_in_scope_evidence_before_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            (repo / ".gitignore").write_text("_state/\n", encoding="utf-8")
            _git(["add", ".gitignore"], cwd=repo)
            _git(["commit", "-q", "-m", "ignore runtime state"], cwd=repo)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision(
                "TASK-2026-07-22-0007-release-evidence",
                "d-" + "7" * 32,
            )
            ledger = handle.worktree_root / "_state" / "lane-ledger.md"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("durable lane evidence\n", encoding="utf-8")

            receipt = wti.integrate_worktree_commits(
                handle, ("_state/lane-ledger.md",)
            )
            self.assertEqual(receipt.status, "no-committed-in-scope-changes")
            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "pre-release evidence sweep retained"
            ):
                pool.release(handle)

            self.assertTrue(handle.worktree_root.is_dir())
            preserved = _git(
                ["show", f"refs/heads/{handle.branch}:_state/lane-ledger.md"],
                cwd=repo,
            ).stdout
            self.assertEqual(preserved, "durable lane evidence\n")

    def test_high_assurance_provisioning_requires_dedicated_volume_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "dedicated volume"):
                pool.provision(
                    "TASK-2026-07-22-0005-epsilon",
                    "d-" + "e" * 32,
                    high_assurance=True,
                )

            handle = pool.provision(
                "TASK-2026-07-22-0006-zeta",
                "d-" + "f" * 32,
                high_assurance=True,
                dedicated_volume_attested=True,
            )
            self.assertTrue(handle.worktree_root.is_dir())


class TerminalEvidenceOutputIdentityTests(unittest.TestCase):
    OUTPUT = "departments/coding/outbox/TASK-2026-08-30-0858-output-response.md"

    def _provision(self, root: Path) -> tuple[Path, Path, wti.WorktreeHandle]:
        repo = _init_repo(root)
        pool_root = root / "pool"
        handle = wti.WorktreePool(repo, pool_root, base_branch="v2").provision(
            "TASK-2026-08-30-0858-output",
            "d-" + "a" * 32,
        )
        return repo, pool_root, handle

    def test_result_and_outbox_may_intentionally_share_one_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, pool_root, handle = self._provision(Path(directory))
            output = handle.worktree_root / self.OUTPUT
            output.parent.mkdir(parents=True)
            output.write_text(
                "original terminal cause: HTTP 403 quota exhausted\n",
                encoding="utf-8",
            )
            authority = {
                "task_id": handle.task_id,
                "attempt_id": handle.attempt_id,
                "repo_root": str(repo),
                "pool_root": str(pool_root),
                "write_paths": [self.OUTPUT],
                "expected_result_path": self.OUTPUT,
                "expected_outbox_path": self.OUTPUT,
            }

            evidence = wti.preserve_terminal_evidence(authority, base_branch="v2")

            self.assertEqual(evidence.status, "preserved")
            self.assertEqual(evidence.explicit_output_paths, (self.OUTPUT,))
            preserved = _git(
                ["show", f"{evidence.evidence_commit}:{self.OUTPUT}"],
                cwd=repo,
            ).stdout
            self.assertEqual(
                preserved,
                "original terminal cause: HTTP 403 quota exhausted\n",
            )

    def test_distinct_required_outputs_colliding_after_normalization_are_refused(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, _pool_root, handle = self._provision(Path(directory))
            lexical_alias = self.OUTPUT.replace("/outbox/", "/outbox//")

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError,
                "explicit evidence outputs contain duplicates",
            ):
                wti._preserve_attempt_evidence(
                    handle,
                    (self.OUTPUT,),
                    # These entries model distinct required outputs whose
                    # spellings resolve to the same repository path.
                    explicit_output_paths=(self.OUTPUT, lexical_alias),
                )


class ReleaseHandleIdentityTests(unittest.TestCase):
    """REJECT defect 1 (P1): release() must never trust a caller-supplied handle."""

    def test_release_rejects_a_forged_handle_with_a_matching_key_but_a_different_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle_a = pool.provision("TASK-2026-07-22-0010-victim-a", "d-" + "1" * 32)
            handle_b = pool.provision("TASK-2026-07-22-0011-victim-b", "d-" + "2" * 32)

            forged = wti.WorktreeHandle(
                task_id=handle_a.task_id,
                attempt_id=handle_a.attempt_id,
                branch=handle_b.branch,
                worktree_root=handle_b.worktree_root,
                repo_root=handle_a.repo_root,
            )

            with self.assertRaises(wti.WorktreeIsolationError):
                pool.release(forged)

            # Neither victim's filesystem state nor the pool map changed.
            self.assertTrue(handle_a.worktree_root.is_dir())
            self.assertTrue(handle_b.worktree_root.is_dir())
            self.assertEqual(
                {h.task_id for h in pool.active()}, {handle_a.task_id, handle_b.task_id}
            )

    def test_release_rejects_a_cross_pool_handle_with_the_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root_1 = base / "pool-one"
            root_2 = base / "pool-two"
            root_1.mkdir()
            root_2.mkdir()
            repo_1 = _init_repo(root_1)
            repo_2 = _init_repo(root_2)
            pool_1 = wti.WorktreePool(repo_1, root_1 / "pool", base_branch="v2")
            pool_2 = wti.WorktreePool(repo_2, root_2 / "pool", base_branch="v2")
            attempt = "d-" + "c" * 32
            handle_1 = pool_1.provision("TASK-2026-07-22-0021-cross-pool", attempt)
            handle_2 = pool_2.provision("TASK-2026-07-22-0021-cross-pool", attempt)

            with self.assertRaises(wti.WorktreeIsolationError):
                pool_1.release(handle_2)

            self.assertTrue(handle_1.worktree_root.is_dir())
            self.assertEqual({h.task_id for h in pool_1.active()}, {handle_1.task_id})


class ProvisionTransactionalRollbackTests(unittest.TestCase):
    """REJECT defect 2 (P1): a failed provision must leave zero shared-git trace."""

    def test_provision_leaves_no_worktree_or_branch_when_pool_root_is_inside_shared_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            forbidden_pool_root = repo / ".git" / "pool"
            pool = wti.WorktreePool(repo, forbidden_pool_root, base_branch="v2")
            attempt = "d-" + "3" * 32

            with self.assertRaises(wti.WorktreeIsolationError):
                pool.provision("TASK-2026-07-22-0012-rollback", attempt)

            self.assertEqual(pool.active(), ())
            listed = _git(["worktree", "list", "--porcelain"], cwd=repo).stdout
            self.assertNotIn(attempt, listed)
            branches = _git(["branch", "--list"], cwd=repo).stdout
            self.assertNotIn("worktree/TASK-2026-07-22-0012-rollback", branches)

    def test_provision_rolls_back_the_real_worktree_and_branch_when_post_add_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            attempt = "d-" + "4" * 32

            original_validator = wti.worktree_write_scope_paths

            def _always_fail(worktree_root, repo_root):
                raise wti.WorktreeIsolationError("forced post-add validation failure for the test")

            wti.worktree_write_scope_paths = _always_fail
            try:
                with self.assertRaises(wti.WorktreeIsolationError):
                    pool.provision("TASK-2026-07-22-0013-postfail", attempt)
            finally:
                wti.worktree_write_scope_paths = original_validator

            self.assertEqual(pool.active(), ())
            listed = _git(["worktree", "list", "--porcelain"], cwd=repo).stdout
            self.assertNotIn(attempt, listed)
            branches = _git(["branch", "--list"], cwd=repo).stdout
            self.assertNotIn("worktree/TASK-2026-07-22-0013-postfail", branches)


class BoardIntegrationTests(unittest.TestCase):
    def test_to_board_task_attaches_read_only_git_claims_and_the_worktree_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0007-eta", "d-" + "1" * 32)

            task = wti.to_board_task(handle)

            self.assertEqual(task.worktree_root, str(handle.worktree_root))
            self.assertTrue(all(claim.mode == "read" for claim in task.resources))
            self.assertEqual(
                {claim.resource_class for claim in task.resources},
                set(wti.GIT_RESOURCE_CLASSES),
            )
            for claim in task.resources:
                self.assertIn(claim.resource_class, board_router.KNOWN_RESOURCE_CLASSES)

    def test_two_worktree_board_tasks_parallelize_via_the_real_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle_a = pool.provision("TASK-2026-07-22-0008-theta", "d-" + "2" * 32)
            handle_b = pool.provision("TASK-2026-07-22-0009-iota", "d-" + "3" * 32)

            task_a = wti.to_board_task(handle_a)
            task_b = wti.to_board_task(handle_b)

            self.assertTrue(
                board_router.can_parallelize(
                    task_a,
                    task_b,
                    dependency_index=board_router.build_dependency_index((task_a, task_b)),
                    capacities={},
                )
            )
            result = board_router.schedule(
                (task_a, task_b), concurrency=2, logical_only=True
            )
            self.assertEqual(set(result.run_now), {task_a.task_id, task_b.task_id})


class ToBoardTaskScopeValidationTests(unittest.TestCase):
    """REJECT defect 3 (P2): the scheduler seam must reject fabricated scope."""

    def test_to_board_task_rejects_a_caller_write_path_pointing_at_shared_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0014-scope-a", "d-" + "5" * 32)

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.to_board_task(handle, write_paths=(str(repo / ".git"),))

    def test_to_board_task_rejects_a_caller_write_path_pointing_at_a_sibling_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle_a = pool.provision("TASK-2026-07-22-0015-scope-b", "d-" + "6" * 32)
            handle_b = pool.provision("TASK-2026-07-22-0016-scope-c", "d-" + "7" * 32)

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.to_board_task(handle_a, write_paths=(str(handle_b.worktree_root),))

    def test_to_board_task_rejects_a_relative_caller_write_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0017-scope-d", "d-" + "8" * 32)

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.to_board_task(handle, write_paths=("relative/escape",))

    def test_to_board_task_rejects_a_symlink_write_path_that_resolves_to_shared_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0018-scope-e", "d-" + "9" * 32)
            escape_link = handle.worktree_root / "escape-to-git"
            escape_link.symlink_to(wti.git_common_dir(repo))

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.to_board_task(handle, write_paths=(str(escape_link),))

    def test_to_board_task_rejects_a_fabricated_handle_that_is_not_a_registered_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            fabricated = wti.WorktreeHandle(
                task_id="TASK-2026-07-22-0019-fabricated",
                attempt_id="d-" + "0" * 32,
                branch="worktree/fake",
                worktree_root=repo / ".git",
                repo_root=repo,
            )

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.to_board_task(fabricated)

    def test_to_board_task_still_accepts_the_legitimate_caller_supplied_write_path(self) -> None:
        # Backward-compat proof: bin/board-supervisor.sh's trusted-launch composition
        # (outside this task's write scope, must keep working unmodified) calls
        # to_board_task(handle, write_paths=(str(handle.worktree_root),)) -- the
        # fix must not reject the one legitimate value that call site passes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = _init_repo(root)
            pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
            handle = pool.provision("TASK-2026-07-22-0020-scope-legit", "d-" + "b" * 32)

            task = wti.to_board_task(handle, write_paths=(str(handle.worktree_root),))

            self.assertEqual(task.write_paths, (str(handle.worktree_root),))


class WorktreeCommitIntegrationTests(unittest.TestCase):
    def _provision(self, root: Path):
        repo = _init_repo(root)
        pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
        handle = pool.provision(
            "TASK-2026-07-23-9901-integrate",
            "d-" + "a" * 32,
        )
        return repo, handle

    def _worker_commit(
        self,
        handle: wti.WorktreeHandle,
        paths: dict[str, str],
        *,
        message: str = "worker change",
    ) -> str:
        for relative, content in paths.items():
            destination = handle.worktree_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        _git(["add", "--", *paths], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", message], cwd=handle.worktree_root)
        return _git(["rev-parse", "HEAD"], cwd=handle.worktree_root).stdout.strip()

    def test_exact_base_fast_forwards_the_original_worker_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            worker_head = self._worker_commit(
                handle,
                {"_state/integration/code.txt": "worker landed\n"},
            )

            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/",),
            )

            self.assertEqual(receipt.status, "integrated")
            self.assertTrue(receipt.exact_worker_history)
            self.assertEqual(receipt.integration_commit, worker_head)
            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                worker_head,
            )
            self.assertEqual(
                (repo / "_state/integration/code.txt").read_text(encoding="utf-8"),
                "worker landed\n",
            )

    def test_linked_commit_scope_excludes_the_v2_ref_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            common = wti.git_common_dir(repo)

            directories = wti.linked_worktree_commit_write_dirs(handle)

            self.assertEqual(
                directories[0],
                common / "worktrees" / handle.attempt_id,
            )
            self.assertIn(common / "objects", directories)
            self.assertIn(
                common / "refs/heads" / Path(handle.branch).parent,
                directories,
            )
            self.assertNotIn(common / "refs/heads", directories)
            self.assertNotIn((common / "refs/heads/v2").parent, directories)

    def test_uncommitted_out_of_scope_probe_is_contained_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_commit(
                handle,
                {"_state/integration/code.txt": "in scope\n"},
            )
            (handle.worktree_root / "outside-probe.txt").write_text(
                "must stay isolated\n",
                encoding="utf-8",
            )

            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/",),
            )

            self.assertEqual(
                receipt.uncommitted_excluded_paths,
                ("outside-probe.txt",),
            )
            self.assertTrue((repo / "_state/integration/code.txt").is_file())
            self.assertFalse((repo / "outside-probe.txt").exists())
            missing = subprocess.run(
                ["/usr/bin/git", "show", "v2:outside-probe.txt"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)

    def test_committed_out_of_scope_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            self._worker_commit(
                handle,
                {
                    "_state/integration/code.txt": "in scope\n",
                    "outside-committed.txt": "not allowed\n",
                },
            )

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError,
                "outside the integration scope",
            ):
                wti.integrate_worktree_commits(
                    handle,
                    ("_state/integration/",),
                )

            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )
            self.assertFalse((repo / "_state/integration/code.txt").exists())
            self.assertFalse((repo / "outside-committed.txt").exists())

    def test_transient_out_of_scope_commit_then_restore_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            (handle.worktree_root / "README.md").write_text(
                "transient forbidden content\n",
                encoding="utf-8",
            )
            _git(["add", "README.md"], cwd=handle.worktree_root)
            _git(
                ["commit", "-q", "-m", "transient out of scope"],
                cwd=handle.worktree_root,
            )
            (handle.worktree_root / "README.md").write_text(
                "root\n",
                encoding="utf-8",
            )
            allowed = handle.worktree_root / "_state/integration/code.txt"
            allowed.parent.mkdir(parents=True)
            allowed.write_text("allowed final change\n", encoding="utf-8")
            _git(
                ["add", "README.md", "_state/integration/code.txt"],
                cwd=handle.worktree_root,
            )
            _git(["commit", "-q", "-m", "restore and allow"], cwd=handle.worktree_root)

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError,
                "outside the integration scope",
            ):
                wti.integrate_worktree_commits(
                    handle,
                    ("_state/integration/",),
                )

            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )
            self.assertFalse((repo / "_state/integration/code.txt").exists())

    def test_worker_merge_commit_is_rejected_before_integration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            _git(["checkout", "-q", "-b", "worker-side"], cwd=handle.worktree_root)
            self._worker_commit(
                handle,
                {"_state/integration/code.txt": "side change\n"},
                message="side commit",
            )
            _git(["checkout", "-q", handle.branch], cwd=handle.worktree_root)
            _git(
                ["merge", "--no-ff", "-m", "worker merge", "worker-side"],
                cwd=handle.worktree_root,
            )

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError,
                "history must be linear",
            ):
                wti.integrate_worktree_commits(
                    handle,
                    ("_state/integration/",),
                )

            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )
            self.assertFalse((repo / "_state/integration/code.txt").exists())

    def test_overlapping_target_change_fails_without_moving_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_commit(handle, {"README.md": "worker\n"})
            (repo / "README.md").write_text("pane advance\n", encoding="utf-8")
            _git(["add", "README.md"], cwd=repo)
            _git(["commit", "-q", "-m", "overlapping advance"], cwd=repo)
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError,
                "changed since",
            ):
                wti.integrate_worktree_commits(handle, ("README.md",))

            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )
            self.assertEqual(
                (repo / "README.md").read_text(encoding="utf-8"),
                "pane advance\n",
            )

    def test_disjoint_target_advance_preserves_worker_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            worker_head = self._worker_commit(
                handle,
                {"_state/integration/code.txt": "worker\n"},
            )
            (repo / "README.md").write_text("disjoint pane advance\n", encoding="utf-8")
            _git(["add", "README.md"], cwd=repo)
            _git(["commit", "-q", "-m", "disjoint advance"], cwd=repo)
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()

            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/",),
            )

            self.assertFalse(receipt.exact_worker_history)
            self.assertNotEqual(receipt.integration_commit, worker_head)
            self.assertEqual(
                _git(["merge-base", "--is-ancestor", worker_head, "v2"], cwd=repo).returncode,
                0,
            )
            parents = _git(
                ["show", "-s", "--format=%P", receipt.integration_commit],
                cwd=repo,
            ).stdout.split()
            self.assertEqual(parents, [target_before, worker_head])
            self.assertEqual(
                (repo / "README.md").read_text(encoding="utf-8"),
                "disjoint pane advance\n",
            )
            self.assertEqual(
                (repo / "_state/integration/code.txt").read_text(encoding="utf-8"),
                "worker\n",
            )


class WorkerResidueIntegrationTests(unittest.TestCase):
    """A specialist CLI edits files; it does not commit them.

    Integration only ever moves *committed* worker history, so an edit-only
    worker used to be a hard block ("worker left uncommitted in-scope code
    changes") and the whole dispatch died at exit 75 with its real response
    stranded in the worktree. The controller now commits that residue itself,
    inside the declared scope, before integration runs.
    """

    ARTIFACT = "departments/coding/outbox/TASK-2026-07-23-9901-integrate-response.md"

    def _provision(self, root: Path):
        repo = _init_repo(root)
        pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
        handle = pool.provision(
            "TASK-2026-07-23-9901-integrate",
            "d-" + "b" * 32,
        )
        return repo, handle

    def _write(self, handle: wti.WorktreeHandle, relative: str, content: str) -> Path:
        destination = handle.worktree_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def test_edit_only_worker_lands_its_in_scope_change_on_the_integration_branch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._write(handle, "_state/integration/code.txt", "edited not committed\n")
            self._write(handle, self.ARTIFACT, "the real response\n")

            committed = wti.commit_worker_residue(
                handle,
                ("_state/integration/", self.ARTIFACT),
                exclude_paths=(self.ARTIFACT,),
            )
            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/", self.ARTIFACT),
                exclude_paths=(self.ARTIFACT,),
            )

            self.assertEqual(committed, ("_state/integration/code.txt",))
            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(
                (repo / "_state/integration/code.txt").read_text(encoding="utf-8"),
                "edited not committed\n",
            )

    def test_bridge_owned_artifact_is_never_swept_into_the_integration_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._write(handle, "_state/integration/code.txt", "in scope\n")
            self._write(handle, self.ARTIFACT, "bridge publishes this, not git\n")

            wti.commit_worker_residue(
                handle,
                ("_state/integration/", self.ARTIFACT),
                exclude_paths=(self.ARTIFACT,),
            )
            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/", self.ARTIFACT),
                exclude_paths=(self.ARTIFACT,),
            )

            self.assertEqual(receipt.integrated_paths, ("_state/integration/code.txt",))
            self.assertFalse((repo / self.ARTIFACT).exists())
            self.assertTrue((handle.worktree_root / self.ARTIFACT).is_file())

    def test_out_of_scope_worker_probe_is_left_uncommitted_and_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._write(handle, "_state/integration/code.txt", "in scope\n")
            self._write(handle, "outside-probe.txt", "must stay isolated\n")

            committed = wti.commit_worker_residue(
                handle,
                ("_state/integration/",),
            )
            receipt = wti.integrate_worktree_commits(
                handle,
                ("_state/integration/",),
            )

            self.assertEqual(committed, ("_state/integration/code.txt",))
            self.assertEqual(receipt.uncommitted_excluded_paths, ("outside-probe.txt",))
            self.assertFalse((repo / "outside-probe.txt").exists())

    def test_an_out_of_scope_path_the_worker_staged_is_not_swept_in(self) -> None:
        """`git add` inside the worktree must not widen the integration scope."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._write(handle, "_state/integration/code.txt", "in scope\n")
            self._write(handle, "outside-staged.txt", "worker staged this\n")
            _git(["add", "--", "outside-staged.txt"], cwd=handle.worktree_root)

            wti.commit_worker_residue(handle, ("_state/integration/",))
            receipt = wti.integrate_worktree_commits(handle, ("_state/integration/",))

            self.assertEqual(receipt.integrated_paths, ("_state/integration/code.txt",))
            self.assertFalse((repo / "outside-staged.txt").exists())

    def test_a_worker_deletion_inside_scope_still_fails_closed(self) -> None:
        """Auto-committing residue must not become a back door around the no-delete rule."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            seeded = handle.worktree_root / "_state/integration/code.txt"
            seeded.parent.mkdir(parents=True, exist_ok=True)
            seeded.write_text("seed\n", encoding="utf-8")
            _git(["add", "--", "_state/integration/code.txt"], cwd=handle.worktree_root)
            _git(["commit", "-q", "-m", "seed"], cwd=handle.worktree_root)
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            seeded.unlink()

            wti.commit_worker_residue(handle, ("_state/integration/",))
            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(handle, ("_state/integration/",))

            self.assertIn("deletes are not authorized", str(raised.exception))
            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )

    def _seed_tracked(self, handle: wti.WorktreeHandle, *relatives: str) -> None:
        """Commit files onto the worker branch so a later delete is a tracked delete."""

        for relative in relatives:
            self._write(handle, relative, "seed\n")
        _git(["add", "--", *relatives], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", "seed"], cwd=handle.worktree_root)

    def test_a_worker_git_rm_deletion_is_staged_and_committed_with_its_edits(
        self,
    ) -> None:
        """F16: `git rm` residue must commit, not abort the whole integration.

        `git rm` drops the index entry *and* the worktree file, so the path
        survives only in HEAD and matches no `git add` pathspec -- the bare
        `git add -- <path>` this used to run died with exit 128 and discarded
        the worker's finished work. A plain `rm` never had this problem (git
        already stages worktree deletions), which is why it went unnoticed
        until a fold-then-remove task did the correct thing.
        """

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._seed_tracked(
                handle,
                "_state/integration/removed.txt",
                "_state/integration/kept.txt",
            )
            _git(
                ["rm", "-q", "--", "_state/integration/removed.txt"],
                cwd=handle.worktree_root,
            )
            self._write(handle, "_state/integration/kept.txt", "edited\n")
            self._write(handle, "_state/integration/added.txt", "brand new\n")

            committed = wti.commit_worker_residue(handle, ("_state/integration/",))

            self.assertEqual(
                committed,
                (
                    "_state/integration/added.txt",
                    "_state/integration/kept.txt",
                    "_state/integration/removed.txt",
                ),
            )
            recorded = _git(
                ["diff", "--name-status", "HEAD~1", "HEAD"],
                cwd=handle.worktree_root,
            ).stdout.split()
            self.assertEqual(
                recorded,
                [
                    "A",
                    "_state/integration/added.txt",
                    "M",
                    "_state/integration/kept.txt",
                    "D",
                    "_state/integration/removed.txt",
                ],
            )
            self.assertEqual(
                _git(["status", "--porcelain"], cwd=handle.worktree_root).stdout,
                "",
            )

    def test_an_out_of_scope_git_rm_is_not_swept_into_the_residue_commit(self) -> None:
        """Staging a deletion must stay pathspec-limited to the declared scope."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._seed_tracked(
                handle,
                "_state/integration/removed.txt",
                "outside-removed.txt",
            )
            _git(
                [
                    "rm",
                    "-q",
                    "--",
                    "_state/integration/removed.txt",
                    "outside-removed.txt",
                ],
                cwd=handle.worktree_root,
            )

            committed = wti.commit_worker_residue(handle, ("_state/integration/",))

            self.assertEqual(committed, ("_state/integration/removed.txt",))
            recorded = _git(
                ["diff", "--name-status", "HEAD~1", "HEAD"],
                cwd=handle.worktree_root,
            ).stdout.split()
            self.assertEqual(recorded, ["D", "_state/integration/removed.txt"])
            # The out-of-scope deletion stays staged-but-uncommitted in the
            # isolated worktree, exactly like any other out-of-scope residue.
            self.assertEqual(
                _git(["status", "--porcelain"], cwd=handle.worktree_root).stdout,
                "D  outside-removed.txt\n",
            )

    def test_a_worker_git_rm_deletion_still_fails_closed_at_integration(self) -> None:
        """Stageable is not the same as authorized: the delete gate still holds.

        Committing the residue is what lets the *gate* see the deletion at all.
        Integration must still refuse it -- deletes are an operator-approved
        action, and making them stageable must not become a back door.
        """

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._seed_tracked(handle, "_state/integration/removed.txt")
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            _git(
                ["rm", "-q", "--", "_state/integration/removed.txt"],
                cwd=handle.worktree_root,
            )

            wti.commit_worker_residue(handle, ("_state/integration/",))
            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(handle, ("_state/integration/",))

            self.assertIn("deletes are not authorized", str(raised.exception))
            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )

    def test_a_clean_artifact_only_worker_still_integrates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._write(handle, self.ARTIFACT, "artifact-only task\n")

            committed = wti.commit_worker_residue(
                handle,
                (self.ARTIFACT,),
                exclude_paths=(self.ARTIFACT,),
            )
            receipt = wti.integrate_worktree_commits(
                handle,
                (self.ARTIFACT,),
                exclude_paths=(self.ARTIFACT,),
            )

            self.assertEqual(committed, ())
            self.assertEqual(receipt.status, "no-committed-in-scope-changes")


@unittest.skipUnless(sys.platform == "darwin", "F4 denial proof requires real macOS Seatbelt")
class RealHostDenialTests(unittest.TestCase):
    """Every class PROVES the OS actually denies the write, not just that our code says no."""

    def _fixture(self):
        # Canonicalize immediately: tempfile roots on macOS are themselves a
        # symlink (/var -> /private/var), and the compiled profile always
        # grants against the realpath. Building target paths from the
        # non-canonical prefix would make "denied" assertions pass for the
        # wrong reason (a path-prefix mismatch, not the property under test).
        directory = tempfile.TemporaryDirectory()
        root = Path(os.path.realpath(directory.name))
        repo = _init_repo(root)
        worktree_root = root / "wt-worker"
        _add_worktree(repo, worktree_root, "task/worker", "v2")
        self.addCleanup(directory.cleanup)
        return repo, worktree_root

    def test_write_inside_own_worktree_is_allowed(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        target = worktree_root / "own-file.txt"

        wti.assert_write_effect(profile, target, allowed=True)

        self.assertTrue(target.exists())

    def test_write_to_shared_config_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        common = wti.git_common_dir(repo)

        wti.assert_write_effect(profile, common / "config", allowed=False)

    def test_write_to_shared_hooks_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        common = wti.git_common_dir(repo)

        wti.assert_write_effect(profile, common / "hooks" / "pre-commit", allowed=False)

    def test_write_to_a_shared_ref_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        common = wti.git_common_dir(repo)

        wti.assert_write_effect(profile, common / "refs" / "heads" / "main", allowed=False)

    def test_write_to_a_shared_remote_tracking_ref_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        common = wti.git_common_dir(repo)

        wti.assert_write_effect(
            profile, common / "refs" / "remotes" / "origin" / "v2", allowed=False
        )

    def test_write_to_a_sibling_worktrees_files_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        sibling_root = worktree_root.parent / "wt-sibling"
        _add_worktree(repo, sibling_root, "task/sibling", "v2")
        profile = wti.compile_worktree_profile(worktree_root, repo)

        wti.assert_write_effect(profile, sibling_root / "intruder.txt", allowed=False)

    def test_symlink_escape_from_inside_the_worktree_to_shared_config_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        common = wti.git_common_dir(repo)
        escape_link = worktree_root / "escape-to-config"
        escape_link.symlink_to(common / "config")
        profile = wti.compile_worktree_profile(worktree_root, repo)

        wti.assert_write_effect(profile, escape_link, allowed=False)

    def test_write_to_the_integration_branch_ref_is_denied(self) -> None:
        repo, worktree_root = self._fixture()
        profile = wti.compile_worktree_profile(worktree_root, repo)
        common = wti.git_common_dir(repo)

        wti.assert_write_effect(profile, common / "refs" / "heads" / "v2", allowed=False)


class CBSEHardeningTests(unittest.TestCase):
    """Configuration-Based Sandbox Escape hardening (corpus C 1.A, corpus A #7)."""

    def _provision(self, root: Path):
        repo = _init_repo(root)
        pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
        handle = pool.provision(
            "TASK-2026-07-26-9950-cbse",
            "d-" + "b" * 32,
        )
        return repo, handle

    def _worker_commit(
        self,
        handle: wti.WorktreeHandle,
        paths: dict[str, str],
        *,
        message: str = "worker change",
    ) -> str:
        for relative, content in paths.items():
            destination = handle.worktree_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        _git(["add", "--", *paths], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", message], cwd=handle.worktree_root)
        return _git(["rev-parse", "HEAD"], cwd=handle.worktree_root).stdout.strip()

    def test_planted_pre_commit_hook_never_runs_during_board_residue_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            common = wti.git_common_dir(repo)
            hooks_dir = common / "hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            marker = Path(directory) / "cbse-hook-fired.marker"
            hook = hooks_dir / "pre-commit"
            hook.write_text(
                f"#!/bin/sh\n/usr/bin/touch {marker}\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            (handle.worktree_root / "_state" / "integration").mkdir(
                parents=True, exist_ok=True
            )
            (handle.worktree_root / "_state" / "integration" / "code.txt").write_text(
                "worker landed\n", encoding="utf-8"
            )

            committed = wti.commit_worker_residue(handle, ("_state/integration/",))

            self.assertEqual(committed, ("_state/integration/code.txt",))
            self.assertFalse(
                marker.exists(),
                "worker-planted pre-commit hook fired during a board git op",
            )

    def test_worker_symlink_output_is_refused_at_integration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_commit(
                handle,
                {"_state/integration/code.txt": "in scope\n"},
            )
            target_before = _git(["rev-parse", "v2"], cwd=repo).stdout.strip()
            link = handle.worktree_root / "_state" / "integration" / "link"
            link.symlink_to("/etc/hosts")

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "CBSE"):
                wti.integrate_worktree_commits(handle, ("_state/integration/",))

            # Fail-closed: the target branch never advanced.
            self.assertEqual(
                _git(["rev-parse", "v2"], cwd=repo).stdout.strip(),
                target_before,
            )

    def test_out_of_scope_autoexec_residue_is_blocked_not_silently_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_commit(
                handle,
                {"_state/integration/code.txt": "in scope\n"},
            )
            planted = handle.worktree_root / ".vscode" / "settings.json"
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(
                '{"terminal.integrated.env.osx": {"X": "pwn"}}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "CBSE"):
                wti.integrate_worktree_commits(handle, ("_state/integration/",))

    def test_inert_out_of_scope_residue_is_still_retained_not_over_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_commit(
                handle,
                {"_state/integration/code.txt": "in scope\n"},
            )
            (handle.worktree_root / "scratch-notes.txt").write_text(
                "harmless\n", encoding="utf-8"
            )

            receipt = wti.integrate_worktree_commits(handle, ("_state/integration/",))

            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(receipt.uncommitted_excluded_paths, ("scratch-notes.txt",))

    def test_in_scope_autoload_edit_is_authorized_and_integrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            # package.json is an auto-load surface, but here it is INSIDE the
            # declared write scope: the packet authorized it, so it must land.
            self._worker_commit(
                handle,
                {"_state/integration/package.json": '{"name": "ok"}\n'},
            )

            receipt = wti.integrate_worktree_commits(handle, ("_state/integration/",))

            self.assertEqual(receipt.status, "integrated")
            self.assertIn("_state/integration/package.json", receipt.integrated_paths)
            self.assertTrue(
                (repo / "_state/integration/package.json").is_file()
            )

    def test_scan_flags_structural_git_path_regardless_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            with self.assertRaisesRegex(wti.WorktreeIsolationError, "CBSE"):
                wti.scan_cbse_artifacts(
                    handle.worktree_root,
                    (PurePosixPath("tools/.githooks/pre-push"),),
                    (PurePosixPath("tools"),),
                    (),
                )

    def test_scan_ignores_bridge_owned_excluded_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            # The board's own return artifact/envelope are excluded; a markdown
            # response is not an auto-exec surface and must never trip the scan.
            wti.scan_cbse_artifacts(
                handle.worktree_root,
                (PurePosixPath("departments/coding/outbox/x-response.md"),),
                (PurePosixPath("departments/coding/outbox"),),
                (PurePosixPath("departments/coding/outbox/x-response.md"),),
            )


if __name__ == "__main__":
    unittest.main()
