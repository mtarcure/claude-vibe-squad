#!/usr/bin/env python3
"""Tests for the `## Pending completions` capsule section (Task 4, notification spine).

chrono/CLAUDE.md step 7 tells Chrono to read `_state/chrono-queue.md` directly, but
the capsule — the only thing a session actually reads at start — never included it:
3,722 lines, zero handled. This proves the section renders from the queue, is absent
(not crashing) when the queue is missing, and sits before the operator-turn section.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import resume  # noqa: E402

EMPTY_VIEW = {"live": [], "deferred": [], "unclassified": {}}


class TestPendingCompletions(unittest.TestCase):
    def render_with_queue(self, queue_text, max_tokens=3000):
        with tempfile.TemporaryDirectory() as d:
            queue_path = Path(d) / "chrono-queue.md" if queue_text is not None else Path(d) / "missing" / "chrono-queue.md"
            if queue_text is not None:
                queue_path.write_text(queue_text)
            with (
                mock.patch.object(resume, "QUEUE_PATH", queue_path),
                mock.patch.object(resume, "registry_view", return_value=EMPTY_VIEW),
                mock.patch.object(resume, "active_decisions", return_value=[]),
            ):
                return resume.render_capsule(
                    "sess-1", latest_operator_turn="go", max_tokens=max_tokens
                )

    def test_grouped_counts_render_for_two_lines_in_one_namespace_status(self):
        queue = (
            "# Chrono Queue\n"
            "# timestamp | status | namespace/task-id | summary\n"
            "2026-08-16T00:00:00Z | needs_review | coding/TASK-1 | first\n"
            "2026-08-16T00:01:00Z | needs_review | coding/TASK-2 | second\n"
        )
        cap = self.render_with_queue(queue)
        self.assertIn(resume.QUEUE_HEADING, cap)
        self.assertIn("- 2 x coding | needs_review", cap)

    def test_absent_queue_renders_no_heading_and_does_not_raise(self):
        cap = self.render_with_queue(None)
        self.assertNotIn(resume.QUEUE_HEADING, cap)
        self.assertNotIn("Pending completions", cap)

    def test_section_appears_before_latest_operator_instruction(self):
        queue = "2026-08-16T00:00:00Z | needs_review | coding/TASK-1 | first\n"
        cap = self.render_with_queue(queue)
        self.assertIn(resume.QUEUE_HEADING, cap)
        self.assertLess(cap.index(resume.QUEUE_HEADING), cap.index(resume.TURN_HEADING))

    def test_pending_completions_direct_grouping_and_sort_order(self):
        with tempfile.TemporaryDirectory() as d:
            queue_path = Path(d) / "chrono-queue.md"
            queue_path.write_text(
                "# comment line, skipped\n"
                "\n"
                "2026-08-16T00:00:00Z | needs_review | coding/TASK-1 | a\n"
                "2026-08-16T00:01:00Z | needs_review | coding/TASK-2 | b\n"
                "2026-08-16T00:02:00Z | needs_review | coding/TASK-3 | c\n"
                "2026-08-16T00:03:00Z | BLOCKED | security/TASK-4 | d\n"
                "malformed line with no pipes at all\n"
            )
            result = resume.pending_completions(path=queue_path)
        self.assertEqual(
            result,
            [(("coding", "needs_review"), 3), (("security", "BLOCKED"), 1)],
        )

    def test_pending_completions_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "does-not-exist" / "chrono-queue.md"
            self.assertEqual(resume.pending_completions(path=missing), [])

    def test_pending_completions_collapses_under_the_token_bound(self):
        """The section must never break the capsule's hard token bound.

        Fix round 2: a collapsed section still shows its heading plus a
        one-line declared omission (never silently vanishes) — see
        test_resume_canary.py's test_pending_drops_under_the_bound_are_declared
        for the dedicated omission-declaration coverage.
        """
        lines = [
            f"2026-08-16T00:{i:02d}:00Z | needs_review | ns{i}/TASK-{i} | " + ("x" * 80)
            for i in range(60)
        ]
        # 150 tokens comfortably fits the collapsed (declared-omission) form but
        # not the full 60-group listing — the collapse itself must still work.
        cap = self.render_with_queue("\n".join(lines) + "\n", max_tokens=150)
        self.assertLessEqual(len(cap) // 4, 150)
        # the latest operator instruction is never dropped
        self.assertIn("go", cap)

    def test_pending_completions_invalid_utf8_returns_empty_list_not_a_crash(self):
        """A corrupt queue (e.g. raw ANSI/control bytes) must not break the capsule.

        Fix round 2: `read_text(encoding="utf-8")` raises `UnicodeDecodeError`
        (a `ValueError` subclass) on invalid bytes; the prior `except OSError`
        alone did not catch this.
        """
        with tempfile.TemporaryDirectory() as d:
            queue_path = Path(d) / "chrono-queue.md"
            # 0xFF is never valid as a UTF-8 lead byte.
            queue_path.write_bytes(b"2026-08-16T00:00:00Z | needs_review | coding/TASK-1 | \xff\xfe bad bytes\n")
            self.assertEqual(resume.pending_completions(path=queue_path), [])

    def test_pending_completions_invalid_utf8_does_not_break_capsule_render(self):
        with tempfile.TemporaryDirectory() as d:
            queue_path = Path(d) / "chrono-queue.md"
            queue_path.write_bytes(b"\xff\xfe not valid utf-8 at all\n")
            with (
                mock.patch.object(resume, "QUEUE_PATH", queue_path),
                mock.patch.object(resume, "registry_view", return_value=EMPTY_VIEW),
                mock.patch.object(resume, "active_decisions", return_value=[]),
            ):
                cap = resume.render_capsule(
                    "sess-1", latest_operator_turn="go", max_tokens=3000
                )
        self.assertNotIn(resume.QUEUE_HEADING, cap)
        self.assertIn("go", cap)


if __name__ == "__main__":
    unittest.main()
