"""Lifecycle operations for canonical Chrono memory notes."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import audit
from clearance import (
    require_controller_lifecycle,
    require_memory_operation,
    require_note_visible,
    require_note_within_clearance,
)
import curation_queue
import index as vault_index
import notes as vault_notes
from vaultroot import REPO_ROOT, resolve_vault_root


OUTCOMES = frozenset({"used", "not_useful", "incorrect"})
# Usage feedback demotes but never promotes (spec §8): "used" is the majority
# outcome by a wide margin, and promoting on it would entrench whatever a weak
# ranker already surfaced. Only these two outcomes flag a note to the curation
# queue for a human to review; neither ever sets `invalidated` directly.
DEMOTING_OUTCOMES = frozenset({"not_useful", "incorrect"})
NOTE_ID_PATTERN = re.compile(r"mem-[0-9a-f]{12}")
# A bound on the supersession walk: far above any real chain, it only exists so a
# pre-existing corrupt cycle in the store can never spin the guard forever.
MAX_SUPERSESSION_WALK = 4096


def _creates_supersession_cycle(
    root: Path, note_id: str, replacement_id: str
) -> bool:
    """Would making `replacement_id` supersede `note_id` close a cycle?

    Marking `note_id` superseded-by `replacement_id` adds the edge
    `replacement supersedes note_id`. That closes a cycle exactly when
    `replacement_id` is already superseded (transitively) by `note_id`, so we
    walk the `superseded_by` chain from the replacement: reaching `note_id` means
    A-supersedes-B-supersedes-A (or a longer loop). The walk is bounded and
    visited-guarded so a store that is *already* cyclic cannot hang it.
    """
    seen: set[str] = set()
    current: str | None = replacement_id
    for _ in range(MAX_SUPERSESSION_WALK):
        if current is None:
            return False
        if current == note_id:
            return True
        if current in seen:
            return False
        seen.add(current)
        try:
            _, parsed = _find_note(root, current)
        except (NoteNotFound, LifecycleError):
            return False
        current = parsed.get("superseded_by")
    return False


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
    require_memory_operation("get_note")
    note_id = _validate_note_id(id)
    root = resolve_vault_root()
    with vault_index._locked(root):
        _, parsed = _find_note(root, note_id)
        require_note_visible(parsed)
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

    if replacement_id is not None:
        # Verify the canonical (replacement) is itself current before superseding
        # the predecessor. Superseding in favour of an unverified note would leave
        # nothing verified as the live answer — the "nothing current" failure Sol
        # warned about. A missing target keeps its existing NoteNotFound.
        _, replacement_check = _find_note(root, replacement_id)
        if replacement_check["status"] != "verified":
            raise LifecycleError(
                "replacement note must be verified before superseding predecessors"
            )
        if _creates_supersession_cycle(root, note_id, replacement_id):
            raise LifecycleError("supersession would create a cycle")

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
    if new_status == "verified":
        # The promotion time, stamped here because this is the only path a
        # note reaches `verified` by. Without it `promotion_throughput`
        # measures nothing: it refuses file `mtime` as a proxy, so an
        # unstamped promotion is indistinguishable from no promotion, and
        # the doctor check that reads it would silently always pass.
        primary_update["verified_at"] = updated_at
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
    require_controller_lifecycle()
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

    # A status change is the one live lifecycle mutation, so it emits a
    # `set_status` audit event whether it lands (`transitioned`) or a guard
    # refuses it (`conflict`/`rejected`) — the reviewed, auditable record of what
    # changed that a live transition must never happen without.
    request_hash = audit.request_digest(
        "set_status",
        {
            "id": note_id,
            "new_status": new_status,
            "supersedes": replacement_id,
            "expected_revision": expected_revision,
        },
    )
    result_code = audit.ERROR
    updated_ids: list[str] = []
    root = resolve_vault_root()
    _ensure_index_for_write(root)
    try:
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
            updated_ids = sorted(updates)
            result_code = audit.TRANSITIONED
            return {
                **result,
                "reason": reason,
                "index_generation": generation,
            }
    except RevisionConflict:
        result_code = audit.CONFLICT
        raise
    except (NoteNotFound, LifecycleError):
        result_code = audit.REJECTED
        raise
    except Exception:
        result_code = audit.ERROR
        raise
    finally:
        audit.emit(
            "set_status",
            result=result_code,
            request_hash=request_hash,
            returned_note_ids=updated_ids,
            extra={"new_status": new_status, "replacement_id": replacement_id},
        )


def record_usage(
    recall_id: str,
    note_id: str,
    outcome: str,
    source_task: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Persist one apply-feedback signal for a recalled note.

    `outcome` never changes the note's status here. `not_useful` and
    `incorrect` flag the note to the curation queue (see
    `curation_queue.flag_for_curation`) for a human to review; only that
    review, not this call, may set `invalidated`. `repo_root` is the public
    repo root the queue file lives under -- it defaults to this checkout
    (`vaultroot.REPO_ROOT`) and exists as a parameter only so tests can point
    it at a throwaway directory instead of writing into the real repo.
    """
    # A usage row is a write, and `record` is the permission that governs vault
    # writes. This required `recall` as well until 2026-08-17, which made usage
    # telemetry structurally unrecordable under `cold` -- 2,665 of 2,669
    # dispatches. `record` stayed allowed under `cold`, so notes kept being
    # written and nothing looked broken while the usage table sat empty for 23
    # days. Decoupled by operator decision: reporting an outcome for a note the
    # caller already holds discloses no memory it did not already have.
    context = require_memory_operation("record")
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
    if context is not None:
        if source_task not in {None, context["task_id"]}:
            raise LifecycleError("source_task does not match the engagement")
        source_task = context["task_id"]

    root = resolve_vault_root()
    _ensure_index_for_write(root)
    timestamp = vault_notes._utc_now()
    is_new_signal = True
    with vault_index._locked(root) as index_dir:
        _, parsed_note = _find_note(root, validated_note_id)
        # Clearance only. `require_note_visible` is the *read* gate and calls
        # `require_memory_operation("get_note")`, which `cold` denies — the second
        # half of the same coupling removed above. Nothing of the note is returned
        # here, so its status/type/target/age admissibility is not this call's
        # question; whether this server may handle its contents at all still is.
        require_note_within_clearance(parsed_note)
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
                # A retried, identical (recall_id, note_id) report is the same
                # observation replayed, not a second one -- flagging it again
                # would let a retry inflate the demotion signal's sample count.
                is_new_signal = False
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    if is_new_signal and outcome in DEMOTING_OUTCOMES:
        curation_queue.flag_for_curation(
            validated_note_id,
            outcome,
            source_task,
            repo_root if repo_root is not None else REPO_ROOT,
        )

    return {
        "recall_id": parsed_recall_id,
        "note_id": validated_note_id,
        "outcome": outcome,
        "source_task": source_task,
        "ts": timestamp,
    }
