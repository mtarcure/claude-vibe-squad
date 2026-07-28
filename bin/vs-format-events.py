#!/usr/bin/env python3
"""Format a board spawn's --json event stream into a readable, CLI-like view.

Reads log lines on stdin (as `tail -f` feeds them) and prints human-readable,
coloured lines — agent messages, shell commands, file writes, tool calls, turn
summaries — instead of raw JSON. Non-JSON lines pass through unchanged, so claude/
gemini/kimi human-text logs still render. Lane-agnostic on the common keys.
"""
import json
import sys


def c(text, code):
    return f"\033[{code}m{text}\033[0m"


def first_line(value, limit=240):
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    value = str(value).strip()
    return (value.splitlines()[0] if value else "")[:limit]


def _tool_hint(inp):
    """Short one-line hint for a Claude tool_use block's `input`."""
    if isinstance(inp, dict):
        for key in ("file_path", "command", "path"):
            if inp.get(key):
                return first_line(inp[key])
        for value in inp.values():
            if value:
                return first_line(value)
        return ""
    return first_line(inp) if inp else ""


def _tool_result_text(content):
    """tool_result.content is either a bare string or a list of text blocks."""
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict)]
        return first_line(" ".join(p for p in parts if p))
    return first_line(content) if content else ""


def emit_claude(obj):
    """Render the Claude Agent SDK stream-json schema.

    Top-level `assistant`/`user` lines carry a `message.content` list of blocks
    (text / tool_use / thinking / tool_result); one line can hold several. Other
    top-level types (system/thinking_tokens, rate_limit_event, result, ...) are
    viewer noise and are skipped. Reuses the same emoji/colour vocabulary as the
    item-schema branches for a consistent transcript.
    """
    etype = obj.get("type", "")
    if etype not in ("assistant", "user"):
        return  # system / rate_limit_event / result / fallback → noise, skip
    for block in obj.get("message", {}).get("content", []) or []:
        if not isinstance(block, dict):
            continue  # malformed block: never crash the viewer
        btype = block.get("type", "")
        if btype == "text" and block.get("text"):
            print(c("💬 " + first_line(block["text"], 400), "38;5;252"), flush=True)
        elif btype == "thinking" and block.get("thinking"):
            print(c("   · " + first_line(block["thinking"], 160), "2"), flush=True)
        elif btype == "tool_use":
            name = block.get("name") or "tool"
            hint = _tool_hint(block.get("input"))
            label = f"{name} {hint}".rstrip()
            print(c("🔧 " + first_line(label), "38;5;147"), flush=True)
        elif btype == "tool_result":
            body = _tool_result_text(block.get("content"))
            if body:
                print(c("   ← " + body, "38;5;109"), flush=True)


def emit(obj):
    etype = obj.get("type", "")
    # Claude Agent SDK stream-json nests content blocks under message.content.
    if etype in ("assistant", "user"):
        emit_claude(obj)
        return
    # items fire both `item.started` and `item.completed`; render once, on completed.
    if etype == "item.started":
        return
    item = obj.get("item", obj)
    itype = item.get("type", "") if isinstance(item, dict) else ""
    text = item.get("text") or item.get("message")
    server, tool = item.get("server"), (item.get("tool") or item.get("name"))
    cmd = item.get("command") or item.get("cmd")
    path = item.get("path")

    if etype == "thread.started" or itype == "session.created":
        print(c("▶ session started", "1;38;5;45"), flush=True)
    elif itype in ("agent_message", "assistant_message") and text:
        print(c("💬 " + first_line(text, 400), "38;5;252"), flush=True)
    elif itype == "reasoning" and text:
        print(c("   · " + first_line(text, 160), "2"), flush=True)
    elif itype == "command_execution" and cmd:
        print(c("$ " + first_line(cmd), "38;5;114"), flush=True)
    elif itype == "file_change" and path:
        print(c("✎ wrote " + str(path), "38;5;179"), flush=True)
    elif itype == "mcp_tool_call" and (server or tool):
        print(c(f"⚙ {server or ''}·{tool or ''}", "38;5;147"), flush=True)
    elif etype == "turn.completed":
        usage = obj.get("usage") or {}
        if usage:
            print(c(f"   ✓ turn · in {usage.get('input_tokens','?')} / "
                    f"out {usage.get('output_tokens','?')} tok", "2"), flush=True)


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            # not JSON: pass plain-text lane output through, but drop the supervisor's
            # transcript framing/footer noise so the view stays CLI-clean.
            if line.startswith(("=== board child", "=== end board", "board_supervisor_rc=",
                                "worktree_autocleaned=", "Reading additional input")):
                continue
            print(line, flush=True)
            continue
        try:
            emit(obj)
        except Exception:  # noqa: BLE001 — never let a weird event kill the viewer
            pass


if __name__ == "__main__":
    main()
