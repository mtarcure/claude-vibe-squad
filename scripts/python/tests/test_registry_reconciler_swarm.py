"""Pins the one intentional reconciler guard for retired swarm records.

The live transport is gone. Historical registry rows remain fail-closed because
repairing them as ordinary single tasks would erase their settlement semantics.
General registration/reconciliation coverage formerly housed here now lives in
``test_capability_dispatch_integrity.RegistryReconcilerContractTests``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import registry_reconciler as rr  # noqa: E402


class RetiredSwarmRegistryTests(unittest.TestCase):
    def test_historical_swarm_entry_cannot_be_repaired_as_single(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "_state" / "active-tasks.json"
            registry.parent.mkdir(parents=True)
            task_id = "TASK-RETIRED-SWARM"
            registry.write_text(
                json.dumps(
                    {
                        task_id: {
                            "dispatch_kind": "swarm",
                            "status": "blocked",
                        }
                    }
                ),
                encoding="utf-8",
            )
            patches = (
                patch.dict(os.environ, {rr.TEST_ISOLATION_ENV: "1"}),
                patch.object(rr, "VAULT_ROOT", root),
                patch.object(rr, "STATE_DIR", root / "_state"),
                patch.object(rr, "REGISTRY_PATH", registry),
            )
            for item in patches:
                item.start()
                self.addCleanup(item.stop)

            with self.assertRaisesRegex(
                ValueError, "retired swarm transport task cannot be repaired"
            ):
                rr.repair_promoted_envelope(task_id)

if __name__ == "__main__":
    unittest.main()
