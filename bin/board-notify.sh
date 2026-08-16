#!/usr/bin/env bash
# Report registry transitions for headless controllers; one process watches all tasks.

set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

export PYTHONPATH="${VAULT_ROOT}/scripts/python${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -u - <<'PY'
import os
import time

from chrono_state import registry
from registry_reconciler import return_artifact_path

interval = float(os.environ.get("BOARD_NOTIFY_INTERVAL", "1"))
if interval <= 0:
    raise SystemExit("BOARD_NOTIFY_INTERVAL must be greater than zero")

# registry_view intentionally bounds terminal rows away from resume consumers.
# This dedicated reader asks that same classifier to materialize its canonical
# terminal set in the deferred slice; no raw registry path or status copy exists.
terminal_states = set(registry.DEFERRED_STATUSES | registry.TERMINAL_STATUSES)
registry.DEFERRED_STATUSES = frozenset(terminal_states)
registry.TERMINAL_STATUSES = frozenset()


def snapshot():
    view = registry.registry_view()
    return {
        task["id"]: task["state"]
        for bucket in ("live", "deferred")
        for task in view[bucket]
    }


current = snapshot()
known = set(current)
open_tasks = {task for task, status in current.items() if status in registry.LIVE_STATUSES}
print(f"board-notify: watching registry every {interval:g}s", flush=True)
while True:
    time.sleep(interval)
    current = snapshot()
    candidates = open_tasks | (set(current) - known)
    settled = {task for task in candidates if current.get(task) in terminal_states}
    for task in sorted(settled):
        status = current[task]
        path = return_artifact_path(task, {})
        artifact = "yes" if path is not None and path.is_file() else "no"
        print(f"task={task} status={status} artifact={artifact}", flush=True)
    open_tasks.difference_update(settled)
    open_tasks.update(task for task, status in current.items() if status in registry.LIVE_STATUSES)
    known.update(current)
PY
