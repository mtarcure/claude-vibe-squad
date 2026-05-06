#!/usr/bin/env python3
"""Build short cross-day continuity context for the daily newsletter.

Inputs:
- `_state/morning-briefs/<date>.md`
- `_state/content-synthesis-<date>.md`
- `_state/content-triage-<date>.json` depth-tier titles only

Output:
- `_state/cross-day-<utc-date>.md`
- `_state/cleanup-logs/<utc-date>-cross-day-context.md`
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MAX_INPUT_CHARS = 12_000


@dataclass
class DayBundle:
    date: str
    offset: int
    morning: str
    synthesis: str
    depth_titles: list[str]

    @property
    def exists(self) -> bool:
        return bool(self.morning.strip() or self.synthesis.strip() or self.depth_titles)


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_time_section() -> str:
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now_utc.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def read_text(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


def depth_titles(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []

    titles: list[str] = []
    for item in data.get("items") or []:
        if item.get("tier") != "depth":
            continue
        metadata = item.get("feed_metadata") or {}
        title = str(metadata.get("title") or "").strip()
        source = str(item.get("source_name") or item.get("source_lane") or "").strip()
        if title and source:
            titles.append(f"{title} — {source}")
        elif title:
            titles.append(title)
    return titles[:20]


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def load_day(date: datetime, offset: int) -> DayBundle:
    day = date.strftime("%Y-%m-%d")
    return DayBundle(
        date=day,
        offset=offset,
        morning=read_text(STATE_DIR / "morning-briefs" / f"{day}.md", 1800),
        synthesis=read_text(STATE_DIR / f"content-synthesis-{day}.md", 1800),
        depth_titles=depth_titles(STATE_DIR / f"content-triage-{day}.json"),
    )


def render_day(bundle: DayBundle, label: str) -> str:
    parts = [f"## {label} ({bundle.date})"]
    if bundle.depth_titles:
        parts.append("Depth titles:")
        parts.extend(f"- {title}" for title in bundle.depth_titles[:12])
    if bundle.synthesis.strip():
        parts.append("Synthesis excerpt:")
        parts.append(bundle.synthesis.strip())
    if bundle.morning.strip():
        parts.append("Morning excerpt:")
        parts.append(bundle.morning.strip())
    return "\n".join(parts)


def build_input(prior_days: list[DayBundle], today: DayBundle) -> str:
    prior = "\n\n".join(render_day(day, f"DAY-{day.offset}") for day in prior_days)
    current = render_day(today, "TODAY")
    combined = (
        "=== DAY-7 ... DAY-1 BRIEF + SYNTHESIS + DEPTH TITLES ===\n"
        f"{prior or '(none)'}\n\n"
        "=== TODAY: BRIEF + SYNTHESIS + DEPTH TITLES ===\n"
        f"{current}\n\n"
        "=== TODAY UTC DATE ===\n"
        f"{today.date}\n"
        f"{current_time_section()}\n"
    )
    if len(combined) <= MAX_INPUT_CHARS:
        return combined
    keep_prior = max(2000, MAX_INPUT_CHARS - len(current) - 400)
    prior = prior[-keep_prior:]
    combined = (
        "=== DAY-7 ... DAY-1 BRIEF + SYNTHESIS + DEPTH TITLES ===\n"
        "[older context truncated]\n"
        f"{prior}\n\n"
        "=== TODAY: BRIEF + SYNTHESIS + DEPTH TITLES ===\n"
        f"{current}\n\n"
        "=== TODAY UTC DATE ===\n"
        f"{today.date}\n"
        f"{current_time_section()}\n"
    )
    return combined[:MAX_INPUT_CHARS]


def build_prompt(input_bundle: str, is_sunday: bool, day_count: int) -> str:
    sunday_block = "\n\n[SUNDAY ONLY] ## Week themes\n(2-4 terse bullets. The arc across 7 days: what shifted, what consolidated, what got refuted. Cite specific items. Prioritize this section over long daily bullets.)"
    return f"""You are the cross-day continuity editor for Vibe Squad's daily newsletter. Read the last {day_count} days of brief artifacts below and produce a SHORT markdown digest under 1500 chars. Required structure:

## Ongoing themes
(0-3 bullets. Topics that appear 2+ days in the recent window. Cite specific past-day items by title. Skip section if nothing recurs.)

## Yesterday extended
(0-2 bullets. Items from yesterday's depth picks that today's depth picks build on, contradict, or close out. Skip if no continuity.)

## Today's new ground
(1 bullet. The single most novel angle in today's depth picks vs. the prior days. ALWAYS produce this section if today has any depth content.){sunday_block if is_sunday else ""}

Constraints:
- Researcher voice. No AI rhetorical tells. No "let me know if you have questions."
- Do not call tools. This is a text-generation-only continuity pass.
- Don't invent items. Only reference titles that appear in the input.
- Be conservative — skip a section before padding it.
- Output markdown only.

Sunday mode: {"on" if is_sunday else "off"}

Input:
{input_bundle}
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
            timeout=240,
            env=env,
        )
        return result.returncode, result.stdout or "", result.stderr or "", time.monotonic() - start
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\nclaude command timed out after 240s"
        return 124, stdout, stderr, time.monotonic() - start


def write_log(path: Path, date: str, status: str, rc: int | None, stderr: str, duration: float, output_len: int, note: str = "") -> None:
    content = f"""# Cross-Day Context - {date}

Run at: {datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
Status: {status}
Return code: {"" if rc is None else rc}
Duration seconds: {duration:.1f}
Output length: {output_len}
Note: {note}

## Stderr first 4000

```
{stderr[:4000]}
```
"""
    atomic_write(path, content)


def clamp_output(text: str) -> str:
    text = text.strip()
    if len(text) <= 1500:
        return text + ("\n" if text else "")
    clipped = text[:1500].rstrip()
    if "\n" in clipped:
        clipped = clipped.rsplit("\n", 1)[0].rstrip()
    lines = clipped.splitlines()
    while lines and lines[-1].strip().startswith("## "):
        lines.pop()
    clipped = "\n".join(lines).rstrip()
    return clipped + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="UTC date override for tests, YYYY-MM-DD.")
    parser.add_argument("--weekday", type=int, help="UTC weekday override for tests, 1=Mon..7=Sun.")
    parser.add_argument("--output")
    parser.add_argument("--log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = parse_date(args.date or utc_date())
    date = target_date.strftime("%Y-%m-%d")
    output_path = Path(args.output or STATE_DIR / f"cross-day-{date}.md")
    log_path = Path(args.log or STATE_DIR / "cleanup-logs" / f"{date}-cross-day-context.md")

    prior_days = [load_day(target_date - timedelta(days=offset), offset) for offset in range(7, 0, -1)]
    existing_prior = [day for day in prior_days if day.exists]
    today = load_day(target_date, 0)

    if len(existing_prior) < 3:
        content = "insufficient history; skipping\n"
        atomic_write(output_path, content)
        write_log(log_path, date, "skipped", None, "", 0.0, len(content), f"prior_days={len(existing_prior)}")
        print(f"Cross-day context: {output_path} (insufficient history)")
        return 0

    is_sunday = (args.weekday if args.weekday else target_date.isoweekday()) == 7
    input_bundle = build_input(existing_prior, today)
    prompt = build_prompt(input_bundle, is_sunday, len(existing_prior) + 1)
    rc, stdout, stderr, duration = call_claude(prompt)
    if rc != 0:
        atomic_write(output_path, "")
        write_log(log_path, date, "failed", rc, stderr, duration, 0, "wrote empty fallback stub")
        print(f"cross-day-context failed - claude exited {rc}", file=sys.stderr)
        return 0

    output = clamp_output(stdout)
    atomic_write(output_path, output)
    write_log(log_path, date, "ok", rc, stderr, duration, len(output), f"sunday={str(is_sunday).lower()}")
    print(f"Cross-day context: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
