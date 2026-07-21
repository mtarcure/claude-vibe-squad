"""Hermetic production-runtime tests for host sampling, sweep, and scan delivery."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[3]
RUNTIME_PATH = REPO / "scripts/python/swarm_runtime.py"
spec = importlib.util.spec_from_file_location("swarm_runtime_tested", RUNTIME_PATH)
assert spec and spec.loader
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


VM_HEALTHY = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               200000.
Pages inactive:                           300000.
Pages speculative:                        10000.
Pages purgeable:                           10000.
Pages occupied by compressor:              10000.
"""

VM_PRESSURE = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                 1000.
Pages inactive:                             1000.
Pages speculative:                            0.
Pages purgeable:                              0.
Pages occupied by compressor:             300000.
"""


class SwarmRuntimeTest(unittest.TestCase):
    def runner(self, vm: str, *, free: int, swap: float):
        def run(command: list[str], _timeout: float) -> str:
            joined = " ".join(command)
            if "hw.memsize" in joined:
                return str(16 * 1024 * 1024 * 1024)
            if "vm_stat" in joined:
                return vm
            if "memory_pressure" in joined:
                return f"System-wide memory free percentage: {free}%\n"
            if "vm.swapusage" in joined:
                return f"total = 2048.00M  used = {swap:.2f}M  free = 2048.00M\n"
            raise AssertionError(command)
        return run

    def test_live_host_sampler_admits_healthy_and_denies_pressure(self):
        healthy = runtime.sample_macos_host(
            16384, 14336, run_text=self.runner(VM_HEALTHY, free=35, swap=0)
        )
        self.assertFalse(healthy["memory_pressure"])
        self.assertFalse(healthy["swap_active"])
        self.assertFalse(healthy["compressor_pressure"])
        self.assertLess(healthy["used_memory_mib"], 14336)

        pressured = runtime.sample_macos_host(
            16384, 14336, run_text=self.runner(VM_PRESSURE, free=5, swap=512)
        )
        self.assertTrue(pressured["memory_pressure"])
        self.assertTrue(pressured["swap_active"])
        self.assertTrue(pressured["compressor_pressure"])

        fallback = runtime.sample_macos_host(
            16384, 14336,
            run_text=lambda _command, _timeout: (_ for _ in ()).throw(OSError("missing")),
        )
        self.assertEqual(fallback["used_memory_mib"], 16384)
        self.assertTrue(fallback["memory_pressure"])

    def test_direct_fence_delivery_uses_worker_claim_without_reauthorization(self):
        with tempfile.TemporaryDirectory(prefix="worker-delivery-") as raw:
            root = Path(raw)
            task = root / "departments/coding/inbox/TASK-idle.md"
            task.parent.mkdir(parents=True)
            task.write_text("---\nid: TASK-idle\n---\n", encoding="utf-8")
            fake_tmux = root / "tmux"
            fake_tmux.write_text(
                "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$TMUX_LOG\"\n",
                encoding="utf-8",
            )
            fake_tmux.chmod(0o755)
            log = root / "tmux.log"
            fence = {
                "task_id": "TASK-idle", "delivery_lane": "gpt-codex",
                "delivery_attempt_id": "d-one", "delivery_worker_id": "gpt-codex-lead",
                "worker_epoch": "epoch-one", "lease_generation": 1,
            }
            with patch.object(runtime, "VAULT_ROOT", root), patch.dict(
                os.environ, {"TMUX_BIN": str(fake_tmux), "TMUX_LOG": str(log),
                             "SQUAD_SESSION": "test"}, clear=False,
            ):
                runtime.deliver_fence(fence)
            sent = log.read_text(encoding="utf-8")
            self.assertIn("claim-task.sh' 'TASK-idle' 'd-one' 'gpt-codex-lead'", sent)
            self.assertIn("'epoch-one' '1' 'gpt-codex'", sent)
            self.assertNotIn("authorize-delivery", sent)

    def test_scan_consumer_delivers_every_returned_work_not_only_new(self):
        policy = type("Policy", (), {
            "host_memory_mib": 16384, "memory_high_water_mib": 14336,
            "nudge_scan_interval_seconds": 5, "policy_sha256": "approved-hash",
        })()
        scan = {
            "new_assignments": [{"task_id": "TASK-new"}],
            "work": [
                {"task_id": "TASK-new"},
                {"task_id": "TASK-replay"},
            ],
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(scan), "")
        delivered: list[str] = []
        with patch.dict(os.environ, {
            "SQUAD_WORKER_POOL_ENABLED": "1",
            "SQUAD_WORKER_POOL_GUARDS_ENABLED": "1",
            "SQUAD_WORKER_POOL_POLICY_REVIEW_STATE": "approved",
            "SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256": "approved-hash",
            "SQUAD_PROVIDER_STATES_JSON": json.dumps({lane: "ready" for lane in runtime.LANES}),
        }, clear=False), patch.object(runtime, "load_worker_pool_policy", return_value=policy), \
             patch.object(runtime, "sample_macos_host", return_value={
                 "used_memory_mib": 1000, "memory_pressure": False,
                 "swap_active": False, "compressor_pressure": False,
             }), patch.object(runtime, "live_workers", return_value=[]), \
             patch.object(runtime.subprocess, "run", return_value=completed), \
             patch.object(runtime, "deliver_fence",
                          side_effect=lambda fence: delivered.append(fence["task_id"])):
            result = runtime.scan_once(datetime(2026, 7, 19, tzinfo=UTC))
        self.assertEqual(delivered, ["TASK-new", "TASK-replay"])
        self.assertEqual(result["delivered"], delivered)

    def test_reconcile_sweep_times_out_hung_process_and_keeps_control(self):
        with patch.dict(os.environ, {"SQUAD_RECONCILE_SWEEP_TIMEOUT_SECONDS": "0.01"}), \
             patch.object(runtime.subprocess, "run", side_effect=subprocess.TimeoutExpired([], .01)):
            result = runtime.reconcile_once()
        self.assertEqual(result, {"ok": False, "timeout": True})

    def test_reconcile_sweep_settles_preexisting_response_without_watcher_event(self):
        with tempfile.TemporaryDirectory(prefix="reconcile-sweep-") as raw:
            root = Path(raw)
            (root / "_state").mkdir()
            (root / "shared").mkdir()
            (root / "shared/specialist-runtime-map.tsv").write_text(
                "specialist\tc2\tc3\tc4\tc5\tc6\tprimary_lane\n"
                "systems-engineer\tx\tx\tx\tx\tx\tcodex\n", encoding="utf-8"
            )
            task_id = "TASK-sweep-landed"
            entry = {
                "compatibility_namespace": "coding", "source_namespace": "coding",
                "specialist": "systems-engineer", "to_model": "gpt-codex",
                "mandatory_review": "false", "review_model": "none",
                "status": "in-flight",
            }
            (root / "_state/active-tasks.json").write_text(
                json.dumps({task_id: entry}), encoding="utf-8"
            )
            response = root / f"departments/coding/outbox/{task_id}-response.md"
            response.parent.mkdir(parents=True)
            response.write_text(
                "---\n" f"id: {task_id}-response\n" f"in_response_to: {task_id}\n"
                "from: gpt-codex\nto: chrono\ntype: RESULT\nstatus: complete\n---\n\ndone\n",
                encoding="utf-8",
            )
            wrapper = root / "bin/registry-reconciler.sh"
            wrapper.parent.mkdir()
            wrapper.write_text(
                f"#!/bin/bash\nexec '{sys.executable}' '{REPO / 'scripts/python/registry_reconciler.py'}' \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            with patch.object(runtime, "VAULT_ROOT", root), patch.dict(os.environ, {
                "VAULT_ROOT": str(root), "RESPONSE_MIN_AGE_SECONDS": "0",
                "TMUX_BIN": "/nonexistent/tmux", "SQUAD_SESSION": "none",
            }, clear=False):
                result = runtime.reconcile_once()
            final = json.loads((root / "_state/active-tasks.json").read_text())[task_id]
            self.assertTrue(result["ok"], result)
            self.assertEqual(final["status"], "complete")


if __name__ == "__main__":
    unittest.main()
