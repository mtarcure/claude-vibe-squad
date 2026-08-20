#!/usr/bin/env python3
"""Regression tests for the v4 report-only cleanup safety boundary."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import run_weekly  # noqa: E402


SYSTEM_CLEANUP = ROOT / "bin" / "system-cleanup.sh"


def _census(root: Path) -> dict[str, tuple[int, int, int, str | None]]:
    """Capture the path, inode, type/size, and bytes beneath ``root``."""
    entries = [root, *root.rglob("*")]
    result: dict[str, tuple[int, int, int, str | None]] = {}
    for path in sorted(entries, key=lambda item: str(item.relative_to(root))):
        metadata = path.lstat()
        digest = None
        if stat.S_ISREG(metadata.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(root)) or "."] = (
            metadata.st_ino,
            stat.S_IFMT(metadata.st_mode),
            metadata.st_size,
            digest,
        )
    return result


def _mark_old(path: Path, now: datetime, *, days: int = 100) -> None:
    old = now.timestamp() - days * 86_400
    for child in sorted(path.rglob("*"), reverse=True):
        os.utime(child, (old, old), follow_symlinks=False)
    os.utime(path, (old, old), follow_symlinks=False)


def _run_system_cleanup(
    *,
    vault: Path,
    tmp_root: Path,
    home: Path,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "VAULT_ROOT": str(vault),
        "HOME": str(home),
        "VIBESQUAD_CLEANUP_TMP_ROOT": str(tmp_root),
        "PATH": "/usr/bin:/bin",
        "APPLY": "1",
        "CLEANUP_APPLY": "1",
        "SQUAD_CLEAN_CONFIRM": "1",
    }
    return subprocess.run(
        ["bash", str(SYSTEM_CLEANUP), "--apply", "--force"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _system_report_path(vault: Path) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return vault / "_state" / "cleanup-logs" / f"{date}-system.md"


class CleanupReportOnlyTest(unittest.TestCase):
    def test_weekly_auth_audit_labels_gemini_api_key_truthfully(self):
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with (
            mock.patch.object(run_weekly.shutil, "which", return_value="/fake/cli"),
            mock.patch.object(run_weekly.subprocess, "run", return_value=completed),
        ):
            result = run_weekly.subscription_audit()
        self.assertEqual(result["gemini"], "✓ gemini-api-key auth OK")
        for lane in ("claude", "codex", "kimi"):
            self.assertEqual(result[lane], "✓ subscription auth OK")

    def test_system_cleanup_cannot_apply_to_old_or_ambiguous_paths(self):
        source = SYSTEM_CLEANUP.read_text()
        # Keep this assertion first: the previously live script must never be
        # executed by this test before the report-only boundary exists.
        self.assertIn("cleanup_mode: report-only", source)
        self.assertNotRegex(source, r"(?m)^\s*brew\s+cleanup(?:\s|$)")
        self.assertNotRegex(source, r"(?m)^\s*npm\s+cache\s+verify(?:\s|$)")
        self.assertNotRegex(source, r"(?m)^\s*pip\s+cache\s+purge(?:\s|$)")
        self.assertNotRegex(source, r"(?m)^\s*find\s+[^\n]*\s-delete(?:\s|$)")

        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "vault"
            target = vault / "runs" / "target"
            target.mkdir(parents=True)
            (target / "undeclared.txt").write_bytes(b"retain me exactly\n")
            tmp_root = base / "tmp"
            tmp_root.mkdir()
            (tmp_root / "old-undeclared.cache").write_bytes(b"cache bytes\n")
            home = base / "home"
            home.mkdir()
            _mark_old(target, now)
            _mark_old(tmp_root, now)

            before_runs = _census(vault / "runs")
            before_tmp = _census(tmp_root)
            # Reading bytes for the census can update atime. Restore the old
            # observation timestamp; timestamps are deliberately not census data.
            _mark_old(tmp_root, now)

            completed = _run_system_cleanup(
                vault=vault,
                tmp_root=tmp_root,
                home=home,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(_census(vault / "runs"), before_runs)
            self.assertEqual(_census(tmp_root), before_tmp)
            self.assertTrue(target.is_dir())
            self.assertTrue((target / "undeclared.txt").is_file())

            self.assertFalse((vault / "_state" / "cleanup-logs").exists())
            report = completed.stdout
            self.assertIn("cleanup_mode: report-only", report)
            self.assertIn("runs/target", report)
            self.assertIn("storage_class: unknown", report)
            self.assertIn("effective_storage_class: DURABLE", report)
            self.assertIn("cleanup_eligible: false", report)
            self.assertIn("non-authoritative", report)
            self.assertIn("temporary scan complete: true", report)

    def test_system_cleanup_never_touches_preexisting_report_file_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "vault"
            log = _system_report_path(vault)
            log.parent.mkdir(parents=True)
            outside = base / "outside.md"
            outside.write_bytes(b"outside sentinel\n")
            log.symlink_to(outside)
            tmp_root = base / "tmp"
            tmp_root.mkdir()
            home = base / "home"
            home.mkdir()
            before = _census(base)

            completed = _run_system_cleanup(
                vault=vault,
                tmp_root=tmp_root,
                home=home,
            )

            self.assertEqual(_census(base), before)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(log.is_symlink())
            self.assertEqual(outside.read_bytes(), b"outside sentinel\n")

    def test_system_cleanup_never_touches_report_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "vault"
            state = vault / "_state"
            state.mkdir(parents=True)
            outside = base / "outside-logs"
            outside.mkdir()
            outside_report = outside / _system_report_path(vault).name
            outside_report.write_bytes(b"directory target sentinel\n")
            (state / "cleanup-logs").symlink_to(outside, target_is_directory=True)
            tmp_root = base / "tmp"
            tmp_root.mkdir()
            home = base / "home"
            home.mkdir()
            before = _census(base)

            completed = _run_system_cleanup(
                vault=vault,
                tmp_root=tmp_root,
                home=home,
            )

            self.assertEqual(_census(base), before)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((state / "cleanup-logs").is_symlink())
            self.assertEqual(
                outside_report.read_bytes(), b"directory target sentinel\n"
            )

    def test_weekly_archival_only_reports_and_retains_missing_declarations(self):
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            target = runs / "target"
            target.mkdir(parents=True)
            (target / "undeclared.md").write_text("durable until proven otherwise\n")
            _mark_old(target, now)
            before = _census(runs)

            flags = {"APPLY": "1", "CLEANUP_APPLY": "1", "SQUAD_CLEAN_CONFIRM": "1"}
            with (
                mock.patch.dict(os.environ, flags, clear=False),
                mock.patch.object(
                    run_weekly.shutil,
                    "move",
                    side_effect=AssertionError("report-only code invoked shutil.move"),
                ),
            ):
                report = run_weekly.mode_archival(
                    days=60,
                    runs_dir=runs,
                    now=now,
                )

            self.assertEqual(_census(runs), before)
            self.assertFalse((runs / "_archive").exists())
            self.assertEqual(report["mode"], "report-only")
            self.assertIs(report["scan_complete"], True)
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["archived_count"], 0)
            candidate = report["candidates"][0]
            self.assertEqual(Path(candidate["path"]), target)
            self.assertEqual(candidate["storage_class"], "unknown")
            self.assertEqual(candidate["effective_storage_class"], "DURABLE")
            self.assertIs(candidate["cleanup_eligible"], False)
            self.assertIn("non-authoritative", report["age_basis"])

    def test_python_cleanup_reports_bound_samples_without_losing_counts(self):
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            for index in range(25):
                run = runs / f"run-{index:02d}"
                run.mkdir(parents=True)
            _mark_old(runs, now)
            before = _census(root)

            archival = run_weekly.mode_archival(runs_dir=runs, now=now, sample_limit=25)

            self.assertEqual(_census(root), before)
            self.assertEqual(archival["candidate_count"], 25)
            self.assertEqual(archival["sample_limit"], 20)
            self.assertEqual(len(archival["candidates"]), 20)
            self.assertEqual(archival["omitted_candidate_count"], 5)

    def test_incomplete_scans_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "vault"
            vault.mkdir()
            tmp_root = base / "tmp"
            tmp_root.mkdir()
            home = base / "home"
            fake_bin = home / ".local" / "bin"
            fake_bin.mkdir(parents=True)
            fake_find = fake_bin / "find"
            fake_find.write_text("#!/bin/sh\nexit 1\n")
            fake_find.chmod(0o755)
            before = _census(base)

            completed = _run_system_cleanup(vault=vault, tmp_root=tmp_root, home=home)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("temporary scan complete: false", completed.stdout)
            self.assertIn("census incomplete", completed.stderr)
            self.assertEqual(_census(base), before)

            with mock.patch.object(Path, "iterdir", side_effect=PermissionError):
                weekly = run_weekly.mode_archival(runs_dir=base, sample_limit=25)
            self.assertIs(weekly["scan_complete"], False)


if __name__ == "__main__":
    unittest.main()
