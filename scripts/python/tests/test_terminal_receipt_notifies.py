#!/usr/bin/env python3
"""A terminal board receipt must produce exactly one operator event.

Regression coverage for the terminal-receipt branch of ``reconcile()``
(registry_reconciler.py ~3218-3243): a registry entry whose status is
*already* ``blocked``/``complete``/``completed`` and which resolves a
matching terminal board receipt on re-reconcile must emit exactly one
``events`` entry -- either REVIEW-REQUIRED (mandatory cross-family review
still pending) or AUTO-CLOSED (no review pending) -- so the entry gets a
durable chrono-queue record and a gated nudge via ``emit_event``. Before this
fix, both arms of that branch appended only to ``messages`` and then
``continue``'d, reaching neither ``emit_event`` nor ``append_chrono_queue``.

The lifecycle now also covers the earlier in-flight ingest pass.  A receipt
that first settles the registry and is auto-closed on the following sweep must
not page once for each state.  Coordination that is discovered with the same
receipt is context for that one terminal event, not a second operator page.
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
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

import registry_reconciler as rr  # noqa: E402


@contextmanager
def _patch_runtime(root: Path, state: Path, registry_path: Path):
    patchers = (
        mock.patch.object(rr, "VAULT_ROOT", root),
        mock.patch.object(rr, "STATE_DIR", state),
        mock.patch.object(rr, "REGISTRY_PATH", registry_path),
        mock.patch.object(rr, "CHRONO_QUEUE_PATH", state / "chrono-queue.md"),
        mock.patch.object(
            rr, "CHRONO_NOTIFY_LOCKDIR", state / "chrono-notify.lockdir"
        ),
        mock.patch.object(
            rr,
            "CHRONO_NOTIFY_RECEIPTS_DIR",
            state / "chrono-notify-receipts",
        ),
        mock.patch.object(rr, "RESPONSE_MIN_AGE", rr.timedelta(seconds=0)),
        mock.patch.dict("os.environ", {rr.TEST_ISOLATION_ENV: "1"}),
    )
    with ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        yield


def _terminal_entry(attempt_id: str, generation: int = 1) -> dict[str, object]:
    return {
        "status": "in-flight",
        "specialist": "site-reliability-engineer",
        "to_model": "gpt-codex",
        "compatibility_namespace": "coding",
        "return_artifact": "_state/consults/result.md",
        "write_scope": ["shared/some-scope"],
        "delivery_attempt_id": attempt_id,
        "delivery_generation": generation,
        "delivery_state": "in-progress",
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
    }


@contextmanager
def _terminal_lifecycles(
    specifications: dict[str, tuple[str, str, int]],
):
    """Yield a hermetic registry plus captured operator-facing events."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "_state"
        registry_path = state / "active-tasks.json"
        board_dir = state / "board-dispatch"
        board_dir.mkdir(parents=True)
        registry = {
            task_id: _terminal_entry(attempt_id, generation)
            for task_id, (_raw_status, attempt_id, generation) in specifications.items()
        }
        registry_path.write_text(
            json.dumps(registry) + "\n", encoding="utf-8"
        )
        for task_id, (raw_status, attempt_id, generation) in specifications.items():
            receipt_path = board_dir / f"{task_id}.{attempt_id}.receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "status": raw_status,
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "generation": generation,
                        "reason": f"fixture terminal outcome {raw_status}",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

        captured: list[tuple[str, str, str, str]] = []
        with _patch_runtime(root, state, registry_path):
            with mock.patch.object(
                rr,
                "emit_event",
                side_effect=lambda *args: captured.append(args) or True,
            ):
                yield registry_path, board_dir, captured


@contextmanager
def _promoted_responses(
    specifications: dict[str, tuple[str, str]],
):
    """Yield hermetic promoted responses plus captured operator events."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "_state"
        registry_path = state / "active-tasks.json"
        outbox = root / "departments" / "coding" / "outbox"
        outbox.mkdir(parents=True)
        state.mkdir(parents=True)
        registry = {
            task_id: {
                "status": "in-flight",
                "specialist": "site-reliability-engineer",
                "to_model": "gpt-codex",
                "compatibility_namespace": "coding",
                "dispatched_at": "2020-01-01T00:00:00+00:00",
            }
            for task_id in specifications
        }
        registry_path.write_text(
            json.dumps(registry) + "\n", encoding="utf-8"
        )
        responses: dict[str, Path] = {}
        for task_id, (status, body) in specifications.items():
            response = outbox / f"{task_id}-response.md"
            response.write_text(
                f"---\nstatus: {status}\n---\n\n{body}\n", encoding="utf-8"
            )
            responses[task_id] = response

        captured: list[tuple[str, str, str, str]] = []
        with _patch_runtime(root, state, registry_path):
            with mock.patch.object(
                rr,
                "emit_event",
                side_effect=lambda *args: captured.append(args) or True,
            ):
                yield registry_path, responses, captured


class TerminalReceiptNotifies(unittest.TestCase):
    def _reconcile_one_terminal_receipt(self, pending: bool) -> list[tuple]:
        task_id = "TASK-2026-08-16-0001-terminal-receipt-notify"
        attempt_id = "d-" + "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            board_dir = state / "board-dispatch"
            board_dir.mkdir(parents=True)

            entry: dict[str, object] = {
                # Already-terminal status: this is the re-reconcile shape
                # that hits registry_reconciler.py:3188's
                # `current_status in {"blocked", "complete", "completed"}`
                # gate -- a task settled to a terminal status by an earlier
                # pass that still needs its terminal-receipt bookkeeping
                # (mark_delivery_terminal / terminal_receipt_path / the
                # review-vs-close decision) finished.
                "status": "blocked",
                "specialist": "sol",
                "to_model": "gpt-codex",
                "compatibility_namespace": "coding",
                "return_artifact": "_state/consults/result.md",
                "write_scope": ["shared/some-scope"],
                "delivery_attempt_id": attempt_id,
                "delivery_generation": 1,
                "delivery_state": "in-progress",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }
            if pending:
                # mandatory_review "true" with a review_model in a distinct
                # family from to_model, and no review_class set, holds the
                # task for review (cross_family_review_pending refuses an
                # unreadable review_class rather than defaulting it) --
                # the REVIEW-REQUIRED arm.
                entry["mandatory_review"] = "true"
                entry["review_model"] = "gemini"

            registry_path.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
            )
            receipt_path = board_dir / f"{task_id}.{attempt_id}.receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "reason": "completion prevalidation failed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            captured: list[tuple] = []
            with _patch_runtime(root, state, registry_path):
                with mock.patch.object(
                    rr,
                    "emit_event",
                    side_effect=lambda *a: captured.append(a) or True,
                ):
                    rr.reconcile(task_id, dry_run=False)
            return captured

    def test_review_required_terminal_receipt_emits_one_event(self) -> None:
        captured = self._reconcile_one_terminal_receipt(pending=True)
        self.assertEqual(
            len(captured), 1, "review-required terminal receipt emitted no event"
        )
        status, task_ref, _summary, _nudge = captured[0]
        self.assertEqual(status, "REVIEW-REQUIRED")
        self.assertIn("/", task_ref)

    def test_auto_closed_terminal_receipt_emits_one_event(self) -> None:
        captured = self._reconcile_one_terminal_receipt(pending=False)
        self.assertEqual(
            len(captured), 1, "auto-closed terminal receipt emitted no event"
        )
        self.assertEqual(captured[0][0], "AUTO-CLOSED")

    def test_receipt_ingest_and_auto_close_emit_one_combined_event(self) -> None:
        """Canary: one receipt stays one event across all lifecycle sweeps."""

        task_id = "TASK-2026-08-26-1035-terminal-receipt-canary"
        attempt_id = "d-" + "c" * 32
        with _terminal_lifecycles(
            {task_id: ("failed", attempt_id, 1)}
        ) as (registry_path, _board_dir, captured):
            rr.reconcile(task_id, dry_run=False)
            first = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(first["status"], "blocked")

            rr.reconcile(task_id, dry_run=False)
            rr.reconcile(task_id, dry_run=False)
            closed = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]

        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["closed_from_status"], "blocked")
        self.assertEqual(len(captured), 1, captured)
        status, task_ref, summary, nudge = captured[0]
        self.assertEqual(status, "AUTO-CLOSED")
        self.assertTrue(task_ref.endswith(task_id), task_ref)
        self.assertIn("failed", summary)
        self.assertIn("closed", nudge.lower())
        self.assertIn("failed", nudge)

    def test_terminal_receipt_coalesces_simultaneous_coordination(self) -> None:
        task_id = "TASK-2026-08-26-1035-terminal-coordination"
        attempt_id = "d-" + "d" * 32
        with _terminal_lifecycles(
            {task_id: ("needs_review", attempt_id, 1)}
        ) as (_registry_path, _board_dir, captured):
            rr.reconcile(task_id, dry_run=False)
            rr.reconcile(task_id, dry_run=False)

        self.assertEqual(len(captured), 1, captured)
        status, _task_ref, summary, nudge = captured[0]
        self.assertEqual(status, "complete")
        self.assertIn("needs_review", summary)
        self.assertIn("coordination requested", summary.lower())
        self.assertIn("coordination requested", nudge.lower())

    def test_distinct_tasks_each_emit_a_terminal_event(self) -> None:
        first_task = "TASK-2026-08-26-1035-terminal-positive-a"
        second_task = "TASK-2026-08-26-1035-terminal-positive-b"
        specifications = {
            first_task: ("failed", "d-" + "e" * 32, 1),
            second_task: ("failed", "d-" + "f" * 32, 1),
        }
        with _terminal_lifecycles(specifications) as (
            _registry_path,
            _board_dir,
            captured,
        ):
            rr.reconcile(None, dry_run=False)
            rr.reconcile(None, dry_run=False)
            rr.reconcile(None, dry_run=False)

        self.assertEqual(len(captured), 2, captured)
        self.assertEqual(
            {event[1].rsplit("/", 1)[-1] for event in captured},
            {first_task, second_task},
        )

    def test_same_task_real_state_change_still_emits(self) -> None:
        task_id = "TASK-2026-08-26-1035-terminal-positive-state-change"
        first_attempt = "d-" + "1" * 32
        with _terminal_lifecycles(
            {task_id: ("failed", first_attempt, 1)}
        ) as (registry_path, board_dir, captured):
            rr.reconcile(task_id, dry_run=False)
            rr.reconcile(task_id, dry_run=False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = registry[task_id]
            second_attempt = "d-" + "2" * 32
            entry.update(
                {
                    "status": "in-flight",
                    "delivery_attempt_id": second_attempt,
                    "delivery_generation": 2,
                    "delivery_state": "in-progress",
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            registry_path.write_text(
                json.dumps(registry) + "\n", encoding="utf-8"
            )
            (board_dir / f"{task_id}.{second_attempt}.receipt.json").write_text(
                json.dumps(
                    {
                        "status": "cancelled",
                        "task_id": task_id,
                        "attempt_id": second_attempt,
                        "generation": 2,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rr.reconcile(task_id, dry_run=False)
            rr.reconcile(task_id, dry_run=False)

        self.assertEqual(len(captured), 2, captured)
        self.assertEqual([event[0] for event in captured], ["AUTO-CLOSED", "cancelled"])


class PromotedResponseNotifies(unittest.TestCase):
    def test_promoted_response_coalesces_simultaneous_coordination(self) -> None:
        """Canary: completion plus coordination is one operator event."""

        task_id = "TASK-2026-08-26-1420-promoted-canary"
        with _promoted_responses(
            {task_id: ("needs_review", "Promoted work finished.")}
        ) as (registry_path, _responses, captured):
            _changed, messages = rr.reconcile(task_id, dry_run=False)
            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]

        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["notification_state"], "complete")
        self.assertEqual(
            entry["coordination_notification_state"], rr.COORDINATION_REQUESTED
        )
        self.assertEqual(len(captured), 1, captured)
        status, task_ref, summary, nudge = captured[0]
        self.assertEqual(status, "complete")
        self.assertTrue(task_ref.endswith(task_id), task_ref)
        self.assertIn("Promoted work finished.", summary)
        self.assertIn("coordination requested", summary.lower())
        self.assertIn("complete", nudge.lower())
        self.assertIn("coordination requested", nudge.lower())
        self.assertIn(
            f"chrono-queue appended coding/{task_id} -> {rr.COORDINATION_REQUESTED}",
            messages,
        )

    def test_distinct_promoted_tasks_each_emit_an_event(self) -> None:
        first_task = "TASK-2026-08-26-1420-promoted-positive-a"
        second_task = "TASK-2026-08-26-1420-promoted-positive-b"
        with _promoted_responses(
            {
                first_task: ("needs_review", "First promoted response."),
                second_task: ("needs_review", "Second promoted response."),
            }
        ) as (_registry_path, _responses, captured):
            rr.reconcile(None, dry_run=False)

        self.assertEqual(len(captured), 2, captured)
        self.assertEqual(
            {event[1].rsplit("/", 1)[-1] for event in captured},
            {first_task, second_task},
        )

    def test_direct_helper_fallback_emits_coordination(self) -> None:
        """Exercise the helper fallback without promising live reachability.

        ``reconcile()`` cannot make this second same-generation call: each
        production call site transitions its entry out of that site's re-entry
        condition after the first call. This direct control proves only that the
        helper retains a safe fallback if a future caller gains such a path.
        """
        task_id = "TASK-2026-08-26-1420-promoted-positive-later"
        entry: dict[str, object] = {}
        captured: list[tuple[str, str, str, str]] = []
        now = datetime.now(timezone.utc)
        rr.append_terminal_event(
            captured,
            entry,
            task_id,
            "coding",
            now,
            "complete",
            "Initial promoted completion.",
            f"complete: {task_id} response landed.",
        )
        self.assertEqual(len(captured), 1, captured)

        entry["coordination_requested"] = True
        entry["coordination_request_summary"] = (
            "Route the genuinely later follow-up."
        )
        rr.append_terminal_event(
            captured,
            entry,
            task_id,
            "coding",
            now,
            "complete",
            "Initial promoted completion.",
            f"complete: {task_id} response landed.",
        )

        self.assertEqual(len(captured), 2, captured)
        self.assertEqual(
            [event[0] for event in captured],
            ["complete", rr.COORDINATION_REQUESTED],
        )
        self.assertIn("genuinely later follow-up", captured[1][2])


if __name__ == "__main__":
    unittest.main()
