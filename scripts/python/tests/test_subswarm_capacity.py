"""Capacity, output-isolation, and real DAG-runtime tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from subswarm_capacity import (  # noqa: E402
    DEFAULT_SUBAGENT_CODE_CEILING,
    CapacityError,
    compute_subswarm_capacity,
    subagent_code_ceiling,
)
from swarm_diff import seal_orchestration_directive  # noqa: E402
from swarm_runtime import run_subswarm_directive  # noqa: E402


FEATURE = "SQUAD_SUBSWARM_ORCHESTRATION_ENABLED"
CAP = "SQUAD_SUBAGENT_CONCURRENCY_CAP"


class SubswarmCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flags = patch.dict(os.environ, {FEATURE: "1", CAP: "16"}, clear=False)
        self.flags.start()

    def tearDown(self) -> None:
        self.flags.stop()

    def directive(self, count: int, dependencies: dict[int, list[int]] | None = None) -> dict:
        dependencies = dependencies or {}
        members = []
        for index in range(1, count + 1):
            members.append(
                {
                    "member_id": f"gpt-codex:sub{index:02d}",
                    "lane": "gpt-codex",
                    "replica_index": index,
                    "role": "systems-engineer",
                    "objective_sha256": f"{index:064x}",
                    "output_path": f"_state/subswarm/TASK-CAPACITY/gpt-codex/sub{index:02d}/result.json",
                    "requires_mcp": False,
                    "tool_mode": "none",
                    "depends_on": [f"gpt-codex:sub{item:02d}" for item in dependencies.get(index, [])],
                }
            )
        return seal_orchestration_directive(
            {
                "schema_version": "lead-orchestration-directive/v1",
                "parent_task_id": "TASK-CAPACITY",
                "lane": "gpt-codex",
                "mode": "parallel",
                "max_concurrency": count,
                "members": members,
            }
        )

    @staticmethod
    def healthy_snapshot() -> dict[str, object]:
        return {
            "used_memory_mib": 2048,
            "memory_pressure": False,
            "swap_active": False,
            "compressor_pressure": False,
        }

    def test_code_ceiling_is_high_configurable_and_fail_closed(self) -> None:
        self.assertGreaterEqual(DEFAULT_SUBAGENT_CODE_CEILING, 12)
        self.assertEqual(subagent_code_ceiling({}), DEFAULT_SUBAGENT_CODE_CEILING)
        self.assertEqual(subagent_code_ceiling({CAP: "24"}), 24)
        for raw in ("0", "bogus", "65"):
            with self.subTest(raw=raw), self.assertRaises(CapacityError):
                subagent_code_ceiling({CAP: raw})

    def test_host_ceiling_reports_code_host_and_effective_numbers(self) -> None:
        capacity = compute_subswarm_capacity(
            code_ceiling=16,
            member_count=12,
            requested_concurrency=12,
            host_snapshot=self.healthy_snapshot(),
            host_memory_mib=32768,
            memory_high_water_mib=28672,
            worker_memory_estimate_mib=1024,
            logical_cpu_count=12,
            one_minute_load=1.0,
        )
        self.assertTrue(capacity["admitted"])
        self.assertEqual(capacity["code_ceiling"], 16)
        self.assertEqual(capacity["host_ceiling"], 11)
        self.assertEqual(capacity["effective_concurrency"], 11)

        pressured = dict(self.healthy_snapshot(), memory_pressure=True)
        denied = compute_subswarm_capacity(
            code_ceiling=16,
            member_count=8,
            requested_concurrency=8,
            host_snapshot=pressured,
            host_memory_mib=32768,
            memory_high_water_mib=28672,
            worker_memory_estimate_mib=1024,
            logical_cpu_count=12,
            one_minute_load=1.0,
        )
        self.assertFalse(denied["admitted"])
        self.assertEqual(denied["host_ceiling"], 0)

    def test_real_eight_process_run_uses_distinct_outputs(self) -> None:
        directive = self.directive(8)
        commands = {
            member["member_id"]: [
                sys.executable,
                "-c",
                f"import time; time.sleep(0.05); print('{member['member_id']}')",
            ]
            for member in directive["members"]
        }
        with tempfile.TemporaryDirectory(prefix="subswarm-capacity-") as raw:
            root = Path(raw)
            evidence = root / "evidence.json"
            result = run_subswarm_directive(
                directive,
                commands,
                evidence_output=evidence,
                repo_root=root,
                host_snapshot=self.healthy_snapshot(),
                host_memory_mib=32768,
                memory_high_water_mib=28672,
                worker_memory_estimate_mib=1024,
                logical_cpu_count=12,
                one_minute_load=1.0,
                timeout_seconds=5,
            )
            self.assertEqual(result["member_count"], 8)
            self.assertGreaterEqual(result["peak_concurrency"], 4)
            outputs = [root / member["output_path"] for member in directive["members"]]
            self.assertEqual(len(set(outputs)), 8)
            self.assertTrue(all(path.is_file() for path in outputs))
            self.assertEqual(
                {json.loads(path.read_text())["member_id"] for path in outputs},
                {member["member_id"] for member in directive["members"]},
            )

    def test_mixed_dag_join_starts_only_after_parallel_roots_finish(self) -> None:
        directive = self.directive(3, {3: [1, 2]})
        commands = {
            "gpt-codex:sub01": [sys.executable, "-c", "import time; time.sleep(.08); print('one')"],
            "gpt-codex:sub02": [sys.executable, "-c", "import time; time.sleep(.08); print('two')"],
            "gpt-codex:sub03": [sys.executable, "-c", "print('join')"],
        }
        with tempfile.TemporaryDirectory(prefix="subswarm-dag-") as raw:
            result = run_subswarm_directive(
                directive,
                commands,
                evidence_output=Path(raw) / "evidence.json",
                repo_root=Path(raw),
                host_snapshot=self.healthy_snapshot(),
                host_memory_mib=32768,
                memory_high_water_mib=28672,
                worker_memory_estimate_mib=1024,
                logical_cpu_count=12,
                one_minute_load=1.0,
                timeout_seconds=5,
            )
        by_id = {member["member_id"]: member for member in result["members"]}
        self.assertGreaterEqual(
            by_id["gpt-codex:sub03"]["started_ns"],
            max(by_id["gpt-codex:sub01"]["finished_ns"], by_id["gpt-codex:sub02"]["finished_ns"]),
        )
        self.assertEqual(result["peak_concurrency"], 2)


if __name__ == "__main__":
    unittest.main()
