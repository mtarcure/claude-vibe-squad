#!/usr/bin/env python3
"""Format the daily raw brief into a reader-friendly newsletter.

Inputs:
- `_state/morning-briefs/<utc-date>.md`
- `_state/content-synthesis-<utc-date>.md`
- `_state/content-triage-<utc-date>.json`
- `_state/content-actions/*.md` with `status: pending`

Output:
- `_state/newsletter-<utc-date>.md`
- `_state/cleanup-logs/<utc-date>-newsletter-format.md` on failure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


@dataclass
class FormatInputs:
    date: str
    morning: str
    synthesis: str
    actions: list[str]
    triage_summary: str
    depth_count: int


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated for newsletter formatter]"


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_pending_actions(actions_dir: Path) -> list[str]:
    cards: list[str] = []
    if not actions_dir.exists():
        return cards
    for path in sorted(actions_dir.glob("*.md")):
        text = read_text(path)
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("status", "").lower() != "pending":
            continue
        card_id = frontmatter.get("id", path.stem)
        title = frontmatter.get("title", path.stem)
        rationale = frontmatter.get("rationale", "")
        proposed = frontmatter.get("proposed_action", "")
        cards.append(
            "\n".join(
                [
                    f"card_path: {path}",
                    f"id: {card_id}",
                    f"title: {title}",
                    f"rationale: {rationale}",
                    f"proposed_action: {proposed}",
                    "",
                    truncate(text, 1800),
                ]
            )
        )
    return cards


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("feed_metadata") or {}
    return {
        "tier": item.get("tier"),
        "depth_kind": item.get("depth_kind"),
        "lane": item.get("source_lane"),
        "source": item.get("source_name"),
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "score": item.get("relevance_score"),
        "reason": item.get("reason"),
    }


def load_triage_summary(path: Path) -> tuple[str, int]:
    if not path.exists():
        return "triage file missing", 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"triage unreadable: {exc}", 0

    items = data.get("items") or []
    summary = data.get("summary") or {}
    lanes: dict[str, int] = {}
    for item in items:
        lane = str(item.get("source_lane") or "unknown")
        lanes[lane] = lanes.get(lane, 0) + 1

    depth_items = [compact_item(i) for i in items if i.get("tier") == "depth"]
    skim_items = [compact_item(i) for i in items if i.get("tier") == "skim"][:12]
    dropped = [compact_item(i) for i in items if i.get("tier") == "drop"][:5]
    payload = {
        "total": summary.get("total_items", len(items)),
        "depth": summary.get("depth_count", len(depth_items)),
        "skim": summary.get("skim_count"),
        "drop": summary.get("drop_count"),
        "lanes": lanes,
        "depth_items": depth_items,
        "top_skim_items": skim_items,
        "dropped_examples": dropped,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2), int(summary.get("depth_count") or len(depth_items))


def load_inputs(args: argparse.Namespace) -> FormatInputs:
    date = args.date or utc_date()
    morning_path = Path(args.morning or STATE_DIR / "morning-briefs" / f"{date}.md")
    synthesis_path = Path(args.synthesis or STATE_DIR / f"content-synthesis-{date}.md")
    triage_path = Path(args.triage or STATE_DIR / f"content-triage-{date}.json")
    actions_dir = Path(args.actions_dir or STATE_DIR / "content-actions")

    triage_summary, depth_count = load_triage_summary(triage_path)
    return FormatInputs(
        date=date,
        morning=truncate(read_text(morning_path), 9000),
        synthesis=truncate(read_text(synthesis_path), 6000),
        actions=load_pending_actions(actions_dir),
        triage_summary=triage_summary,
        depth_count=depth_count,
    )


def no_signal(inputs: FormatInputs) -> bool:
    text = f"{inputs.morning}\n{inputs.synthesis}".lower()
    if inputs.actions:
        return False
    if inputs.depth_count > 0:
        return False
    # These mirror the legacy email skip markers. If the brief has operational
    # signal but no content depth picks, let Claude format it instead of
    # collapsing it to the deterministic no-signal stub.
    non_content_signal_markers = (
        "warnings / 1",
        "issues",
        "### warnings",
        "### issues",
        "processed blog artifacts",
        "podcast headline artifacts",
        "pending dream proposals",
        "cards for your decision",
        "active modes",
        "top n worth reading",
        "depth synthesis",
    )
    if any(marker in text for marker in non_content_signal_markers):
        return False
    return True


def build_no_signal_newsletter(inputs: FormatInputs) -> tuple[str, str]:
    subject = "No notable signal today"
    body = "## Lead\nNo notable signal today.\n\n## Top reads today\nNothing cleared the depth bar."
    return body, subject


def build_prompt(inputs: FormatInputs) -> str:
    pending_actions = "\n\n---\n\n".join(inputs.actions) if inputs.actions else "none"
    return f"""You are the daily-newsletter editor for Vibe Squad's content brief. Produce a single markdown digest under 16 KB suitable for email. Required structure in this order:

Use these exact markdown section headings, in this order:
1. ## Lead
   1-2 sentences: the single most important thing in today's brief, named explicitly. Picked from depth-tier items. If a content-action card is pending APPROVE, that takes precedence as the lead.
2. ## Decisions to make
   Only if pending action cards exist. List each card as a 2-3 line item with: title, why it matters, "Reply APPROVE or REJECT [card-id]". Skip section entirely if no cards.
3. ## Top reads today
   3-7 items from depth tier. Each: source-tagged title link, one-sentence operator-relevance summary written in your own voice, audio/article link when present.
4. ## Worth a skim
   5-12 items from highest-scoring skim items. One-line each, source-tagged. Group by lane if it adds clarity; flat list is also fine.
5. ## What's out
   1 sentence or skip if uninteresting. If anything notable was muted/dropped, mention by source/topic.
6. SUBJECT:
   Last block only. One line, <=80 chars, reflects today's lead story, no quotes, no "Daily Brief" prefix.

Constraints:
- Researcher-voice prose, not AI rhetorical tells. No "let me know if you have questions," no "I hope this helps," no triple-bullet emoji headers.
- Do not call tools. This is a text-generation-only formatting pass.
- Do not invent content. Every named item, link, or fact must come from the input.
- Preserve all URLs verbatim from the input.
- If input is empty or near-empty, produce a 2-line "no notable signal today" digest.

Input:
=== MORNING BRIEF ===
{inputs.morning or "(missing)"}

=== CONTENT SYNTHESIS ===
{inputs.synthesis or "(missing)"}

=== PENDING ACTION CARDS ===
{pending_actions}

=== TRIAGE SUMMARY ===
{inputs.triage_summary}
"""


def call_claude(prompt: str) -> tuple[int, str, str, float]:
    if not shutil.which(CLAUDE_BIN):
        return 127, "", f"{CLAUDE_BIN} not found", 0.0
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                CLAUDE_BIN,
                "-p",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--allowed-tools",
                "",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        return result.returncode, result.stdout or "", result.stderr or "", time.monotonic() - start
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\nclaude command timed out after 300s"
        return 124, stdout, stderr, time.monotonic() - start


def extract_subject(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        stripped = line.strip().strip("#` ")
        match = re.match(r"^(?:\*\*)?SUBJECT:(?:\*\*)?\s*(.*)$", stripped)
        if not match:
            continue
        tail = [l.strip() for l in lines[idx + 1 :] if l.strip()]
        inline_subject = match.group(1).strip().strip("*` ")
        if not inline_subject:
            if len(tail) != 1:
                continue
            subject = tail[0].strip("*` ")
            body = "\n".join(lines[:idx]).strip()
            if body and subject:
                return body, subject
            continue
        if tail:
            continue
        body = "\n".join(lines[:idx]).strip()
        if body:
            return body, inline_subject
    raise ValueError("Claude response missing parseable SUBJECT block")


def normalize_body(body: str) -> str:
    text = body.strip()
    lead_match = re.search(r"(?m)^## Lead\s*$", text)
    if lead_match:
        return text[lead_match.start() :].strip()

    split_match = re.search(r"(?m)^## Top reads today\s*$", text)
    if split_match:
        lead = text[: split_match.start()].strip()
        rest = text[split_match.start() :].lstrip()
        lead_lines = [
            line
            for line in lead.splitlines()
            if not re.match(r"^#(?!#)\s+", line.strip())
        ]
        lead = "\n".join(lead_lines).strip()
        if lead:
            return f"## Lead\n{lead}\n\n{rest}".strip()

    return f"## Lead\n{text}".strip()


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def clamp_subject(subject: str, limit: int = 80) -> str:
    subject = " ".join(subject.split())
    if len(subject) <= limit:
        return subject
    clipped = subject[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" .:-")


def render_newsletter(date: str, body: str, subject: str) -> str:
    subject = clamp_subject(subject)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return f"---\ndate: {date}\nsubject: {yaml_quote(subject)}\ngenerated_at: {generated_at}\n---\n\n{body.strip()}\n"


def write_failure_log(path: Path, date: str, reason: str, prompt: str, stdout: str = "", stderr: str = "", duration: float = 0.0) -> None:
    content = f"""# Newsletter Format - {date}

Run at: {datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
Status: failed
Reason: {reason}
Prompt length: {len(prompt)}
Stdout length: {len(stdout)}
Stderr length: {len(stderr)}
Duration seconds: {duration:.1f}

## Stdout first 1000

```
{stdout[:1000]}
```

## Stderr first 4000

```
{stderr[:4000]}
```
"""
    atomic_write(path, content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--morning")
    parser.add_argument("--synthesis")
    parser.add_argument("--triage")
    parser.add_argument("--actions-dir")
    parser.add_argument("--output")
    parser.add_argument("--log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = load_inputs(args)
    output_path = Path(args.output or STATE_DIR / f"newsletter-{inputs.date}.md")
    log_path = Path(args.log or STATE_DIR / "cleanup-logs" / f"{inputs.date}-newsletter-format.md")

    if no_signal(inputs):
        body, subject = build_no_signal_newsletter(inputs)
        atomic_write(output_path, render_newsletter(inputs.date, body, subject))
        print(f"Newsletter: {output_path}")
        return 0

    prompt = build_prompt(inputs)
    rc, stdout, stderr, duration = call_claude(prompt)
    if rc != 0:
        write_failure_log(log_path, inputs.date, f"claude exited {rc}", prompt, stdout, stderr, duration)
        print(f"newsletter-format failed - claude exited {rc}", file=sys.stderr)
        return 1

    try:
        body, subject = extract_subject(stdout)
    except ValueError as exc:
        write_failure_log(log_path, inputs.date, str(exc), prompt, stdout, stderr, duration)
        print(f"newsletter-format failed - {exc}", file=sys.stderr)
        return 1

    body = normalize_body(body)
    atomic_write(output_path, render_newsletter(inputs.date, body, subject))
    print(f"Newsletter: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
