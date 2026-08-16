from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import notes  # noqa: E402
from query import build_fts_query  # noqa: E402
import recall as vault_recall  # noqa: E402


V3_GOLD_FILTERS = {
    "max_sensitivity": "internal",
    "status": ["candidate", "verified"],
    "type": "finding",
    "written_before": "2100-01-01T00:00:00Z",
}
V3_ALGORITHM_GOLD = (
    ("how could a Solana program create an unbacked mint", ("svm-emitter",)),
    ("can an SVM emitter forge a cross chain deposit", ("svm-emitter",)),
    ("what malformed execute message can stop validators", ("execute-halt",)),
    ("does the finalized nonce RPC survive a chain reorg", ("finalized-nonce",)),
    ("when should a report fail the reproducible impact bar", ("impact-gate",)),
    ("how do we test the bug across transaction families", ("cross-family",)),
    (
        "what causes Cosmos validators to derive different states",
        ("cosmos-nondeterminism",),
    ),
    ("should we use vectors or keyword search", ("retrieval-strategy",)),
)
V3_ALGORITHM_GOLD_SHA256 = (
    "ab8c68d77aedc2152069f1236232b11e5d341537849ac0d2fcab9e531dd88a1d"
)
V3_ALGORITHM_BASELINE = (0.2, 1.0, 1.0, 1.0)
APERTURE_ARGUMENTS = ("aperture", "campaign", "campaign_id", "project", "project_id")


class QueryBuilderTests(unittest.TestCase):
    def test_natural_language_terms_are_or_joined_without_stopwords(self) -> None:
        built = build_fts_query("should we use vectors or keyword search")

        self.assertEqual(built, '"vectors" OR "keyword" OR "search"')

    def test_identifiers_survive_and_fts_syntax_is_quoted(self) -> None:
        built = build_fts_query(
            'title:MsgExecutePayload finalized-nonce forge* "unterminated'
        )

        self.assertIn('"MsgExecutePayload"', built)
        self.assertIn('"finalized-nonce"', built)
        self.assertNotIn("title:", built)
        self.assertNotIn("forge*", built)

    def test_stopword_only_query_falls_back_to_sanitized_raw_terms(self) -> None:
        built = build_fts_query("should we use for the a of how do")

        self.assertTrue(built)
        self.assertEqual(
            built,
            '"should" OR "we" OR "use" OR "for" OR "the" OR "a" OR "of" OR "how" OR "do"',
        )


class RecallQualityEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-recall-eval-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "recall-eval", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.note_ids = self._seed_notes()

    def _seed_notes(self) -> dict[str, str]:
        fixtures = {
            "svm-emitter": {
                "title": "SVM emitter can forge an inbound deposit",
                "body": (
                    "An unauthorized Solana program can emit a forged cross-chain "
                    "deposit and cause an unbacked mint."
                ),
                "target": "example-chain",
                "component": "svm-emitter",
                "attack_class": "forged-inbound",
                "aliases": ["Solana forged deposit", "unbacked token mint"],
            },
            "execute-halt": {
                "title": "MsgExecutePayload can halt consensus",
                "body": (
                    "A malformed executor message reaches a panic path and stops "
                    "validator block processing."
                ),
                "target": "example-chain",
                "component": "executor",
                "attack_class": "availability",
                "aliases": ["C1 chain halt", "execute payload panic"],
            },
            "finalized-nonce": {
                "title": "Finalized nonce reads latest state",
                "body": (
                    "The finalized-nonce path incorrectly reads the latest block, "
                    "making nonce validation vulnerable to reorganization."
                ),
                "target": "example-chain",
                "component": "rpc",
                "attack_class": "state-consistency",
                "aliases": ["finality mismatch", "reorg nonce read"],
            },
            "impact-gate": {
                "title": "Impact bar gates non-reproducible reports",
                "body": (
                    "Do not resubmit a finding when exploit impact cannot be "
                    "reproduced under the program rules."
                ),
                "target": "bounty-process",
                "component": "triage",
                "attack_class": "impact-validation",
                "aliases": ["submission quality gate", "reproduction required"],
            },
            "cross-family": {
                "title": "Reproduce findings across transaction families",
                "body": (
                    "Test the same authorization bug across EVM, SVM, and Cosmos "
                    "transaction variants before narrowing the claim."
                ),
                "target": "example-chain",
                "component": "testing",
                "attack_class": "cross-family-reproduction",
                "aliases": ["multi-family test matrix", "transaction variants"],
            },
            "cosmos-nondeterminism": {
                "title": "Cosmos execution can become nondeterministic",
                "body": (
                    "Map iteration in a consensus handler can make validators "
                    "derive different state roots."
                ),
                "target": "example-chain",
                "component": "cosmos-executor",
                "attack_class": "nondeterminism",
                "aliases": ["validator disagreement", "consensus state divergence"],
            },
            "retrieval-strategy": {
                "title": "Use keyword search before vector retrieval",
                "body": (
                    "For a small memory vault, SQLite FTS5 BM25 keyword retrieval "
                    "is simpler than embeddings or a vector database."
                ),
                "target": "chrono-vault",
                "component": "recall",
                "attack_class": "retrieval-design",
                "aliases": ["vectors versus keywords", "BM25 search"],
            },
        }
        note_ids: dict[str, str] = {}
        for key, fields in fixtures.items():
            note_ids[key] = notes.record("finding", fields)["id"]
        return note_ids

    def test_natural_language_query_finds_keyword_search_note(self) -> None:
        result = vault_recall.recall(
            "should we use vectors or keyword search",
            limit=5,
        )

        self.assertEqual(
            result["results"][0]["id"],
            self.note_ids["retrieval-strategy"],
        )

    def test_stopword_only_recall_is_graceful(self) -> None:
        result = vault_recall.recall("should we use for the a of how do", limit=5)

        self.assertNotIn("query_error", result)
        self.assertIsInstance(result["results"], list)

    def test_frozen_v3_production_algorithm_baseline(self) -> None:
        """Freeze algorithm behavior, not quality on the private legacy corpus."""
        encoded_gold = json.dumps(
            {"filters": V3_GOLD_FILTERS, "queries": V3_ALGORITHM_GOLD},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.assertEqual(
            hashlib.sha256(encoded_gold).hexdigest(),
            V3_ALGORITHM_GOLD_SHA256,
        )

        precision = recall = mrr = 0.0
        status_checked = status_compliant = 0
        allowed_statuses = set(V3_GOLD_FILTERS["status"])
        for query, relevant_keys in V3_ALGORITHM_GOLD:
            rows = vault_recall.recall(
                query,
                filters=dict(V3_GOLD_FILTERS),
                limit=5,
            )["results"]
            ranked_ids = [row["id"] for row in rows]
            relevant = {self.note_ids[key] for key in relevant_keys}
            hits = sum(note_id in relevant for note_id in ranked_ids[:5])
            precision += hits / 5
            recall += hits / len(relevant)
            mrr += next(
                (
                    1 / rank
                    for rank, note_id in enumerate(ranked_ids[:5], 1)
                    if note_id in relevant
                ),
                0.0,
            )
            status_checked += len(rows)
            status_compliant += sum(row["status"] in allowed_statuses for row in rows)

        query_count = len(V3_ALGORITHM_GOLD)
        self.assertGreater(status_checked, 0)
        measured = tuple(
            round(value, 6)
            for value in (
                precision / query_count,
                recall / query_count,
                mrr / query_count,
                status_compliant / status_checked,
            )
        )
        print(
            "recall_eval scope=disposable-production-algorithm "
            f"precision@5={measured[0]:.3f} recall@5={measured[1]:.3f} "
            f"mrr={measured[2]:.3f} status_integrity={measured[3]:.3f}"
        )
        self.assertEqual(measured, V3_ALGORITHM_BASELINE)

    def test_supported_filter_leak_sentinels(self) -> None:
        def sentinel(
            token: str,
            blocked: dict[str, object],
            *,
            visible: dict[str, object] | None = None,
            note_type: str = "finding",
            **fields: object,
        ) -> None:
            note_id = notes.record(
                note_type,
                {
                    "title": f"{token} sentinel",
                    "body": f"{token} must be excluded by its production filter.",
                    "target": "filter-eval",
                    "component": "recall",
                    "attack_class": "filter-sentinel",
                    **fields,
                },
            )["id"]
            visible_ids = [
                row["id"]
                for row in vault_recall.recall(token, filters=visible)["results"]
            ]
            self.assertEqual(visible_ids, [note_id])
            self.assertEqual(vault_recall.recall(token, filters=blocked)["results"], [])

        sentinel(
            "StatusLeakSentinel",
            {"status": ["candidate", "verified"]},
            visible={"status": "invalidated"},
            status="invalidated",
        )
        sentinel("TypeLeakSentinel", {"type": "finding"}, note_type="attempt")
        sentinel(
            "CutoffLeakSentinel",
            {"written_before": "2000-01-01T00:00:00Z"},
        )
        with mock.patch.dict(os.environ, {"CHRONO_VAULT_CLEARANCE": "restricted"}):
            sentinel(
                "SensitivityLeakSentinel",
                {"max_sensitivity": "internal"},
                sensitivity="restricted",
            )

    def test_v3_aperture_enforcement_is_blocked_and_cannot_be_spoofed(self) -> None:
        """V3 has no server-owned engagement aperture; do not claim otherwise."""
        self.assertTrue(set(APERTURE_ARGUMENTS).isdisjoint(vault_recall.FILTER_FIELDS))
        for argument in APERTURE_ARGUMENTS:
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(
                    vault_recall.RecallError, "unknown filters"
                ):
                    vault_recall.recall(
                        "aperture sentinel",
                        filters={argument: "client-controlled-label"},
                    )


if __name__ == "__main__":
    unittest.main()
