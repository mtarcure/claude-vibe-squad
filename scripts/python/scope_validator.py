#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Warn when response-reported file changes fall outside packet write_scope."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
SECTION_RE = re.compile(r"(?i)^#{1,6}\s+.*(files?\s+(modified|created|changed)|deliverables|changes|modified).*$")
TERMINAL_HEADING_RE = re.compile(r"^#{1,6}\s+")


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


def strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    lines = match.group(1).splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if ":" not in line:
            idx += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            block: list[str] = []
            idx += 1
            while idx < len(lines) and (lines[idx].startswith(" ") or lines[idx].startswith("-")):
                block.append(lines[idx])
                idx += 1
            meta[key] = "\n".join(block)
            continue
        meta[key] = value.strip('"').strip("'")
        idx += 1
    return meta, text[match.end():]


def parse_scope(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return []
    try:
        value = ast.literal_eval(raw)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    except (ValueError, SyntaxError):
        pass
    scopes: list[str] = []
    for line in raw.splitlines():
        item = line.strip()
        if item.startswith("-"):
            item = item[1:].strip()
        if item:
            scopes.append(item.strip('"').strip("'"))
    return scopes


def packet_path(task_id: str, namespace: str) -> Path | None:
    for state in ("archive", "inbox", "active"):
        path = VAULT_ROOT / "departments" / namespace / state / f"{task_id}.md"
        if path.exists():
            return path
    return None


def response_path(task_id: str, namespace: str) -> Path:
    return VAULT_ROOT / "departments" / namespace / "outbox" / f"{task_id}-response.md"


def extract_reported_files(response_body: str) -> list[str]:
    files: list[str] = []
    lines = response_body.splitlines()
    idx = 0
    while idx < len(lines):
        if not SECTION_RE.match(lines[idx].strip()):
            idx += 1
            continue
        idx += 1
        while idx < len(lines) and not TERMINAL_HEADING_RE.match(lines[idx].strip()):
            match = re.match(r"^\s*[-*]\s+`?([^`]+?)`?\s*$", lines[idx])
            if match:
                files.append(match.group(1).strip())
            idx += 1
    return files


def in_scope(path: str, scopes: list[str]) -> bool:
    norm = path.strip().lstrip("./")
    for scope in scopes:
        pattern = scope.strip().lstrip("./")
        if not pattern:
            continue
        if fnmatch.fnmatch(norm, pattern) or fnmatch.fnmatch(path, scope):
            return True
        if pattern.endswith("/") and norm.startswith(pattern):
            return True
        if norm == pattern:
            return True
    return False


def append_warning(task_id: str, namespace: str, out_of_scope: list[str]) -> None:
    path = STATE_DIR / "cleanup-logs" / f"{utc_date()}-scope-drift.md"
    existing = read_text(path, f"# Scope Drift - {utc_date()}\n\n")
    detail = ", ".join(out_of_scope)
    line = f"- {datetime.now(timezone.utc).isoformat()} WARN task_id={task_id} namespace={namespace} out_of_scope={detail}\n"
    atomic_write(path, existing + line)


def validate(task_id: str, namespace: str) -> list[str]:
    packet = packet_path(task_id, namespace)
    if not packet:
        return []
    meta, _ = strip_frontmatter(read_text(packet))
    scopes = parse_scope(meta.get("write_scope", ""))
    if not scopes:
        return []
    _, response_body = strip_frontmatter(read_text(response_path(task_id, namespace)))
    files = extract_reported_files(response_body)
    out_of_scope = [path for path in files if not in_scope(path, scopes)]
    if out_of_scope:
        append_warning(task_id, namespace, out_of_scope)
    return out_of_scope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("namespace")
    args = parser.parse_args()
    out_of_scope = validate(args.task_id, args.namespace)
    if out_of_scope:
        print(f"⚠️ scope-drift: {args.task_id} outside write_scope: {', '.join(out_of_scope)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
