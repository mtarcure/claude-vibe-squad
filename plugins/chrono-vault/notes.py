"""Canonical markdown note validation and atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import audit
from clearance import ClearanceError, apply_record_policy
from vaultroot import VaultRootError, resolve_vault_root


NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
NOTE_ID_RE = re.compile(r"mem-[0-9a-f]{12}")

# The write-time contradiction directive. It is an input instruction, never a
# stored frontmatter field: the caller declares how this write relates to an
# existing active note, and the declaration is reflected through machinery that
# already exists (the `supersedes` list; a `coexists-with:` evidence ref) rather
# than a new schema field. See `record` for the full contract.
CONTRADICTION_FIELD = "contradiction"
CONTRADICTION_RELATIONSHIPS = frozenset({"new", "supersedes", "coexists-with"})
COEXISTS_REF_PREFIX = "coexists-with:"
COEXISTS_CONDITION_PREFIX = "coexists-condition:"
MAX_COEXISTS_CONDITION_CHARS = 512
ACTIVE_STATUSES = ("candidate", "verified")
STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
SENSITIVITIES = frozenset({"internal", "restricted"})

# `target` and `attack_class` describe an attack, so only attack-shaped notes
# require them. An omission is stored as NOT_APPLICABLE rather than null because
# the index parser rejects non-string frontmatter and the FTS columns are text.
ATTACK_NOTE_TYPES = frozenset({"attempt", "finding"})
NOT_APPLICABLE = "none"

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
    "verified_at",
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
# Stamped by the promotion handler when a note reaches `verified`, never
# supplied by a writer: a note cannot be born carrying the timestamp of a
# review it has not had. `promotion_throughput` in
# `scripts/python/memory_metrics.py` counts on this being a real promotion
# time -- it deliberately refuses to fall back to file `mtime`, which every
# reindex resets and which once reported 99 promotions on a vault where
# promotion had never run.
DERIVED_FIELDS = frozenset({"verified_at"})
ALLOWED_INPUT_FIELDS = (
    (frozenset(FRONTMATTER_FIELDS) - DERIVED_FIELDS)
    | IGNORED_LOCATION_FIELDS
    | frozenset({"body"})
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


def _refresh_content_ref(note: dict[str, Any]) -> None:
    evidence_refs = [
        value
        for value in note["evidence_refs"]
        if not value.startswith("note-content-sha256:")
    ]
    note["evidence_refs"] = evidence_refs
    hash_payload = {
        key: note[key]
        for key in (*FRONTMATTER_FIELDS, "body")
        # `verified_at` joins the other bookkeeping fields: a content ref
        # that moved when a note was promoted would say the text changed
        # when only its lifecycle did.
        if key not in {"id", "created_at", "updated_at", "verified_at", "revision"}
    }
    digest = hashlib.sha256(
        json.dumps(
            hash_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    note["evidence_refs"].append(f"note-content-sha256:{digest}")


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

    if note_type in ATTACK_NOTE_TYPES:
        target = _require_nonempty_string(fields.get("target"), "target")
        attack_class = _require_nonempty_string(
            fields.get("attack_class"), "attack_class"
        )
    else:
        target = _optional_string(fields.get("target"), "target") or NOT_APPLICABLE
        attack_class = (
            _optional_string(fields.get("attack_class"), "attack_class")
            or NOT_APPLICABLE
        )

    note = {
        "schema_version": 1,
        "id": None,
        "title": title,
        "type": note_type,
        "status": status,
        "target": target,
        "program": _optional_string(fields.get("program"), "program"),
        "component": _optional_string(fields.get("component"), "component"),
        "attack_class": attack_class,
        "sensitivity": sensitivity,
        "source_task": _optional_string(fields.get("source_task"), "source_task"),
        "source_artifact_hash": _optional_string(
            fields.get("source_artifact_hash"), "source_artifact_hash"
        ),
        "created_at": created_at,
        "updated_at": updated_at,
        # A note recorded straight to `verified` reached that status now.
        # Anything else has no promotion time yet, and null is the honest
        # way to say so -- see DERIVED_FIELDS.
        "verified_at": updated_at if status == "verified" else None,
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

    _refresh_content_ref(note)
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


def _extract_contradiction_directive(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pop and shape-validate the optional `contradiction` directive.

    Returns `(fields_without_directive, directive)` where `directive` always has
    a `relationship`. Shape is caller-controllable and deterministic, so a
    malformed directive is a `SchemaError` like any other bad input — this is
    *not* the "detection was inconclusive" path, which never refuses a write.
    """
    if not isinstance(fields, dict) or CONTRADICTION_FIELD not in fields:
        return fields, {"relationship": "new"}
    cleaned = dict(fields)
    raw = cleaned.pop(CONTRADICTION_FIELD)
    if not isinstance(raw, dict):
        raise SchemaError("contradiction must be an object")
    unknown = set(raw) - {"relationship", "note_id", "condition"}
    if unknown:
        raise SchemaError(f"unknown contradiction fields: {sorted(map(str, unknown))}")
    relationship = raw.get("relationship", "new")
    if relationship not in CONTRADICTION_RELATIONSHIPS:
        raise SchemaError(
            f"contradiction.relationship must be one of {sorted(CONTRADICTION_RELATIONSHIPS)}"
        )
    note_id = raw.get("note_id")
    condition = raw.get("condition")
    if relationship == "new":
        if note_id is not None or condition is not None:
            raise SchemaError("contradiction.new takes no note_id or condition")
        return cleaned, {"relationship": "new"}
    if not isinstance(note_id, str) or NOTE_ID_RE.fullmatch(note_id) is None:
        raise SchemaError("contradiction.note_id must be a canonical note id")
    if relationship == "supersedes":
        if condition is not None:
            raise SchemaError("contradiction.supersedes takes no condition")
        return cleaned, {"relationship": "supersedes", "note_id": note_id}
    if not isinstance(condition, str) or not condition.strip():
        raise SchemaError("contradiction.coexists-with requires a non-empty condition")
    if len(condition) > MAX_COEXISTS_CONDITION_CHARS or "\x00" in condition:
        raise SchemaError("contradiction.condition is too long or contains a null byte")
    return cleaned, {
        "relationship": "coexists-with",
        "note_id": note_id,
        "condition": condition,
    }


def _apply_declared_relationship(note: dict[str, Any], directive: dict[str, Any]) -> None:
    """Reflect a declared relationship onto the note using existing machinery.

    `supersedes` rides the existing frontmatter list (a candidate note may only
    *declare* the pointer; `set_status` ratifies the live transition later).
    `coexists-with` is recorded as a structured evidence ref plus its condition,
    so the "both are right under different conditions" distinction is durable and
    covered by the content hash instead of being merged away.
    """
    relationship = directive["relationship"]
    if relationship == "supersedes":
        target = directive["note_id"]
        if target not in note["supersedes"]:
            note["supersedes"] = [*note["supersedes"], target]
    elif relationship == "coexists-with":
        target = directive["note_id"]
        marker = f"{COEXISTS_REF_PREFIX}{target}"
        refs = [
            ref
            for ref in note["evidence_refs"]
            if not ref.startswith("note-content-sha256:")
        ]
        if marker not in refs:
            refs.append(marker)
            refs.append(f"{COEXISTS_CONDITION_PREFIX}{directive['condition']}")
            note["evidence_refs"] = refs
    else:
        return
    _refresh_content_ref(note)


def _coexists_ids(note: dict[str, Any]) -> set[str]:
    return {
        ref[len(COEXISTS_REF_PREFIX):]
        for ref in note.get("evidence_refs", [])
        if isinstance(ref, str) and ref.startswith(COEXISTS_REF_PREFIX)
    }


def _subject_key(note: dict[str, Any]) -> tuple[str, str] | None:
    """The corpus dimension on which two notes are "about the same thing".

    A concrete `component` is the sharpest subject; a real `target` is the
    fallback. A note with neither carries too little signal to detect against
    without flagging every target-less note against every other, so it returns
    None (treated as no contradiction).
    """
    component = note.get("component")
    if isinstance(component, str) and component.strip():
        return "component", component
    target = note.get("target")
    if isinstance(target, str) and target.strip() and target != NOT_APPLICABLE:
        return "target", target
    return None


def _detect_contradictions(note: dict[str, Any], root: Any) -> tuple[list[str], bool]:
    """Best-effort candidate finder. Returns `(active_same_subject_ids, ran_ok)`.

    Detection is never a gate and never a semantic judge. Any failure — no index
    yet, a stale schema, an unreadable store — returns `([], False)` so the write
    is recorded and flagged rather than refused. An empty but readable store
    conclusively has no contradiction, so it returns `([], True)`.
    """
    subject = _subject_key(note)
    if subject is None:
        return [], True
    column, value = subject
    try:
        from recall import _read_index

        with _read_index(root) as connection:
            if connection is None:
                return [], True
            rows = connection.execute(
                "SELECT m.id FROM notes_fts "
                "JOIN meta AS m ON m.docid = notes_fts.rowid "
                f"WHERE notes_fts.{column} = ? "
                f"AND m.status IN ({','.join('?' for _ in ACTIVE_STATUSES)}) "
                "AND m.note_type = ?",
                (value, *ACTIVE_STATUSES, note["type"]),
            ).fetchall()
    except Exception:  # noqa: BLE001 — detection must never break a write
        return [], False
    return sorted({row[0] for row in rows}), True


def _emit_contradiction_event(
    note_type: str,
    note: dict[str, Any],
    directive: dict[str, Any],
    detected_ids: list[str],
    detection_ok: bool,
) -> None:
    """Record the write-time contradiction check as one auditable declaration.

    The *resolution* is the caller's declaration, recorded here for a reviewer to
    read later — the write is never blocked and the check never grades itself.
    An unreconciled contradiction lands as `flagged`, not a refusal.
    """
    relationship = directive["relationship"]
    declared_ids = set(note["supersedes"]) | _coexists_ids(note)
    unreconciled = [note_id for note_id in detected_ids if note_id not in declared_ids]
    if not detection_ok:
        result = audit.CONTRA_INCONCLUSIVE
    elif unreconciled:
        result = audit.CONTRA_FLAGGED
    elif declared_ids:
        result = audit.CONTRA_DECLARED
    else:
        result = audit.CONTRA_CLEAR
    request_hash = audit.request_digest(
        "contradiction",
        {
            "note_type": note_type,
            "target": note["target"],
            "component": note["component"],
            "relationship": relationship,
        },
    )
    audit.emit(
        "contradiction",
        result=result,
        request_hash=request_hash,
        returned_note_ids=sorted(detected_ids),
        extra={
            "relationship": relationship,
            "declared_note_ids": sorted(declared_ids),
            "unreconciled_note_ids": sorted(unreconciled),
            "detection_ok": detection_ok,
        },
    )


def record(note_type: str, fields: dict) -> dict[str, Any]:
    """Validate, atomically write, and best-effort index a canonical note.

    Emits one `record` audit event (best-effort, never gating): `recorded` when
    the note is written and indexed, `recorded_unindexed` when the note landed
    but the best-effort index update failed, `denied`/`rejected`/`unavailable`
    when it did not. The event carries the new note id (never its content) so a
    write can be told apart from a silent no-op. Every exception is re-raised
    exactly as before.

    It also emits one `contradiction` event describing the write-time check
    against the existing corpus (`clear`/`declared`/`flagged`/`inconclusive`).
    An optional `fields["contradiction"]` directive declares how this write
    relates to an active note — `{"relationship": "supersedes", "note_id": ...}`
    or `{"relationship": "coexists-with", "note_id": ..., "condition": ...}`.
    A malformed directive is a `SchemaError`; a detected-but-undeclared
    contradiction is flagged, not refused.
    """
    request_hash = audit.request_digest(
        "record", {"note_type": note_type, "fields": fields}
    )
    result_code = audit.ERROR
    returned_note_ids: list[str] = []
    try:
        result = _record(note_type, fields)
        returned_note_ids = [result["id"]]
        result_code = (
            audit.RECORDED_UNINDEXED if result["index_dirty"] else audit.RECORDED
        )
        return result
    except ClearanceError:
        result_code = audit.DENIED
        raise
    except SchemaError:
        result_code = audit.REJECTED
        raise
    except (VaultRootError, NoteWriteError):
        result_code = audit.UNAVAILABLE
        raise
    finally:
        audit.emit(
            "record",
            result=result_code,
            request_hash=request_hash,
            returned_note_ids=returned_note_ids,
        )


def _record(note_type: str, fields: dict) -> dict[str, Any]:
    if not isinstance(fields, dict):
        raise SchemaError("fields must be a dict")
    fields, directive = _extract_contradiction_directive(fields)
    note = _normalize(note_type, apply_record_policy(note_type, fields))
    root = resolve_vault_root()

    # Write-time contradiction handling: reflect any declared relationship, run
    # best-effort detection against the corpus, and record the check as one
    # auditable declaration. None of this gates the write — a contradiction is
    # flagged, never refused (losing a note is the worse failure).
    _apply_declared_relationship(note, directive)
    detected_ids, detection_ok = _detect_contradictions(note, root)
    _emit_contradiction_event(note_type, note, directive, detected_ids, detection_ok)

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
