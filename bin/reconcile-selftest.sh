#!/bin/bash
# Safe fixture-only proof for centralized task registry reconciliation.

set -euo pipefail

VAULT_ROOT_UNDER_TEST="${VAULT_ROOT_UNDER_TEST:-${HOME}/Obsidian-Claude-Vibe-Squad}"
RECONCILER="${VAULT_ROOT_UNDER_TEST}/scripts/python/registry_reconciler.py"
FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/reconcile-selftest.XXXXXX")"
STATE_DIR="${FIXTURE_ROOT}/_state"
TMUX_LOG="${FIXTURE_ROOT}/tmux.log"
FAKE_TMUX="${FIXTURE_ROOT}/tmux-selftest"

mkdir -p \
    "${STATE_DIR}/artifacts" \
    "${FIXTURE_ROOT}/departments/security/outbox" \
    "${FIXTURE_ROOT}/departments/security/archive" \
    "${FIXTURE_ROOT}/departments/coding/outbox" \
    "${FIXTURE_ROOT}/departments/coding/archive"

cat > "${FAKE_TMUX}" <<'TMUX_EOF'
#!/bin/bash
set -eu
case "${1:-}" in
    has-session)
        exit 0
        ;;
    capture-pane)
        if [[ "$*" == *":active-lane"* ]]; then
            printf 'Working (esc to interrupt)\n'
        else
            printf '❯\n'
        fi
        ;;
    send-keys)
        printf '%s\n' "$*" >> "${TMUX_LOG}"
        ;;
    *)
        exit 0
        ;;
esac
TMUX_EOF
chmod +x "${FAKE_TMUX}"

cat > "${STATE_DIR}/active-tasks.json" <<'JSON_EOF'
{
  "TASK-2099-01-01-0001-needs": {
    "compatibility_namespace": "security",
    "to_model": "gpt-codex",
    "dispatched_at": "2020-01-01T00:00:00+00:00",
    "status": "in-flight"
  },
  "TASK-2099-01-01-0002-mismatch": {
    "compatibility_namespace": "security",
    "to_model": "gpt-codex",
    "dispatched_at": "2020-01-01T00:00:00+00:00",
    "status": "in-flight"
  },
  "TASK-2099-01-01-0003-no-envelope": {
    "compatibility_namespace": "coding",
    "to_model": "gpt-codex",
    "return_artifact": "_state/artifacts/no-envelope.md",
    "dispatched_at": "2020-01-01T00:00:00+00:00",
    "status": "in-flight"
  },
  "TASK-2099-01-01-0004-complete": {
    "compatibility_namespace": "coding",
    "to_model": "gpt-codex",
    "dispatched_at": "2020-01-01T00:00:00+00:00",
    "status": "in-flight"
  }
}
JSON_EOF

cat > "${FIXTURE_ROOT}/departments/security/outbox/TASK-2099-01-01-0001-needs-response.md" <<'RESPONSE_EOF'
---
status: needs_review
---
Needs mandatory reviewer confirmation.
RESPONSE_EOF

# Dispatched in security, deliberately landed in coding.
cat > "${FIXTURE_ROOT}/departments/coding/outbox/TASK-2099-01-01-0002-mismatch-response.md" <<'RESPONSE_EOF'
---
status: blocked
---
Matched across namespaces by task id.
RESPONSE_EOF

cat > "${FIXTURE_ROOT}/departments/coding/outbox/TASK-2099-01-01-0004-complete-response.md" <<'RESPONSE_EOF'
---
status: completed
---
Historical completed response still closes to complete.
RESPONSE_EOF

printf '%s\n' '# Return artifact exists without an envelope' > "${STATE_DIR}/artifacts/no-envelope.md"

# Reproduce the review blocker: a reused artifact predates the new dispatch,
# is much older than grace, and the lane is still actively working.
printf '%s\n' '# Stale artifact from an earlier dispatch' > "${STATE_DIR}/artifacts/stale-active.md"
python3 - "${STATE_DIR}/active-tasks.json" "${STATE_DIR}/artifacts/stale-active.md" <<'PY_EOF'
import json
import os
import sys
from datetime import datetime, timedelta, timezone

registry_path, artifact_path = sys.argv[1:]
registry = json.load(open(registry_path, encoding="utf-8"))
dispatched = datetime.now(timezone.utc)
registry["TASK-2099-01-01-0005-stale-active"] = {
    "compatibility_namespace": "coding",
    "to_model": "active-lane",
    "return_artifact": "_state/artifacts/stale-active.md",
    "dispatched_at": dispatched.isoformat(),
    "write_scope": ["shared/protected-scope"],
    "status": "in-flight",
}
with open(registry_path, "w", encoding="utf-8") as handle:
    json.dump(registry, handle, indent=2)
old = (dispatched - timedelta(days=1)).timestamp()
os.utime(artifact_path, (old, old))
PY_EOF

export TMUX_LOG
FIRST_OUTPUT="$(
    VAULT_ROOT="${FIXTURE_ROOT}" \
    STATE_DIR="${STATE_DIR}" \
    TMUX_BIN="${FAKE_TMUX}" \
    SQUAD_SESSION="selftest" \
    RESPONSE_MIN_AGE_SECONDS=0 \
    NO_ENVELOPE_GRACE_SECONDS=3600 \
    python3 "${RECONCILER}"
)"
printf '%s\n' "${FIRST_OUTPUT}"

python3 - "${STATE_DIR}/active-tasks.json" <<'PY_EOF'
import json
import sys

registry = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {
    "TASK-2099-01-01-0001-needs": "needs_review",
    "TASK-2099-01-01-0002-mismatch": "blocked",
    "TASK-2099-01-01-0003-no-envelope": "work-done-no-envelope",
    "TASK-2099-01-01-0004-complete": "complete",
}
for task_id, status in expected.items():
    actual = registry[task_id]["status"]
    assert actual == status, f"{task_id}: expected {status}, got {actual}"
    assert registry[task_id].get("reconciled_at"), f"{task_id}: missing reconciled_at"
for task_id in (expected.keys() - {"TASK-2099-01-01-0003-no-envelope"}):
    assert registry[task_id].get("completed_at"), f"{task_id}: missing completed_at"
assert registry["TASK-2099-01-01-0002-mismatch"]["response_path"].startswith(
    "departments/coding/outbox/"
)
print("PASS registry statuses: needs_review / blocked cross-namespace / work-done-no-envelope / complete")

stale = registry["TASK-2099-01-01-0005-stale-active"]
assert stale["status"] == "in-flight"
new_scope = "shared/protected-scope/child"
conflicts = [
    active_id
    for active_id, active in registry.items()
    if active.get("status") == "in-flight"
    for active_scope in active.get("write_scope", [])
    if (
        new_scope == active_scope
        or new_scope.startswith(active_scope.rstrip("/") + "/")
        or active_scope.startswith(new_scope.rstrip("/") + "/")
    )
]
assert "TASK-2099-01-01-0005-stale-active" in conflicts
print("PASS active lane + stale pre-dispatch artifact stays in-flight and retains write_scope blocking")
PY_EOF

grep -q '| needs_review | security/TASK-2099-01-01-0001-needs |' "${STATE_DIR}/chrono-queue.md"
grep -q '| work-done-no-envelope | coding/TASK-2099-01-01-0003-no-envelope |' "${STATE_DIR}/chrono-queue.md"
grep -q -- '-t selftest:chrono' "${TMUX_LOG}"
printf '%s\n' "PASS chrono queue audit and named-window nudge"

NUDGE_LINES_BEFORE="$(wc -l < "${TMUX_LOG}" | tr -d ' ')"
SECOND_OUTPUT="$(
    VAULT_ROOT="${FIXTURE_ROOT}" \
    STATE_DIR="${STATE_DIR}" \
    TMUX_BIN="${FAKE_TMUX}" \
    SQUAD_SESSION="selftest" \
    RESPONSE_MIN_AGE_SECONDS=0 \
    NO_ENVELOPE_GRACE_SECONDS=3600 \
    python3 "${RECONCILER}"
)"
printf '%s\n' "${SECOND_OUTPUT}"
grep -q 'changes=0' <<<"${SECOND_OUTPUT}"
NUDGE_LINES_AFTER="$(wc -l < "${TMUX_LOG}" | tr -d ' ')"
[[ "${NUDGE_LINES_BEFORE}" == "${NUDGE_LINES_AFTER}" ]]
printf '%s\n' "PASS repeated run is idempotent (no registry change or duplicate nudge)"

# A real envelope arriving after the provisional no-envelope settlement must
# replace that provisional state with the truthful response status.
cat > "${FIXTURE_ROOT}/departments/coding/outbox/TASK-2099-01-01-0003-no-envelope-response.md" <<'RESPONSE_EOF'
---
status: needs_review
---
Late envelope supersedes the provisional work-done-no-envelope state.
RESPONSE_EOF
THIRD_OUTPUT="$(
    VAULT_ROOT="${FIXTURE_ROOT}" \
    STATE_DIR="${STATE_DIR}" \
    TMUX_BIN="${FAKE_TMUX}" \
    SQUAD_SESSION="selftest" \
    RESPONSE_MIN_AGE_SECONDS=0 \
    NO_ENVELOPE_GRACE_SECONDS=3600 \
    python3 "${RECONCILER}"
)"
printf '%s\n' "${THIRD_OUTPUT}"
grep -q 'changes=1' <<<"${THIRD_OUTPUT}"
python3 - "${STATE_DIR}/active-tasks.json" <<'PY_EOF'
import json
import sys

registry = json.load(open(sys.argv[1], encoding="utf-8"))
entry = registry["TASK-2099-01-01-0003-no-envelope"]
assert entry["status"] == "needs_review"
assert entry["prior_missing_envelope_status"] == "work-done-no-envelope"
assert entry.get("completed_at")
print("PASS late envelope supersedes provisional work-done-no-envelope status")
PY_EOF

# Prove dispatch registration waits on the same flock and preserves a
# concurrent writer's update rather than replacing its stale snapshot.
LOCK_READY="${FIXTURE_ROOT}/registry-lock-ready"
python3 - "${STATE_DIR}/active-tasks.json" "${STATE_DIR}/active-tasks.json.lock" "${LOCK_READY}" <<'PY_EOF' &
import fcntl
import json
import os
import sys
import time

registry_path, lock_path, ready_path = sys.argv[1:]
with open(lock_path, "w", encoding="utf-8") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    with open(ready_path, "w", encoding="utf-8") as ready:
        ready.write("locked\n")
    registry = json.load(open(registry_path, encoding="utf-8"))
    time.sleep(0.5)
    registry["LOCK-HOLDER-UPDATE"] = {"status": "complete"}
    tmp = f"{registry_path}.holder.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, registry_path)
PY_EOF
LOCK_HOLDER_PID=$!
for _ in {1..100}; do
    [[ -f "${LOCK_READY}" ]] && break
    sleep 0.02
done
[[ -f "${LOCK_READY}" ]]
REGISTER_OUTPUT="$(
    VAULT_ROOT="${FIXTURE_ROOT}" \
    STATE_DIR="${STATE_DIR}" \
    python3 "${RECONCILER}" \
        --register-task "TASK-2099-01-01-0006-registered" \
        --entry-json '{"status":"in-flight","write_scope":["shared/new-scope"]}'
)"
wait "${LOCK_HOLDER_PID}"
printf '%s\n' "${REGISTER_OUTPUT}"
python3 - "${STATE_DIR}/active-tasks.json" <<'PY_EOF'
import json
import sys

registry = json.load(open(sys.argv[1], encoding="utf-8"))
assert registry["LOCK-HOLDER-UPDATE"]["status"] == "complete"
assert registry["TASK-2099-01-01-0006-registered"]["status"] == "in-flight"
print("PASS shared flock preserves concurrent reconcile and dispatch registration updates")
PY_EOF
printf '%s\n' "SELFTEST PASS"
printf '%s\n' "Fixture retained at: ${FIXTURE_ROOT}"
