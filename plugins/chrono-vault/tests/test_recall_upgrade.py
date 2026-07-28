"""Deterministic query expansion and the downgrade-only sensitivity filter."""
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
import recall as vault_recall  # noqa: E402
from query import build_fts_query  # noqa: E402


class _VaultTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-recall-upgrade-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "recall-upgrade-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _record(
        self,
        title: str,
        body: str,
        *,
        sensitivity: str = "internal",
        attack_class: str = "recall-upgrade",
    ) -> dict:
        return notes.record(
            "finding",
            {
                "title": title,
                "body": body,
                "target": "push-chain",
                "attack_class": attack_class,
                "status": "verified",
                "sensitivity": sensitivity,
                "source_task": "TASK-recall-upgrade-fixture",
            },
        )


class QueryExpansionTests(_VaultTestCase):
    """Close the vocabulary gap without blurring the identifiers BM25 is good at."""

    def test_an_acronym_query_recalls_the_spelled_out_note(self) -> None:
        """Only the alias map can bridge these two vocabularies."""
        expected = self._record(
            "Unauthenticated fetch primitive",
            "The endpoint performs a server side request forgery against metadata.",
            attack_class="unmapped-class",
        )

        result = vault_recall.recall("ssrf")

        self.assertIn(expected["id"], [row["id"] for row in result["results"]])

    def test_a_spelled_out_query_recalls_the_acronym_note(self) -> None:
        expected = self._record(
            "Proxy weakness",
            "An ssrf reaches the internal metadata endpoint.",
            attack_class="unmapped-class",
        )

        result = vault_recall.recall("server side request forgery")

        self.assertIn(expected["id"], [row["id"] for row in result["results"]])

    def test_an_exact_identifier_query_is_never_expanded(self) -> None:
        for identifier in (
            "MsgExecutePayload",
            "mem-6640fcc23dce",
            "0648551",
            "CVE-2024-1234",
        ):
            with self.subTest(identifier=identifier):
                self.assertEqual(
                    vault_recall.build_expanded_fts_query(identifier),
                    build_fts_query(identifier),
                )

    def test_expansion_never_displaces_the_exact_identifier_match(self) -> None:
        exact = self._record(
            "Commit 0648551 regression",
            "Commit 0648551 introduced the auth regression.",
        )
        self._record(
            "Commit 0648552 regression",
            "Commit 0648552 is a different commit entirely.",
        )

        result = vault_recall.recall("0648551")

        self.assertEqual(result["results"][0]["id"], exact["id"])

    def test_expansion_only_adds_terms_and_is_deterministic(self) -> None:
        original = build_fts_query("auth bypass")
        expanded = vault_recall.build_expanded_fts_query("auth bypass")

        self.assertTrue(expanded.startswith(original))
        self.assertIn('"authentication"', expanded)
        self.assertEqual(expanded, vault_recall.build_expanded_fts_query("auth bypass"))

    def test_expansion_is_bounded(self) -> None:
        crowded = " ".join(
            term
            for group in vault_recall.SYNONYM_GROUPS
            for term in group
            if " " not in term
        )
        expanded = vault_recall.build_expanded_fts_query(crowded)

        added = expanded.count(" OR ") - build_fts_query(crowded).count(" OR ")
        self.assertLessEqual(added, vault_recall.MAX_EXPANSION_TERMS)

    def test_an_unknown_word_expands_to_nothing(self) -> None:
        self.assertEqual(
            vault_recall.build_expanded_fts_query("zzz_unmapped_term"),
            build_fts_query("zzz_unmapped_term"),
        )


class MaxSensitivityFilterTests(_VaultTestCase):
    """A result filter may narrow the clearance-allowed set, never widen it."""

    def _restricted_env(self):
        return mock.patch.dict(os.environ, {"CHRONO_VAULT_CLEARANCE": "restricted"})

    def test_internal_request_hides_restricted_notes_from_a_restricted_process(
        self,
    ) -> None:
        restricted = self._record(
            "TieredToken restricted evidence",
            "TieredToken restricted body.",
            sensitivity="restricted",
        )
        internal = self._record(
            "TieredToken internal evidence",
            "TieredToken internal body.",
            sensitivity="internal",
        )

        with self._restricted_env():
            unfiltered = vault_recall.recall("TieredToken")
            narrowed = vault_recall.recall(
                "TieredToken",
                filters={"max_sensitivity": "internal"},
            )

        self.assertIn(restricted["id"], [row["id"] for row in unfiltered["results"]])
        self.assertEqual([row["id"] for row in narrowed["results"]], [internal["id"]])

    def test_the_filter_cannot_widen_an_internal_process(self) -> None:
        self._record(
            "WidenToken restricted evidence",
            "WidenToken restricted body.",
            sensitivity="restricted",
        )

        widened = vault_recall.recall(
            "WidenToken",
            filters={"max_sensitivity": "restricted"},
        )

        self.assertEqual(widened["results"], [])

    def test_restricted_notes_never_enter_the_candidate_pool(self) -> None:
        """Post-ranking filtering would let a restricted note displace an allowed one."""
        for index in range(3):
            self._record(
                f"PoolToken restricted {index}",
                f"PoolToken restricted body {index} PoolToken PoolToken.",
                sensitivity="restricted",
            )
        allowed = self._record(
            "PoolToken internal",
            "PoolToken internal body.",
            sensitivity="internal",
        )

        with self._restricted_env():
            narrowed = vault_recall.recall(
                "PoolToken",
                filters={"max_sensitivity": "internal"},
                limit=1,
            )

        self.assertEqual([row["id"] for row in narrowed["results"]], [allowed["id"]])

    def test_an_invalid_max_sensitivity_is_rejected(self) -> None:
        """Silently ignoring a typo would return more than the caller asked for."""
        for value in ("public", "", "RESTRICTED", None):
            with self.subTest(value=value):
                with self.assertRaises(vault_recall.RecallError) as error:
                    vault_recall.recall("anything", filters={"max_sensitivity": value})
                self.assertIn("max_sensitivity", str(error.exception))

    def test_absent_filter_preserves_process_behaviour(self) -> None:
        restricted = self._record(
            "AbsentToken restricted evidence",
            "AbsentToken restricted body.",
            sensitivity="restricted",
        )

        with self._restricted_env():
            result = vault_recall.recall("AbsentToken")

        self.assertEqual([row["id"] for row in result["results"]], [restricted["id"]])


if __name__ == "__main__":
    unittest.main()
