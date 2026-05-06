#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Reconcile `_state/active-tasks.json` from landed task responses."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
REGISTRY_PATH = STATE_DIR / "active-tasks.json"
CANONICAL_RESPONSE_STATUSES = {
    "completed",
    "completed_with_partials",
    "completed_with_notes",
    "needs_human",
    "BLOCKED",
    "cancelled",
}
TERMINAL_REGISTRY_STATUSES = {
    "complete",
    "completed",
    "completed_with_partials",
    "completed_with_notes",
    "needs_human",
    "BLOCKED",
    "cancelled",
    "canceled",
}


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


def load_registry() -> dict[str, Any]:
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def locked_registry():
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".lock")
    lock_fh = lock_path.open("w", encoding="utf-8")
    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    return lock_fh


def strip_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def canonical_status(raw: str) -> str:
    if raw == "complete":
        return "completed"
    if raw == "blocked":
        return "BLOCKED"
    if raw == "canceled":
        return "cancelled"
    return raw


def response_status(path: Path) -> str:
    return canonical_status(strip_frontmatter(read_text(path)).get("status", ""))


def response_ready(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age >= timedelta(seconds=60)


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def append_drift(task_id: str, detail: str) -> None:
    path = STATE_DIR / "cleanup-logs" / f"{utc_date()}-registry-drift.md"
    existing = read_text(path, f"# Registry Drift - {utc_date()}\n\n")
    atomic_write(path, existing + f"- {datetime.now(timezone.utc).isoformat()} {task_id}: {detail}\n")


def expected_response(task_id: str, entry: dict[str, Any]) -> Path:
    namespace = entry.get("compatibility_namespace") or "coding"
    return VAULT_ROOT / "departments" / str(namespace) / "outbox" / f"{task_id}-response.md"


def mapped_registry_status(status: str) -> str:
    return "complete" if status == "completed" else status


def reconcile(task_id_filter: str | None, dry_run: bool) -> tuple[int, list[str]]:
    with locked_registry() as _lock:
        registry = load_registry()
        now = datetime.now(timezone.utc)
        changed = 0
        messages: list[str] = []
        for task_id, raw_entry in registry.items():
            if task_id_filter and task_id != task_id_filter:
                continue
            if not isinstance(raw_entry, dict):
                continue
            if raw_entry.get("chrono_reconciled") is True:
                messages.append(f"skip chrono_reconciled {task_id}")
                continue
            current_status = str(raw_entry.get("status", ""))
            if current_status in TERMINAL_REGISTRY_STATUSES:
                continue
            response = expected_response(task_id, raw_entry)
            if response_ready(response):
                status = response_status(response)
                if status in CANONICAL_RESPONSE_STATUSES:
                    raw_entry["status"] = mapped_registry_status(status)
                    raw_entry["completed_at"] = datetime.fromtimestamp(response.stat().st_mtime, tz=timezone.utc).isoformat()
                    raw_entry["auto_reconciled_at"] = now.isoformat()
                    changed += 1
                    messages.append(f"reconciled {task_id} -> {raw_entry['status']}")
                continue
            if not response.exists():
                dispatched = parse_dt(raw_entry.get("dispatched_at"))
                if dispatched and now - dispatched > timedelta(hours=12):
                    if not dry_run:
                        append_drift(task_id, f"no response after >12h; status={current_status}")
                    messages.append(f"drift {task_id}")
        if changed and not dry_run:
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        return changed, messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    changed, messages = reconcile(args.task_id, args.dry_run)
    mode = "dry-run" if args.dry_run else "write"
    print(f"registry-reconciler {mode}: changes={changed}")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
