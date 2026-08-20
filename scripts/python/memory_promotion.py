"""Promote memory notes when work that used them passed review.

Hooked to the reconciler's explicit review settlement -- an EVENT, not a
sweep. Event handlers fail loudly at the event; sweeps fail silently
forever, which is how 94.6% of notes ended up stuck at `candidate` after
curation and usage telemetry both stopped on 2026-07-25 and nothing
noticed for 23 days.

The bar is deliberately weaker than the spec's ideal. "Independently
confirmed outcome" (bounty validated, fix merged with a passing test) has
no live event: `shared/lifecycle.md:57` says settlement and outcome are
staged V4 terms, "not live event automation". Operator decision
2026-08-17: take the weaker signal that fires over the stronger signal
that does not exist.

What it is NOT weaker on is per-note judgement. A note is promoted only
when the worker that read it reported `outcome="used"` AND the task passed
review -- two signals from two different parties. Second operator decision,
2026-08-17: promotion requires a positive signal. The first implementation
joined `recall_returned` and so promoted every note the search HANDED a
worker, read or not, useful or not; spec section 8 had already rejected
usage-driven promotion as "promoting whatever BM25 already liked", and
returned-set promotion is that same objection one step weaker. See
`_cited_candidates`.

Read the expected throughput before reading spec §11 item 4's numbers.
Spec §6 justifies the hook with "893 tasks have reached `complete`", but
the hook is on `settle_review`, and of 864 `complete` registry entries
measured 2026-08-17 only 195 carry `review_settled_by` and only 109
(12.6%) are `chrono-explicit`. `settle_review` is the right place -- it is
where the verdict exists -- but the ceiling is about 1/8 of what that
sentence suggests, and a low absolute number is not evidence of a stall.

Deliberately absent: time-based decay, TTL, and recency demotion (spec
§9). With 7.2% of notes ever recalled, "never recalled" describes nearly
the whole store, so decay would demote almost everything -- including the
rare-but-critical note whose moment has not come. Demotion requires a
positive signal that a note is wrong.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Reviews that can promote. A formatting or structural pass says nothing
# about whether the memory was RIGHT, so it must not promote. This is an
# allowlist stated in the reconciler's real vocabulary (`REVIEW_CLASSES`,
# `registry_reconciler.py:97`), not a plausible-looking one: a weaker
# review class added later must not start promoting by default.
# `test_memory_promotion.py` pins it to that constant.
#
# Stated plainly so nobody reads this as an active filter: today this set is
# EQUAL to `REVIEW_CLASSES`, so it excludes nothing. The spec asked for a
# gate that "excludes formatting-only", and this repo has no formatting-only
# review class to exclude -- the plan's hypothetical `"format"` does not
# exist. The allowlist earns its place prospectively, not currently: it is
# what makes adding one a deliberate act rather than a silent widening.
SUBSTANTIVE_REVIEW_CLASSES = frozenset({"standard", "factual", "security-finding"})

# `require_approval_verdict` (`registry_reconciler.py:2118`) settles on
# exactly APPROVE and refuses everything else, so APPROVE is the only
# verdict that can mean "this work passed". A forced override reaches
# settlement carrying its original non-APPROVE verdict and therefore
# promotes nothing -- which is correct: an override is the operator
# closing a task, not a review passing.
PASSING_VERDICTS = frozenset({"APPROVE"})

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "chrono-vault"


class MemoryPromotionError(RuntimeError):
    """Promotion could not run against the configured vault."""


def _vault_lifecycle():
    """Import the vault's lifecycle module, which owns the atomic write.

    Imported lazily so the reconciler pays nothing for it on the paths
    that never promote, and appended (not prepended) to `sys.path` so the
    vault's bare-name modules cannot shadow a caller's own.
    """
    plugin_root = str(_PLUGIN_ROOT)
    if plugin_root not in sys.path:
        sys.path.append(plugin_root)
    try:
        import lifecycle  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - a broken checkout
        raise MemoryPromotionError(f"chrono-vault is unavailable: {exc}") from exc
    return lifecycle


@contextmanager
def _vault_root_env(vault_root: Path) -> Iterator[None]:
    """Point the vault modules at `vault_root` for the duration.

    `lifecycle.set_status` resolves its root from `CHRONO_VAULT_ROOT`
    rather than a parameter, so honouring this function's `vault_root`
    argument means binding the variable around the call. Restored on every
    exit, including the raising one.
    """
    previous = os.environ.get("CHRONO_VAULT_ROOT")
    os.environ["CHRONO_VAULT_ROOT"] = str(vault_root)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CHRONO_VAULT_ROOT", None)
        else:
            os.environ["CHRONO_VAULT_ROOT"] = previous


# The outcome a worker must have reported for a note to be promotable.
# `lifecycle.OUTCOMES` is {used, not_useful, incorrect}; only the positive
# one is a statement that this note helped. Stated as a constant so the
# vocabulary has one home and `test_memory_promotion.py` can pin it there.
PROMOTING_OUTCOME = "used"


def _cited_candidates(db: Path, task_ref: str) -> list[str]:
    """Return the candidate notes this task reported it actually USED.

    Operator decision, 2026-08-17: promotion requires a positive signal. The
    join is on `usage`, not `recall_returned` -- the difference is a
    per-note judgement by the worker that read the note, versus no judgement
    at all. Promoting on `recall_returned` promoted every note the search
    HANDED the worker, whether or not it was read, useful, or even on topic;
    spec section 8 rejected usage-driven promotion as "promoting whatever
    BM25 already liked", and returned-set promotion is that same objection
    one step weaker. A note now earns `verified` only when the worker
    explicitly reported it as `used` AND the task passed review. Both are
    required: usage alone says a worker found it helpful, and review is what
    says the work it helped was right.

    Both sides of the join are authenticated. `task_ref` is the identity the
    reconciler holds under the registry lock at settlement, and
    `usage.source_task` is overwritten from the bound engagement's context
    rather than taken on the caller's word (`lifecycle.record_usage`), so a
    worker cannot promote another engagement's notes by declaring its id.

    The dispatch prompt already asks for this by name -- `record_usage(...,
    outcome="used")` for each recalled note that informed the work, wherever
    the aperture permits reads (`dispatch_context_builder`) -- so this is a
    signal production is instructed to produce, not a new demand on workers.
    Where a worker reports nothing, nothing promotes: the failure direction
    is a note left at `candidate`, which the next task that recalls and uses
    it can still promote.

    Only `candidate` promotes. `superseded`, `invalidated` and `archived`
    are lifecycle decisions already made, and a passing review of work
    that happened to use such a note must not overturn them.
    """
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise MemoryPromotionError(f"memory index is unreadable: {exc}") from exc
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usage'"
        ).fetchone()
        if exists is None:
            # Nothing has reported an outcome yet, so nothing is promotable.
            return []
        rows = connection.execute(
            "SELECT DISTINCT u.note_id FROM usage AS u"
            " JOIN meta AS m ON m.id = u.note_id"
            " WHERE u.source_task = ? AND u.outcome = ?"
            " AND m.status = 'candidate'"
            " ORDER BY u.note_id",
            (task_ref, PROMOTING_OUTCOME),
        ).fetchall()
    except sqlite3.Error as exc:
        raise MemoryPromotionError(f"memory index query failed: {exc}") from exc
    finally:
        connection.close()
    return [row[0] for row in rows]


def promote_cited_notes(
    task_ref: str, verdict: str, review_class: str, vault_root: Path
) -> list[str]:
    """Promote candidate notes this task reported it used. Returns IDs.

    Returns `[]` whenever the gate says no -- a failing verdict, a
    non-substantive review class, an unauthenticated task, or no note this
    task reported as `used`. Raises `MemoryPromotionError` when the vault
    itself cannot be reached, so a misconfigured vault is reported rather
    than read as "there was nothing to promote".
    """
    if not isinstance(task_ref, str) or not task_ref.strip():
        return []
    if (verdict or "").strip().upper() not in PASSING_VERDICTS:
        return []
    if (review_class or "").strip().lower() not in SUBSTANTIVE_REVIEW_CLASSES:
        return []

    root = Path(vault_root)
    db = root / "index" / "kg.db"
    if not db.is_file():
        raise MemoryPromotionError(f"memory index is missing: {db}")

    candidates = _cited_candidates(db, task_ref.strip())
    if not candidates:
        return []

    lifecycle = _vault_lifecycle()
    reason = (
        f"reported used by {task_ref.strip()}, which passed {review_class} review"
    )
    promoted: list[str] = []
    with _vault_root_env(root):
        for note_id in candidates:
            # `set_status` is a compare-and-swap, so the revision has to
            # come from the note itself. `get_note` is the wrong reader
            # here: its aperture/clearance gate governs DISCLOSURE to a
            # caller, and would refuse every `restricted` note -- which is
            # every note a bounty engagement writes. Promotion discloses
            # nothing; it reads and rewrites the note in place, exactly as
            # `set_status` does. Same reasoning `record_usage` used when it
            # dropped `require_note_visible` for `require_note_within_clearance`.
            try:
                _path, note = lifecycle._find_note(root, note_id)
            except lifecycle.NoteNotFound:
                # The index outran the notes directory. Nothing to promote.
                continue
            if note["status"] != "candidate":
                continue
            try:
                lifecycle.set_status(
                    note_id, "verified", reason, expected_revision=note["revision"]
                )
            except lifecycle.RevisionConflict:
                # Someone else wrote the note between the read and the
                # swap. Leave it candidate; the next passing review that
                # cites it promotes it.
                continue
            promoted.append(note_id)
    return promoted
