#!/usr/bin/env bash
# One-time migration: partition chrono-queue.md by whether the task is still
# open. Open lines stay; everything else moves to chrono-queue-handled.md.
# Idempotent -- re-running with the same registry is a no-op.
set -uo pipefail

# shellcheck source-path=SCRIPTDIR source=../shared/repo-root.sh disable=SC1091
source "$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")/.." && pwd -P)/shared/repo-root.sh"
: "${VAULT_ROOT:?VAULT_ROOT must be set}"
STATE="${VAULT_ROOT}/_state"
QUEUE="${STATE}/chrono-queue.md"
HANDLED="${STATE}/chrono-queue-handled.md"
REGISTRY="${STATE}/active-tasks.json"
LOCKDIR="${QUEUE}.lockdir"
[[ -f "$QUEUE" ]] || { echo "no queue at ${QUEUE}; nothing to do"; exit 0; }

# Same lockdir protocol as every other chrono-queue.md writer
# (registry_reconciler.py's lockdir(), bin/outbox-watcher.sh's
# append_chrono_queue): write PID to owner.pid, wait while the owner is
# alive, break only if the owner is dead or the lock is stale (>300s),
# release by removing owner.pid then the lockdir. Without this the backfill
# is a second, uncoordinated writer -- a concurrent settlement's append can
# land between this script's read and its whole-file rewrite and be
# silently discarded, the exact class of loss this plan exists to kill.
LOCK_ACQUIRED=0
release_lock() {
    if [[ "$LOCK_ACQUIRED" == 1 ]]; then
        rm -f "${LOCKDIR}/owner.pid"
        rmdir "$LOCKDIR" 2>/dev/null || true
        LOCK_ACQUIRED=0
    fi
}
trap release_lock EXIT HUP INT TERM

# Overall wall-clock bound on the wait below. This does NOT change the
# dead/absent-owner behavior directly above/below (a confirmed-dead owner, or
# an owner.pid stale past the 300s mtime rule, is still broken immediately --
# no timeout wait needed for either). It bounds only the case that used to
# spin forever: a CONFIRMED-LIVE owner that never releases. A recent fix
# faithfully ported the unbounded spin from registry_reconciler.py's
# lockdir() into this script, so this same bound is added to both in one
# change (Plan B Task 2) rather than fixing one writer and leaving the other
# two able to strand the queue.
LOCK_TIMEOUT_SECONDS="${CHRONO_QUEUE_LOCK_TIMEOUT:-60}"
LOCK_WAIT_START="$(date +%s)"
# Every path through this loop body reaches the timeout check at the bottom --
# there is deliberately no `continue` past it. Both lock-breaking branches used
# to `continue` on the assumption that the break had worked, jumping over BOTH
# the timeout check and the sleep. When the break cannot succeed (parent
# directory unwritable or read-only, lock directory owned by another user, a
# leftover file inside it, a full disk) that was an unbounded busy spin at 100%
# CPU with no bound at all -- a hang where this script's whole point is to fail
# loudly. Same correction, same shape, as bin/launch-squad.sh's
# acquire_dir_lock(); registry_reconciler.py's _lockdir_wait_or_timeout()
# already had it.
while ! mkdir "$LOCKDIR" 2>/dev/null; do
    broke_lock=0
    owner="$(cat "${LOCKDIR}/owner.pid" 2>/dev/null || true)"
    if [[ "$owner" =~ ^[0-9]+$ ]]; then
        if ! kill -0 "$owner" 2>/dev/null; then
            rm -f "${LOCKDIR}/owner.pid" 2>/dev/null || true
            rmdir "$LOCKDIR" 2>/dev/null && broke_lock=1
        fi
    else
        mtime="$(stat -c %Y "$LOCKDIR" 2>/dev/null || stat -f %m "$LOCKDIR" 2>/dev/null || echo 0)"
        age=$(( $(date +%s) - mtime ))
        if [[ "$age" -gt 300 ]]; then
            rm -f "${LOCKDIR}/owner.pid" 2>/dev/null || true
            rmdir "$LOCKDIR" 2>/dev/null && broke_lock=1
        fi
    fi
    now="$(date +%s)"
    waited=$((now - LOCK_WAIT_START))
    if [[ "$waited" -ge "$LOCK_TIMEOUT_SECONDS" ]]; then
        # A lock directory that does not exist was never "held" -- mkdir
        # itself is failing, and naming a phantom owner would send the
        # operator hunting a process that is not there.
        if [[ ! -d "$LOCKDIR" ]]; then
            echo "ERROR: ${LOCKDIR} could not be CREATED after ${waited}s: mkdir keeps failing and the directory does not exist." >&2
            echo "This is not a held lock. Check that $(dirname -- "$LOCKDIR") is writable by this user and that the disk is not full." >&2
            exit 1
        fi
        mtime="$(stat -c %Y "$LOCKDIR" 2>/dev/null || stat -f %m "$LOCKDIR" 2>/dev/null || echo "$now")"
        if [[ "$owner" =~ ^[0-9]+$ ]]; then
            echo "ERROR: ${LOCKDIR} still held after ${waited}s by PID ${owner} (lock age $((now - mtime))s); refusing to wait longer." >&2
            echo "Never broken automatically for a live owner -- if PID ${owner} is confirmed gone, remove manually: rm -rf ${LOCKDIR}" >&2
        else
            echo "ERROR: ${LOCKDIR} still held after ${waited}s by an unreadable/corrupt owner.pid (lock age $((now - mtime))s); refusing to wait longer." >&2
            echo "Never broken automatically before the 300s staleness rule -- remove manually if confirmed abandoned: rm -rf ${LOCKDIR}" >&2
        fi
        exit 1
    fi
    # A break that actually succeeded retries immediately (nothing to wait
    # for); every other path backs off, so a break that keeps failing cannot
    # burn a core while it waits out the timeout above.
    [[ "$broke_lock" == 1 ]] || sleep 0.1
done
LOCK_ACQUIRED=1
printf '%s\n' "$$" > "${LOCKDIR}/owner.pid"

python3 - "$QUEUE" "$HANDLED" "$REGISTRY" <<'PY'
import hashlib, json, os, sys, tempfile
queue_path, handled_path, registry_path = sys.argv[1:4]
OPEN = {"review-required", "needs_review", "needs_human"}

try:
    registry = json.load(open(registry_path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit("registry unreadable; refusing to partition the queue")

def is_open(line: str) -> bool:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 3:
        return True                      # unparseable -> keep, never discard silently
    task_id = parts[2].rsplit("/", 1)[-1]
    entry = registry.get(task_id)
    return isinstance(entry, dict) and str(entry.get("status") or "") in OPEN

header, kept, archived = [], [], []
for line in open(queue_path, encoding="utf-8").read().splitlines():
    if line.startswith("#") or not line.strip():
        header.append(line)
    elif is_open(line):
        kept.append(line)
    else:
        archived.append(line)

def atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)

if archived:
    # Crash safety: handled_path is written before queue_path (data-loss-safe
    # order -- a crash before either write leaves the queue untouched). But a
    # crash AFTER handled_path commits and BEFORE queue_path commits would, on
    # naive retry, recompute the identical archived batch (queue_path is still
    # unchanged) and append it a second time. To make that retry safe, the
    # batch and a hash marker of its exact contents are written to handled_path
    # in the SAME atomic_write -- marker and batch always land together, never
    # one without the other. On retry, if that marker is already present the
    # batch already landed; skip the append and just finish the interrupted
    # queue_path write. This never collapses genuine duplicate lines *within*
    # one batch -- the batch is treated as one atomic unit, not de-duplicated
    # line by line -- it only prevents re-landing the same whole batch twice.
    batch_hash = hashlib.sha256("\n".join(archived).encode("utf-8")).hexdigest()
    marker = f"<!-- chrono-queue-backfill:batch={batch_hash} -->"
    prior = open(handled_path, encoding="utf-8").read() if os.path.exists(handled_path) else ""
    if marker not in prior:
        atomic_write(handled_path, prior + "\n".join(archived) + "\n" + marker + "\n")
atomic_write(queue_path, "\n".join(header + kept) + "\n")
print(f"kept={len(kept)} archived={len(archived)}")
PY
