"""Regression tests for completion racing the squad stall monitor."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MONITOR = ROOT / "bin" / "squad-monitor.sh"
TASK_ID = "TASK-2026-08-11-9999-monitor-completion-race"


def _shell_function(source: str, name: str, *, fallback: str = "") -> str:
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n", source)
    if match is not None:
        return match.group(0)
    if fallback:
        return fallback
    raise AssertionError(f"{name} is missing from squad-monitor.sh")


class MonitorCompletionEvidenceTests(unittest.TestCase):
    def test_response_landing_during_liveness_check_prevents_idle_alert(self) -> None:
        monitor = MONITOR.read_text(encoding="utf-8")
        completion_fallback = "task_has_completion_evidence() { return 1; }\n"
        shell = (
            "set -uo pipefail\n"
            + _shell_function(monitor, "packet_to_model")
            + _shell_function(monitor, "iso_to_epoch")
            + _shell_function(monitor, "task_dispatched_epoch")
            + _shell_function(monitor, "packet_created_epoch")
            + _shell_function(monitor, "task_idle_secs")
            + _shell_function(monitor, "task_registry_status")
            + _shell_function(
                monitor,
                "task_has_completion_evidence",
                fallback=completion_fallback,
            )
            + _shell_function(monitor, "detect_stuck")
            + 'runtime_window_name() { printf "%s\\n" "$1"; }\n'
            + 'runtime_display_name() { printf "%s\\n" "$1"; }\n'
            + 'send_alert() { printf "ALERT:%s\\n" "$1"; }\n'
            + 'capture_stop_reason() { :; }\n'
            + 'tmux() { return 1; }\n'
            # Model the observed ordering: no response at the detector's first
            # check, then completion is promoted while liveness is inspected.
            + 'board_spawn_live() {\n'
            + '  mkdir -p "$VAULT_ROOT/departments/sysmgmt/outbox"\n'
            + '  printf "%s\\n" "---" "status: complete" "---" > '
            + '"$VAULT_ROOT/departments/sysmgmt/outbox/'
            + TASK_ID
            + '-response.md"\n'
            + '  return 1\n'
            + '}\n'
            + 'VAULT_ROOT="$1"\n'
            + 'REGISTRY="$2"\n'
            + 'STATE_DIR="$3"\n'
            + 'now="$4"\n'
            + 'STUCK_THRESHOLD=300\n'
            + 'SESSION=squad\n'
            + 'detect_stuck sysmgmt\n'
        )
        now = 1_800_000_000
        dispatched = datetime.fromtimestamp(
            now - 13 * 60, tz=timezone.utc
        ).isoformat()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "departments" / "sysmgmt" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / f"{TASK_ID}.md").write_text(
                "---\nto_model: claude\ncreated: " + dispatched + "\n---\n",
                encoding="utf-8",
            )
            state = root / "_state" / "monitor"
            state.mkdir(parents=True)
            registry = root / "_state" / "active-tasks.json"
            registry.write_text(
                json.dumps(
                    {
                        TASK_ID: {
                            "status": "in-flight",
                            "dispatched_at": dispatched,
                            "compatibility_namespace": "sysmgmt",
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
                    str(now),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("ALERT:", completed.stdout, completed.stdout)


if __name__ == "__main__":
    unittest.main()
