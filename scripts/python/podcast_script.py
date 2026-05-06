#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Generate a conversational daily podcast script for newsletter TTS.

Input:
- `_state/newsletter-<utc-date>.md` trimmed Telegram digest
- `_state/blog-summaries/<utc-date>-*.md` analysis_json frontmatter

Output:
- `_state/podcast-script-<utc-date>.md`
- `_state/cleanup-logs/<utc-date>-podcast-script.md`
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
DEPTH_CONTEXT_LIMIT = 8_000


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_time_section() -> str:
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
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


def strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end():]


def parse_analysis(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        try:
            value = json.loads(raw.replace('\\"', '"'))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def compact_analysis(path: Path) -> dict[str, Any] | None:
    text = read_text(path)
    meta, _ = strip_frontmatter(text)
    analysis = parse_analysis(meta.get("analysis_json", ""))
    if not analysis:
        return None
    relevance = analysis.get("relevance_to_me") if isinstance(analysis.get("relevance_to_me"), dict) else {}

    def short(value: Any, limit: int = 900) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."

    def short_list(value: Any, limit: int = 360, max_items: int = 3) -> list[str]:
        if not isinstance(value, list):
            value = [value] if value else []
        out: list[str] = []
        for item in value:
            item_text = short(item, limit)
            if item_text and item_text.lower() not in {"none", "(none)", "none observed"}:
                out.append(item_text)
            if len(out) >= max_items:
                break
        return out

    return {
        "title": meta.get("title") or path.stem,
        "source": meta.get("feed") or meta.get("source_lane") or "source",
        "url": meta.get("url"),
        "time_horizon": meta.get("time_horizon") or analysis.get("time_horizon"),
        "core_finding": short(analysis.get("core_finding"), 1_000),
        "why_for_you": short_list(relevance.get("current_work_connections"), 380, 2),
        "why_now": short(relevance.get("why_now"), 360),
        "what_it_enables": short_list(analysis.get("what_it_enables"), 320, 2),
        "immediate_fixes": short_list(analysis.get("immediate_fixes"), 320, 2),
    }


def load_depth_context(date: str) -> str:
    items: list[dict[str, Any]] = []
    for path in sorted((STATE_DIR / "blog-summaries").glob(f"{date}-*.md")):
        item = compact_analysis(path)
        if item:
            items.append(item)
        if len(items) >= 8:
            break
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    if len(payload) <= DEPTH_CONTEXT_LIMIT:
        return payload
    return payload[:DEPTH_CONTEXT_LIMIT].rstrip() + "\n[truncated for podcast-script prompt]"


def build_prompt(newsletter: str, depth_context: str) -> str:
    return f"""You are writing a 4-5 minute podcast script for a daily AI/agent-infrastructure brief. The listener is on transit (phone, AirPods, distracted attention). Write FOR THE EAR, not the eye.

Constraints:
- Target output: 5,000-6,500 chars (approximately 4-5 min spoken at about 180 WPM via ElevenLabs).
- Hard maximum output: 7,500 chars. End naturally; do not run long and rely on truncation.
- Conversational tone, like a podcast cohost talking to one person. NOT a news broadcast or formal briefing. NOT a TTS of markdown.
- Open with a brief greeting that acknowledges the day. Close with a brief sign-off.
- Cover the top 3 items from "Worth your time today" with about 1 minute each: what it is, why it matters to them, and the one thing they should think about.
- If there's a system-improvement proposal with score >=7, mention it briefly as "something to think about doing."
- DO NOT enumerate every item. DO NOT list URLs (mention sources by name only). DO NOT read section headings aloud.
- DO NOT use markdown formatting in the output. Plain prose only. No bullets, no asterisks, no code fences.
- Use natural speech patterns: contractions ("we're", "don't"), occasional "and", brief asides.
- DO NOT include sponsor reads, calls to subscribe, or any marketing fluff.
- If today's signal is thin (no depth items, no improvements), produce a short 60-second "quiet day" script acknowledging that and pointing at one thing worth catching up on.

Input materials:
=== TRIMMED NEWSLETTER ===
{newsletter}

=== TODAY'S DEPTH ITEMS (full multi-dim analysis) ===
{depth_context}

{current_time_section()}

Output ONLY the script body. No preface, no metadata, no labels.
"""


def call_claude(prompt: str) -> tuple[int, str, str, float]:
    if not shutil.which(CLAUDE_BIN):
        return 127, "", f"{CLAUDE_BIN} not found", 0.0
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    start = time.monotonic()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--output-format", "text", "--no-session-persistence", "--allowed-tools", ""],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        return result.returncode, result.stdout or "", result.stderr or "", time.monotonic() - start
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", (exc.stderr or "") + "\nclaude command timed out after 300s", time.monotonic() - start


def clean_script(raw: str) -> str:
    text = (raw or "").split("To resume this session:")[0].strip()
    text = re.sub(r"^```(?:text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fallback_script(newsletter: str) -> str:
    _, body = strip_frontmatter(newsletter)
    body = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", body)
    body = re.sub(r"(?m)^#{1,6}\s*", "", body)
    body = re.sub(r"[*_`]+", "", body)
    body = re.sub(r"\n+", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return (
        "Good morning. Today is a lighter, tighter version of the Vibe Squad brief. "
        "The main thing to carry with you is this: "
        f"{body[:1800].rstrip()} "
        "That is the whole point of the new format: keep the phone brief short, and save the deeper connective tissue for the archive. "
        "That's it for this morning. Keep the archive nearby if you want the full trail later."
    )


def render_log(date: str, status: str, **kwargs: Any) -> str:
    lines = [f"# Podcast Script - {date}", "", current_time_section(), "", f"Status: {status}"]
    for key, value in kwargs.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    args = parser.parse_args()
    date = args.date or utc_date()
    newsletter_path = STATE_DIR / f"newsletter-{date}.md"
    output_path = STATE_DIR / f"podcast-script-{date}.md"
    log_path = STATE_DIR / "cleanup-logs" / f"{date}-podcast-script.md"

    newsletter = read_text(newsletter_path)
    if not newsletter.strip():
        atomic_write(log_path, render_log(date, "skipped", reason=f"missing newsletter {newsletter_path}"))
        print(f"Podcast script skipped: missing {newsletter_path}")
        return 0

    depth_context = load_depth_context(date)
    prompt = build_prompt(newsletter, depth_context)
    rc, stdout, stderr, duration = call_claude(prompt)
    if rc == 0:
        script = clean_script(stdout)
    else:
        script = fallback_script(newsletter)

    if not script:
        script = fallback_script(newsletter)

    atomic_write(output_path, script + "\n")
    atomic_write(log_path, render_log(
        date,
        "ok" if rc == 0 else "fallback",
        output_path=output_path,
        script_chars=len(script),
        depth_context_chars=len(depth_context),
        returncode=rc,
        subprocess_duration_s=f"{duration:.1f}",
        stderr=(stderr or "")[:2000],
    ))
    print(f"Podcast script: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
