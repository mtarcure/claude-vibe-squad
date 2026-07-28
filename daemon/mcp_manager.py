import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VIBE_SQUAD_ROOT", Path(__file__).resolve().parents[1])).expanduser().resolve()
PLUGINS_ROOT = Path(os.environ.get("VIBE_PLUGINS", REPO_ROOT / "plugins")).expanduser().resolve()
PYTHON = os.environ.get("VIBE_PYTHON", str(REPO_ROOT / ".venv" / "bin" / "python"))


def plugin_command(plugin_name: str, *args: str) -> list[str]:
    return [PYTHON, str(PLUGINS_ROOT / plugin_name / "mcp_server.py"), *args]


MCP_REGISTRY = {
    "chrono-vault": plugin_command("chrono-vault"),
    "chrono-research-arsenal": plugin_command("chrono-research-arsenal"),
    "chrono-media-studio": plugin_command("chrono-media-studio"),
    "chrono-recon": plugin_command("chrono-recon"),
}


class MCPManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self.initialized: set[str] = set()
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
            # Mark as uninitialized since we're restarting
            self.initialized.discard(server)
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

    async def _initialize_server(self, server: str, proc: subprocess.Popen) -> None:
        """Send MCP initialize request if not already done."""
        if server in self.initialized:
            return
        self._request_id += 1
        init_request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "vibe-squad-daemon",
                    "version": "1.0"
                }
            }
        }
        payload = (json.dumps(init_request) + "\n").encode()
        await asyncio.to_thread(proc.stdin.write, payload)
        await asyncio.to_thread(proc.stdin.flush)
        response_line = await asyncio.to_thread(proc.stdout.readline)
        if not response_line:
            raise RuntimeError(f"MCP server {server} closed stdout during initialization")
        try:
            response = json.loads(response_line)
            if "error" in response:
                raise RuntimeError(f"MCP server {server} initialization failed: {response['error']}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP server {server} returned invalid JSON during init: {response_line[:200]!r}") from e
        self.initialized.add(server)

    async def call_tool(self, server: str, tool: str, arguments: dict) -> dict:
        proc = self.ensure_running(server)
        await self._initialize_server(server, proc)
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
