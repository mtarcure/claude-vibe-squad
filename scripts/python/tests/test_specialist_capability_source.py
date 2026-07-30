from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/python"))
from specialist_capability_source import (  # noqa: E402
    CapabilitySourceError,
    SOURCE_RELATIVE,
    available_arrays,
    load_source,
)

VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_capability_homes_source_tests",
    ROOT / "scripts/python/validate_capability_homes.py",
)
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC.loader is not None
VALIDATOR_SPEC.loader.exec_module(validator)

REGISTRY_SPEC = importlib.util.spec_from_file_location(
    "lane_adapter_registry_source_tests",
    ROOT / "scripts/python/lane_adapter_registry.py",
)
registry = importlib.util.module_from_spec(REGISTRY_SPEC)
assert REGISTRY_SPEC.loader is not None
REGISTRY_SPEC.loader.exec_module(registry)


class SpecialistCapabilitySourceTests(unittest.TestCase):
    def test_source_covers_every_routed_pair_and_every_primary_is_full(self) -> None:
        entries, payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        expected = {
            (specialist, lane)
            for specialist, row in rows.items()
            for lane in validator.routed_lanes(row)
        }
        self.assertEqual(set(entries), expected)
        self.assertEqual(len(entries), 163)
        self.assertEqual(
            sum(entry["coverage"] == "full" for entry in entries.values()), 73
        )
        self.assertEqual(
            sum("primary_requirements" in entry for entry in entries.values()), 0
        )
        self.assertEqual(validator.source_coverage_diagnostics(rows, entries), [])
        self.assertEqual(
            validator.required_primary_diagnostics(rows, entries, root=ROOT), []
        )

    def test_required_installed_skill_root_is_usable(self) -> None:
        payload = json.loads((ROOT / SOURCE_RELATIVE).read_text(encoding="utf-8"))
        entry = next(item for item in payload["entries"] if item["skills"])
        skill = entry["skills"][0]
        skill.update(
            requirement="required",
            availability="installed-skill-root",
            evidence="installed-skill-root",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            entries, _payload = load_source(ROOT, path)

        self.assertIn(
            skill["id"],
            available_arrays(entries, entry["specialist"], entry["lane"])["skills"],
        )

    def test_operation_provider_relations_are_reciprocal_and_assigned(self) -> None:
        entries, payload = load_source(ROOT)
        servers = {
            item["id"]: set(item["provides"])
            for item in payload["servers"]
        }
        operations = 0
        for entry in entries.values():
            assigned = {ref.identifier for ref in entry["mcps"]}
            for ref in entry["tools"]:
                if not ref.provided_by:
                    continue
                operations += 1
                self.assertIn(ref.identifier, servers[ref.provided_by])
                self.assertIn(ref.provided_by, assigned)
        # 160 = 151 + 9. +7: prior_art_check reclassified from a phantom local
        # binary to the chrono-dedup MCP operation it actually is (the board
        # denied exploit-developer launch looking for a `prior_art_check`
        # executable that never existed). +2: exploit-developer@claude gained
        # arxiv_search/xai_search when its 2-tool set was mirrored from the
        # 28-tool codex set so cross-family PoC reproduction is symmetric.
        self.assertEqual(operations, 160)

    def test_validator_fails_closed_on_runtime_projection_drift(self) -> None:
        entries, _payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        with mock.patch.object(validator, "render_runtime_map", return_value="drift\n"):
            issues = validator.required_primary_diagnostics(
                rows,
                entries,
                root=ROOT,
            )
        self.assertIn("runtime-tool-summary", {issue["check"] for issue in issues})

    def test_validator_fails_closed_when_provider_registry_record_is_missing(self) -> None:
        entries, _payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        records = validator.shared_registry_records(ROOT)
        records.pop("chrono-research-arsenal")
        with mock.patch.object(
            validator,
            "shared_registry_records",
            return_value=records,
        ):
            issues = validator.required_primary_diagnostics(
                rows,
                entries,
                root=ROOT,
            )
        self.assertIn("provider-closure", {issue["check"] for issue in issues})

    def test_tool_backed_host_path_absent_cannot_be_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "specialist-lane-capabilities/v1",
                        "version": 1,
                        "entries": [
                            {
                                "specialist": "x",
                                "lane": "claude",
                                "coverage": "full",
                                "limitations": [],
                                "skills": [],
                                "tools": [
                                    {
                                        "id": "missing",
                                        "requirement": "required",
                                        "availability": "uninstalled",
                                        "evidence": "host-PATH:absent",
                                    }
                                ],
                                "mcps": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CapabilitySourceError, "must be preferred"):
                load_source(ROOT, path)

    def test_required_tools_are_satisfied_only_by_primary_available_source(self) -> None:
        entries, _payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        self.assertEqual(
            validator.required_primary_diagnostics(rows, entries, namespace="security"),
            [],
        )
        self.assertTrue(
            {"chrome-devtools", "playwright"}.issubset(
                set(available_arrays(entries, "scout", "claude")["mcps"])
            )
        )
        self.assertEqual(
            {lane for specialist, lane in entries if specialist == "scout"},
            {"claude", "gpt-codex"},
        )
        self.assertEqual(entries[("scout", "gpt-codex")]["coverage"], "partial")
        frontend = entries[("frontend-engineer", "gpt-codex")]
        self.assertEqual(
            tuple(
                ref.identifier
                for ref in frontend["mcps"]
                if ref.requirement == "required"
            ),
            ("chrome-devtools", "playwright"),
        )

    def test_security_recovered_skills_are_authored_and_registered(self) -> None:
        expected = {
            "attack-coverage-map",
            "detection-as-code",
            "detection-tuning",
            "program-rubric-lookup",
            "forensic-timeline-authoring",
            "incident-response-runbook",
            "data-flow-trace",
            "threat-model-loop",
        }
        with (ROOT / "shared/registries/skill-tool-registry.tsv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = {row["name"]: row for row in csv.DictReader(handle, delimiter="\t")}
        self.assertTrue(expected.issubset(rows))
        for name in expected:
            self.assertEqual(rows[name]["type"], "authored-pattern-doc")
            self.assertEqual(rows[name]["verified_state"], "authored")
            self.assertIn("status: authored", (ROOT / rows[name]["path_or_source"]).read_text(encoding="utf-8"))

    def test_adapter_render_is_deterministic_and_preserves_gemini_native_tools(self) -> None:
        first = registry.render_adapter(ROOT, "gemini", "scout")
        second = registry.render_adapter(ROOT, "gemini", "scout")
        self.assertEqual(first, second)
        self.assertIn('tools: ["read_file"', first)
        self.assertIn(f"capability_source: {SOURCE_RELATIVE.as_posix()}", first)
        self.assertNotIn("skills:", first)

    def test_projection_roundtrip_preserves_unrelated_adapter_content(self) -> None:
        codex = (
            'name = "frontend_engineer"\n'
            'sandbox_mode = "workspace-write"\n'
            '# curated-policy: keep-me\n'
            'developer_instructions = """Canonical specialist instructions live at '
            '`departments/coding/specialists/frontend-engineer.md`."""\n'
        )
        first = registry.upsert_capability_projection(
            ROOT, "gpt-codex", "frontend-engineer", codex
        )
        second = registry.upsert_capability_projection(
            ROOT, "gpt-codex", "frontend-engineer", first
        )
        self.assertEqual(first, second)
        self.assertIn('sandbox_mode = "workspace-write"', second)
        self.assertIn("# curated-policy: keep-me", second)
        self.assertEqual(second.count(registry.PROJECTION_BEGIN), 1)

        gemini = (
            "---\nname: bounty-researcher\n"
            'tools: ["read_file","run_shell_command"]\n'
            "---\n\nCanonical specialist instructions live at "
            "`departments/research/specialists/bounty-researcher.md`.\n"
        )
        projected = registry.upsert_capability_projection(
            ROOT, "gemini", "bounty-researcher", gemini
        )
        self.assertIn('tools: ["read_file","run_shell_command"]', projected)
        self.assertIn(
            'capability_mcps: ["chrono-vault","sequential-thinking"]',
            projected,
        )
        self.assertNotIn("capability_tools:", projected)
        self.assertEqual(
            projected,
            registry.upsert_capability_projection(
                ROOT, "gemini", "bounty-researcher", projected
            ),
        )

    def test_nmap_is_explicitly_preferred_and_available(self) -> None:
        entries, _payload = load_source(ROOT)
        nmap = next(ref for ref in entries[("scout", "claude")]["tools"] if ref.identifier == "nmap")
        self.assertEqual(nmap.requirement, "preferred")
        self.assertEqual(nmap.availability, "available")
        self.assertIn("nmap", available_arrays(entries, "scout", "claude")["tools"])

    def test_firecrawl_wrapper_is_primary_while_legacy_plugin_stays_claude_only(self) -> None:
        entries, _payload = load_source(ROOT)
        self.assertIn(
            "firecrawl", available_arrays(entries, "research", "claude")["tools"]
        )
        self.assertNotIn(
            "firecrawl", available_arrays(entries, "research", "gemini")["tools"]
        )
        self.assertIn(
            "firecrawl_scrape",
            available_arrays(entries, "copywriter", "gemini")["tools"],
        )

    def test_pending_and_failed_capabilities_are_tracked_but_not_projected(self) -> None:
        entries, _payload = load_source(ROOT)
        analyst = entries[("large-context-analyst", "claude")]
        ultra = next(ref for ref in analyst["skills"] if ref.identifier == "ultra-research")
        self.assertEqual(ultra.availability, "uninstalled")
        self.assertEqual(ultra.evidence, "pending-reprobe")
        self.assertNotIn(
            "ultra-research",
            available_arrays(entries, "large-context-analyst", "claude")["skills"],
        )

        for specialist in (
            "exploit-developer",
            "security-analyst",
            "smart-contract-engineer",
        ):
            for lane in ("claude", "gpt-codex"):
                refs = {
                    ref.identifier: ref.availability
                    for ref in entries[(specialist, lane)]["mcps"]
                    if ref.identifier.startswith("guarded-")
                }
                self.assertEqual(
                    refs,
                    {
                        "guarded-semgrep": "available",
                        "guarded-slither": "available",
                        "guarded-solodit": "available",
                    },
                )
                self.assertTrue(
                    set(refs).issubset(
                        available_arrays(entries, specialist, lane)["mcps"]
                    )
                )

        self.assertNotIn(
            "playwright",
            available_arrays(entries, "frontend-engineer", "gpt-codex")["tools"],
        )


if __name__ == "__main__":
    unittest.main()
