#!/usr/bin/env python3
"""Entry-point tests for the resume capsule — the wrapper and the read instruction.

The 0210 review rejected library-only coverage twice over: `write_capsule()` preserved
the operator line while `bin/chrono-resume-capsule.sh` overwrote it from a stale
compaction snapshot, and "pull at read" was wired into one launcher branch while the
actual read instruction in `chrono/CLAUDE.md` regenerated nothing. Both defects lived
exactly in the gap between the tested library and the untested entry points, so these
tests go through the real wrapper (subprocess) and the real instruction file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "bin" / "chrono-resume-capsule.sh"


class ActualWrapperPrecedence(unittest.TestCase):
    """Operator-turn precedence must hold through bin/chrono-resume-capsule.sh.

    The 0230 review killed the mtime competition for good: a file's mtime is not
    a causality signal (an exact tie went to the snapshot, and a copied or
    restored file carries a NEWER mtime with OLDER content), so the precedence
    is now timestamp-free — an explicit --latest-turn wins, otherwise a real
    line already in the capsule is kept, and the snapshot only fills a vacuum
    (a missing capsule or the placeholder). These tests include the review's
    own `equal` and `copy_reset` reproductions as regressions.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # The wrapper derives PYTHONPATH from VAULT_ROOT, so the throwaway root
        # must expose the real scripts tree under itself.
        (self.root / "scripts").symlink_to(ROOT / "scripts")
        self.capsule = self.root / "_state" / "chrono" / "resume.md"
        self.snap_dir = self.root / "_state" / "chrono" / "compaction"

    def run_wrapper(self, *args):
        return subprocess.run(
            ["bash", str(WRAPPER), *args],
            env={**os.environ, "VAULT_ROOT": str(self.root)},
            capture_output=True,
            text=True,
        )

    def write_snapshot(self, turn, age_seconds=0):
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        snap = self.snap_dir / "current.json"
        snap.write_text(json.dumps({"latest_turn": turn}))
        if age_seconds:
            past = time.time() - age_seconds
            os.utime(snap, (past, past))

    def test_a_stale_snapshot_never_overwrites_a_newer_capsule_line(self):
        self.write_snapshot("OLDER SNAPSHOT TURN", age_seconds=3600)
        seed = self.run_wrapper("--latest-turn", "NEWER CAPSULE TURN")
        self.assertEqual(seed.returncode, 0, seed.stderr)
        refresh = self.run_wrapper()
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        text = self.capsule.read_text()
        self.assertIn("NEWER CAPSULE TURN", text)
        self.assertNotIn("OLDER SNAPSHOT TURN", text)

    def test_a_newer_snapshot_never_replaces_an_existing_capsule_line(self):
        """The accepted cost of deleting the mtime rule, stated in code.

        A genuinely fresher snapshot used to beat an older capsule line; now the
        capsule line is kept, because no timestamp can prove the snapshot's
        freshness. Compact-recovery therefore only recovers a turn when the
        capsule has none — the honest trade for removing an unprovable ordering.
        """
        seed = self.run_wrapper("--latest-turn", "PRE-COMPACT TURN")
        self.assertEqual(seed.returncode, 0, seed.stderr)
        old = time.time() - 3600
        os.utime(self.capsule, (old, old))
        self.write_snapshot("POST-COMPACT TURN")
        refresh = self.run_wrapper()
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        text = self.capsule.read_text()
        self.assertIn("PRE-COMPACT TURN", text)
        self.assertNotIn("POST-COMPACT TURN", text)

    def test_equal_mtimes_never_let_the_snapshot_replace_the_capsule_line(self):
        """The 0230 review's `equal` probe: an exact mtime tie overwrote the
        causally newer capsule line (`snapshot_mtime >= capsule_mtime`)."""
        seed = self.run_wrapper("--latest-turn", "NEWER CAPSULE TURN")
        self.assertEqual(seed.returncode, 0, seed.stderr)
        self.write_snapshot("OLDER SNAPSHOT TURN")
        tie = time.time()
        os.utime(self.capsule, (tie, tie))
        os.utime(self.snap_dir / "current.json", (tie, tie))
        refresh = self.run_wrapper()
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        text = self.capsule.read_text()
        self.assertIn("NEWER CAPSULE TURN", text)
        self.assertNotIn("OLDER SNAPSHOT TURN", text)

    def test_a_restored_snapshot_with_newer_mtime_and_older_content_never_wins(self):
        """The 0230 review's `copy_reset` probe: a copy or restore refreshes the
        snapshot's mtime without changing its content — mtime is not causality."""
        self.write_snapshot("OLDER SNAPSHOT TURN")
        seed = self.run_wrapper("--latest-turn", "NEWER CAPSULE TURN")
        self.assertEqual(seed.returncode, 0, seed.stderr)
        restored = time.time() + 5
        os.utime(self.snap_dir / "current.json", (restored, restored))
        refresh = self.run_wrapper()
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        text = self.capsule.read_text()
        self.assertIn("NEWER CAPSULE TURN", text)
        self.assertNotIn("OLDER SNAPSHOT TURN", text)

    def test_the_snapshot_fills_a_placeholder_capsule(self):
        """The placeholder counts as "no line recorded": the snapshot still
        fills the vacuum, so the compact-recovery flow it exists for survives."""
        first = self.run_wrapper()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("(none recorded", self.capsule.read_text())
        self.write_snapshot("RECOVERED AFTER COMPACT")
        refresh = self.run_wrapper()
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        self.assertIn("RECOVERED AFTER COMPACT", self.capsule.read_text())

    def test_first_run_with_no_capsule_recovers_the_snapshot_turn(self):
        self.write_snapshot("SNAPSHOT ONLY TURN")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SNAPSHOT ONLY TURN", self.capsule.read_text())

    def test_first_run_with_nothing_records_the_placeholder(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(none recorded", self.capsule.read_text())

    def test_an_explicit_latest_turn_always_wins(self):
        self.write_snapshot("SNAPSHOT TURN")
        result = self.run_wrapper("--latest-turn", "EXPLICIT OPERATOR TURN")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.capsule.read_text()
        self.assertIn("EXPLICIT OPERATOR TURN", text)
        self.assertNotIn("SNAPSHOT TURN", text)


class SessionStartInstructionCoupling(unittest.TestCase):
    """Reading the capsule and regenerating it must be one inseparable step.

    Regeneration wired into one launcher branch is "refresh in one launcher",
    not "pull at read": a bare coordinator CLI never traverses the launcher. The
    only artifact every Chrono session start does traverse is the Start Of
    Session instruction in chrono/CLAUDE.md, so the read instruction there must
    itself regenerate — non-fatally, because a stale capsule must never block a
    session.
    """

    def step_one(self):
        text = (ROOT / "chrono" / "CLAUDE.md").read_text()
        section = text[text.index("## Start Of Session") :]
        match = re.search(r"\n1\.(.*?)\n2\.", section, re.S)
        self.assertIsNotNone(match, "Start Of Session has no numbered step 1")
        return match.group(1)

    def test_the_read_instruction_regenerates_before_reading(self):
        step = self.step_one()
        self.assertIn("chrono-resume-capsule.sh", step)
        self.assertIn("_state/chrono/resume.md", step)
        self.assertLess(
            step.index("chrono-resume-capsule.sh"),
            step.index("_state/chrono/resume.md"),
            "the regenerate command must come before the read",
        )

    def test_the_regeneration_is_instructed_as_non_fatal(self):
        step = self.step_one().lower()
        self.assertIn("stale", step)
        self.assertTrue(
            "non-fatal" in step or "never block" in step,
            "step 1 must say a failed regeneration cannot block the session",
        )


if __name__ == "__main__":
    unittest.main()
