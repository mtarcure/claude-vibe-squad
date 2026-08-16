"""Regression coverage for the outbox watcher's strict flat frontmatter parser."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
WATCHER = REPO / "bin" / "outbox-watcher.sh"
TASK_ID = "TASK-2026-08-11-0570-envelope-parser-test"


class OutboxWatcherFrontmatterTests(unittest.TestCase):
    def _run_watcher(
        self,
        frontmatter_rows: list[str],
        *,
        reconciler_exit: int = 70,
    ) -> tuple[subprocess.CompletedProcess[str], str, bool, bool, bool, bool, str]:
        with tempfile.TemporaryDirectory(prefix="outbox-frontmatter-") as tmp:
            root = Path(tmp)
            vault = root / "vault"
            bin_dir = vault / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "outbox-watcher.sh").symlink_to(WATCHER)

            marker = root / "reconciler-called"
            reconciler = bin_dir / "registry-reconciler.sh"
            reconciler.write_text(
                "#!/bin/bash\n"
                "printf 'called\\n' >> \"$WATCHER_RECONCILER_MARKER\"\n"
                "exit \"$WATCHER_RECONCILER_EXIT\"\n",
                encoding="utf-8",
            )
            reconciler.chmod(0o755)

            state_dir = vault / "_state"
            state_dir.mkdir()
            department = vault / "departments" / "security"
            for subdirectory in ("inbox", "active", "outbox", "archive"):
                (department / subdirectory).mkdir(parents=True)

            packet = department / "active" / f"{TASK_ID}.md"
            packet.write_text(
                "---\n"
                f"id: {TASK_ID}\n"
                "to_model: gpt-codex\n"
                "specialist: systems-engineer\n"
                "---\n\npacket body\n",
                encoding="utf-8",
            )
            response = department / "outbox" / f"{TASK_ID}-response.md"
            response.write_text(
                "---\n" + "\n".join(frontmatter_rows) + "\n---\n\nfinished work.\n",
                encoding="utf-8",
            )
            artifact = vault / "result.md"
            artifact.write_text("completed deliverable\n", encoding="utf-8")

            fakebin = root / "fakebin"
            fakebin.mkdir()
            fswatch = fakebin / "fswatch"
            fswatch.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            fswatch.chmod(0o755)

            environment = {
                **os.environ,
                "VAULT_ROOT": str(vault),
                "SQUAD_SESSION": "none",
                "TMUX_BIN": "/nonexistent/tmux",
                "RESPONSE_MIN_AGE_SECONDS": "0",
                "WATCHER_RECONCILER_EXIT": str(reconciler_exit),
                "WATCHER_RECONCILER_MARKER": str(marker),
                "PATH": f"{fakebin}:{os.environ['PATH']}",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            environment.pop("CHRONO_VAULT_ROOT", None)
            result = subprocess.run(
                ["bash", str(bin_dir / "outbox-watcher.sh"), "security"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            output = result.stdout + result.stderr
            queue_path = state_dir / "chrono-queue.md"
            queue = queue_path.read_text(encoding="utf-8") if queue_path.exists() else ""
            return (
                result,
                output,
                packet.is_file(),
                response.is_file(),
                artifact.is_file(),
                marker.is_file(),
                queue,
            )

    @staticmethod
    def _required_rows() -> list[str]:
        return [
            f"id: {TASK_ID}-response",
            f"in_response_to: {TASK_ID}",
            "from: gpt-codex",
            "to: chrono",
            "type: RESULT",
        ]

    def test_nested_key_names_key_and_lines_and_holds_response(self) -> None:
        rows = self._required_rows() + [
            "status: complete",
            "reviews:",
            "  reviewer: approve",
            "return_artifact: result.md",
        ]

        result, output, packet_exists, response_exists, artifact_exists, called, _ = (
            self._run_watcher(rows)
        )

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("frontmatter key 'reviews' at line 8", output)
        self.assertIn("nested content at line 9", output)
        self.assertIn("flat scalar values are required", output)
        self.assertIn("held in outbox", output)
        self.assertTrue(packet_exists, output)
        self.assertTrue(response_exists, output)
        self.assertTrue(artifact_exists, output)
        self.assertFalse(called, output)

    def test_duplicate_key_is_named_and_held(self) -> None:
        rows = self._required_rows() + [
            "status: complete",
            "status: blocked",
            "return_artifact: result.md",
        ]

        result, output, packet_exists, response_exists, artifact_exists, called, _ = (
            self._run_watcher(rows)
        )

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("frontmatter key 'status' is duplicated at line 8", output)
        self.assertIn("first declared at line 7", output)
        self.assertIn("held in outbox", output)
        self.assertTrue(packet_exists, output)
        self.assertTrue(response_exists, output)
        self.assertTrue(artifact_exists, output)
        self.assertFalse(called, output)

    def test_key_text_and_colon_space_inside_scalar_are_preserved(self) -> None:
        rows = self._required_rows() + [
            "note: status: blocked: still scalar",
            "status: complete",
            "return_artifact: result.md",
        ]

        (
            result,
            output,
            packet_exists,
            response_exists,
            artifact_exists,
            called,
            queue,
        ) = self._run_watcher(rows, reconciler_exit=0)

        self.assertEqual(result.returncode, 0, output)
        self.assertTrue(called, output)
        self.assertTrue(packet_exists, output)
        self.assertTrue(response_exists, output)
        self.assertTrue(artifact_exists, output)
        self.assertIn(f" | complete | security/{TASK_ID} |", queue)
        self.assertNotIn("held in outbox", output)


if __name__ == "__main__":
    unittest.main()
