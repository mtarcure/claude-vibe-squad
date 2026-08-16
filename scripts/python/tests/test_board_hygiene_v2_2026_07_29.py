#!/usr/bin/env python3
"""Focused regressions for the 2026-07-29 board-hygiene v2 fixes."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TEST_ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION_ROOT = Path(
    os.environ.get("BOARD_HYGIENE_V2_IMPLEMENTATION_ROOT", TEST_ROOT)
).resolve()
PYTHON_DIR = IMPLEMENTATION_ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
import registry_reconciler as reconciler  # noqa: E402


class ModeAwareTimeoutTests(unittest.TestCase):
    def test_mode_budget_map_and_recoverable_timeout_owner(self) -> None:
        self.assertEqual(dcb.timeout_budget_for_mode("bounty"), 3600)
        for mode in ("project", "advisory", "canary", ""):
            with self.subTest(mode=mode):
                self.assertEqual(dcb.timeout_budget_for_mode(mode), 2700)

        supervisor = (
            IMPLEMENTATION_ROOT / "bin" / "board-supervisor.sh"
        ).read_text(encoding="utf-8")
        detached = supervisor[
            supervisor.index('if [[ "${1:-}" == "detached-launch" ]]') :
            supervisor.index('if [[ "${1:-}" == "trusted-launch" ]]')
        ]
        self.assertNotIn("timeout_bin", detached)
        self.assertNotIn("--kill-after", detached)
        self.assertRegex(
            supervisor,
            (
                r'authority\["mode_profile"\] == "bounty"\s+'
                r'and 2700 < budgets\["timeout_seconds"\] <= 3600'
            ),
        )


class TerminalReceiptAutoCloseTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def _runtime(root: Path):
        state = root / "_state"
        registry = state / "active-tasks.json"
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry),
            mock.patch.object(
                reconciler,
                "CHRONO_QUEUE_PATH",
                state / "chrono-queue.md",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_LOCKDIR",
                state / "chrono-notify.lockdir",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                state / "chrono-notify-receipts",
            ),
            mock.patch.object(reconciler, "notification_due", return_value=False),
            mock.patch.object(reconciler, "emit_event", return_value=False),
            mock.patch.dict(
                "os.environ",
                {reconciler.TEST_ISOLATION_ENV: "1"},
            ),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield state, registry

    @staticmethod
    def _stage(
        root: Path,
        *,
        task_id: str,
        receipt_status: str,
        mandatory_review: bool,
    ) -> tuple[Path, Path]:
        state = root / "_state"
        attempt_id = "d-" + "a" * 32
        registry = state / "active-tasks.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                {
                    task_id: {
                        "status": "in-flight",
                        "specialist": "systems-engineer",
                        "to_model": "claude",
                        "review_model": "gpt-codex",
                        "mandatory_review": str(mandatory_review).lower(),
                        "compatibility_namespace": "coding",
                        "source_namespace": "coding",
                        "write_scope": ["_state/board-hygiene-test/"],
                        "return_artifact": "artifact.md",
                        "delivery_attempt_id": attempt_id,
                        "delivery_generation": 1,
                        "delivery_state": "in-progress",
                        "dispatched_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        packet = (
            root
            / "departments"
            / "coding"
            / "inbox"
            / f"{task_id}.md"
        )
        packet.parent.mkdir(parents=True)
        packet.write_text(f"---\nid: {task_id}\n---\n", encoding="utf-8")
        receipt = (
            state
            / "board-dispatch"
            / f"{task_id}.{attempt_id}.receipt.json"
        )
        receipt.parent.mkdir(parents=True)
        receipt.write_text(
            json.dumps(
                {
                    "status": receipt_status,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "generation": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "artifact.md").write_text(
            "blocked\n\n"
            f"# Board dispatch blocked — {task_id}\n\n"
            "Controller reason: fixture terminal receipt\n",
            encoding="utf-8",
        )
        return packet, receipt

    def test_terminal_receipts_auto_close_and_archive_idempotently(self) -> None:
        for index, receipt_status in enumerate(("blocked", "complete", "completed")):
            with self.subTest(receipt_status=receipt_status):
                task_id = (
                    f"TASK-2026-07-29-91{index:02d}-receipt-{receipt_status}"
                )
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    packet, _receipt = self._stage(
                        root,
                        task_id=task_id,
                        receipt_status=receipt_status,
                        mandatory_review=False,
                    )
                    with self._runtime(root) as (_state, registry_path):
                        changed, messages = reconciler.reconcile(
                            task_id, dry_run=False
                        )
                        retry_changed, retry_messages = reconciler.reconcile(
                            task_id, dry_run=False
                        )
                        idempotent_changed, idempotent_messages = (
                            reconciler.reconcile(task_id, dry_run=False)
                        )

                    entry = json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )[task_id]
                    archived = (
                        root
                        / "departments"
                        / "coding"
                        / "archive"
                        / f"{task_id}.md"
                    )
                    self.assertGreater(changed, 0, messages)
                    self.assertGreater(retry_changed, 0, retry_messages)
                    self.assertEqual(
                        idempotent_changed, 0, idempotent_messages
                    )
                    self.assertEqual(entry["status"], "closed")
                    self.assertEqual(
                        entry["closed_from_status"],
                        "blocked" if receipt_status == "blocked" else "complete",
                    )
                    self.assertEqual(
                        entry["lifecycle_closed_by"],
                        "registry-reconciler-auto",
                    )
                    self.assertEqual(len(entry["closure_history"]), 1)
                    self.assertFalse(packet.exists())
                    self.assertTrue(archived.is_file())
                    self.assertFalse((root / "artifact.md").exists())
                    self.assertTrue(
                        (
                            root
                            / f"artifact.md.blocked-{task_id}"
                        ).is_file(),
                        "the production reconcile path must retire the exact task's "
                        "blocked stub when lifecycle closure frees its artifact path",
                    )

    def test_pending_mandatory_review_is_never_auto_closed(self) -> None:
        task_id = "TASK-2026-07-29-9199-receipt-review-hold"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._stage(
                root,
                task_id=task_id,
                receipt_status="complete",
                mandatory_review=True,
            )
            with self._runtime(root) as (_state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], reconciler.REVIEW_REQUIRED)
            self.assertEqual(entry["review_required_by"], "gpt-codex")
            self.assertNotIn("lifecycle_closed_at", entry)
            self.assertNotIn("closure_history", entry)


def _shell_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"{name} is missing from squad-monitor.sh")
    return match.group(0)


class AwaitingReviewMonitorTests(unittest.TestCase):
    def _run_status(self, status: str) -> subprocess.CompletedProcess[str]:
        monitor = (
            IMPLEMENTATION_ROOT / "bin" / "squad-monitor.sh"
        ).read_text(encoding="utf-8")
        shell = (
            "set -uo pipefail\n"
            + _shell_function(monitor, "task_registry_status")
            + _shell_function(monitor, "detect_stale_active")
            + 'send_alert() { printf "ALERT:%s\\n" "$1"; }\n'
            + "board_spawn_live() { return 1; }\n"
            + 'stat() { printf "%s\\n" "$((now - STALE_THRESHOLD - 60))"; }\n'
            + 'VAULT_ROOT="$1"\n'
            + 'REGISTRY="$2"\n'
            + 'STATE_DIR="$3"\n'
            + "now=1800000000\n"
            + "STALE_THRESHOLD=1800\n"
            + 'detect_stale_active "coding"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "departments" / "coding" / "active"
            active.mkdir(parents=True)
            task_id = "TASK-2026-07-29-9299-monitor-review"
            (active / f"{task_id}.md").write_text("task\n", encoding="utf-8")
            state = root / "_state" / "monitor"
            state.mkdir(parents=True)
            registry = root / "_state" / "active-tasks.json"
            registry.write_text(
                json.dumps({task_id: {"status": status}}) + "\n",
                encoding="utf-8",
            )
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    shell,
                    "--",
                    str(root),
                    str(registry),
                    str(state),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_review_holds_are_informational_but_active_tasks_stay_stale(self) -> None:
        for status in ("needs_review", reconciler.REVIEW_REQUIRED):
            with self.subTest(status=status):
                completed = self._run_status(status)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("INFO:", completed.stdout)
                self.assertIn("awaiting review", completed.stdout)
                self.assertNotIn("ALERT:", completed.stdout)

        active = self._run_status("in-flight")
        self.assertEqual(active.returncode, 0, active.stderr)
        self.assertIn("ALERT:", active.stdout)
        self.assertIn("stale active task", active.stdout)


if __name__ == "__main__":
    unittest.main()
