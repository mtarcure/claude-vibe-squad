from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts/python/gen_runtime_tool_summary.py"
SPEC = importlib.util.spec_from_file_location("gen_runtime_tool_summary", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class RuntimeToolSummaryTests(unittest.TestCase):
    def test_runtime_map_tool_columns_byte_match_generated_projection(self) -> None:
        actual = (ROOT / module.RUNTIME_MAP_RELATIVE).read_bytes()
        expected = module.render_runtime_map(ROOT).encode("utf-8")
        self.assertEqual(actual, expected)

    def test_projection_uses_primary_server_and_operation_provider_closure(self) -> None:
        payload = module.load_payload(ROOT)
        relations = module.server_relations(payload)
        self.assertIn("perplexity_search", relations["chrono-research-arsenal"])
        self.assertNotIn("perplexity_search_web", relations["chrono-research-arsenal"])
        perplexity_entries = [
            (entry["specialist"], entry["lane"])
            for entry in payload["entries"]
            if any(tool["id"] == "perplexity_search" for tool in entry["tools"])
        ]
        self.assertTrue(perplexity_entries)
        self.assertTrue(
            all(lane in {"claude", "gpt-codex"} for _specialist, lane in perplexity_entries)
        )
        self.assertFalse(
            any(
                tool["id"] == "perplexity_search_web"
                for entry in payload["entries"]
                for tool in entry["tools"]
            )
        )
        rows = module.project_runtime_tools(ROOT)
        self.assertEqual(rows["backend-engineer"]["required_tools"], ())
        self.assertEqual(
            rows["backend-engineer"]["preferred_tools"],
            (
                "chrono-research-arsenal",
                "chrono-vault",
                "context7",
                "sequential-thinking",
            ),
        )
        self.assertEqual(
            rows["frontend-engineer"]["required_tools"],
            ("chrome-devtools", "playwright"),
        )
        self.assertNotIn("perplexity_search", rows["frontend-engineer"]["preferred_tools"])

    def test_required_provider_dominates_preferred_provider(self) -> None:
        payload = {
            "schema": module.SOURCE_SCHEMA,
            "version": 1,
            "servers": [
                {
                    "id": "search-server",
                    "provides": ["optional_search", "required_search"],
                }
            ],
            "entries": [
                {
                    "specialist": "example",
                    "lane": "gpt-codex",
                    "coverage": "full",
                    "limitations": [],
                    "skills": [],
                    "tools": [
                        {
                            "id": "optional_search",
                            "requirement": "preferred",
                            "availability": "mcp-operation",
                            "evidence": "search-server",
                            "provided_by": "search-server",
                        },
                        {
                            "id": "required_search",
                            "requirement": "required",
                            "availability": "available",
                            "evidence": "lane-inventory",
                            "provided_by": "search-server",
                        },
                    ],
                    "mcps": [],
                }
            ],
        }
        runtime_rows = {
            "example": {
                "specialist": "example",
                "primary_lane": "codex",
            }
        }
        projection = module.project_payload(payload, runtime_rows)
        self.assertEqual(projection["example"]["required_tools"], ("search-server",))
        self.assertEqual(projection["example"]["preferred_tools"], ())

    def test_write_mode_changes_only_runtime_tool_columns(self) -> None:
        source = ROOT / module.RUNTIME_MAP_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "runtime.tsv"
            target.write_bytes(source.read_bytes())
            with target.open(newline="") as handle:
                before = list(csv.DictReader(handle, delimiter="\t"))
            module.write_runtime_map(ROOT, target)
            with target.open(newline="") as handle:
                after = list(csv.DictReader(handle, delimiter="\t"))
        for old, new in zip(before, after, strict=True):
            self.assertEqual(
                {key: value for key, value in old.items() if key not in module.TOOL_COLUMNS},
                {key: value for key, value in new.items() if key not in module.TOOL_COLUMNS},
            )


if __name__ == "__main__":
    unittest.main()
