"""Auto-capture handlers invoked by .claude/settings.json PostToolUse hooks.

Each handler reads tool input/output from environment variables Claude Code
provides to hook commands, atomically writes to the appropriate vault file.

Atomic writes per TOOLS.md: tmp + fsync + os.replace. Append paths additionally
use fcntl.flock on a sidecar lockfile so concurrent fan-out captures (multiple
PostToolUse hooks racing on the same daily file) cannot lose writes.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any


@contextlib.contextmanager
def _flock(path: Path):
    """Acquire an exclusive flock on a sidecar lockfile next to `path`.

    Yields after the lock is held; releases on context exit. Lockfile is created
    on demand and persists; that's fine — the inode is the lock identity.
    """
    lockpath = path.with_suffix(path.suffix + ".lock")
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lockpath), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _vault_root() -> Path:
    root = os.environ.get("CHRONO_VAULT_ROOT") or os.path.expanduser("~/Obsidian-Chrono")
    return Path(root)


def _slugify(text: str, max_len: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "untitled"


def _short_id() -> str:
    return f"{int(time.time()):x}"[-6:]


def _today() -> str:
    return date.today().isoformat()


def _atomic_append(path: Path, content: str) -> None:
    """Append content atomically with cross-process locking.

    Concurrent fan-out captures (multiple PostToolUse hooks racing on the same
    daily file) would lose writes without locking — read-concat-replace is
    inherently racy. fcntl.flock on a sidecar lockfile serializes all writers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _flock(path):
        existing = path.read_text() if path.exists() else ""
        new = existing + content
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _frontmatter(**fields: Any) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(repr(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# Phase 15.8: real Claude PostToolUse hook payload shapes vary by tool.
# Bash:    {tool_input: {command, description}, tool_response: {output, exit_code}}
# Edit:    {tool_input: {file_path, old_string, new_string}, tool_response: {...}}
# Agent:   {tool_input: {subagent_type, prompt, model}, tool_response: {final_text, ...}}
# These extraction helpers walk known keys + nested shapes so handlers don't
# need bespoke parsing per tool.

def _coalesce(d: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty value among `d[k]` for k in keys, or ''."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v if isinstance(v, str) else str(v)
    return ""


def _extract_input_field(event: dict[str, Any], *keys: str) -> str:
    """Pull a field from event['tool_input'] OR event['input'] OR event root."""
    for container_key in ("tool_input", "input"):
        container = event.get(container_key)
        if isinstance(container, dict):
            v = _coalesce(container, *keys)
            if v:
                return v
    return _coalesce(event, *keys)


def _extract_response_field(event: dict[str, Any], *keys: str) -> str:
    """Pull a field from event['tool_response'] OR event root."""
    container = event.get("tool_response")
    if isinstance(container, dict):
        v = _coalesce(container, *keys)
        if v:
            return v
    return _coalesce(event, *keys)


def normalize_event(event: dict[str, Any]) -> dict[str, str]:
    """Convert a raw Claude hook payload (or already-normalized event) into the
    flat canonical shape capture handlers expect.

    Returns a dict with the load-bearing string keys used by handlers:
    role, model, prompt, output, target, query, tool, command, file_path.
    Missing keys map to "" (empty string), never None.

    Examples:
        Bash PostToolUse: {tool_input: {command: "ls"}, tool_response: {output: "a\\nb"}}
        -> {prompt: "", output: "a\\nb", command: "ls", ...}

        Already-normalized: {role: "architect", prompt: "design X"}
        -> {role: "architect", prompt: "design X", ...}
    """
    return {
        "role": _extract_input_field(event, "role", "subagent_type") or _coalesce(event, "role", "subagent_type"),
        "model": _extract_input_field(event, "model") or _coalesce(event, "model"),
        "prompt": _extract_input_field(event, "prompt", "message", "query"),
        "output": _extract_response_field(event, "output", "final_text", "result", "stdout"),
        "target": _coalesce(event, "target"),
        "query": _extract_input_field(event, "query", "prompt"),
        "tool": _coalesce(event, "tool", "tool_name"),
        "command": _extract_input_field(event, "command"),
        "file_path": _extract_input_field(event, "file_path", "notebook_path", "path"),
    }


def handle_session_start(event: dict[str, Any]) -> None:
    """Append session header to sessions/<today>.md."""
    p = _vault_root() / "chrono" / "sessions" / f"{_today()}.md"
    header = (
        f"\n## Session start {time.strftime('%H:%M:%S')}\n"
        f"- model: {event.get('model', 'unknown')}\n"
        f"- cwd: {event.get('cwd', 'unknown')}\n"
        f"- first message: {event.get('first_message', '')[:200]}\n"
    )
    _atomic_append(p, header)


def handle_session_end(event: dict[str, Any]) -> None:
    """Append session footer."""
    p = _vault_root() / "chrono" / "sessions" / f"{_today()}.md"
    files = event.get("files_touched", [])
    footer = (
        f"\n## Session end {time.strftime('%H:%M:%S')}\n"
        f"- tokens used: {event.get('tokens_used', 'n/a')}\n"
        f"- files touched: {len(files)}\n"
        f"  " + "\n  ".join(f"- {f}" for f in files[:20])
        + ("\n" if files else "")
    )
    _atomic_append(p, footer)


def handle_dispatch(event: dict[str, Any]) -> None:
    """Append dispatch entry to dispatches/<today>.md.

    Accepts either the legacy normalized shape {role, model, prompt, output} or
    a raw Claude PostToolUse payload {tool_input, tool_response, ...}.
    """
    norm = normalize_event(event)
    p = _vault_root() / "chrono" / "dispatches" / f"{_today()}.md"
    role = norm["role"] or "unknown"
    entry = (
        f"\n## {time.strftime('%H:%M:%S')} — Dispatch: {role}\n"
        f"- model: {norm['model'] or 'unknown'}\n"
        f"- prompt: {norm['prompt'][:500]}\n"
        f"- output: {norm['output'][:1000]}\n"
    )
    _atomic_append(p, entry)


def handle_review(provider: str, event: dict[str, Any]) -> None:
    """Write review to reviews/<target>-<date>-<provider>-<short-id>.md."""
    norm = normalize_event(event)
    target = _slugify(norm["target"] or "untitled")
    fname = f"{target}-{_today()}-{provider}-{_short_id()}.md"
    p = _vault_root() / "chrono" / "reviews" / fname
    body = (
        _frontmatter(type="review", topic=target, date=_today(), status="active",
                     provider=provider, target=target)
        + f"\n# Review: {target} ({provider})\n\n"
        f"## Prompt\n\n{norm['prompt']}\n\n"
        f"## Output\n\n{norm['output']}\n"
    )
    _atomic_write(p, body)


def handle_research(event: dict[str, Any]) -> None:
    """Write research to research/<date>-<slug>.md."""
    norm = normalize_event(event)
    query = norm["query"] or norm["prompt"] or "untitled"
    slug = _slugify(query)
    fname = f"{_today()}-{slug}.md"
    p = _vault_root() / "chrono" / "research" / fname
    body = (
        _frontmatter(type="research", topic=slug, date=_today(), status="active")
        + f"\n# Research: {query}\n\n"
        f"## Tool\n\n{norm['tool'] or 'unknown'}\n\n"
        f"## Output\n\n{norm['output']}\n"
    )
    _atomic_write(p, body)


def main() -> None:
    """CLI entry point invoked by `.claude/settings.json` hooks.

    Usage: python plugins/_support/capture.py <handler> [provider]
    Reads event JSON from stdin (or CHRONO_HOOK_INPUT env var).
    """
    import sys
    handler = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = os.environ.get("CHRONO_HOOK_INPUT") or sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}
    if handler == "session_start":
        handle_session_start(event)
    elif handler == "session_end":
        handle_session_end(event)
    elif handler == "dispatch":
        handle_dispatch(event)
    elif handler == "review":
        provider = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        handle_review(provider, event)
    elif handler == "research":
        handle_research(event)
    else:
        print(f"unknown handler: {handler}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
