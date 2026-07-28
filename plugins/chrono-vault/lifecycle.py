"""Lifecycle operations for canonical Chrono memory notes."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import index as vault_index
import notes as vault_notes
from vaultroot import resolve_vault_root


OUTCOMES = frozenset({"used", "not_useful", "incorrect"})
NOTE_ID_PATTERN = re.compile(r"mem-[0-9a-f]{12}")


class LifecycleError(RuntimeError):
    """A lifecycle request is invalid or could not be applied safely."""


class NoteNotFound(LifecycleError):
    """The requested canonical note does not exist."""


class RevisionConflict(LifecycleError):
    """The note changed since the caller's expected revision."""


class UsageConflict(LifecycleError):
    """The recall/note pair already carries different usage feedback."""


def _validate_note_id(note_id: str, field: str = "id") -> str:
    if not isinstance(note_id, str) or NOTE_ID_PATTERN.fullmatch(note_id) is None:
        raise LifecycleError(f"{field} must be a canonical memory note id")
    return note_id


def _find_note(root: Path, note_id: str) -> tuple[Path, dict[str, Any]]:
    _validate_note_id(note_id)
    candidates = [
        root / "notes" / note_type / f"{note_id}.md"
        for note_type in sorted(vault_notes.NOTE_TYPES)
    ]
    matches = [path for path in candidates if os.path.lexists(path)]
    if not matches:
        raise NoteNotFound(f"note does not exist: {note_id}")
    if len(matches) != 1:
        raise LifecycleError(f"duplicate canonical note id: {note_id}")
    path = matches[0]
    try:
        parsed = vault_index._parse_note(path)
    except (vault_index.MalformedNote, OSError) as exc:
        raise LifecycleError(f"note is malformed or unsafe: {note_id}") from exc
    return path, parsed


def _public_note(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        **{field: parsed[field] for field in vault_notes.FRONTMATTER_FIELDS},
        "body": parsed["body"],
    }


def get_note(id: str) -> dict[str, Any]:
    """Return one complete canonical note by stable ID."""
    note_id = _validate_note_id(id)
    root = resolve_vault_root()
    with vault_index._locked(root):
        _, parsed = _find_note(root, note_id)
        return _public_note(parsed)


def _ensure_index_for_write(root: Path) -> None:
    db_path = root / "index" / "kg.db"
    current = vault_index._existing_schema_is_current(db_path)
    if current is None or current is False:
        vault_index.rebuild_index()


def _stage_note(path: Path, content: bytes) -> dict[str, Any]:
    directory_fd = os.open(path.parent, vault_notes._directory_flags())
    temp_name = ""
    temp_fd = -1
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for _ in range(100):
            temp_name = f".{path.name}.{uuid.uuid4().hex[:12]}.lifecycle.tmp"
            try:
                temp_fd = os.open(
                    temp_name,
                    flags,
                    0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            raise LifecycleError("could not allocate lifecycle staging file")

        with os.fdopen(temp_fd, "wb", closefd=True) as handle:
            temp_fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return {
            "path": path,
            "directory_fd": directory_fd,
            "temp_name": temp_name,
            "published": False,
            "original": path.read_bytes(),
        }
    except Exception:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)
        raise


def _publish_stage(stage: dict[str, Any]) -> None:
    os.replace(
        stage["temp_name"],
        stage["path"].name,
        src_dir_fd=stage["directory_fd"],
        dst_dir_fd=stage["directory_fd"],
    )
    stage["temp_name"] = ""
    stage["published"] = True
    os.fsync(stage["directory_fd"])


def _close_stage(stage: dict[str, Any]) -> None:
    if stage["temp_name"]:
        try:
            os.unlink(stage["temp_name"], dir_fd=stage["directory_fd"])
        except OSError:
            pass
    os.close(stage["directory_fd"])


def _restore_published(stages: list[dict[str, Any]]) -> None:
    failures: list[str] = []
    for stage in reversed(stages):
        if not stage["published"]:
            continue
        try:
            vault_notes._write_atomic(
                stage["directory_fd"],
                stage["path"].name,
                stage["original"],
            )
        except Exception:
            failures.append(stage["path"].name)
    if failures:
        raise LifecycleError(
            f"lifecycle rollback failed for notes: {sorted(failures)}"
        )


def _updated_notes(
    root: Path,
    note_id: str,
    new_status: str,
    replacement_id: str | None,
    expected_revision: int,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    primary_path, primary = _find_note(root, note_id)
    if primary["revision"] != expected_revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, found {primary['revision']}"
        )

    updates: dict[str, tuple[Path, dict[str, Any]]] = {
        note_id: (primary_path, dict(primary))
    }
    old_replacement_id = primary["superseded_by"]
    if old_replacement_id is not None:
        old_path, old_replacement = _find_note(root, old_replacement_id)
        updates[old_replacement_id] = (old_path, dict(old_replacement))

    if replacement_id is not None and replacement_id not in updates:
        replacement_path, replacement = _find_note(root, replacement_id)
        updates[replacement_id] = (replacement_path, dict(replacement))

    primary_update = updates[note_id][1]
    primary_update["status"] = new_status
    primary_update["superseded_by"] = replacement_id

    changed_targets: set[str] = set()
    if old_replacement_id is not None and old_replacement_id != replacement_id:
        old_update = updates[old_replacement_id][1]
        old_update["supersedes"] = [
            value for value in old_update["supersedes"] if value != note_id
        ]
        changed_targets.add(old_replacement_id)
    if replacement_id is not None:
        replacement_update = updates[replacement_id][1]
        if note_id not in replacement_update["supersedes"]:
            replacement_update["supersedes"] = [
                *replacement_update["supersedes"],
                note_id,
            ]
            changed_targets.add(replacement_id)

    updated_at = vault_notes._utc_now()
    primary_update["revision"] += 1
    primary_update["updated_at"] = updated_at
    vault_notes._refresh_content_ref(primary_update)
    for target_id in changed_targets:
        target = updates[target_id][1]
        target["revision"] += 1
        target["updated_at"] = updated_at
        vault_notes._refresh_content_ref(target)

    return {
        current_id: value
        for current_id, value in updates.items()
        if current_id == note_id or current_id in changed_targets
    }


def set_status(
    id: str,
    new_status: str,
    reason: str,
    expected_revision: int,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Compare-and-swap a status and atomically update supersede pointers."""
    note_id = _validate_note_id(id)
    if not isinstance(new_status, str) or new_status not in vault_notes.STATUSES:
        raise LifecycleError(f"new_status must be one of {sorted(vault_notes.STATUSES)}")
    if not isinstance(reason, str) or not reason.strip():
        raise LifecycleError("reason must be a non-empty string")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise LifecycleError("expected_revision must be an integer")
    if new_status == "superseded":
        replacement_id = _validate_note_id(supersedes, "supersedes")
        if replacement_id == note_id:
            raise LifecycleError("a note cannot supersede itself")
    else:
        if supersedes is not None:
            raise LifecycleError("supersedes is only valid with status superseded")
        replacement_id = None

    root = resolve_vault_root()
    _ensure_index_for_write(root)
    with vault_index._locked(root) as index_dir:
        updates = _updated_notes(
            root,
            note_id,
            new_status,
            replacement_id,
            expected_revision,
        )
        stages: list[dict[str, Any]] = []
        connection: sqlite3.Connection | None = None
        committed = False
        try:
            for current_id in sorted(updates):
                path, note = updates[current_id]
                stages.append(_stage_note(path, vault_notes._serialize(note)))

            connection = vault_index._connect(index_dir / "kg.db", wal=True)
            connection.execute("BEGIN IMMEDIATE")
            for stage in stages:
                _publish_stage(stage)
            reparsed = [
                vault_index._parse_note(stage["path"])
                for stage in stages
            ]
            for note in reparsed:
                vault_index._upsert_connection(connection, note)
            generation = vault_index._generation(connection) + 1
            vault_index._set_generation(connection, generation)
            connection.commit()
            committed = True
        except (RevisionConflict, NoteNotFound, LifecycleError):
            if connection is not None:
                connection.rollback()
            if not committed:
                _restore_published(stages)
            raise
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            try:
                if not committed:
                    _restore_published(stages)
            except LifecycleError as rollback_error:
                raise rollback_error from exc
            raise LifecycleError("status update failed; canonical notes restored") from exc
        finally:
            if connection is not None:
                connection.close()
            for stage in stages:
                _close_stage(stage)

        result = _public_note(updates[note_id][1])
        return {
            **result,
            "reason": reason,
            "index_generation": generation,
        }


def record_usage(
    recall_id: str,
    note_id: str,
    outcome: str,
    source_task: str | None = None,
) -> dict[str, Any]:
    """Persist one apply-feedback signal for a recalled note."""
    if not isinstance(recall_id, str):
        raise LifecycleError("recall_id must be a UUID string")
    try:
        parsed_recall_id = str(uuid.UUID(recall_id))
    except (ValueError, AttributeError) as exc:
        raise LifecycleError("recall_id must be a UUID string") from exc
    if parsed_recall_id != recall_id:
        raise LifecycleError("recall_id must use canonical UUID form")
    validated_note_id = _validate_note_id(note_id, "note_id")
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise LifecycleError(f"outcome must be one of {sorted(OUTCOMES)}")
    if source_task is not None and (
        not isinstance(source_task, str) or not source_task.strip()
    ):
        raise LifecycleError("source_task must be a non-empty string or null")

    root = resolve_vault_root()
    _ensure_index_for_write(root)
    timestamp = vault_notes._utc_now()
    with vault_index._locked(root) as index_dir:
        _find_note(root, validated_note_id)
        connection = vault_index._connect(index_dir / "kg.db", wal=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO usage(recall_id, note_id, outcome, source_task, ts) "
                    "VALUES(?,?,?,?,?)",
                    (
                        parsed_recall_id,
                        validated_note_id,
                        outcome,
                        source_task,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    "SELECT outcome, source_task, ts FROM usage "
                    "WHERE recall_id=? AND note_id=?",
                    (parsed_recall_id, validated_note_id),
                ).fetchone()
                if existing is None or existing[:2] != (outcome, source_task):
                    raise UsageConflict(
                        "recall/note pair already has different feedback"
                    ) from exc
                timestamp = existing[2]
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return {
        "recall_id": parsed_recall_id,
        "note_id": validated_note_id,
        "outcome": outcome,
        "source_task": source_task,
        "ts": timestamp,
    }
