"""Append-only Chrono decision-authority record.

Confirmed operator decisions are current AUTHORITY — kept deliberately separate from
chrono-vault, which holds quoted, potentially-stale learning. (Conflating the two would
demote an authoritative decision to untrusted-evidence status: a precedence bug.) The
active view is a fold of an immutable event log; a change appends a superseding event
rather than rewriting history. Only an explicit operator statement is `confirmed`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DECISIONS_FILE = (
    Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono" / "decisions.jsonl"
)


def record(statement, status, source_turn_ids, scope=None, supersedes=None):
    """Append an immutable decision event; return its decision_id.

    status is one of {"proposed", "confirmed", "superseded"}. supersedes is a list of
    prior decision_ids this event retires.
    """
    DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    did = "DEC-" + hashlib.sha256(
        (statement + ts + os.urandom(6).hex()).encode()
    ).hexdigest()[:12]
    event = {
        "decision_id": did,
        "status": status,
        "statement": statement,
        "scope": scope or [],
        "source_turn_ids": source_turn_ids,
        "supersedes": supersedes or [],
        "timestamp": ts,
    }
    with open(DECISIONS_FILE, "a") as fh:
        fh.write(json.dumps(event) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return did


def active_decisions():
    """Fold the journal to the currently-authoritative decisions.

    A decision is active if it is confirmed/proposed and not superseded by a later event.
    """
    if not DECISIONS_FILE.exists():
        return []
    events = [
        json.loads(line)
        for line in DECISIONS_FILE.read_text().splitlines()
        if line.strip()
    ]
    superseded = {sid for e in events for sid in e.get("supersedes", [])}
    latest = {}
    for e in events:
        if e["decision_id"] not in superseded and e["status"] in ("confirmed", "proposed"):
            latest[e["decision_id"]] = e
    return list(latest.values())
