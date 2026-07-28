#!/usr/bin/env python3
"""Regression tests for board-receipt terminal settlement."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import registry_reconciler as reconciler  # noqa: E402


class BoardReceiptSettlementTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def _patch_runtime(root: Path, state: Path, registry_path: Path):
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry_path),
            mock.patch.object(
                reconciler,
                "CHRONO_QUEUE_PATH",
                state / "chrono-queue.md",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_LOCKDIR",
                state / "chrono-notify.lockdir",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                state / "chrono-notify-receipts",
            ),
            mock.patch.object(
                reconciler,
                "RESPONSE_MIN_AGE",
                reconciler.timedelta(seconds=0),
            ),
            mock.patch.dict(
                "os.environ",
                {reconciler.TEST_ISOLATION_ENV: "1"},
            ),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield

    def test_blocked_receipt_closes_unpromoted_worktree_response_and_releases_scope(
        self,
    ) -> None:
        task_id = "TASK-2026-07-24-9998-blocked-board-receipt"
        attempt_id = "d-" + "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            board_dir = state / "board-dispatch"
            board_dir.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: {
                            "status": "in-flight",
                            "specialist": "sol",
                            "to_model": "gpt-codex",
                            "compatibility_namespace": "coding",
                            "return_artifact": "_state/consults/blocked.md",
                            "write_scope": ["shared/locked-scope"],
                            "delivery_attempt_id": attempt_id,
                            "delivery_generation": 1,
                            "delivery_state": "in-progress",
                            "dispatched_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipt_path = board_dir / f"{task_id}.{attempt_id}.receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "reason": "completion prevalidation failed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            worktree_response = (
                state
                / "board-worktrees"
                / attempt_id
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            worktree_response.parent.mkdir(parents=True)
            worktree_response.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: blocked\n"
                "return_artifact: _state/consults/blocked.md\n"
                "---\n\n"
                "Blocked before output promotion.\n",
                encoding="utf-8",
            )

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = registry[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], "blocked")
            self.assertEqual(
                entry["terminal_receipt_path"],
                str(receipt_path.relative_to(root)),
            )
            active_scopes = [
                scope
                for candidate in registry.values()
                if candidate.get("status") == "in-flight"
                for scope in candidate.get("write_scope", [])
            ]
            self.assertNotIn("shared/locked-scope", active_scopes)

    def test_advisory_completed_response_settles_terminal_and_releases_scope(
        self,
    ) -> None:
        task_id = "TASK-2026-07-24-9994-advisory-completed"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: {
                            "status": "in-flight",
                            "specialist": "sol",
                            "to_model": "gpt-codex",
                            "compatibility_namespace": "coding",
                            "return_artifact": "_state/consults/advisory.md",
                            "write_scope": ["_state/consults/advisory.md"],
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = state / "consults" / "advisory.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("Independent opinion.\n", encoding="utf-8")
            response = (
                root
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            response.parent.mkdir(parents=True)
            response.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: completed\n"
                "return_artifact: _state/consults/advisory.md\n"
                "---\n\n"
                "Advisory completed.\n",
                encoding="utf-8",
            )

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertGreater(changed, 0, messages)
            self.assertEqual(registry[task_id]["status"], "complete")
            self.assertFalse(
                any(
                    entry.get("status") == "in-flight"
                    for entry in registry.values()
                )
            )


if __name__ == "__main__":
    unittest.main()
