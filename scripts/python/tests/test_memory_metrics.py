import json, re, sqlite3, sys, tempfile, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.python.memory_metrics import (
    DEFAULT_NOTE_TYPES, DEFAULT_STATUSES, NEGATIVE_OUTCOMES, PROMOTION_EVENT,
    QUEUE_FILES, reachability, utilisation_breadth, negative_feedback_rate,
    autocapture_write_failures, promotion_events, promotion_throughput,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))
import registry_reconciler  # noqa: E402

def _vault(rows, usage=()):
    root = Path(tempfile.mkdtemp())
    (root / "index").mkdir()
    con = sqlite3.connect(root / "index" / "kg.db")
    con.execute("CREATE TABLE meta (docid INTEGER, id TEXT, status TEXT, note_type TEXT, mtime_ns INTEGER)")
    con.execute("CREATE TABLE usage (recall_id TEXT, note_id TEXT, outcome TEXT, source_task TEXT, ts TEXT)")
    con.executemany("INSERT INTO meta VALUES (?,?,?,?,?)", rows)
    con.executemany("INSERT INTO usage VALUES (?,?,?,?,?)", usage)
    con.commit(); con.close()
    return root

def _vault_with_verified_at(rows):
    """Like _vault, but the meta table also carries verified_at_ns --
    the promotion-time column the corrected metric requires and today's
    live schema does not yet have."""
    root = Path(tempfile.mkdtemp())
    (root / "index").mkdir()
    con = sqlite3.connect(root / "index" / "kg.db")
    con.execute(
        "CREATE TABLE meta (docid INTEGER, id TEXT, status TEXT, note_type TEXT, "
        "mtime_ns INTEGER, verified_at_ns INTEGER)"
    )
    con.executemany("INSERT INTO meta VALUES (?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return root

class MemoryMetricsTests(unittest.TestCase):
    def test_reachability_counts_admitted_notes_only(self):
        root = _vault([
            (1, "mem-a", "candidate", "learning", 0),
            (2, "mem-b", "verified",  "finding",  0),
            (3, "mem-c", "invalidated", "finding", 0),
        ])
        # default aperture admits candidate|verified across all three types
        self.assertEqual(reachability(root), 2)

    def test_utilisation_breadth_is_distinct_notes_over_total(self):
        root = _vault(
            [(1, "mem-a", "candidate", "learning", 0), (2, "mem-b", "candidate", "finding", 0)],
            usage=[("r1", "mem-a", "used", "TASK-1", "2026-08-01T00:00:00Z"),
                   ("r2", "mem-a", "used", "TASK-2", "2026-08-02T00:00:00Z")],
        )
        self.assertEqual(utilisation_breadth(root), (1, 2))

    def test_negative_feedback_rate_counts_not_useful_and_incorrect(self):
        root = _vault(
            [(1, "mem-a", "candidate", "learning", 0)],
            usage=[("r1", "mem-a", "used", "T", "2026-08-01T00:00:00Z"),
                   ("r2", "mem-a", "not_useful", "T", "2026-08-01T00:00:00Z"),
                   ("r3", "mem-a", "incorrect", "T", "2026-08-01T00:00:00Z")],
        )
        self.assertEqual(negative_feedback_rate(root), (2, 3))

    def test_promotion_throughput_returns_zero_without_verification_timestamp(self):
        # mtime_ns is the file's last-touch time (reindex, vault sync,
        # anything) -- never a promotion event. A verified note with a
        # recent mtime and no verified_at_ns must not be counted as a
        # recent promotion; it must not count at all.
        now_ns = time.time_ns()
        root = _vault([
            (1, "mem-a", "verified", "finding", now_ns),
            (2, "mem-b", "candidate", "finding", now_ns),
        ])
        self.assertEqual(promotion_throughput(root, days=30), 0)

    def test_promotion_throughput_counts_recent_verified_at(self):
        now_ns = time.time_ns()
        old_ns = now_ns - (40 * 86400 * 10**9)
        root = _vault_with_verified_at([
            (1, "mem-a", "verified", "finding", now_ns, now_ns),   # recent, counts
            (2, "mem-b", "verified", "finding", now_ns, old_ns),   # verified_at too old
            (3, "mem-c", "verified", "finding", now_ns, None),     # promoted pre-stamping
            (4, "mem-d", "candidate", "finding", now_ns, now_ns),  # not verified
        ])
        self.assertEqual(promotion_throughput(root, days=30), 1)


class PromotionEventTests(unittest.TestCase):
    """The alarm must count the handler, not something adjacent to it.

    `verified_at` has three provenances -- promotion, a note recorded
    straight to `verified`, and a manual `set_status` during curation --
    so a single hand-verified note silenced "the handler stopped firing"
    for a whole window. `MEMORY-PROMOTION` has exactly one writer.
    """

    def _repo(self, lines: list[str], archived: list[str] | None = None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "_state").mkdir()
        (root / "_state" / "chrono-queue.md").write_text(
            "# Chrono Queue\n# timestamp | status | namespace/task-id | summary\n\n"
            + "".join(f"{line}\n" for line in lines),
            encoding="utf-8",
        )
        if archived is not None:
            # Exactly what bin/chrono-queue-backfill.sh writes: the moved
            # lines plus its batch marker, no header.
            (root / "_state" / "chrono-queue-handled.md").write_text(
                "".join(f"{line}\n" for line in archived)
                + "<!-- chrono-queue-backfill:batch=" + "0" * 64 + " -->\n",
                encoding="utf-8",
            )
        return root

    @staticmethod
    def _stamp(days_ago: float) -> str:
        moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_counts_only_recent_promotion_events(self):
        root = self._repo([
            f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-A | promoted 2 note(s)",
            f"{self._stamp(29)} | MEMORY-PROMOTION | coding/TASK-B | promoted 1 note(s)",
            f"{self._stamp(40)} | MEMORY-PROMOTION | coding/TASK-C | promoted 1 note(s)",
            f"{self._stamp(1)} | REVIEW-SETTLED | coding/TASK-D | settled",
            f"{self._stamp(1)} | SWARM-REVIEW-SETTLED | coding/TASK-E | settled",
        ])
        self.assertEqual(promotion_events(root, days=30), 2)

    def test_a_hand_verified_note_does_not_register_as_an_event(self):
        """The exact silencing I1 reported: stamped note, no handler firing."""
        vault = _vault_with_verified_at(
            [(1, "mem-a", "verified", "finding", time.time_ns(), time.time_ns())]
        )
        repo = self._repo([f"{self._stamp(1)} | REVIEW-SETTLED | coding/TASK-A | settled"])

        self.assertEqual(promotion_throughput(vault, days=30), 1)
        self.assertEqual(promotion_events(repo, days=30), 0)

    def test_an_absent_queue_is_zero_not_an_error(self):
        self.assertEqual(promotion_events(Path(tempfile.mkdtemp()), days=30), 0)

    def test_a_malformed_line_is_skipped_not_fatal(self):
        root = self._repo([
            "garbage without a timestamp | MEMORY-PROMOTION | x | y",
            "9999-99-99T99:99:99Z | MEMORY-PROMOTION | coding/TASK-X | bad date",
            f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-A | promoted 1 note(s)",
        ])
        self.assertEqual(promotion_events(root, days=30), 1)

    def test_a_skipped_promotion_is_not_an_event(self):
        """N1: an unset CHRONO_VAULT_ROOT at settlement promotes NOTHING.

        This is the alarm's own sentence, one layer on: while every outcome
        of the handler wore one status, a shell with no `CHRONO_VAULT_ROOT`
        -- a recurring condition on this machine -- made the doctor report
        "the promotion handler fired" on a vault where nothing had ever been
        promoted.
        """
        root = self._repo([
            f"{self._stamp(1)} | MEMORY-PROMOTION-SKIPPED | coding/TASK-A | "
            "memory promotion skipped: CHRONO_VAULT_ROOT is unset",
            f"{self._stamp(2)} | MEMORY-PROMOTION-SKIPPED | coding/TASK-B | "
            "memory promotion skipped: CHRONO_VAULT_ROOT is unset",
        ])
        self.assertEqual(promotion_events(root, days=30), 0)

    def test_a_failed_promotion_is_not_an_event(self):
        root = self._repo([
            f"{self._stamp(1)} | MEMORY-PROMOTION-FAILED | coding/TASK-A | "
            "memory promotion failed: memory index is missing",
        ])
        self.assertEqual(promotion_events(root, days=30), 0)

    def test_skips_and_failures_do_not_hide_a_real_promotion(self):
        """The other direction: noise must not suppress the real count."""
        root = self._repo([
            f"{self._stamp(1)} | MEMORY-PROMOTION-SKIPPED | coding/TASK-A | skipped",
            f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-B | promoted 1 note(s)",
            f"{self._stamp(1)} | MEMORY-PROMOTION-FAILED | coding/TASK-C | failed",
        ])
        self.assertEqual(promotion_events(root, days=30), 1)

    def test_archived_promotion_lines_are_still_counted(self):
        """N2: `bin/chrono-queue-backfill.sh` moves every settled line out.

        A `MEMORY-PROMOTION` line is written at settlement, so its task is
        `complete` -- never one of the OPEN statuses the backfill keeps --
        and it is archived on the next run. Live state proves this runs:
        `chrono-queue-handled.md` held 110 `REVIEW-SETTLED` lines while
        `chrono-queue.md` held 0. Reading only the live queue would report
        ZERO on exactly the machine that has been promoting normally.
        """
        root = self._repo(
            [f"{self._stamp(1)} | REVIEW-SETTLED | coding/TASK-OPEN | settled"],
            archived=[
                f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-A | promoted 1",
                f"{self._stamp(29)} | MEMORY-PROMOTION | coding/TASK-B | promoted 2",
                f"{self._stamp(40)} | MEMORY-PROMOTION | coding/TASK-C | too old",
                f"{self._stamp(1)} | MEMORY-PROMOTION-FAILED | coding/TASK-D | failed",
            ],
        )
        self.assertEqual(promotion_events(root, days=30), 2)

    def test_live_and_archived_halves_sum(self):
        root = self._repo(
            [f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-A | promoted 1"],
            archived=[
                f"{self._stamp(2)} | MEMORY-PROMOTION | coding/TASK-B | promoted 1"
            ],
        )
        self.assertEqual(promotion_events(root, days=30), 2)

    def test_an_absent_archive_is_not_an_error(self):
        root = self._repo(
            [f"{self._stamp(1)} | MEMORY-PROMOTION | coding/TASK-A | promoted 1"]
        )
        self.assertFalse((root / "_state" / "chrono-queue-handled.md").exists())
        self.assertEqual(promotion_events(root, days=30), 1)

    def test_the_counted_status_is_the_reconcilers_own_constant(self):
        """CLAUDE.md rule 10: one fact, one home.

        `memory_metrics` parses the queue rather than importing the
        settlement module, so this string is a copy. This is what keeps the
        copy honest -- and what stops a later rename of the reconciler's
        status from silently zeroing the alarm.
        """
        self.assertEqual(PROMOTION_EVENT, registry_reconciler.MEMORY_PROMOTION_STATUS)
        for other in (
            registry_reconciler.MEMORY_PROMOTION_SKIPPED_STATUS,
            registry_reconciler.MEMORY_PROMOTION_FAILED_STATUS,
        ):
            self.assertNotEqual(other, PROMOTION_EVENT)

    def test_the_archive_filename_matches_the_backfill_script(self):
        """The other half of the same rule: the archive's name is a copy of
        `bin/chrono-queue-backfill.sh`'s `HANDLED`."""
        script = (
            Path(__file__).resolve().parents[3] / "bin" / "chrono-queue-backfill.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('HANDLED="${STATE}/chrono-queue-handled.md"', script)
        self.assertEqual(
            QUEUE_FILES, ("chrono-queue.md", "chrono-queue-handled.md")
        )


class VocabularyPinTests(unittest.TestCase):
    """M1: `reachability` drives spec §11's "number that silently regressed".

    `DEFAULT_STATUSES` / `DEFAULT_NOTE_TYPES` were a seventh copy of the
    aperture vocabulary with a "keep the two in step" comment and nothing
    enforcing it. This is the enforcement.
    """

    def test_default_statuses_and_types_match_the_policy_registry(self):
        rows = (
            Path(__file__).resolve().parents[3]
            / "shared" / "registries" / "memory-apertures.tsv"
        ).read_text(encoding="utf-8").splitlines()
        header = rows[0].split("\t")
        for line in rows[1:]:
            if not line.strip():
                continue
            cells = dict(zip(header, line.split("\t")))
            if cells["aperture"] != "default":
                continue
            self.assertEqual(
                tuple(cells["statuses"].split("|")), DEFAULT_STATUSES
            )
            self.assertEqual(
                tuple(cells["note_types"].split("|")), DEFAULT_NOTE_TYPES
            )
            break
        else:
            self.fail("memory-apertures.tsv no longer declares a `default` row")

    def test_negative_outcomes_match_the_vault_outcome_vocabulary(self):
        lifecycle = (
            Path(__file__).resolve().parents[3]
            / "plugins" / "chrono-vault" / "lifecycle.py"
        ).read_text(encoding="utf-8")
        match = re.search(r"OUTCOMES\s*=\s*frozenset\(\{([^}]*)\}\)", lifecycle)
        self.assertIsNotNone(match, "lifecycle.py no longer declares OUTCOMES")
        declared = set(re.findall(r'"([a-z_]+)"', match.group(1)))
        self.assertTrue(set(NEGATIVE_OUTCOMES) <= declared)
        self.assertNotIn("used", NEGATIVE_OUTCOMES)


class AutocaptureWriteFailureTests(unittest.TestCase):
    """I5: a broken distillation lane writes no note and moves no metric.

    `reachability` and `utilisation_breadth` describe the notes that exist,
    not the ones that were never written, so "gemini is unauthenticated for
    three weeks and memory quietly stops growing" moved nothing at all --
    the 2026-07-25 shape, reintroduced by the fix for it.
    """

    def _repo(self, rows: list[dict]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "_state").mkdir()
        (root / "_state" / "autocapture-failures.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        return root

    @staticmethod
    def _at(days_ago: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def test_counts_only_failures_inside_the_window(self):
        root = self._repo([
            {"schema_version": 1, "reason": "distillation_failed:x", "at": self._at(1)},
            {"schema_version": 1, "reason": "distillation_failed:y", "at": self._at(2)},
            {"schema_version": 1, "reason": "distillation_failed:z", "at": self._at(30)},
        ])
        self.assertEqual(autocapture_write_failures(root, days=7), 2)

    def test_an_absent_log_is_zero_not_an_error(self):
        self.assertEqual(
            autocapture_write_failures(Path(tempfile.mkdtemp()), days=7), 0
        )

    def test_a_malformed_row_is_skipped_not_fatal(self):
        root = Path(tempfile.mkdtemp())
        (root / "_state").mkdir()
        (root / "_state" / "autocapture-failures.jsonl").write_text(
            "not json\n"
            + json.dumps({"reason": "no timestamp"})
            + "\n"
            + json.dumps({"reason": "ok", "at": self._at(1)})
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual(autocapture_write_failures(root, days=7), 1)
