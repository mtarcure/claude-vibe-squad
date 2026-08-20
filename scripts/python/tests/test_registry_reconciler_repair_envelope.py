#!/usr/bin/env python3
"""Regression tests for --repair-envelope (interrupted-bridge settlement).

The 2026-08-18 incident: the output bridge published the raw worker response
(artifact write) and then refused its own envelope write at the same aliased
path, so the canonical outbox file existed WITHOUT the delivery pins that
`landed_response` requires. Reviewed, approved work could not be settled
through `--settle-review` ("task has no landed response") and the registry
recorded it `blocked`. `repair_promoted_envelope` completes the interrupted
promotion from registry-held pins, never from the file being repaired.
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import registry_reconciler as reconciler  # noqa: E402


TASK_ID = "TASK-2026-08-18-9002-repair"
ATTEMPT_ID = "d-" + "b" * 32
OUTBOX_RELATIVE = f"departments/coding/outbox/{TASK_ID}-response.md"


def _raw_response_text(task_id: str = TASK_ID) -> str:
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        "from: gpt-codex\n"
        "to: chrono\n"
        "type: RESULT\n"
        "status: complete\n"
        f"return_artifact: departments/coding/outbox/{task_id}-response.md\n"
        "---\n\n"
        "Finished work whose envelope promotion was interrupted.\n"
    )


class RepairPromotedEnvelopeTests(unittest.TestCase):
    @staticmethod
    def _entry(**extra: object) -> dict[str, object]:
        entry: dict[str, object] = {
            "status": "blocked",
            "to_model": "gpt-codex",
            "compatibility_namespace": "coding",
            "return_artifact": OUTBOX_RELATIVE,
            "delivery_attempt_id": ATTEMPT_ID,
            "delivery_generation": 1,
        }
        entry.update(extra)
        return entry

    @staticmethod
    @contextmanager
    def _patch_runtime(root: Path):
        state = root / "_state"
        state.mkdir(parents=True, exist_ok=True)
        registry_path = state / "active-tasks.json"
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry_path),
            mock.patch.object(
                reconciler, "CHRONO_QUEUE_PATH", state / "chrono-queue.md"
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_LOCKDIR",
                state / "chrono-notify.lockdir",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                state / "chrono-notify-receipts",
            ),
            mock.patch.object(
                reconciler,
                "RESPONSE_MIN_AGE",
                reconciler.timedelta(seconds=0),
            ),
            mock.patch.dict(
                "os.environ",
                {reconciler.TEST_ISOLATION_ENV: "1"},
            ),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield registry_path

    def _stage(self, root: Path, registry_path: Path, entry: dict[str, object]) -> Path:
        registry_path.write_text(
            json.dumps({TASK_ID: entry}, indent=2) + "\n", encoding="utf-8"
        )
        response = root / OUTBOX_RELATIVE
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text(_raw_response_text(), encoding="utf-8")
        return response

    def test_repair_restores_pins_and_reopens_blocked_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._patch_runtime(root) as registry_path:
                response = self._stage(root, registry_path, self._entry())
                self.assertTrue(reconciler.repair_promoted_envelope(TASK_ID))

                repaired = response.read_text(encoding="utf-8")
                self.assertIn(f"delivery_attempt_id: {ATTEMPT_ID}\n", repaired)
                self.assertIn("delivery_generation: 1\n", repaired)
                self.assertIn("status: complete\n", repaired)
                self.assertIn(
                    "Finished work whose envelope promotion was interrupted.",
                    repaired,
                )

                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                entry = registry[TASK_ID]
                self.assertEqual(entry["status"], "needs_review")
                self.assertEqual(entry["envelope_repaired_by"], "chrono-explicit")
                self.assertEqual(entry["envelope_repaired_from_status"], "blocked")

                # The repaired envelope now LANDS for settlement purposes.
                landed, status = reconciler.landed_response(
                    TASK_ID,
                    reconciler.response_candidates(TASK_ID, entry, "v2"),
                    "v2",
                    entry,
                )
                self.assertEqual(landed, response)
                self.assertEqual(status, "complete")

                # Idempotent: a second repair changes nothing.
                self.assertFalse(reconciler.repair_promoted_envelope(TASK_ID))

    def test_repair_refuses_another_tasks_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._patch_runtime(root) as registry_path:
                response = self._stage(root, registry_path, self._entry())
                response.write_text(
                    _raw_response_text("TASK-2026-08-18-9999-other"),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    ValueError, "another task's identity"
                ):
                    reconciler.repair_promoted_envelope(TASK_ID)

    def test_repair_refuses_a_blocked_stub(self) -> None:
        # A genuinely failed task holds the controller stub, which does not
        # parse as an envelope -- it cannot be "repaired" into a completion.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._patch_runtime(root) as registry_path:
                response = self._stage(root, registry_path, self._entry())
                response.write_text(
                    "blocked\n\n"
                    f"# Board dispatch blocked — {TASK_ID}\n\n"
                    "Controller reason: lane launch failed\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    ValueError, "not a repairable envelope"
                ):
                    reconciler.repair_promoted_envelope(TASK_ID)

    def test_repair_refuses_without_delivery_fence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._patch_runtime(root) as registry_path:
                entry = self._entry()
                entry.pop("delivery_attempt_id")
                self._stage(root, registry_path, entry)
                with self.assertRaisesRegex(
                    ValueError, "no delivery fence"
                ):
                    reconciler.repair_promoted_envelope(TASK_ID)

    def test_repair_refuses_settled_complete_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self._patch_runtime(root) as registry_path:
                self._stage(root, registry_path, self._entry(status="complete"))
                with self.assertRaisesRegex(
                    ValueError, "already settled complete"
                ):
                    reconciler.repair_promoted_envelope(TASK_ID)


if __name__ == "__main__":
    unittest.main()
