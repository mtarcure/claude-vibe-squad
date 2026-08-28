"""Standing Skill telemetry and bounded worker-transcript retention."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "python" / "dispatch_log.py"
WATCHER = ROOT / "bin" / "outbox-watcher.sh"
PRUNER = ROOT / "bin" / "prune-board-worktrees.sh"

SPEC = importlib.util.spec_from_file_location("dispatch_log", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
dispatch_log = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dispatch_log
SPEC.loader.exec_module(dispatch_log)


class SkillTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.state = self.repo / "_state"
        self.board = self.state / "board-dispatch"
        self.board.mkdir(parents=True)

    def _write_registry(self, entries: dict[str, object]) -> None:
        (self.state / "active-tasks.json").write_text(
            json.dumps(entries) + "\n", encoding="utf-8"
        )

    def _write_dispatch_log(self, rows: list[dict[str, object]]) -> Path:
        path = self.state / "dispatch-log.jsonl"
        path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def _write_attempt(
        self,
        task_id: str,
        attempt_id: str,
        events: list[object],
    ) -> tuple[Path, Path]:
        base = self.board / f"{task_id}.{attempt_id}"
        transcript = Path(f"{base}.log")
        transcript.write_text(
            "".join(
                event + "\n"
                if isinstance(event, str)
                else json.dumps(event, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        descriptor = Path(f"{base}.dispatch.json")
        descriptor.write_text(
            json.dumps(
                {
                    "schema": "board-dispatch-process/v2",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "log_path": str(transcript),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return descriptor, transcript

    def test_recorded_skill_invocation_appears_in_dispatch_log(self) -> None:
        task_id = "TASK-positive"
        attempt_id = "d-positive"
        self._write_registry(
            {task_id: {"delivery_attempt_id": attempt_id, "status": "complete"}}
        )
        path = self._write_dispatch_log(
            [{"ts": "now", "task_id": task_id, "specialist": "devops-engineer"}]
        )
        self._write_attempt(
            task_id,
            attempt_id,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Skill"},
                            {"type": "tool_use", "name": "Read"},
                        ]
                    },
                },
                {"type": "result", "text": "Skill is only text here"},
            ],
        )

        result = dispatch_log.record_skill_telemetry(self.repo, task_id)

        row = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result.skills, 1)
        self.assertEqual(row["skills"], 1)

    def test_no_skill_use_records_explicit_zero(self) -> None:
        task_id = "TASK-zero"
        attempt_id = "d-zero"
        self._write_registry(
            {task_id: {"delivery_attempt_id": attempt_id, "status": "complete"}}
        )
        path = self._write_dispatch_log(
            [{"ts": "now", "task_id": task_id, "specialist": "devops-engineer"}]
        )
        self._write_attempt(
            task_id,
            attempt_id,
            [{"type": "tool_use", "name": "Read"}],
        )

        result = dispatch_log.record_skill_telemetry(self.repo, task_id)

        row = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result.skills, 0)
        self.assertIn("skills", row)
        self.assertEqual(row["skills"], 0)

    def test_unparseable_transcript_does_not_fabricate_zero(self) -> None:
        task_id = "TASK-unreadable"
        attempt_id = "d-unreadable"
        self._write_registry(
            {task_id: {"delivery_attempt_id": attempt_id, "status": "complete"}}
        )
        path = self._write_dispatch_log(
            [{"ts": "now", "task_id": task_id, "specialist": "devops-engineer"}]
        )
        self._write_attempt(task_id, attempt_id, ["not json"])

        with self.assertRaises(dispatch_log.DispatchLogError):
            dispatch_log.record_skill_telemetry(self.repo, task_id)

        self.assertNotIn("skills", json.loads(path.read_text(encoding="utf-8")))

    def test_legacy_rows_stay_parseable_and_absent_is_distinct_from_zero(self) -> None:
        task_id = "TASK-new-zero"
        attempt_id = "d-new-zero"
        self._write_registry(
            {task_id: {"delivery_attempt_id": attempt_id, "status": "complete"}}
        )
        legacy_rows = [
            {
                "ts": f"legacy-{index}",
                "task_id": f"TASK-legacy-{index}",
                "specialist": "devops-engineer",
            }
            for index in range(2180)
        ]
        path = self._write_dispatch_log(
            legacy_rows
            + [{"ts": "new", "task_id": task_id, "specialist": "devops-engineer"}]
        )
        first_line_before = path.read_bytes().splitlines(keepends=True)[0]
        self._write_attempt(
            task_id,
            attempt_id,
            [{"type": "tool_use", "name": "Read"}],
        )

        dispatch_log.record_skill_telemetry(self.repo, task_id)

        lines = path.read_bytes().splitlines(keepends=True)
        rows = [json.loads(line) for line in lines]
        self.assertEqual(len(rows), 2181)
        self.assertEqual(lines[0], first_line_before)
        self.assertNotIn("skills", rows[0])
        self.assertIn("skills", rows[-1])
        self.assertEqual(rows[-1]["skills"], 0)

    def test_retention_keeps_live_and_recent_but_expires_old_settled_logs(self) -> None:
        now = 2_000_000_000.0
        live_task = "TASK-live"
        recent_task = "TASK-recent"
        old_task = "TASK-old"
        self._write_registry(
            {
                live_task: {"status": "in-flight"},
                recent_task: {"status": "complete"},
                old_task: {"status": "complete"},
            }
        )
        _live_descriptor, live_log = self._write_attempt(
            live_task, "d-live", [{"type": "result"}]
        )
        _recent_descriptor, recent_log = self._write_attempt(
            recent_task, "d-recent", [{"type": "result"}]
        )
        _old_descriptor, old_log = self._write_attempt(
            old_task, "d-old", [{"type": "result"}]
        )
        os.utime(live_log, (now - 90 * 86400, now - 90 * 86400))
        os.utime(recent_log, (now - 10 * 86400, now - 10 * 86400))
        os.utime(old_log, (now - 31 * 86400, now - 31 * 86400))

        report = dispatch_log.enforce_transcript_retention(
            self.repo, retention_days=30, apply=False, now=now
        )
        self.assertEqual(report.retained_live, 1)
        self.assertEqual(report.retained_recent, 1)
        self.assertEqual(report.expired, 1)
        self.assertEqual(report.removed, 0)
        self.assertTrue(old_log.is_file(), "report mode must not delete")

        with mock.patch.object(Path, "unlink") as unlink:
            applied = dispatch_log.enforce_transcript_retention(
                self.repo, retention_days=30, apply=True, now=now
            )
        self.assertEqual(applied.removed, 1)
        unlink.assert_called_once_with()

    def test_registered_concurrent_append_is_preserved_during_update(self) -> None:
        target = "TASK-update-target"
        queued = "TASK-concurrent-queued"
        path = self._write_dispatch_log(
            [{"ts": "target", "task_id": target, "specialist": "devops-engineer"}]
        )
        self._write_registry(
            {
                target: {"status": "complete", "delivery_generation": 1},
                queued: {
                    "status": "in-flight",
                    "delivery_state": "queued",
                    "delivery_generation": 1,
                },
            }
        )

        def finish_registered_append() -> None:
            time.sleep(0.05)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "ts": "concurrent",
                            "task_id": queued,
                            "specialist": "test-engineer",
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )

        appender = threading.Thread(target=finish_registered_append)
        appender.start()
        try:
            dispatch_log.update_dispatch_log(self.repo, target, 0)
        finally:
            appender.join(timeout=1)
        self.assertFalse(appender.is_alive())

        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["task_id"] for row in rows], [target, queued])
        self.assertEqual(rows[0]["skills"], 0)

    def test_production_wiring_is_not_staged(self) -> None:
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertIn(
            'python3 "${VAULT_ROOT}/scripts/python/dispatch_log.py" record-skills',
            watcher,
        )
        self.assertIn(
            'if [[ "$reconciler_handled" == 1 ]]; then\n'
            '            record_skill_telemetry_best_effort "$task_id"',
            watcher,
        )

        pruner = PRUNER.read_text(encoding="utf-8")
        self.assertIn("TRANSCRIPT_RETENTION_DAYS=30", pruner)
        self.assertIn("enforce_transcript_retention(", pruner)
        self.assertIn('apply=mode == "apply"', pruner)


if __name__ == "__main__":
    unittest.main()
