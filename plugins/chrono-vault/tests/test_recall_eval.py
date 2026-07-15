from __future__ import annotations

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
                "target": "push-chain",
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
                "target": "push-chain",
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
                "target": "push-chain",
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
                "target": "push-chain",
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
                "target": "push-chain",
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

    def test_gold_queries_meet_recall_at_five_threshold_and_report_mrr(self) -> None:
        gold = (
            ("how could a Solana program create an unbacked mint", "svm-emitter"),
            ("can an SVM emitter forge a cross chain deposit", "svm-emitter"),
            ("what malformed execute message can stop validators", "execute-halt"),
            ("does the finalized nonce RPC survive a chain reorg", "finalized-nonce"),
            ("when should a report fail the reproducible impact bar", "impact-gate"),
            ("how do we test the bug across transaction families", "cross-family"),
            ("what causes Cosmos validators to derive different states", "cosmos-nondeterminism"),
            ("should we use vectors or keyword search", "retrieval-strategy"),
        )
        hits = 0
        reciprocal_ranks: list[float] = []
        for natural_query, expected_key in gold:
            ranked_ids = [
                row["id"]
                for row in vault_recall.recall(natural_query, limit=5)["results"]
            ]
            expected_id = self.note_ids[expected_key]
            if expected_id in ranked_ids:
                hits += 1
                reciprocal_ranks.append(1.0 / (ranked_ids.index(expected_id) + 1))
            else:
                reciprocal_ranks.append(0.0)

        recall_at_five = hits / len(gold)
        mrr = sum(reciprocal_ranks) / len(gold)
        print(f"recall_eval recall@5={recall_at_five:.3f} mrr={mrr:.3f}")
        self.assertGreaterEqual(recall_at_five, 0.75)


if __name__ == "__main__":
    unittest.main()
