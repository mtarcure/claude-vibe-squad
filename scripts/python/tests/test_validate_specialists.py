from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.python.validate_specialists import (
    LEGACY_RUNTIME_HEADER,
    POLICY_HEADER,
    PROFILE_HEADER,
    RUNTIME_HEADER,
    TOOL_HEADER,
    Validator,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/python/validate_specialists.py"


def line(fields: list[str]) -> str:
    return "\t".join(fields) + "\n"


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.row = [
            "sample", "coding", "implementation", "low", "[]", "none",
            "codex", "codex.primary", "claude", "claude.backup", "claude",
            "claude.escalate", "escalation.signal.v1", "gemini", "gemini.review",
            "none", "none", "none", "throughput.never.v1",
            "failover.conservative.v1", "[]", "false", "[]", "[]", "[]",
            "Fixture notes.", "[]", "1.0", "false",
        ]
        self.runtime_header = RUNTIME_HEADER
        self.tool_rows: list[list[str]] = []
        self._write_static()
        self.flush()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_static(self) -> None:
        self.write("shared/registries/profiles.tsv", line(PROFILE_HEADER) + "".join([
            line(["claude.backup", "claude", "claude", "high", "none", "backup"]),
            line(["claude.escalate", "claude", "claude", "max", "none", "escalation"]),
            line(["codex.primary", "codex", "codex", "high", "none", "primary"]),
            line(["gemini.review", "gemini", "gemini", "high", "none", "review"]),
        ]))
        self.write("shared/registries/policies.tsv", line(POLICY_HEADER) + "".join([
            line(["escalation.signal.v1", "escalation", "signal"]),
            line(["failover.conservative.v1", "failover", "conservative"]),
            line(["throughput.never.v1", "throughput", "never"]),
        ]))
        self.write("shared/api-catalog.md", "# fixture\n")
        self.write("departments/coding/specialists/sample.md", """# sample

## Tools available to me

### MCPs

### Skills

## When to fan out

No peers.

## When to escalate

On ambiguity.

## What I do NOT do

No unrelated work.
""")
        self.write("model-lanes/gpt-codex/.codex/agents/sample.toml",
                   'name = "sample"\ndescription = "fixture"\n')

    def add_tool(self, name: str, *, lanes: str = "codex", state: str = "yes",
                 record_type: str = "mcp-tool") -> None:
        self.tool_rows.append([name, "tool", record_type, "fixture", lanes, "invoke",
                               state, "none", "fixture", "fixture"])

    def flush(self) -> None:
        self.write("shared/specialist-runtime-map.tsv", line(self.runtime_header) + line(self.row))
        self.write("shared/registries/skill-tool-registry.tsv",
                   line(TOOL_HEADER) + "".join(line(row) for row in self.tool_rows))

    def result(self, strict_adapters: bool = False):
        self.flush()
        return Validator(self.root, expected_rows=1, strict_adapters=strict_adapters).run()


class SpecialistValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def issues(self) -> list[str]:
        findings, _summary, _code = self.fixture.result()
        return [issue for finding in findings for issue in finding.issues]

    def test_clean_fixture_passes_with_compatible_summary(self) -> None:
        findings, summary, code = self.fixture.result()
        self.assertEqual(code, 0)
        self.assertEqual(summary, "Total: 1  Passed: 1  Failed: 0  Warnings(non-fatal): 0")
        self.assertEqual([finding.status for finding in findings], ["pass"])

    def test_legacy_runtime_schema_defaults_optional_consult_false(self) -> None:
        self.fixture.runtime_header = LEGACY_RUNTIME_HEADER
        self.fixture.row = self.fixture.row[:-1]
        findings, _summary, code = self.fixture.result()
        self.assertEqual(code, 0)
        self.assertEqual([finding.status for finding in findings], ["pass"])

    def test_operator_model_consult_requires_boolean_when_present(self) -> None:
        self.fixture.row[-1] = "maybe"
        self.assertIn("invalid-operator-model-consult:maybe", self.issues())

    def test_empty_operator_model_consult_defaults_false(self) -> None:
        self.fixture.row[-1] = ""
        _findings, _summary, code = self.fixture.result()
        self.assertEqual(code, 0)

    def test_missing_tool_is_fatal(self) -> None:
        self.fixture.row[23] = "[missing-tool]"
        self.assertIn("unresolved-tool-reference:required:missing-tool", self.issues())

    def test_required_no_stale_and_retired_tools_are_fatal(self) -> None:
        cases = (("no", "mcp-tool"), ("stale", "mcp-tool"), ("yes", "retired-mcp"))
        for index, (state, record_type) in enumerate(cases):
            with self.subTest(state=state, record_type=record_type):
                fixture = Fixture(Path(self.temp.name) / str(index))
                fixture.add_tool("bad-tool", state=state, record_type=record_type)
                fixture.row[23] = "[bad-tool]"
                findings, _summary, code = fixture.result()
                all_issues = [item for finding in findings for item in finding.issues]
                self.assertEqual(code, 1)
                self.assertTrue(any(issue.startswith("unusable-required-tool:bad-tool")
                                    for issue in all_issues))

    def test_required_wrong_lane_is_fatal(self) -> None:
        self.fixture.add_tool("wrong-lane", lanes="local")
        self.fixture.row[23] = "[wrong-lane]"
        self.assertIn("required-tool-wrong-lane:wrong-lane:local", self.issues())

    def test_ambiguous_namespaced_operation_is_fatal(self) -> None:
        self.fixture.row[23] = "[family:operation]"
        self.assertIn("ambiguous-namespaced-tool:required:family:operation", self.issues())

    def test_registered_colon_identifier_remains_valid(self) -> None:
        self.fixture.add_tool("plugin:github:github", lanes="all")
        self.fixture.row[23] = "[plugin:github:github]"
        _findings, _summary, code = self.fixture.result()
        self.assertEqual(code, 0)

    def test_partial_preferred_requires_degradation(self) -> None:
        self.fixture.add_tool("partial-tool", state="partial")
        self.fixture.row[24] = "[partial-tool]"
        self.assertIn("partial-preferred-missing-degradation:partial-tool", self.issues())
        self.fixture.row[25] = "Partial tool falls back to manual work when unavailable."
        _findings, _summary, code = self.fixture.result()
        self.assertEqual(code, 0)

    def test_unrelated_degradation_keyword_does_not_cover_partial_tool(self) -> None:
        self.fixture.add_tool("partial-tool", state="partial")
        self.fixture.row[24] = "[partial-tool]"
        self.fixture.row[25] = "An unrelated compliance control is optional."
        self.assertIn("partial-preferred-missing-degradation:partial-tool", self.issues())

    def test_stale_route_name_does_not_match_inside_larger_identifier(self) -> None:
        mode = self.fixture.root / "shared/modes/project.md"
        mode.parent.mkdir(parents=True, exist_ok=True)
        mode.write_text("vibecoding-check delegates to legacy-code-auditor-v2.\n")
        _findings, _summary, code = self.fixture.result()
        self.assertEqual(code, 0)

    def test_registry_shape_duplicate_sort_and_foreign_key_failures(self) -> None:
        profile = self.fixture.root / "shared/registries/profiles.tsv"
        rows = profile.read_text().splitlines()
        profile.write_text("\n".join([rows[0], rows[2], rows[1], *rows[3:]]) + "\n")
        self.fixture.row[7] = "missing.profile"
        self.fixture.add_tool("duplicate")
        self.fixture.add_tool("duplicate")
        issues = self.issues()
        self.assertIn("registry-not-sorted", issues)
        self.assertIn("unknown-profile:missing.profile", issues)
        self.assertIn("duplicate-registry-ids:duplicate", issues)

    def test_strict_adapter_mode_fails_missing_adapter(self) -> None:
        (self.fixture.root / "model-lanes/gpt-codex/.codex/agents/sample.toml").unlink()
        findings, _summary, code = self.fixture.result(strict_adapters=True)
        self.assertEqual(code, 1)
        self.assertIn("missing-codex-agent-adapter:sample",
                      [issue for finding in findings for issue in finding.issues])

    def test_cli_emits_jsonl_and_stderr_summary(self) -> None:
        self.fixture.flush()
        completed = subprocess.run(
            [sys.executable, os.fspath(SCRIPT), "--root", os.fspath(self.fixture.root),
             "--expected-runtime-rows", "1", "--quiet"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        records = [json.loads(item) for item in completed.stdout.splitlines()]
        expected_file = (self.fixture.root /
                         "departments/coding/specialists/sample.md").resolve()
        self.assertEqual(records, [{"file": os.fspath(expected_file),
                                    "status": "pass", "issues": []}])
        self.assertEqual(completed.stderr,
                         "\nTotal: 1  Passed: 1  Failed: 0  Warnings(non-fatal): 0\n")

    def test_production_registry_has_zero_warning_budget(self) -> None:
        completed = subprocess.run(
            [sys.executable, os.fspath(SCRIPT), "--root", os.fspath(REPO_ROOT)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Warnings(non-fatal): 0", completed.stderr)
        self.assertFalse(any(json.loads(line)["status"] == "warn"
                             for line in completed.stdout.splitlines()))


if __name__ == "__main__":
    unittest.main()
