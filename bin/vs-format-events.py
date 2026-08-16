#!/usr/bin/env python3
"""Format a board spawn's --json event stream into a readable, CLI-like view.

Reads log lines on stdin (as `tail -f` feeds them) and prints human-readable,
coloured lines — agent messages, shell commands, file writes, tool calls, turn
summaries — instead of raw JSON. Non-JSON lines pass through unchanged, so claude/
gemini/kimi human-text logs still render. Lane-agnostic on the common keys.
"""
import ast
import json
import re
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


def _maybe_list(value):
    """Kimi writes `content` / `tool_calls` as a Python repr, not JSON.

    The line itself is valid JSON, but these two fields arrive as the *string*
    "[{'type': 'think', ...}]" — single-quoted, so json.loads on the outer line
    leaves them as text. literal_eval recovers the list; anything unparseable is
    returned as-is so a malformed record can never crash the viewer.
    """
    if isinstance(value, str):
        # `content`/`tool_calls` arrive as Python reprs; `function.arguments`
        # arrives as JSON. Try both before giving up.
        for parse in (ast.literal_eval, json.loads):
            try:
                return parse(value)
            except (ValueError, SyntaxError):
                continue
        return value
    return value


def _kimi_arg_hint(arguments):
    """Best-effort hint from a kimi tool call's `arguments`.

    Kimi truncates long argument strings IN THE LOG: 26 of 48 calls on a measured
    lane carried incomplete JSON like '{"command": "ls -'. They are not partial
    duplicates -- every call id appears exactly once -- so discarding the
    unparseable ones would silently drop more than half the transcript. Parse when
    we can; otherwise salvage the first quoted value so the viewer still shows
    what the call was doing.
    """
    if not isinstance(arguments, str):
        return _tool_hint(arguments)
    try:
        return _tool_hint(json.loads(arguments))
    except ValueError:
        pass
    # Truncated: pull the first "key": "value" pair, value possibly unterminated.
    match = re.search(r'"(?:command|path|pattern|file_path)"\s*:\s*"([^"]*)', arguments)
    if match:
        return first_line(match.group(1)) + " …"
    match = re.search(r':\s*"([^"]*)', arguments)
    return (first_line(match.group(1)) + " …") if match else ""


def emit_kimi(obj):
    """Render kimi's OpenAI chat-completion schema.

    Kimi is the one lane that emits no `type` key: records are
    {"role": ..., "content": [...], "tool_calls": [...]} and tool results come
    back as {"role": "tool", "tool_call_id": ..., "content": ...}. Every other
    consumer here switches on `type`, so kimi's records fell through and the
    watcher showed an idle lane while it ran dozens of calls — 44 measured on a
    live lane that looked dead (2026-08-06).

    Reuses the same emoji/colour vocabulary as the other branches so a kimi
    transcript reads identically to a claude or codex one.
    """
    role = obj.get("role", "")

    if role == "tool":
        body = _tool_result_text(_maybe_list(obj.get("content")))
        if body:
            print(c("   \u2190 " + body, "38;5;109"), flush=True)
        return

    if role != "assistant":
        return  # system / user echo -> viewer noise

    for block in _maybe_list(obj.get("content")) or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        # kimi names the reasoning field after its own block type: think/think.
        body = block.get(btype) or block.get("text")
        if not body:
            continue
        if btype == "think":
            print(c("   \u00b7 " + first_line(body, 160), "2"), flush=True)
        else:
            print(c("\U0001f4ac " + first_line(body, 400), "38;5;252"), flush=True)

    for call in _maybe_list(obj.get("tool_calls")) or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = fn.get("name") or call.get("name") or "tool"
        hint = _kimi_arg_hint(fn.get("arguments"))
        print(c("\U0001f527 " + first_line(f"{name} {hint}".rstrip()), "38;5;147"), flush=True)


def emit(obj):
    etype = obj.get("type", "")
    # Kimi emits no `type` at all -- dispatch on `role` before anything else.
    if not etype and ("role" in obj or "tool_calls" in obj):
        emit_kimi(obj)
        return
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
