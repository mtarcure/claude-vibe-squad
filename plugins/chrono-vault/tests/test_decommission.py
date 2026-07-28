from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class DecommissionTests(unittest.TestCase):
    def _run_without_httpx(self, assertions: str) -> subprocess.CompletedProcess[str]:
        bootstrap = textwrap.dedent(
            f"""
            import importlib.abc
            import os
            import sys
            import types

            sys.path.insert(0, {str(PLUGIN_ROOT)!r})

            class BlockHttpx(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "httpx" or fullname.startswith("httpx."):
                        raise ModuleNotFoundError("httpx blocked by decommission test")
                    return None

            class FakeFastMCP:
                def __init__(self, name):
                    self.name = name
                    self.settings = types.SimpleNamespace(port=None)

                def tool(self, name=None):
                    return lambda function: function

                def run(self, **kwargs):
                    pass

            fake_mcp = types.ModuleType("mcp")
            fake_mcp_server = types.ModuleType("mcp.server")
            fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
            fake_fastmcp.FastMCP = FakeFastMCP
            sys.modules["mcp"] = fake_mcp
            sys.modules["mcp.server"] = fake_mcp_server
            sys.modules["mcp.server.fastmcp"] = fake_fastmcp
            sys.meta_path.insert(0, BlockHttpx())

            import mcp_server
            """
        ) + "\n" + textwrap.dedent(assertions)
        return subprocess.run(
            [sys.executable, "-c", bootstrap],
            cwd=PLUGIN_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_core_imports_without_httpx_and_legacy_search_degrades(self) -> None:
        result = self._run_without_httpx(
            """
            assert "httpx" not in sys.modules
            os.environ["OBSIDIAN_REST_API_KEY"] = "fixture-key"
            response = mcp_server.vault_search("human browse")
            assert response == {
                "ok": False,
                "error": "optional_dependency_unavailable: httpx",
                "human_only": True,
                "legacy": True,
            }, response
            """
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_removed_catalog_and_split_sql_symbols_stay_absent(self) -> None:
        result = self._run_without_httpx(
            """
            for name in (
                "catalog_alias_mcp",
                "_catalog_alias_list_skills",
                "_init_kg_schema",
                "_connect",
                "list_attempts",
                "_kg_alias_list_attempts",
                "_vault_root",
            ):
                assert not hasattr(mcp_server, name), name
            """
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
