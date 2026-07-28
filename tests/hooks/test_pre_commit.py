from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pre-commit"


class PreCommitLeakGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="chrono-hook-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self._git("init", "-q")
        self._git("config", "user.name", "Hook Test")
        self._git("config", "user.email", "hook@example.invalid")

    def _git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            check=check,
            capture_output=True,
            text=True,
        )

    def _stage(self, relative: str, content: bytes, *, force: bool = False) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        arguments = ["add"]
        if force:
            arguments.append("-f")
        arguments.extend(["--", relative])
        self._git(*arguments)

    def _run_hook(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(HOOK)],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_restricted_frontmatter_is_refused_but_internal_is_allowed(self) -> None:
        self._stage(
            "restricted.md",
            b'---\nsensitivity: "restricted"\n---\nprivate\n',
        )
        blocked = self._run_hook()
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("restricted sensitivity", blocked.stderr)

        self._git("reset", "-q")
        self._stage("internal.md", b"---\nsensitivity: internal\n---\nsafe\n")
        allowed = self._run_hook()
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_database_bounty_and_phantom_paths_are_refused(self) -> None:
        cases = (
            ("nested/kg.db", b"SQLite format 3\x00"),
            ("nested/state.db-wal", b"binary\x00data"),
            ("_state/bounty/report.md", b"private bounty"),
            ("x/${CHRONO_VAULT_ROOT}/note.md", b"phantom vault"),
        )
        for relative, content in cases:
            with self.subTest(path=relative):
                self._git("reset", "-q")
                self._stage(relative, content, force=True)
                blocked = self._run_hook()
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("BLOCKED", blocked.stderr)

    def test_normal_file_and_send_task_without_auto_snapshot_are_allowed(self) -> None:
        self._stage("normal.txt", b"normal public content\n")
        normal = self._run_hook()
        self.assertEqual(normal.returncode, 0, normal.stderr)

        self._git("reset", "-q")
        self._stage(
            "bin/send-task.sh",
            b"#!/bin/bash\nset -uo pipefail\necho dispatch\n",
        )
        send_task = self._run_hook()
        self.assertEqual(send_task.returncode, 0, send_task.stderr)

    def test_hook_reads_staged_blob_not_unstaged_worktree(self) -> None:
        self._stage("partial.md", b"---\nsensitivity: internal\n---\nsafe\n")
        (self.repo / "partial.md").write_text(
            "---\nsensitivity: restricted\n---\nworking tree only\n",
            encoding="utf-8",
        )

        result = self._run_hook()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gitignore_contains_defense_in_depth_patterns(self) -> None:
        lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("_state/bounty/**", lines)
        self.assertIn("**/kg.db*", lines)
        self.assertIn("**/*.db-wal", lines)
        self.assertIn("**/*.db-shm", lines)
        self.assertIn("**/${CHRONO_VAULT_ROOT}/", lines)


if __name__ == "__main__":
    unittest.main()
