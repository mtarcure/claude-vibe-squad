"""Chrono compaction policy + atomic snapshot helpers.

These are the two modules the orphaned `compact-now` skill imported but that never
existed (`coordinator_compaction_policy` / `coordinator_compaction_snapshot`).

- snapshot()/recover() externalize/restore the load-bearing state around a native
  /compact, so compaction is recoverable rather than lossy.

Removed 2026-08-31: should_compact(), a nine-line predicate computing
`token_estimate >= ceiling * threshold and not in_flight`. It was deleted rather
than repaired because all three of its parts were broken and none was worth
fixing:

- No production caller. Only its own tests invoked it; the sole non-test importer
  of this module (bin/chrono-resume-capsule.sh:47) calls recover(), never it.
- No obtainable input. There is no token-counting code anywhere in the repo, so
  nothing could compute `token_estimate`. Per shared/lifecycle.md rule 9 there are
  deliberately no per-model token counters, only proxy signals.
- Wrong number. Its `ceiling=200000, threshold=0.72` contradicted
  shared/lifecycle.md's "60% of model max", and the hardcoded ceiling tracked no
  actual model.

The rule it encoded now lives once, in prose, in shared/lifecycle.md § 8 — where
Chrono reads and applies it by judgment. This is a markdown-first repo; a
threshold comparison is not machinery worth keeping. The live-work check it also
performed is a real data lookup and survives in the compact-now skill via
registry_view().
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SNAP_DIR = (
    Path(os.environ.get("VAULT_ROOT", ".")) / "_state" / "chrono" / "compaction"
)


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
