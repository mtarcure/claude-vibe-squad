#!/usr/bin/env python3
"""Tests for the bounded Chrono active-task registry (Phase 1, Task 1.1)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import registry  # noqa: E402


class TestChronoRegistry(unittest.TestCase):
    def test_load_active_excludes_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            registry.TASKS_DIR = Path(d)
            (Path(d) / "active.json").write_text(
                json.dumps(
                    [
                        {"id": "T-1", "state": "running"},
                        {"id": "T-2", "state": "completed"},
                    ]
                )
            )
            active = registry.load_active()
            self.assertEqual([t["id"] for t in active], ["T-1"])

    def test_migrate_from_legacy_keeps_only_nonterminal(self):
        with tempfile.TemporaryDirectory() as d:
            legacy = Path(d) / "active-tasks.json"
            legacy.write_text(
                json.dumps(
                    {
                        "TASK-A": {"status": "complete", "specialist": "x"},
                        "TASK-B": {"status": "blocked", "specialist": "y"},
                        "TASK-C": {"status": "review-required", "specialist": "z"},
                        "TASK-D": {"status": "superseded", "specialist": "w"},
                    }
                )
            )
            migrated = registry.migrate_from_legacy(str(legacy))
            self.assertEqual({m["id"] for m in migrated}, {"TASK-B", "TASK-C"})
            self.assertTrue(all("next_action" in m for m in migrated))

    def test_archive_moves_terminal_out_of_active(self):
        with tempfile.TemporaryDirectory() as d:
            registry.TASKS_DIR = Path(d)
            (Path(d) / "active.json").write_text(
                json.dumps(
                    [
                        {"id": "T-1", "state": "running"},
                        {"id": "T-2", "state": "completed"},
                    ]
                )
            )
            moved = registry.archive_terminal("2026-07-23T00:00:00Z")
            self.assertEqual(moved, 1)
            remaining = json.loads((Path(d) / "active.json").read_text())
            self.assertEqual([t["id"] for t in remaining], ["T-1"])
            archive = (Path(d) / "archive" / "2026-07.jsonl").read_text().strip()
            self.assertIn("T-2", archive)


if __name__ == "__main__":
    unittest.main()
