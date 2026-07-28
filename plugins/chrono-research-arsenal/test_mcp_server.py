from __future__ import annotations

import base64
import importlib.util
import inspect
import json
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


class _ForbiddenResponse(_Response):
    status_code = 403
    reason_phrase = "Forbidden"

    def raise_for_status(self) -> None:
        request = server.httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape")
        response = server.httpx.Response(403, request=request)
        raise server.httpx.HTTPStatusError("forbidden", request=request, response=response)


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


class _ForbiddenClient(_Client):
    def post(self, url: str, **kwargs: object) -> _ForbiddenResponse:
        self.calls.append({"url": url, **kwargs})
        return _ForbiddenResponse()


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
        self.assertEqual(result["status_code"], 200)
        call = _Client.calls[0]
        self.assertEqual(call["url"], "https://api.firecrawl.dev/v2/scrape")
        self.assertEqual(call["json"]["formats"], ["markdown"])
        self.assertEqual(call["json"]["waitFor"], 30_000)
        self.assertNotIn("zeroDataRetention", call["json"])
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
        self.assertNotIn("zeroDataRetention", payload)

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
        self.assertEqual(result["status_code"], 200)
        call = _Client.calls[0]
        self.assertEqual(call["url"], "https://api.firecrawl.dev/v2/parse")
        self.assertEqual(call["files"]["file"][0], "report.pdf")
        self.assertEqual(call["files"]["file"][1], b"%PDF-probe")
        options = json.loads(call["files"]["options"][1])
        self.assertNotIn("zeroDataRetention", options)
        self.assertNotIn("test-secret", repr(result))

    def test_zero_data_retention_is_explicit_and_applies_to_all_operations(self) -> None:
        encoded = base64.b64encode(b"%PDF-probe").decode()
        env = {
            "FIRECRAWL_API_KEY": "test-secret",
            "FIRECRAWL_ZERO_DATA_RETENTION": "true",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(server.httpx, "Client", _Client):
            server.firecrawl_scrape("https://example.com")
            server.firecrawl_crawl("https://example.com")
            server.firecrawl_parse("report.pdf", encoded)

        self.assertIs(_Client.calls[0]["json"]["zeroDataRetention"], True)
        self.assertIs(_Client.calls[1]["json"]["zeroDataRetention"], True)
        options = json.loads(_Client.calls[2]["files"]["options"][1])
        self.assertIs(options["zeroDataRetention"], True)

    def test_zero_data_retention_falsey_values_are_omitted(self) -> None:
        for value in ("", "0", "false", "no", "off", "unexpected"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"FIRECRAWL_API_KEY": "test-secret", "FIRECRAWL_ZERO_DATA_RETENTION": value},
                clear=True,
            ), patch.object(server.httpx, "Client", _Client):
                _Client.calls.clear()
                server.firecrawl_scrape("https://example.com")
                self.assertNotIn("zeroDataRetention", _Client.calls[0]["json"])

    def test_enterprise_retention_403_returns_typed_non_fallback_error(self) -> None:
        env = {
            "FIRECRAWL_API_KEY": "test-secret",
            "FIRECRAWL_ZERO_DATA_RETENTION": "yes",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(
            server.httpx, "Client", _ForbiddenClient
        ):
            result = server.firecrawl_scrape("https://example.com")

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "firecrawl_zero_data_retention_requires_enterprise",
                "status_code": 403,
                "reason_phrase": "Forbidden",
                "zero_data_retention": True,
                "safe_retry": "disable only if the task data policy permits",
            },
        )

    def test_default_off_403_stays_generic(self) -> None:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"}, clear=True), patch.object(
            server.httpx, "Client", _ForbiddenClient
        ):
            result = server.firecrawl_scrape("https://example.com")

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "firecrawl_http_error",
                "status_code": 403,
                "reason_phrase": "Forbidden",
            },
        )

    def test_firecrawl_tools_do_not_accept_caller_headers(self) -> None:
        for function in (server.firecrawl_scrape, server.firecrawl_crawl, server.firecrawl_parse):
            self.assertNotIn("headers", inspect.signature(function).parameters)


if __name__ == "__main__":
    unittest.main()
