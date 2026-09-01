from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import date as _date
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts/python/validate_capability_homes.py"
SPEC = importlib.util.spec_from_file_location("validate_capability_homes", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


POINTER = "Capabilities are lane-specific; read the structured adapter."
FABRICATED_BASELINE = "1" * 40


def _git(root: Path, *args: str) -> str:
    """Run one git command against a hermetic throwaway repository."""
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "baseline test",
        "GIT_AUTHOR_EMAIL": "baseline@example.invalid",
        "GIT_COMMITTER_NAME": "baseline test",
        "GIT_COMMITTER_EMAIL": "baseline@example.invalid",
    }
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    ).stdout.strip()


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
            '---\nname: x\nskills: ["one", "two"]\ntools: []\n---\n',
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
                '---\nskills: ["one"]\nskills: ["two"]\n---\n', Path("x.md")
            )
        with self.assertRaisesRegex(module.CapabilityHomeError, "duplicate top-level"):
            module._yaml_top_level('skills: ["one"]\nskills: ["two"]\n', Path("x.yaml"))

    def test_gemini_comment_projection_is_loaded_after_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter_path = root / "model-lanes/gemini/.gemini/agents/example.md"
            adapter_path.parent.mkdir(parents=True)
            adapter_path.write_text(
                "---\n"
                "name: example\n"
                "description: Example\n"
                "kind: local\n"
                "tools: []\n"
                "---\n"
                "<!-- generated_by=lane-capability-registry/v1 registry_sha256=abc\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                'capability_skills: ["scope-gate"]\n'
                'capability_tools: ["nuclei"]\n'
                'capability_mcps: ["chrono-vault"]\n'
                "# END SPECIALIST CAPABILITY PROJECTION\n"
                "-->\n",
                encoding="utf-8",
            )
            adapters, issues = module.load_adapters(root, {"example": row()})
            self.assertEqual(issues, [])
            adapter = adapters[("example", "gemini")]
            self.assertEqual(adapter["skills"], ("scope-gate",))
            self.assertEqual(adapter["tools"], ("nuclei",))
            self.assertEqual(adapter["mcps"], ("chrono-vault",))
            self.assertEqual(
                adapter["capability_source"],
                "model-lanes/specialist-lane-capabilities.v1.json",
            )
            self.assertEqual(adapter["capability_source_sha256"], "deadbeef")
            self.assertTrue(adapter["lane_native_mirror"])

    def test_gemini_comment_projection_drift_is_detected(self) -> None:
        projection = module._gemini_comment_projection(
            "---\nname: example\n---\n"
            "<!-- generated_by=lane-capability-registry/v1\n"
            "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
            "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
            "capability_source_sha256: expected-sha\n"
            'capability_mcps: ["drifted-mcp"]\n'
            "# END SPECIALIST CAPABILITY PROJECTION\n"
            "-->\n",
            Path("example.md"),
        )
        adapter = {
            "adapter": "model-lanes/gemini/.gemini/agents/example.md",
            "specialist": "example",
            "lane": "gemini",
            "skills": (),
            "tools": (),
            "mcps": tuple(projection["capability_mcps"]),
            "capability_source": projection["capability_source"],
            "capability_source_sha256": projection["capability_source_sha256"],
        }
        capability_ref = type(
            "CapabilityRef",
            (),
            {
                "identifier": "chrono-vault",
                "requirement": "required",
                "availability": "available",
                "evidence": "lane-live",
            },
        )()
        source = {
            ("example", "gemini"): {
                "specialist": "example",
                "lane": "gemini",
                "skills": (),
                "tools": (),
                "mcps": (capability_ref,),
                "primary_requirements": (),
            }
        }
        # adapter_source_sync_diagnostics delegates accepted-hash policy to
        # accepted_source_sha256s.  Patch that active seam so this fixture
        # isolates MCP-array drift; source-pointer drift has its own diagnostic.
        with mock.patch.object(
            module,
            "accepted_source_sha256s",
            return_value=frozenset({"expected-sha"}),
        ):
            issues = module.adapter_source_sync_diagnostics(
                Path("."),
                {("example", "gemini"): adapter},
                source,
            )
        self.assertEqual(
            [(issue["identifier"], issue["kind"]) for issue in issues],
            [("example:gemini:mcps", "mcps")],
        )

        source_drift_adapter = {
            **adapter,
            "mcps": ("chrono-vault",),
            "capability_source_sha256": "stale-sha",
        }
        with mock.patch.object(
            module,
            "accepted_source_sha256s",
            return_value=frozenset({"expected-sha"}),
        ):
            source_issues = module.adapter_source_sync_diagnostics(
                Path("."),
                {("example", "gemini"): source_drift_adapter},
                source,
            )
        self.assertEqual(
            [(issue["identifier"], issue["kind"]) for issue in source_issues],
            [("example:gemini:source", "schema")],
        )

    def test_gemini_comment_projection_rejects_malformed_sentinel(self) -> None:
        malformed_cases = {
            "missing end": (
                "---\nname: example\n---\n"
                "<!-- generated_by=lane-capability-registry/v1\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                "-->\n"
            ),
            "repeated begin": (
                "---\nname: example\n---\n"
                "<!-- generated_by=lane-capability-registry/v1\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                "# END SPECIALIST CAPABILITY PROJECTION\n"
                "-->\n"
            ),
            "outside comment": (
                "---\nname: example\n---\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                "# END SPECIALIST CAPABILITY PROJECTION\n"
            ),
            "comment closes inside block": (
                "---\nname: example\n---\n"
                "<!-- generated_by=lane-capability-registry/v1\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "-->\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                "# END SPECIALIST CAPABILITY PROJECTION\n"
                "-->\n"
            ),
        }
        for label, malformed in malformed_cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                adapter_path = root / "model-lanes/gemini/.gemini/agents/example.md"
                adapter_path.parent.mkdir(parents=True)
                adapter_path.write_text(malformed, encoding="utf-8")
                adapters, issues = module.load_adapters(root, {"example": row()})
                self.assertEqual(adapters, {})
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["check"], "adapter-schema")

    def test_gemini_projection_rejects_frontmatter_comment_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter_path = root / "model-lanes/gemini/.gemini/agents/example.md"
            adapter_path.parent.mkdir(parents=True)
            adapter_path.write_text(
                "---\n"
                "name: example\n"
                'capability_mcps: ["chrono-vault"]\n'
                "---\n"
                "<!-- generated_by=lane-capability-registry/v1\n"
                "# BEGIN SPECIALIST CAPABILITY PROJECTION\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                'capability_mcps: ["chrono-vault"]\n'
                "# END SPECIALIST CAPABILITY PROJECTION\n"
                "-->\n",
                encoding="utf-8",
            )
            adapters, issues = module.load_adapters(root, {"example": row()})
            self.assertEqual(adapters, {})
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["check"], "adapter-schema")
            self.assertIn("ambiguous", issues[0]["message"])

    def test_gemini_frontmatter_projection_remains_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter_path = root / "model-lanes/gemini/.gemini/agents/example.md"
            adapter_path.parent.mkdir(parents=True)
            adapter_path.write_text(
                "---\n"
                "name: example\n"
                "capability_source: model-lanes/specialist-lane-capabilities.v1.json\n"
                "capability_source_sha256: deadbeef\n"
                'capability_mcps: ["chrono-vault"]\n'
                "---\n",
                encoding="utf-8",
            )
            adapters, issues = module.load_adapters(root, {"example": row()})
            self.assertEqual(issues, [])
            self.assertEqual(adapters[("example", "gemini")]["mcps"], ("chrono-vault",))

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
        self.assertEqual(module._skill_identifiers(section), {"one-skill", "two-skill"})

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
        self.assertEqual({issue["identifier"] for issue in issues}, expected)

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
                "Use WebFetch with --parallel-directive and result_diff.py:16-22.\n",
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
            self.assertIn("--parallel-directive", ids)
            self.assertIn("result_diff.py:16-22", ids)
            self.assertNotIn("generic-adapter-pointer", ids)
            # The exempt requires_approval value must not create a second WebFetch hit.
            self.assertEqual(
                sum(issue["identifier"] == "WebFetch" for issue in issues), 1
            )

    def test_boundary_requires_exactly_one_generic_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brief = root / "departments/coding/specialists/example.md"
            brief.parent.mkdir(parents=True)
            brief.write_text(
                "---\nspecialist: example\n---\n\nNo pointer.\n", encoding="utf-8"
            )
            baseline = {"example": {"skills": set(), "tools": set(), "mcps": set()}}
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

    def test_migration_parity_retirement_is_dated_scoped_and_fail_closed(self) -> None:
        reviewed = module.load_policy(ROOT)
        retirements = reviewed["migration_parity_retirements"]
        # Assert the CONTRACT each record must satisfy, not a literal list. The
        # previous exact-list assertion pinned a single record and went red the
        # moment SKL-08 added eleven more -- a stale expectation, not a product
        # defect, but a red required test all the same.
        self.assertGreaterEqual(len(retirements), 1)
        for record in retirements:
            self.assertEqual(
                set(record),
                {"specialist", "kind", "identifier", "retired_on", "source_task", "reason"},
            )
            # Semantics, not string shape. A regex accepts 2026-02-30; parsing
            # does not. A prefix match accepts "TASK-...-9999-" with no slug.
            self.assertEqual(
                _date.fromisoformat(record["retired_on"]).isoformat(),
                record["retired_on"],
            )
            self.assertRegex(
                record["source_task"], r"^TASK-\d{4}-\d{2}-\d{2}-\d{4}-\S+$"
            )
            self.assertTrue(record["specialist"] and record["identifier"] and record["reason"])
        # The original record stays present; retirement is append-only.
        self.assertIn(
            {
                "specialist": "content-verifier",
                "kind": "skills",
                "identifier": "citation-audit",
                "retired_on": "2026-08-29",
                "source_task": "TASK-2026-08-29-1300-u15",
                "reason": "evidence-backed stale pointer retired from the capability source",
            },
            retirements,
        )
        # Must-fail matrix, driven through the PRODUCTION load_policy path so the
        # standalone validator is proven too -- not just this unit test. Each
        # malformed record must be rejected; a survivor means the contract went
        # back to checking string shape instead of meaning.
        import copy
        import json as _json
        import tempfile

        base = dict(retirements[0])
        for label, mutation in (
            ("calendar-invalid date", {"retired_on": "2026-02-30"}),
            ("truncated source task", {"source_task": "TASK-2026-08-29-9999-"}),
            ("non-ISO date", {"retired_on": "29-08-2026"}),
            ("blank reason", {"reason": "   "}),
            ("empty source_task", {"source_task": ""}),
        ):
            with self.subTest(malformed=label):
                bad = copy.deepcopy(reviewed)
                record = dict(base)
                record.update(mutation)
                bad["migration_parity_retirements"] = [record]
                with tempfile.TemporaryDirectory() as tmp:
                    bad_path = Path(tmp) / "policy.json"
                    bad_path.write_text(_json.dumps(bad), encoding="utf-8")
                    with self.assertRaises(module.CapabilityHomeError):
                        module.load_policy(ROOT, policy_path=bad_path)
        # Positive control: the SAME harness must accept the unmutated policy, or
        # the matrix above proves nothing (it would pass on any error at all).
        with tempfile.TemporaryDirectory() as tmp:
            good_path = Path(tmp) / "policy.json"
            good_path.write_text(_json.dumps(reviewed), encoding="utf-8")
            module.load_policy(ROOT, policy_path=good_path)
        rows = {
            "content-verifier": row("content-verifier"),
            "other-specialist": row("other-specialist"),
        }
        adapters = {
            (specialist, "gpt-codex"): {
                "adapter": f"{specialist}.toml",
                "specialist": specialist,
                "lane": "gpt-codex",
                "skills": (),
                "tools": (),
                "mcps": (),
            }
            for specialist in rows
        }
        baseline = {
            "content-verifier": {
                "skills": {"citation-audit", "unacknowledged-skill"},
                "tools": set(),
                "mcps": set(),
            },
            "other-specialist": {
                "skills": {"citation-audit"},
                "tools": set(),
                "mcps": set(),
            },
        }

        issues = module.migration_parity_diagnostics(
            rows,
            adapters,
            baseline,
            retirements=module.migration_parity_retirement_keys(reviewed),
        )
        self.assertEqual(
            [(issue["path"], issue["identifier"]) for issue in issues],
            [
                (
                    "departments/coding/specialists/content-verifier.md",
                    "unacknowledged-skill",
                ),
                (
                    "departments/coding/specialists/other-specialist.md",
                    "citation-audit",
                ),
            ],
        )

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
            skill_names={
                lane: ({"real-skill"} if lane == "gpt-codex" else set())
                for lane in module.LANES
            },
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

    def test_source_existence_does_not_probe_knowledge_skills_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "shared/registries/skill-tool-registry.tsv"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                "name\trecord_kind\ttype\tlanes\tverified_state\n",
                encoding="utf-8",
            )
            runtime_path = root / module.RUNTIME_MAP_RELATIVE
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(
                "specialist\trequires_approval\nexample\t[]\n",
                encoding="utf-8",
            )
            inventory = {
                lane: {
                    "skills": set(),
                    "tools": set(),
                    "mcps": set(),
                    "staged_mcps": set(),
                }
                for lane in module.LANES
            }
            ref = type(
                "CapabilityRef",
                (),
                {
                    "identifier": "knowledge-reference",
                    "requirement": "preferred",
                    "availability": "uninstalled",
                    "evidence": "host-PATH:absent",
                },
            )()
            source = {
                ("example", "gpt-codex"): {
                    "specialist": "example",
                    "lane": "gpt-codex",
                    "skills": (ref,),
                    "tools": (),
                    "mcps": (),
                }
            }
            probes: list[str] = []

            issues = module.source_existence_diagnostics(
                root,
                source,
                lane_inventory=inventory,
                catalog_tools={lane: set() for lane in module.LANES},
                skill_names={lane: set() for lane in module.LANES},
                which=lambda identifier: probes.append(identifier) or "/bin/reference",
            )

            self.assertEqual(issues, [])
            self.assertEqual(probes, [])

    def test_pending_reprobe_evidence_blocks_available_projection(self) -> None:
        payload = json.loads(
            (ROOT / module.SOURCE_RELATIVE).read_text(encoding="utf-8")
        )
        target = next(
            item
            for entry in payload["entries"]
            if entry["specialist"] == "experimental-attacker"
            and entry["lane"] == "gpt-codex"
            for item in entry["tools"]
            if item["id"] == "amass"
        )
        self.assertEqual(
            (target["availability"], target["evidence"]),
            ("probe-failed", "pending-reprobe"),
        )
        target["availability"] = "available"

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / module.SOURCE_RELATIVE.name
            source.write_text(json.dumps(payload), encoding="utf-8")
            entries, _ = module.load_source(ROOT, source)

        # The generic loader still parses the authored record. The projection
        # acceptance boundary must reject the one-field reactivation.
        self.assertIn(
            "amass",
            module.available_arrays(
                entries, "experimental-attacker", "gpt-codex"
            )["tools"],
        )
        with self.assertRaisesRegex(
            module.CapabilityHomeError,
            "availability 'available' cannot retain evidence 'pending-reprobe'",
        ):
            module.projection_arrays(
                entries, "experimental-attacker", "gpt-codex"
            )

    def test_refreshed_reprobe_evidence_allows_available_projection(self) -> None:
        payload = json.loads(
            (ROOT / module.SOURCE_RELATIVE).read_text(encoding="utf-8")
        )
        target = next(
            item
            for entry in payload["entries"]
            if entry["specialist"] == "experimental-attacker"
            and entry["lane"] == "gpt-codex"
            for item in entry["tools"]
            if item["id"] == "amass"
        )
        target["availability"] = "available"
        target["evidence"] = "host-PATH"

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / module.SOURCE_RELATIVE.name
            source.write_text(json.dumps(payload), encoding="utf-8")
            entries, _ = module.load_source(ROOT, source)

        self.assertIn(
            "amass",
            module.projection_arrays(
                entries, "experimental-attacker", "gpt-codex"
            )["tools"],
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
            policy_path.write_text(
                json.dumps(policy(), sort_keys=True), encoding="utf-8"
            )
            adapters = {
                ("zeta", "claude"): {
                    "adapter": "z.md",
                    "specialist": "zeta",
                    "lane": "claude",
                    "lane_native_mirror": True,
                    "skills": ("native", "b", "a"),
                    "tools": (),
                    "mcps": (),
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

    def test_generated_source_index_counts_distinct_surfaces_dynamically(self) -> None:
        ref = type(
            "CapabilityRef",
            (),
            {
                "identifier": "scope-gate",
                "requirement": "required",
                "availability": "available",
                "evidence": "lane-inventory",
            },
        )()
        source = {
            (specialist, lane): {
                "specialist": specialist,
                "lane": lane,
                "coverage": "full",
                "limitations": (),
                "skills": (ref,),
                "tools": (),
                "mcps": (),
            }
            for specialist, lane in (
                ("alpha", "claude"),
                ("beta", "claude"),
                ("gamma", "gpt-codex"),
            )
        }
        runtime = {
            specialist: {**row(specialist), "primary_lane": lane}
            for specialist, lane in (
                ("alpha", "claude"),
                ("beta", "claude"),
                ("gamma", "codex"),
            )
        }
        runtime_summary = {
            specialist: {"required_tools": (), "preferred_tools": ()}
            for specialist in runtime
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / module.POLICY_RELATIVE
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(
                json.dumps(policy(), sort_keys=True), encoding="utf-8"
            )
            with (
                mock.patch.object(module, "runtime_rows", return_value=runtime),
                mock.patch.object(
                    module, "project_runtime_tools", return_value=runtime_summary
                ),
                mock.patch.object(module, "source_sha256", return_value="source-sha"),
            ):
                payload = json.loads(
                    module.render_index(root, {}, policy(), source_entries=source)
                )

        surface_hashes = [entry["surface_sha256"] for entry in payload["entries"]]
        self.assertEqual(surface_hashes[0], surface_hashes[1])
        self.assertNotEqual(surface_hashes[0], surface_hashes[2])
        self.assertEqual(payload["surface_count"], len(set(surface_hashes)))

    def test_generated_index_subtracts_unmarked_legacy_gemini_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / module.POLICY_RELATIVE
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(
                json.dumps(policy(), sort_keys=True), encoding="utf-8"
            )
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


class BaselineAcquisitionTests(unittest.TestCase):
    """Cover the step that *reads* the baseline, not only the one that parses it.

    Every other baseline test above hands `extract_baseline_capabilities` a
    literal string, so the suite used to begin after the only step that can
    fail.  An absent baseline commit was silently converted into an empty
    historical capability set, which left `migration-parity` comparing every
    brief against nothing and reporting `pass` -- the one answer it must never
    be able to reach by accident.
    """

    def setUp(self) -> None:
        module.require_baseline_commit.cache_clear()
        self.addCleanup(module.require_baseline_commit.cache_clear)

    def _repository(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        brief = root / "departments/coding/specialists/example.md"
        brief.parent.mkdir(parents=True)
        brief.write_text("## Tools\n- Foundry / nuclei\n\n## Next\n", encoding="utf-8")
        _git(root, "init", "-q", ".")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "pre-strip baseline")
        return root

    def test_absent_baseline_commit_is_configuration_fatal(self) -> None:
        root = self._repository()
        relative = Path("departments/coding/specialists/example.md")

        # Pin the premise. For a commit it cannot resolve, git still reports
        # the *path*, in the same words it uses for a brief that postdates a
        # perfectly reachable baseline. The empty-set fallback keyed on exactly
        # this string, which is why it could not tell the two causes apart.
        probe = subprocess.run(
            ["git", "show", f"{FABRICATED_BASELINE}:{relative.as_posix()}"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(probe.returncode, 0)
        self.assertIn("exists on disk, but not in", probe.stderr)

        with self.assertRaises(module.CapabilityHomeError) as caught:
            module.baseline_text(root, FABRICATED_BASELINE, relative)
        self.assertIn(FABRICATED_BASELINE, str(caught.exception))

    def test_load_baseline_refuses_before_reading_any_brief(self) -> None:
        root = self._repository()
        configured = {**policy(), "baseline_ref": FABRICATED_BASELINE}
        with self.assertRaises(module.CapabilityHomeError) as caught:
            module.load_baseline(root, {}, configured)
        self.assertIn(FABRICATED_BASELINE, str(caught.exception))

    def test_validator_run_refuses_rather_than_reporting_pass(self) -> None:
        """The public-clone shape: a real tree whose baseline object is absent."""
        with tempfile.TemporaryDirectory() as directory:
            configured = json.loads(
                (ROOT / module.POLICY_RELATIVE).read_text(encoding="utf-8")
            )
            configured["baseline_ref"] = FABRICATED_BASELINE
            policy_path = Path(directory) / "adapter-capability-policy.json"
            policy_path.write_text(json.dumps(configured), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main(
                    ["--repo-root", str(ROOT), "--policy", str(policy_path)]
                )
        self.assertEqual(code, 2)
        self.assertNotIn('"status": "pass"', stdout.getvalue())
        reported = json.loads(stderr.getvalue())
        self.assertEqual(reported["status"], "error")
        self.assertIn(FABRICATED_BASELINE, reported["message"])

    def test_brief_added_after_a_reachable_baseline_stays_empty(self) -> None:
        """Negative control: the legitimate new-specialist path must survive."""
        root = self._repository()
        reachable = _git(root, "rev-parse", "HEAD")
        added = Path("departments/coding/specialists/added-later.md")
        (root / added).write_text("## Tools\n- nuclei\n", encoding="utf-8")
        self.assertEqual(module.baseline_text(root, reachable, added), "")

    def test_brief_absent_from_baseline_and_disk_stays_fatal(self) -> None:
        root = self._repository()
        reachable = _git(root, "rev-parse", "HEAD")
        with self.assertRaises(module.CapabilityHomeError):
            module.baseline_text(
                root, reachable, Path("departments/coding/specialists/absent.md")
            )

    def test_reachable_baseline_still_extracts_pre_strip_capabilities(self) -> None:
        """Negative control: the maintainer path still reads real history."""
        root = self._repository()
        reachable = _git(root, "rev-parse", "HEAD")
        loaded = module.load_baseline(
            root, {"example": row()}, {**policy(), "baseline_ref": reachable}
        )
        self.assertEqual(loaded["example"]["tools"], {"forge", "nuclei"})

    def test_index_only_run_does_not_need_the_baseline_history(self) -> None:
        """The refusal belongs to the checks that read history, not to the run."""
        with tempfile.TemporaryDirectory() as directory:
            configured = json.loads(
                (ROOT / module.POLICY_RELATIVE).read_text(encoding="utf-8")
            )
            configured["baseline_ref"] = FABRICATED_BASELINE
            policy_path = Path(directory) / "adapter-capability-policy.json"
            policy_path.write_text(json.dumps(configured), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main(
                    [
                        "--repo-root",
                        str(ROOT),
                        "--policy",
                        str(policy_path),
                        "--only",
                        "index",
                    ]
                )
        self.assertNotEqual(code, 2)
        self.assertNotIn("baseline commit", stderr.getvalue())


class ClaudeSkillHomeVisibilityTests(unittest.TestCase):
    """The claude lane's skill home must be the one that actually holds skills.

    `actual_skill_names()` listed `model-lanes/claude/.claude/skills`, which does
    not exist. The lane's only other home is `~/.claude/plugins/cache`, so the
    gate saw 321 cached plugin skills and 67 of the repo's 95 `.claude/skills`
    were invisible to it -- it reported pass on a set it could not see.

    validate_skill_wiring.py:5-14 already names `.claude/skills` (repo root) as
    the corrected model and calls the old path out as wrong; this pins the same
    truth in the validator that was still using it.
    """

    def test_repo_claude_skills_are_visible_to_the_gate(self) -> None:
        skills_dir = ROOT / ".claude" / "skills"
        if not skills_dir.is_dir():
            self.skipTest("repo has no .claude/skills")
        on_disk = {p.name for p in skills_dir.iterdir() if p.is_dir()}
        self.assertTrue(on_disk, "no skills on disk to check")
        seen = module.actual_skill_names(ROOT, "claude")
        missing = on_disk - seen
        self.assertFalse(
            missing,
            f"{len(missing)} of {len(on_disk)} repo skills are invisible to the "
            f"claude capability-home gate: {sorted(missing)[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
