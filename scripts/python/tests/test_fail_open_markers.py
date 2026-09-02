#!/usr/bin/env python3
"""A broken input must never render identically to a clean, empty one.

Four handlers converted a read failure into a confident "all clear": an
unreadable charter rail and an unreadable `_state/chrono-queue.md` both became
"nothing owed" in the resume capsule, a broken task packet became zero dispatch
advisories, and an unreadable board receipt became "not quarantined". Root
`CLAUDE.md` § Session Resume promises the capsule carries "a loud marker for any
status the partition does not know, so nothing owed is ever silently absent" --
a promise the first two broke outright.

Every test here asserts runtime behaviour on a deliberately broken input, and
each is paired with a test that a genuinely empty input still renders as empty,
so the fix cannot be "raise on everything".
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_preflight as preflight  # noqa: E402
from chrono_state import resume  # noqa: E402
from chrono_state import thread_charters  # noqa: E402

EMPTY_VIEW = {"live": [], "deferred": [], "unclassified": {}}


def stubbed_capsule(queue: Path, root: Path, max_tokens: int = 3000, **patches) -> str:
    """Render a capsule with every rail stubbed to "nothing owed".

    `queue` and `root` bind the two paths the capsule reads. `patches` names any
    further `resume` attribute to stub, as `attribute=<patch.object kwargs>` --
    e.g. `load_archived_debt={"side_effect": OSError("boom")}` -- so each test
    breaks exactly one rail and inherits a clean, silent everything else. Whether
    that one break is loud is what every caller is asserting.
    """
    stubs: dict[str, dict] = {
        "QUEUE_PATH": {"new": queue},
        "ARCHIVED_DEBT_ROOT": {"new": root},
        "registry_view": {"return_value": EMPTY_VIEW},
        "active_decisions": {"return_value": []},
        "active_thread_charters": {"return_value": []},
        "open_work_items": {"return_value": []},
        **patches,
    }
    with ExitStack() as stack:
        for name, kwargs in stubs.items():
            stack.enter_context(mock.patch.object(resume, name, **kwargs))
        return resume.render_capsule(
            "sess-1", latest_operator_turn="go", max_tokens=max_tokens
        )


def unreadable_dir(case: unittest.TestCase) -> Path:
    """A directory that exists and holds work, but cannot be listed."""
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    rail = Path(temporary.name) / "active"
    rail.mkdir()
    (rail / "thread.md").write_text("# ASK\nowed work nobody can see\n")
    os.chmod(rail, 0o000)
    case.addCleanup(os.chmod, rail, 0o755)
    return rail


class CharterRailFailureTests(unittest.TestCase):
    """`load_active_charters` said "absence means none" and meant it too broadly."""

    def test_unreadable_rail_raises_instead_of_reporting_no_charters(self):
        # Mutation caught: restoring `try: ... except OSError: return []`, or
        # going back to `path.glob("*.md")` -- pathlib's glob swallows the
        # scandir PermissionError internally, so the rail reads as empty.
        with self.assertRaises(OSError):
            thread_charters.load_active_charters(unreadable_dir(self))

    def test_absent_rail_is_still_genuinely_empty(self):
        # Mutation caught: "fixing" the above by raising whenever the rail is
        # not a readable directory. A rail that was never created owes nothing.
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "never-created"
            self.assertEqual(thread_charters.load_active_charters(missing), [])

    def test_empty_rail_is_still_genuinely_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            rail = Path(directory) / "active"
            rail.mkdir()
            self.assertEqual(thread_charters.load_active_charters(rail), [])

    def test_resume_projects_an_unreadable_rail_as_a_loud_marker(self):
        # The loud handler in `active_thread_charters` already existed; the
        # swallow below it made it dead code for the likeliest failure. This
        # pins that the marker is actually reachable.
        # Mutation caught: any change that lets the rail failure return [].
        charters = resume.active_thread_charters(path=unreadable_dir(self))
        self.assertEqual(len(charters), 1)
        self.assertTrue(charters[0].issues, "the marker charter must carry an issue")
        self.assertIn("unreadable", " ".join(charters[0].issues).lower())

    def test_the_capsule_names_the_unreadable_rail(self):
        # A marker that renders as "- THE ASK: (unreadable)" reads like one bad
        # charter file, not like a rail nobody could list. The capsule has to
        # say which.
        # Mutation caught: dropping charter issues from the projection.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        capsule_path = root / "_state" / "chrono" / "resume.md"
        rail = capsule_path.parent / thread_charters.CHARTERS_REL.relative_to(
            "_state/chrono"
        )
        rail.mkdir(parents=True)
        (rail / "thread.md").write_text("# ASK\nowed work nobody can see\n")
        os.chmod(rail, 0o000)
        self.addCleanup(os.chmod, rail, 0o755)
        queue = root / "chrono-queue.md"
        queue.write_text("# header only\n")
        with (
            mock.patch.object(resume, "CAPSULE_PATH", capsule_path),
            mock.patch.object(resume, "QUEUE_PATH", queue),
            mock.patch.object(resume, "ARCHIVED_DEBT_ROOT", root),
            mock.patch.object(resume, "registry_view", return_value=EMPTY_VIEW),
            mock.patch.object(resume, "active_decisions", return_value=[]),
            mock.patch.object(resume, "open_work_items", return_value=[]),
        ):
            capsule = resume.render_capsule(
                "sess-1", latest_operator_turn="go", max_tokens=3000
            )
        self.assertIn(resume.THREAD_HEADING, capsule)
        self.assertIn("charter rail unreadable", capsule)

    def test_resume_projects_a_readable_empty_rail_as_no_charters(self):
        with tempfile.TemporaryDirectory() as directory:
            rail = Path(directory) / "active"
            rail.mkdir()
            self.assertEqual(resume.active_thread_charters(path=rail), [])


class PendingCompletionFailureTests(unittest.TestCase):
    """A corrupt queue must not render as an empty queue."""

    def corrupt_queue(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        queue = Path(directory.name) / "chrono-queue.md"
        # 0xFF is never a valid UTF-8 lead byte; `read_text` raises
        # UnicodeDecodeError, a ValueError subclass.
        queue.write_bytes(b"2026-08-16T00:00:00Z | needs_review | coding/T-1 | \xff\xfe\n")
        return queue

    def test_undecodable_queue_is_unknown_not_empty(self):
        # Mutation caught: restoring `except (OSError, ValueError): return []`.
        self.assertIsNone(resume.pending_completions(path=self.corrupt_queue()))

    def test_unreadable_queue_is_unknown_not_empty(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        queue = Path(directory.name) / "chrono-queue.md"
        queue.write_text("2026-08-16T00:00:00Z | needs_review | coding/T-1 | x\n")
        os.chmod(queue, 0o000)
        self.addCleanup(os.chmod, queue, 0o644)
        self.assertIsNone(resume.pending_completions(path=queue))

    def test_absent_queue_is_still_empty(self):
        # Mutation caught: collapsing "absent" into "unknown" -- a queue that
        # was never written owes nothing and must not raise a false alarm.
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "chrono-queue.md"
            self.assertEqual(resume.pending_completions(path=missing), [])

    def test_empty_queue_is_still_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "chrono-queue.md"
            queue.write_text("# header only\n\n")
            self.assertEqual(resume.pending_completions(path=queue), [])

    def test_capsule_declares_an_unreadable_queue(self):
        # Mutation caught: dropping the marker line, or gating the heading on
        # `if pending:` alone (None is falsy, so the section vanishes).
        queue = self.corrupt_queue()
        capsule = stubbed_capsule(queue, queue.parent)
        self.assertIn(resume.QUEUE_HEADING, capsule)
        section = capsule.split(resume.QUEUE_HEADING, 1)[1]
        self.assertIn("unavailable", section.lower())
        self.assertIn("chrono-queue.md", section)

    def test_capsule_omits_the_queue_section_when_the_queue_is_really_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "chrono-queue.md"
            queue.write_text("# header only\n")
            capsule = stubbed_capsule(queue, Path(directory))
        self.assertNotIn(resume.QUEUE_HEADING, capsule)


class ArchivedDebtFailureTests(unittest.TestCase):
    """A debt scan that blew up must not read as "no debt"."""

    def test_scan_failure_becomes_a_loud_row(self):
        # Mutation caught: restoring `except Exception: return []`.
        with mock.patch.object(
            resume, "load_archived_debt", side_effect=OSError("archive rail gone")
        ):
            rows, _failed = resume._archived_debt_rows(root=Path("/nonexistent"))
        self.assertEqual(len(rows), 1)
        self.assertIn("archive rail gone", rows[0])

    def test_scan_failure_reaches_the_capsule(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "chrono-queue.md"
            queue.write_text("# header only\n")
            capsule = stubbed_capsule(
                queue,
                Path(directory),
                load_archived_debt={"side_effect": OSError("archive rail gone")},
            )
        self.assertIn(resume.ARCHIVED_DEBT_HEADING, capsule)
        self.assertIn("archive rail gone", capsule)

    def test_a_failure_row_is_never_collapsed_into_an_owed_count(self):
        # A scan failure squeezed through the token-bound collapse would read
        # "1 archived charter(s) still owed" -- a fabricated fact.
        # Mutation caught: reusing the ordinary collapsed count line for the
        # failure row.
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "chrono-queue.md"
            queue.write_text("# header only\n")
            capsule = stubbed_capsule(
                queue,
                Path(directory),
                max_tokens=1,
                load_archived_debt={"side_effect": OSError("boom")},
            )
        self.assertIn("boom", capsule)
        self.assertNotIn("still owed, omitted", capsule)

    def test_no_debt_is_still_no_rows(self):
        # Mutation caught: emitting the marker unconditionally.
        with mock.patch.object(resume, "load_archived_debt", return_value=[]):
            self.assertEqual(resume._archived_debt_rows(root=Path("/nonexistent")), ([], False))


class DispatchPreflightAdvisoryFailureTests(unittest.TestCase):
    """Zero advisories must mean "scanned and clean", never "scan blew up"."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.packet = self.repo / "packet.md"
        self.packet.write_text(
            "---\nid: TASK-1\nwrite_scope: [docs/]\nreturn_artifact: docs/out.md\n"
            "---\nbody\n"
        )

    @staticmethod
    def codes(warnings) -> set[str]:
        return {warning.get("code") for warning in warnings}

    def test_unreadable_packet_yields_a_loud_advisory(self):
        # Mutation caught: restoring `except Exception: return ()` in
        # `authoring_warnings`.
        missing = self.repo / "not-there.md"
        warnings = preflight.authoring_warnings(self.repo, missing)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))

    def test_advisory_scan_crash_yields_a_loud_advisory(self):
        # Mutation caught: restoring `except Exception: return ()` in
        # `_write_scope_advisories`.
        with mock.patch.object(
            preflight, "_git_paths", side_effect=RuntimeError("git exploded")
        ):
            warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))
        failure = next(
            w for w in warnings if w["code"] == preflight.ADVISORY_SCAN_FAILED
        )
        self.assertIn("git exploded", failure["message"])

    def test_the_failure_advisory_still_never_gates_dispatch(self):
        # Mutation caught: turning the new marker into a blocking refusal or a
        # required acknowledgement. Advisories are diagnostics, not gates.
        with mock.patch.object(
            preflight, "_git_paths", side_effect=RuntimeError("git exploded")
        ):
            warnings = preflight.authoring_warnings(self.repo, self.packet)
        failure = next(
            w for w in warnings if w["code"] == preflight.ADVISORY_SCAN_FAILED
        )
        self.assertEqual(failure["gate"], "advisory")
        self.assertFalse(failure["blocking"])
        self.assertNotIn("required_ack", failure)

    def test_the_failure_advisory_is_printed_to_stderr(self):
        # A marker nobody renders is the same silence in a new place.
        from contextlib import redirect_stderr
        import io

        with mock.patch.object(
            preflight, "_git_paths", side_effect=RuntimeError("git exploded")
        ):
            warnings = preflight.authoring_warnings(self.repo, self.packet)
        stream = io.StringIO()
        with redirect_stderr(stream):
            preflight._print_advisories(warnings)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, stream.getvalue())

    # The three tests above inject RuntimeError, which `_git_paths` does not
    # catch -- so they proved the OUTER handler works while never exercising the
    # way git actually fails. Real git failures raise OSError/TimeoutExpired, and
    # `_git_paths` swallowed those into `()` one level below the marker. The
    # advisory could not fire for the failure it was written for.

    def test_a_git_timeout_yields_a_loud_advisory(self):
        # Mutation caught: restoring `except ...: return ()` in `_git_paths`.
        # A slow-but-healthy git looked identical to "scanned, nothing found".
        with mock.patch.object(
            preflight.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=3),
        ):
            warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))

    def test_a_missing_git_binary_yields_a_loud_advisory(self):
        # Mutation caught: same swallow, via the OSError arm.
        with mock.patch.object(
            preflight.subprocess, "run", side_effect=FileNotFoundError("no git")
        ):
            warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))

    def test_a_non_repository_root_yields_a_loud_advisory(self):
        # `git ls-files` exits 128 outside a repository (measured). That is a
        # scan that did not run, not a repository with no tracked files.
        warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))

    def test_git_grep_finding_nothing_is_not_a_failure(self):
        # Over-correction guard. `git grep` exits 1 for "no matches" (measured),
        # which is a real answer. Treating every nonzero exit as a failure would
        # put a scan-failed marker on the common clean case and train the
        # operator to ignore it.
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True
        )
        tracked = self.repo / "docs"
        tracked.mkdir(exist_ok=True)
        (tracked / "out.md").write_text("no digest here\n")
        subprocess.run(
            ["git", "add", "."], cwd=self.repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@e.invalid",
             "commit", "-qm", "baseline"],
            cwd=self.repo, check=True, capture_output=True,
        )
        warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertNotIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))

    def test_a_scannable_packet_gets_no_failure_advisory(self):
        # Mutation caught: emitting the marker unconditionally, which would
        # make every dispatch look broken.
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True
        )
        warnings = preflight.authoring_warnings(self.repo, self.packet)
        self.assertNotIn(preflight.ADVISORY_SCAN_FAILED, self.codes(warnings))


class SupervisorReceiptQuarantineTests(unittest.TestCase):
    """An unreadable receipt must not read as "this response is fine"."""

    MARKER = "quarantine-marker"
    SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"

    @classmethod
    def fragment(cls) -> str:
        """The PYQUARANTINE heredoc, extracted so its behaviour can be run."""
        lines = cls.SUPERVISOR.read_text(encoding="utf-8").splitlines()
        start = next(
            index for index, line in enumerate(lines) if "<<'PYQUARANTINE'" in line
        )
        # The redirection is spread over continuation lines; the heredoc body
        # begins after the last of them.
        while lines[start].rstrip().endswith("\\"):
            start += 1
        end = next(
            index
            for index, line in enumerate(lines)
            if index > start and line.strip() == "PYQUARANTINE"
        )
        return "\n".join(lines[start + 1 : end])

    def run_fragment(self, receipt: Path) -> str:
        script = Path(self.directory.name) / "fragment.py"
        script.write_text(self.fragment(), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(script), str(receipt), self.MARKER],
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def receipt(self, **overrides) -> Path:
        payload = {
            "schema": "board-dispatch-receipt/v2",
            "status": "blocked",
            "terminal_outcome": "needs_review",
            "response_status": "needs_review",
            "controller_quarantine": self.MARKER,
            "cli_exec_succeeded": False,
            "failure_class": "cli_nonzero",
        }
        payload.update(overrides)
        path = Path(self.directory.name) / "receipt.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_a_quarantined_receipt_still_says_yes(self):
        self.assertEqual(self.run_fragment(self.receipt()), "yes")

    def test_a_healthy_receipt_still_says_nothing(self):
        # Mutation caught: emitting the unreadable marker for every receipt,
        # which would route every clean dispatch down the quarantine branch.
        self.assertEqual(self.run_fragment(self.receipt(status="launched")), "")

    def test_a_missing_receipt_is_distinguishable_from_a_healthy_one(self):
        # Mutation caught: restoring `except Exception: raise SystemExit(0)`.
        absent = Path(self.directory.name) / "never-written.json"
        result = self.run_fragment(absent)
        self.assertNotEqual(result, "")
        self.assertNotEqual(result, "yes")

    def test_a_corrupt_receipt_is_distinguishable_from_a_healthy_one(self):
        path = Path(self.directory.name) / "receipt.json"
        path.write_text("{not json at all", encoding="utf-8")
        result = self.run_fragment(path)
        self.assertNotEqual(result, "")
        self.assertNotEqual(result, "yes")

    def test_the_unreadable_marker_names_the_cause(self):
        absent = Path(self.directory.name) / "never-written.json"
        self.assertIn("unreadable", self.run_fragment(absent).lower())


if __name__ == "__main__":
    unittest.main()


class ArchivedDebtRailTests(unittest.TestCase):
    """`load_archived_debt` is the sibling of `load_active_charters` on the SAME
    rail, and it kept the bug that function was repaired for.

    `Path.glob` suppresses the underlying `scandir` PermissionError, so the
    `except OSError` guarding it was dead and an unreadable archive rail read as
    "no debt" -- byte-identical to a clean one. `_archived_debt_rows`'s marker
    only fires when this RAISES, so the likeliest real failure was exactly the
    one the glob ate.

    Catches: reverting `iterdir` to `glob` here, which restores the silent
    empty and makes the marker above it unreachable again.
    """

    def _rail(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "_state/chrono/thread-charters/complete").mkdir(parents=True)
        (root / "_state/chrono/thread-charters/parked").mkdir(parents=True)
        return root

    def test_an_unreadable_archive_rail_does_not_read_as_no_debt(self) -> None:
        root = self._rail()
        rail = root / "_state/chrono/thread-charters/complete"
        os.chmod(rail, 0o000)
        self.addCleanup(os.chmod, rail, 0o755)
        with self.assertRaises(OSError):
            thread_charters.load_archived_debt(root)

    def test_a_readable_but_empty_rail_still_reads_as_no_debt(self) -> None:
        """Control: the fix must not turn genuinely-empty into an error."""
        self.assertEqual(thread_charters.load_archived_debt(self._rail()), [])

    def test_an_absent_rail_still_reads_as_no_debt(self) -> None:
        """Control: an archive rail that was never created is not a failure."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertEqual(thread_charters.load_archived_debt(root), [])


class DebtScanFailureIsAFlagNotAStringTests(unittest.TestCase):
    """The token-bound protection must not depend on how the row is worded.

    `_render` decided whether to protect the scan-failure row with
    `any(row.startswith(ARCHIVED_DEBT_SCAN_FAILED) ...)` -- a control-flow
    decision recovered by re-parsing a DISPLAY string. Reword the row and the
    protection silently stops applying, with no test failing and no error: the
    marker collapses into the "N still owed" count line, which states a charter
    count nobody measured. That is the same failure-renders-as-success shape
    this phase exists to remove, one layer up.

    Catches: reverting to a text-derived flag. Under the old code the returned
    value was a bare list, so unpacking raises; and once unpacked, a reworded
    prefix would leave `failed` False while the row is present.
    """

    def test_a_failed_scan_reports_a_flag_alongside_its_row(self) -> None:
        with mock.patch.object(
            resume, "load_archived_debt", side_effect=OSError("boom")
        ):
            rows, failed = resume._archived_debt_rows(root=Path("/nonexistent"))
        self.assertTrue(failed, "a blown-up scan must report failure as a flag")
        self.assertTrue(rows, "the human-readable row must still be emitted")

    def test_the_flag_does_not_depend_on_the_rows_wording(self) -> None:
        """Reword the marker: the flag must be unaffected."""
        with mock.patch.object(resume, "ARCHIVED_DEBT_SCAN_FAILED", "- totally different"):
            with mock.patch.object(
                resume, "load_archived_debt", side_effect=OSError("boom")
            ):
                _rows, failed = resume._archived_debt_rows(root=Path("/nonexistent"))
        self.assertTrue(failed, "the flag was derived from the row text, not set")

    def test_a_clean_scan_reports_no_failure(self) -> None:
        """Control: a scan that simply found nothing is not a failure."""
        with mock.patch.object(resume, "load_archived_debt", return_value=[]):
            rows, failed = resume._archived_debt_rows(root=Path("/nonexistent"))
        self.assertFalse(failed)
        self.assertEqual(rows, [])
