from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


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
        entries, _payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        expected = {
            (specialist, lane)
            for specialist, row in rows.items()
            for lane in validator.routed_lanes(row)
        }
        self.assertEqual(set(entries), expected)
        self.assertEqual(len(entries), 156)
        self.assertEqual(
            sum(entry["coverage"] == "full" for entry in entries.values()), 71
        )
        self.assertEqual(
            sum("primary_requirements" in entry for entry in entries.values()), 71
        )
        self.assertEqual(validator.source_coverage_diagnostics(rows, entries), [])
        self.assertEqual(
            validator.required_primary_diagnostics(rows, entries, root=ROOT), []
        )

    def test_unavailable_capability_cannot_be_required(self) -> None:
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
                                        "evidence": "PATH probe",
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
        self.assertEqual(entries[("scout", "gemini")]["coverage"], "partial")
        self.assertEqual(entries[("scout", "gpt-codex")]["coverage"], "partial")
        frontend = entries[("frontend-engineer", "gpt-codex")]["primary_requirements"]
        self.assertEqual(
            [(item.identifier, item.kind, item.resolution, item.provider_lane) for item in frontend],
            [
                ("chrono-vault", "mcps", "local", "gpt-codex"),
                ("chrome-devtools", "mcps", "local", "gpt-codex"),
                ("playwright", "mcps", "local", "gpt-codex"),
            ],
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
        self.assertIn('capability_tools: ["google_web_search"]', projected)
        self.assertEqual(
            projected,
            registry.upsert_capability_projection(
                ROOT, "gemini", "bounty-researcher", projected
            ),
        )

    def test_nmap_is_explicitly_preferred_and_uninstalled(self) -> None:
        entries, _payload = load_source(ROOT)
        nmap = next(ref for ref in entries[("scout", "claude")]["tools"] if ref.identifier == "nmap")
        self.assertEqual(nmap.requirement, "preferred")
        self.assertEqual(nmap.availability, "uninstalled")
        self.assertNotIn("nmap", available_arrays(entries, "scout", "claude")["tools"])

    def test_firecrawl_wrapper_is_primary_while_legacy_plugin_stays_claude_only(self) -> None:
        entries, payload = load_source(ROOT)
        self.assertIn(
            "firecrawl", available_arrays(entries, "research", "claude")["tools"]
        )
        self.assertNotIn(
            "firecrawl", available_arrays(entries, "research", "gemini")["tools"]
        )
        self.assertEqual(
            payload["primary_requirement_policy"]["overrides"]["firecrawl"],
            {
                "capability_id": "firecrawl_scrape",
                "kind": "tools",
                "provider_lane": "primary",
            },
        )
        copywriter = entries[("copywriter", "gemini")]["primary_requirements"]
        self.assertIn(
            ("firecrawl", "firecrawl_scrape", "tools", "local", "gemini"),
            [
                (
                    item.identifier,
                    item.capability_id,
                    item.kind,
                    item.resolution,
                    item.provider_lane,
                )
                for item in copywriter
            ],
        )

    def test_pending_and_failed_capabilities_are_tracked_but_not_projected(self) -> None:
        entries, _payload = load_source(ROOT)
        analyst = entries[("large-context-analyst", "claude")]
        ultra = next(ref for ref in analyst["skills"] if ref.identifier == "ultra-research")
        self.assertEqual(ultra.availability, "probe-failed")
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
                        "guarded-semgrep": "pending-restart-activation",
                        "guarded-slither": "pending-restart-activation",
                        "guarded-solodit": "pending-restart-activation",
                    },
                )
                self.assertTrue(
                    set(refs).isdisjoint(
                        available_arrays(entries, specialist, lane)["mcps"]
                    )
                )

        self.assertNotIn(
            "playwright",
            available_arrays(entries, "frontend-engineer", "gpt-codex")["tools"],
        )
        self.assertNotIn(
            "playwright",
            available_arrays(entries, "scout", "gemini")["tools"],
        )


if __name__ == "__main__":
    unittest.main()
