#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.28",
#     "trafilatura>=2.0",
# ]
# ///
"""Content processing for Claude-Vibe-Squad.

Reads `_state/new-items-<date>.json` from feed-sweep, processes each item:

- **Blog text** (`processor: kimi-summarize`): fetch URL, extract main text with
  trafilatura, summarize via `kimi -p`, write to `_state/blog-summaries/`.

- **Podcast** (`processor: gemini-transcribe + kimi-synthesize`): write a
  headline brief from RSS metadata with audio URL prominent. Full transcription
  is deferred (TODO: gemini -p with --file <audio>).

Defaults to processing 5 items per run (`--limit 5`) to keep API spend bounded.
Use `--limit 0` to dry-run (list what would be processed without invoking LLMs).

Idempotent via `_state/processed-content.json` — items already briefed are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import trafilatura

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NEW_ITEMS_PATH = STATE_DIR / f"new-items-{DATE}.json"
PROCESSED_CONTENT_PATH = STATE_DIR / "processed-content.json"
LOG_DIR = STATE_DIR / "cleanup-logs"
LOG_PATH = LOG_DIR / f"{DATE}-content-processing.md"

KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")
GEMINI_BIN = os.environ.get("GEMINI_BIN", "gemini")

SUMMARY_PROMPT = (
    "Summarize the article below in 5-8 bullet points. Lead with the news / claim. "
    "Include any concrete numbers, names, or product changes. End with one bullet "
    "for 'why it matters.' Keep total under 150 words. Do not preface with phrases "
    "like 'Here is a summary'; output the bullets directly.\n\n"
    "ARTICLE:\n{text}"
)


@dataclass
class ItemResult:
    feed_name: str
    item_id: str
    title: str
    url: str
    output_path: str | None = None
    tier: str = "headline-only"  # full | headline-only
    status: str = "pending"      # ok | failed | skipped | dry-run
    error: str | None = None
    duration_s: float = 0.0


@dataclass
class RunReport:
    items_total: int
    items_processed: int
    items_skipped: int
    items_failed: int
    duration_s: float
    item_results: list[ItemResult] = field(default_factory=list)


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


def load_new_items() -> list[dict[str, Any]]:
    if not NEW_ITEMS_PATH.exists():
        return []
    return json.loads(NEW_ITEMS_PATH.read_text())


def load_processed_set() -> set[str]:
    if not PROCESSED_CONTENT_PATH.exists():
        return set()
    try:
        data = json.loads(PROCESSED_CONTENT_PATH.read_text())
        return set(data.get("ids", []))
    except json.JSONDecodeError:
        return set()


def save_processed_set(ids: set[str]) -> None:
    payload = {"updated": datetime.now(timezone.utc).isoformat(), "ids": sorted(ids)}
    atomic_write(PROCESSED_CONTENT_PATH, json.dumps(payload, indent=2))


def oauth_env() -> dict:
    """Drop API-key env vars so headless CLI calls fall back to OAuth/subscription."""
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env.pop(k, None)
    return env


def fetch_article_text(url: str, timeout: float = 20.0) -> str | None:
    # Some vendor blogs (OpenAI) 403 generic UAs; mimic a recent browser.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return trafilatura.extract(resp.text, include_comments=False, include_tables=False)
    except (httpx.HTTPError, ValueError) as e:
        print(f"  fetch failed: {e}", file=sys.stderr)
        return None


def kimi_summarize(text: str, max_chars: int = 12000) -> str | None:
    """Call `kimi -p` with the summarization prompt. Truncate input to bound cost."""
    snippet = text[:max_chars]
    if len(text) > max_chars:
        snippet += "\n\n[truncated for processing]"
    prompt = SUMMARY_PROMPT.format(text=snippet)
    try:
        # --quiet = --print --output-format text --final-message-only
        # --no-thinking suppresses intermediate reasoning emission.
        result = subprocess.run(
            [KIMI_BIN, "--quiet", "--no-thinking", "-p", prompt,
             "--max-steps-per-turn", "5"],
            capture_output=True, text=True, timeout=180, env=oauth_env(),
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        print(f"  kimi binary not found at {KIMI_BIN}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"  kimi exit {result.returncode}: {result.stderr[:300]}", file=sys.stderr)
        return None

    out = result.stdout.strip()
    # Strip any "To resume this session" footer kimi sometimes emits.
    out = out.split("To resume this session:")[0].rstrip()
    return out or None


def render_blog_brief(item: dict[str, Any], summary: str) -> str:
    return (
        f"---\n"
        f"feed: {item['feed_name']}\n"
        f"title: {json.dumps(item['title'])}\n"
        f"url: {item['url']}\n"
        f"published: {item.get('published_iso', '')}\n"
        f"cadence_tag: {item['cadence_tag']}\n"
        f"processed_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"processor: kimi-summarize\n"
        f"tier: full\n"
        f"---\n\n"
        f"# {item['title']}\n\n"
        f"**Source:** [{item['feed_name']}]({item['url']})\n\n"
        f"## Summary\n\n"
        f"{summary}\n\n"
        f"## Original\n\n"
        f"{item['url']}\n"
    )


def render_podcast_headline(item: dict[str, Any]) -> str:
    audio_line = f"**Audio:** {item['audio_url']}\n\n" if item.get("audio_url") else ""
    return (
        f"---\n"
        f"feed: {item['feed_name']}\n"
        f"title: {json.dumps(item['title'])}\n"
        f"url: {item['url']}\n"
        f"audio_url: {item.get('audio_url') or ''}\n"
        f"published: {item.get('published_iso', '')}\n"
        f"cadence_tag: {item['cadence_tag']}\n"
        f"processed_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"processor: rss-headline\n"
        f"tier: headline-only\n"
        f"---\n\n"
        f"# {item['title']}\n\n"
        f"**Show:** {item['feed_name']}\n"
        f"**Published:** {item.get('published_iso', 'unknown')}\n\n"
        f"{audio_line}"
        f"## Headline\n\n"
        f"{item['summary_short'] or '(no summary in feed)'}\n\n"
        f"---\n"
        f"*Headline-only. Run with `--enable-transcription` for full transcript brief (uses ElevenLabs Scribe — pay-per-minute).*\n"
    )


def transcribe_audio_elevenlabs(audio_url: str, max_seconds: int = 300) -> str | None:
    """Download audio, send to ElevenLabs Scribe, return transcript text.

    Pay-per-use API. Caller must have set --enable-transcription explicitly.
    Bounds at max_seconds so we don't accidentally transcribe a 4-hour podcast.
    """
    import tempfile

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("  ELEVENLABS_API_KEY not set; cannot transcribe", file=sys.stderr)
        return None

    # Download audio to temp file
    try:
        with httpx.Client(timeout=120, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as client:
            with client.stream("GET", audio_url) as resp:
                resp.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    downloaded = 0
                    # Stream-cap at ~max_seconds * 50KB/s to avoid huge dl
                    cap_bytes = max_seconds * 50 * 1024
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > cap_bytes:
                            break
                    audio_path = tmp.name
    except httpx.HTTPError as e:
        print(f"  audio download failed: {e}", file=sys.stderr)
        return None

    # Send to ElevenLabs Speech-to-Text (Scribe)
    # API: POST https://api.elevenlabs.io/v1/speech-to-text
    try:
        with open(audio_path, "rb") as fh:
            with httpx.Client(timeout=300) as client:
                resp = client.post(
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    headers={"xi-api-key": api_key},
                    files={"file": ("audio.mp3", fh, "audio/mpeg")},
                    data={"model_id": "scribe_v1"},
                )
                resp.raise_for_status()
                payload = resp.json()
    except httpx.HTTPError as e:
        print(f"  ElevenLabs transcription failed: {e}", file=sys.stderr)
        return None
    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass
    return payload.get("text") or None


PODCAST_SYNTHESIS_PROMPT = (
    "Synthesize this podcast transcript into a structured brief. Output:\n\n"
    "## TL;DR\n(2-3 sentences capturing the headline take)\n\n"
    "## Key points\n(5-8 bullets — each a substantive insight, claim, or "
    "concrete number/name. Lead with news, end with a 'why it matters' bullet.)\n\n"
    "## Worth listening if\n(1-2 bullets — what kind of operator should hear "
    "the full episode rather than just the brief)\n\n"
    "Rules:\n"
    "- Cite speakers/guests when names appear in the transcript.\n"
    "- Don't pad. Under 250 words total.\n"
    "- No preface like 'Here is the synthesis'; output directly.\n\n"
    "TRANSCRIPT:\n{text}"
)


def render_podcast_full(item: dict[str, Any], synthesis: str) -> str:
    audio_line = f"**Audio:** {item['audio_url']}\n\n" if item.get("audio_url") else ""
    return (
        f"---\n"
        f"feed: {item['feed_name']}\n"
        f"title: {json.dumps(item['title'])}\n"
        f"url: {item['url']}\n"
        f"audio_url: {item.get('audio_url') or ''}\n"
        f"published: {item.get('published_iso', '')}\n"
        f"cadence_tag: {item['cadence_tag']}\n"
        f"processed_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"processor: elevenlabs-scribe + kimi-synthesize\n"
        f"tier: full\n"
        f"---\n\n"
        f"# {item['title']}\n\n"
        f"**Show:** {item['feed_name']}\n"
        f"**Published:** {item.get('published_iso', 'unknown')}\n\n"
        f"{audio_line}"
        f"{synthesis}\n"
    )


def slugify(text: str, max_len: int = 60) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    out = "-".join(filter(None, out.split("-")))
    return out[:max_len].rstrip("-") or "untitled"


def output_path_for(item: dict[str, Any]) -> Path:
    out_dir = VAULT_ROOT / item["output_dir"].lstrip("/")
    slug = slugify(item["title"])
    return out_dir / f"{DATE}-{item['feed_name'][:20].strip().replace(' ', '-')}-{slug}.md"


def process_blog_item(item: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Returns (status, output_path_str, error)."""
    text = fetch_article_text(item["url"])
    if not text:
        return ("failed", None, "could not extract article text")
    summary = kimi_summarize(text)
    if not summary:
        return ("failed", None, "kimi summarization returned empty")
    out_path = output_path_for(item)
    atomic_write(out_path, render_blog_brief(item, summary))
    return ("ok", str(out_path.relative_to(VAULT_ROOT)), None)


def process_podcast_item(item: dict[str, Any], enable_transcription: bool = False) -> tuple[str, str | None, str | None]:
    out_path = output_path_for(item)
    if enable_transcription and item.get("audio_url"):
        transcript = transcribe_audio_elevenlabs(item["audio_url"])
        if transcript:
            synthesis = kimi_summarize(transcript, max_chars=20000)
            if synthesis:
                # Reuse the summarize path but with podcast-specific framing
                synth_prompt = PODCAST_SYNTHESIS_PROMPT.format(text=transcript[:18000])
                try:
                    result = subprocess.run(
                        [KIMI_BIN, "--quiet", "--no-thinking", "-p", synth_prompt,
                         "--max-steps-per-turn", "5"],
                        capture_output=True, text=True, timeout=240, env=oauth_env(),
                    )
                    if result.returncode == 0:
                        out = result.stdout.split("To resume this session:")[0].strip()
                        if out:
                            atomic_write(out_path, render_podcast_full(item, out))
                            return ("ok", str(out_path.relative_to(VAULT_ROOT)), None)
                except subprocess.TimeoutExpired:
                    pass
        # Fall through to headline if transcription path failed
    atomic_write(out_path, render_podcast_headline(item))
    return ("ok", str(out_path.relative_to(VAULT_ROOT)), None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process feed-sweep items into briefs.")
    parser.add_argument("--limit", type=int, default=5,
                        help="Max items to process this run (0 = dry-run, default 5)")
    parser.add_argument("--filter", default=None,
                        help="Only process items whose feed_name contains this substring")
    parser.add_argument("--podcasts-only", action="store_true")
    parser.add_argument("--blogs-only", action="store_true")
    parser.add_argument("--enable-transcription", action="store_true",
                        help="Run full ElevenLabs Scribe transcription on podcasts "
                        "(pay-per-minute; default is headline-only)")
    return parser.parse_args()


def render_log(report: RunReport) -> str:
    lines = [f"# Content Processing — {DATE}", "",
             f"Run at: {datetime.now(timezone.utc).isoformat()}",
             f"Duration: {report.duration_s:.1f}s",
             ""]
    lines.append("## Summary")
    lines.append(f"- Items in queue: {report.items_total}")
    lines.append(f"- Processed: {report.items_processed}")
    lines.append(f"- Skipped (already done): {report.items_skipped}")
    lines.append(f"- Failed: {report.items_failed}")
    lines.append("")
    if report.item_results:
        lines.append("## Per-item")
        for r in report.item_results:
            marker = {"ok": "✓", "failed": "✗", "skipped": "○", "dry-run": "·"}.get(r.status, "?")
            lines.append(f"- {marker} **{r.feed_name}** — {r.title[:80]}  *(tier: {r.tier}, {r.duration_s:.1f}s)*")
            if r.output_path:
                lines.append(f"    - output: `{r.output_path}`")
            if r.error:
                lines.append(f"    - error: {r.error}")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    items = load_new_items()
    if not items:
        print(f"No new-items file at {NEW_ITEMS_PATH}; nothing to do.")
        return 0

    processed = load_processed_set()
    queue: list[dict[str, Any]] = []
    skipped_count = 0
    for item in items:
        if item["item_id"] in processed:
            skipped_count += 1
            continue
        if args.filter and args.filter.lower() not in item["feed_name"].lower():
            continue
        if args.podcasts_only and item["feed_type"] != "podcast":
            continue
        if args.blogs_only and item["feed_type"] not in ("rss-text", "html-scrape"):
            continue
        queue.append(item)

    queue = queue[: max(args.limit, 0)] if args.limit > 0 else queue

    report = RunReport(
        items_total=len(items), items_processed=0,
        items_skipped=skipped_count, items_failed=0, duration_s=0.0,
    )
    run_start = time.monotonic()

    for item in queue:
        item_start = time.monotonic()
        if args.limit == 0:
            report.item_results.append(ItemResult(
                feed_name=item["feed_name"], item_id=item["item_id"],
                title=item["title"], url=item["url"],
                tier="full" if item["feed_type"] == "rss-text" else "headline-only",
                status="dry-run",
            ))
            continue

        print(f"Processing: [{item['feed_name']}] {item['title'][:80]}")
        if item["feed_type"] in ("rss-text", "html-scrape"):
            status, out_path, err = process_blog_item(item)
            tier = "full"
        elif item["feed_type"] == "podcast":
            status, out_path, err = process_podcast_item(
                item, enable_transcription=args.enable_transcription)
            tier = "full" if args.enable_transcription else "headline-only"
        else:
            status, out_path, err, tier = "skipped", None, f"unknown feed_type: {item['feed_type']}", "headline-only"

        result = ItemResult(
            feed_name=item["feed_name"], item_id=item["item_id"],
            title=item["title"], url=item["url"],
            output_path=out_path, tier=tier, status=status, error=err,
            duration_s=time.monotonic() - item_start,
        )
        report.item_results.append(result)
        if status == "ok":
            report.items_processed += 1
            processed.add(item["item_id"])
        elif status == "failed":
            report.items_failed += 1

    report.duration_s = time.monotonic() - run_start
    save_processed_set(processed)
    atomic_write(LOG_PATH, render_log(report))
    print(f"\nLog: {LOG_PATH}")
    print(f"Processed: {report.items_processed}, Failed: {report.items_failed}, Skipped: {report.items_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
