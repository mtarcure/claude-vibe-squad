"""Regression tests for gemini's lane-cwd return-artifact placement.

Gemini is the only lane whose process cwd is not the worktree root: it is
launched with `cwd = <worktree>/model-lanes/gemini` because that directory
holds the lane `.gemini` settings/agents AND is the cwd used to enumerate the
authorized MCP inventory.  Every path in a task packet is worktree-root
relative, so a worker that resolves `return_artifact` against its own cwd
lands the file at `<worktree>/model-lanes/gemini/<relative>` and completion
prevalidation reports "return artifact is missing, non-regular, or a symlink".

Observed 2026-07-26: 3 of 4 gemini research dispatches wrote
`departments/research/outbox/<id>-response.md` (cwd-relative, blocked) while
the one that succeeded happened to guess `../../departments/...`.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from dispatch_context_builder import (  # noqa: E402
    canonical_mailbox_relative,
    DispatchContextError,
    prepare_worktree_outputs,
    reclaim_lane_cwd_outputs,
)


GEMINI_CWD = "model-lanes/gemini"


def _envelope_text(task_id: str, result_relative: str) -> str:
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        "from: gemini\n"
        "to: chrono\n"
        "type: RESULT\n"
        "status: complete\n"
        f"return_artifact: {result_relative}\n"
        "---\n\n"
        "Reclaimed summary.\n"
    )


class GeminiArtifactReclaimTests(unittest.TestCase):
    """`reclaim_lane_cwd_outputs` maps lane-cwd strays back to the contract."""

    def test_output_written_relative_to_lane_cwd_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-x-response.md"
            stray = worktree / GEMINI_CWD / relative
            stray.parent.mkdir(parents=True)
            stray.write_text("brief\n", encoding="utf-8")

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, (relative,))
            self.assertEqual(
                (worktree / relative).read_text(encoding="utf-8"), "brief\n"
            )
            self.assertFalse(stray.exists())

    def test_multi_kilobyte_artifact_survives_reclaim_byte_for_byte(self) -> None:
        """The real payload is a multi-KB research brief, not a trivial 'OK'."""
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-big-response.md"
            payload = ("# Brief\n" + ("lorem ipsum dolor sit amet\n" * 4000))
            self.assertGreater(len(payload.encode("utf-8")), 64 * 1024)
            stray = worktree / GEMINI_CWD / relative
            stray.parent.mkdir(parents=True)
            stray.write_text(payload, encoding="utf-8")

            reclaim_lane_cwd_outputs(worktree, GEMINI_CWD, (relative,))

            self.assertEqual(
                (worktree / relative).read_text(encoding="utf-8"), payload
            )

    def test_output_already_at_the_declared_path_is_left_untouched(self) -> None:
        """The lane that guesses `../../` correctly must not be disturbed."""
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-ok-response.md"
            declared = worktree / relative
            declared.parent.mkdir(parents=True)
            declared.write_text("already correct\n", encoding="utf-8")

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, ())
            self.assertEqual(
                declared.read_text(encoding="utf-8"), "already correct\n"
            )

    def test_a_declared_output_is_never_overwritten_by_a_stray(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-both-response.md"
            declared = worktree / relative
            declared.parent.mkdir(parents=True)
            declared.write_text("authoritative\n", encoding="utf-8")
            stray = worktree / GEMINI_CWD / relative
            stray.parent.mkdir(parents=True)
            stray.write_text("stray duplicate\n", encoding="utf-8")

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, ())
            self.assertEqual(
                declared.read_text(encoding="utf-8"), "authoritative\n"
            )
            self.assertTrue(stray.is_file())

    def test_a_symlinked_stray_is_not_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-link-response.md"
            secret = worktree / "secret.md"
            secret.write_text("not the artifact\n", encoding="utf-8")
            stray = worktree / GEMINI_CWD / relative
            stray.parent.mkdir(parents=True)
            stray.symlink_to(secret)

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, ())
            self.assertFalse((worktree / relative).exists())

    def test_a_stray_escaping_the_worktree_is_not_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir()
            outside = root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            relative = "departments/research/outbox/TASK-esc-response.md"
            stray_parent = worktree / GEMINI_CWD / "departments" / "research"
            stray_parent.mkdir(parents=True)
            # outbox itself is a symlink to a directory outside the worktree
            (stray_parent / "outbox").symlink_to(root)

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, ())

    def test_a_stray_directory_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            relative = "departments/research/outbox/TASK-dir-response.md"
            (worktree / GEMINI_CWD / relative).mkdir(parents=True)

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (relative,)
            )

            self.assertEqual(reclaimed, ())
            self.assertFalse((worktree / relative).is_file())

    def test_traversal_in_the_lane_cwd_or_outputs_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            with self.assertRaises(DispatchContextError):
                reclaim_lane_cwd_outputs(worktree, "../escape", ("a.md",))
            with self.assertRaises(DispatchContextError):
                reclaim_lane_cwd_outputs(worktree, GEMINI_CWD, ("../a.md",))
            with self.assertRaises(DispatchContextError):
                reclaim_lane_cwd_outputs(worktree, GEMINI_CWD, ("/tmp/a.md",))

    def test_the_production_failure_is_repaired_end_to_end(self) -> None:
        """Reproduce TASK-2026-07-26-1024-325d45ef exactly, then repair it."""
        task_id = "TASK-2026-07-26-9001-gemini-reclaim"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worktree = root / "worktree"
            repo.mkdir()
            worktree.mkdir()
            result_relative = (
                f"departments/research/outbox/{task_id}-response.md"
            )
            authority = {
                "task_id": task_id,
                "lane": "gemini",
                "write_paths": ["departments/research/outbox/"],
                "expected_result_path": result_relative,
                "expected_outbox_path": result_relative,
            }
            # The worker resolved the packet-relative path against its own cwd.
            stray = worktree / GEMINI_CWD / result_relative
            stray.parent.mkdir(parents=True)
            stray.write_text(
                _envelope_text(task_id, result_relative), encoding="utf-8"
            )

            with self.assertRaises(DispatchContextError) as caught:
                prepare_worktree_outputs(repo, worktree, authority)
            self.assertIn("return artifact", str(caught.exception))

            reclaimed = reclaim_lane_cwd_outputs(
                worktree, GEMINI_CWD, (result_relative,)
            )
            self.assertEqual(reclaimed, (result_relative,))

            prepared = prepare_worktree_outputs(repo, worktree, authority)
            self.assertEqual(prepared.status, "complete")
            self.assertEqual(
                prepared.result_relative,
                canonical_mailbox_relative("outbox", task_id, response=True),
            )


if __name__ == "__main__":
    unittest.main()
