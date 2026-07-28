from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import index as vault_index  # noqa: E402
import lifecycle  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-lifecycle-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "lifecycle-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _record(self, token: str, *, status: str = "candidate") -> dict:
        return notes.record(
            "finding",
            {
                "title": f"{token} lifecycle finding",
                "body": f"The {token} body is canonical markdown.",
                "target": "push-chain",
                "component": "executor",
                "attack_class": "lifecycle",
                "status": status,
                "keywords": ["lifecycle"],
                "source_task": "TASK-lifecycle-fixture",
            },
        )

    @property
    def db_path(self) -> Path:
        return self.vault_root / "index" / "kg.db"

    def test_get_note_returns_full_frontmatter_and_body(self) -> None:
        recorded = self._record("GetNoteToken", status="verified")

        note = lifecycle.get_note(recorded["id"])

        self.assertEqual(note["id"], recorded["id"])
        self.assertEqual(note["type"], "finding")
        self.assertEqual(note["status"], "verified")
        self.assertEqual(note["revision"], 1)
        self.assertEqual(note["keywords"], ["lifecycle"])
        self.assertEqual(note["body"], "The GetNoteToken body is canonical markdown.\n")

    def test_stale_revision_and_unknown_status_are_rejected_without_change(self) -> None:
        recorded = self._record("CasToken")

        with self.assertRaises(lifecycle.RevisionConflict):
            lifecycle.set_status(
                recorded["id"],
                "verified",
                "reviewed evidence",
                expected_revision=2,
            )
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.set_status(
                recorded["id"],
                "unknown",
                "invalid transition",
                expected_revision=1,
            )

        unchanged = lifecycle.get_note(recorded["id"])
        self.assertEqual(unchanged["status"], "candidate")
        self.assertEqual(unchanged["revision"], 1)

    def test_supersede_updates_both_notes_and_default_recall(self) -> None:
        original = self._record("SupersedeToken")
        replacement = self._record("ReplacementToken", status="verified")

        result = lifecycle.set_status(
            original["id"],
            "superseded",
            "replaced by stronger evidence",
            supersedes=replacement["id"],
            expected_revision=1,
        )

        old_note = lifecycle.get_note(original["id"])
        new_note = lifecycle.get_note(replacement["id"])
        self.assertEqual(result["id"], original["id"])
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(result["revision"], 2)
        self.assertEqual(old_note["superseded_by"], replacement["id"])
        self.assertIn(original["id"], new_note["supersedes"])
        self.assertEqual(new_note["revision"], 2)

        default = vault_recall.recall("SupersedeToken")
        explicit = vault_recall.recall(
            "SupersedeToken",
            filters={"status": "superseded"},
        )
        self.assertEqual(default["results"], [])
        self.assertEqual([row["id"] for row in explicit["results"]], [original["id"]])

    def test_supersede_requires_an_existing_target(self) -> None:
        original = self._record("MissingTargetToken")

        with self.assertRaises(lifecycle.NoteNotFound):
            lifecycle.set_status(
                original["id"],
                "superseded",
                "missing replacement",
                supersedes="mem-000000000000",
                expected_revision=1,
            )

        unchanged = lifecycle.get_note(original["id"])
        self.assertEqual(unchanged["status"], "candidate")
        self.assertEqual(unchanged["revision"], 1)

    def test_status_change_drops_and_restores_default_recall(self) -> None:
        recorded = self._record("RestoreToken", status="verified")
        original_ref = lifecycle.get_note(recorded["id"])["evidence_refs"][-1]

        invalidated = lifecycle.set_status(
            recorded["id"],
            "invalidated",
            "evidence disproved",
            expected_revision=1,
        )
        hidden = vault_recall.recall("RestoreToken")
        invalidated_ref = lifecycle.get_note(recorded["id"])["evidence_refs"][-1]
        restored = lifecycle.set_status(
            recorded["id"],
            "verified",
            "replacement evidence verified",
            expected_revision=2,
        )
        visible = vault_recall.recall("RestoreToken")

        self.assertEqual(invalidated["revision"], 2)
        self.assertNotEqual(invalidated_ref, original_ref)
        self.assertEqual(hidden["results"], [])
        self.assertEqual(restored["revision"], 3)
        self.assertEqual(restored["evidence_refs"][-1], original_ref)
        self.assertEqual([row["id"] for row in visible["results"]], [recorded["id"]])

    def test_second_publish_failure_restores_first_note(self) -> None:
        original = self._record("RollbackToken")
        replacement = self._record("RollbackReplacementToken")
        real_publish = lifecycle._publish_stage
        calls = 0

        def fail_second_publish(stage):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated second publish failure")
            real_publish(stage)

        with mock.patch.object(
            lifecycle,
            "_publish_stage",
            side_effect=fail_second_publish,
        ):
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.set_status(
                    original["id"],
                    "superseded",
                    "must roll back",
                    supersedes=replacement["id"],
                    expected_revision=1,
                )

        old_note = lifecycle.get_note(original["id"])
        new_note = lifecycle.get_note(replacement["id"])
        self.assertEqual(old_note["status"], "candidate")
        self.assertIsNone(old_note["superseded_by"])
        self.assertEqual(old_note["revision"], 1)
        self.assertEqual(new_note["supersedes"], [])
        self.assertEqual(new_note["revision"], 1)

    def test_record_usage_persists_apply_feedback_across_rebuild(self) -> None:
        recorded = self._record("UsageToken", status="verified")
        recall_id = vault_recall.recall("UsageToken")["recall_id"]
        generation_before = vault_index.index_generation()

        result = lifecycle.record_usage(
            recall_id,
            recorded["id"],
            "used",
            source_task="TASK-usage-consumer",
        )

        self.assertEqual(result["recall_id"], recall_id)
        self.assertEqual(result["note_id"], recorded["id"])
        self.assertEqual(result["outcome"], "used")
        self.assertEqual(vault_index.index_generation(), generation_before)
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT recall_id, note_id, outcome, source_task, ts "
                "FROM usage WHERE recall_id=?",
                (recall_id,),
            ).fetchone()
        self.assertEqual(row[:4], (recall_id, recorded["id"], "used", "TASK-usage-consumer"))
        self.assertTrue(row[4].endswith("Z"))

        vault_index.rebuild_index()
        with closing(sqlite3.connect(self.db_path)) as connection:
            preserved = connection.execute(
                "SELECT outcome FROM usage WHERE recall_id=? AND note_id=?",
                (recall_id, recorded["id"]),
            ).fetchone()
        self.assertEqual(preserved, ("used",))

    def test_record_usage_is_idempotent_but_rejects_conflicting_feedback(self) -> None:
        recorded = self._record("UsageRetryToken")
        recall_id = vault_recall.recall("UsageRetryToken")["recall_id"]

        first = lifecycle.record_usage(recall_id, recorded["id"], "not_useful")
        repeated = lifecycle.record_usage(recall_id, recorded["id"], "not_useful")

        self.assertEqual(repeated, first)
        with self.assertRaises(lifecycle.UsageConflict):
            lifecycle.record_usage(recall_id, recorded["id"], "incorrect")

    def test_record_usage_rejects_bad_outcome_and_missing_note(self) -> None:
        recorded = self._record("UsageValidationToken")
        recall_id = vault_recall.recall("UsageValidationToken")["recall_id"]

        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.record_usage(recall_id, recorded["id"], "maybe")
        with self.assertRaises(lifecycle.NoteNotFound):
            lifecycle.record_usage(recall_id, "mem-000000000000", "incorrect")


if __name__ == "__main__":
    unittest.main()
