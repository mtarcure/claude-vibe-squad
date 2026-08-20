#!/usr/bin/env python3
"""bin/rotate-logs.sh, and the one detail it must not get wrong.

Every file this script rotates is held open for writing by a process that
outlives it -- `tmux pipe-pane -o "cat >> ..."` for the pane captures, launchd's
StandardOutPath for the daemon. A `mv` would leave the writer appending to the
same inode under a new name: no space freed, the "fresh" log empty forever. So
the archive must be a copy and the live file must be truncated IN PLACE.

The open-descriptor test below is the regression that protects that. It holds a
real O_APPEND descriptor across the rotation and checks the writer keeps
working, into the same inode, at offset 0.

Nothing here touches a real log: every path is inside a temporary directory the
test created, and the script is pointed at it by environment variable.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
ROTATE = ROOT / "bin" / "rotate-logs.sh"

CAP = 4096


class RotationHarness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.daemon_dir = self.base / "daemon"
        self.tmux_dir = self.base / "tmux-logs"
        self.daemon_dir.mkdir()
        self.tmux_dir.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def run_rotate(self, *flags: str, keep: int = 2) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["/bin/bash", str(ROTATE), *flags],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "VIBESQUAD_DAEMON_LOG_DIR": str(self.daemon_dir),
                "VIBESQUAD_TMUX_LOG_DIR": str(self.tmux_dir),
                "VIBESQUAD_DAEMON_LOG_CAP": str(CAP),
                "VIBESQUAD_TMUX_LOG_CAP": str(CAP),
                "VIBESQUAD_DAEMON_LOG_KEEP": str(keep),
                "VIBESQUAD_TMUX_LOG_KEEP": str(keep),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed

    def oversized(self, name: str = "chrono.log", marker: bytes = b"A") -> Path:
        path = self.tmux_dir / name
        path.write_bytes(marker * (CAP * 3))
        return path

    def archives(self, path: Path) -> list[Path]:
        return sorted(path.parent.glob(f"{path.name}.*.gz"))


class UnderCapTests(RotationHarness):
    def test_a_file_under_the_cap_is_not_touched(self) -> None:
        path = self.tmux_dir / "watchers-status.log"
        path.write_bytes(b"x" * (CAP // 2))
        before = (path.stat().st_ino, path.read_bytes())

        self.run_rotate("--apply")

        self.assertEqual((path.stat().st_ino, path.read_bytes()), before)
        self.assertEqual(self.archives(path), [])


class ReportModeTests(RotationHarness):
    def test_report_mode_writes_nothing(self) -> None:
        path = self.oversized()
        before = (path.stat().st_ino, path.stat().st_size)

        report = self.run_rotate().stdout

        self.assertIn("rotate:", report)
        self.assertIn("nothing was written", report)
        self.assertEqual((path.stat().st_ino, path.stat().st_size), before)
        self.assertEqual(self.archives(path), [])


class CopyTruncateTests(RotationHarness):
    def test_rotation_preserves_the_inode_and_frees_the_bytes(self) -> None:
        path = self.oversized()
        inode = path.stat().st_ino

        self.run_rotate("--apply")

        self.assertEqual(path.stat().st_ino, inode, "a rename would break the writer")
        self.assertEqual(path.stat().st_size, 0)
        archives = self.archives(path)
        self.assertEqual(len(archives), 1)
        self.assertEqual(gzip.decompress(archives[0].read_bytes()), b"A" * (CAP * 3))

    def test_an_open_append_writer_survives_rotation(self) -> None:
        """The regression that protects the whole design.

        `pipe-pane` holds this descriptor across the rotation. Because it was
        opened O_APPEND, the kernel recomputes the offset at each write, so the
        post-rotation write lands at 0 -- no sparse hole the size of the old
        file, and no writes silently going to an unlinked inode.
        """
        path = self.tmux_dir / "chrono.log"
        path.write_bytes(b"")
        with open(path, "ab", buffering=0) as writer:
            writer.write(b"before-rotation\n" * 512)
            self.assertGreater(path.stat().st_size, CAP)
            inode = path.stat().st_ino

            self.run_rotate("--apply")

            # Same descriptor, after the truncate.
            writer.write(b"after-rotation\n")

        self.assertEqual(path.stat().st_ino, inode)
        self.assertEqual(path.read_bytes(), b"after-rotation\n")
        archive = self.archives(path)[0]
        self.assertIn(b"before-rotation", gzip.decompress(archive.read_bytes()))


class PruneTests(RotationHarness):
    def test_only_the_newest_generations_are_kept(self) -> None:
        path = self.oversized()
        stale = [
            path.parent / f"{path.name}.{stamp}.gz"
            for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z")
        ]
        for archive in stale:
            archive.write_bytes(gzip.compress(b"old"))

        self.run_rotate("--apply", keep=2)

        remaining = {p.name for p in self.archives(path)}
        # Three stale plus the one just written, keep 2: the two oldest stamps go.
        self.assertNotIn(stale[0].name, remaining)
        self.assertNotIn(stale[1].name, remaining)
        self.assertEqual(len(remaining), 2)

    def test_an_archive_is_never_rotated_into_an_archive(self) -> None:
        path = self.oversized()
        archive = path.parent / f"{path.name}.20260101T000000Z.gz"
        archive.write_bytes(b"Z" * (CAP * 3))  # oversized, but not a *.log
        before = archive.read_bytes()

        self.run_rotate("--apply", keep=5)

        self.assertEqual(archive.read_bytes(), before)
        self.assertFalse(list(path.parent.glob("*.gz.*.gz")))


class SafetyTests(RotationHarness):
    def test_a_symlinked_log_is_refused_not_followed(self) -> None:
        """Resolving the link would gzip and then TRUNCATE its target."""
        target = self.base / "not-a-log.txt"
        target.write_bytes(b"S" * (CAP * 3))
        link = self.tmux_dir / "chrono.log"
        link.symlink_to(target)

        report = self.run_rotate("--apply").stdout

        self.assertIn("symlink, refused", report)
        self.assertEqual(target.read_bytes(), b"S" * (CAP * 3))
        self.assertTrue(link.is_symlink())
        self.assertEqual(list(self.tmux_dir.glob("*.gz")), [])

    def test_daemon_logs_are_rotated_by_name(self) -> None:
        for name in ("vibesquad-daemon-stdout.log", "vibesquad-daemon-stderr.log"):
            (self.daemon_dir / name).write_bytes(b"D" * (CAP * 3))
        # A same-directory file that is not one of ours must be left alone --
        # the daemon logs live in /tmp, alongside everything else on the system.
        bystander = self.daemon_dir / "someone-elses.log"
        bystander.write_bytes(b"E" * (CAP * 3))

        self.run_rotate("--apply")

        for name in ("vibesquad-daemon-stdout.log", "vibesquad-daemon-stderr.log"):
            self.assertEqual((self.daemon_dir / name).stat().st_size, 0)
        self.assertEqual(bystander.stat().st_size, CAP * 3)
        self.assertEqual(list(self.daemon_dir.glob("someone-elses*.gz")), [])


class NightlyWiringTests(unittest.TestCase):
    def test_nightly_runs_rotation_with_apply_and_after_doctor(self) -> None:
        """Order matters. bin/doctor.sh's retry-storm scan reads the last hour
        of each tmux log; rotating first would hand it a freshly emptied file
        with a fresh mtime and it would report a quiet hour as a clean one."""
        nightly = (ROOT / "bin" / "run-nightly.sh").read_text(encoding="utf-8")
        self.assertIn('"${VAULT_ROOT}/bin/rotate-logs.sh" --apply', nightly)
        self.assertLess(
            nightly.index('run_phase "doctor"'),
            nightly.index('run_phase "rotate-logs"'),
            "rotation must not run before the scan that reads those logs",
        )


if __name__ == "__main__":
    unittest.main()
