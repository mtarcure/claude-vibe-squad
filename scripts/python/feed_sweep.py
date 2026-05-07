#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "feedparser>=6.0",
#     "pyyaml>=6.0",
#     "httpx>=0.28",
# ]
# ///
"""Feed sweep for Claude-Vibe-Squad.

Reads `_state/feed-config.yaml`, fetches each RSS feed, dedups against
`_state/processed-ids.json`, tags cadence (on/off/skipped), and writes
`_state/new-items-<date>.json` for content-processing.sh to consume.

HTML-scrape feeds are fetched from configured index pages via `scrape_html_index`.

Atomic writes throughout: temp + rename.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import yaml

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
CONFIG_PATH = STATE_DIR / "feed-config.yaml"
PROCESSED_IDS_PATH = STATE_DIR / "processed-ids.json"
LOG_DIR = STATE_DIR / "cleanup-logs"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOG_PATH = LOG_DIR / f"{DATE}-feed-sweep.md"
TWITTER_LOG_PATH = LOG_DIR / f"{DATE}-twitter-search.md"
YOUTUBE_LOG_PATH = LOG_DIR / f"{DATE}-youtube-sweep.md"
NEW_ITEMS_PATH = STATE_DIR / f"new-items-{DATE}.json"
OPERATOR_INTERESTS_PATH = STATE_DIR / "operator-interests.yaml"
MANUAL_QUEUE_PATH = STATE_DIR / "manual-queue.txt"
MANUAL_QUEUE_DONE_PATH = STATE_DIR / "manual-queue-done.txt"
MANUAL_QUEUE_FAILED_PATH = STATE_DIR / "manual-queue-failed.txt"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
XAI_TOOL = "mcp__plugin_chrono-research-arsenal_chrono-research-arsenal__xai_search"
PERPLEXITY_TOOL = "mcp__plugin_chrono-research-arsenal_perplexity__perplexity_search_web"
ARXIV_API_LAST_FETCH_MONO: float | None = None

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
YOUTUBE_LOG_ENTRIES: list[dict[str, Any]] = []
FEED_SWEEP_EXTRA_LOG_LINES: list[str] = []


@dataclass
class NewItem:
    feed_name: str
    feed_type: str  # podcast | rss-text | html-scrape | youtube-channel
    item_id: str
    title: str
    url: str
    published_iso: str
    audio_url: str | None
    summary_short: str
    cadence_tag: str  # on-schedule | off-schedule | unknown
    processor: str
    output_dir: str
    source_type: str | None = None
    source_lane: str | None = None


@dataclass
class FeedReport:
    name: str
    type: str
    fetched: bool
    new_count: int
    skipped: int
    error: str | None = None
    cadence_notes: list[str] = field(default_factory=list)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(content)
    try:
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    tmp.rename(path)


def append_atomic(path: Path, line: str) -> None:
    existing = path.read_text() if path.exists() else ""
    atomic_write(path, existing + line)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        sys.exit(f"feed-config.yaml not found at {CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text())


def load_operator_interests() -> dict[str, Any]:
    if not OPERATOR_INTERESTS_PATH.exists():
        return {}
    try:
        return yaml.safe_load(OPERATOR_INTERESTS_PATH.read_text()) or {}
    except yaml.YAMLError:
        return {}


def load_processed_ids() -> dict[str, list[str]]:
    if not PROCESSED_IDS_PATH.exists():
        return {}
    try:
        return json.loads(PROCESSED_IDS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_processed_ids(ids: dict[str, list[str]]) -> None:
    atomic_write(PROCESSED_IDS_PATH, json.dumps(ids, indent=2, sort_keys=True))


def strip_json_fence(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def clean_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def parse_youtube_published(video: dict[str, Any]) -> str:
    upload_date = str(video.get("upload_date") or "").strip()
    if re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}T00:00:00+00:00"
    timestamp = video.get("timestamp") or video.get("release_timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    return ""


def youtube_watch_url(video: dict[str, Any]) -> str | None:
    webpage_url = str(video.get("webpage_url") or "").strip()
    if webpage_url.startswith("http"):
        return webpage_url.split("&list=")[0]
    video_id = str(video.get("id") or "").strip()
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    url = str(video.get("url") or "").strip()
    if url.startswith("http"):
        return url
    if url:
        return f"https://www.youtube.com/watch?v={url}"
    return None


def fetch_youtube_video_details(video_url: str, timeout: float = 60.0) -> tuple[dict[str, Any], str | None]:
    if not shutil.which("yt-dlp"):
        return {}, "yt-dlp not found"
    cmd = ["yt-dlp", "--no-warnings", "--dump-json", "--skip-download", video_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {}, "detail fetch timed out"
    if result.returncode != 0:
        return {}, f"detail fetch exited {result.returncode}: {(result.stderr or '')[:300]}"
    line = next((line.strip() for line in (result.stdout or "").splitlines() if line.strip()), "")
    if not line:
        return {}, "detail fetch returned no JSON"
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        return {}, f"detail fetch malformed JSON: {exc}"
    return (payload if isinstance(payload, dict) else {}), None


def twitter_side_log(entries: list[dict[str, Any]]) -> str:
    lines = [
        f"# Twitter Search — {DATE}",
        "",
        f"Run at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Per-person",
    ]
    for entry in entries:
        lines.append(
            f"- **{entry.get('name')}** (@{entry.get('handle')}): "
            f"transport={entry.get('transport', 'none')}, results={entry.get('result_count', 0)}, "
            f"new={entry.get('new_count', 0)}, skipped={entry.get('skipped', 0)}"
        )
        if entry.get("error"):
            lines.append(f"  - error: {entry['error']}")
        if entry.get("returncode") is not None:
            lines.append(
                f"  - claude: rc={entry.get('returncode')}, duration={entry.get('duration_s', 0):.1f}s, "
                f"stdout={entry.get('stdout_len', 0)}, stderr={entry.get('stderr_len', 0)}"
            )
        if entry.get("stderr"):
            lines.append("  - stderr first 1000:")
            lines.append("")
            lines.append("```")
            lines.append(str(entry["stderr"])[:1000])
            lines.append("```")
    return "\n".join(lines) + "\n"


def youtube_side_log(entries: list[dict[str, Any]]) -> str:
    lines = [
        f"# YouTube Sweep — {DATE}",
        "",
        f"Run at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Per-channel",
    ]
    for entry in entries:
        lines.append(
            f"- **{entry.get('name')}**: status={entry.get('status', 'unknown')}, "
            f"videos={entry.get('video_count', 0)}, new={entry.get('new_count', 0)}, "
            f"skipped={entry.get('skipped', 0)}"
        )
        lines.append(f"  - channel: {entry.get('channel_url', '')}")
        if entry.get("returncode") is not None:
            lines.append(
                f"  - yt-dlp: rc={entry.get('returncode')}, duration={entry.get('duration_s', 0):.1f}s, "
                f"stdout={entry.get('stdout_len', 0)}, stderr={entry.get('stderr_len', 0)}"
            )
        if entry.get("error"):
            lines.append(f"  - error: {entry['error']}")
        for detail_error in entry.get("detail_errors", [])[:10]:
            lines.append(f"  - detail: {detail_error}")
        if entry.get("stderr"):
            lines.append("  - stderr first 1000:")
            lines.append("")
            lines.append("```")
            lines.append(str(entry["stderr"])[:1000])
            lines.append("```")
    return "\n".join(lines) + "\n"


def item_dict(item: NewItem) -> dict[str, Any]:
    data = asdict(item)
    if data.get("source_type") is None:
        data.pop("source_type", None)
    if data.get("source_lane") is None:
        data.pop("source_lane", None)
    return data


def parse_published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        ts = entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if ts:
            return datetime(*ts[:6], tzinfo=timezone.utc)
    return None


def find_audio_url(entry: Any) -> str | None:
    enclosures = getattr(entry, "enclosures", None) or (entry.get("enclosures") if isinstance(entry, dict) else None)
    if not enclosures:
        return None
    for enc in enclosures:
        href = enc.get("href") or enc.get("url")
        type_ = (enc.get("type") or "").lower()
        if href and ("audio" in type_ or href.endswith(".mp3") or href.endswith(".m4a")):
            return href
    return None


def short_summary(entry: Any, max_chars: int = 400) -> str:
    raw = ""
    content_list = entry.get("content") if isinstance(entry, dict) else getattr(entry, "content", None)
    if content_list:
        first = content_list[0] if len(content_list) > 0 else None
        if first:
            raw = first.get("value") if isinstance(first, dict) else getattr(first, "value", "") or ""
    if not raw:
        if isinstance(entry, dict):
            raw = entry.get("summary") or entry.get("description") or ""
        else:
            raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
    text = re.sub(r"<[^>]+>", "", raw)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


def cadence_tag(feed_cfg: dict[str, Any], published_at: datetime | None) -> tuple[str, str | None]:
    expected = (feed_cfg.get("expected_cadence") or "").lower()
    if expected in ("", "irregular"):
        return "unknown", None
    if not published_at:
        return "unknown", "no published timestamp"
    expected_day = (feed_cfg.get("expected_day") or "any").lower()
    actual_day = DAYS[published_at.weekday()]
    if expected == "weekly":
        if expected_day == "any" or actual_day == expected_day:
            return "on-schedule", None
        return "off-schedule", f"expected {expected_day}, published {actual_day}"
    if expected == "daily":
        expected_days = feed_cfg.get("expected_days") or list(DAYS[:5])
        expected_days = [d.lower() for d in expected_days]
        if actual_day[:3] in [d[:3] for d in expected_days] or actual_day in expected_days:
            return "on-schedule", None
        return "off-schedule", f"expected {expected_days}, published {actual_day}"
    return "unknown", None


def fetch_feed(url: str, timeout: float = 30.0) -> Any:
    """Use httpx for fetching, then feedparser for parsing.

    feedparser's built-in fetcher uses urllib which can hang; httpx gives us
    explicit timeouts and better TLS handling.
    """
    headers = {"User-Agent": "Claude-Vibe-Squad-feed-sweep/0.1"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return feedparser.parse(resp.content)


def fetch_arxiv_api(category: str, max_results: int, start: int = 0, timeout: float = 30.0) -> Any:
    global ARXIV_API_LAST_FETCH_MONO
    if ARXIV_API_LAST_FETCH_MONO is not None:
        elapsed = time.monotonic() - ARXIV_API_LAST_FETCH_MONO
        if elapsed < 3.0:
            time.sleep(3.0 - elapsed)
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
        "start": str(start),
    }
    headers = {"User-Agent": "Claude-Vibe-Squad-feed-sweep/0.1"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get("http://export.arxiv.org/api/query", params=params)
        resp.raise_for_status()
        ARXIV_API_LAST_FETCH_MONO = time.monotonic()
        return feedparser.parse(resp.content)


def fetch_arxiv_by_id(arxiv_id: str, timeout: float = 30.0) -> Any:
    headers = {"User-Agent": "Claude-Vibe-Squad-feed-sweep/0.1"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get("http://export.arxiv.org/api/query", params={"id_list": arxiv_id})
        resp.raise_for_status()
        return feedparser.parse(resp.content)


def log_extra(line: str) -> None:
    FEED_SWEEP_EXTRA_LOG_LINES.append(line)


# Browser-mimicking UA for vendor sites that block generic UAs.
HTML_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape_html_index(url: str, link_pattern: str, timeout: float = 30.0) -> list[tuple[str, str]]:
    """Fetch an index page, return (article_url, title) pairs matching link_pattern.

    `link_pattern` is a regex (with one capture group for the slug). Title is
    extracted from the link's anchor text or surrounding heading.
    """
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=HTML_SCRAPE_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    base = re.match(r"https?://[^/]+", url).group(0)
    pattern_re = re.compile(link_pattern)
    # Match either <a href="..." ...>TEXT</a> or naked anchors with various
    # attribute orders. Capture href + inner text.
    anchor_re = re.compile(
        r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    h_tag_re = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.IGNORECASE | re.DOTALL)
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for match in anchor_re.finditer(html):
        href, inner = match.group(1), match.group(2)
        if not pattern_re.search(href):
            continue
        full_url = href if href.startswith("http") else base + href
        full_url = full_url.split("#")[0].rstrip("/")
        if full_url in seen:
            continue
        seen.add(full_url)
        # Prefer the link's inner h-tag (clean title); fall back to full text.
        title = ""
        h_match = h_tag_re.search(inner)
        if h_match:
            title = re.sub(r"<[^>]+>", " ", h_match.group(1))
            title = re.sub(r"\s+", " ", title).strip()
        if not title:
            title = re.sub(r"<[^>]+>", " ", inner)
            title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 5:
            continue
        found.append((full_url, title))
    return found[:25]  # cap to 25 newest as with RSS


def followed_people_needing_adapter() -> list[dict[str, str]]:
    interests = load_operator_interests()
    people: list[dict[str, str]] = []
    for person in interests.get("followed_people", []) or []:
        if str(person.get("source", "")).strip() != "needs_adapter":
            continue
        name = str(person.get("name", "")).strip()
        handle = str(person.get("handle", "")).lstrip("@").strip()
        if name and handle:
            people.append({"name": name, "handle": handle})
    return people


def twitter_search_prompt(name: str, handle: str) -> str:
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    return f"""You are a JSON-only search adapter for Vibe Squad feed-sweep.

Goal: find recent X/Twitter posts from @{handle} ({name}) from the past 7 days.

Use tools exactly this way:
1. First call {XAI_TOOL} with query: "recent posts by @{handle} on X / Twitter, past 7 days".
2. If xAI returns no useful results or errors, call {PERPLEXITY_TOOL} with query: "site:x.com from:{handle} after:{seven_days_ago}" and recency "week".
3. Do not call any other tools.

Return JSON only, no prose, with this schema:
{{
  "transport": "xai" | "perplexity-fallback" | "none",
  "error": null | "short reason",
  "results": [
    {{
      "title": "short title",
      "url": "https://x.com/... or source URL",
      "snippet": "short snippet/content",
      "published": "ISO date if available, else empty string"
    }}
  ]
}}

Rules:
- Include at most 5 results.
- Prefer direct x.com tweet/status URLs.
- If results are not actually by @{handle}, omit them.
- Preserve URLs verbatim.
"""


def call_twitter_search(name: str, handle: str, timeout: float = 120.0) -> tuple[dict[str, Any], dict[str, Any]]:
    log_entry: dict[str, Any] = {
        "name": name,
        "handle": handle,
        "transport": "none",
        "result_count": 0,
        "new_count": 0,
        "skipped": 0,
    }
    if not shutil.which(CLAUDE_BIN):
        log_entry["error"] = f"{CLAUDE_BIN} not found"
        return {"transport": "none", "error": log_entry["error"], "results": []}, log_entry

    prompt = twitter_search_prompt(name, handle)
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--output-format",
        "text",
        "--no-session-persistence",
        "--allowed-tools",
        f"{XAI_TOOL},{PERPLEXITY_TOOL}",
    ]
    start = time.monotonic()
    try:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
        log_entry.update({
            "returncode": result.returncode,
            "duration_s": time.monotonic() - start,
            "stdout_len": len(result.stdout or ""),
            "stderr_len": len(result.stderr or ""),
            "stderr": result.stderr or "",
        })
    except subprocess.TimeoutExpired as exc:
        log_entry.update({
            "returncode": 124,
            "duration_s": time.monotonic() - start,
            "stdout_len": len(exc.stdout or ""),
            "stderr_len": len(exc.stderr or ""),
            "stderr": (exc.stderr or "") + f"\nclaude command timed out after {timeout}s",
            "error": "timeout",
        })
        return {"transport": "none", "error": "timeout", "results": []}, log_entry

    if result.returncode != 0:
        log_entry["error"] = f"claude exited {result.returncode}"
        return {"transport": "none", "error": log_entry["error"], "results": []}, log_entry

    try:
        payload = json.loads(strip_json_fence(result.stdout or ""))
    except json.JSONDecodeError as exc:
        log_entry["error"] = f"malformed-json: {exc}"
        return {"transport": "none", "error": log_entry["error"], "results": []}, log_entry

    if not isinstance(payload, dict):
        log_entry["error"] = "malformed-json: root not object"
        return {"transport": "none", "error": log_entry["error"], "results": []}, log_entry

    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    payload["results"] = results[:5]
    payload["transport"] = payload.get("transport") or ("none" if not payload["results"] else "xai")
    payload["error"] = payload.get("error")
    log_entry["transport"] = payload["transport"]
    log_entry["result_count"] = len(payload["results"])
    if payload.get("error"):
        log_entry["error"] = str(payload["error"])
    return payload, log_entry


def sweep_twitter_via_search(feed_cfg: dict[str, Any], processed_ids: dict[str, list[str]]) -> tuple[FeedReport, list[NewItem]]:
    name = feed_cfg["name"]
    feed_type = feed_cfg.get("type", "twitter-via-search")
    report = FeedReport(name=name, type=feed_type, fetched=True, new_count=0, skipped=0)
    new_items: list[NewItem] = []
    log_entries: list[dict[str, Any]] = []
    today_iso = datetime.now(timezone.utc).date().isoformat()

    people = followed_people_needing_adapter()
    if not people:
        report.error = "no followed_people with source=needs_adapter"
        atomic_write(TWITTER_LOG_PATH, twitter_side_log(log_entries))
        return report, new_items

    for person in people:
        person_feed = f"Twitter — {person['name']}"
        payload, log_entry = call_twitter_search(person["name"], person["handle"])
        seen_ids = set(processed_ids.get(person_feed, []))
        feed_seen: list[str] = []
        for result in payload.get("results", [])[:5]:
            if not isinstance(result, dict):
                continue
            url = clean_text(result.get("url"), 500)
            if not url:
                continue
            feed_seen.append(url)
            if url in seen_ids:
                report.skipped += 1
                log_entry["skipped"] = log_entry.get("skipped", 0) + 1
                continue
            title = clean_text(result.get("title") or result.get("snippet") or url, 100)
            summary = clean_text(result.get("snippet") or result.get("title") or "", 500)
            published = clean_text(result.get("published") or "", 80) or today_iso
            new_items.append(NewItem(
                feed_name=person_feed,
                feed_type=feed_type,
                item_id=url,
                title=title or url,
                url=url,
                published_iso=published,
                audio_url=None,
                summary_short=summary,
                cadence_tag="unknown",
                processor=feed_cfg.get("processor", "kimi-summarize"),
                output_dir=feed_cfg.get("output_dir", "_state/blog-summaries/"),
                source_type="twitter-via-search",
                source_lane=feed_cfg.get("lane"),
            ))
            report.new_count += 1
            log_entry["new_count"] = log_entry.get("new_count", 0) + 1
        processed_ids[person_feed] = list(dict.fromkeys((feed_seen + list(seen_ids))[:200]))
        if payload.get("error") and not payload.get("results"):
            report.cadence_notes.append(f"{person['name']}: {payload['error']}")
        log_entries.append(log_entry)

    atomic_write(TWITTER_LOG_PATH, twitter_side_log(log_entries))
    return report, new_items


def fetch_youtube_channel(channel_url: str, timeout: float = 120.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    log_entry: dict[str, Any] = {
        "channel_url": channel_url,
        "status": "pending",
        "video_count": 0,
        "new_count": 0,
        "skipped": 0,
    }
    if not shutil.which("yt-dlp"):
        log_entry.update({"status": "failed", "error": "yt-dlp not found"})
        return [], log_entry

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--no-warnings",
        "--dump-json",
        "--playlist-end",
        "10",
        channel_url,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        log_entry.update({
            "status": "failed",
            "returncode": 124,
            "duration_s": time.monotonic() - started,
            "stdout_len": len(exc.stdout or ""),
            "stderr_len": len(exc.stderr or ""),
            "stderr": (exc.stderr or "") + f"\nyt-dlp timed out after {timeout}s",
            "error": "timeout",
        })
        return [], log_entry

    log_entry.update({
        "returncode": result.returncode,
        "duration_s": time.monotonic() - started,
        "stdout_len": len(result.stdout or ""),
        "stderr_len": len(result.stderr or ""),
        "stderr": result.stderr or "",
    })
    if result.returncode != 0:
        log_entry.update({"status": "failed", "error": f"yt-dlp exited {result.returncode}"})
        return [], log_entry

    videos: list[dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            video = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(video, dict) and youtube_watch_url(video):
            videos.append(video)

    log_entry["video_count"] = min(len(videos), 10)
    log_entry["status"] = "ok" if videos else "empty"
    if not videos:
        log_entry["error"] = "yt-dlp returned no videos"
    return videos[:10], log_entry


def sweep_youtube_channel(feed_cfg: dict[str, Any], processed_ids: dict[str, list[str]]) -> tuple[FeedReport, list[NewItem]]:
    name = feed_cfg["name"]
    feed_type = feed_cfg.get("type", "youtube-channel")
    channel_url = str(feed_cfg.get("channel_url") or "").strip()
    report = FeedReport(name=name, type=feed_type, fetched=False, new_count=0, skipped=0)
    new_items: list[NewItem] = []

    if not channel_url:
        report.error = "youtube-channel mode but no channel_url configured"
        return report, new_items

    videos, log_entry = fetch_youtube_channel(channel_url)
    log_entry["name"] = name
    seen_ids = set(processed_ids.get(name, []))
    feed_seen: list[str] = []

    if log_entry.get("status") == "ok":
        report.fetched = True
    else:
        report.error = str(log_entry.get("error") or log_entry.get("status") or "youtube fetch failed")

    for video in videos[:10]:
        video_url = youtube_watch_url(video)
        if not video_url:
            continue
        feed_seen.append(video_url)
        if video_url in seen_ids:
            report.skipped += 1
            log_entry["skipped"] = log_entry.get("skipped", 0) + 1
            continue
        if not parse_youtube_published(video) or not video.get("description"):
            details, detail_error = fetch_youtube_video_details(video_url)
            if details:
                video = {**video, **details}
            if detail_error:
                log_entry.setdefault("detail_errors", []).append(f"{video_url}: {detail_error}")
        new_items.append(NewItem(
            feed_name=name,
            feed_type=feed_type,
            item_id=video_url,
            title=clean_text(video.get("title") or video_url, 200),
            url=video_url,
            published_iso=parse_youtube_published(video),
            audio_url=None,
            summary_short=clean_text(video.get("description") or "", 500),
            cadence_tag="unknown",
            processor=feed_cfg.get("processor", "kimi-summarize"),
            output_dir=feed_cfg.get("output_dir", "_state/blog-summaries/"),
            source_type="youtube-channel",
            source_lane=feed_cfg.get("lane"),
        ))
        report.new_count += 1
        log_entry["new_count"] = log_entry.get("new_count", 0) + 1

    processed_ids[name] = list(dict.fromkeys((feed_seen + list(seen_ids))[:200]))
    YOUTUBE_LOG_ENTRIES.append(log_entry)
    atomic_write(YOUTUBE_LOG_PATH, youtube_side_log(YOUTUBE_LOG_ENTRIES))
    return report, new_items


def init_manual_queue() -> None:
    if not MANUAL_QUEUE_PATH.exists():
        atomic_write(
            MANUAL_QUEUE_PATH,
            "# Manual feed queue - one URL per line.\n"
            "# Blank lines and # comments are ignored. Processed URLs move to manual-queue-done.txt.\n",
        )
    if not MANUAL_QUEUE_DONE_PATH.exists():
        atomic_write(MANUAL_QUEUE_DONE_PATH, "")


def manual_item_id(url: str) -> str:
    return "manual:" + sha256(url.encode("utf-8")).hexdigest()[:24]


def classify_manual_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and path.startswith("/i/broadcasts/"):
        return "x-broadcast"
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"} and path == "/watch":
        return "youtube"
    if host in {"youtu.be", "www.youtu.be"}:
        return "youtube"
    if host in {"arxiv.org", "www.arxiv.org", "alphaxiv.org", "www.alphaxiv.org"} and re.match(r"^/(abs|pdf)/", path):
        return "arxiv"
    return "generic-blog"


def extract_arxiv_id(url: str) -> str:
    match = re.search(r"/(?:abs|pdf)/([^/?#]+)", url)
    if not match:
        raise ValueError("no arxiv id in URL")
    return re.sub(r"\.pdf$", "", match.group(1))


def today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def generic_blog_metadata(url: str, timeout: float = 30.0) -> tuple[str, str, str]:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=HTML_SCRAPE_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = clean_text(unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))) if title_match else url, 200)
    desc_match = re.search(
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not desc_match:
        desc_match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:name|property)=["\'](?:description|og:description)["\']',
            html,
            re.IGNORECASE | re.DOTALL,
        )
    if desc_match:
        summary = clean_text(unescape(desc_match.group(1)), 500)
    else:
        body_match = re.search(r"<article[^>]*>(.*?)</article>", html, re.IGNORECASE | re.DOTALL)
        body = body_match.group(1) if body_match else html
        summary = clean_text(unescape(re.sub(r"<[^>]+>", " ", body)), 500)
    return title or url, summary, today_iso_date()


def manual_arxiv_item(url: str) -> tuple[str, str, str]:
    arxiv_id = extract_arxiv_id(url)
    parsed = fetch_arxiv_by_id(arxiv_id)
    if not parsed.entries:
        raise ValueError(f"arxiv API returned no entry for {arxiv_id}")
    entry = parsed.entries[0]
    published_at = parse_published(entry)
    return (
        clean_text(entry.get("title") or f"arXiv {arxiv_id}", 200),
        short_summary(entry, 500),
        published_at.isoformat() if published_at else today_iso_date(),
    )


def manual_media_item(url: str) -> tuple[str, str, str]:
    details, error = fetch_youtube_video_details(url)
    if error:
        raise ValueError(error)
    return (
        clean_text(details.get("title") or url, 200),
        clean_text(details.get("description") or "", 500),
        parse_youtube_published(details) or today_iso_date(),
    )


def build_manual_item(url: str) -> NewItem:
    url_type = classify_manual_url(url)
    audio_url: str | None = None
    if url_type in {"x-broadcast", "youtube"}:
        title, summary, published = manual_media_item(url)
        audio_url = url
    elif url_type == "arxiv":
        title, summary, published = manual_arxiv_item(url)
    else:
        title, summary, published = generic_blog_metadata(url)
    return NewItem(
        feed_name="Manual queue",
        feed_type="manual-queue",
        item_id=manual_item_id(url),
        title=title,
        url=url,
        published_iso=published,
        audio_url=audio_url,
        summary_short=summary[:500],
        cadence_tag="unknown",
        processor="kimi-summarize",
        output_dir="_state/blog-summaries/",
        source_type="manual-queue",
        source_lane="practitioner",
    )


def sweep_manual_queue(processed_ids: dict[str, list[str]]) -> tuple[FeedReport, list[NewItem]]:
    init_manual_queue()
    name = "Manual queue"
    report = FeedReport(name=name, type="manual-queue", fetched=True, new_count=0, skipped=0)
    new_items: list[NewItem] = []
    lines = MANUAL_QUEUE_PATH.read_text().splitlines()
    keep_lines: list[str] = []
    seen_ids = set(processed_ids.get(name, []))
    feed_seen: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            keep_lines.append(raw_line)
            continue
        url = stripped.split()[0]
        item_id = manual_item_id(url)
        if item_id in seen_ids:
            report.skipped += 1
            append_atomic(MANUAL_QUEUE_DONE_PATH, f"{utc_now_iso()}\talready-processed\t{url}\n")
            log_extra(f"- Manual queue: already-processed `{url}`")
            continue
        try:
            item = build_manual_item(url)
        except Exception as exc:
            reason = clean_text(exc, 300)
            append_atomic(MANUAL_QUEUE_FAILED_PATH, f"{utc_now_iso()}\tfailed\t{url}\t{reason}\n")
            log_extra(f"- Manual queue: failed `{url}` — {reason}")
            report.skipped += 1
            continue
        new_items.append(item)
        report.new_count += 1
        feed_seen.append(item_id)
        append_atomic(MANUAL_QUEUE_DONE_PATH, f"{utc_now_iso()}\tprocessed\t{url}\t{item.item_id}\n")
        log_extra(f"- Manual queue: processed `{url}` as {classify_manual_url(url)}")

    processed_ids[name] = list(dict.fromkeys((feed_seen + list(seen_ids))[:200]))
    atomic_write(MANUAL_QUEUE_PATH, "\n".join(keep_lines).rstrip() + "\n")
    return report, new_items


def sweep_feed(feed_cfg: dict[str, Any], processed_ids: dict[str, list[str]]) -> tuple[FeedReport, list[NewItem]]:
    name = feed_cfg["name"]
    feed_type = feed_cfg.get("type", "rss-text")
    report = FeedReport(name=name, type=feed_type, fetched=False, new_count=0, skipped=0)
    new_items: list[NewItem] = []

    if feed_type == "twitter-via-search":
        return sweep_twitter_via_search(feed_cfg, processed_ids)

    if feed_type == "youtube-channel":
        return sweep_youtube_channel(feed_cfg, processed_ids)

    if feed_type == "arxiv-api":
        category = str(feed_cfg.get("arxiv_category") or "").strip()
        if not category:
            report.error = "arxiv-api mode but no arxiv_category configured"
            return report, new_items
        window_days = int(feed_cfg.get("arxiv_api_window_days") or 14)
        max_results = int(feed_cfg.get("arxiv_api_max_results") or 200)
        max_pages = int(feed_cfg.get("arxiv_api_max_pages") or 20)
        try:
            parsed_entries: list[Any] = []
            for page in range(max_pages):
                parsed = fetch_arxiv_api(category, max_results, start=page * max_results)
                entries = list(parsed.entries or [])
                parsed_entries.extend(entries)
                if not entries:
                    break
                cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
                oldest = parse_published(entries[-1])
                if oldest and oldest < cutoff:
                    break
        except Exception as e:
            report.error = f"arxiv-api fetch failed: {e}"
            log_extra(f"- arxiv-api {category}: failed — {clean_text(e, 300)}")
            return report, new_items
        report.fetched = True
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        seen_ids = set(processed_ids.get(name, []))
        feed_seen: list[str] = []
        for entry in parsed_entries:
            item_id = entry.get("id") or entry.get("guid") or entry.get("link") or ""
            if not item_id:
                continue
            published_at = parse_published(entry)
            if published_at and published_at < cutoff:
                continue
            feed_seen.append(item_id)
            if item_id in seen_ids:
                report.skipped += 1
                continue
            tag, note = cadence_tag(feed_cfg, published_at)
            if note:
                report.cadence_notes.append(f"{entry.get('title', '?')}: {note}")
            new_items.append(NewItem(
                feed_name=name,
                feed_type=feed_type,
                item_id=item_id,
                title=entry.get("title") or "(untitled)",
                url=entry.get("link") or item_id,
                published_iso=(published_at.isoformat() if published_at else ""),
                audio_url=None,
                summary_short=short_summary(entry),
                cadence_tag=tag,
                processor=feed_cfg.get("processor", "kimi-summarize"),
                output_dir=feed_cfg.get("output_dir", "_state/blog-summaries/"),
                source_type="arxiv-api",
                source_lane=feed_cfg.get("lane"),
            ))
            report.new_count += 1
        retention = max(max_results * max_pages, 200)
        processed_ids[name] = list(dict.fromkeys((feed_seen + list(seen_ids))[:retention]))
        log_extra(f"- arxiv-api {category}: fetched={len(parsed_entries)} window_new={report.new_count} skipped={report.skipped}")
        return report, new_items

    if feed_type == "html-scrape":
        url = feed_cfg.get("url")
        if not url:
            report.error = "html-scrape mode but no URL configured"
            return report, new_items
        link_pattern = feed_cfg.get("link_pattern", r"/news/[a-z0-9-]+$")
        try:
            links = scrape_html_index(url, link_pattern)
        except Exception as e:
            report.error = f"html-scrape failed: {e}"
            return report, new_items
        report.fetched = True
        seen_ids = set(processed_ids.get(name, []))
        feed_seen: list[str] = []
        for full_url, title in links:
            feed_seen.append(full_url)
            if full_url in seen_ids:
                report.skipped += 1
                continue
            new_items.append(NewItem(
                feed_name=name,
                feed_type=feed_type,
                item_id=full_url,
                title=title,
                url=full_url,
                published_iso="",  # index pages rarely expose dates reliably
                audio_url=None,
                summary_short="",  # full text fetched during content-processing
                cadence_tag="unknown",
                processor=feed_cfg.get("processor", "kimi-summarize"),
                output_dir=feed_cfg.get("output_dir", "_state/blog-summaries/"),
                source_lane=feed_cfg.get("lane"),
            ))
            report.new_count += 1
        processed_ids[name] = list(dict.fromkeys((feed_seen + list(seen_ids))[:200]))
        return report, new_items

    url = feed_cfg.get("rss") or feed_cfg.get("url")
    if not url:
        report.error = "no RSS URL configured"
        return report, new_items

    try:
        parsed = fetch_feed(url)
    except Exception as e:
        report.error = f"fetch failed: {e}"
        return report, new_items

    report.fetched = True

    if parsed.get("bozo") and parsed.get("entries") is None:
        report.error = f"parse error: {parsed.get('bozo_exception')}"
        return report, new_items

    seen_ids = set(processed_ids.get(name, []))
    feed_seen: list[str] = []

    for entry in parsed.entries[:25]:  # cap per-feed at 25 newest
        item_id = entry.get("id") or entry.get("guid") or entry.get("link") or ""
        if not item_id:
            continue
        feed_seen.append(item_id)
        if item_id in seen_ids:
            report.skipped += 1
            continue
        published_at = parse_published(entry)
        # Skip items older than 14d to avoid first-run flooding
        if published_at and published_at < datetime.now(timezone.utc) - timedelta(days=14):
            report.skipped += 1
            continue
        tag, note = cadence_tag(feed_cfg, published_at)
        if note:
            report.cadence_notes.append(f"{entry.get('title', '?')}: {note}")
        new_items.append(NewItem(
            feed_name=name,
            feed_type=feed_type,
            item_id=item_id,
            title=entry.get("title") or "(untitled)",
            url=entry.get("link") or url,
            published_iso=(published_at.isoformat() if published_at else ""),
            audio_url=find_audio_url(entry),
            summary_short=short_summary(entry),
            cadence_tag=tag,
            processor=feed_cfg.get("processor", "kimi-summarize"),
            output_dir=feed_cfg.get("output_dir", "_state/blog-summaries/"),
            source_lane=feed_cfg.get("lane"),
        ))
        report.new_count += 1

    # Update processed-ids: keep last 200 per feed to bound growth
    processed_ids[name] = list(dict.fromkeys((feed_seen + list(seen_ids))[:200]))
    return report, new_items


def render_log(reports: list[FeedReport], new_items: list[NewItem]) -> str:
    lines = [f"# Feed Sweep — {DATE}", "", f"Run at: {datetime.now(timezone.utc).isoformat()}", ""]
    lines.append("## Summary")
    lines.append(f"- Feeds checked: {len(reports)}")
    fetched_ok = sum(1 for r in reports if r.fetched)
    failed = sum(1 for r in reports if r.error)
    total_new = sum(r.new_count for r in reports)
    lines.append(f"- Successful fetches: {fetched_ok}")
    lines.append(f"- Errors: {failed}")
    lines.append(f"- New items found: {total_new}")
    lines.append("")

    lines.append("## Per-feed")
    for r in reports:
        status = "✗" if r.error else "✓"
        lines.append(f"- {status} **{r.name}** ({r.type}): new={r.new_count}, skipped={r.skipped}")
        if r.error:
            lines.append(f"    - error: {r.error}")
        for note in r.cadence_notes:
            lines.append(f"    - cadence: {note}")
    lines.append("")

    if new_items:
        lines.append("## New items")
        for item in new_items:
            tag_marker = "" if item.cadence_tag == "on-schedule" else f" *[{item.cadence_tag}]*"
            lines.append(f"- **{item.feed_name}** — {item.title}{tag_marker}")
            if item.published_iso:
                lines.append(f"    - published: {item.published_iso}")
            lines.append(f"    - url: {item.url}")
            if item.audio_url:
                lines.append(f"    - audio: {item.audio_url}")
        lines.append("")

    if FEED_SWEEP_EXTRA_LOG_LINES:
        lines.append("## Sidecar events")
        lines.extend(FEED_SWEEP_EXTRA_LOG_LINES)
        lines.append("")

    lines.append("---")
    lines.append(f"*New items written to `{NEW_ITEMS_PATH.relative_to(VAULT_ROOT)}` for content-processing.sh*")
    return "\n".join(lines) + "\n"


def main() -> int:
    config = load_config()
    feeds = config.get("feeds", [])
    if not feeds:
        sys.exit("no feeds configured in feed-config.yaml")

    processed_ids = load_processed_ids()
    all_reports: list[FeedReport] = []
    all_new: list[NewItem] = []

    manual_report, manual_items = sweep_manual_queue(processed_ids)
    all_reports.append(manual_report)
    all_new.extend(manual_items)

    for feed_cfg in feeds:
        report, items = sweep_feed(feed_cfg, processed_ids)
        all_reports.append(report)
        all_new.extend(items)
        time.sleep(0.5)  # gentle on origin servers

    save_processed_ids(processed_ids)
    atomic_write(NEW_ITEMS_PATH, json.dumps([item_dict(i) for i in all_new], indent=2))
    atomic_write(LOG_PATH, render_log(all_reports, all_new))

    print(f"Feed sweep log: {LOG_PATH}")
    print(f"New items: {len(all_new)} → {NEW_ITEMS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
