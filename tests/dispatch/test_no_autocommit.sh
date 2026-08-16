#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/send-task-no-autocommit.XXXXXX")"
FIXTURE_ROOT="${FIXTURE_PARENT}/repo"
trap 'rm -rf "${FIXTURE_PARENT}"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_unchanged_and_untracked() {
    local expected_head="$1"
    local phase="$2"
    local actual_head status

    actual_head="$(git -C "${FIXTURE_ROOT}" rev-parse HEAD)"
    [[ "${actual_head}" == "${expected_head}" ]] \
        || fail "${phase}: dispatcher created commit ${actual_head} (expected ${expected_head})"

    status="$(git -C "${FIXTURE_ROOT}" status --porcelain -- x.untracked-sentinel)"
    [[ "${status}" == "?? x.untracked-sentinel" ]] \
        || fail "${phase}: x.untracked-sentinel was staged or committed (status: ${status:-clean})"

    git -C "${FIXTURE_ROOT}" diff --cached --quiet \
        || fail "${phase}: dispatcher staged repository changes"

    if git -C "${FIXTURE_ROOT}" diff --quiet -- tracked.txt; then
        fail "${phase}: dispatcher committed or discarded the tracked sentinel change"
    fi
}

git clone -q --shared --no-hardlinks "${REPO_ROOT}" "${FIXTURE_ROOT}"
mkdir -p "${FIXTURE_ROOT}/home" "${FIXTURE_ROOT}/_state"

# Exercise the real dispatcher and its real repo-root dependencies, but stop the
# fixture at its external process boundary. The stub accepts the detached-launch
# contract long enough for send-task.sh to capture its process identity, without
# launching a model CLI or touching anything outside this temporary clone.
cat > "${FIXTURE_ROOT}/bin/board-supervisor.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "detached-launch" ]] || exit 64
sleep 2
EOF
chmod +x "${FIXTURE_ROOT}/bin/board-supervisor.sh"

# Host-capacity telemetry is outside this regression and is unavailable in some
# test sandboxes. Preserve the candidate-vector binding while admitting this one
# hermetic fixture.
cat > "${FIXTURE_ROOT}/scripts/python/host_admission.py" <<'EOF'
#!/usr/bin/env python3
import json
import sys

index = sys.argv.index("--vector-sha256")
vector_sha256 = sys.argv[index + 1]
print(
    json.dumps(
        {
            "action": "admit",
            "admitted": True,
            "candidate_vector_sha256": vector_sha256,
        }
    )
)
EOF

# The production observer uses /bin/ps on macOS; this sandbox denies that one
# syscall. Keep the fixture's PID/PGID identity fence while replacing only its
# start-token probe.
python3 - "${FIXTURE_ROOT}/scripts/python/board_process_truth.py" <<'PYEOF'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
start = source.index("def observe_process(pid):")
end = source.index("\ndef timestamp_epoch", start)
replacement = '''def observe_process(pid):
    try:
        pid, pgid = int(pid), os.getpgid(int(pid))
    except (TypeError, ValueError, OSError):
        return None
    return {
        "pid": pid,
        "pgid": pgid,
        "process_start_token": f"fixture:{pid}",
        "argv_sha256": hashlib.sha256(str(pid).encode("ascii")).hexdigest(),
    }

'''
path.write_text(source[:start] + replacement + source[end + 1 :], encoding="utf-8")
PYEOF

cat > "${FIXTURE_ROOT}/task.md" <<'EOF'
---
id: TASK-2099-01-01-0000-test
run_id: none
to_model: claude
specialist: backend-engineer
source_namespace: coding
compatibility_namespace: coding
review_model: none
mandatory_review: false
write_scope: [departments/coding/outbox/TASK-2099-01-01-0000-test-response.md]
return_artifact: departments/coding/outbox/TASK-2099-01-01-0000-test-response.md
parallel_safe: true
direct_lane_work_allowed: false
mode: project
result_type: normal
memory_aperture: none
capability: none
---

# Dispatch regression fixture
EOF

echo "baseline" > "${FIXTURE_ROOT}/tracked.txt"

git -C "${FIXTURE_ROOT}" config user.name "Dispatch Test"
git -C "${FIXTURE_ROOT}" config user.email "dispatch-test@example.invalid"
git -C "${FIXTURE_ROOT}" config commit.gpgsign false
git -C "${FIXTURE_ROOT}" config core.hooksPath /dev/null
git -C "${FIXTURE_ROOT}" add .
git -C "${FIXTURE_ROOT}" commit -qm "fixture baseline"

echo "dirty" >> "${FIXTURE_ROOT}/tracked.txt"
touch "${FIXTURE_ROOT}/x.untracked-sentinel"
baseline_head="$(git -C "${FIXTURE_ROOT}" rev-parse HEAD)"

set +e
dry_run_output="$(
    HOME="${FIXTURE_ROOT}/home" VAULT_ROOT="${FIXTURE_ROOT}" \
        bash "${FIXTURE_ROOT}/bin/send-task.sh" "${FIXTURE_ROOT}/task.md" --dry-run 2>&1
)"
dry_run_rc=$?
set -e

[[ "${dry_run_rc}" -eq 2 ]] \
    || fail "dry-run returned ${dry_run_rc}, expected 2; output: ${dry_run_output}"
[[ "${dry_run_output}" == *"[DRY RUN] Would validate"* ]] \
    || fail "dry-run did not describe the non-snapshot dispatch path"
[[ "${dry_run_output}" != *"snapshot"* ]] \
    || fail "dry-run still advertises a Git snapshot"
assert_unchanged_and_untracked "${baseline_head}" "dry-run"

HOME="${FIXTURE_ROOT}/home" VAULT_ROOT="${FIXTURE_ROOT}" \
    env -u CHRONO_VAULT_CONTEXT -u CHRONO_VAULT_AUDIT_DIR \
    bash "${FIXTURE_ROOT}/bin/send-task.sh" "${FIXTURE_ROOT}/task.md" >/dev/null

# The stub is a detached session leader by contract. Let its bounded sleep end
# before removing the fixture so this regression leaves no transient process.
sleep 3

assert_unchanged_and_untracked "${baseline_head}" "dispatch"

echo "PASS: dispatch leaves unrelated untracked files and HEAD unchanged"
