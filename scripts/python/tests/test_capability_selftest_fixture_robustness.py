"""The capability self-test fixtures must survive registry status changes.

Wave 2 authored `requirements-elicitation` (stub -> authored). The `composite`
negative fixture derived its intended `skill-registry-mismatch` from that real
skill's label, so the flip silently deleted the defect and turned the self-test
red. Because a negative fixture only asserts that its expected codes are a
SUBSET of the emitted codes, that class of drift is silent coverage loss.

These tests re-derive the whole fixture suite against deliberately mutated
registries and assert every intended defect still fires.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts/python/validate_capabilities.py"
REGISTRY_RELPATH = "shared/registries/skill-tool-registry.tsv"
SPEC = importlib.util.spec_from_file_location("validate_capabilities", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_capabilities = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_capabilities
SPEC.loader.exec_module(validate_capabilities)

SKILL_TYPE_CYCLE = {
    "invokable": "authored-pattern-doc",
    "authored-pattern-doc": "pattern-doc-stub",
    "pattern-doc-stub": "pattern-doc-untyped",
    "pattern-doc-untyped": "invokable",
}
TOOL_STATE_FLIP = {
    "yes": "partial",
    "lane-live": "partial",
    "partial": "yes",
    "needs-research": "yes",
    "no": "yes",
    "needs_tool": "yes",
    "catalog-absent": "yes",
}
COST_FLIP = {
    "metered": "subscription",
    "subscription": "metered",
    "unknown": "subscription",
    "—": "metered",
}
# Every real tool a fixture names because the rule under test keys on that name.
FIXTURE_TOOLS = {
    "Google Search grounding",
    "Perplexity Sonar structured+recency",
    "higgsfield__models_explore",
    "higgsfield__upscale_image",
    "Higgsfield raw generation",
    "xai_search",
}


def rewrite_registry(mutate: Callable[[dict[str, str]], None]) -> str:
    """Return the real registry TSV with `mutate` applied to every data row."""
    raw = (REPO_ROOT / REGISTRY_RELPATH).read_text(encoding="utf-8").splitlines()
    header = raw[0].split("\t")
    lines = [raw[0]]
    for line in raw[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            lines.append(line)
            continue
        row = dict(zip(header, cells))
        mutate(row)
        lines.append("\t".join(row[column] for column in header))
    return "\n".join(lines) + "\n"


def mutated_root(base: Path, registry_text: str) -> Path:
    """A repo root whose `shared/` mirrors the real one but for the registry."""
    root = base / "root"
    (root / "shared" / "registries").mkdir(parents=True)
    for child in (REPO_ROOT / "shared").iterdir():
        if child.name != "registries":
            (root / "shared" / child.name).symlink_to(child)
    for child in (REPO_ROOT / "shared" / "registries").iterdir():
        if child.name != Path(REGISTRY_RELPATH).name:
            (root / "shared" / "registries" / child.name).symlink_to(child)
    (root / REGISTRY_RELPATH).write_text(registry_text, encoding="utf-8")
    return root


class FixtureRobustnessTests(unittest.TestCase):
    def build(self, root: Path):
        validator = validate_capabilities.Validator(root)
        golden_text = {
            path: (root / path).read_text(encoding="utf-8")
            for path in validate_capabilities.GOLDEN_CARDS
        }
        return validator, validate_capabilities.build_self_test_fixtures(validator, golden_text)

    def assert_suite_holds(self, validator, suite, label: str) -> None:
        for name, text in suite.positives.items():
            result = validator.validate_text(text, f"<{label}-{name}>", None)
            self.assertEqual(
                result["status"],
                "pass",
                f"{label}: positive fixture {name} regressed: {result['errors']}",
            )
        for name, (text, expected_codes) in suite.negatives.items():
            result = validator.validate_text(text, f"<{label}-{name}>", None)
            actual = {error["code"] for error in result["errors"]}
            self.assertEqual(
                result["status"], "fail", f"{label}: negative fixture {name} stopped failing"
            )
            self.assertLessEqual(
                expected_codes,
                actual,
                f"{label}: negative fixture {name} lost "
                f"{sorted(expected_codes - actual)}; emitted {sorted(actual)}",
            )
        self.assertNotIn(
            "step-row-malformed",
            {
                error["code"]
                for error in validator.validate_text(
                    suite.negatives["bold-step-control"][0], f"<{label}-control>", None
                )["errors"]
            },
            f"{label}: the bolded control tripped the malformed-step-row detector",
        )

    def test_baseline_suite_has_no_precondition_drift(self) -> None:
        validator, suite = self.build(REPO_ROOT)
        self.assertEqual(suite.preconditions, [])
        self.assertEqual(len(suite.dead_key_fixtures), 2)
        self.assert_suite_holds(validator, suite, "baseline")

    def test_skill_status_flip_cannot_retire_a_fixture(self) -> None:
        """The exact Wave-2 shape: every skill's registry type changes."""

        def mutate(row: dict[str, str]) -> None:
            if row["record_kind"] == "skill":
                row["type"] = SKILL_TYPE_CYCLE.get(row["type"], "invokable")

        with tempfile.TemporaryDirectory() as directory:
            root = mutated_root(Path(directory), rewrite_registry(mutate))
            validator, suite = self.build(root)
            self.assertEqual(suite.preconditions, [])
            self.assert_suite_holds(validator, suite, "skill-flip")

    def test_tool_status_flip_cannot_retire_a_fixture(self) -> None:
        """Every real tool a fixture names changes verified_state and cost_tier."""

        def mutate(row: dict[str, str]) -> None:
            if row["record_kind"] == "tool" and row["name"] in FIXTURE_TOOLS:
                row["verified_state"] = TOOL_STATE_FLIP.get(row["verified_state"], "yes")
                row["cost_tier"] = COST_FLIP.get(row["cost_tier"], "subscription")

        with tempfile.TemporaryDirectory() as directory:
            root = mutated_root(Path(directory), rewrite_registry(mutate))
            validator, suite = self.build(root)
            self.assertEqual(suite.preconditions, [])
            self.assert_suite_holds(validator, suite, "tool-flip")

    def test_dead_key_revival_reports_a_named_precondition(self) -> None:
        """Losing every auth-dead key must fail loudly, not as an error-set diff."""

        def mutate(row: dict[str, str]) -> None:
            if row["record_kind"] != "tool":
                return
            if row["verified_state"] not in validate_capabilities.UNAVAILABLE_TOOL_STATES:
                return
            if validate_capabilities.unavailable_reason([row]) == "auth":
                row["verified_state"] = "yes"

        with tempfile.TemporaryDirectory() as directory:
            root = mutated_root(Path(directory), rewrite_registry(mutate))
            validator, suite = self.build(root)
            self.assertEqual(suite.dead_key_fixtures, {})
            self.assertTrue(
                any("dead-key-auth-primary" in item for item in suite.preconditions),
                f"expected a named dead-key precondition, got {suite.preconditions}",
            )
            # every remaining fixture must still assert its own defect
            self.assert_suite_holds(validator, suite, "dead-key-revival")


if __name__ == "__main__":
    unittest.main()
