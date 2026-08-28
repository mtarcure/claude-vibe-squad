"""Pin the *ordinal design intent* the BM25 field-weight vector encodes.

`index.BM25_WEIGHTS = (8,1,6,3,2,6,3,1)` over the FTS columns
`(title, body, aliases, target, component, attack_class, keywords,
evidence_summary)` weights label-ish fields (title=8, aliases=6,
attack_class=6) far above prose fields (body=1, evidence_summary=1). Both
`index.py` and `recall.py` already record, honestly, that the *magnitudes*
have no measured derivation (index.py: provenance on `BM25_WEIGHTS`;
recall.py: provenance on the ranking bonuses). This test does the other half:
it makes the one thing those magnitudes are actually load-bearing for — the
ordering "a query term in a label field outranks the same term in prose" —
FALSIFIABLE, so a later flatten or reshuffle of the vector is caught instead
of passing silently.

What this test proves, and only this: the *ordering* the current vector
produces is caused by the vector, not by field length or note recency. It
does NOT claim (8,1,6,...) are tuned, optimal, or better than any other
label-over-prose ordering. Validating the absolute magnitudes needs a labeled
query -> relevant-note set that does not exist in this repo; the design note
for TASK-2026-08-27-1520-wc2 states what that measurement would require.

Construction (the trap this avoids): a naive "term-in-title beats term-in-body"
fixture is vacuous, because BM25 length normalization already favors the
shorter title field regardless of weight, so it would pass even with the
weights flattened. Each pair here is therefore mirror-symmetric — the two
notes have identical field *lengths*, differing only in which column holds the
unique probe token — so under a flat weight vector the two notes score
identically and the recency tiebreak (the body-hit note is made newer) decides.
The negative control flattens the vector and asserts the ordering FLIPS, which
is what shows the positive assertion is weight-caused.
"""
from __future__ import annotations

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
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


# The probe token in each pair is unique and appears in exactly one field of
# exactly one note in the pair; the pair's other note carries it in `body`.
TITLE_PROBE = "zylophonecue"
ALIAS_PROBE = "quafflemarker"


class WeightOrdinalityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_dir = tempfile.TemporaryDirectory(prefix="chrono-weight-ord-")
        self.addCleanup(self.vault_dir.cleanup)
        self.vault_root = Path(os.path.realpath(self.vault_dir.name))
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "weight-ordinality", "schema_version": 1}),
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

    def _finding(self, **fields: object) -> str:
        payload = {
            "target": "alphaunit",
            "attack_class": "betaclass",
            "component": "gammacomp",
            "status": "candidate",
            "source_task": "TASK-weight-ordinality-fixture",
            **fields,
        }
        return notes.record("finding", payload)["id"]

    def _set_mtime(self, note_id: str, ns: int) -> None:
        path = next((self.vault_root / "notes").rglob(f"{note_id}.md"))
        os.utime(path, ns=(ns, ns))

    def _ranked(self, query: str) -> list[str]:
        return [row["id"] for row in vault_recall.recall(query, limit=5)["results"]]

    def _bm25(self, query: str, note_id: str) -> float:
        row = next(
            row
            for row in vault_recall.recall(query, limit=5)["results"]
            if row["id"] == note_id
        )
        return row["score_components"]["bm25"]

    def test_field_weight_ordering_is_weight_caused_not_length_or_recency(self) -> None:
        # Decoys that never contain either probe token, so the probe terms carry
        # a healthy positive IDF (N large, n=2) and the score margin is a
        # comfortable ~0.8, not a near-zero knife edge.
        for i in range(4):
            self._finding(
                title=f"decoy{i} lorem ipsum",
                body=f"decoy body {i} sit amet",
                aliases=[f"dec{i}"],
            )

        # Pair 1: title(8) vs body(1). Titles are 3 tokens in both notes and
        # bodies are 3 tokens in both, so the pair is length-symmetric.
        title_hit = self._finding(
            title=f"{TITLE_PROBE} alpha bravo",
            body="charlie delta echo",
            aliases=["sierrax"],
        )
        title_body_hit = self._finding(
            title="foxtrot alpha bravo",
            body=f"{TITLE_PROBE} delta echo",
            aliases=["sierrax"],
        )

        # Pair 2: aliases(6) vs body(1). Aliases join to 3 tokens in both notes
        # and bodies are 3 tokens in both, so this pair is length-symmetric too.
        alias_hit = self._finding(
            title="papa quebec romeo",
            body="mike november oscar",
            aliases=[ALIAS_PROBE, "delta", "echo"],
        )
        alias_body_hit = self._finding(
            title="papa quebec romeo",
            body=f"{ALIAS_PROBE} november oscar",
            aliases=["sierra", "delta", "echo"],
        )

        # Make the body-hit note of each pair NEWER, so that if the field
        # weights stop mattering the recency tiebreak resolves to it. Under the
        # real vector the label-field note must still win despite being older.
        self._set_mtime(title_hit, 1_000_000_000)
        self._set_mtime(title_body_hit, 2_000_000_000)
        self._set_mtime(alias_hit, 1_000_000_000)
        self._set_mtime(alias_body_hit, 2_000_000_000)

        # Real weights: publish a clean full index that captures the mtimes and
        # writes the canonical BM25_WEIGHTS into the index config.
        vault_index.rebuild_index()

        self.assertEqual(self._ranked(TITLE_PROBE)[0], title_hit)
        self.assertEqual(self._ranked(ALIAS_PROBE)[0], alias_hit)
        # Document the mechanism: the label-field note is more relevant by a
        # real margin, not a floating-point tie broken the lucky way.
        self.assertGreater(
            self._bm25(TITLE_PROBE, title_hit),
            self._bm25(TITLE_PROBE, title_body_hit),
        )
        self.assertGreater(
            self._bm25(ALIAS_PROBE, alias_hit),
            self._bm25(ALIAS_PROBE, alias_body_hit),
        )

        # Negative control (baked-in inverted control): flatten the weight
        # vector and rebuild. The pairs are length-symmetric, so both notes now
        # score identically and the newer (body-hit) note wins each pair. The
        # ordering FLIPPING is what proves the positive assertions above are
        # caused by BM25_WEIGHTS and not by field length or note recency. If a
        # future change made recall ignore the field weights, the positive
        # assertions would silently still pass on length alone; this control is
        # the guard against exactly that "green test over a broken guard".
        with mock.patch.object(vault_index, "BM25_WEIGHTS", (1.0,) * 8):
            vault_index.rebuild_index()
            self.assertEqual(self._ranked(TITLE_PROBE)[0], title_body_hit)
            self.assertEqual(self._ranked(ALIAS_PROBE)[0], alias_body_hit)
            self.assertEqual(
                self._bm25(TITLE_PROBE, title_hit),
                self._bm25(TITLE_PROBE, title_body_hit),
            )


if __name__ == "__main__":
    unittest.main()
