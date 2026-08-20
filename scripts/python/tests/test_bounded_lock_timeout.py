#!/usr/bin/env python3
"""Plan B Task 2: every unbounded lock must be bounded, and bounded correctly.

docs/superpowers/sdd/2026-08-17-plan-B-stop-lying-about-state/task-2-brief.md

Three separate waits used to be able to block forever against a live-but-hung
owner, with no way to tell anyone was waiting or on whom:

  - bin/launch-squad.sh:691 (`ensure_watcher_fleet`'s WATCHER_FLEET_LOCK) --
    was `tmux wait-for -L`, no timeout, no owner introspection, and never
    released if the holder was SIGKILLed (a tmux wait-for lock is not tied to
    the holder's process lifetime).
  - scripts/python/registry_reconciler.py's `lockdir()` -- spun on `kill -0`
    with `time.sleep(0.1)` and no overall bound.
  - bin/chrono-queue-backfill.sh -- a recent fix faithfully ported the same
    unbounded spin; three writers now share the chrono-queue.md.lockdir
    protocol.

The fix adds an overall wall-clock timeout to each, on top of -- not instead
of -- their existing dead/absent-owner handling:

  - A CONFIRMED-DEAD owner (kill -0 fails) still breaks the lock immediately.
    No timeout wait needed for that case, and this must stay true.
  - A CONFIRMED-LIVE owner is never broken early, no matter how long the
    wait -- only the overall timeout, on expiry, fails loudly (owner PID +
    lock age reported), instead of silently proceeding or silently breaking
    a live owner's lock out from under it.

launch-squad.sh's `acquire_dir_lock`/`release_dir_lock` (added in this same
remediation, now used for both WATCHER_FLEET_LOCK and LAUNCH_LOCK) are pure
bash functions with no VAULT_ROOT/tmux/daemon/doctor preconditions, so this
file extracts their exact source text (verbatim, not reimplemented) out of
bin/launch-squad.sh and drives them directly -- see
docs/superpowers/sdd/2026-08-17-plan-B-stop-lying-about-state/task-1-report.md
for why nothing in this remediation may invoke the real launcher end-to-end
outside that file's own, deliberately narrow, isolation harness
(SQUAD_SKIP_WATCHER_FLEET): `ensure_watcher_fleet()`'s repair path matches
"watcher-supervisor:" processes system-wide with no VAULT_ROOT/SQUAD_SESSION
scoping, and killed this host's real, live watcher fleet once already while
that harness was being built.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LAUNCH_SQUAD = REPO / "bin" / "launch-squad.sh"
BACKFILL_SCRIPT = REPO / "bin" / "chrono-queue-backfill.sh"
PYTHON_DIR = REPO / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import registry_reconciler as rr  # noqa: E402


def _spawn_live_process() -> subprocess.Popen:
    """A process guaranteed alive (and killable) for the duration of a test."""
    return subprocess.Popen(
        ["sleep", "300"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@contextlib.contextmanager
def _unwritable_dir(path: Path):
    """Make `path` read+execute but NOT writable for its owner, restoring the
    original mode on the way out so TemporaryDirectory cleanup still works.

    This is the condition that turned both lock loops into an unbounded busy
    spin: `mkdir <lock>` fails with EACCES forever, `owner.pid` is unreadable,
    `stat` on the (nonexistent) lock directory fails so the age reads as
    "ancient", the stale-break fires, `rm`/`rmdir` fail too -- and the old
    `continue` jumped straight past both the timeout check and the sleep.
    Reachable in production because the launch/watcher locks moved out of
    always-writable /tmp and under ${VAULT_ROOT}/_state, which a single
    `sudo squad up` leaves root-owned.
    """
    original = path.stat().st_mode
    path.chmod(0o500)
    try:
        yield path
    finally:
        path.chmod(original)


def _dead_pid() -> int:
    """A PID guaranteed dead: spawn, wait for exit, reuse the now-free number.

    Safer than a hardcoded large PID (which could coincide with something
    real on a busy host, and could also be silently invalid on some systems).
    """
    proc = subprocess.Popen(["true"])
    proc.wait(timeout=5)
    return proc.pid


class ExtractedDirLockBashFunctionsTests(unittest.TestCase):
    """Drives bin/launch-squad.sh's acquire_dir_lock/release_dir_lock via
    their exact, verbatim source text -- see module docstring for why this
    file never invokes the real launcher script directly."""

    @classmethod
    def setUpClass(cls) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        mtime_match = re.search(
            r"\nfile_mtime_epoch\(\) \{.*?\n\}\n",
            text,
            re.DOTALL,
        )
        lock_match = re.search(
            r"\nacquire_dir_lock\(\) \{.*?\nrelease_dir_lock\(\) \{.*?\n\}\n",
            text,
            re.DOTALL,
        )
        if not mtime_match or not lock_match:
            raise RuntimeError(
                "could not locate file_mtime_epoch/acquire_dir_lock/release_dir_lock in bin/launch-squad.sh "
                "-- extraction regex is stale, update it to match the current source"
            )
        cls.functions_src = mtime_match.group(0) + lock_match.group(0)

    def _run_bash(
        self,
        script_body: str,
        timeout: float = 30,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        full = "#!/bin/bash\nset -uo pipefail\n" + self.functions_src + "\n" + script_body
        return subprocess.run(
            ["bash", "-c", full],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None if extra_env is None else {**os.environ, **extra_env},
        )

    def test_dead_owner_breaks_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d) / "some.lockdir"
            lock_dir.mkdir()
            (lock_dir / "owner.pid").write_text(f"{_dead_pid()}\n", encoding="utf-8")

            start = time.monotonic()
            result = self._run_bash(
                f'acquire_dir_lock "{lock_dir}" 30 "test lock"; echo "rc=$?"'
            )
            elapsed = time.monotonic() - start

            self.assertIn("rc=0", result.stdout, result.stderr)
            self.assertLess(
                elapsed, 5,
                f"dead owner should break the lock immediately, not wait out any part of "
                f"the 30s timeout; took {elapsed:.1f}s. stderr:\n{result.stderr}",
            )
            self.assertTrue((lock_dir / "owner.pid").exists())

    def test_live_owner_blocks_then_times_out(self) -> None:
        live = _spawn_live_process()
        try:
            with tempfile.TemporaryDirectory() as d:
                lock_dir = Path(d) / "some.lockdir"
                lock_dir.mkdir()
                (lock_dir / "owner.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                original_mtime = lock_dir.stat().st_mtime

                start = time.monotonic()
                result = self._run_bash(
                    f'acquire_dir_lock "{lock_dir}" 2 "test lock"; echo "rc=$?"'
                )
                elapsed = time.monotonic() - start

                # Lower bound is not the full 2s: acquire_dir_lock buckets
                # elapsed time via `date +%s` (whole seconds), so a target of
                # 2 can fire as little as ~1.0s of real time after start (if
                # `start_ts` was captured a hair before a second boundary).
                # The property under test is "waited a real, non-trivial
                # amount, not zero" -- not "waited exactly the nominal value".
                self.assertGreaterEqual(
                    elapsed, 0.9,
                    f"must actually wait for a live owner, not return early; took {elapsed:.1f}s",
                )
                self.assertIn("rc=1", result.stdout, result.stderr)
                self.assertIn(str(live.pid), result.stderr)
                self.assertIn("still held", result.stderr)
                # Never silently break a live owner's lock: the lock directory
                # and its owner.pid must be exactly as this test left them.
                self.assertTrue(lock_dir.is_dir())
                self.assertEqual(
                    (lock_dir / "owner.pid").read_text(encoding="utf-8").strip(),
                    str(live.pid),
                )
                self.assertEqual(lock_dir.stat().st_mtime, original_mtime)
        finally:
            live.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                live.wait(timeout=5)

    def test_uncreatable_lock_fails_within_the_timeout_instead_of_spinning(self) -> None:
        """The bound has to hold on the path where the lock can be neither
        acquired NOR broken. Before this, both break branches `continue`d past
        the timeout check and the sleep, so an unwritable parent produced an
        unbounded busy spin at 100% CPU -- `squad up` hanging forever, which
        is the exact failure this whole task exists to remove.

        `subprocess.run(timeout=...)` is the fail-safe: if the loop ever spins
        again this raises TimeoutExpired rather than hanging the suite.
        """
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d) / "readonly-parent"
            parent.mkdir()
            with _unwritable_dir(parent):
                lock_dir = parent / "some.lockdir"

                start = time.monotonic()
                result = self._run_bash(
                    f'acquire_dir_lock "{lock_dir}" 2 "test lock"; echo "rc=$?"', timeout=20
                )
                elapsed = time.monotonic() - start

            self.assertIn("rc=1", result.stdout, result.stderr)
            self.assertLess(
                elapsed, 15,
                f"must fail within its own timeout, not spin; took {elapsed:.1f}s",
            )
            # And it must say what is actually wrong. A directory that does not
            # exist was never "held": reporting a phantom owner PID and a 0s
            # lock age would send the operator hunting a process that is not
            # there.
            self.assertIn("could not be CREATED", result.stderr)
            self.assertNotIn("still held", result.stderr)
            self.assertFalse(lock_dir.exists())

    def test_unreadable_mtime_never_authorizes_breaking_unknown_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lock_dir = root / "some.lockdir"
            lock_dir.mkdir()
            fakebin = root / "fakebin"
            fakebin.mkdir()
            fake_stat = fakebin / "stat"
            fake_stat.write_text("#!/bin/bash\nexit 66\n", encoding="utf-8")
            fake_stat.chmod(0o755)

            start = time.monotonic()
            result = self._run_bash(
                f'acquire_dir_lock "{lock_dir}" 2 "test lock"; echo "rc=$?"',
                extra_env={"PATH": f"{fakebin}:/usr/bin:/bin"},
            )
            elapsed = time.monotonic() - start

            self.assertGreaterEqual(elapsed, 0.9, result.stderr)
            self.assertLess(elapsed, 15, result.stderr)
            self.assertIn("rc=1", result.stdout)
            self.assertIn("lock age unknown (mtime unreadable)", result.stderr)
            self.assertIn("refusing to wait longer", result.stderr)
            self.assertTrue(lock_dir.is_dir())
            self.assertFalse((lock_dir / "owner.pid").exists())


class RegistryReconcilerLockdirTests(unittest.TestCase):
    def test_dead_owner_breaks_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d) / "some.lockdir"
            lock_dir.mkdir()
            (lock_dir / "owner.pid").write_text(f"{_dead_pid()}\n", encoding="utf-8")

            start = time.monotonic()
            with rr.lockdir(lock_dir, timeout=30):
                elapsed = time.monotonic() - start
            self.assertLess(
                elapsed, 5,
                f"dead owner should break the lock immediately, not wait out any part of "
                f"the 30s timeout; took {elapsed:.1f}s",
            )

    def test_live_owner_blocks_then_times_out(self) -> None:
        live = _spawn_live_process()
        try:
            with tempfile.TemporaryDirectory() as d:
                lock_dir = Path(d) / "some.lockdir"
                lock_dir.mkdir()
                (lock_dir / "owner.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                original_mtime = lock_dir.stat().st_mtime

                start = time.monotonic()
                with self.assertRaises(TimeoutError) as ctx:
                    with rr.lockdir(lock_dir, timeout=1.5):
                        pass
                elapsed = time.monotonic() - start

                self.assertGreaterEqual(elapsed, 1.4)
                self.assertIn(str(live.pid), str(ctx.exception))
                self.assertTrue(lock_dir.is_dir())
                self.assertEqual(
                    (lock_dir / "owner.pid").read_text(encoding="utf-8").strip(),
                    str(live.pid),
                )
                self.assertEqual(lock_dir.stat().st_mtime, original_mtime)
        finally:
            live.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                live.wait(timeout=5)


class ChronoQueueBackfillLockTests(unittest.TestCase):
    def _make_vault(self, d: Path) -> Path:
        state = d / "_state"
        state.mkdir()
        (state / "active-tasks.json").write_text("{}", encoding="utf-8")
        (state / "chrono-queue.md").write_text(
            "# Chrono Queue\n# timestamp | status | namespace/task-id | summary\n\n",
            encoding="utf-8",
        )
        return d

    def _run(self, vault: Path, extra_env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(BACKFILL_SCRIPT)],
            env={"PATH": "/usr/bin:/bin", "VAULT_ROOT": str(vault), **extra_env},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_dead_owner_breaks_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            vault = self._make_vault(Path(d))
            lock_dir = vault / "_state" / "chrono-queue.md.lockdir"
            lock_dir.mkdir()
            (lock_dir / "owner.pid").write_text(f"{_dead_pid()}\n", encoding="utf-8")

            start = time.monotonic()
            result = self._run(vault, {"CHRONO_QUEUE_LOCK_TIMEOUT": "30"})
            elapsed = time.monotonic() - start

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(
                elapsed, 10,
                f"dead owner should break the lock immediately, not wait out any part of "
                f"the 30s timeout; took {elapsed:.1f}s. stderr:\n{result.stderr}",
            )

    def test_live_owner_blocks_then_times_out(self) -> None:
        live = _spawn_live_process()
        try:
            with tempfile.TemporaryDirectory() as d:
                vault = self._make_vault(Path(d))
                lock_dir = vault / "_state" / "chrono-queue.md.lockdir"
                lock_dir.mkdir()
                (lock_dir / "owner.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                original_mtime = lock_dir.stat().st_mtime

                start = time.monotonic()
                result = self._run(vault, {"CHRONO_QUEUE_LOCK_TIMEOUT": "2"})
                elapsed = time.monotonic() - start

                # See ExtractedDirLockBashFunctionsTests for why this is 0.9
                # and not ~2: `date +%s` whole-second bucketing means a
                # target of 2 can legitimately fire after as little as ~1.0s
                # of real time.
                self.assertGreaterEqual(elapsed, 0.9, result.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(live.pid), result.stderr)
                self.assertIn("still held", result.stderr)
                self.assertTrue(lock_dir.is_dir())
                self.assertEqual(
                    (lock_dir / "owner.pid").read_text(encoding="utf-8").strip(),
                    str(live.pid),
                )
                self.assertEqual(lock_dir.stat().st_mtime, original_mtime)
                # Never silently proceed: the queue file itself must be
                # untouched since the critical section was never entered.
                self.assertEqual(
                    (vault / "_state" / "chrono-queue.md").read_text(encoding="utf-8"),
                    "# Chrono Queue\n# timestamp | status | namespace/task-id | summary\n\n",
                )
        finally:
            live.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                live.wait(timeout=5)

    def test_uncreatable_lock_fails_within_the_timeout_instead_of_spinning(self) -> None:
        """Mirror of ExtractedDirLockBashFunctionsTests' case, against the
        third writer of the same protocol: an unwritable `_state` means the
        lock can be neither acquired nor broken, and both break branches used
        to `continue` past the timeout and the sleep."""
        with tempfile.TemporaryDirectory() as d:
            vault = self._make_vault(Path(d))
            with _unwritable_dir(vault / "_state"):
                start = time.monotonic()
                result = self._run(vault, {"CHRONO_QUEUE_LOCK_TIMEOUT": "2"})
                elapsed = time.monotonic() - start

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertLess(
                elapsed, 15,
                f"must fail within its own timeout, not spin; took {elapsed:.1f}s",
            )
            self.assertIn("could not be CREATED", result.stderr)
            self.assertNotIn("still held", result.stderr)
            self.assertFalse((vault / "_state" / "chrono-queue.md.lockdir").exists())


if __name__ == "__main__":
    unittest.main()
