#!/usr/bin/env python3
"""Regression coverage for completion/review/coordination status separation."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import registry_reconciler as rr  # noqa: E402


def _envelope(task_id: str, status: str, body: str = "Done.") -> str:
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        "from: gpt-codex\n"
        "to: chrono\n"
        "type: RESULT\n"
        f"status: {status}\n"
        "---\n\n"
        f"{body}\n"
    )


@contextmanager
def _runtime(root: Path):
    state = root / "_state"
    registry = state / "active-tasks.json"
    patchers = (
        mock.patch.object(rr, "VAULT_ROOT", root),
        mock.patch.object(rr, "STATE_DIR", state),
        mock.patch.object(rr, "REGISTRY_PATH", registry),
        mock.patch.object(rr, "CHRONO_QUEUE_PATH", state / "chrono-queue.md"),
        mock.patch.object(rr, "CHRONO_NOTIFY_LOCKDIR", state / "notify.lockdir"),
        mock.patch.object(
            rr,
            "CHRONO_NOTIFY_RECEIPTS_DIR",
            state / "chrono-notify-receipts",
        ),
        mock.patch.object(rr, "RESPONSE_MIN_AGE", rr.timedelta(seconds=0)),
        mock.patch.object(rr, "nudge_chrono", return_value=True),
        mock.patch.dict(
            os.environ,
            {
                "VAULT_ROOT": str(root),
                rr.TEST_ISOLATION_ENV: "1",
            },
        ),
    )
    with ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        yield state, registry


class StatusVocabularyTests(unittest.TestCase):
    def _reconcile_response(
        self, entry: dict[str, object], status: str, body: str
    ) -> tuple[dict[str, object], str]:
        task_id = "TASK-2026-08-26-status-vocabulary"
        with tempfile.TemporaryDirectory(prefix="status-vocabulary-") as directory:
            root = Path(directory)
            state = root / "_state"
            state.mkdir(parents=True)
            registry = state / "active-tasks.json"
            registry.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
            )
            response = (
                root
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            response.parent.mkdir(parents=True)
            response.write_text(
                _envelope(task_id, status, body), encoding="utf-8"
            )
            with _runtime(root):
                changed, _messages = rr.reconcile(task_id, dry_run=False)
            self.assertGreaterEqual(changed, 1)
            result = json.loads(registry.read_text(encoding="utf-8"))[task_id]
            queue = (state / "chrono-queue.md").read_text(encoding="utf-8")
            return result, queue

    def test_untriggered_needs_review_becomes_complete_plus_coordination(self) -> None:
        entry, queue = self._reconcile_response(
            {
                "status": "in-flight",
                "specialist": "systems-engineer",
                "to_model": "gpt-codex",
                "review_model": "none",
                "mandatory_review": "false",
                "review_triggers": [],
                "compatibility_namespace": "coding",
            },
            "needs_review",
            "Done.\n\n## NEEDS FROM CHRONO\n- Route a bounded follow-up.",
        )
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["worker_reported_status"], "needs_review")
        self.assertIs(entry["coordination_requested"], True)
        self.assertEqual(entry["review_disposition"], "not-required")
        self.assertIn("| complete |", queue)
        self.assertIn(f"| {rr.COORDINATION_REQUESTED} |", queue)
        self.assertNotIn("| needs_review |", queue)

    def test_triggered_needs_review_still_blocks_as_review_required(self) -> None:
        entry, queue = self._reconcile_response(
            {
                "status": "in-flight",
                "specialist": "systems-engineer",
                "to_model": "gpt-codex",
                "review_model": "claude",
                "mandatory_review": "true",
                "review_triggers": ["architecture"],
                "review_class": "standard",
                "compatibility_namespace": "coding",
                "write_scope": ["shared/runtime-control"],
            },
            "needs_review",
            "Done pending the declared architecture review.",
        )
        self.assertEqual(entry["status"], rr.REVIEW_REQUIRED)
        self.assertEqual(entry["worker_reported_status"], "needs_review")
        self.assertNotIn("coordination_requested", entry)
        self.assertIn("REVIEW-REQUIRED", queue)
        self.assertNotIn(rr.COORDINATION_REQUESTED, queue)

    def test_complete_response_can_request_coordination_separately(self) -> None:
        entry, queue = self._reconcile_response(
            {
                "status": "in-flight",
                "specialist": "systems-engineer",
                "to_model": "gpt-codex",
                "review_model": "none",
                "mandatory_review": "false",
                "review_triggers": [],
                "compatibility_namespace": "coding",
            },
            "complete",
            "Done.\n\n## COORDINATION REQUESTED\n- Schedule the downstream canary.",
        )
        self.assertEqual(entry["status"], "complete")
        self.assertIs(entry["coordination_requested"], True)
        self.assertEqual(entry["worker_reported_status"], "complete")
        self.assertIn("Schedule the downstream canary", queue)
        self.assertIn(f"| {rr.COORDINATION_REQUESTED} |", queue)

    def test_legacy_heading_does_not_weaken_needs_human_stop(self) -> None:
        entry, queue = self._reconcile_response(
            {
                "status": "in-flight",
                "specialist": "systems-engineer",
                "to_model": "gpt-codex",
                "review_model": "none",
                "mandatory_review": "false",
                "review_triggers": [],
                "compatibility_namespace": "coding",
            },
            "needs_human",
            "Stopped.\n\n## NEEDS FROM CHRONO\n- Operator must choose the target.",
        )
        self.assertEqual(entry["status"], "needs_human")
        self.assertEqual(entry["worker_reported_status"], "needs_human")
        self.assertNotIn("coordination_requested", entry)
        self.assertIn("| needs_human |", queue)
        self.assertNotIn(rr.COORDINATION_REQUESTED, queue)

    def test_locked_migration_is_dry_run_first_and_reversible(self) -> None:
        target = "TASK-2026-08-26-migrate-target"
        triggered = "TASK-2026-08-26-migrate-triggered"
        human = "TASK-2026-08-26-migrate-human"
        blocked = "TASK-2026-08-26-migrate-blocked"
        original_registry = {
            target: {
                "status": "needs_review",
                "mandatory_review": "false",
                "review_triggers": [],
                "review_model": "none",
                "delivery_generation": 1,
                "reconciled_at": "2026-08-26T00:00:00+00:00",
            },
            triggered: {
                "status": "needs_review",
                "mandatory_review": "true",
                "review_triggers": ["blast_radius"],
                "review_model": "claude",
            },
            human: {
                "status": "needs_human",
                "mandatory_review": "false",
                "review_triggers": [],
            },
            blocked: {
                "status": "blocked",
                "mandatory_review": "false",
                "review_triggers": [],
            },
        }
        original_queue = (
            "# Chrono Queue\n"
            "# timestamp | status | namespace/task-id | summary\n\n"
            f"2026-08-26T00:00:00Z | needs_review | coding/{target} | follow-up owed\n"
            f"2026-08-26T00:00:01Z | needs_review | coding/{triggered} | review owed\n"
            f"2026-08-26T00:00:02Z | needs_human | coding/{human} | decision owed\n"
            f"2026-08-26T00:00:03Z | blocked | coding/{blocked} | blocked\n"
        )
        with tempfile.TemporaryDirectory(prefix="status-migration-") as directory:
            root = Path(directory)
            state = root / "_state"
            state.mkdir(parents=True)
            registry_path = state / "active-tasks.json"
            queue_path = state / "chrono-queue.md"
            registry_path.write_text(
                json.dumps(original_registry, indent=2) + "\n", encoding="utf-8"
            )
            queue_path.write_text(original_queue, encoding="utf-8")

            with _runtime(root):
                with self.assertRaisesRegex(ValueError, "preceding locked --dry-run"):
                    rr.migrate_untriggered_needs_review(dry_run=False)

                dry_run = rr.migrate_untriggered_needs_review(dry_run=True)
                self.assertEqual(dry_run["candidate_count"], 1)
                self.assertEqual(dry_run["queue_entry_count"], 1)
                self.assertEqual(dry_run["preserved_needs_human"], 1)
                self.assertEqual(dry_run["preserved_blocked"], 1)
                self.assertEqual(dry_run["triggered_needs_review"], 1)
                self.assertEqual(
                    json.loads(registry_path.read_text(encoding="utf-8")),
                    original_registry,
                )
                self.assertEqual(queue_path.read_text(encoding="utf-8"), original_queue)

                real_atomic_write = rr.atomic_write
                failed_registry_publish = False

                def fail_once_after_registry_rename(
                    path: Path, content: str
                ) -> None:
                    nonlocal failed_registry_publish
                    real_atomic_write(path, content)
                    if path == registry_path and not failed_registry_publish:
                        failed_registry_publish = True
                        raise OSError("simulated post-rename fsync failure")

                with mock.patch.object(
                    rr, "atomic_write", side_effect=fail_once_after_registry_rename
                ):
                    with self.assertRaisesRegex(
                        rr.RegistryCorruptError, "both files restored"
                    ):
                        rr.migrate_untriggered_needs_review(
                            dry_run=False,
                            apply_plan_sha256=dry_run["plan_sha256"],
                        )
                self.assertEqual(
                    json.loads(registry_path.read_text(encoding="utf-8")),
                    original_registry,
                )
                self.assertEqual(queue_path.read_text(encoding="utf-8"), original_queue)

                # Simulate a hard process death after the queue rename but before
                # the registry rename. The same dry-run hash must resume safely.
                partial_queue = original_queue.replace(
                    f"| needs_review | coding/{target} |",
                    f"| {rr.COORDINATION_REQUESTED} | coding/{target} |",
                )
                queue_path.write_text(partial_queue, encoding="utf-8")

                applied = rr.migrate_untriggered_needs_review(
                    dry_run=False,
                    apply_plan_sha256=dry_run["plan_sha256"],
                )
                self.assertEqual(applied["outcome"], "applied")
                self.assertEqual(applied["partially_published_queue_count"], 1)
                migrated = json.loads(registry_path.read_text(encoding="utf-8"))
                self.assertEqual(migrated[target]["status"], "complete")
                self.assertEqual(
                    migrated[target]["worker_reported_status"], "needs_review"
                )
                self.assertIs(migrated[target]["coordination_requested"], True)
                self.assertEqual(migrated[triggered], original_registry[triggered])
                self.assertEqual(migrated[human], original_registry[human])
                self.assertEqual(migrated[blocked], original_registry[blocked])
                migrated_queue = queue_path.read_text(encoding="utf-8")
                self.assertIn(
                    f"| {rr.COORDINATION_REQUESTED} | coding/{target} |",
                    migrated_queue,
                )
                self.assertIn(
                    f"| needs_review | coding/{triggered} |", migrated_queue
                )

                rollback_dry_run = rr.migrate_untriggered_needs_review(
                    dry_run=True,
                    rollback_migration_id=applied["migration_id"],
                )
                rolled_back = rr.migrate_untriggered_needs_review(
                    dry_run=False,
                    rollback_migration_id=applied["migration_id"],
                    apply_plan_sha256=rollback_dry_run["plan_sha256"],
                )
                self.assertEqual(rolled_back["outcome"], "rolled-back")

            self.assertEqual(
                json.loads(registry_path.read_text(encoding="utf-8")),
                original_registry,
            )
            self.assertEqual(queue_path.read_text(encoding="utf-8"), original_queue)


if __name__ == "__main__":
    unittest.main()
