#!/usr/bin/env bash
# Cancel a running board spawn — the RELIABLE emergency stop.
#
# The supervisor starts the CLI in a NEW SESSION (start_new_session=True), so killing
# only the recorded pid orphans the CLI (it keeps running + burning). This signals the
# WHOLE process subtree (supervisor + CLI + any children), snapshotting the tree BEFORE
# signaling so reparenting can't hide a process, TERM -> grace -> KILL, then settles the
# attempt terminally (cancelled receipt + best-effort registry envelope) so it leaves the
# live board and the registry.
#
# Arg: a task_id, or the spawn's .log path.
set -u
# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
BOARD="$VAULT_ROOT/_state/board-dispatch"
ARG="${1:-}"
[ -n "$ARG" ] || { echo "usage: vs-cancel-spawn.sh <task_id|log_path>"; exit 2; }

case "$ARG" in
  *.log) DISPATCH="${ARG%.log}.dispatch.json" ;;
  *)     DISPATCH="$(ls -t "$BOARD/${ARG}".*.dispatch.json 2>/dev/null | head -1)" ;;
esac
[ -f "$DISPATCH" ] || { echo "no dispatch record for '$ARG'"; exit 1; }
BASE="${DISPATCH%.dispatch.json}"
read_j() { python3 -c "import json,sys;print(json.load(open('$DISPATCH')).get('$1',''))" 2>/dev/null; }
TASK="$(read_j task_id)"; PID="$(read_j pid)"; ATTEMPT="$(read_j attempt_id)"
[ -n "${PID:-}" ] || { echo "no pid recorded for $TASK"; exit 1; }

# snapshot the whole subtree first (root + all descendants), depth-first
collect() { local p="$1"; printf '%s\n' "$p"; local c; for c in $(pgrep -P "$p" 2>/dev/null); do collect "$c"; done; }
PIDS="$(collect "$PID" | sort -un)"
echo "cancelling $TASK — process tree: $(echo $PIDS | tr '\n' ' ')"

for p in $PIDS; do kill -TERM "$p" 2>/dev/null; done   # graceful first
for _ in 1 2 3 4 5; do
  alive=0; for p in $PIDS; do kill -0 "$p" 2>/dev/null && alive=1; done
  [ "$alive" = 0 ] && break
  sleep 1
done
for p in $PIDS; do kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null; done  # force
survivors=0; for p in $PIDS; do kill -0 "$p" 2>/dev/null && survivors=$((survivors+1)); done
echo "  terminated (survivors: $survivors)"

# settle terminally so the dashboard moves it to history immediately
python3 - "$BASE.receipt.json" "$TASK" "$ATTEMPT" <<'PY'
import json, sys, time
json.dump({"task_id": sys.argv[2], "attempt_id": sys.argv[3], "status": "blocked",
           "failure_class": "cancelled", "reason": "cancelled by operator",
           "response_status": "cancelled", "returncode": None,
           "cancelled_at": int(time.time())}, open(sys.argv[1], "w"))
PY
echo "  settled as cancelled (receipt written)"

# best-effort registry reconcile: write a cancel envelope in the source mailbox
NS="$(python3 -c "import json,re;tp=json.load(open('${BASE}.context.json')).get('task_prompt','');m=re.search(r'Source mailbox namespace: .([a-z-]+).',tp);print(m.group(1) if m else '')" 2>/dev/null)"
if [ -n "$NS" ] && [ -d "$VAULT_ROOT/departments/$NS/outbox" ]; then
  cat > "$VAULT_ROOT/departments/$NS/outbox/${TASK}-response.md" <<EOF
---
id: ${TASK}-response
in_response_to: ${TASK}
from: chrono
to: chrono
type: RESULT
status: blocked
---

Cancelled by operator via the dashboard Stop control. The spawn's process tree was terminated (TERM then KILL) and the attempt settled as cancelled.
EOF
  echo "  cancel envelope → departments/$NS/outbox (registry reconcile)"
fi
