"""Demotion queue: `incorrect` / `not_useful` usage outcomes flag, never invalidate.

Spec §8. `incorrect` is a 5-sample signal today, nothing re-validates it, and
this design deliberately adds no time-based decay (spec §9) -- so setting
`invalidated` from a single worker's judgment would be terminal and
unreviewable, while *promotion* requires a passed review. That asymmetry is
backwards, so demotion signals land here instead: an append-only flag queue
that a human (Chrono, at a session boundary -- see `shared/curation-protocol.md`)
reads and decides on. Nothing in this module ever changes a note's status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import jsonl

QUEUE_RELATIVE_PATH = Path("_state") / "curation-queue.jsonl"


def queue_path(repo_root: Path) -> Path:
    return Path(repo_root) / QUEUE_RELATIVE_PATH


def flag_for_curation(
    note_id: str,
    reason: str,
    source_task: str | None,
    repo_root: Path,
) -> None:
    """Append one demotion signal to `<repo_root>/_state/curation-queue.jsonl`.

    Named `repo_root`, not `vault_root`, because this queue is a repo artifact
    -- process/review state -- and must never land in the private Obsidian
    vault. Each call appends exactly one line; repeated flags for the same
    `note_id` accumulate as separate rows so the reviewer sees every signal.

    `ts` is not decoration. This queue has no acknowledgement, no cursor and
    no archive -- `curation-protocol.md` §3 says a dismissed flag "stays in
    the queue's history" -- so without a timestamp every session boundary
    re-renders every flag ever recorded with no way to tell a new one from
    one seen ten sessions ago. §5 claims the degradation mode is "a growing
    queue and a correspondingly noisier ranking", but an undifferentiated
    queue does not degrade, it becomes unreadable, and an unreadable queue is
    an ignored queue -- which is how curation stalled in the first place.
    With `ts`, `bin/curation-review.sh --since` makes the claimed
    degradation mode the real one.

    The append goes through `jsonl.append_line`, the single home for this
    operation. This function previously used a plain `open("a")` with the
    process umask and no lock, for the same job `autocapture._spool_episodic`
    did carefully, written days apart.
    """
    row = {
        "note_id": note_id,
        "reason": reason,
        "source_task": source_task,
        "ts": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    jsonl.append_line(queue_path(repo_root), row)
