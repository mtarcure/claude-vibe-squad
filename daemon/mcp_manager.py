import asyncio
import json
import subprocess
import sys

MCP_REGISTRY = {
    "chrono-vault": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-vault/mcp_server.py"],
    "chrono-research-arsenal": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-research-arsenal/mcp_server.py"],
    "chrono-content-engineer": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-content-engineer/mcp_server.py"],
    "chrono-recon": ["/Users/user/chrono/.venv/bin/python", "/Users/user/chrono/plugins/chrono-recon/mcp_server.py"],
}


class MCPManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self._request_id: int = 0

    def ensure_running(self, server: str) -> subprocess.Popen:
        proc = self.processes.get(server)
        if proc:
            rc = proc.poll()
            if rc is None:
                return proc
            # Process died — try to capture stderr for debugging
            try:
                stderr_bytes = proc.stderr.read() if proc.stderr else b""
                if stderr_bytes:
                    sys.stderr.write(f"[mcp_manager] {server} exited rc={rc}: {stderr_bytes.decode('utf-8', errors='replace')[:500]}\n")
            except Exception:
                pass
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
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        payload = (json.dumps(request) + "\n").encode()
        await asyncio.to_thread(proc.stdin.write, payload)
        await asyncio.to_thread(proc.stdin.flush)
        response_line = await asyncio.to_thread(proc.stdout.readline)
        if not response_line:
            raise RuntimeError(f"MCP server {server} closed stdout unexpectedly")
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP server {server} returned invalid JSON: {response_line[:200]!r}") from e


MANAGER = MCPManager()
