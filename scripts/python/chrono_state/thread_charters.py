"""Markdown-first active-thread charters for Chrono's resume rail.

An active charter is one regular ``*.md`` file under
``_state/chrono/thread-charters/active``.  The path supplies the active status;
the file therefore needs exactly three fields and no frontmatter:

``THE ASK`` / ``OPEN LOOPS`` / ``DONE-WHEN``.

The parser is deliberately small and fail-soft.  The resume capsule can surface a
malformed charter without crashing, while the skill-wiring validator reports the
same issue informationally.  This module never mutates a charter: OPEN LOOPS is an
append-only operator/Chrono ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


CHARTERS_REL = Path("_state/chrono/thread-charters/active")
FIELD_ORDER = ("THE ASK", "OPEN LOOPS", "DONE-WHEN")
STALE_AFTER = timedelta(hours=24)

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_CHECKBOX_RE = re.compile(r"^- \[(?P<mark>[ xX])\]\s+\S")
_QUEUE_ID = r"Q-[A-Za-z0-9][A-Za-z0-9._-]*"
_QUEUE_CLASS_RE = re.compile(rf"^QUEUE\s+(?P<id>{_QUEUE_ID})$")
_RESOLUTION_CLASS_RE = re.compile(
    rf"^(?P<kind>FOLD|DECLINE)\s+resolves\s+(?P<id>{_QUEUE_ID})$"
)
_TERMINAL_CLASS_RE = re.compile(r"^(FOLD|DECLINE)$")
_LOOP_RE = re.compile(
    r"^- (?P<stamp>[^|]+?)\s*\|\s*(?P<classification>[^|]+?)\s*\|\s*"
    r"(?P<request>.+?)\s+—\s+why:\s*(?P<why>.+?);\s*resume:\s*(?P<resume>.+?)\s*$"
)
_OBSERVED_AT_RE = re.compile(
    r"\bobserved_at=(?P<stamp>\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))"
)


@dataclass(frozen=True)
class OpenLoop:
    """One physical OPEN LOOPS ledger line."""

    raw: str
    classification: str
    queue_id: str | None = None
    resolves: str | None = None


@dataclass(frozen=True)
class StaleClaim:
    """One ``observed_at`` stamp older than the capsule freshness window."""

    line_number: int
    observed_at: str


@dataclass(frozen=True)
class ThreadCharter:
    """Parsed projection of one active charter, including loud parse issues."""

    path: Path
    ask: str
    open_loops: tuple[OpenLoop, ...]
    done_when: tuple[str, ...]
    done_when_met: bool
    unresolved_queues: tuple[OpenLoop, ...]
    stale_claims: tuple[StaleClaim, ...]
    issues: tuple[str, ...]

    @property
    def thread_id(self) -> str:
        return self.path.stem


def _parse_iso8601(value: str) -> datetime | None:
    """Parse the bounded ISO-8601 spellings used by charter ledger lines."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _section(lines: list[str], heading: str) -> list[str]:
    """Return a heading's body up to the next level-two heading."""
    marker = f"## {heading}"
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if _HEADING_RE.match(lines[index]):
            end = index
            break
    return lines[start:end]


def _one_line(lines: list[str]) -> str:
    """Collapse a prose field for the bounded capsule projection."""
    return " ".join(line.strip() for line in lines if line.strip())


def parse_charter(path: Path, now: datetime | None = None) -> ThreadCharter:
    """Parse one charter without raising for malformed or unreadable state."""
    issues: list[str] = []
    if path.is_symlink() or not path.is_file():
        return ThreadCharter(
            path=path,
            ask="",
            open_loops=(),
            done_when=(),
            done_when_met=False,
            unresolved_queues=(),
            stale_claims=(),
            issues=("charter must be a regular file, not a symlink or special entry",),
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ThreadCharter(
            path=path,
            ask="",
            open_loops=(),
            done_when=(),
            done_when_met=False,
            unresolved_queues=(),
            stale_claims=(),
            issues=(f"charter is unreadable UTF-8 ({exc})",),
        )

    lines = text.splitlines()
    headings = [m.group(1) for line in lines if (m := _HEADING_RE.match(line))]
    if tuple(headings) != FIELD_ORDER:
        issues.append(
            "level-two headings must be exactly, once each, and in order: "
            + " / ".join(FIELD_ORDER)
        )

    ask_lines = _section(lines, "THE ASK")
    loop_lines = _section(lines, "OPEN LOOPS")
    done_lines = [line.strip() for line in _section(lines, "DONE-WHEN") if line.strip()]
    ask = _one_line(ask_lines)
    if not ask:
        issues.append("THE ASK is empty")

    if not done_lines:
        issues.append("DONE-WHEN is empty; use one or more checkbox lines")
    checkbox_marks: list[bool] = []
    for line in done_lines:
        match = _CHECKBOX_RE.match(line)
        if not match:
            issues.append(f"DONE-WHEN entry is not a checkbox line: {line}")
            continue
        checkbox_marks.append(match.group("mark").lower() == "x")
    done_when_met = bool(done_lines) and len(checkbox_marks) == len(done_lines) and all(
        checkbox_marks
    )

    parsed_loops: list[OpenLoop] = []
    queue_by_id: dict[str, OpenLoop] = {}
    resolved: set[str] = set()
    nonblank_loops = [line.strip() for line in loop_lines if line.strip()]
    if nonblank_loops == ["- (none)"]:
        nonblank_loops = []
    for line in nonblank_loops:
        match = _LOOP_RE.match(line)
        if not match:
            issues.append(
                "OPEN LOOPS entry must be one line shaped "
                "'<ISO> | FOLD|QUEUE Q-id|DECLINE [resolves Q-id] | request "
                "— why: ...; resume: ...': "
                + line
            )
            continue
        stamp = match.group("stamp").strip()
        if _parse_iso8601(stamp) is None:
            issues.append(f"OPEN LOOPS entry has a non-ISO timestamp: {stamp}")
        classification = match.group("classification").strip()
        queue_match = _QUEUE_CLASS_RE.match(classification)
        resolution_match = _RESOLUTION_CLASS_RE.match(classification)
        if queue_match:
            queue_id = queue_match.group("id")
            loop = OpenLoop(line, "QUEUE", queue_id=queue_id)
            if queue_id in queue_by_id:
                issues.append(f"OPEN LOOPS reuses queue id {queue_id}")
            else:
                queue_by_id[queue_id] = loop
        elif resolution_match:
            queue_id = resolution_match.group("id")
            loop = OpenLoop(
                line,
                resolution_match.group("kind"),
                resolves=queue_id,
            )
            if queue_id not in queue_by_id:
                issues.append(
                    f"OPEN LOOPS resolves {queue_id} before that queue id is recorded"
                )
            resolved.add(queue_id)
        elif _TERMINAL_CLASS_RE.match(classification):
            loop = OpenLoop(line, classification)
        else:
            issues.append(f"OPEN LOOPS has invalid classification: {classification}")
            continue
        parsed_loops.append(loop)

    unresolved = tuple(
        loop for queue_id, loop in queue_by_id.items() if queue_id not in resolved
    )

    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stale: list[StaleClaim] = []
    for line_number, line in enumerate(lines, start=1):
        for match in _OBSERVED_AT_RE.finditer(line):
            value = match.group("stamp")
            observed = _parse_iso8601(value)
            if observed is None:
                issues.append(f"line {line_number} has invalid observed_at={value}")
            elif reference_now - observed > STALE_AFTER:
                stale.append(StaleClaim(line_number, value))
    stale.sort(
        key=lambda claim: _parse_iso8601(claim.observed_at) or reference_now
    )

    return ThreadCharter(
        path=path,
        ask=ask,
        open_loops=tuple(parsed_loops),
        done_when=tuple(done_lines),
        done_when_met=done_when_met,
        unresolved_queues=unresolved,
        stale_claims=tuple(stale),
        issues=tuple(issues),
    )


def load_active_charters(path: Path, now: datetime | None = None) -> list[ThreadCharter]:
    """Load active Markdown charters in stable name order; absence means none."""
    try:
        entries = sorted(path.glob("*.md"))
    except OSError:
        return []
    return [parse_charter(entry, now=now) for entry in entries]


def clip(text: str, limit: int) -> str:
    """Bound one projected field without hiding that truncation occurred."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 2)].rstrip() + " …"
