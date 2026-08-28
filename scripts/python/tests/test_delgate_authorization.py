#!/usr/bin/env python3
"""Invariant tests for the B-enumerated worker-deletion authorization gate.

The board's default is a categorical refusal of every worker-committed
deletion. This suite pins the one authorized path: an EXACT file list the
dispatcher freezes into the verification contract, threaded into integration by
the controller. The properties under test are, in order of importance:

1. **Unforgeability** — the authorization lives in the contract (covered by
   ``verification_contract_sha256``) and is read controller-side. A worker
   editing its worktree copy of the packet gains nothing.
2. **No authority inflation** — ``write_scope`` is not deletion authority;
   ``deleted ⊆ authorized ⊆ write_scope`` and ``authorized ∩ excluded = ∅``,
   with entries file-precise against the immutable base tree.
3. **Symmetry** — the fast-forward and merge routes apply one rule, so a
   worker's outcome never depends on whether v2 advanced concurrently.
"""

from __future__ import annotations

import io
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import tokenize
import unittest
import unittest.mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import verification_contract as vc  # noqa: E402
import worktree_isolation as wti  # noqa: E402

SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"
SCOPE = ("_state/integration/",)
BASE_ADMISSION = {
    "task_id": "TASK-2026-07-27-0422-delgate-impl",
    "run_id": "PROJ-BOARD-HARDENING-2026-07-27",
    "mode": "project",
    "result_type": "normal",
    "to_model": "claude",
    "dispatch_kind": "single",
    "capability": None,
}


def _integration_call_sites(text: str) -> list[str]:
    """Return each supervisor integration call as inspected by the guard."""
    sites = []
    cursor = 0
    while True:
        found = text.find("wti.integrate_worktree_commits(", cursor)
        if found == -1:
            return sites
        source = text[found:]
        line_offsets = [0]
        for line in source.splitlines(keepends=True):
            line_offsets.append(line_offsets[-1] + len(line))
        depth = 0
        opened = False
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.OP:
                continue
            if token.string == "(":
                depth += 1
                opened = True
            elif token.string == ")" and opened:
                depth -= 1
                if depth == 0:
                    end = found + line_offsets[token.end[0] - 1] + token.end[1]
                    sites.append(text[found:end])
                    cursor = end
                    break
        else:
            raise AssertionError("unterminated wti.integrate_worktree_commits call")


def _integration_authorization_errors(text: str) -> list[str]:
    errors = []
    for ordinal, call in enumerate(_integration_call_sites(text), start=1):
        if "authorized_delete_paths=" not in call:
            errors.append(f"call {ordinal} omits authorized_delete_paths")
        elif (
            "authorized_delete_paths=authorized_delete_paths" not in call
            and "or ()" not in call
        ):
            errors.append(f"call {ordinal} does not preserve default refusal")
    return errors


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


def _init_repo(root: Path, seed: dict[str, str]) -> Path:
    """A repo on v2 whose base commit already tracks ``seed``.

    Deletion targets have to exist at the worktree's immutable base: a path a
    worker created inside its own history was never operator-approved, and the
    authorization is frozen against the base tree specifically so a same-name
    replacement cannot inherit a stale approval.
    """

    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "v2"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    for relative, content in seed.items():
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    return repo


class DeleteAuthorizationHarness(unittest.TestCase):
    def _provision(self, root: Path, seed: dict[str, str] | None = None):
        repo = _init_repo(
            root,
            seed
            if seed is not None
            else {
                "_state/integration/doomed.txt": "delete me\n",
                "_state/integration/kept.txt": "keep me\n",
            },
        )
        pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
        handle = pool.provision("TASK-2026-07-27-0422-delgate", "d-" + "a" * 32)
        return repo, handle

    def _worker_commit(self, handle: wti.WorktreeHandle, message: str) -> str:
        _git(["add", "-A"], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", message], cwd=handle.worktree_root)
        return _git(["rev-parse", "HEAD"], cwd=handle.worktree_root).stdout.strip()

    def _worker_rm(self, handle: wti.WorktreeHandle, *relatives: str) -> None:
        _git(["rm", "-q", "--", *relatives], cwd=handle.worktree_root)

    def _advance_target_off_scope(self, repo: Path) -> None:
        """Move v2 on a path outside the declared scope, forcing the merge route."""

        (repo / "README.md").write_text("pane advance\n", encoding="utf-8")
        _git(["add", "README.md"], cwd=repo)
        _git(["commit", "-q", "-m", "off-scope advance"], cwd=repo)

    def _head(self, repo: Path) -> str:
        return _git(["rev-parse", "v2"], cwd=repo).stdout.strip()


class ContractAuthorizationTests(unittest.TestCase):
    """The authorization is contract-resident, so it is SHA-covered."""

    def test_no_deletion_leaves_every_existing_contract_byte_identical(self) -> None:
        # The key is absent-when-empty on purpose: emitting `[]` by default
        # would re-hash every contract ever dispatched and invalidate the
        # verification_contract_sha256 pinned in each in-flight packet.
        contract = vc.derive_verification_contract(dict(BASE_ADMISSION))
        self.assertNotIn("authorized_delete_paths", contract)

        explicit_empty = vc.derive_verification_contract(
            {**BASE_ADMISSION, "authorized_delete_paths": []}
        )
        self.assertEqual(
            vc.verification_contract_sha256(contract),
            vc.verification_contract_sha256(explicit_empty),
        )

    def test_live_dispatched_contract_still_validates_unchanged(self) -> None:
        """Regression: the schema change must not strand in-flight packets."""

        contract = vc.derive_verification_contract(dict(BASE_ADMISSION))
        self.assertEqual(contract, vc.validate_verification_contract(dict(contract)))

    def test_authorization_is_normalized_sorted_and_round_trips(self) -> None:
        contract = vc.derive_verification_contract(
            {
                **BASE_ADMISSION,
                "authorized_delete_paths": ["b/second.py", "a/first.py"],
            }
        )
        self.assertEqual(
            contract["authorized_delete_paths"], ["a/first.py", "b/second.py"]
        )
        self.assertEqual(contract, vc.validate_verification_contract(dict(contract)))

    def test_forging_the_authorization_breaks_the_contract_hash(self) -> None:
        """The unforgeability claim, stated as an assertion.

        Adding a deletion target to a contract changes its SHA-256, so a forged
        authorization has to break the hash the dispatcher pinned into the
        packet and the launch authority -- the same bar as forging write_scope.
        """

        clean = vc.derive_verification_contract(dict(BASE_ADMISSION))
        forged = dict(clean)
        forged["authorized_delete_paths"] = ["secrets/prod.env"]
        self.assertNotEqual(
            vc.verification_contract_sha256(clean),
            vc.verification_contract_sha256(forged),
        )
        # And the forgery is itself a well-formed contract only because the
        # dispatcher would have had to derive it; validation still passes, which
        # is the point -- the hash, not the shape, is what pins it.
        self.assertEqual(forged, vc.validate_verification_contract(dict(forged)))

    def test_non_canonical_empty_list_is_rejected(self) -> None:
        contract = vc.derive_verification_contract(
            {**BASE_ADMISSION, "authorized_delete_paths": ["a/first.py"]}
        )
        contract["authorized_delete_paths"] = []
        with self.assertRaises(vc.ContractError):
            vc.validate_verification_contract(contract)

    def test_directories_globs_and_traversal_are_rejected(self) -> None:
        for entry in (
            "src/legacy/",
            "/etc/passwd",
            "src/../../etc/passwd",
            "src/*.py",
            "src/mod[0-9].py",
            ":(literal)src/mod.py",
            "src//mod.py",
            "src/./mod.py",
            "",
            ".",
        ):
            with self.subTest(entry=entry):
                with self.assertRaises(vc.ContractError):
                    vc.derive_verification_contract(
                        {**BASE_ADMISSION, "authorized_delete_paths": [entry]}
                    )

    def test_duplicate_entries_are_rejected(self) -> None:
        with self.assertRaises(vc.ContractError):
            vc.derive_verification_contract(
                {**BASE_ADMISSION, "authorized_delete_paths": ["a/x.py", "a/x.py"]}
            )

    def test_advisory_mode_cannot_authorize_deletions(self) -> None:
        with self.assertRaisesRegex(vc.ContractError, "advisory"):
            vc.derive_verification_contract(
                {
                    **BASE_ADMISSION,
                    "mode": "advisory",
                    "authorized_delete_paths": ["a/x.py"],
                }
            )


class DefaultRefusalTests(DeleteAuthorizationHarness):
    """With no authorization, behavior is byte-for-byte what it was."""

    def test_unauthorized_delete_is_refused_and_target_never_moves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "worker removes a file")
            target_before = self._head(repo)

            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertIn("deletes are not authorized", str(raised.exception))
            self.assertEqual(self._head(repo), target_before)

    def test_refusal_names_the_unauthorized_paths_and_the_authorized_set(self) -> None:
        """One-glance salvage: a refusal must distinguish 'never approved'
        from 'the approval list has a typo'."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/kept.txt")
            self._worker_commit(handle, "worker removes the wrong file")

            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/doomed.txt",),
                )

            message = str(raised.exception)
            self.assertIn("_state/integration/kept.txt", message)
            self.assertIn("authorized deletions for this task", message)
            self.assertIn("_state/integration/doomed.txt", message)

    def test_refusal_with_no_authorization_says_so_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "worker removes a file")

            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertIn("authorized deletions for this task: (none)", str(raised.exception))


class AuthorizedDeleteTests(DeleteAuthorizationHarness):
    def test_authorized_delete_integrates_on_the_fast_forward_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "authorized cleanup")

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=("_state/integration/doomed.txt",),
            )

            self.assertEqual(receipt.status, "integrated")
            self.assertTrue(receipt.exact_worker_history)
            self.assertFalse((repo / "_state/integration/doomed.txt").exists())
            self.assertTrue((repo / "_state/integration/kept.txt").is_file())

    def test_authorized_delete_integrates_on_the_merge_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "authorized cleanup")
            self._advance_target_off_scope(repo)

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=("_state/integration/doomed.txt",),
            )

            self.assertEqual(receipt.status, "integrated")
            self.assertFalse(receipt.exact_worker_history)
            self.assertFalse((repo / "_state/integration/doomed.txt").exists())

    def test_receipt_states_the_deletions_and_the_authorization(self) -> None:
        """Deletion must never be inferable only by diffing the receipt."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            (handle.worktree_root / "_state/integration/kept.txt").write_text(
                "edited\n", encoding="utf-8"
            )
            self._worker_commit(handle, "authorized cleanup plus an edit")

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=(
                    "_state/integration/doomed.txt",
                    "_state/integration/kept.txt",
                ),
            )

            self.assertEqual(receipt.deleted_paths, ("_state/integration/doomed.txt",))
            self.assertEqual(
                receipt.authorized_delete_paths,
                ("_state/integration/doomed.txt", "_state/integration/kept.txt"),
            )
            # An edited path is integrated, not deleted: the two are distinct.
            self.assertIn("_state/integration/kept.txt", receipt.integrated_paths)

    def test_deleting_a_strict_subset_of_the_authorization_integrates(self) -> None:
        """The authorization is a maximum, not a quota."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "delete only one of the two approved files")

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=(
                    "_state/integration/doomed.txt",
                    "_state/integration/kept.txt",
                ),
            )

            self.assertEqual(receipt.status, "integrated")
            self.assertTrue((repo / "_state/integration/kept.txt").is_file())

    def test_a_superset_delete_refuses_atomically(self) -> None:
        """One unauthorized path fails the whole integration; the approved
        deletion does not land on its own."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            self._worker_rm(
                handle,
                "_state/integration/doomed.txt",
                "_state/integration/kept.txt",
            )
            self._worker_commit(handle, "worker over-deletes")
            target_before = self._head(repo)

            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/doomed.txt",),
                )

            self.assertIn("_state/integration/kept.txt", str(raised.exception))
            self.assertEqual(self._head(repo), target_before)
            self.assertTrue((repo / "_state/integration/doomed.txt").is_file())

    def test_rename_decomposes_into_authorized_delete_plus_in_scope_add(self) -> None:
        """`--no-renames` means a rename cannot disguise a deletion: the old
        path needs deletion authority, the new path needs scope."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            _git(
                [
                    "mv",
                    "_state/integration/doomed.txt",
                    "_state/integration/renamed.txt",
                ],
                cwd=handle.worktree_root,
            )
            self._worker_commit(handle, "rename")

            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(handle, SCOPE)
            self.assertIn("deletes are not authorized", str(raised.exception))

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=("_state/integration/doomed.txt",),
            )
            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(receipt.deleted_paths, ("_state/integration/doomed.txt",))
            self.assertTrue((repo / "_state/integration/renamed.txt").is_file())


class AuthorizationBoundsTests(DeleteAuthorizationHarness):
    """`authorized ⊆ write_scope`, `authorized ∩ excluded = ∅`, file-precise."""

    def test_authorization_outside_the_write_scope_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            self._worker_commit_noop = None

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "outside the declared write scope"
            ):
                wti.integrate_worktree_commits(
                    handle, SCOPE, authorized_delete_paths=("README.md",)
                )

    def test_a_bridge_output_can_never_be_an_authorized_target(self) -> None:
        """The return artifact and response envelope are controller-owned."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(
                Path(directory),
                seed={"_state/integration/artifact.md": "bridge output\n"},
            )

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "bridge-owned output"
            ):
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    exclude_paths=("_state/integration/artifact.md",),
                    authorized_delete_paths=("_state/integration/artifact.md",),
                )

    def test_a_directory_entry_is_rejected_file_precision(self) -> None:
        """A directory that survives contract syntax is still refused against
        the base tree, where it resolves to a tree rather than a blob."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "resolves to a tree"):
                wti.integrate_worktree_commits(
                    handle, SCOPE, authorized_delete_paths=("_state/integration",)
                )

    def test_a_trailing_slash_entry_is_rejected_before_git_sees_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))

            with self.assertRaisesRegex(wti.WorktreeIsolationError, "canonical"):
                wti.integrate_worktree_commits(
                    handle, SCOPE, authorized_delete_paths=("_state/integration/",)
                )

    def test_patterns_and_pathspec_magic_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            for entry in (
                "_state/integration/*.txt",
                "_state/integration/f[0-9].txt",
                ":(literal)_state/integration/doomed.txt",
            ):
                with self.subTest(entry=entry):
                    with self.assertRaises(wti.WorktreeIsolationError):
                        wti.integrate_worktree_commits(
                            handle, SCOPE, authorized_delete_paths=(entry,)
                        )

    def test_a_path_untracked_at_the_base_cannot_be_authorized(self) -> None:
        """Freshness: approval is frozen against the immutable base tree, so a
        path that did not exist there can never inherit it."""

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "not tracked at the worktree base"
            ):
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/never-existed.txt",),
                )

    def test_traversal_in_an_authorization_entry_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))

            with self.assertRaises(wti.WorktreeIsolationError):
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/../../etc/passwd",),
                )


class RouteSymmetryTests(DeleteAuthorizationHarness):
    """P0.2: the ff route and the merge route must apply ONE rule.

    Before this change the fast-forward case was governed only by the
    worker-history audit and the merge case by both, so a divergent patch would
    have made a worker's outcome depend on unrelated concurrent traffic on v2.
    """

    def _refusal_for(self, root: Path, *, advance_target: bool) -> str:
        repo, handle = self._provision(root)
        self._worker_rm(handle, "_state/integration/doomed.txt")
        self._worker_commit(handle, "worker removes a file")
        if advance_target:
            self._advance_target_off_scope(repo)
        target_before = self._head(repo)
        with self.assertRaises(wti.WorktreeIsolationError) as raised:
            wti.integrate_worktree_commits(handle, SCOPE)
        self.assertEqual(self._head(repo), target_before)
        return str(raised.exception)

    def test_unauthorized_delete_refuses_identically_on_both_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fast_forward = self._refusal_for(Path(directory), advance_target=False)
        with tempfile.TemporaryDirectory() as directory:
            merged = self._refusal_for(Path(directory), advance_target=True)

        self.assertEqual(fast_forward, merged)
        self.assertIn("deletes are not authorized", fast_forward)

    def test_authorized_delete_integrates_identically_on_both_routes(self) -> None:
        outcomes = []
        for advance_target in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                repo, handle = self._provision(Path(directory))
                self._worker_rm(handle, "_state/integration/doomed.txt")
                self._worker_commit(handle, "authorized cleanup")
                if advance_target:
                    self._advance_target_off_scope(repo)
                receipt = wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/doomed.txt",),
                )
                outcomes.append(
                    (
                        receipt.status,
                        receipt.deleted_paths,
                        (repo / "_state/integration/doomed.txt").exists(),
                    )
                )

        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], ("integrated", ("_state/integration/doomed.txt",), False))


class TypechangeTests(DeleteAuthorizationHarness):
    """A `T` record is not a `D`, so it never reached the deletion gate."""

    def _stage_cacheinfo(
        self, handle: wti.WorktreeHandle, mode: str, content: str, relative: str
    ) -> None:
        blob = subprocess.run(
            ["/usr/bin/git", "hash-object", "-w", "--stdin"],
            cwd=str(handle.worktree_root),
            input=content,
            capture_output=True,
            text=True,
            check=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        ).stdout.strip()
        _git(
            ["update-index", "--add", "--cacheinfo", f"{mode},{blob},{relative}"],
            cwd=handle.worktree_root,
        )
        _git(
            ["commit", "-q", "-m", f"typechange to {mode}"],
            cwd=handle.worktree_root,
        )

    def test_committed_symlink_typechange_is_refused(self) -> None:
        """The exact gap: the on-disk file stays a regular file, so the CBSE
        lstat scan sees nothing, and the committed tree carries a symlink."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = self._head(repo)
            self._stage_cacheinfo(
                handle, "120000", "/etc/hosts", "_state/integration/doomed.txt"
            )
            # Proving the bypass is real: the worktree copy is still a plain file.
            on_disk = handle.worktree_root / "_state/integration/doomed.txt"
            self.assertTrue(on_disk.is_file())
            self.assertFalse(on_disk.is_symlink())

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(self._head(repo), target_before)

    def test_a_typechange_cannot_be_laundered_through_delete_authorization(
        self,
    ) -> None:
        """Authorizing a path for DELETION does not authorize replacing it
        with a symlink: the path does not disappear, so it is not a delete."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = self._head(repo)
            self._stage_cacheinfo(
                handle, "120000", "/etc/hosts", "_state/integration/doomed.txt"
            )

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=("_state/integration/doomed.txt",),
                )

            self.assertEqual(self._head(repo), target_before)

    def test_committed_gitlink_is_refused(self) -> None:
        """A `160000` submodule pointer has no on-disk symlink and no CBSE
        classification, so committed mode is the only thing that catches it."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = self._head(repo)
            _git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{'0' * 39}1,_state/integration/vendored",
                ],
                cwd=handle.worktree_root,
            )
            _git(["commit", "-q", "-m", "gitlink"], cwd=handle.worktree_root)

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(self._head(repo), target_before)

    def test_committed_submodule_pointer_with_a_clean_worktree_is_refused(self) -> None:
        """The live gap this gate closes, reproduced end to end.

        A worker that materializes a real nested repo and commits it as a
        `160000` gitlink leaves a completely CLEAN worktree, so no residue
        check fires; `_cbse_classification` sees no `.git` path segment,
        because the `.git` directory is inside the nested repo rather than in
        any committed path; and a gitlink is not a `D`, so the deletion gate
        never saw it. Before this gate the pointer integrated onto v2 with no
        refusal at all -- after which any host `git submodule update` fetches
        and checks out worker-chosen content.
        """

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            target_before = self._head(repo)
            nested = handle.worktree_root / "_state/integration/vendored"
            nested.mkdir(parents=True)
            _git(["init", "-q", "-b", "main"], cwd=nested)
            _git(["config", "user.email", "test@example.com"], cwd=nested)
            _git(["config", "user.name", "Test"], cwd=nested)
            (nested / "payload.sh").write_text("#!/bin/sh\necho pwned\n", encoding="utf-8")
            _git(["add", "-A"], cwd=nested)
            _git(["commit", "-q", "-m", "payload"], cwd=nested)
            pointer = _git(["rev-parse", "HEAD"], cwd=nested).stdout.strip()
            _git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{pointer},_state/integration/vendored",
                ],
                cwd=handle.worktree_root,
            )
            _git(["commit", "-q", "-m", "vendor a submodule"], cwd=handle.worktree_root)

            # The precondition that made this slip every other gate.
            self.assertEqual(
                _git(["status", "--porcelain"], cwd=handle.worktree_root).stdout, ""
            )

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(self._head(repo), target_before)
            self.assertNotIn(
                "160000", _git(["ls-tree", "-r", "v2"], cwd=repo).stdout
            )

    def test_an_executable_bit_change_is_still_an_ordinary_modification(self) -> None:
        """Not over-blocking: 100644 <-> 100755 is a normal in-scope edit."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            (handle.worktree_root / "_state/integration/doomed.txt").chmod(0o755)
            self._worker_commit(handle, "make it executable")

            receipt = wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(receipt.deleted_paths, ())
            self.assertNotEqual(self._head(repo), receipt.base_commit)


class TransientNonRegularModeTests(DeleteAuthorizationHarness):
    """History laundering: an unsafe mode in an INTERMEDIATE audited commit.

    The mode gate first shipped as a single check on the ``worker_head`` tree.
    But integration ships a HISTORY, not a state: on the fast-forward route the
    worker's commits become the target history verbatim, and on the merge route
    ``worker_head`` is retained as a parent. So a worker could commit a
    ``120000``/``160000`` entry for a base-tracked path, restore a regular blob
    in a LATER commit, and land the unsafe commit in v2's ancestry with both a
    clean worktree and a clean head tree -- every other gate blind to it.

    Reproduced by the cross-family review of
    ``TASK-2026-07-27-0422-delgate-impl`` on all four (mode x route) pairs. The
    gate is now applied at every commit ``_audited_worker_changes`` walks.
    """

    RELATIVE = "_state/integration/doomed.txt"

    def _pointer_for(self, handle: wti.WorktreeHandle, mode: str) -> str:
        """The object a ``cacheinfo`` entry at ``mode`` has to name.

        ``160000`` needs a commit id -- the worktree base is a real one, which
        is also the cheapest way to make the gitlink resolvable. ``120000``
        needs a blob holding the link target.
        """

        if mode == "160000":
            return handle.base_commit
        return subprocess.run(
            ["/usr/bin/git", "hash-object", "-w", "--stdin"],
            cwd=str(handle.worktree_root),
            input="/etc/hosts",
            capture_output=True,
            text=True,
            check=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        ).stdout.strip()

    def _launder(self, handle: wti.WorktreeHandle, mode: str) -> str:
        """Commit ``RELATIVE`` at ``mode``, then restore the regular blob.

        Returns the transient commit -- the one that must never become an
        ancestor of the target branch.
        """

        _git(
            [
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode},{self._pointer_for(handle, mode)},{self.RELATIVE}",
            ],
            cwd=handle.worktree_root,
        )
        _git(["commit", "-q", "-m", f"transient {mode}"], cwd=handle.worktree_root)
        transient = _git(
            ["rev-parse", "HEAD"], cwd=handle.worktree_root
        ).stdout.strip()
        # The worktree copy was never touched, so this restores the ORIGINAL
        # bytes: base..head is empty for this path and the head tree is clean.
        _git(["add", "--", self.RELATIVE], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", "restore regular blob"], cwd=handle.worktree_root)
        return transient

    def _assert_is_not_ancestor(self, repo: Path, commit: str) -> None:
        ancestry = subprocess.run(
            ["/usr/bin/git", "merge-base", "--is-ancestor", commit, "v2"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )
        self.assertNotEqual(
            ancestry.returncode,
            0,
            "the transient non-regular commit reached the target branch ancestry",
        )

    def _assert_laundering_refused(
        self,
        mode: str,
        *,
        advance_target: bool,
        preface: bool = False,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            if preface:
                # Buries the unsafe tree MID-history: a gate that audits only
                # the first commit, or only the head, sees nothing wrong.
                (handle.worktree_root / "_state/integration/kept.txt").write_text(
                    "ordinary first commit\n", encoding="utf-8"
                )
                self._worker_commit(handle, "ordinary work")
            transient = self._launder(handle, mode)

            # The preconditions that made this a bypass rather than a missing
            # diagnostic: nothing but the intermediate tree carries evidence.
            self.assertEqual(
                _git(["status", "--porcelain"], cwd=handle.worktree_root).stdout,
                "",
                "the worker worktree must be clean, or residue checks would fire",
            )
            self.assertTrue(
                _git(
                    ["ls-tree", "HEAD", "--", self.RELATIVE],
                    cwd=handle.worktree_root,
                ).stdout.startswith("100644 "),
                "the head tree must look innocent, or the head-only gate suffices",
            )
            self.assertEqual(
                _git(
                    [
                        "diff",
                        "--name-only",
                        handle.base_commit,
                        "HEAD",
                        "--",
                        self.RELATIVE,
                    ],
                    cwd=handle.worktree_root,
                ).stdout,
                "",
                "the restoration must be byte-identical to the base blob",
            )
            self.assertTrue(
                _git(
                    ["ls-tree", transient, "--", self.RELATIVE],
                    cwd=handle.worktree_root,
                ).stdout.startswith(f"{mode} "),
                "the transient commit must actually carry the unsafe mode",
            )

            if advance_target:
                self._advance_target_off_scope(repo)
            target_before = self._head(repo)

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(self._head(repo), target_before)
            self._assert_is_not_ancestor(repo, transient)

    def test_transient_symlink_is_refused_on_the_fast_forward_route(self) -> None:
        self._assert_laundering_refused("120000", advance_target=False)

    def test_transient_symlink_is_refused_on_the_merge_route(self) -> None:
        self._assert_laundering_refused("120000", advance_target=True)

    def test_transient_gitlink_is_refused_on_the_fast_forward_route(self) -> None:
        self._assert_laundering_refused("160000", advance_target=False)

    def test_transient_gitlink_is_refused_on_the_merge_route(self) -> None:
        self._assert_laundering_refused("160000", advance_target=True)

    def test_a_mid_history_gitlink_is_refused_on_the_fast_forward_route(self) -> None:
        """Not just the first commit: the unsafe tree is the SECOND of three."""

        self._assert_laundering_refused("160000", advance_target=False, preface=True)

    def test_a_mid_history_symlink_is_refused_on_the_merge_route(self) -> None:
        self._assert_laundering_refused("120000", advance_target=True, preface=True)

    def test_an_authorized_delete_cannot_launder_an_earlier_gitlink(self) -> None:
        """The other shape a head-only gate misses: the path is GONE at head.

        Authorizing a deletion authorizes removing the file, not routing an
        unsafe intermediate tree through v2's ancestry on the way there.
        """

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            _git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{handle.base_commit},{self.RELATIVE}",
                ],
                cwd=handle.worktree_root,
            )
            _git(["commit", "-q", "-m", "transient gitlink"], cwd=handle.worktree_root)
            transient = _git(
                ["rev-parse", "HEAD"], cwd=handle.worktree_root
            ).stdout.strip()
            # `git rm` cannot express this: the index holds a gitlink while the
            # worktree still holds the original file, so it either reports local
            # modifications or tries to remove a submodule directory. Removing
            # the scratch fixture's file and the index entry directly is what a
            # worker's `rm` + `git add -A` would produce anyway.
            (handle.worktree_root / self.RELATIVE).unlink()
            _git(
                ["update-index", "--force-remove", "--", self.RELATIVE],
                cwd=handle.worktree_root,
            )
            _git(
                ["commit", "-q", "-m", "authorized cleanup"], cwd=handle.worktree_root
            )
            target_before = self._head(repo)

            with self.assertRaisesRegex(
                wti.WorktreeIsolationError, "non-regular file"
            ):
                wti.integrate_worktree_commits(
                    handle,
                    SCOPE,
                    authorized_delete_paths=(self.RELATIVE,),
                )

            self.assertEqual(self._head(repo), target_before)
            self._assert_is_not_ancestor(repo, transient)

    def test_an_unresolvable_path_fails_closed_at_the_per_commit_gate(self) -> None:
        """The mode gate must never pass a path it did not actually inspect.

        Its refusal is driven by the ``ls-tree`` records it gets back, so a
        changed path that produces NO record would otherwise sail through the
        very check meant to look at it. A worker cannot commit that state --
        a non-``D`` path is in its commit's tree by definition -- so the
        unmatched lookup is injected at the enumeration seam, which is also
        what proves integration passes ``require_present`` rather than merely
        that the helper supports it.
        """

        phantom = PurePosixPath("_state/integration/phantom.txt")
        real = wti._changed_records

        def with_phantom(repo_root, base, head):
            return real(repo_root, base, head) + (("M", phantom),)

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            (handle.worktree_root / "_state/integration/kept.txt").write_text(
                "ordinary edit\n", encoding="utf-8"
            )
            self._worker_commit(handle, "ordinary edit")
            target_before = self._head(repo)

            with unittest.mock.patch.object(wti, "_changed_records", with_phantom):
                with self.assertRaisesRegex(
                    wti.WorktreeIsolationError, "no tree entry at the commit"
                ):
                    wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(self._head(repo), target_before)

    def test_the_head_tree_pass_tolerates_a_path_deleted_later(self) -> None:
        """The mirror of the check above, and why it is not the default.

        The head-tree pass is handed the union of non-`D` paths over the whole
        history, so an authorized delete legitimately leaves no head record.
        Demanding presence there would refuse `modify, then delete` cleanups.
        """

        with tempfile.TemporaryDirectory() as directory:
            _repo, handle = self._provision(Path(directory))
            absent = PurePosixPath("_state/integration/never-existed.txt")

            wti._reject_non_regular_committed_modes(
                handle.worktree_root,
                handle.base_commit,
                (absent,),
            )

    def test_modify_then_delete_under_authorization_still_integrates(self) -> None:
        """The end-to-end shape the tolerance above exists for."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            (handle.worktree_root / self.RELATIVE).write_text(
                "edited first\n", encoding="utf-8"
            )
            self._worker_commit(handle, "edit the doomed file")
            self._worker_rm(handle, self.RELATIVE)
            self._worker_commit(handle, "then remove it")

            receipt = wti.integrate_worktree_commits(
                handle,
                SCOPE,
                authorized_delete_paths=(self.RELATIVE,),
            )

            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(receipt.deleted_paths, (self.RELATIVE,))
            self.assertFalse((repo / self.RELATIVE).exists())

    def test_an_ordinary_multi_commit_history_still_integrates(self) -> None:
        """Not over-blocking: widening the gate to every audited commit must
        leave ordinary incremental work -- including an exec-bit flip in an
        intermediate commit -- integrating untouched."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(Path(directory))
            (handle.worktree_root / "_state/integration/kept.txt").write_text(
                "first pass\n", encoding="utf-8"
            )
            (handle.worktree_root / "_state/integration/doomed.txt").chmod(0o755)
            self._worker_commit(handle, "first pass")
            (handle.worktree_root / "_state/integration/kept.txt").write_text(
                "second pass\n", encoding="utf-8"
            )
            self._worker_commit(handle, "second pass")

            receipt = wti.integrate_worktree_commits(handle, SCOPE)

            self.assertEqual(receipt.status, "integrated")
            self.assertEqual(receipt.deleted_paths, ())
            self.assertEqual(
                (repo / "_state/integration/kept.txt").read_text(encoding="utf-8"),
                "second pass\n",
            )


class ForgedWorktreeAuthorizationTests(DeleteAuthorizationHarness):
    """P0.3: authorization is read controller-side, never from the worktree."""

    def test_a_worker_edited_packet_copy_grants_nothing(self) -> None:
        packet_relative = "departments/coding/inbox/TASK-2026-07-27-0422-delgate.md"
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._provision(
                Path(directory),
                seed={
                    "_state/integration/doomed.txt": "delete me\n",
                    packet_relative: "---\nid: TASK-2026-07-27-0422-delgate\n---\n",
                },
            )
            target_before = self._head(repo)

            # The worker rewrites ITS OWN copy of the packet to grant itself
            # deletion authority, then deletes the file.
            forged = handle.worktree_root / packet_relative
            forged.write_text(
                "---\n"
                "id: TASK-2026-07-27-0422-delgate\n"
                'authorized_delete_paths: ["_state/integration/doomed.txt"]\n'
                "operator_approved: true\n"
                "---\n",
                encoding="utf-8",
            )
            self._worker_rm(handle, "_state/integration/doomed.txt")
            self._worker_commit(handle, "self-authorized deletion")

            # Sanity: the forgery really is present in the worktree, so this
            # test would fail if integration ever read authorization from there.
            self.assertIn("authorized_delete_paths", forged.read_text(encoding="utf-8"))

            # The controller passes the authorization it holds -- which is empty.
            with self.assertRaises(wti.WorktreeIsolationError) as raised:
                wti.integrate_worktree_commits(
                    handle,
                    ("_state/integration/", "departments/coding/inbox/"),
                    authorized_delete_paths=(),
                )

            self.assertIn("deletes are not authorized", str(raised.exception))
            self.assertEqual(self._head(repo), target_before)
            self.assertTrue((repo / "_state/integration/doomed.txt").is_file())


class SupervisorThreadingTests(unittest.TestCase):
    """The supervisor is a shell file with an embedded python block; these are
    source-level assertions in the style of ``test_board_dispatch.py``."""

    def setUp(self) -> None:
        self.text = SUPERVISOR.read_text(encoding="utf-8")

    def test_authorization_defaults_to_empty(self) -> None:
        self.assertIn("authorized_delete_paths = ()", self.text)

    def test_authorization_is_derived_from_the_main_repo_packet(self) -> None:
        derivation = self.text.index('authorized_delete_paths = tuple(')
        preamble = self.text[:derivation]
        # It must be read from the controller-side packet path, whose bytes are
        # already pinned against the authenticated authority.
        self.assertIn("packet_path = repo_path / packet_scope_entries[0]", preamble)
        self.assertIn(
            'deny("inbox packet content does not match authenticated authority")',
            preamble,
        )
        self.assertIn("read_yaml_frontmatter(packet_path)", preamble)
        self.assertNotIn("handle.worktree_root", preamble.rsplit("packet_path", 1)[-1])

    def test_contract_hash_is_pinned_against_the_authority(self) -> None:
        self.assertIn(
            'deny("canonical packet contract does not match the authenticated contract hash")',
            self.text,
        )

    def test_a_delete_carrying_packet_needs_operator_approval_before_launch(self) -> None:
        """The launch-side approval check must precede integration.

        This also asserted a second branch requiring "delete" to be a
        controller-held category. That branch was removed on 2026-08-08 as
        provably unreachable: the authority check earlier in the same path
        refuses dispatch unless operator_gates equals HELD_CATEGORIES exactly,
        and "delete" is always a member, so the membership test was a constant.
        Asserting its presence pinned dead code in place and made the file read
        as though two independent controls guarded deletion. Only one ever did.
        """
        approval = self.text.index('packet_frontmatter.get("operator_approved") is not True')
        integration = self.text.index("wti.integrate_worktree_commits(")
        self.assertLess(approval, integration)
        self.assertNotIn('"delete-from-main"', self.text)

    def test_every_integration_call_site_threads_the_authorization(self) -> None:
        """EVERY caller, not just the first one found.

        V113-18 added a second integration call site that lands a blocked
        attempt's committed code when only its return path failed. It integrates
        real commits, so it is an authorization boundary too -- and a test that
        checked only `text.index(...)` would have inspected whichever site
        happened to sit higher in the file while the other went unguarded.
        """
        sites = _integration_call_sites(self.text)
        self.assertGreaterEqual(len(sites), 2, "expected success and recovery call sites")
        self.assertEqual(_integration_authorization_errors(self.text), [])

    def test_call_census_does_not_borrow_arguments_from_the_next_call(self) -> None:
        safe_next_call = """
wti.integrate_worktree_commits(
    handle,
    scope,
    authorized_delete_paths=authorized_delete_paths,
    target_branch="v2",
)
"""
        mutations = {
            "missing authorization": "wti.integrate_worktree_commits(handle, scope)\n",
            "scope is not authorization": (
                "wti.integrate_worktree_commits("
                "handle, scope, authorized_delete_paths=scope)\n"
            ),
        }
        for label, unsafe_call in mutations.items():
            with self.subTest(label=label):
                self.assertNotEqual(
                    _integration_authorization_errors(unsafe_call + safe_next_call),
                    [],
                )

    def test_residue_commit_is_not_an_authorization_path(self) -> None:
        """`commit_worker_residue` is scope-limited evidence capture; the
        authorization boundary is integration. It must not learn about
        deletion authority."""

        residue = self.text.index("wti.commit_worker_residue(")
        integration = self.text.index("wti.integrate_worktree_commits(")
        self.assertNotIn(
            "authorized_delete_paths", self.text[residue:integration]
        )


if __name__ == "__main__":
    unittest.main()
