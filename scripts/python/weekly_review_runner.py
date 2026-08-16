#!/usr/bin/env python3
"""Generate weekly review markdown from handoffs + board response envelopes.

Runs unattended on a Sunday launchd schedule, which is why the empty-evidence
guard in `main` matters more than anything else here: asking a model for six
named sections over an empty corpus does not produce six empty sections, it
produces six invented ones. This script did exactly that until 2026-08-09 --
both collectors were wired to paths that never yielded a file, so it POSTed a
52-byte payload and wrote a review describing a cloud migration, a Redis
incident and four engineers who do not exist.

The guard is therefore structural rather than advisory. Evidence is collected as
a list of documents and counted as documents; the request and the file write are
reachable only past that count. Repointing the collectors at nothing again would
produce silence, not fiction.
"""
import asyncio
import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from repo_root import resolve_vault_root

REPO = resolve_vault_root()

SUMMARIZE_URL = "http://127.0.0.1:9876/summarize"

# The floor below which a week counts as having produced nothing. Measured
# against the live mailboxes on 2026-08-09: the smallest real response envelope
# in that week was 304 bytes across 369 files, so a single genuine document
# always clears 200 characters, while a glob that matched only empty or
# whitespace files never does.
MIN_EVIDENCE_CHARS = 200

# /summarize proxies to Gemini Flash under a 30-second timeout (daemon/
# flash_summarizer.py), so the prompt is held near 50k tokens rather than at the
# model's context ceiling. A live week is far larger than that -- 2.6 MB raw
# across those 369 envelopes -- so both bounds bite in normal operation.
#
# The per-document cap sits just above the median envelope (1,342 bytes) and
# envelopes carry their frontmatter and summary paragraph first, so head
# truncation keeps the meaningful part of the long tail. MAX_EVIDENCE_CHARS
# bounds the collected documents; the short manifest header is added above them,
# so the assembled prompt runs a few hundred characters over.
MAX_DOC_CHARS = 1_500
MAX_EVIDENCE_CHARS = 200_000

# Handoffs are named "<YYYY-MM-DD>-<slug>.md".
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")

INSTRUCTIONS = (
    "Write a weekly engineering review from the material below. That material is"
    " the complete record available for this week.\n"
    "\n"
    "Rules, in order of importance:\n"
    "1. Use ONLY the supplied material. Do not introduce projects, people,"
    " systems, tools, incidents, metrics or dates that do not appear in it.\n"
    "2. If a section has no supporting evidence, write exactly 'No evidence this"
    " week.' under it. Do not fill it with plausible content.\n"
    "3. Attribute every claim to the document it came from, by that document's"
    " heading.\n"
    "4. Some documents may be truncated or omitted for size, and the header says"
    " so. Report that as a limit on what you could see; do not infer what they"
    " contained.\n"
    "\n"
    "Sections:\n"
    "- Surprising moments\n"
    "- Underused required tools\n"
    "- Overused preferred tools (candidates for required)\n"
    "- Specialist patches accumulated this week\n"
    "- Handoff patterns worth codifying\n"
    "- Projects touched this week\n"
)


@dataclass(frozen=True)
class Evidence:
    """One collected document: where it came from, when, and what it says."""

    source: str
    date: datetime.date
    text: str


def _document_date(path: Path) -> datetime.date:
    """The day a document belongs to: its filename prefix, else its mtime.

    Both collected trees are gitignored (.gitignore lines 26 and 93), so git
    never rewrites their mtimes the way a checkout would, and mtime is a real
    signal for the files that carry no date in their name.
    """
    match = DATE_PREFIX.match(path.name)
    if match:
        try:
            return datetime.date.fromisoformat(match.group(1))
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).date()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


async def collect_handoffs(
    week_start: datetime.date, week_end: datetime.date
) -> list[Evidence]:
    """Handoff notes written this week.

    The previous glob asked for `docs/handoffs/<YYYY-MM-DD>.md`. Handoffs are
    named `<YYYY-MM-DD>-<slug>.md`, so it matched nothing in the directory's
    entire history -- the one file there is `2026-07-12-tmux-ux-polish-handoff.md`.
    """
    handoffs = REPO / "docs" / "handoffs"
    if not handoffs.is_dir():
        return []
    collected = []
    for path in sorted(handoffs.glob("*.md")):
        day = _document_date(path)
        if week_start <= day <= week_end:
            collected.append(Evidence(f"handoff: {path.name}", day, _read(path)))
    return collected


async def collect_manifests(
    week_start: datetime.date, week_end: datetime.date
) -> list[Evidence]:
    """Board response envelopes written this week.

    The previous source was `daemon/state/outbox`, which exists but has never
    held a `.md` file. The live mailboxes are `departments/<namespace>/outbox`.
    """
    outboxes = REPO / "departments"
    if not outboxes.is_dir():
        return []
    collected = []
    for path in sorted(outboxes.glob("*/outbox/*.md")):
        day = _document_date(path)
        if week_start <= day <= week_end:
            namespace = path.parent.parent.name
            collected.append(
                Evidence(f"{namespace}: {path.name}", day, _read(path))
            )
    return collected


def evidence_chars(collected: list[Evidence]) -> int:
    """Characters of actual content, ignoring whitespace-only documents."""
    return sum(len(item.text.strip()) for item in collected)


def build_payload(collected: list[Evidence], week_label: str) -> str:
    """Render the evidence newest-first, inside the size budget.

    Everything dropped is stated in the payload. A summariser told what it could
    not see does not have to guess at it, and rule 4 of INSTRUCTIONS asks it to
    report the gap rather than fill it.
    """
    blocks: list[str] = []
    used = 0
    omitted = 0
    truncated = 0

    for item in sorted(collected, key=lambda e: (e.date, e.source), reverse=True):
        body = item.text.strip()
        if not body:
            continue
        if len(body) > MAX_DOC_CHARS:
            body = (
                body[:MAX_DOC_CHARS]
                + f"\n\n[truncated: {len(body)} characters in the full document]"
            )
            truncated += 1
        block = f"## {item.source} ({item.date.isoformat()})\n\n{body}\n"
        if blocks and used + len(block) > MAX_EVIDENCE_CHARS:
            omitted += 1
            continue
        blocks.append(block)
        used += len(block)

    header = [f"# Evidence for {week_label}", "", f"{len(blocks)} documents included."]
    if truncated:
        header.append(f"{truncated} were truncated to {MAX_DOC_CHARS} characters.")
    if omitted:
        header.append(
            f"{omitted} further documents were omitted entirely for size and are "
            "not shown below."
        )
    return "\n".join(header) + "\n\n" + "\n---\n\n".join(blocks)


async def summarize(payload: str, token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SUMMARIZE_URL,
            json={"text": payload, "instructions": INSTRUCTIONS},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["summary"]


async def main() -> int:
    """Collect the week's evidence and, only if there is any, write the review."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    year, week, _ = today.isocalendar()
    week_label = f"{year}-W{week:02d}"

    collected = await collect_handoffs(week_start, week_end)
    collected += await collect_manifests(week_start, week_end)

    # The guard. The client, the request and the file write below are reachable
    # only through here, so a week with no evidence cannot produce a document --
    # including when a collector above silently stops matching anything.
    total = evidence_chars(collected)
    if total < MIN_EVIDENCE_CHARS:
        print(
            f"no review for {week_label}: collected {len(collected)} documents "
            f"and {total} characters of evidence, below the {MIN_EVIDENCE_CHARS} "
            f"character floor. Not calling /summarize and not writing a file."
        )
        return 0

    # Checked after the guard on purpose: a quiet week must exit 0, not fail the
    # scheduled job over a token it was never going to use.
    token = os.environ.get("VIBESQUAD_DAEMON_TOKEN")
    if not token:
        raise RuntimeError("VIBESQUAD_DAEMON_TOKEN not set")

    summary = await summarize(build_payload(collected, week_label), token)

    out_dir = REPO / "docs" / "reviews" / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{week_label}.md"
    out.write_text(
        f"# Week {week_label}\n\n"
        f"Generated from {len(collected)} documents "
        f"({week_start.isoformat()} to {week_end.isoformat()}).\n\n"
        f"{summary}\n"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
