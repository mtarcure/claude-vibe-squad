"""Citation must be a byproduct of recalling, not an act of discipline.
protocol.md:445 asks workers to cite `mem-...` IDs; nothing enforced it,
so promotion had no reliable input."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import notes  # noqa: E402
from recall import RecallError, recall  # noqa: E402

TASK_ID = "TASK-2026-08-17-0100-recall-returns"
OTHER_TASK_ID = "TASK-2026-08-17-0200-someone-else"


@contextmanager
def _engagement(task_id: str):
    """Run the block as a dispatched lane worker, not as the controller.

    The same `CHRONO_VAULT_CONTEXT` envelope `dispatch_context_builder`
    hands a worker, under the `default` aperture every dispatch now gets.
    """
    context = {
        "schema": "chrono-vault-context/v1",
        "task_id": task_id,
        "attempt_id": "d-" + "3" * 32,
        "generation": 1,
        "mode": "project",
        "aperture": "default",
        "focus": None,
        "engagement_start": "2026-08-17T00:00:00Z",
    }
    with mock.patch.dict(
        os.environ, {"CHRONO_VAULT_CONTEXT": json.dumps(context)}
    ):
        yield


class RecallRecordsReturnsTests(unittest.TestCase):
    def _vault_with_notes(self, titles: list[str]) -> Path:
        """Build an isolated vault (same tempdir + `.chrono-vault` marker +
        CHRONO_VAULT_ROOT fixture pattern as test_recall.py's setUp) and
        record one finding per title, each written so the query "anything"
        matches it."""
        vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-recall-returns-test-"))
        )
        self.addCleanup(shutil.rmtree, vault_root, ignore_errors=True)
        (vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "recall-returns-test", "schema_version": 1}),
            encoding="utf-8",
        )
        env = mock.patch.dict(os.environ, {"CHRONO_VAULT_ROOT": str(vault_root)})
        env.start()
        self.addCleanup(env.stop)
        # See test_recall.py: patch.dict does not clear an operator-exported
        # CHRONO_VAULT_CLEARANCE, so an ambient one would silently widen
        # every recall() call below.
        os.environ.pop("CHRONO_VAULT_CLEARANCE", None)

        for title in titles:
            notes.record(
                "finding",
                {
                    "title": f"{title} anything finding",
                    "body": "This note matches the query anything.",
                    "target": "example-chain",
                    "component": "executor",
                    "attack_class": "returns-fixture",
                    "status": "candidate",
                    "source_task": "TASK-recall-returns-fixture",
                },
            )
        return vault_root

    def test_recall_records_every_returned_note_id(self) -> None:
        root = self._vault_with_notes(["alpha", "beta"])

        result = recall("anything", filters={"source_task": "TASK-X"})

        con = sqlite3.connect(root / "index" / "kg.db")
        try:
            rows = con.execute(
                "SELECT note_id, source_task FROM recall_returned"
            ).fetchall()
        finally:
            con.close()

        returned = {note["id"] for note in result["results"]}
        self.assertTrue(returned, "fixture notes must actually match the query")
        self.assertEqual({row[0] for row in rows}, returned)
        self.assertTrue(all(row[1] == "TASK-X" for row in rows))

    def test_empty_recall_records_nothing(self) -> None:
        self._vault_with_notes([])

        result = recall("nothing matches", filters={"source_task": "TASK-Y"})

        # No notes were ever written, so there is no index at all yet
        # (test_recall.py's test_missing_index_returns_empty_without_creating_storage
        # pins that recall() must not create one just to run) -- there is
        # nothing to record, and recall() must not fail.
        self.assertEqual(result["results"], [])

    def _source_tasks(self, root: Path) -> list[str | None]:
        con = sqlite3.connect(root / "index" / "kg.db")
        try:
            return [
                row[0]
                for row in con.execute("SELECT source_task FROM recall_returned")
            ]
        finally:
            con.close()

    def test_a_bound_engagement_derives_source_task_from_its_context(self) -> None:
        """The production shape: no filters at all, and citation still lands.

        This is the assertion the branch was missing. `dispatch_context_
        builder`'s launch prompt tells every worker "Pass no filters", and
        the MCP `recall` tool does not expose `source_task`, so a
        caller-declared key was NULL on every real recall and
        `memory_promotion`'s `WHERE r.source_task = ?` could never match.
        Drive recall exactly as the prompt mandates and the key must still
        be the engagement's task.
        """
        root = self._vault_with_notes(["solo"])

        with _engagement(TASK_ID):
            result = recall("anything")

        self.assertTrue(result["results"])
        recorded = self._source_tasks(root)
        self.assertTrue(recorded)
        self.assertTrue(all(value == TASK_ID for value in recorded))

    def test_a_declared_source_task_matching_the_engagement_is_accepted(self) -> None:
        root = self._vault_with_notes(["solo"])

        with _engagement(TASK_ID):
            recall("anything", filters={"source_task": TASK_ID})

        self.assertTrue(all(value == TASK_ID for value in self._source_tasks(root)))

    def test_a_caller_cannot_cite_another_engagements_task(self) -> None:
        """Same refusal `lifecycle.record_usage` makes, for the same reason.

        Deriving the key would be pointless if a caller could still declare
        someone else's task and have it silently override -- or be silently
        overridden. Refuse, exactly as `record_usage` does.
        """
        self._vault_with_notes(["solo"])

        with _engagement(TASK_ID):
            with self.assertRaisesRegex(RecallError, "source_task"):
                recall("anything", filters={"source_task": OTHER_TASK_ID})

    def test_an_unbound_process_records_null_without_failing(self) -> None:
        """Recall must never break because there is no engagement to derive from.

        Chrono and the operator recall outside any dispatch. There is no
        authenticated task to attribute those to, and inventing one would
        make promotion claim a review that never happened, so the column is
        NULL and nothing promotes -- the correct direction.
        """
        root = self._vault_with_notes(["solo"])

        result = recall("anything")

        self.assertTrue(result["results"])
        recorded = self._source_tasks(root)
        self.assertTrue(recorded)
        self.assertTrue(all(value is None for value in recorded))


if __name__ == "__main__":
    unittest.main()
