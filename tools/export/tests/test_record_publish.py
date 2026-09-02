"""The ledger's publish record had a reader and no writer.

`projector._read_last_source_anchor` honours `{"event": "publish",
"published_tip": ...}` records specifically so the continuity check will not
"silently ignore every publish since" -- its own comment. Nothing wrote one.
The ledger held 32 projection records and zero publish records, so every real
push left the recorded public tip behind the live rail and the NEXT projection
was refused with `ledger/public mismatch`. That is what blocked the v1.1.5
publish.

These tests pin the writer, and pin that it verifies rather than believes: a
record naming a tip that is not on the public rail is a claim, not a receipt.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))

import projector  # noqa: E402
import record_publish  # noqa: E402


class RecordPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ledger = self.root / "export-ledger.jsonl"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(("git", *a), cwd=self.repo, check=True,
                                        capture_output=True)
        run("init", "-q", ".")
        (self.repo / "a.txt").write_text("one\n")
        run("add", ".")
        run("-c", "user.name=T", "-c", "user.email=t@e.invalid", "commit", "-qm", "one")
        self.tip = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=self.repo,
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def _projection(self, public_tip: str) -> None:
        self.ledger.write_text(
            json.dumps({"public_tip": public_tip, "source_sha": "0" * 40}) + "\n",
            encoding="utf-8",
        )

    def test_a_publish_record_moves_the_continuity_anchor(self) -> None:
        """The whole point: the next projection must see the tip we pushed."""
        self._projection("1" * 40)
        record_publish.record_publish(
            ledger_path=self.ledger, root=self.repo, published_tip=self.tip,
            public_ref="HEAD", source_sha="2" * 40, note="test",
        )
        # `_read_last_ledger_entry` is the function the continuity gate calls;
        # it raises `ledger/public mismatch` when this disagrees with the live
        # rail, which is exactly what blocked the v1.1.5 publish.
        entry = projector._read_last_ledger_entry(self.ledger)
        self.assertEqual(entry["public_tip"], self.tip)

    def test_it_refuses_a_tip_that_is_not_on_the_public_rail(self) -> None:
        """A record is a receipt, not a claim. Verify before writing."""
        self._projection("1" * 40)
        with self.assertRaises(record_publish.PublishRecordError):
            record_publish.record_publish(
                ledger_path=self.ledger, root=self.repo, published_tip="3" * 40,
                public_ref="HEAD", source_sha="2" * 40, note="test",
            )
        self.assertEqual(
            len(self.ledger.read_text().strip().splitlines()), 1,
            "a refused record must not be appended",
        )

    def test_the_record_is_marked_as_a_publish_and_keeps_the_rest_intact(self) -> None:
        self._projection("1" * 40)
        record_publish.record_publish(
            ledger_path=self.ledger, root=self.repo, published_tip=self.tip,
            public_ref="HEAD", source_sha="2" * 40, note="v9.9.9 publish",
        )
        lines = self.ledger.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2, "append-only: the projection stays")
        record = json.loads(lines[-1])
        self.assertEqual(record["event"], "publish")
        self.assertEqual(record["published_tip"], self.tip)
        self.assertEqual(record["source_sha"], "2" * 40)
        self.assertEqual(record["note"], "v9.9.9 publish")
        self.assertIn("recorded_at", record)
        self.assertNotIn(
            "public_tip", record,
            "publish records own published_tip; public_tip belongs to projections",
        )


if __name__ == "__main__":
    unittest.main()
