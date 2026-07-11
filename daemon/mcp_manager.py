import asyncio
import json
import subprocess
from pathlib import Path
from typing import Optional

MCP_REGISTRY = {
    "chrono-vault": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-vault/mcp_server.py"],
    "chrono-research-arsenal": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-research-arsenal/mcp_server.py"],
    "chrono-content-engineer": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-content-engineer/mcp_server.py"],
    "chrono-recon": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-recon/mcp_server.py"],
}


class MCPManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}

    def ensure_running(self, server: str) -> subprocess.Popen:
        proc = self.processes.get(server)
        if proc and proc.poll() is None:
            return proc
        if server not in MCP_REGISTRY:
            raise ValueError(f"unknown MCP server: {server}")
        proc = subprocess.Popen(
            MCP_REGISTRY[server],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.processes[server] = proc
        return proc

    async def call_tool(self, server: str, tool: str, arguments: dict) -> dict:
        proc = self.ensure_running(server)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        proc.stdin.write((json.dumps(request) + "\n").encode())
        proc.stdin.flush()
        response_line = proc.stdout.readline()
        return json.loads(response_line)


MANAGER = MCPManager()
