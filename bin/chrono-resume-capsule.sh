#!/bin/bash
# Regenerate _state/chrono/resume.md from live state (decisions + board registry).
#
# Why an entry point rather than a push from the sweep: the capsule's only consumer is
# a session-start read, and a capsule regenerated AT read time cannot be stale by
# construction. A push-based writer is only as fresh as its last successful tick and
# goes quiet when the daemon is not running — which is exactly how the previous file
# reached ten days old without anyone noticing. Pull-at-read is the correctness
# property; wiring this into the reconcile sweep is an optimization on top of it, and
# safe to add because the write is atomic and idempotent.
#
# Pure stdlib — deliberately no `uv`, so session start never blocks on a toolchain.

set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"

usage() {
    cat <<'EOF'
Usage: bin/chrono-resume-capsule.sh [--session-id ID] [--latest-turn TEXT] [--stdout]

  --session-id ID    Compaction snapshot to recover the operator turn from (default: current).
  --latest-turn TEXT Operator instruction to record. Omitted: keep what the capsule already has.
  --stdout           Render to stdout and write nothing.
EOF
}

SESSION_ID="current"
LATEST_TURN=""
MODE="write"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-id) SESSION_ID="${2:-}"; shift 2 ;;
        --latest-turn) LATEST_TURN="${2:-}"; shift 2 ;;
        --stdout) MODE="stdout"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

PYTHONPATH="${VAULT_ROOT}/scripts/python" VAULT_ROOT="${VAULT_ROOT}" \
    python3 - "$SESSION_ID" "$LATEST_TURN" "$MODE" <<'PYEOF'
import sys

from chrono_state import compaction, resume

session_id, latest_turn, mode = sys.argv[1], sys.argv[2], sys.argv[3]

# An explicit --latest-turn wins; otherwise a real line already in the capsule is
# kept, and the compaction snapshot's turn only fills a vacuum (a missing capsule
# or the placeholder). No timestamps: mtime is not a causality signal, and the
# snapshot never competes with an existing line (resolve_operator_turn owns the
# rule).
turn = resume.resolve_operator_turn(
    latest_turn or None,
    compaction.recover(session_id).get("latest_turn"),
)

if mode == "stdout":
    sys.stdout.write(
        resume.render_capsule(session_id, turn or "(none recorded)") + "\n"
    )
else:
    dest = resume.write_capsule(session_id, turn)
    print(f"resume capsule regenerated: {dest}")
PYEOF
