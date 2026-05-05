#!/usr/bin/env python3
"""Probe an MCP stdio server with initialize plus tools/resources list calls.

The Python MCP SDK used by Chrono's local servers speaks newline-delimited JSON
over stdio, not LSP-style Content-Length frames.
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


def read_frames(proc: subprocess.Popen[bytes], deadline: float) -> list[dict[str, Any]]:
    buffer = b""
    messages: list[dict[str, Any]] = []
    while time.time() < deadline:
        if proc.stdout is None:
            break
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        chunk = proc.stdout.readline()
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line.decode("utf-8")))
            except json.JSONDecodeError:
                pass
    return messages


def result_for(messages: list[dict[str, Any]], message_id: int) -> dict[str, Any]:
    for message in messages:
        if isinstance(message, dict) and message.get("id") == message_id:
            result = message.get("result")
            return result if isinstance(result, dict) else {}
    return {}


def names_from_result(result: dict[str, Any], key: str) -> list[str]:
    items = result.get(key)
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return sorted(set(names))


def csv(names: list[str]) -> str:
    return ",".join(names) if names else "none"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: mcp_probe.py <command> [args...]", file=sys.stderr)
        return 2

    proc = subprocess.Popen(
        sys.argv[1:],
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
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
    ]

    try:
        for request in requests:
            proc.stdin.write(frame(request))
            proc.stdin.flush()
        messages = read_frames(proc, time.time() + 5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

    ids = {msg.get("id") for msg in messages if isinstance(msg, dict)}
    errors = [msg for msg in messages if isinstance(msg, dict) and msg.get("error")]
    if 1 not in ids:
        print("usable=false initialize_response=false")
        return 1
    tools = names_from_result(result_for(messages, 2), "tools")
    resources = names_from_result(result_for(messages, 3), "resources")
    if 2 in ids or 3 in ids:
        print(
            "usable=true initialize_response=true list_response=true "
            f"errors={len(errors)} tools={csv(tools)} resources={csv(resources)}"
        )
        return 0
    print(
        "usable=true initialize_response=true list_response=false "
        f"errors={len(errors)} tools={csv(tools)} resources={csv(resources)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
