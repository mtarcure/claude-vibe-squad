from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402


class DispatchStatusCoercionTests(unittest.TestCase):
    def test_failure_shaped_and_unmappable_statuses_fail_toward_visibility(
        self,
    ) -> None:
        worker_statuses = (
            "zzzz-unmappable",
            "incomplete",
            "not done",
            "abandoned",
            "broken",
            "unable to complete",
            "could not complete",
            "out of tokens",
            "token limit exceeded",
        )
        for worker_status in worker_statuses:
            with self.subTest(worker_status=worker_status):
                self.assertEqual(dcb._coerce_status(worker_status), "needs_review")

    def test_canonical_status_controls_pass_through(self) -> None:
        controls = (
            ("complete", "complete"),
            ("completed", "completed"),
            ("needs_review", "needs_review"),
            ("needs_human", "needs_human"),
            ("blocked", "blocked"),
        )
        for worker_status, expected in controls:
            with self.subTest(worker_status=worker_status):
                self.assertEqual(dcb._coerce_status(worker_status), expected)


if __name__ == "__main__":
    unittest.main()
