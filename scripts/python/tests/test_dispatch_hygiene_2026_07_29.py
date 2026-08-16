#!/usr/bin/env python3
"""Focused regressions for the 2026-07-29 dispatch-hygiene fixes."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import ClassVar
import unittest
from unittest import mock


TEST_ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION_ROOT = Path(
    os.environ.get("DISPATCH_HYGIENE_IMPLEMENTATION_ROOT", TEST_ROOT)
).resolve()
PYTHON_DIR = IMPLEMENTATION_ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
import registry_reconciler as reconciler  # noqa: E402


TASK_ID = "TASK-2026-07-29-2045-dispatch-hygiene"
RESULT_RELATIVE = "_state/dispatch-hygiene-regression/report.md"
OUTBOX_RELATIVE = f"departments/coding/outbox/{TASK_ID}-response.md"


def _authority() -> dict[str, object]:
    return {
        "task_id": TASK_ID,
        "lane": "codex",
        "write_paths": ["_state/dispatch-hygiene-regression/"],
        "expected_result_path": RESULT_RELATIVE,
        "expected_outbox_path": OUTBOX_RELATIVE,
    }


def _stage_worker_completion(worktree: Path) -> None:
    result = worktree / RESULT_RELATIVE
    result.parent.mkdir(parents=True)
    result.write_text("fresh worker result\n", encoding="utf-8")
    envelope = worktree / OUTBOX_RELATIVE
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        "---\n"
        f"id: {TASK_ID}-response\n"
        f"in_response_to: {TASK_ID}\n"
        "from: gpt-codex\n"
        "to: chrono\n"
        "type: RESULT\n"
        "status: complete\n"
        f"return_artifact: {RESULT_RELATIVE}\n"
        "---\n\n"
        "Fresh retry completed.\n",
        encoding="utf-8",
    )


class RegistryAtomicWriteDurabilityTests(unittest.TestCase):
    def test_atomic_write_fsyncs_file_then_parent_directory(self) -> None:
        real_fsync = os.fsync
        observed: list[str] = []

        def recording_fsync(descriptor: int) -> None:
            mode = os.fstat(descriptor).st_mode
            observed.append("directory" if stat.S_ISDIR(mode) else "file")
            real_fsync(descriptor)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "active-tasks.json"
            with mock.patch.object(
                reconciler.os, "fsync", side_effect=recording_fsync
            ):
                reconciler.atomic_write(destination, '{"TASK": {}}\n')

            self.assertEqual(observed, ["file", "directory"])
            self.assertEqual(destination.read_text(encoding="utf-8"), '{"TASK": {}}\n')

    def test_atomic_write_removes_staging_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "active-tasks.json"
            destination.write_text("old\n", encoding="utf-8")

            with mock.patch.object(
                Path, "replace", side_effect=OSError("injected replace failure")
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    reconciler.atomic_write(destination, "new\n")

            self.assertEqual(destination.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(destination.parent.glob("active-tasks.json.tmp.*")), [])


class BlockedStubReclaimTests(unittest.TestCase):
    def test_exact_controller_blocked_stub_is_reclaimed_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "main"
            worktree = root / "worktree"
            repo.mkdir()
            worktree.mkdir()
            blocked = repo / RESULT_RELATIVE
            blocked.parent.mkdir(parents=True)
            blocked.write_text(
                "blocked\n\n"
                f"# Board dispatch blocked — {TASK_ID}\n\n"
                "Controller reason: prior detached supervisor failed\n",
                encoding="utf-8",
            )
            _stage_worker_completion(worktree)

            receipt = dcb.bridge_worktree_outputs(repo, worktree, _authority())

            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(
                blocked.read_text(encoding="utf-8"),
                "fresh worker result\n",
            )
            self.assertIn(
                "status: complete",
                (repo / OUTBOX_RELATIVE).read_text(encoding="utf-8"),
            )

    def test_arbitrary_preexisting_artifact_remains_no_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "main"
            worktree = root / "worktree"
            repo.mkdir()
            worktree.mkdir()
            existing = repo / RESULT_RELATIVE
            existing.parent.mkdir(parents=True)
            existing.write_text(
                "blocked\n\n"
                "# Board dispatch blocked — TASK-2026-07-29-2046-other\n\n"
                "Controller reason: belongs to a different task\n",
                encoding="utf-8",
            )
            _stage_worker_completion(worktree)

            with self.assertRaises(dcb.DispatchContextError) as caught:
                dcb.prepare_worktree_outputs(repo, worktree, _authority())

            self.assertIn("return artifact destination already differs", str(caught.exception))
            self.assertIn("belongs to a different task", existing.read_text(encoding="utf-8"))


def _shell_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"{name} is missing from squad-monitor.sh")
    return match.group(0)


class TaskIdleMetricTests(unittest.TestCase):
    def test_idle_uses_the_task_registry_activity_not_lane_age(self) -> None:
        monitor = (IMPLEMENTATION_ROOT / "bin" / "squad-monitor.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('idle_secs=$(task_idle_secs "$task_id")', monitor)
        shell = (
            "set -uo pipefail\n"
            + _shell_function(monitor, "iso_to_epoch")
            + _shell_function(monitor, "task_idle_secs")
            + 'REGISTRY="$1"\n'
            + 'now="$2"\n'
            + 'task_idle_secs "$3"\n'
        )
        now = 1_800_000_000
        dispatched = datetime.fromtimestamp(
            now - 20 * 60, tz=timezone.utc
        ).isoformat()
        heartbeat = datetime.fromtimestamp(now - 45, tz=timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "active-tasks.json"
            registry.write_text(
                json.dumps(
                    {
                        TASK_ID: {
                            "dispatched_at": dispatched,
                            "started_at": datetime.fromtimestamp(
                                now - 15 * 60, tz=timezone.utc
                            ).isoformat(),
                            "heartbeat_observed_at": heartbeat,
                        }
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["bash", "-c", shell, "--", str(registry), str(now), TASK_ID],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "45")
        self.assertLessEqual(int(completed.stdout), 20 * 60)


class InboxArchiveSettlementTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def _runtime(root: Path):
        state = root / "_state"
        registry = state / "active-tasks.json"
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry),
            mock.patch.object(
                reconciler,
                "RESPONSE_MIN_AGE",
                timedelta(seconds=0),
            ),
            mock.patch.object(reconciler, "append_chrono_queue"),
            mock.patch.object(reconciler, "emit_event", return_value=False),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield registry

    @staticmethod
    def _packet(root: Path) -> tuple[Path, bytes]:
        packet = root / "departments" / "coding" / "inbox" / f"{TASK_ID}.md"
        packet.parent.mkdir(parents=True)
        payload = f"---\nid: {TASK_ID}\n---\n\nTask packet.\n".encode()
        packet.write_bytes(payload)
        return packet, payload

    def test_explicit_close_atomically_archives_the_inbox_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, payload = self._packet(root)
            with self._runtime(root) as registry:
                registry.parent.mkdir(parents=True)
                registry.write_text(
                    json.dumps(
                        {
                            TASK_ID: {
                                "status": "in-flight",
                                "compatibility_namespace": "coding",
                            }
                        }
                    ),
                    encoding="utf-8",
                )

                changed = reconciler.close_task(
                    TASK_ID, "superseded by a clean retry", "superseded"
                )
                retry_changed = reconciler.close_task(
                    TASK_ID, "superseded by a clean retry", "superseded"
                )

            archived = (
                root
                / "departments"
                / "coding"
                / "archive"
                / f"{TASK_ID}.md"
            )
            self.assertTrue(changed)
            self.assertFalse(retry_changed)
            self.assertFalse(packet.exists())
            self.assertEqual(archived.read_bytes(), payload)

    def test_response_settlement_archives_the_inbox_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, payload = self._packet(root)
            with self._runtime(root) as registry:
                registry.parent.mkdir(parents=True)
                registry.write_text(
                    json.dumps(
                        {
                            TASK_ID: {
                                "status": "in-flight",
                                "compatibility_namespace": "coding",
                                "source_namespace": "coding",
                                "return_artifact": RESULT_RELATIVE,
                                "write_scope": [RESULT_RELATIVE],
                                "dispatched_at": (
                                    datetime.now(timezone.utc) - timedelta(minutes=1)
                                ).isoformat(),
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                artifact = root / RESULT_RELATIVE
                artifact.parent.mkdir(parents=True)
                artifact.write_text("settled result\n", encoding="utf-8")
                response = root / OUTBOX_RELATIVE
                response.parent.mkdir(parents=True)
                response.write_text(
                    "---\n"
                    f"id: {TASK_ID}-response\n"
                    f"in_response_to: {TASK_ID}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    f"return_artifact: {RESULT_RELATIVE}\n"
                    "---\n\n"
                    "Settled response.\n",
                    encoding="utf-8",
                )

                changed, messages = reconciler.reconcile(TASK_ID, dry_run=False)

            archived = (
                root
                / "departments"
                / "coding"
                / "archive"
                / f"{TASK_ID}.md"
            )
            self.assertGreater(changed, 0, messages)
            self.assertFalse(packet.exists())
            self.assertEqual(archived.read_bytes(), payload)


class StructuralWriteScopeRefusalTest(unittest.TestCase):
    """send-task.sh must refuse a structural write_scope path at DISPATCH time.

    worktree_isolation refuses any worker commit touching `.git` or `.githooks`
    regardless of write_scope, and that refusal discards the entire lane's
    output rather than just the offending file. So granting such a path reads as
    authorization while behaving as a guaranteed total loss. Measured
    2026-08-15: lane 6200 lost a full documentation pass exactly this way.
    """

    SEND_TASK = IMPLEMENTATION_ROOT / "bin" / "send-task.sh"

    # send-task.sh refuses to dispatch from a linked worktree, and that guard runs
    # BEFORE the structural write_scope check. Running these tests from a worktree
    # would therefore exercise the wrong guard and assert on a message that cannot
    # appear -- the result would depend on which checkout the suite ran in rather
    # than on the behaviour under test. So when we are in a worktree, build a
    # throwaway NORMAL repo from the same tree and drive the real script there.
    # That is also the production path: dispatch only ever happens from a main
    # checkout.
    _scratch: ClassVar[tempfile.TemporaryDirectory | None] = None
    _root: ClassVar[Path]

    @classmethod
    def setUpClass(cls):
        git_dir = subprocess.run(
            ["git", "-C", str(IMPLEMENTATION_ROOT), "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        common_dir = subprocess.run(
            ["git", "-C", str(IMPLEMENTATION_ROOT), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if git_dir == common_dir:
            cls._root = IMPLEMENTATION_ROOT      # already a normal checkout
            return
        cls._scratch = tempfile.TemporaryDirectory()
        root = Path(cls._scratch.name) / "repo"
        root.mkdir()
        archive = Path(cls._scratch.name) / "tree.tar"
        subprocess.run(
            ["git", "-C", str(IMPLEMENTATION_ROOT), "archive", "HEAD", "-o", str(archive)],
            check=True, capture_output=True,
        )
        subprocess.run(["tar", "-xf", str(archive), "-C", str(root)], check=True)
        for cmd in (
            ["git", "init", "-q", "."],
            ["git", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "scratch"],
        ):
            subprocess.run(cmd, cwd=str(root), check=False, capture_output=True)
        cls._root = root

    @classmethod
    def tearDownClass(cls):
        if cls._scratch is not None:
            cls._scratch.cleanup()
            cls._scratch = None

    def _packet(self, write_scope: str) -> str:
        return (
            "---\n"
            "id: TASK-2026-08-15-9991-structural-scope-test\n"
            "run_id: TEST-STRUCTURAL\n"
            "from: chrono\n"
            "to_model: claude\n"
            "specialist: technical-writer\n"
            "source_namespace: content\n"
            "compatibility_namespace: content\n"
            "review_model: gpt-codex\n"
            "mandatory_review: false\n"
            "review_class: standard\n"
            "mode: project\n"
            "result_type: normal\n"
            "memory_aperture: none\n"
            "capability: none\n"
            "phase: P14.2\n"
            "type: TASK\n"
            "priority: low\n"
            "status: new\n"
            "created: 2026-08-15T21:00:00-07:00\n"
            "deadline: 2026-08-15T23:59:00-07:00\n"
            f"write_scope: [{write_scope}]\n"
            "read_scope: [docs]\n"
            "return_artifact: docs/unused-structural-test.md\n"
            "success_criteria: [never runs]\n"
            "out_of_scope: [everything]\n"
            "parallel_safe: true\n"
            "direct_lane_work_allowed: true\n"
            "operator_approved: true\n"
            "model_override_reason: none\n"
            "---\n\n"
            "# Structural write_scope canary\n\n"
            "This packet must never launch a lane.\n"
        )

    def _run(self, write_scope: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "canary.md"
            packet.write_text(self._packet(write_scope), encoding="utf-8")
            return subprocess.run(
                ["bash", str(self._root / "bin" / "send-task.sh"), str(packet)],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self._root),
            )

    def test_structural_path_is_refused_before_dispatch(self):
        completed = self._run("docs/git-hooks.md, .githooks/pre-commit")
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("structural path a worker can never commit", output)
        self.assertIn(".githooks", output)
        # It must die BEFORE anything is dispatched, or the guard is decorative.
        self.assertNotIn("Dispatching TASK-2026-08-15-9991", output)

    def test_nested_structural_segment_is_also_refused(self):
        # A segment anywhere in the path counts, not only the first one.
        completed = self._run("tools/.git/config")
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("structural path a worker can never commit", output)

    def test_the_segment_set_has_one_home(self):
        """The guard must import the enforcer's constant, never restate it.

        A hardcoded copy would predict the enforcer correctly today and drift
        silently the moment a segment is added on the other side.
        """
        source = self.SEND_TASK.read_text(encoding="utf-8")
        self.assertIn(
            "from worktree_isolation import _CBSE_STRUCTURAL_SEGMENTS",
            source,
            "send-task.sh must import the structural-segment set, not restate it",
        )
        guard = source.split("Refuse a structural path HERE", 1)[1].split("PYEOF", 1)[0]
        self.assertNotIn(
            '".githooks"',
            guard,
            "structural segments must not be hardcoded in the dispatcher",
        )


if __name__ == "__main__":
    unittest.main()
