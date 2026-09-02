#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

self_test_requested=false
for argument in "$@"; do
  if [[ "$argument" == "--self-test" ]]; then
    self_test_requested=true
  fi
done

# Existing capability-home/tool-registry validation. The outer wrapper attests
# that --self-test actually emitted its typed result; a silent zero exit (for
# example, main() short-circuited to return 0) is not evidence that it ran.
if $self_test_requested; then
  if capability_output="$(
    python3 "$repo_root/scripts/python/validate_capabilities.py" --root "$repo_root" "$@" 2>&1
  )"; then
    printf '%s\n' "$capability_output"
  else
    capability_status=$?
    printf '%s\n' "$capability_output"
    exit "$capability_status"
  fi
  if ! python3 -c '
import json
import sys

attested = False
for line in sys.stdin:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        continue
    if record.get("type") == "self-test" and record.get("status") == "pass":
        attested = True
    if (
        record.get("type") == "registry-degradation"
        and record.get("status") == "not-applicable"
        and record.get("code") == "registry-not-published"
    ):
        attested = True
raise SystemExit(0 if attested else 1)
' <<<"$capability_output"; then
    printf '%s\n' \
      'FAIL[capability-self-test] missing passing self-test attestation' >&2
    exit 1
  fi
else
  python3 "$repo_root/scripts/python/validate_capabilities.py" --root "$repo_root" "$@"
fi

# Skill-wiring integrity on the PROVEN claude load path (repo-root .claude/skills/).
# Shares "$@" so `--self-test` from bin/test exercises both validators; each ignores the
# other's unknown flags. Runs after the line above so a failure here also fails the gate.
if $self_test_requested; then
  if skill_output="$(
    python3 "$repo_root/scripts/python/validate_skill_wiring.py" --root "$repo_root" "$@" 2>&1
  )"; then
    printf '%s\n' "$skill_output"
  else
    skill_status=$?
    printf '%s\n' "$skill_output"
    exit "$skill_status"
  fi
  if [[ "$skill_output" != *"self-test PASSED ("* ]]; then
    printf '%s\n' \
      'FAIL[capability-self-test] missing skill-wiring self-test attestation' >&2
    exit 1
  fi
else
  python3 "$repo_root/scripts/python/validate_skill_wiring.py" --root "$repo_root" "$@"
fi
