from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "python" / "lane_adapter_registry.py"
SPEC = importlib.util.spec_from_file_location("lane_adapter_registry", MODULE_PATH)
registry_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(registry_module)

SOURCE_MODULE_PATH = ROOT / "scripts" / "python" / "specialist_capability_source.py"
SOURCE_SPEC = importlib.util.spec_from_file_location(
    "specialist_capability_source", SOURCE_MODULE_PATH
)
capability_source = importlib.util.module_from_spec(SOURCE_SPEC)
assert SOURCE_SPEC.loader is not None
SOURCE_SPEC.loader.exec_module(capability_source)


def staged_mcps_by_lane() -> dict[str, tuple[str, ...]]:
    """Derive, per lane, the MCPs that are actually awaiting a restart.

    ``staged_mcp_surface`` exists only to back ``pending-restart-activation``
    refs in the capability source -- that state is defined as NOT usable
    ("staged MCP awaiting a lane restart before it can connect"), so an empty
    column means "nothing is waiting", which is the healthy state.
    """
    entries, _meta = capability_source.load_source(ROOT)
    staged: dict[str, set[str]] = {}
    for (_specialist, lane), entry in entries.items():
        pending = staged.setdefault(lane, set())
        for ref in entry.get("mcps", ()):
            if ref.availability == "pending-restart-activation":
                pending.add(ref.identifier)
    return {lane: tuple(sorted(names)) for lane, names in staged.items()}


class LaneAdapterRegistryTests(unittest.TestCase):
    def test_registry_has_one_fail_closed_row_per_lane(self) -> None:
        registry = registry_module.load_capability_registry(
            ROOT / "model-lanes" / "lane-capabilities.tsv"
        )
        self.assertEqual(
            set(registry), {"gpt-codex", "claude", "gemini", "grok", "kimi"}
        )
        self.assertEqual(registry["kimi"].child_mcp_policy, "lead-broker-only")
        self.assertEqual(registry["gemini"].grounding, "google-search-grounding")
        # Derive the expectation from the capability source rather than pinning a
        # literal. The previous literal was the guarded trio, authored 2026-07-21;
        # c55b573c promoted that trio pending-restart-activation -> available on
        # 2026-07-26 without touching this column, so the pin outlived the state it
        # described and the tsv only caught up on 2026-08-14.
        #
        # This equality is strictly STRONGER than the one-directional check in
        # validate_capability_homes.py (which only requires that every
        # pending-restart ref has a staged declaration). Equality also forbids the
        # inverse -- a lane declaring an MCP staged that nothing is waiting on --
        # which is exactly the drift that sat in the tree for three weeks.
        expected_staged = staged_mcps_by_lane()
        for lane in ("gpt-codex", "claude", "gemini", "grok", "kimi"):
            self.assertEqual(
                tuple(sorted(registry[lane].staged_mcp_surface)),
                expected_staged.get(lane, ()),
                f"{lane}: staged_mcp_surface must equal exactly the MCPs whose "
                "capability-source availability is pending-restart-activation. "
                "A promoted MCP must be removed from this column; a newly staged "
                "one must be added.",
            )

    def test_registry_is_the_native_cli_auth_and_kimi_broker_contract(self) -> None:
        registry = registry_module.load_capability_registry(
            ROOT / "model-lanes" / "lane-capabilities.tsv"
        )
        self.assertEqual(
            {lane: row.cli for lane, row in registry.items()},
            {
                "gpt-codex": "codex",
                "claude": "claude",
                "gemini": "gemini",
                "grok": "grok",
                "kimi": "kimi",
            },
        )
        self.assertEqual(
            {lane: row.auth_policy for lane, row in registry.items()},
            {
                "gpt-codex": "subscription-drop-provider-keys",
                "claude": "subscription-drop-provider-keys",
                "gemini": "gemini-api-key-only",
                "grok": "xai-api-key-only",
                "kimi": "managed-login-drop-provider-keys",
            },
        )
        self.assertIn("chrono-vault", registry["gpt-codex"].mcp_surface)
        self.assertIn("chrono-vault", registry["claude"].mcp_surface)
        self.assertIn("chrono-vault", registry["gemini"].mcp_surface)
        self.assertIn("chrono-vault", registry["grok"].mcp_surface)
        self.assertIn("lead:chrono-vault", registry["kimi"].mcp_surface)
        self.assertEqual(registry["kimi"].child_mcp_policy, "lead-broker-only")

    def test_kimi_prompt_guard_is_controlled_by_child_mcp_policy(self) -> None:
        registry_path = ROOT / "model-lanes" / "lane-capabilities.tsv"
        registry = registry_module.load_capability_registry(registry_path)
        source_adapters = sorted(
            path
            for path in (ROOT / "model-lanes/kimi/.kimi/agents").glob("*.yaml")
            if "../prompts/" in path.read_text(encoding="utf-8")
        )
        self.assertTrue(source_adapters, "no live Kimi native prompt adapter found")
        source_adapter = source_adapters[0]
        specialist = source_adapter.stem
        boundary = "MCP tools are unavailable inside Kimi subagents"

        with tempfile.TemporaryDirectory() as directory:
            staged_root = Path(directory)
            agents = staged_root / ".kimi" / "agents"
            prompts = staged_root / ".kimi" / "prompts"
            agents.mkdir(parents=True)
            prompts.mkdir(parents=True)
            adapter = agents / source_adapter.name
            prompt = prompts / f"{specialist}.md"
            shutil.copyfile(source_adapter, adapter)
            shutil.copyfile(
                ROOT / "model-lanes/kimi/.kimi/prompts" / prompt.name,
                prompt,
            )
            original_prompt = prompt.read_text(encoding="utf-8")
            self.assertIn(boundary, original_prompt)
            prompt.write_text(
                original_prompt.replace(boundary, "MCP tools are available"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                registry_module.AdapterValidationError,
                "lacks lead-broker MCP policy",
            ):
                registry_module.validate_adapter_file(
                    ROOT, "kimi", adapter, registry["kimi"]
                )

            lines = registry_path.read_text(encoding="utf-8").splitlines()
            header = lines[0].split("\t")
            policy_index = header.index("child_mcp_policy")
            inverted_lines = [lines[0]]
            for line in lines[1:]:
                fields = line.split("\t")
                if fields[0] == "kimi":
                    self.assertEqual(fields[policy_index], "lead-broker-only")
                    fields[policy_index] = "inherit-full"
                inverted_lines.append("\t".join(fields))
            inverted_path = staged_root / "lane-capabilities.tsv"
            inverted_path.write_text(
                "\n".join(inverted_lines) + "\n",
                encoding="utf-8",
            )
            inverted = registry_module.load_capability_registry(inverted_path)
            self.assertEqual(inverted["kimi"].child_mcp_policy, "inherit-full")
            registry_module.validate_adapter_file(
                ROOT, "kimi", adapter, inverted["kimi"]
            )

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
        self.assertEqual(report["ranked_gaps"]["grok"], [])
        self.assertEqual(report["ranked_gaps"]["kimi"], [])
        for role in registry_module.SWARM_CRITICAL_ROLES:
            with self.subTest(role=role):
                self.assertGreaterEqual(len(report["physical_lanes"][role]), 2)

    def test_kimi_registry_points_only_at_current_native_adapters(self) -> None:
        main = (ROOT / "model-lanes/kimi/main.yaml").read_text(encoding="utf-8")
        for role in registry_module.KIMI_GENERATED_ROLES:
            with self.subTest(role=role):
                self.assertIn(
                    f"    {role}:\n      path: ./.kimi/agents/{role}.yaml",
                    main,
                )
        self.assertFalse(
            (ROOT / "model-lanes/kimi/subagents/experimental-attacker.yaml").exists()
        )
        self.assertFalse(
            (ROOT / "model-lanes/kimi/prompts/experimental-attacker.md").exists()
        )

    def test_grok_registry_points_at_smokey_native_adapter(self) -> None:
        main = (ROOT / "model-lanes/grok/main.yaml").read_text(encoding="utf-8")
        self.assertIn(
            "    smokey:\n      path: ./.grok/agents/smokey.yaml",
            main,
        )
        adapter = ROOT / "model-lanes/grok/.grok/agents/smokey.yaml"
        registry_module.validate_adapter_file(ROOT, "grok", adapter)


if __name__ == "__main__":
    unittest.main()
