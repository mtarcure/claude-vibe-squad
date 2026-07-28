"""Chrono compaction policy + atomic snapshot helpers.

These are the two modules the orphaned `compact-now` skill imported but that never
existed (`coordinator_compaction_policy` / `coordinator_compaction_snapshot`).

- should_compact() is the proactive-compaction predicate: fire before the hard ceiling,
  but never while work is in flight.
- snapshot()/recover() externalize/restore the load-bearing state around a native
  /compact, so compaction is recoverable rather than lossy.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SNAP_DIR = (
    Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono" / "compaction"
)


def should_compact(token_estimate, in_flight, ceiling=200000, threshold=0.72):
    """Return {compact, blockers, ...}. Compact only when over threshold AND clear."""
    blockers = list(in_flight or [])
    over = token_estimate >= ceiling * threshold
    return {
        "compact": bool(over and not blockers),
        "blockers": blockers,
        "token_estimate": token_estimate,
        "threshold_tokens": int(ceiling * threshold),
    }


def snapshot(session_id, state):
    """Atomically write the load-bearing state snapshot; return its path."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAP_DIR / f"{session_id}.json"
    tmp = tempfile.NamedTemporaryFile("w", dir=SNAP_DIR, delete=False)
    json.dump(state, tmp, indent=2)
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp.close()
    os.replace(tmp.name, dest)
    return dest


def recover(session_id):
    """Read back the snapshot for session_id ({} if none)."""
    f = SNAP_DIR / f"{session_id}.json"
    return json.loads(f.read_text()) if f.exists() else {}
