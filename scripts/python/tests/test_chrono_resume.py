#!/usr/bin/env python3
"""Tests for the bounded, source-tagged Chrono resume capsule (Phase 1, Task 1.5)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import resume  # noqa: E402


class TestChronoResume(unittest.TestCase):
    def test_capsule_is_bounded_and_sourced(self):
        with (
            mock.patch.object(
                resume,
                "registry_view",
                return_value={
                    "live": [
                        {"id": "TASK-9", "state": "blocked", "next_action": "retry"}
                    ],
                    "deferred": [],
                    "unclassified": {},
                },
            ),
            mock.patch.object(
                resume,
                "active_decisions",
                return_value=[
                    {"decision_id": "DEC-abc", "statement": "clean in place"}
                ],
            ),
            # Isolation (fix round 2): without this, pending_completions() reads
            # this HOST's real _state/chrono-queue.md, making the test's outcome
            # depend on whatever happens to be on disk right now.
            mock.patch.object(resume, "pending_completions", return_value=[]),
        ):
            cap = resume.render_capsule(
                "sess-1", latest_operator_turn="write the plan", max_tokens=3000
            )
        self.assertIn("[DEC-abc]", cap)
        self.assertIn("[TASK-9]", cap)
        self.assertIn("write the plan", cap)
        self.assertLessEqual(len(cap) // 4, 3000)

    def test_capsule_truncates_tasks_to_stay_bounded(self):
        with (
            mock.patch.object(resume, "active_decisions", return_value=[]),
            mock.patch.object(
                resume,
                "registry_view",
                return_value={
                    "live": [
                        {
                            "id": f"TASK-{i}",
                            "state": "running",
                            "next_action": "x" * 200,
                        }
                        for i in range(50)
                    ],
                    "deferred": [],
                    "unclassified": {},
                },
            ),
            # Isolation (fix round 2): see the note in the previous test.
            mock.patch.object(resume, "pending_completions", return_value=[]),
        ):
            cap = resume.render_capsule(
                "sess-1", latest_operator_turn="go", max_tokens=200
            )
        self.assertLessEqual(len(cap) // 4, 200)
        # the latest operator instruction is never dropped
        self.assertIn("go", cap)


if __name__ == "__main__":
    unittest.main()
