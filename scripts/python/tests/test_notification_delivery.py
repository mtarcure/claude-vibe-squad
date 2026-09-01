#!/usr/bin/env python3
"""Retry and crash-gap coverage for registry-backed Chrono notifications."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import registry_reconciler as rr  # noqa: E402


class SimulatedCrash(RuntimeError):
    """Stand in for process death after delivery but before registry ack."""


class NotificationDeliveryRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "_state"
        self.registry_path = self.state / "active-tasks.json"
        self.queue_path = self.state / "chrono-queue.md"
        self.outbox = self.root / "departments" / "coding" / "outbox"
        self.outbox.mkdir(parents=True)
        self.state.mkdir(parents=True)

        self.task_id = "TASK-2026-08-30-0110-notification-delivery"
        self.event_key = f"{self.task_id}|complete|1"
        self.registry_path.write_text(
            json.dumps(
                {
                    self.task_id: {
                        "status": "in-flight",
                        "specialist": "systems-engineer",
                        "to_model": "gpt-codex",
                        "compatibility_namespace": "coding",
                        "delivery_generation": 1,
                        "dispatched_at": "2020-01-01T00:00:00+00:00",
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.outbox / f"{self.task_id}-response.md").write_text(
            "---\nstatus: complete\n---\n\nDelivery fixture completed.\n",
            encoding="utf-8",
        )

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for patcher in (
            mock.patch.object(rr, "VAULT_ROOT", self.root),
            mock.patch.object(rr, "STATE_DIR", self.state),
            mock.patch.object(rr, "REGISTRY_PATH", self.registry_path),
            mock.patch.object(rr, "CHRONO_QUEUE_PATH", self.queue_path),
            mock.patch.object(
                rr, "CHRONO_NOTIFY_LOCKDIR", self.state / "chrono-notify.lockdir"
            ),
            mock.patch.object(
                rr,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                self.state / "chrono-notify-receipts",
            ),
            mock.patch.object(rr, "RESPONSE_MIN_AGE", timedelta(seconds=0)),
            mock.patch.object(rr, "registered_in_canonical_registry", return_value=True),
        ):
            self.stack.enter_context(patcher)

    def entry(self) -> dict[str, object]:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))[
            self.task_id
        ]

    def test_failed_nudge_is_retried_by_next_reconcile(self) -> None:
        nudge = self.stack.enter_context(
            mock.patch.object(rr, "nudge_chrono", side_effect=(False, True))
        )

        _changed, first_messages = rr.reconcile(self.task_id, dry_run=False)
        failed = self.entry()
        self.assertNotIn("notification_key", failed)
        pending = failed["notification_pending_events"][self.event_key]
        self.assertEqual(pending["outcome"], "failed")
        self.assertEqual(pending["attempt_count"], 1)
        self.assertTrue(pending["queue_recorded"])
        self.assertIn(
            f"chrono-nudge queued-only coding/{self.task_id}", first_messages
        )

        _changed, second_messages = rr.reconcile(self.task_id, dry_run=False)
        delivered = self.entry()

        self.assertEqual(nudge.call_count, 2)
        self.assertEqual(delivered["notification_key"], self.event_key)
        self.assertNotIn("notification_pending_events", delivered)
        self.assertIn(f"chrono-nudge sent coding/{self.task_id}", second_messages)
        queue = self.queue_path.read_text(encoding="utf-8")
        self.assertEqual(queue.count(self.task_id), 1, queue)

    def test_successful_delivery_is_not_resent(self) -> None:
        nudge = self.stack.enter_context(
            mock.patch.object(rr, "nudge_chrono", return_value=True)
        )

        rr.reconcile(self.task_id, dry_run=False)
        rr.reconcile(self.task_id, dry_run=False)

        delivered = self.entry()
        self.assertEqual(nudge.call_count, 1)
        self.assertEqual(delivered["notification_key"], self.event_key)
        self.assertNotIn("notification_pending_events", delivered)
        queue = self.queue_path.read_text(encoding="utf-8")
        self.assertEqual(queue.count(self.task_id), 1, queue)

    def test_repeated_failure_retries_without_registry_churn(self) -> None:
        nudge = self.stack.enter_context(
            mock.patch.object(rr, "nudge_chrono", return_value=False)
        )

        rr.reconcile(self.task_id, dry_run=False)
        after_first_failure = self.registry_path.read_bytes()
        rr.reconcile(self.task_id, dry_run=False)

        self.assertEqual(nudge.call_count, 2)
        self.assertEqual(self.registry_path.read_bytes(), after_first_failure)
        queue = self.queue_path.read_text(encoding="utf-8")
        self.assertEqual(queue.count(self.task_id), 1, queue)

    def test_crash_after_send_before_key_write_stays_retryable(self) -> None:
        receipts: set[str] = set()
        operator_sends: list[str] = []

        def receipt_backed_nudge(_message: str, event_key: str) -> bool:
            if event_key not in receipts:
                receipts.add(event_key)
                operator_sends.append(event_key)
            return True

        nudge = self.stack.enter_context(
            mock.patch.object(rr, "nudge_chrono", side_effect=receipt_backed_nudge)
        )
        with mock.patch.object(
            rr,
            "acknowledge_notification_delivery",
            side_effect=SimulatedCrash("process died before registry ack"),
        ):
            with self.assertRaises(SimulatedCrash):
                rr.reconcile(self.task_id, dry_run=False)

        crashed = self.entry()
        self.assertNotIn("notification_key", crashed)
        self.assertIn(self.event_key, crashed["notification_pending_events"])

        rr.reconcile(self.task_id, dry_run=False)
        recovered = self.entry()

        self.assertEqual(nudge.call_count, 2)
        self.assertEqual(
            operator_sends,
            [
                rr.notification_event_key(
                    f"coding/{self.task_id}", "complete"
                )
            ],
        )
        self.assertEqual(recovered["notification_key"], self.event_key)
        self.assertNotIn("notification_pending_events", recovered)

    def test_existing_receipt_is_success_without_another_send(self) -> None:
        receipt_key = rr.notification_event_key(
            f"coding/{self.task_id}", "complete"
        )
        receipt = rr.notification_receipt_path(receipt_key)
        receipt.parent.mkdir(parents=True)
        receipt.write_text("{}\n", encoding="utf-8")

        with (
            mock.patch.dict(rr.os.environ, {rr.TEST_ISOLATION_ENV: "0"}),
            mock.patch.object(rr.subprocess, "run") as run,
        ):
            delivered = rr.nudge_chrono("receipt-backed replay", receipt_key)

        self.assertTrue(delivered)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
