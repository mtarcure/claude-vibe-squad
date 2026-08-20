"""`bin/curation-review.sh` is the read side of Task 9's demotion queue.

Task 9 makes `flag_for_curation` append `not_useful`/`incorrect` usage
outcomes to `_state/curation-queue.jsonl`. Without a reader, that file is
write-only and `invalidated` is never set by anyone (self-review gap, spec
§10). This script renders the queue for Chrono to judge at a session
boundary; it must never set `invalidated` itself, and it must say so
explicitly when there is nothing to review -- silence must be
distinguishable from breakage, the same lesson `bin/doctor.sh`'s
`note_absent_input` encodes for probe output.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "bin" / "curation-review.sh"


class CurationReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="curation-review-test-"))
        self.addCleanup(
            lambda: subprocess.run(["rm", "-rf", str(self.workdir)], check=False)
        )
        self.queue_path = self.workdir / "curation-queue.jsonl"

    def run_review(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["CURATION_QUEUE_UNDER_TEST"] = str(self.queue_path)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def _write_rows(self, rows: list[dict]) -> None:
        self.queue_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_missing_queue_file_exits_zero_with_explicit_empty_line(self) -> None:
        self.assertFalse(self.queue_path.exists())
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("queue empty", completed.stdout.lower())

    def test_present_but_empty_queue_file_exits_zero_with_explicit_empty_line(
        self,
    ) -> None:
        self.queue_path.write_text("", encoding="utf-8")
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("queue empty", completed.stdout.lower())

    def test_renders_reason_and_count_grouped_by_note_id(self) -> None:
        self._write_rows(
            [
                {"note_id": "mem-a", "reason": "incorrect", "source_task": "T1"},
                {"note_id": "mem-a", "reason": "incorrect", "source_task": "T2"},
                {"note_id": "mem-a", "reason": "not_useful", "source_task": "T3"},
                {"note_id": "mem-b", "reason": "not_useful", "source_task": "T4"},
            ]
        )
        completed = self.run_review()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("queue empty", completed.stdout.lower())

        mem_a_line = next(
            line for line in completed.stdout.splitlines() if "mem-a" in line
        )
        mem_b_line = next(
            line for line in completed.stdout.splitlines() if "mem-b" in line
        )
        # mem-a: 3 total flags, grouped repeats -- 2x incorrect and 1x not_useful.
        self.assertIn("3", mem_a_line)
        self.assertIn("incorrect", mem_a_line)
        self.assertIn("not_useful", mem_a_line)
        # mem-b: 1 flag.
        self.assertIn("1", mem_b_line)
        self.assertIn("not_useful", mem_b_line)

    def test_never_calls_set_status_or_mutates_notes(self) -> None:
        """A renderer only: setting `invalidated` is Chrono's judgment, not this
        script's -- it must never call the lifecycle write path that could."""
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("set_status", text)
        self.assertNotIn("lifecycle.", text)
        self.assertNotIn("record_usage", text)

    def test_malformed_row_is_reported_as_an_error_not_silently_dropped(self) -> None:
        self.queue_path.write_text('{"note_id": "mem-a"}\n', encoding="utf-8")
        completed = self.run_review()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("curation-review", completed.stderr.lower())
    # -- I7: the cursor ---------------------------------------------------
    #
    # The queue has no acknowledgement and no archive -- `curation-protocol.md`
    # §3 says a dismissed flag "stays in the queue's history" -- so without a
    # way to separate new from old every session boundary re-renders every
    # flag ever recorded. §5 claims the stall mode is "a growing queue and a
    # correspondingly noisier ranking"; an undifferentiated queue does not
    # degrade, it becomes unreadable, and an unreadable queue is an ignored
    # one. Folded into this class rather than a subclass: a TestCase subclass
    # re-runs every inherited test under `discover`.

    def test_since_renders_only_flags_recorded_at_or_after_it(self) -> None:
        self._write_rows([
            {"note_id": "mem-old", "reason": "incorrect", "source_task": "T1",
             "ts": "2026-08-01T00:00:00Z"},
            {"note_id": "mem-new", "reason": "not_useful", "source_task": "T2",
             "ts": "2026-08-17T12:00:00Z"},
        ])

        completed = self.run_review("--since", "2026-08-10T00:00:00Z")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("mem-new", completed.stdout)
        self.assertNotIn("mem-old", completed.stdout)
        self.assertIn("2026-08-10T00:00:00Z", completed.stdout)

    def test_without_since_every_flag_is_still_rendered(self) -> None:
        self._write_rows([
            {"note_id": "mem-old", "reason": "incorrect", "source_task": "T1",
             "ts": "2026-08-01T00:00:00Z"},
            {"note_id": "mem-new", "reason": "not_useful", "source_task": "T2",
             "ts": "2026-08-17T12:00:00Z"},
        ])

        completed = self.run_review()

        self.assertIn("mem-old", completed.stdout)
        self.assertIn("mem-new", completed.stdout)

    def test_a_row_written_before_ts_existed_is_kept_not_hidden(self) -> None:
        """Unknown age is not known-old.

        Dropping undated rows under --since would hide exactly the backlog
        this flag exists to make navigable.
        """
        self._write_rows([
            {"note_id": "mem-undated", "reason": "incorrect", "source_task": "T1"},
        ])

        completed = self.run_review("--since", "2026-08-10T00:00:00Z")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("mem-undated", completed.stdout)
        self.assertIn("undated", completed.stdout)

    def test_nothing_new_is_distinguishable_from_an_empty_queue(self) -> None:
        self._write_rows([
            {"note_id": "mem-old", "reason": "incorrect", "source_task": "T1",
             "ts": "2026-08-01T00:00:00Z"},
        ])

        filtered = self.run_review("--since", "2026-08-10T00:00:00Z")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        self.assertIn("nothing new", filtered.stdout.lower())
        self.assertNotIn("queue empty", filtered.stdout.lower())

    def test_a_malformed_since_is_refused_loudly(self) -> None:
        self._write_rows([
            {"note_id": "mem-a", "reason": "incorrect", "source_task": "T1",
             "ts": "2026-08-17T00:00:00Z"},
        ])

        completed = self.run_review("--since", "last tuesday")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--since", completed.stderr)

    def test_an_unknown_argument_is_refused_loudly(self) -> None:
        completed = self.run_review("--invalidate-everything")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown argument", completed.stderr)


if __name__ == "__main__":
    unittest.main()
