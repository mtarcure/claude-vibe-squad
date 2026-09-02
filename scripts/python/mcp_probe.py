#!/usr/bin/env python3
"""Probe an MCP stdio server: handshake, list, and a real tools/call round-trip.

The Python MCP SDK used by Chrono's local servers speaks newline-delimited JSON
over stdio, not LSP-style Content-Length frames.

`usable=true` means the server answered `initialize`, advertised at least one
tool, and served a `tools/call`. A stdio handshake alone proves only that a
process started -- a server whose tool dispatch is dead (a bad import inside a
tool module, a half-registered decorator) handshakes perfectly and then fails
every real request, which is precisely the outage this probe exists to catch.

By default the dispatch check calls a sentinel name that cannot exist, so the
probe never fires a real tool: MCP tools have side effects (they write to the
KG, spend API credit). A healthy server answers that call with a clean
rejection; a broken one answers nothing.

`--call NAME` invokes a specific known-safe tool instead, and then the tool has
to report itself healthy, not merely answer. That is a strictly stronger gate:
chrono-vault's `health` answers a sentinel call and a real call equally well
while reporting `recall_ready: false`, which means recall is dead behind a
server that handshakes and dispatches perfectly.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from typing import Any


def frame(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def read_frames(
    proc: subprocess.Popen[bytes], deadline: float, expected_ids: set[int]
) -> list[dict[str, Any]]:
    """Read replies until every expected id has arrived, or the deadline passes.

    Returning as soon as the conversation is complete keeps a responsive server
    from costing the full read window; the audit probes every MCP on each
    doctor and launch run, and a probe that always burns its timeout is a probe
    operators route around.
    """
    if proc.stdout is None:
        return []
    # Read the raw fd, never proc.stdout.readline(): select() reports on the
    # kernel pipe, but readline() drains it into a Python-level buffer. A server
    # that answers everything in one burst then exits leaves replies 2..N sitting
    # in that invisible buffer while select reports "nothing to read" forever --
    # the probe would see the handshake and silently lose every later reply.
    # os.read() also cannot block past the deadline the way readline() can.
    fd = proc.stdout.fileno()
    buffer = b""
    messages: list[dict[str, Any]] = []
    seen: set[int] = set()
    while time.time() < deadline and not expected_ids <= seen:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            messages.append(message)
            if isinstance(message, dict) and isinstance(message.get("id"), int):
                seen.add(message["id"])
    return messages


def result_for(messages: list[dict[str, Any]], message_id: int) -> dict[str, Any]:
    for message in messages:
        if isinstance(message, dict) and message.get("id") == message_id:
            result = message.get("result")
            return result if isinstance(result, dict) else {}
    return {}


def tool_names(result: dict[str, Any]) -> list[str]:
    items = result.get("tools")
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return sorted(set(names))


def csv(names: list[str]) -> str:
    return ",".join(names) if names else "none"


PROBE_SENTINEL_TOOL = "__vibesquad_probe_no_such_tool__"

# Payload fields whose explicit `false` means the tool is not serving. Named
# keys, never "any false boolean": chrono-vault's `health` reports
# `index_dirty: false` to mean healthy, so a blanket rule would invert it.
# `ok` is this repo's `_degraded()` convention; `root_valid` and `recall_ready`
# are `health`'s own.
HEALTH_ASSERTIONS = ("ok", "root_valid", "recall_ready")


def parse_options(argv: list[str]) -> tuple[str | None, list[str], str | None]:
    """Split the probe's own leading options from the server command.

    Only leading `--` arguments belong to the probe; everything from the first
    non-option onward is the command, so a server's own flags (chrono-obsidian
    is launched as `... mcp_server.py --namespace obsidian`) pass through
    untouched.
    """
    call_tool: str | None = None
    index = 0
    while index < len(argv) and argv[index].startswith("--"):
        if argv[index] == "--call":
            if index + 1 >= len(argv):
                return None, [], "--call requires a tool name"
            call_tool = argv[index + 1]
            index += 2
            continue
        return None, [], f"unknown option: {argv[index]}"
    return call_tool, argv[index:], None


def result_payload(result: Any) -> dict[str, Any]:
    """The tool's own return value: structuredContent, else its JSON text."""
    if not isinstance(result, dict):
        return {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                decoded = json.loads(item.get("text") or "")
            except ValueError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return {}


def classify_call(message: dict[str, Any] | None) -> tuple[str, str]:
    """`ok` | `error` | `unhealthy` | `absent`, plus a short reason.

    A tool reports failure three ways, and the third is why `--call` exists: a
    JSON-RPC error, an `isError` result, or a result payload that says so in
    its own fields. Measured 2026-08-08 (see `_index_health` in
    plugins/chrono-vault/mcp_server.py): `health` reported root_valid:true
    while every `recall` errored "index schema is stale". No transport-level
    failure ever arrives for that, so the first two checks alone would call a
    server with a dead read path healthy.
    """
    if message is None:
        return "absent", ""
    if message.get("error"):
        error = message["error"]
        return "error", str(error.get("message", error) if isinstance(error, dict) else error)
    result = message.get("result")
    if isinstance(result, dict) and result.get("isError"):
        return "error", "tool returned isError"
    payload = result_payload(result)
    failed = [key for key in HEALTH_ASSERTIONS if payload.get(key) is False]
    if failed:
        return "unhealthy", " ".join(f"{key}=false" for key in failed)
    return "ok", ""


def main() -> int:
    call_tool, command, option_error = parse_options(sys.argv[1:])
    if option_error is not None or not command:
        print(option_error or "usage: mcp_probe.py [--call TOOL] <command> [args...]",
              file=sys.stderr)
        return 2

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
    )
    assert proc.stdin is not None

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vibe-squad-mcp-audit", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        # Tools only. A `resources/list` round-trip used to run here and print
        # its answer; no chrono MCP registers a resource, so every row of every
        # audit log read `resources=none` — a constant field bought with a
        # request inside the read deadline.
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": call_tool or PROBE_SENTINEL_TOOL, "arguments": {}},
        },
    ]

    try:
        for request in requests:
            proc.stdin.write(frame(request))
            proc.stdin.flush()
        messages = read_frames(proc, time.time() + 5, {1, 2, 3})
    except BrokenPipeError:
        messages = []
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

    ids = {msg.get("id") for msg in messages if isinstance(msg, dict)}
    tools = tool_names(result_for(messages, 2))
    call_reply = next(
        (m for m in messages if isinstance(m, dict) and m.get("id") == 3), None
    )
    tool_call, tool_detail = classify_call(call_reply)

    # The sentinel call is *meant* to be rejected, so its error is not the
    # server's. Counting it would put a phantom error on every healthy server.
    # A named tool's error is real and is counted.
    errors = [
        msg for msg in messages
        if isinstance(msg, dict) and msg.get("error")
        and not (call_tool is None and msg.get("id") == 3)
    ]

    initialize_response = 1 in ids
    list_response = 2 in ids
    # A named tool must come back `ok`: the operator asked about that tool, so
    # both a failed call and a self-reported broken state mean unusable. The
    # sentinel only has to be ANSWERED, because answering at all is what proves
    # the dispatch path runs, and a rejection is its only correct answer.
    dispatch_ok = tool_call == "ok" if call_tool else tool_call != "absent"
    usable = initialize_response and list_response and bool(tools) and dispatch_ok
    if call_tool is None:
        # The sentinel's rejection is the expected answer, not a diagnosis. Its
        # detail would be a phantom on every healthy server, which is the same
        # noise the `errors` filter above exists to prevent.
        tool_detail = ""

    print(
        f"usable={str(usable).lower()} "
        f"initialize_response={str(initialize_response).lower()} "
        f"list_response={str(list_response).lower()} "
        f"tool_count={len(tools)} tool_call={tool_call} "
        # Squashed and capped: this line is parsed as space-separated k=v.
        f"tool_call_detail={'_'.join(tool_detail.split())[:80] or 'none'} "
        f"errors={len(errors)} tools={csv(tools)}"
    )
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
