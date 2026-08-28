#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Reconcile `_state/active-tasks.json` from landed task responses."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

# registry_reconciler is loaded both as a script (scripts/python on sys.path[0])
# and via importlib.spec_from_file_location (e.g. bin/review-loop-guard-selftest.py),
# where the sibling dir is NOT on sys.path — ensure it before the sibling import.
_this_dir = str(Path(__file__).resolve().parent)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)
from repo_root import resolve_vault_root
from durable_publish import rename_noreplace as _rename_noreplace


VAULT_ROOT = resolve_vault_root()
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
REGISTRY_PATH = STATE_DIR / "active-tasks.json"
CHRONO_QUEUE_PATH = STATE_DIR / "chrono-queue.md"
LONG_RUNNING_NOTED_DIR = STATE_DIR / "long-running-noted"
LONG_RUNNING_MIN_AGE = timedelta(minutes=15)
LONG_RUNNING_DEBOUNCE = timedelta(minutes=15)
LONG_RUNNING_STALE_AGE = timedelta(hours=12)
SQUAD_SESSION = os.environ.get("SQUAD_SESSION", "squad")
TMUX_BIN = os.environ.get("TMUX_BIN", "tmux")
CHRONO_TMUX_TARGET = os.environ.get("CHRONO_TMUX_TARGET", f"{SQUAD_SESSION}:chrono")
CHRONO_PANE_HELPER = Path(__file__).resolve().parents[2] / "shared" / "chrono-pane.sh"
RESPONSE_MIN_AGE = timedelta(seconds=float(os.environ.get("RESPONSE_MIN_AGE_SECONDS", "5")))
NO_ENVELOPE_GRACE = timedelta(
    seconds=float(
        os.environ.get(
            "NO_ENVELOPE_GRACE_SECONDS",
            str(float(os.environ.get("NO_ENVELOPE_GRACE_MINUTES", "10")) * 60),
        )
    )
)
NO_ENVELOPE_MIN_DISPATCH_AGE = timedelta(
    seconds=float(os.environ.get("NO_ENVELOPE_MIN_DISPATCH_AGE_SECONDS", "60"))
)
# ── F5: never-launched tasks must not hold a write_scope ─────────────────────
# `bin/send-task.sh` registers a task (`delivery_state: queued`) and only flips
# it to `in-progress` in the same locked step that immediately precedes
# detaching the supervisor. So a task still sitting at `queued` with a zero
# attempt count NEVER STARTED. When the dispatch then dies before launch --
# context-build error, capability denial, an exit 74/75, or a `die` on the
# narrow paths that publish no blocked envelope -- the entry stayed `in-flight`
# forever, and `bin/send-task.sh`'s conflict check counts every in-flight entry,
# so the abandoned task kept blocking every re-dispatch that touched the same
# paths. Clearing it needed a hand-forged `cancelled` envelope plus
# `--close-task`; it was the single biggest time-sink of the 2026-07-26 session.
#
# The window between registration and the delivery-start flip is sub-second, so
# a task that has been queued for this long, produced NOTHING, and has no
# legacy assigned-worker fence never ran and owes nothing.
NEVER_LAUNCHED_GRACE = timedelta(
    seconds=float(os.environ.get("NEVER_LAUNCHED_GRACE_SECONDS", "120"))
)
SETTLED_WITHOUT_ENVELOPE = "work-done-no-envelope"
REVIEW_REQUIRED = "review-required"
COORDINATION_REQUESTED = "COORDINATION-REQUESTED"
COORDINATION_MIGRATION_SCHEMA = "coordination-status-migration/v1"
COORDINATION_MIGRATION_FIELD = "coordination_status_migration"
INBOX_ARCHIVE_STATUSES = frozenset(
    {
        "complete",
        "completed",
        "blocked",
        "needs_review",
        "needs_human",
        "cancelled",
        "closed",
        "superseded",
        SETTLED_WITHOUT_ENVELOPE,
        REVIEW_REQUIRED,
    }
)
RUNTIME_MAP_PATH = VAULT_ROOT / "shared" / "specialist-runtime-map.tsv"
DELIVERY_OPEN_STATES = frozenset({"queued", "claimed", "in-progress"})
REVIEW_CLASSES = frozenset({"standard", "factual", "security-finding"})
REVIEW_TRIGGERS = frozenset(
    {"blast_radius", "adversarial_claim", "deciding_measurement", "architecture"}
)
INVALID_REVIEW_LANE = "distinct-family-review-required"
WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
WORKER_EPOCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LANE_AUTHOR_FAMILY = {
    "gpt-codex": "openai",
    "claude": "anthropic",
    "gemini": "google",
    "kimi": "moonshot",
}

# Read-only review packets performed by verdict-producing roles must not require
# a review of their own review. The explicit empty write scope is essential:
# reviewer specialists doing implementation work still follow a declared trigger.
#
# The set must span BOTH review families or anti-affinity has no landing spot:
# code-reviewer and security-analyst both map to gpt-codex, so a codex-authored
# task -- which needs a non-openai reviewer -- had no eligible read-only verdict
# role at all. `skeptic` is the canonical claude-lane judgment role (shared ns,
# safety_level high, primary_lane claude in shared/specialist-runtime-map.tsv),
# so it completes the pair. The dispatcher no longer reads this set: packet
# review is trigger-derived, while this remains the narrow settlement exemption
# that prevents an explicitly reviewed verdict from recursing forever.
REVIEW_VERDICT_SPECIALISTS = frozenset({"code-reviewer", "security-analyst", "skeptic"})
TEST_ISOLATION_ENV = "SQUAD_TEST_ISOLATION"
CHRONO_NOTIFY_LOCKDIR = STATE_DIR / "chrono-notify.lockdir"
CHRONO_NOTIFY_RECEIPTS_DIR = STATE_DIR / "chrono-notify-receipts"


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _canonical_mailbox_contract() -> tuple[Any, re.Pattern[str], Any]:
    """Load the dispatch-only mailbox contract when reconciliation needs it.

    Notification health imports this module only for the queue paths and the
    canonical-registry membership predicate. Pulling the whole dispatch stack
    into that probe made an unrelated dispatch dependency an availability
    requirement for the notification spine. Keep the mailbox facts in their
    canonical module, but do not import that module on notification-only paths.
    """

    from dispatch_context_builder import (
        CANONICAL_MAILBOX_ROOT,
        MAILBOX_TASK_RE,
        canonical_mailbox_relative,
    )

    return CANONICAL_MAILBOX_ROOT, MAILBOX_TASK_RE, canonical_mailbox_relative


def _canonical_mailbox_label() -> str:
    mailbox_root, _, _ = _canonical_mailbox_contract()
    return str(mailbox_root.name)


def _mailbox_file_candidates(
    state: str, task_id: str, *, response: bool = False
) -> list[Path]:
    """Canonical path first, followed by drain-only legacy mailbox content."""

    _, mailbox_task_re, mailbox_relative = _canonical_mailbox_contract()
    if not mailbox_task_re.fullmatch(task_id):
        raise ValueError(f"invalid mailbox task id: {task_id!r}")
    canonical = VAULT_ROOT / mailbox_relative(
        state, task_id, response=response
    )
    filename = f"{task_id}-response.md" if response else f"{task_id}.md"
    legacy = sorted(
        path
        for path in (VAULT_ROOT / "departments").glob(f"*/{state}/{filename}")
        if path != canonical
    )
    return [canonical, *legacy]


def archive_inbox_packet(task_id: str) -> bool:
    """Atomically drain one terminal packet into the unified archive."""

    sources = [
        path
        for path in _mailbox_file_candidates("inbox", task_id)
        if os.path.lexists(path)
    ]
    if not sources:
        return False
    if len(sources) != 1:
        raise ValueError(
            f"multiple inbox packets exist for one task identity: {task_id}"
        )
    source = sources[0]
    _, _, mailbox_relative = _canonical_mailbox_contract()
    destination = VAULT_ROOT / mailbox_relative("archive", task_id)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"inbox packet is not a regular file: {source}")
    if os.path.lexists(destination):
        raise FileExistsError(f"archive packet already differs or conflicts: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, destination)
    except FileNotFoundError:
        if not os.path.lexists(source):
            return False
        raise
    for directory in (source.parent, destination.parent):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return True


# Overall wall-clock bound for lockdir()'s wait loop. This does NOT change the
# existing dead/absent-owner behavior (a confirmed-dead owner, per kill(0), or
# an owner.pid stale past the 300s mtime rule, is still broken immediately,
# with no timeout wait needed). It bounds the one case that used to spin
# forever: a CONFIRMED-LIVE owner that never releases. Env override lets a
# specific call site (or a test) shorten the wait without touching call sites
# that are fine with the default.
LOCKDIR_DEFAULT_TIMEOUT = float(os.environ.get("LOCKDIR_TIMEOUT_SECONDS", "60"))


def _lockdir_wait_or_timeout(path: Path, owner_text: str, start: float, timeout: float) -> None:
    """Sleep one poll tick, or fail loudly if the overall timeout has elapsed.

    Only reached while the current holder is confirmed alive, or its
    owner.pid is unreadable/corrupt but not yet 300s stale -- a live owner's
    lock is never broken here, only reported. "Never silently proceed": on
    expiry this raises rather than letting the caller believe it acquired the
    lock or silently skip the critical section.
    """
    elapsed = time.monotonic() - start
    if elapsed < timeout:
        time.sleep(0.1)
        return
    owner_display = owner_text or "unknown"
    try:
        age_display = f"{time.time() - path.stat().st_mtime:.1f}s"
    except OSError:
        age_display = "unknown"
    raise TimeoutError(
        f"lockdir {path} still held after {elapsed:.1f}s by PID {owner_display} "
        f"(lock age {age_display}); refusing to wait longer. Never broken "
        f"automatically for a live owner -- if PID {owner_display} is confirmed "
        f"gone, remove manually: rm -rf {path}"
    )


@contextmanager
def lockdir(path: Path, timeout: float = LOCKDIR_DEFAULT_TIMEOUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    start = time.monotonic()
    while not acquired:
        try:
            path.mkdir()
            acquired = True
            (path / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            break
        except FileExistsError:
            owner_text = read_text(path / "owner.pid").strip()
            if owner_text.isdigit():
                try:
                    os.kill(int(owner_text), 0)
                    _lockdir_wait_or_timeout(path, owner_text, start, timeout)
                    continue
                except ProcessLookupError:
                    try:
                        (path / "owner.pid").unlink(missing_ok=True)
                        path.rmdir()
                    except OSError:
                        _lockdir_wait_or_timeout(path, owner_text, start, timeout)
                    continue
                except PermissionError:
                    _lockdir_wait_or_timeout(path, owner_text, start, timeout)
                    continue
            try:
                age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                _lockdir_wait_or_timeout(path, owner_text, start, timeout)
                continue
            if age > timedelta(minutes=5):
                try:
                    (path / "owner.pid").unlink(missing_ok=True)
                    path.rmdir()
                except OSError:
                    _lockdir_wait_or_timeout(path, owner_text, start, timeout)
                continue
            _lockdir_wait_or_timeout(path, owner_text, start, timeout)
    try:
        yield
    finally:
        if acquired:
            try:
                (path / "owner.pid").unlink(missing_ok=True)
                path.rmdir()
            except OSError:
                pass


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def append_chrono_queue(status: str, task_ref: str, summary: str) -> None:
    safe_summary = re.sub(r"\s+", " ", summary or "").strip().replace("|", "/")
    if not safe_summary:
        safe_summary = "(no pane snippet)"
    safe_summary = safe_summary[:200]
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | {status} | {task_ref} | {safe_summary}\n"
    with lockdir(CHRONO_QUEUE_PATH.with_suffix(CHRONO_QUEUE_PATH.suffix + ".lockdir")):
        existing = read_text(
            CHRONO_QUEUE_PATH,
            "# Chrono Queue\n# timestamp | status | namespace/task-id | summary\n\n",
        )
        atomic_write(CHRONO_QUEUE_PATH, existing + line)


def notification_event_key(task_ref: str, state: str) -> str:
    """Return an unambiguous receipt key for one task-ref/state event."""
    return f"{len(task_ref)}:{task_ref}|{len(state)}:{state}"


def notification_receipt_path(event_key: str) -> Path:
    digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
    return CHRONO_NOTIFY_RECEIPTS_DIR / f"{digest}.sent"


def chrono_pane_has_coordinator() -> bool:
    """Use the same version-independent presence probe as sibling notifiers."""

    if CHRONO_PANE_HELPER.is_symlink() or not CHRONO_PANE_HELPER.is_file():
        return False
    completed = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; chrono_pane_has_coordinator "$2"',
            "chrono-pane-presence",
            str(CHRONO_PANE_HELPER),
            CHRONO_TMUX_TARGET,
        ],
        capture_output=True,
        timeout=5,
    )
    return completed.returncode == 0


def nudge_chrono(message: str, event_key: str | None = None) -> bool:
    """Send one serialized, receipt-backed nudge to the ``chrono`` window.

    The shared lock spans both tmux calls, so one notification's text cannot
    interleave with another notification's Enter. A receipt is written only
    after both calls succeed; concurrent/replayed senders for the same
    length-prefixed event key therefore become no-ops. The caller appends the
    durable Chrono queue before entering this function.
    """
    # Unit/integration fixtures must never type into the operator's real tmux
    # session. Tests opt into this process-local seam explicitly and assert that
    # subprocess.run is never reached; production behavior is unchanged.
    if os.environ.get(TEST_ISOLATION_ENV) == "1":
        return False
    if event_key is None:
        event_key = notification_event_key(
            "legacy-direct",
            hashlib.sha256(message.encode("utf-8")).hexdigest(),
        )
    try:
        with lockdir(CHRONO_NOTIFY_LOCKDIR):
            receipt = notification_receipt_path(event_key)
            if receipt.is_file():
                return True
            session = subprocess.run(
                [TMUX_BIN, "has-session", "-t", SQUAD_SESSION],
                capture_output=True,
                timeout=5,
            )
            if session.returncode != 0:
                return False
            if not chrono_pane_has_coordinator():
                return False
            literal = subprocess.run(
                [TMUX_BIN, "send-keys", "-l", "-t", CHRONO_TMUX_TARGET, message],
                capture_output=True,
                timeout=5,
            )
            if literal.returncode != 0:
                return False
            # Match the shell fallback. The shared lock remains held across the
            # settle delay and Enter, so no other notifier can interleave.
            time.sleep(0.3)
            submit = subprocess.run(
                [TMUX_BIN, "send-keys", "-t", CHRONO_TMUX_TARGET, "Enter"],
                capture_output=True,
                timeout=5,
            )
            if submit.returncode != 0:
                return False
            receipt_payload = {
                "event_key": event_key,
                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "target": CHRONO_TMUX_TARGET,
            }
            try:
                atomic_write(
                    receipt,
                    json.dumps(receipt_payload, sort_keys=True, ensure_ascii=False) + "\n",
                )
            except OSError:
                # The durable queue entry already exists. Surface failure so
                # the caller cannot claim receipt-backed delivery.
                return False
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# F12: every other reconciler sink (registry, outbox, chrono-queue) is scoped by
# VAULT_ROOT, but `nudge_chrono` types into CHRONO_TMUX_TARGET -- a HOST-GLOBAL
# pane. A sweep run against a throwaway VAULT_ROOT (the hermetic tests, which
# reconcile their own fixtures, or bin/reconcile-selftest.sh) therefore escapes
# its sandbox and pages the operator's real Chrono about tasks Chrono never
# dispatched. The page is only meaningful for task ids the HOST's own registry
# knows, so that is what gates it.
CANONICAL_REGISTRY_RELPATHS = ("_state/tasks/active.json", "_state/active-tasks.json")


def canonical_vault_root() -> Path:
    """The host's vault, deliberately independent of the VAULT_ROOT override.

    A hermetic run sets VAULT_ROOT; it must not be able to redefine which
    registry is authoritative for the operator-facing pane.
    """
    return Path(
        os.environ.get("CHRONO_CANONICAL_VAULT_ROOT")
        or str(Path.home() / "Obsidian-Claude-Vibe-Squad")
    )


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def registered_in_canonical_registry(task_id: str) -> bool:
    """True when the host's canonical registry knows ``task_id``.

    Fails toward SILENCE only for a task the canonical registry can be read and
    does NOT contain -- a hermetic-test fixture, a bare response-file discovery,
    or rotated-out residue. Two cases deliberately stay loud:

    * we are reconciling a canonical registry itself, where membership holds by
      construction because ``reconcile()`` only iterates registered entries; and
    * no canonical registry is readable at all, which is absence of evidence
      rather than evidence of non-registration, so a relocated real deployment
      keeps paging.
    """
    operating = _resolved(REGISTRY_PATH)
    root = canonical_vault_root()
    canonical_paths = [root / relpath for relpath in CANONICAL_REGISTRY_RELPATHS]
    if any(_resolved(path) == operating for path in canonical_paths):
        return True
    readable = 0
    for path in canonical_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        readable += 1
        if task_id in data:
            return True
    return readable == 0


def emit_event(status: str, task_ref: str, summary: str, nudge: str) -> bool:
    # Durable-first: if queueing fails, do not type an unrecoverable nudge.
    # The queue append is VAULT_ROOT-scoped and unconditional -- it is the
    # recovery record, and withholding it would degrade replay. Only the
    # host-global page is gated (see registered_in_canonical_registry).
    append_chrono_queue(status, task_ref, summary)
    if not registered_in_canonical_registry(task_ref.rsplit("/", 1)[-1]):
        return False
    return nudge_chrono(nudge, notification_event_key(task_ref, status))


def notification_due(
    entry: dict[str, Any], task_id: str, state: str, now: datetime
) -> bool:
    """Persist an exactly-once notification key for one task state/generation.

    This function only mutates the caller-owned entry. `reconcile()` persists
    that mutation in the same locked atomic registry write as the state
    transition before it emits the event outside the registry lock.
    A watcher restart therefore cannot turn the same response into an unbounded
    notification loop. Recovery is provided by durable queue state; repeating an
    identical notification is not a delivery mechanism.
    """
    generation = int(entry.get("delivery_generation") or 1)
    key = f"{task_id}|{state}|{generation}"
    previous = str(entry.get("notification_key") or "")
    if previous == key:
        return False
    entry["notification_key"] = key
    entry["notification_state"] = state
    entry["notification_delivery_generation"] = generation
    entry["notification_last_emitted_at"] = now.isoformat()
    return True


def coordination_notification_due(
    entry: dict[str, Any], task_id: str, now: datetime
) -> bool:
    """Persist an exactly-once key for the nonblocking coordination signal.

    Completion and coordination are independent facts, so they cannot share the
    single ``notification_key`` slot without oscillating on every reconcile.
    """

    generation = int(entry.get("delivery_generation") or 1)
    key = f"{task_id}|{COORDINATION_REQUESTED}|{generation}"
    if entry.get("coordination_notification_key") == key:
        return False
    entry["coordination_notification_key"] = key
    entry["coordination_notification_state"] = COORDINATION_REQUESTED
    entry["coordination_notification_delivery_generation"] = generation
    entry["coordination_notification_last_emitted_at"] = now.isoformat()
    return True


def canonical_review_class(value: Any, *, source: str) -> str:
    """Return the one canonical review class, or refuse.

    ``review_class`` decides which validator settles a task: ``standard``
    accepts any independent cross-family review, ``security-finding`` demands an
    exact response-hash binding, and ``factual`` demands a Chrono attestation.
    A permissive default on a field with that shape is a downgrade dressed as a
    convenience -- the weakest value is exactly what an omission must not
    silently select. Absence, blankness, and any unrecognized value are refused
    here so a constructor that forgets the field is loud at registration rather
    than quiet at settlement.

    Surrounding whitespace and case are normalized rather than refused so a
    semantically identical retry (`" FACTUAL "` vs `"factual"`) is idempotent
    instead of registering as a conflicting re-registration.
    """

    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{source} is missing an explicit review_class; a security field has "
            "no default -- the dispatching constructor must carry the packet's "
            f"validated class (one of {', '.join(sorted(REVIEW_CLASSES))})"
        )
    canonical = value.strip().lower()
    if canonical not in REVIEW_CLASSES:
        raise ValueError(
            f"{source} has an invalid review_class {value!r}; expected one of "
            + ", ".join(sorted(REVIEW_CLASSES))
        )
    return canonical


def canonical_review_triggers(value: Any, *, source: str) -> list[str]:
    """Validate the packet-level reasons for independent review.

    The dispatcher accepts a single-line inline list and stores it as JSON. This
    second validation protects direct registry callers and makes trigger data a
    stable part of dispatch identity. Missing remains a legacy shape; callers
    decide whether to preserve the old mandatory flag or require migration.
    """

    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{source} review_triggers must be a list of strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{source} review_triggers contains duplicate values")
    unknown = sorted(set(value) - REVIEW_TRIGGERS)
    if unknown:
        raise ValueError(
            f"{source} review_triggers contains unknown value(s): "
            + ", ".join(unknown)
        )
    return list(value)


def apply_worker_schema_defaults(entry: dict[str, Any]) -> None:
    """Add nullable compatibility fields without changing dispatch identity.

    ``review_class`` deliberately does NOT appear here. It is policy, not a
    nullable compatibility field. Callers canonicalize it explicitly via
    :func:`canonical_review_class` so malformed registrations fail closed.
    """
    entry.setdefault("delivery_worker_id", None)
    entry.setdefault("worker_epoch", None)
    entry.setdefault("lease_generation", 0)
    entry.setdefault("lease_expires_at", None)
    entry.setdefault("heartbeat_observed_at", None)
    entry.setdefault("member_id", None)
    entry.setdefault("replica_index", None)
    entry.setdefault("priority_class", "normal")
    entry.setdefault("enqueued_at", entry.get("dispatched_at"))


def validate_member_identity(entry: dict[str, Any]) -> None:
    member_id = entry.get("member_id")
    if member_id in (None, ""):
        if entry.get("replica_index") is not None:
            raise ValueError("replica_index requires member_id")
        return
    lane = _delivery_lane(entry)
    if not lane or not re.fullmatch(rf"{re.escape(lane)}:(?:r\d{{2}}|sub\d{{2}})", str(member_id)):
        raise ValueError(
            "member_id must be <lane>:rNN or <lane>:subNN and match delivery lane"
        )
    replica = entry.get("replica_index")
    suffix = str(member_id).split(":", 1)[1]
    expected = int(re.sub(r"^(?:r|sub)", "", suffix))
    if replica is not None and int(replica) != expected:
        raise ValueError("replica_index does not match member_id")


def _validate_worker_token(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    token = str(value or "").strip()
    if not pattern.fullmatch(token):
        raise ValueError(f"invalid {label}: {token!r}")
    return token


class RegistryCorruptError(RuntimeError):
    """active-tasks.json exists but is malformed or is not a JSON object."""


def _preserve_corrupt_registry(raw: bytes) -> None:
    """Best-effort timestamped diagnostic copy of a corrupt registry.

    Writes the raw bytes byte-for-byte (binary) so an invalid-UTF-8 registry is
    preserved exactly, not lossily re-encoded.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    diagnostic = REGISTRY_PATH.with_name(f"{REGISTRY_PATH.name}.corrupt.{stamp}")
    try:
        if not diagnostic.exists():
            with diagnostic.open("xb") as handle:
                handle.write(raw)
    except OSError:
        pass


def load_registry() -> dict[str, Any]:
    """Load the active-task registry.

    An ABSENT file is a legitimate empty registry ({}). A file that EXISTS but is
    not valid UTF-8, not valid JSON, or is valid JSON that is not an object, is a
    HARD corruption error: we refuse to write (a subsequent register/reconcile
    write would erase every in-flight task), preserve a timestamped diagnostic copy
    (byte-for-byte), and surface the failure — we never silently reset the registry
    to empty.
    """
    try:
        raw_bytes = REGISTRY_PATH.read_bytes()
    except FileNotFoundError:
        return {}
    # MED4 (wave-2): read BYTES first. read_text(encoding="utf-8") raises
    # UnicodeDecodeError BEFORE the JSON branch, which would escape uncaught (no
    # exit-2, no diagnostic). Decode explicitly and translate the failure.
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            f"active-tasks.json is not valid UTF-8 ({exc}); refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            f"active-tasks.json is not valid JSON ({exc}); refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        ) from exc
    if not isinstance(data, dict):
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            "active-tasks.json is not a JSON object; refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        )
    return data


def locked_registry():
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".lock")
    lock_fh = lock_path.open("w", encoding="utf-8")
    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    return lock_fh


def _stored_review_class(entry: dict[str, Any]) -> Any:
    """Identity-stable review class for comparing a stored entry to a new one.

    Registration canonicalizes before storing, so a freshly built entry is
    always canonical. A value already on disk is normalized the same way when
    it is recognizable and otherwise compared verbatim: an unrecognizable or
    absent stored class must not silently compare equal to a canonical one.
    """

    value = entry.get("review_class")
    if isinstance(value, str) and value.strip().lower() in REVIEW_CLASSES:
        return value.strip().lower()
    return value


def _validated_review_target(value: Any, *, source: str) -> str:
    """Return one canonical held-task id from controller-owned provenance."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} has an invalid reviews provenance value")
    target = value.strip()
    _, mailbox_task_re, _ = _canonical_mailbox_contract()
    if not mailbox_task_re.fullmatch(target):
        raise ValueError(
            f"{source} has an invalid reviews provenance task id: {target!r}"
        )
    return target


def _packet_review_target(task_id: str) -> str:
    """Read an optional review target from the controller-authored task packet.

    ``send-task.sh`` lands the packet before it registers the task. Projecting
    that immutable dispatch fact into the registry at registration time gives
    settlement a controller-owned target without granting any authority to the
    later worker-authored response. Historical rows can use the same source to
    repair the one field the old registrar omitted, including after the packet
    has moved to the mailbox archive.
    """

    # `close_task` commits the terminal registry row before it atomically moves
    # the packet from inbox to archive. If that rename lands after candidate
    # enumeration but before the read, a second immediate scan sees the new
    # location without turning a harmless race into a failed settlement.
    for _attempt in range(2):
        observed: dict[str, list[str]] = {}
        for packet in task_packet_candidates(task_id):
            text = read_text(packet)
            loose = strip_frontmatter(text)
            strict = strip_frontmatter(text, reject_duplicates=True)
            if loose.get("reviews") and not strict:
                raise ValueError(
                    f"review task packet has ambiguous frontmatter: {packet}"
                )
            raw_target = strict.get("reviews")
            if not raw_target:
                continue
            target = _validated_review_target(
                raw_target, source=f"review task packet {packet}"
            )
            observed.setdefault(target, []).append(str(packet))
        if len(observed) > 1:
            details = "; ".join(
                f"{target} via {', '.join(paths)}"
                for target, paths in sorted(observed.items())
            )
            raise ValueError(
                "review task packet copies disagree on reviews provenance: "
                f"{details}"
            )
        if observed:
            return next(iter(observed))
    return ""


def _project_review_packet_provenance(
    task_id: str, entry: dict[str, Any]
) -> str:
    """Validate and store packet-owned review linkage on a registry entry."""

    raw_stored = entry.get("reviews")
    stored = (
        _validated_review_target(
            raw_stored, source=f"review task registry entry {task_id}"
        )
        if raw_stored is not None
        else ""
    )
    packet = _packet_review_target(task_id)
    if stored and packet and stored != packet:
        raise ValueError(
            "review task registry provenance conflicts with its task packet: "
            f"task={task_id} registry={stored} packet={packet}"
        )
    if packet:
        entry["reviews"] = packet
        return packet
    return stored


def _dispatch_identity(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        entry.get("specialist"),
        entry.get("to_model"),
        entry.get("source_namespace"),
        entry.get("return_artifact"),
        tuple(entry.get("write_scope") or ()),
        entry.get("capability_card_sha256"),
        entry.get("verification_contract_sha256"),
        entry.get("review_model"),
        entry.get("mandatory_review"),
        tuple(entry.get("review_triggers") or ()),
        # Canonical, so a semantically identical retry is idempotent. A stored
        # entry that predates canonicalization compares by its own raw value.
        _stored_review_class(entry),
        # General frozen-question provenance retained for independently
        # dispatched single tasks; this is not a transport discriminator.
        entry.get("swarm_spec_sha256"),
        # A review task's held subject is controller-owned dispatch identity.
        entry.get("reviews"),
    )


def requires_review_class(entry: dict[str, Any]) -> bool:
    """True when this entry's review class actually selects a validator.

    A task with ``mandatory_review: false`` never reaches ``_review_class`` --
    ``cross_family_review_pending`` returns early -- so an absent class there
    downgrades nothing. Storing an invented ``standard`` for it was the worse
    option: it records a policy the packet never declared. Absent stays absent;
    required where it is load-bearing; strict wherever it is read.
    """

    return str(entry.get("mandatory_review", "")).strip().lower() == "true"


def register_task(task_id: str, entry: dict[str, Any]) -> bool:
    """Register once under the shared lock; idempotent retries preserve receipts."""
    if "review_triggers" in entry:
        entry["review_triggers"] = canonical_review_triggers(
            entry.get("review_triggers"), source=f"task {task_id}"
        )
        has_triggers = bool(entry["review_triggers"])
        flag = str(entry.get("mandatory_review", "")).strip().lower() == "true"
        if has_triggers != flag:
            raise ValueError(
                f"task {task_id} review_triggers and mandatory_review disagree"
            )
    if requires_review_class(entry) or entry.get("review_class") is not None:
        entry["review_class"] = canonical_review_class(
            entry.get("review_class"), source=f"task {task_id}"
        )
    _project_review_packet_provenance(task_id, entry)
    apply_worker_schema_defaults(entry)
    validate_member_identity(entry)
    with locked_registry() as _lock:
        registry = load_registry()
        existing = registry.get(task_id)
        if existing is not None:
            if not isinstance(existing, dict):
                raise ValueError(f"conflicting task re-registration: {task_id}")
            existing_target = existing.get("reviews")
            incoming_target = entry.get("reviews")
            if existing_target is None and incoming_target is not None:
                enriched = dict(existing)
                enriched["reviews"] = incoming_target
                if _dispatch_identity(enriched) == _dispatch_identity(entry):
                    # Schema enrichment is still the same dispatch: retain all
                    # delivery receipts and report the retry as idempotent.
                    existing["reviews"] = incoming_target
                    atomic_write(
                        REGISTRY_PATH,
                        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                    )
                    return False
            elif existing_target is not None and incoming_target is None:
                comparable = dict(entry)
                comparable["reviews"] = existing_target
                if _dispatch_identity(existing) == _dispatch_identity(comparable):
                    return False
            if _dispatch_identity(existing) != _dispatch_identity(entry):
                raise ValueError(f"conflicting task re-registration: {task_id}")
            return False
        registry[task_id] = entry
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return True




def _parse_action_time(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("delivery time must include a timezone")
    return value.astimezone(timezone.utc)


def _delivery_lane(entry: dict[str, Any]) -> str:
    return str(entry.get("delivery_lane") or entry.get("to_model") or "")


def _delivery_head(registry: dict[str, Any], lane: str) -> str | None:
    candidates: list[tuple[str, str]] = []
    for task_id, candidate in registry.items():
        if not isinstance(candidate, dict) or _delivery_lane(candidate) != lane:
            continue
        status = str(candidate.get("status") or "")
        state = candidate.get("delivery_state")
        if status == "in-flight" and state in DELIVERY_OPEN_STATES:
            candidates.append((str(candidate.get("dispatched_at") or ""), task_id))
    return min(candidates)[1] if candidates else None


def _worker_fence(entry: dict[str, Any], task_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "delivery_attempt_id": str(entry.get("delivery_attempt_id") or ""),
        "delivery_generation": int(entry.get("delivery_generation") or 1),
        "delivery_worker_id": str(entry.get("delivery_worker_id") or ""),
        "worker_epoch": str(entry.get("worker_epoch") or ""),
        "lease_generation": int(entry.get("lease_generation") or 0),
        "delivery_lane": _delivery_lane(entry),
        "lease_expires_at": str(entry.get("lease_expires_at") or ""),
        "member_id": entry.get("member_id"),
        "replica_index": entry.get("replica_index"),
    }


def claim_task(
    task_id: str,
    attempt_id: str,
    *,
    worker_id: str | None = None,
    worker_epoch: str | None = None,
    lease_generation: int | None = None,
    lane: str | None = None,
    now_raw: str | None = None,
) -> dict[str, Any]:
    """Atomically record the lane-authored claim and execution start."""
    now = _parse_action_time(now_raw)
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        current_attempt = str(entry.get("delivery_attempt_id") or "")
        if attempt_id != current_attempt:
            raise ValueError(f"stale delivery attempt for {task_id}")
        state = str(entry.get("delivery_state") or "")
        pooled = bool(entry.get("delivery_worker_id"))
        if pooled:
            assigned_worker = str(entry.get("delivery_worker_id") or "")
            if not assigned_worker:
                raise ValueError(f"task requires scheduler assignment before claim: {task_id}")
            claimed_worker = _validate_worker_token(worker_id, "worker_id", WORKER_ID_RE)
            claimed_epoch = _validate_worker_token(worker_epoch, "worker_epoch", WORKER_EPOCH_RE)
            if lease_generation is None:
                raise ValueError("worker claim requires lease_generation")
            claimed_lane = _lane(lane)
            expected_lane = _delivery_lane(entry)
            if claimed_worker != assigned_worker:
                raise ValueError(f"worker assignment mismatch for {task_id}")
            if claimed_epoch != str(entry.get("worker_epoch") or ""):
                raise ValueError(f"stale worker epoch for {task_id}")
            if int(lease_generation) != int(entry.get("lease_generation") or 0):
                raise ValueError(f"stale lease generation for {task_id}")
            if not claimed_lane or claimed_lane != expected_lane:
                raise ValueError(f"worker lane mismatch for {task_id}")
            expiry = parse_dt(entry.get("lease_expires_at"))
            if expiry is None or now >= expiry:
                if state in DELIVERY_OPEN_STATES:
                    mark_delivery_terminal(
                        task_id, entry, now, "worker-lease-expired-at-claim"
                    )
                    entry["worker_assignment_state"] = "expired"
                    entry["worker_cancel_reason"] = "worker-lease-expired-at-claim"
                    entry["worker_cancelled_at"] = now.isoformat()
                    atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
                raise ValueError(f"worker lease expired for {task_id}")
            for other_id, other in registry.items():
                if other_id == task_id or not isinstance(other, dict):
                    continue
                if str(other.get("delivery_worker_id") or "") != claimed_worker:
                    continue
                if str(other.get("status") or "") == "in-flight" \
                    and str(other.get("delivery_state") or "") in DELIVERY_OPEN_STATES:
                    raise ValueError(
                        f"worker {claimed_worker} already has active task {other_id}"
                    )
            if state == "in-progress":
                return {
                    **_worker_fence(entry, task_id),
                    "attempt_id": attempt_id,
                    "delivery_state": state,
                    "idempotent": True,
                }
        elif state == "in-progress":
            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "delivery_state": state,
                "idempotent": True,
            }
        if state != "queued":
            raise ValueError(f"task cannot be claimed from delivery state {state or 'missing'}")
        if str(entry.get("status") or "") != "in-flight":
            raise ValueError(f"task cannot be claimed from registry status {entry.get('status') or 'missing'}")
        lane = _delivery_lane(entry)
        if not pooled and _delivery_head(registry, lane) != task_id:
            raise ValueError(f"task is not the head of lane {lane}: {task_id}")

        generation = int(entry.get("delivery_generation") or 1)
        history = entry.setdefault("delivery_history", [])
        entry["delivery_state"] = "claimed"
        entry["claimed_at"] = entry.get("claimed_at") or now.isoformat()
        history.append(
            {
                "event": "claimed",
                "at": now.isoformat(),
                "attempt_id": attempt_id,
                "generation": generation,
                **(
                    {
                        "worker_id": entry.get("delivery_worker_id"),
                        "worker_epoch": entry.get("worker_epoch"),
                        "lease_generation": int(entry.get("lease_generation") or 0),
                    }
                    if pooled
                    else {}
                ),
            }
        )
        entry["delivery_state"] = "in-progress"
        if pooled:
            entry["worker_assignment_state"] = "in-progress"
        entry["started_at"] = entry.get("started_at") or now.isoformat()
        history.append(
            {
                "event": "in-progress",
                "at": now.isoformat(),
                "attempt_id": attempt_id,
                "generation": generation,
            }
        )
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return {
            **(_worker_fence(entry, task_id) if pooled else {}),
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": generation,
            "delivery_state": "in-progress",
            "idempotent": False,
        }


def mark_delivery_terminal(
    task_id: str,
    entry: dict[str, Any],
    now: datetime,
    reason: str,
) -> bool:
    if not entry.get("delivery_attempt_id") or entry.get("delivery_state") == "terminal":
        return False
    entry["delivery_state"] = "terminal"
    entry["delivery_terminal_at"] = now.isoformat()
    entry.pop("delivery_next_attempt_at", None)
    entry.setdefault("delivery_history", []).append(
        {
            "event": "terminal",
            "at": now.isoformat(),
            "attempt_id": entry.get("delivery_attempt_id"),
            "generation": int(entry.get("delivery_generation") or 1),
            "reason": reason,
        }
    )
    release_blocked_stub(task_id, entry)
    return True


def strip_frontmatter(text: str, *, reject_duplicates: bool = False) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if reject_duplicates and key in meta:
            return {}
        meta[key] = value.strip().strip('"').strip("'")
    return meta


# FIX 3 (wave-2): ONE canonical settleable-status vocabulary — the single source
# of truth for which response statuses may settle a task. A landed response may
# settle a task only to a status here; empty / unknown / typo statuses canonicalize
# to "" and are rejected, so a misspelling can NEVER settle a task with a bogus
# state (fail closed → the task stays open). `bin/outbox-watcher.sh` delegates ALL
# settlement to this module and never settles on its own, so this is the sole
# settle authority. `review-required` / `work-done-no-envelope` are reconciler
# registry states, not response statuses, and are intentionally not settleable here.
_STATUS_ALIASES = {"completed": "complete", "canceled": "cancelled"}
SETTLEABLE_STATUSES = frozenset(
    {"complete", "needs_review", "blocked", "needs_human", "cancelled"}
)
_COORDINATION_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s+COORDINATION[ _-]+REQUESTED\s*:?\s*$",
    re.IGNORECASE,
)
_LEGACY_NEEDS_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s+NEEDS\s+FROM\s+CHRONO\s*:?\s*$",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def packet_declares_review(entry: dict[str, Any]) -> bool:
    """Return whether trusted packet state declares a real review obligation.

    Malformed trigger state fails closed.  Missing triggers retain the legacy
    ``mandatory_review`` behavior, while an explicit empty list plus a false
    mandatory flag is the only modern untriggered shape.
    """

    mandatory = str(entry.get("mandatory_review", "")).strip().lower() == "true"
    raw_triggers = entry.get("review_triggers")
    if raw_triggers is None:
        return mandatory
    try:
        triggers = canonical_review_triggers(raw_triggers, source="registry entry")
    except ValueError:
        return True
    return mandatory or bool(triggers)


def resolve_worker_status(
    entry: dict[str, Any], reported_status: str
) -> tuple[str, bool]:
    """Separate a worker's outcome from its nonblocking coordination request.

    A worker cannot manufacture review debt absent a trusted packet trigger.
    The raw spelling remains caller-visible via ``worker_reported_status``.
    """

    if reported_status == "needs_review" and not packet_declares_review(entry):
        return "complete", True
    return reported_status, False


def registry_status(raw: str) -> str:
    """Canonicalize a landed response status; '' for empty/unknown (fail closed)."""
    status = (raw or "").strip()
    status = _STATUS_ALIASES.get(status, status)
    return status if status in SETTLEABLE_STATUSES else ""


def response_status(path: Path) -> str:
    return registry_status(strip_frontmatter(read_text(path)).get("status", ""))


def raw_response_status(path: Path) -> str:
    """Return the response's uncanonicalized worker spelling for provenance."""

    return strip_frontmatter(read_text(path)).get("status", "").strip()


def valid_response_status(status: str) -> bool:
    """True only for a canonical settleable status (rejects '', 'in-flight', typos)."""
    return status in SETTLEABLE_STATUSES


def settlement_process(
    task_id: str, entry: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    """Return the exact attempt's settlement rail and descriptor."""
    attempt = str(entry.get("delivery_attempt_id") or "")
    raw_generation = entry.get("delivery_generation")
    generation = 1 if raw_generation is None else raw_generation
    raw_history = entry.get("delivery_history")
    if raw_history is not None and not isinstance(raw_history, list):
        return "invalid", None
    board_history = [
        item
        for item in raw_history or ()
        if isinstance(item, dict)
        and item.get("event") == "in-progress"
        and item.get("transport") == "board-supervisor"
    ]
    descriptor = STATE_DIR / "board-dispatch" / f"{task_id}.{attempt}.dispatch.json"
    if not board_history and not os.path.lexists(descriptor):
        return "v1", None
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        return "invalid", None
    if board_history:
        board_rows = [
            item for item in board_history if item.get("attempt_id") == attempt
        ]
        if not any(
            type(item.get("generation")) is int
            and item.get("generation") == generation
            for item in board_rows
        ):
            return "invalid", None
    if descriptor.is_symlink() or not descriptor.is_file():
        return "invalid", None
    # Lazy V2-only reuse keeps the V1 rail independent while sharing the exact
    # strict JSON and process-descriptor contract with its producer.
    try:
        from board_process_truth import descriptor_error, load_json
    except ImportError:
        return "invalid", None

    payload = load_json(descriptor)
    if descriptor_error(descriptor, payload) or payload.get("generation") != generation:
        return "invalid", None
    schema = {
        "board-dispatch-process/v1": "v1" if generation == 1 else "invalid",
        "board-dispatch-process/v2": "v2",
    }.get(payload.get("schema"), "invalid")
    if not board_history and schema != "v1":
        return "invalid", None
    return schema, payload if schema != "invalid" else None


def response_ready(path: Path, schema: str = "v1") -> bool:
    if schema == "v2":
        return not path.is_symlink() and path.is_file()
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age >= RESPONSE_MIN_AGE


def response_candidates(
    task_id: str, entry: dict[str, Any] | None = None, schema: str = "v1"
) -> list[Path]:
    if schema == "v2" and entry is not None:
        # New authorities can name only the canonical outbox. The legacy scan
        # is drain-only migration for packets that were already in flight at
        # cutover; it is keyed by the globally unique task id, never by a
        # compatibility/source namespace that could disagree with authority.
        return [
            candidate
            for candidate in _mailbox_file_candidates(
                "outbox", task_id, response=True
            )
            if not candidate.is_symlink() and candidate.is_file()
        ]
    if schema != "v1":
        return []
    candidates: list[Path] = []
    for state in ("outbox", "archive"):
        candidates.extend(
            path
            for path in _mailbox_file_candidates(state, task_id, response=True)
            if path.is_file() and not path.is_symlink()
        )
    return sorted(
        set(candidates),
        key=lambda path: (path.stat().st_mtime, str(path)),
        reverse=True,
    )


def landed_response(
    task_id: str,
    candidates: list[Path] | None = None,
    schema: str = "v1",
    entry: dict[str, Any] | None = None,
) -> tuple[Path | None, str]:
    for candidate in candidates if candidates is not None else response_candidates(task_id):
        if not response_ready(candidate, schema):
            continue
        if schema == "v2":
            meta = strip_frontmatter(
                read_text(candidate), reject_duplicates=True
            )
            if (
                meta.get("id") != f"{task_id}-response"
                or meta.get("in_response_to") != task_id
                or meta.get("type") != "RESULT"
                or entry is None
                or meta.get("delivery_attempt_id")
                != str(entry.get("delivery_attempt_id") or "")
                or meta.get("delivery_generation")
                != str(entry.get("delivery_generation"))
            ):
                continue
        status = response_status(candidate)
        if valid_response_status(status):
            return candidate, status
    return None, ""


RECEIPT_DIAGNOSTIC_REASON_LIMIT = 240

# Every registry key `receipt_failure_diagnostics` knows how to produce. A
# re-reconcile that finds a receipt WITHOUT one of these clears the stale value
# instead of leaving a previous answer standing: these fields describe one exact
# attempt, and a stale evidence ref is worse than none -- it sends a reader to a
# branch that does not hold their work.
RECEIPT_DIAGNOSTIC_FIELDS = (
    "failure_class",
    "reason",
    "returncode",
    "evidence_status",
    "evidence_ref",
    "evidence_commit",
    "evidence_location",
    "evidence_worktree_location",
    "evidence_preserved_path_count",
    "evidence_worktree_retained_required",
    "evidence_reason",
    "evidence_out_of_scope_paths",
    "evidence_out_of_scope_path_count",
    "work_recovery_status",
    "work_recovery_commit",
    "work_recovery_paths",
)

# receipt `evidence_preservation` key -> diagnostics key.
_EVIDENCE_STRING_FIELDS = (
    ("status", "evidence_status"),
    ("evidence_ref", "evidence_ref"),
    ("evidence_commit", "evidence_commit"),
    ("evidence_location", "evidence_location"),
    ("worktree_location", "evidence_worktree_location"),
    ("reason", "evidence_reason"),
)


def attempt_evidence_ref(task_id: str, entry: dict[str, Any]) -> str:
    """The Git ref an attempt's private branch takes, by construction.

    `worktree_isolation._branch_name` derives every attempt branch as
    `worktree/<task_id>/<attempt_id>`, so this name is knowable from the
    registry alone -- including when the receipt recorded no evidence because
    the worktree directory was already gone. That case is not hypothetical: it
    is what made TASK-2026-08-11-0180 read as "permanently unverifiable" while
    4,538 bytes of its evidence sat on exactly this ref.
    """

    attempt_id = str(entry.get("delivery_attempt_id") or "").strip()
    if not attempt_id:
        return ""
    return f"refs/heads/worktree/{task_id}/{attempt_id}"


def never_ran_statement(entry: dict[str, Any]) -> str:
    """Say loudly when a task settled without ever launching.

    `never_launched_reason` only fires for status `in-flight` + delivery_state
    `queued`. A task rejected BEFORE launch -- a context-builder refusal, a
    capability-enforcement denial -- settles terminal instead, and if the packet
    carried `mandatory_review: true` it inherits `review-required`. That status
    is indistinguishable from a task that ran, produced work, and is awaiting a
    reviewer.

    Measured 2026-08-14: four dispatches died this way in one sequence (two
    packet errors, two flaky MCP-enumeration timeouts) and every one reported
    `review-required`. Only the missing artifact gave them away. Had the leak
    audit been trusted as done-pending-review, this repository would have gone
    public with no pre-publication leak scan.

    Returns "" when the task genuinely launched, so this never fires on the
    ordinary path.
    """

    attempts = entry.get("delivery_attempt_count")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts > 0:
        return ""
    if entry.get("started_at") or entry.get("delivery_worker_id"):
        return ""
    if str(entry.get("delivery_state") or "") != "terminal":
        return ""
    status = str(entry.get("status") or "")
    # superseded/cancelled/blocked are HONEST zero-attempt outcomes: they say
    # plainly that nothing ran. Only the ones that read as finished mislead.
    if status not in {"review-required", "complete", "closed"}:
        return ""
    return (
        f"NEVER LAUNCHED: 0 delivery attempts, no worker, no start time -- but status is "
        f"`{status}`, which reads as finished work. This task produced NOTHING. "
        "Read the response envelope for the pre-launch refusal reason."
    )


def promoted_artifact_statement(entry: dict[str, Any]) -> str:
    """Name the promoted return_artifact when it is present on disk.

    A board artifact is promoted to the packet's `return_artifact` path, and
    those paths live under `_state/` -- which is gitignored. So a completely
    successful promotion leaves NOTHING in git, and the branch-evidence check
    below cannot see it by construction.

    That mismatch made `preserved_work_statement` tell the reader to run
    `git log -1 <ref>` on four terminal receipts in one day (2026-08-13:
    1090, 1110, 1130, and earlier 0180) while the finished artifact -- 36KB in
    one case -- sat promoted and complete on disk. The advice was not merely
    unhelpful, it pointed at the one place the evidence can never be, so a
    reader who followed it concluded the work was lost.

    Returns "" when there is no artifact path or nothing at it, which lets the
    caller fall through to the git-branch wording that is correct for code.
    """

    artifact = str(entry.get("return_artifact") or "").strip()
    if not artifact:
        return ""
    try:
        path = canonical_vault_root() / artifact
        size = path.stat().st_size
    except (OSError, ValueError):
        return ""
    return f"PROMOTED ARTIFACT: {artifact} is present on disk ({size} bytes)"


def preserved_work_statement(
    task_id: str,
    entry: dict[str, Any],
    diagnostics: dict[str, Any],
) -> str:
    """State whether a terminal failure left recoverable work, and where.

    This NEVER returns an empty string. `blocked: CLI timed out` and `blocked:
    response envelope has invalid frontmatter` are both true and both describe
    the TRANSPORT; neither says whether anything was in it, and a reader
    reasonably concludes nothing was produced. On 2026-08-11 that reading was
    wrong three times in one session -- one of those "failures" had 298
    insertions sitting on a reachable private branch. So every terminal failure
    states a verdict here, including the verdict "this receipt recorded none".
    """

    # A task that never launched is the most misleading state in the system:
    # it reads as finished. Say so before any evidence wording.
    never_ran = never_ran_statement(entry)
    if never_ran:
        return never_ran

    status = str(diagnostics.get("evidence_status") or "")
    ref = str(diagnostics.get("evidence_ref") or "")
    commit = str(diagnostics.get("evidence_commit") or "")
    worktree = str(diagnostics.get("evidence_worktree_location") or "")
    count = diagnostics.get("evidence_preserved_path_count")
    retained_required = diagnostics.get("evidence_worktree_retained_required") is True
    preservation_reason = str(diagnostics.get("evidence_reason") or "")
    out_of_scope_paths = diagnostics.get("evidence_out_of_scope_paths")
    if not isinstance(out_of_scope_paths, list):
        out_of_scope_paths = []
    out_of_scope_count = diagnostics.get("evidence_out_of_scope_path_count")
    if not isinstance(out_of_scope_count, int) or isinstance(out_of_scope_count, bool):
        out_of_scope_count = len(out_of_scope_paths)
    scale = (
        f"{count} path(s)"
        if isinstance(count, int) and not isinstance(count, bool)
        else "work"
    )

    def preservation_statement() -> str:
        if not status:
            # Check the promoted artifact FIRST. It is gitignored, so no amount
            # of git advice can surface it, and it is the usual reason a receipt
            # has no evidence block: the work was promoted, not lost.
            promoted = promoted_artifact_statement(entry)
            conventional = attempt_evidence_ref(task_id, entry)
            if promoted:
                if conventional:
                    return (
                        f"{promoted}. This receipt attached no evidence block, which is "
                        "expected for an artifact under gitignored `_state/`; read the "
                        f"path above. `git log -1 {conventional}` covers only committed "
                        "code and will not show it"
                    )
                return (
                    f"{promoted}. This receipt attached no evidence block, which is "
                    "expected for an artifact under gitignored `_state/`; read the path "
                    "above"
                )
            if not conventional:
                return (
                    "PRESERVED WORK: NOT RECORDED by this receipt, this entry names no "
                    "attempt id so no branch can be named, and no promoted artifact is "
                    "on disk -- do not conclude nothing was produced"
                )
            return (
                "PRESERVED WORK: NOT RECORDED -- this receipt attached no evidence "
                "block and no promoted artifact is on disk; check "
                f"`git log -1 {conventional}` before concluding nothing was produced"
            )

        branch_preserved = status in {
            "preserved",
            "preserved_existing",
            "preserved_partial",
        }
        if branch_preserved and ref and commit:
            statement = (
                f"PRESERVED WORK ({status}): {scale} on {ref}@{commit} -- recover "
                f"with `git show {commit}:<path>`"
            )
        elif worktree and (status != "none" or retained_required):
            statement = (
                f"PRESERVED WORK ({status}): {scale} is NOT on a branch; it is "
                f"retained in the attempt worktree {worktree} -- do not prune it"
            )
        elif status == "none":
            statement = (
                "PRESERVED WORK (none): this receipt recorded no additional "
                "unpromoted work"
            )
        else:
            statement = (
                f"PRESERVED WORK ({status}): recorded, but this receipt names "
                "neither a ref nor a retained worktree"
            )

        if preservation_reason:
            statement += f". Preservation detail: {preservation_reason}"

        must_retain_worktree = (
            retained_required
            or status in {"preserved_partial", "error"}
            or bool(out_of_scope_paths)
        )
        if out_of_scope_paths:
            names = ", ".join(out_of_scope_paths)
            location = worktree or "the retained attempt worktree"
            statement += (
                f". OUT-OF-SCOPE RESIDUE: {out_of_scope_count} path(s) ({names}) "
                f"remain in {location} -- do not prune it"
            )
        elif must_retain_worktree and "do not prune" not in statement:
            location = worktree or "the attempt worktree named by the receipt"
            statement += (
                f". Additional residue remains in {location} -- do not prune it"
            )
        return statement

    # Recovery and preservation describe disjoint subsets and can coexist:
    # recovery proves committed in-scope code landed, while preservation may
    # still protect bridge-owned outputs or residue in the attempt worktree.
    preservation = preservation_statement()
    recovery_status = str(diagnostics.get("work_recovery_status") or "")
    recovery_commit = str(diagnostics.get("work_recovery_commit") or "")
    if recovery_status == "integrated" and recovery_commit:
        recovered_paths = diagnostics.get("work_recovery_paths")
        where = (
            f" ({', '.join(recovered_paths)})"
            if isinstance(recovered_paths, list) and recovered_paths
            else ""
        )
        return (
            f"RECOVERED WORK: this attempt blocked, but its committed code{where} "
            f"was integrated onto the base branch as {recovery_commit}; no "
            f"cherry-pick is needed for that recovered code. {preservation}. "
            "The task stays blocked until it settles on its own merits"
        )
    return preservation


def receipt_failure_diagnostics(receipt: Path) -> dict[str, Any]:
    """Lift a terminal receipt's triage fields into registry-shaped keys.

    ``status`` alone cannot tell a toolchain gate from a policy denial from a
    launch crash: ten distinct ``failure_class`` values all reach the registry
    as ``blocked``. The receipt records the distinction, so triage currently
    means opening JSON by hand and usually does not happen. Fail-open -- a
    missing or malformed receipt costs diagnostics, never a reconcile.
    """

    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    diagnostics: dict[str, Any] = {}
    failure_class = payload.get("failure_class")
    if isinstance(failure_class, str) and failure_class.strip():
        diagnostics["failure_class"] = failure_class.strip()
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        # Receipt reasons embed whole argv lines; collapse and cap so the
        # registry stays readable.
        diagnostics["reason"] = " ".join(reason.split())[
            :RECEIPT_DIAGNOSTIC_REASON_LIMIT
        ]
    returncode = payload.get("returncode")
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        diagnostics["returncode"] = returncode
    # The salvage receipt already records WHERE a terminal failure's work
    # survived. Until now this function read straight past it, so the board
    # computed the answer and never printed it.
    evidence = payload.get("evidence_preservation")
    if isinstance(evidence, dict):
        for source, field in _EVIDENCE_STRING_FIELDS:
            value = evidence.get(source)
            if isinstance(value, str) and value.strip():
                diagnostics[field] = " ".join(value.split())[
                    :RECEIPT_DIAGNOSTIC_REASON_LIMIT
                ]
        count = evidence.get("preserved_path_count")
        if isinstance(count, int) and not isinstance(count, bool):
            diagnostics["evidence_preserved_path_count"] = count
        retained = evidence.get("worktree_retained_required")
        if isinstance(retained, bool):
            diagnostics["evidence_worktree_retained_required"] = retained
        out_of_scope = evidence.get("out_of_scope_paths")
        if isinstance(out_of_scope, list):
            clean = [
                " ".join(path.split())[:RECEIPT_DIAGNOSTIC_REASON_LIMIT]
                for path in out_of_scope
                if isinstance(path, str) and path.strip()
            ][:32]
            if clean:
                diagnostics["evidence_out_of_scope_paths"] = clean
        out_of_scope_count = evidence.get("out_of_scope_path_count")
        if isinstance(out_of_scope_count, int) and not isinstance(
            out_of_scope_count, bool
        ):
            diagnostics["evidence_out_of_scope_path_count"] = out_of_scope_count
    # `work_recovery` (V113-18) records a block whose committed code was
    # nonetheless integrated onto the base branch. It coexists with
    # `evidence_preservation`, so reading only the latter reports recovered
    # work as stranded.
    recovery = payload.get("work_recovery")
    if isinstance(recovery, dict):
        for source, field in (
            ("status", "work_recovery_status"),
            ("integration_commit", "work_recovery_commit"),
        ):
            value = recovery.get(source)
            if isinstance(value, str) and value.strip():
                diagnostics[field] = " ".join(value.split())[
                    :RECEIPT_DIAGNOSTIC_REASON_LIMIT
                ]
        paths = recovery.get("integrated_paths")
        if isinstance(paths, list):
            clean = [p for p in paths if isinstance(p, str) and p.strip()]
            if clean:
                diagnostics["work_recovery_paths"] = clean
    return diagnostics


def apply_receipt_diagnostics(
    entry: dict[str, Any],
    diagnostics: dict[str, Any],
) -> bool:
    """Write diagnostics onto the entry; report whether anything changed.

    A known field absent from `diagnostics` is CLEARED rather than left
    standing. These keys describe one exact attempt's receipt, so carrying a
    previous attempt's evidence ref forward would name a branch that does not
    hold the current work -- a confident wrong answer where there was silence.
    """

    changed = False
    for key in RECEIPT_DIAGNOSTIC_FIELDS:
        field = f"terminal_receipt_{key}"
        if key in diagnostics:
            if entry.get(field) != diagnostics[key]:
                entry[field] = diagnostics[key]
                changed = True
        elif field in entry:
            del entry[field]
            changed = True
    # Total by construction: a key added to the lifter without being declared
    # above is still written, it simply does not get stale-clearing.
    for key, value in diagnostics.items():
        if key in RECEIPT_DIAGNOSTIC_FIELDS:
            continue
        field = f"terminal_receipt_{key}"
        if entry.get(field) != value:
            entry[field] = value
            changed = True
    return changed


def terminal_board_receipt(
    task_id: str,
    entry: dict[str, Any],
    schema: str = "v1",
    descriptor: dict[str, Any] | None = None,
) -> tuple[Path | None, str, str, str | None]:
    """Return a fenced terminal board receipt when no response was promoted.

    The filename and JSON identity must both match the active registry attempt.
    A raw ``failed`` receipt maps to the existing terminal ``blocked`` state
    instead of creating a parallel registry status.
    """

    attempt_id = str(entry.get("delivery_attempt_id") or "")
    if not attempt_id:
        return None, "", "", None
    receipt = (
        STATE_DIR
        / "board-dispatch"
        / f"{task_id}.{attempt_id}.receipt.json"
    )
    if receipt.is_symlink() or not receipt.is_file():
        return None, "", "", None
    if schema == "v2":
        from board_process_truth import load_json, terminal_outcome

        payload = load_json(receipt)
    else:
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None, "", "", None
    if not isinstance(payload, dict):
        return None, "", "", None
    if payload.get("task_id") != task_id or payload.get("attempt_id") != attempt_id:
        return None, "", "", None
    expected_generation = int(entry.get("delivery_generation") or 1)
    receipt_generation = payload.get("generation")
    if schema == "v2":
        completed_at = payload.get("completed_at")
        try:
            strict_outcome = terminal_outcome(payload, descriptor)
        except (AttributeError, TypeError, ValueError):
            return None, "", "", None
        if strict_outcome is None:
            return None, "", "", None
        raw_status = strict_outcome
        status = "blocked" if raw_status in {"failed", "denied"} else raw_status
        return (receipt, status, raw_status, str(completed_at)) if valid_response_status(status) else (None, "", "", None)
    if schema != "v1" or payload.get("schema") not in (None, "board-dispatch-receipt/v1"):
        return None, "", "", None
    # Explicit V1 compatibility: generation-less receipts and mtime completion.
    if (receipt_generation is None and expected_generation > 1) or (
        receipt_generation is not None
        and (type(receipt_generation) is not int or receipt_generation != expected_generation)
    ):
        return None, "", "", None
    raw_status = str(payload.get("status") or "").strip()
    status = "blocked" if raw_status == "failed" else registry_status(raw_status)
    completed_at = datetime.fromtimestamp(receipt.stat().st_mtime, tz=timezone.utc).isoformat()
    return (receipt, status, raw_status, completed_at) if valid_response_status(status) else (None, "", "", None)


def auto_close_terminal_receipt(
    task_id: str,
    entry: dict[str, Any],
    now: datetime,
    receipt_status: str,
    raw_receipt_status: str,
    diagnostics: dict[str, Any] | None = None,
) -> None:
    """Close one non-review terminal receipt using the lifecycle audit shape."""

    history = entry.setdefault("closure_history", [])
    if not isinstance(history, list):
        raise RegistryCorruptError("task has malformed closure_history")
    reason = f"terminal board receipt={raw_receipt_status}"
    diagnostics = diagnostics or {}
    if diagnostics.get("failure_class"):
        reason += f" failure_class={diagnostics['failure_class']}"
    if diagnostics.get("returncode") is not None:
        reason += f" rc={diagnostics['returncode']}"
    if diagnostics.get("reason"):
        reason += f": {diagnostics['reason']}"
    # `closure_reason` is deliberately NOT extended with the preserved-work
    # statement. Its shape is a documented no-drift contract for existing
    # consumers; the durable record of preserved evidence lives in the
    # `terminal_receipt_evidence_*` fields that apply_receipt_diagnostics writes
    # onto this same entry, and the operator-facing statement goes in the
    # notification, which is where it was missing.
    history.append(
        {
            "at": now.isoformat(),
            "from_status": receipt_status,
            "to_status": "closed",
            "reason": reason,
            "by": "registry-reconciler-auto",
        }
    )
    entry["status"] = "closed"
    entry["lifecycle_closed_at"] = now.isoformat()
    entry["lifecycle_closed_by"] = "registry-reconciler-auto"
    entry["closed_from_status"] = receipt_status
    entry["closure_reason"] = reason
    # Free the return_artifact path here too. This is the path that fires on
    # BLOCKED tasks -- exactly when a stub gets written -- so covering only the
    # explicit close left the primary stub-producing route unfixed.
    release_blocked_stub(task_id, entry)


def never_launched_reason(
    task_id: str,
    entry: dict[str, Any],
    now: datetime,
    *,
    candidates: list[Path] | None = None,
) -> str:
    """Return why this task never ran and owes nothing; '' means leave it open.

    Fail-closed by construction: every clause must independently prove the task
    produced no work. Called only after the landed-response and terminal-receipt
    branches have already failed, so those are known absent. See
    ``NEVER_LAUNCHED_GRACE`` for the root cause (friction F5).
    """

    if str(entry.get("status") or "") != "in-flight":
        return ""
    # `queued` is the only state that never reached the supervisor. `claimed` /
    # `in-progress` mean a launch was attempted and may still be running.
    if str(entry.get("delivery_state") or "") != "queued":
        return ""
    if int(entry.get("delivery_attempt_count") or 0) != 0:
        return ""
    if entry.get("claimed_at") or entry.get("started_at"):
        return ""
    # A legacy assigned-worker task may still be waiting on its recorded fence.
    if entry.get("delivery_worker_id"):
        return ""
    # Any response at all (even one too young or with an invalid status) means
    # the earlier branches are the right authority, not this one.
    if candidates is None:
        candidates = response_candidates(task_id)
    if candidates:
        return ""
    artifact = return_artifact_path(task_id, entry)
    if artifact is not None and artifact.exists():
        return ""
    # A provisioned worktree proves the supervisor got as far as launching.
    attempt_id = str(entry.get("delivery_attempt_id") or "")
    if attempt_id and (STATE_DIR / "board-worktrees" / attempt_id).exists():
        return ""
    queued_at = parse_dt(entry.get("dispatched_at")) or parse_dt(
        entry.get("enqueued_at")
    )
    if queued_at is None or now - queued_at < NEVER_LAUNCHED_GRACE:
        return ""
    return (
        f"registered at {queued_at.isoformat()} and never launched: still "
        f"delivery_state=queued with 0 attempts, no response, no return "
        f"artifact, and no attempt worktree after {NEVER_LAUNCHED_GRACE}"
    )


def response_namespace(path: Path) -> str:
    try:
        index = path.parts.index("departments")
        return path.parts[index + 1]
    except (ValueError, IndexError):
        return "unknown"


def response_summary(path: Path) -> str:
    text = read_text(path)
    match = re.match(r"^---\s*\n.*?\n---\s*(?:\n|$)(.*)$", text, re.S)
    body = match.group(1) if match else text
    for paragraph in re.split(r"\n\s*\n", body):
        summary = re.sub(r"\s+", " ", paragraph.strip().lstrip("#").strip())
        if summary:
            return summary[:200]
    return "response envelope landed"


def response_coordination_request(
    path: Path, *, include_legacy: bool = False
) -> tuple[bool, str]:
    """Read the first real coordination section outside Markdown code fences."""

    lines = read_text(path).splitlines()
    fence: str | None = None
    heading_index: int | None = None
    for index, line in enumerate(lines):
        fence_match = _MARKDOWN_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None and (
            _COORDINATION_HEADING_RE.fullmatch(line)
            or include_legacy
            and _LEGACY_NEEDS_HEADING_RE.fullmatch(line)
        ):
            heading_index = index
            break
    if heading_index is None:
        return False, ""

    section: list[str] = []
    fence = None
    for line in lines[heading_index + 1 :]:
        fence_match = _MARKDOWN_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None and _MARKDOWN_HEADING_RE.match(line):
            break
        if fence is None:
            section.append(line)
    summary = re.sub(r"\s+", " ", " ".join(section)).strip()
    summary = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", summary)
    return True, (summary[:200] if summary else response_summary(path))


def apply_worker_outcome_metadata(
    entry: dict[str, Any],
    *,
    reported_status: str,
    coordination_requested: bool,
    coordination_source: str = "",
    coordination_summary: str = "",
) -> bool:
    """Persist raw worker provenance and the independent coordination fact."""

    changed = False
    if reported_status and entry.get("worker_reported_status") != reported_status:
        entry["worker_reported_status"] = reported_status
        changed = True
    desired: dict[str, Any] = {}
    if coordination_requested:
        desired = {
            "coordination_requested": True,
            "coordination_request_source": coordination_source,
            "coordination_request_summary": coordination_summary,
        }
    for key in (
        "coordination_requested",
        "coordination_request_source",
        "coordination_request_summary",
    ):
        if key in desired:
            if entry.get(key) != desired[key]:
                entry[key] = desired[key]
                changed = True
        elif key in entry:
            del entry[key]
            changed = True
    return changed


def coordination_summary_due(
    entry: dict[str, Any],
    task_id: str,
    now: datetime,
) -> str:
    """Return newly due coordination text, or an empty string."""

    if not entry.get("coordination_requested"):
        return ""
    if not coordination_notification_due(entry, task_id, now):
        return ""
    summary = str(entry.get("coordination_request_summary") or "").strip()
    if not summary:
        summary = "worker completed and requested nonblocking Chrono coordination"
    return summary


def append_coordination_event(
    events: list[tuple[str, str, str, str]],
    entry: dict[str, Any],
    task_id: str,
    namespace: str,
    now: datetime,
) -> bool:
    """Queue coordination separately from completion; return whether keyed."""

    summary = coordination_summary_due(entry, task_id, now)
    if not summary:
        return False
    events.append(
        (
            COORDINATION_REQUESTED,
            f"{namespace}/{task_id}",
            summary,
            f"COORDINATION REQUESTED: {task_id} is complete; {summary}",
        )
    )
    return True


def append_terminal_event(
    events: list[tuple[str, str, str, str]],
    entry: dict[str, Any],
    task_id: str,
    namespace: str,
    now: datetime,
    status: str,
    summary: str,
    nudge: str,
    coordination_queue_records: list[tuple[str, str, str]] | None = None,
) -> bool:
    """Append one terminal event, coalescing simultaneous coordination.

    Coordination is folded into the terminal event only when both facts become
    newly due on this pass.  The fallback branch preserves a distinct
    coordination event if a future caller reaches this helper after the terminal
    event is no longer due; current call sites transition out of their re-entry
    conditions after one call. Promoted-response callers may also retain the
    separate coordination fact as a queue-only audit record without adding a
    second operator event.
    """

    if not notification_due(entry, task_id, status, now):
        return append_coordination_event(events, entry, task_id, namespace, now)
    coordination = coordination_summary_due(entry, task_id, now)
    if coordination:
        if coordination_queue_records is not None:
            coordination_queue_records.append(
                (
                    COORDINATION_REQUESTED,
                    f"{namespace}/{task_id}",
                    coordination,
                )
            )
        summary = f"{summary}; coordination requested: {coordination}"
        nudge = f"{nudge} Coordination requested: {coordination}."
    events.append((status, f"{namespace}/{task_id}", summary, nudge))
    return True


def capability_response_issue(entry: dict[str, Any], response: Path) -> str:
    """Return a pin-echo failure; empty means the dispatched snapshot matches."""
    pinned = str(entry.get("capability_card_sha256") or "").strip()
    if not pinned:
        return ""
    echoed = strip_frontmatter(read_text(response)).get(
        "capability_card_sha256", ""
    ).strip()
    if not echoed:
        return "missing capability_card_sha256 echo"
    if echoed != pinned:
        return f"capability_card_sha256 mismatch: dispatched={pinned} response={echoed}"
    return ""


def worker_response_issue(
    task_id: str,
    entry: dict[str, Any],
    response: Path,
    schema: str = "v1",
) -> str:
    """Return a worker-fence echo failure; empty means the response is current."""
    if not entry.get("delivery_worker_id"):
        return ""
    state = str(entry.get("worker_assignment_state") or "")
    if state in {"expired", "silent"} or entry.get("worker_cancel_reason"):
        return f"worker assignment is terminal: {state}"
    expiry = parse_dt(entry.get("lease_expires_at"))
    if expiry is None:
        return "assigned worker task is missing lease_expires_at"
    if schema == "v1" and datetime.fromtimestamp(
        response.stat().st_mtime, tz=timezone.utc
    ) > expiry:
        return "response landed after worker lease expiry"

    meta = strip_frontmatter(read_text(response))
    target = meta.get("in_response_to", "").strip()
    if not target:
        return "missing in_response_to task-fence echo"
    if target != task_id:
        return f"in_response_to mismatch: assigned={task_id} response={target}"
    expected_strings = {
        "delivery_attempt_id": str(entry.get("delivery_attempt_id") or ""),
        "delivery_worker_id": str(entry.get("delivery_worker_id") or ""),
        "worker_epoch": str(entry.get("worker_epoch") or ""),
        "delivery_lane": _delivery_lane(entry),
    }
    for key, expected in expected_strings.items():
        observed = meta.get(key, "").strip()
        if not observed:
            return f"missing {key} worker-fence echo"
        if observed != expected:
            return f"{key} mismatch: assigned={expected} response={observed}"
    expected_ints = {
        "delivery_generation": int(entry.get("delivery_generation") or 1),
        "lease_generation": int(entry.get("lease_generation") or 0),
    }
    if entry.get("replica_index") is not None:
        expected_ints["replica_index"] = int(entry["replica_index"])
    for key, expected in expected_ints.items():
        observed = meta.get(key, "").strip()
        if not observed:
            return f"missing {key} worker-fence echo"
        try:
            parsed = int(observed)
        except ValueError:
            return f"invalid {key} worker-fence echo: {observed!r}"
        if parsed != expected:
            return f"{key} mismatch: assigned={expected} response={parsed}"
    if entry.get("member_id") is not None:
        expected_member = str(entry["member_id"])
        observed_member = meta.get("member_id", "").strip()
        if not observed_member:
            return "missing member_id worker-fence echo"
        if observed_member != expected_member:
            return (
                f"member_id mismatch: assigned={expected_member} "
                f"response={observed_member}"
            )
    return ""




# A lowercase 64-hex digest, not glued to further hex on either side.
_SHA256_TOKEN_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])")

# Prose that names a digest as an ARTIFACT BUNDLE specifically. Deliberately
# narrow: a response body quotes commit hashes, contract hashes and blob hashes
# constantly, and holding a task over one of those would be a false accusation
# rather than a safety margin.
# The gap deliberately allows ordinary words ("the artifact bundle hash is X"):
# an earlier hex-only gap matched a backticked digest but not that sentence,
# which is most of how humans actually write it. Lazy and same-line bounded, so
# the nearest digest within 40 characters is the one claimed.
_BUNDLE_PROSE_RE = re.compile(
    r"artifact[\s_\-]*bundle(?:[\s_\-]*sha256)?[^\n]{0,40}?"
    r"((?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F]))",
    re.IGNORECASE,
)

# A file that can bind a bundle digest to bytes: the run manifest or the
# artifact list that enumerates {path, sha256, role} tuples.
_MANIFEST_NAME_RE = re.compile(r"(manifest|artifact-list).*\.json$", re.IGNORECASE)

# Hard cap on directory entries examined per task, so a broad write_scope cannot
# turn one reconcile pass into a filesystem crawl. Exhausting it means "could not
# determine", NOT "unresolvable" -- accusing a response because our own scan
# budget ran out would be a hold we cannot justify.
DECLARED_HASH_SCAN_FILE_LIMIT = 2048


def declared_bundle_hashes(response: Path) -> list[str]:
    """Digests this response offers as its artifact-bundle identity."""

    text = read_text(response)
    declared: list[str] = []
    frontmatter = (
        strip_frontmatter(text).get("artifact_bundle_sha256", "").strip().lower()
    )
    if _SHA256_TOKEN_RE.fullmatch(frontmatter):
        declared.append(frontmatter)
    for match in _BUNDLE_PROSE_RE.finditer(text):
        value = match.group(1).lower()
        if value not in declared:
            declared.append(value)
    return declared


def declared_hash_search_roots(entry: dict[str, Any]) -> list[Path]:
    """The task's own declared output territory, where its manifest belongs.

    Bounded to `return_artifact` and `write_scope` on purpose. A reviewer
    handed a bundle digest looks where the task was authorised to write; if the
    manifest is not there, the reviewer cannot find it either, and neither
    should this check pretend to.
    """

    roots: list[Path] = []
    candidates = [str(entry.get("return_artifact") or "")]
    scope = entry.get("write_scope")
    if isinstance(scope, list):
        candidates.extend(str(item) for item in scope)
    for raw in candidates:
        raw = raw.strip()
        if not raw or raw.startswith("/") or ".." in raw.split("/"):
            continue
        target = VAULT_ROOT / raw
        directory = target if target.is_dir() else target.parent
        if directory.is_dir() and directory not in roots:
            roots.append(directory)
    return roots


def bundle_declaring_file(entry: dict[str, Any], digest: str) -> str | None:
    """Find a reachable manifest declaring `digest`.

    Returns its repo-relative path, "" when the task's own output territory
    demonstrably does not declare it, or None when the scan budget ran out
    before that could be established. None is the fail-open answer: a hold has
    to rest on evidence that the digest is unbacked, never on our own timeout.
    """

    examined = 0
    for root in declared_hash_search_roots(entry):
        for path in root.rglob("*.json"):
            examined += 1
            if examined > DECLARED_HASH_SCAN_FILE_LIMIT:
                return None
            if path.is_symlink() or not path.is_file():
                continue
            if not _MANIFEST_NAME_RE.search(path.name):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(payload, dict)
                and str(payload.get("artifact_bundle_sha256") or "").lower() == digest
            ):
                return str(path.relative_to(VAULT_ROOT))
    return ""


def declared_hash_issue(entry: dict[str, Any], response: Path) -> str:
    """Refuse to settle a response on a digest that resolves to nothing.

    TASK-2026-08-11-0180 settled `complete` declaring an artifact bundle whose
    manifest was never reachable from the repository. Its pinned contract set
    `deliverable_review_policy.subject = artifact_bundle_sha256`, so the review
    that approved it was a review of a subject nobody could open. A hash
    pointing at bytes no one can produce reads as rigour and carries none.

    This HOLDS; it never drops. The response file is untouched, the registry is
    kept OPEN, and the issue clears the moment the manifest lands or the
    unbacked digest is removed -- because the lesson of TASK-2026-08-11-0490 is
    that rejecting an envelope destroyed a complete deliverable.
    """

    declared = declared_bundle_hashes(response)
    if not declared:
        return ""
    unresolvable = [
        digest
        for digest in declared
        if bundle_declaring_file(entry, digest) == ""
    ]
    if not unresolvable:
        return ""
    roots = declared_hash_search_roots(entry)
    where = ", ".join(str(root.relative_to(VAULT_ROOT)) for root in roots)
    return (
        "declared artifact bundle "
        + ", ".join(unresolvable)
        + " resolves to nothing reachable: no manifest declares it under "
        + (where or "any declared output path for this task")
    )


def update_capability_card_drift(
    entry: dict[str, Any], now: datetime
) -> tuple[bool, bool]:
    """Record current-card drift without changing the immutable dispatch pin."""
    pinned = str(entry.get("capability_card_sha256") or "").strip()
    capability_id = str(entry.get("capability_id") or "").strip()
    if not pinned:
        return False, False
    current = "missing"
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*", capability_id):
        card = VAULT_ROOT / "shared" / "capabilities" / f"{capability_id}.md"
        if card.is_file() and not card.is_symlink():
            try:
                current = hashlib.sha256(card.read_bytes()).hexdigest()
            except OSError:
                current = "missing"
    drift = current != pinned
    previous_drift = entry.get("capability_card_drift")
    changed = (
        entry.get("capability_card_current_sha256") != current
        or previous_drift != drift
    )
    if changed:
        entry["capability_card_current_sha256"] = current
        entry["capability_card_drift"] = drift
        entry["capability_card_drift_checked_at"] = now.isoformat()
    return changed, drift and previous_drift is not True


def task_packet_candidates(task_id: str) -> list[Path]:
    candidates: list[Path] = []
    for state in ("inbox", "active", "archive"):
        candidates.extend(
            path
            for path in _mailbox_file_candidates(state, task_id)
            if path.is_file() and not path.is_symlink()
        )
    return list(dict.fromkeys(candidates))


def return_artifact_path(task_id: str, entry: dict[str, Any]) -> Path | None:
    raw = str(entry.get("return_artifact") or "").strip()
    learned_from_packet = False
    if not raw:
        for packet in task_packet_candidates(task_id):
            raw = strip_frontmatter(read_text(packet)).get("return_artifact", "").strip()
            if raw:
                learned_from_packet = True
                break
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
        if (
            not path.parts
            or path == Path(".")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            return None
        root = VAULT_ROOT.resolve(strict=True)
        candidate = path if path.is_absolute() else VAULT_ROOT / path
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved == root:
        return None
    if learned_from_packet:
        entry["return_artifact"] = raw
    return resolved


def _lane(value: Any) -> str:
    lane = str(value or "").strip().lower()
    return "gpt-codex" if lane == "codex" else lane


def _specialist_primary_lane(specialist: str) -> str:
    """Primary lane (registry spelling) for a specialist from the runtime map."""
    if not specialist:
        return ""
    try:
        with RUNTIME_MAP_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if parts and parts[0] == specialist and len(parts) >= 7:
                    return _lane(parts[6])
    except OSError:
        return ""
    return ""


def _is_read_only_review_task(entry: dict[str, Any]) -> bool:
    """True only for an explicitly read-only task owned by a verdict role."""
    specialist = str(entry.get("specialist") or "").strip()
    return specialist in REVIEW_VERDICT_SPECIALISTS and entry.get("write_scope") == []


def _review_class(entry: dict[str, Any]) -> str:
    """Read the settlement class, refusing rather than assuming the weakest one.

    This is the read side of the same defect ``canonical_review_class`` closes
    on the write side: mapping an absent or unrecognized value onto
    ``standard`` here would let a task that demanded a security-finding or
    factual review settle on an ordinary one. An entry whose class cannot be
    read is held, not settled.
    """

    return canonical_review_class(
        entry.get("review_class"), source="registry entry"
    )


def _entry_author_family(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("author_family") or "").strip().lower()
    if explicit:
        return explicit
    contract = entry.get("verification_contract")
    if isinstance(contract, dict):
        contracted = str(contract.get("author_family") or "").strip().lower()
        if contracted:
            return contracted
    return LANE_AUTHOR_FAMILY.get(_lane(entry.get("to_model")), "")


def _response_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_factual_attestation(
    task_id: str,
    entry: dict[str, Any],
    response: Path,
    review_path: Path,
) -> None:
    meta = strip_frontmatter(read_text(review_path))
    if meta.get("from", "").strip().lower() != "chrono":
        raise ValueError("factual coordinator attestation must be authored by from: chrono")
    if meta.get("type", "").strip().upper() != "REVIEW_ATTESTATION":
        raise ValueError("factual coordinator attestation requires type: REVIEW_ATTESTATION")
    if meta.get("review_class", "").strip().lower() != "factual":
        raise ValueError("factual coordinator attestation must echo review_class: factual")
    if meta.get("in_response_to", "").strip() != task_id:
        raise ValueError("factual coordinator attestation must target the held task")
    if registry_status(meta.get("status", "")) != "complete":
        raise ValueError("factual coordinator attestation status must be complete")
    reviewer_lane = _lane(meta.get("reviewer_lane"))
    required_lane = _lane(entry.get("review_model"))
    if not reviewer_lane or reviewer_lane != required_lane:
        raise ValueError("factual coordinator attestation reviewer_lane must match review_model")
    reviewer_family = str(meta.get("reviewer_family") or "").strip().lower()
    expected_family = LANE_AUTHOR_FAMILY.get(reviewer_lane, "")
    author_family = _entry_author_family(entry)
    if not reviewer_family or reviewer_family != expected_family:
        raise ValueError("factual coordinator attestation has invalid reviewer_family")
    if not author_family or reviewer_family == author_family:
        raise ValueError("factual coordinator attestation must be cross-family")
    attested_hash = meta.get("attested_response_sha256", "").strip().lower()
    if attested_hash != _response_sha256(response):
        raise ValueError("factual coordinator attestation response hash mismatch")


def _validate_security_review(
    task_id: str,
    entry: dict[str, Any],
    response: Path,
    review_path: Path,
) -> None:
    meta = strip_frontmatter(read_text(review_path))
    if meta.get("from", "").strip().lower() == "chrono" \
        or meta.get("type", "").strip().upper() == "REVIEW_ATTESTATION":
        raise ValueError("security-finding tasks require an independent lane review")
    if meta.get("in_response_to", "").strip() != task_id:
        raise ValueError("security-finding review must target the held task")
    reviewer_lane = _lane(meta.get("from"))
    required_lane = _lane(entry.get("review_model"))
    if not reviewer_lane or reviewer_lane != required_lane:
        raise ValueError("security-finding review must come from the configured review_model")
    reviewer_family = LANE_AUTHOR_FAMILY.get(reviewer_lane, "")
    echoed_family = str(meta.get("reviewer_family") or reviewer_family).strip().lower()
    author_family = _entry_author_family(entry)
    if not reviewer_family or echoed_family != reviewer_family:
        raise ValueError("security-finding review has invalid reviewer family")
    if not author_family or reviewer_family == author_family:
        raise ValueError("security-finding review must be cross-family")
    reviewed_hash = meta.get("reviewed_response_sha256", "").strip().lower()
    if reviewed_hash != _response_sha256(response):
        raise ValueError("security-finding review response hash mismatch")
    if registry_status(meta.get("status", "")) != "complete":
        raise ValueError("security-finding review status must be complete")


def cross_family_review_pending(entry: dict[str, Any]) -> tuple[bool, str, str]:
    mandatory = str(entry.get("mandatory_review", "")).strip().lower() == "true"
    raw_triggers = entry.get("review_triggers")
    if raw_triggers is not None:
        try:
            trigger_required = bool(
                canonical_review_triggers(raw_triggers, source="registry entry")
            )
        except ValueError:
            # A malformed review contract is held, never downgraded to no review.
            trigger_required = True
        mandatory = mandatory or trigger_required
    if not mandatory:
        return (False, "", "")
    review_lane = _lane(entry.get("review_model"))
    executing_lane = _lane(entry.get("to_model")) \
        or _specialist_primary_lane(str(entry.get("specialist") or ""))
    if review_lane in ("", "none"):
        return (True, executing_lane or "unknown", INVALID_REVIEW_LANE)
    if not executing_lane:
        return (True, "unknown", review_lane)
    if executing_lane == review_lane:
        return (True, executing_lane, review_lane)
    try:
        readable_class = _review_class(entry)
    except ValueError:
        # An entry whose class cannot be read is held, never exempted. This
        # runs over every entry in a sweep, so it answers "review pending"
        # rather than raising: strictest outcome, no sweep-wide crash.
        return (True, executing_lane, review_lane)
    if readable_class != "standard":
        return (True, executing_lane, review_lane)
    if _is_read_only_review_task(entry):
        # A review of a read-only review creates an infinite regress. The exact
        # role allowlist and explicit empty write scope keep this exemption
        # narrow; implementation-bearing reviewer tasks are not exempt.
        return (False, executing_lane, review_lane)
    return (True, executing_lane, review_lane)


def review_hold_reason(executing_lane: str, review_lane: str) -> str:
    if review_lane == INVALID_REVIEW_LANE:
        return "invalid mandatory-review contract: distinct-family review_model is missing"
    if executing_lane == review_lane:
        return (
            "invalid mandatory-review anti-affinity: to_model and review_model are both "
            f"{review_lane}; redispatch with a distinct-family review_model"
        )
    return f"awaiting explicit Chrono settlement after {review_lane} review"


def review_hold_next_action(executing_lane: str, review_lane: str) -> str:
    if review_lane == INVALID_REVIEW_LANE or executing_lane == review_lane:
        return "Correct the packet contract and redispatch; this invalid entry cannot be review-settled"
    return (
        f"Dispatch/read the {review_lane} review, then use registry_reconciler.py "
        "--settle-review with its review ref"
    )


def response_review_pending(
    entry: dict[str, Any], response_status: str
) -> tuple[bool, str, str]:
    pending, executing_lane, review_lane = cross_family_review_pending(entry)
    if pending or response_status != "needs_review":
        return pending, executing_lane, review_lane
    if str(entry.get("mandatory_review", "")).strip().lower() != "true":
        return pending, executing_lane, review_lane
    if review_lane in {"", "none"} or executing_lane == review_lane:
        return pending, executing_lane, review_lane
    if _is_read_only_review_task(entry):
        return pending, executing_lane, review_lane
    return True, executing_lane, review_lane


def _review_reference(raw: str) -> tuple[Path, str]:
    """Resolve an explicit review reference to a mailbox response file."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = VAULT_ROOT / path
    if path.is_symlink():
        raise ValueError("--review-ref must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(VAULT_ROOT.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError("--review-ref must name an existing mailbox response") from exc
    parts = relative.parts
    if (
        not resolved.is_file()
        or len(parts) != 4
        or parts[0] != "departments"
        or parts[2] not in {"outbox", "archive"}
        or not parts[3].endswith("-response.md")
    ):
        raise ValueError("--review-ref must name an outbox/archive response inside VAULT_ROOT")
    return resolved, str(relative)


def review_verdict(review_path: Path) -> str:
    """Return the normalized structured verdict from a review response."""
    return strip_frontmatter(read_text(review_path)).get("verdict", "").strip().upper()


# The three queue statuses this handler can write. They are distinct
# because `memory_metrics.promotion_events` -- the alarm that notices the
# promotion handler has stopped firing -- counts `MEMORY_PROMOTION_STATUS`
# lines and nothing else. When all three outcomes shared one status, an
# unset `CHRONO_VAULT_ROOT` at settlement made the alarm report "the handler
# fired" on a machine that had never promoted anything: the alarm counted
# its own failures as successes. A skip and a failure stay LOUD in the queue
# -- an event handler that fails silently is what this design replaced --
# they simply do not wear the status that means "notes moved".
# `scripts/python/tests/test_memory_metrics.py` pins the metric to these.
MEMORY_PROMOTION_STATUS = "MEMORY-PROMOTION"
MEMORY_PROMOTION_SKIPPED_STATUS = "MEMORY-PROMOTION-SKIPPED"
MEMORY_PROMOTION_FAILED_STATUS = "MEMORY-PROMOTION-FAILED"


def memory_promotion_message(
    task_id: str, verdict: str, review_class: str
) -> tuple[str, str] | None:
    """Promote the memory this task cited, and never let that block a receipt.

    Returns `(queue_status, summary)` for the caller to append verbatim, or
    `None` when the gate simply said no and there is nothing to report.

    Memory bookkeeping is not allowed to break task settlement, so every
    failure returns a message instead of propagating. It returns a message
    rather than swallowing quietly: an event handler that fails silently is
    the exact defect this handler exists to replace -- curation and usage
    telemetry both stopped on 2026-07-25 and nothing noticed for 23 days.
    The status distinguishes the three outcomes so a reader -- and the
    doctor's alarm -- can tell "promoted" from "could not promote".

    `task_id` is the authenticated identity held under the registry lock,
    not a worker's self-declared label. See `memory_promotion` for why that
    distinction decides the direction of every failure here.

    The import is local and inside the guard on purpose. A module-level one
    would make `memory_promotion.py` a hard dependency of every reconciler
    invocation -- including the minimal fixture trees that stage the
    reconciler's imports by hand (`doctor_fixture._RECONCILER_MODULES`,
    `test_capability_dispatch_integrity.install_board_rail_fixture`), where
    an unstaged module turns a settlement into an exit-1. Memory
    bookkeeping is not allowed to break settlement, and that has to hold
    for a missing module too, not just a failing promotion.
    """
    try:
        import memory_promotion  # noqa: PLC0415

        vault_root = os.environ.get("CHRONO_VAULT_ROOT")
        if not vault_root:
            return (
                MEMORY_PROMOTION_SKIPPED_STATUS,
                "memory promotion skipped: CHRONO_VAULT_ROOT is unset",
            )
        promoted = memory_promotion.promote_cited_notes(
            task_id, verdict, review_class, Path(vault_root)
        )
        if not promoted:
            return None
        return (
            MEMORY_PROMOTION_STATUS,
            f"promoted {len(promoted)} memory note(s) to verified: "
            + ", ".join(promoted),
        )
    except Exception as exc:  # never let memory bookkeeping break settlement
        return (MEMORY_PROMOTION_FAILED_STATUS, f"memory promotion failed: {exc}")


def require_approval_verdict(review_path: Path, force: bool) -> tuple[str, bool]:
    """Fail closed unless the structured review verdict is exactly APPROVE."""
    verdict = review_verdict(review_path)
    forced_override = verdict != "APPROVE" and force
    if verdict != "APPROVE" and not force:
        raise ValueError(
            "review response verdict must be exactly APPROVE; "
            f"observed {verdict or 'MISSING'} (use explicit --force to override)"
        )
    return verdict or "MISSING", forced_override


def _standard_review_provenance(
    registry: dict[str, Any], review_path: Path
) -> tuple[str, str, str, str]:
    """Return the registry-owned review task, target, lane, and family.

    A review response is worker-authored, so neither its ``in_response_to``
    nor its optional ``reviews`` / ``reviewer_family`` echoes can establish
    which held task it was dispatched to review or which provider family
    authored it.  The response filename identifies the separately dispatched
    review task; that task's registry entry owns both facts.
    """

    suffix = "-response.md"
    filename = review_path.name
    review_task_id = filename[: -len(suffix)] if filename.endswith(suffix) else ""
    if not review_task_id:
        raise ValueError("standard review response has no registry task identity")
    review_entry = registry.get(review_task_id)
    if not isinstance(review_entry, dict):
        raise ValueError(
            f"standard review task is absent from the registry: {review_task_id}"
        )
    raw_target = review_entry.get("reviews")
    if raw_target is None:
        # Before registry projection existed, send-task.sh still registered the
        # review task and retained its terminal row, but omitted the packet's
        # `reviews` field. Recover only from that controller-authored packet;
        # the review response remains an assertion and is never a fallback.
        raw_target = _project_review_packet_provenance(
            review_task_id, review_entry
        )
    if not isinstance(raw_target, str) or not raw_target.strip():
        raise ValueError(
            "standard review task registry entry is missing reviews provenance: "
            f"{review_task_id}"
        )
    review_target = raw_target.strip()
    reviewer_lane = _lane(review_entry.get("to_model"))
    if not reviewer_lane:
        raise ValueError(
            "standard review task registry entry is missing its reviewer lane: "
            f"{review_task_id}"
        )
    reviewer_family = LANE_AUTHOR_FAMILY.get(reviewer_lane, "")
    if not reviewer_family:
        raise ValueError(
            "standard review task registry lane has no author family: "
            f"{reviewer_lane}"
        )
    return review_task_id, review_target, reviewer_lane, reviewer_family


def _validate_standard_review(
    task_id: str,
    entry: dict[str, Any],
    review_path: Path,
    registry: dict[str, Any],
) -> None:
    """Require a registry-targeted, configured, cross-family lane review."""
    meta = strip_frontmatter(read_text(review_path))
    if meta.get("from", "").strip().lower() == "chrono" \
        or meta.get("type", "").strip().upper() == "REVIEW_ATTESTATION":
        raise ValueError("standard review requires an independent lane response")
    if meta.get("type", "").strip().upper() != "RESULT":
        raise ValueError("standard review must be a RESULT response")
    (
        review_task_id,
        reviewed_target,
        reviewer_lane,
        reviewer_family,
    ) = _standard_review_provenance(registry, review_path)
    if reviewed_target != task_id:
        raise ValueError(
            "standard review registry provenance targets a different held task: "
            f"review={review_task_id} expected={task_id} observed={reviewed_target}"
        )
    echoed_target = meta.get("reviews", "").strip()
    if echoed_target and echoed_target != reviewed_target:
        raise ValueError(
            "standard review response reviews conflicts with registry provenance: "
            f"expected={reviewed_target} observed={echoed_target}"
        )
    echoed_lane = _lane(meta.get("from"))
    if not echoed_lane:
        raise ValueError("standard review response is missing from")
    if echoed_lane != reviewer_lane:
        raise ValueError(
            "standard review response from conflicts with registry reviewer lane: "
            f"expected={reviewer_lane} observed={echoed_lane}"
        )
    required_lane = _lane(entry.get("review_model"))
    if not reviewer_lane or reviewer_lane != required_lane:
        raise ValueError("standard review must come from the configured review_model")
    echoed_family = str(meta.get("reviewer_family") or "").strip().lower()
    author_family = _entry_author_family(entry)
    if echoed_family and echoed_family != reviewer_family:
        raise ValueError(
            "standard review response reviewer_family conflicts with registry "
            f"reviewer lane: expected={reviewer_family} observed={echoed_family}"
        )
    if not author_family or reviewer_family == author_family:
        raise ValueError("standard review must be cross-family")
    if registry_status(meta.get("status", "")) not in {"complete", "needs_review"}:
        raise ValueError("standard review status must be complete or needs_review")


def settle_review(task_id: str, review_ref: str, *, force: bool = False) -> bool:
    """Explicitly settle one held cross-family review under the registry lock.

    Review files have no automatic authority. This command is the trusted Chrono
    action taken only after the controller has read the referenced review and
    decided that the task may close. Returns False for an idempotent retry.
    """
    _review_path, normalized_ref = _review_reference(review_ref)
    # Promotion takes the VAULT's lock, and a schema-stale index can hold that
    # for a full `rebuild_index()` of the corpus. Holding the GLOBAL registry
    # lock for that duration would block every dispatch and every settlement,
    # so a receipt must never wait on memory bookkeeping. Defer the promotion
    # receipt until the registry lock has been released, even if a later queue
    # write raises after the settlement itself has landed.
    deferred_promotion: tuple[str, str, str] | None = None
    try:
        with locked_registry() as _lock:
            registry = load_registry()
            entry = registry.get(task_id)
            if not isinstance(entry, dict):
                raise ValueError(f"unknown registry task: {task_id}")
            if entry.get("status") == "complete" and str(entry.get("review_settled_by") or "").startswith("chrono-"):
                if entry.get("cross_family_review_ref") == normalized_ref:
                    return False
                raise ValueError(f"task already settled with a different review ref: {task_id}")
            current_status = str(entry.get("status") or "")
            if current_status not in {REVIEW_REQUIRED, "needs_review"}:
                raise ValueError(
                    f"task is not {REVIEW_REQUIRED} or needs_review: {task_id}"
                )
            schema, _descriptor = settlement_process(task_id, entry)
            response, status = landed_response(
                task_id, response_candidates(task_id, entry, schema), schema, entry
            )
            if response is None:
                raise ValueError(f"task has no landed response: {task_id}")
            issue = capability_response_issue(entry, response)
            if issue:
                raise ValueError(
                    f"task response does not match dispatched capability snapshot: {issue}"
                )
            if entry.get("envelope_repaired_by") != "chrono-explicit":
                # After a chrono-explicit envelope repair the fence rows were
                # re-derived from THIS entry under the registry lock, so the
                # echo comparison would be self-agreement, and the remaining
                # lease-lifecycle checks are expected to read terminal on a
                # task that already terminally closed once. Chrono vouches
                # explicitly twice on that path (repair, then settle).
                issue = worker_response_issue(task_id, entry, response, schema)
                if issue:
                    raise ValueError(f"task response does not match dispatched worker fence: {issue}")
            if status not in {"complete", "needs_review"}:
                raise ValueError(f"task response status cannot be settled: {status or 'missing'}")
            if normalized_ref == str(response.relative_to(VAULT_ROOT)):
                raise ValueError("--review-ref must not be the task's own response")
            pending, _executing_lane, _review_lane = response_review_pending(entry, status)
            if not pending:
                raise ValueError(f"task does not require cross-family settlement: {task_id}")

            review_class = _review_class(entry)
            if review_class == "factual":
                _validate_factual_attestation(task_id, entry, response, _review_path)
                settled_by = "chrono-factual-attestation"
            elif review_class == "security-finding":
                _validate_security_review(task_id, entry, response, _review_path)
                settled_by = "chrono-explicit-independent"
            else:
                _validate_standard_review(task_id, entry, _review_path, registry)
                settled_by = "chrono-explicit"

            verdict, forced_override = require_approval_verdict(_review_path, force)

            now = datetime.now(timezone.utc)
            update_capability_card_drift(entry, now)
            entry["status"] = "complete"
            entry["completed_at"] = now.isoformat()
            entry["reconciled_at"] = now.isoformat()
            entry["review_settled_at"] = now.isoformat()
            entry["review_settled_by"] = settled_by
            entry["cross_family_review_ref"] = normalized_ref
            entry["review_ref"] = normalized_ref
            entry["verdict"] = verdict
            entry["review_force_override"] = forced_override
            if forced_override:
                entry["review_force_override_at"] = now.isoformat()
            if review_class == "factual":
                entry["coordinator_attestation_ref"] = normalized_ref
            entry["response_path"] = str(response.relative_to(VAULT_ROOT))
            entry.pop("review_blocking_ref", None)
            entry.pop("review_signature", None)
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
            namespace = _canonical_mailbox_label()
            deferred_promotion = (namespace, verdict, review_class)
    finally:
        # Runs only after `locked_registry()` has released.
        if deferred_promotion is not None:
            promotion_namespace, promotion_verdict, promotion_class = deferred_promotion
            append_chrono_queue(
                (
                    "FACTUAL-ATTESTATION-SETTLED-FORCED"
                    if promotion_class == "factual" and forced_override
                    else "FACTUAL-ATTESTATION-SETTLED"
                    if promotion_class == "factual"
                    else "REVIEW-SETTLED-FORCED"
                    if forced_override
                    else "REVIEW-SETTLED"
                ),
                f"{promotion_namespace}/{task_id}",
                "explicit Chrono settlement "
                f"class={promotion_class}; review={normalized_ref}; "
                f"verdict={promotion_verdict}; force={forced_override}",
            )
            promotion = memory_promotion_message(
                task_id, promotion_verdict, promotion_class
            )
            if promotion:
                append_chrono_queue(
                    promotion[0],
                    f"{promotion_namespace}/{task_id}",
                    promotion[1],
                )
    return True


def repair_promoted_envelope(task_id: str) -> bool:
    """Re-render one task's landed outbox response as the canonical envelope.

    Completes a promotion the output bridge started and lost: the bridge
    publishes the return artifact first and the pin-carrying envelope last, so
    a refusal between the two leaves the worker's own well-formed response at
    the canonical outbox path WITHOUT the delivery pins ``landed_response``
    requires -- present on disk, invisible to settlement, and auto-closed
    ``blocked`` over finished work (measured 2026-08-18, ~a dozen tasks).

    "Landed" deliberately keeps meaning *promoted through the trusted bridge*:
    mere presence must never settle a task, because the pins are what stop a
    worker (or any stray writer) from authoring its own settlement. This
    repair preserves that property by construction -- every pin it writes is
    taken from the task's own registry entry under the registry lock, never
    from the file being repaired, and the file must sit at the task's one
    canonical outbox path carrying that task's identity in its frontmatter.
    A blocked stub does not parse as an envelope, so a genuinely failed task
    cannot be "repaired" into a completion.

    Chrono-explicit, like ``--settle-review``. A terminal ``blocked`` /
    ``closed`` / ``superseded`` entry is reopened to ``needs_review`` so the
    normal settlement paths (reconcile sweep, ``--settle-review``) apply.
    Returns False when everything is already canonical (idempotent retry).
    """

    try:
        import dispatch_context_builder as dcb
    except ImportError as exc:  # pragma: no cover - co-located module
        raise ValueError(f"dispatch_context_builder is unavailable: {exc}") from exc
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        # Historical rows from the retired transport require operator-led
        # migration; repairing them as ordinary single tasks would erase their
        # original settlement semantics.
        if entry.get("dispatch_kind") == "swarm":
            raise ValueError(f"retired swarm transport task cannot be repaired: {task_id}")
        current_status = str(entry.get("status") or "")
        if current_status == "complete":
            raise ValueError(f"task is already settled complete: {task_id}")
        responses = [
            path
            for path in _mailbox_file_candidates(
                "outbox", task_id, response=True
            )
            if path.is_file() and not path.is_symlink()
        ]
        if not responses:
            raise ValueError(f"task has no outbox response to repair: {task_id}")
        if len(responses) > 1:
            raise ValueError(
                f"task has multiple outbox responses to repair: {task_id}"
            )
        response_path = responses[0]
        attempt_id = str(entry.get("delivery_attempt_id") or "")
        generation = entry.get("delivery_generation")
        if (
            not attempt_id
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
        ):
            raise ValueError(f"task has no delivery fence to restore: {task_id}")
        lane = dcb.MODEL_TO_LANE.get(_delivery_lane(entry), _delivery_lane(entry))
        if lane not in dcb.LANE_TO_MODEL:
            raise ValueError(f"task has no recognizable delivery lane: {task_id}")
        raw_bytes = response_path.read_bytes()
        try:
            fields, summary = dcb._parse_response_envelope(raw_bytes)
        except dcb.DispatchContextError as exc:
            raise ValueError(f"outbox response is not a repairable envelope: {exc}") from exc
        observed_id = fields.get("id", "").strip()
        observed_target = fields.get("in_response_to", "").strip()
        if (observed_target and observed_target != task_id) or (
            observed_id and observed_id != f"{task_id}-response"
        ):
            raise ValueError(
                "outbox response carries another task's identity: "
                f"{observed_id or observed_target}"
            )
        echo: dict[str, str] = {
            "delivery_attempt_id": attempt_id,
            "delivery_generation": str(generation),
        }
        if entry.get("delivery_worker_id"):
            echo.update(
                {
                    "delivery_worker_id": str(entry.get("delivery_worker_id") or ""),
                    "worker_epoch": str(entry.get("worker_epoch") or ""),
                    "lease_generation": str(int(entry.get("lease_generation") or 0)),
                    "delivery_lane": _delivery_lane(entry),
                }
            )
            for optional in ("replica_index", "member_id"):
                if entry.get(optional) is not None:
                    echo[optional] = str(entry[optional])
        capability_pin = str(entry.get("capability_card_sha256") or "").strip()
        if capability_pin:
            echo["capability_card_sha256"] = capability_pin
        try:
            rendered = dcb._render_response_envelope(
                task_id=task_id,
                lane=lane,
                result_relative=str(
                    entry.get("return_artifact")
                    or fields.get("return_artifact")
                    or ""
                ),
                status=dcb._coerce_status(fields.get("status", "")),
                summary=summary,
                reconciliation_echo=dcb.validate_reconciliation_echo(echo),
            )
        except dcb.DispatchContextError as exc:
            raise ValueError(f"cannot render a canonical envelope: {exc}") from exc
        changed = False
        if rendered != raw_bytes:
            atomic_write(response_path, rendered.decode("utf-8"))
            changed = True
        now = datetime.now(timezone.utc)
        if current_status in {"blocked", "closed", "superseded"}:
            entry["envelope_repaired_from_status"] = current_status
            entry["status"] = "needs_review"
            entry["completed_at"] = None
            entry["reconciled_at"] = None
            changed = True
        if changed:
            entry["envelope_repaired_at"] = now.isoformat()
            entry["envelope_repaired_by"] = "chrono-explicit"
            atomic_write(
                REGISTRY_PATH,
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
            )
            append_chrono_queue(
                "ENVELOPE-REPAIRED",
                f"{_canonical_mailbox_label()}/{task_id}",
                "canonical envelope re-rendered from registry pins; "
                f"prior status={current_status or 'unknown'}",
            )
        return changed


def reopen_task(task_id: str, target_status: str | None = None) -> bool:
    """Reopen one explicitly settled task under the registry lock.

    The default is ``needs_rework`` when a stored non-APPROVE verdict proves the
    prior settlement was an override, otherwise ``needs_review``. Audit fields
    and a reopen history are retained; only the live lifecycle status changes.
    """
    allowed = {"needs_review", "needs_rework"}
    if target_status is not None and target_status not in allowed:
        raise ValueError("--reopen-status must be needs_review or needs_rework")
    now = datetime.now(timezone.utc)
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        stored_verdict = str(entry.get("verdict") or "").strip().upper()
        target = target_status or (
            "needs_rework" if stored_verdict and stored_verdict != "APPROVE" else "needs_review"
        )
        current = str(entry.get("status") or "")
        if current == target and entry.get("reopened_by") == "chrono-explicit":
            return False
        if current != "complete":
            raise ValueError(f"task is not explicitly settled complete: {task_id}")
        history = entry.setdefault("reopen_history", [])
        if not isinstance(history, list):
            raise ValueError(f"task has malformed reopen_history: {task_id}")
        history.append(
            {
                "at": now.isoformat(),
                "from_status": current,
                "to_status": target,
                "completed_at": entry.get("completed_at"),
                "review_settled_at": entry.get("review_settled_at"),
                "review_settled_by": entry.get("review_settled_by"),
                "review_ref": entry.get("review_ref") or entry.get("cross_family_review_ref"),
                "verdict": entry.get("verdict"),
            }
        )
        entry["status"] = target
        entry["completed_at"] = None
        entry["review_settled_at"] = None
        entry["review_settled_by"] = "chrono-reopened"
        entry["reopened_at"] = now.isoformat()
        entry["reopened_by"] = "chrono-explicit"
        entry["reopened_from_status"] = current
        entry["reopen_count"] = int(entry.get("reopen_count") or 0) + 1
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        namespace = _canonical_mailbox_label()
    append_chrono_queue(
        "REVIEW-REOPENED",
        f"{namespace}/{task_id}",
        f"explicit Chrono reopen -> {target}; verdict={stored_verdict or 'MISSING'}",
    )
    return True


BOARD_BLOCKED_STUB_RE = re.compile(
    r"blocked\n\n# Board dispatch blocked — (TASK-[0-9A-Za-z._-]+)\n\n"
    r"Controller reason: [^\r\n]{1,2000}\n"
)


def release_blocked_stub(task_id: str, entry: dict) -> str | None:
    """Free a closed task's return_artifact path so a re-dispatch can promote.

    The promoter's stub-reclaim (`_is_board_blocked_stub` in
    dispatch_context_builder) matches the stub against the *promoting* task's id.
    Supersede-and-redispatch deliberately uses a NEW id, so the stub still names
    the old one, the exact-match fails, and promotion is refused with
    "return artifact destination already differs" -- AFTER the replacement lane
    has done all of its work. Measured four times in one campaign; each cost a
    completed lane its promotion and was recovered only by sweeping the worktree.

    Widening the promoter's match would weaken a real control: it is what stops
    one task clobbering another's artifact. Instead the stub is retired here, at
    close time, where the task is already terminal and the stub is provably dead
    residue rather than someone else's work.

    Renames rather than deletes: the stub is audit history, and deletion is
    operator-gated. Returns the new path, or None if there was nothing to do.
    """
    raw = str(entry.get("return_artifact") or "").strip()
    if not raw:
        return None

    try:
        lexical_root = VAULT_ROOT.absolute()
        resolved_root = VAULT_ROOT.resolve(strict=True)
    except (OSError, RuntimeError):
        return None

    supplied = Path(raw)
    if supplied.is_absolute():
        relative: Path | None = None
        # `VAULT_ROOT` may itself be a symlink. Accept either spelling of an
        # absolute in-vault artifact, but never infer containment from a common
        # string prefix.
        for root_form in (lexical_root, resolved_root):
            try:
                relative = supplied.relative_to(root_form)
                break
            except ValueError:
                continue
        if relative is None:
            return None
    else:
        relative = supplied

    if (
        not relative.parts
        or relative == Path(".")
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None

    # Anchor every lookup to an already-opened vault directory and refuse
    # symlinks at every component. A resolve-then-rename check alone leaves a
    # race in which a parent can be swapped for a symlink after validation.
    # The dir-fd walk also permits the documented absolute-in-vault fallback
    # without ever operating on an absolute path supplied by the registry.
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory_flag:
        return None
    opened: list[int] = []
    try:
        parent_fd = os.open(
            resolved_root,
            os.O_RDONLY | directory_flag | nofollow,
        )
        opened.append(parent_fd)
        for component in relative.parts[:-1]:
            parent_fd = os.open(
                component,
                os.O_RDONLY | directory_flag | nofollow,
                dir_fd=parent_fd,
            )
            opened.append(parent_fd)

        source_name = relative.name
        source_fd = os.open(
            source_name,
            os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        opened.append(source_fd)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            return None
        try:
            with os.fdopen(os.dup(source_fd), "rb") as stream:
                source_bytes = stream.read()
            text = source_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        match = BOARD_BLOCKED_STUB_RE.fullmatch(text)
        if match is None:
            return None  # a real artifact, never touch it
        if match.group(1) != task_id:
            return None  # names a different task; not ours to retire

        retired_name = f"{source_name}.blocked-{task_id}"
        # Re-check that the directory entry still names the file we inspected.
        # The rename remains anchored to the no-follow parent descriptor and is
        # atomic no-replace, so a concurrently-created audit path survives.
        current_stat = os.stat(
            source_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or current_stat.st_dev != source_stat.st_dev
            or current_stat.st_ino != source_stat.st_ino
        ):
            return None
        _rename_noreplace(
            source_name,
            retired_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )

        # Native rename cannot predicate on the source inode. Verify the moved
        # entry still names the exact regular file and bytes inspected above.
        # If a writer replaced or rewrote the source in the narrow pre-rename
        # window, move that entry back with the same no-overwrite primitive.
        moved_valid = False
        try:
            moved_fd = os.open(
                retired_name,
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
            opened.append(moved_fd)
            moved_stat = os.fstat(moved_fd)
            if (
                stat.S_ISREG(moved_stat.st_mode)
                and moved_stat.st_dev == source_stat.st_dev
                and moved_stat.st_ino == source_stat.st_ino
            ):
                with os.fdopen(os.dup(moved_fd), "rb") as stream:
                    moved_valid = stream.read() == source_bytes
        except OSError:
            moved_valid = False
        if not moved_valid:
            try:
                _rename_noreplace(
                    retired_name,
                    source_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
            except OSError:
                pass
            return None
        return str(relative.with_name(retired_name))
    except (OSError, ValueError):
        return None
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


# ── Batch close: all-or-nothing, and never silent about a requested id ───────
# Found in use 2026-08-12: `--close-task A --close-task B` closed B, left A
# open, and printed `closed task=B` -- a success message for a half-applied
# batch. The abort was NOT mid-loop and the preflight was not at fault.
# `--close-task` was declared `nargs="+"` with no accumulating action, so
# argparse OVERWROTE the first occurrence and handed close_task a ONE-id batch;
# A was discarded before this function was ever entered, and the report could
# only name what survived parsing. A 69-test suite missed it because every test
# called close_task(["a", "b", "c"]) directly and so never crossed the argv
# boundary where the id is lost.
#
# Two rules follow, and the tests pin both:
#   1. Repeated flags accumulate, so the batch the operator typed is the batch
#      that gets validated (see `action="extend"` on the argument).
#   2. Every requested id gets its own line in the report -- on success, on
#      idempotent replay, and on refusal. Silence about a requested id is the
#      defect, because it is what makes a partial result look like a whole one.
CLOSE_CLOSED = "closed"
CLOSE_ALREADY = "already-closed"
CLOSE_ELIGIBLE = "eligible"
CLOSE_REFUSED = "REFUSED"


class CloseOutcome:
    """What one batch member's close did, or would have done had the batch run.

    Deliberately a plain class, not a `@dataclass`. `bin/review-loop-guard-
    selftest.py` loads this module via `importlib.spec_from_file_location`
    WITHOUT registering it in `sys.modules`, and `@dataclass` resolves its
    annotations through `sys.modules.get(cls.__module__).__dict__` -- which is
    `None` under that loader, so the decorator raises at import time and takes
    the whole selftest down with it.
    """

    def __init__(self, task_id: str, disposition: str, detail: str) -> None:
        self.task_id = task_id
        self.disposition = disposition
        self.detail = detail
        self.notes: list[str] = []

    def render(self) -> str:
        line = f"  {self.task_id}: {self.disposition} ({self.detail})"
        for note in self.notes:
            line += f"\n      ! {note}"
        return line


class CloseReport:
    """Per-id result of a batch close.

    Truthy exactly when the registry changed, so every existing caller that
    treated `close_task`'s return value as a bool keeps its old meaning; carries
    `outcomes` so the CLI can prove it accounted for every requested member.
    """

    def __init__(self, outcomes: list[CloseOutcome]) -> None:
        self.outcomes = outcomes

    def __bool__(self) -> bool:
        return any(item.disposition == CLOSE_CLOSED for item in self.outcomes)

    @property
    def follow_through_failures(self) -> list[CloseOutcome]:
        return [item for item in self.outcomes if item.notes]

    def render(self) -> list[str]:
        return [item.render() for item in self.outcomes]


class BatchCloseRefused(ValueError):
    """Preflight refused the whole batch; nothing was written.

    Subclasses ValueError so existing `except ValueError` callers are
    unaffected, and aggregates EVERY ineligible member's reason into the message
    rather than raising on the first one found -- a refusal that names only the
    first bad id makes the operator rerun the batch once per defect.
    """

    def __init__(self, message: str, report: CloseReport) -> None:
        super().__init__(message)
        self.report = report


def close_task(
    task_ids: str | list[str],
    reason: str,
    target_status: str = "superseded",
) -> CloseReport:
    """Terminalize one or more stale registry tasks with durable audit records.

    The full batch is validated before any entry is changed, then every changed
    entry is committed in one atomic registry write. Replaying the same terminal
    status and normalized reason is idempotent. A different close request for
    any already closed task fails the entire batch closed so audit history
    cannot be silently rewritten.

    Returns a `CloseReport` holding one outcome per requested id. It is truthy
    exactly when the registry changed, so `bool(close_task(...))` keeps its
    previous meaning; read `.outcomes` to report what happened to each member.
    """
    allowed = {"superseded", "closed"}
    if target_status not in allowed:
        raise ValueError("--close-status must be superseded or closed")
    normalized_reason = re.sub(r"\s+", " ", reason or "").strip()
    if not normalized_reason:
        raise ValueError("--close-reason must be non-empty")
    requested_ids = [task_ids] if isinstance(task_ids, str) else list(task_ids)
    if not requested_ids:
        raise ValueError("--close-task requires at least one task id")
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for raw_task_id in requested_ids:
        task_id = str(raw_task_id).strip()
        if not task_id:
            raise ValueError("--close-task task ids must be non-empty")
        if task_id in seen:
            raise ValueError(f"duplicate --close-task id: {task_id}")
        seen.add(task_id)
        normalized_ids.append(task_id)

    now = datetime.now(timezone.utc)
    plan: dict[str, CloseOutcome] = {}
    with locked_registry() as _lock:
        registry = load_registry()
        prepared: list[tuple[str, dict[str, Any], str, str, bool]] = []
        refusals: list[str] = []

        # Preflight every member before mutating even the in-memory registry.
        # This is the all-or-nothing boundary for an invalid batch member. Every
        # member is judged even after one is found ineligible, so the refusal can
        # name all of them at once instead of one rerun per defect.
        for task_id in normalized_ids:
            entry = registry.get(task_id)
            if not isinstance(entry, dict):
                detail = f"unknown registry task: {task_id}"
                refusals.append(detail)
                plan[task_id] = CloseOutcome(task_id, CLOSE_REFUSED, detail)
                continue
            current = str(entry.get("status") or "")
            namespace = _canonical_mailbox_label()
            if current in allowed:
                if (
                    current == target_status
                    and entry.get("closure_reason") == normalized_reason
                    and entry.get("lifecycle_closed_by") == "chrono-explicit"
                ):
                    prepared.append((task_id, entry, current, namespace, False))
                    plan[task_id] = CloseOutcome(
                        task_id,
                        CLOSE_ALREADY,
                        f"already {current} under this exact reason; no change",
                    )
                    continue
                detail = (
                    f"task is already terminal lifecycle status {current}: {task_id}"
                )
                refusals.append(detail)
                plan[task_id] = CloseOutcome(task_id, CLOSE_REFUSED, detail)
                continue
            history = entry.get("closure_history")
            if history is not None and not isinstance(history, list):
                detail = f"task has malformed closure_history: {task_id}"
                refusals.append(detail)
                plan[task_id] = CloseOutcome(task_id, CLOSE_REFUSED, detail)
                continue
            prepared.append((task_id, entry, current, namespace, True))
            plan[task_id] = CloseOutcome(
                task_id, CLOSE_ELIGIBLE, f"{current} -> {target_status}"
            )

        if refusals:
            # Nothing has been mutated yet -- not even in memory -- so raising
            # here IS the all-or-nothing guarantee. The report travels with the
            # error so the caller can show that no member closed.
            raise BatchCloseRefused(
                "; ".join(refusals),
                CloseReport([plan[task_id] for task_id in normalized_ids]),
            )

        changed_entries: list[tuple[str, dict[str, Any], str]] = []
        for task_id, entry, current, namespace, should_change in prepared:
            if not should_change:
                continue
            history = entry.setdefault("closure_history", [])
            history.append(
                {
                    "at": now.isoformat(),
                    "from_status": current,
                    "to_status": target_status,
                    "reason": normalized_reason,
                    "by": "chrono-explicit",
                }
            )
            entry["status"] = target_status
            entry["lifecycle_closed_at"] = now.isoformat()
            entry["lifecycle_closed_by"] = "chrono-explicit"
            entry["closed_from_status"] = current
            entry["closure_reason"] = normalized_reason
            changed_entries.append((task_id, entry, namespace))

        if changed_entries:
            # One write commits every member. This single call is what makes the
            # registry side of the batch genuinely all-or-nothing: it either
            # renames into place for all of them or for none of them.
            atomic_write(
                REGISTRY_PATH,
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
            )
        for task_id, _entry, current, _namespace, should_change in prepared:
            if should_change:
                plan[task_id] = CloseOutcome(
                    task_id, CLOSE_CLOSED, f"{current} -> {target_status}"
                )

    # Follow-through runs after the durable commit, so a failure here can no
    # longer un-close anything. Aborting the loop would leave the REMAINING
    # members without their archive/stub/queue records -- the same
    # partial-application shape, one layer down -- so each member's failure is
    # recorded against that member and the loop continues. The caller reports
    # every note and exits non-zero; nothing here is swallowed.
    def _follow_through(task_id: str, what: str, action: Any) -> Any:
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - recorded per id, never silent
            plan[task_id].notes.append(
                f"{what} failed after the close committed: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    for task_id, _entry, _current, namespace, _should_change in prepared:
        _follow_through(
            task_id,
            "inbox packet archive",
            lambda task_id=task_id: archive_inbox_packet(task_id),
        )
    for task_id, entry, namespace in changed_entries:
        retired = _follow_through(
            task_id,
            "blocked stub release",
            lambda task_id=task_id, entry=entry: release_blocked_stub(task_id, entry),
        )
        if retired:
            print(
                f"  → retired blocked stub to {retired}; "
                "return_artifact path is free for re-dispatch"
            )
        _follow_through(
            task_id,
            "chrono-queue append",
            lambda task_id=task_id, namespace=namespace: append_chrono_queue(
                f"TASK-{target_status.upper()}",
                f"{namespace}/{task_id}",
                f"explicit Chrono lifecycle close; reason={normalized_reason}",
            ),
        )
    return CloseReport([plan[task_id] for task_id in normalized_ids])


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def append_drift(task_id: str, detail: str) -> None:
    path = STATE_DIR / "cleanup-logs" / f"{utc_date()}-registry-drift.md"
    existing = read_text(path, f"# Registry Drift - {utc_date()}\n\n")
    atomic_write(path, existing + f"- {datetime.now(timezone.utc).isoformat()} {task_id}: {detail}\n")


def marker_recent(task_id: str, now: datetime) -> bool:
    marker = LONG_RUNNING_NOTED_DIR / f"{task_id}.noted"
    try:
        age = now - datetime.fromtimestamp(marker.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return False
    return age < LONG_RUNNING_DEBOUNCE


def touch_marker(task_id: str) -> None:
    LONG_RUNNING_NOTED_DIR.mkdir(parents=True, exist_ok=True)
    marker = LONG_RUNNING_NOTED_DIR / f"{task_id}.noted"
    marker.touch()


def meaningful_lines(text: str, limit: int = 3) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def pane_snapshot(to_model: str) -> tuple[str, str]:
    target = f"{SQUAD_SESSION}:{to_model}"
    try:
        result = subprocess.run(
            [TMUX_BIN, "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown", "pane unreachable"
    if result.returncode != 0:
        return "unknown", "pane unreachable"
    lines = meaningful_lines(result.stdout or "")
    snippet = " / ".join(lines)[:200] if lines else "(pane blank)"
    joined = "\n".join(lines)
    active_re = re.compile(
        r"(Working|Waiting for background|esc to interrupt|Wandering|Thinking|Brewed|Running|Applying patch)",
        re.I,
    )
    idle_re = re.compile(r"(Explain this codebase|^▶|❯|^\$|^%|^>)", re.I | re.M)
    if active_re.search(joined):
        return "active", snippet
    if idle_re.search(joined):
        return "idle", snippet
    return "unknown", snippet


def note_long_running(task_id: str, entry: dict[str, Any], now: datetime, dry_run: bool) -> str | None:
    if entry.get("chrono_reconciled") is True:
        return None
    dispatched = parse_dt(entry.get("dispatched_at"))
    if not dispatched:
        return None
    elapsed = now - dispatched
    if elapsed < LONG_RUNNING_MIN_AGE or elapsed >= LONG_RUNNING_STALE_AGE:
        return None
    if response_candidates(task_id) or marker_recent(task_id, now):
        return None
    namespace = _canonical_mailbox_label()
    to_model = str(entry.get("to_model") or "unknown-model")
    state, snippet = pane_snapshot(to_model)
    if not dry_run:
        append_chrono_queue(f"long-running:{state}", f"{namespace}/{task_id}", snippet)
        touch_marker(task_id)
    return f"long-running:{state} {task_id}"




_COORDINATION_MIGRATION_MUTATED_FIELDS = (
    "status",
    "worker_reported_status",
    "coordination_requested",
    "coordination_request_source",
    "coordination_request_summary",
    "review_disposition",
    "reconciled_at",
    "coordination_notification_key",
    "coordination_notification_state",
    "coordination_notification_delivery_generation",
    "coordination_notification_last_emitted_at",
)


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _queue_record(line: str) -> tuple[str, str, str, str] | None:
    body = line[:-1] if line.endswith("\n") else line
    parts = body.split(" | ", 3)
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def _queue_line_with_status(line: str, status: str) -> str:
    record = _queue_record(line)
    if record is None:
        raise ValueError("coordination migration encountered a malformed queue row")
    timestamp, _status, task_ref, summary = record
    newline = "\n" if line.endswith("\n") else ""
    return f"{timestamp} | {status} | {task_ref} | {summary}{newline}"


def _migration_report(
    *,
    action: str,
    plan_sha256: str,
    items: list[dict[str, Any]],
    registry: dict[str, Any],
    migration_id: str = "",
) -> dict[str, Any]:
    return {
        "schema": COORDINATION_MIGRATION_SCHEMA,
        "action": action,
        "plan_sha256": plan_sha256,
        "migration_id": migration_id,
        "candidate_count": len(items),
        "queue_entry_count": len(items),
        "partially_published_queue_count": sum(
            bool(item.get("queue_already_changed")) for item in items
        ),
        "preserved_needs_human": sum(
            isinstance(entry, dict) and entry.get("status") == "needs_human"
            for entry in registry.values()
        ),
        "preserved_blocked": sum(
            isinstance(entry, dict) and entry.get("status") == "blocked"
            for entry in registry.values()
        ),
        "triggered_needs_review": sum(
            isinstance(entry, dict)
            and entry.get("status") == "needs_review"
            and packet_declares_review(entry)
            for entry in registry.values()
        ),
        "task_ids": [item["task_id"] for item in items],
    }


def _build_coordination_migration_plan(
    registry: dict[str, Any], queue_text: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    targets = {
        task_id
        for task_id, entry in registry.items()
        if isinstance(entry, dict)
        and entry.get("status") == "needs_review"
        and not packet_declares_review(entry)
    }
    queue_lines = queue_text.splitlines(keepends=True)
    matches: dict[str, list[tuple[int, str, str]]] = {
        task_id: [] for task_id in targets
    }
    for index, line in enumerate(queue_lines):
        record = _queue_record(line)
        if record is None:
            continue
        _timestamp, status, task_ref, _summary = record
        task_id = task_ref.rsplit("/", 1)[-1]
        if task_id in matches and status in {
            "needs_review",
            COORDINATION_REQUESTED,
        }:
            matches[task_id].append((index, line, status))

    mismatches = {
        task_id: len(rows) for task_id, rows in matches.items() if len(rows) != 1
    }
    if mismatches:
        detail = ", ".join(
            f"{task_id}={count}" for task_id, count in sorted(mismatches.items())
        )
        raise ValueError(
            "coordination migration requires exactly one needs_review/"
            "COORDINATION-REQUESTED queue row "
            f"per candidate; observed {detail}"
        )

    items: list[dict[str, Any]] = []
    digest_items: list[dict[str, str]] = []
    for task_id in sorted(targets):
        queue_index, observed, observed_status = matches[task_id][0]
        queue_already_changed = observed_status == COORDINATION_REQUESTED
        before = (
            _queue_line_with_status(observed, "needs_review")
            if queue_already_changed
            else observed
        )
        after = (
            observed
            if queue_already_changed
            else _queue_line_with_status(observed, COORDINATION_REQUESTED)
        )
        item = {
            "task_id": task_id,
            "queue_index": queue_index,
            "queue_before": before,
            "queue_after": after,
            "entry_sha256": _canonical_json_sha256(registry[task_id]),
            "queue_already_changed": queue_already_changed,
        }
        items.append(item)
        digest_items.append(
            {
                "task_id": task_id,
                "entry_sha256": item["entry_sha256"],
                "queue_before_sha256": hashlib.sha256(
                    before.encode("utf-8")
                ).hexdigest(),
                "queue_after_sha256": hashlib.sha256(
                    after.encode("utf-8")
                ).hexdigest(),
            }
        )
    plan_sha256 = _canonical_json_sha256(
        {
            "schema": COORDINATION_MIGRATION_SCHEMA,
            "action": "migrate",
            "items": digest_items,
        }
    )
    return (
        _migration_report(
            action="migrate",
            plan_sha256=plan_sha256,
            items=items,
            registry=registry,
        ),
        items,
    )


def _build_coordination_rollback_plan(
    registry: dict[str, Any], queue_text: str, migration_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    digest_items: list[dict[str, str]] = []
    queue_lines = queue_text.splitlines(keepends=True)
    for task_id, entry in sorted(registry.items()):
        if not isinstance(entry, dict):
            continue
        metadata = entry.get(COORDINATION_MIGRATION_FIELD)
        if not isinstance(metadata, dict) or metadata.get("plan_sha256") != migration_id:
            continue
        if metadata.get("schema") != COORDINATION_MIGRATION_SCHEMA:
            raise ValueError(f"task {task_id} has an unknown coordination migration schema")
        if (
            entry.get("status") != "complete"
            or entry.get("coordination_requested") is not True
            or entry.get("worker_reported_status") != "needs_review"
        ):
            raise ValueError(
                f"task {task_id} changed after migration; refusing destructive rollback"
            )
        before = metadata.get("queue_before")
        after = metadata.get("queue_after")
        prior_fields = metadata.get("prior_fields")
        if not isinstance(before, str) or not isinstance(after, str) or not isinstance(
            prior_fields, dict
        ):
            raise ValueError(f"task {task_id} has incomplete rollback metadata")
        after_indexes = [
            index for index, line in enumerate(queue_lines) if line == after
        ]
        before_indexes = [
            index for index, line in enumerate(queue_lines) if line == before
        ]
        if len(after_indexes) + len(before_indexes) != 1:
            raise ValueError(
                f"rollback requires exactly one original/migrated queue row for "
                f"{task_id}; observed {len(before_indexes)} original and "
                f"{len(after_indexes)} migrated"
            )
        queue_already_changed = bool(before_indexes)
        item = {
            "task_id": task_id,
            "queue_index": (
                before_indexes[0] if before_indexes else after_indexes[0]
            ),
            "queue_before": before,
            "queue_after": after,
            "entry_sha256": _canonical_json_sha256(entry),
            "prior_fields": prior_fields,
            "queue_already_changed": queue_already_changed,
        }
        items.append(item)
        digest_items.append(
            {
                "task_id": task_id,
                "entry_sha256": item["entry_sha256"],
                "queue_before_sha256": hashlib.sha256(
                    before.encode("utf-8")
                ).hexdigest(),
                "queue_after_sha256": hashlib.sha256(
                    after.encode("utf-8")
                ).hexdigest(),
            }
        )
    if not items:
        raise ValueError(f"no applied coordination migration found for {migration_id}")
    plan_sha256 = _canonical_json_sha256(
        {
            "schema": COORDINATION_MIGRATION_SCHEMA,
            "action": "rollback",
            "migration_id": migration_id,
            "items": digest_items,
        }
    )
    return (
        _migration_report(
            action="rollback",
            plan_sha256=plan_sha256,
            migration_id=migration_id,
            items=items,
            registry=registry,
        ),
        items,
    )


def _commit_registry_and_queue(
    registry_before: str,
    registry_after: dict[str, Any],
    queue_before: str,
    queue_after: str,
) -> None:
    """Publish both locked files, restoring both originals on an exception."""

    try:
        atomic_write(CHRONO_QUEUE_PATH, queue_after)
        atomic_write(
            REGISTRY_PATH,
            json.dumps(registry_after, indent=2, ensure_ascii=False) + "\n",
        )
    except Exception as exc:
        restore_errors: list[str] = []
        try:
            atomic_write(REGISTRY_PATH, registry_before)
        except Exception as registry_restore_exc:
            restore_errors.append(f"registry: {registry_restore_exc}")
        try:
            atomic_write(CHRONO_QUEUE_PATH, queue_before)
        except Exception as queue_restore_exc:
            restore_errors.append(f"queue: {queue_restore_exc}")
        if restore_errors:
            raise RegistryCorruptError(
                "coordination migration failed after publication and compensating "
                f"restore was incomplete ({'; '.join(restore_errors)})"
            ) from exc
        raise RegistryCorruptError(
            f"coordination migration registry write failed; both files restored: {exc}"
        ) from exc


def migrate_untriggered_needs_review(
    *,
    dry_run: bool,
    apply_plan_sha256: str = "",
    rollback_migration_id: str = "",
) -> dict[str, Any]:
    """Plan/apply/rollback the locked status+queue coordination migration."""

    if apply_plan_sha256 and not re.fullmatch(r"[0-9a-f]{64}", apply_plan_sha256):
        raise ValueError("--apply-plan-sha256 must be lowercase 64-hex")
    if rollback_migration_id and not re.fullmatch(
        r"[0-9a-f]{64}", rollback_migration_id
    ):
        raise ValueError("--rollback-coordination-migration must be lowercase 64-hex")
    if not dry_run and not apply_plan_sha256:
        raise ValueError(
            "apply requires --apply-plan-sha256 from a preceding locked --dry-run"
        )

    with locked_registry() as _registry_lock:
        queue_lock = CHRONO_QUEUE_PATH.with_suffix(
            CHRONO_QUEUE_PATH.suffix + ".lockdir"
        )
        with lockdir(queue_lock):
            registry_text = read_text(REGISTRY_PATH)
            registry = load_registry()
            queue_text = read_text(CHRONO_QUEUE_PATH)
            if rollback_migration_id:
                report, items = _build_coordination_rollback_plan(
                    registry, queue_text, rollback_migration_id
                )
            else:
                report, items = _build_coordination_migration_plan(
                    registry, queue_text
                )
            if dry_run:
                report["outcome"] = "dry-run"
                return report
            if report["plan_sha256"] != apply_plan_sha256:
                already_applied = (
                    not rollback_migration_id
                    and not items
                    and any(
                        isinstance(entry, dict)
                        and isinstance(entry.get(COORDINATION_MIGRATION_FIELD), dict)
                        and entry[COORDINATION_MIGRATION_FIELD].get("plan_sha256")
                        == apply_plan_sha256
                        for entry in registry.values()
                    )
                )
                if already_applied:
                    report["outcome"] = "already-applied"
                    report["migration_id"] = apply_plan_sha256
                    return report
                raise ValueError(
                    "migration plan changed after dry-run; expected "
                    f"{apply_plan_sha256}, observed {report['plan_sha256']}; "
                    "run a fresh --dry-run"
                )
            if not items:
                report["outcome"] = "no-op"
                report["migration_id"] = report["plan_sha256"]
                return report

            now = datetime.now(timezone.utc)
            queue_lines = queue_text.splitlines(keepends=True)
            if rollback_migration_id:
                for item in items:
                    task_id = item["task_id"]
                    queue_lines[item["queue_index"]] = item["queue_before"]
                    entry = registry[task_id]
                    prior_fields = item["prior_fields"]
                    for field in _COORDINATION_MIGRATION_MUTATED_FIELDS:
                        prior = prior_fields.get(field)
                        if not isinstance(prior, dict) or not isinstance(
                            prior.get("present"), bool
                        ):
                            raise ValueError(
                                f"task {task_id} has invalid prior field {field!r}"
                            )
                        if prior["present"]:
                            entry[field] = prior.get("value")
                        else:
                            entry.pop(field, None)
                    entry.pop(COORDINATION_MIGRATION_FIELD, None)
                outcome = "rolled-back"
            else:
                for item in items:
                    task_id = item["task_id"]
                    entry = registry[task_id]
                    prior_fields = {
                        field: {
                            "present": field in entry,
                            "value": entry.get(field),
                        }
                        for field in _COORDINATION_MIGRATION_MUTATED_FIELDS
                    }
                    queue_lines[item["queue_index"]] = item["queue_after"]
                    queue_record = _queue_record(item["queue_before"])
                    queue_summary = queue_record[3] if queue_record else ""
                    entry["status"] = "complete"
                    entry["worker_reported_status"] = "needs_review"
                    entry["coordination_requested"] = True
                    entry["coordination_request_source"] = (
                        "legacy-needs_review-status-migration"
                    )
                    entry["coordination_request_summary"] = queue_summary
                    entry["review_disposition"] = "not-required"
                    entry["reconciled_at"] = now.isoformat()
                    coordination_notification_due(entry, task_id, now)
                    entry[COORDINATION_MIGRATION_FIELD] = {
                        "schema": COORDINATION_MIGRATION_SCHEMA,
                        "plan_sha256": report["plan_sha256"],
                        "migrated_at": now.isoformat(),
                        "from_status": "needs_review",
                        "to_status": "complete",
                        "queue_before": item["queue_before"],
                        "queue_after": item["queue_after"],
                        "prior_fields": prior_fields,
                    }
                outcome = "applied"

            _commit_registry_and_queue(
                registry_text,
                registry,
                queue_text,
                "".join(queue_lines),
            )
            report["outcome"] = outcome
            report["migration_id"] = (
                rollback_migration_id
                if rollback_migration_id
                else report["plan_sha256"]
            )
            return report


def reconcile(task_id_filter: str | None, dry_run: bool) -> tuple[int, list[str]]:
    events: list[tuple[str, str, str, str]] = []
    coordination_queue_records: list[tuple[str, str, str]] = []
    archive_requests: list[tuple[str, str]] = []
    with locked_registry() as _lock:
        registry = load_registry()
        now = datetime.now(timezone.utc)
        changed = 0
        messages: list[str] = []
        for task_id, raw_entry in registry.items():
            if task_id_filter and task_id != task_id_filter:
                continue
            if not isinstance(raw_entry, dict):
                continue
            current_status = str(raw_entry.get("status", ""))
            schema, process_descriptor = settlement_process(task_id, raw_entry)
            if current_status in {"blocked", "complete", "completed"}:
                terminal_receipt, receipt_status, raw_receipt_status, receipt_completed_at = (
                    terminal_board_receipt(
                        task_id, raw_entry, schema, process_descriptor
                    )
                )
                if (
                    terminal_receipt is not None
                    and receipt_status in {"blocked", "complete"}
                ):
                    namespace = _canonical_mailbox_label()
                    pending, _executing_lane, review_lane = (
                        response_review_pending(raw_entry, receipt_status)
                    )
                    mark_delivery_terminal(
                        task_id,
                        raw_entry,
                        now,
                        f"board-receipt:{receipt_status}",
                    )
                    raw_entry["terminal_receipt_path"] = str(
                        terminal_receipt.relative_to(VAULT_ROOT)
                    )
                    raw_entry["terminal_receipt_status"] = raw_receipt_status
                    raw_entry["completed_at"] = receipt_completed_at
                    receipt_diagnostics = receipt_failure_diagnostics(
                        terminal_receipt
                    )
                    apply_receipt_diagnostics(raw_entry, receipt_diagnostics)
                    preserved = preserved_work_statement(
                        task_id, raw_entry, receipt_diagnostics
                    )
                    raw_entry["reconciled_at"] = now.isoformat()
                    if pending:
                        raw_entry["status"] = REVIEW_REQUIRED
                        raw_entry["review_required_by"] = review_lane
                        messages.append(
                            f"review-required {task_id} -> terminal board receipt "
                            f"{raw_receipt_status} awaits {review_lane} review"
                        )
                        append_terminal_event(
                            events,
                            raw_entry,
                            task_id,
                            namespace,
                            now,
                            "REVIEW-REQUIRED",
                            f"terminal board status={raw_receipt_status}; "
                            f"disposition=awaiting {review_lane} review; {preserved}",
                            f"REVIEW REQUIRED: {task_id} ended with terminal board "
                            f"status {raw_receipt_status} and awaits {review_lane} review. "
                            f"{preserved}.",
                        )
                    else:
                        auto_close_terminal_receipt(
                            task_id,
                            raw_entry,
                            now,
                            receipt_status,
                            raw_receipt_status,
                            receipt_diagnostics,
                        )
                        messages.append(
                            f"auto-closed {task_id} from terminal board receipt "
                            f"{raw_receipt_status}"
                        )
                        append_terminal_event(
                            events,
                            raw_entry,
                            task_id,
                            namespace,
                            now,
                            "AUTO-CLOSED",
                            f"terminal board status={raw_receipt_status}; "
                            f"disposition=closed; {preserved}",
                            f"AUTO-CLOSED: {task_id} ended with terminal board status "
                            f"{raw_receipt_status} and was closed. {preserved}.",
                        )
                    changed += 1
                    continue
            legacy_review_open = (
                current_status == "needs_review"
                and response_review_pending(raw_entry, current_status)[0]
            )
            if current_status not in {"in-flight", SETTLED_WITHOUT_ENVELOPE, REVIEW_REQUIRED} \
                and not legacy_review_open:
                if mark_delivery_terminal(
                    task_id, raw_entry, now, f"registry-status:{current_status}"
                ):
                    changed += 1
                if task_id_filter:
                    messages.append(f"already-settled {task_id} -> {current_status}")
                continue
            receipt_preempts_response = schema == "v2" and terminal_board_receipt(
                task_id, raw_entry, schema, process_descriptor
            )[0] is not None
            candidates = (
                []
                if receipt_preempts_response
                else response_candidates(task_id, raw_entry, schema)
            )
            response, status = landed_response(task_id, candidates, schema, raw_entry)
            if response is None and candidates:
                # BLOCK2 (wave-2): a response file may EXIST and be old enough to
                # settle yet carry a non-canonical status (typo/unknown). landed_response
                # returns None for it; without this guard execution falls through to the
                # return-artifact path and settles the task to work-done-no-envelope —
                # which, for a mandatory cross-family task, silently bypasses the Option-A
                # review-required hold. Distinguish "no response exists" from "a response
                # exists but its status is INVALID": for the latter keep the task OPEN
                # (fail closed) and flag it; never settle on an unusable status.
                # Presence alone suppresses the no-envelope backstop, including
                # during the response quiescence/min-age window. Otherwise a young
                # invalid response can be ignored once, settle through the artifact
                # backstop, and remain provisionally settled when it becomes ready.
                reopened = current_status == SETTLED_WITHOUT_ENVELOPE
                if reopened:
                    raw_entry["status"] = "in-flight"
                    raw_entry.pop("work_landed_at", None)
                    raw_entry.pop("missing_envelope_artifact", None)
                    raw_entry.pop("prior_missing_envelope_status", None)

                stray = next(
                    (cand for cand in candidates if response_ready(cand, schema)), None
                )
                if stray is None:
                    if reopened:
                        raw_entry["reconciled_at"] = now.isoformat()
                        changed += 1
                        messages.append(
                            f"response-pending {task_id} -> reopened pending status validation"
                        )
                    elif task_id_filter:
                        messages.append(f"response-pending {task_id} -> awaiting status validation")
                    continue

                bad_status = strip_frontmatter(read_text(stray)).get("status", "")
                namespace = response_namespace(stray)
                response_path = str(stray.relative_to(VAULT_ROOT))
                metadata_changed = (
                    raw_entry.get("response_path") != response_path
                    or raw_entry.get("invalid_response_status") != bad_status
                )
                if reopened or metadata_changed:
                    raw_entry["invalid_response_status"] = bad_status
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    changed += 1
                    messages.append(
                        f"invalid-response-status {task_id} -> {bad_status!r} (kept open)"
                    )
                    events.append(
                        (
                            "INVALID-RESPONSE-STATUS",
                            f"{namespace}/{task_id}",
                            f"response {response_path} has non-canonical status {bad_status!r}",
                            f"INVALID RESPONSE STATUS: {task_id} response status {bad_status!r} is "
                            "not canonical; registry kept OPEN (not settled, review hold intact). "
                            "Fix the response 'status' field or re-dispatch.",
                        )
                    )
                continue
            if response is not None:
                namespace = response_namespace(response)
                drift_changed, newly_drifted = update_capability_card_drift(
                    raw_entry, now
                )
                if newly_drifted:
                    current_hash = raw_entry.get("capability_card_current_sha256")
                    messages.append(
                        f"capability-card-drift {task_id} -> current={current_hash}"
                    )
                    events.append(
                        (
                            "CAPABILITY-CARD-DRIFT",
                            f"{namespace}/{task_id}",
                            f"dispatched={raw_entry.get('capability_card_sha256')} / current={current_hash}",
                            f"CAPABILITY CARD DRIFT: {task_id} current card hash is {current_hash}; "
                            "the dispatched snapshot remains authoritative for settlement.",
                        )
                    )
                capability_issue = capability_response_issue(raw_entry, response)
                worker_issue = worker_response_issue(task_id, raw_entry, response, schema)
                contract_issue = capability_issue or worker_issue
                if contract_issue:
                    response_path = str(response.relative_to(VAULT_ROOT))
                    metadata_changed = (
                        current_status != "in-flight"
                        or str(raw_entry.get("capability_response_issue") or "") != capability_issue
                        or str(raw_entry.get("worker_response_issue") or "") != worker_issue
                        or raw_entry.get("response_path") != response_path
                    )
                    raw_entry["status"] = "in-flight"
                    if capability_issue:
                        raw_entry["capability_response_issue"] = capability_issue
                    else:
                        raw_entry.pop("capability_response_issue", None)
                    if worker_issue:
                        raw_entry["worker_response_issue"] = worker_issue
                    else:
                        raw_entry.pop("worker_response_issue", None)
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    if metadata_changed or drift_changed:
                        changed += 1
                    if metadata_changed:
                        messages.append(
                            f"capability-contract-hold {task_id} -> {contract_issue}"
                        )
                        events.append(
                            (
                                "CAPABILITY-CONTRACT-HOLD",
                                f"{namespace}/{task_id}",
                                contract_issue,
                                f"DISPATCH CONTRACT HOLD: {task_id} response does not match "
                                "the dispatched pin/fence; registry kept OPEN.",
                            )
                        )
                    continue
                # A declared hash must resolve to something a reviewer can open.
                # This runs AFTER the pin/fence checks so an off-attempt
                # response is rejected on identity first, and it HOLDS rather
                # than rejects: the response file and the deliverable are left
                # exactly where they are, and the hold clears the moment the
                # manifest lands or the unbacked digest is removed.
                hash_issue = declared_hash_issue(raw_entry, response)
                if hash_issue:
                    response_path = str(response.relative_to(VAULT_ROOT))
                    metadata_changed = (
                        current_status != "in-flight"
                        or str(raw_entry.get("declared_hash_issue") or "") != hash_issue
                        or raw_entry.get("response_path") != response_path
                    )
                    raw_entry["status"] = "in-flight"
                    raw_entry["declared_hash_issue"] = hash_issue
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    if metadata_changed or drift_changed:
                        changed += 1
                    if metadata_changed:
                        messages.append(
                            f"declared-hash-hold {task_id} -> {hash_issue}"
                        )
                        # No terminal receipt is in play on this route, so the
                        # preserved-work verdict would be unfounded here. What
                        # IS knowable is the attempt branch name, which is where
                        # the worker's full tree sits if the manifest was
                        # written but never promoted.
                        attempt_ref = attempt_evidence_ref(task_id, raw_entry)
                        events.append(
                            (
                                "DECLARED-HASH-HOLD",
                                f"{namespace}/{task_id}",
                                hash_issue,
                                f"DECLARED HASH RESOLVES TO NOTHING: {task_id} "
                                f"{hash_issue}. The response and its artifact are "
                                "UNTOUCHED and the registry is kept OPEN; land the "
                                "manifest or drop the unbacked digest and "
                                "re-reconcile."
                                + (
                                    f" The attempt's full tree is on {attempt_ref}."
                                    if attempt_ref
                                    else ""
                                ),
                            )
                        )
                    continue
                capability_issue_cleared = (
                    raw_entry.pop("capability_response_issue", None) is not None
                )
                worker_issue_cleared = (
                    raw_entry.pop("worker_response_issue", None) is not None
                )
                hash_issue_cleared = (
                    raw_entry.pop("declared_hash_issue", None) is not None
                )
                contract_issue_cleared = (
                    capability_issue_cleared or worker_issue_cleared or hash_issue_cleared
                )
                worker_status = status
                raw_worker_status = raw_response_status(response)
                resolved_status, legacy_coordination = resolve_worker_status(
                    raw_entry, worker_status
                )
                explicit_coordination, coordination_summary = (
                    response_coordination_request(
                        response, include_legacy=legacy_coordination
                    )
                )
                coordination_requested = (
                    explicit_coordination or legacy_coordination
                )
                coordination_source = (
                    "response-heading"
                    if explicit_coordination
                    else "legacy-needs_review-status"
                    if legacy_coordination
                    else ""
                )
                if legacy_coordination and not coordination_summary:
                    coordination_summary = response_summary(response)
                outcome_metadata_changed = apply_worker_outcome_metadata(
                    raw_entry,
                    reported_status=raw_worker_status or worker_status,
                    coordination_requested=coordination_requested,
                    coordination_source=coordination_source,
                    coordination_summary=coordination_summary,
                )
                delivery_changed = mark_delivery_terminal(
                    task_id, raw_entry, now, f"response:{worker_status}"
                )
                pinned_hash = str(
                    raw_entry.get("capability_card_sha256") or ""
                ).strip()
                if pinned_hash:
                    raw_entry["response_capability_card_sha256"] = pinned_hash
                # A genuine cross-family mandatory_review task may NOT settle on
                # its own response or on any parsed review file. It stays held
                # until Chrono explicitly runs --settle-review after reading the
                # review. Unknown or malformed review state is therefore inert.
                pending, executing_lane, review_lane = response_review_pending(
                    raw_entry, worker_status
                )
                if pending:
                    newly_flagged = current_status != REVIEW_REQUIRED
                    lane_changed = raw_entry.get("review_required_by") != review_lane
                    response_path = str(response.relative_to(VAULT_ROOT))
                    response_changed = raw_entry.get("response_path") != response_path
                    obsolete_present = any(
                        key in raw_entry
                        for key in (
                            "cross_family_review_ref",
                            "review_blocking_ref",
                            "review_signature",
                            "invalid_response_status",
                        )
                    )
                    raw_entry["status"] = REVIEW_REQUIRED
                    raw_entry["review_required_by"] = review_lane
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    raw_entry.pop("cross_family_review_ref", None)
                    raw_entry.pop("review_blocking_ref", None)
                    raw_entry.pop("review_signature", None)
                    raw_entry.pop("invalid_response_status", None)
                    hold_changed = (
                        newly_flagged
                        or lane_changed
                        or response_changed
                        or obsolete_present
                        or drift_changed
                        or contract_issue_cleared
                        or delivery_changed
                        or outcome_metadata_changed
                    )
                    if hold_changed:
                        changed += 1
                    reason = review_hold_reason(executing_lane, review_lane)
                    next_action = review_hold_next_action(executing_lane, review_lane)
                    if newly_flagged or lane_changed:
                        messages.append(f"review-required {task_id} -> {reason}")
                    elif task_id_filter:
                        messages.append(f"review-held {task_id} -> {reason}")
                    if notification_due(raw_entry, task_id, REVIEW_REQUIRED, now):
                        if not hold_changed:
                            changed += 1
                        events.append(
                            (
                                "REVIEW-REQUIRED",
                                f"{namespace}/{task_id}",
                                f"{executing_lane} specialist '{raw_entry.get('specialist')}' "
                                f"is held; {reason}",
                                f"REVIEW-REQUIRED: {task_id} ({raw_entry.get('specialist')}, lane "
                                f"{executing_lane}) cannot settle: {reason}. {next_action}.",
                            )
                        )
                    if append_coordination_event(
                        events, raw_entry, task_id, namespace, now
                    ) and not hold_changed:
                        changed += 1
                    continue
                status = resolved_status
                if current_status == SETTLED_WITHOUT_ENVELOPE:
                    raw_entry["prior_missing_envelope_status"] = current_status
                if status == "complete":
                    # This is the intended settlement path for ordinary work:
                    # the author's own verified response closes automatically
                    # only after the trigger contract says no review is owed.
                    raw_entry["review_disposition"] = (
                        "read-only-verdict-exemption"
                        if str(raw_entry.get("mandatory_review", "")).strip().lower()
                        == "true"
                        else "not-required"
                    )
                raw_entry["status"] = status
                if schema == "v2":
                    *_, receipt_completed_at = terminal_board_receipt(
                        task_id, raw_entry, schema, process_descriptor
                    )
                    if receipt_completed_at:
                        raw_entry["completed_at"] = receipt_completed_at
                    else:
                        raw_entry.pop("completed_at", None)
                else:  # Explicit V1 compatibility: response mtime is legacy display truth.
                    raw_entry["completed_at"] = datetime.fromtimestamp(
                        response.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry["auto_reconciled_at"] = now.isoformat()
                raw_entry["response_path"] = str(response.relative_to(VAULT_ROOT))
                raw_entry.pop("invalid_response_status", None)
                changed += 1
                messages.append(f"reconciled {task_id} -> {status} via {namespace}")
                append_terminal_event(
                    events,
                    raw_entry,
                    task_id,
                    namespace,
                    now,
                    status,
                    response_summary(response),
                    f"{status}: {task_id} response landed in departments/{namespace}/"
                    f"{response.parent.name}/{response.name}; registry reconciled. Read and surface now.",
                    coordination_queue_records,
                )
                continue
            terminal_receipt, receipt_status, raw_receipt_status, receipt_completed_at = (
                terminal_board_receipt(
                    task_id, raw_entry, schema, process_descriptor
                )
            )
            if terminal_receipt is not None:
                namespace = _canonical_mailbox_label()
                delivery_changed = mark_delivery_terminal(
                    task_id,
                    raw_entry,
                    now,
                    f"board-receipt:{receipt_status}",
                )
                receipt_path = str(terminal_receipt.relative_to(VAULT_ROOT))
                receipt_diagnostics = receipt_failure_diagnostics(terminal_receipt)
                receipt_response: Path | None = None
                receipt_response_status = ""
                if schema == "v2":
                    receipt_response, receipt_response_status = landed_response(
                        task_id,
                        response_candidates(task_id, raw_entry, schema),
                        schema,
                        raw_entry,
                    )
                    if receipt_response_status != receipt_status:
                        receipt_response = None
                explicit_coordination = False
                coordination_summary = ""
                resolved_receipt_status, legacy_coordination = resolve_worker_status(
                    raw_entry, receipt_status
                )
                if receipt_response is not None:
                    explicit_coordination, coordination_summary = (
                        response_coordination_request(
                            receipt_response, include_legacy=legacy_coordination
                        )
                    )
                coordination_requested = (
                    explicit_coordination or legacy_coordination
                )
                coordination_source = (
                    "response-heading"
                    if explicit_coordination
                    else "legacy-needs_review-status"
                    if legacy_coordination
                    else ""
                )
                if legacy_coordination and not coordination_summary:
                    coordination_summary = (
                        response_summary(receipt_response)
                        if receipt_response is not None
                        else f"terminal board receipt reported {receipt_status} without a declared review trigger"
                    )
                raw_worker_status = (
                    raw_receipt_status
                    if registry_status(raw_receipt_status)
                    else receipt_status
                )
                outcome_metadata_changed = apply_worker_outcome_metadata(
                    raw_entry,
                    reported_status=raw_worker_status,
                    coordination_requested=coordination_requested,
                    coordination_source=coordination_source,
                    coordination_summary=coordination_summary,
                )
                # This route fires exactly when NO response envelope was
                # promoted -- the shape where a reader has nothing but the
                # notification text to go on, and so the one place the preserved
                # location must be stated rather than merely stored.
                preserved = preserved_work_statement(
                    task_id, raw_entry, receipt_diagnostics
                )
                # Diagnostics must join change-detection: on a re-reconcile where
                # nothing else moved, `changed` stays 0, the registry is never
                # written, and the fields would be silently dropped.
                diagnostics_changed = apply_receipt_diagnostics(
                    raw_entry, receipt_diagnostics
                )
                metadata_changed = (
                    raw_entry.get("completed_at") != receipt_completed_at
                    or raw_entry.get("terminal_receipt_path") != receipt_path
                    or raw_entry.get("terminal_receipt_status") != raw_receipt_status
                    or diagnostics_changed
                    or outcome_metadata_changed
                )
                raw_entry["completed_at"] = receipt_completed_at
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry.setdefault("auto_reconciled_at", now.isoformat())
                raw_entry["terminal_receipt_path"] = receipt_path
                raw_entry["terminal_receipt_status"] = raw_receipt_status
                raw_entry.pop("invalid_response_status", None)
                pending, executing_lane, review_lane = response_review_pending(
                    raw_entry, receipt_status
                )
                if pending:
                    reason = review_hold_reason(executing_lane, review_lane)
                    hold_changed = (
                        current_status != REVIEW_REQUIRED
                        or raw_entry.get("review_required_by") != review_lane
                        or metadata_changed
                        or delivery_changed
                    )
                    raw_entry["status"] = REVIEW_REQUIRED
                    raw_entry["review_required_by"] = review_lane
                    if hold_changed:
                        changed += 1
                        messages.append(
                            f"review-required {task_id} -> terminal board receipt "
                            f"{raw_receipt_status}; {reason}"
                        )
                    event_keyed = append_terminal_event(
                        events,
                        raw_entry,
                        task_id,
                        namespace,
                        now,
                        "REVIEW-REQUIRED",
                        f"terminal board status={raw_receipt_status}; "
                        f"disposition=awaiting {review_lane} review; {preserved}",
                        f"REVIEW-REQUIRED: {task_id} ended with terminal board "
                        f"status {raw_receipt_status} on {executing_lane}, but "
                        f"cannot close: {reason}. {preserved}.",
                    )
                    if event_keyed and not hold_changed:
                        changed += 1
                    continue
                auto_close_on_next_pass = (
                    receipt_status in {"blocked", "complete"}
                    and resolved_receipt_status in {"blocked", "complete"}
                )
                receipt_status = resolved_receipt_status
                if receipt_status == "complete":
                    raw_entry["review_disposition"] = "not-required"
                raw_entry["status"] = receipt_status
                # This status mutation earns the increment; unlike the review
                # arm, it does not depend on whether an event key was added.
                changed += 1
                messages.append(
                    f"reconciled {task_id} -> {receipt_status} via terminal board receipt"
                )
                if auto_close_on_next_pass:
                    # This single-shot deferral relies on three invariants:
                    # board-dispatch receipts are not pruned while unresolved,
                    # no writer outside this reconciler changes entry["status"],
                    # and delivery_generation has no increment path.
                    # Keep the existing two-step registry lifecycle intact, but
                    # defer its operator event until the next pass has actually
                    # recorded the close disposition.  Emitting here would page
                    # once for the receipt state and again for AUTO-CLOSED.
                    # Both append_chrono_queue's durable recovery record and the
                    # live pane nudge are deferred, so the registry is the only
                    # trace of the terminal task between these two passes.
                    continue
                append_terminal_event(
                    events,
                    raw_entry,
                    task_id,
                    namespace,
                    now,
                    receipt_status,
                    f"terminal board status={raw_receipt_status}; "
                    f"disposition={receipt_status}; {preserved}",
                    f"{receipt_status}: {task_id} ended with terminal board status "
                    f"{raw_receipt_status}; registry disposition is {receipt_status} "
                    f"because no promoted response envelope was available. {preserved}.",
                )
                continue
            # F5: a task that registered and never launched auto-releases its
            # write_scope. Any status other than `in-flight` frees the scope,
            # because the dispatcher's conflict check only counts in-flight
            # entries; `cancelled` is the honest one -- the work never started.
            never_launched = never_launched_reason(
                task_id, raw_entry, now, candidates=candidates
            )
            if never_launched:
                namespace = _canonical_mailbox_label()
                mark_delivery_terminal(task_id, raw_entry, now, "never-launched")
                raw_entry["status"] = "cancelled"
                raw_entry["never_launched_reason"] = never_launched
                raw_entry["completed_at"] = now.isoformat()
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry["auto_reconciled_at"] = now.isoformat()
                changed += 1
                messages.append(
                    f"reconciled {task_id} -> cancelled (never launched; "
                    "write_scope released)"
                )
                if notification_due(raw_entry, task_id, "cancelled", now):
                    events.append(
                        (
                            "cancelled",
                            f"{namespace}/{task_id}",
                            never_launched,
                            f"cancelled: {task_id} was registered but never "
                            "launched and produced nothing; its write_scope is "
                            "released and it is safe to re-dispatch.",
                        )
                    )
                continue
            if current_status == SETTLED_WITHOUT_ENVELOPE:
                # This is a provisional settled state: it stops counting as
                # running, but a later real envelope must still win.
                if schema == "v1":
                    continue
                raw_entry["status"] = "in-flight"
                raw_entry.pop("work_landed_at", None)
                raw_entry.pop("missing_envelope_artifact", None)
                raw_entry["reconciled_at"] = now.isoformat()
                changed += 1
            # Artifact presence/age is settlement authority only on the V1 rail.
            artifact = return_artifact_path(task_id, raw_entry) if schema == "v1" else None
            if artifact and artifact.is_file():
                pane_state, snippet = pane_snapshot(str(raw_entry.get("to_model") or "unknown-model"))
                artifact_mtime = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
                artifact_age = now - artifact_mtime
                dispatched = parse_dt(raw_entry.get("dispatched_at"))
                artifact_fresh = dispatched is None or artifact_mtime >= dispatched
                dispatch_old_enough = (
                    dispatched is not None and now - dispatched >= NO_ENVELOPE_MIN_DISPATCH_AGE
                )
                grace_elapsed = dispatch_old_enough and artifact_age >= NO_ENVELOPE_GRACE
                if artifact_fresh and pane_state != "active" and (pane_state == "idle" or grace_elapsed):
                    namespace = _canonical_mailbox_label()
                    raw_entry["status"] = SETTLED_WITHOUT_ENVELOPE
                    raw_entry["work_landed_at"] = artifact_mtime.isoformat()
                    raw_entry["reconciled_at"] = now.isoformat()
                    raw_entry["missing_envelope_artifact"] = str(artifact)
                    mark_delivery_terminal(
                        task_id, raw_entry, now, SETTLED_WITHOUT_ENVELOPE
                    )
                    changed += 1
                    reason = "lane idle" if pane_state == "idle" else f"artifact grace {artifact_age}"
                    messages.append(f"flagged {task_id} -> {SETTLED_WITHOUT_ENVELOPE} ({reason})")
                    if notification_due(raw_entry, task_id, SETTLED_WITHOUT_ENVELOPE, now):
                        events.append(
                            (
                                SETTLED_WITHOUT_ENVELOPE,
                                f"{namespace}/{task_id}",
                                f"artifact={artifact} / pane={pane_state} / {snippet}",
                                f"WORK DONE, NO ENVELOPE: {task_id} return artifact exists and {reason}. "
                                "Registry no longer counts it as running; inspect and reconcile now.",
                            )
                        )
                    continue
            dispatched = parse_dt(raw_entry.get("dispatched_at"))
            if dispatched and now - dispatched > timedelta(hours=12):
                if not dry_run:
                    append_drift(task_id, f"no response after >12h; status={current_status}")
                messages.append(f"drift {task_id}")
            long_running_message = note_long_running(task_id, raw_entry, now, dry_run)
            if long_running_message:
                messages.append(long_running_message)
        if task_id_filter:
            held_entry = registry.get(task_id_filter)
            if isinstance(held_entry, dict) and str(held_entry.get("status") or "") in {"in-flight", REVIEW_REQUIRED, "needs_review"}:
                held_schema, _held_descriptor = settlement_process(
                    task_id_filter, held_entry
                )
                if held_schema in {"v2", "invalid"}:
                    messages.append(
                        f"v2-settlement-hold {task_id_filter} -> schema={held_schema}"
                    )
        if changed and not dry_run:
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        if not dry_run:
            archive_requests = [
                candidate_id
                for candidate_id, candidate in registry.items()
                if isinstance(candidate, dict)
                and (not task_id_filter or candidate_id == task_id_filter)
                and str(candidate.get("status") or "") in INBOX_ARCHIVE_STATUSES
            ]
    if not dry_run:
        for archived_task_id in archive_requests:
            if archive_inbox_packet(archived_task_id):
                messages.append(
                    "archived inbox packet "
                    f"{_canonical_mailbox_label()}/{archived_task_id}"
                )
        for status, task_ref, summary, nudge in events:
            nudged = emit_event(status, task_ref, summary, nudge)
            messages.append(f"chrono-nudge {'sent' if nudged else 'queued-only'} {task_ref}")
        # Completion and coordination remain separate durable audit facts even
        # when the promoted-response path coalesces their operator page.
        for status, task_ref, summary in coordination_queue_records:
            append_chrono_queue(status, task_ref, summary)
            messages.append(f"chrono-queue appended {task_ref} -> {status}")
    return changed, messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id")
    parser.add_argument("--register-task")
    parser.add_argument("--entry-json")
    parser.add_argument("--claim-task")
    parser.add_argument("--attempt-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--worker-epoch")
    parser.add_argument("--lease-generation", type=int)
    parser.add_argument("--worker-lane")
    parser.add_argument("--now")
    parser.add_argument("--settle-review")
    parser.add_argument("--review-ref")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reopen")
    parser.add_argument("--reopen-status", choices=("needs_review", "needs_rework"))
    parser.add_argument("--repair-envelope", metavar="TASK_ID")
    parser.add_argument(
        "--migrate-untriggered-needs-review", action="store_true"
    )
    parser.add_argument(
        "--rollback-coordination-migration", metavar="MIGRATION_SHA256"
    )
    parser.add_argument("--apply-plan-sha256", metavar="PLAN_SHA256")
    # `action="extend"` is load-bearing, not cosmetic: with plain `nargs="+"`
    # argparse OVERWRITES on a repeated flag, so `--close-task A --close-task B`
    # silently discarded A and closed only B while reporting success. Both the
    # space-separated form (`--close-task A B`) and the repeated-flag form now
    # produce the same batch, and the duplicate check inside close_task catches
    # an id supplied twice across the two forms.
    parser.add_argument("--close-task", nargs="+", action="extend", metavar="TASK_ID")
    parser.add_argument(
        "--close-status", choices=("superseded", "closed"), default="superseded"
    )
    parser.add_argument("--close-reason")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if bool(args.register_task) != bool(args.entry_json):
        parser.error("--register-task and --entry-json must be used together")
    if bool(args.settle_review) != bool(args.review_ref):
        parser.error("--settle-review and --review-ref must be used together")
    lifecycle_actions = sum(
        bool(value)
        for value in (
            args.settle_review,
            args.reopen,
            args.close_task,
            args.repair_envelope,
            args.migrate_untriggered_needs_review
            or args.rollback_coordination_migration,
        )
    )
    if lifecycle_actions > 1:
        parser.error(
            "--settle-review, --reopen, --close-task, --repair-envelope, and "
            "coordination migration actions are mutually exclusive"
        )
    if (
        args.migrate_untriggered_needs_review
        and args.rollback_coordination_migration
    ):
        parser.error(
            "--migrate-untriggered-needs-review and "
            "--rollback-coordination-migration are mutually exclusive"
        )
    coordination_migration_action = bool(
        args.migrate_untriggered_needs_review
        or args.rollback_coordination_migration
    )
    if args.apply_plan_sha256 and not coordination_migration_action:
        parser.error("--apply-plan-sha256 requires a coordination migration action")
    if args.dry_run and args.apply_plan_sha256:
        parser.error("--dry-run and --apply-plan-sha256 are mutually exclusive")
    if coordination_migration_action and args.task_id:
        parser.error("coordination migration cannot be combined with --task-id")
    if args.force and not args.settle_review:
        parser.error("--force is valid only with --settle-review")
    if args.reopen_status and not args.reopen:
        parser.error("--reopen-status requires --reopen")
    if bool(args.close_task) != bool(args.close_reason):
        parser.error("--close-task and --close-reason must be used together")
    if args.close_status != "superseded" and not args.close_task:
        parser.error("--close-status requires --close-task")
    if args.claim_task and (
        args.register_task
        or args.settle_review
        or args.reopen
        or args.close_task
        or args.repair_envelope
        or coordination_migration_action
        or args.task_id
        or args.dry_run
    ):
        parser.error("--claim-task cannot be combined with register/reconcile/review actions")
    if args.claim_task:
        if not args.attempt_id:
            parser.error("--claim-task requires --attempt-id")
        worker_values = (
            args.worker_id,
            args.worker_epoch,
            args.lease_generation,
            args.worker_lane,
        )
        if any(value is not None for value in worker_values) and not all(
            value is not None for value in worker_values
        ):
            parser.error(
                "worker claim requires --worker-id, --worker-epoch, "
                "--lease-generation, and --worker-lane together"
            )
        try:
            result = claim_task(
                args.claim_task,
                args.attempt_id,
                worker_id=args.worker_id,
                worker_epoch=args.worker_epoch,
                lease_generation=args.lease_generation,
                lane=args.worker_lane,
                now_raw=args.now,
            )
        except (RegistryCorruptError, ValueError) as exc:
            print(json.dumps({"claimed": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.register_task:
        if (
            args.dry_run
            or args.task_id
            or args.settle_review
            or args.reopen
            or args.close_task
            or coordination_migration_action
        ):
            parser.error(
                "--register-task cannot be combined with reconcile/review/lifecycle actions"
            )
        try:
            entry = json.loads(args.entry_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--entry-json is not valid JSON: {exc}")
        if not isinstance(entry, dict):
            parser.error("--entry-json must decode to an object")
        try:
            registered = register_task(args.register_task, entry)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 3
        outcome = "registered" if registered else "idempotent"
        print(f"registry-reconciler register: task={args.register_task} outcome={outcome}")
        return 0
    if coordination_migration_action:
        try:
            report = migrate_untriggered_needs_review(
                dry_run=args.dry_run,
                apply_plan_sha256=args.apply_plan_sha256 or "",
                rollback_migration_id=args.rollback_coordination_migration or "",
            )
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 3
        print(
            "registry-reconciler coordination-migration: "
            f"outcome={report['outcome']} action={report['action']} "
            f"candidates={report['candidate_count']} "
            f"queue_entries={report['queue_entry_count']} "
            f"plan_sha256={report['plan_sha256']} "
            f"preserved_needs_human={report['preserved_needs_human']} "
            f"preserved_blocked={report['preserved_blocked']} "
            f"triggered_needs_review={report['triggered_needs_review']}"
        )
        for migrated_task_id in report["task_ids"]:
            print(f"coordination-migration task={migrated_task_id}")
        if report.get("migration_id"):
            print(f"coordination-migration id={report['migration_id']}")
        return 0
    if args.settle_review:
        if args.dry_run or args.task_id:
            parser.error("--settle-review cannot be combined with --task-id or --dry-run")
        try:
            changed = settle_review(args.settle_review, args.review_ref, force=args.force)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        outcome = "settled" if changed else "already-settled"
        print(f"registry-reconciler review: {outcome} task={args.settle_review}")
        return 0
    if args.repair_envelope:
        if args.dry_run or args.task_id:
            parser.error("--repair-envelope cannot be combined with --task-id or --dry-run")
        try:
            changed = repair_promoted_envelope(args.repair_envelope)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        outcome = "repaired" if changed else "already-canonical"
        print(f"registry-reconciler repair: {outcome} task={args.repair_envelope}")
        return 0
    if args.reopen:
        if args.dry_run or args.task_id:
            parser.error("--reopen cannot be combined with --task-id or --dry-run")
        try:
            changed = reopen_task(args.reopen, args.reopen_status)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        outcome = "reopened" if changed else "already-reopened"
        print(
            f"registry-reconciler reopen: {outcome} task={args.reopen} "
            f"status={args.reopen_status or 'derived'}"
        )
        return 0
    if args.close_task:
        if args.dry_run or args.task_id:
            parser.error("--close-task cannot be combined with --task-id or --dry-run")
        try:
            report = close_task(args.close_task, args.close_reason, args.close_status)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except BatchCloseRefused as exc:
            # A refusal is all-or-nothing, so say so about EVERY requested id.
            # Naming only the member that failed reads as "the rest went
            # through", which is the misreading this whole path exists to stop.
            print(
                f"registry-reconciler close: REFUSED, no task was closed: {exc}",
                file=sys.stderr,
            )
            for line in exc.report.render():
                print(line, file=sys.stderr)
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        outcome = "closed" if report else "already-closed"
        task_field = "task" if len(args.close_task) == 1 else "tasks"
        task_value = (
            args.close_task[0]
            if len(args.close_task) == 1
            else ",".join(args.close_task)
        )
        print(
            f"registry-reconciler close: {outcome} {task_field}={task_value} "
            f"status={args.close_status}"
        )
        # One line per requested id. A partial result cannot hide behind the
        # summary line, because the summary is no longer the only thing printed.
        for line in report.render():
            print(line)
        incomplete = report.follow_through_failures
        if incomplete:
            print(
                "registry-reconciler close: FOLLOW-THROUGH INCOMPLETE for "
                f"{len(incomplete)} task(s); the registry close is committed and "
                "durable, but the records below were not written",
                file=sys.stderr,
            )
            for item in incomplete:
                print(item.render(), file=sys.stderr)
            return 1
        return 0
    try:
        changed, messages = reconcile(args.task_id, args.dry_run)
    except RegistryCorruptError as exc:
        print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
        return 2
    mode = "dry-run" if args.dry_run else "write"
    print(f"registry-reconciler {mode}: changes={changed}")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
