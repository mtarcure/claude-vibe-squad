"""The four measurements from the memory-loop spec, §11.

Read-only. Every function takes a vault root and opens the index in
read-only URI mode, so calling these can never mutate the operator's
memory. They exist so the spec's central claim is falsifiable: if
utilisation breadth does not rise after admission opens, the
admission-first hypothesis is wrong and the work redirects to
retrieval quality.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# `registry_reconciler.append_chrono_queue` writes
# `<ISO8601Z> | <status> | <namespace>/<task-id> | <summary>`, append-only,
# never rotated. Parsed rather than imported because importing the reconciler
# would make every metric read pull in the whole settlement module.
_QUEUE_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) \| (?P<status>[^|]+) \|"
)
# `registry_reconciler.MEMORY_PROMOTION_STATUS`. Restated rather than
# imported for the reason in the comment above, and pinned to the reconciler
# constant by `test_memory_metrics.PromotionEventTests`. The reconciler also
# writes `MEMORY-PROMOTION-SKIPPED` and `MEMORY-PROMOTION-FAILED`; those are
# deliberately NOT this string, and the exact-equality match below is what
# keeps them out of the count.
PROMOTION_EVENT = "MEMORY-PROMOTION"

# Every file a `MEMORY-PROMOTION` line can be sitting in. `bin/chrono-queue-
# backfill.sh` partitions `chrono-queue.md` by whether the task is still open
# (`review-required`/`needs_review`/`needs_human`) and MOVES everything else
# to `chrono-queue-handled.md`. A promotion line is written at settlement, so
# its task is `complete` and never open -- every one of them is archived on
# the next backfill run. Reading only the live queue therefore reports zero
# on exactly the machine that has been promoting and archiving normally.
# The partition is a move, not a copy, so summing the two cannot double-count.
QUEUE_FILES = ("chrono-queue.md", "chrono-queue-handled.md")

# The default aperture admits these. Mirrors memory.default.v1 in
# shared/registries/memory-apertures.tsv -- keep the two in step.
DEFAULT_STATUSES = ("candidate", "verified")
DEFAULT_NOTE_TYPES = ("attempt", "finding", "learning")

NEGATIVE_OUTCOMES = ("not_useful", "incorrect")


def _connect(root: Path) -> sqlite3.Connection:
    db = Path(root) / "index" / "kg.db"
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def reachability(root: Path) -> int:
    """Notes recall can return at all under the default aperture."""
    con = _connect(root)
    try:
        marks_s = ",".join("?" * len(DEFAULT_STATUSES))
        marks_t = ",".join("?" * len(DEFAULT_NOTE_TYPES))
        row = con.execute(
            f"SELECT COUNT(*) FROM meta "
            f"WHERE status IN ({marks_s}) AND note_type IN ({marks_t})",
            (*DEFAULT_STATUSES, *DEFAULT_NOTE_TYPES),
        ).fetchone()
        return int(row[0])
    finally:
        con.close()


def utilisation_breadth(root: Path) -> tuple[int, int]:
    """(distinct notes ever recalled, total notes). The headline probe."""
    con = _connect(root)
    try:
        used = con.execute("SELECT COUNT(DISTINCT note_id) FROM usage").fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
        return int(used), int(total)
    finally:
        con.close()


def negative_feedback_rate(root: Path) -> tuple[int, int]:
    """(negative usage outcomes, all usage outcomes).

    Early warning for the risk of opening `candidate`: if workers are
    flooded with plumbing-framed notes, this rises.
    """
    con = _connect(root)
    try:
        marks = ",".join("?" * len(NEGATIVE_OUTCOMES))
        neg = con.execute(
            f"SELECT COUNT(*) FROM usage WHERE outcome IN ({marks})", NEGATIVE_OUTCOMES
        ).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
        return int(neg), int(total)
    finally:
        con.close()


def promotion_events(repo_root: Path | None = None, days: int = 30) -> int:
    """Times the promotion HANDLER fired in the window. The alarm's number.

    `promotion_throughput` below counts notes carrying a `verified_at`
    stamp, and that stamp has three provenances, only one of which is
    promotion: `notes._normalize` stamps it for a note recorded straight to
    `verified`, and `lifecycle.set_status` stamps it for any manual
    promotion -- including Chrono setting a status by hand during curation,
    which `shared/curation-protocol.md` §3 has it doing at every session
    boundary. One hand-verified note therefore silenced the "the handler
    stopped firing" alarm for a full 30 days.

    That is the same defect class as the `mtime` bug the controller caught
    during Task 10 (Ruling T2a), one layer down: a number adjacent to
    promotion standing in for promotion. This one is not adjacent.
    `registry_reconciler.settle_review` appends exactly one
    `MEMORY-PROMOTION` line per settlement that promoted anything -- a
    settlement that skipped promotion (`CHRONO_VAULT_ROOT` unset) or failed
    it writes `MEMORY-PROMOTION-SKIPPED` / `MEMORY-PROMOTION-FAILED`
    instead, so the exact-equality match below counts the handler
    SUCCEEDING and only that. It matters which: the whole point of this
    number is to be loud when promotion is not happening, and until
    2026-08-17 all three outcomes shared one status, so an unset vault root
    at settlement made this metric answer "the handler fired" on a machine
    that had never promoted a single note. An alarm that counts its own
    failures as successes is the defect I1 reported, restated one layer on.

    Reads the repo's Chrono queue -- BOTH halves of it -- not the vault: the
    handler lives on the reconciler side, and this measures the handler. See
    `QUEUE_FILES` for why the archived half is not optional. An absent queue
    is 0 -- a machine that has never settled a review has never promoted.
    """
    state = Path(repo_root or REPO_ROOT) / "_state"
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    count = 0
    for name in QUEUE_FILES:
        try:
            text = (state / name).read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue
        for line in text.splitlines():
            match = _QUEUE_LINE.match(line)
            if match is None or match.group("status").strip() != PROMOTION_EVENT:
                continue
            try:
                stamped = datetime.strptime(
                    match.group("ts"), "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if stamped >= cutoff:
                count += 1
    return count


def autocapture_write_failures(repo_root: Path | None = None, days: int = 7) -> int:
    """Captures that produced NO semantic note in the window.

    The write path now depends on a live model lane: `autocapture.distill()`
    shells out to the agy-backed `gemini` lane, and a `DistillationFailed` means the raw
    capture is spooled to the episodic tier but no note is written. Memory
    stops growing, and none of spec §11's four measurements moves --
    `reachability` and `utilisation_breadth` describe the notes that exist,
    not the ones that were never written.

    This repo's recorded history with lane-CLI auth fragility is exactly why
    that matters: "gemini is unauthenticated for three weeks and memory
    quietly stops growing" is the 2026-07-25 failure shape, reintroduced by
    the fix for it. A shorter default window than the promotion metric's,
    because a broken lane is a now-problem, not a trend.

    An absent log is 0: nothing has failed, or nothing has run.
    """
    path = Path(repo_root or REPO_ROOT) / "_state" / "autocapture-failures.jsonl"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            stamped = datetime.strptime(
                str(row["at"]), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if stamped >= cutoff:
            count += 1
    return count


def promotion_throughput(root: Path, days: int = 30) -> int:
    """Notes that reached `verified` within the window, by promotion time.

    NOT the handler's throughput -- an upper bound on it. Read
    `promotion_events` above for why, and use that one for any alarm that
    means "the promotion handler stopped firing".

    Counts on `verified_at_ns` -- a column the promotion handler is
    expected to stamp when it sets a note's status to `verified` -- never
    on `mtime_ns`. `mtime_ns` is `stat_result.st_mtime_ns`: the file's
    last-touch time (index rebuild, vault sync, anything), set by
    `plugins/chrono-vault/index.py`'s `_parse_note`/`_upsert_connection`
    on every reindex. It is not evidence of when promotion happened, and
    counting on it made this metric read 99 on a vault where promotion
    has never stamped anything -- a check that cannot fail is the exact
    defect this design exists to remove.

    If `verified_at_ns` does not exist yet -- today's state, since
    nothing stamps it -- this returns 0 rather than falling back to
    mtime and reporting a silently-wrong number. A `verified` row with a
    NULL `verified_at_ns` (promoted before stamping existed) is excluded
    the same way: it is not "recent" just because nothing marks it as
    anything else.

    Zero over a full window means either the promotion handler is not
    firing, or it does not yet stamp `verified_at_ns`. Task 10 turns
    this into a doctor check that fails loudly, because a silent sweep
    is what this whole design exists to avoid.
    """
    cutoff_ns = time.time_ns() - int(days) * 86400 * 10**9
    con = _connect(root)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(meta)")}
        if "verified_at_ns" not in cols:
            return 0
        row = con.execute(
            "SELECT COUNT(*) FROM meta WHERE status = 'verified' "
            "AND verified_at_ns IS NOT NULL AND verified_at_ns >= ?",
            (cutoff_ns,),
        ).fetchone()
        return int(row[0])
    finally:
        con.close()
