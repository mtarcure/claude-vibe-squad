from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "chrono-vault"
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "python"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

import clearance  # noqa: E402
import verification_contract  # noqa: E402


def _documented_modes() -> frozenset[str]:
    modes: set[str] = set()
    for path in sorted((REPO_ROOT / "shared" / "modes").glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "---":
            raise AssertionError(f"mode document has no frontmatter: {path}")
        try:
            end = lines.index("---", 1)
        except ValueError as exc:
            raise AssertionError(
                f"mode document has unterminated frontmatter: {path}"
            ) from exc
        names = [
            line.partition(":")[2].strip()
            for line in lines[1:end]
            if line.startswith("name:")
        ]
        if names != [path.stem]:
            raise AssertionError(
                f"mode document name must match its filename: {path}"
            )
        modes.add(names[0])
    if not modes:
        raise AssertionError("shared/modes contains no named mode documents")
    return frozenset(modes)


def _context(mode: str) -> dict[str, object]:
    return {
        "schema": clearance.CONTEXT_SCHEMA,
        "task_id": "TASK-2026-08-26-2250-w8b",
        "attempt_id": "d-abec618ffba249f9b5058c3c216179c7",
        "generation": 1,
        "mode": mode,
        "aperture": "default",
        "focus": None,
        "engagement_start": "2026-08-26T22:50:00Z",
    }


class ModeVocabularyTests(unittest.TestCase):
    def test_runtime_allowlists_match_the_canonical_mode_documents(self) -> None:
        documented = _documented_modes()
        self.assertEqual(clearance.MEMORY_ENGAGEMENT_MODES, documented)
        self.assertEqual(verification_contract.SUPPORTED_TYPED_MODES, documented)

    def test_every_documented_mode_has_a_valid_memory_context(self) -> None:
        for mode in sorted(_documented_modes()):
            with self.subTest(mode=mode):
                self.assertEqual(
                    clearance.validate_memory_context(_context(mode))["mode"],
                    mode,
                )

    def test_unknown_mode_diagnostic_names_the_offending_value(self) -> None:
        unknown = "chronoz_mode_never_7f3a"
        with self.assertRaises(clearance.ClearanceError) as denied:
            clearance.validate_memory_context(_context(unknown))
        self.assertEqual(
            str(denied.exception),
            "unsupported memory engagement mode "
            "'chronoz_mode_never_7f3a'; expected one of: bounty, project",
        )


if __name__ == "__main__":
    unittest.main()
