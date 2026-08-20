"""Regression coverage: restart replay must not re-queue archived work.

Plan B Task 9. scan_existing_responses() (bin/outbox-watcher.sh) replays every
existing response file on watcher start so nothing that landed while the
watcher was down is stranded. But bin/chrono-queue-backfill.sh separately
moves settled entries out of _state/chrono-queue.md into
_state/chrono-queue-handled.md, and by the time a task's response file is
replayed its registry entry may have been pruned, so
registry-reconciler.sh no longer reports it "already-settled". Without a
check against chrono-queue-handled.md, outbox-watcher.sh's fallback path
(bin/outbox-watcher.sh:585, "reconciler found no settled registry entry")
re-appends the archived task to chrono-queue.md on every restart -- this was
measured live growing the queue 233 -> 242 lines, 8 of which were tasks
already archived by the backfill.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
WATCHER = REPO / "bin" / "outbox-watcher.sh"
TASK_ID = "TASK-2026-08-17-0900-replay-requeue-test"


class OutboxWatcherReplayRequeueTests(unittest.TestCase):
    def _run_watcher(
        self, *, handled_lines: list[str] | None = None
    ) -> tuple[subprocess.CompletedProcess[str], str, str]:
        with tempfile.TemporaryDirectory(prefix="outbox-replay-") as tmp:
            root = Path(tmp)
            vault = root / "vault"
            bin_dir = vault / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "outbox-watcher.sh").symlink_to(WATCHER)

            marker = root / "reconciler-called"
            reconciler = bin_dir / "registry-reconciler.sh"
            # Exit 0 with no "reconciled"/"already-settled"/etc. keyword in
            # stdout reproduces the live scenario the report measured:
            # registry-reconciler.sh no longer finds a settled registry entry
            # for an already-archived task (its active-tasks.json entry was
            # pruned), so reconciler_handled stays 0 and outbox-watcher.sh
            # falls into the notification-queue fallback -- the exact path
            # that re-queued archived work on restart.
            reconciler.write_text(
                "#!/bin/bash\n"
                "printf 'called\\n' >> \"$WATCHER_RECONCILER_MARKER\"\n"
                "exit 0\n",
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
                "---\n"
                f"id: {TASK_ID}-response\n"
                f"in_response_to: {TASK_ID}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "---\n\nfinished work.\n",
                encoding="utf-8",
            )

            if handled_lines is not None:
                handled_path = state_dir / "chrono-queue-handled.md"
                handled_path.write_text(
                    "\n".join(handled_lines) + "\n", encoding="utf-8"
                )

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
            return result, output, queue

    def test_already_handled_task_is_not_requeued_on_replay(self) -> None:
        task_ref = f"security/{TASK_ID}"
        handled_line = f"2026-08-16T00:00:00Z | complete | {task_ref} | archived by backfill"
        result, output, queue = self._run_watcher(handled_lines=[handled_line])

        self.assertEqual(result.returncode, 0, output)
        self.assertIn(
            f"skipping fallback queue: {task_ref} already archived in "
            "chrono-queue-handled.md",
            output,
        )
        self.assertNotIn(task_ref, queue)
        # A fully-drained restart -- everything already archived -- must add
        # zero lines: chrono-queue.md is never even created.
        self.assertEqual(queue, "")

    def test_not_yet_handled_task_still_falls_back_to_queue(self) -> None:
        # No chrono-queue-handled.md at all: the pre-existing, still-open
        # fallback path must be unaffected by the new archived-task check.
        result, output, queue = self._run_watcher(handled_lines=None)

        task_ref = f"security/{TASK_ID}"
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("skipping fallback queue", output)
        self.assertIn(f" | complete | {task_ref} |", queue)

    def test_handled_file_present_but_task_not_in_it_still_queues(self) -> None:
        # chrono-queue-handled.md exists (other tasks were archived) but does
        # not mention this task: the check must be a precise per-task match,
        # not "any handled file present => skip everything".
        other_ref = "security/TASK-2026-08-01-0001-unrelated"
        handled_line = f"2026-08-01T00:00:00Z | complete | {other_ref} | unrelated archived task"
        result, output, queue = self._run_watcher(handled_lines=[handled_line])

        task_ref = f"security/{TASK_ID}"
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("skipping fallback queue", output)
        self.assertIn(f" | complete | {task_ref} |", queue)


if __name__ == "__main__":
    unittest.main()
