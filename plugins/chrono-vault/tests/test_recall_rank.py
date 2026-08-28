"""Regression fixtures for recall ranking, feedback, and lifecycle folding.

The synthetic judgments below are deliberately small. They detect changes to
known-correct results; they do not claim that the legacy coefficients are tuned
or that this corpus represents production recall quality.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import clearance  # noqa: E402
import index as vault_index  # noqa: E402
import lifecycle  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


RANK_BASELINE_FIXTURES = {
    "feedback-ranking": {
        "title": "Incorrect feedback demotes a recalled note",
        "body": (
            "Usage outcome history lowers a contested note while keeping it "
            "retrievable for audit."
        ),
        "component": "recall",
        "attack_class": "ranking-feedback",
        "aliases": ["wrong memory ranking"],
        "keywords": ["incorrect", "used", "disputed"],
    },
    "lifecycle-fold": {
        "title": "Lifecycle status folds superseded memory",
        "body": (
            "Archived, invalidated, and superseded notes leave default recall "
            "but remain available through status filters."
        ),
        "component": "recall",
        "attack_class": "selection-folding",
        "aliases": ["recoverable memory landmark"],
        "keywords": ["archived", "superseded", "status"],
    },
    "sparse-baseline": {
        "title": "Repository fixtures measure sparse recall",
        "body": (
            "Known-correct query judgments freeze BM25 ranking behavior without "
            "tuning field weights."
        ),
        "component": "recall-evaluation",
        "attack_class": "ranking-regression",
        "aliases": ["lexical retrieval benchmark"],
        "keywords": ["bm25", "baseline", "fixtures"],
    },
    "reader-restart": {
        "title": "Index rebuild replaces the SQLite inode",
        "body": (
            "Long-lived MCP readers must restart after a vault rebuild to stop "
            "reading the dead inode."
        ),
        "component": "index-lifecycle",
        "attack_class": "reader-freshness",
        "aliases": ["dead inode reader"],
        "keywords": ["mcp", "restart", "rebuild"],
    },
    "state-boundary": {
        "title": "Workboard owns deterministic current work state",
        "body": (
            "The capsule stores current promise, focus, queue, and next action; "
            "the vault stores reusable learned context."
        ),
        "target": "workboard",
        "component": "capsule",
        "attack_class": "state-boundary",
        "aliases": ["work state memory boundary"],
        "keywords": ["promise", "focus", "queue"],
    },
}

RANK_BASELINE_GOLD = (
    ("how should incorrect usage feedback affect recall ranking", "feedback-ranking"),
    ("where can superseded and archived notes be found", "lifecycle-fold"),
    ("how do fixtures detect a BM25 regression without tuning weights", "sparse-baseline"),
    ("why must MCP readers restart after an index rebuild", "reader-restart"),
    ("where do current promise focus queue and next action belong", "state-boundary"),
)
RANK_BASELINE_SHA256 = (
    "dacbcde51ab96f09b541c24712b61b3a33ac6bc80b6f2d688a8bee14ecfc69f9"
)


class RecallRankTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_dir = tempfile.TemporaryDirectory(prefix="chrono-recall-rank-")
        self.addCleanup(self.vault_dir.cleanup)
        self.repo_dir = tempfile.TemporaryDirectory(prefix="chrono-recall-rank-repo-")
        self.addCleanup(self.repo_dir.cleanup)
        self.vault_root = Path(os.path.realpath(self.vault_dir.name))
        self.repo_root = Path(os.path.realpath(self.repo_dir.name))
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "recall-rank", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_VAULT_AUDIT_DIR": str(self.vault_root / "audit"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("CHRONO_VAULT_CLEARANCE", None)
        os.environ.pop(clearance.CONTEXT_ENV, None)

    def _write(
        self,
        token: str,
        *,
        status: str = "candidate",
        note_type: str = "learning",
        **fields: object,
    ) -> dict:
        payload = {
            "title": f"{token} recall fixture",
            "body": f"{token} has identical lexical evidence for ranking.",
            "status": status,
            "source_task": "TASK-recall-rank-fixture",
            **fields,
        }
        if note_type != "learning":
            payload.setdefault("target", "chrono-vault")
            payload.setdefault("attack_class", "ranking-fixture")
        return notes.record(note_type, payload)

    def _set_mtimes(self, older: dict, newer: dict) -> None:
        os.utime(older["path"], ns=(1_000_000_000, 1_000_000_000))
        os.utime(newer["path"], ns=(2_000_000_000, 2_000_000_000))
        vault_index.sync_index()

    @staticmethod
    def _row(result: dict, note_id: str) -> dict:
        return next(row for row in result["results"] if row["id"] == note_id)


class UsageOutcomeRankTests(RecallRankTestCase):
    def test_incorrect_demotes_repeatedly_but_remains_findable_and_disputed(self) -> None:
        neutral = self._write("IncorrectRankProbe")
        incorrect = self._write("IncorrectRankProbe")
        self._set_mtimes(neutral, incorrect)

        before = vault_recall.recall("IncorrectRankProbe")
        self.assertEqual(before["results"][0]["id"], incorrect["id"])

        lifecycle.record_usage(
            before["recall_id"],
            incorrect["id"],
            "incorrect",
            repo_root=self.repo_root,
        )
        once = vault_recall.recall("IncorrectRankProbe")
        once_row = self._row(once, incorrect["id"])
        self.assertEqual(once["results"][0]["id"], neutral["id"])
        self.assertTrue(once_row["disputed"])
        self.assertEqual(once_row["score_components"]["usage"]["incorrect"], 1)

        lifecycle.record_usage(
            once["recall_id"],
            incorrect["id"],
            "incorrect",
            repo_root=self.repo_root,
        )
        twice = vault_recall.recall("IncorrectRankProbe")
        twice_row = self._row(twice, incorrect["id"])
        self.assertIn(incorrect["id"], [row["id"] for row in twice["results"]])
        self.assertLess(
            twice_row["score_components"]["usage"]["signal"],
            once_row["score_components"]["usage"]["signal"],
        )
        self.assertLess(twice_row["score"], once_row["score"])

    def test_used_supports_an_older_equally_relevant_note(self) -> None:
        supported = self._write("UsedRankProbe")
        neutral = self._write("UsedRankProbe")
        self._set_mtimes(supported, neutral)

        before = vault_recall.recall("UsedRankProbe")
        self.assertEqual(before["results"][0]["id"], neutral["id"])
        lifecycle.record_usage(
            before["recall_id"],
            supported["id"],
            "used",
            repo_root=self.repo_root,
        )

        after = vault_recall.recall("UsedRankProbe")
        supported_row = self._row(after, supported["id"])
        self.assertEqual(after["results"][0]["id"], supported["id"])
        self.assertGreater(supported_row["score_components"]["usage"]["signal"], 0)
        self.assertFalse(supported_row["disputed"])


class LifecycleFoldingTests(RecallRankTestCase):
    def test_default_folds_terminal_statuses_and_status_filter_recovers_them(self) -> None:
        notes_by_status = {
            status: self._write("FoldedStatusProbe", status=status)
            for status in (*vault_recall.ACTIVE_STATUSES, *vault_recall.FOLDED_STATUSES)
        }

        active = vault_recall.recall("FoldedStatusProbe", limit=10)
        self.assertEqual(active["tiers_searched"], ["active"])
        self.assertEqual(
            {row["id"] for row in active["results"]},
            {notes_by_status[status]["id"] for status in vault_recall.ACTIVE_STATUSES},
        )

        folded = vault_recall.recall(
            "FoldedStatusProbe",
            filters={"status": list(vault_recall.FOLDED_STATUSES)},
            limit=10,
        )
        self.assertEqual(folded["tiers_searched"], ["folded"])
        self.assertEqual(
            {row["id"] for row in folded["results"]},
            {notes_by_status[status]["id"] for status in vault_recall.FOLDED_STATUSES},
        )

        all_statuses = vault_recall.recall(
            "FoldedStatusProbe",
            filters={"status": [
                *vault_recall.ACTIVE_STATUSES,
                *vault_recall.FOLDED_STATUSES,
            ]},
            limit=10,
        )
        self.assertEqual(all_statuses["tiers_searched"], ["active", "folded"])


class RepoControlledRankBaselineTests(RecallRankTestCase):
    def test_known_correct_queries_hold_the_frozen_sparse_baseline(self) -> None:
        encoded_judgments = json.dumps(
            {
                "fixtures": RANK_BASELINE_FIXTURES,
                "gold": RANK_BASELINE_GOLD,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.assertEqual(
            hashlib.sha256(encoded_judgments).hexdigest(),
            RANK_BASELINE_SHA256,
        )

        note_ids: dict[str, str] = {}
        for key, fields in RANK_BASELINE_FIXTURES.items():
            note_ids[key] = notes.record(
                "finding",
                {
                    "target": "chrono-vault",
                    "status": "candidate",
                    "source_task": "TASK-recall-rank-baseline",
                    **fields,
                },
            )["id"]

        reciprocal_rank = 0.0
        top_one = 0
        for query, expected_key in RANK_BASELINE_GOLD:
            with self.subTest(query=query):
                ranked = [
                    row["id"]
                    for row in vault_recall.recall(query, limit=5)["results"]
                ]
                expected_id = note_ids[expected_key]
                self.assertIn(expected_id, ranked)
                rank = ranked.index(expected_id) + 1
                reciprocal_rank += 1 / rank
                top_one += rank == 1

        query_count = len(RANK_BASELINE_GOLD)
        measured = (top_one / query_count, reciprocal_rank / query_count)
        print(
            "recall_rank_baseline scope=synthetic-repo-fixtures "
            f"top1={measured[0]:.3f} mrr={measured[1]:.3f} "
            f"queries={query_count}"
        )
        self.assertEqual(measured, (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
