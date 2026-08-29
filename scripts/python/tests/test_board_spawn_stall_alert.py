#!/usr/bin/env python3
"""Regression controls for live board-spawn log-silence alerts.

The fixture drives ``detect_stuck`` and its production helpers verbatim from
``bin/squad-monitor.sh``. Process identity is the one boundary stub: returning
success models a descriptor whose detached supervisor identity is still live.
All attempt, log, receipt, registry, inbox, and monitor-state paths retain their
production shapes under a temporary vault.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MONITOR = ROOT / "bin" / "squad-monitor.sh"
TASK_ID = "TASK-2026-08-29-9999-board-spawn-stall-fixture"
ATTEMPT_ID = "d-0123456789abcdef0123456789abcdef"
NOW = 1_800_000_000
STALE_LOG_SECS = 600
FRESH_LOG_SECS = 120


def _shell_function(source: str, name: str, *, fallback: str = "") -> str:
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n", source)
    if match is not None:
        return match.group(0)
    if fallback:
        return fallback
    raise AssertionError(f"{name} is missing from squad-monitor.sh")


def _with_bare_board_continue(detect_stuck: str) -> str:
    """Restore the pre-fix board guard inside the extracted detector."""
    replacement = (
        "        # Board-native guard restored for the inverted control.\n"
        "        if board_spawn_live \"$task_id\"; then\n"
        "            continue\n"
        "        fi\n\n"
    )
    changed, count = re.subn(
        r"        # Board-native guard:.*?(?=        # Liveness guard 1:)",
        replacement,
        detect_stuck,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise AssertionError("could not restore the bare board-spawn continue")
    return changed


@dataclass(frozen=True)
class RunResult:
    completed: subprocess.CompletedProcess[str]
    monitor_files: tuple[str, ...]


def _run_fixture(
    *,
    log_idle_secs: int = STALE_LOG_SECS,
    receipt_status: str | None = None,
    inverted: bool = False,
    preexisting_pane_alert: bool = False,
    invocations: int = 1,
    tmux_output: str = "",
) -> RunResult:
    monitor = MONITOR.read_text(encoding="utf-8")
    detect_stuck = _shell_function(monitor, "detect_stuck")
    if inverted:
        detect_stuck = _with_bare_board_continue(detect_stuck)

    shell = (
        "set -uo pipefail\n"
        + _shell_function(monitor, "packet_to_model")
        + _shell_function(monitor, "iso_to_epoch")
        + _shell_function(monitor, "task_dispatched_epoch")
        + _shell_function(monitor, "packet_created_epoch")
        + _shell_function(monitor, "task_idle_secs")
        + _shell_function(monitor, "task_registry_status")
        + _shell_function(monitor, "task_has_completion_evidence")
        + _shell_function(monitor, "board_spawn_live")
        + _shell_function(
            monitor,
            "board_spawn_log_idle_secs",
            fallback="board_spawn_log_idle_secs() { return 1; }\n",
        )
        + detect_stuck
        + "board_dispatch_process_is_live() { return 0; }\n"
        + 'namespace_default_model() { printf "gpt-codex\\n"; }\n'
        + 'runtime_window_name() { printf "codex\\n"; }\n'
        + 'runtime_display_name() { printf "Codex\\n"; }\n'
        + 'send_alert() { printf "ALERT:%s\\n" "$1"; }\n'
        + "capture_stop_reason() { :; }\n"
        + 'tmux() { [[ -n "$TMUX_OUTPUT" ]] && printf "%s\\n" "$TMUX_OUTPUT"; }\n'
        + 'VAULT_ROOT="$1"\n'
        + 'REGISTRY="$2"\n'
        + 'STATE_DIR="$3"\n'
        + 'now="$4"\n'
        + 'TMUX_OUTPUT="$5"\n'
        + "STUCK_THRESHOLD=300\n"
        + "BOARD_SPAWN_STALL_THRESHOLD=480\n"
        + "SESSION=squad\n"
        + 'for ((run = 0; run < $6; run++)); do detect_stuck coding; done\n'
    )
    dispatched = datetime.fromtimestamp(
        NOW - 15 * 60, tz=timezone.utc
    ).isoformat()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inbox = root / "departments" / "coding" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / f"{TASK_ID}.md").write_text(
            f"---\nto_model: gpt-codex\ncreated: {dispatched}\n---\n",
            encoding="utf-8",
        )

        state = root / "_state" / "monitor"
        state.mkdir(parents=True)
        if preexisting_pane_alert:
            (state / f"stuck-task-{TASK_ID}-codex-alerted").touch()

        board = root / "_state" / "board-dispatch"
        board.mkdir(parents=True)
        base = board / f"{TASK_ID}.{ATTEMPT_ID}"
        Path(f"{base}.dispatch.json").write_text("{}\n", encoding="utf-8")
        log = Path(f"{base}.log")
        log.touch()
        log_mtime = NOW - log_idle_secs
        os.utime(log, (log_mtime, log_mtime))
        if receipt_status is not None:
            Path(f"{base}.receipt.json").write_text(
                json.dumps(
                    {
                        "task_id": TASK_ID,
                        "attempt_id": ATTEMPT_ID,
                        "generation": 1,
                        "status": receipt_status,
                    }
                ),
                encoding="utf-8",
            )

        registry = root / "_state" / "active-tasks.json"
        registry.write_text(
            json.dumps(
                {
                    TASK_ID: {
                        "status": "in-flight",
                        "dispatched_at": dispatched,
                        "delivery_attempt_id": ATTEMPT_ID,
                        "delivery_generation": 1,
                        "compatibility_namespace": "coding",
                    }
                }
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                "bash",
                "-c",
                shell,
                "--",
                str(root),
                str(registry),
                str(state),
                str(NOW),
                tmux_output,
                str(invocations),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        monitor_files = tuple(sorted(path.name for path in state.iterdir()))

    return RunResult(completed=completed, monitor_files=monitor_files)


class BoardSpawnStallAlertTests(unittest.TestCase):
    def assert_clean_run(self, result: RunResult) -> str:
        self.assertEqual(
            result.completed.returncode,
            0,
            result.completed.stderr or result.completed.stdout,
        )
        return result.completed.stdout

    def test_threshold_is_a_distinct_eight_minute_constant(self) -> None:
        monitor = MONITOR.read_text(encoding="utf-8")
        self.assertRegex(
            monitor,
            r"(?m)^BOARD_SPAWN_STALL_THRESHOLD=480(?:\s|$)",
        )
        self.assertRegex(monitor, r"(?m)^STUCK_THRESHOLD=300(?:\s|$)")

    def test_stale_live_attempt_without_receipt_alerts_with_observation(self) -> None:
        output = self.assert_clean_run(_run_fixture())
        self.assertEqual(output.count("ALERT:"), 1, output)
        self.assertIn(TASK_ID, output)
        self.assertIn(f"idle {STALE_LOG_SECS}s, no receipt", output)
        self.assertNotRegex(output.lower(), r"\b(dead|hung|killed|cancelled)\b")

    def test_fresh_live_attempt_does_not_alert(self) -> None:
        output = self.assert_clean_run(
            _run_fixture(log_idle_secs=FRESH_LOG_SECS)
        )
        self.assertNotIn("ALERT:", output, output)

    def test_terminal_receipt_suppresses_alert_regardless_of_log_age(self) -> None:
        output = self.assert_clean_run(_run_fixture(receipt_status="launched"))
        self.assertNotIn("ALERT:", output, output)

    def test_bare_continue_inversion_makes_the_positive_control_silent(self) -> None:
        output = self.assert_clean_run(_run_fixture(inverted=True))
        self.assertNotIn("ALERT:", output, output)

    def test_board_episode_alerts_once_despite_pre_spawn_pane_marker(self) -> None:
        result = _run_fixture(preexisting_pane_alert=True, invocations=2)
        output = self.assert_clean_run(result)
        self.assertEqual(output.count("ALERT:"), 1, output)
        self.assertIn(
            f"stuck-task-{TASK_ID}-codex-board-alerted",
            result.monitor_files,
        )

    def test_active_subagent_indicator_suppresses_stale_board_alert(self) -> None:
        output = self.assert_clean_run(
            _run_fixture(tmux_output="local agent fixture running")
        )
        self.assertNotIn("ALERT:", output, output)

    def test_cdp_dump_guard_remains_task_scoped(self) -> None:
        detect_stuck = _shell_function(
            MONITOR.read_text(encoding="utf-8"), "detect_stuck"
        )
        self.assertIn("/tmp/cdp_dumps", detect_stuck)
        self.assertIn('grep -qF -- "${task_id}"', detect_stuck)


if __name__ == "__main__":
    unittest.main()
