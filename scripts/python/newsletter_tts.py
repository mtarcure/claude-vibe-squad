#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Synthesize the daily podcast script to MP3 via ElevenLabs MCP.

The script calls headless Claude with only
`mcp__plugin_chrono-content-engineer_elevenlabs__text_to_speech` allowed.
Voice policy: request ElevenLabs Nate (`Ifu36BnEjjIY932etsqk`) on `eleven_v3`
for a natural podcast read, and record the voice/model returned by the tool
when available. Defaults are tuned for podcast feel per operator feedback
2026-05-06: stability=0.4, similarity_boost=0.85, style=0.55,
use_speaker_boost=true. Operator can override with
`VIBE_SQUAD_TTS_VOICE_ID`, `VIBE_SQUAD_TTS_STABILITY`,
`VIBE_SQUAD_TTS_SIMILARITY`, `VIBE_SQUAD_TTS_STYLE`, and
`VIBE_SQUAD_TTS_SPEAKER_BOOST`; legacy `ELEVENLABS_NEWSLETTER_*` voice/model
overrides are still honored. Operator fallback voice options:
`fVVjLtJgnQI61CoImgHU`
(American male, high_quality), `Tx7VLgfksXHVnoY6jDGU` (Conversational Joe,
British RP; explicit opt-in), and `pNInz6obpgDQGcFmaJgB` (Adam, prior default
legacy narrator). Audio is retained under
`~/Vibe-Squad-Audio/<YYYY-MM>/<DD>.mp3` with an `index.json` audit manifest.
Retention: MP3 files older than 14 days are deleted by this script after each
successful run to keep the local cache organized.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
AUDIO_ROOT = Path(os.environ.get("VIBE_SQUAD_AUDIO_ROOT", Path.home() / "Vibe-Squad-Audio"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
TTS_TOOL = "mcp__plugin_chrono-content-engineer_elevenlabs__text_to_speech"
VOICE_NAME = os.environ.get("VIBE_SQUAD_TTS_VOICE_NAME", os.environ.get("ELEVENLABS_NEWSLETTER_VOICE_NAME", "Nate"))
VOICE_ID = os.environ.get("VIBE_SQUAD_TTS_VOICE_ID", os.environ.get("ELEVENLABS_NEWSLETTER_VOICE_ID", "Ifu36BnEjjIY932etsqk"))
MODEL_ID = os.environ.get("VIBE_SQUAD_TTS_MODEL_ID", os.environ.get("ELEVENLABS_NEWSLETTER_MODEL_ID", "eleven_v3"))
MAX_TTS_CHARS = 8_000
RETENTION_DAYS = 14


def env_float(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


VOICE_SETTINGS = {
    "stability": env_float("VIBE_SQUAD_TTS_STABILITY", "0.4"),
    "similarity_boost": env_float("VIBE_SQUAD_TTS_SIMILARITY", "0.85"),
    "style": env_float("VIBE_SQUAD_TTS_STYLE", "0.55"),
    "use_speaker_boost": env_bool("VIBE_SQUAD_TTS_SPEAKER_BOOST", "true"),
}


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_time_section() -> str:
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    mode = "wb" if isinstance(content, bytes) else "w"
    with tmp.open(mode) as fh:
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


def speech_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"\1.", text, flags=re.M)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def oauth_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def strip_json(raw: str) -> str:
    raw = (raw or "").split("To resume this session:")[0].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw


def call_claude_tts(text: str) -> tuple[int, str, str, float]:
    if not shutil.which(CLAUDE_BIN):
        return 127, "", f"{CLAUDE_BIN} not found", 0.0
    prompt = (
        "Use the allowed ElevenLabs text_to_speech MCP tool to synthesize the podcast script below as MP3. "
        f"Use model_id {MODEL_ID}. Use voice {VOICE_NAME} with voice_id {VOICE_ID}. "
        "Pass these exact voice settings in the text_to_speech call: "
        f"{json.dumps(VOICE_SETTINGS, sort_keys=True)}. "
        "Aim for a natural conversational podcast read, not a formal newsreader style. "
        "Return JSON only with any available fields: "
        "audio_url, file_path, audio_base64, voice_id, voice_name, model_id, duration_seconds, voice_settings.\n\n"
        f"{current_time_section()}\n\n"
        f"PODCAST_SCRIPT:\n{text}"
    )
    start = time.monotonic()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--output-format", "text", "--no-session-persistence", "--allowed-tools", TTS_TOOL],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            env=oauth_env(),
        )
        return result.returncode, result.stdout or "", result.stderr or "", time.monotonic() - start
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", (exc.stderr or "") + "\nclaude TTS timed out after 600s", time.monotonic() - start


def parse_payload(stdout: str) -> dict[str, Any]:
    try:
        data = json.loads(strip_json(stdout))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        url = re.search(r"https?://\S+", stdout or "")
        path = re.search(r"(/[^\s`]+\.mp3)", stdout or "")
        return {
            "audio_url": url.group(0).rstrip(").,") if url else None,
            "file_path": path.group(1) if path else None,
        }


def write_audio_from_payload(payload: dict[str, Any], out_path: Path) -> None:
    b64 = payload.get("audio_base64") or payload.get("base64")
    if isinstance(b64, str) and b64.strip():
        atomic_write(out_path, base64.b64decode(b64))
        return
    src = payload.get("file_path") or payload.get("path")
    if isinstance(src, str) and src:
        source_path = Path(src).expanduser()
        if source_path.exists():
            atomic_write(out_path, source_path.read_bytes())
            return
    url = payload.get("audio_url") or payload.get("url")
    if isinstance(url, str) and url.startswith("http"):
        with urllib.request.urlopen(url, timeout=120) as resp:
            atomic_write(out_path, resp.read())
        return
    raise ValueError("TTS response did not include audio_base64, file_path, or audio_url")


def audio_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def load_index() -> list[dict[str, Any]]:
    path = AUDIO_ROOT / "index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def update_index(entry: dict[str, Any]) -> None:
    rows = [
        row for row in load_index()
        if isinstance(row, dict)
        and row.get("date") != entry.get("date")
        and (not row.get("mp3_path") or Path(str(row.get("mp3_path"))).exists())
    ]
    rows.append(entry)
    rows.sort(key=lambda r: str(r.get("date", "")))
    atomic_write(AUDIO_ROOT / "index.json", json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


def existing_index_entry(date: str) -> dict[str, Any]:
    for row in load_index():
        if isinstance(row, dict) and row.get("date") == date:
            return row
    return {}


def cleanup_old_audio(now: datetime) -> list[str]:
    removed: list[str] = []
    cutoff = now - timedelta(days=RETENTION_DAYS)
    if not AUDIO_ROOT.exists():
        return removed
    for path in AUDIO_ROOT.glob("*/*.mp3"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
            except OSError:
                continue
            removed.append(str(path))
    return removed


def render_log(date: str, status: str, **kwargs: Any) -> str:
    lines = [f"# Newsletter TTS - {date}", "", current_time_section(), "", f"Status: {status}"]
    for key, value in kwargs.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--force", action="store_true", help="regenerate even when the dated MP3 already exists")
    args = parser.parse_args()
    date = args.date or utc_date()
    script_path = STATE_DIR / f"podcast-script-{date}.md"
    newsletter_path = STATE_DIR / f"newsletter-{date}.md"
    log_path = STATE_DIR / "cleanup-logs" / f"{date}-newsletter-tts.md"
    month, day = date[:7], date[-2:]
    out_path = AUDIO_ROOT / month / f"{day}.mp3"

    raw = read_text(script_path)
    if not raw.strip():
        atomic_write(log_path, render_log(date, "skipped", reason=f"missing podcast script {script_path}"))
        print(f"Newsletter TTS skipped: missing {script_path}")
        return 0
    newsletter_meta, _ = strip_frontmatter(read_text(newsletter_path))
    _, body = strip_frontmatter(raw)
    raw_text = speech_text(body)
    text = raw_text[:MAX_TTS_CHARS]
    chars_truncated = max(0, len(raw_text) - len(text))
    source_hash = text_hash(text)
    if not text or "No notable signal today" in text[:200]:
        atomic_write(log_path, render_log(date, "skipped", reason="nothing substantive to synthesize"))
        print("Newsletter TTS skipped: no substantive newsletter")
        return 0
    existing = existing_index_entry(date)
    reusable = (
        out_path.exists()
        and out_path.stat().st_size > 0
        and existing.get("input_sha256") == source_hash
        and existing.get("model_id") == MODEL_ID
        and existing.get("voice_id") == VOICE_ID
        and existing.get("voice_settings") == VOICE_SETTINGS
    )
    if reusable and not args.force:
        size = out_path.stat().st_size
        audio_s = audio_duration(out_path)
        removed = cleanup_old_audio(datetime.now(timezone.utc))
        update_index({
            "date": date,
            "mp3_path": str(out_path),
            "file_size_bytes": size,
            "duration_seconds": audio_s,
            "subject": newsletter_meta.get("subject", ""),
            "input_path": str(script_path),
            "input_sha256": source_hash,
            "voice_name": VOICE_NAME,
            "voice_id": VOICE_ID,
            "model_id": MODEL_ID,
            "voice_settings": VOICE_SETTINGS,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reused_existing": True,
        })
        atomic_write(log_path, render_log(
            date,
            "already-exists",
            chars_available=len(raw_text),
            chars_sent=len(text),
            chars_truncated=chars_truncated,
            mp3_path=out_path,
            mp3_file_size=size,
            audio_duration_s=audio_s,
            voice_id=VOICE_ID,
            voice_name=VOICE_NAME,
            model_id=MODEL_ID,
            stability=VOICE_SETTINGS["stability"],
            similarity_boost=VOICE_SETTINGS["similarity_boost"],
            style=VOICE_SETTINGS["style"],
            use_speaker_boost=VOICE_SETTINGS["use_speaker_boost"],
            input_path=script_path,
            cleaned_old_files=len(removed),
        ))
        print(f"Newsletter TTS: {out_path} (already exists)")
        return 0

    rc, stdout, stderr, duration = call_claude_tts(text)
    if rc != 0:
        atomic_write(log_path, render_log(
            date,
            "failed",
            chars_sent=len(text),
            requested_voice_name=VOICE_NAME,
            requested_voice_id=VOICE_ID,
            model_id=MODEL_ID,
            stability=VOICE_SETTINGS["stability"],
            similarity_boost=VOICE_SETTINGS["similarity_boost"],
            style=VOICE_SETTINGS["style"],
            use_speaker_boost=VOICE_SETTINGS["use_speaker_boost"],
            returncode=rc,
            duration_s=f"{duration:.1f}",
            stderr=stderr[:4000],
            stdout=stdout[:1000],
        ))
        print(f"newsletter-tts failed: claude exited {rc}", file=sys.stderr)
        return 1
    payload = parse_payload(stdout)
    try:
        write_audio_from_payload(payload, out_path)
    except Exception as exc:
        atomic_write(log_path, render_log(
            date,
            "failed",
            chars_sent=len(text),
            requested_voice_name=VOICE_NAME,
            requested_voice_id=VOICE_ID,
            model_id=MODEL_ID,
            stability=VOICE_SETTINGS["stability"],
            similarity_boost=VOICE_SETTINGS["similarity_boost"],
            style=VOICE_SETTINGS["style"],
            use_speaker_boost=VOICE_SETTINGS["use_speaker_boost"],
            returncode=rc,
            duration_s=f"{duration:.1f}",
            error=str(exc),
            stderr=stderr[:4000],
            stdout=stdout[:2000],
        ))
        print(f"newsletter-tts failed: {exc}", file=sys.stderr)
        return 1

    size = out_path.stat().st_size
    audio_s = audio_duration(out_path)
    removed = cleanup_old_audio(datetime.now(timezone.utc))
    entry = {
        "date": date,
        "mp3_path": str(out_path),
        "file_size_bytes": size,
        "duration_seconds": audio_s,
        "subject": newsletter_meta.get("subject", ""),
        "input_path": str(script_path),
        "input_sha256": source_hash,
        "voice_name": VOICE_NAME,
        "voice_id": payload.get("voice_id") or VOICE_ID,
        "model_id": payload.get("model_id") or MODEL_ID,
        "voice_settings": payload.get("voice_settings") if isinstance(payload.get("voice_settings"), dict) else VOICE_SETTINGS,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    update_index(entry)
    atomic_write(log_path, render_log(
        date,
        "ok",
        chars_available=len(raw_text),
        chars_sent=len(text),
        chars_truncated=chars_truncated,
        requested_voice_name=VOICE_NAME,
        requested_voice_id=VOICE_ID,
        voice_id=payload.get("voice_id") or payload.get("voice_name") or VOICE_ID,
        voice_name=payload.get("voice_name") or VOICE_NAME,
        model_id=payload.get("model_id") or MODEL_ID,
        stability=VOICE_SETTINGS["stability"],
        similarity_boost=VOICE_SETTINGS["similarity_boost"],
        style=VOICE_SETTINGS["style"],
        use_speaker_boost=VOICE_SETTINGS["use_speaker_boost"],
        input_path=script_path,
        mp3_path=out_path,
        mp3_file_size=size,
        audio_duration_s=audio_s,
        returncode=rc,
        subprocess_duration_s=f"{duration:.1f}",
        stderr=(stderr or "")[:2000],
        cleaned_old_files=len(removed),
    ))
    print(f"Newsletter TTS: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
