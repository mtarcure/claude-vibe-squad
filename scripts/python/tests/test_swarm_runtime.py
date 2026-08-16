"""Hermetic tests for the live mailbox reconciliation sweep."""

from __future__ import annotations

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


class SwarmRuntimeTest(unittest.TestCase):
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
