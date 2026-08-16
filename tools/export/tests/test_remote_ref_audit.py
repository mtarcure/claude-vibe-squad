from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPORT_DIR))

from remote_ref_audit import audit_refs  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class RemoteRefAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.origin = self.base / "origin"
        self.origin.mkdir()
        _git(self.origin, "init", "-q", "--bare")
        self.work = self.base / "work"
        self.work.mkdir()
        _git(self.work, "init", "-q")
        _git(self.work, "checkout", "-q", "-b", "main")
        _git(self.work, "config", "user.email", "t@t")
        _git(self.work, "config", "user.name", "t")
        _git(self.work, "remote", "add", "origin", str(self.origin))
        (self.work / "a.txt").write_text("clean\n")
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-qm", "clean")
        _git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")

    def test_all_clean_when_only_main_advertised(self) -> None:
        records = audit_refs(self.work, "origin", "refs/remotes/origin/main")
        self.assertTrue(records)
        self.assertTrue(all(r["status"].startswith("clean") for r in records))

    def test_disjoint_advertised_ref_is_flagged(self) -> None:
        # A disjoint (orphan) lineage pushed to a pull-like ref — the leak shape.
        _git(self.work, "checkout", "-q", "--orphan", "leak")
        (self.work / "secret.txt").write_text("old private\n")
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-qm", "leak")
        _git(self.work, "push", "-q", "origin", "HEAD:refs/pull/1/head")
        records = audit_refs(self.work, "origin", "refs/remotes/origin/main")
        statuses = {r["ref"]: r["status"] for r in records}
        self.assertEqual(statuses["refs/pull/1/head"], "LEAK")
        self.assertIn(statuses["refs/heads/main"], ("clean-equal", "clean-ancestor"))

    def test_allowlist_suppresses_a_known_ref(self) -> None:
        _git(self.work, "checkout", "-q", "--orphan", "keep")
        (self.work / "b.txt").write_text("intentional\n")
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-qm", "keep")
        _git(self.work, "push", "-q", "origin", "HEAD:refs/heads/gh-pages")
        records = audit_refs(
            self.work, "origin", "refs/remotes/origin/main", allow=("refs/heads/gh-pages",)
        )
        statuses = {r["ref"]: r["status"] for r in records}
        self.assertEqual(statuses["refs/heads/gh-pages"], "allowlisted")

    def test_cli_reports_fetch_failure_without_a_traceback(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(EXPORT_DIR / "remote_ref_audit.py"),
                "--repo",
                str(self.work),
                "--remote",
                "missing",
                "--clean-ref",
                "refs/remotes/missing/main",
            ],
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("remote-ref audit could not complete", result.stderr)
        self.assertIn("git fetch --quiet missing exited 128", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
