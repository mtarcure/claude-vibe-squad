#!/usr/bin/env python3
"""Tests for the Chrono decision-authority record (Phase 1, Task 1.2)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import decisions  # noqa: E402


class TestChronoDecisions(unittest.TestCase):
    def test_supersede_folds_to_latest(self):
        with tempfile.TemporaryDirectory() as d:
            decisions.DECISIONS_FILE = Path(d) / "decisions.jsonl"
            d1 = decisions.record("Concurrency cap is 2", "confirmed", ["turn-1"])
            decisions.record(
                "No fixed cap; dynamic gate", "confirmed", ["turn-9"], supersedes=[d1]
            )
            active = [x["statement"] for x in decisions.active_decisions()]
            self.assertIn("No fixed cap; dynamic gate", active)
            self.assertNotIn("Concurrency cap is 2", active)

    def test_confirmed_and_proposed_both_active_until_superseded(self):
        with tempfile.TemporaryDirectory() as d:
            decisions.DECISIONS_FILE = Path(d) / "decisions.jsonl"
            decisions.record("clean in place", "confirmed", ["turn-2"])
            decisions.record("maybe defer phase 9 cleanup", "proposed", ["turn-3"])
            statuses = {x["status"] for x in decisions.active_decisions()}
            self.assertEqual(statuses, {"confirmed", "proposed"})


if __name__ == "__main__":
    unittest.main()
