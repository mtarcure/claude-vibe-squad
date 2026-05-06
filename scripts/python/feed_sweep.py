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
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

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
NEW_ITEMS_PATH = STATE_DIR / f"new-items-{DATE}.json"

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass
class NewItem:
    feed_name: str
    feed_type: str  # podcast | rss-text | html-scrape
    item_id: str
    title: str
    url: str
    published_iso: str
    audio_url: str | None
    summary_short: str
    cadence_tag: str  # on-schedule | off-schedule | unknown
    processor: str
    output_dir: str


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


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        sys.exit(f"feed-config.yaml not found at {CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text())


def load_processed_ids() -> dict[str, list[str]]:
    if not PROCESSED_IDS_PATH.exists():
        return {}
    try:
        return json.loads(PROCESSED_IDS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_processed_ids(ids: dict[str, list[str]]) -> None:
    atomic_write(PROCESSED_IDS_PATH, json.dumps(ids, indent=2, sort_keys=True))


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
    if isinstance(entry, dict):
        raw = entry.get("summary") or entry.get("description") or ""
    else:
        raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
    text = re.sub(r"<[^>]+>", "", raw)
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


def sweep_feed(feed_cfg: dict[str, Any], processed_ids: dict[str, list[str]]) -> tuple[FeedReport, list[NewItem]]:
    name = feed_cfg["name"]
    feed_type = feed_cfg.get("type", "rss-text")
    report = FeedReport(name=name, type=feed_type, fetched=False, new_count=0, skipped=0)
    new_items: list[NewItem] = []

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

    for feed_cfg in feeds:
        report, items = sweep_feed(feed_cfg, processed_ids)
        all_reports.append(report)
        all_new.extend(items)
        time.sleep(0.5)  # gentle on origin servers

    save_processed_ids(processed_ids)
    atomic_write(NEW_ITEMS_PATH, json.dumps([asdict(i) for i in all_new], indent=2))
    atomic_write(LOG_PATH, render_log(all_reports, all_new))

    print(f"Feed sweep log: {LOG_PATH}")
    print(f"New items: {len(all_new)} → {NEW_ITEMS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
