#!/usr/bin/env python3
"""Regression tests for the v4 report-only cleanup safety boundary."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import run_weekly  # noqa: E402
import transcription_cache_ttl  # noqa: E402


SYSTEM_CLEANUP = ROOT / "bin" / "system-cleanup.sh"
TTL_WRAPPER = ROOT / "bin" / "transcription-cache-ttl.sh"


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

    def test_transcription_ttl_only_reports_and_retains_old_cache_bytes(self):
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "transcription-cache"
            cache.mkdir()
            old_file = cache / "target"
            old_file.write_bytes(b"undeclared audio bytes")
            _mark_old(cache, now)
            before = _census(cache)

            flags = {"APPLY": "1", "CLEANUP_APPLY": "1", "SQUAD_CLEAN_CONFIRM": "1"}
            with (
                mock.patch.dict(os.environ, flags, clear=False),
                mock.patch.object(
                    Path,
                    "unlink",
                    side_effect=AssertionError("report-only code invoked Path.unlink"),
                ),
            ):
                report = transcription_cache_ttl.audit_cache(
                    cache_dir=cache,
                    ttl_days=15,
                    now=now.timestamp(),
                )
                output = io.StringIO()
                with (
                    mock.patch.object(transcription_cache_ttl, "CACHE_DIR", cache),
                    mock.patch.object(
                        transcription_cache_ttl.time,
                        "time",
                        return_value=now.timestamp(),
                    ),
                    redirect_stdout(output),
                ):
                    self.assertEqual(transcription_cache_ttl.main(), 0)

            self.assertEqual(_census(cache), before)
            self.assertTrue(old_file.is_file())
            self.assertEqual(old_file.read_bytes(), b"undeclared audio bytes")
            self.assertEqual(report["mode"], "report-only")
            self.assertIs(report["scan_complete"], True)
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["removed_count"], 0)
            self.assertEqual(report["bytes_freed"], 0)
            candidate = report["candidates"][0]
            self.assertEqual(Path(candidate["path"]), old_file)
            self.assertEqual(candidate["storage_class"], "unknown")
            self.assertEqual(candidate["effective_storage_class"], "DURABLE")
            self.assertIs(candidate["cleanup_eligible"], False)
            self.assertIn("non-authoritative", report["age_basis"])
            self.assertIn("report-only", output.getvalue())
            self.assertIn("effective_storage_class=DURABLE", output.getvalue())

    def test_transcription_ttl_real_wrapper_runs_with_launchd_python(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            cache = vault / "_state" / "transcription-cache"
            cache.mkdir(parents=True)
            target = cache / "target"
            target.write_bytes(b"launchd compatibility sentinel")
            _mark_old(cache, now)
            before = _census(cache)
            env = {
                "PATH": "/usr/bin:/bin",
                "VAULT_ROOT": str(vault),
                "TTL_DAYS": "15",
                "HOME": str(Path(tmp) / "home"),
                "APPLY": "1",
                "CLEANUP_APPLY": "1",
            }
            Path(env["HOME"]).mkdir()
            before_tree = _census(Path(tmp))

            completed = subprocess.run(
                [str(TTL_WRAPPER)],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("report-only", completed.stdout)
            self.assertIn("effective_storage_class=DURABLE", completed.stdout)
            self.assertEqual(_census(cache), before)
            self.assertEqual(_census(Path(tmp)), before_tree)

    def test_python_cleanup_reports_bound_samples_without_losing_counts(self):
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            cache = root / "cache"
            for index in range(25):
                run = runs / f"run-{index:02d}"
                run.mkdir(parents=True)
                cached = cache / f"item-{index:02d}"
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(b"x")
            _mark_old(runs, now)
            _mark_old(cache, now)
            before = _census(root)

            archival = run_weekly.mode_archival(runs_dir=runs, now=now, sample_limit=25)
            ttl = transcription_cache_ttl.audit_cache(
                cache_dir=cache,
                now=now.timestamp(),
                sample_limit=25,
            )

            self.assertEqual(_census(root), before)
            for report in (archival, ttl):
                self.assertEqual(report["candidate_count"], 25)
                self.assertEqual(report["sample_limit"], 20)
                self.assertEqual(len(report["candidates"]), 20)
                self.assertEqual(report["omitted_candidate_count"], 5)

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

            def broken_walk(*args, **kwargs):
                kwargs["onerror"](PermissionError("denied"))
                return iter(())

            with mock.patch.object(
                transcription_cache_ttl.os, "walk", side_effect=broken_walk
            ):
                ttl = transcription_cache_ttl.audit_cache(cache_dir=base)
            self.assertIs(ttl["scan_complete"], False)


if __name__ == "__main__":
    unittest.main()
