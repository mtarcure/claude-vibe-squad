"""Ranking must make promotion visible. Before this, `verified` changed
admission only, so promoting a note altered nothing a worker saw."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import index as vault_index  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402
from recall import _rank_bonus_sql  # noqa: E402


class RankBonusTests(unittest.TestCase):
    """Shape only. The behaviour is pinned end-to-end below.

    These three assertions used to be the ONLY per-bonus coverage, and they
    pass with both bonuses set to 0 and with the fragment never spliced into
    the query. Kept because the sign is genuinely easy to get wrong and
    cheap to guard; not trusted for anything else.
    """

    def test_the_fragment_names_both_bonus_conditions(self):
        sql = _rank_bonus_sql()
        self.assertIn("m.status = 'verified'", sql)
        self.assertIn("m.note_type = 'finding'", sql)

    def test_bonus_is_subtracted_not_added(self):
        # bm25 returns NEGATIVE scores ordered ASC, so a bonus must be
        # SUBTRACTED to move a row earlier. Guard the sign.
        self.assertIn("-", _rank_bonus_sql())


class RankBonusEndToEndTests(unittest.TestCase):
    """Prove the bonus actually reorders results on a real index, not just
    that the SQL fragment contains the right substrings."""

    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-recall-rank-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "recall-rank-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        # patch.dict does not clear ambient vars; an operator with
        # CHRONO_VAULT_CLEARANCE exported would silently constrain this
        # write to candidate-only, which would make the verified fixture
        # below impossible to create and the test would fail for an
        # environmental reason instead of the one under test.
        os.environ.pop("CHRONO_VAULT_CLEARANCE", None)

    # Spec §17 names TWO assertions -- "a `verified` note outranks an
    # equally-relevant `candidate`; a `finding` outranks an equally-relevant
    # `learning`" -- and each needs a pair that differs in ONE of them. The
    # original end-to-end test compared a verified finding against a
    # candidate learning, so either bonus alone carried it: zeroing
    # `_VERIFIED_BONUS` failed nothing, and zeroing `_FINDING_BONUS` failed
    # nothing. Only zeroing both was detectable.
    #
    # The other half of that blind spot was ordering. Absent any bonus the
    # query falls through to `m.mtime_ns DESC`, and the original fixture
    # wrote the privileged note SECOND -- so recency alone put it first and
    # the assertion held with the mechanism removed. Every pair below writes
    # the privileged note first and then back-dates it, so recency actively
    # opposes the bonus and only the bonus can produce the expected order.

    def _write(self, note_type: str, status: str, token: str) -> dict:
        return notes.record(
            note_type,
            {
                "title": f"{token} forged inbound payload",
                "body": f"{token} reaches the privileged executor path.",
                "target": "example-chain",
                "component": "executor",
                "attack_class": "forged-inbound",
                "status": status,
                "source_task": "TASK-recall-rank-fixture",
            },
        )

    def _backdate(self, note: dict) -> None:
        """Make this note the OLDEST, so recency ranks it last.

        `index._parse_note` reads `st_mtime_ns` at index time, so the file
        stamp has to be moved before the index is rebuilt from it.
        """
        older = time.time_ns() - 3600 * 10**9
        os.utime(note["path"], ns=(older, older))
        vault_index.rebuild_index()

    def _order(self, token: str) -> list[str]:
        return [row["id"] for row in vault_recall.recall(token)["results"]]

    def test_verified_outranks_candidate_at_equal_relevance_and_type(self) -> None:
        """The status bonus alone. Both notes are `learning`."""
        verified = self._write("learning", "verified", "RankStatusProbe")
        candidate = self._write("learning", "candidate", "RankStatusProbe")
        self._backdate(verified)

        order = self._order("RankStatusProbe")

        self.assertIn(verified["id"], order)
        self.assertIn(candidate["id"], order)
        self.assertLess(
            order.index(verified["id"]),
            order.index(candidate["id"]),
            "verified must outrank candidate at equal relevance, type and "
            "against an unfavourable recency tiebreak",
        )

    def test_finding_outranks_learning_at_equal_relevance_and_status(self) -> None:
        """The type bonus alone. Both notes are `candidate`."""
        finding = self._write("finding", "candidate", "RankTypeProbe")
        learning = self._write("learning", "candidate", "RankTypeProbe")
        self._backdate(finding)

        order = self._order("RankTypeProbe")

        self.assertIn(finding["id"], order)
        self.assertIn(learning["id"], order)
        self.assertLess(
            order.index(finding["id"]),
            order.index(learning["id"]),
            "finding must outrank learning at equal relevance, status and "
            "against an unfavourable recency tiebreak",
        )

    def test_verified_finding_outranks_candidate_learning_at_equal_text(self) -> None:
        """Both bonuses together, still against recency."""
        verified_finding = self._write("finding", "verified", "RankBonusProbe")
        candidate_learning = self._write("learning", "candidate", "RankBonusProbe")
        self._backdate(verified_finding)

        order = self._order("RankBonusProbe")

        self.assertIn(verified_finding["id"], order)
        self.assertIn(candidate_learning["id"], order)
        self.assertLess(
            order.index(verified_finding["id"]),
            order.index(candidate_learning["id"]),
            "verified finding should outrank candidate learning at equal relevance",
        )


if __name__ == "__main__":
    unittest.main()
