#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Deliver the daily newsletter to Telegram as HTML text plus MP3 audio.

Uses Telegram Bot API with HTML parse_mode. Secrets are read from environment:
`CHRONO_TG_TOKEN` and `CHRONO_TG_CHAT_ID`. Full tokens are never logged.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import socket
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
AUDIO_ROOT = Path(os.environ.get("VIBE_SQUAD_AUDIO_ROOT", Path.home() / "Vibe-Squad-Audio"))
MAX_TELEGRAM_TEXT = 4096


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


def is_trivial(body: str) -> bool:
    stripped = re.sub(r"\s+", " ", body).strip().lower()
    return not stripped or ("no notable signal today" in stripped and len(stripped) < 600)


def convert_inline(markdown: str) -> str:
    placeholders: list[tuple[str, str]] = []

    def stash(value: str) -> str:
        token = f"@@TG{len(placeholders)}@@"
        placeholders.append((token, value))
        return token

    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: stash(f'<a href="{html.escape(m.group(2), quote=True)}">{html.escape(m.group(1))}</a>'),
        markdown,
    )
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<b>{m.group(1)}</b>", text)
    text = re.sub(r"__([^_]+)__", lambda m: f"<i>{m.group(1)}</i>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: f"<i>{m.group(1)}</i>", text)
    for token, value in placeholders:
        text = text.replace(html.escape(token), value)
    return text


def markdown_to_telegram_html(body: str, subject: str) -> str:
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    lines: list[str] = []
    if subject:
        lines += [f"<b>{html.escape(subject)}</b>", ""]
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line:
            lines.append("")
            continue
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading:
            lines.append(f"<b>{convert_inline(heading.group(1))}</b>")
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet:
            lines.append(f"• {convert_inline(bullet.group(1))}")
            continue
        lines.append(convert_inline(line))
    text = "\n".join(lines)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text


def split_messages(text: str) -> list[str]:
    limit = MAX_TELEGRAM_TEXT - 196
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < 1000:
            cut = remaining.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"({idx}/{total})\n{chunk}" for idx, chunk in enumerate(chunks, 1)]


def api_post(token: str, method: str, data: dict[str, Any], files: dict[str, Path] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if not files:
        encoded = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=encoded)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            return {"ok": False, "error_code": exc.code, "description": body}
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            return {"ok": False, "error_code": "network", "method": method, "description": str(exc)}

    boundary = f"----VibeSquad{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in data.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    for field, path in files.items():
        filename = path.name
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode())
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        return {"ok": False, "error_code": exc.code, "description": body_text}
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {"ok": False, "error_code": "network", "method": method, "description": str(exc)}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def plain_text_from_html(text: str) -> str:
    text = re.sub(r'<a\s+href="[^"]*">([^<]+)</a>', r"\1", text)
    text = re.sub(r"</?(?:b|i)>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def send_message_part(token: str, chat_id: str, text: str) -> dict[str, Any]:
    response = api_post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    })
    if response.get("ok"):
        return response
    description = str(response.get("description") or "")
    if "parse" not in description.lower() and "entity" not in description.lower():
        return response
    fallback = api_post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": plain_text_from_html(text),
        "disable_web_page_preview": "true",
    })
    if fallback.get("ok"):
        fallback["fallback_parse_mode"] = "plain"
    return fallback


def render_log(date: str, status: str, **kwargs: Any) -> str:
    lines = [f"# Telegram Deliver - {date}", "", current_time_section(), "", f"Status: {status}"]
    for key, value in kwargs.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def audio_path_for(date: str) -> Path:
    return AUDIO_ROOT / date[:7] / f"{date[-2:]}.mp3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    args = parser.parse_args()
    date = args.date or utc_date()
    newsletter_path = STATE_DIR / f"newsletter-{date}.md"
    log_path = STATE_DIR / "cleanup-logs" / f"{date}-telegram-deliver.md"
    marker = STATE_DIR / f"telegram-deliver-{date}.delivered"
    progress_path = STATE_DIR / f"telegram-deliver-{date}.progress.json"
    ping_marker = STATE_DIR / "telegram-deliver-script-ping.delivered"

    token = os.environ.get("CHRONO_TG_TOKEN", "")
    chat_id = os.environ.get("CHRONO_TG_CHAT_ID", "")
    chat_tail = chat_id[-4:] if chat_id else "none"
    if marker.exists():
        atomic_write(log_path, render_log(date, "already-delivered", marker=marker, chat_id_tail=chat_tail))
        print("Telegram deliver: already delivered")
        return 0
    if not token or not chat_id:
        atomic_write(log_path, render_log(date, "failed", reason="missing Telegram env", chat_id_tail=chat_tail))
        print("telegram-deliver failed: missing CHRONO_TG_TOKEN or CHRONO_TG_CHAT_ID", file=sys.stderr)
        return 1

    raw = read_text(newsletter_path)
    if not raw.strip():
        atomic_write(log_path, render_log(date, "skipped", reason=f"missing newsletter {newsletter_path}", chat_id_tail=chat_tail))
        print("Telegram deliver skipped: missing newsletter")
        return 0
    meta, body = strip_frontmatter(raw)
    if is_trivial(body):
        atomic_write(log_path, render_log(date, "skipped", reason="nothing substantive to deliver", chat_id_tail=chat_tail))
        print("Telegram deliver skipped: no substantive newsletter")
        return 0

    progress = load_json(progress_path, {})
    message_ids: list[int] = list(progress.get("message_ids") or [])
    ping_id: int | None = None
    if not ping_marker.exists():
        ping = api_post(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "Vibe Squad nightly delivery channel armed — first newsletter coming next 03:00 PDT.",
            "disable_web_page_preview": "true",
        })
        if not ping.get("ok"):
            atomic_write(log_path, render_log(date, "failed", phase="ping", response=json.dumps(ping), chat_id_tail=chat_tail))
            print("telegram-deliver failed: ping failed", file=sys.stderr)
            return 1
        ping_id = ping.get("result", {}).get("message_id")
        atomic_write(ping_marker, json.dumps({"date": date, "message_id": ping_id, "sent_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
        time.sleep(0.5)

    html_text = markdown_to_telegram_html(body, meta.get("subject", ""))
    parts = split_messages(html_text)
    sent_parts = int(progress.get("sent_parts") or 0)
    for idx, part in enumerate(parts):
        if idx < sent_parts:
            continue
        response = send_message_part(token, chat_id, part)
        if not response.get("ok"):
            atomic_write(log_path, render_log(date, "failed", phase="sendMessage", response=json.dumps(response), message_ids=message_ids, chat_id_tail=chat_tail))
            print("telegram-deliver failed: sendMessage failed", file=sys.stderr)
            return 1
        message_ids.append(response.get("result", {}).get("message_id"))
        atomic_write(progress_path, json.dumps({
            "date": date,
            "sent_parts": idx + 1,
            "message_ids": message_ids,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2) + "\n")
        time.sleep(0.6)

    audio = audio_path_for(date)
    audio_response: dict[str, Any] = {}
    audio_file_id = None
    audio_status = "missing"
    if audio.exists():
        audio_response = api_post(token, "sendAudio", {
            "chat_id": chat_id,
            "title": f"Vibe Squad — {date}",
            "performer": "Chrono",
        }, files={"audio": audio})
        if audio_response.get("ok"):
            audio_status = "ok"
            audio_file_id = audio_response.get("result", {}).get("audio", {}).get("file_id")
        else:
            audio_status = "failed"
    if audio_status != "ok":
        follow = api_post(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "(audio delivery failed; text-only this morning)",
            "disable_web_page_preview": "true",
        })
        if follow.get("ok"):
            message_ids.append(follow.get("result", {}).get("message_id"))

    marker_payload = {
        "date": date,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "message_ids": message_ids,
        "audio_status": audio_status,
        "audio_file_id": audio_file_id,
    }
    atomic_write(marker, json.dumps(marker_payload, indent=2) + "\n")
    atomic_write(log_path, render_log(
        date,
        "ok" if audio_status == "ok" else "text-only",
        chat_id_tail=chat_tail,
        ping_message_id=ping_id,
        message_ids=message_ids,
        audio_status=audio_status,
        audio_file_id=audio_file_id,
        audio_bytes=audio.stat().st_size if audio.exists() else 0,
        part_count=len(parts),
        text_chars=len(html_text),
        audio_response=json.dumps(audio_response)[:2000] if audio_response and not audio_response.get("ok") else "",
    ))
    print(f"Telegram deliver: text messages={message_ids}, audio_status={audio_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
