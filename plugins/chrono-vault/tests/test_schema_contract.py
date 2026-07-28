"""Tool-schema honesty (U1) and stdio-only transport (U3).

The hermetic suite stubs `mcp.server.fastmcp`, so the enum contract is asserted
on the annotations pydantic consumes. `RealSchemaTests` re-derives the same
contract from a real FastMCP server in a subprocess whenever the optional `mcp`
dependency is installed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import typing
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

import lifecycle  # noqa: E402
import mcp_server  # noqa: E402
import notes  # noqa: E402


def _literal_values(function, parameter: str) -> tuple:
    hints = typing.get_type_hints(function)
    annotation = hints[parameter]
    if typing.get_origin(annotation) is not typing.Literal:
        raise AssertionError(
            f"{function.__name__}.{parameter} is {annotation!r}, not a Literal"
        )
    return typing.get_args(annotation)


class DeclaredEnumTests(unittest.TestCase):
    """Closed sets enforced internally must also be declared in the signature."""

    def test_record_note_type_declares_the_canonical_note_types(self) -> None:
        self.assertEqual(
            sorted(_literal_values(mcp_server.record, "note_type")),
            sorted(notes.NOTE_TYPES),
        )

    def test_set_status_declares_the_canonical_statuses(self) -> None:
        self.assertEqual(
            sorted(_literal_values(mcp_server.set_status, "new_status")),
            sorted(notes.STATUSES),
        )

    def test_record_usage_declares_the_canonical_outcomes(self) -> None:
        self.assertEqual(
            sorted(_literal_values(mcp_server.record_usage, "outcome")),
            sorted(lifecycle.OUTCOMES),
        )

    def test_record_declares_the_conditionally_required_fields(self) -> None:
        hints = typing.get_type_hints(mcp_server.record)

        for parameter in ("title", "body", "target", "attack_class"):
            with self.subTest(parameter=parameter):
                self.assertIn(parameter, hints)
                self.assertIn(type(None), typing.get_args(hints[parameter]))

    def test_server_side_validation_survives_the_declaration(self) -> None:
        """Schemas are advisory to well-behaved clients, not a security boundary."""
        with self.assertRaises(notes.SchemaError):
            notes.record("not_a_note_type", {"title": "t", "body": "b"})
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.record_usage(
                recall_id="00000000-0000-4000-8000-000000000000",
                note_id="mem-000000000000",
                outcome="not_an_outcome",
            )


class ConditionalFieldTests(unittest.TestCase):
    """`target`/`attack_class` describe an attack, so only attacks require them."""

    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-schema-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "schema-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(self.vault_root)},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_learning_note_records_without_target_or_attack_class(self) -> None:
        created = notes.record(
            "learning",
            {"title": "Board settle rule", "body": "Only APPROVE settles a review."},
        )

        stored = lifecycle.get_note(created["id"])
        self.assertEqual(stored["target"], notes.NOT_APPLICABLE)
        self.assertEqual(stored["attack_class"], notes.NOT_APPLICABLE)

    def test_learning_note_without_target_stays_indexable(self) -> None:
        """The index parser rejects empty text, so the omission must normalize."""
        created = notes.record(
            "learning",
            {"title": "IndexableToken lesson", "body": "IndexableToken is recallable."},
        )
        self.assertTrue(created["indexed"])

        import recall as vault_recall

        result = vault_recall.recall("IndexableToken")
        self.assertEqual([row["id"] for row in result["results"]], [created["id"]])

    def test_finding_still_requires_target_and_attack_class(self) -> None:
        with self.assertRaises(notes.SchemaError) as target_error:
            notes.record(
                "finding",
                {"title": "t", "body": "b", "attack_class": "forged-inbound"},
            )
        self.assertIn("target", str(target_error.exception))

        with self.assertRaises(notes.SchemaError) as class_error:
            notes.record("finding", {"title": "t", "body": "b", "target": "chain"})
        self.assertIn("attack_class", str(class_error.exception))

    def test_attempt_still_requires_target_and_attack_class(self) -> None:
        with self.assertRaises(notes.SchemaError):
            notes.record("attempt", {"title": "t", "body": "b"})

    def test_explicit_target_is_preserved_on_a_learning_note(self) -> None:
        created = notes.record(
            "learning",
            {"title": "t", "body": "b", "target": "chrono-vault"},
        )

        self.assertEqual(lifecycle.get_note(created["id"])["target"], "chrono-vault")

    def test_record_tool_accepts_top_level_fields(self) -> None:
        created = mcp_server.record(
            note_type="learning",
            title="TopLevelToken lesson",
            body="Recorded through typed parameters.",
        )

        stored = lifecycle.get_note(created["id"])
        self.assertEqual(stored["title"], "TopLevelToken lesson")
        self.assertEqual(stored["target"], notes.NOT_APPLICABLE)

    def test_record_tool_still_accepts_the_legacy_fields_dict(self) -> None:
        """Every dispatched packet calls `record(note_type=..., fields={...})`."""
        created = mcp_server.record(
            note_type="learning",
            fields={"title": "LegacyToken lesson", "body": "Recorded the old way."},
        )

        self.assertEqual(
            lifecycle.get_note(created["id"])["title"],
            "LegacyToken lesson",
        )

    def test_record_tool_rejects_a_conflicting_duplicate_field(self) -> None:
        with self.assertRaises(ValueError) as error:
            mcp_server.record(
                note_type="learning",
                title="one",
                body="b",
                fields={"title": "two"},
            )
        self.assertIn("title", str(error.exception))


class StdioOnlyTransportTests(unittest.TestCase):
    """CB-26: the SSE branch was an unauthenticated listener over private memory."""

    def test_run_uses_stdio_even_when_sse_is_requested(self) -> None:
        calls: list[dict] = []

        class _Server:
            settings = types.SimpleNamespace(port=None)

            def run(self, **kwargs) -> None:
                calls.append(kwargs)

        server = _Server()
        with mock.patch.dict(
            os.environ,
            {"MCP_TRANSPORT": "sse", "MCP_PORT": "3001"},
        ):
            mcp_server._run_mcp_server(server)

        self.assertEqual(calls, [{}])
        self.assertIsNone(server.settings.port)

    def test_no_network_transport_remains_in_the_source(self) -> None:
        source = (PLUGIN_ROOT / "mcp_server.py").read_text(encoding="utf-8")

        for forbidden in ('transport="sse"', "MCP_TRANSPORT", "MCP_PORT", "settings.port"):
            with self.subTest(token=forbidden):
                self.assertFalse(
                    forbidden in source,
                    f"{forbidden} still reachable in mcp_server.py",
                )


REAL_SCHEMA_PROBE = textwrap.dedent(
    """
    import asyncio, json, sys
    try:
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        sys.exit(77)
    import mcp_server

    async def main():
        tools = {tool.name: tool for tool in await mcp_server.mcp.list_tools()}
        schemas = {
            name: tools[name].inputSchema
            for name in ("record", "set_status", "record_usage")
        }
        rejected = None
        try:
            await mcp_server.mcp.call_tool(
                "record_usage",
                {
                    "recall_id": "00000000-0000-4000-8000-000000000000",
                    "note_id": "mem-000000000000",
                    "outcome": "not_an_outcome",
                },
            )
        except Exception as exc:
            rejected = type(exc).__name__
        print(json.dumps({"schemas": schemas, "rejected": rejected}))

    asyncio.run(main())
    """
)


class RealSchemaTests(unittest.TestCase):
    """Prove the declaration reaches the wire schema, not just the annotation."""

    def _probe(self) -> dict:
        completed = subprocess.run(
            [sys.executable, "-c", REAL_SCHEMA_PROBE],
            cwd=str(PLUGIN_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode == 77:
            raise unittest.SkipTest("optional dependency unavailable: mcp")
        if completed.returncode != 0:
            self.fail(f"schema probe failed: {completed.stderr[-2000:]}")
        return json.loads(completed.stdout)

    def test_generated_json_schema_publishes_the_enums(self) -> None:
        probe = self._probe()
        expected = {
            "record": ("note_type", notes.NOTE_TYPES),
            "set_status": ("new_status", notes.STATUSES),
            "record_usage": ("outcome", lifecycle.OUTCOMES),
        }

        for tool, (parameter, allowed) in expected.items():
            with self.subTest(tool=tool):
                published = probe["schemas"][tool]["properties"][parameter]
                self.assertEqual(sorted(published["enum"]), sorted(allowed))

    def test_an_invalid_enum_value_is_rejected_before_the_handler(self) -> None:
        probe = self._probe()

        self.assertIsNotNone(
            probe["rejected"],
            "an out-of-enum outcome must be rejected by the tool layer",
        )


if __name__ == "__main__":
    unittest.main()
