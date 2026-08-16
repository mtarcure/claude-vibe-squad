#!/usr/bin/env python3
"""Integration coverage for the registry-backed headless completion notifier."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import registry  # noqa: E402


NOTIFIER = ROOT / "bin" / "board-notify.sh"
TERMINAL_STATES = sorted(registry.DEFERRED_STATUSES | registry.TERMINAL_STATUSES)


class BoardNotifyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="board-notify-")
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name)
        (self.vault / "_state").mkdir()
        (self.vault / "scripts").mkdir()
        (self.vault / "scripts" / "python").symlink_to(
            PYTHON_DIR, target_is_directory=True
        )
        self.registry_path = self.vault / "_state" / "active-tasks.json"

    def write_registry(self, entries: dict[str, dict[str, str]]) -> None:
        temporary = self.registry_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(entries), encoding="utf-8")
        temporary.replace(self.registry_path)

    @staticmethod
    def read_until(
        process: subprocess.Popen[str], predicate, timeout: float = 5
    ) -> list[str]:
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process.poll() is None:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    lines.append(line.rstrip())
                    if predicate(lines):
                        break
        return lines

    def test_reports_every_canonical_terminal_transition_and_fast_task(self) -> None:
        tasks = {
            f"TASK-2099-01-01-{index:04d}-notify": {"status": "in-flight"}
            for index, _ in enumerate(TERMINAL_STATES, start=1)
        }
        historical = "TASK-2099-01-01-9000-historical"
        tasks[historical] = {"status": "complete"}
        self.write_registry(tasks)

        artifact_task = next(iter(tasks))
        artifact = self.vault / "_state" / "results" / "notified.md"
        artifact.parent.mkdir()
        artifact.write_text("promoted\n", encoding="utf-8")
        packet_dir = self.vault / "departments" / "coding" / "active"
        packet_dir.mkdir(parents=True)
        (packet_dir / f"{artifact_task}.md").write_text(
            "---\n"
            f"id: {artifact_task}\n"
            "return_artifact: _state/results/notified.md\n"
            "---\n",
            encoding="utf-8",
        )

        environment = {
            **os.environ,
            "VAULT_ROOT": str(self.vault),
            "BOARD_NOTIFY_INTERVAL": "0.05",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        process = subprocess.Popen(
            ["bash", str(NOTIFIER)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            startup = self.read_until(
                process,
                lambda lines: any("watching registry" in line for line in lines),
            )
            self.assertTrue(startup, process.stderr.read() if process.poll() else "")

            transitioned = {
                task_id: {"status": status}
                for task_id, status in zip(
                    (task for task in tasks if task != historical), TERMINAL_STATES
                )
            }
            transitioned[historical] = {"status": "complete"}
            between_polls = "TASK-2099-01-01-9999-between-polls"
            transitioned[between_polls] = {"status": "complete"}
            self.write_registry(transitioned)

            expected = len(TERMINAL_STATES) + 1
            output = self.read_until(
                process,
                lambda lines: (
                    sum(line.startswith("task=") for line in lines) >= expected
                ),
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

        task_lines = [line for line in output if line.startswith("task=")]
        self.assertEqual(len(task_lines), expected, "\n".join(startup + output))
        for task_id, status in (
            item for item in transitioned.items() if item[0] != historical
        ):
            expected_artifact = "yes" if task_id == artifact_task else "no"
            self.assertIn(
                f"task={task_id} status={status['status']} artifact={expected_artifact}",
                task_lines,
            )
        self.assertFalse(any(historical in line for line in task_lines))

    def test_source_uses_registry_view_without_raw_registry_access(self) -> None:
        source = NOTIFIER.read_text(encoding="utf-8")
        self.assertIn("registry.registry_view()", source)
        self.assertNotIn("active-tasks.json", source)
        self.assertNotIn("json.load", source)
        self.assertNotIn("outbox-watcher.sh", source)


if __name__ == "__main__":
    unittest.main()
