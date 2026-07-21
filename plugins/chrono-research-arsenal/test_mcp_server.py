from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SERVER_PATH = Path(__file__).with_name("mcp_server.py")
SPEC = importlib.util.spec_from_file_location("chrono_research_arsenal_mcp_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class _Response:
    status_code = 200
    reason_phrase = "OK"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"success": True, "id": "probe-job"}


class _Client:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return _Response()


class FirecrawlToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        _Client.calls.clear()

    def test_scrape_requires_off_repo_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = server.firecrawl_scrape("https://example.com")
        self.assertEqual(result, {"ok": False, "error": "FIRECRAWL_API_KEY missing"})

    def test_scrape_uses_v2_and_bounded_options(self) -> None:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"}, clear=True), patch.object(
            server.httpx, "Client", _Client
        ):
            result = server.firecrawl_scrape(
                "https://example.com", formats=["markdown", "not-a-format"], wait_for_ms=99_999
            )
        self.assertTrue(result["ok"])
        call = _Client.calls[0]
        self.assertEqual(call["url"], "https://api.firecrawl.dev/v2/scrape")
        self.assertEqual(call["json"]["formats"], ["markdown"])
        self.assertEqual(call["json"]["waitFor"], 30_000)
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-secret")
        self.assertNotIn("test-secret", repr(result))

    def test_crawl_is_bounded(self) -> None:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"}, clear=True), patch.object(
            server.httpx, "Client", _Client
        ):
            result = server.firecrawl_crawl("https://example.com", max_pages=10_000, max_discovery_depth=99)
        self.assertTrue(result["ok"])
        payload = _Client.calls[0]["json"]
        self.assertEqual(payload["limit"], 100)
        self.assertEqual(payload["maxDiscoveryDepth"], 10)

    def test_parse_rejects_paths_and_invalid_content(self) -> None:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"}, clear=True):
            self.assertEqual(
                server.firecrawl_parse("../secret.pdf", base64.b64encode(b"x").decode()),
                {"ok": False, "error": "unsupported_or_unsafe_filename"},
            )
            self.assertEqual(
                server.firecrawl_parse("report.pdf", "not-base64"),
                {"ok": False, "error": "invalid_base64"},
            )

    def test_parse_posts_explicit_bytes_without_local_file_access(self) -> None:
        encoded = base64.b64encode(b"%PDF-probe").decode()
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"}, clear=True), patch.object(
            server.httpx, "Client", _Client
        ):
            result = server.firecrawl_parse("report.pdf", encoded)
        self.assertTrue(result["ok"])
        call = _Client.calls[0]
        self.assertEqual(call["url"], "https://api.firecrawl.dev/v2/parse")
        self.assertEqual(call["files"]["file"][0], "report.pdf")
        self.assertEqual(call["files"]["file"][1], b"%PDF-probe")
        self.assertNotIn("test-secret", repr(result))


if __name__ == "__main__":
    unittest.main()
