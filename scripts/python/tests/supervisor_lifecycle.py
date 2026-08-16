"""Shared lifecycle cleanup for tests that detach a board supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.python.board_process_truth import (  # noqa: E402
    PROCESS_IDENTITY_FIELDS,
    observe_process,
)


def same_process_is_live(pid: int, expected: dict[str, object]) -> bool:
    """Use kill -0 plus the launch identity so a recycled PID is never signalled."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        observed = observe_process(pid)
    except OSError:
        # Codex's macOS sandbox can deny board_process_truth's /bin/ps probe.
        # The descriptor still proves this PID was a fresh session/group leader;
        # retain that narrower kernel fence rather than disabling cleanup.
        try:
            return os.getpgid(pid) == expected.get("pgid") == pid
        except ProcessLookupError:
            return False
    # kill -0 still sees an unreaped zombie. Treat it as present until init
    # removes the numeric PID, matching send-task's reparented detached child.
    return observed is None or observed == expected


def reap_detached_supervisor(
    pid: int,
    expected: dict[str, object] | None,
    *,
    timeout: float = 2.0,
) -> None:
    """Terminate one test-owned detached supervisor and prove that it is gone."""
    if expected is None or not same_process_is_live(pid, expected):
        return

    for requested_signal in (signal.SIGTERM, signal.SIGKILL):
        # One PID per call. Multi-PID kill commands have returned false success on
        # the board host, so cleanup deliberately never batches signal targets.
        try:
            os.kill(pid, requested_signal)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not same_process_is_live(pid, expected):
                return
            time.sleep(0.02)

    if same_process_is_live(pid, expected):
        raise AssertionError(
            f"detached supervisor outlived its test: pid={pid} "
            f"start={expected.get('process_start_token')}"
        )


def detached_supervisors(root: Path) -> list[tuple[int, dict[str, object]]]:
    """Load exact identities that send-task published before returning a PID."""
    supervisors: list[tuple[int, dict[str, object]]] = []
    seen: set[tuple[object, ...]] = set()
    state = root / "_state/board-dispatch"
    for descriptor in sorted(state.glob("*.dispatch.json")):
        try:
            payload = json.loads(descriptor.read_text(encoding="utf-8"))
            identity = {field: payload[field] for field in PROCESS_IDENTITY_FIELDS}
        except (KeyError, OSError, ValueError) as exc:
            raise AssertionError(
                f"cannot identify detached supervisor from {descriptor}: {exc}"
            ) from exc
        pid = identity["pid"]
        if not isinstance(pid, int) or pid <= 0 or identity["pgid"] != pid:
            raise AssertionError(f"invalid detached supervisor identity: {descriptor}")
        key = tuple(identity[field] for field in PROCESS_IDENTITY_FIELDS)
        if key not in seen:
            supervisors.append((pid, identity))
            seen.add(key)
    return supervisors


def cleanup_supervisors_before_root(
    root: Path, supervisor_root: Path | None = None
) -> None:
    """Reap every recorded supervisor before removing the filesystem it polls."""
    failures: list[str] = []
    for pid, expected in detached_supervisors(supervisor_root or root):
        try:
            reap_detached_supervisor(pid, expected)
        except (AssertionError, OSError) as exc:
            failures.append(str(exc))
    if failures:
        # Preserve the root under a surviving process. Deleting it is the exact
        # condition that created the orphan-supervisor incident.
        raise AssertionError("; ".join(failures))
    if root.exists() or root.is_symlink():
        shutil.rmtree(root)
