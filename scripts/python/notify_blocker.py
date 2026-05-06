#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Telegram blocker notification helper for outbox-watcher."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
TERMINAL_BLOCKERS = {"needs_human", "BLOCKED"}


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
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


def response_path(task_id: str, namespace: str) -> Path:
    return VAULT_ROOT / "departments" / namespace / "outbox" / f"{task_id}-response.md"


def task_meta(task_id: str, namespace: str) -> dict[str, str]:
    for state in ("archive", "active", "inbox"):
        path = VAULT_ROOT / "departments" / namespace / state / f"{task_id}.md"
        if path.exists():
            meta, _ = strip_frontmatter(read_text(path))
            return meta
    return {}


def first_paragraph(body: str) -> str:
    body = body.strip()
    for para in re.split(r"\n\s*\n", body):
        text = re.sub(r"(?m)^#+\s*", "", para).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            return text[:200]
    return ""


def quiet_hours_active(now: datetime) -> bool:
    # Quiet hours are UTC by contract: default 05-14 maps to PDT 22-07.
    raw = os.environ.get("VIBE_SQUAD_NOTIFICATIONS_QUIET_HOURS", "05-14")
    match = re.match(r"^(\d{1,2})-(\d{1,2})$", raw.strip())
    if not match:
        return False
    start, end = int(match.group(1)) % 24, int(match.group(2)) % 24
    hour = now.hour
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def append_batch(task_id: str, namespace: str, status: str, reason: str, message: str) -> None:
    path = STATE_DIR / "notification-batch-pending.md"
    existing = read_text(path)
    entry = (
        f"\n\n## {datetime.now(timezone.utc).isoformat()} — {task_id}\n"
        f"- namespace: {namespace}\n"
        f"- status: {status}\n"
        f"- reason: {reason}\n\n"
        f"{message}\n"
    )
    atomic_write(path, existing.rstrip() + entry + "\n")


def prune_rate_log(path: Path, now: datetime) -> list[str]:
    raw = load_json(path, [])
    timestamps = [str(item) for item in raw] if isinstance(raw, list) else []
    kept: list[str] = []
    cutoff = now - timedelta(hours=1)
    for value in timestamps:
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            kept.append(value)
    return kept


def send_telegram(token: str, chat_id: str, text: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error_code": exc.code, "description": exc.read().decode(errors="replace")}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error_code": "network", "description": str(exc)}


def redact_secrets(value: str) -> str:
    return re.sub(r"bot[A-Za-z0-9:_-]+/", "bot<REDACTED>/", value)


def render_log_line(task_id: str, namespace: str, status: str, action: str, detail: str = "") -> str:
    return (
        f"- {datetime.now(timezone.utc).isoformat()} task_id={task_id} namespace={namespace} "
        f"status={status} action={action}{(' detail=' + detail) if detail else ''}\n"
    )


def append_log(task_id: str, namespace: str, status: str, action: str, detail: str = "") -> None:
    path = STATE_DIR / "cleanup-logs" / f"{utc_date()}-notify-blocker.md"
    existing = read_text(path, f"# Notify Blocker - {utc_date()}\n\n")
    atomic_write(path, existing + render_log_line(task_id, namespace, status, action, detail))


def lock_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("namespace")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    notified = STATE_DIR / "notified" / f"{args.task_id}.notified"
    task_lock = lock_file(STATE_DIR / "notified" / f"{args.task_id}.lock")
    try:
        if notified.exists():
            age = now - datetime.fromtimestamp(notified.stat().st_mtime, tz=timezone.utc)
            if age < timedelta(hours=24):
                return 0

        response = response_path(args.task_id, args.namespace)
        response_meta, response_body = strip_frontmatter(read_text(response))
        status = response_meta.get("status", "unknown")
        if status not in TERMINAL_BLOCKERS:
            return 0
        meta = task_meta(args.task_id, args.namespace)
        specialist = meta.get("specialist", "unknown-specialist")
        model = meta.get("to_model", "unknown-model")
        summary = first_paragraph(response_body)
        message = (
            f"🚨 BLOCKER — {args.task_id}\n"
            f"{specialist} on {model} reports: {status}\n"
            f"{summary}\n"
            "Reply or wake chrono to act."
        )

        rate_path = STATE_DIR / "notification-rate-log.json"
        rate_lock = lock_file(rate_path.with_suffix(rate_path.suffix + ".lock"))
        try:
            recent = prune_rate_log(rate_path, now)
            if len(recent) >= 5:
                append_batch(args.task_id, args.namespace, status, "rate-limit", message)
                atomic_write(notified, "")
                append_log(args.task_id, args.namespace, status, "batched", "rate-limit")
                return 0
            if quiet_hours_active(now):
                append_batch(args.task_id, args.namespace, status, "quiet-hours", message)
                atomic_write(notified, "")
                append_log(args.task_id, args.namespace, status, "batched", "quiet-hours")
                return 0

            token = os.environ.get("CHRONO_TG_TOKEN", "")
            chat_id = os.environ.get("CHRONO_TG_CHAT_ID", "")
            chat_tail = chat_id[-4:] if chat_id else "none"
            if not token or not chat_id:
                append_batch(args.task_id, args.namespace, status, "missing-env", message)
                append_log(args.task_id, args.namespace, status, "batched", f"missing-env chat_tail={chat_tail}")
                return 1

            result = send_telegram(token, chat_id, message)
            if result.get("ok"):
                recent.append(now.isoformat())
                atomic_write(rate_path, json.dumps(recent, indent=2) + "\n")
                atomic_write(notified, "")
                message_id = result.get("result", {}).get("message_id")
                append_log(args.task_id, args.namespace, status, "pushed", f"message_id={message_id} chat_tail={chat_tail}")
                print(message)
                return 0
            append_batch(args.task_id, args.namespace, status, "telegram-failed", message)
            append_log(args.task_id, args.namespace, status, "failed", redact_secrets(json.dumps(result))[:500])
            return 1
        finally:
            rate_lock.close()
    finally:
        task_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
