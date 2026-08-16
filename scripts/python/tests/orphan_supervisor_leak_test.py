"""Regression detector for detached board-supervisor lifecycle leaks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR = REPO_ROOT / "bin/board-supervisor.sh"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.python.board_process_truth import observe_process  # noqa: E402
from scripts.python.tests import supervisor_lifecycle  # noqa: E402


def wait_for_path(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for fixture path: {path}")


def supervisors_scoped_to(root: Path, process_listing: str) -> list[tuple[int, str]]:
    """Return live detached supervisors whose argv names this suite's temp root."""
    root_spellings = {str(root), str(root.resolve())}
    survivors: list[tuple[int, str]] = []
    for line in process_listing.splitlines():
        match = re.match(r"^\s*([0-9]+)\s+(\S+)\s+(.*)$", line)
        if match is None:
            continue
        pid, state, command = int(match.group(1)), match.group(2), match.group(3)
        if state.startswith("Z"):
            continue
        if (
            any(root_text in command for root_text in root_spellings)
            and "board-supervisor.sh" in command
            and "detached-launch" in command
        ):
            survivors.append((pid, command))
    return survivors


def scan_suite_survivors(root: Path, timeout: float = 1.0) -> list[tuple[int, str]]:
    """Allow normal exit races, then report supervisors still scoped to the suite."""
    deadline = time.monotonic() + timeout
    while True:
        listing = subprocess.run(
            ["/bin/ps", "-axo", "pid=,state=,command="],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        ).stdout
        survivors = supervisors_scoped_to(root, listing)
        if not survivors or time.monotonic() >= deadline:
            return survivors
        time.sleep(0.05)


class OrphanSupervisorLeakTests(unittest.TestCase):
    def test_suite_scanner_ignores_other_roots_and_zombies(self) -> None:
        root = Path("/private/tmp/vs-suite-owned")
        listing = "\n".join(
            (
                " 101 S /bin/bash /private/tmp/vs-suite-owned/bin/board-supervisor.sh detached-launch x",
                " 102 Z /bin/bash /private/tmp/vs-suite-owned/bin/board-supervisor.sh detached-launch x",
                " 103 S /bin/bash /private/tmp/other/bin/board-supervisor.sh detached-launch x",
                " 104 S /bin/bash /private/tmp/vs-suite-owned/bin/board-supervisor.sh trusted-launch x",
            )
        )

        self.assertEqual(
            supervisors_scoped_to(root, listing),
            [(101, listing.splitlines()[0].split(maxsplit=2)[2])],
        )

    def test_cleanup_reaps_before_deleting_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="supervisor-cleanup-order-") as parent:
            parent_path = Path(parent)
            root = parent_path / "vault"
            root.mkdir()
            ready = parent_path / "ready"
            order = parent_path / "signal-order"
            child_code = (
                "import pathlib,signal,sys,time\n"
                "root=pathlib.Path(sys.argv[1]); ready=pathlib.Path(sys.argv[2]); "
                "order=pathlib.Path(sys.argv[3])\n"
                "def stop(_signum, _frame):\n"
                " order.write_text('root-present' if root.is_dir() else 'root-missing')\n"
                " raise SystemExit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "ready.write_text('ready')\n"
                "while True: time.sleep(0.05)\n"
            )
            launcher = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import subprocess,sys\n"
                        "child=subprocess.Popen(\n"
                        " [sys.argv[1], '-c', sys.argv[2], *sys.argv[3:]],\n"
                        " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
                        " stderr=subprocess.DEVNULL, start_new_session=True)\n"
                        "print(child.pid, flush=True)\n"
                    ),
                    sys.executable,
                    child_code,
                    str(root),
                    str(ready),
                    str(order),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=True,
            )
            child_pid = int(launcher.stdout.strip())
            identity: dict[str, object] | None = None
            try:
                wait_for_path(ready)
                try:
                    identity = observe_process(child_pid)
                except OSError:
                    identity = {
                        "pid": child_pid,
                        "pgid": os.getpgid(child_pid),
                        "process_start_token": f"fixture:{child_pid}",
                        "argv_sha256": hashlib.sha256(
                            b"orphan-supervisor-cleanup-fixture"
                        ).hexdigest(),
                    }
                self.assertIsNotNone(identity)
                descriptor = root / "_state/board-dispatch/fixture.dispatch.json"
                descriptor.parent.mkdir(parents=True)
                descriptor.write_text(
                    json.dumps(identity, sort_keys=True) + "\n", encoding="utf-8"
                )

                supervisor_lifecycle.cleanup_supervisors_before_root(root)

                self.assertEqual(order.read_text(encoding="utf-8"), "root-present")
                self.assertFalse(root.exists())
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if (
                    identity is not None
                    and supervisor_lifecycle.same_process_is_live(child_pid, identity)
                ):
                    os.kill(child_pid, signal.SIGKILL)
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        try:
                            os.kill(child_pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.02)

    def test_detector_rejects_a_supervisor_that_survives_term_and_kill(self) -> None:
        expected = {
            "pid": 424242,
            "pgid": 424242,
            "process_start_token": "fixture:start",
            "argv_sha256": "0" * 64,
        }
        with (
            mock.patch.object(
                supervisor_lifecycle, "same_process_is_live", return_value=True
            ),
            mock.patch.object(supervisor_lifecycle.os, "kill") as send_signal,
        ):
            with self.assertRaisesRegex(
                AssertionError, "detached supervisor outlived its test"
            ):
                supervisor_lifecycle.reap_detached_supervisor(
                    expected["pid"], expected, timeout=0.0
                )

        self.assertEqual(
            send_signal.call_args_list,
            [
                mock.call(expected["pid"], signal.SIGTERM),
                mock.call(expected["pid"], signal.SIGKILL),
            ],
        )

    @unittest.skipIf(os.geteuid() == 0, "board supervisor refuses root execution")
    def test_real_supervisor_exits_when_vault_root_disappears(self) -> None:
        with tempfile.TemporaryDirectory(prefix="supervisor-missing-root-") as parent:
            root = Path(parent) / "vault"
            root.mkdir()
            descriptor = root / "dispatch.json"
            process = subprocess.Popen(
                [
                    "/bin/bash",
                    str(SUPERVISOR),
                    "detached-launch",
                    str(root / "context.json"),
                    str(root / "supervisor.log"),
                    str(root / "receipt.json"),
                    str(root / "settlement-error"),
                    str(root / "context-builder.py"),
                    str(root),
                    "TASK-ORPHAN-SUPERVISOR-FIXTURE",
                    "codex",
                    "_state/result.md",
                    "coding",
                    str(root / "registry-reconciler.sh"),
                ],
                env={
                    **os.environ,
                    "BOARD_DISPATCH_DESCRIPTOR_PATH": str(descriptor),
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(0.05)
                started = time.monotonic()
                shutil.rmtree(root)
                stdout, stderr = process.communicate(timeout=2)
                elapsed = time.monotonic() - started
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)

            self.assertEqual(process.returncode, 75, stdout + stderr)
            self.assertIn("vault root disappeared", stderr)
            self.assertLess(elapsed, 0.8)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--scan-root":
        scan_root = Path(sys.argv[2])
        try:
            leaked = scan_suite_survivors(scan_root)
        except (OSError, subprocess.SubprocessError) as exc:
            print(
                f"orphan supervisor detector could not inspect processes: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if leaked:
            for leaked_pid, leaked_command in leaked:
                print(
                    f"orphan supervisor survived dispatch suite: pid={leaked_pid} "
                    f"root={scan_root} argv={leaked_command}",
                    file=sys.stderr,
                )
            raise SystemExit(1)
        print(f"ORPHAN SUPERVISOR DETECTOR PASS: root={scan_root}")
    else:
        unittest.main()
