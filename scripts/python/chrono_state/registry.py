"""Bounded Chrono active-task registry.

`active.json` holds only nonterminal tasks; terminal tasks move to an append-only
monthly archive. This replaces reading a 2.24MB / 853-record monolith into Chrono's
context at every session start when only ~17 records are actually live.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

TASKS_DIR = Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "tasks"
TERMINAL = {"completed", "closed", "superseded", "blocked_final"}

# Legacy _state/active-tasks.json vocabulary → the states that are still live.
LEGACY_NONTERMINAL = {"in-flight", "review-required", "blocked"}
_LEGACY_NEXT_ACTION = {
    "blocked": "unblock or rework",
    "review-required": "settle review",
    "in-flight": "await completion / verify",
}


def migrate_from_legacy(legacy_path):
    """Return only the nonterminal live tasks from the legacy active-tasks.json,
    translated to the bounded-registry record shape. Read-only on the legacy file."""
    data = json.loads(Path(legacy_path).read_text())
    items = data.items() if isinstance(data, dict) else [(r.get("id"), r) for r in data]
    active = []
    for tid, r in items:
        if not isinstance(r, dict) or r.get("status") not in LEGACY_NONTERMINAL:
            continue
        active.append(
            {
                "id": tid,
                "state": r["status"],
                "specialist": r.get("specialist"),
                "to_model": r.get("to_model"),
                "next_action": _LEGACY_NEXT_ACTION.get(r["status"], "review"),
            }
        )
    return active


def write_active(records):
    """Atomically write the new bounded active.json from a list of records."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", dir=TASKS_DIR, delete=False)
    json.dump(records, tmp, indent=2)
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp.close()
    os.replace(tmp.name, TASKS_DIR / "active.json")


def load_active():
    """Return only nonterminal task records from active.json (or [] if absent)."""
    f = TASKS_DIR / "active.json"
    if not f.exists():
        return []
    return [t for t in json.loads(f.read_text()) if t.get("state") not in TERMINAL]


def append_event(event):
    """Append a typed lifecycle event to events.jsonl (atomic, fsync'd)."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(TASKS_DIR / "events.jsonl", "a") as fh:
        fh.write(json.dumps(event) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def archive_terminal(now):
    """Move terminal records out of active.json into archive/YYYY-MM.jsonl.

    `now` is an ISO-8601 timestamp; its YYYY-MM prefix names the archive file.
    Returns the count moved. active.json is rewritten atomically (temp + rename).
    """
    f = TASKS_DIR / "active.json"
    if not f.exists():
        return 0
    rows = json.loads(f.read_text())
    keep = [t for t in rows if t.get("state") not in TERMINAL]
    gone = [t for t in rows if t.get("state") in TERMINAL]
    if not gone:
        return 0
    arc = TASKS_DIR / "archive"
    arc.mkdir(parents=True, exist_ok=True)
    with open(arc / f"{now[:7]}.jsonl", "a") as fh:
        for t in gone:
            fh.write(json.dumps(t) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp = tempfile.NamedTemporaryFile("w", dir=TASKS_DIR, delete=False)
    json.dump(keep, tmp)
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp.close()
    os.replace(tmp.name, f)
    return len(gone)
