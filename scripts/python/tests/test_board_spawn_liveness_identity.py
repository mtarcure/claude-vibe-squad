#!/usr/bin/env python3
"""Plan B whole-branch review I6: board_spawn_live() proved liveness with a
bare `kill -0`.

`bin/squad-monitor.sh`'s stall detector treats "a live board spawn exists" as
proof the task is being supervised and returns early. The PID came straight
out of a `_state/board-dispatch/*.dispatch.json` that outlives its process by
days, and the predicate is only ever reached for dispatches with NO terminal
receipt -- i.e. exactly the stalled ones. A recycled PID therefore read as
live forever and the task never alerted: a guard satisfied by an unrelated
process, suppressing the alarm that exists to notice it.

The board spawn has no fixed argv shape (it is whatever specialist CLI the
packet routed to), so shared/process-identity.sh's exact-argv predicate does
not apply. The descriptor already carries the start-time fingerprint
(`process_start_token`) and `argv_sha256`, both written by
board_process_truth.observe_process() at spawn, and process_truth() is the
established comparison. This file drives the shell predicate verbatim out of
bin/squad-monitor.sh, against descriptors built by that same producer.

SAFETY: every process here is a `sleep` this test spawns, owns and reaps. The
descriptors live in a temp directory. Nothing reads or writes the real
_state/board-dispatch, and nothing invokes squad-monitor.sh itself.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MONITOR = REPO / "bin" / "squad-monitor.sh"
PYTHON_DIR = REPO / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import board_process_truth as bpt  # noqa: E402

TASK_ID = "TASK-2026-08-17-0001-board-liveness-identity"
ATTEMPT_ID = "d-0123456789abcdef0123456789abcdef"


class BoardDispatchProcessIsLiveTests(unittest.TestCase):
    """Drives bin/squad-monitor.sh's board_dispatch_process_is_live(),
    extracted verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        text = MONITOR.read_text(encoding="utf-8")
        match = re.search(
            r"\nboard_dispatch_process_is_live\(\) \{.*?\n\}\n", text, re.DOTALL
        )
        if not match:
            raise RuntimeError(
                "could not locate board_dispatch_process_is_live() in "
                "bin/squad-monitor.sh -- extraction regex is stale, update it "
                "to match the current source"
            )
        cls.function_src = match.group(0)

    def _descriptor_for(self, board: Path, pid: int, *, schema: str | None = None) -> Path:
        """A descriptor of the exact shape bin/send-task.sh writes, with the
        process identity taken from the same observe_process() the dispatcher
        uses -- so a mismatch in this test can only ever be a real identity
        mismatch, never a fixture that never agreed in the first place."""
        base = board / f"{TASK_ID}.{ATTEMPT_ID}"
        dispatch = Path(f"{base}.dispatch.json")
        observed = bpt.observe_process(pid)
        self.assertIsNotNone(observed, "test setup: the process must be observable")
        descriptor = {
            "schema": schema or bpt.DESCRIPTOR_V2,
            "task_id": TASK_ID,
            "attempt_id": ATTEMPT_ID,
            "generation": 1,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "context_path": f"{base}.context.json",
            "log_path": f"{base}.log",
            "receipt_path": f"{base}.receipt.json",
            **observed,
        }
        dispatch.write_text(json.dumps(descriptor, sort_keys=True), encoding="utf-8")
        return dispatch

    def _run(self, dispatch: Path) -> int:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            f'VAULT_ROOT="{REPO}"\n'
            + self.function_src
            + f'\nboard_dispatch_process_is_live "{dispatch}"; echo "rc=$?"'
        )
        result = subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=30
        )
        match = re.search(r"rc=(\d+)", result.stdout)
        self.assertIsNotNone(match, f"no rc in stdout:\n{result.stdout}\n{result.stderr}")
        return int(match.group(1))

    def test_a_matching_live_process_reads_as_live(self) -> None:
        # start_new_session=True mirrors board-supervisor.sh's own spawn shape:
        # the spawn becomes its own process-group and session leader, which
        # process_truth() also checks.
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            with tempfile.TemporaryDirectory() as d:
                dispatch = self._descriptor_for(Path(d), proc.pid)
                self.assertEqual(self._run(dispatch), 0)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_recycled_pid_does_not_read_as_live(self) -> None:
        """The defect itself: same PID, different process. `kill -0` cannot
        tell them apart; the recorded start-time fingerprint can."""
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            with tempfile.TemporaryDirectory() as d:
                dispatch = self._descriptor_for(Path(d), proc.pid)
                descriptor = json.loads(dispatch.read_text(encoding="utf-8"))
                # Exactly what a recycled PID looks like: the process at this
                # PID is alive, but it started at a different moment.
                descriptor["process_start_token"] = "ps:Mon Jan 1 00:00:00 2001"
                dispatch.write_text(json.dumps(descriptor, sort_keys=True), encoding="utf-8")

                self.assertEqual(os.kill(proc.pid, 0), None, "the PID is alive: kill -0 passes")
                self.assertEqual(self._run(dispatch), 1)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_different_process_at_the_same_pid_slot_does_not_read_as_live(self) -> None:
        """Same shape from the other side: the argv fingerprint differs even
        when the start time happens not to."""
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            with tempfile.TemporaryDirectory() as d:
                dispatch = self._descriptor_for(Path(d), proc.pid)
                descriptor = json.loads(dispatch.read_text(encoding="utf-8"))
                descriptor["argv_sha256"] = "0" * 64
                dispatch.write_text(json.dumps(descriptor, sort_keys=True), encoding="utf-8")
                self.assertEqual(self._run(dispatch), 1)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_dead_process_does_not_read_as_live(self) -> None:
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        with tempfile.TemporaryDirectory() as d:
            dispatch = self._descriptor_for(Path(d), proc.pid)
            proc.terminate()
            proc.wait(timeout=5)
            self.assertEqual(self._run(dispatch), 1)

    def test_a_legacy_descriptor_reads_as_not_live(self) -> None:
        """A descriptor too old to carry a process identity cannot be vouched
        for. Not-live is the safe direction: the monitor alerts on a task it
        cannot verify rather than silently suppressing the alarm."""
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            with tempfile.TemporaryDirectory() as d:
                dispatch = self._descriptor_for(
                    Path(d), proc.pid, schema=bpt.DESCRIPTOR_V1
                )
                self.assertEqual(self._run(dispatch), 1)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_missing_or_unparseable_descriptor_does_not_read_as_live(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / f"{TASK_ID}.{ATTEMPT_ID}.dispatch.json"
            self.assertEqual(self._run(missing), 1)
            missing.write_text("{not json", encoding="utf-8")
            self.assertEqual(self._run(missing), 1)


class BoardSpawnLiveUsesIdentityTests(unittest.TestCase):
    """Structural half: board_spawn_live() is a loop over descriptor files,
    not an extractable pure function, so these pin that it asks the identity
    predicate and no longer settles for bare liveness."""

    def setUp(self) -> None:
        text = MONITOR.read_text(encoding="utf-8")
        match = re.search(r"\nboard_spawn_live\(\) \{.*?\n\}\n", text, re.DOTALL)
        self.assertIsNotNone(match, "board_spawn_live() moved or was removed")
        self.body = match.group(0)

    def test_it_delegates_to_the_identity_predicate(self) -> None:
        self.assertIn("board_dispatch_process_is_live", self.body)

    def test_it_no_longer_proves_liveness_with_a_bare_kill_zero(self) -> None:
        self.assertNotIn("kill -0", self.body)


if __name__ == "__main__":
    unittest.main()
