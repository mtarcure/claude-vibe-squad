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
    def test_should_compact_is_gone(self):
        """The threshold predicate was deleted 2026-08-31, not renamed.

        It had no production caller, no way to obtain its `token_estimate`
        argument (the repo has no token-counting code at all), and a threshold
        that contradicted shared/lifecycle.md. The rule now lives once, in prose,
        in shared/lifecycle.md § 8. Reintroducing a code copy would recreate the
        two-sources-of-truth problem that Hard Rule 10 forbids.
        """
        self.assertFalse(
            hasattr(compaction, "should_compact"),
            "should_compact() is back. The compaction threshold belongs in "
            "shared/lifecycle.md, read by judgment -- not duplicated in code "
            "where it can drift from the prose rule again.",
        )

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
