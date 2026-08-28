"""Server-owned sensitivity and engagement aperture for chrono-vault."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


INTERNAL = "internal"
RESTRICTED = "restricted"
SENSITIVITIES = frozenset({INTERNAL, RESTRICTED})
CONTEXT_ENV = "CHRONO_VAULT_CONTEXT"
CONTEXT_SCHEMA = "chrono-vault-context/v1"
MEMORY_ENGAGEMENT_MODES = frozenset({"project", "bounty"})
POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "shared"
    / "registries"
    / "memory-apertures.tsv"
)
POLICY_FIELDS = (
    "policy_id",
    "aperture",
    "recall",
    "record",
    "get_note",
    "browse",
    "statuses",
    "note_types",
    "focus",
    "written_before",
    "read_sensitivity",
    "write_status",
    "project_write_floor",
    "bounty_write_floor",
)
# `default` is the dispatch default from 2026-08-17 (memory-loop spec §4).
# It exists because `focused` requires scope=exact plus an engagement_start,
# which a general-purpose default cannot supply -- see
# scripts/python/dispatch_context_builder.py, which rejects `focused`
# without a memory_focus.
_APERTURES = frozenset({"rich", "focused", "default", "cold", "pool_blind", "none"})
_POLICY_TOKEN_RE = re.compile(r"^[a-z0-9_.|-]{1,128}$")
_POLICY_STATUSES = frozenset(
    {"candidate", "verified", "superseded", "invalidated", "archived"}
)
_POLICY_NOTE_TYPES = frozenset({"attempt", "finding", "learning"})
POLICY_SHA256 = "7f08fcfa1d9773a8bb2bbb6d51c9a03fc7026bad8b9432f5288ce7ecf6720870"
CONTEXT_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "attempt_id",
        "generation",
        "mode",
        "aperture",
        "focus",
        "engagement_start",
    }
)
TASK_RE = re.compile(
    r"^TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[A-Za-z0-9][A-Za-z0-9-]*$"
)
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
# Filesystem addresses of the vault, as opposed to the operations on it. A
# launcher hands these to a worker so its stdio MCP child can resolve the root;
# the worker therefore holds them too, which is why the aperture has to decide
# whether they are handed over at all.
VAULT_PATH_ENV = ("CHRONO_VAULT_ROOT", "OBSIDIAN_VAULT_ROOT")
VAULT_READ_OPERATIONS = ("recall", "get_note", "browse")
PATH_READ = "read"
PATH_WRITE_ONLY = "write_only"
PATH_NONE = "none"


class ClearanceError(PermissionError):
    """The current MCP instance may not return the requested note."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate context key")
        result[key] = value
    return result


def _timestamp_ns(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ClearanceError(f"{field} must be a bounded timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise ClearanceError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ClearanceError(f"{field} requires a timezone")
    try:
        return int(parsed.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    except (OSError, OverflowError, ValueError) as exc:
        raise ClearanceError(f"{field} is outside the supported range") from exc


def _policy_set(value: str, allowed: frozenset[str]) -> tuple[str, ...]:
    if value == "-":
        return ()
    tokens = tuple(value.split("|"))
    if (
        tokens != tuple(sorted(tokens))
        or len(tokens) != len(set(tokens))
        or any(token not in allowed for token in tokens)
    ):
        raise ClearanceError("memory aperture policy set is invalid")
    return tokens


def _validate_policy_row(row: dict[str, str]) -> None:
    if set(row) != set(POLICY_FIELDS):
        raise ClearanceError("memory aperture policy row width is invalid")
    values = tuple(row.get(field) for field in POLICY_FIELDS)
    if any(
        not isinstance(value, str) or _POLICY_TOKEN_RE.fullmatch(value) is None
        for value in values
    ):
        raise ClearanceError("memory aperture policy token is invalid")

    aperture = row["aperture"]
    if (
        aperture not in _APERTURES
        or row["policy_id"] != f"memory.{aperture.replace('_', '-')}.v1"
        or any(row[field] not in {"allow", "deny"} for field in (
            "recall", "record", "get_note", "browse"
        ))
        or row["focus"] not in {"any", "exact", "none"}
        or row["written_before"] not in {"engagement_start", "none"}
        or row["read_sensitivity"] not in {"context", "none"}
        or row["write_status"] not in {"candidate", "-"}
        or row["project_write_floor"] not in {*SENSITIVITIES, "-"}
        or row["bounty_write_floor"] not in {*SENSITIVITIES, "-"}
    ):
        raise ClearanceError("memory aperture policy domain is invalid")

    statuses = _policy_set(row["statuses"], _POLICY_STATUSES)
    note_types = _policy_set(row["note_types"], _POLICY_NOTE_TYPES)
    note_read_allowed = row["recall"] == "allow" or row["get_note"] == "allow"
    if note_read_allowed:
        if not statuses or not note_types or row["read_sensitivity"] != "context":
            raise ClearanceError("memory aperture readable policy is incomplete")
    elif (
        statuses
        or note_types
        or row["focus"] != "none"
        or row["written_before"] != "none"
        or row["read_sensitivity"] != "none"
    ):
        raise ClearanceError("memory aperture denied read carries readable policy")

    if aperture == "focused":
        if (
            not note_read_allowed
            or row["focus"] != "exact"
            or row["written_before"] != "engagement_start"
        ):
            raise ClearanceError("focused memory policy is incomplete")
    elif row["focus"] == "exact":
        raise ClearanceError("exact memory focus requires the focused aperture")

    if row["record"] == "deny":
        if any(row[field] != "-" for field in (
            "write_status", "project_write_floor", "bounty_write_floor"
        )):
            raise ClearanceError("memory aperture denied record carries write policy")
    elif (
        row["write_status"] != "candidate"
        or row["project_write_floor"] not in SENSITIVITIES
        or row["bounty_write_floor"] != RESTRICTED
    ):
        raise ClearanceError("memory aperture write policy is unsafe")


@lru_cache(maxsize=1)
def memory_policies() -> dict[str, dict[str, str]]:
    """Load the one canonical six-row aperture table."""
    try:
        raw = POLICY_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != POLICY_SHA256:
            raise ClearanceError("memory aperture policy hash is invalid")
        reader = csv.DictReader(raw.decode("utf-8").splitlines(), delimiter="\t")
        if tuple(reader.fieldnames or ()) != POLICY_FIELDS:
            raise ClearanceError("memory aperture policy header is invalid")
        rows = list(reader)
    except (OSError, UnicodeDecodeError) as exc:
        raise ClearanceError("memory aperture policy is unavailable") from exc
    policies: dict[str, dict[str, str]] = {}
    for row in rows:
        _validate_policy_row(row)
        aperture = row["aperture"]
        if aperture in policies:
            raise ClearanceError("memory aperture policy row is invalid")
        policies[aperture] = dict(row)
    if set(policies) != _APERTURES:
        raise ClearanceError("memory aperture policy set is incomplete")
    return policies


def validate_memory_context(
    value: Any,
    *,
    task_id: str | None = None,
    attempt_id: str | None = None,
    generation: int | None = None,
    mode: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Validate and optionally cross-bind one controller engagement context."""
    if not isinstance(value, dict) or set(value) != CONTEXT_FIELDS:
        raise ClearanceError("memory engagement context fields are invalid")
    if value.get("schema") != CONTEXT_SCHEMA:
        raise ClearanceError("memory engagement context schema is invalid")
    if not isinstance(value.get("task_id"), str) or not TASK_RE.fullmatch(
        value["task_id"]
    ):
        raise ClearanceError("memory engagement task identity is invalid")
    if not isinstance(value.get("attempt_id"), str) or not ATTEMPT_RE.fullmatch(
        value["attempt_id"]
    ):
        raise ClearanceError("memory engagement attempt identity is invalid")
    if (
        isinstance(value.get("generation"), bool)
        or not isinstance(value.get("generation"), int)
        or value["generation"] < 1
    ):
        raise ClearanceError("memory engagement generation is invalid")
    engagement_mode = value.get("mode")
    if engagement_mode not in MEMORY_ENGAGEMENT_MODES:
        supported = ", ".join(sorted(MEMORY_ENGAGEMENT_MODES))
        raise ClearanceError(
            f"unsupported memory engagement mode {engagement_mode!r}; "
            f"expected one of: {supported}"
        )
    policies = memory_policies()
    if value.get("aperture") not in policies:
        raise ClearanceError("memory engagement aperture is invalid")
    focus = value.get("focus")
    if focus is not None and (
        not isinstance(focus, str)
        or not focus.strip()
        or len(focus) > 256
        or any(character in focus for character in "\x00\r\n")
    ):
        raise ClearanceError("memory engagement focus is invalid")
    if (value["aperture"] == "focused") != (focus is not None):
        raise ClearanceError("focused memory requires one exact target")
    expected = {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "mode": mode,
    }
    if any(
        wanted is not None and value[name] != wanted
        for name, wanted in expected.items()
    ):
        raise ClearanceError("memory engagement context identity is inconsistent")
    if created_at is not None:
        if (
            isinstance(created_at, bool)
            or not isinstance(created_at, int)
            or created_at <= 0
        ):
            raise ClearanceError("memory engagement creation time is invalid")
        try:
            expected_start = (
                datetime.fromtimestamp(created_at, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (OSError, OverflowError, ValueError) as exc:
            raise ClearanceError("memory engagement creation time is invalid") from exc
        if value["engagement_start"] != expected_start:
            raise ClearanceError("memory engagement start is inconsistent")
    _timestamp_ns(value.get("engagement_start"), "engagement_start")
    return dict(value)


def memory_context() -> dict[str, Any] | None:
    """Return the controller-bound engagement context, if this is a lane process.

    Unbound controller/maintenance processes retain the legacy clearance behavior.
    Board dispatch always supplies this context, with a missing packet aperture
    projected to ``cold`` before launch.
    """
    raw = os.environ.get(CONTEXT_ENV)
    if raw is None:
        return None
    if not raw or len(raw.encode("utf-8")) > 4096:
        raise ClearanceError("memory engagement context is invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ClearanceError("memory engagement context is invalid JSON") from exc
    value = validate_memory_context(value)
    result = dict(value)
    result["engagement_start_ns"] = _timestamp_ns(
        value.get("engagement_start"), "engagement_start"
    )
    result["policy"] = memory_policies()[value["aperture"]]
    return result


def require_memory_operation(operation: str) -> dict[str, Any] | None:
    if operation not in {"recall", "record", "get_note", "browse"}:
        raise ValueError("unknown memory operation")
    context = memory_context()
    if context is not None and context["policy"][operation] != "allow":
        raise ClearanceError(
            f"memory {operation} is denied by aperture {context['aperture']}"
        )
    return context


def apply_record_policy(note_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Apply the bound write floor before the vault is resolved or mutated."""
    context = require_memory_operation("record")
    if context is None:
        return dict(fields)
    result = dict(fields)
    if result.get("status", "candidate") != "candidate":
        raise ClearanceError("engagement memory may create candidate notes only")
    result["status"] = "candidate"
    task_id = context["task_id"]
    if result.get("source_task", task_id) != task_id:
        raise ClearanceError("memory source_task does not match the engagement")
    result["source_task"] = task_id
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result["created_at"] = now
    result["updated_at"] = now
    floor = context["policy"][f"{context['mode']}_write_floor"]
    if floor == "restricted":
        result["sensitivity"] = "restricted"
    focus = context["focus"]
    if focus is not None:
        supplied = result.get("target")
        if supplied not in {None, "none", focus}:
            raise ClearanceError("memory target is outside the focused engagement")
        result["target"] = focus
    return result


def recall_constraints() -> dict[str, Any] | None:
    """What this engagement may retrieve, and which task is doing so.

    `task_id` is carried here for the same reason `record_usage` reads it
    off the context directly: what a recall HANDED a task is the key
    promotion joins on, and a caller-declared key is a key nobody declares.
    Every other field narrows the query; this one identifies the querier.
    """
    context = require_memory_operation("recall")
    if context is None:
        return None
    policy = context["policy"]
    return {
        "task_id": context["task_id"],
        "statuses": tuple(filter(None, policy["statuses"].split("|"))),
        "note_types": tuple(filter(None, policy["note_types"].split("|"))),
        "target": context["focus"],
        "written_before_ns": (
            context["engagement_start_ns"]
            if policy["written_before"] == "engagement_start"
            else None
        ),
    }


def require_note_within_clearance(note: dict[str, Any]) -> None:
    """Enforce the sensitivity clearance alone, without the read aperture.

    The two checks answer different questions and `record_usage` needs only this
    one. Clearance asks whether this server may ever handle the note's contents;
    the aperture asks what this engagement may *retrieve*. Feedback on an already
    recalled note discloses no note content — the caller supplies the id and gets
    back only what it sent — so gating it on retrieval permission denied it under
    `cold`, which is nearly every dispatch (2026-08-17). Clearance still applies:
    a note above the lane's clearance is one the caller could never have been
    shown, so feedback on it is a claim about a note it does not hold.
    """
    if not can_read(str(note.get("sensitivity")), lane_clearance()):
        raise ClearanceError("memory note exceeds lane clearance")


def require_note_visible(note: dict[str, Any]) -> None:
    context = require_memory_operation("get_note")
    require_note_within_clearance(note)
    if context is None:
        return
    policy = context["policy"]
    if note.get("status") not in policy["statuses"].split("|"):
        raise ClearanceError("memory note status is outside the aperture")
    if note.get("type") not in policy["note_types"].split("|"):
        raise ClearanceError("memory note type is outside the aperture")
    if context["focus"] is not None and note.get("target") != context["focus"]:
        raise ClearanceError("memory note target is outside the focused engagement")
    if (
        policy["written_before"] == "engagement_start"
        and _timestamp_ns(note.get("created_at"), "created_at")
        >= context["engagement_start_ns"]
    ):
        raise ClearanceError("memory note was created after engagement start")


def require_controller_lifecycle() -> None:
    if memory_context() is not None:
        raise ClearanceError("memory lifecycle changes are controller-only")


def vault_path_entitlement(aperture: str) -> str:
    """Return the filesystem access one aperture's own policy row entitles.

    Derived from the single canonical row, never from a second table. An
    aperture that may read a note needs a readable vault; an aperture that may
    only record needs the path but no read; an aperture that may do neither
    needs no vault path at all. This is the fact a launcher needs in order to
    decide what to put in a worker's process environment, and it is deliberately
    the same fact ``require_memory_operation`` enforces at the interface.
    """
    policies = memory_policies()
    if aperture not in policies:
        raise ClearanceError("memory engagement aperture is invalid")
    policy = policies[aperture]
    if any(policy[operation] == "allow" for operation in VAULT_READ_OPERATIONS):
        return PATH_READ
    if policy["record"] == "allow":
        return PATH_WRITE_ONLY
    return PATH_NONE


def project_worker_vault_environment(
    environment: dict[str, str], *, aperture: str
) -> dict[str, str]:
    """Return ``environment`` without vault paths the aperture cannot use.

    The interface check refuses the *operation*; this refuses the *address*. A
    worker whose aperture grants no vault operation is handed no vault path, so
    an honest worker has nothing to open and the stdio MCP child it spawns fails
    closed — which is the correct outcome, because every operation that child
    could serve is denied anyway.

    This bounds an honest worker only. It does not bound a worker that goes
    looking for the vault by other means; see the threat model in
    ``_state/v4-audit/p10b-isolation/``. ``write_only`` apertures still receive
    the path because ``record`` needs it, and remain reachable by a direct read.
    """
    if not isinstance(environment, dict):
        raise ClearanceError("worker environment must be a mapping")
    if vault_path_entitlement(aperture) != PATH_NONE:
        return dict(environment)
    return {
        name: value
        for name, value in environment.items()
        if name not in VAULT_PATH_ENV
    }


def lane_clearance() -> str:
    """Return this process's configured clearance, defaulting fail-safe."""
    configured = os.environ.get("CHRONO_VAULT_CLEARANCE")
    if configured == RESTRICTED:
        return RESTRICTED
    return INTERNAL


def can_read(note_sensitivity: str, clearance: str) -> bool:
    """Return whether a server clearance permits one sensitivity label."""
    if note_sensitivity not in SENSITIVITIES:
        return False
    if note_sensitivity == INTERNAL:
        return True
    return note_sensitivity == RESTRICTED and clearance == RESTRICTED
