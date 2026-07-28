#!/usr/bin/env python3
"""Tests for the Chrono compaction policy + snapshot helpers (Phase 1, Task 1.3)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import compaction  # noqa: E402


class TestChronoCompaction(unittest.TestCase):
    def test_should_compact_blocks_on_inflight(self):
        r = compaction.should_compact(token_estimate=180000, in_flight=["T-1"])
        self.assertFalse(r["compact"])
        self.assertIn("T-1", r["blockers"])

    def test_should_compact_fires_over_threshold_when_clear(self):
        r = compaction.should_compact(token_estimate=180000, in_flight=[])
        self.assertTrue(r["compact"])
        self.assertEqual(r["blockers"], [])

    def test_should_compact_quiet_below_threshold(self):
        r = compaction.should_compact(token_estimate=50000, in_flight=[])
        self.assertFalse(r["compact"])

    def test_snapshot_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            compaction.SNAP_DIR = Path(d)
            compaction.snapshot("sess-1", {"next_action": "resume phase 2"})
            self.assertEqual(
                compaction.recover("sess-1")["next_action"], "resume phase 2"
            )

    def test_recover_missing_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            compaction.SNAP_DIR = Path(d)
            self.assertEqual(compaction.recover("nope"), {})


if __name__ == "__main__":
    unittest.main()
