#!/usr/bin/env python3
"""Acceptance canaries for interruption-safe Chrono resumption.

These tests use the real ``bin/chrono-resume-capsule.sh`` entry point twice.  Each
invocation starts a fresh Python process, so the second invocation represents a
restart that can recover only from the Markdown state under ``VAULT_ROOT``.

The stub controls are intentionally inverted: the suite stays green only when
the canary oracle raises against a projection with the relevant guard removed.
That demonstrates the test would be red for the pre-fix shape instead of merely
documenting the current output.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import resume, thread_charters, workboard  # noqa: E402


WRAPPER = ROOT / "bin" / "chrono-resume-capsule.sh"
EMPTY_VIEW = {"live": [], "deferred": [], "unclassified": {}}
THREAD_SECTION_END = re.compile(r"\n## ")


class InterruptionRestartCanaries(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # The wrapper imports production code from VAULT_ROOT/scripts/python.
        # A symlink keeps the fixture state isolated without copying source.
        (self.root / "scripts").symlink_to(ROOT / "scripts")
        self.charter_dir = (
            self.root / "_state" / "chrono" / "thread-charters" / "active"
        )
        self.charter_dir.mkdir(parents=True)
        self.ledger = self.root / "_state" / "chrono" / "OPEN-WORK.md"
        self.capsule = self.root / "_state" / "chrono" / "resume.md"
        self.event_index = 0

    def run_session_start(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(WRAPPER), *args],
            env={**os.environ, "VAULT_ROOT": str(self.root)},
            capture_output=True,
            text=True,
            check=False,
        )

    def restart_and_read_capsule(self, latest_turn: str) -> str:
        first = self.run_session_start("--latest-turn", latest_turn)
        self.assertEqual(first.returncode, 0, first.stderr)
        restarted = self.run_session_start()
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        return self.capsule.read_text(encoding="utf-8")

    def write_charter(
        self,
        thread_id: str,
        ask: str,
        loops: list[str],
        done_when: list[str],
    ) -> Path:
        path = self.charter_dir / f"{thread_id}.md"
        path.write_text(
            "## THE ASK\n"
            f"{ask}\n\n"
            "## OPEN LOOPS\n"
            + "\n".join(loops)
            + "\n\n## DONE-WHEN\n"
            + "\n".join(done_when)
            + "\n",
            encoding="utf-8",
        )
        return path

    def append_event(self, kind: str, **facts: str) -> None:
        self.event_index += 1
        workboard.append_event(
            kind,
            path=self.ledger,
            event_id=f"EV-INT-{self.event_index:02d}",
            at=f"2026-08-26T08:20:{self.event_index:02d}Z",
            **facts,
        )

    def start_campaign(self) -> None:
        self.append_event(
            "start",
            item_id="atlas-campaign",
            summary="Complete the Atlas bounty campaign through submission-ready evidence.",
            why="the approved campaign has not met DONE-WHEN",
            next_action="return to exploit validation at CASE-17",
        )

    def queue_interruption(
        self, item_id: str, summary: str, resume_action: str
    ) -> None:
        self.append_event(
            "queue",
            item_id=item_id,
            summary=summary,
            why="the request is separate from the active Atlas campaign",
            resume_action=resume_action,
        )

    @staticmethod
    def section(text: str, heading: str) -> str:
        if heading not in text:
            return ""
        return THREAD_SECTION_END.split(text.split(heading, 1)[1], maxsplit=1)[0]

    def assert_five_interrupt_restart(
        self, capsule: str, charter_path: Path
    ) -> None:
        charter = thread_charters.parse_charter(charter_path)
        expected_queue_ids = [f"INT-{index}" for index in range(1, 6)]
        projected = workboard.load_workboard(self.ledger, strict=True)

        self.assertEqual(charter.thread_id, "atlas-campaign")
        self.assertEqual(
            charter.ask,
            "Complete the Atlas bounty campaign through submission-ready evidence.",
        )
        self.assertEqual(charter.open_loops, ())
        self.assertEqual(charter.unresolved_queues, ())
        self.assertFalse(charter.issues)
        self.assertEqual(projected.active_item_id, "atlas-campaign")
        self.assertEqual(
            projected.next_action, "return to exploit validation at CASE-17"
        )
        self.assertEqual(
            {item.item_id for item in projected.items if item.state == "queued"},
            set(expected_queue_ids),
        )

        thread = self.section(capsule, resume.THREAD_HEADING)
        self.assertIn("[THREAD-atlas-campaign]", thread)
        self.assertIn("THE ASK: Complete the Atlas bounty campaign", thread)

        open_work = self.section(capsule, resume.OPEN_WORK_HEADING)
        self.assertEqual(
            set(re.findall(r"\[OPEN-WORK-(INT-\d+)\]", open_work)),
            set(expected_queue_ids),
            "the interruption disposition projection lost queued requests",
        )
        for index in range(1, 6):
            with self.subTest(interrupt=index):
                self.assertIn(f"[OPEN-WORK-INT-{index}]", open_work)
                self.assertIn(f"handle interruption {index}", open_work)
        self.assertEqual(open_work.count("next_action:"), 1)

    def test_five_successive_interruptions_survive_restart_without_silent_loss(self):
        charter = self.write_charter(
            "atlas-campaign",
            "Complete the Atlas bounty campaign through submission-ready evidence.",
            [],
            ["- [ ] validate CASE-17", "- [ ] package the final report"],
        )
        self.start_campaign()
        for index in range(1, 6):
            self.queue_interruption(
                f"INT-{index}",
                f"operator interruption {index} is queued",
                f"handle interruption {index} after the Atlas campaign",
            )

        capsule = self.restart_and_read_capsule("continue Atlas at CASE-17")

        self.assert_five_interrupt_restart(capsule, charter)
        self.assertIn("continue Atlas at CASE-17", capsule)

    def test_five_interrupt_canary_rejects_a_stubbed_disposition_projection(self):
        """Control: removing the workboard projection makes the oracle red."""
        charter = self.write_charter(
            "atlas-campaign",
            "Complete the Atlas bounty campaign through submission-ready evidence.",
            [],
            ["- [ ] validate CASE-17"],
        )
        self.start_campaign()
        for index in range(1, 6):
            self.queue_interruption(
                f"INT-{index}",
                f"operator interruption {index} is queued",
                f"handle interruption {index} later",
            )

        with (
            mock.patch.object(resume, "active_decisions", return_value=[]),
            mock.patch.object(resume, "pending_completions", return_value=[]),
            mock.patch.object(
                resume,
                "active_thread_charters",
                return_value=[thread_charters.parse_charter(charter)],
            ),
            mock.patch.object(resume, "_archived_debt_rows", return_value=([], False)),
            mock.patch.object(resume, "open_work_items", return_value=[]),
        ):
            stubbed = resume._render(
                "continue Atlas", EMPTY_VIEW, max_tokens=3000, unreconciled=0
            )

        with self.assertRaises(AssertionError):
            self.assert_five_interrupt_restart(stubbed, charter)

    def assert_two_thread_restart(self, capsule: str) -> None:
        thread = self.section(capsule, resume.THREAD_HEADING)
        open_work = self.section(capsule, resume.OPEN_WORK_HEADING)
        projected = workboard.load_workboard(self.ledger, strict=True)

        self.assertIn("[THREAD-atlas-campaign]", thread)
        self.assertIn("THE ASK: Complete the Atlas bounty campaign", thread)
        self.assertEqual(projected.active_item_id, "atlas-campaign")
        self.assertEqual(
            projected.next_action, "return to exploit validation at CASE-17"
        )
        self.assertEqual(
            next(item for item in projected.items if item.item_id == "BUG-1").state,
            "queued",
        )

        self.assertIn("[OPEN-WORK-BUG-1]", open_work)
        self.assertIn("unrelated capsule lock race", open_work)
        self.assertIn("resume: reproduce the lock race in its own packet", open_work)

    def test_campaign_and_unrelated_bug_both_survive_in_one_restart_capsule(self):
        self.write_charter(
            "atlas-campaign",
            "Complete the Atlas bounty campaign through submission-ready evidence.",
            [],
            ["- [ ] validate CASE-17", "- [ ] package the final report"],
        )
        self.start_campaign()
        self.queue_interruption(
            "BUG-1",
            "investigate the unrelated capsule lock race",
            "reproduce the lock race in its own packet",
        )

        capsule = self.restart_and_read_capsule("resume Atlas at CASE-17")

        self.assert_two_thread_restart(capsule)
        self.assertEqual(self.capsule, self.root / "_state" / "chrono" / "resume.md")

    def test_two_thread_canary_rejects_promotion_without_a_switch_event(self):
        """Control: a second start cannot implicitly promote an interruption."""
        self.write_charter(
            "atlas-campaign",
            "Complete the Atlas bounty campaign through submission-ready evidence.",
            [],
            ["- [ ] validate CASE-17"],
        )
        self.start_campaign()
        self.append_event(
            "start",
            item_id="BUG-1",
            summary="broken implicit promotion of the lock-race interruption",
            why="a switch event was omitted",
            next_action="reproduce the lock race",
        )

        with self.assertRaisesRegex(
            workboard.WorkboardConsistencyError, "exactly one active item"
        ):
            workboard.load_workboard(self.ledger, strict=True)


if __name__ == "__main__":
    unittest.main()
