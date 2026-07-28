from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from role_context_compiler import (  # noqa: E402
    RoleContextError,
    compile_role_context,
    verify_role_context,
)


class RoleContextCompilerTests(unittest.TestCase):
    def test_role_context_is_deterministic_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            role = root / "systems-engineer.md"
            overlay = root / "codex.md"
            role.write_text("# Systems Engineer\r\n\r\nBuild carefully.\r\n", encoding="utf-8")
            overlay.write_text("# Codex overlay\n\nUse the native lane.\n", encoding="utf-8")

            first = compile_role_context(
                role,
                overlay,
                specialist="systems-engineer",
                lane="gpt-codex",
                mode_profile="project",
            )
            second = compile_role_context(
                role,
                overlay,
                specialist="systems-engineer",
                lane="gpt-codex",
                mode_profile="project",
            )

            self.assertEqual(first, second)
            self.assertEqual(first.sha256, second.sha256)
            self.assertNotIn("\r", first.prompt)
            self.assertIs(verify_role_context(first), first)

    def test_role_context_hash_changes_with_role_or_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            role = root / "role.md"
            overlay = root / "overlay.md"
            role.write_text("canonical\n", encoding="utf-8")
            overlay.write_text("overlay-v1\n", encoding="utf-8")
            before = compile_role_context(role, overlay, specialist="s", lane="codex")

            overlay.write_text("overlay-v2\n", encoding="utf-8")
            after = compile_role_context(role, overlay, specialist="s", lane="codex")

            self.assertNotEqual(before.sha256, after.sha256)
            with self.assertRaisesRegex(RoleContextError, "hash"):
                verify_role_context(before.__class__(**{**before.__dict__, "prompt": "tampered"}))

    def test_role_context_rejects_binary_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            role = root / "role.md"
            overlay = root / "overlay.md"
            role.write_bytes(b"bad\x00role")
            overlay.write_text("overlay\n", encoding="utf-8")

            with self.assertRaises(RoleContextError):
                compile_role_context(role, overlay, specialist="s", lane="codex")


if __name__ == "__main__":
    unittest.main()
