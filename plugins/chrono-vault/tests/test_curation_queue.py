# plugins/chrono-vault/tests/test_curation_queue.py
"""`incorrect` is a 5-sample signal today. Nothing re-validates and the
spec adds no decay, so `invalidated` would be terminal -- one worker's
judgment silently deleting a true note, while PROMOTION requires a
passed review. That asymmetry is backwards."""
import json, stat, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from curation_queue import flag_for_curation
from jsonl import JsonlAppendError


class CurationQueueTests(unittest.TestCase):
    def test_incorrect_appends_a_flag_and_does_not_change_status(self):
        repo = Path(tempfile.mkdtemp())
        flag_for_curation("mem-a", "incorrect", "TASK-X", repo)
        line = json.loads((repo / "_state" / "curation-queue.jsonl").read_text().strip())
        self.assertEqual(line["note_id"], "mem-a")
        self.assertEqual(line["reason"], "incorrect")
        self.assertNotIn("status", line)

    def test_repeated_not_useful_appends_separate_rows(self):
        repo = Path(tempfile.mkdtemp())
        flag_for_curation("mem-a", "not_useful", "T1", repo)
        flag_for_curation("mem-a", "not_useful", "T2", repo)
        rows = (repo / "_state" / "curation-queue.jsonl").read_text().strip().splitlines()
        self.assertEqual(len(rows), 2)

    def test_every_row_carries_a_timestamp(self):
        """Alone among every record this design writes, it had none.

        `usage`, `recall_returned` and the episodic spool all carry one, and
        without it `bin/curation-review.sh --since` cannot tell a new flag
        from one seen ten sessions ago -- which is what makes a stalled
        queue unreadable rather than merely long.
        """
        repo = Path(tempfile.mkdtemp())
        flag_for_curation("mem-a", "incorrect", "TASK-X", repo)
        row = json.loads(
            (repo / "_state" / "curation-queue.jsonl").read_text().strip()
        )
        self.assertRegex(row["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        parsed = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        self.assertLess(
            abs((datetime.now(timezone.utc) - parsed).total_seconds()), 120
        )

    def test_the_queue_file_is_owner_only(self):
        """M3: this used a plain `open("a")` and inherited the umask.

        `autocapture._spool_episodic` did the same job carefully days
        earlier. Both now go through `jsonl.append_line`.
        """
        repo = Path(tempfile.mkdtemp())
        flag_for_curation("mem-a", "incorrect", "TASK-X", repo)
        mode = (repo / "_state" / "curation-queue.jsonl").stat().st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_the_queue_is_never_written_through_a_symlink(self):
        repo = Path(tempfile.mkdtemp())
        elsewhere = Path(tempfile.mkdtemp()) / "stolen.jsonl"
        (repo / "_state").mkdir(parents=True)
        (repo / "_state" / "curation-queue.jsonl").symlink_to(elsewhere)

        with self.assertRaises(JsonlAppendError):
            flag_for_curation("mem-a", "incorrect", "TASK-X", repo)
        self.assertFalse(elsewhere.exists())


if __name__ == "__main__":
    unittest.main()
