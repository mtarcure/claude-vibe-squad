from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts/python/validate_capability_homes.py"
SPEC = importlib.util.spec_from_file_location("validate_capability_homes", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


POINTER = "Capabilities are lane-specific; read the structured adapter."


def policy() -> dict:
    return {
        "aliases": {"Foundry": "forge", "WebFetch": "WebFetch"},
        "baseline_ref": "a" * 40,
        "context_required_tool_seeds": ["requests"],
        "frontmatter_exempt_keys": [
            "specialist",
            "version",
            "department",
            "lane",
            "model_key",
            "requires_approval",
            "safety_level",
            "tags",
        ],
        "generic_pointer_line": POINTER,
        "identifier_seeds": {
            "skills": ["scope-gate"],
            "tools": ["WebFetch", "nuclei"],
            "mcps": ["chrono-vault"],
        },
        "parity_identifier_seeds": {
            "skills": ["scope-gate"],
            "tools": ["Foundry", "nuclei"],
            "mcps": [],
        },
        "regex_rules": [
            {
                "id": "command-flag",
                "kind": "tools",
                "pattern": r"(?<![A-Za-z0-9_])--[a-z][a-z0-9-]*",
            },
            {
                "id": "tool-schema-ref",
                "kind": "tools",
                "pattern": r"\b[A-Za-z0-9_.-]+\.py:[0-9]+(?:-[0-9]+)?\b",
            },
        ],
        "schema": "adapter-capability-policy/v1",
        "tool_section_headings": ["Tools"],
    }


def row(specialist: str = "example") -> dict[str, str]:
    return {
        "specialist": specialist,
        "source_namespace": "coding",
        "primary_lane": "codex",
        "backup_lane": "claude",
        "escalate_lane": "codex",
        "review_lane": "claude",
        "throughput_lane": "none",
    }


class CapabilityHomeTests(unittest.TestCase):
    def test_markdown_capabilities_require_json_string_arrays(self) -> None:
        parsed = module._markdown_frontmatter(
            "---\nname: x\nskills: [\"one\", \"two\"]\ntools: []\n---\n",
            Path("x.md"),
        )
        self.assertEqual(parsed["skills"], ["one", "two"])
        with self.assertRaisesRegex(module.CapabilityHomeError, "JSON-compatible"):
            module._markdown_frontmatter(
                "---\nname: x\nskills: [one, two]\n---\n", Path("x.md")
            )
        with self.assertRaisesRegex(module.CapabilityHomeError, "duplicate"):
            module._json_string_list(["one", "one"], "skills", Path("x.md"))
        with self.assertRaisesRegex(module.CapabilityHomeError, "duplicate top-level"):
            module._markdown_frontmatter(
                "---\nskills: [\"one\"]\nskills: [\"two\"]\n---\n", Path("x.md")
            )
        with self.assertRaisesRegex(module.CapabilityHomeError, "duplicate top-level"):
            module._yaml_top_level(
                "skills: [\"one\"]\nskills: [\"two\"]\n", Path("x.yaml")
            )

    def test_baseline_extractor_canonicalizes_tools_and_collects_skills(self) -> None:
        text = (
            "### Skills (read on start)\n- `scope-gate`\n\n"
            "## Tools\n- Foundry / nuclei (verified)\n\n## Next\n"
        )
        found = module.extract_baseline_capabilities(text, policy())
        self.assertEqual(found["skills"], {"scope-gate"})
        self.assertEqual(found["tools"], {"forge", "nuclei"})

    def test_baseline_tool_extractor_ignores_prose_labels(self) -> None:
        text = (
            "## Tools\n"
            "- Process audit: `ps`, `pgrep`\n"
            "- Date / amount normalization\n"
            "- Draft / email workflow\n\n"
            "## Next\n"
        )
        reviewed = policy()
        reviewed["parity_identifier_seeds"] = {
            "skills": reviewed["identifier_seeds"]["skills"],
            "tools": ["ps", "pgrep"],
            "mcps": [],
        }
        found = module.extract_baseline_capabilities(text, reviewed)
        self.assertEqual(found["tools"], {"ps", "pgrep"})
        self.assertNotIn("process", found["tools"])
        self.assertNotIn("amount", found["tools"])
        self.assertNotIn("draft", found["tools"])

    def test_skill_extractor_ignores_prose_and_description_code_refs(self) -> None:
        section = (
            "- If the integration is missing, report `capability_gap`.\n"
            "- `one-skill`, `two-skill` — compare output with `memory.md`.\n"
        )
        self.assertEqual(
            module._skill_identifiers(section), {"one-skill", "two-skill"}
        )

    def test_baseline_tool_extractor_scans_reviewed_lexicon_in_full_body(self) -> None:
        reviewed = policy()
        reviewed["parity_identifier_seeds"]["tools"] = ["Playwright"]
        reviewed["aliases"]["Playwright"] = "playwright"
        found = module.extract_baseline_capabilities(
            "## Workflow\nUse Playwright for the browser pass.\n", reviewed
        )
        self.assertEqual(found["tools"], {"playwright"})

    def test_ambiguous_full_body_tool_requires_code_context(self) -> None:
        reviewed = policy()
        reviewed["parity_identifier_seeds"]["tools"] = ["requests"]
        ordinary = module.extract_baseline_capabilities(
            "The role handles user requests carefully.\n", reviewed
        )
        coded = module.extract_baseline_capabilities(
            "Use `requests` for the HTTP client.\n", reviewed
        )
        self.assertEqual(ordinary["tools"], set())
        self.assertEqual(coded["tools"], {"requests"})

    def test_lowercase_smart_contract_arsenal_is_extracted_and_required(self) -> None:
        reviewed = module.load_policy(ROOT)
        requested_spellings = {
            "slither",
            "semgrep",
            "aderyn",
            "solhint",
            "halmos",
            "echidna",
            "medusa",
            "ityfuzz",
            "cast",
            "anvil",
            "chisel",
            "forge",
            "mythril",
            "myth",
        }
        self.assertTrue(
            requested_spellings.issubset(reviewed["parity_identifier_seeds"]["tools"])
        )
        self.assertEqual(reviewed["aliases"]["mythril"], "myth")
        self.assertTrue(
            {"cast", "anvil"}.issubset(reviewed["context_required_tool_seeds"])
        )
        baseline_text = (
            "Use slither, semgrep, aderyn, solhint, halmos, echidna, medusa, "
            "and ityfuzz for the audit floor.\n\n"
            "## Tools\n"
            "- cast / anvil / chisel / forge\n"
            "- mythril / myth\n\n"
            "## Next\n"
        )
        extracted = module.extract_baseline_capabilities(baseline_text, reviewed)
        expected = {
            "slither",
            "semgrep",
            "aderyn",
            "solhint",
            "halmos",
            "echidna",
            "medusa",
            "ityfuzz",
            "cast",
            "anvil",
            "chisel",
            "forge",
            "myth",
        }
        self.assertEqual(extracted["tools"], expected)

        specialist_row = row("exploit-developer")
        specialist_row["source_namespace"] = "security"
        adapters = {
            ("exploit-developer", "gpt-codex"): {
                "adapter": "exploit-developer.toml",
                "specialist": "exploit-developer",
                "lane": "gpt-codex",
                "skills": (),
                "tools": (),
                "mcps": (),
            }
        }
        issues = module.migration_parity_diagnostics(
            {"exploit-developer": specialist_row},
            adapters,
            {
                "exploit-developer": {
                    "skills": set(),
                    "tools": extracted["tools"],
                    "mcps": set(),
                }
            },
        )
        self.assertEqual(
            {issue["identifier"] for issue in issues}, expected
        )

    def test_cast_and_anvil_require_context(self) -> None:
        reviewed = module.load_policy(ROOT)
        ordinary = module.extract_baseline_capabilities(
            "The cast is forging a prop on an anvil.\n",
            reviewed,
        )
        coded = module.extract_baseline_capabilities(
            "Use `cast` and `anvil` for the local chain.\n",
            reviewed,
        )
        self.assertEqual(ordinary["tools"], set())
        self.assertEqual(coded["tools"], {"cast", "anvil"})

    def test_boundary_scans_full_body_and_nonexempt_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brief = root / "departments/coding/specialists/example.md"
            brief.parent.mkdir(parents=True)
            brief.write_text(
                "---\n"
                "specialist: example\n"
                "requires_approval:\n  - WebFetch\n"
                "required_tools: [scope-gate]\n"
                "---\n\n"
                f"{POINTER}\n\n"
                "Use WebFetch with --subswarm-directive and swarm_diff.py:16-22.\n",
                encoding="utf-8",
            )
            baseline = {
                "example": {"skills": {"scope-gate"}, "tools": set(), "mcps": set()}
            }
            issues = module.base_boundary_diagnostics(
                root, {"example": row()}, policy(), baseline
            )
            ids = {issue["identifier"] for issue in issues}
            self.assertIn("scope-gate", ids)
            self.assertIn("WebFetch", ids)
            self.assertIn("--subswarm-directive", ids)
            self.assertIn("swarm_diff.py:16-22", ids)
            self.assertNotIn("generic-adapter-pointer", ids)
            # The exempt requires_approval value must not create a second WebFetch hit.
            self.assertEqual(sum(issue["identifier"] == "WebFetch" for issue in issues), 1)

    def test_boundary_requires_exactly_one_generic_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brief = root / "departments/coding/specialists/example.md"
            brief.parent.mkdir(parents=True)
            brief.write_text("---\nspecialist: example\n---\n\nNo pointer.\n", encoding="utf-8")
            baseline = {
                "example": {"skills": set(), "tools": set(), "mcps": set()}
            }
            issues = module.base_boundary_diagnostics(
                root, {"example": row()}, policy(), baseline
            )
            self.assertEqual(issues[0]["identifier"], "generic-adapter-pointer")

    def test_migration_parity_unions_only_routed_lane_adapters(self) -> None:
        rows = {"example": row()}
        adapters = {
            ("example", "gpt-codex"): {
                "adapter": "codex.toml",
                "specialist": "example",
                "lane": "gpt-codex",
                "skills": ("scope-gate",),
                "tools": (),
                "mcps": (),
            },
            ("example", "gemini"): {
                "adapter": "gemini.md",
                "specialist": "example",
                "lane": "gemini",
                "skills": (),
                "tools": ("nuclei",),
                "mcps": (),
            },
        }
        baseline = {
            "example": {
                "skills": {"scope-gate"},
                "tools": {"nuclei"},
                "mcps": set(),
            }
        }
        issues = module.migration_parity_diagnostics(rows, adapters, baseline)
        self.assertEqual([issue["identifier"] for issue in issues], ["nuclei"])

    def test_migration_parity_accepts_same_id_mcp_as_tool_deduplication(self) -> None:
        rows = {"example": row()}
        adapters = {
            ("example", "claude"): {
                "adapter": "claude.md",
                "specialist": "example",
                "lane": "claude",
                "skills": (),
                "tools": (),
                "mcps": ("playwright",),
            }
        }
        baseline = {
            "example": {
                "skills": set(),
                "tools": {"playwright"},
                "mcps": set(),
            }
        }
        issues = module.migration_parity_diagnostics(rows, adapters, baseline)
        self.assertEqual(issues, [])

    def test_tool_existence_checks_each_category_fail_closed(self) -> None:
        adapter = {
            "adapter": "model-lanes/gpt-codex/x.toml",
            "specialist": "example",
            "lane": "gpt-codex",
            "skills": ("real-skill", "fake-skill"),
            "tools": ("catalog-tool", "fake-tool"),
            "mcps": ("real-mcp", "fake-mcp"),
        }
        inventory = {
            lane: {"skills": set(), "tools": set(), "mcps": set()}
            for lane in module.LANES
        }
        inventory["gpt-codex"]["mcps"].add("real-mcp")
        issues = module.tool_existence_diagnostics(
            Path("."),
            {("example", "gpt-codex"): adapter},
            lane_inventory=inventory,
            catalog_tools={"catalog-tool"},
            skill_names={lane: ({"real-skill"} if lane == "gpt-codex" else set()) for lane in module.LANES},
            which=lambda _name: None,
        )
        self.assertEqual(
            {(issue["kind"], issue["identifier"]) for issue in issues},
            {("skills", "fake-skill"), ("tools", "fake-tool"), ("mcps", "fake-mcp")},
        )

    def test_tool_existence_catalog_is_lane_scoped(self) -> None:
        adapter = {
            "adapter": "model-lanes/gpt-codex/x.toml",
            "specialist": "example",
            "lane": "gpt-codex",
            "skills": (),
            "tools": ("claude-only",),
            "mcps": (),
        }
        inventory = {
            lane: {"skills": set(), "tools": set(), "mcps": set()}
            for lane in module.LANES
        }
        inventory["gpt-codex"]["skills"].add("repo-shell")
        catalog = {lane: set() for lane in module.LANES}
        catalog["claude"].add("claude-only")
        issues = module.tool_existence_diagnostics(
            Path("."),
            {("example", "gpt-codex"): adapter},
            lane_inventory=inventory,
            catalog_tools=catalog,
            skill_names={lane: set() for lane in module.LANES},
            which=lambda _name: None,
        )
        self.assertEqual([issue["identifier"] for issue in issues], ["claude-only"])

    def test_catalog_parser_never_certifies_arbitrary_heading_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / module.API_CATALOG_RELATIVE
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                "## 1. Anthropic / Claude\n\n"
                "### Claude Model API\n"
                "- specialists: all claude specialists\n"
                "- verified: yes\n",
                encoding="utf-8",
            )
            found = module.verified_catalog_tools(root)
            self.assertIn("claude-model-api", found["claude"])
            self.assertNotIn("claude", found["claude"])
            self.assertNotIn("model", found["claude"])
            self.assertNotIn("api", found["claude"])
            self.assertEqual(found["gpt-codex"], set())

    def test_registry_lane_restriction_overrides_catalog_route_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / module.API_CATALOG_RELATIVE
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                "## Shared tools\n\n"
                "### firecrawl (`firecrawl-scrape`)\n"
                "- specialists: research\n"
                "- verified: yes\n",
                encoding="utf-8",
            )
            registry_path = root / "shared/registries/skill-tool-registry.tsv"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                "name\trecord_kind\ttype\tlanes\tverified_state\n"
                "firecrawl\ttool\tplugin-skill-family\tclaude\tlane-live\n",
                encoding="utf-8",
            )
            runtime_path = root / module.RUNTIME_MAP_RELATIVE
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(
                "specialist\trequires_approval\nresearch\t[]\n",
                encoding="utf-8",
            )
            research = row("research")
            research["primary_lane"] = "gemini"
            research["backup_lane"] = "claude"
            catalog = module.verified_catalog_tools(root, {"research": research})
            self.assertIn("firecrawl", catalog["claude"])
            self.assertIn("firecrawl-scrape", catalog["claude"])
            self.assertNotIn("firecrawl", catalog["gemini"])
            self.assertNotIn("firecrawl-scrape", catalog["gemini"])

            inventory = {
                lane: {"skills": set(), "tools": set(), "mcps": set()}
                for lane in module.LANES
            }
            adapter = {
                "adapter": "model-lanes/gemini/.gemini/agents/research.md",
                "specialist": "research",
                "lane": "gemini",
                "skills": (),
                "tools": ("firecrawl",),
                "mcps": (),
            }
            issues = module.tool_existence_diagnostics(
                root,
                {("research", "gemini"): adapter},
                lane_inventory=inventory,
                catalog_tools=catalog,
                skill_names={lane: set() for lane in module.LANES},
                which=lambda _name: None,
            )
            self.assertEqual([issue["identifier"] for issue in issues], ["firecrawl"])

            ref = type(
                "CapabilityRef",
                (),
                {
                    "identifier": "firecrawl",
                    "requirement": "required",
                    "availability": "available",
                    "evidence": "installed-or-shared-authored",
                },
            )()
            source = {
                ("research", "gemini"): {
                    "specialist": "research",
                    "lane": "gemini",
                    "skills": (),
                    "tools": (ref,),
                    "mcps": (),
                }
            }
            source_issues = module.source_existence_diagnostics(
                root,
                source,
                lane_inventory=inventory,
                catalog_tools=catalog,
                skill_names={lane: set() for lane in module.LANES},
                which=lambda _name: None,
            )
            self.assertEqual(
                [issue["identifier"] for issue in source_issues],
                ["research:gemini:firecrawl"],
            )

    def test_registry_accepts_pipe_delimited_multi_lane_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "shared/registries/skill-tool-registry.tsv"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                "name\trecord_kind\ttype\tlanes\tverified_state\n"
                "playwright\ttool\tmcp-tool\tclaude|codex|gemini\tyes\n",
                encoding="utf-8",
            )
            found = module.shared_registry_capabilities(root)
            for lane in ("claude", "gpt-codex", "gemini"):
                self.assertIn("playwright", found[lane]["mcps"])
                self.assertIn("playwright", found[lane]["tools"])
            self.assertNotIn("playwright", found["kimi"]["mcps"])

    def test_catalog_only_lane_restriction_overrides_route_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / module.API_CATALOG_RELATIVE
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                "## 9.5 Non-chrono plugin capabilities (Claude lane)\n\n"
                "### firecrawl\n"
                "- specialists: research\n"
                "- verified: yes\n",
                encoding="utf-8",
            )
            research = row("research")
            research["primary_lane"] = "gemini"
            research["backup_lane"] = "claude"
            catalog = module.verified_catalog_tools(root, {"research": research})
            self.assertIn("firecrawl", catalog["claude"])
            self.assertNotIn("firecrawl", catalog["gemini"])

    def test_generated_index_is_deterministic_and_freshness_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / module.POLICY_RELATIVE
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(json.dumps(policy(), sort_keys=True), encoding="utf-8")
            adapters = {
                ("zeta", "claude"): {
                    "adapter": "z.md", "specialist": "zeta", "lane": "claude",
                    "lane_native_mirror": True,
                    "skills": ("native", "b", "a"), "tools": (), "mcps": (),
                }
            }
            inventory = {
                lane: {"skills": set(), "tools": set(), "mcps": set()}
                for lane in module.LANES
            }
            inventory["claude"]["skills"].add("native")
            first = module.render_index(
                root, adapters, policy(), lane_inventory=inventory
            )
            second = module.render_index(
                root, adapters, policy(), lane_inventory=inventory
            )
            self.assertEqual(first, second)
            self.assertLess(first.index('"a"'), first.index('"b"'))
            self.assertNotIn('"native"', first)
            index = root / module.INDEX_RELATIVE
            index.write_text(first, encoding="utf-8")
            self.assertEqual(module.index_freshness_diagnostics(root, first), [])
            index.write_text(first + "\n", encoding="utf-8")
            self.assertEqual(
                module.index_freshness_diagnostics(root, first)[0]["check"],
                "index-freshness",
            )

    def test_generated_index_subtracts_unmarked_legacy_gemini_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / module.POLICY_RELATIVE
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(json.dumps(policy(), sort_keys=True), encoding="utf-8")
            adapters = {
                ("zeta", "gemini"): {
                    "adapter": "z.md",
                    "specialist": "zeta",
                    "lane": "gemini",
                    "lane_native_mirror": False,
                    "skills": (),
                    "tools": ("read_file", "write_file"),
                    "mcps": (),
                }
            }
            inventory = {
                lane: {"skills": set(), "tools": set(), "mcps": set()}
                for lane in module.LANES
            }
            inventory["gemini"]["tools"].update({"read_file", "write_file"})
            rendered = module.render_index(
                root, adapters, policy(), lane_inventory=inventory
            )
            entry = json.loads(rendered)["entries"][0]
            self.assertEqual(entry["tools"], [])


if __name__ == "__main__":
    unittest.main()
