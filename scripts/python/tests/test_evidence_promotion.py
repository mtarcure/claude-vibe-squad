#!/usr/bin/env python3
"""Terminal evidence survives independently of task success/promotion."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "python"))

import board_process_truth as bpt  # noqa: E402
import worktree_isolation as wti  # noqa: E402


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


class TerminalEvidencePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.repo = self.root / "repo"
        self.pool_root = self.root / "worktrees"
        self.dispatch_root = self.root / "dispatch"
        self.repo.mkdir()
        self.dispatch_root.mkdir()
        _git(["init", "-q"], cwd=self.repo)
        _git(["config", "user.name", "Evidence Test"], cwd=self.repo)
        _git(["config", "user.email", "evidence@example.test"], cwd=self.repo)
        (self.repo / "src").mkdir()
        (self.repo / "scripts" / "python" / "tests").mkdir(parents=True)
        (self.repo / "src" / "existing.c").write_text(
            "int answer(void) { return 1; }\n", encoding="utf-8"
        )
        (self.repo / "scripts" / "python" / "base.py").write_text(
            "BASE = True\n", encoding="utf-8"
        )
        (self.repo / "scripts" / "python" / "tests" / "base.txt").write_text(
            "fixture\n", encoding="utf-8"
        )
        (self.repo / ".gitignore").write_text(
            "_state/\n"
            "departments/*/outbox/\n"
            "__pycache__/\n"
            "*.pyc\n"
            "build/\n",
            encoding="utf-8",
        )
        _git(["add", "."], cwd=self.repo)
        _git(["commit", "-q", "-m", "base"], cwd=self.repo)
        _git(["branch", "-M", "v2"], cwd=self.repo)
        self.counter = 0

    def _attempt(self, label: str) -> tuple[wti.WorktreeHandle, dict[str, object]]:
        self.counter += 1
        task_id = f"TASK-2026-08-10-9{self.counter:03d}-{label}"
        attempt_id = f"d-{self.counter:032x}"
        pool = wti.WorktreePool(self.repo, self.pool_root, base_branch="v2")
        handle = pool.provision(task_id, attempt_id)
        authority: dict[str, object] = {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "repo_root": str(self.repo),
            "pool_root": str(self.pool_root),
            "write_paths": [
                "src",
                "scripts/python",
                "_state/results",
                "departments/coding/outbox",
            ],
            "expected_result_path": f"_state/results/{task_id}.md",
            "expected_outbox_path": (
                f"departments/coding/outbox/{task_id}-response.md"
            ),
        }
        return handle, authority

    def _descriptor(
        self,
        authority: dict[str, object],
    ) -> tuple[Path, Path, Path]:
        task_id = str(authority["task_id"])
        attempt_id = str(authority["attempt_id"])
        base = self.dispatch_root / f"{task_id}.{attempt_id}"
        dispatch = Path(f"{base}.dispatch.json")
        context = Path(f"{base}.context.json")
        receipt = Path(f"{base}.receipt.json")
        log = Path(f"{base}.log")
        context.write_text(json.dumps({"authority": authority}), encoding="utf-8")
        log.touch()
        identity = {
            "pid": 424242,
            "pgid": 424242,
            "process_start_token": "fixture:terminal-evidence",
            "argv_sha256": "a" * 64,
        }
        descriptor = {
            "schema": bpt.DESCRIPTOR_V2,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "created_at": bpt.utc_now(),
            **identity,
            "context_path": str(context),
            "log_path": str(log),
            "receipt_path": str(receipt),
        }
        dispatch.write_text(json.dumps(descriptor) + "\n", encoding="utf-8")
        return dispatch, context, receipt

    def _finalize(
        self,
        authority: dict[str, object],
        *,
        status: str = "blocked",
        reason: str,
        failure_class: str | None = None,
    ) -> dict[str, object]:
        dispatch, _context, receipt = self._descriptor(authority)
        raw = Path(f"{receipt}.capture")
        payload: dict[str, object] = {
            "status": status,
            "reason": reason,
            "task_id": authority["task_id"],
            "attempt_id": authority["attempt_id"],
            "generation": 1,
        }
        if failure_class is not None:
            payload["failure_class"] = failure_class
        raw.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with mock.patch.object(
            bpt,
            "process_truth",
            return_value={"state": "live", "reason": "fixture", "observed": {}},
        ):
            return bpt.finalize_receipt(raw, dispatch, receipt)

    def _show(self, commit: str, relative: str) -> str:
        return _git(["show", f"{commit}:{relative}"], cwd=self.repo)

    def test_timed_out_tracked_change_is_snapshotted_and_named_in_receipt(self) -> None:
        handle, authority = self._attempt("timeout-tracked")
        (handle.worktree_root / "src" / "existing.c").write_text(
            "int answer(void) { return 42; }\n", encoding="utf-8"
        )

        receipt = self._finalize(
            authority,
            reason="fresh lane CLI timed out after 1800 seconds",
            failure_class="cli_timeout",
        )

        self.assertEqual(receipt["terminal_outcome"], "blocked")
        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "preserved")
        self.assertTrue(evidence["snapshot_created"])
        self.assertIn("src/existing.c", evidence["tracked_residue_paths"])
        self.assertEqual(
            evidence["evidence_location"],
            f"{evidence['evidence_ref']}@{evidence['evidence_commit']}",
        )
        self.assertIn("return 42", self._show(evidence["evidence_commit"], "src/existing.c"))

        # Retrying terminalisation names the same durable snapshot; it does not
        # manufacture a second WIP commit.
        repeated = wti.preserve_terminal_evidence(authority, base_branch="v2")
        self.assertEqual(repeated.status, "preserved_existing")
        self.assertFalse(repeated.snapshot_created)
        self.assertEqual(repeated.evidence_commit, evidence["evidence_commit"])
        _git(["worktree", "remove", str(handle.worktree_root)], cwd=self.repo)
        self.assertFalse(handle.worktree_root.exists())
        self.assertIn(
            "return 42",
            self._show(evidence["evidence_commit"], "src/existing.c"),
        )

    def test_timed_out_untracked_source_and_test_files_are_both_preserved(self) -> None:
        handle, authority = self._attempt("timeout-untracked")
        implementation = handle.worktree_root / "scripts" / "python" / "dispatch_preflight.py"
        test_file = (
            handle.worktree_root
            / "scripts"
            / "python"
            / "tests"
            / "test_dispatch_preflight.py"
        )
        implementation.write_text("def preflight():\n    return True\n", encoding="utf-8")
        test_file.write_text("def test_preflight():\n    assert True\n", encoding="utf-8")

        receipt = self._finalize(
            authority,
            reason="fresh lane CLI timed out after 1800 seconds",
            failure_class="cli_timeout",
        )

        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "preserved")
        self.assertEqual(evidence["untracked_residue_count"], 2)
        self.assertEqual(
            set(evidence["untracked_residue_paths"]),
            {
                "scripts/python/dispatch_preflight.py",
                "scripts/python/tests/test_dispatch_preflight.py",
            },
        )
        commit = evidence["evidence_commit"]
        self.assertIn("return True", self._show(commit, "scripts/python/dispatch_preflight.py"))
        self.assertIn("assert True", self._show(commit, "scripts/python/tests/test_dispatch_preflight.py"))

    def test_missing_envelope_preserves_mixed_code_and_ignored_artifact(self) -> None:
        handle, authority = self._attempt("missing-envelope-mixed")
        (handle.worktree_root / "src" / "existing.c").write_text(
            "int answer(void) { return 87; }\n", encoding="utf-8"
        )
        new_test = handle.worktree_root / "scripts" / "python" / "tests" / "test_new.py"
        new_test.write_text("def test_new():\n    assert 87\n", encoding="utf-8")
        result_relative = str(authority["expected_result_path"])
        result = handle.worktree_root / result_relative
        result.parent.mkdir(parents=True)
        result.write_text("complete worker artifact\n", encoding="utf-8")
        # The response envelope is deliberately absent: this is the real 0870
        # failure shape. The ignored artifact must still enter the branch snapshot.

        receipt = self._finalize(
            authority,
            reason="fresh lane completion prevalidation failed: response envelope is missing",
        )

        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "preserved")
        self.assertEqual(evidence["tracked_residue_count"], 1)
        self.assertEqual(evidence["untracked_residue_count"], 2)
        self.assertIn(result_relative, evidence["explicit_output_paths"])
        commit = evidence["evidence_commit"]
        self.assertIn("return 87", self._show(commit, "src/existing.c"))
        self.assertIn("assert 87", self._show(commit, "scripts/python/tests/test_new.py"))
        self.assertEqual(self._show(commit, result_relative), "complete worker artifact")
        self.assertFalse((self.repo / result_relative).exists())

    def test_failed_process_without_receipt_is_reaped_with_evidence(self) -> None:
        handle, authority = self._attempt("failed-reap")
        source = handle.worktree_root / "scripts" / "python" / "recovered.py"
        source.write_text("RECOVERED = True\n", encoding="utf-8")
        dispatch, _context, _receipt = self._descriptor(authority)
        with mock.patch.object(
            bpt,
            "process_truth",
            return_value={"state": "dead", "reason": "process_not_live", "observed": None},
        ):
            receipt = bpt.reap_dead_attempt(dispatch)

        self.assertEqual(receipt["terminal_outcome"], "failed")
        evidence = receipt["evidence_preservation"]
        self.assertIn(evidence["status"], {"preserved", "preserved_existing"})
        self.assertEqual(
            self._show(evidence["evidence_commit"], "scripts/python/recovered.py"),
            "RECOVERED = True",
        )

    def test_post_provision_denial_still_preserves_work(self) -> None:
        handle, authority = self._attempt("denied-after-provision")
        source = handle.worktree_root / "scripts" / "python" / "denied_work.py"
        source.write_text("DENIED_BUT_DURABLE = True\n", encoding="utf-8")

        receipt = self._finalize(
            authority,
            status="denied",
            reason="post-provision capability denial",
        )

        self.assertEqual(receipt["terminal_outcome"], "denied")
        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "preserved")
        self.assertEqual(
            self._show(evidence["evidence_commit"], "scripts/python/denied_work.py"),
            "DENIED_BUT_DURABLE = True",
        )

    def test_operator_cancellation_receipt_preserves_work(self) -> None:
        handle, authority = self._attempt("cancelled")
        source = handle.worktree_root / "scripts" / "python" / "cancelled_work.py"
        source.write_text("CANCELLED_BUT_DURABLE = True\n", encoding="utf-8")
        dispatch, _context, receipt_path = self._descriptor(authority)

        with (
            mock.patch.object(
                bpt,
                "process_truth",
                return_value={"state": "live", "reason": "fixture", "observed": {}},
            ),
            mock.patch.object(bpt, "terminate_attributable_tree"),
        ):
            bpt.cancel_attempt(dispatch, 0)

        receipt = bpt.load_json(receipt_path)
        self.assertEqual(receipt["terminal_outcome"], "cancelled")
        evidence = receipt["evidence_preservation"]
        self.assertEqual(evidence["status"], "preserved")
        self.assertEqual(
            self._show(evidence["evidence_commit"], "scripts/python/cancelled_work.py"),
            "CANCELLED_BUT_DURABLE = True",
        )

    def test_success_receipt_does_not_snapshot_or_double_promote(self) -> None:
        handle, authority = self._attempt("normal-success")
        result_relative = str(authority["expected_result_path"])
        canonical = self.repo / result_relative
        canonical.parent.mkdir(parents=True)
        canonical.write_text("already promoted\n", encoding="utf-8")
        before_head = _git(["rev-parse", "HEAD"], cwd=handle.worktree_root)

        receipt = self._finalize(
            authority,
            status="launched",
            reason="normal successful task",
        )

        self.assertEqual(receipt["terminal_outcome"], "complete")
        self.assertNotIn("evidence_preservation", receipt)
        self.assertEqual(_git(["rev-parse", "HEAD"], cwd=handle.worktree_root), before_head)
        self.assertEqual(canonical.read_text(encoding="utf-8"), "already promoted\n")

    def test_existing_canonical_artifact_is_never_overwritten(self) -> None:
        handle, authority = self._attempt("artifact-conflict")
        result_relative = str(authority["expected_result_path"])
        canonical = self.repo / result_relative
        canonical.parent.mkdir(parents=True)
        canonical.write_text("canonical bytes\n", encoding="utf-8")
        worker = handle.worktree_root / result_relative
        worker.parent.mkdir(parents=True)
        worker.write_text("worker bytes\n", encoding="utf-8")

        with mock.patch.dict(os.environ, {"SQUAD_BASE_BRANCH": "v2"}):
            evidence = wti.preserve_terminal_evidence(authority)

        self.assertEqual(canonical.read_text(encoding="utf-8"), "canonical bytes\n")
        self.assertIn(result_relative, evidence.divergent_promoted_paths)
        self.assertEqual(self._show(evidence.evidence_commit, result_relative), "worker bytes")

    def test_git_ignored_residue_is_excluded_and_untracked_bounds_are_visible(self) -> None:
        handle, authority = self._attempt("bounded-residue")
        ignored = handle.worktree_root / "scripts" / "python" / "__pycache__" / "noise.pyc"
        ignored.parent.mkdir(parents=True)
        ignored.write_bytes(b"build residue")
        source = handle.worktree_root / "scripts" / "python" / "intentional.py"
        source.write_bytes(b"12345")

        evidence = wti.preserve_terminal_evidence(
            authority,
            base_branch="v2",
            maximum_untracked_files=1,
            maximum_untracked_file_bytes=4,
            maximum_untracked_total_bytes=4,
        )

        self.assertEqual(evidence.status, "retained_bounded")
        self.assertEqual(evidence.omitted_untracked_paths, ("scripts/python/intentional.py",))
        self.assertEqual(evidence.omitted_untracked_bytes, 5)
        self.assertNotIn("noise.pyc", " ".join(evidence.omitted_untracked_paths))
        self.assertTrue(evidence.worktree_retained_required)
        self.assertEqual(evidence.evidence_location, str(handle.worktree_root))


if __name__ == "__main__":
    unittest.main()
