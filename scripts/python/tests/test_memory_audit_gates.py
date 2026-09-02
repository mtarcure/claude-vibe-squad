#!/usr/bin/env python3
"""G-N2: bin/memory-audit.sh must go red when the memory store is broken.

Seven measured shapes all exited 0 before this suite. They are not seven
independent bugs; they collapse into three root causes, and each class below
is named for the root it pins:

  1. NO CENSUS. The audit globbed ``departments/*/memory.md`` and audited
     whatever the glob returned. A department whose memory.md was deleted, or
     replaced by a dangling symlink, simply left the glob -- so partial loss
     read as healthy, and only a *total* wipe (files_scanned=0) was reported.
     The census anchor is ``departments/*/NAMESPACE.md``: it is tracked in git,
     it is the department's own declaration that it exists, and memory.md is
     gitignored -- which is exactly why memory.md can vanish with nothing else
     in the tree changing.

  2. UNVERIFIED LOG. Every write went to "$LOG" unchecked. With the log
     directory unwritable the run emitted a wall of "Permission denied", wrote
     no log at all, and still exited 0. A check that cannot record that it ran
     has no evidence it ran.

  3. SUBSTRING-DEEP CONTENT CHECK. The only condition that could raise an
     issue was ``grep -q 'shared/memory-discipline.md'``. Any file containing
     that byte sequence passed: a one-line file, the line inside an HTML
     comment, the line buried in unrelated prose. None of those is a memory
     store.

The seventh shape -- every entry lacking a source citation -- is NOT asserted
red here, and deliberately so. See test_uncited_entries_stay_a_warning.

Assertions are on exit code, the summary line, and whether a log exists. None
read the audit's source text.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "bin" / "memory-audit.sh"
REPO_ROOT_HELPER = ROOT / "shared" / "repo-root.sh"

DEPARTMENTS = ("coding", "content", "research", "security", "sysmgmt")

# A department memory file that a healthy audit must accept. It cites the
# discipline outside any comment and carries real entries. Some entries lack a
# source citation on purpose: that is the state of the live repo, so a fixture
# without it would not be a healthy control.
HEALTHY_MEMORY = """# {name} memory

Discipline: shared/memory-discipline.md

## Durable facts

- The daemon reload is `launchctl kickstart -k` (source: TASK-2026-08-11-0001)
- A dispatch without a receipt wedges the board
- Placeholder for conventions not yet learned
"""


class MemoryAuditGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="memory-audit-")
        self.vault = Path(self.temporary.name) / "vault"
        (self.vault / "shared").mkdir(parents=True)
        (self.vault / "_state").mkdir()
        (self.vault / "shared" / "repo-root.sh").write_text(
            REPO_ROOT_HELPER.read_text(encoding="utf-8"), encoding="utf-8"
        )
        for name in DEPARTMENTS:
            department = self.vault / "departments" / name
            department.mkdir(parents=True)
            (department / "NAMESPACE.md").write_text(
                f"# {name}\n", encoding="utf-8"
            )
            (department / "memory.md").write_text(
                HEALTHY_MEMORY.format(name=name), encoding="utf-8"
            )

    def tearDown(self) -> None:
        # Restore any directory this suite made unwritable, or cleanup fails.
        for path in self.vault.rglob("*"):
            if path.is_dir():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
        self.temporary.cleanup()

    # --- harness ----------------------------------------------------------

    def run_audit(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(AUDIT)],
            cwd=ROOT,
            env={**os.environ, "VAULT_ROOT": str(self.vault)},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def summary(self, result: subprocess.CompletedProcess[str]) -> str:
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("summary: ")
        ]
        self.assertTrue(lines, result.stdout + result.stderr)
        return lines[-1]

    def logs_written(self) -> list[Path]:
        return sorted((self.vault / "_state" / "audit-logs").glob("*memory-audit.md"))

    def assert_red(self, result: subprocess.CompletedProcess[str]) -> str:
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        summary = self.summary(result)
        self.assertNotIn("status=clean", summary, combined)
        return summary

    def rewrite_all(self, body: str) -> None:
        for name in DEPARTMENTS:
            (self.vault / "departments" / name / "memory.md").write_text(
                body, encoding="utf-8"
            )

    # --- positive control -------------------------------------------------

    def test_healthy_store_passes(self) -> None:
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = self.summary(result)
        self.assertIn("status=clean", summary)
        self.assertIn(f"files_scanned={len(DEPARTMENTS)}", summary)
        self.assertEqual(len(self.logs_written()), 1, summary)

    # --- root cause 1: no census ------------------------------------------

    def test_one_department_memory_deleted_is_red(self) -> None:
        (self.vault / "departments" / "research" / "memory.md").unlink()
        summary = self.assert_red(self.run_audit())
        self.assertIn("research", summary + "\n".join(
            path.read_text(encoding="utf-8") for path in self.logs_written()
        ))

    def test_department_memory_replaced_by_dangling_symlink_is_red(self) -> None:
        target = self.vault / "departments" / "security" / "memory.md"
        target.unlink()
        target.symlink_to(self.vault / "departments" / "security" / "gone.md")
        self.assertTrue(target.is_symlink())
        self.assertFalse(target.exists())
        self.assert_red(self.run_audit())

    def test_total_wipe_still_reports_files_scanned_zero(self) -> None:
        """Doctor keys 'nothing to scan' off files_scanned=0; keep that intact."""
        for name in DEPARTMENTS:
            (self.vault / "departments" / name / "memory.md").unlink()
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("files_scanned=0", self.summary(result))

    # --- root cause 2: unverified log -------------------------------------

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_log_directory_is_red(self) -> None:
        logs = self.vault / "_state" / "audit-logs"
        logs.mkdir(parents=True)
        logs.chmod(0o500)
        result = self.run_audit()
        self.assertEqual(self.logs_written(), [], result.stdout)
        # A run with no durable record cannot claim a verdict.
        summary = self.assert_red(result)
        self.assertIn("unknowns=", summary)
        self.assertNotRegex(summary, r"unknowns=0(\s|$)")

    # --- root cause 3: substring-deep content check ------------------------

    def test_single_discipline_line_with_no_entries_is_red(self) -> None:
        self.rewrite_all("shared/memory-discipline.md\n")
        self.assert_red(self.run_audit())

    def test_discipline_line_inside_an_html_comment_is_red(self) -> None:
        self.rewrite_all("<!-- shared/memory-discipline.md -->\n")
        self.assert_red(self.run_audit())

    def test_unrelated_prose_carrying_the_discipline_line_is_red(self) -> None:
        self.rewrite_all(
            "lorem ipsum dolor sit amet nothing real here\n"
            "shared/memory-discipline.md\n"
            "more filler text\n"
        )
        self.assert_red(self.run_audit())

    # --- the shape that must NOT go red -----------------------------------

    def test_uncited_entries_stay_a_warning(self) -> None:
        """Uncited entries are the live repo's own state, not a breakage.

        Measured on 2026-09-01 at 449afb5e: departments/coding/memory.md has 0
        of 8 top-level entries carrying a source citation and sysmgmt 0 of 14,
        so promoting this warning to an issue would fail the healthy repo --
        a worse defect than the one being fixed. It stays counted and visible
        in `warnings=`, and it stays out of the exit code.
        """
        self.rewrite_all(
            "# Memory\n\nSee shared/memory-discipline.md\n\n"
            "- a thing happened\n- another thing happened\n- a third thing\n"
        )
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = self.summary(result)
        self.assertIn("status=clean", summary)
        self.assertRegex(summary, r"warnings=[1-9]")


class MemoryAuditRealRepoTest(unittest.TestCase):
    """Over-tightening guard: the operator's live store must still pass."""

    def test_live_repo_memory_store_is_clean(self) -> None:
        present = sorted((ROOT / "departments").glob("*/memory.md"))
        if not present:
            self.skipTest("departments/*/memory.md is gitignored and absent here")
        result = subprocess.run(
            ["/bin/bash", str(AUDIT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        summary = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("summary: ")
        ]
        self.assertTrue(summary, result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, summary[-1])
        self.assertIn("status=clean", summary[-1])
        match = re.search(r"files_scanned=(\d+)", summary[-1])
        self.assertIsNotNone(match, summary[-1])
        self.assertEqual(int(match.group(1)), len(present), summary[-1])


if __name__ == "__main__":
    unittest.main()
