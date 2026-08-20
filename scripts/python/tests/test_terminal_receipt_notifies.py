#!/usr/bin/env python3
"""A terminal board receipt must produce exactly one durable queue record.

Regression coverage for the terminal-receipt branch of ``reconcile()``
(registry_reconciler.py ~3218-3243): a registry entry whose status is
*already* ``blocked``/``complete``/``completed`` and which resolves a
matching terminal board receipt on re-reconcile must emit exactly one
``events`` entry -- either REVIEW-REQUIRED (mandatory cross-family review
still pending) or AUTO-CLOSED (no review pending) -- so the entry gets a
durable chrono-queue record and a gated nudge via ``emit_event``. Before this
fix, both arms of that branch appended only to ``messages`` and then
``continue``'d, reaching neither ``emit_event`` nor ``append_chrono_queue``.
"""

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

import registry_reconciler as rr  # noqa: E402


@contextmanager
def _patch_runtime(root: Path, state: Path, registry_path: Path):
    patchers = (
        mock.patch.object(rr, "VAULT_ROOT", root),
        mock.patch.object(rr, "STATE_DIR", state),
        mock.patch.object(rr, "REGISTRY_PATH", registry_path),
        mock.patch.object(rr, "CHRONO_QUEUE_PATH", state / "chrono-queue.md"),
        mock.patch.object(
            rr, "CHRONO_NOTIFY_LOCKDIR", state / "chrono-notify.lockdir"
        ),
        mock.patch.object(
            rr,
            "CHRONO_NOTIFY_RECEIPTS_DIR",
            state / "chrono-notify-receipts",
        ),
        mock.patch.object(rr, "RESPONSE_MIN_AGE", rr.timedelta(seconds=0)),
        mock.patch.dict("os.environ", {rr.TEST_ISOLATION_ENV: "1"}),
    )
    with ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        yield


class TerminalReceiptNotifies(unittest.TestCase):
    def _reconcile_one_terminal_receipt(self, pending: bool) -> list[tuple]:
        task_id = "TASK-2026-08-16-0001-terminal-receipt-notify"
        attempt_id = "d-" + "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            board_dir = state / "board-dispatch"
            board_dir.mkdir(parents=True)

            entry: dict[str, object] = {
                # Already-terminal status: this is the re-reconcile shape
                # that hits registry_reconciler.py:3188's
                # `current_status in {"blocked", "complete", "completed"}`
                # gate -- a task settled to a terminal status by an earlier
                # pass that still needs its terminal-receipt bookkeeping
                # (mark_delivery_terminal / terminal_receipt_path / the
                # review-vs-close decision) finished.
                "status": "blocked",
                "specialist": "sol",
                "to_model": "gpt-codex",
                "compatibility_namespace": "coding",
                "return_artifact": "_state/consults/result.md",
                "write_scope": ["shared/some-scope"],
                "delivery_attempt_id": attempt_id,
                "delivery_generation": 1,
                "delivery_state": "in-progress",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }
            if pending:
                # mandatory_review "true" with a review_model in a distinct
                # family from to_model, and no review_class set, holds the
                # task for review (cross_family_review_pending refuses an
                # unreadable review_class rather than defaulting it) --
                # the REVIEW-REQUIRED arm.
                entry["mandatory_review"] = "true"
                entry["review_model"] = "gemini"

            registry_path.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
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

            captured: list[tuple] = []
            with _patch_runtime(root, state, registry_path):
                with mock.patch.object(
                    rr,
                    "emit_event",
                    side_effect=lambda *a: captured.append(a) or True,
                ):
                    rr.reconcile(task_id, dry_run=False)
            return captured

    def test_review_required_terminal_receipt_emits_one_event(self) -> None:
        captured = self._reconcile_one_terminal_receipt(pending=True)
        self.assertEqual(
            len(captured), 1, "review-required terminal receipt emitted no event"
        )
        status, task_ref, _summary, _nudge = captured[0]
        self.assertEqual(status, "REVIEW-REQUIRED")
        self.assertIn("/", task_ref)

    def test_auto_closed_terminal_receipt_emits_one_event(self) -> None:
        captured = self._reconcile_one_terminal_receipt(pending=False)
        self.assertEqual(
            len(captured), 1, "auto-closed terminal receipt emitted no event"
        )
        self.assertEqual(captured[0][0], "AUTO-CLOSED")


if __name__ == "__main__":
    unittest.main()
