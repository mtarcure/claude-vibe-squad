#!/usr/bin/env python3
"""Retention reaper tests against isolated, real filesystem fixtures.

The rescue fixture is a real Git repository because the safety boundary is an
exact match to an indexed regular-file blob.  A same-name file is deliberately
different to prove names and extensions never classify rescued work.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "python" / "reap_unbounded_state.py"
SCRATCH_ROOT = Path(tempfile.gettempdir())
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
OLD = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc).timestamp()
RECENT = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc).timestamp()


class ReapUnboundedStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(
            tempfile.mkdtemp(prefix="reap-unbounded-", dir=SCRATCH_ROOT)
        ).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "retention@test.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Retention Test"],
            cwd=self.root,
            check=True,
        )
        (self.root / "canonical.txt").write_bytes(b"tracked duplicate\n")
        subprocess.run(["git", "add", "canonical.txt"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "fixture"], cwd=self.root, check=True
        )

        self.state = self.root / "_state"
        self.receipt_dir = self.root / "receipts"
        self.snapshots = self.root / "vault-snapshots"
        for relative in (
            "board-codex-homes",
            "board-worktrees",
            "chrono-notify-receipts",
            "long-running-noted",
            "rescued-worker-artifacts",
        ):
            (self.state / relative).mkdir(parents=True)
        self.snapshots.mkdir()

    @staticmethod
    def _set_mtime(path: Path, timestamp: float) -> None:
        os.utime(path, (timestamp, timestamp), follow_symlinks=False)

    def _old_file(self, path: Path, data: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._set_mtime(path, OLD)
        return path

    def _run(self, *mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(REPO_ROOT / ".venv" / "bin" / "python3.13"),
                str(SCRIPT),
                *mode,
                "--root",
                str(self.root),
                "--vault-snapshot-dir",
                str(self.snapshots),
                "--receipt-dir",
                str(self.receipt_dir),
                "--now",
                NOW.isoformat().replace("+00:00", "Z"),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _build_candidates(self) -> dict[str, Path]:
        homes = self.state / "board-codex-homes"
        orphan = homes / "d-orphan"
        self._old_file(orphan / "cache.bin", b"orphan cache")
        self._set_mtime(orphan, OLD)

        active = homes / "d-active"
        self._old_file(active / "cache.bin", b"active cache")
        self._set_mtime(active, OLD)
        (self.state / "board-worktrees" / active.name).mkdir()

        fresh = homes / "d-fresh"
        self._old_file(fresh / "cache.bin", b"fresh cache")
        self._set_mtime(fresh / "cache.bin", RECENT)
        self._set_mtime(fresh, RECENT)

        notifications = self.state / "chrono-notify-receipts"
        old_notifications = []
        for index in range(2):
            old_notifications.append(
                self._old_file(notifications / f"old-{index}.sent", b"old")
            )
        for index in range(1000):
            path = notifications / f"recent-{index:04d}.sent"
            path.write_bytes(b"recent")
            self._set_mtime(path, RECENT + index)

        markers = self.state / "long-running-noted"
        marker = self._old_file(markers / "old.noted", b"")
        recent_marker = markers / "recent.noted"
        recent_marker.write_bytes(b"")
        self._set_mtime(recent_marker, RECENT)
        self._old_file(markers / ".gitkeep", b"")

        oldest_snapshot = self._old_file(
            self.snapshots / "chrono-vault-20260701-120000Z.tar.gz", b"old-snapshot"
        )
        for day in range(25, 32):
            path = self.snapshots / f"chrono-vault-202608{day}-120000Z.tar.gz"
            path.write_bytes(f"snapshot-{day}".encode())
            self._set_mtime(path, RECENT + day)

        rescue = self.state / "rescued-worker-artifacts" / "TASK-old"
        duplicate = self._old_file(rescue / "copy" / "anything.bin", b"tracked duplicate\n")
        unique = self._old_file(rescue / "copy" / "canonical.txt", b"unique poc\n")
        recent_duplicate = rescue / "fresh" / "duplicate.txt"
        recent_duplicate.parent.mkdir(parents=True)
        recent_duplicate.write_bytes(b"tracked duplicate\n")
        self._set_mtime(recent_duplicate, RECENT)

        return {
            "orphan": orphan,
            "active": active,
            "fresh": fresh,
            "notification_0": old_notifications[0],
            "notification_1": old_notifications[1],
            "marker": marker,
            "snapshot": oldest_snapshot,
            "rescue_duplicate": duplicate,
            "rescue_unique": unique,
            "rescue_recent_duplicate": recent_duplicate,
        }

    def test_default_is_dry_run_and_receipts_every_planned_removal(self) -> None:
        paths = self._build_candidates()

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode=preserve", result.stdout)
        for name in (
            "orphan",
            "notification_0",
            "notification_1",
            "marker",
            "snapshot",
            "rescue_duplicate",
        ):
            self.assertTrue(paths[name].exists(), f"dry run removed {name}")
        receipt = json.loads(
            (self.receipt_dir / "latest-preserve.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["schema"], "unbounded-state-reaper-receipt/v1")
        self.assertEqual(receipt["mode"], "preserve")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["totals"]["planned_items"], 5)
        self.assertGreater(receipt["totals"]["planned_logical_bytes"], 0)
        self.assertEqual(receipt["totals"]["removed_items"], 0)
        self.assertEqual(receipt["removed"], [])
        self.assertEqual(len(receipt["planned"]), 5)
        self.assertNotIn(
            "board_codex_homes",
            receipt["categories"],
            "the general retention reaper duplicated the established owner: "
            "bin/prune-board-worktrees.sh",
        )

    def test_apply_removes_only_candidates_and_records_exact_receipt(self) -> None:
        paths = self._build_candidates()

        result = self._run("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        for name in (
            "notification_0",
            "notification_1",
            "marker",
            "snapshot",
            "rescue_duplicate",
        ):
            self.assertFalse(paths[name].exists(), f"apply retained candidate {name}")
        for name in (
            "orphan",
            "active",
            "fresh",
            "rescue_unique",
            "rescue_recent_duplicate",
        ):
            self.assertTrue(paths[name].exists(), f"apply removed retained {name}")

        receipt_path = self.receipt_dir / "latest-apply.json"
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["mode"], "apply")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["totals"]["planned_items"], 5)
        self.assertEqual(receipt["totals"]["removed_items"], 5)
        self.assertEqual(
            receipt["totals"]["removed_logical_bytes"],
            receipt["totals"]["planned_logical_bytes"],
        )
        self.assertEqual(
            {item["path"] for item in receipt["removed"]},
            {item["path"] for item in receipt["planned"]},
        )

    def test_rescue_classification_uses_content_not_name_or_extension(self) -> None:
        paths = self._build_candidates()

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(
            (self.receipt_dir / "latest-preserve.json").read_text(encoding="utf-8")
        )
        rescue_planned = [
            item for item in receipt["planned"] if item["category"] == "rescued_worker_artifacts"
        ]
        self.assertEqual(len(rescue_planned), 1)
        self.assertEqual(
            rescue_planned[0]["path"],
            str(paths["rescue_duplicate"].relative_to(self.root)),
        )
        self.assertEqual(rescue_planned[0]["evidence"]["kind"], "exact_git_index_blob")
        self.assertIn("canonical.txt", rescue_planned[0]["evidence"]["tracked_paths"])
        self.assertTrue(paths["rescue_unique"].exists())

    def test_healthy_empty_state_reaps_nothing_and_still_emits_receipt(self) -> None:
        result = self._run("--preserve")

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt_path = self.receipt_dir / "latest-preserve.json"
        self.assertTrue(receipt_path.is_file(), "no-op run emitted no receipt")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["totals"]["planned_items"], 0)
        self.assertEqual(receipt["totals"]["planned_logical_bytes"], 0)
        self.assertEqual(receipt["totals"]["removed_items"], 0)
        self.assertEqual(receipt["planned"], [])
        self.assertIn("planned=0", result.stdout)

    def test_apply_and_preserve_are_mutually_exclusive(self) -> None:
        result = self._run("--preserve", "--apply")

        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)


if __name__ == "__main__":
    unittest.main()
