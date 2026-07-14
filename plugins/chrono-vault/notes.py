"""Canonical markdown note validation and atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vaultroot import resolve_vault_root


NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
SENSITIVITIES = frozenset({"internal", "restricted"})

FRONTMATTER_FIELDS = (
    "schema_version",
    "id",
    "title",
    "type",
    "status",
    "target",
    "program",
    "component",
    "attack_class",
    "sensitivity",
    "source_task",
    "source_artifact_hash",
    "created_at",
    "updated_at",
    "valid_from",
    "valid_to",
    "supersedes",
    "superseded_by",
    "aliases",
    "keywords",
    "evidence_refs",
    "revision",
)
IGNORED_LOCATION_FIELDS = frozenset({"id", "path", "dest"})
ALLOWED_INPUT_FIELDS = (
    frozenset(FRONTMATTER_FIELDS) | IGNORED_LOCATION_FIELDS | frozenset({"body"})
)


class SchemaError(ValueError):
    """A note type or field does not conform to the canonical schema."""


class NoteWriteError(RuntimeError):
    """A validated note could not be written safely."""


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value, field)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SchemaError(f"{field} must be a list of strings")
    return list(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize(note_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(note_type, str) or note_type not in NOTE_TYPES:
        raise SchemaError(f"type must be one of {sorted(NOTE_TYPES)}")
    if not isinstance(fields, dict):
        raise SchemaError("fields must be a dict")

    unknown = [field for field in fields if field not in ALLOWED_INPUT_FIELDS]
    if unknown:
        raise SchemaError(f"unknown fields: {sorted(map(str, unknown))}")

    supplied_type = fields.get("type", note_type)
    if not isinstance(supplied_type, str) or supplied_type not in NOTE_TYPES:
        raise SchemaError(f"type must be one of {sorted(NOTE_TYPES)}")
    if supplied_type != note_type:
        raise SchemaError("fields.type must match note_type")

    status = fields.get("status", "candidate")
    if not isinstance(status, str) or status not in STATUSES:
        raise SchemaError(f"status must be one of {sorted(STATUSES)}")
    sensitivity = fields.get("sensitivity", "internal")
    if not isinstance(sensitivity, str) or sensitivity not in SENSITIVITIES:
        raise SchemaError(
            f"sensitivity must be one of {sorted(SENSITIVITIES)}"
        )

    schema_version = fields.get("schema_version", 1)
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise SchemaError("schema_version must be 1")
    revision = fields.get("revision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision != 1:
        raise SchemaError("revision must be 1 for a new note")

    now = _utc_now()
    created_at = fields.get("created_at", now)
    updated_at = fields.get("updated_at", now)
    _require_nonempty_string(created_at, "created_at")
    _require_nonempty_string(updated_at, "updated_at")

    if fields.get("valid_to") is not None:
        raise SchemaError("valid_to must be null for a new note")

    title = _require_nonempty_string(fields.get("title"), "title")
    if "\n" in title or "\r" in title:
        raise SchemaError("title must be one line")
    body = _require_nonempty_string(fields.get("body"), "body")
    if not body.endswith("\n"):
        body += "\n"

    note = {
        "schema_version": 1,
        "id": None,
        "title": title,
        "type": note_type,
        "status": status,
        "target": _require_nonempty_string(fields.get("target"), "target"),
        "program": _optional_string(fields.get("program"), "program"),
        "component": _optional_string(fields.get("component"), "component"),
        "attack_class": _require_nonempty_string(
            fields.get("attack_class"), "attack_class"
        ),
        "sensitivity": sensitivity,
        "source_task": _optional_string(fields.get("source_task"), "source_task"),
        "source_artifact_hash": _optional_string(
            fields.get("source_artifact_hash"), "source_artifact_hash"
        ),
        "created_at": created_at,
        "updated_at": updated_at,
        "valid_from": _optional_string(fields.get("valid_from"), "valid_from"),
        "valid_to": None,
        "supersedes": _string_list(fields.get("supersedes", []), "supersedes"),
        "superseded_by": _optional_string(
            fields.get("superseded_by"), "superseded_by"
        ),
        "aliases": _string_list(fields.get("aliases", []), "aliases"),
        "keywords": _string_list(fields.get("keywords", []), "keywords"),
        "evidence_refs": _string_list(
            fields.get("evidence_refs", []), "evidence_refs"
        ),
        "revision": 1,
        "body": body,
    }

    hash_payload = {
        key: value
        for key, value in note.items()
        if key not in {"id", "created_at", "updated_at", "revision"}
    }
    digest = hashlib.sha256(
        json.dumps(
            hash_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    content_ref = f"note-content-sha256:{digest}"
    if content_ref not in note["evidence_refs"]:
        note["evidence_refs"].append(content_ref)
    return note


def _serialize(note: dict[str, Any]) -> bytes:
    lines = ["---"]
    for field in FRONTMATTER_FIELDS:
        value = json.dumps(
            note[field],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(f"{field}: {value}")
    lines.extend(("---", ""))
    return ("\n".join(lines) + note["body"]).encode("utf-8")


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise NoteWriteError("secure directory traversal is unavailable")
    return os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)


def _open_or_create_directory(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        return os.open(name, _directory_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise NoteWriteError(f"unsafe or inaccessible note directory: {name}") from exc


def _new_note_id(destination_fd: int) -> str:
    for _ in range(100):
        note_id = f"mem-{secrets.token_hex(6)}"
        try:
            os.stat(
                f"{note_id}.md",
                dir_fd=destination_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return note_id
    raise NoteWriteError("could not allocate a unique note id")


def _write_atomic(destination_fd: int, final_name: str, content: bytes) -> None:
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
                temp_fd = os.open(
                    temp_name,
                    file_flags,
                    0o600,
                    dir_fd=destination_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise NoteWriteError("could not allocate a temporary note file")

        with os.fdopen(temp_fd, "wb", closefd=True) as handle:
            temp_fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temp_name,
            final_name,
            src_dir_fd=destination_fd,
            dst_dir_fd=destination_fd,
        )
        temp_name = ""
        os.fsync(destination_fd)
    except NoteWriteError:
        raise
    except OSError as exc:
        raise NoteWriteError("atomic note write failed") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=destination_fd)
            except OSError:
                pass


def record(note_type: str, fields: dict) -> dict[str, Any]:
    """Validate, atomically write, and best-effort index a canonical note."""
    note = _normalize(note_type, fields)
    root = resolve_vault_root()

    root_fd = -1
    notes_fd = -1
    destination_fd = -1
    try:
        root_fd = os.open(root, _directory_flags())
        notes_fd = _open_or_create_directory(root_fd, "notes")
        destination_fd = _open_or_create_directory(notes_fd, note_type)

        note_id = _new_note_id(destination_fd)
        note["id"] = note_id
        final_name = f"{note_id}.md"
        _write_atomic(destination_fd, final_name, _serialize(note))
    except NoteWriteError:
        raise
    except OSError as exc:
        raise NoteWriteError("could not access the private vault") from exc
    finally:
        for descriptor in (destination_fd, notes_fd, root_fd):
            if descriptor >= 0:
                os.close(descriptor)

    path = root / "notes" / note_type / final_name
    try:
        from index import upsert

        upsert({**note, "path": str(path)})
    except Exception:
        indexed = False
        index_dirty = True
    else:
        indexed = True
        index_dirty = False

    return {
        "id": note_id,
        "path": str(path),
        "indexed": indexed,
        "index_dirty": index_dirty,
    }
