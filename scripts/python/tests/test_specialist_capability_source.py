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
    SURFACE_SCHEMA,
    CapabilityRef,
    CapabilitySourceError,
    SOURCE_RELATIVE,
    accepted_source_sha256s,
    available_arrays,
    load_source,
    role_surface_payload,
    role_surface_sha256,
    source_sha256,
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
    def test_projection_compatibility_hashes_include_current_and_explicit_prior(self) -> None:
        _entries, payload = load_source(ROOT)
        accepted = accepted_source_sha256s(ROOT, payload)
        self.assertIn(source_sha256(ROOT), accepted)
        self.assertTrue(
            set(payload["projection_compatible_source_sha256s"]) < accepted
        )

    def test_role_surface_payload_is_canonical_and_splits_brokered_mcps(self) -> None:
        entry = {
            "specialist": "example",
            "lane": "claude",
            "coverage": "partial",
            "limitations": ("metadata is not part of the surface",),
            "skills": (
                CapabilityRef("z-skill", "preferred", "available", "lane-inventory"),
                CapabilityRef("a-skill", "required", "installed-skill-root", "installed-skill-root"),
                CapabilityRef("draft", "preferred", "authored:stub", "shared-skills:stub"),
            ),
            "tools": (
                CapabilityRef("z-tool", "preferred", "available", "host-PATH"),
                CapabilityRef("missing", "preferred", "uninstalled", "host-PATH:absent"),
                CapabilityRef("a-tool", "required", "available", "host-PATH"),
            ),
            "mcps": (
                CapabilityRef("lead:research", "preferred", "available", "lane-inventory"),
                CapabilityRef("vault", "required", "available", "lane-inventory"),
            ),
        }

        self.assertEqual(
            role_surface_payload(entry),
            {
                "schema": SURFACE_SCHEMA,
                "lane": "claude",
                "skills": ["a-skill", "z-skill"],
                "tools": ["a-tool", "z-tool"],
                "mcps": ["vault"],
                "brokered_mcps": ["research"],
            },
        )

    def test_role_surface_hash_ignores_metadata_but_binds_lane_and_route(self) -> None:
        direct = {
            "specialist": "alpha",
            "lane": "claude",
            "coverage": "full",
            "limitations": (),
            "skills": (),
            "tools": (),
            "mcps": (
                CapabilityRef("vault", "required", "available", "lane-inventory"),
                CapabilityRef("ignored-a", "preferred", "uninstalled", "lane-not-wired"),
            ),
        }
        metadata_changed = {
            **direct,
            "specialist": "beta",
            "coverage": "partial",
            "limitations": ("different",),
            "mcps": (
                CapabilityRef("ignored-b", "preferred", "probe-failed", "pending-reprobe"),
                CapabilityRef("vault", "preferred", "available", "verified-registry:claude-mcp"),
            ),
        }
        brokered = {
            **direct,
            "mcps": (CapabilityRef("lead:vault", "required", "available", "lane-inventory"),),
        }

        self.assertEqual(role_surface_sha256(direct), role_surface_sha256(metadata_changed))
        self.assertNotEqual(role_surface_sha256(direct), role_surface_sha256({**direct, "lane": "gpt-codex"}))
        self.assertNotEqual(role_surface_sha256(direct), role_surface_sha256(brokered))

    def test_source_covers_every_routed_pair_and_every_primary_is_full(self) -> None:
        entries, payload = load_source(ROOT)
        rows = validator.runtime_rows(ROOT)
        expected = {
            (specialist, lane)
            for specialist, row in rows.items()
            for lane in validator.routed_lanes(row)
        }
        self.assertEqual(set(entries), expected)
        self.assertEqual(
            len(entries),
            sum(len(validator.routed_lanes(row)) for row in rows.values()),
        )
        self.assertEqual(
            sum(entry["coverage"] == "full" for entry in entries.values()),
            len(rows),
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
        assigned_operations = {
            server_id: set()
            for server_id in servers
            if not server_id.startswith("lead:")
        }
        for entry in entries.values():
            assigned = {ref.identifier for ref in entry["mcps"]}
            for ref in entry["tools"]:
                if not ref.provided_by:
                    continue
                self.assertIn(ref.identifier, servers[ref.provided_by])
                self.assertIn(ref.provided_by, assigned)
                if not ref.provided_by.startswith("lead:"):
                    assigned_operations[ref.provided_by].add(ref.identifier)
        # Every directly callable provider operation must have at least one
        # current routed consumer. This closes both directions without copying a
        # roster-dependent declaration count into the test.
        direct_server_operations = {
            server_id: operations
            for server_id, operations in servers.items()
            if not server_id.startswith("lead:")
        }
        self.assertEqual(assigned_operations, direct_server_operations)

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

    def test_security_capability_skills_are_active_authored_and_registered(self) -> None:
        expected = {
            "detection-as-code",
            "program-rubric-lookup",
            "forensic-timeline-authoring",
            "incident-response-runbook",
            "data-flow-trace",
            "pre-audit-threat-model",
            "security-ownership-map",
            "security-threat-model",
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
        rows = validator.runtime_rows(ROOT)
        self.assertIn(
            "firecrawl", available_arrays(entries, "research", "claude")["tools"]
        )
        self.assertNotIn(
            "firecrawl", available_arrays(entries, "research", "gemini")["tools"]
        )
        gemini_wrapper_consumers = []
        for specialist, row in sorted(rows.items()):
            if "gemini" not in validator.routed_lanes(row):
                continue
            entry = entries[(specialist, "gemini")]
            wrapper = next(
                (
                    ref
                    for ref in entry["tools"]
                    if ref.identifier == "firecrawl_scrape"
                ),
                None,
            )
            if wrapper is None:
                continue
            gemini_wrapper_consumers.append(specialist)
            self.assertEqual(wrapper.availability, "mcp-operation")
            self.assertEqual(wrapper.provided_by, "chrono-research-arsenal")
            self.assertIn(
                "chrono-research-arsenal",
                {ref.identifier for ref in entry["mcps"]},
            )
        self.assertGreater(
            len(gemini_wrapper_consumers),
            0,
            "no current Gemini-routed specialist consumes firecrawl_scrape",
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
