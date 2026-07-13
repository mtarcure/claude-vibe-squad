"""Conservative, durable dispatch/failover control plane.

The mailbox remains the transport.  This module owns only the correctness
boundary around a dispatch: one leased attempt, typed terminal signals,
generation-fenced staging, and CAS publication of the canonical response.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import yaml


HARD_SIGNALS = {"dispatch_ack_failure", "process_exit", "provider_error", "operational_error"}
AMBIGUOUS_SIGNALS = {"slow", "silent", "missed_heartbeat", "soft_deadline", "hard_deadline", "unknown"}
REFUSAL_SIGNALS = {"safety_refusal", "policy_refusal"}
TERMINAL_STATUSES = {"HARD_FAILED", "REFUSED", "POSSIBLE_REFUSAL", "NEEDS_HUMAN", "SUCCEEDED", "ORPHANED"}
GATE_FIELDS = {
    "gate_type",
    "gate_version",
    "subject_id",
    "subject_hash",
    "subject_version",
    "status",
    "evidence_refs",
    "unresolved_items",
    "specialist",
    "reviewer",
    "completed_at",
    "override_actor",
    "override_reason",
}
VALID_LANES = {"gpt-codex", "claude", "gemini", "kimi"}


class ControlPlaneError(RuntimeError):
    """A fail-closed control-plane decision."""


class LeaseConflict(ControlPlaneError):
    """Another attempt still owns the task."""


class FailoverRejected(ControlPlaneError):
    """The observed state does not permit cross-family failover."""


class PublicationRejected(ControlPlaneError):
    """A staging artifact failed fencing, schema, identity, hash, or gate checks."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Durably replace *path* with bytes using temp+fsync+rename+dir-fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_bytes(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


def parse_markdown_frontmatter(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationRejected("artifact is not UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise PublicationRejected("artifact is missing YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise PublicationRejected("artifact frontmatter is not closed") from exc
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise PublicationRejected("artifact frontmatter is invalid YAML") from exc
    if not isinstance(metadata, dict):
        raise PublicationRejected("artifact frontmatter must be a mapping")
    if not metadata.get("status"):
        raise PublicationRejected("artifact frontmatter is missing status")
    return metadata


def validate_publication_gate(subject: bytes, gate_record: dict[str, Any] | None) -> None:
    """Reject missing, incomplete, non-PASS, or stale publication gates."""
    if not gate_record:
        raise PublicationRejected("publication gate is required")
    missing = sorted(field for field in GATE_FIELDS if field not in gate_record)
    if missing:
        raise PublicationRejected(f"publication gate missing fields: {','.join(missing)}")
    if gate_record["gate_type"] not in {"rights", "truth"}:
        raise PublicationRejected("publication gate type must be rights or truth")
    if gate_record["status"] != "PASS":
        raise PublicationRejected(f"publication gate status is {gate_record['status']}, not PASS")
    actual_hash = _sha256(subject)
    if gate_record["subject_hash"] != actual_hash:
        raise PublicationRejected("publication gate subject_hash is stale")


class DispatchControlPlane:
    """File-backed task ledger with per-task flock serialization."""

    def __init__(self, state_root: Path | str | None = None):
        default = Path(__file__).resolve().parents[1] / "_state" / "failover"
        self.root = Path(state_root or os.environ.get("VIBESQUAD_CONTROL_STATE", default)).expanduser().resolve()
        self.ledgers = self.root / "ledgers"
        self.locks = self.root / "locks"
        self.staging = self.root / "staging"
        for directory in (self.ledgers, self.locks, self.staging):
            directory.mkdir(parents=True, exist_ok=True)

    def ledger_path(self, task_id: str) -> Path:
        self._validate_key(task_id)
        return self.ledgers / f"{task_id}.json"

    @staticmethod
    def _validate_key(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ControlPlaneError(f"unsafe task/attempt identifier: {value!r}")

    @contextmanager
    def _locked(self, task_id: str) -> Iterator[None]:
        self._validate_key(task_id)
        lock_path = self.locks / f"{task_id}.lock"
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self, task_id: str) -> dict[str, Any]:
        path = self.ledger_path(task_id)
        if not path.exists():
            raise ControlPlaneError(f"task ledger does not exist: {task_id}")
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlPlaneError(f"task ledger is unreadable: {task_id}") from exc
        if data.get("task_id") != task_id:
            raise ControlPlaneError("task ledger identity mismatch")
        return data

    def read(self, task_id: str) -> dict[str, Any]:
        with self._locked(task_id):
            return self._load(task_id)

    def _save(self, task_id: str, ledger: dict[str, Any]) -> None:
        ledger["updated_at"] = _iso(_utcnow())
        atomic_write_json(self.ledger_path(task_id), ledger)

    def _new_attempt(
        self,
        task_id: str,
        generation: int,
        lane: str,
        lease_owner: str,
        lease_seconds: int,
        effective_model: str | None,
    ) -> dict[str, Any]:
        attempt_id = f"a-{uuid.uuid4().hex}"
        artifact_path = self.staging / task_id / f"{attempt_id}.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": generation,
            "lane": lane,
            "lease_owner": lease_owner,
            "lease_expiry": _iso(_utcnow() + timedelta(seconds=lease_seconds)),
            "terminal_status": None,
            "terminal_signal": None,
            "effective_model_history": [effective_model] if effective_model else [],
            "artifact_path": str(artifact_path),
            "artifact_hash": None,
        }

    def initialize_task(
        self,
        *,
        task_id: str,
        primary_lane: str,
        backup_lane: str,
        lease_owner: str,
        canonical_artifact_path: Path | str,
        lease_seconds: int = 1800,
        effective_model: str | None = None,
    ) -> dict[str, Any]:
        if primary_lane not in VALID_LANES:
            raise ControlPlaneError(f"invalid primary lane: {primary_lane}")
        if backup_lane not in VALID_LANES | {"none"}:
            raise ControlPlaneError(f"invalid backup lane: {backup_lane}")
        if primary_lane == backup_lane:
            raise ControlPlaneError("primary and backup lanes must differ")
        if not lease_owner or lease_seconds <= 0:
            raise ControlPlaneError("lease owner must be non-empty and lease duration positive")
        with self._locked(task_id):
            path = self.ledger_path(task_id)
            if path.exists():
                ledger = self._load(task_id)
                requested_canonical = str(Path(canonical_artifact_path).expanduser().resolve())
                if (
                    ledger["primary_lane"] != primary_lane
                    or ledger["backup_lane"] != backup_lane
                    or ledger["canonical_artifact_path"] != requested_canonical
                ):
                    raise LeaseConflict("task was already initialized with different routing")
                return self._current_attempt(ledger)
            attempt = self._new_attempt(task_id, 1, primary_lane, lease_owner, lease_seconds, effective_model)
            ledger = {
                "task_id": task_id,
                "generation": 1,
                "primary_lane": primary_lane,
                "backup_lane": backup_lane,
                "canonical_artifact_path": str(Path(canonical_artifact_path).expanduser().resolve()),
                "current_attempt_id": attempt["attempt_id"],
                "winner_attempt_id": None,
                "failover_count": 0,
                "safety_refusal_seen": False,
                "refusal_veto_seen": False,
                "attempts": [attempt],
                "audit_events": [],
                "created_at": _iso(_utcnow()),
            }
            self._save(task_id, ledger)
            return attempt

    @staticmethod
    def _current_attempt(ledger: dict[str, Any]) -> dict[str, Any]:
        current = ledger.get("current_attempt_id")
        for attempt in ledger["attempts"]:
            if attempt["attempt_id"] == current:
                return attempt
        raise ControlPlaneError("ledger has no current attempt")

    @staticmethod
    def _attempt(ledger: dict[str, Any], attempt_id: str) -> dict[str, Any]:
        for attempt in ledger["attempts"]:
            if attempt["attempt_id"] == attempt_id:
                return attempt
        raise ControlPlaneError(f"unknown attempt: {attempt_id}")

    def record_terminal_signal(
        self,
        *,
        task_id: str,
        attempt_id: str,
        signal: str,
        typed_error: bool = False,
        process_confirmed: bool = False,
        valid_artifact: bool = False,
    ) -> str:
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            if signal in REFUSAL_SIGNALS or signal == "possible_refusal":
                ledger["refusal_veto_seen"] = True
                if signal in REFUSAL_SIGNALS:
                    ledger["safety_refusal_seen"] = True
                    status = "REFUSED"
                else:
                    status = "POSSIBLE_REFUSAL"
                attempt["terminal_signal"] = signal
                attempt["terminal_status"] = status
                attempt["lease_expiry"] = _iso(_utcnow())
                current = self._current_attempt(ledger)
                if current["attempt_id"] != attempt_id and current["terminal_status"] is None:
                    current["terminal_status"] = "NEEDS_HUMAN"
                    current["terminal_signal"] = "prior_generation_refusal_veto"
                    current["lease_expiry"] = _iso(_utcnow())
                self._save(task_id, ledger)
                return status
            if attempt["terminal_status"] in TERMINAL_STATUSES:
                return attempt["terminal_status"]
            if signal == "dispatch_ack_failure":
                status = "HARD_FAILED"
            elif signal == "process_exit" and process_confirmed and not valid_artifact:
                status = "HARD_FAILED"
            elif signal in {"provider_error", "operational_error"} and typed_error:
                status = "HARD_FAILED"
            elif signal in AMBIGUOUS_SIGNALS or signal in HARD_SIGNALS:
                status = "NEEDS_HUMAN"
            else:
                status = "NEEDS_HUMAN"
            attempt["terminal_signal"] = signal
            attempt["terminal_status"] = status
            attempt["lease_expiry"] = _iso(_utcnow())
            self._save(task_id, ledger)
            return status

    def begin_failover(
        self,
        *,
        task_id: str,
        lease_owner: str,
        lease_seconds: int = 1800,
        effective_model: str | None = None,
    ) -> dict[str, Any]:
        with self._locked(task_id):
            ledger = self._load(task_id)
            if ledger.get("winner_attempt_id"):
                raise FailoverRejected("task already has a published winner")
            if ledger.get("refusal_veto_seen"):
                raise FailoverRejected("a refusal or possible-refusal veto forbids cross-family failover")
            current = self._current_attempt(ledger)
            if current["terminal_status"] != "HARD_FAILED":
                raise FailoverRejected(f"failover requires HARD_FAILED, got {current['terminal_status']}")
            if current["terminal_signal"] not in HARD_SIGNALS:
                raise FailoverRejected("failover requires a hard operational signal")
            if ledger["failover_count"] >= 1:
                raise FailoverRejected("cross-family hop budget exhausted")
            if ledger["backup_lane"] == "none":
                raise FailoverRejected("task has no configured backup lane")
            generation = ledger["generation"] + 1
            attempt = self._new_attempt(
                task_id,
                generation,
                ledger["backup_lane"],
                lease_owner,
                lease_seconds,
                effective_model,
            )
            ledger["generation"] = generation
            ledger["current_attempt_id"] = attempt["attempt_id"]
            ledger["failover_count"] += 1
            ledger["attempts"].append(attempt)
            self._save(task_id, ledger)
            return attempt

    def _validate_artifact_identity(self, task_id: str, metadata: dict[str, Any]) -> None:
        response_id = str(metadata.get("id", ""))
        reply_id = str(metadata.get("in_response_to") or metadata.get("in_reply_to") or "")
        if reply_id != task_id and response_id not in {task_id, f"{task_id}-response"}:
            raise PublicationRejected("artifact task ID does not match its ledger")

    def publish_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        artifact_path: Path | str | None = None,
        gate_required: bool = False,
        gate_record: dict[str, Any] | None = None,
        subject: bytes | None = None,
        operator_override: dict[str, Any] | None = None,
    ) -> Path:
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            candidate = Path(artifact_path or attempt["artifact_path"]).expanduser().resolve()
            expected = Path(attempt["artifact_path"]).resolve()
            if candidate != expected:
                raise PublicationRejected("artifact is outside its attempt-specific staging path")
            if ledger.get("refusal_veto_seen"):
                raise PublicationRejected("publication blocked by refusal veto")
            if attempt["generation"] != ledger["generation"] or attempt_id != ledger["current_attempt_id"]:
                attempt["terminal_status"] = "ORPHANED"
                self._save(task_id, ledger)
                raise PublicationRejected("attempt is generation-fenced")
            if ledger.get("winner_attempt_id") and ledger["winner_attempt_id"] != attempt_id:
                attempt["terminal_status"] = "ORPHANED"
                self._save(task_id, ledger)
                raise PublicationRejected("another attempt already won the CAS")
            if attempt["terminal_status"] not in {None, "SUCCEEDED"}:
                raise PublicationRejected(f"attempt is terminal: {attempt['terminal_status']}")
            try:
                before = candidate.stat()
                data = candidate.read_bytes()
                after = candidate.stat()
            except OSError as exc:
                raise PublicationRejected("staging artifact is unreadable") from exc
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise PublicationRejected("staging artifact changed while hashing")
            metadata = parse_markdown_frontmatter(data)
            self._validate_artifact_identity(task_id, metadata)
            artifact_hash = _sha256(data)

            if ledger.get("winner_attempt_id") == attempt_id:
                canonical = Path(ledger["canonical_artifact_path"])
                if attempt.get("artifact_hash") != artifact_hash:
                    raise PublicationRejected("published winner staging artifact was mutated")
                try:
                    canonical_hash = _sha256(canonical.read_bytes())
                except OSError as exc:
                    raise PublicationRejected("published winner canonical artifact is missing") from exc
                if canonical_hash != artifact_hash:
                    raise PublicationRejected("published winner canonical artifact hash mismatch")
                return canonical

            if gate_required:
                try:
                    validate_publication_gate(subject if subject is not None else data, gate_record)
                except PublicationRejected as gate_error:
                    override = operator_override or {}
                    if not (override.get("authorized") is True and override.get("actor") and override.get("reason")):
                        raise
                    ledger["audit_events"].append(
                        {
                            "type": "publication_gate_override",
                            "attempt_id": attempt_id,
                            "actor": override["actor"],
                            "reason": override["reason"],
                            "gate_error": str(gate_error),
                            "at": _iso(_utcnow()),
                        }
                    )

            canonical = Path(ledger["canonical_artifact_path"])
            atomic_write_bytes(canonical, data)
            attempt["artifact_hash"] = artifact_hash
            attempt["terminal_status"] = "SUCCEEDED"
            attempt["terminal_signal"] = "valid_artifact"
            attempt["lease_expiry"] = _iso(_utcnow())
            ledger["winner_attempt_id"] = attempt_id
            self._save(task_id, ledger)
            return canonical
