#!/usr/bin/env python3
"""Focused regressions for the 2026-07-29 dispatch-hygiene fixes."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
