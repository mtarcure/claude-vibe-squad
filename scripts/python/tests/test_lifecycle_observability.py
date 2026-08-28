#!/usr/bin/env python3
"""Cause-aware parked-work observability regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
MONITOR = ROOT / "bin" / "squad-monitor.sh"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import registry, resume  # noqa: E402


EMPTY_VIEW = {"live": [], "deferred": [], "unclassified": {}}
COORDINATION_STATUS = "coordination_requested"


def _shell_function(source: str, name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n", source)
    if match is None:
        raise AssertionError(f"{name} is missing from squad-monitor.sh")
    return match.group(0)


class ParkedCauseCapsuleTests(unittest.TestCase):
    def render_with_queue(
        self,
        lines: list[str],
        max_tokens: int = 3000,
        *,
        include_coordination: bool = True,
    ) -> str:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            queue = base / "chrono-queue.md"
            queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
            vocabulary = registry.KNOWN_STATUSES
            if include_coordination:
                vocabulary = vocabulary | {COORDINATION_STATUS}
            with (
                mock.patch.object(resume, "QUEUE_PATH", queue),
                mock.patch.object(resume, "ARCHIVED_DEBT_ROOT", base),
                mock.patch.object(resume, "registry_view", return_value=EMPTY_VIEW),
                mock.patch.object(resume, "active_decisions", return_value=[]),
                mock.patch.object(registry, "KNOWN_STATUSES", vocabulary),
            ):
                return resume.render_capsule(
                    "session", latest_operator_turn="continue", max_tokens=max_tokens
                )

    def test_four_parked_causes_render_as_distinct_groups(self) -> None:
        capsule = self.render_with_queue(
            [
                "2026-08-26T00:00:00Z | review-required | coding/TASK-R | review",
                f"2026-08-26T00:01:00Z | {COORDINATION_STATUS} | coding/TASK-C | coordinate",
                "2026-08-26T00:02:00Z | needs_human | coding/TASK-H | decide",
                "2026-08-26T00:03:00Z | blocked | coding/TASK-B | unblock",
            ]
        )

        positions = [
            capsule.index(f"### {cause}") for cause in resume.PARKED_CAUSES
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- 1 x coding | review-required", capsule)
        self.assertIn(f"- 1 x coding | {COORDINATION_STATUS}", capsule)
        self.assertIn("- 1 x coding | needs_human", capsule)
        self.assertIn("- 1 x coding | blocked", capsule)

    def test_grouping_and_declared_omission_survive_token_truncation(self) -> None:
        statuses = (
            "review-required",
            COORDINATION_STATUS,
            "needs_human",
            "blocked",
        )
        lines = [
            f"2026-08-26T00:{index:02d}:00Z | {status} | ns{index}/TASK-{index} | parked"
            for index, status in enumerate(statuses * 12)
        ]

        # Cause-specific queue ownership lengthened the irreducible collapsed
        # capsule slightly; 190 tokens is the smallest supported fixture budget.
        capsule = self.render_with_queue(lines, max_tokens=190)

        self.assertLessEqual(len(capsule) // 4, 190)
        self.assertIn("48 group(s) omitted for the token bound", capsule)
        for cause in resume.PARKED_CAUSES:
            self.assertIn(f"{cause}=12", capsule)

    def test_coordination_signal_is_runtime_vocabulary_gated(self) -> None:
        self.assertIn(
            resume.COORDINATION_REQUESTED,
            resume.runtime_parked_status_vocabulary(),
        )
        self.assertEqual(
            resume.parked_cause(COORDINATION_STATUS),
            resume.COORDINATION_REQUESTED,
        )

        with mock.patch.object(
            resume,
            "QUEUE_ONLY_STATUSES",
            frozenset(),
        ):
            self.assertNotIn(
                resume.COORDINATION_REQUESTED,
                resume.runtime_parked_status_vocabulary(),
            )
            self.assertIsNone(resume.parked_cause(COORDINATION_STATUS))

    def test_legacy_needs_review_fallback_declares_ambiguity(self) -> None:
        capsule = self.render_with_queue(
            [
                "2026-08-26T00:00:00Z | needs_review | coding/TASK-A | ambiguous",
            ],
            include_coordination=False,
        )
        self.assertIn(f"### {resume.REVIEW_REQUIRED}", capsule)
        self.assertNotIn(f"### {resume.COORDINATION_REQUESTED}", capsule)
        self.assertNotIn("coordination signal unavailable", capsule)


class ParkedCauseMonitorTests(unittest.TestCase):
    def test_parked_row_ages_at_five_minutes_while_active_row_does_not(self) -> None:
        monitor = MONITOR.read_text(encoding="utf-8")
        shell = (
            "set -uo pipefail\n"
            + _shell_function(monitor, "task_registry_status")
            + _shell_function(monitor, "task_parked_cause")
            + _shell_function(monitor, "detect_stale_active")
            + 'board_spawn_live() { return 1; }\n'
            + 'send_alert() { printf "ALERT:%s\\n" "$1"; }\n'
            + 'VAULT_ROOT="$1"\n'
            + 'REGISTRY="$2"\n'
            + 'STATE_DIR="$3"\n'
            + 'PYTHON_DIR="$4"\n'
            + 'now="$5"\n'
            + 'PARKED_THRESHOLD=300\n'
            + 'STALE_THRESHOLD=1800\n'
            + 'detect_stale_active coding\n'
        )
        now = 1_800_000_000
        parked_id = "TASK-2026-08-26-parked"
        active_id = "TASK-2026-08-26-active"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active_dir = root / "departments" / "coding" / "active"
            active_dir.mkdir(parents=True)
            parked = active_dir / f"{parked_id}.md"
            active = active_dir / f"{active_id}.md"
            parked.write_text("parked\n", encoding="utf-8")
            active.write_text("active\n", encoding="utf-8")
            six_minutes_old = now - 6 * 60
            os.utime(parked, (six_minutes_old, six_minutes_old))
            os.utime(active, (six_minutes_old, six_minutes_old))
            state = root / "_state" / "monitor"
            state.mkdir(parents=True)
            registry_path = root / "_state" / "active-tasks.json"
            registry_path.write_text(
                json.dumps(
                    {
                        parked_id: {"status": "needs_review"},
                        active_id: {"status": "in-flight"},
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
                    str(registry_path),
                    str(state),
                    str(PYTHON_DIR),
                    str(now),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ALERT:REVIEW-REQUIRED:", completed.stdout)
        self.assertIn(parked_id, completed.stdout)
        self.assertNotIn(active_id, completed.stdout)


if __name__ == "__main__":
    unittest.main()
