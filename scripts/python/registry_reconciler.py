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
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
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
SETTLED_WITHOUT_ENVELOPE = "work-done-no-envelope"
REVIEW_REQUIRED = "review-required"
RUNTIME_MAP_PATH = VAULT_ROOT / "shared" / "specialist-runtime-map.tsv"
DELIVERY_OPEN_STATES = frozenset({"queued", "claimed", "in-progress"})
DELIVERY_BACKOFF_SECONDS = (2, 4, 8, 16)
DELIVERY_MAX_ATTEMPTS = len(DELIVERY_BACKOFF_SECONDS) + 1
REVIEW_CLASSES = frozenset({"standard", "factual", "security-finding"})
WORKER_POOL_FLAG = "SQUAD_WORKER_POOL_ENABLED"
WORKER_POOL_GUARDS_FLAG = "SQUAD_WORKER_POOL_GUARDS_ENABLED"
WORKER_POOL_POLICY_APPROVAL = "SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256"
WORKER_POOL_POLICY_REVIEW_STATE = "SQUAD_WORKER_POOL_POLICY_REVIEW_STATE"
WORKER_PRIORITY = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
WORKER_EPOCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HARD_REQUEUE_SIGNALS = frozenset({"confirmed-worker-exit", "dispatch-ack-failure"})
LANE_AUTHOR_FAMILY = {
    "gpt-codex": "openai",
    "claude": "anthropic",
    "gemini": "google",
    "kimi": "moonshot",
}

# Executing lane -> review lanes it can run IN-LANE (same-family), per
# shared/protocol.md "Mandatory Review Behavior". Only gpt-codex can invoke
# Claude as an in-lane tool today; every OTHER cross-lane pair needs a separate
# reviewer response, which is exactly what this enforcement requires. Lanes are
# normalized to the registry spelling ("gpt-codex", not the map's "codex").
IN_LANE_REVIEW_CAPABLE = {"gpt-codex": {"claude"}}

# Read-only review packets performed by verdict-producing roles must not require
# a review of their own review. The explicit empty write scope is essential:
# reviewer specialists doing implementation work still follow the normal gate.
REVIEW_VERDICT_SPECIALISTS = frozenset({"code-reviewer", "security-analyst"})
TEST_ISOLATION_ENV = "SQUAD_TEST_ISOLATION"
CHRONO_NOTIFY_LOCKDIR = STATE_DIR / "chrono-notify.lockdir"
CHRONO_NOTIFY_RECEIPTS_DIR = STATE_DIR / "chrono-notify-receipts"


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


@contextmanager
def lockdir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
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
                    time.sleep(0.1)
                    continue
                except ProcessLookupError:
                    try:
                        (path / "owner.pid").unlink(missing_ok=True)
                        path.rmdir()
                    except OSError:
                        time.sleep(0.1)
                    continue
                except PermissionError:
                    time.sleep(0.1)
                    continue
            try:
                age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                time.sleep(0.1)
                continue
            if age > timedelta(minutes=5):
                try:
                    (path / "owner.pid").unlink(missing_ok=True)
                    path.rmdir()
                except OSError:
                    time.sleep(0.1)
                continue
            time.sleep(0.1)
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


def emit_event(status: str, task_ref: str, summary: str, nudge: str) -> bool:
    # Durable-first: if queueing fails, do not type an unrecoverable nudge.
    append_chrono_queue(status, task_ref, summary)
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


def worker_pool_enabled() -> bool:
    """P1 worker plumbing is inert unless the operator enables this flag."""
    return os.environ.get(WORKER_POOL_FLAG, "0") == "1"


def worker_pool_guards_enabled() -> bool:
    """P3 policy enforcement is separately default-off from P1 assignment."""
    return os.environ.get(WORKER_POOL_GUARDS_FLAG, "0") == "1"


def _load_enforced_worker_policy(policy_markdown_path: Path | None = None):
    from worker_pool_policy import load_worker_pool_policy

    path = policy_markdown_path or VAULT_ROOT / "shared/worker-pool-policy.md"
    policy = load_worker_pool_policy(path)
    if os.environ.get(WORKER_POOL_POLICY_REVIEW_STATE, "") != "approved":
        raise ValueError(
            f"worker-pool policy review is not approved; set {WORKER_POOL_POLICY_REVIEW_STATE}=approved "
            "only after independent review"
        )
    approved = os.environ.get(WORKER_POOL_POLICY_APPROVAL, "")
    if approved != policy.policy_sha256:
        raise ValueError(
            f"worker-pool policy hash is not approved; set {WORKER_POOL_POLICY_APPROVAL} "
            "to the independently reviewed policy_sha256"
        )
    return policy


def apply_worker_schema_defaults(entry: dict[str, Any]) -> None:
    """Add nullable P1 fields without changing legacy dispatch identity."""
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


def _dispatch_identity(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        entry.get("compatibility_namespace"),
        entry.get("specialist"),
        entry.get("to_model"),
        entry.get("source_namespace"),
        entry.get("return_artifact"),
        tuple(entry.get("write_scope") or ()),
        entry.get("capability_card_sha256"),
        entry.get("verification_contract_sha256"),
        entry.get("review_model"),
        entry.get("mandatory_review"),
        entry.get("review_class", "standard"),
        entry.get("swarm_parent_id"),
        entry.get("swarm_spec_sha256"),
        entry.get("swarm_role"),
        entry.get("swarm_member_result"),
        tuple(entry.get("swarm_children") or ()),
        entry.get("swarm_diff_path"),
        entry.get("subswarm_directive_sha256"),
        entry.get("subswarm_dispatch_sha256"),
        entry.get("subswarm_member_bundle"),
        entry.get("subswarm_max_concurrency"),
    )


def register_task(task_id: str, entry: dict[str, Any]) -> bool:
    """Register once under the shared lock; idempotent retries preserve receipts."""
    apply_worker_schema_defaults(entry)
    validate_member_identity(entry)
    with locked_registry() as _lock:
        registry = load_registry()
        existing = registry.get(task_id)
        if existing is not None:
            if not isinstance(existing, dict) or _dispatch_identity(existing) != _dispatch_identity(entry):
                raise ValueError(f"conflicting task re-registration: {task_id}")
            return False
        registry[task_id] = entry
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return True


def register_swarm(
    parent_task_id: str,
    parent_entry: dict[str, Any],
    member_entries: dict[str, dict[str, Any]],
) -> bool:
    """Atomically register one controller record and every real lane child.

    The full batch is validated before the registry lock is acquired. Retrying an
    identical batch is idempotent; a partial or conflicting prior batch fails
    closed instead of publishing the missing remainder.
    """

    from verification_contract import (
        ContractError,
        author_family_for_lane,
        validate_verification_contract,
        verification_contract_sha256,
    )

    if not isinstance(parent_entry, dict) or not isinstance(member_entries, dict):
        raise ValueError("swarm registration requires object entries")
    if parent_entry.get("dispatch_kind") != "swarm" or parent_entry.get("swarm_role") != "parent":
        raise ValueError("swarm parent must declare dispatch_kind=swarm and swarm_role=parent")
    if "verification_contract" in parent_entry or "verification_contract_sha256" in parent_entry:
        raise ValueError("swarm parent is a controller record and must not carry an author contract")
    spec_hash = str(parent_entry.get("swarm_spec_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", spec_hash):
        raise ValueError("swarm parent requires a lowercase 64-hex swarm_spec_sha256")
    children = parent_entry.get("swarm_children")
    if not isinstance(children, list) or set(children) != set(member_entries) or not children:
        raise ValueError("swarm_children must exactly name every member entry")
    lanes: set[str] = set()
    for child_id, child in member_entries.items():
        apply_worker_schema_defaults(child)
        validate_member_identity(child)
        if child_id != f"{parent_task_id}-swarm-{child.get('to_model')}":
            raise ValueError(f"non-deterministic swarm child id: {child_id}")
        if child.get("dispatch_kind") != "swarm" or child.get("swarm_role") != "member":
            raise ValueError(f"invalid swarm member record: {child_id}")
        if child.get("swarm_parent_id") != parent_task_id or child.get("swarm_spec_sha256") != spec_hash:
            raise ValueError(f"swarm member does not echo parent/spec: {child_id}")
        contract = child.get("verification_contract")
        if not isinstance(contract, dict) or contract.get("dispatch_kind") != "swarm":
            raise ValueError(f"swarm member requires a verification-contract/v1 object: {child_id}")
        try:
            validate_verification_contract(contract)
        except ContractError as exc:
            raise ValueError(f"invalid swarm member verification contract for {child_id}: {exc}") from exc
        if child.get("verification_contract_sha256") != verification_contract_sha256(contract):
            raise ValueError(f"swarm member verification contract hash mismatch: {child_id}")
        lane = str(child.get("to_model") or "")
        if not lane or lane in lanes:
            raise ValueError("swarm member lanes must be nonempty and unique")
        if contract.get("task_id") != child_id:
            raise ValueError(f"swarm member contract task_id mismatch: {child_id}")
        if contract.get("author_family") != author_family_for_lane(lane):
            raise ValueError(f"swarm member contract author_family mismatch: {child_id}")
        echoed_family = str(child.get("author_family") or "")
        if echoed_family and echoed_family != contract.get("author_family"):
            raise ValueError(f"swarm member author_family echo mismatch: {child_id}")
        child["author_family"] = contract["author_family"]
        expected_review = "claude" if lane == "gpt-codex" else "gpt-codex"
        if child.get("mandatory_review") != "true" or child.get("review_model") != expected_review:
            raise ValueError(
                f"swarm member review policy must be mandatory via {expected_review}: {child_id}"
            )
        lanes.add(lane)

    batch = {parent_task_id: parent_entry, **member_entries}
    with locked_registry() as _lock:
        registry = load_registry()
        present = [task_id for task_id in batch if task_id in registry]
        if present:
            if len(present) != len(batch):
                raise ValueError("partial prior swarm registration detected; refusing repair publication")
            for task_id, entry in batch.items():
                existing = registry.get(task_id)
                if not isinstance(existing, dict) or _dispatch_identity(existing) != _dispatch_identity(entry):
                    raise ValueError(f"conflicting swarm re-registration: {task_id}")
            return False
        registry.update(batch)
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return True


def mark_swarm_publication_failed(
    parent_task_id: str, unpublished_children: list[str], detail: str
) -> bool:
    """Mark every unattempted/failed child without deleting the partial batch."""

    if not unpublished_children or not all(isinstance(item, str) and item for item in unpublished_children):
        raise ValueError("publication failure requires nonempty child IDs")
    now = datetime.now(timezone.utc)
    with locked_registry() as _lock:
        registry = load_registry()
        parent = registry.get(parent_task_id)
        if not isinstance(parent, dict) or parent.get("swarm_role") != "parent":
            raise ValueError(f"unknown swarm parent: {parent_task_id}")
        expected = set(parent.get("swarm_children") or [])
        if not set(unpublished_children).issubset(expected):
            raise ValueError("publication failure names a child outside the swarm")
        changed = False
        failures = parent.setdefault("swarm_publication_failures", [])
        record = {"children": sorted(unpublished_children), "detail": detail}
        if record not in failures:
            failures.append(record)
            failures.sort(key=lambda item: (item["children"], item["detail"]))
            changed = True
        for child_id in unpublished_children:
            child = registry.get(child_id)
            if not isinstance(child, dict):
                raise ValueError(f"missing swarm child: {child_id}")
            if child.get("status") == "blocked" and child.get("publication_failure") == detail:
                continue
            child["status"] = "blocked"
            child["publication_failure"] = detail
            child["completed_at"] = now.isoformat()
            child["reconciled_at"] = now.isoformat()
            mark_delivery_terminal(child, now, "swarm-publication-failed")
            changed = True
        if changed:
            parent["reconciled_at"] = now.isoformat()
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return changed


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


def _worker_sort_time(entry: dict[str, Any]) -> datetime:
    value = entry.get("enqueued_at") or entry.get("dispatched_at")
    parsed = parse_dt(value)
    if parsed is None:
        raise ValueError("queued worker-pool task requires enqueued_at or dispatched_at")
    return parsed


def _worker_records(
    workers: list[dict[str, Any]], now: datetime, heartbeat_max_age_seconds: int
) -> dict[str, dict[str, Any]]:
    if heartbeat_max_age_seconds <= 0:
        raise ValueError("heartbeat_max_age_seconds must be positive")
    result: dict[str, dict[str, Any]] = {}
    for raw in workers:
        if not isinstance(raw, dict):
            raise ValueError("worker records must be objects")
        worker_id = _validate_worker_token(raw.get("worker_id"), "worker_id", WORKER_ID_RE)
        if worker_id in result:
            raise ValueError(f"duplicate worker_id: {worker_id}")
        epoch = _validate_worker_token(raw.get("worker_epoch"), "worker_epoch", WORKER_EPOCH_RE)
        lane = _lane(raw.get("lane"))
        if lane not in LANE_AUTHOR_FAMILY:
            raise ValueError(f"invalid worker lane: {lane or 'missing'}")
        heartbeat = parse_dt(raw.get("heartbeat_observed_at"))
        if heartbeat is None:
            raise ValueError(f"worker {worker_id} requires heartbeat_observed_at")
        if heartbeat > now + timedelta(seconds=5):
            raise ValueError(f"worker {worker_id} heartbeat is in the future")
        lead_id = str(raw.get("lead_id") or worker_id).strip()
        _validate_worker_token(lead_id, "lead_id", WORKER_ID_RE)
        subagent_count = raw.get("subagent_count", 0)
        if isinstance(subagent_count, bool) or not isinstance(subagent_count, int) \
            or subagent_count < 0:
            raise ValueError(f"worker {worker_id} subagent_count must be a nonnegative integer")
        result[worker_id] = {
            "worker_id": worker_id,
            "worker_epoch": epoch,
            "lane": lane,
            "heartbeat_observed_at": heartbeat,
            "fresh": now - heartbeat <= timedelta(seconds=heartbeat_max_age_seconds),
            "available": raw.get("available", True) is True,
            "lead_id": lead_id,
            "subagent_count": subagent_count,
        }
    return result


def _pool_review_candidate(entry: dict[str, Any]) -> bool:
    return _is_read_only_review_task(entry) or "review_subject_author_family" in entry


def _pool_review_task(entry: dict[str, Any]) -> bool:
    """Only explicit, typed, read-only review work may use reserved capacity."""
    subject_family = str(entry.get("review_subject_author_family") or "").strip().lower()
    return entry.get("write_scope") == [] and subject_family in set(LANE_AUTHOR_FAMILY.values())


def _cross_family_pool_review(entry: dict[str, Any]) -> bool:
    if not _pool_review_task(entry):
        return False
    return str(entry.get("review_subject_author_family") or "").strip().lower() \
        != LANE_AUTHOR_FAMILY.get(_delivery_lane(entry), "")


def _entry_author_family(entry: dict[str, Any]) -> str:
    contract = entry.get("verification_contract")
    if isinstance(contract, dict):
        family = str(contract.get("author_family") or "").strip().lower()
        if family:
            return family
    return LANE_AUTHOR_FAMILY.get(_delivery_lane(entry), "")


def _review_debt(registry: dict[str, Any]) -> tuple[int, dict[str, int]]:
    by_family = {family: 0 for family in LANE_AUTHOR_FAMILY.values()}
    total = 0
    for entry in registry.values():
        if not isinstance(entry, dict) or str(entry.get("status") or "") != REVIEW_REQUIRED:
            continue
        family = _entry_author_family(entry)
        if family in by_family:
            by_family[family] += 1
        total += 1
    return total, by_family


def _defer_worker_task(
    entry: dict[str, Any], task_id: str, lane: str, stage: str, reason: str,
    deferred: list[dict[str, str]],
) -> bool:
    record = {"task_id": task_id, "lane": lane, "stage": stage, "reason": reason}
    deferred.append(record)
    changed = (
        entry.get("worker_queue_state") != "deferred"
        or entry.get("worker_deferred_stage") != stage
        or entry.get("worker_deferred_reason") != reason
    )
    entry["worker_queue_state"] = "deferred"
    entry["worker_deferred_stage"] = stage
    entry["worker_deferred_reason"] = reason
    return changed


def _admit_worker_task(entry: dict[str, Any]) -> bool:
    changed = any(
        key in entry
        for key in ("worker_deferred_stage", "worker_deferred_reason")
    ) or entry.get("worker_queue_state") != "admitted"
    entry["worker_queue_state"] = "admitted"
    entry.pop("worker_deferred_stage", None)
    entry.pop("worker_deferred_reason", None)
    return changed


def schedule_worker_scan(
    workers: list[dict[str, Any]],
    *,
    now_raw: str | None = None,
    lease_seconds: int = 300,
    heartbeat_max_age_seconds: int = 30,
    nudge_callback: Callable[[dict[str, Any]], bool] | None = None,
    policy_markdown_path: Path | None = None,
    host_snapshot: dict[str, Any] | None = None,
    provider_states: dict[str, str] | None = None,
    provider_usage: dict[str, dict[str, int]] | None = None,
    scan_interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Run one authoritative worker scan and atomically assign queued work.

    Nudges occur only after the assignment is durable. Returning every current
    assignment in ``work`` makes the next periodic scan recover a lost nudge.
    Expiry/silence terminalizes and surfaces work but never clears its assignment.
    """
    if not worker_pool_enabled():
        raise ValueError(f"worker pool is disabled; set {WORKER_POOL_FLAG}=1 to test/activate")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    guards_enabled = worker_pool_guards_enabled()
    policy = None
    validated_host = None
    validated_providers = None
    validated_usage = None
    if guards_enabled:
        from worker_pool_policy import (
            validate_host_snapshot, validate_provider_states, validate_provider_usage,
        )

        policy = _load_enforced_worker_policy(policy_markdown_path)
        validated_host = validate_host_snapshot(host_snapshot)
        validated_providers = validate_provider_states(provider_states)
        validated_usage = validate_provider_usage(provider_usage)
        if scan_interval_seconds != policy.nudge_scan_interval_seconds:
            raise ValueError(
                "scan interval must exactly match the reviewed worker-pool policy"
            )
        lease_seconds = policy.lease_timeout_seconds
        heartbeat_max_age_seconds = policy.heartbeat_timeout_seconds
    now = _parse_action_time(now_raw)
    worker_map = _worker_records(workers, now, heartbeat_max_age_seconds)
    new_assignments: list[dict[str, Any]] = []
    surfaced: list[dict[str, Any]] = []
    work: list[dict[str, Any]] = []
    deferred: list[dict[str, str]] = []

    with locked_registry() as _lock:
        registry = load_registry()
        changed = False
        occupied: set[str] = set()
        active_entries: list[tuple[str, dict[str, Any]]] = []

        for task_id, entry in registry.items():
            if not isinstance(entry, dict):
                continue
            apply_worker_schema_defaults(entry)
            worker_id = str(entry.get("delivery_worker_id") or "")
            if not worker_id or str(entry.get("status") or "") != "in-flight" \
                or str(entry.get("delivery_state") or "") not in DELIVERY_OPEN_STATES:
                continue
            expiry = parse_dt(entry.get("lease_expires_at"))
            observed = parse_dt(entry.get("heartbeat_observed_at"))
            worker = worker_map.get(worker_id)
            if (
                worker
                and str(entry.get("worker_epoch") or "") == worker["worker_epoch"]
                and worker["fresh"]
                and expiry is not None
                and now < expiry
                and (observed is None or worker["heartbeat_observed_at"] > observed)
            ):
                observed = worker["heartbeat_observed_at"]
                expiry = now + timedelta(seconds=lease_seconds)
                entry["heartbeat_observed_at"] = observed.isoformat()
                entry["lease_expires_at"] = expiry.isoformat()
                entry.setdefault("delivery_history", []).append(
                    {
                        "event": "worker-lease-renewed",
                        "at": now.isoformat(),
                        "worker_id": worker_id,
                        "worker_epoch": worker["worker_epoch"],
                        "lease_generation": int(entry.get("lease_generation") or 0),
                        "lease_expires_at": expiry.isoformat(),
                    }
                )
                changed = True
            reason = ""
            if expiry is None or now >= expiry:
                reason = "worker-lease-expired"
                assignment_state = "expired"
            elif observed is None or now - observed > timedelta(seconds=heartbeat_max_age_seconds):
                reason = "worker-heartbeat-silent"
                assignment_state = "silent"
            if reason:
                mark_delivery_terminal(entry, now, reason)
                entry["worker_assignment_state"] = assignment_state
                entry["worker_cancel_reason"] = reason
                entry["worker_cancelled_at"] = now.isoformat()
                surfaced.append({**_worker_fence(entry, task_id), "reason": reason})
                changed = True
                continue
            occupied.add(worker_id)
            active_entries.append((task_id, entry))

        available = {
            worker_id: worker
            for worker_id, worker in worker_map.items()
            if worker["fresh"] and worker["available"] and worker_id not in occupied
        }
        candidates: list[tuple[int, datetime, str, dict[str, Any]]] = []
        due_ids: set[str] = set()
        for task_id, entry in registry.items():
            if not isinstance(entry, dict):
                continue
            apply_worker_schema_defaults(entry)
            if str(entry.get("status") or "") != "in-flight" \
                or str(entry.get("delivery_state") or "") != "queued" \
                or entry.get("delivery_worker_id"):
                continue
            next_at = parse_dt(entry.get("delivery_next_attempt_at"))
            priority = str(entry.get("priority_class") or "normal")
            if priority not in WORKER_PRIORITY:
                raise ValueError(f"invalid priority_class for {task_id}: {priority}")
            validate_member_identity(entry)
            candidates.append((WORKER_PRIORITY[priority], _worker_sort_time(entry), task_id, entry))
            if next_at is None or now >= next_at:
                due_ids.add(task_id)

        sorted_candidates = sorted(candidates, key=lambda item: item[:3])
        if guards_enabled:
            assert policy is not None
            sorted_candidates = (
                [item for item in sorted_candidates if _cross_family_pool_review(item[3])]
                + [item for item in sorted_candidates if not _cross_family_pool_review(item[3])]
            )
            admitted_ids: set[str] = set()
            lane_depth = {lane: 0 for lane in LANE_AUTHOR_FAMILY}
            global_depth = 0
            for _priority, _enqueued, task_id, entry in sorted_candidates:
                lane = _delivery_lane(entry)
                if lane not in policy.lanes:
                    changed |= _defer_worker_task(
                        entry, task_id, lane, "queue", "unknown-lane", deferred
                    )
                    continue
                if global_depth >= policy.queue_depth_cap:
                    changed |= _defer_worker_task(
                        entry, task_id, lane, "queue", "global-queue-depth-cap", deferred
                    )
                    continue
                if lane_depth[lane] >= policy.lanes[lane].queue_depth_cap:
                    changed |= _defer_worker_task(
                        entry, task_id, lane, "queue", "lane-queue-depth-cap", deferred
                    )
                    continue
                global_depth += 1
                lane_depth[lane] += 1
                admitted_ids.add(task_id)
                changed |= _admit_worker_task(entry)
            sorted_candidates = [
                item for item in sorted_candidates
                if item[2] in admitted_ids and item[2] in due_ids
            ]
        else:
            sorted_candidates = [item for item in sorted_candidates if item[2] in due_ids]

        active_by_lane = {lane: 0 for lane in LANE_AUTHOR_FAMILY}
        active_author_count = 0
        active_scopes: list[list[str]] = []
        for _task_id, active_entry in active_entries:
            active_lane = _delivery_lane(active_entry)
            if active_lane in active_by_lane:
                active_by_lane[active_lane] += 1
            if not _pool_review_task(active_entry):
                active_author_count += 1
            scope = active_entry.get("write_scope") or []
            if scope:
                active_scopes.append(scope)
        projected_memory = validated_host["used_memory_mib"] if validated_host else 0
        provider_reserved = {lane: 0 for lane in LANE_AUTHOR_FAMILY}
        provider_recent = {lane: 0 for lane in LANE_AUTHOR_FAMILY}
        minute_ago = now - timedelta(minutes=1)
        for historical in registry.values():
            if not isinstance(historical, dict):
                continue
            historical_lane = _delivery_lane(historical)
            if historical_lane not in provider_reserved:
                continue
            reserved = historical.get("provider_cost_reserved_microusd", 0)
            if isinstance(reserved, int) and not isinstance(reserved, bool) and reserved > 0:
                provider_reserved[historical_lane] += reserved
            admitted_at = parse_dt(historical.get("provider_admitted_at"))
            if admitted_at is not None and admitted_at >= minute_ago:
                provider_recent[historical_lane] += 1
        total_debt, debt_by_family = _review_debt(registry)
        lead_subagent_counts: dict[str, int] = {}
        for worker in worker_map.values():
            lead_id = worker["lead_id"]
            lead_subagent_counts[lead_id] = (
                lead_subagent_counts.get(lead_id, 0) + worker["subagent_count"]
            )

        for _priority, _enqueued, task_id, entry in sorted_candidates:
            lane = _delivery_lane(entry)
            matches = sorted(
                (worker_id for worker_id, worker in available.items() if worker["lane"] == lane)
            )
            if not matches:
                if guards_enabled:
                    changed |= _defer_worker_task(
                        entry, task_id, lane, "lease", "lane-capacity-unavailable", deferred
                    )
                continue
            worker_id = matches[0]
            worker = available.pop(worker_id)
            review_candidate = _pool_review_candidate(entry)
            is_review = _pool_review_task(entry)
            if guards_enabled:
                assert policy is not None and validated_host is not None \
                    and validated_providers is not None and validated_usage is not None
                reason = ""
                lane_policy = policy.lanes[lane]
                usage = validated_usage[lane]
                estimated_cost = entry.get(
                    "estimated_cost_microusd", lane_policy.default_task_cost_microusd
                )
                if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, int) \
                    or estimated_cost < 0:
                    raise ValueError(
                        f"estimated_cost_microusd for {task_id} must be a nonnegative integer"
                    )
                subject_family = str(entry.get("review_subject_author_family") or "").strip().lower()
                if review_candidate and subject_family not in set(LANE_AUTHOR_FAMILY.values()):
                    reason = "review-subject-family-required"
                elif review_candidate and entry.get("write_scope") != []:
                    reason = "review-read-only-required"
                elif len(active_entries) >= policy.global_worker_cap:
                    reason = "global-worker-cap"
                elif active_by_lane[lane] >= lane_policy.max_workers:
                    reason = "lane-worker-cap"
                elif not is_review and active_author_count >= (
                    policy.global_worker_cap - policy.reserved_review_workers
                ):
                    reason = "reserved-review-capacity"
                elif validated_host["memory_pressure"]:
                    reason = "memory-pressure"
                elif validated_host["swap_active"]:
                    reason = "swap-active"
                elif validated_host["compressor_pressure"]:
                    reason = "compressor-pressure"
                elif projected_memory + lane_policy.worker_memory_estimate_mib \
                    >= policy.memory_high_water_mib:
                    reason = "projected-memory-high-water"
                elif validated_providers[lane] == "blocked":
                    reason = "provider-blocked"
                elif validated_providers[lane] == "throttled":
                    reason = "provider-throttled"
                elif usage["active_requests"] + active_by_lane[lane] \
                    >= lane_policy.provider_concurrency_cap:
                    reason = "provider-concurrency-cap"
                elif usage["requests_last_minute"] + provider_recent[lane] \
                    >= lane_policy.provider_rate_limit_per_minute:
                    reason = "provider-rate-limit"
                elif lane_policy.provider_guard == "metered" and (
                    usage["spent_microusd"] + provider_reserved[lane] + estimated_cost
                    > lane_policy.provider_budget_microusd
                ):
                    reason = "provider-budget-exhausted"
                requested_subagents = entry.get("requested_subagent_count", 0)
                if isinstance(requested_subagents, bool) or not isinstance(requested_subagents, int) \
                    or requested_subagents < 0:
                    raise ValueError(
                        f"requested_subagent_count for {task_id} must be a nonnegative integer"
                    )
                if not reason and lead_subagent_counts[worker["lead_id"]] + requested_subagents \
                    > lane_policy.subagent_concurrency_cap:
                    reason = "per-lead-subagent-cap"
                if not reason and is_review:
                    if subject_family == LANE_AUTHOR_FAMILY[lane]:
                        reason = "review-anti-affinity"
                if not reason and not is_review:
                    author_family = _entry_author_family(entry)
                    if total_debt >= policy.review_debt_cap \
                        or debt_by_family.get(author_family, 0) >= lane_policy.review_debt_cap:
                        reason = "review-debt-cap"
                if not reason:
                    from worker_pool_policy import PolicyError, write_scopes_conflict

                    try:
                        candidate_scope = entry.get("write_scope") or []
                        if any(write_scopes_conflict(candidate_scope, scope) for scope in active_scopes):
                            reason = "write-scope-conflict"
                    except PolicyError as exc:
                        raise ValueError(f"invalid write scope for {task_id}: {exc}") from exc
                if reason:
                    available[worker_id] = worker
                    changed |= _defer_worker_task(
                        entry, task_id, lane, "lease", reason, deferred
                    )
                    continue
            lease_generation = int(entry.get("lease_generation") or 0) + 1
            expiry = now + timedelta(seconds=lease_seconds)
            entry["delivery_worker_id"] = worker_id
            entry["worker_epoch"] = worker["worker_epoch"]
            entry["lease_generation"] = lease_generation
            entry["lease_expires_at"] = expiry.isoformat()
            entry["heartbeat_observed_at"] = worker["heartbeat_observed_at"].isoformat()
            entry["worker_assignment_state"] = "assigned"
            if guards_enabled:
                entry["provider_cost_reserved_microusd"] = estimated_cost
                entry["provider_admitted_at"] = now.isoformat()
                provider_reserved[lane] += estimated_cost
                provider_recent[lane] += 1
            entry.pop("worker_cancel_reason", None)
            entry.pop("worker_cancelled_at", None)
            entry.setdefault("delivery_history", []).append(
                {
                    "event": "worker-assigned",
                    "at": now.isoformat(),
                    "attempt_id": entry.get("delivery_attempt_id"),
                    "generation": int(entry.get("delivery_generation") or 1),
                    "worker_id": worker_id,
                    "worker_epoch": worker["worker_epoch"],
                    "lease_generation": lease_generation,
                    "lease_expires_at": expiry.isoformat(),
                }
            )
            new_assignments.append(_worker_fence(entry, task_id))
            if guards_enabled:
                assert policy is not None
                active_entries.append((task_id, entry))
                active_by_lane[lane] += 1
                if not is_review:
                    active_author_count += 1
                scope = entry.get("write_scope") or []
                if scope:
                    active_scopes.append(scope)
                projected_memory += policy.lanes[lane].worker_memory_estimate_mib
                lead_subagent_counts[worker["lead_id"]] += requested_subagents
                _admit_worker_task(entry)
            changed = True

        for task_id, entry in registry.items():
            if not isinstance(entry, dict):
                continue
            worker_id = str(entry.get("delivery_worker_id") or "")
            worker = worker_map.get(worker_id)
            if not worker or str(entry.get("worker_epoch") or "") != worker["worker_epoch"]:
                continue
            if str(entry.get("status") or "") == "in-flight" \
                and str(entry.get("delivery_state") or "") == "queued":
                work.append(_worker_fence(entry, task_id))

        if changed:
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")

    nudge_results: list[dict[str, Any]] = []
    for assignment in new_assignments:
        attempted = nudge_callback is not None
        succeeded = False
        error = ""
        if nudge_callback is not None:
            try:
                succeeded = bool(nudge_callback(dict(assignment)))
            except Exception as exc:  # best-effort transport must not undo assignment
                error = type(exc).__name__
        nudge_results.append(
            {
                "task_id": assignment["task_id"],
                "attempted": attempted,
                "succeeded": succeeded,
                "error": error,
            }
        )
    return {
        "scan_authoritative": True,
        **({
            "guards_enabled": True,
            "policy_sha256": policy.policy_sha256,
            "next_scan_after_seconds": policy.nudge_scan_interval_seconds,
            "deferred": sorted(deferred, key=lambda item: item["task_id"]),
        } if policy is not None else {}),
        "new_assignments": new_assignments,
        "work": sorted(work, key=lambda item: item["task_id"]),
        "surfaced": surfaced,
        "nudges": nudge_results,
    }


def authorize_delivery(
    task_id: str, *, attempt_id: str | None = None, now_raw: str | None = None
) -> dict[str, Any]:
    """Persist one due, head-of-lane delivery authorization before transport."""
    now = _parse_action_time(now_raw)
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            return {"authorized": False, "reason": "unknown-task", "task_id": task_id}
        current_attempt = str(entry.get("delivery_attempt_id") or "")
        if not current_attempt:
            return {"authorized": False, "reason": "legacy-unreceipted-task", "task_id": task_id}
        if attempt_id and attempt_id != current_attempt:
            return {
                "authorized": False,
                "reason": "stale-generation",
                "task_id": task_id,
                "attempt_id": attempt_id,
            }
        status = str(entry.get("status") or "")
        if status != "in-flight":
            return {
                "authorized": False,
                "reason": f"status-{status or 'missing'}",
                "task_id": task_id,
                "attempt_id": current_attempt,
            }
        state = str(entry.get("delivery_state") or "")
        if state != "queued":
            return {
                "authorized": False,
                "reason": f"state-{state or 'missing'}",
                "task_id": task_id,
                "attempt_id": current_attempt,
            }
        assigned = bool(entry.get("delivery_worker_id"))
        if assigned or worker_pool_enabled():
            return {
                "authorized": False,
                "reason": "worker-scan-owned" if assigned else "scheduler-assignment-required",
                "task_id": task_id,
                "attempt_id": current_attempt,
                "delivery_worker_id": entry.get("delivery_worker_id"),
            }
        lane = _delivery_lane(entry)
        head = _delivery_head(registry, lane)
        if head != task_id:
            return {
                "authorized": False,
                "reason": "lane-head-blocked",
                "task_id": task_id,
                "blocked_by": head,
                "attempt_id": current_attempt,
            }
        attempts = int(entry.get("delivery_attempt_count") or 0)
        maximum = int(entry.get("delivery_max_attempts") or DELIVERY_MAX_ATTEMPTS)
        if attempts >= maximum:
            return {
                "authorized": False,
                "reason": "retry-budget-exhausted",
                "task_id": task_id,
                "attempt_id": current_attempt,
                "attempt_count": attempts,
            }
        next_at = parse_dt(entry.get("delivery_next_attempt_at"))
        if next_at and now < next_at:
            return {
                "authorized": False,
                "reason": "not-due",
                "task_id": task_id,
                "attempt_id": current_attempt,
                "next_attempt_at": next_at.isoformat(),
            }

        attempt_number = attempts + 1
        entry["delivery_attempt_count"] = attempt_number
        entry["delivery_retry_count"] = max(0, attempt_number - 1)
        entry["delivery_first_attempt_at"] = entry.get("delivery_first_attempt_at") or now.isoformat()
        entry["delivery_last_attempt_at"] = now.isoformat()
        if attempt_number < maximum:
            delay = DELIVERY_BACKOFF_SECONDS[attempt_number - 1]
            entry["delivery_next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
        else:
            entry["delivery_next_attempt_at"] = None
        entry.setdefault("delivery_history", []).append(
            {
                "event": "delivery-authorized",
                "at": now.isoformat(),
                "attempt_id": current_attempt,
                "generation": int(entry.get("delivery_generation") or 1),
                "attempt_number": attempt_number,
            }
        )
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return {
            "authorized": True,
            "task_id": task_id,
            "attempt_id": current_attempt,
            "generation": int(entry.get("delivery_generation") or 1),
            "attempt_number": attempt_number,
            "retry_count": entry["delivery_retry_count"],
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
        if worker_pool_enabled() and not pooled:
            raise ValueError(f"task requires scheduler assignment before claim: {task_id}")
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
                    mark_delivery_terminal(entry, now, "worker-lease-expired-at-claim")
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


def advance_delivery(
    task_id: str,
    attempt_id: str,
    generation: int,
    lane: str,
    *,
    hard_signal: str | None = None,
    now_raw: str | None = None,
) -> dict[str, Any]:
    """Fence the old generation and queue exactly one failover attempt."""
    now = _parse_action_time(now_raw)
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        current_generation = int(entry.get("delivery_generation") or 1)
        current_attempt = str(entry.get("delivery_attempt_id") or "")
        if generation == current_generation and attempt_id == current_attempt:
            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "generation": generation,
                "delivery_state": entry.get("delivery_state"),
                "idempotent": True,
            }
        if generation != current_generation + 1:
            raise ValueError(
                f"delivery generation must advance exactly once: {current_generation} -> {generation}"
            )
        if not lane or not attempt_id:
            raise ValueError("delivery failover requires lane and attempt ID")
        status = str(entry.get("status") or "")
        state = str(entry.get("delivery_state") or "")
        assigned = bool(entry.get("delivery_worker_id"))
        if status != "in-flight":
            raise ValueError(
                f"delivery is closed for {task_id}: status={status or 'missing'} "
                f"state={state or 'missing'}"
            )
        if assigned:
            if hard_signal not in HARD_REQUEUE_SIGNALS:
                raise ValueError(
                    "worker assignment requeue requires --hard-signal "
                    "confirmed-worker-exit|dispatch-ack-failure"
                )
        elif state not in DELIVERY_OPEN_STATES:
            raise ValueError(
                f"delivery is closed for {task_id}: status={status or 'missing'} "
                f"state={state or 'missing'}"
            )
        entry["delivery_generation"] = generation
        entry["delivery_attempt_id"] = attempt_id
        entry["delivery_lane"] = lane
        entry["delivery_state"] = "queued"
        entry["delivery_attempt_count"] = 0
        entry["delivery_retry_count"] = 0
        entry["delivery_first_attempt_at"] = None
        entry["delivery_last_attempt_at"] = None
        entry["delivery_next_attempt_at"] = now.isoformat()
        entry["claimed_at"] = None
        entry["started_at"] = None
        if assigned:
            entry["delivery_worker_id"] = None
            entry["worker_epoch"] = None
            entry["lease_expires_at"] = None
            entry["heartbeat_observed_at"] = None
            entry["worker_assignment_state"] = None
            entry.pop("worker_cancel_reason", None)
            entry.pop("worker_cancelled_at", None)
        entry.setdefault("delivery_history", []).append(
            {
                "event": "generation-advanced",
                "at": now.isoformat(),
                "attempt_id": attempt_id,
                "generation": generation,
                "lane": lane,
                **({"hard_signal": hard_signal} if hard_signal else {}),
            }
        )
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": generation,
            "delivery_state": "queued",
            "idempotent": False,
        }


def mark_delivery_terminal(entry: dict[str, Any], now: datetime, reason: str) -> bool:
    if not entry.get("delivery_attempt_id") or entry.get("delivery_state") == "terminal":
        return False
    entry["delivery_state"] = "terminal"
    entry["delivery_terminal_at"] = now.isoformat()
    entry["delivery_next_attempt_at"] = None
    entry.setdefault("delivery_history", []).append(
        {
            "event": "terminal",
            "at": now.isoformat(),
            "attempt_id": entry.get("delivery_attempt_id"),
            "generation": int(entry.get("delivery_generation") or 1),
            "reason": reason,
        }
    )
    return True


def strip_frontmatter(text: str) -> dict[str, str]:
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
        meta[key.strip()] = value.strip().strip('"').strip("'")
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


def registry_status(raw: str) -> str:
    """Canonicalize a landed response status; '' for empty/unknown (fail closed)."""
    status = (raw or "").strip()
    status = _STATUS_ALIASES.get(status, status)
    return status if status in SETTLEABLE_STATUSES else ""


def response_status(path: Path) -> str:
    return registry_status(strip_frontmatter(read_text(path)).get("status", ""))


def valid_response_status(status: str) -> bool:
    """True only for a canonical settleable status (rejects '', 'in-flight', typos)."""
    return status in SETTLEABLE_STATUSES


def response_ready(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age >= RESPONSE_MIN_AGE


def response_candidates(task_id: str) -> list[Path]:
    departments = VAULT_ROOT / "departments"
    candidates: list[Path] = []
    for state in ("outbox", "archive"):
        candidates.extend(departments.glob(f"*/{state}/{task_id}-response.md"))
    return sorted(
        set(candidates),
        key=lambda path: (path.stat().st_mtime, str(path)),
        reverse=True,
    )


def landed_response(
    task_id: str, candidates: list[Path] | None = None
) -> tuple[Path | None, str]:
    for candidate in candidates if candidates is not None else response_candidates(task_id):
        if not response_ready(candidate):
            continue
        status = response_status(candidate)
        if valid_response_status(status):
            return candidate, status
    return None, ""


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


def worker_response_issue(task_id: str, entry: dict[str, Any], response: Path) -> str:
    """Return a worker-fence echo failure; empty means the response is current."""
    if not entry.get("delivery_worker_id"):
        return ""
    state = str(entry.get("worker_assignment_state") or "")
    if state in {"expired", "silent"} or entry.get("worker_cancel_reason"):
        return f"worker assignment is terminal: {state}"
    expiry = parse_dt(entry.get("lease_expires_at"))
    if expiry is None:
        return "assigned worker task is missing lease_expires_at"
    landed_at = datetime.fromtimestamp(response.stat().st_mtime, tz=timezone.utc)
    if landed_at > expiry:
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


def swarm_response_issue(entry: dict[str, Any], response: Path) -> str:
    """Return a swarm pin-echo failure; empty means the response matches."""

    if entry.get("dispatch_kind") != "swarm" or entry.get("swarm_role") != "member":
        return ""
    pinned = str(entry.get("swarm_spec_sha256") or "").strip()
    echoed = strip_frontmatter(read_text(response)).get("swarm_spec_sha256", "").strip()
    if not echoed:
        return "missing swarm_spec_sha256 echo"
    if echoed != pinned:
        return f"swarm_spec_sha256 mismatch: dispatched={pinned} response={echoed}"
    return ""


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
    departments = VAULT_ROOT / "departments"
    candidates: list[Path] = []
    for state in ("inbox", "active", "archive"):
        candidates.extend(departments.glob(f"*/{state}/{task_id}.md"))
    return sorted(set(candidates), key=str)


def return_artifact_path(task_id: str, entry: dict[str, Any]) -> Path | None:
    raw = str(entry.get("return_artifact") or "").strip()
    if not raw:
        for packet in task_packet_candidates(task_id):
            raw = strip_frontmatter(read_text(packet)).get("return_artifact", "").strip()
            if raw:
                entry["return_artifact"] = raw
                break
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else VAULT_ROOT / path


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
    value = str(entry.get("review_class") or "standard").strip().lower()
    return value if value in REVIEW_CLASSES else "standard"


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
    """Decide whether a task needs an out-of-lane review response before settling.

    Returns (pending, executing_lane, review_lane). Pending is True for a genuine
    cross-family review: mandatory_review is true, review_model names a real lane,
    and the task's ACTUAL executing lane cannot run that review in-lane.

    The exemption is based on the real execution lane (`to_model`, after dispatch
    override validation) — falling back to the specialist's mapped primary lane
    only when `to_model` is absent — so a specialist mapped to gpt-codex but
    overridden to another lane cannot inherit the gpt-codex->claude exemption.
    An indeterminate lane fails CLOSED (pending) rather than settling silently.
    """
    if str(entry.get("mandatory_review", "")).strip().lower() != "true":
        return (False, "", "")
    review_lane = _lane(entry.get("review_model"))
    if review_lane in ("", "none"):
        return (False, "", "")
    executing_lane = _lane(entry.get("to_model")) \
        or _specialist_primary_lane(str(entry.get("specialist") or ""))
    if not executing_lane:
        # Fix 6: unknown execution lane for a mandatory review with a real
        # reviewer — fail closed (open), never treat as non-pending.
        return (True, "unknown", review_lane)
    if _review_class(entry) in {"factual", "security-finding"}:
        # Explicit review classes never use a read-only-review or in-lane tool
        # exemption. Factual tasks require a coordinator attestation; security
        # findings require a separately authored cross-family review.
        return (True, executing_lane, review_lane)
    if _is_read_only_review_task(entry):
        # A review of a read-only review creates an infinite regress. The exact
        # role allowlist and explicit empty write scope keep this exemption
        # narrow; implementation-bearing reviewer tasks are not exempt.
        return (False, executing_lane, review_lane)
    if executing_lane == review_lane:
        return (False, executing_lane, review_lane)
    if review_lane in IN_LANE_REVIEW_CAPABLE.get(executing_lane, set()):
        return (False, executing_lane, review_lane)
    return (True, executing_lane, review_lane)


def response_review_pending(
    entry: dict[str, Any], response_status: str
) -> tuple[bool, str, str]:
    """Apply the response's explicit review request to the mandatory-review gate.

    An in-lane review capability may settle a response that reports completion,
    but it cannot turn an author's explicit ``needs_review`` result into a final
    state. Implementation-bearing work remains held until explicit settlement.
    """
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


def _validate_standard_review(
    task_id: str, entry: dict[str, Any], review_path: Path
) -> None:
    """Require a targeted, configured, cross-family lane review."""
    meta = strip_frontmatter(read_text(review_path))
    if meta.get("from", "").strip().lower() == "chrono" \
        or meta.get("type", "").strip().upper() == "REVIEW_ATTESTATION":
        raise ValueError("standard review requires an independent lane response")
    if meta.get("type", "").strip().upper() != "RESULT":
        raise ValueError("standard review must be a RESULT response")
    direct_target = meta.get("in_response_to", "").strip()
    reviewed_target = meta.get("reviews", "").strip()
    if task_id not in {direct_target, reviewed_target}:
        raise ValueError("standard review must target the held task")
    reviewer_lane = _lane(meta.get("from"))
    required_lane = _lane(entry.get("review_model"))
    if not reviewer_lane or reviewer_lane != required_lane:
        raise ValueError("standard review must come from the configured review_model")
    reviewer_family = LANE_AUTHOR_FAMILY.get(reviewer_lane, "")
    echoed_family = str(meta.get("reviewer_family") or reviewer_family).strip().lower()
    author_family = _entry_author_family(entry)
    if not reviewer_family or echoed_family != reviewer_family:
        raise ValueError("standard review has invalid reviewer family")
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
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        if entry.get("dispatch_kind") == "swarm" and entry.get("swarm_role") == "parent":
            if entry.get("status") == "complete" and entry.get("review_settled_by") == "chrono-explicit":
                if entry.get("cross_family_review_ref") == normalized_ref:
                    return False
                raise ValueError(f"task already settled with a different review ref: {task_id}")
            if entry.get("status") != REVIEW_REQUIRED or not entry.get("swarm_frozen_at"):
                raise ValueError(f"swarm parent has no frozen bundle awaiting review: {task_id}")
            own_response = str(entry.get("expected_response_path") or "")
            if normalized_ref == own_response:
                raise ValueError("--review-ref must not be the swarm controller's own response")
            review_meta = strip_frontmatter(read_text(_review_path))
            review_status = registry_status(review_meta.get("status", ""))
            if review_status not in {"complete", "needs_review"}:
                raise ValueError("swarm review response status must be complete or needs_review")
            echoed_bundle = review_meta.get("swarm_bundle_sha256", "").strip()
            frozen_bundle = str(entry.get("swarm_bundle_sha256") or "").strip()
            if not echoed_bundle:
                raise ValueError("swarm review response is missing swarm_bundle_sha256")
            if echoed_bundle != frozen_bundle:
                raise ValueError(
                    f"swarm_bundle_sha256 mismatch: frozen={frozen_bundle} review={echoed_bundle}"
                )
            verdict, forced_override = require_approval_verdict(_review_path, force)
            now = datetime.now(timezone.utc)
            entry["status"] = "complete"
            entry["completed_at"] = now.isoformat()
            entry["reconciled_at"] = now.isoformat()
            entry["review_settled_at"] = now.isoformat()
            entry["review_settled_by"] = "chrono-explicit"
            entry["cross_family_review_ref"] = normalized_ref
            entry["review_ref"] = normalized_ref
            entry["verdict"] = verdict
            entry["review_force_override"] = forced_override
            if forced_override:
                entry["review_force_override_at"] = now.isoformat()
            atomic_write(
                _swarm_path(entry.get("expected_response_path")),
                _swarm_envelope(
                    task_id, entry, status="complete", review_ref=normalized_ref
                ),
            )
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
            namespace = str(entry.get("compatibility_namespace") or "coding")
            append_chrono_queue(
                "SWARM-REVIEW-SETTLED-FORCED" if forced_override else "SWARM-REVIEW-SETTLED",
                f"{namespace}/{task_id}",
                "explicit Chrono frozen-bundle settlement; "
                f"review={normalized_ref}; verdict={verdict}; force={forced_override}",
            )
            return True
        if entry.get("status") == "complete" and str(entry.get("review_settled_by") or "").startswith("chrono-"):
            if entry.get("cross_family_review_ref") == normalized_ref:
                return False
            raise ValueError(f"task already settled with a different review ref: {task_id}")
        current_status = str(entry.get("status") or "")
        if current_status not in {REVIEW_REQUIRED, "needs_review"}:
            raise ValueError(
                f"task is not {REVIEW_REQUIRED} or needs_review: {task_id}"
            )
        response, status = landed_response(task_id)
        if response is None:
            raise ValueError(f"task has no landed response: {task_id}")
        issue = capability_response_issue(entry, response)
        if issue:
            raise ValueError(
                f"task response does not match dispatched capability snapshot: {issue}"
            )
        issue = worker_response_issue(task_id, entry, response)
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
            _validate_standard_review(task_id, entry, _review_path)
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
        namespace = str(
            entry.get("compatibility_namespace")
            or entry.get("source_namespace")
            or "coding"
        )
    append_chrono_queue(
        (
            "FACTUAL-ATTESTATION-SETTLED-FORCED"
            if review_class == "factual" and forced_override
            else "FACTUAL-ATTESTATION-SETTLED"
            if review_class == "factual"
            else "REVIEW-SETTLED-FORCED"
            if forced_override
            else "REVIEW-SETTLED"
        ),
        f"{namespace}/{task_id}",
        "explicit Chrono settlement "
        f"class={review_class}; review={normalized_ref}; verdict={verdict}; "
        f"force={forced_override}",
    )
    return True


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
        namespace = str(
            entry.get("compatibility_namespace")
            or entry.get("source_namespace")
            or "coding"
        )
    append_chrono_queue(
        "REVIEW-REOPENED",
        f"{namespace}/{task_id}",
        f"explicit Chrono reopen -> {target}; verdict={stored_verdict or 'MISSING'}",
    )
    return True


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
    namespace = str(entry.get("compatibility_namespace") or "coding")
    to_model = str(entry.get("to_model") or "unknown-model")
    state, snippet = pane_snapshot(to_model)
    if not dry_run:
        append_chrono_queue(f"long-running:{state}", f"{namespace}/{task_id}", snippet)
        touch_marker(task_id)
    return f"long-running:{state} {task_id}"


def _swarm_path(raw: Any) -> Path:
    path = Path(str(raw or "")).expanduser()
    return path if path.is_absolute() else VAULT_ROOT / path


def _swarm_markdown(
    parent_task_id: str, diff: dict[str, Any], controller_status: str
) -> str:
    rendered_status = "needs_review" if controller_status == REVIEW_REQUIRED else controller_status
    lines = [
        f"# Swarm result: {parent_task_id}",
        "",
        f"- Frozen bundle SHA-256: `{diff['diff_sha256']}`",
        f"- Swarm spec SHA-256: `{diff['swarm_spec_sha256']}`",
        f"- Freeze state at creation: `{rendered_status}` (current lifecycle status is in the controller envelope).",
        (
            "- Agreement is corroboration only; explicit frozen-bundle review is required."
            if controller_status == REVIEW_REQUIRED
            else "- Fewer than two valid author families returned; comparison is blocked."
        ),
    ]
    for field, title in (
        ("agreement", "Agreement"),
        ("divergence", "Divergence"),
        ("lane_only", "Lane-only findings"),
        ("coverage_gaps", "Coverage gaps"),
    ):
        lines.extend(["", f"## {title}", ""])
        records = diff[field]
        if not records:
            lines.append("- None.")
            continue
        for record in records:
            key = record.get("finding_key") or record.get("lane") or "coverage-gap"
            lanes = record.get("lanes") or [record.get("lane")]
            lanes_text = ", ".join(str(lane) for lane in lanes if lane)
            status = f"; status={record['status']}" if record.get("status") else ""
            lines.append(f"- `{key}` — lanes: {lanes_text or 'none'}{status}")
    lines.extend(["", "The canonical machine-readable record is the frozen `swarm-diff/v1` JSON.", ""])
    return "\n".join(lines)


def _swarm_envelope(
    parent_task_id: str,
    parent: dict[str, Any],
    *,
    status: str,
    review_ref: str = "",
) -> str:
    rendered_status = "needs_review" if status == REVIEW_REQUIRED else status
    review_line = f"review_ref: {review_ref}\n" if review_ref else ""
    if status == "complete":
        summary = "The deterministic swarm bundle has passed explicit frozen-bundle review."
    elif status == "blocked":
        summary = "The swarm is blocked because fewer than two valid author families returned."
    else:
        summary = "The deterministic swarm bundle is frozen and awaits explicit independent review."
    return (
        "---\n"
        f"id: {parent_task_id}-response\n"
        f"in_response_to: {parent_task_id}\n"
        "from: swarm-controller\n"
        "to: chrono\n"
        "type: RESULT\n"
        f"status: {rendered_status}\n"
        f"return_artifact: {parent.get('return_artifact', '')}\n"
        f"swarm_spec_sha256: {parent.get('swarm_spec_sha256', '')}\n"
        f"swarm_bundle_sha256: {parent.get('swarm_bundle_sha256', '')}\n"
        f"{review_line}"
        "---\n\n"
        f"{summary}\n"
    )


def _write_once_or_verify(path: Path, content: str, label: str) -> str:
    if path.is_file():
        return "" if read_text(path) == content else f"frozen {label} differs from existing file"
    atomic_write(path, content)
    return ""


def _write_swarm_parent_outputs(
    parent_task_id: str, parent: dict[str, Any], diff: dict[str, Any]
) -> str:
    parent["swarm_bundle_sha256"] = diff["diff_sha256"]
    controller_status = str(parent.get("swarm_controller_status") or REVIEW_REQUIRED)
    artifact = _swarm_path(parent.get("return_artifact"))
    envelope = _swarm_path(parent.get("expected_response_path"))
    if not str(parent.get("return_artifact") or ""):
        return "swarm parent is missing return_artifact"
    if not str(parent.get("expected_response_path") or ""):
        return "swarm parent is missing expected_response_path"
    issue = _write_once_or_verify(
        artifact,
        _swarm_markdown(parent_task_id, diff, controller_status),
        "parent markdown artifact",
    )
    if issue:
        return issue
    return _write_once_or_verify(
        envelope,
        _swarm_envelope(parent_task_id, parent, status=controller_status),
        f"parent {controller_status} envelope",
    )


def _freeze_swarm_diff(
    parent_task_id: str,
    parent: dict[str, Any],
    registry: dict[str, Any],
) -> str:
    """Freeze the deterministic diff, synthesizing explicit gaps for absent sidecars."""

    from swarm_diff import (
        SwarmDiffError,
        build_diff,
        load_taxonomy,
        sha256,
        validate_member_result,
    )

    output = _swarm_path(parent.get("swarm_diff_path"))
    def set_viability(diff: dict[str, Any]) -> None:
        valid_task_ids = {
            member["task_id"]
            for member in diff.get("members", [])
            if member.get("status") in {"complete", "needs_review"}
        }
        families = sorted(
            {
                str(
                    (registry[task_id].get("verification_contract") or {}).get(
                        "author_family"
                    )
                    or registry[task_id].get("author_family")
                    or ""
                )
                for task_id in valid_task_ids
                if isinstance(registry.get(task_id), dict)
                and str(
                    (registry[task_id].get("verification_contract") or {}).get(
                        "author_family"
                    )
                    or registry[task_id].get("author_family")
                    or ""
                )
            }
        )
        parent["swarm_valid_author_families"] = families
        parent["swarm_controller_status"] = (
            REVIEW_REQUIRED if len(families) >= 2 else "blocked"
        )

    if output.is_file():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"existing swarm diff is unreadable: {exc}"
        if existing.get("swarm_spec_sha256") != parent.get("swarm_spec_sha256"):
            return "existing swarm diff belongs to a different spec"
        claimed = existing.get("diff_sha256")
        unhashed = dict(existing)
        unhashed.pop("diff_sha256", None)
        if claimed != sha256(unhashed):
            return "existing swarm diff hash is invalid"
        if not parent.get("swarm_controller_status"):
            set_viability(existing)
        return _write_swarm_parent_outputs(parent_task_id, parent, existing)

    try:
        taxonomy = load_taxonomy(_swarm_path(parent.get("swarm_taxonomy_path")))
        sidecars = parent.get("swarm_member_results")
        if not isinstance(sidecars, dict):
            raise SwarmDiffError("swarm_member_results must map lane to sidecar path")
        members: list[dict[str, Any]] = []
        for child_id in parent["swarm_children"]:
            child = registry.get(child_id)
            if not isinstance(child, dict):
                raise SwarmDiffError(f"missing child registry entry: {child_id}")
            lane = str(child.get("to_model") or "")
            sidecar = _swarm_path(sidecars.get(lane))
            child_registry_status = str(child.get("status") or "")
            if child_registry_status in {"blocked", "needs_human", "cancelled", "timed_out"}:
                members.append(
                    {
                        "schema_version": "swarm-member-result/v1",
                        "task_id": child_id,
                        "parent_task_id": parent_task_id,
                        "lane": lane,
                        "swarm_spec_sha256": parent["swarm_spec_sha256"],
                        "status": child_registry_status,
                        "findings": [],
                        "coverage": [],
                        "limitations": [f"member terminal status: {child_registry_status}"],
                    }
                )
            elif sidecar.is_file():
                try:
                    raw_member = json.loads(sidecar.read_text(encoding="utf-8"))
                    members.append(
                        validate_member_result(
                            raw_member, taxonomy, str(parent["swarm_spec_sha256"])
                        )
                    )
                except (OSError, json.JSONDecodeError, SwarmDiffError) as exc:
                    members.append(
                        {
                            "schema_version": "swarm-member-result/v1",
                            "task_id": child_id,
                            "parent_task_id": parent_task_id,
                            "lane": lane,
                            "swarm_spec_sha256": parent["swarm_spec_sha256"],
                            "status": "blocked",
                            "findings": [],
                            "coverage": [],
                            "limitations": [f"invalid member sidecar: {exc}"],
                        }
                    )
            else:
                members.append(
                    {
                        "schema_version": "swarm-member-result/v1",
                        "task_id": child_id,
                        "parent_task_id": parent_task_id,
                        "lane": lane,
                        "swarm_spec_sha256": parent["swarm_spec_sha256"],
                        "status": "blocked",
                        "findings": [],
                        "coverage": [],
                        "limitations": ["member sidecar unavailable at frozen-bundle closure"],
                    }
                )
        diff = build_diff(members, taxonomy, str(parent["swarm_spec_sha256"]))
    except (OSError, json.JSONDecodeError, SwarmDiffError, KeyError) as exc:
        return str(exc)
    set_viability(diff)
    atomic_write(output, json.dumps(diff, indent=2, ensure_ascii=False) + "\n")
    return _write_swarm_parent_outputs(parent_task_id, parent, diff)


def reconcile_swarm_parent(
    parent_task_id: str,
    parent: dict[str, Any],
    registry: dict[str, Any],
    now: datetime,
    dry_run: bool,
) -> tuple[bool, str]:
    """Advance a parent controller from member execution to frozen review hold."""

    if parent.get("status") not in {"in-flight", REVIEW_REQUIRED}:
        return False, f"already-settled {parent_task_id} -> {parent.get('status')}"
    children = parent.get("swarm_children")
    if not isinstance(children, list) or not children:
        return False, f"swarm-parent-invalid {parent_task_id} -> missing children"
    missing = [task_id for task_id in children if not isinstance(registry.get(task_id), dict)]
    if missing:
        return False, f"swarm-parent-invalid {parent_task_id} -> missing {','.join(missing)}"

    changed = False
    deadline = parse_dt(parent.get("swarm_deadline_at"))
    if deadline and now >= deadline:
        for child_id in children:
            child = registry[child_id]
            if child.get("status") in {"in-flight", SETTLED_WITHOUT_ENVELOPE}:
                child["status"] = "timed_out"
                child["completed_at"] = now.isoformat()
                child["reconciled_at"] = now.isoformat()
                mark_delivery_terminal(child, now, "swarm-timeout")
                changed = True

    open_children = [
        child_id
        for child_id in children
        if registry[child_id].get("status") in {"in-flight", SETTLED_WITHOUT_ENVELOPE}
    ]
    if open_children:
        return changed, f"swarm-waiting {parent_task_id} -> {len(open_children)} member(s) open"

    issue = _freeze_swarm_diff(parent_task_id, parent, registry) if not dry_run else ""
    if issue:
        if parent.get("swarm_diff_issue") != issue:
            parent["swarm_diff_issue"] = issue
            parent["reconciled_at"] = now.isoformat()
            changed = True
        return changed, f"swarm-diff-hold {parent_task_id} -> {issue}"

    controller_status = str(parent.get("swarm_controller_status") or REVIEW_REQUIRED)
    if parent.get("swarm_frozen_at"):
        if controller_status == "blocked":
            return changed, f"swarm-blocked {parent_task_id} -> fewer than two valid author families"
        return changed, f"swarm-review-required {parent_task_id} -> frozen bundle awaits explicit review"

    snapshot = [
        {
            "task_id": child_id,
            "lane": registry[child_id].get("to_model"),
            "status": registry[child_id].get("status"),
            "response_path": registry[child_id].get("response_path"),
        }
        for child_id in children
    ]
    if parent.get("status") != controller_status or parent.get("swarm_frozen_members") != snapshot:
        parent["status"] = controller_status
        parent["mandatory_review"] = "true"
        parent["swarm_frozen_members"] = snapshot
        parent["swarm_frozen_at"] = parent.get("swarm_frozen_at") or now.isoformat()
        parent["reconciled_at"] = now.isoformat()
        parent.pop("swarm_diff_issue", None)
        changed = True
    if controller_status == "blocked":
        return changed, f"swarm-blocked {parent_task_id} -> fewer than two valid author families"
    return changed, f"swarm-review-required {parent_task_id} -> frozen bundle awaits explicit review"


def reconcile(task_id_filter: str | None, dry_run: bool) -> tuple[int, list[str]]:
    events: list[tuple[str, str, str, str]] = []
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
            if raw_entry.get("dispatch_kind") == "swarm" and raw_entry.get("swarm_role") == "parent":
                # Parents are advanced in a second pass after every selected child.
                # This preserves child->parent atomicity even when dict insertion
                # order places the controller before its members.
                continue
            current_status = str(raw_entry.get("status", ""))
            legacy_review_open = (
                current_status == "needs_review"
                and response_review_pending(raw_entry, current_status)[0]
            )
            if current_status not in {"in-flight", SETTLED_WITHOUT_ENVELOPE, REVIEW_REQUIRED} \
                and not legacy_review_open:
                if mark_delivery_terminal(raw_entry, now, f"registry-status:{current_status}"):
                    changed += 1
                if task_id_filter:
                    messages.append(f"already-settled {task_id} -> {current_status}")
                continue
            candidates = response_candidates(task_id)
            response, status = landed_response(task_id, candidates)
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

                stray = next((cand for cand in candidates if response_ready(cand)), None)
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
                capability_issue = capability_response_issue(
                    raw_entry, response
                ) or swarm_response_issue(raw_entry, response)
                worker_issue = worker_response_issue(task_id, raw_entry, response)
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
                capability_issue_cleared = (
                    raw_entry.pop("capability_response_issue", None) is not None
                )
                worker_issue_cleared = (
                    raw_entry.pop("worker_response_issue", None) is not None
                )
                contract_issue_cleared = capability_issue_cleared or worker_issue_cleared
                delivery_changed = mark_delivery_terminal(
                    raw_entry, now, f"response:{status}"
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
                    raw_entry, status
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
                    )
                    if hold_changed:
                        changed += 1
                    reason = f"awaiting explicit Chrono settlement after {review_lane} review"
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
                                f"needs {review_lane} review; {reason}",
                                f"REVIEW-REQUIRED: {task_id} ({raw_entry.get('specialist')}, lane "
                                f"{executing_lane}) must be cross-family reviewed by {review_lane} "
                                f"before it can settle. {reason}. Dispatch/read the {review_lane} review, "
                                "then use registry_reconciler.py --settle-review with its review ref.",
                            )
                        )
                    continue
                if current_status == SETTLED_WITHOUT_ENVELOPE:
                    raw_entry["prior_missing_envelope_status"] = current_status
                raw_entry["status"] = status
                raw_entry["completed_at"] = datetime.fromtimestamp(
                    response.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry["auto_reconciled_at"] = now.isoformat()
                raw_entry["response_path"] = str(response.relative_to(VAULT_ROOT))
                raw_entry.pop("invalid_response_status", None)
                changed += 1
                messages.append(f"reconciled {task_id} -> {status} via {namespace}")
                if notification_due(raw_entry, task_id, status, now):
                    events.append(
                        (
                            status,
                            f"{namespace}/{task_id}",
                            response_summary(response),
                            f"{status}: {task_id} response landed in departments/{namespace}/"
                            f"{response.parent.name}/{response.name}; registry reconciled. Read and surface now.",
                        )
                    )
                continue
            if current_status == SETTLED_WITHOUT_ENVELOPE:
                # This is a provisional settled state: it stops counting as
                # running, but a later real envelope must still win.
                continue
            artifact = return_artifact_path(task_id, raw_entry)
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
                    namespace = str(
                        raw_entry.get("compatibility_namespace")
                        or raw_entry.get("source_namespace")
                        or "coding"
                    )
                    raw_entry["status"] = SETTLED_WITHOUT_ENVELOPE
                    raw_entry["work_landed_at"] = artifact_mtime.isoformat()
                    raw_entry["reconciled_at"] = now.isoformat()
                    raw_entry["missing_envelope_artifact"] = str(artifact)
                    mark_delivery_terminal(
                        raw_entry, now, SETTLED_WITHOUT_ENVELOPE
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
        # Evaluate applicable swarm parents after members, under the same lock.
        # A child-filtered outbox callback therefore advances its parent without
        # waiting for the periodic full-registry reconciliation pass.
        for parent_id, parent in registry.items():
            if not isinstance(parent, dict) or parent.get("dispatch_kind") != "swarm" \
                or parent.get("swarm_role") != "parent":
                continue
            children = parent.get("swarm_children") or []
            if task_id_filter and task_id_filter != parent_id and task_id_filter not in children:
                continue
            parent_changed, parent_message = reconcile_swarm_parent(
                parent_id, parent, registry, now, dry_run
            )
            if parent_changed:
                changed += 1
            if parent_message:
                messages.append(parent_message)
        if changed and not dry_run:
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    if not dry_run:
        for status, task_ref, summary, nudge in events:
            nudged = emit_event(status, task_ref, summary, nudge)
            messages.append(f"chrono-nudge {'sent' if nudged else 'queued-only'} {task_ref}")
    return changed, messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id")
    parser.add_argument("--register-task")
    parser.add_argument("--entry-json")
    parser.add_argument("--register-swarm")
    parser.add_argument("--parent-entry-json")
    parser.add_argument("--member-entries-json")
    parser.add_argument("--mark-swarm-publication-failed")
    parser.add_argument("--unpublished-children-json")
    parser.add_argument("--failure-detail")
    parser.add_argument("--authorize-delivery")
    parser.add_argument("--claim-task")
    parser.add_argument("--advance-delivery")
    parser.add_argument("--schedule-workers-json")
    parser.add_argument("--plan-worker-targets-json")
    parser.add_argument("--worker-policy")
    parser.add_argument("--host-snapshot-json")
    parser.add_argument("--provider-states-json")
    parser.add_argument("--provider-usage-json")
    parser.add_argument("--scan-interval-seconds", type=int)
    parser.add_argument("--attempt-id")
    parser.add_argument("--generation", type=int)
    parser.add_argument("--lane")
    parser.add_argument("--worker-id")
    parser.add_argument("--worker-epoch")
    parser.add_argument("--lease-generation", type=int)
    parser.add_argument("--worker-lane")
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--heartbeat-max-age-seconds", type=int, default=30)
    parser.add_argument("--hard-signal", choices=sorted(HARD_REQUEUE_SIGNALS))
    parser.add_argument("--now")
    parser.add_argument("--settle-review")
    parser.add_argument("--review-ref")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reopen")
    parser.add_argument("--reopen-status", choices=("needs_review", "needs_rework"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if bool(args.register_task) != bool(args.entry_json):
        parser.error("--register-task and --entry-json must be used together")
    swarm_registration_values = (
        args.register_swarm,
        args.parent_entry_json,
        args.member_entries_json,
    )
    if any(swarm_registration_values) and not all(swarm_registration_values):
        parser.error(
            "--register-swarm, --parent-entry-json, and --member-entries-json must be used together"
        )
    if args.register_task and args.register_swarm:
        parser.error("choose only one registration action")
    publication_values = (
        args.mark_swarm_publication_failed,
        args.unpublished_children_json,
        args.failure_detail,
    )
    if any(publication_values) and not all(publication_values):
        parser.error(
            "--mark-swarm-publication-failed, --unpublished-children-json, and --failure-detail must be used together"
        )
    if bool(args.settle_review) != bool(args.review_ref):
        parser.error("--settle-review and --review-ref must be used together")
    if args.settle_review and args.reopen:
        parser.error("--settle-review and --reopen are mutually exclusive")
    if args.force and not args.settle_review:
        parser.error("--force is valid only with --settle-review")
    if args.reopen_status and not args.reopen:
        parser.error("--reopen-status requires --reopen")
    delivery_actions = sum(
        bool(value)
        for value in (
            args.authorize_delivery,
            args.claim_task,
            args.advance_delivery,
            args.schedule_workers_json,
            args.plan_worker_targets_json,
        )
    )
    if delivery_actions > 1:
        parser.error("choose only one delivery action")
    if delivery_actions and (
        args.register_task
        or args.register_swarm
        or args.mark_swarm_publication_failed
        or args.settle_review
        or args.reopen
        or args.task_id
        or args.dry_run
    ):
        parser.error("delivery actions cannot be combined with register/reconcile/review actions")
    if args.authorize_delivery:
        try:
            result = authorize_delivery(
                args.authorize_delivery, attempt_id=args.attempt_id, now_raw=args.now
            )
        except (RegistryCorruptError, ValueError) as exc:
            print(json.dumps({"authorized": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.plan_worker_targets_json:
        if not worker_pool_enabled() or not worker_pool_guards_enabled():
            print(json.dumps({"planned": False, "error": "P1 and P3 worker-pool flags are required"}), file=sys.stderr)
            return 2
        try:
            raw = json.loads(args.plan_worker_targets_json)
            providers = json.loads(args.provider_states_json or "null")
            if not isinstance(raw, dict) or set(raw) != {
                "current_targets", "stable_scans", "pressure", "workers"
            } or not isinstance(raw["pressure"], bool):
                raise ValueError("supervisor input keys or pressure value are invalid")
            policy = _load_enforced_worker_policy(
                Path(args.worker_policy) if args.worker_policy else None
            )
            from worker_pool_policy import supervisor_aimd

            result = supervisor_aimd(
                policy,
                current_targets=raw["current_targets"],
                stable_scans=raw["stable_scans"],
                pressure=raw["pressure"],
                provider_states=providers,
                workers=raw["workers"],
            )
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            print(json.dumps({"planned": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.schedule_workers_json:
        try:
            workers = json.loads(args.schedule_workers_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--schedule-workers-json is not valid JSON: {exc}")
        if not isinstance(workers, list):
            parser.error("--schedule-workers-json must decode to a list")
        try:
            host_snapshot = json.loads(args.host_snapshot_json or "null")
            provider_states = json.loads(args.provider_states_json or "null")
            provider_usage = json.loads(args.provider_usage_json or "null")
            result = schedule_worker_scan(
                workers,
                now_raw=args.now,
                lease_seconds=args.lease_seconds,
                heartbeat_max_age_seconds=args.heartbeat_max_age_seconds,
                policy_markdown_path=Path(args.worker_policy) if args.worker_policy else None,
                host_snapshot=host_snapshot,
                provider_states=provider_states,
                provider_usage=provider_usage,
                scan_interval_seconds=args.scan_interval_seconds,
            )
        except (json.JSONDecodeError, OSError, RegistryCorruptError, ValueError) as exc:
            print(json.dumps({"scheduled": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
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
    if args.advance_delivery:
        if not args.attempt_id or args.generation is None or not args.lane:
            parser.error("--advance-delivery requires --attempt-id, --generation, and --lane")
        try:
            result = advance_delivery(
                args.advance_delivery,
                args.attempt_id,
                args.generation,
                args.lane,
                hard_signal=args.hard_signal,
                now_raw=args.now,
            )
        except (RegistryCorruptError, ValueError) as exc:
            print(json.dumps({"advanced": False, "error": str(exc)}), file=sys.stderr)
            return 3
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.register_task:
        if args.dry_run or args.task_id or args.settle_review or args.reopen:
            parser.error(
                "--register-task cannot be combined with reconcile/review/reopen actions"
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
    if args.register_swarm:
        if args.dry_run or args.task_id or args.settle_review or args.reopen:
            parser.error(
                "--register-swarm cannot be combined with reconcile/review/reopen actions"
            )
        try:
            parent_entry = json.loads(args.parent_entry_json)
            member_entries = json.loads(args.member_entries_json)
        except json.JSONDecodeError as exc:
            parser.error(f"swarm registration JSON is invalid: {exc}")
        try:
            registered = register_swarm(
                args.register_swarm, parent_entry, member_entries
            )
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 3
        outcome = "registered" if registered else "idempotent"
        print(f"registry-reconciler swarm: task={args.register_swarm} outcome={outcome}")
        return 0
    if args.mark_swarm_publication_failed:
        if args.dry_run or args.task_id or args.settle_review or args.reopen:
            parser.error("publication failure marking cannot be combined with reconcile/review")
        try:
            child_ids = json.loads(args.unpublished_children_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--unpublished-children-json is invalid: {exc}")
        if not isinstance(child_ids, list):
            parser.error("--unpublished-children-json must decode to a list")
        try:
            changed = mark_swarm_publication_failed(
                args.mark_swarm_publication_failed, child_ids, args.failure_detail
            )
        except (RegistryCorruptError, ValueError) as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 3
        print(
            f"registry-reconciler swarm-publication: task={args.mark_swarm_publication_failed} "
            f"outcome={'marked' if changed else 'idempotent'}"
        )
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
