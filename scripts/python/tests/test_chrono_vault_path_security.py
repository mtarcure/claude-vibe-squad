"""Security regressions for the Obsidian vault_get URL boundary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "chrono-vault"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import mcp_server as vault_server  # noqa: E402


class FakeResponse:
    status_code = 200
    reason_phrase = "OK"
    text = "fixture content"

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, url: str, **_: object) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse()


class VaultGetPathSecurityTests(unittest.TestCase):
    def _fake_httpx(self, client: FakeClient) -> SimpleNamespace:
        return SimpleNamespace(
            Client=lambda **_: client,
            HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
            RequestError=type("RequestError", (Exception,), {}),
        )

    def _call(self, path: str, *, alias: bool = False) -> tuple[dict[str, object], FakeClient]:
        client = FakeClient()
        entrypoint = (
            vault_server._obsidian_alias_vault_get
            if alias
            else vault_server.vault_get
        )
        with (
            mock.patch.object(vault_server, "require_memory_operation"),
            mock.patch.object(
                vault_server,
                "_obsidian_headers",
                return_value={"Authorization": "Bearer unit-test-placeholder"},
            ),
            mock.patch.object(
                vault_server,
                "_load_httpx",
                return_value=self._fake_httpx(client),
            ),
        ):
            result = entrypoint(path)
        return result, client

    def test_traversal_absolute_authority_query_and_fragment_paths_are_refused(self) -> None:
        attacks = (
            "../commands/",
            "../../etc/passwd",
            "..%2f..%2fetc%2fpasswd",
            "%2e%2e/%2e%2e/etc/passwd",
            "%252e%252e%252fcommands/",
            "/commands/",
            "%2fcommands/",
            "//127.0.0.1/commands/",
            "%2f%2f127.0.0.1/commands/",
            "http://127.0.0.1/commands/",
            "http%3a%2f%2f127.0.0.1/commands/",
            "x?cmd=1",
            "x%3fcmd=1",
            "x#fragment",
            "x%23fragment",
        )
        for path in attacks:
            with self.subTest(path=path):
                result, client = self._call(path)
                self.assertEqual(result, {"ok": False, "error": "invalid vault path"})
                self.assertEqual(client.urls, [])

    def test_namespace_alias_uses_the_same_path_boundary(self) -> None:
        result, client = self._call("..%2fcommands/", alias=True)

        self.assertEqual(result, {"ok": False, "error": "invalid vault path"})
        self.assertEqual(client.urls, [])

    def test_legitimate_path_segments_are_percent_encoded_before_transport(self) -> None:
        result, client = self._call("notes/Project plan (β).md")

        self.assertTrue(result["ok"])
        self.assertEqual(
            client.urls,
            [
                "http://127.0.0.1:27123/vault/"
                "notes/Project%20plan%20%28%CE%B2%29.md"
            ],
        )


if __name__ == "__main__":
    unittest.main()
