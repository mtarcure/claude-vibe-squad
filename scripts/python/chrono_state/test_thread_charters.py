#!/usr/bin/env python3
"""Focused tests for the active-thread charter parser and resume projection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import resume, thread_charters  # noqa: E402


EMPTY_VIEW = {"live": [], "deferred": [], "unclassified": {}}


def charter_text(loops: str, done: str, ask: str = "Wire the skills.") -> str:
    return (
        f"## THE ASK\n{ask}\n\n"
        f"## OPEN LOOPS\n{loops}\n\n"
        f"## DONE-WHEN\n{done}\n"
    )


class ThreadCharterParserTests(unittest.TestCase):
    def parse(self, text: str, now: datetime | None = None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "skills-wiring.md"
        path.write_text(text, encoding="utf-8")
        return thread_charters.parse_charter(path, now=now)

    def test_unresolved_queue_is_cleared_only_by_an_appended_resolution(self):
        queued = (
            "- 2026-08-18T12:00:00Z | QUEUE Q-001 | remove mirrors "
            "— why: deletion is separate; resume: rerun the validator"
        )
        charter = self.parse(charter_text(queued, "- [ ] settle the queue"))
        self.assertEqual([q.queue_id for q in charter.unresolved_queues], ["Q-001"])

        resolved = (
            queued
            + "\n- 2026-08-18T12:01:00Z | DECLINE resolves Q-001 | keep mirrors "
            "— why: no delete grant; resume: close the thread"
        )
        charter = self.parse(charter_text(resolved, "- [ ] settle the queue"))
        self.assertEqual(charter.unresolved_queues, ())
        self.assertFalse(charter.issues)

    def test_done_when_met_requires_every_item_checked(self):
        done = self.parse(charter_text("- (none)", "- [x] first\n- [X] second"))
        open_charter = self.parse(
            charter_text("- (none)", "- [x] first\n- [ ] second")
        )
        self.assertTrue(done.done_when_met)
        self.assertFalse(open_charter.done_when_met)

    def test_old_observed_at_is_stale_after_24_hours(self):
        charter = self.parse(
            charter_text(
                "- (none)",
                "- [ ] Current reach is 26 skills "
                "(observed_at=2026-08-18T12:00:00Z)",
            ),
            now=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(charter.stale_claims), 1)
        self.assertEqual(charter.stale_claims[0].observed_at, "2026-08-18T12:00:00Z")

    def test_a_fourth_field_is_reported(self):
        charter = self.parse(
            charter_text("- (none)", "- [ ] proof") + "\n## STATUS\nactive\n"
        )
        self.assertTrue(any("exactly" in issue for issue in charter.issues))


class ThreadCharterCapsuleTests(unittest.TestCase):
    def parsed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "skills-wiring.md"
        path.write_text(
            charter_text(
                "- 2026-08-18T12:00:00Z | QUEUE Q-001 | remove mirrors "
                "— why: deletion is separate; resume: rerun the validator",
                "- [ ] settle Q-001",
            ),
            encoding="utf-8",
        )
        return thread_charters.parse_charter(path)

    def render(self, charters, max_tokens=3000):
        with (
            mock.patch.object(resume, "active_decisions", return_value=[]),
            mock.patch.object(resume, "pending_completions", return_value=[]),
            mock.patch.object(resume, "active_thread_charters", return_value=charters),
        ):
            return resume._render(
                "continue",
                EMPTY_VIEW,
                max_tokens=max_tokens,
                unreconciled=0,
            )

    def test_present_charter_projects_ask_done_when_and_unresolved_queue(self):
        capsule = self.render([self.parsed()])
        self.assertIn(resume.THREAD_HEADING, capsule)
        self.assertIn("THE ASK: Wire the skills.", capsule)
        self.assertIn("DONE-WHEN: - [ ] settle Q-001", capsule)
        self.assertIn("QUEUE Q-001", capsule)
        self.assertIn("[THREAD-skills-wiring]", capsule)

    def test_absent_charter_projects_no_thread_heading(self):
        capsule = self.render([])
        self.assertNotIn(resume.THREAD_HEADING, capsule)

    def test_stale_current_claim_gets_a_capsule_warning(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "stale.md"
        path.write_text(
            charter_text(
                "- (none)",
                "- [ ] Current reach is 26 skills "
                "(observed_at=2026-08-18T12:00:00Z)",
            ),
            encoding="utf-8",
        )
        charter = thread_charters.parse_charter(
            path,
            now=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )
        capsule = self.render([charter])
        self.assertIn("WARNING: 1 current claim(s) are stale", capsule)
        self.assertIn("observed_at=2026-08-18T12:00:00Z", capsule)

    def test_token_pressure_keeps_a_loud_charter_count(self):
        capsule = self.render([self.parsed()], max_tokens=60)
        self.assertLessEqual(len(capsule) // 4, 60)
        self.assertIn(resume.THREAD_HEADING, capsule)
        self.assertIn("active=1; open_QUEUE=1", capsule)


if __name__ == "__main__":
    unittest.main()
