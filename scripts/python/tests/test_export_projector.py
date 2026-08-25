#!/usr/bin/env python3
"""Pin the public-export projector's default ledger and gate-report paths.

The projector once defaulted both to `_state/repo-split-2026-07-16/`, a
directory that was retired and no longer exists. Every run worked only because
the operator passed `--ledger` explicitly; the first run that forgot it would
have written a second publish history under the retired path, which is the
duplication Hard Rule 10 forbids.

These tests deliberately do NOT compare the constant against a second copy of
the same string. A test that hardcodes the expected path passes whatever the
constant happens to say, and would have passed against the stale default too.
Instead the expectation is derived from `git ls-files` -- the ledger is the one
git-tracked file in that directory, so the repository itself is the oracle for
where the publish line lives. Rename or move the ledger and this fails; change
the constant and this fails.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = ROOT / "tools" / "export"


def _import_projector():
    """Import the projector without leaving tools/export on the shared path.

    `unittest discover` runs the whole suite in one process, so a permanent
    sys.path.insert(0, ...) here would put ten export module names ahead of
    every later import in every other test file. Nothing collides today; the
    scoping is so that adding a module to tools/export later cannot quietly
    shadow one somewhere else.
    """
    sys.path.insert(0, str(EXPORT_DIR))
    try:
        import projector as module

        return module
    finally:
        sys.path.remove(str(EXPORT_DIR))


projector = _import_projector()

#: The directory the projector must never default back to. Named here rather
#: than only in prose so the regression has a name in the failure output.
RETIRED_STATE_DIR = "repo-split-2026-07-16"


def _tracked_ledgers() -> list[str]:
    """Every git-tracked export ledger, as repo-relative POSIX paths."""
    completed = subprocess.run(
        ["git", "ls-files", "--", "*export-ledger.jsonl"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line.strip())


class TestDefaultLedgerPath(unittest.TestCase):
    def test_exactly_one_ledger_is_tracked(self):
        """Two tracked ledgers would mean the fork already happened.

        This is the precondition for every other assertion here: the oracle is
        only an oracle while there is one answer.
        """
        ledgers = _tracked_ledgers()
        self.assertEqual(
            len(ledgers),
            1,
            f"expected exactly one tracked export ledger, found {ledgers!r}. "
            "More than one means publish history has already forked.",
        )

    def test_default_ledger_matches_the_tracked_ledger(self):
        """The default must point at the ledger the repository actually keeps."""
        tracked = _tracked_ledgers()[0]
        self.assertEqual(
            str(projector.DEFAULT_LEDGER_PATH),
            tracked,
            "projector.DEFAULT_LEDGER_PATH does not name the git-tracked export "
            "ledger. This constant is now load-bearing twice over: it is the "
            "default, and it is also how _require_canonical_ledger recognises "
            "that a run is pointed away from the history the repository keeps "
            "-- which it decides before reading the ledger, so an alternate "
            "that happens to agree with the rail cannot certify itself.",
        )

    def test_default_ledger_exists_on_disk(self):
        """Tracked means it is checked out, including in a board worktree."""
        self.assertTrue(
            (ROOT / projector.DEFAULT_LEDGER_PATH).is_file(),
            f"{projector.DEFAULT_LEDGER_PATH} is not a readable file under {ROOT}",
        )


class TestDefaultGateReportPath(unittest.TestCase):
    def test_gate_report_shares_the_ledger_directory(self):
        """The gate report is the evidence for the ledger entry beside it.

        `project()` hands this path to bin/product-hygiene.sh, reads it back,
        and refuses to continue unless it is passing -- then appends the ledger
        record it justifies. Splitting the two directories would file the proof
        somewhere other than the claim.
        """
        self.assertEqual(
            projector.DEFAULT_GATE_REPORT_PATH.parent,
            projector.DEFAULT_LEDGER_PATH.parent,
            "the gate report and the ledger it justifies must land in one "
            "directory",
        )

    def test_gate_report_keeps_its_basename(self):
        self.assertEqual(projector.DEFAULT_GATE_REPORT_PATH.name, "candidate-gate.md")


class TestRetiredDirectoryStaysGone(unittest.TestCase):
    def test_no_default_points_at_the_retired_directory(self):
        for constant in (
            projector.EXPORT_STATE_DIR,
            projector.DEFAULT_LEDGER_PATH,
            projector.DEFAULT_GATE_REPORT_PATH,
        ):
            with self.subTest(constant=str(constant)):
                self.assertNotIn(RETIRED_STATE_DIR, str(constant))

    def test_nothing_under_tools_export_mentions_the_retired_directory(self):
        """Catches a reintroduction anywhere in the export tool, not just the defaults.

        Widened from projector.py alone on 2026-08-24: the retired name had
        survived in `tools/export/tests/test_projector.py` as fixture paths.
        Those were only tmpdir fixtures and broke nothing, which is exactly why
        they lasted -- a path in a test reads as an authoritative one to whoever
        greps for it next, and it was the last place in code the name lived.

        Reported as file:line rather than via assertNotIn on whole files: a
        failure should name where the string came back, not print the tree.
        """
        offenders = []
        for path in sorted(EXPORT_DIR.rglob("*")):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            offenders.extend(
                f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
                for number, line in enumerate(text.splitlines(), start=1)
                if RETIRED_STATE_DIR in line
            )
        self.assertEqual(
            offenders,
            [],
            f"tools/export names the retired {RETIRED_STATE_DIR} directory "
            "again; nothing lives there.",
        )


if __name__ == "__main__":
    unittest.main()
