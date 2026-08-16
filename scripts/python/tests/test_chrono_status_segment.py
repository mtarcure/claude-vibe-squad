from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ChronoStatusSegmentTests(unittest.TestCase):
    def test_unclassified_registry_status_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_root = Path(directory)
            (fixture_root / "bin").mkdir()
            shutil.copy2(
                ROOT / "bin" / "doctor-log-home.sh",
                fixture_root / "bin" / "doctor-log-home.sh",
            )
            package = fixture_root / "scripts" / "python" / "chrono_state"
            package.mkdir(parents=True)
            shutil.copy2(
                ROOT / "scripts" / "python" / "chrono_state" / "__init__.py",
                package / "__init__.py",
            )
            shutil.copy2(
                ROOT / "scripts" / "python" / "chrono_state" / "registry.py",
                package / "registry.py",
            )
            state = fixture_root / "_state"
            state.mkdir()
            (state / "active-tasks.json").write_text(
                json.dumps(
                    {
                        "TASK-future-status": {
                            "status": "future_registry_status"
                        }
                    }
                ),
                encoding="utf-8",
            )
            doctor_logs = fixture_root / "doctor-logs"
            doctor_logs.mkdir()
            environment = {
                **os.environ,
                "VAULT_ROOT": str(fixture_root),
                "CHRONO_DOCTOR_LOG_DIR": str(doctor_logs),
            }

            completed = subprocess.run(
                ["bash", str(ROOT / "bin" / "chrono-status-segment.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CHRONO unknown:1", completed.stdout)


if __name__ == "__main__":
    unittest.main()
