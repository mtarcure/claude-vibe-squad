#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Existing capability-home/tool-registry validation.
python3 "$repo_root/scripts/python/validate_capabilities.py" --root "$repo_root" "$@"

# Skill-wiring integrity on the PROVEN claude load path (repo-root .claude/skills/).
# Shares "$@" so `--self-test` from bin/test exercises both validators; each ignores the
# other's unknown flags. Runs after the line above so a failure here also fails the gate.
python3 "$repo_root/scripts/python/validate_skill_wiring.py" --root "$repo_root" "$@"
