from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


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


class CompatHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-compat-health-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "compat-health-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_record_finding_without_attempt_is_recallable(self) -> None:
        note_id = mcp_server.record_finding(
            title="CompatRecallToken critical finding",
            severity="critical",
            description="CompatRecallToken is reachable without a prior attempt.",
            evidence="artifact:compat-fixture",
            target="push-chain",
            attack_class="compatibility",
        )

        recalled = mcp_server.recall(
            "CompatRecallToken",
            filters={"keywords": "severity-critical"},
        )
        note = mcp_server.get_note(note_id)

        self.assertRegex(note_id, r"^mem-[0-9a-f]{12}$")
        self.assertEqual([row["id"] for row in recalled["results"]], [note_id])
        self.assertEqual(note["target"], "push-chain")
        self.assertEqual(note["attack_class"], "compatibility")
        self.assertIn("severity-critical", note["keywords"])
        self.assertIn("artifact:compat-fixture", note["evidence_refs"])
        self.assertFalse((self.vault_root / "chrono").exists())

    def test_finding_can_inherit_target_and_attack_class_from_attempt(self) -> None:
        attempt_id = mcp_server.record_attempt(
            role="exploit-developer",
            target="push-chain",
            attack_class="forged-inbound",
        )

        finding_id = mcp_server.record_finding(
            attempt_id=attempt_id,
            title="Inherited attempt context",
            severity="high",
            description="The finding inherits canonical attempt context.",
            evidence="artifact:inheritance-fixture",
        )

        attempt = mcp_server.get_note(attempt_id)
        finding = mcp_server.get_note(finding_id)
        self.assertEqual(attempt["type"], "attempt")
        self.assertEqual(attempt["target"], "push-chain")
        self.assertEqual(finding["target"], attempt["target"])
        self.assertEqual(finding["attack_class"], attempt["attack_class"])
        self.assertIn(f"note:{attempt_id}", finding["evidence_refs"])

    def test_legacy_five_positional_signature_and_alias_remain_callable(self) -> None:
        attempt_id = mcp_server.record_attempt("reviewer", "target-a", "audit")

        canonical = mcp_server.record_finding(
            attempt_id,
            "Positional compatibility",
            "medium",
            "The original five positional arguments remain valid.",
            "artifact:positional",
        )
        alias = mcp_server._kg_alias_record_finding(
            None,
            "Alias compatibility",
            "low",
            "The legacy namespace can record without an attempt.",
            "legacy free text evidence",
            target="target-b",
            attack_class="compatibility",
        )

        self.assertEqual(mcp_server.get_note(canonical)["target"], "target-a")
        alias_note = mcp_server.get_note(alias)
        self.assertEqual(alias_note["target"], "target-b")
        self.assertNotIn("legacy free text evidence", alias_note["evidence_refs"])
        self.assertTrue(
            any(
                value.startswith("legacy-evidence-sha256:")
                for value in alias_note["evidence_refs"]
            )
        )

    def test_missing_attempt_context_is_rejected_without_placeholder_note(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server.record_finding(
                title="Missing canonical context",
                severity="low",
                description="No target or attack class was supplied.",
                evidence="artifact:missing-context",
            )

        self.assertFalse((self.vault_root / "notes").exists())

    def test_canonical_record_tool_routes_to_markdown_store(self) -> None:
        result = mcp_server.record(
            "learning",
            {
                "title": "Canonical record tool",
                "body": "The MCP record tool returns the full write result.",
                "target": "memory",
                "attack_class": "learning",
            },
        )

        self.assertRegex(result["id"], r"^mem-[0-9a-f]{12}$")
        self.assertTrue(result["indexed"])
        self.assertEqual(mcp_server.get_note(result["id"])["type"], "learning")

    def test_health_reports_counts_fts_and_planted_legacy_store(self) -> None:
        mcp_server.record_attempt("ai-engineer", "memory", "retrieval")
        mcp_server.record_finding(
            title="Health fixture finding",
            severity="info",
            description="Health should count this canonical finding.",
            evidence="artifact:health-fixture",
            target="memory",
            attack_class="health",
        )
        legacy = self.vault_root / "chrono" / "_state" / "kg.db"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy fixture")

        result = mcp_server.health()

        self.assertEqual(
            set(result),
            {
                "vault_id",
                "root_valid",
                "schema_version",
                "fts5",
                "note_counts",
                "index_generation",
                "index_dirty",
                "legacy_stores",
            },
        )
        self.assertEqual(result["vault_id"], "compat-health-test")
        self.assertTrue(result["root_valid"])
        self.assertEqual(result["schema_version"], 1)
        self.assertTrue(result["fts5"])
        self.assertEqual(
            result["note_counts"],
            {"attempt": 1, "finding": 1, "learning": 0},
        )
        self.assertGreater(result["index_generation"], 0)
        self.assertFalse(result["index_dirty"])
        self.assertIn("vault:chrono/_state/kg.db", result["legacy_stores"])
        self.assertNotIn(str(self.vault_root), json.dumps(result))

    def test_empty_health_is_read_only_and_invalid_root_is_structured(self) -> None:
        empty = mcp_server.health()

        self.assertTrue(empty["root_valid"])
        self.assertEqual(empty["index_generation"], 0)
        self.assertTrue(empty["index_dirty"])
        self.assertFalse((self.vault_root / "index").exists())

        with mock.patch.dict(os.environ, {}, clear=True):
            invalid = mcp_server.health()
        self.assertFalse(invalid["root_valid"])
        self.assertIsNone(invalid["vault_id"])
        self.assertIsNone(invalid["schema_version"])
        self.assertTrue(invalid["index_dirty"])
        self.assertEqual(
            invalid["note_counts"],
            {"attempt": 0, "finding": 0, "learning": 0},
        )

    def test_health_does_not_count_malformed_markdown_as_a_canonical_note(self) -> None:
        note_dir = self.vault_root / "notes" / "finding"
        note_dir.mkdir(parents=True)
        (note_dir / "malformed.md").write_text(
            "not canonical frontmatter\n",
            encoding="utf-8",
        )

        result = mcp_server.health()

        self.assertEqual(result["note_counts"]["finding"], 0)
        self.assertTrue(result["index_dirty"])

    def test_health_marks_dangling_markdown_symlink_dirty_without_following_it(self) -> None:
        mcp_server.record_finding(
            title="Symlink health fixture",
            severity="info",
            description="The canonical note establishes a clean index.",
            evidence="artifact:symlink-health",
            target="memory",
            attack_class="health",
        )
        self.assertFalse(mcp_server.health()["index_dirty"])
        dangling = self.vault_root / "notes" / "finding" / "mem-deadbeefdead.md"
        dangling.symlink_to(self.vault_root / "does-not-exist.md")

        result = mcp_server.health()

        self.assertEqual(result["note_counts"]["finding"], 1)
        self.assertTrue(result["index_dirty"])


if __name__ == "__main__":
    unittest.main()
