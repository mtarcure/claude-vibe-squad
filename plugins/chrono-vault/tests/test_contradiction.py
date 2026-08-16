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


class ContradictionDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-contradiction-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "contradiction-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_VAULT_AUDIT_DIR": str(self.vault_root / "audit"),
                "CHRONO_VAULT_CLEARANCE": "internal",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("CHRONO_VAULT_CONTEXT", None)

    def _record(self, title: str, body: str) -> dict:
        return notes.record(
            "finding",
            {
                "title": title,
                "body": body,
                "target": "example-chain",
                "component": "bridge-executor",
                "attack_class": "authorization",
            },
        )

    def test_second_active_note_on_same_subject_is_flagged(self) -> None:
        original = self._record(
            "Executor requires an authorized signer",
            "Only an authorized signer can invoke the executor.",
        )
        self._record(
            "Executor accepts an unauthorized signer",
            "An unauthorized signer can invoke the same executor.",
        )

        events = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.vault_root / "audit" / "contradiction").glob(
                "evt-*.json"
            )
        ]
        flagged = [event for event in events if event["result"] == "flagged"]

        self.assertEqual(len(events), 2)
        self.assertEqual(len(flagged), 1)
        self.assertTrue(flagged[0]["detection_ok"])
        self.assertEqual(flagged[0]["relationship"], "new")
        self.assertEqual(flagged[0]["returned_note_ids"], [original["id"]])
        self.assertEqual(flagged[0]["unreconciled_note_ids"], [original["id"]])


if __name__ == "__main__":
    unittest.main()
