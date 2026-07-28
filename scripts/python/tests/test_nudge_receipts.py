#!/usr/bin/env python3
"""Tests for durable Path B nudge receipts and bounded resend behavior."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from scripts.python import nudge_receipts
from scripts.python.nudge_receipts import NudgeReceiptStore, RegistryUnavailable, TmuxSender


class MutableClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class NudgeReceiptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.state_dir = self.root / "_state"
        self.registry_path = self.state_dir / "active-tasks.json"
        self.packet_path = self.root / "departments" / "coding" / "inbox" / "TASK-1.md"
        self.packet_path.parent.mkdir(parents=True)
        self.packet_path.write_text("---\nid: TASK-1\n---\n", encoding="utf-8")
        self.state_dir.mkdir()
        self.registry_path.write_text("{}\n", encoding="utf-8")
        self.clock = MutableClock(1_000.0)
        self.store = NudgeReceiptStore(
            state_dir=self.state_dir,
            registry_path=self.registry_path,
            clock=self.clock,
        )
        self.sent: list[tuple[str, str, str]] = []

    def sender(self, target: str, message: str, buffer_name: str) -> None:
        # The durable prepared record must exist before the injection attempt.
        receipts = list((self.state_dir / "dispatch-nudge-receipts").glob("*.json"))
        self.assertTrue(receipts)
        persisted_states = {
            json.loads(path.read_text(encoding="utf-8"))["state"] for path in receipts
        }
        self.assertTrue(persisted_states & {"prepared", "resending"})
        self.sent.append((target, message, buffer_name))

    def test_dropped_nudge_is_receipted_resendable_once_then_confirmed_noop(self) -> None:
        receipt = self.store.send(
            task_id="TASK-1",
            target_lane="gpt-codex",
            target="vibe-coding:gpt-codex",
            attempt="attempt-1",
            task_path=self.packet_path,
            message="claim this task",
            sender=self.sender,
        )

        self.assertEqual("sent-unconfirmed", receipt["state"])
        self.assertEqual(1, receipt["send_count"])
        self.assertEqual(1, len(self.sent))

        # tmux accepted the commands, but the lane dropped the keystrokes and
        # therefore never claimed the packet. A stale scan resends it once.
        self.clock.value = 1_061.0
        resent = self.store.resend_due(stale_after_seconds=60, sender=self.sender)
        self.assertEqual(1, len(resent))
        self.assertEqual(2, len(self.sent))
        self.assertEqual(1, resent[0]["resend_count"])

        # A second scan at the same instant is a no-op: the resend advanced the
        # durable attempt timestamp while holding the shared notification lock.
        self.assertEqual([], self.store.resend_due(stale_after_seconds=60, sender=self.sender))
        self.assertEqual(2, len(self.sent))

        # Once the task registry proves that this delivery attempt was claimed,
        # the next scan confirms the receipt and never injects another prompt.
        self.registry_path.write_text(
            json.dumps(
                {
                    "TASK-1": {
                        "delivery_attempt_id": "attempt-1",
                        "delivery_state": "in-progress",
                        "claimed_at": "2026-07-22T12:00:00Z",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.clock.value = 1_122.0
        self.assertEqual([], self.store.resend_due(stale_after_seconds=60, sender=self.sender))
        confirmed = self.store.get("TASK-1", "vibe-coding:gpt-codex", "attempt-1")
        self.assertEqual("confirmed", confirmed["state"])
        self.assertEqual(2, len(self.sent))

        # Explicitly re-running the original send is also a confirmed no-op.
        again = self.store.send(
            task_id="TASK-1",
            target_lane="gpt-codex",
            target="vibe-coding:gpt-codex",
            attempt="attempt-1",
            task_path=self.packet_path,
            message="claim this task",
            sender=self.sender,
        )
        self.assertEqual("confirmed", again["state"])
        self.assertEqual(2, len(self.sent))

    def test_resend_fails_closed_when_registry_is_missing_or_malformed(self) -> None:
        self.store.send(
            task_id="TASK-1",
            target_lane="gpt-codex",
            target="vibe-coding:gpt-codex",
            attempt="attempt-1",
            task_path=self.packet_path,
            message="claim this task",
            sender=self.sender,
        )
        self.clock.value = 1_061.0

        for registry_text in (None, "not json\n", "[]\n"):
            with self.subTest(registry_text=registry_text):
                if registry_text is None:
                    self.registry_path.unlink(missing_ok=True)
                else:
                    self.registry_path.write_text(registry_text, encoding="utf-8")
                before = len(self.sent)
                with self.assertRaises(RegistryUnavailable):
                    self.store.resend_due(stale_after_seconds=60, sender=self.sender)
                self.assertEqual(before, len(self.sent))

    def test_packet_missing_and_second_full_timeout_do_not_resend_again(self) -> None:
        self.store.send(
            task_id="TASK-1",
            target_lane="gpt-codex",
            target="vibe-coding:gpt-codex",
            attempt="attempt-1",
            task_path=self.packet_path,
            message="claim this task",
            sender=self.sender,
        )
        self.clock.value = 1_061.0
        self.assertEqual(1, len(self.store.resend_due(stale_after_seconds=60, sender=self.sender)))
        self.clock.value = 1_122.0
        self.assertEqual([], self.store.resend_due(stale_after_seconds=60, sender=self.sender))
        exhausted = self.store.get("TASK-1", "vibe-coding:gpt-codex", "attempt-1")
        self.assertEqual("resend-exhausted", exhausted["state"])
        self.assertEqual(2, len(self.sent))

        other_packet = self.packet_path.with_name("TASK-2.md")
        other_packet.write_text("---\nid: TASK-2\n---\n", encoding="utf-8")
        self.store.send(
            task_id="TASK-2",
            target_lane="gpt-codex",
            target="vibe-coding:gpt-codex",
            attempt="attempt-2",
            task_path=other_packet,
            message="claim task two",
            sender=self.sender,
        )
        other_packet.unlink()
        self.clock.value = 1_183.0
        self.assertEqual([], self.store.resend_due(stale_after_seconds=60, sender=self.sender))
        missing = self.store.get("TASK-2", "vibe-coding:gpt-codex", "attempt-2")
        self.assertEqual("closed-packet-missing", missing["state"])
        self.assertEqual(3, len(self.sent))

    def test_resend_releases_shared_lock_between_receipts(self) -> None:
        second_packet = self.packet_path.with_name("TASK-2.md")
        second_packet.write_text("---\nid: TASK-2\n---\n", encoding="utf-8")
        for task_id, attempt, packet in (
            ("TASK-1", "attempt-1", self.packet_path),
            ("TASK-2", "attempt-2", second_packet),
        ):
            self.store.send(
                task_id=task_id,
                target_lane="gpt-codex",
                target="vibe-coding:gpt-codex",
                attempt=attempt,
                task_path=packet,
                message=f"claim {task_id}",
                sender=self.sender,
            )
        self.clock.value = 1_061.0

        original_lock = nudge_receipts.shared_notify_lock
        events: list[str] = []

        @contextmanager
        def counting_lock(*args, **kwargs):
            events.append("enter")
            with original_lock(*args, **kwargs):
                yield
            events.append("exit")

        with mock.patch("scripts.python.nudge_receipts.shared_notify_lock", counting_lock):
            resent = self.store.resend_due(stale_after_seconds=60, sender=self.sender)

        self.assertEqual(2, len(resent))
        self.assertEqual(["enter", "exit", "enter", "exit"], events)

    def test_tmux_sender_uses_buffered_literal_paste_then_enter(self) -> None:
        calls: list[tuple[list[str], str | None]] = []

        def fake_run(argv, **kwargs):
            calls.append((list(argv), kwargs.get("input")))
            return subprocess.CompletedProcess(argv, 0)

        sleeps: list[float] = []
        sender = TmuxSender(tmux_bin="tmux", sleeper=sleeps.append)
        with mock.patch("scripts.python.nudge_receipts.subprocess.run", side_effect=fake_run):
            sender("vibe-coding:gpt-codex", "literal $() `text`", "nudge-abc")

        self.assertEqual(
            [
                (["tmux", "load-buffer", "-b", "nudge-abc", "-"], "literal $() `text`"),
                (
                    [
                        "tmux",
                        "paste-buffer",
                        "-d",
                        "-p",
                        "-b",
                        "nudge-abc",
                        "-t",
                        "vibe-coding:gpt-codex",
                    ],
                    None,
                ),
                (["tmux", "send-keys", "-t", "vibe-coding:gpt-codex", "Enter"], None),
            ],
            calls,
        )
        self.assertEqual([0.4, 0.15], sleeps)


if __name__ == "__main__":
    unittest.main()
