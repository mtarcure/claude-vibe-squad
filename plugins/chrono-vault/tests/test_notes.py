from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import notes  # noqa: E402


def parse_frontmatter(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("missing opening frontmatter delimiter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError("missing closing frontmatter delimiter") from exc

    parsed: dict[str, object] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(": ")
        if not separator:
            raise AssertionError(f"invalid frontmatter line: {line!r}")
        parsed[key] = json.loads(value)
    return parsed


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-notes-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "notes-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_valid_finding_writes_canonical_note(self) -> None:
        result = notes.record(
            "finding",
            {
                "target": "push-chain",
                "attack_class": "forged-inbound",
                "program": "bounty",
                "component": "executor",
            },
        )

        self.assertRegex(result["id"], r"^mem-[0-9a-f]{12}$")
        self.assertFalse(result["indexed"])
        self.assertTrue(result["index_dirty"])

        note_path = Path(result["path"])
        self.assertTrue(note_path.is_file())
        self.assertEqual(
            note_path.parent,
            self.vault_root / "notes" / "finding",
        )

        frontmatter = parse_frontmatter(note_path)
        self.assertEqual(frontmatter["id"], result["id"])
        self.assertEqual(frontmatter["type"], "finding")
        self.assertEqual(frontmatter["status"], "candidate")
        self.assertEqual(frontmatter["sensitivity"], "internal")
        self.assertEqual(frontmatter["revision"], 1)
        self.assertEqual(frontmatter["schema_version"], 1)
        self.assertEqual(frontmatter["target"], "push-chain")
        self.assertEqual(frontmatter["attack_class"], "forged-inbound")
        self.assertRegex(
            frontmatter["evidence_refs"][-1],
            r"^note-content-sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(stat.S_IMODE(note_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(note_path.parent.stat().st_mode), 0o700)

    def test_missing_required_field_raises_before_creating_notes_dir(self) -> None:
        with self.assertRaises(notes.SchemaError):
            notes.record("finding", {"attack_class": "forged-inbound"})
        self.assertFalse((self.vault_root / "notes").exists())

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(notes.SchemaError):
            notes.record(
                "finding",
                {
                    "target": "push-chain",
                    "attack_class": "forged-inbound",
                    "unknown": "nope",
                },
            )

    def test_caller_path_dest_and_id_are_ignored(self) -> None:
        escaped = self.vault_root / "caller-selected.md"
        result = notes.record(
            "learning",
            {
                "target": "dispatch",
                "attack_class": "operational",
                "id": "mem-callerchosen",
                "path": str(escaped),
                "dest": str(escaped),
            },
        )

        self.assertNotEqual(result["id"], "mem-callerchosen")
        self.assertRegex(result["id"], r"^mem-[0-9a-f]{12}$")
        self.assertEqual(
            Path(result["path"]).parent,
            self.vault_root / "notes" / "learning",
        )
        self.assertFalse(escaped.exists())

    def test_bad_enums_raise_schema_error(self) -> None:
        cases = (
            ("unknown", {"target": "t", "attack_class": "a"}),
            (
                "finding",
                {"target": "t", "attack_class": "a", "status": "draft"},
            ),
            (
                "finding",
                {"target": "t", "attack_class": "a", "sensitivity": "public"},
            ),
            (
                "finding",
                {"target": "t", "attack_class": "a", "type": "attempt"},
            ),
            (
                "finding",
                {"target": "t", "attack_class": "a", "status": ["candidate"]},
            ),
        )
        for note_type, fields in cases:
            with self.subTest(note_type=note_type, fields=fields):
                with self.assertRaises(notes.SchemaError):
                    notes.record(note_type, fields)

    def test_symlinked_notes_directory_cannot_escape_vault(self) -> None:
        outside = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-notes-outside-"))
        )
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (self.vault_root / "notes").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(notes.NoteWriteError):
            notes.record(
                "finding",
                {"target": "target", "attack_class": "symlink-escape"},
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_yaml_control_text_round_trips_as_quoted_data(self) -> None:
        injected = "line one\n---\n!!python/object:danger"
        result = notes.record(
            "attempt",
            {"target": injected, "attack_class": "prompt-injection"},
        )
        frontmatter = parse_frontmatter(Path(result["path"]))
        self.assertEqual(frontmatter["target"], injected)

    def test_semantic_hash_is_stable_across_field_order(self) -> None:
        first = notes.record(
            "finding",
            {
                "target": "target-a",
                "attack_class": "class-a",
                "aliases": ["alpha"],
            },
        )
        second = notes.record(
            "finding",
            {
                "aliases": ["alpha"],
                "attack_class": "class-a",
                "target": "target-a",
            },
        )

        first_hash = parse_frontmatter(Path(first["path"]))["evidence_refs"][-1]
        second_hash = parse_frontmatter(Path(second["path"]))["evidence_refs"][-1]
        self.assertTrue(re.fullmatch(r"note-content-sha256:[0-9a-f]{64}", first_hash))
        self.assertEqual(first_hash, second_hash)


if __name__ == "__main__":
    unittest.main()
