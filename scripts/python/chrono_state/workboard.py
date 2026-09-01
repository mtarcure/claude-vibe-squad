"""Append-only Markdown authority for Chrono work state.

``_state/chrono/OPEN-WORK.md`` remains Markdown.  New state changes are one
structured list item each::

    - workboard-event/v1 event_id=EV-1 at=2026-08-27T00:00:00Z \
      kind=start work_id=W-0123456789abcdef0123456789abcdef alias=CASE-1 \
      summary='Validate CASE-1' \
      next_action='run the scalar oracle'

The format deliberately separates facts from prose: ``next_action`` is a named
field, not a suffix another consumer must rediscover with a regular expression.
The only current-state view is ``project_workboard`` and the only consistency
gate is ``validate_workboard``.  Writers append; no update/delete API exists.

Legacy checkbox rows remain readable for the migration pre-image and its one
id-less completed historical row. That compatibility branch is contained in
this parser so it does not create a second authority.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import tempfile
from typing import Mapping


WORKBOARD_REL = Path("_state/chrono/OPEN-WORK.md")
WORKBOARD_PATH = Path(os.environ.get("VAULT_ROOT", ".")) / WORKBOARD_REL
EVENT_TAG = "workboard-event/v1"
ACTIVE_MARKER = "**IN PROGRESS — Chrono**"

# This is the complete terminal vocabulary for the workboard event spine.
# A context boundary, restart, or compaction is deliberately absent.
TERMINAL_KINDS = frozenset({"complete", "archive", "drop"})
COMPACTION_KIND = "compact"
ADOPTION_KIND = "adopt"
NONTERMINAL_KINDS = frozenset(
    {
        "start",
        "queue",
        "fold",
        "switch",
        "advance",
        "block",
        "restart",
        COMPACTION_KIND,
        ADOPTION_KIND,
    }
)
EVENT_KINDS = TERMINAL_KINDS | NONTERMINAL_KINDS

MAX_PROJECTED_ITEMS = 12
SUMMARY_CLIP = 160
ACTION_CLIP = 120

MIGRATION_SCHEMA = "workboard-migration/v1"
# Legacy checklist rows carry no reliable creation timestamp. This explicit
# sentinel preserves that uncertainty instead of fabricating historical times.
MIGRATION_AT = "1970-01-01T00:00:00Z"
MIGRATION_WHY = (
    "legacy checklist state imported; original item text is preserved verbatim "
    "in summary"
)
MIGRATION_COMPLETED_ACTION = "item was already checked before workboard migration"
MIGRATION_MARKER_PREFIX = f"<!-- {MIGRATION_SCHEMA} "
HEADER_CONTRACT_VERSION = "append-only-events/v1"
HEADER_CONTRACT_REPLACEMENTS = (
    (
        "The single list. Everything raised and not yet done lives here and "
        "nowhere else.",
        "The single append-only workboard. Everything raised and not yet done "
        "lives here and nowhere else.",
    ),
    (
        "**Read this before accepting any new request.** If the request matches "
        "an entry below, continue\n"
        "that entry rather than opening new work. If it does not, add a line "
        "here — do not start it, and do\n"
        "not write a plan file for it.",
        "**Read this before accepting any new request.** If it matches an open "
        "item below, continue\n"
        "that item. Otherwise append a `queue` event through the canonical "
        "workboard API; never\n"
        "hand-edit prior events or open a separate plan file.",
    ),
    (
        "**Tick items off as they finish, in the same action that finishes "
        "them.** An item marked done later\n"
        "is an item that was already forgotten once.",
        "**Record every state change through "
        "`chrono_state.workboard.append_event`.** A prior event is\n"
        "immutable; completion is a `complete` event, never an edited checkbox.",
    ),
    (
        "Format: `- [ ] <id> | <one line> — <why it matters>; next: <the exact "
        "next action>`",
        "Format: one structured event line emitted by "
        "`chrono_state.workboard.format_event` per state change.",
    ),
)

_LEGACY_ITEM_RE = re.compile(r"^- \[(?P<state>[ xX])\]\s+(?P<body>\S.*?)\s*$")
_LEGACY_NEXT_RE = re.compile(r"[;.]\s*next:\s*", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WORK_ID_RE = re.compile(r"^W-[0-9a-f]{32}$")
_MIGRATABLE_LEGACY_RE = re.compile(
    r"^- \[(?P<state>[ x])\] "
    r"(?P<item_id>[A-Za-z0-9][A-Za-z0-9._-]*) \| (?P<text>.*)$"
)
_MIGRATION_MARKER_RE = re.compile(
    rf"^<!-- {re.escape(MIGRATION_SCHEMA)} "
    r"plan_sha256=(?P<plan>[0-9a-f]{64}) "
    r"source_sha256=(?P<source>[0-9a-f]{64}) "
    r"body_sha256=(?P<body>[0-9a-f]{64}) "
    r"body_size=(?P<size>[0-9]+) -->$"
)
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ID_CHARS = 64

_REQUIRED_FIELD_VARIANTS = {
    # ``item_id`` variants are the immutable migration pre-image. New writes
    # carry an opaque identity plus a searchable human alias.
    "start": (
        frozenset({"work_id", "alias", "summary", "why", "next_action"}),
        frozenset({"item_id", "summary", "why", "next_action"}),
    ),
    "queue": (
        frozenset({"work_id", "alias", "summary", "why", "resume_action"}),
        frozenset({"item_id", "summary", "why", "resume_action"}),
    ),
    "fold": (
        frozenset({"request_id", "target_work_id", "summary", "why", "next_action"}),
        frozenset({"request_id", "target_id", "summary", "why", "next_action"}),
    ),
    "drop": (
        frozenset({"work_id", "summary", "why"}),
        frozenset({"request_id", "summary", "why"}),
    ),
    "switch": (
        frozenset({"work_id", "next_action"}),
        frozenset({"item_id", "next_action"}),
    ),
    "advance": (
        frozenset({"work_id", "next_action"}),
        frozenset({"item_id", "next_action"}),
    ),
    "block": (
        frozenset({"work_id", "resume_action"}),
        frozenset({"item_id", "resume_action"}),
    ),
    "complete": (frozenset({"work_id"}), frozenset({"item_id"})),
    "archive": (frozenset({"work_id"}), frozenset({"item_id"})),
    "restart": (frozenset(),),
    COMPACTION_KIND: (frozenset(),),
    ADOPTION_KIND: (frozenset({"source_event_id", "work_id", "alias"}),),
}


class WorkboardConsistencyError(ValueError):
    """Raised when strict loading finds an invalid workboard."""


class WorkboardMigrationError(WorkboardConsistencyError):
    """Raised when a locked migration cannot prove a lossless transition."""

    def __init__(self, message: str, report: Mapping[str, object] | None = None):
        super().__init__(message)
        self.report = dict(report or {})


@dataclass(frozen=True)
class WorkEvent:
    """One parsed structured event line."""

    event_id: str
    at: str
    kind: str
    fields: Mapping[str, str]
    line_number: int


@dataclass(frozen=True)
class LegacyItem:
    """One pre-event checkbox row retained only for migration compatibility."""

    item_id: str | None
    summary: str
    resume_action: str | None
    checked: bool
    active: bool
    source_text: str
    line_number: int


@dataclass(frozen=True)
class WorkItem:
    """One nonterminal item in the projected workboard.

    Legacy openings resolve through their human alias only. Their projected
    ``legacy-...`` work IDs are internal compatibility values and must never be
    supplied as ``work_id`` to an appended transition.
    """

    work_id: str
    alias: str
    summary: str
    why: str | None
    resume_action: str | None
    state: str
    disposition: str
    last_event_id: str
    last_index: int

    @property
    def item_id(self) -> str:
        """Compatibility display name; identity is always ``work_id``."""
        return self.alias


@dataclass(frozen=True)
class WorkboardDocument:
    """Syntactic result from the one workboard parser."""

    path: Path
    records: tuple[WorkEvent | LegacyItem, ...]
    issues: tuple[str, ...]
    has_structured_events: bool


@dataclass(frozen=True)
class WorkboardProjection:
    """Current facts derived from an append-only document."""

    document: WorkboardDocument
    items: tuple[WorkItem, ...]
    prominent_items: tuple[WorkItem, ...]
    active_work_id: str | None
    active_item_id: str | None
    next_action: str | None
    terminal_work_ids: frozenset[str]
    terminal_ids: frozenset[str]
    known_work_ids: frozenset[str]
    transition_issues: tuple[str, ...]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ItemCensus:
    """Explicit IDs plus anonymous-row fingerprints for migration comparison."""

    checked: Mapping[str, bool]
    text: Mapping[str, str]
    anonymous_hashes: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True)
class _LegacyMigrationRow:
    line_number: int
    item_id: str
    text: str
    checked: bool
    active: bool


@dataclass(frozen=True)
class WorkboardMigrationPlan:
    action: str
    plan_sha256: str
    migration_id: str
    source_bytes: bytes
    target_bytes: bytes
    report: Mapping[str, object]


class ResumeRows(list):
    """Legacy three-tuples plus the authoritative projection that ordered them."""

    def __init__(self, projection: WorkboardProjection, rows):
        super().__init__(rows)
        self.projection = projection


def _legacy_split_next_action(text: str) -> tuple[str, str | None]:
    """Parse only the legacy migration syntax; structured events never use this."""
    matches = list(_LEGACY_NEXT_RE.finditer(text))
    if not matches:
        return text.strip(), None
    last = matches[-1]
    return text[: last.start()].strip(), text[last.end() :].strip() or None


def _parse_event_line(
    line: str, line_number: int
) -> tuple[WorkEvent | None, list[str]]:
    prefix = f"- {EVENT_TAG}"
    payload = line[len(prefix) :].strip()
    issues: list[str] = []
    try:
        tokens = shlex.split(payload, posix=True)
    except ValueError as exc:
        return None, [f"line {line_number}: malformed {EVENT_TAG} quoting ({exc})"]

    values: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if not separator or not key:
            issues.append(
                f"line {line_number}: event facts must be key=value tokens ({token!r})"
            )
            continue
        if key in values:
            issues.append(f"line {line_number}: duplicate event field {key!r}")
            continue
        values[key] = value

    common = {name: values.pop(name, "") for name in ("event_id", "at", "kind")}
    missing = [name for name, value in common.items() if not value.strip()]
    if missing:
        issues.append(
            f"line {line_number}: event is missing common fact(s): {', '.join(missing)}"
        )
        return None, issues
    return (
        WorkEvent(
            event_id=common["event_id"],
            at=common["at"],
            kind=common["kind"].lower(),
            fields=values,
            line_number=line_number,
        ),
        issues,
    )


def _parse_workboard_text(source: Path, text: str) -> WorkboardDocument:
    """Parse already-decoded bytes so a dry-run can validate without writing."""
    records: list[WorkEvent | LegacyItem] = []
    issues: list[str] = []
    has_structured = False
    prefix = f"- {EVENT_TAG}"
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(prefix):
            has_structured = True
            event, line_issues = _parse_event_line(line, line_number)
            issues.extend(line_issues)
            if event is not None:
                records.append(event)
            continue
        if "workboard-event/" in line:
            issues.append(
                f"line {line_number}: unsupported or non-top-level workboard event"
            )
            continue
        match = _LEGACY_ITEM_RE.match(line)
        if not match:
            continue
        raw = match.group("body")
        head, separator, rest = raw.partition("|")
        head = head.strip()
        if separator and _ITEM_ID_RE.fullmatch(head) and len(head) <= 64:
            item_id = head
            # The canonical visible delimiter is ``ID | text``. ``rest`` begins
            # with that delimiter's one separating space; it is syntax, not
            # item text, and migration's strict row matcher pins the distinction.
            remainder = rest[1:] if rest.startswith(" ") else rest
        else:
            item_id, remainder = None, raw
        summary, resume_action = _legacy_split_next_action(remainder)
        records.append(
            LegacyItem(
                item_id=item_id,
                summary=summary,
                resume_action=resume_action,
                checked=match.group("state").lower() == "x",
                active=bool(
                    re.search(r"\*\*IN PROGRESS\s+—\s+[^*]+\*\*", summary, re.I)
                ),
                source_text=remainder,
                line_number=line_number,
            )
        )

    return WorkboardDocument(
        source,
        tuple(records),
        tuple(issues),
        has_structured,
    )


def parse_workboard(path: Path | str | None = None) -> WorkboardDocument:
    """Parse the Markdown authority once; never derive current state here."""
    source = Path(path) if path is not None else WORKBOARD_PATH
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        return WorkboardDocument(source, (), (), False)
    except (OSError, UnicodeError) as exc:
        return WorkboardDocument(
            source,
            (),
            (f"{source} is present but unreadable ({exc})",),
            False,
        )
    return _parse_workboard_text(source, text)


def _legacy_work_id(alias: str) -> str:
    """Return a namespaced compatibility identity for a pre-work-id alias."""
    digest = hashlib.sha256(
        b"workboard-legacy-work-id/v1\0" + alias.encode("utf-8")
    ).hexdigest()
    return f"legacy-{digest[:32]}"


def _legacy_projection_alias(record: LegacyItem) -> str:
    if record.item_id is not None:
        return record.item_id
    digest = hashlib.sha256(record.source_text.encode("utf-8")).hexdigest()[:16]
    return f"legacy-anon-{digest}"


def generate_work_id(existing: frozenset[str] | set[str] = frozenset()) -> str:
    """Generate a fresh opaque identity, retrying the in-document collision check."""
    while True:
        candidate = f"W-{secrets.token_hex(16)}"
        if candidate not in existing:
            return candidate


def _event_schema_issues(event: WorkEvent) -> list[str]:
    issues: list[str] = []
    if event.kind not in EVENT_KINDS:
        return [f"line {event.line_number}: unknown event kind {event.kind!r}"]
    variants = _REQUIRED_FIELD_VARIANTS[event.kind]
    present = frozenset(event.fields)
    required = min(
        variants,
        key=lambda fields: (
            len(fields - present) + len(present - fields),
            len(fields - present),
            sorted(fields),
        ),
    )
    missing = sorted(required - present)
    extra = sorted(present - required)
    blank = sorted(
        name for name in required & present if not event.fields[name].strip()
    )
    if missing:
        issues.append(
            f"line {event.line_number}: {event.kind} missing fact(s): {', '.join(missing)}"
        )
    if extra:
        issues.append(
            f"line {event.line_number}: {event.kind} has unexpected fact(s): {', '.join(extra)}"
        )
    if blank:
        issues.append(
            f"line {event.line_number}: {event.kind} has blank fact(s): {', '.join(blank)}"
        )
    for key in ("item_id", "request_id", "target_id", "alias"):
        value = event.fields.get(key)
        if value and (len(value) > MAX_ID_CHARS or not _ITEM_ID_RE.fullmatch(value)):
            issues.append(
                f"line {event.line_number}: {key} is not a valid work alias: {value!r}"
            )
    for key in ("work_id", "target_work_id"):
        value = event.fields.get(key)
        if value and not _WORK_ID_RE.fullmatch(value):
            issues.append(
                f"line {event.line_number}: {key} is not an opaque work id: {value!r}"
            )
    try:
        parsed = datetime.fromisoformat(event.at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError:
        issues.append(
            f"line {event.line_number}: at must be an ISO-8601 timestamp with timezone"
        )
    return issues


def project_workboard(document: WorkboardDocument) -> WorkboardProjection:
    """Fold all records once and decide current state plus prominence."""
    items: dict[str, WorkItem] = {}
    terminal_work_ids: set[str] = set()
    terminal_aliases: set[str] = set()
    known_work_ids: set[str] = set()
    disposed_requests: set[str] = set()
    aliases_by_work_id: dict[str, str] = {}
    rejected_openings: dict[str, tuple[WorkEvent, str, str, str]] = {}
    seen_events: set[str] = set()
    issues: list[str] = []

    def transition_issue(record, message: str) -> None:
        issues.append(f"line {record.line_number}: {message}")

    def opening_identity(record: WorkEvent) -> tuple[str, str, str]:
        if "work_id" in record.fields:
            return (
                record.fields["work_id"],
                record.fields["alias"],
                record.fields["work_id"],
            )
        alias = record.fields["item_id"]
        return _legacy_work_id(alias), alias, alias

    def target_identity(fields: Mapping[str, str]) -> tuple[str, str]:
        if "work_id" in fields:
            work_id = fields["work_id"]
            return work_id, aliases_by_work_id.get(work_id, work_id)
        alias = fields["item_id"]
        return _legacy_work_id(alias), alias

    for index, record in enumerate(document.records):
        if isinstance(record, LegacyItem):
            alias = _legacy_projection_alias(record)
            work_id = _legacy_work_id(alias)
            if work_id in items or work_id in terminal_work_ids:
                transition_issue(record, f"duplicate open item {alias}")
                continue
            known_work_ids.add(work_id)
            aliases_by_work_id[work_id] = alias
            if record.checked:
                terminal_work_ids.add(work_id)
                terminal_aliases.add(alias)
                continue
            items[work_id] = WorkItem(
                work_id=work_id,
                alias=alias,
                summary=record.summary,
                why=None,
                resume_action=record.resume_action,
                state="active" if record.active else "queued",
                disposition="legacy",
                last_event_id=f"legacy:{record.line_number}",
                last_index=index,
            )
            continue

        schema_issues = _event_schema_issues(record)
        if schema_issues:
            issues.extend(schema_issues)
            continue
        if record.event_id in seen_events:
            transition_issue(record, f"duplicate event_id {record.event_id}")
            continue
        seen_events.add(record.event_id)
        kind = record.kind
        fields = record.fields

        if kind == "start":
            work_id, alias, display_id = opening_identity(record)
            if work_id in known_work_ids:
                issue = f"line {record.line_number}: start reuses work id {display_id}"
                issues.append(issue)
                rejected_openings[record.event_id] = (record, work_id, alias, issue)
                continue
            known_work_ids.add(work_id)
            aliases_by_work_id[work_id] = alias
            items[work_id] = WorkItem(
                work_id=work_id,
                alias=alias,
                summary=fields["summary"],
                why=fields["why"],
                resume_action=fields["next_action"],
                state="active",
                disposition="start",
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind == "queue":
            work_id, alias, display_id = opening_identity(record)
            if work_id in known_work_ids or work_id in disposed_requests:
                issue = f"line {record.line_number}: queue reuses work id {display_id}"
                issues.append(issue)
                rejected_openings[record.event_id] = (record, work_id, alias, issue)
                continue
            known_work_ids.add(work_id)
            disposed_requests.add(work_id)
            aliases_by_work_id[work_id] = alias
            items[work_id] = WorkItem(
                work_id=work_id,
                alias=alias,
                summary=fields["summary"],
                why=fields["why"],
                resume_action=fields["resume_action"],
                state="queued",
                disposition="queue",
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind == "fold":
            request_alias = fields["request_id"]
            request_id = _legacy_work_id(request_alias)
            if "target_work_id" in fields:
                target = fields["target_work_id"]
                target_display = aliases_by_work_id.get(target, target)
            else:
                target_display = fields["target_id"]
                target = _legacy_work_id(target_display)
            if (
                request_id in items
                or request_id in terminal_work_ids
                or request_id in disposed_requests
            ):
                transition_issue(record, f"fold reuses request id {request_alias}")
                continue
            item = items.get(target)
            if item is None or item.state != "active":
                transition_issue(
                    record, f"fold target {target_display} is not the active item"
                )
                continue
            disposed_requests.add(request_id)
            items[target] = replace(
                item,
                resume_action=fields["next_action"],
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind == "drop":
            if "work_id" in fields:
                request_id = fields["work_id"]
                request_alias = aliases_by_work_id.get(request_id, request_id)
            else:
                request_alias = fields["request_id"]
                request_id = _legacy_work_id(request_alias)
            if request_id in items:
                # DROP may be the initial disposition or a later terminal
                # disposition for a previously queued interruption.
                del items[request_id]
                terminal_work_ids.add(request_id)
                terminal_aliases.add(request_alias)
                continue
            if request_id in terminal_work_ids or request_id in disposed_requests:
                transition_issue(record, f"drop reuses work id {request_alias}")
                continue
            known_work_ids.add(request_id)
            aliases_by_work_id[request_id] = request_alias
            disposed_requests.add(request_id)
            terminal_work_ids.add(request_id)
            terminal_aliases.add(request_alias)
        elif kind == "switch":
            target, target_display = target_identity(fields)
            item = items.get(target)
            if item is None:
                transition_issue(record, f"switch target {target_display} is not open")
                continue
            for active_id, active in tuple(items.items()):
                if active.state == "active" and active_id != target:
                    items[active_id] = replace(active, state="queued")
            items[target] = replace(
                item,
                state="active",
                resume_action=fields["next_action"],
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind == "advance":
            target, target_display = target_identity(fields)
            item = items.get(target)
            if item is None or item.state != "active":
                transition_issue(
                    record, f"advance target {target_display} is not active"
                )
                continue
            items[target] = replace(
                item,
                resume_action=fields["next_action"],
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind == "block":
            target, target_display = target_identity(fields)
            item = items.get(target)
            if item is None:
                transition_issue(record, f"block target {target_display} is not open")
                continue
            items[target] = replace(
                item,
                state="blocked",
                resume_action=fields["resume_action"],
                last_event_id=record.event_id,
                last_index=index,
            )
        elif kind in {"complete", "archive"}:
            target, target_display = target_identity(fields)
            if target not in items:
                transition_issue(record, f"{kind} target {target_display} is not open")
                continue
            terminal_aliases.add(items[target].alias)
            del items[target]
            terminal_work_ids.add(target)
        elif kind == ADOPTION_KIND:
            source_event_id = fields["source_event_id"]
            rejected = rejected_openings.get(source_event_id)
            if rejected is None:
                transition_issue(
                    record,
                    f"adopt source {source_event_id} is not an unresolved opening collision",
                )
                continue
            source, _rejected_id, source_alias, source_issue = rejected
            work_id = fields["work_id"]
            alias = fields["alias"]
            if alias != source_alias:
                transition_issue(
                    record,
                    f"adopt alias {alias} does not match source alias {source_alias}",
                )
                continue
            if work_id in known_work_ids or work_id in disposed_requests:
                transition_issue(record, f"adopt reuses work id {work_id}")
                continue
            source_fields = source.fields
            source_kind = source.kind
            known_work_ids.add(work_id)
            aliases_by_work_id[work_id] = alias
            if source_kind == "queue":
                disposed_requests.add(work_id)
            items[work_id] = WorkItem(
                work_id=work_id,
                alias=alias,
                summary=source_fields["summary"],
                why=source_fields["why"],
                resume_action=source_fields[
                    "next_action" if source_kind == "start" else "resume_action"
                ],
                state="active" if source_kind == "start" else "queued",
                disposition=ADOPTION_KIND,
                last_event_id=record.event_id,
                last_index=index,
            )
            issues.remove(source_issue)
            del rejected_openings[source_event_id]
        elif kind in {"restart", COMPACTION_KIND}:
            # Context boundaries are recorded facts, never state transitions.
            continue

    source_order = tuple(items.values())
    prominent = tuple(
        sorted(
            source_order,
            key=lambda item: (item.state == "active", item.last_index),
            reverse=True,
        )
    )
    active = [item for item in source_order if item.state == "active"]
    active_work_id = active[0].work_id if len(active) == 1 else None
    active_id = active[0].alias if len(active) == 1 else None
    next_action = active[0].resume_action if len(active) == 1 else None
    return WorkboardProjection(
        document=document,
        items=source_order,
        prominent_items=prominent,
        active_work_id=active_work_id,
        active_item_id=active_id,
        next_action=next_action,
        terminal_work_ids=frozenset(terminal_work_ids),
        terminal_ids=frozenset(terminal_aliases),
        known_work_ids=frozenset(known_work_ids),
        transition_issues=tuple(issues),
    )


def validate_workboard(
    document: WorkboardDocument,
    projection: WorkboardProjection | None = None,
) -> tuple[str, ...]:
    """Return every consistency violation from the one canonical validator."""
    view = projection or project_workboard(document)
    issues = list(document.issues) + list(view.transition_issues)

    if TERMINAL_KINDS != frozenset({"complete", "archive", "drop"}):
        issues.append(
            "terminal set drift: expected exactly complete/archive/drop; "
            "compaction and restart are nonterminal"
        )
    if COMPACTION_KIND in TERMINAL_KINDS:
        issues.append("compaction must never be terminal")

    # The strict facts apply to the event spine. Legacy checkbox rows remain
    # readable for rollback evidence, but they are not silently upgraded into
    # claims the old format cannot prove.
    if document.has_structured_events and view.items:
        active = [item for item in view.items if item.state == "active"]
        if len(active) != 1:
            issues.append(
                f"structured workboard must project exactly one active item; found {len(active)}"
            )
        if not view.next_action:
            issues.append(
                "structured workboard must project exactly one literal next_action"
            )
        elif not view.next_action.strip():
            issues.append("projected next_action must not be blank")
        for item in view.items:
            if item.work_id in view.terminal_work_ids:
                issues.append(f"terminal item {item.alias} also appears open")
            if not item.resume_action:
                issues.append(f"open item {item.alias} has no literal resume action")

    return tuple(dict.fromkeys(issues))


def load_workboard(
    path: Path | str | None = None,
    *,
    strict: bool = False,
) -> WorkboardProjection:
    """Parse, project, and validate through the three canonical authorities."""
    document = parse_workboard(path)
    projection = project_workboard(document)
    issues = validate_workboard(document, projection)
    result = replace(projection, issues=issues)
    if strict and issues:
        raise WorkboardConsistencyError("; ".join(issues))
    return result


def item_census(document: WorkboardDocument) -> ItemCensus:
    """Inventory stable item IDs without conflating projection with existence.

    Legacy checked rows and structured terminal events are deliberately retained:
    the migration acceptance test is about every historical item ID, not only the
    currently-open projection. Anonymous checklist rows are fingerprinted and
    reported separately because assigning them a new visible ID would itself be
    an invention.
    """

    checked: dict[str, bool] = {}
    text: dict[str, str] = {}
    anonymous: list[str] = []
    issues: list[str] = []
    census_key_by_work_id: dict[str, str] = {}
    rejected_openings: dict[str, tuple[WorkEvent, str]] = {}

    for record in document.records:
        if isinstance(record, LegacyItem):
            if record.item_id is None:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "checked": record.checked,
                            "text": record.source_text,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                anonymous.append(fingerprint)
                continue
            if record.item_id in checked:
                issues.append(
                    f"line {record.line_number}: duplicate census item {record.item_id}"
                )
                continue
            checked[record.item_id] = record.checked
            text[record.item_id] = record.source_text
            census_key_by_work_id[_legacy_work_id(record.item_id)] = record.item_id
            continue

        schema_issues = _event_schema_issues(record)
        if schema_issues:
            issues.extend(schema_issues)
            continue
        if record.kind in {"start", "queue"}:
            if "work_id" in record.fields:
                work_id = record.fields["work_id"]
                census_key = work_id
                display = record.fields["alias"]
            else:
                display = record.fields["item_id"]
                work_id = _legacy_work_id(display)
                census_key = display
            if census_key in checked or work_id in census_key_by_work_id:
                issue = f"line {record.line_number}: duplicate census item {display}"
                issues.append(issue)
                rejected_openings[record.event_id] = (record, issue)
                continue
            checked[census_key] = False
            text[census_key] = record.fields["summary"]
            census_key_by_work_id[work_id] = census_key
        elif record.kind == ADOPTION_KIND:
            rejected = rejected_openings.get(record.fields["source_event_id"])
            if rejected is None:
                issues.append(
                    f"line {record.line_number}: adopt has no rejected census source "
                    f"for {record.fields['source_event_id']}"
                )
                continue
            source, source_issue = rejected
            work_id = record.fields["work_id"]
            if work_id in census_key_by_work_id:
                issues.append(
                    f"line {record.line_number}: duplicate census work id {work_id}"
                )
                continue
            checked[work_id] = False
            text[work_id] = source.fields["summary"]
            census_key_by_work_id[work_id] = work_id
            issues.remove(source_issue)
            del rejected_openings[record.fields["source_event_id"]]
        elif record.kind in {"complete", "archive"}:
            if "work_id" in record.fields:
                work_id = record.fields["work_id"]
            else:
                work_id = _legacy_work_id(record.fields["item_id"])
            census_key = census_key_by_work_id.get(work_id)
            if census_key is None:
                issues.append(
                    f"line {record.line_number}: {record.kind} has no census source "
                    f"for {record.fields.get('item_id', work_id)}"
                )
                continue
            checked[census_key] = True
        elif record.kind == "drop":
            # A drop can either close a queued item or dispose of a request that
            # never became an item. Only the former belongs in an item census.
            if "work_id" in record.fields:
                work_id = record.fields["work_id"]
            else:
                work_id = _legacy_work_id(record.fields["request_id"])
            census_key = census_key_by_work_id.get(work_id)
            if census_key is not None:
                checked[census_key] = True

    return ItemCensus(
        checked=checked,
        text=text,
        anonymous_hashes=tuple(sorted(anonymous)),
        issues=tuple(dict.fromkeys(issues)),
    )


def compare_item_censuses(
    before: WorkboardDocument, after: WorkboardDocument
) -> dict[str, object]:
    """Return the bidirectional ID/state/text census required by migration."""

    left = item_census(before)
    right = item_census(after)
    before_ids = set(left.checked)
    after_ids = set(right.checked)
    dropped = sorted(before_ids - after_ids)
    invented = sorted(after_ids - before_ids)
    shared = sorted(before_ids & after_ids)
    state_changed = [
        {
            "item_id": item_id,
            "before": "checked" if left.checked[item_id] else "unchecked",
            "after": "checked" if right.checked[item_id] else "unchecked",
        }
        for item_id in shared
        if left.checked[item_id] != right.checked[item_id]
    ]
    text_changed = [
        item_id for item_id in shared if left.text[item_id] != right.text[item_id]
    ]
    anonymous_changed = left.anonymous_hashes != right.anonymous_hashes
    census_issues = sorted(set(left.issues) | set(right.issues))
    identity_ok = not dropped and not invented
    text_ok = not text_changed
    state_preserved = not state_changed
    anonymous_ok = not anonymous_changed
    return {
        "count_in": len(before_ids),
        "count_out": len(after_ids),
        "checked_in": sum(left.checked.values()),
        "checked_out": sum(right.checked.values()),
        "unchecked_in": sum(not value for value in left.checked.values()),
        "unchecked_out": sum(not value for value in right.checked.values()),
        "dropped": dropped,
        "invented": invented,
        "state_changed": state_changed,
        "text_changed": text_changed,
        "anonymous_count_in": len(left.anonymous_hashes),
        "anonymous_count_out": len(right.anonymous_hashes),
        "anonymous_changed": anonymous_changed,
        "census_issues": census_issues,
        "identity_ok": identity_ok,
        "text_ok": text_ok,
        "state_preserved": state_preserved,
        "anonymous_ok": anonymous_ok,
        "ok": identity_ok and text_ok and anonymous_ok and not census_issues,
    }


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def format_event(
    kind: str,
    *,
    event_id: str | None = None,
    at: str | None = None,
    **facts: str,
) -> str:
    """Serialize one structured Markdown fact line and validate its schema."""
    normalized = kind.lower()
    values = {
        "event_id": event_id or f"EV-{secrets.token_hex(6)}",
        "at": at or _now(),
        "kind": normalized,
        **{key: str(value) for key, value in facts.items() if value is not None},
    }
    multiline = sorted(
        key for key, value in values.items() if "\n" in value or "\r" in value
    )
    if multiline:
        raise WorkboardConsistencyError(
            "event facts must be single-line: " + ", ".join(multiline)
        )
    line = f"- {EVENT_TAG} " + " ".join(
        f"{key}={shlex.quote(value)}" for key, value in values.items()
    )
    parsed, issues = _parse_event_line(line, 1)
    if parsed is None:
        raise WorkboardConsistencyError("; ".join(issues))
    issues.extend(_event_schema_issues(parsed))
    if issues:
        raise WorkboardConsistencyError("; ".join(issues))
    return line + "\n"


def _declared_work_ids(
    document: WorkboardDocument, projection: WorkboardProjection
) -> set[str]:
    """Include invalid declarations so a future generator never recycles them."""
    declared = set(projection.known_work_ids)
    for record in document.records:
        if isinstance(record, WorkEvent):
            work_id = record.fields.get("work_id")
            if work_id:
                declared.add(work_id)
    return declared


def _open_work_id_for_alias(projection: WorkboardProjection, alias: str) -> str | None:
    matches = [item.work_id for item in projection.items if item.alias == alias]
    if len(matches) > 1:
        raise WorkboardConsistencyError(
            f"work alias {alias!r} is ambiguous across {len(matches)} open work ids; "
            "pass work_id explicitly"
        )
    return matches[0] if matches else None


def _normalize_append_facts(
    kind: str,
    facts: Mapping[str, str],
    document: WorkboardDocument,
    projection: WorkboardProjection,
) -> dict[str, str]:
    """Resolve compatibility aliases and allocate identities under the write lock."""
    normalized = dict(facts)
    declared = _declared_work_ids(document, projection)

    if kind in {"start", "queue"}:
        legacy_alias = normalized.pop("item_id", None)
        alias = normalized.get("alias")
        if alias is not None and legacy_alias is not None and alias != legacy_alias:
            raise WorkboardConsistencyError(
                f"item_id {legacy_alias!r} and alias {alias!r} disagree"
            )
        if alias is None and legacy_alias is not None:
            alias = legacy_alias
            normalized["alias"] = alias
        if alias is not None:
            matches = tuple(
                item.work_id for item in projection.items if item.alias == alias
            )
            if matches:
                noun = "item" if len(matches) == 1 else "items"
                raise WorkboardConsistencyError(
                    f"cannot {kind} alias {alias!r}: it already belongs to "
                    f"{len(matches)} open {noun}; {kind} is an opening event, "
                    "so use an existing-item transition instead"
                )
        if "work_id" not in normalized:
            normalized["work_id"] = generate_work_id(declared)
        return normalized

    if kind == ADOPTION_KIND:
        source_event_id = normalized.get("source_event_id")
        source = next(
            (
                record
                for record in document.records
                if isinstance(record, WorkEvent)
                and record.event_id == source_event_id
                and record.kind in {"start", "queue"}
            ),
            None,
        )
        if source is None:
            raise WorkboardConsistencyError(
                f"adopt source {source_event_id!r} is not a prior opening event"
            )
        source_alias = source.fields.get("alias") or source.fields.get("item_id")
        supplied_alias = normalized.get("alias")
        if supplied_alias is not None and supplied_alias != source_alias:
            raise WorkboardConsistencyError(
                f"adopt alias {supplied_alias!r} does not match source alias "
                f"{source_alias!r}"
            )
        normalized["alias"] = source_alias
        if "work_id" not in normalized:
            normalized["work_id"] = generate_work_id(declared)
        return normalized

    if kind in {"switch", "advance", "block", "complete", "archive"}:
        alias = normalized.get("item_id")
        if alias is not None:
            if "work_id" in normalized:
                raise WorkboardConsistencyError(
                    "pass either item_id as an alias or work_id, not both"
                )
            work_id = _open_work_id_for_alias(projection, alias)
            if work_id is not None and _WORK_ID_RE.fullmatch(work_id):
                del normalized["item_id"]
                normalized["work_id"] = work_id
        return normalized

    if kind == "fold" and "target_id" in normalized:
        target = _open_work_id_for_alias(projection, normalized["target_id"])
        if target is not None and _WORK_ID_RE.fullmatch(target):
            del normalized["target_id"]
            normalized["target_work_id"] = target
        return normalized

    if kind == "drop" and "request_id" in normalized:
        target = _open_work_id_for_alias(projection, normalized["request_id"])
        if target is not None and _WORK_ID_RE.fullmatch(target):
            del normalized["request_id"]
            normalized["work_id"] = target
        return normalized

    return normalized


def _event_target_work_id(event: WorkEvent) -> str | None:
    fields = event.fields
    if event.kind in {"start", "queue", ADOPTION_KIND}:
        return fields.get("work_id") or _legacy_work_id(fields["item_id"])
    if event.kind == "fold":
        return fields.get("target_work_id") or _legacy_work_id(fields["target_id"])
    if event.kind == "drop":
        return fields.get("work_id") or _legacy_work_id(fields["request_id"])
    if event.kind in {"switch", "advance", "block", "complete", "archive"}:
        return fields.get("work_id") or _legacy_work_id(fields["item_id"])
    return None


def _event_is_reflected(
    before: WorkboardProjection,
    after: WorkboardProjection,
    event: WorkEvent,
) -> bool:
    """Prove the candidate changed the projection according to its event kind."""
    prior_event_ids = {
        record.event_id
        for record in before.document.records
        if isinstance(record, WorkEvent)
    }
    if event.event_id in prior_event_ids:
        return False
    if event.kind in {"restart", COMPACTION_KIND}:
        return True

    target = _event_target_work_id(event)
    if target is None:
        return False
    before_item = next((item for item in before.items if item.work_id == target), None)
    after_item = next((item for item in after.items if item.work_id == target), None)

    if event.kind in {
        "start",
        "queue",
        ADOPTION_KIND,
        "switch",
        "advance",
        "block",
        "fold",
    }:
        return after_item is not None and after_item.last_event_id == event.event_id
    if event.kind in {"complete", "archive"}:
        return (
            before_item is not None
            and after_item is None
            and target in after.terminal_work_ids
        )
    if event.kind == "drop":
        return after_item is None and target in after.terminal_work_ids
    return False


def _added_issues(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[str, ...]:
    remaining = Counter(before)
    added: list[str] = []
    for issue in after:
        if remaining[issue]:
            remaining[issue] -= 1
        else:
            added.append(issue)
    return tuple(added)


@contextmanager
def _locked_workboard_registry(dest: Path, *, create_parent: bool = True):
    """Hold the stable registry lock shared by append, apply, and rollback.

    A lock on ``dest`` alone is not stable across atomic replacement: a waiter
    can retain the pre-rename inode and append into an unlinked file. The parent
    directory inode remains stable across the rename and requires no sidecar
    file outside the packet's declared write scope. Every workboard writer takes
    this lock before opening the destination, then keeps the existing file lock
    as compatibility defense.
    """

    if create_parent:
        dest.parent.mkdir(parents=True, exist_ok=True)
    elif not dest.parent.is_dir():
        raise WorkboardMigrationError(
            f"workboard parent directory does not exist: {dest.parent}"
        )
    directory_fd = os.open(dest.parent, os.O_RDONLY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        yield directory_fd
    finally:
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_UN)
        finally:
            os.close(directory_fd)


def append_event(
    kind: str,
    *,
    path: Path | str | None = None,
    event_id: str | None = None,
    at: str | None = None,
    **facts: str,
) -> WorkEvent:
    """Append only after a locked simulation proves the event is not discarded.

    Legacy openings resolve through ``item_id`` as an alias only. Their
    projected ``legacy-...`` IDs are internal compatibility values and are
    never valid ``work_id`` arguments.
    """
    dest = Path(path) if path is not None else WORKBOARD_PATH
    with _locked_workboard_registry(dest):
        fd: int | None = None
        try:
            if dest.exists():
                fd = os.open(dest, os.O_RDWR | os.O_APPEND)
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.lseek(fd, 0, os.SEEK_SET)
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                existing = b"".join(chunks)
            else:
                existing = b""
            try:
                current_text = existing.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkboardConsistencyError(
                    f"{dest} is not valid UTF-8; refusing append ({exc})"
                ) from exc

            before_document = _parse_workboard_text(dest, current_text)
            before_projection = project_workboard(before_document)
            before_issues = validate_workboard(before_document, before_projection)
            normalized_kind = kind.lower()
            normalized_facts = _normalize_append_facts(
                normalized_kind, facts, before_document, before_projection
            )
            line = format_event(
                normalized_kind,
                event_id=event_id,
                at=at,
                **normalized_facts,
            )
            rendered_event, rendered_issues = _parse_event_line(line.rstrip("\n"), 1)
            if rendered_event is None or rendered_issues:
                raise AssertionError("formatted event did not round-trip")
            header = ""
            if not existing:
                header = (
                    "# Open Work\n\n"
                    "Append-only machine facts. Add state only through "
                    "`chrono_state.workboard.append_event`.\n\n"
                )
            candidate_text = current_text + header + line
            after_document = _parse_workboard_text(dest, candidate_text)
            after_projection = project_workboard(after_document)
            after_issues = validate_workboard(after_document, after_projection)
            candidate = next(
                (
                    record
                    for record in reversed(after_document.records)
                    if isinstance(record, WorkEvent)
                    and record.event_id == rendered_event.event_id
                ),
                None,
            )
            if candidate is None:
                raise WorkboardConsistencyError(
                    "append rejected: candidate event did not parse from the simulated document"
                )
            if not _event_is_reflected(before_projection, after_projection, candidate):
                added = _added_issues(before_issues, after_issues)
                detail = "; ".join(added) or "projection postcondition failed"
                raise WorkboardConsistencyError(
                    f"append rejected: {candidate.event_id} was not reflected as "
                    f"{candidate.kind}; added issue(s): {detail}"
                )
            if fd is None:
                fd = os.open(
                    dest,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_APPEND,
                    0o644,
                )
                fcntl.flock(fd, fcntl.LOCK_EX)
            payload = (header + line).encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("append-only workboard write made no progress")
                offset += written
            os.fsync(fd)
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
    return candidate


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_replace_bytes(path: Path, content: bytes, mode: int) -> None:
    """Publish bytes as temp + fsync + rename + directory fsync."""

    temporary = tempfile.NamedTemporaryFile(
        "w+b",
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        temporary.write(content)
        temporary.flush()
        os.fchmod(temporary.fileno(), mode)
        os.fsync(temporary.fileno())
        temporary.close()
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.close()
        except Exception:
            pass
        try:
            os.unlink(temporary_path)
        except OSError:
            # Cleanup must not mask the write/rename/fsync failure that reached
            # this finally block. A successful rename already removed the name.
            pass


def _decode_migration_source(source: bytes, path: Path) -> str:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkboardMigrationError(
            f"{path} is not valid UTF-8; refusing migration ({exc})"
        ) from exc
    if "\r" in text:
        raise WorkboardMigrationError(
            "migration requires canonical LF line endings so rollback is byte-exact"
        )
    if source and not source.endswith(b"\n"):
        raise WorkboardMigrationError(
            "migration requires a final LF so rollback is byte-exact"
        )
    return text


def _rewrite_header_contract(text: str, *, reverse: bool = False) -> tuple[str, bool]:
    """Replace only the pre-list writer instructions, never item text."""

    prefix, separator, remainder = text.partition("\n---\n")
    if not separator:
        return text, False
    pairs = [
        (after, before) if reverse else (before, after)
        for before, after in HEADER_CONTRACT_REPLACEMENTS
    ]
    present = [source in prefix for source, _target in pairs]
    if any(present) and not all(present):
        direction = "event" if reverse else "legacy"
        raise WorkboardMigrationError(
            f"partial {direction} header contract; refusing ambiguous rewrite"
        )
    if not all(present):
        return text, False
    for source, target in pairs:
        prefix = prefix.replace(source, target, 1)
    return prefix + separator + remainder, True


def _legacy_migration_rows(
    source: bytes, path: Path
) -> tuple[WorkboardDocument, dict[int, _LegacyMigrationRow]]:
    text = _decode_migration_source(source, path)
    document = _parse_workboard_text(path, text)
    if document.has_structured_events:
        raise WorkboardMigrationError(
            "workboard already contains structured events; use the migration census"
        )
    if document.issues:
        raise WorkboardMigrationError(
            "legacy workboard is invalid: " + "; ".join(document.issues)
        )

    rows: dict[int, _LegacyMigrationRow] = {}
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(keepends=True), start=1):
        line = raw_line[:-1]
        legacy_match = _LEGACY_ITEM_RE.fullmatch(line)
        if legacy_match is None:
            continue
        head = legacy_match.group("body").partition("|")[0].strip()
        if not _ITEM_ID_RE.fullmatch(head) or len(head) > MAX_ID_CHARS:
            # One live completed historical row intentionally has no ID. It is
            # not assigned one during migration; its exact bytes and anonymous
            # census fingerprint remain in place.
            continue
        match = _MIGRATABLE_LEGACY_RE.fullmatch(line)
        if match is None:
            raise WorkboardMigrationError(
                f"line {line_number}: explicit-ID checklist row is not in the "
                "canonical '- [ ] ID | text' form"
            )
        item_id = match.group("item_id")
        if item_id in seen_ids:
            raise WorkboardMigrationError(
                f"line {line_number}: duplicate migration item ID {item_id}"
            )
        seen_ids.add(item_id)
        item_text = match.group("text")
        rows[line_number] = _LegacyMigrationRow(
            line_number=line_number,
            item_id=item_id,
            text=item_text,
            checked=match.group("state") == "x",
            active=bool(re.search(r"\*\*IN PROGRESS\s+—\s+[^*]+\*\*", item_text, re.I)),
        )

    if not rows:
        raise WorkboardMigrationError("no explicit-ID legacy checklist rows found")
    active = [row.item_id for row in rows.values() if row.active and not row.checked]
    if len(active) != 1:
        raise WorkboardMigrationError(
            "migration requires exactly one unchecked IN PROGRESS item; "
            f"found {len(active)} ({', '.join(active) or 'none'})"
        )
    return document, rows


def _migration_resume_action(row: _LegacyMigrationRow) -> str:
    _summary, action = _legacy_split_next_action(row.text)
    return action or f"continue {row.item_id} from its preserved workboard entry"


def _migration_events(row: _LegacyMigrationRow, event_seed: str, ordinal: int) -> str:
    event_base = f"MIG-{event_seed}-{ordinal:04d}"
    if row.checked:
        return format_event(
            "queue",
            event_id=f"{event_base}-OPEN",
            at=MIGRATION_AT,
            item_id=row.item_id,
            summary=row.text,
            why=MIGRATION_WHY,
            resume_action=MIGRATION_COMPLETED_ACTION,
        ) + format_event(
            "complete",
            event_id=f"{event_base}-COMPLETE",
            at=MIGRATION_AT,
            item_id=row.item_id,
        )
    if row.active:
        return format_event(
            "start",
            event_id=f"{event_base}-OPEN",
            at=MIGRATION_AT,
            item_id=row.item_id,
            summary=row.text,
            why=MIGRATION_WHY,
            next_action=_migration_resume_action(row),
        )
    return format_event(
        "queue",
        event_id=f"{event_base}-OPEN",
        at=MIGRATION_AT,
        item_id=row.item_id,
        summary=row.text,
        why=MIGRATION_WHY,
        resume_action=_migration_resume_action(row),
    )


def _build_migration_plan(source: bytes, path: Path) -> WorkboardMigrationPlan:
    before, rows = _legacy_migration_rows(source, path)
    source_sha256 = _sha256_bytes(source)
    event_seed = source_sha256[:16]
    source_text = source.decode("utf-8")
    rendered_text, header_contract_updated = _rewrite_header_contract(source_text)

    body_parts: list[str] = []
    marker_index: int | None = None
    ordinal = 0
    for line_number, raw_line in enumerate(
        rendered_text.splitlines(keepends=True), start=1
    ):
        row = rows.get(line_number)
        if row is None:
            body_parts.append(raw_line)
            continue
        if marker_index is None:
            marker_index = len(body_parts)
        ordinal += 1
        body_parts.append(_migration_events(row, event_seed, ordinal))

    if marker_index is None:
        raise AssertionError("migration rows vanished during render")
    body = "".join(body_parts).encode("utf-8")
    body_sha256 = _sha256_bytes(body)
    plan_sha256 = _canonical_json_sha256(
        {
            "schema": MIGRATION_SCHEMA,
            "action": "migrate",
            "source_sha256": source_sha256,
            "body_sha256": body_sha256,
            "body_size": len(body),
            "event_seed": event_seed,
            "migration_at": MIGRATION_AT,
            "header_contract": (
                HEADER_CONTRACT_VERSION if header_contract_updated else "unchanged"
            ),
            "items": [
                {
                    "line_number": row.line_number,
                    "item_id": row.item_id,
                    "checked": row.checked,
                    "active": row.active,
                    "text_sha256": _sha256_bytes(row.text.encode("utf-8")),
                }
                for row in rows.values()
            ],
        }
    )
    marker = (
        f"{MIGRATION_MARKER_PREFIX}"
        f"plan_sha256={plan_sha256} "
        f"source_sha256={source_sha256} "
        f"body_sha256={body_sha256} "
        f"body_size={len(body)} -->\n"
    )
    target_parts = list(body_parts)
    target_parts.insert(marker_index, marker)
    target = "".join(target_parts).encode("utf-8")

    after = _parse_workboard_text(path, target.decode("utf-8"))
    projection = project_workboard(after)
    validation_issues = validate_workboard(after, projection)
    census = compare_item_censuses(before, after)
    before_projection = project_workboard(before)
    report: dict[str, object] = {
        "schema": MIGRATION_SCHEMA,
        "action": "migrate",
        "plan_sha256": plan_sha256,
        "migration_id": "",
        "source_sha256": source_sha256,
        "target_sha256": _sha256_bytes(target),
        "legacy_explicit_rows_migrated": len(rows),
        "legacy_checklist_count_in": len(before.records),
        "legacy_anonymous_rows_preserved": census["anonymous_count_in"],
        "header_contract": (
            HEADER_CONTRACT_VERSION if header_contract_updated else "unchanged"
        ),
        "header_contract_updated": header_contract_updated,
        "active_id_in": before_projection.active_item_id or "",
        "active_id_out": projection.active_item_id or "",
        "validation_issues": list(validation_issues),
        "lock": "exclusive flock on stable workboard parent-directory inode",
        "atomic_publish": "same-directory temp + file fsync + rename + directory fsync",
        "rollback": "migration marker + byte-exact source reconstruction",
        **census,
    }
    if validation_issues or not census["ok"] or not census["state_preserved"]:
        raise WorkboardMigrationError(
            "migration candidate failed validation or preservation census", report
        )
    return WorkboardMigrationPlan(
        action="migrate",
        plan_sha256=plan_sha256,
        migration_id=plan_sha256,
        source_bytes=source,
        target_bytes=target,
        report=report,
    )


def _split_migrated_body(
    current: bytes, path: Path
) -> tuple[dict[str, str | int], bytes, bytes]:
    text = _decode_migration_source(current, path)
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        marker = _MIGRATION_MARKER_RE.fullmatch(line.rstrip("\n"))
        if marker is not None:
            matches.append((index, marker))
    if len(matches) != 1:
        raise WorkboardMigrationError(
            f"expected exactly one {MIGRATION_SCHEMA} marker; found {len(matches)}"
        )
    marker_index, marker = matches[0]
    without_marker = "".join(
        line for index, line in enumerate(lines) if index != marker_index
    ).encode("utf-8")
    body_size = int(marker.group("size"))
    if body_size > len(without_marker):
        raise WorkboardMigrationError("migration marker body_size exceeds file size")
    body = without_marker[:body_size]
    suffix = without_marker[body_size:]
    if _sha256_bytes(body) != marker.group("body"):
        raise WorkboardMigrationError(
            "migrated base changed after apply; refusing reconstruction"
        )
    return (
        {
            "plan_sha256": marker.group("plan"),
            "source_sha256": marker.group("source"),
            "body_sha256": marker.group("body"),
            "body_size": body_size,
        },
        body,
        suffix,
    )


def _event_from_rendered_line(line: str, line_number: int) -> WorkEvent | None:
    if not line.startswith(f"- {EVENT_TAG}"):
        return None
    event, issues = _parse_event_line(line.rstrip("\n"), line_number)
    if event is None or issues:
        raise WorkboardMigrationError(
            f"line {line_number}: malformed migration event ({'; '.join(issues)})"
        )
    return event


def _restore_migration_source(
    body: bytes, metadata: Mapping[str, str | int], path: Path
) -> bytes:
    text = _decode_migration_source(body, path)
    lines = text.splitlines(keepends=True)
    restored: list[str] = []
    prefix = f"MIG-{str(metadata['source_sha256'])[:16]}-"
    index = 0
    while index < len(lines):
        line = lines[index]
        event = _event_from_rendered_line(line, index + 1)
        if event is None or not event.event_id.startswith(prefix):
            restored.append(line)
            index += 1
            continue
        if event.kind not in {"start", "queue"} or not event.event_id.endswith("-OPEN"):
            raise WorkboardMigrationError(
                f"line {index + 1}: unexpected migration event {event.event_id}"
            )
        item_id = event.fields["item_id"]
        checked = False
        if event.kind == "queue" and index + 1 < len(lines):
            following = _event_from_rendered_line(lines[index + 1], index + 2)
            expected = event.event_id[: -len("-OPEN")] + "-COMPLETE"
            if (
                following is not None
                and following.event_id == expected
                and following.kind == "complete"
                and following.fields.get("item_id") == item_id
            ):
                checked = True
                index += 1
        state = "x" if checked else " "
        restored.append(f"- [{state}] {item_id} | {event.fields['summary']}\n")
        index += 1

    restored_text, _header_restored = _rewrite_header_contract(
        "".join(restored), reverse=True
    )
    result = restored_text.encode("utf-8")
    if _sha256_bytes(result) != metadata["source_sha256"]:
        raise WorkboardMigrationError(
            "rollback reconstruction does not match the pre-migration SHA-256"
        )
    return result


def _build_rollback_plan(
    current: bytes, path: Path, migration_id: str
) -> WorkboardMigrationPlan:
    metadata, body, suffix = _split_migrated_body(current, path)
    if metadata["plan_sha256"] != migration_id:
        raise WorkboardMigrationError(
            "rollback migration ID does not match the applied marker"
        )
    if suffix:
        raise WorkboardMigrationError(
            "workboard changed after migration; refusing destructive rollback"
        )
    restored = _restore_migration_source(body, metadata, path)
    before = _parse_workboard_text(path, current.decode("utf-8"))
    after = _parse_workboard_text(path, restored.decode("utf-8"))
    census = compare_item_censuses(before, after)
    plan_sha256 = _canonical_json_sha256(
        {
            "schema": MIGRATION_SCHEMA,
            "action": "rollback",
            "migration_id": migration_id,
            "source_sha256": _sha256_bytes(current),
            "target_sha256": _sha256_bytes(restored),
        }
    )
    report: dict[str, object] = {
        "schema": MIGRATION_SCHEMA,
        "action": "rollback",
        "plan_sha256": plan_sha256,
        "migration_id": migration_id,
        "source_sha256": _sha256_bytes(current),
        "target_sha256": _sha256_bytes(restored),
        "post_migration_bytes": 0,
        **census,
    }
    if not census["ok"] or not census["state_preserved"]:
        raise WorkboardMigrationError("rollback census failed", report)
    return WorkboardMigrationPlan(
        action="rollback",
        plan_sha256=plan_sha256,
        migration_id=migration_id,
        source_bytes=current,
        target_bytes=restored,
        report=report,
    )


def _apply_migration_plan(path: Path, plan: WorkboardMigrationPlan, mode: int) -> None:
    try:
        _atomic_replace_bytes(path, plan.target_bytes, mode)
    except Exception as exc:
        restore_error: Exception | None = None
        try:
            if path.read_bytes() != plan.source_bytes:
                _atomic_replace_bytes(path, plan.source_bytes, mode)
        except Exception as restore_exc:
            restore_error = restore_exc
        if restore_error is not None:
            raise WorkboardMigrationError(
                f"atomic {plan.action} failed and compensating restore failed: "
                f"{restore_error}; original error: {exc}"
            ) from exc
        raise WorkboardMigrationError(
            f"atomic {plan.action} failed; original restored: {exc}"
        ) from exc
    observed = path.read_bytes()
    if observed == plan.target_bytes:
        return
    try:
        _atomic_replace_bytes(path, plan.source_bytes, mode)
    except Exception as restore_exc:
        raise WorkboardMigrationError(
            f"{plan.action} verification failed and restore failed: {restore_exc}"
        ) from restore_exc
    raise WorkboardMigrationError(
        f"{plan.action} verification failed; original restored"
    )


def _audit_migration_bytes(
    current: bytes, path: Path, migration_id: str
) -> dict[str, object]:
    metadata, body, suffix = _split_migrated_body(current, path)
    if metadata["plan_sha256"] != migration_id:
        raise WorkboardMigrationError(
            "census migration ID does not match the applied marker"
        )
    restored = _restore_migration_source(body, metadata, path)
    before = _parse_workboard_text(path, restored.decode("utf-8"))
    after = _parse_workboard_text(path, current.decode("utf-8"))
    projection = project_workboard(after)
    validation_issues = validate_workboard(after, projection)
    census = compare_item_censuses(before, after)
    report: dict[str, object] = {
        "schema": MIGRATION_SCHEMA,
        "action": "census",
        "outcome": "pass" if census["ok"] and not validation_issues else "fail",
        "plan_sha256": migration_id,
        "migration_id": migration_id,
        "source_sha256": metadata["source_sha256"],
        "applied_sha256": _sha256_bytes(current),
        "base_body_sha256": metadata["body_sha256"],
        "post_migration_bytes": len(suffix),
        "active_id_out": projection.active_item_id or "",
        "validation_issues": list(validation_issues),
        **census,
    }
    report["ok"] = bool(census["ok"] and not validation_issues)
    return report


def migrate_workboard(
    *,
    dry_run: bool,
    apply_plan_sha256: str = "",
    rollback_migration_id: str = "",
    path: Path | str | None = None,
) -> dict[str, object]:
    """Dry-run/apply/rollback the legacy checklist under one stable lock."""

    if apply_plan_sha256 and not _HEX_SHA256_RE.fullmatch(apply_plan_sha256):
        raise WorkboardMigrationError("apply plan SHA-256 must be lowercase 64-hex")
    if rollback_migration_id and not _HEX_SHA256_RE.fullmatch(rollback_migration_id):
        raise WorkboardMigrationError("rollback migration ID must be lowercase 64-hex")
    if not dry_run and not apply_plan_sha256:
        raise WorkboardMigrationError(
            "apply requires a plan SHA-256 from a preceding locked dry-run"
        )

    dest = Path(path) if path is not None else WORKBOARD_PATH
    with _locked_workboard_registry(dest, create_parent=False):
        if dest.is_symlink() or not dest.is_file():
            raise WorkboardMigrationError(
                f"migration target must be an existing regular file: {dest}"
            )
        source = dest.read_bytes()
        mode = stat.S_IMODE(dest.stat().st_mode)
        if rollback_migration_id:
            plan = _build_rollback_plan(source, dest, rollback_migration_id)
        elif MIGRATION_MARKER_PREFIX.encode("utf-8") in source:
            metadata, _body, _suffix = _split_migrated_body(source, dest)
            applied_id = str(metadata["plan_sha256"])
            if apply_plan_sha256 and apply_plan_sha256 != applied_id:
                raise WorkboardMigrationError(
                    "workboard already carries a different migration plan"
                )
            report = _audit_migration_bytes(source, dest, applied_id)
            report.update(
                {
                    "action": "migrate",
                    "outcome": "already-applied",
                    "plan_sha256": applied_id,
                }
            )
            return report
        else:
            plan = _build_migration_plan(source, dest)

        report = dict(plan.report)
        if dry_run:
            report["outcome"] = "dry-run"
            return report
        if plan.plan_sha256 != apply_plan_sha256:
            raise WorkboardMigrationError(
                "migration plan changed after dry-run; expected "
                f"{apply_plan_sha256}, observed {plan.plan_sha256}; run a fresh "
                "dry-run",
                report,
            )
        _apply_migration_plan(dest, plan, mode)
        report["outcome"] = "rolled-back" if plan.action == "rollback" else "applied"
        report["migration_id"] = plan.migration_id
        report["applied_sha256"] = _sha256_bytes(dest.read_bytes())
        return report


def audit_workboard_migration(
    migration_id: str, path: Path | str | None = None
) -> dict[str, object]:
    """Reconstruct the pre-image and census the bytes actually on disk."""

    if not _HEX_SHA256_RE.fullmatch(migration_id):
        raise WorkboardMigrationError("migration ID must be lowercase 64-hex")
    dest = Path(path) if path is not None else WORKBOARD_PATH
    with _locked_workboard_registry(dest, create_parent=False):
        if dest.is_symlink() or not dest.is_file():
            raise WorkboardMigrationError(
                f"census target must be an existing regular file: {dest}"
            )
        report = _audit_migration_bytes(dest.read_bytes(), dest, migration_id)
    if not report["ok"]:
        raise WorkboardMigrationError("applied migration census failed", report)
    return report


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 2)].rstrip() + " …"


def resume_rows(path: Path | str | None = None) -> ResumeRows:
    """Return legacy-compatible rows backed by the canonical projection."""
    projection = load_workboard(path)
    rows = []
    for item in projection.items:
        summary = item.summary
        if item.why:
            summary += f" — why: {item.why}"
        if item.state == "active" and ACTIVE_MARKER not in summary:
            summary = f"{ACTIVE_MARKER} {summary}"
        item_id = (
            None
            if item.item_id.startswith(("legacy-line-", "legacy-anon-"))
            else item.item_id
        )
        rows.append((item_id, summary, item.resume_action))
    if projection.issues:
        rows.append(
            (
                None,
                "WORKBOARD INVALID: " + "; ".join(projection.issues),
                f"repair {WORKBOARD_REL} through the canonical validator",
            )
        )
    return ResumeRows(projection, rows)


def render_resume_rows(rows, show_detail: bool) -> list[str]:
    """Render the one prominence projection into the bounded resume block."""
    projection = rows.projection if isinstance(rows, ResumeRows) else None
    real_count = len(projection.items) if projection is not None else len(rows)
    if not show_detail:
        collapsed = []
        if projection is not None and projection.issues:
            collapsed.append(
                "- WORKBOARD INVALID: "
                + _clip("; ".join(projection.issues), SUMMARY_CLIP)
                + " [OPEN-WORK]"
            )
        if (
            projection is not None
            and projection.document.has_structured_events
            and projection.next_action
        ):
            # The active action is the one work-state fact the token bound may
            # not summarize or clip. A context boundary is nonterminal.
            collapsed.append(f"- next_action: {projection.next_action}")
        collapsed.append(
            f"- ({real_count} open item(s) omitted for the token bound — "
            f"regenerate at a higher budget or read {WORKBOARD_REL})"
        )
        return collapsed

    if projection is not None:
        selected_rows = []
        for item in projection.prominent_items[:MAX_PROJECTED_ITEMS]:
            item_id = (
                None
                if item.item_id.startswith(("legacy-line-", "legacy-anon-"))
                else item.item_id
            )
            body = item.summary + (f" — why: {item.why}" if item.why else "")
            if item.state == "active" and ACTIVE_MARKER not in body:
                body = f"{ACTIVE_MARKER} {body}"
            selected_rows.append((item_id, body, item.resume_action, item))
        invalid_rows = [
            (item_id, body, action, None)
            for item_id, body, action in rows
            if body.startswith("WORKBOARD INVALID:")
        ]
        selected_rows += invalid_rows
    else:
        selected_rows = [(*row, None) for row in list(rows)[:MAX_PROJECTED_ITEMS]]

    lines: list[str] = []
    structured = bool(
        projection is not None and projection.document.has_structured_events
    )
    for item_id, body, action, item in selected_rows:
        source = f"[OPEN-WORK-{item_id}]" if item_id else "[OPEN-WORK]"
        row = _clip(body or "(no summary)", SUMMARY_CLIP)
        if structured and item is not None:
            if item.state == "active" and projection.next_action:
                row += f"; next_action: {projection.next_action}"
            elif action:
                row += f"; resume: {_clip(action, ACTION_CLIP)}"
        elif action:
            row += f"; next: {_clip(action, ACTION_CLIP)}"
        lines.append(f"- {row} {source}")

    dropped = real_count - min(real_count, MAX_PROJECTED_ITEMS)
    if dropped > 0:
        lines.append(
            f"- +{dropped} open item(s) omitted from this bounded block — "
            f"read {WORKBOARD_REL}"
        )
    return lines


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, migrate, and census the canonical Chrono workboard"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    migrate = subcommands.add_parser(
        "migrate", help="locked dry-run/apply/rollback of legacy checklist rows"
    )
    migrate.add_argument("--path", type=Path, default=WORKBOARD_PATH)
    action = migrate.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply-plan-sha256", metavar="SHA256", default="")
    migrate.add_argument("--rollback-migration-id", metavar="SHA256", default="")

    census = subcommands.add_parser(
        "census", help="reconstruct the pre-image and compare it to applied bytes"
    )
    census.add_argument("--path", type=Path, default=WORKBOARD_PATH)
    census.add_argument("--migration-id", required=True, metavar="SHA256")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    try:
        if args.command == "migrate":
            report = migrate_workboard(
                dry_run=args.dry_run,
                apply_plan_sha256=args.apply_plan_sha256,
                rollback_migration_id=args.rollback_migration_id,
                path=args.path,
            )
        else:
            report = audit_workboard_migration(args.migration_id, args.path)
    except WorkboardMigrationError as exc:
        if exc.report:
            print(json.dumps(exc.report, ensure_ascii=False, sort_keys=True))
        print(f"workboard migration ERROR: {exc}", file=os.sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
