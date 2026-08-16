"""A closed task's blocked stub must stop blocking its own re-dispatch.

Root cause this guards: the promoter's stub-reclaim
(`_is_board_blocked_stub` in dispatch_context_builder) matches the stub against
the *promoting* task's id. Supersede-and-redispatch deliberately uses a NEW id,
so the stub still names the old task, the exact match fails, and promotion is
refused with "return artifact destination already differs" -- AFTER the
replacement lane has finished all of its work. Four completed lanes hit this in
one campaign and were recovered only by sweeping their worktrees.

The two negative cases below are the point of this file. A release that fires
too eagerly would silently destroy real artifacts, which is strictly worse than
the bug it fixes -- so the control that must NOT fire is tested first-class.
"""

import importlib.util
from datetime import datetime, timezone
import os
import pathlib
import signal
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "registry_reconciler", ROOT / "scripts" / "python" / "registry_reconciler.py"
)
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)

TASK = "TASK-2026-08-05-1620-pcn-chain-b"


def _stub(task_id: str) -> str:
    return (
        f"blocked\n\n# Board dispatch blocked — {task_id}\n\n"
        "Controller reason: context builder failed: task packet is too large\n"
    )


class BlockedStubReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved_root = rr.VAULT_ROOT
        rr.VAULT_ROOT = self.root
        self.rel = "artifact.md"
        self.dest = self.root / self.rel

    def tearDown(self) -> None:
        rr.VAULT_ROOT = self._saved_root
        self._tmp.cleanup()

    def test_stub_for_this_task_is_retired_and_path_freed(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        retired = rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
        self.assertIsNotNone(retired)
        self.assertFalse(self.dest.exists(), "path must be free for the re-dispatch")
        self.assertTrue(
            (self.root / retired).is_file(), "stub is renamed, not deleted -- it is audit history"
        )

    def test_real_artifact_is_never_touched(self) -> None:
        """Shown-to-catch: the release must fail to fire on real work."""
        body = "# Real chaining artifact\n\nEXP-6 measured slope 1795680\n"
        self.dest.write_text(body, encoding="utf-8")
        self.assertIsNone(rr.release_blocked_stub(TASK, {"return_artifact": self.rel}))
        self.assertEqual(self.dest.read_text(encoding="utf-8"), body)

    def test_another_tasks_stub_is_never_touched(self) -> None:
        """Shown-to-catch: retiring a sibling's stub would be a clobber."""
        other = _stub("TASK-2026-08-05-9999-someone-else")
        self.dest.write_text(other, encoding="utf-8")
        self.assertIsNone(rr.release_blocked_stub(TASK, {"return_artifact": self.rel}))
        self.assertEqual(self.dest.read_text(encoding="utf-8"), other)

    def test_crlf_lookalike_is_not_the_exact_controller_stub(self) -> None:
        lookalike = _stub(TASK).replace("\n", "\r\n")
        self.dest.write_bytes(lookalike.encode("utf-8"))
        self.assertIsNone(
            rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
        )
        self.assertEqual(self.dest.read_bytes(), lookalike.encode("utf-8"))

    def test_missing_or_unsafe_return_artifact_is_a_noop(self) -> None:
        self.assertIsNone(rr.release_blocked_stub(TASK, {}))
        self.assertIsNone(rr.release_blocked_stub(TASK, {"return_artifact": "../escape.md"}))
        self.assertIsNone(rr.release_blocked_stub(TASK, {"return_artifact": "/abs/path.md"}))

    def test_contained_absolute_stub_is_retired(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        retired = rr.release_blocked_stub(
            TASK,
            {"return_artifact": str(self.dest)},
        )
        self.assertEqual(retired, f"{self.rel}.blocked-{TASK}")
        self.assertFalse(self.dest.exists())

    def test_absolute_path_outside_vault_is_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = pathlib.Path(outside_directory) / "artifact.md"
            outside.write_text(_stub(TASK), encoding="utf-8")
            self.assertIsNone(
                rr.release_blocked_stub(
                    TASK,
                    {"return_artifact": str(outside)},
                )
            )
            self.assertEqual(outside.read_text(encoding="utf-8"), _stub(TASK))
            self.assertFalse(
                outside.with_name(f"artifact.md.blocked-{TASK}").exists()
            )

    def test_symlinked_parent_escape_is_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside_root = pathlib.Path(outside_directory)
            outside = outside_root / "artifact.md"
            outside.write_text(_stub(TASK), encoding="utf-8")
            (self.root / "link").symlink_to(outside_root, target_is_directory=True)

            self.assertIsNone(
                rr.release_blocked_stub(
                    TASK,
                    {"return_artifact": "link/artifact.md"},
                )
            )
            self.assertEqual(outside.read_text(encoding="utf-8"), _stub(TASK))
            self.assertFalse(
                outside.with_name(f"artifact.md.blocked-{TASK}").exists()
            )

    def test_symlink_artifact_is_never_retired(self) -> None:
        target = self.root / "target.md"
        target.write_text(_stub(TASK), encoding="utf-8")
        self.dest.symlink_to(target)
        self.assertIsNone(
            rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
        )
        self.assertTrue(self.dest.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), _stub(TASK))

    def test_existing_broken_retired_symlink_is_never_overwritten(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        retired = self.root / f"{self.rel}.blocked-{TASK}"
        retired.symlink_to(self.root / "missing-target")
        self.assertIsNone(
            rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
        )
        self.assertTrue(self.dest.is_file())
        self.assertTrue(retired.is_symlink())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO fixture requires POSIX")
    def test_fifo_artifact_fails_closed_without_blocking_registry_progress(self) -> None:
        os.mkfifo(self.dest)

        class OpenTimedOut(RuntimeError):
            pass

        def timeout_handler(_signum, _frame):
            raise OpenTimedOut("FIFO open blocked")

        previous = signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        started = time.monotonic()
        try:
            try:
                result = rr.release_blocked_stub(
                    TASK,
                    {"return_artifact": self.rel},
                )
            except OpenTimedOut:
                self.fail("blocked-stub retirement performed a blocking FIFO open")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(self.dest.exists())

    def test_concurrent_audit_destination_is_never_overwritten(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        retired = self.root / f"{self.rel}.blocked-{TASK}"
        existing_audit = "existing audit bytes\n"
        real_rename = rr._rename_noreplace
        injected = False

        def inject_destination(*args, **kwargs):
            nonlocal injected
            if not injected:
                retired.write_text(existing_audit, encoding="utf-8")
                injected = True
            return real_rename(*args, **kwargs)

        with mock.patch.object(
            rr,
            "_rename_noreplace",
            side_effect=inject_destination,
        ):
            self.assertIsNone(
                rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
            )
        self.assertEqual(self.dest.read_text(encoding="utf-8"), _stub(TASK))
        self.assertEqual(retired.read_text(encoding="utf-8"), existing_audit)

    def test_concurrent_source_replacement_is_restored_not_retired(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        original = self.root / "original-stub.md"
        retired = self.root / f"{self.rel}.blocked-{TASK}"
        replacement = "# Real replacement artifact\n"
        real_rename = rr._rename_noreplace
        injected = False

        def inject_source(*args, **kwargs):
            nonlocal injected
            if not injected:
                self.dest.rename(original)
                self.dest.write_text(replacement, encoding="utf-8")
                injected = True
            return real_rename(*args, **kwargs)

        with mock.patch.object(
            rr,
            "_rename_noreplace",
            side_effect=inject_source,
        ):
            self.assertIsNone(
                rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
            )
        self.assertEqual(self.dest.read_text(encoding="utf-8"), replacement)
        self.assertEqual(original.read_text(encoding="utf-8"), _stub(TASK))
        self.assertFalse(retired.exists())

    def test_concurrent_in_place_rewrite_is_restored_not_retired(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        retired = self.root / f"{self.rel}.blocked-{TASK}"
        replacement = "# Rewritten real artifact\n"
        real_rename = rr._rename_noreplace
        injected = False

        def inject_rewrite(*args, **kwargs):
            nonlocal injected
            if not injected:
                self.dest.write_text(replacement, encoding="utf-8")
                injected = True
            return real_rename(*args, **kwargs)

        with mock.patch.object(
            rr,
            "_rename_noreplace",
            side_effect=inject_rewrite,
        ):
            self.assertIsNone(
                rr.release_blocked_stub(TASK, {"return_artifact": self.rel})
            )
        self.assertEqual(self.dest.read_text(encoding="utf-8"), replacement)
        self.assertFalse(retired.exists())

    def test_delivery_terminal_uses_registry_task_identity_to_retire_stub(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        entry = {
            "return_artifact": self.rel,
            "delivery_attempt_id": "d-" + "a" * 32,
            "delivery_generation": 1,
            "delivery_state": "in-progress",
        }
        changed = rr.mark_delivery_terminal(
            TASK,
            entry,
            datetime(2026, 8, 7, tzinfo=timezone.utc),
            "fixture-terminal",
        )
        self.assertTrue(changed)
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.root / f"{self.rel}.blocked-{TASK}").is_file())

    def test_auto_close_uses_registry_task_identity_to_retire_stub(self) -> None:
        self.dest.write_text(_stub(TASK), encoding="utf-8")
        entry = {"return_artifact": self.rel}
        rr.auto_close_terminal_receipt(
            TASK,
            entry,
            datetime(2026, 8, 7, tzinfo=timezone.utc),
            "blocked",
            "blocked",
        )
        self.assertEqual(entry["status"], "closed")
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.root / f"{self.rel}.blocked-{TASK}").is_file())


class TerminalPathCoverageTests(unittest.TestCase):
    """The fix must cover EVERY route to terminal, not just the explicit one.

    Measured 2026-08-05: the first version of this fix covered `close_task`
    only. 83 registry entries carry `lifecycle_closed_by:
    registry-reconciler-auto`, and that auto path is the one that fires on
    BLOCKED tasks -- precisely when a stub is written -- so the primary
    stub-producing route was still unfixed. A partial fix here looks identical
    to a complete one until a lane loses its promotion again.
    """

    def test_every_terminal_path_releases_the_stub(self) -> None:
        import re

        source = (
            ROOT / "scripts" / "python" / "registry_reconciler.py"
        ).read_text(encoding="utf-8")
        for func in (
            "close_task",
            "auto_close_terminal_receipt",
            "mark_delivery_terminal",
        ):
            match = re.search(rf"^def {func}\(.*?(?=^def )", source, re.S | re.M)
            self.assertIsNotNone(match, f"{func} not found")
            self.assertIn(
                "release_blocked_stub",
                match.group(0),
                f"{func} reaches terminal status without freeing the return_artifact "
                f"path; a re-dispatch will be refused after doing all of its work",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
