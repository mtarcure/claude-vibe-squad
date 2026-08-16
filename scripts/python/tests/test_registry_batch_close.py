"""Regression tests for atomic multi-task lifecycle closure."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


# `RECONCILER_UNDER_TEST` points the suite at a different copy of the
# reconciler. It exists so "this test fails without the fix" is a command anyone
# can rerun: drop `git show <pre-fix-rev>:scripts/python/registry_reconciler.py`
# plus its two siblings (`repo_root.py`, `durable_publish.py`) into a temp dir
# and point this at it. Unset in CI, where the in-tree reconciler is the subject.
RECONCILER = Path(
    os.environ.get("RECONCILER_UNDER_TEST")
    or Path(__file__).resolve().parents[1] / "registry_reconciler.py"
)


class RegistryBatchCloseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="registry-batch-close-")
        self.root = Path(self._tmp.name)
        self.state = self.root / "_state"
        self.state.mkdir(parents=True)
        self.registry_path = self.state / "active-tasks.json"
        self.task_ids = (
            "TASK-2026-08-12-1001-batch-a",
            "TASK-2026-08-12-1002-batch-b",
            "TASK-2026-08-12-1003-batch-c",
        )
        statuses = ("in-flight", "needs_review", "needs_rework")
        registry = {
            task_id: {
                "compatibility_namespace": "coding",
                "source_namespace": "coding",
                "status": status,
                "fixture_sentinel": task_id,
            }
            for task_id, status in zip(self.task_ids, statuses, strict=True)
        }
        self.registry_path.write_text(
            json.dumps(registry, indent=2) + "\n", encoding="utf-8"
        )
        inbox = self.root / "departments" / "coding" / "inbox"
        inbox.mkdir(parents=True)
        for task_id in self.task_ids:
            (inbox / f"{task_id}.md").write_text(
                f"---\nid: {task_id}\n---\n", encoding="utf-8"
            )
        self.reason = (
            "verified: promoted outputs and recipient contracts passed for every "
            "listed task"
        )
        self.env = {
            **os.environ,
            "VAULT_ROOT": str(self.root),
            "STATE_DIR": str(self.state),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SQUAD_TEST_ISOLATION": "1",
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_argv(
        self, argv: list[str], *, expected_returncode: int
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(RECONCILER), *argv],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, expected_returncode, msg=result.stderr)
        return result

    def run_close(
        self,
        task_ids: tuple[str, ...],
        *,
        expected_returncode: int,
        reason: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_argv(
            [
                "--close-task",
                *task_ids,
                "--close-status",
                "closed",
                "--close-reason",
                reason or self.reason,
            ],
            expected_returncode=expected_returncode,
        )

    def repeated_flag_argv(self, task_ids: tuple[str, ...]) -> list[str]:
        """The form the operator actually typed: one `--close-task` per id."""
        argv: list[str] = []
        for task_id in task_ids:
            argv += ["--close-task", task_id]
        return argv + ["--close-status", "closed", "--close-reason", self.reason]

    def registry(self) -> dict[str, dict[str, object]]:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def test_three_tasks_close_atomically_with_one_reason(self) -> None:
        result = self.run_close(self.task_ids, expected_returncode=0)
        self.assertIn("tasks=" + ",".join(self.task_ids), result.stdout)

        registry = self.registry()
        timestamps = set()
        for task_id in self.task_ids:
            entry = registry[task_id]
            self.assertEqual(entry["status"], "closed")
            self.assertEqual(entry["closure_reason"], self.reason)
            self.assertEqual(entry["lifecycle_closed_by"], "chrono-explicit")
            self.assertEqual(entry["fixture_sentinel"], task_id)
            self.assertEqual(len(entry["closure_history"]), 1)
            self.assertEqual(entry["closure_history"][0]["reason"], self.reason)
            timestamps.add(entry["closure_history"][0]["at"])
            self.assertFalse(
                (self.root / "departments" / "coding" / "inbox" / f"{task_id}.md").exists()
            )
            self.assertTrue(
                (self.root / "departments" / "coding" / "archive" / f"{task_id}.md").is_file()
            )
        self.assertEqual(len(timestamps), 1, "one batch uses one lifecycle timestamp")
        queue = (self.state / "chrono-queue.md").read_text(encoding="utf-8")
        self.assertEqual(queue.count(" | TASK-CLOSED | "), len(self.task_ids))
        for task_id in self.task_ids:
            self.assertIn(f"coding/{task_id}", queue)
            self.assertIn(f"reason={self.reason}", queue)

        before_registry = self.registry_path.read_bytes()
        before_queue = (self.state / "chrono-queue.md").read_bytes()
        replay = self.run_close(self.task_ids, expected_returncode=0)
        self.assertIn("already-closed", replay.stdout)
        self.assertEqual(self.registry_path.read_bytes(), before_registry)
        self.assertEqual((self.state / "chrono-queue.md").read_bytes(), before_queue)

    def test_unknown_id_refuses_entire_batch_without_side_effects(self) -> None:
        before_registry = self.registry_path.read_bytes()
        invalid_batch = (
            self.task_ids[0],
            "TASK-2026-08-12-9999-not-registered",
            self.task_ids[1],
        )

        result = self.run_close(invalid_batch, expected_returncode=2)

        self.assertIn("unknown registry task", result.stderr)
        self.assertEqual(self.registry_path.read_bytes(), before_registry)
        self.assertFalse((self.state / "chrono-queue.md").exists())
        for task_id in self.task_ids:
            self.assertTrue(
                (self.root / "departments" / "coding" / "inbox" / f"{task_id}.md").is_file()
            )
            self.assertFalse(
                (self.root / "departments" / "coding" / "archive" / f"{task_id}.md").exists()
            )

    def test_repeated_close_task_flags_close_every_requested_id(self) -> None:
        """The batch that half-applied, found in use 2026-08-12.

        `--close-task 0530 --close-task 0540` closed 0540, left 0530 at
        review-required, and printed `closed task=...0540` -- a success message
        for a half-applied batch. `close_task` was not at fault and no loop
        aborted: `--close-task` was `nargs="+"` with no accumulating action, so
        argparse OVERWROTE the first occurrence and the function received a
        ONE-id batch.

        The 69-test focused suite could not see this. Every one of its cases
        called `close_task(["a", "b", "c"])` directly, and the id is lost at the
        argv boundary -- upstream of the function under test.
        """
        first, second = self.task_ids[0], self.task_ids[1]

        result = self.run_argv(
            self.repeated_flag_argv((first, second)), expected_returncode=0
        )

        registry = self.registry()
        # Pre-fix this is the assertion that fails: `first` is still "in-flight"
        # because argparse never handed it to close_task.
        self.assertEqual(registry[first]["status"], "closed")
        self.assertEqual(registry[second]["status"], "closed")
        self.assertEqual(registry[first]["closure_reason"], self.reason)
        self.assertIn(f"{first}: closed (", result.stdout)
        self.assertIn(f"{second}: closed (", result.stdout)

    def test_repeated_and_space_separated_forms_agree(self) -> None:
        """Both spellings must build the same batch, or one of them is a trap."""
        repeated = self.run_argv(
            self.repeated_flag_argv(self.task_ids), expected_returncode=0
        )
        for task_id in self.task_ids:
            self.assertEqual(self.registry()[task_id]["status"], "closed")
            self.assertIn(f"{task_id}: closed (", repeated.stdout)

        # A duplicate supplied across the two forms is still refused.
        mixed = self.run_argv(
            [
                "--close-task",
                self.task_ids[0],
                "--close-task",
                self.task_ids[0],
                "--close-status",
                "closed",
                "--close-reason",
                self.reason,
            ],
            expected_returncode=2,
        )
        self.assertIn("duplicate --close-task id", mixed.stderr)

    def test_second_id_that_cannot_close_leaves_the_first_open_and_reports_both(
        self,
    ) -> None:
        """The packet's decider, on a valid-but-ineligible member.

        The unknown-id path was already sound. This uses a member that is a real
        registry task and simply cannot take this close (already terminal under a
        different reason), and pins BOTH halves of the guarantee: the eligible
        member stays open, and the output accounts for every requested id.
        """
        first, second = self.task_ids[0], self.task_ids[1]
        self.run_close(
            (second,),
            expected_returncode=0,
            reason="closed earlier under a different judgement",
        )
        before_registry = self.registry_path.read_bytes()

        result = self.run_argv(
            self.repeated_flag_argv((first, second)), expected_returncode=2
        )

        self.assertEqual(
            self.registry()[first]["status"],
            "in-flight",
            "an eligible member must not close when a later member cannot",
        )
        self.assertEqual(self.registry_path.read_bytes(), before_registry)
        # Pre-fix, `first` is absent from the output entirely -- argparse dropped
        # it, so the refusal could only ever have named `second`.
        self.assertIn(f"{first}: eligible (", result.stderr)
        self.assertIn(f"{second}: REFUSED (", result.stderr)
        self.assertIn("already terminal", result.stderr)
        self.assertIn("no task was closed", result.stderr)

    def test_report_names_every_id_on_success_and_on_replay(self) -> None:
        first = self.run_close(self.task_ids, expected_returncode=0)
        for task_id in self.task_ids:
            self.assertIn(f"{task_id}: closed (", first.stdout)

        replay = self.run_close(self.task_ids, expected_returncode=0)
        for task_id in self.task_ids:
            self.assertIn(f"{task_id}: already-closed (", replay.stdout)

    def test_refusal_names_every_ineligible_member_not_just_the_first(self) -> None:
        """One rerun per defect is how a batch backlog stops being a batch."""
        batch = (
            "TASK-2026-08-12-9998-not-registered",
            self.task_ids[0],
            "TASK-2026-08-12-9999-also-not-registered",
        )

        result = self.run_close(batch, expected_returncode=2)

        self.assertIn("9998-not-registered", result.stderr)
        self.assertIn("9999-also-not-registered", result.stderr)
        self.assertIn(f"{self.task_ids[0]}: eligible (", result.stderr)
        self.assertEqual(self.registry()[self.task_ids[0]]["status"], "in-flight")

    def test_follow_through_failure_is_per_id_and_does_not_skip_the_rest(self) -> None:
        """The same partial shape, one layer down, after the commit.

        Archive/stub/queue records are written after the registry commit, so a
        failure there can no longer un-close anything -- but aborting the loop
        would leave every LATER member without its records while its close
        stood. The middle member is made un-archivable; the third must still be
        archived and queued, and the middle one's failure must be named.
        """
        blocked = self.task_ids[1]
        archive = self.root / "departments" / "coding" / "archive"
        archive.mkdir(parents=True)
        (archive / f"{blocked}.md").write_text("pre-existing\n", encoding="utf-8")

        result = self.run_close(self.task_ids, expected_returncode=1)

        for task_id in self.task_ids:
            self.assertEqual(self.registry()[task_id]["status"], "closed")
            self.assertIn(f"{task_id}: closed (", result.stdout)
        # Pre-fix the raised FileExistsError aborted the loop, so the third
        # member's packet was never archived and its queue line never written.
        inbox = self.root / "departments" / "coding" / "inbox"
        self.assertFalse((inbox / f"{self.task_ids[0]}.md").exists())
        self.assertTrue((inbox / f"{blocked}.md").is_file())
        self.assertFalse((inbox / f"{self.task_ids[2]}.md").exists())
        queue = (self.state / "chrono-queue.md").read_text(encoding="utf-8")
        self.assertEqual(queue.count(" | TASK-CLOSED | "), len(self.task_ids))

        self.assertIn("FOLLOW-THROUGH INCOMPLETE", result.stderr)
        self.assertIn("inbox packet archive failed after the close committed", result.stderr)
        self.assertIn(blocked, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
