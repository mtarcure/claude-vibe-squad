from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import index as vault_index  # noqa: E402
import notes  # noqa: E402


def _concurrent_upsert(vault_root: str, note: dict) -> None:
    os.environ["CHRONO_VAULT_ROOT"] = vault_root
    vault_index.upsert(note)


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-index-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "index-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _record(self, token: str) -> dict:
        return notes.record(
            "finding",
            {
                "title": f"{token} forged payload",
                "body": f"The {token} identifier appears in the note body.",
                "target": "push-chain",
                "component": "executor",
                "attack_class": "forged-inbound",
                "aliases": [f"{token}-alias"],
                "keywords": ["bridge", "payload"],
                "evidence_refs": ["artifact:fixture"],
            },
        )

    @property
    def db_path(self) -> Path:
        return self.vault_root / "index" / "kg.db"

    def _rows(self) -> list[tuple[str, str]]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return list(
                connection.execute(
                    "SELECT id, content_hash FROM meta ORDER BY id"
                )
            )

    def test_record_persists_body_and_indexes_title_token(self) -> None:
        result = self._record("ZephyrToken")

        self.assertTrue(result["indexed"])
        self.assertFalse(result["index_dirty"])
        note_text = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn('title: "ZephyrToken forged payload"', note_text)
        self.assertTrue(
            note_text.endswith("The ZephyrToken identifier appears in the note body.\n")
        )

        with closing(sqlite3.connect(self.db_path)) as connection:
            match_count = connection.execute(
                "SELECT count(*) FROM notes_fts WHERE notes_fts MATCH ?",
                ("ZephyrToken",),
            ).fetchone()[0]
            fts_columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(notes_fts)")
            ]
            weights = connection.execute(
                "SELECT value FROM config WHERE key='bm25_weights'"
            ).fetchone()[0]
            schema_version = connection.execute(
                "SELECT value FROM config WHERE key='index_schema_version'"
            ).fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(match_count, 1)
        self.assertIn("keywords", fts_columns)
        self.assertNotIn("tags", fts_columns)
        self.assertEqual(len(json.loads(weights)), 8)
        self.assertEqual(int(schema_version), vault_index.INDEX_SCHEMA_VERSION)
        self.assertEqual(user_version, vault_index.INDEX_SCHEMA_VERSION)
        self.assertEqual(journal_mode, "wal")
        self.assertEqual(stat.S_IMODE(self.db_path.stat().st_mode), 0o600)

    def test_stale_tags_schema_rebuilds_from_markdown_with_new_generation(self) -> None:
        result = self._record("SchemaBumpToken")
        generation_before = vault_index.index_generation()
        rows_before = self._rows()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("DROP TABLE notes_fts")
            connection.execute(
                """
                CREATE VIRTUAL TABLE notes_fts USING fts5(
                    title, body, aliases, target, component, attack_class,
                    tags, evidence_summary, tokenize='unicode61'
                )
                """
            )
            connection.execute(
                "INSERT INTO notes_fts(rowid, title, tags) VALUES(?,?,?)",
                (1, "legacy row", "legacy-tag"),
            )
            connection.execute(
                "INSERT OR REPLACE INTO config(key, value) "
                "VALUES('index_schema_version', '1')"
            )
            connection.execute("PRAGMA user_version=1")
            connection.commit()

        report = vault_index.sync_index()

        self.assertEqual(report["generation"], generation_before + 1)
        self.assertEqual(self._rows(), rows_before)
        with closing(sqlite3.connect(self.db_path)) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(notes_fts)")
            ]
            match = connection.execute(
                "SELECT rowid FROM notes_fts WHERE keywords MATCH ?",
                ("bridge",),
            ).fetchone()
            indexed_id = connection.execute(
                "SELECT id FROM meta WHERE docid=?",
                (match[0],),
            ).fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("keywords", columns)
        self.assertNotIn("tags", columns)
        self.assertEqual(user_version, vault_index.INDEX_SCHEMA_VERSION)
        self.assertEqual(indexed_id, result["id"])

    def test_rebuild_after_index_deletion_is_deterministic(self) -> None:
        self._record("FirstToken")
        self._record("SecondToken")
        before = self._rows()

        self.db_path.unlink()
        report = vault_index.rebuild_index()

        self.assertEqual(report["indexed"], 2)
        self.assertEqual(report["quarantined"], [])
        self.assertEqual(self._rows(), before)
        self.assertGreaterEqual(vault_index.index_generation(), 1)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA journal_mode").fetchone()[0],
                "wal",
            )

    def test_malformed_note_is_quarantined_and_not_indexed(self) -> None:
        good = self._record("GoodToken")
        malformed = Path(good["path"]).parent / "malformed.md"
        malformed.write_text("not frontmatter\n", encoding="utf-8")

        report = vault_index.sync_index()

        quarantined_paths = {entry["path"] for entry in report["quarantined"]}
        self.assertIn(str(malformed), quarantined_paths)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM meta").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM quarantine WHERE path=?",
                    (str(malformed),),
                ).fetchone()[0],
                1,
            )

    def test_two_process_upsert_has_no_loss_or_corruption(self) -> None:
        first = self._record("ConcurrentOne")
        second = self._record("ConcurrentTwo")
        first_note = vault_index._parse_note(Path(first["path"]))
        second_note = vault_index._parse_note(Path(second["path"]))
        self.db_path.unlink()

        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(
                target=_concurrent_upsert,
                args=(str(self.vault_root), note),
            )
            for note in (first_note, second_note)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
            self.assertEqual(process.exitcode, 0)

        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM meta").fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )

    def test_index_failure_preserves_note_and_marks_dirty(self) -> None:
        with mock.patch.object(
            vault_index,
            "upsert",
            side_effect=sqlite3.OperationalError("simulated index failure"),
        ):
            result = self._record("FailureToken")

        self.assertTrue(Path(result["path"]).is_file())
        self.assertFalse(result["indexed"])
        self.assertTrue(result["index_dirty"])

    def test_preplanted_database_symlink_is_rejected(self) -> None:
        index_dir = self.vault_root / "index"
        index_dir.mkdir(mode=0o700)
        outside_dir = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-index-outside-"))
        )
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        outside = outside_dir / "outside.db"
        outside.write_bytes(b"untouched")
        self.db_path.symlink_to(outside)

        result = self._record("SymlinkToken")

        self.assertFalse(result["indexed"])
        self.assertTrue(result["index_dirty"])
        self.assertEqual(outside.read_bytes(), b"untouched")

    def test_rebuild_checkpoint_failure_preserves_old_index(self) -> None:
        self._record("PreservedToken")
        before = self._rows()
        real_checkpoint = vault_index._checkpoint

        def fail_existing_checkpoint(connection, label):
            if label == "existing index":
                raise vault_index.IndexError("simulated busy WAL")
            return real_checkpoint(connection, label)

        with mock.patch.object(
            vault_index,
            "_checkpoint",
            side_effect=fail_existing_checkpoint,
        ):
            with self.assertRaises(vault_index.IndexError):
                vault_index.rebuild_index()

        self.assertEqual(self._rows(), before)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )


if __name__ == "__main__":
    unittest.main()
