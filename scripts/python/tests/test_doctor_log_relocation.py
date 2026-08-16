"""Regression coverage for the durable doctor-log home."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOCTOR = ROOT / "bin" / "doctor.sh"
RESOLVER = ROOT / "bin" / "doctor-log-home.sh"


class DoctorLogRelocationTests(unittest.TestCase):
    def test_missing_vault_root_still_writes_configured_durable_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-log-relocation-") as raw:
            fixture = Path(raw)
            missing_vault_root = fixture / "missing-vault-root"
            durable_log_dir = fixture / "off-repo-state" / "doctor-logs"
            environment = dict(os.environ)
            environment["VAULT_ROOT"] = str(missing_vault_root)
            environment["CHRONO_DOCTOR_LOG_DIR"] = str(durable_log_dir)
            environment.pop("CHRONO_VAULT_ROOT", None)

            completed = subprocess.run(
                ["bash", str(DOCTOR)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            report = durable_log_dir / f"{today}.md"
            summary = durable_log_dir / f"{today}-summary.json"
            diagnostic = completed.stdout + completed.stderr

            self.assertNotEqual(completed.returncode, 0, diagnostic)
            self.assertTrue(report.is_file(), diagnostic)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn(f"# Doctor Report — {today}", report_text)
            self.assertIn("Runtime repository not accessible", report_text)
            self.assertTrue(summary.is_file(), diagnostic)
            summary_text = summary.read_text(encoding="utf-8")
            self.assertIn(f'"date": "{today}"', summary_text)
            self.assertIn('"issue_count": ', summary_text)
            self.assertFalse((missing_vault_root / "_state" / "doctor-logs").exists())

    def test_default_home_is_absolute_off_repo_and_attempt_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-log-default-") as raw:
            fixture = Path(raw)
            home = fixture / "operator-home"
            home.mkdir()
            environment = dict(os.environ)
            environment["HOME"] = str(home)
            environment["VAULT_ROOT"] = str(ROOT)
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            completed = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; printf "%s" "$CHRONO_DOCTOR_LOG_DIR"',
                    "bash",
                    str(RESOLVER),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            expected = home / ".local" / "state" / "chrono-vault" / "doctor-logs"
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(Path(completed.stdout), expected)
            self.assertFalse(Path(completed.stdout).is_relative_to(ROOT))
            self.assertNotIn("_state/board-worktrees", completed.stdout)

    def test_all_known_consumers_use_the_durable_home(self) -> None:
        consumers = (
            "launch-squad.sh",
            "chrono-status-segment.sh",
            "morning-brief.sh",
            "where-are-we.sh",
        )
        for name in consumers:
            with self.subTest(name=name):
                text = (ROOT / "bin" / name).read_text(encoding="utf-8")
                self.assertIn("CHRONO_DOCTOR_LOG_DIR", text)
                self.assertNotIn('${VAULT_ROOT}/_state/doctor-logs', text)
        morning_brief = (ROOT / "bin" / "morning-brief.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("../doctor-logs/", morning_brief)

    def test_relative_override_is_rejected_before_any_log_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-log-relative-") as raw:
            fixture = Path(raw)
            environment = dict(os.environ)
            environment["VAULT_ROOT"] = str(fixture / "missing-vault-root")
            environment["CHRONO_DOCTOR_LOG_DIR"] = "relative-doctor-logs"
            completed = subprocess.run(
                ["bash", str(DOCTOR)],
                cwd=fixture,
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(completed.returncode, 64, completed.stderr)
            self.assertIn("must be absolute", completed.stderr)
            self.assertFalse((fixture / "relative-doctor-logs").exists())

    def test_both_launch_entry_points_export_the_durable_home(self) -> None:
        for name in ("launch-squad.sh", "board-supervisor.sh"):
            with self.subTest(name=name):
                text = (ROOT / "bin" / name).read_text(encoding="utf-8")
                self.assertIn("doctor-log-home.sh", text)
                self.assertIn("export CHRONO_DOCTOR_LOG_DIR", text)


if __name__ == "__main__":
    unittest.main()
