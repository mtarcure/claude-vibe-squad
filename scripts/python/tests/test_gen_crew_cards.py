from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts/python/gen_crew_cards.py"
SPEC = importlib.util.spec_from_file_location("gen_crew_cards", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class CrewCardFreshnessTests(unittest.TestCase):
    def fixture_card(self, directory: Path) -> Path:
        path = directory / "systems-engineer.card"
        path.write_text(
            "name: Reiner\n"
            "anime: Attack on Titan\n"
            "department: coding\n"
            "motif: gear\n"
            "---idle---\n"
            "stale body\n"
            "---active---\n"
            "stale body\n",
            encoding="utf-8",
        )
        return path

    def test_check_fails_when_tracked_card_differs_from_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cards = Path(directory)
            path = self.fixture_card(cards)
            with (
                mock.patch.object(module, "CARDS", cards),
                mock.patch.object(
                    module, "FACES", {"systems-engineer": module.FACES["systems-engineer"]}
                ),
                mock.patch.object(
                    module,
                    "TAGLINES",
                    {"systems-engineer": module.TAGLINES["systems-engineer"]},
                ),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                self.assertFalse(module.check_cards())

            self.assertIn("FAIL crew-card", stderr.getvalue())
            self.assertIn("stale body", stderr.getvalue())
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[5], "stale body")

    def test_check_passes_without_writing_when_card_matches_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cards = Path(directory)
            path = self.fixture_card(cards)
            with (
                mock.patch.object(module, "CARDS", cards),
                mock.patch.object(
                    module, "FACES", {"systems-engineer": module.FACES["systems-engineer"]}
                ),
                mock.patch.object(
                    module,
                    "TAGLINES",
                    {"systems-engineer": module.TAGLINES["systems-engineer"]},
                ),
            ):
                expected = module.build("systems-engineer", write=False)
                self.assertIsNotNone(expected)
                path.write_text(expected, encoding="utf-8")
                before = path.read_bytes()
                self.assertTrue(module.check_cards())
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
