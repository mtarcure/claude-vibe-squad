#!/usr/bin/env python3
"""Transactional record-time gate for the local chrono-vault backbone."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Mapping, Sequence

from cred_broker import canonical_request_sha256


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
FINDING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,191}$")
URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
MAX_CONTENT_BYTES = 1024 * 1024
REDACTED = "[REDACTED]"
RESTRICTED = "[REDACTED:RESTRICTED]"
FRAME_MARKER = "[REDACTED:FRAME_MARKER]"
BEGIN_FRAME = "[BEGIN QUOTED UNTRUSTED NOTE]"
END_FRAME = "[END QUOTED UNTRUSTED NOTE]"
SECRET_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session",
    "signed_url",
    "token",
}
TOKEN_URL_MARKERS = (
    "signature=",
    "x_amz_signature=",
    "x-amz-signature=",
    "sig=",
    "token=",
    "key=",
    "credential=",
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"authorization|password|private[_-]?key|secret|session|token)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)


class GateDenied(RuntimeError):
    """A memory admission or idempotency check failed closed."""


@dataclass(frozen=True)
class SettledArtifact:
    task_id: str
    generation: int
    artifact_bundle_sha256: str
    verification_state: str = "settled"

    def validate(self) -> None:
        _validate_provenance(self.task_id, self.generation, self.artifact_bundle_sha256)
        if self.verification_state not in {"settled", "review_pending", "rejected", "invalidated"}:
            raise ValueError("invalid verification state")


@dataclass(frozen=True)
class MemoryCandidate:
    finding_id: str
    content: str
    source_task_id: str
    source_generation: int
    artifact_bundle_sha256: str
    source_kind: str
    sensitivity: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        if not FINDING_RE.fullmatch(self.finding_id):
            raise ValueError("invalid finding id")
        _validate_provenance(
            self.source_task_id,
            self.source_generation,
            self.artifact_bundle_sha256,
        )
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("finding content must be non-empty text")
        if len(self.content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("finding content is too large")
        if self.sensitivity not in {"public", "internal", "restricted"}:
            raise ValueError("invalid sensitivity")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        try:
            _canonical_json(dict(self.metadata))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be canonical JSON") from exc


@dataclass(frozen=True)
class RecordReceipt:
    record_id: str
    inserted: bool
    content_sha256: str
    broker_body: dict[str, object]
    broker_request_sha256: str


@dataclass(frozen=True)
class RecallResult:
    record_id: str
    framed_content: str
    untrusted: bool
    source_task_id: str
    source_generation: int
    artifact_bundle_sha256: str


def _validate_provenance(task_id: str, generation: int, bundle_hash: str) -> None:
    if not isinstance(task_id, str) or not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid source task id")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
        raise ValueError("source generation must be a positive integer")
    if not isinstance(bundle_hash, str) or not SHA256_RE.fullmatch(bundle_hash):
        raise ValueError("artifact bundle hash must be lowercase SHA-256")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_key(value: object) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value))
    return re.sub(r"[^a-z0-9]+", "_", separated.casefold()).strip("_")


def _is_secret_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in SECRET_KEYS or any(
        normalized.endswith(f"_{secret_key}") for secret_key in SECRET_KEYS
    )


def _redact_url(match: re.Match[str]) -> str:
    value = match.group(0)
    lowered = value.casefold()
    normalized = lowered.replace("%2d", "-").replace("%5f", "_")
    if any(marker in normalized for marker in TOKEN_URL_MARKERS):
        return "[REDACTED_URL]"
    return value


def _sanitize_string(
    value: str,
    provider_secrets: Sequence[str],
    restricted_values: Sequence[str],
) -> str:
    sanitized = value.replace(BEGIN_FRAME, FRAME_MARKER).replace(END_FRAME, FRAME_MARKER)
    for secret in (*provider_secrets, *restricted_values):
        if secret:
            sanitized = re.compile(re.escape(secret), re.IGNORECASE).sub(REDACTED, sanitized)
    sanitized = PRIVATE_KEY_RE.sub(REDACTED, sanitized)
    sanitized = SECRET_ASSIGNMENT_RE.sub(REDACTED, sanitized)
    sanitized = BEARER_RE.sub(REDACTED, sanitized)
    return URL_RE.sub(_redact_url, sanitized)


def _sanitize_value(
    value: object,
    provider_secrets: Sequence[str],
    restricted_values: Sequence[str],
) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED
            if _is_secret_key(key)
            else _sanitize_value(item, provider_secrets, restricted_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, provider_secrets, restricted_values) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value, provider_secrets, restricted_values)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return REDACTED


def _frame_untrusted(content: str) -> str:
    safe = content.replace(BEGIN_FRAME, FRAME_MARKER).replace(END_FRAME, FRAME_MARKER)
    quoted = "\n".join(f"> {line}" for line in safe.splitlines() or [""])
    return f"{BEGIN_FRAME}\n{quoted}\n{END_FRAME}"


class MemoryGate:
    """SQLite-backed gate whose settled registry is supplied by the supervisor."""

    def __init__(
        self,
        database_path: Path,
        *,
        settled_artifacts: Sequence[SettledArtifact],
        provider_secrets: Sequence[str] = (),
        restricted_values: Sequence[str] = (),
    ) -> None:
        path = Path(database_path)
        if not path.is_absolute() or "\x00" in str(path):
            raise ValueError("vault index path must be absolute")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = path
        self._provider_secrets = tuple(provider_secrets)
        self._restricted_values = tuple(restricted_values)
        if any(not isinstance(value, str) or not value for value in self._provider_secrets):
            raise ValueError("provider secrets must be non-empty strings")
        if any(not isinstance(value, str) or not value for value in self._restricted_values):
            raise ValueError("restricted values must be non-empty strings")
        registry: dict[tuple[str, int, str], str] = {}
        for artifact in settled_artifacts:
            artifact.validate()
            key = (
                artifact.task_id,
                artifact.generation,
                artifact.artifact_bundle_sha256,
            )
            prior = registry.get(key)
            if prior is not None and prior != artifact.verification_state:
                raise ValueError("conflicting settled-artifact registry entries")
            registry[key] = artifact.verification_state
        self._settled_registry = registry
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    record_id TEXT PRIMARY KEY,
                    finding_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    source_generation INTEGER NOT NULL,
                    artifact_bundle_sha256 TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    created_ns INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memory_records_provenance
                    ON memory_records(source_task_id, source_generation, artifact_bundle_sha256);
                CREATE TABLE IF NOT EXISTS memory_gate_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    record_id TEXT,
                    provenance_sha256 TEXT,
                    content_sha256 TEXT,
                    detail TEXT NOT NULL,
                    created_ns INTEGER NOT NULL
                );
                """
            )
        os.chmod(self.database_path, 0o600)

    def _provenance_key(self, item: MemoryCandidate) -> tuple[str, int, str]:
        return (
            item.source_task_id,
            item.source_generation,
            item.artifact_bundle_sha256,
        )

    def _provenance_hash(self, item: MemoryCandidate) -> str:
        return _sha256_text(_canonical_json(self._provenance_key(item)))

    def _record_id(self, item: MemoryCandidate) -> str:
        material = {
            "finding_id": item.finding_id,
            "source_task_id": item.source_task_id,
            "source_generation": item.source_generation,
            "artifact_bundle_sha256": item.artifact_bundle_sha256,
        }
        return f"memg-{_sha256_text(_canonical_json(material))[:32]}"

    def _append_log(
        self,
        *,
        action: str,
        decision: str,
        detail: str,
        record_id: str | None = None,
        provenance_sha256: str | None = None,
        content_sha256: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO memory_gate_log(
                    action, decision, record_id, provenance_sha256,
                    content_sha256, detail, created_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    decision,
                    record_id,
                    provenance_sha256,
                    content_sha256,
                    detail,
                    time.time_ns(),
                ),
            )
            connection.commit()

    def _deny(self, item: MemoryCandidate, detail: str) -> None:
        self._append_log(
            action="record",
            decision="deny",
            detail=detail,
            record_id=self._record_id(item),
            provenance_sha256=self._provenance_hash(item),
        )
        raise GateDenied(detail)

    def record(self, item: MemoryCandidate) -> RecordReceipt:
        try:
            item.validate()
        except ValueError as exc:
            raise GateDenied(str(exc)) from None
        if item.source_kind != "verified_finding":
            self._deny(item, "record source must be a verified finding")
        if self._settled_registry.get(self._provenance_key(item)) != "settled":
            self._deny(item, "finding does not match exact settled provenance")

        if item.sensitivity == "restricted":
            content = RESTRICTED
            metadata: object = {"restricted": RESTRICTED}
        else:
            content = _sanitize_string(
                item.content,
                self._provider_secrets,
                self._restricted_values,
            )
            metadata = _sanitize_value(
                dict(item.metadata),
                self._provider_secrets,
                self._restricted_values,
            )
        metadata_json = _canonical_json(metadata)
        content_sha256 = _sha256_text(
            _canonical_json(
                {
                    "content": content,
                    "metadata": metadata,
                    "sensitivity": item.sensitivity,
                }
            )
        )
        record_id = self._record_id(item)
        provenance_sha256 = self._provenance_hash(item)
        inserted = False
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT content_sha256 FROM memory_records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                if existing is not None:
                    if existing["content_sha256"] != content_sha256:
                        connection.rollback()
                        self._deny(item, "idempotency conflict for settled finding")
                else:
                    connection.execute(
                        """
                        INSERT INTO memory_records(
                            record_id, finding_id, source_task_id, source_generation,
                            artifact_bundle_sha256, sensitivity, content, metadata_json,
                            content_sha256, created_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            item.finding_id,
                            item.source_task_id,
                            item.source_generation,
                            item.artifact_bundle_sha256,
                            item.sensitivity,
                            content,
                            metadata_json,
                            content_sha256,
                            time.time_ns(),
                        ),
                    )
                    inserted = True
                connection.execute(
                    """
                    INSERT INTO memory_gate_log(
                        action, decision, record_id, provenance_sha256,
                        content_sha256, detail, created_ns
                    ) VALUES ('record', 'allow', ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        provenance_sha256,
                        content_sha256,
                        "inserted" if inserted else "idempotent_retry",
                        time.time_ns(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise GateDenied("local vault transaction failed closed") from exc

        broker_body: dict[str, object] = {
            "note_type": "verified_finding",
            "record_id": record_id,
            "finding_id": item.finding_id,
            "source_task_id": item.source_task_id,
            "source_generation": item.source_generation,
            "artifact_bundle_sha256": item.artifact_bundle_sha256,
            "sensitivity": item.sensitivity,
            "content": content,
            "metadata": metadata,
        }
        return RecordReceipt(
            record_id=record_id,
            inserted=inserted,
            content_sha256=content_sha256,
            broker_body=broker_body,
            broker_request_sha256=canonical_request_sha256(broker_body),
        )

    def get(self, record_id: str) -> dict[str, object]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memory_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return {
            "record_id": row["record_id"],
            "finding_id": row["finding_id"],
            "source_task_id": row["source_task_id"],
            "source_generation": row["source_generation"],
            "artifact_bundle_sha256": row["artifact_bundle_sha256"],
            "sensitivity": row["sensitivity"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "content_sha256": row["content_sha256"],
        }

    def recall(self, query: str = "", *, limit: int = 10) -> list[RecallResult]:
        if not isinstance(query, str) or "\x00" in query:
            raise ValueError("recall query must be text")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("recall limit must be in 1..100")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                """
                SELECT record_id, content, source_task_id, source_generation,
                       artifact_bundle_sha256
                FROM memory_records
                WHERE content LIKE ? ESCAPE '\\'
                ORDER BY created_ns, record_id
                LIMIT ?
                """,
                (pattern, limit),
            ).fetchall()
            connection.commit()
        self._append_log(
            action="recall",
            decision="allow",
            detail=f"results:{len(rows)}",
            content_sha256=_sha256_text(query),
        )
        return [
            RecallResult(
                record_id=row["record_id"],
                framed_content=_frame_untrusted(row["content"]),
                untrusted=True,
                source_task_id=row["source_task_id"],
                source_generation=row["source_generation"],
                artifact_bundle_sha256=row["artifact_bundle_sha256"],
            )
            for row in rows
        ]

    def count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM memory_records").fetchone()
        return int(row["count"])

    def action_log(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT action, decision, record_id, provenance_sha256,
                       content_sha256, detail, created_ns
                FROM memory_gate_log
                ORDER BY sequence
                """
            ).fetchall()
        return [dict(row) for row in rows]
