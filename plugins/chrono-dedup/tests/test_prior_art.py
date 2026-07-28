from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from chrono_dedup import composite_chain_key, prior_art_check


class FixtureSource:
    def __init__(
        self,
        name: str,
        records: list[dict[str, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.records = records or []
        self.error = error

    def search(
        self,
        target: str | dict[str, object],
        item: dict[str, object],
        query: dict[str, object],
    ) -> list[dict[str, object]]:
        if self.error is not None:
            raise self.error
        return self.records


class PriorArtCheckTests(unittest.TestCase):
    def test_known_duplicate_returns_duplicate_with_source(self) -> None:
        finding = {
            "title": "Signature replay bypasses nonce validation",
            "component": "bridge-relayer",
            "version": "2.4.1",
            "weakness": "signature replay",
            "keywords": ["nonce", "replay", "signature"],
        }
        source = FixtureSource(
            "github_security_advisories",
            [
                {
                    "id": "GHSA-abcd-1234",
                    "title": "Signature replay bypass in bridge-relayer",
                    "url": "https://github.com/advisories/GHSA-abcd-1234",
                    "item": finding,
                }
            ],
        )

        result = prior_art_check("acme-bridge", finding, sources=[source])

        self.assertEqual(result["verdict"], "duplicate")
        self.assertEqual(result["hits"][0]["source"], "github_security_advisories")
        self.assertEqual(result["hits"][0]["source_id"], "GHSA-abcd-1234")

    def test_novel_fixture_returns_novel(self) -> None:
        finding = {
            "title": "Unexpected quorum rollover freezes withdrawals",
            "component": "validator-set",
            "version": "9.0.0",
            "weakness": "quorum rollover",
            "keywords": ["epoch", "quorum", "withdrawal"],
        }
        unrelated = FixtureSource(
            "cve",
            [
                {
                    "id": "CVE-2025-0001",
                    "title": "Parser denial of service",
                    "component": "json-parser",
                    "version": "1.0.0",
                    "keywords": ["parser", "denial", "service"],
                }
            ],
        )

        result = prior_art_check("acme-bridge", finding, sources=[unrelated])

        self.assertEqual(result["verdict"], "novel")
        self.assertEqual(result["hits"], [])

    def test_unstructured_disclosure_title_can_be_likely_duplicate(self) -> None:
        finding = {
            "title": "Signature replay bypasses nonce validation",
            "component": "bridge-relayer",
            "version": "2.4.1",
            "weakness": "signature replay",
            "keywords": ["nonce", "replay", "signature"],
        }
        source = FixtureSource(
            "hackerone_hacktivity",
            [
                {
                    "id": "123",
                    "title": (
                        "Signature replay bypasses nonce validation in "
                        "bridge-relayer 2.4.1"
                    ),
                }
            ],
        )

        result = prior_art_check("acme-bridge", finding, sources=[source])

        self.assertEqual(result["verdict"], "likely-duplicate")
        self.assertEqual(result["hits"][0]["source"], "hackerone_hacktivity")

    def test_composite_key_uses_terminus_and_complete_link_set(self) -> None:
        chain = {
            "kind": "composite_chain",
            "terminus": {
                "impact": "unauthorized withdrawal",
                "asset": "escrowed funds",
            },
            "links": [
                {"primitive": "stale signer accepted", "transition": "forge approval"},
                {"primitive": "nonce not consumed", "transition": "replay withdrawal"},
            ],
        }
        reordered = {
            **chain,
            "links": list(reversed(chain["links"])),
        }
        missing_link = {
            **chain,
            "links": [chain["links"][0]],
        }
        different_terminus = {
            **chain,
            "terminus": {"impact": "temporary denial of service"},
        }

        self.assertEqual(composite_chain_key("acme-bridge", chain), composite_chain_key("acme-bridge", reordered))
        self.assertNotEqual(composite_chain_key("acme-bridge", chain), composite_chain_key("acme-bridge", missing_link))
        self.assertNotEqual(
            composite_chain_key("acme-bridge", chain),
            composite_chain_key("acme-bridge", different_terminus),
        )

    def test_known_composite_is_duplicate_but_known_part_alone_is_not(self) -> None:
        chain = {
            "kind": "composite_chain",
            "terminus": {"impact": "drain escrow"},
            "links": [
                {"primitive": "oracle lag", "transition": "inflate collateral"},
                {"primitive": "missing cap", "transition": "borrow excess"},
            ],
        }
        whole_chain = FixtureSource(
            "chrono_vault",
            [
                {
                    "id": "mem-chain-1",
                    "title": "Oracle lag plus missing cap drains escrow",
                    "item": chain,
                }
            ],
        )
        one_part = FixtureSource(
            "hackerone_hacktivity",
            [
                {
                    "id": "report-1",
                    "title": "Oracle lag affects collateral price",
                    "item": chain["links"][0],
                }
            ],
        )

        duplicate = prior_art_check("acme-lending", chain, sources=[whole_chain])
        novel = prior_art_check("acme-lending", chain, sources=[one_part])

        self.assertEqual(duplicate["verdict"], "duplicate")
        self.assertEqual(duplicate["dedup_key"], composite_chain_key("acme-lending", chain))
        self.assertEqual(novel["verdict"], "novel")

    def test_unavailable_source_does_not_crash_and_is_reported(self) -> None:
        finding = {
            "title": "Novel accounting invariant break",
            "component": "accounting",
            "version": "1.0.0",
        }
        unavailable = FixtureSource(
            "immunefi",
            error=TimeoutError("provider did not respond"),
        )
        available = FixtureSource("osv")

        result = prior_art_check(
            "acme-lending",
            finding,
            sources=[unavailable, available],
        )

        self.assertEqual(result["verdict"], "novel")
        self.assertEqual(
            result["sources_consulted"],
            [
                {
                    "source": "immunefi",
                    "status": "unavailable",
                    "hit_count": 0,
                    "error": "TimeoutError",
                },
                {
                    "source": "osv",
                    "status": "ok",
                    "hit_count": 0,
                },
            ],
        )

    def test_rejects_invalid_items_without_contacting_sources(self) -> None:
        source = FixtureSource("osv")

        with self.assertRaisesRegex(ValueError, "component"):
            prior_art_check("acme", {"title": "missing component"}, sources=[source])
        with self.assertRaisesRegex(ValueError, "terminus"):
            prior_art_check(
                "acme",
                {"kind": "composite_chain", "links": [{"primitive": "one"}]},
                sources=[source],
            )


if __name__ == "__main__":
    unittest.main()
