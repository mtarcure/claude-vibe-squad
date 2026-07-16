#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.28",
#     "pypdf>=5.0",
#     "trafilatura>=2.0",
# ]
# ///
"""Content processing for Claude-Vibe-Squad.

Reads `_state/new-items-<date>.json` from feed-sweep, processes each item:

- **Depth items**: fetch deep source content where possible, then run a
  Claude sequential-thinking analysis pass that writes structured frontmatter
  for downstream newsletter formatting.

- **Podcast** (`processor: gemini-transcribe + kimi-synthesize`): write a
  headline brief from RSS metadata with audio URL prominent. Full transcription
  is deferred (TODO: gemini -p with --file <audio>).

Defaults to processing 5 items per run (`--limit 5`) to keep API spend bounded.
Use `--limit 0` to dry-run (list what would be processed without invoking LLMs).

Idempotent via `_state/processed-content.json` — items already briefed are skipped.

YouTube depth-tier items use a retained transcription cache under
`_state/transcription-cache/`: downloaded audio and `.txt` transcripts are kept
for audit and re-runs. The processor does not delete cached audio. The normal
depth `--limit` is applied first; `YOUTUBE_TRANSCRIPTION_LIMIT` is an additional
per-run cap inside that depth queue. YouTube/podcast Scribe is capped at 30
minutes per item and 300 total audio minutes per run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from io import BytesIO
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import trafilatura

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NEW_ITEMS_PATH = STATE_DIR / f"new-items-{DATE}.json"
TRIAGE_PATH = STATE_DIR / f"content-triage-{DATE}.json"
PROCESSED_CONTENT_PATH = STATE_DIR / "processed-content.json"
LOG_DIR = STATE_DIR / "cleanup-logs"
LOG_PATH = LOG_DIR / f"{DATE}-content-processing.md"
TRANSCRIPTION_CACHE_DIR = STATE_DIR / "transcription-cache"
CONTENT_CACHE_DIR = STATE_DIR / "content-cache"
OPERATOR_INTERESTS_PATH = STATE_DIR / "operator-interests.yaml"

KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")
GEMINI_BIN = os.environ.get("GEMINI_BIN", "gemini")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
SCRIBE_TOOL = "mcp__plugin_chrono-content-engineer_elevenlabs__speech_to_text"
SEQUENTIAL_THINKING_TOOL = "mcp__sequential-thinking__sequentialthinking"
YOUTUBE_TRANSCRIPTION_LIMIT = 10
FINAL_AUDIO_EXTENSIONS = {".mp3"}
SCRIBE_ITEM_MAX_SECONDS = 1800
SCRIBE_RUN_MAX_MINUTES = 300.0
DEPTH_ANALYSIS_LIMIT = 10

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
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    transcriptions: list[dict[str, Any]] = field(default_factory=list)
    content_fetches: list[dict[str, Any]] = field(default_factory=list)


LLM_CALLS: list[dict[str, Any]] = []
TRANSCRIPTION_EVENTS: list[dict[str, Any]] = []
CONTENT_FETCH_EVENTS: list[dict[str, Any]] = []
SCRIBE_MINUTES_USED = 0.0


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


def current_time_section() -> str:
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now_utc.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


def strip_json_fence(raw: str) -> str:
    raw = (raw or "").split("To resume this session:")[0].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def load_operator_profile() -> str:
    try:
        return OPERATOR_INTERESTS_PATH.read_text(encoding="utf-8")[:12000]
    except OSError:
        return "(operator interests unavailable)"


def load_new_items() -> list[dict[str, Any]]:
    if not NEW_ITEMS_PATH.exists():
        return []
    return json.loads(NEW_ITEMS_PATH.read_text())


def load_triage_manifest() -> dict[str, Any] | None:
    if not TRIAGE_PATH.exists():
        return None
    try:
        return json.loads(TRIAGE_PATH.read_text())
    except json.JSONDecodeError:
        return None


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


def canonical_url(url: str) -> str:
    return re.sub(r"#.*$", "", url.strip()).rstrip("/")


def stable_item_id(item: dict[str, Any]) -> str:
    feed = str(item.get("feed_name", "")).strip().lower()
    url = canonical_url(str(item.get("url", "")))
    published = str(item.get("published_iso", "")).strip()
    return hashlib.sha256(f"{feed}\n{url}\n{published}".encode()).hexdigest()[:24]


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
    started = time.monotonic()
    call = {"name": "kimi-summarize", "returncode": None, "stdout_len": 0, "stderr": "", "duration_s": 0.0}
    try:
        # --quiet = --print --output-format text --final-message-only
        # --no-thinking suppresses intermediate reasoning emission.
        result = subprocess.run(
            [KIMI_BIN, "--quiet", "--no-thinking", "-p", prompt,
             "--max-steps-per-turn", "5"],
            capture_output=True, text=True, timeout=180, env=oauth_env(),
        )
    except subprocess.TimeoutExpired:
        call.update({"returncode": "timeout", "duration_s": time.monotonic() - started})
        LLM_CALLS.append(call)
        return None
    except FileNotFoundError:
        print(f"  kimi binary not found at {KIMI_BIN}", file=sys.stderr)
        call.update({"returncode": "missing-binary", "duration_s": time.monotonic() - started})
        LLM_CALLS.append(call)
        return None

    call.update({
        "returncode": result.returncode,
        "stdout_len": len(result.stdout or ""),
        "stderr": (result.stderr or "")[:1200],
        "duration_s": time.monotonic() - started,
    })
    LLM_CALLS.append(call)
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


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip() and str(v).strip().lower() not in {"none", "(none)", "none observed", "(none observed)"}]
    if isinstance(value, str) and value.strip() and value.strip().lower() not in {"none", "(none)", "none observed", "(none observed)"}:
        return [value.strip()]
    return []


def render_structured_analysis_body(item: dict[str, Any], analysis: dict[str, Any], content_source: str) -> str:
    relevance = analysis.get("relevance_to_me") if isinstance(analysis.get("relevance_to_me"), dict) else {}
    connections = normalize_list(relevance.get("current_work_connections"))
    what_it_enables = normalize_list(analysis.get("what_it_enables"))
    immediate_fixes = normalize_list(analysis.get("immediate_fixes"))
    hypothetical = normalize_list(analysis.get("hypothetical_combinations"))
    risks = normalize_list(analysis.get("risks_of_action"))
    links = normalize_list(analysis.get("connections"))

    def bullets(values: list[str]) -> str:
        return "\n".join(f"- {v}" for v in values)

    parts = [
        f"# {item['title']}",
        "",
        f"**Source:** [{item['feed_name']}]({item['url']})",
        f"**Lane:** {item.get('source_lane') or item.get('lane') or 'unknown'}",
        f"**Content source:** {content_source}",
        "",
        "## Core finding",
        "",
        str(analysis.get("core_finding") or "").strip() or "(analysis unavailable)",
        "",
        "## Why for you",
        "",
        (("; ".join(connections) + " — ") if connections else "") + str(relevance.get("why_now") or "").strip(),
        "",
        "## What it enables",
        "",
        bullets(what_it_enables) or "- none observed",
    ]
    if immediate_fixes:
        parts += ["", "## Immediate fixes", "", bullets(immediate_fixes)]
    if hypothetical:
        parts += ["", "## Hypothetical combinations", "", bullets(hypothetical)]
    if risks:
        parts += ["", "## Risks", "", bullets(risks)]
    if links:
        parts += ["", "## Connections", "", bullets(links)]
    parts += ["", "## Original", "", item["url"]]
    return "\n".join(parts) + "\n"


def render_analysis_brief(item: dict[str, Any], analysis: dict[str, Any], content_source: str) -> str:
    analysis_json = json.dumps(analysis, ensure_ascii=False)
    lane = item.get("source_lane") or item.get("lane") or "unknown"
    return (
        f"---\n"
        f"feed: {item['feed_name']}\n"
        f"title: {json.dumps(item['title'])}\n"
        f"url: {item['url']}\n"
        f"published: {item.get('published_iso', '')}\n"
        f"cadence_tag: {item.get('cadence_tag', 'unknown')}\n"
        f"processed_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"processor: claude-sequential-thinking\n"
        f"tier: full\n"
        f"source_lane: {lane}\n"
        f"source_type: {item.get('source_type') or item.get('feed_type') or ''}\n"
        f"time_horizon: {analysis.get('time_horizon', 'near-term')}\n"
        f"content_source: {content_source}\n"
        f"analysis_json: {json.dumps(analysis_json, ensure_ascii=False)}\n"
        f"---\n\n"
        f"{render_structured_analysis_body(item, analysis, content_source)}"
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


def render_text_skim(item: dict[str, Any]) -> str:
    summary = item.get("summary_short") or item.get("triage_reason") or "(no summary in feed)"
    lane = item.get("source_lane") or item.get("lane") or "unknown"
    return (
        f"---\n"
        f"feed: {item['feed_name']}\n"
        f"title: {json.dumps(item['title'])}\n"
        f"url: {item['url']}\n"
        f"published: {item.get('published_iso', '')}\n"
        f"cadence_tag: {item.get('cadence_tag', 'unknown')}\n"
        f"processed_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"processor: rss-headline\n"
        f"tier: headline-only\n"
        f"source_lane: {lane}\n"
        f"---\n\n"
        f"# {item['title']}\n\n"
        f"**Source:** [{item['feed_name']}]({item['url']})\n"
        f"**Lane:** {lane}\n\n"
        f"## Headline\n\n"
        f"{summary}\n\n"
        f"---\n"
        f"*Headline-only skim from triage. Promote to `depth` for full article summary.*\n"
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


def output_has_structured_analysis(item: dict[str, Any]) -> bool:
    path = output_path_for(item)
    if not path.exists():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    return "analysis_json:" in head and "processor: claude-sequential-thinking" in head


def cache_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def arxiv_id_from_url(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", url)
    if match:
        return match.group(1)
    return None


def cache_read(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text if text.strip() else None


def cache_write(path: Path, text: str) -> None:
    atomic_write(path, text[:32000].rstrip() + "\n")


def fetch_arxiv_pdf_text(item: dict[str, Any]) -> tuple[str | None, str]:
    arxiv_id = arxiv_id_from_url(item.get("url", ""))
    if not arxiv_id:
        return None, "arxiv-id-missing"
    cache_path = CONTENT_CACHE_DIR / "arxiv" / f"{arxiv_id}.txt"
    cached = cache_read(cache_path)
    if cached:
        return cached[:32000], "cache:arxiv"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    headers = {"User-Agent": "Claude-Vibe-Squad-content-processing/0.1 (polite; contact local operator)"}
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(resp.content))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            if sum(len(p) for p in pages) >= 32000:
                break
        text = re.sub(r"\s+", " ", "\n".join(pages)).strip()
    except Exception as exc:
        return None, f"arxiv-pdf-failed: {exc}"
    if not text:
        return None, "arxiv-pdf-empty"
    cache_write(cache_path, text)
    return text[:32000], "fetch:arxiv-pdf"


def fetch_html_deep_text(item: dict[str, Any]) -> tuple[str | None, str]:
    url = item.get("url", "")
    if not url:
        return None, "html-url-missing"
    cache_path = CONTENT_CACHE_DIR / "html" / f"{cache_key(canonical_url(url))}.txt"
    cached = cache_read(cache_path)
    if cached:
        return cached[:32000], "cache:html"
    text = fetch_article_text(url, timeout=5.0)
    if not text:
        return None, "html-extract-empty"
    text = text[:32000]
    cache_write(cache_path, text)
    return text, "fetch:html"


def youtube_transcript_content(item: dict[str, Any]) -> tuple[str | None, str]:
    stem = youtube_cache_stem(item)
    transcript_path = TRANSCRIPTION_CACHE_DIR / f"{stem}.txt"
    cached = cache_read(transcript_path)
    if cached:
        content_cache_path = CONTENT_CACHE_DIR / "youtube" / f"{stem}.txt"
        if not content_cache_path.exists():
            cache_write(content_cache_path, cached)
        return cached[:32000], "cache:youtube-transcript"
    return None, "youtube-transcript-missing"


def podcast_transcript_content(item: dict[str, Any]) -> tuple[str | None, str]:
    stem = cache_key(item.get("audio_url") or item.get("url") or item.get("item_id") or item.get("title") or "")
    transcript_path = TRANSCRIPTION_CACHE_DIR / f"{stem}.txt"
    cached = cache_read(transcript_path)
    if cached:
        content_cache_path = CONTENT_CACHE_DIR / "podcast" / f"{stem}.txt"
        if not content_cache_path.exists():
            cache_write(content_cache_path, cached)
        return cached[:32000], "cache:podcast-transcript"
    return None, "podcast-transcript-missing"


def deep_content_for_item(item: dict[str, Any]) -> tuple[str, str]:
    feed_type = item.get("feed_type")
    fallback = item.get("summary_short") or item.get("triage_reason") or ""
    if is_youtube_item(item):
        text, source = youtube_transcript_content(item)
    elif feed_type == "podcast":
        text, source = podcast_transcript_content(item)
    elif "arxiv.org/" in str(item.get("url", "")):
        text, source = fetch_arxiv_pdf_text(item)
    elif feed_type in ("rss-text", "html-scrape"):
        text, source = fetch_html_deep_text(item)
    else:
        text, source = None, "no-deep-fetcher"
    event = {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": source,
        "chars": len(text or ""),
        "fallback": not bool(text),
    }
    if not text:
        text = fallback or "(no RSS description available)"
    CONTENT_FETCH_EVENTS.append(event)
    return text[:32000], source if not event["fallback"] else f"fallback:{source}"


def recent_depth_titles(limit: int = 40) -> str:
    titles: list[str] = []
    for path in sorted((STATE_DIR / "blog-summaries").glob("*.md"), reverse=True)[:200]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            continue
        fm = re.search(r"^---\s*\n(.*?)\n---", text, re.S)
        if not fm or "tier: full" not in fm.group(1):
            continue
        title_match = re.search(r"^title:\s*(.+)$", fm.group(1), re.M)
        feed_match = re.search(r"^feed:\s*(.+)$", fm.group(1), re.M)
        if title_match:
            title = title_match.group(1).strip().strip('"')
            feed = feed_match.group(1).strip() if feed_match else path.stem
            titles.append(f"- {title} — {feed}")
        if len(titles) >= limit:
            break
    return "\n".join(titles) or "(none found)"


def default_analysis(item: dict[str, Any], text: str, reason: str) -> dict[str, Any]:
    return {
        "core_finding": (text[:400].strip() or item.get("title", "")),
        "relevance_to_me": {
            "current_work_connections": [item.get("triage_reason") or "Depth item selected by triage."],
            "why_now": "This was surfaced in today's depth queue.",
        },
        "time_horizon": "near-term",
        "what_it_enables": ["Manual review of the source with context preserved."],
        "immediate_fixes": [],
        "hypothetical_combinations": [],
        "risks_of_action": [f"Structured analysis fallback used because {reason}."],
        "connections": [],
    }


def analysis_prompt(item: dict[str, Any], deep_text: str, content_source: str) -> str:
    triage_context = item.get("triage_entry") or {
        "tier": item.get("triage_tier"),
        "reason": item.get("triage_reason"),
        "source_lane": item.get("source_lane"),
    }
    payload = {
        "item": {
            "feed_name": item.get("feed_name"),
            "title": item.get("title"),
            "url": item.get("url"),
            "source_lane": item.get("source_lane"),
            "published_iso": item.get("published_iso"),
            "content_source": content_source,
        },
        "triage_manifest_entry": triage_context,
        "operator_interests_profile": load_operator_profile(),
        "recent_week_depth_titles": recent_depth_titles(),
        "deep_content_text": deep_text[:32000],
    }
    return (
        "You are the depth-analysis pass for Vibe Squad. Use the allowed sequentialthinking MCP tool "
        "for 5-12 thoughts before finalizing. Think about why this source matters, when it matters, "
        "what it could improve, hypothetical combinations, and risks. Then return JSON only.\n\n"
        f"{current_time_section()}\n\n"
        "Required JSON schema:\n"
        "{\"core_finding\":\"2-3 sentences\",\"relevance_to_me\":{\"current_work_connections\":[\"specific connections\"],"
        "\"why_now\":\"one sentence\"},\"time_horizon\":\"immediate|near-term|speculative-future|archival\","
        "\"what_it_enables\":[\"...\"],\"immediate_fixes\":[\"...\"],\"hypothetical_combinations\":[\"...\"],"
        "\"risks_of_action\":[\"...\"],\"connections\":[\"...\"]}\n\n"
        "Rules: output JSON only after tool use; do not include chain-of-thought; do not invent file paths or dates; "
        "empty lists are allowed when there is no evidence.\n\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def call_depth_analysis(item: dict[str, Any], deep_text: str, content_source: str) -> tuple[dict[str, Any], str | None]:
    if not shutil.which(CLAUDE_BIN):
        return default_analysis(item, deep_text, f"{CLAUDE_BIN} not found"), f"{CLAUDE_BIN} not found"
    prompt = analysis_prompt(item, deep_text, content_source)
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                CLAUDE_BIN,
                "-p",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--allowed-tools",
                SEQUENTIAL_THINKING_TOOL,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=oauth_env(),
        )
    except subprocess.TimeoutExpired:
        LLM_CALLS.append({"name": "claude-depth-analysis", "returncode": "timeout", "stdout_len": 0, "stderr": "", "duration_s": time.monotonic() - started})
        return default_analysis(item, deep_text, "claude depth analysis timeout"), "claude depth analysis timeout"

    LLM_CALLS.append({
        "name": "claude-depth-analysis",
        "returncode": result.returncode,
        "stdout_len": len(result.stdout or ""),
        "stderr": (result.stderr or "")[:1200],
        "duration_s": time.monotonic() - started,
    })
    if result.returncode != 0:
        return default_analysis(item, deep_text, f"claude exited {result.returncode}"), f"claude exited {result.returncode}"
    try:
        analysis = json.loads(strip_json_fence(result.stdout or ""))
    except json.JSONDecodeError as exc:
        return default_analysis(item, deep_text, f"malformed analysis JSON: {exc}"), f"malformed analysis JSON: {exc}"
    if not isinstance(analysis, dict):
        return default_analysis(item, deep_text, "analysis root not object"), "analysis root not object"
    return analysis, None


def youtube_cache_stem(item: dict[str, Any]) -> str:
    source = item.get("item_id") or item.get("url") or item.get("title") or ""
    return hashlib.sha256(str(source).encode()).hexdigest()[:24]


def cached_audio_path(stem: str) -> Path | None:
    if not TRANSCRIPTION_CACHE_DIR.exists():
        return None
    candidates = [
        p for p in TRANSCRIPTION_CACHE_DIR.glob(f"{stem}.*")
        if p.is_file() and p.suffix.lower() in FINAL_AUDIO_EXTENSIONS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def audio_duration_seconds(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return None


def download_youtube_audio(item: dict[str, Any], stem: str) -> tuple[Path | None, dict[str, Any]]:
    TRANSCRIPTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    event: dict[str, Any] = {
        "feed_name": item.get("feed_name", ""),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "cache_stem": stem,
        "download_rc": None,
        "scribe_rc": None,
        "audio_duration_s": None,
        "transcript_chars": 0,
        "scribe_duration_s": 0.0,
        "status": "pending",
    }
    existing = cached_audio_path(stem)
    if existing:
        event["download_rc"] = "cached"
        event["audio_path"] = str(existing.relative_to(VAULT_ROOT))
        event["audio_duration_s"] = audio_duration_seconds(existing)
        return existing, event
    if not shutil.which("yt-dlp"):
        event.update({"download_rc": "missing-binary", "status": "fallback", "error": "yt-dlp not found"})
        return None, event

    output_template = str(TRANSCRIPTION_CACHE_DIR / f"{stem}.%(ext)s")
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "5",
                "-o",
                output_template,
                item["url"],
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        event.update({
            "download_rc": 124,
            "download_duration_s": time.monotonic() - started,
            "stderr": (exc.stderr or "")[:1200],
            "status": "fallback",
            "error": "yt-dlp download timed out",
        })
        return None, event

    event.update({
        "download_rc": result.returncode,
        "download_duration_s": time.monotonic() - started,
        "stderr": (result.stderr or "")[:1200],
    })
    if result.returncode != 0:
        event.update({"status": "fallback", "error": f"yt-dlp download exited {result.returncode}"})
        return None, event

    audio_path = cached_audio_path(stem)
    if not audio_path:
        event.update({"status": "fallback", "error": "yt-dlp download produced no audio file"})
        return None, event
    event["audio_path"] = str(audio_path.relative_to(VAULT_ROOT))
    event["audio_duration_s"] = audio_duration_seconds(audio_path)
    return audio_path, event


def download_podcast_audio(item: dict[str, Any], stem: str) -> tuple[Path | None, dict[str, Any]]:
    TRANSCRIPTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    event: dict[str, Any] = {
        "feed_name": item.get("feed_name", ""),
        "title": item.get("title", ""),
        "url": item.get("audio_url") or item.get("url", ""),
        "cache_stem": stem,
        "download_rc": None,
        "scribe_rc": None,
        "audio_duration_s": None,
        "transcript_chars": 0,
        "scribe_duration_s": 0.0,
        "status": "pending",
    }
    audio_path = TRANSCRIPTION_CACHE_DIR / f"{stem}.mp3"
    if audio_path.exists():
        event["download_rc"] = "cached"
        event["audio_path"] = str(audio_path.relative_to(VAULT_ROOT))
        event["audio_duration_s"] = audio_duration_seconds(audio_path)
        return audio_path, event
    audio_url = item.get("audio_url")
    if not audio_url:
        event.update({"download_rc": "missing-audio-url", "status": "fallback", "error": "audio_url missing"})
        return None, event
    started = time.monotonic()
    try:
        with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Claude-Vibe-Squad-content-processing/0.1"}) as client:
            with client.stream("GET", audio_url) as resp:
                resp.raise_for_status()
                tmp = audio_path.with_suffix(".mp3.tmp")
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                        fh.write(chunk)
                    fh.flush()
                    os.fsync(fh.fileno())
                tmp.rename(audio_path)
    except (httpx.HTTPError, OSError) as exc:
        event.update({"download_rc": "failed", "download_duration_s": time.monotonic() - started, "status": "fallback", "error": f"podcast download failed: {exc}"})
        return None, event
    event.update({
        "download_rc": 0,
        "download_duration_s": time.monotonic() - started,
        "audio_path": str(audio_path.relative_to(VAULT_ROOT)),
        "audio_duration_s": audio_duration_seconds(audio_path),
    })
    return audio_path, event


def transcribe_youtube_audio(audio_path: Path, transcript_path: Path, event: dict[str, Any]) -> str | None:
    if transcript_path.exists():
        transcript = transcript_path.read_text(errors="replace")
        event.update({
            "scribe_rc": "cached",
            "transcript_path": str(transcript_path.relative_to(VAULT_ROOT)),
            "transcript_chars": len(transcript),
            "status": "transcribed",
        })
        return transcript
    if not shutil.which(CLAUDE_BIN):
        event.update({"scribe_rc": "missing-binary", "status": "fallback", "error": f"{CLAUDE_BIN} not found"})
        return None

    prompt = (
        "Use the allowed ElevenLabs speech_to_text MCP tool to transcribe this local audio file "
        f"with model_id scribe_v1: {audio_path}\n\n"
        "Output ONLY the transcript text. No preamble, no labels, no closing remarks. "
        "If the tool returns structured JSON, output only the transcript text field."
    )
    env = oauth_env()
    env.pop("ANTHROPIC_API_KEY", None)
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                CLAUDE_BIN,
                "-p",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--allowed-tools",
                SCRIBE_TOOL,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        event.update({
            "scribe_rc": 124,
            "scribe_duration_s": time.monotonic() - started,
            "scribe_stderr": (exc.stderr or "")[:1200],
            "status": "fallback",
            "error": "Claude Scribe transcription timed out",
        })
        return None

    event.update({
        "scribe_rc": result.returncode,
        "scribe_duration_s": time.monotonic() - started,
        "scribe_stderr": (result.stderr or "")[:1200],
    })
    LLM_CALLS.append({
        "name": "claude-elevenlabs-scribe",
        "returncode": result.returncode,
        "stdout_len": len(result.stdout or ""),
        "stderr": (result.stderr or "")[:1200],
        "duration_s": event["scribe_duration_s"],
    })
    if result.returncode != 0:
        event.update({"status": "fallback", "error": f"Claude Scribe exited {result.returncode}"})
        return None

    transcript = (result.stdout or "").split("To resume this session:")[0].strip()
    if not transcript:
        event.update({"status": "fallback", "error": "Claude Scribe returned empty transcript"})
        return None
    atomic_write(transcript_path, transcript + "\n")
    event.update({
        "transcript_path": str(transcript_path.relative_to(VAULT_ROOT)),
        "transcript_chars": len(transcript),
        "status": "transcribed",
    })
    return transcript


def scribe_cap_error(event: dict[str, Any]) -> str | None:
    global SCRIBE_MINUTES_USED
    audio_s = event.get("audio_duration_s")
    if isinstance(audio_s, (int, float)):
        if audio_s > SCRIBE_ITEM_MAX_SECONDS:
            event.update({"status": "fallback", "error": f"audio duration {audio_s:.1f}s exceeds {SCRIBE_ITEM_MAX_SECONDS}s cap"})
            return event["error"]
        minutes = audio_s / 60.0
        if SCRIBE_MINUTES_USED + minutes > SCRIBE_RUN_MAX_MINUTES:
            event.update({"status": "fallback", "error": f"Scribe run cap would exceed {SCRIBE_RUN_MAX_MINUTES:.0f} minutes"})
            return event["error"]
        SCRIBE_MINUTES_USED += minutes
    return None


def ensure_youtube_transcript(item: dict[str, Any]) -> str | None:
    stem = youtube_cache_stem(item)
    transcript_path = TRANSCRIPTION_CACHE_DIR / f"{stem}.txt"
    cached = cache_read(transcript_path)
    if cached:
        return cached
    audio_path, event = download_youtube_audio(item, stem)
    if not audio_path:
        TRANSCRIPTION_EVENTS.append(event)
        return None
    cap_err = scribe_cap_error(event)
    if cap_err:
        TRANSCRIPTION_EVENTS.append(event)
        return None
    transcript = transcribe_youtube_audio(audio_path, transcript_path, event)
    if transcript:
        event["status"] = "ok"
    TRANSCRIPTION_EVENTS.append(event)
    return transcript


def ensure_podcast_transcript(item: dict[str, Any]) -> str | None:
    stem = cache_key(item.get("audio_url") or item.get("url") or item.get("item_id") or item.get("title") or "")
    transcript_path = TRANSCRIPTION_CACHE_DIR / f"{stem}.txt"
    cached = cache_read(transcript_path)
    if cached:
        return cached
    audio_path, event = download_podcast_audio(item, stem)
    if not audio_path:
        TRANSCRIPTION_EVENTS.append(event)
        return None
    cap_err = scribe_cap_error(event)
    if cap_err:
        TRANSCRIPTION_EVENTS.append(event)
        return None
    transcript = transcribe_youtube_audio(audio_path, transcript_path, event)
    if transcript:
        cache_write(CONTENT_CACHE_DIR / "podcast" / f"{stem}.txt", transcript)
        event["status"] = "ok"
    TRANSCRIPTION_EVENTS.append(event)
    return transcript


def is_youtube_item(item: dict[str, Any]) -> bool:
    return item.get("source_type") == "youtube-channel" or item.get("feed_type") == "youtube-channel"


def process_depth_item(item: dict[str, Any]) -> tuple[str, str | None, str | None]:
    if is_youtube_item(item):
        ensure_youtube_transcript(item)
    elif item.get("feed_type") == "podcast" and item.get("audio_url"):
        ensure_podcast_transcript(item)
    deep_text, content_source = deep_content_for_item(item)
    analysis, err = call_depth_analysis(item, deep_text, content_source)
    out_path = output_path_for(item)
    atomic_write(out_path, render_analysis_brief(item, analysis, content_source))
    return ("ok", str(out_path.relative_to(VAULT_ROOT)), err)


def process_skim_item(item: dict[str, Any]) -> tuple[str, str | None, str | None]:
    out_path = output_path_for(item)
    atomic_write(out_path, render_text_skim(item))
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
                    started = time.monotonic()
                    result = subprocess.run(
                        [KIMI_BIN, "--quiet", "--no-thinking", "-p", synth_prompt,
                         "--max-steps-per-turn", "5"],
                        capture_output=True, text=True, timeout=240, env=oauth_env(),
                    )
                    LLM_CALLS.append({
                        "name": "kimi-podcast-synthesize",
                        "returncode": result.returncode,
                        "stdout_len": len(result.stdout or ""),
                        "stderr": (result.stderr or "")[:1200],
                        "duration_s": time.monotonic() - started,
                    })
                    if result.returncode == 0:
                        out = result.stdout.split("To resume this session:")[0].strip()
                        if out:
                            atomic_write(out_path, render_podcast_full(item, out))
                            return ("ok", str(out_path.relative_to(VAULT_ROOT)), None)
                except subprocess.TimeoutExpired:
                    LLM_CALLS.append({
                        "name": "kimi-podcast-synthesize",
                        "returncode": "timeout",
                        "stdout_len": 0,
                        "stderr": "",
                        "duration_s": 240.0,
                    })
                    pass
        # Fall through to headline if transcription path failed
    atomic_write(out_path, render_podcast_headline(item))
    return ("ok", str(out_path.relative_to(VAULT_ROOT)), None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process feed-sweep items into briefs.")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max depth items to process this run (0 = dry-run, default 10)")
    parser.add_argument("--filter", default=None,
                        help="Only process items whose feed_name contains this substring")
    parser.add_argument("--podcasts-only", action="store_true")
    parser.add_argument("--blogs-only", action="store_true")
    parser.add_argument("--enable-transcription", action="store_true",
                        help="Run full ElevenLabs Scribe transcription on podcasts "
                        "(pay-per-minute; default is headline-only)")
    return parser.parse_args()


def item_from_triage(triage_item: dict[str, Any], raw_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = dict(raw_by_id.get(triage_item["item_id"], {}))
    meta = triage_item.get("feed_metadata", {})
    item.setdefault("feed_name", triage_item.get("source_name", ""))
    item.setdefault("feed_type", meta.get("feed_type", "rss-text"))
    item.setdefault("title", meta.get("title", ""))
    item.setdefault("url", meta.get("url", ""))
    item.setdefault("published_iso", meta.get("published", ""))
    item.setdefault("audio_url", meta.get("audio_url"))
    item.setdefault("summary_short", meta.get("summary", ""))
    item.setdefault("cadence_tag", meta.get("cadence_tag", "unknown"))
    item.setdefault("processor", meta.get("processor", "kimi-summarize"))
    item.setdefault("source_type", meta.get("source_type") or meta.get("feed_type"))
    item.setdefault("output_dir", "_state/podcast-briefs/" if item["feed_type"] == "podcast" else "_state/blog-summaries/")
    item.setdefault("item_id", triage_item["item_id"])
    item["triage_item_id"] = triage_item["item_id"]
    item["triage_tier"] = triage_item.get("tier", "skim")
    item["source_lane"] = triage_item.get("source_lane", "unknown")
    item["triage_reason"] = triage_item.get("reason", "")
    item["triage_entry"] = triage_item
    return item


def build_queue_from_triage(manifest: dict[str, Any], raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_by_id = {stable_item_id(item): item for item in raw_items}
    items = [item_from_triage(t, raw_by_id) for t in manifest.get("items", [])]
    order = {"depth": 0, "skim": 1, "drop": 2}
    return sorted(items, key=lambda i: (order.get(i.get("triage_tier", "skim"), 1), i.get("source_lane", ""), i.get("feed_name", "")))


def render_log(report: RunReport) -> str:
    lines = [f"# Content Processing — {DATE}", "",
             f"Run at: {datetime.now(timezone.utc).isoformat()}",
             "",
             "## Prompt time grounding",
             current_time_section(),
             "",
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
    if report.llm_calls:
        lines.append("")
        lines.append("## LLM calls")
        for c in report.llm_calls:
            lines.append(f"- **{c['name']}** rc={c['returncode']} stdout_len={c['stdout_len']} duration={c['duration_s']:.1f}s")
            if c.get("stderr"):
                lines.append("    - stderr:")
                lines.append("      ```")
                lines.append("      " + str(c["stderr"]).replace("\n", "\n      "))
                lines.append("      ```")
    if report.transcriptions:
        lines.append("")
        lines.append("## YouTube transcriptions")
        total_minutes = 0.0
        for event in report.transcriptions:
            audio_s = event.get("audio_duration_s")
            if isinstance(audio_s, (int, float)):
                total_minutes += float(audio_s) / 60.0
            lines.append(
                f"- **{str(event.get('title', ''))[:80]}** status={event.get('status')} "
                f"download_rc={event.get('download_rc')} scribe_rc={event.get('scribe_rc')} "
                f"audio_s={audio_s if audio_s is not None else 'unknown'} "
                f"transcript_chars={event.get('transcript_chars', 0)} "
                f"scribe_duration_s={event.get('scribe_duration_s', 0):.1f}"
            )
            if event.get("audio_path"):
                lines.append(f"    - audio: `{event['audio_path']}`")
            if event.get("transcript_path"):
                lines.append(f"    - transcript: `{event['transcript_path']}`")
            if event.get("error"):
                lines.append(f"    - error: {event['error']}")
            if event.get("scribe_stderr"):
                lines.append("    - scribe stderr:")
                lines.append("      ```")
                lines.append("      " + str(event["scribe_stderr"]).replace("\n", "\n      "))
                lines.append("      ```")
        lines.append(f"- Total Scribe audio minutes this run: {total_minutes:.2f}")
    if report.content_fetches:
        lines.append("")
        lines.append("## Deep content fetches")
        for event in report.content_fetches:
            lines.append(
                f"- **{str(event.get('title', ''))[:80]}** source={event.get('source')} "
                f"chars={event.get('chars', 0)} fallback={str(event.get('fallback')).lower()}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    items = load_new_items()
    triage = load_triage_manifest()
    if not items and not triage:
        print(f"No new-items file at {NEW_ITEMS_PATH}; nothing to do.")
        return 0

    processed = load_processed_set()
    queue: list[dict[str, Any]]
    skipped_count = 0
    if triage:
        queue = build_queue_from_triage(triage, items)
    else:
        queue = []
        for item in items:
            item["triage_item_id"] = item["item_id"]
            item["triage_tier"] = "depth" if item["feed_type"] in ("rss-text", "html-scrape") else "skim"
            queue.append(item)

    filtered: list[dict[str, Any]] = []
    depth_seen = 0
    for item in queue:
        processed_id = item.get("triage_item_id") or item.get("item_id")
        if processed_id in processed:
            if item.get("triage_tier") == "depth" and not output_has_structured_analysis(item):
                item = dict(item)
                item["needs_analysis_upgrade"] = True
            else:
                skipped_count += 1
                continue
        if args.filter and args.filter.lower() not in item["feed_name"].lower():
            continue
        if args.podcasts_only and item["feed_type"] != "podcast":
            continue
        if args.blogs_only and item["feed_type"] not in ("rss-text", "html-scrape"):
            continue
        if item.get("triage_tier") == "depth":
            if args.limit > 0 and depth_seen >= args.limit:
                item = dict(item)
                item["triage_tier"] = "skim"
            else:
                depth_seen += 1
        filtered.append(item)
    queue = filtered

    report = RunReport(
        items_total=len(items), items_processed=0,
        items_skipped=skipped_count, items_failed=0, duration_s=0.0,
    )
    run_start = time.monotonic()
    youtube_transcriptions_seen = 0
    depth_analysis_seen = 0

    for item in queue:
        item_start = time.monotonic()
        tier_name = item.get("triage_tier", "depth")
        if args.limit == 0:
            report.item_results.append(ItemResult(
                feed_name=item["feed_name"], item_id=item["item_id"],
                title=item["title"], url=item["url"],
                tier=tier_name,
                status="dry-run",
            ))
            continue

        print(f"Processing: [{item['feed_name']}] {item['title'][:80]}")
        is_youtube = is_youtube_item(item)
        if tier_name == "drop":
            status, out_path, err, tier = "skipped", None, "triage tier=drop", "drop"
        elif tier_name == "skim":
            if item["feed_type"] == "podcast":
                status, out_path, err = process_podcast_item(item, enable_transcription=False)
            else:
                status, out_path, err = process_skim_item(item)
            tier = "headline-only"
        elif depth_analysis_seen >= DEPTH_ANALYSIS_LIMIT:
            status, out_path, _ = process_skim_item(item)
            err = f"Depth analysis cap exceeded ({DEPTH_ANALYSIS_LIMIT}); used headline fallback"
            tier = "headline-only"
        elif is_youtube:
            if youtube_transcriptions_seen >= YOUTUBE_TRANSCRIPTION_LIMIT:
                status, out_path, _ = process_skim_item(item)
                err = f"YouTube transcription cap exceeded ({YOUTUBE_TRANSCRIPTION_LIMIT}); used headline fallback"
                tier = "headline-only"
            else:
                youtube_transcriptions_seen += 1
                depth_analysis_seen += 1
                status, out_path, err = process_depth_item(item)
                tier = "full"
        elif item["feed_type"] in ("rss-text", "html-scrape"):
            depth_analysis_seen += 1
            status, out_path, err = process_depth_item(item)
            tier = "full"
        elif item["feed_type"] == "podcast":
            depth_analysis_seen += 1
            status, out_path, err = process_depth_item(item)
            tier = "full"
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
            processed.add(item.get("triage_item_id") or item["item_id"])
        elif status == "failed":
            report.items_failed += 1

    report.duration_s = time.monotonic() - run_start
    report.llm_calls = LLM_CALLS
    report.transcriptions = TRANSCRIPTION_EVENTS
    report.content_fetches = CONTENT_FETCH_EVENTS
    save_processed_set(processed)
    atomic_write(LOG_PATH, render_log(report))
    print(f"\nLog: {LOG_PATH}")
    print(f"Processed: {report.items_processed}, Failed: {report.items_failed}, Skipped: {report.items_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
