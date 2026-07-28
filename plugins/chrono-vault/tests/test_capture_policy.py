from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))


class _FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.settings = types.SimpleNamespace(port=None)

    def tool(self, name: str | None = None):
        del name
        return lambda function: function

    def run(self, **kwargs) -> None:
        del kwargs


fake_httpx = types.ModuleType("httpx")
fake_httpx.HTTPStatusError = type("HTTPStatusError", (Exception,), {})
fake_httpx.RequestError = type("RequestError", (Exception,), {})
fake_mcp = types.ModuleType("mcp")
fake_mcp_server = types.ModuleType("mcp.server")
fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
fake_fastmcp.FastMCP = _FakeFastMCP
sys.modules.setdefault("httpx", fake_httpx)
sys.modules.setdefault("mcp", fake_mcp)
sys.modules.setdefault("mcp.server", fake_mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", fake_fastmcp)

import mcp_server  # noqa: E402


class CapturePolicyTests(unittest.TestCase):
    def test_legacy_capture_tools_are_removed(self) -> None:
        # The four capture_* MCP tools were disabled stubs (they returned
        # capture_disabled_pending_canonical_migration) and have now been removed
        # from the chrono-vault surface. The live capture path is autocapture.py
        # via bin/outbox-watcher.sh, whose secret-redaction policy is covered by
        # test_autocapture.py. Pin the removal so the tools don't creep back.
        for name in (
            "capture_session",
            "capture_dispatch",
            "capture_review",
            "capture_research",
        ):
            self.assertFalse(
                hasattr(mcp_server, name),
                f"{name} should be removed from the chrono-vault MCP surface",
            )
        # The disabled-stub scaffolding is gone too.
        self.assertFalse(hasattr(mcp_server, "_load_capture_support"))
        self.assertFalse(hasattr(mcp_server, "_capture"))
        self.assertFalse(hasattr(mcp_server, "_capture_disabled"))


if __name__ == "__main__":
    unittest.main()
