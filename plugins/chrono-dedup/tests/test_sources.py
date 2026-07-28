from __future__ import annotations

import sys
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from chrono_dedup.sources import (
    ChronoVaultSource,
    OsvSource,
    SearchPageSource,
    SoloditSource,
    default_sources,
)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get_json(self, url: str, **kwargs: object) -> dict[str, object]:
        self.calls.append(("get_json", url, kwargs))
        return {"vulnerabilities": []}

    def post_json(self, url: str, **kwargs: object) -> dict[str, object]:
        self.calls.append(("post_json", url, kwargs))
        if url == SoloditSource.api_url:
            return {
                "findings": [
                    {
                        "id": "solodit-1",
                        "slug": "signature-replay",
                        "title": "Signature replay bypasses nonce validation",
                        "summary": "A bridge relayer accepted a replayed signature.",
                        "source_link": "https://example.test/audit#signature-replay",
                        "protocol_name": "Acme Bridge",
                        "firm_name": "Example Audits",
                        "issues_issuetagscore": [
                            {"tags_tag": {"title": "Signature Replay"}}
                        ],
                    }
                ]
            }
        return {
            "vulns": [
                {
                    "id": "OSV-2026-1",
                    "summary": "Replay in bridge-relayer",
                    "details": "Affected before the nonce patch.",
                }
            ]
        }

    def get_text(self, url: str, **kwargs: object) -> str:
        self.calls.append(("get_text", url, kwargs))
        return '<a href="/reports/123">Replay in bridge relayer</a>'


class SourceAdapterTests(unittest.TestCase):
    def test_default_sources_cover_required_catalogs_and_private_history(self) -> None:
        names = [source.name for source in default_sources(transport=FakeTransport())]

        self.assertEqual(
            names,
            [
                "hackerone_hacktivity",
                "immunefi",
                "solodit",
                "github_security_advisories",
                "cve",
                "osv",
                "target_program_history",
                "chrono_vault",
            ],
        )

    def test_solodit_posts_brokered_query_and_normalizes_findings(self) -> None:
        transport = FakeTransport()
        source = SoloditSource(transport)

        with patch.dict(environ, {"SOLODIT_API_KEY": "unit-test-placeholder"}):
            records = source.search(
                "acme-bridge",
                {"component": "bridge-relayer"},
                {
                    "phrase": "bridge-relayer nonce replay",
                    "terms": ["bridge-relayer", "nonce", "replay"],
                },
            )

        self.assertEqual(records[0]["id"], "solodit-1")
        self.assertEqual(records[0]["weakness"], ["Signature Replay"])
        self.assertEqual(
            transport.calls[0],
            (
                "post_json",
                SoloditSource.api_url,
                {
                    "payload": {
                        "page": 1,
                        "pageSize": 30,
                        "filters": {
                            "keywords": (
                                "acme-bridge bridge-relayer nonce replay"
                            )
                        },
                    },
                    "headers": {
                        "X-Cyfrin-API-Key": "unit-test-placeholder"
                    },
                },
            ),
        )

    def test_osv_queries_affected_component_and_version(self) -> None:
        transport = FakeTransport()
        source = OsvSource(transport)

        records = source.search(
            "acme",
            {"component": "bridge-relayer", "version": "2.4.1", "ecosystem": "PyPI"},
            {
                "component": "bridge-relayer",
                "version": "2.4.1",
                "terms": ["bridge", "replay"],
            },
        )

        self.assertEqual(records[0]["id"], "OSV-2026-1")
        self.assertEqual(
            transport.calls[0],
            (
                "post_json",
                "https://api.osv.dev/v1/query",
                {
                    "payload": {
                        "package": {"name": "bridge-relayer", "ecosystem": "PyPI"},
                        "version": "2.4.1",
                    }
                },
            ),
        )

    def test_search_page_query_includes_target_and_finding_terms(self) -> None:
        transport = FakeTransport()
        source = SearchPageSource(
            "hackerone_hacktivity",
            "https://hackerone.com/hacktivity/overview",
            "querystring",
            link_pattern=r"hackerone\.com/reports/\d+",
            transport=transport,
        )

        records = source.search(
            "acme-bridge",
            {"component": "bridge-relayer"},
            {
                "phrase": "bridge-relayer nonce replay",
                "terms": ["bridge-relayer", "nonce", "replay"],
            },
        )

        self.assertEqual(records[0]["id"], "123")
        self.assertEqual(
            transport.calls[0][2]["params"]["querystring"],
            "acme-bridge bridge-relayer nonce replay",
        )

    def test_chrono_vault_uses_target_scoped_recall(self) -> None:
        calls: list[tuple[str, str]] = []

        def recall(query: str, target: str) -> dict[str, object]:
            calls.append((query, target))
            return {
                "results": [
                    {
                        "id": "mem-1",
                        "snippet": "prior finding for bridge-relayer nonce replay",
                        "note_link": "notes/finding/mem-1.md",
                    }
                ]
            }

        records = ChronoVaultSource(recall).search(
            "acme",
            {"component": "bridge-relayer"},
            {
                "component": "bridge-relayer",
                "version": "2.4.1",
                "phrase": "nonce replay",
            },
        )

        self.assertEqual(calls, [("acme bridge-relayer 2.4.1 nonce replay", "acme")])
        self.assertEqual(records[0]["id"], "mem-1")


if __name__ == "__main__":
    unittest.main()
