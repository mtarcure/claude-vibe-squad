"""Controls for routed skill-id resolution across repo and plugin homes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts/python/validate_capabilities.py"
SOURCE_PATH = REPO_ROOT / "model-lanes/specialist-lane-capabilities.v1.json"
INDEX_PATH = REPO_ROOT / "model-lanes/generated-specialist-capabilities.json"
RETIRED_SKILL_IDS = frozenset(
    {
        "audio-layering-techniques",
        "citation-audit",
        "color-grading-basics",
        "composition-rules",
        "narrative-pacing",
        "sonic-branding",
        "video-production-principles",
        "visual-design-principles",
    }
)
SPEC = importlib.util.spec_from_file_location("validate_capabilities_skill_census", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_capabilities = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_capabilities
SPEC.loader.exec_module(validate_capabilities)


def source_entry(
    specialist: str, lane: str, skills: list[dict[str, str]]
) -> dict[str, object]:
    return {
        "specialist": specialist,
        "lane": lane,
        "coverage": "full",
        "limitations": [],
        "skills": sorted(skills, key=lambda item: item["id"].casefold()),
        "tools": [],
        "mcps": [],
    }


def source_payload(skills: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema": "specialist-lane-capabilities/v1",
        "version": 1,
        "servers": [],
        "entries": [source_entry("fixture-specialist", "claude", skills)],
    }


def available_ref(identifier: str) -> dict[str, str]:
    return {
        "id": identifier,
        "requirement": "required",
        "availability": "available",
        "evidence": "installed-or-shared-authored",
    }


def tracked_ref(identifier: str, availability: str, evidence: str) -> dict[str, str]:
    return {
        "id": identifier,
        "requirement": "preferred",
        "availability": availability,
        "evidence": evidence,
    }


class SkillReferenceCensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.user_root = self.base / "user"
        self.cache = self.user_root / ".claude/plugins/cache"
        self.settings = self.user_root / ".claude/settings.json"
        self.settings.parent.mkdir(parents=True)
        self.source = self.root / "source.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_skill(
        self,
        plugin: str,
        directory_name: str,
        *,
        declared_name: str | None = None,
        marketplace: str = "claude-plugins-official",
    ) -> Path:
        skill_file = (
            self.cache
            / marketplace
            / plugin
            / "1.0.0"
            / "skills"
            / directory_name
            / "SKILL.md"
        )
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(
            f"---\nname: {declared_name or directory_name}\n"
            "description: A trigger-shaped fixture description long enough for resolution.\n"
            "---\n\n# Fixture\n",
            encoding="utf-8",
        )
        return skill_file

    def resolver(self) -> object:
        return validate_capabilities.SkillHomeResolver(
            self.root,
            plugin_cache_root=self.cache,
            settings_paths=(self.settings,),
            installed_plugins_path=self.user_root / ".claude/plugins/installed_plugins.json",
            user_root=self.user_root,
        )

    def write_source(self, refs: list[dict[str, str]]) -> str:
        text = json.dumps(source_payload(refs), indent=2) + "\n"
        self.source.write_text(text, encoding="utf-8")
        return text

    def test_positive_controls_and_inverted_dead_id_restore(self) -> None:
        controls = (
            "systematic-debugging",
            "test-driven-development",
            "writing-skills",
        )
        for identifier in controls:
            self.write_skill("superpowers", identifier)
        self.settings.write_text(
            json.dumps(
                {"enabledPlugins": {"superpowers@claude-plugins-official": True}}
            ),
            encoding="utf-8",
        )
        original = self.write_source([available_ref(identifier) for identifier in controls])

        resolver = self.resolver()
        for identifier in controls:
            self.assertEqual(resolver.resolve(identifier).state, "enabled")
        baseline = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=resolver
        )
        self.assertEqual(baseline["status"], "pass", baseline["errors"])

        synthetic = "synthetic-dead-skill-id"
        self.write_source(
            [available_ref(identifier) for identifier in (*controls, synthetic)]
        )
        inverted = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=resolver
        )
        self.assertEqual(inverted["status"], "fail")
        self.assertEqual(inverted["blocking_absent_distinct"], 1)
        self.assertIn(
            synthetic,
            {error.get("skill_id") for error in inverted["errors"]},
        )
        self.assertIn(
            "skill-reference-absent",
            {error["code"] for error in inverted["errors"]},
        )

        self.source.write_text(original, encoding="utf-8")
        restored = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=resolver
        )
        self.assertEqual(restored["status"], "pass", restored["errors"])

    def test_disabled_plugin_reports_without_failing(self) -> None:
        self.write_skill("disabled-plugin", "cached-only")
        self.settings.write_text(
            json.dumps(
                {
                    "enabledPlugins": {
                        "disabled-plugin@claude-plugins-official": False
                    }
                }
            ),
            encoding="utf-8",
        )
        self.write_source([available_ref("cached-only")])
        resolver = self.resolver()

        self.assertEqual(resolver.resolve("cached-only").state, "plugin-disabled")
        result = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=resolver
        )
        self.assertEqual(result["status"], "pass", result["errors"])
        self.assertEqual(result["errors"], [])
        by_id = {report.get("skill_id"): report for report in result["reports"]}
        self.assertEqual(
            by_id["cached-only"]["code"], "skill-reference-plugin-disabled"
        )
        self.assertEqual(by_id["cached-only"]["severity"], "report")

    def test_disabled_plugin_report_does_not_mask_absent_failure(self) -> None:
        self.write_skill("disabled-plugin", "cached-only")
        self.settings.write_text(
            json.dumps(
                {"enabledPlugins": {"disabled-plugin@claude-plugins-official": False}}
            ),
            encoding="utf-8",
        )
        self.write_source([available_ref("cached-only"), available_ref("missing")])

        result = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=self.resolver()
        )
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            {error.get("skill_id") for error in result["errors"]}, {"missing"}
        )
        self.assertEqual(
            {report.get("skill_id") for report in result["reports"]}, {"cached-only"}
        )

    def test_owed_absent_acknowledgement_is_dated_and_consumer_exact(self) -> None:
        sandbox = available_ref("sandbox-provision-discipline")
        payload = source_payload([])
        payload["entries"] = [
            source_entry("devops-engineer", "gpt-codex", [sandbox]),
            source_entry("exploit-developer", "gpt-codex", [sandbox]),
        ]
        self.source.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        result = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=self.resolver()
        )
        self.assertEqual(result["status"], "pass", result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["reports"]), 1)
        report = result["reports"][0]
        self.assertEqual(report["code"], "skill-reference-absent")
        self.assertEqual(report["severity"], "acknowledged")
        self.assertEqual(
            report["acknowledgement"]["acknowledged_on"], "2026-08-29"
        )
        self.assertEqual(
            report["acknowledgement"]["source_task"],
            "TASK-2026-08-29-1300-u15",
        )

        payload["entries"].append(
            source_entry("fixture-specialist", "gpt-codex", [sandbox])
        )
        payload["entries"].sort(
            key=lambda entry: (entry["specialist"], entry["lane"])
        )
        self.source.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        expanded = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=self.resolver()
        )
        self.assertEqual(expanded["status"], "fail")
        self.assertEqual(
            {error.get("skill_id") for error in expanded["errors"]},
            {"sandbox-provision-discipline"},
        )

    def test_retired_pointers_are_removed_but_owed_pointer_remains(self) -> None:
        source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
        source_consumers: dict[str, set[str]] = {}
        for entry in source["entries"]:
            consumer = f'{entry["specialist"]}:{entry["lane"]}'
            for ref in entry["skills"]:
                source_consumers.setdefault(ref["id"], set()).add(consumer)
        self.assertTrue(RETIRED_SKILL_IDS.isdisjoint(source_consumers))
        self.assertEqual(
            source_consumers["sandbox-provision-discipline"],
            {"devops-engineer:gpt-codex", "exploit-developer:gpt-codex"},
        )

        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        projected = {
            identifier
            for entry in index["entries"]
            for identifier in entry["skills"]
        }
        self.assertTrue(RETIRED_SKILL_IDS.isdisjoint(projected))
        self.assertIn("sandbox-provision-discipline", projected)

    def test_frontmatter_name_wins_when_directory_name_differs(self) -> None:
        self.write_skill(
            "named-plugin", "physical-directory", declared_name="routed-identity"
        )
        self.settings.write_text(
            json.dumps(
                {"enabledPlugins": {"named-plugin@claude-plugins-official": True}}
            ),
            encoding="utf-8",
        )
        resolver = self.resolver()
        self.assertEqual(resolver.resolve("routed-identity").state, "enabled")
        self.assertEqual(resolver.resolve("physical-directory").state, "absent")

    def test_plugin_manifest_name_maps_cache_directory_to_enabled_plugin_id(self) -> None:
        self.write_skill("physical-plugin-directory", "manifest-routed-skill")
        manifest = (
            self.cache
            / "claude-plugins-official"
            / "physical-plugin-directory"
            / "1.0.0"
            / ".claude-plugin/plugin.json"
        )
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"name": "logical-plugin-name"}), encoding="utf-8"
        )
        self.settings.write_text(
            json.dumps(
                {
                    "enabledPlugins": {
                        "logical-plugin-name@claude-plugins-official": True
                    }
                }
            ),
            encoding="utf-8",
        )

        resolution = self.resolver().resolve("manifest-routed-skill")
        self.assertEqual(resolution.state, "enabled")
        self.assertIn(
            "logical-plugin-name@claude-plugins-official",
            resolution.locations[0].plugin_ids,
        )

    def test_nonprojectable_history_is_visible_but_not_a_dispatch_failure(self) -> None:
        self.settings.write_text("{}\n", encoding="utf-8")
        self.write_source(
            [
                tracked_ref("retired", "superseded", "superseded"),
                tracked_ref("draft", "authored:stub", "shared-skills:stub"),
                tracked_ref("not-installed", "uninstalled", "pending-reprobe"),
            ]
        )
        result = validate_capabilities.validate_skill_reference_census(
            self.root, source_override=self.source, resolver=self.resolver()
        )
        self.assertEqual(result["status"], "pass", result["errors"])
        self.assertEqual(result["routed_distinct"], 0)
        self.assertEqual(result["tracked_unrouted_distinct"], 3)


if __name__ == "__main__":
    unittest.main()
