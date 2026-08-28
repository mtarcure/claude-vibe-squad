"""The episodic spool has a production reader and bounded graduation path."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import autocapture  # noqa: E402
import jsonl  # noqa: E402


class JsonlReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="chrono-jsonl-reader-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_reads_object_rows_and_rejects_a_malformed_file(self) -> None:
        path = self.root / "rows.jsonl"
        path.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        self.assertEqual(jsonl.read_objects(path), [{"a": 1}, {"b": 2}])

        path.write_text('{"a": 1}\nnot-json\n', encoding="utf-8")
        with self.assertRaisesRegex(jsonl.JsonlReadError, "invalid JSON"):
            jsonl.read_objects(path)


class SpoolGraduationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(tempfile.mkdtemp(prefix="chrono-spool-vault-"))
        self.spool_root = Path(tempfile.mkdtemp(prefix="chrono-spool-state-"))
        self.mailbox_root = Path(tempfile.mkdtemp(prefix="chrono-spool-mailbox-"))
        for root in (self.vault_root, self.spool_root, self.mailbox_root):
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "spool-reader-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.environment = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_AUTOCAPTURE_DISTILL": "off",
            },
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.spool_patch = mock.patch.object(
            autocapture, "_episodic_root", lambda: self.spool_root
        )
        self.spool_patch.start()
        self.addCleanup(self.spool_patch.stop)
        self.failure_patch = mock.patch.object(
            autocapture,
            "_failure_log_path",
            lambda: self.mailbox_root / "autocapture-failures.jsonl",
        )
        self.failure_patch.start()
        self.addCleanup(self.failure_patch.stop)

    def _row(self, *, task: str, digest: str, body: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "source_task": task,
            "source_artifact_hash": f"sha256:{digest * 64}",
            "response_path": str(self.mailbox_root / f"{task}-response.md"),
            "specialist": "data-extraction-engineer",
            "status": "complete",
            "mode": "research",
            "component": "research",
            "target": "chrono-vault",
            "sensitivity": "internal",
            "captured_at": "2026-08-26T01:02:03Z",
            "raw_title": "Spool graduation preserves reusable extraction evidence",
            "raw_body": body,
        }

    def _spool_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for path in sorted(self.spool_root.glob("*.jsonl")):
            rows.extend(jsonl.read_objects(path))
        return rows

    def _response(self, task: str) -> Path:
        outbox = self.mailbox_root / "departments" / "research" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{task}-response.md"
        path.write_text(
            "---\n"
            f"in_response_to: {json.dumps(task)}\n"
            'specialist: "data-extraction-engineer"\n'
            'status: "complete"\n'
            'mode: "research"\n'
            "---\n\n"
            "The extraction retained seven distinct reusable findings and "
            "preserved a source key for each result so later recall can apply them.\n",
            encoding="utf-8",
        )
        return path

    def test_reader_graduates_one_eligible_missing_row(self) -> None:
        row = self._row(
            task="TASK-2026-08-26-spool-reader",
            digest="a",
            body=(
                "The spool contains a reusable extraction result that is absent "
                "from semantic notes, with provenance retained for later recall."
            ),
        )
        jsonl.append_line(self.spool_root / "2026-08-26.jsonl", row)

        result = autocapture.graduate_spooled_once(seed="reader-test")

        self.assertTrue(result["graduated"], result)
        notes = list((self.vault_root / "notes" / "learning").glob("*.md"))
        self.assertEqual(len(notes), 1)
        note = notes[0].read_text(encoding="utf-8")
        self.assertIn('source_task: "TASK-2026-08-26-spool-reader"', note)
        self.assertIn(f'source_artifact_hash: "sha256:{"a" * 64}"', note)
        self.assertEqual(len(self._spool_rows()), 1, "reader must not consume raw history")

        replay = autocapture.graduate_spooled_once(seed="reader-test")
        self.assertEqual(replay["reason"], "no_eligible_rows")

    def test_refused_rows_remain_raw_and_never_graduate(self) -> None:
        row = self._row(
            task="TASK-2026-08-26-spool-refused",
            digest="b",
            body="Board dispatch was blocked by the controller before work began.",
        )
        jsonl.append_line(self.spool_root / "2026-08-26.jsonl", row)

        result = autocapture.graduate_spooled_once(seed="refused-test")

        self.assertEqual(result["reason"], "no_eligible_rows")
        self.assertEqual(result["refused"], 1)
        self.assertEqual(len(self._spool_rows()), 1)
        self.assertFalse((self.vault_root / "notes" / "learning").exists())

    def test_production_replay_does_not_append_a_second_raw_row(self) -> None:
        path = self._response("TASK-2026-08-26-production-replay")
        first = autocapture.capture_response(str(path))
        replay = autocapture.capture_response(
            str(path), record_replay_event=False
        )

        self.assertTrue(first["captured"], first)
        self.assertEqual(replay["reason"], "duplicate")
        self.assertEqual(len(self._spool_rows()), 1)

    def test_failed_row_replay_promotes_without_appending_again(self) -> None:
        path = self._response("TASK-2026-08-26-production-retry")

        def broken(fields, context):
            raise autocapture.DistillationFailed("lane unavailable")

        with mock.patch.dict(os.environ, {"CHRONO_AUTOCAPTURE_DISTILL": "on"}):
            failed = autocapture.capture_response(str(path), distiller=broken)
        self.assertTrue(str(failed["reason"]).startswith("distillation_failed:"))
        self.assertEqual(len(self._spool_rows()), 1)

        recovered = autocapture.capture_response(
            str(path), record_replay_event=False
        )
        self.assertTrue(recovered["captured"], recovered)
        self.assertEqual(len(self._spool_rows()), 1)

    def test_main_invokes_the_reader_on_a_production_duplicate(self) -> None:
        with mock.patch.object(
            autocapture,
            "capture_response",
            return_value={"captured": False, "note_id": "mem-existing", "reason": "duplicate"},
        ) as capture_mock:
            with mock.patch.object(autocapture, "_spool_reader_due", return_value=True):
                with mock.patch.object(
                    autocapture,
                    "graduate_spooled_once",
                    return_value={"graduated": False, "reason": "no_eligible_rows"},
                ) as reader_mock:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(autocapture.main(["TASK-x-response.md"]), 0)
        capture_mock.assert_called_once_with(
            "TASK-x-response.md", record_replay_event=False
        )
        reader_mock.assert_called_once_with(seed="TASK-x-response.md")


if __name__ == "__main__":
    unittest.main()
