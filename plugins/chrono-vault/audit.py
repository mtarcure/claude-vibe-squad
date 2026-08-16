"""Append-only audit trail for chrono-vault recall/record operations.

Ledger item P4.4: every ``recall`` and ``record`` through this plugin emits one
event carrying the five required fields — engagement, applied policy (the memory
aperture), request hash, returned note ids, and result.

The point is a distinction that used to be invisible: a recall that *ran and
matched nothing* must be tellable apart from one that *never ran* and from one
that *ran against a broken or empty root*. Board spawns once lacked
``CHRONO_VAULT_ROOT``, the vault failed closed, and empty recalls read as "no
relevant memory" rather than "memory was unreachable." The ``result`` vocabulary
below makes those states different lines (or, for "never ran", a missing line).

Design choices that fall out of that requirement:

* **One file per event, written atomically (temp + fsync + rename).** The trail
  is shared state written concurrently by many board lanes; a single appended
  log would race. Per-event files with unique names never contend, mirroring how
  ``notes.py`` already writes notes.
* **The destination is resolved independently of vault-root validity.** A broken
  root is case (c); if the only audit home were ``<root>/audit`` we could not
  record the very failure this file exists to expose. ``CHRONO_VAULT_AUDIT_DIR``
  is the independent home; ``<root>/audit`` is only the fallback when the root is
  valid. Engagement and aperture come from ``CHRONO_VAULT_CONTEXT`` (also
  independent of the root), so every field is computable even when the root is
  gone.
* **Never store note content.** Only ids, a one-way request hash, counts, and the
  ledger fields. This trail is meant to outlive the notes it references.
* **Auditing never gates the operation.** A failure to write an event is logged
  as a bounded stderr breadcrumb and swallowed; it must not break the recall or
  record it was describing.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import clearance
from vaultroot import VaultRootError, resolve_vault_root


SCHEMA = "chrono-vault-audit/v1"
AUDIT_DIR_ENV = "CHRONO_VAULT_AUDIT_DIR"

# ``result`` vocabulary. Recall and record share the enum namespace but each uses
# its own subset; the three-way distinguishability the ledger asks for lives in
# the recall codes.
#
# recall:
#   matched      — the index was queried and returned >= 1 note.
#   no_match     — the index was queried and matched nothing (case a).
#   empty_store  — recall ran but the index was absent/unbuilt; nothing *could*
#                  match (case c, the "empty root" half).
#   filtered     — the aperture/filters excluded everything before the index was
#                  consulted; distinct from a real index no-match so a caller can
#                  tell "my constraints admit nothing" from "the store is empty".
#   query_error  — the query itself was rejected as malformed.
#   unavailable  — the vault root or index was broken/unreadable; recall could
#                  not execute (case c, the "broken root" half — the incident).
#   denied       — the bound aperture denies recall entirely.
#   error        — an unexpected failure (kept so nothing is silently unclassed).
# "never ran" (case b) is the ABSENCE of any event; there is deliberately no code
# for it.
MATCHED = "matched"
NO_MATCH = "no_match"
EMPTY_STORE = "empty_store"
FILTERED = "filtered"
QUERY_ERROR = "query_error"
UNAVAILABLE = "unavailable"
DENIED = "denied"
ERROR = "error"

# record:
#   recorded             — note written and indexed.
#   recorded_unindexed   — note written, best-effort index update failed (the
#                          note's own ``index_dirty`` half-state, surfaced).
#   rejected             — the note failed schema validation; nothing was written.
#   denied / unavailable / error — as for recall.
RECORDED = "recorded"
RECORDED_UNINDEXED = "recorded_unindexed"
REJECTED = "rejected"

# set_status (lifecycle transition). A status change is the one live mutation of
# an existing note's lifecycle, so it emits its own event: `transitioned` when a
# note actually changed status, `conflict` on a revision/usage clash, `rejected`
# when a guard refused (missing/unverified replacement, a supersession cycle),
# and denied/unavailable/error as elsewhere. Sol found these transitions emit
# nothing today; this closes that gap on the P4.4 trail rather than a new channel.
TRANSITIONED = "transitioned"
CONFLICT = "conflict"

# contradiction (write-time detection). A record first checks the corpus for an
# active note on the same subject: `clear` when none is found, `declared` when
# the write covers every detected contradiction with a relationship, `flagged`
# when a contradiction is left unreconciled (recorded anyway, never refused), and
# `inconclusive` when detection itself could not run. Detection reports; it never
# gates the write and never grades its own resolution.
CONTRA_CLEAR = "clear"
CONTRA_DECLARED = "declared"
CONTRA_FLAGGED = "flagged"
CONTRA_INCONCLUSIVE = "inconclusive"

RECALL_RESULTS = frozenset(
    {MATCHED, NO_MATCH, EMPTY_STORE, FILTERED, QUERY_ERROR, UNAVAILABLE, DENIED, ERROR}
)
RECORD_RESULTS = frozenset(
    {RECORDED, RECORDED_UNINDEXED, REJECTED, DENIED, UNAVAILABLE, ERROR}
)
LIFECYCLE_RESULTS = frozenset(
    {TRANSITIONED, REJECTED, CONFLICT, DENIED, UNAVAILABLE, ERROR}
)
CONTRADICTION_RESULTS = frozenset(
    {CONTRA_CLEAR, CONTRA_DECLARED, CONTRA_FLAGGED, CONTRA_INCONCLUSIVE}
)

# The five ledger fields, asserted by the schema test so the set can never drift.
REQUIRED_FIELDS = (
    "engagement",
    "applied_policy",
    "request_hash",
    "returned_note_ids",
    "result",
)

# Applied-policy markers for the two states that are not a bound aperture. These
# describe the *absence* of a lane aperture; they are not a parallel aperture
# vocabulary — a bound lane always reports one of the five canonical apertures.
UNBOUND = "unbound"
INVALID_CONTEXT = "invalid_context"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_digest(operation: str, payload: Any) -> str:
    """Return a one-way ``sha256:`` digest of a request.

    For ``record`` the payload includes note content, but only its digest is
    ever stored — the trail records *that* a request happened and lets two
    identical requests be correlated, without retaining what was written.
    """
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def engagement_snapshot() -> tuple[dict[str, Any] | None, str]:
    """Return ``(engagement, applied_policy)`` from the controller context.

    ``applied_policy`` is the bound memory aperture. Unbound maintenance
    processes report ``unbound``; a malformed context reports ``invalid_context``
    (itself worth recording) rather than crashing the audit path.
    """
    try:
        context = clearance.memory_context()
    except clearance.ClearanceError:
        return None, INVALID_CONTEXT
    if context is None:
        return None, UNBOUND
    engagement = {
        "task_id": context.get("task_id"),
        "attempt_id": context.get("attempt_id"),
        "generation": context.get("generation"),
        "mode": context.get("mode"),
        "focus": context.get("focus"),
    }
    return engagement, str(context.get("aperture"))


def resolve_audit_dir() -> Path | None:
    """Resolve the audit home independently of vault-root validity.

    Priority: an explicit absolute ``CHRONO_VAULT_AUDIT_DIR`` (which keeps
    working when the vault root is broken — the case that most needs auditing),
    then ``<vault_root>/audit`` when the root resolves cleanly. Returns ``None``
    when neither is available; the caller treats that as "nowhere safe to write"
    and skips, best-effort.
    """
    override = os.environ.get(AUDIT_DIR_ENV)
    if override:
        if "${" in override or not os.path.isabs(override):
            return None
        return Path(override)
    try:
        return resolve_vault_root() / "audit"
    except VaultRootError:
        return None


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    return os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)


def _write_event(audit_dir: Path, operation: str, event: dict[str, Any]) -> None:
    """Atomically write one event file: temp + fsync + rename, 0600 under 0700."""
    op_dir = audit_dir / operation
    op_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(op_dir, 0o700)
    except OSError:
        pass

    payload = (
        json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    final_name = f"evt-{event['event_id']}.json"

    dir_fd = os.open(op_dir, _directory_flags())
    temp_name = ""
    temp_fd = -1
    file_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for _ in range(100):
            temp_name = f".{final_name}.{secrets.token_hex(6)}.tmp"
            try:
                temp_fd = os.open(temp_name, file_flags, 0o600, dir_fd=dir_fd)
                break
            except FileExistsError:
                continue
        else:
            raise OSError("could not allocate a temporary audit file")

        with os.fdopen(temp_fd, "wb", closefd=True) as handle:
            temp_fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_name, final_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        temp_name = ""
        os.fsync(dir_fd)
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass
        os.close(dir_fd)


def build_event(
    operation: str,
    *,
    result: str,
    request_hash: str,
    returned_note_ids: Iterable[str],
    recall_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one audit event (pure; no I/O).

    `extra` carries operation-specific fields (e.g. a lifecycle transition's new
    status, or a write's declared relationship). It may only *add* keys: the
    ledger fields above are authoritative and can never be overridden by it, so
    the five-field contract holds for every operation.
    """
    engagement, applied_policy = engagement_snapshot()
    event = {
        "schema": SCHEMA,
        "event_id": str(uuid.uuid4()),
        "recorded_at": _utc_now(),
        "operation": operation,
        "engagement": engagement,
        "applied_policy": applied_policy,
        "request_hash": request_hash,
        "returned_note_ids": list(returned_note_ids),
        "recall_id": recall_id,
        "result": result,
    }
    if extra:
        for key, value in extra.items():
            event.setdefault(key, value)
    return event


def emit(
    operation: str,
    *,
    result: str,
    request_hash: str,
    returned_note_ids: Iterable[str],
    recall_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Best-effort emit of one audit event. Never raises.

    Auditing is observability, not a gate: any failure here is reduced to a
    bounded, content-free stderr breadcrumb so the recall/record it describes is
    never broken by it, while the failure is not fully silent.
    """
    try:
        event = build_event(
            operation,
            result=result,
            request_hash=request_hash,
            returned_note_ids=returned_note_ids,
            recall_id=recall_id,
            extra=extra,
        )
        audit_dir = resolve_audit_dir()
        if audit_dir is None:
            return
        _write_event(audit_dir, operation, event)
    except Exception as exc:  # noqa: BLE001 — audit must never break the op
        try:
            sys.stderr.write(
                f"chrono-vault audit: {operation} event not written "
                f"({type(exc).__name__})\n"
            )
        except Exception:  # noqa: BLE001
            pass
