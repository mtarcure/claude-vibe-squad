from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "python" / "lane_adapter_registry.py"
SPEC = importlib.util.spec_from_file_location("lane_adapter_registry", MODULE_PATH)
registry_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(registry_module)


class LaneAdapterRegistryTests(unittest.TestCase):
    def test_registry_has_one_fail_closed_row_per_lane(self) -> None:
        registry = registry_module.load_capability_registry(
            ROOT / "model-lanes" / "lane-capabilities.tsv"
        )
        self.assertEqual(set(registry), {"gpt-codex", "claude", "gemini", "kimi"})
        self.assertEqual(registry["kimi"].child_mcp_policy, "lead-broker-only")
        self.assertEqual(registry["gemini"].grounding, "google-search-grounding")
        expected_staged = (
            "guarded-semgrep",
            "guarded-slither",
            "guarded-solodit",
        )
        self.assertEqual(registry["gpt-codex"].staged_mcp_surface, expected_staged)
        self.assertEqual(registry["claude"].staged_mcp_surface, expected_staged)
        self.assertEqual(registry["gemini"].staged_mcp_surface, ())
        self.assertEqual(registry["kimi"].staged_mcp_surface, ())

    def test_registry_rejects_adapter_tool_not_held_by_lane(self) -> None:
        registry = registry_module.load_capability_registry(
            ROOT / "model-lanes" / "lane-capabilities.tsv"
        )
        with tempfile.TemporaryDirectory() as directory:
            adapter = Path(directory) / "social-strategist.md"
            adapter.write_text(
                "---\n"
                "name: social-strategist\n"
                'tools: ["read_file", "imaginary_live_tool"]\n'
                "---\n\n"
                "Canonical specialist instructions live at "
                "`departments/content/specialists/social-strategist.md`.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                registry_module.AdapterValidationError,
                "imaginary_live_tool",
            ):
                registry_module.validate_adapter_file(
                    ROOT, "gemini", adapter, registry["gemini"]
                )

    def test_generated_adapters_are_exact_and_close_ranked_gaps(self) -> None:
        report = registry_module.repository_report(ROOT)
        self.assertEqual(report["generated_mismatches"], [])
        self.assertEqual(report["ranked_gaps"]["gemini"], [])
        self.assertEqual(report["ranked_gaps"]["kimi"], [])
        for role in registry_module.SWARM_CRITICAL_ROLES:
            with self.subTest(role=role):
                self.assertGreaterEqual(len(report["physical_lanes"][role]), 2)


if __name__ == "__main__":
    unittest.main()
