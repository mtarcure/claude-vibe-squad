#!/usr/bin/env python3
"""Admission wiring for phase-derived plan bindings and plan authority."""

import json
from pathlib import Path
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = REPO_ROOT / "bin" / "send-task.sh"
BINDING_HELPER = REPO_ROOT / "scripts" / "python" / "plan_item_binding.py"


class PhaseAdmissionCLITests(unittest.TestCase):
    """Exercise the same helper invocation that the dispatcher consumes."""

    def _derive(self, phase: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(BINDING_HELPER),
                "declare",
                "--json",
                "[]",
                f"--phase={phase}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_packet_with_detailed_phase_dispatches_bound(self):
        result = self._derive("P13.52")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["P13.52"])

    def test_packet_with_free_form_phase_is_rejected_at_admission(self):
        for phase in ("B1", "--help"):
            with self.subTest(phase=phase):
                result = self._derive(phase)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid phase plan item id", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_bare_or_none_phase_dispatches_unbound_without_failure(self):
        for phase in ("P13", "none"):
            with self.subTest(phase=phase):
                result = self._derive(phase)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [])


class DispatcherWiringTests(unittest.TestCase):
    """Behavior lives in Python; these assertions pin the shell to that seam."""

    @classmethod
    def setUpClass(cls):
        cls.source = SEND_TASK.read_text(encoding="utf-8")

    def test_dispatcher_reads_phase_and_branches_on_explicit_field_presence(self):
        self.assertIn('PHASE=$(task_frontmatter_field "phase")', self.source)
        self.assertIn('task_frontmatter_has_field "plan_item_ids"', self.source)
        self.assertIn('PLAN_ITEM_PHASE_ARGS=(--phase="$PHASE")', self.source)
        self.assertIn('"${PLAN_ITEM_PHASE_ARGS[@]}"', self.source)


if __name__ == "__main__":
    unittest.main()
