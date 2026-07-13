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
import re
import tempfile
import time
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
VALID_LANES = {"gpt-codex", "claude", "gemini", "kimi", "none"}


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


def build_failover_packet(
    template: bytes, *, lane: str, artifact_path: str, generation: int, attempt_id: str
) -> bytes:
    """Change routing frontmatter while preserving the immutable task body byte-for-byte."""
    try:
        text = template.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ControlPlaneError("packet template is not UTF-8") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ControlPlaneError("packet template is missing YAML frontmatter")
    closing = next((index for index, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"), None)
    if closing is None:
        raise ControlPlaneError("packet template frontmatter is not closed")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    replacements = {
        "to_model": lane,
        "return_artifact": artifact_path,
        "model_override_reason": f"conservative hard-signal failover generation {generation}",
        "failover_generation": str(generation),
        "failover_attempt_id": attempt_id,
    }
    rewritten: list[str] = []
    seen: set[str] = set()
    for line in lines[1:closing]:
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        key = match.group(1) if match else None
        if key in {"failover_generation", "failover_attempt_id"}:
            continue
        if key in replacements:
            rewritten.append(f"{key}: {replacements[key]}{newline}")
            seen.add(key)
        else:
            rewritten.append(line)
    for key, value in replacements.items():
        if key not in seen:
            rewritten.append(f"{key}: {value}{newline}")
    return (lines[0] + "".join(rewritten) + lines[closing] + "".join(lines[closing + 1 :])).encode()


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
        self.packets = self.root / "packets"
        for directory in (self.ledgers, self.locks, self.staging, self.packets):
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

    def list_task_ids(self) -> list[str]:
        """Return only ledgers whose filenames are valid task identifiers."""
        task_ids: list[str] = []
        for path in self.ledgers.glob("*.json"):
            task_id = path.stem
            try:
                self._validate_key(task_id)
            except ControlPlaneError:
                continue
            task_ids.append(task_id)
        return sorted(task_ids)

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
            "dispatched_at": _iso(_utcnow()),
            "accepted_at": None,
            "last_heartbeat_at": None,
            "process_pid": None,
            "runtime_events": [],
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
        gate_required: bool = False,
        gate_record_path: Path | str | None = None,
        gate_subject_path: Path | str | None = None,
        quiescence_seconds: float = 5.0,
        packet_template: bytes | None = None,
        redispatch_path: Path | str | None = None,
        dispatch_ack_seconds: int = 45,
        heartbeat_timeout_seconds: int = 30,
        soft_deadline_seconds: int = 1200,
        hard_deadline_seconds: int = 2400,
    ) -> dict[str, Any]:
        if primary_lane not in VALID_LANES:
            raise ControlPlaneError(f"invalid primary lane: {primary_lane}")
        if backup_lane not in VALID_LANES:
            raise ControlPlaneError(f"invalid backup lane: {backup_lane}")
        if primary_lane == backup_lane:
            backup_lane = "none"
        if (
            not lease_owner
            or lease_seconds <= 0
            or quiescence_seconds < 0
            or dispatch_ack_seconds <= 0
            or heartbeat_timeout_seconds <= 0
            or soft_deadline_seconds <= 0
            or hard_deadline_seconds < soft_deadline_seconds
        ):
            raise ControlPlaneError("lease owner must be non-empty and lease duration positive")
        with self._locked(task_id):
            path = self.ledger_path(task_id)
            if path.exists():
                ledger = self._load(task_id)
                requested_canonical = str(Path(canonical_artifact_path).expanduser().resolve())
                requested_redispatch = (
                    str(Path(redispatch_path).expanduser().resolve()) if redispatch_path else None
                )
                requested_gate_record = (
                    str(Path(gate_record_path).expanduser().resolve()) if gate_record_path else None
                )
                requested_gate_subject = (
                    str(Path(gate_subject_path).expanduser().resolve()) if gate_subject_path else None
                )
                if (
                    ledger["primary_lane"] != primary_lane
                    or ledger["backup_lane"] != backup_lane
                    or ledger["canonical_artifact_path"] != requested_canonical
                    or bool(ledger.get("gate_required", False)) != bool(gate_required)
                    or ledger.get("gate_record_path") != requested_gate_record
                    or ledger.get("gate_subject_path") != requested_gate_subject
                    or float(ledger.get("quiescence_seconds", 5.0)) != float(quiescence_seconds)
                    or ledger.get("packet_template_hash")
                    != (_sha256(packet_template) if packet_template is not None else None)
                    or ledger.get("redispatch_path") != requested_redispatch
                    or int(ledger.get("dispatch_ack_seconds", 45)) != dispatch_ack_seconds
                    or int(ledger.get("heartbeat_timeout_seconds", 30)) != heartbeat_timeout_seconds
                    or int(ledger.get("soft_deadline_seconds", 1200)) != soft_deadline_seconds
                    or int(ledger.get("hard_deadline_seconds", 2400)) != hard_deadline_seconds
                ):
                    raise LeaseConflict("task was already initialized with different routing")
                return self._current_attempt(ledger)
            attempt = self._new_attempt(task_id, 1, primary_lane, lease_owner, lease_seconds, effective_model)
            packet_template_path = None
            packet_template_hash = None
            if packet_template is not None:
                packet_template_path = self.packets / f"{task_id}.md"
                atomic_write_bytes(packet_template_path, packet_template)
                packet_template_hash = _sha256(packet_template)
            ledger = {
                "task_id": task_id,
                "generation": 1,
                "primary_lane": primary_lane,
                "backup_lane": backup_lane,
                "canonical_artifact_path": str(Path(canonical_artifact_path).expanduser().resolve()),
                "gate_required": bool(gate_required),
                "gate_record_path": str(Path(gate_record_path).expanduser().resolve()) if gate_record_path else None,
                "gate_subject_path": str(Path(gate_subject_path).expanduser().resolve()) if gate_subject_path else None,
                "quiescence_seconds": float(quiescence_seconds),
                "packet_template_path": str(packet_template_path) if packet_template_path else None,
                "packet_template_hash": packet_template_hash,
                "redispatch_path": str(Path(redispatch_path).expanduser().resolve()) if redispatch_path else None,
                "dispatch_ack_seconds": int(dispatch_ack_seconds),
                "heartbeat_timeout_seconds": int(heartbeat_timeout_seconds),
                "soft_deadline_seconds": int(soft_deadline_seconds),
                "hard_deadline_seconds": int(hard_deadline_seconds),
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

    def record_runtime_event(
        self,
        *,
        task_id: str,
        attempt_id: str,
        event: str,
        typed_error: bool = False,
        process_confirmed: bool = False,
        valid_artifact: bool = False,
        process_pid: int | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a sensor observation for conservative watchdog processing."""
        if process_pid is not None and process_pid <= 0:
            raise ControlPlaneError("process PID must be positive")
        observed_at = occurred_at or _utcnow()
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            record = {
                "event_id": f"e-{uuid.uuid4().hex}",
                "event": event,
                "occurred_at": _iso(observed_at),
                "typed_error": bool(typed_error),
                "process_confirmed": bool(process_confirmed),
                "valid_artifact": bool(valid_artifact),
                "processed_at": None,
            }
            if process_pid is not None:
                attempt["process_pid"] = process_pid
            if event == "accepted":
                attempt["accepted_at"] = attempt.get("accepted_at") or _iso(observed_at)
                attempt["last_heartbeat_at"] = _iso(observed_at)
                record["processed_at"] = _iso(observed_at)
            elif event == "heartbeat":
                attempt["last_heartbeat_at"] = _iso(observed_at)
                record["processed_at"] = _iso(observed_at)
            attempt.setdefault("runtime_events", []).append(record)
            self._save(task_id, ledger)
            return record

    def pending_runtime_events(self, task_id: str, attempt_id: str) -> list[dict[str, Any]]:
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            return [dict(event) for event in attempt.get("runtime_events", []) if not event.get("processed_at")]

    def mark_runtime_event_processed(self, task_id: str, attempt_id: str, event_id: str) -> None:
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            for event in attempt.get("runtime_events", []):
                if event.get("event_id") == event_id:
                    event["processed_at"] = event.get("processed_at") or _iso(_utcnow())
                    self._save(task_id, ledger)
                    return
            raise ControlPlaneError(f"unknown runtime event: {event_id}")

    def prepare_backup_redispatch(self, *, task_id: str, attempt_id: str) -> Path:
        """Atomically materialize the fenced generation-2 packet in its mailbox."""
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            if attempt_id != ledger.get("current_attempt_id") or attempt.get("generation") != ledger.get("generation"):
                raise FailoverRejected("only the current generation may be redispatched")
            if attempt.get("generation") != 2 or ledger.get("failover_count") != 1:
                raise FailoverRejected("backup redispatch requires the sole generation-2 hop")
            template_path = ledger.get("packet_template_path")
            redispatch_path = ledger.get("redispatch_path")
            if not template_path or not redispatch_path:
                raise FailoverRejected("task has no immutable packet template or redispatch path")
            try:
                template = Path(template_path).read_bytes()
            except OSError as exc:
                raise FailoverRejected("immutable packet template is unreadable") from exc
            if _sha256(template) != ledger.get("packet_template_hash"):
                raise FailoverRejected("immutable packet template hash mismatch")
            packet = build_failover_packet(
                template,
                lane=attempt["lane"],
                artifact_path=attempt["artifact_path"],
                generation=attempt["generation"],
                attempt_id=attempt_id,
            )
            destination = Path(redispatch_path)
            atomic_write_bytes(destination, packet)
            attempt["redispatch_path"] = str(destination)
            attempt["redispatch_hash"] = _sha256(packet)
            attempt["redispatched_at"] = _iso(_utcnow())
            self._save(task_id, ledger)
            return destination

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
            if attempt["terminal_status"] in TERMINAL_STATUSES - {"NEEDS_HUMAN"}:
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
            quiescence_seconds = float(ledger.get("quiescence_seconds", 5.0))
            # Match the shell watcher's integer-second mtime rule exactly.
            age_seconds = max(0.0, float(int(time.time()) - int(after.st_mtime)))
            if age_seconds < quiescence_seconds:
                raise PublicationRejected(
                    f"staging artifact is not quiescent ({age_seconds:.3f}s < {quiescence_seconds:.3f}s)"
                )
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

            effective_gate_required = bool(ledger.get("gate_required", False) or gate_required)
            if effective_gate_required:
                effective_gate_record = gate_record
                effective_subject = subject
                if effective_gate_record is None and ledger.get("gate_record_path"):
                    try:
                        loaded_record = json.loads(Path(ledger["gate_record_path"]).read_text())
                    except (OSError, json.JSONDecodeError) as exc:
                        raise PublicationRejected("publication gate record is unreadable") from exc
                    if not isinstance(loaded_record, dict):
                        raise PublicationRejected("publication gate record must be an object")
                    effective_gate_record = loaded_record
                if effective_subject is None and ledger.get("gate_subject_path"):
                    try:
                        effective_subject = Path(ledger["gate_subject_path"]).read_bytes()
                    except OSError as exc:
                        raise PublicationRejected("publication gate subject is unreadable") from exc
                if effective_subject is None:
                    raise PublicationRejected("publication gate subject is required")
                try:
                    validate_publication_gate(effective_subject, effective_gate_record)
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

    def operator_unlock(
        self,
        *,
        task_id: str,
        attempt_id: str,
        actor: str,
        reason: str,
        approve_publish: bool = False,
        clear_refusal_veto: bool = False,
    ) -> dict[str, Any]:
        """Audit and apply an explicit human unlock; never invoked automatically."""
        if not actor.strip() or not reason.strip():
            raise ControlPlaneError("operator unlock requires actor and reason")
        if not approve_publish and not clear_refusal_veto:
            raise ControlPlaneError("operator unlock requires an explicit action")
        with self._locked(task_id):
            ledger = self._load(task_id)
            attempt = self._attempt(ledger, attempt_id)
            if attempt_id != ledger.get("current_attempt_id"):
                raise ControlPlaneError("only the current generation may be operator-unlocked")
            previous_status = attempt.get("terminal_status")
            previous_veto = bool(ledger.get("refusal_veto_seen"))
            if approve_publish:
                if previous_status not in {"NEEDS_HUMAN", "REFUSED", "POSSIBLE_REFUSAL"}:
                    raise ControlPlaneError(f"attempt is not surfaced for human review: {previous_status}")
                attempt["terminal_status"] = None
                attempt["terminal_signal"] = "operator_publish_approved"
            if clear_refusal_veto:
                ledger["refusal_veto_seen"] = False
                ledger["safety_refusal_seen"] = False
            ledger["audit_events"].append(
                {
                    "type": "operator_unlock",
                    "attempt_id": attempt_id,
                    "actor": actor.strip(),
                    "reason": reason.strip(),
                    "approve_publish": bool(approve_publish),
                    "clear_refusal_veto": bool(clear_refusal_veto),
                    "previous_terminal_status": previous_status,
                    "previous_refusal_veto": previous_veto,
                    "at": _iso(_utcnow()),
                }
            )
            self._save(task_id, ledger)
            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "terminal_status": attempt["terminal_status"],
                "refusal_veto_seen": ledger["refusal_veto_seen"],
            }
