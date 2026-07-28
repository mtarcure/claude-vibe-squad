#!/usr/bin/env python3
"""Resume canary — Phase 1 acceptance gate.

Proves that a confirmed decision, an open task, a superseding decision, and the exact
recent operator request all survive a simulated /compact + restart, recovered ONLY from
the append-only journals + snapshot (no history replay).
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import registry, decisions, compaction, resume  # noqa: E402


class TestResumeCanary(unittest.TestCase):
    def test_decision_task_supersession_survive_compact(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            decisions.DECISIONS_FILE = base / "decisions.jsonl"
            compaction.SNAP_DIR = base / "snap"
            registry.TASKS_DIR = base / "tasks"
            (base / "tasks").mkdir()
            (base / "tasks" / "active.json").write_text(
                '[{"id": "TASK-9", "state": "blocked", "next_action": "retry phase 2"}]'
            )

            # confirm a decision, then supersede it (mirrors this very session)
            d1 = decisions.record("cap is 2", "confirmed", ["turn-1"])
            decisions.record(
                "no fixed cap; dynamic gate", "confirmed", ["turn-9"], supersedes=[d1]
            )

            # externalize load-bearing state (what compact-now does before /compact)
            compaction.snapshot(
                "sess-1",
                {"next_action": "resume phase 2", "latest_turn": "write the plan"},
            )

            # --- simulate compact + restart: recover ONLY from files ---
            recovered = compaction.recover("sess-1")
            active = [x["statement"] for x in decisions.active_decisions()]
            live_tasks = [t["id"] for t in registry.load_active()]

            self.assertEqual(recovered["next_action"], "resume phase 2")
            self.assertIn("no fixed cap; dynamic gate", active)
            self.assertNotIn("cap is 2", active)
            self.assertIn("TASK-9", live_tasks)

            # the regenerated capsule reflects all of it, source-tagged
            cap = resume.render_capsule("sess-1", recovered["latest_turn"])
            self.assertIn("no fixed cap; dynamic gate", cap)
            self.assertIn("TASK-9", cap)
            self.assertIn("write the plan", cap)


if __name__ == "__main__":
    unittest.main()
