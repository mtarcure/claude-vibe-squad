"""Bounded Chrono active-task registry.

`active.json` holds only nonterminal tasks; terminal tasks move to an append-only
monthly archive. This replaces reading a 2.24MB / 853-record monolith into Chrono's
context at every session start when only ~17 records are actually live.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TASKS_DIR = Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "tasks"
TERMINAL = {"completed", "closed", "superseded", "blocked_final"}

# The registry the live board actually feeds (38 writers, updated continuously).
# `TASKS_DIR/active.json` above is the bounded registry from the 2026-07-24
# one-shot migration; nothing has fed it since, so it is NOT the capsule's source.
LIVE_REGISTRY = Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "active-tasks.json"

# Legacy _state/active-tasks.json vocabulary → the states that are still live.
LEGACY_NONTERMINAL = {"in-flight", "review-required", "blocked"}
_LEGACY_NEXT_ACTION = {
    "blocked": "unblock or rework",
    "review-required": "settle review",
    "in-flight": "await completion / verify",
}

# Every status the live registry is known to emit, partitioned exhaustively.
# Exhaustive is the point: an unclassified status must be loud (see
# `unclassified_statuses`), because the capsule's failure mode is silent
# omission, not a crash.
LIVE_STATUSES = frozenset(
    {"in_flight", "in-flight", "dispatched", "queued", "review-required", "pending"}
)
TERMINAL_STATUSES = frozenset(
    {"complete", "completed", "closed", "superseded", "cancelled", "blocked_final"}
)
# Owed work that is stalled awaiting a Chrono/operator action rather than moving
# through the pipeline: `blocked` entries are never promoted by the board and
# accumulate as canary residue (14 of the 17 entries in the 2026-07-24 capsule
# were exactly this). Deferred tasks are itemised in the capsule with their ID
# and next action (see `resume`) — the 0230 review rejected count-only
# declarations because a count line is not a task line, and an undeclared
# deferral is indistinguishable from a closed task.
#
# The last four are every remaining status registry_reconciler.py can write:
# needs_human (SETTLEABLE_STATUSES), needs_rework (reopen_task target),
# timed_out (swarm deadline), work-done-no-envelope (SETTLED_WITHOUT_ENVELOPE).
# All four are owed, unfinished work whose next action belongs to Chrono or the
# operator — nothing is executing, which is what separates DEFERRED from LIVE.
DEFERRED_STATUSES = frozenset(
    {
        "blocked",
        "needs_review",
        "needs_human",
        "needs_rework",
        "timed_out",
        "work-done-no-envelope",
    }
)
KNOWN_STATUSES = LIVE_STATUSES | TERMINAL_STATUSES | DEFERRED_STATUSES

_LIVE_NEXT_ACTION = {
    "in_flight": "await completion / verify",
    "in-flight": "await completion / verify",
    "dispatched": "await claim / verify launch",
    "queued": "await dispatch",
    "pending": "await dispatch",
    "review-required": "settle review",
}

# Deferred work is going nowhere on its own — each status names the action a
# resuming Chrono owes it (the capsule must be actionable without opening the
# registry).
_DEFERRED_NEXT_ACTION = {
    "blocked": "unblock or rework",
    "needs_review": "settle review",
    "needs_human": "operator decision",
    "needs_rework": "rework and redispatch",
    "timed_out": "investigate timeout, redispatch",
    "work-done-no-envelope": "verify work, reconcile envelope",
}


def _iter_registry(data):
    """Yield (task_id, record) from either registry shape.

    The live file has used both a dict keyed by task id and a list of records; a
    loader that understands only one silently returns nothing for the other.
    """
    items = data.items() if isinstance(data, dict) else ((None, r) for r in data)
    for key, record in items:
        if not isinstance(record, dict):
            continue
        task_id = key or record.get("id") or record.get("task_id")
        if task_id:
            yield task_id, record


def _read_registry(path=None):
    target = Path(path) if path else LIVE_REGISTRY
    if not target.exists():
        return None
    return json.loads(target.read_text())


def registry_view(path=None):
    """One consistent read of the live registry, fully partitioned.

    Returns {"live": [records], "deferred": [records],
    "unclassified": {status: count}}. The renderer and the unclassified detector
    share this single classification pass — the 0210 review reproduced exactly the
    drift where the detector existed but the write path never consulted it, so the
    partition is computed once and every consumer sees the same one.

    Bounded by construction: the registry holds ~1,300 records at ~4.7 MB, but
    only the live and deferred slices — the actionable sets — are materialized;
    terminal records are skipped and unclassified reduce to counts. The token
    bound at render time (`resume._render`) caps what either list can cost.
    Sorted (tasks by date-prefixed id, counts by status) so the derived capsule
    is byte-stable across runs when the board has not moved.
    """
    view = {"live": [], "deferred": [], "unclassified": {}}
    data = _read_registry(path)
    if data is None:
        return view
    for task_id, record in _iter_registry(data):
        status = record.get("status")
        if status in LIVE_STATUSES:
            view["live"].append(
                {
                    "id": task_id,
                    "state": status,
                    "specialist": record.get("specialist"),
                    "to_model": record.get("to_model"),
                    "next_action": _LIVE_NEXT_ACTION.get(status, "review"),
                }
            )
        elif status in DEFERRED_STATUSES:
            view["deferred"].append(
                {
                    "id": task_id,
                    "state": status,
                    "specialist": record.get("specialist"),
                    "to_model": record.get("to_model"),
                    "next_action": _DEFERRED_NEXT_ACTION.get(status, "review"),
                }
            )
        elif status not in TERMINAL_STATUSES:
            view["unclassified"][status] = view["unclassified"].get(status, 0) + 1
    view["live"].sort(key=lambda t: t["id"])
    view["deferred"].sort(key=lambda t: t["id"])
    return view


def unclassified_statuses(path=None):
    """Return statuses present in the live registry that KNOWN_STATUSES omits.

    A new board status is otherwise invisible: it is neither live nor terminal, so
    those tasks vanish from the capsule without any error.
    """
    return set(registry_view(path)["unclassified"])


def load_live_active(path=None):
    """Return only the LIVE records from the live board registry (see registry_view)."""
    return registry_view(path)["live"]
