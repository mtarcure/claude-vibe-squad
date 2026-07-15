from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCH_SCRIPT = REPO_ROOT / "bin" / "launch-squad.sh"
CLEARANCE_EXPORT = "'export CHRONO_VAULT_CLEARANCE=restricted'"


class LaunchClearanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = LAUNCH_SCRIPT.read_text(encoding="utf-8").splitlines()

    def test_restricted_clearance_is_wired_to_exactly_three_panes(self) -> None:
        clearance_lines = [
            line.strip()
            for line in self.lines
            if "tmux send-keys" in line and CLEARANCE_EXPORT in line
        ]
        expected = {
            'tmux send-keys -t "${SESSION}:chrono" '
            + CLEARANCE_EXPORT
            + " C-m",
            'tmux send-keys -t "${SESSION}:${GPT_CODEX_WIN}" '
            + CLEARANCE_EXPORT
            + " C-m",
            'tmux send-keys -t "${SESSION}:${CLAUDE_WIN}" '
            + CLEARANCE_EXPORT
            + " C-m",
        }

        self.assertEqual(len(clearance_lines), 3)
        self.assertEqual(set(clearance_lines), expected)
        self.assertFalse(
            any(
                target in line
                for target in ('${GEMINI_WIN}', '${KIMI_WIN}')
                for line in clearance_lines
            )
        )

    def test_clearance_follows_each_pane_auth_command(self) -> None:
        pane_auth = (
            ("${SESSION}:chrono", "MEDIA_AUTH_PREFIX"),
            ("${SESSION}:${GPT_CODEX_WIN}", "AUTH_PREFIX"),
            ("${SESSION}:${CLAUDE_WIN}", "MEDIA_AUTH_PREFIX"),
        )
        for target, prefix in pane_auth:
            with self.subTest(target=target):
                auth = f'tmux send-keys -t "{target}" "${{{prefix}}}" C-m'
                clearance = (
                    f'tmux send-keys -t "{target}" {CLEARANCE_EXPORT} C-m'
                )
                auth_index = self.lines.index(auth)
                self.assertEqual(self.lines[auth_index + 1], clearance)

    def test_shared_auth_prefix_assignments_do_not_embed_clearance(self) -> None:
        for prefix in ("AUTH_PREFIX", "MEDIA_AUTH_PREFIX", "GEMINI_AUTH_PREFIX"):
            with self.subTest(prefix=prefix):
                assignment = next(
                    line for line in self.lines if line.startswith(f"{prefix}=")
                )
                self.assertNotIn("CHRONO_VAULT_CLEARANCE", assignment)


if __name__ == "__main__":
    unittest.main()
