#!/usr/bin/env python3
"""F12b: the host-global Chrono page is withheld for non-live tasks.

Every other reconciler sink is scoped by VAULT_ROOT; the tmux nudge is not. A
sweep over a throwaway VAULT_ROOT (hermetic tests, reconcile-selftest) must not
page the operator's real Chrono, while a genuinely registered task still must.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import registry_reconciler as rr  # noqa: E402


LIVE_TASK = "TASK-2026-07-27-0001-live"
FIXTURE_TASK = "TASK-2026-07-26-0004-r2unsafe"


class NotifyGuardTest(unittest.TestCase):
    """One canonical host registry, one hermetic vault reconciling fixtures."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        canonical = root / "host-vault"
        (canonical / "_state").mkdir(parents=True)
        (canonical / "_state" / "active-tasks.json").write_text(
            json.dumps({LIVE_TASK: {"status": "in-flight"}}), encoding="utf-8"
        )

        # A separate vault standing in for the hermetic fixture run: it has its
        # own registry holding only the fixture task.
        hermetic = root / "throwaway-vault"
        (hermetic / "_state").mkdir(parents=True)
        self.hermetic_registry = hermetic / "_state" / "active-tasks.json"
        self.hermetic_registry.write_text(
            json.dumps({FIXTURE_TASK: {"status": "in-flight"}}), encoding="utf-8"
        )
        self.queue_path = hermetic / "_state" / "chrono-queue.md"

        self.enterContext(
            mock.patch.dict(
                rr.os.environ, {"CHRONO_CANONICAL_VAULT_ROOT": str(canonical)}
            )
        )
        self.enterContext(mock.patch.object(rr, "REGISTRY_PATH", self.hermetic_registry))
        self.enterContext(mock.patch.object(rr, "CHRONO_QUEUE_PATH", self.queue_path))
        self.nudge = self.enterContext(
            mock.patch.object(rr, "nudge_chrono", return_value=True)
        )

    def emit(self, task_id: str) -> bool:
        return rr.emit_event(
            "complete",
            f"coding/{task_id}",
            "summary",
            f"complete: {task_id} response landed. Read and surface now.",
        )

    def test_unregistered_task_does_not_page_but_still_queues(self):
        """(a) A task absent from the canonical registry never reaches tmux."""
        self.assertFalse(rr.registered_in_canonical_registry(FIXTURE_TASK))
        self.assertFalse(self.emit(FIXTURE_TASK))
        self.nudge.assert_not_called()
        # Durable-first is preserved: the queue append is not gated.
        self.assertIn(FIXTURE_TASK, self.queue_path.read_text(encoding="utf-8"))

    def test_registered_task_still_pages(self):
        """(b) A genuine registered in-flight task landing still pages."""
        self.assertTrue(rr.registered_in_canonical_registry(LIVE_TASK))
        self.assertTrue(self.emit(LIVE_TASK))
        self.assertEqual(self.nudge.call_count, 1)

    def test_reconciling_the_canonical_registry_itself_always_pages(self):
        """The live sweep reads the canonical registry, so membership holds."""
        canonical_registry = (
            rr.canonical_vault_root() / "_state" / "active-tasks.json"
        )
        with mock.patch.object(rr, "REGISTRY_PATH", canonical_registry):
            self.assertTrue(rr.registered_in_canonical_registry("TASK-ANY-ID"))

    def test_unreadable_canonical_registry_fails_open(self):
        """No readable canonical registry is absence of evidence -> stay loud."""
        with mock.patch.dict(
            rr.os.environ, {"CHRONO_CANONICAL_VAULT_ROOT": str(Path(tempfile.gettempdir()) / "no-such-vault-f12b")}
        ):
            self.assertTrue(rr.registered_in_canonical_registry(FIXTURE_TASK))


if __name__ == "__main__":
    unittest.main()
