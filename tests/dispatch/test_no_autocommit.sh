#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SUBJECT="${REPO_ROOT}/bin/send-task.sh"
FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/send-task-no-autocommit.XXXXXX")"
trap 'rm -rf "${FIXTURE_ROOT}"' EXIT

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

    status="$(git -C "${FIXTURE_ROOT}" status --porcelain -- x.tmp)"
    [[ "${status}" == "?? x.tmp" ]] \
        || fail "${phase}: x.tmp was staged or committed (status: ${status:-clean})"

    git -C "${FIXTURE_ROOT}" diff --cached --quiet \
        || fail "${phase}: dispatcher staged repository changes"

    if git -C "${FIXTURE_ROOT}" diff --quiet -- tracked.txt; then
        fail "${phase}: dispatcher committed or discarded the tracked sentinel change"
    fi
}

mkdir -p "${FIXTURE_ROOT}/bin" "${FIXTURE_ROOT}/home" "${FIXTURE_ROOT}/_state"

cp "${SUBJECT}" "${FIXTURE_ROOT}/bin/send-task.sh"
chmod +x "${FIXTURE_ROOT}/bin/send-task.sh"

cat > "${FIXTURE_ROOT}/task.md" <<'EOF'
---
id: TASK-2099-01-01-0000-test
run_id: none
to_model: gpt-codex
specialist: none
source_namespace: coding
compatibility_namespace: coding
review_model: none
mandatory_review: false
write_scope: []
return_artifact: departments/coding/outbox/TASK-2099-01-01-0000-test-response.md
parallel_safe: true
direct_lane_work_allowed: true
---

# Dispatch regression fixture
EOF

echo "baseline" > "${FIXTURE_ROOT}/tracked.txt"

git -C "${FIXTURE_ROOT}" init -q
git -C "${FIXTURE_ROOT}" config user.name "Dispatch Test"
git -C "${FIXTURE_ROOT}" config user.email "dispatch-test@example.invalid"
git -C "${FIXTURE_ROOT}" config commit.gpgsign false
git -C "${FIXTURE_ROOT}" config core.hooksPath /dev/null
git -C "${FIXTURE_ROOT}" add .
git -C "${FIXTURE_ROOT}" commit -qm "fixture baseline"

echo "dirty" >> "${FIXTURE_ROOT}/tracked.txt"
touch "${FIXTURE_ROOT}/x.tmp"
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
    bash "${FIXTURE_ROOT}/bin/send-task.sh" "${FIXTURE_ROOT}/task.md" >/dev/null

assert_unchanged_and_untracked "${baseline_head}" "dispatch"

echo "PASS: dispatch leaves unrelated untracked files and HEAD unchanged"
