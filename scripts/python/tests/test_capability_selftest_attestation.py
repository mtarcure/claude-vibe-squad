"""Behavioral guards for the capability validator's self-test contract."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts/python/validate_capabilities.py"
WRAPPER_PATH = REPO_ROOT / "bin/validate-capabilities.sh"
SPEC = importlib.util.spec_from_file_location("validate_capabilities_attestation", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_capabilities = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_capabilities
SPEC.loader.exec_module(validate_capabilities)


class WrapperAttestationTests(unittest.TestCase):
    def run_wrapper(self, capability_program: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "scripts/python").mkdir(parents=True)
            (root / "bin/validate-capabilities.sh").write_text(
                WRAPPER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (root / "scripts/python/validate_capabilities.py").write_text(
                capability_program, encoding="utf-8"
            )
            (root / "scripts/python/validate_skill_wiring.py").write_text(
                "print('self-test PASSED (fixture skill validator)')\n", encoding="utf-8"
            )
            return subprocess.run(
                ["bash", str(root / "bin/validate-capabilities.sh"), "--self-test"],
                capture_output=True,
                text=True,
            )

    def test_silent_zero_exit_cannot_attest_that_the_self_test_ran(self) -> None:
        result = self.run_wrapper("raise SystemExit(0)\n")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "FAIL[capability-self-test] missing passing self-test attestation",
            result.stderr,
        )

    def test_typed_passing_attestation_is_accepted(self) -> None:
        result = self.run_wrapper(
            "import json\n"
            "print(json.dumps({'type': 'self-test', 'status': 'pass'}))\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class BuiltInNegativeControlTests(unittest.TestCase):
    EXPECTED_FIXTURES = {
        "frontmatter-required": {"frontmatter-required"},
        "id-path-mismatch": {"id-path-mismatch"},
        "metered-without-guard": {"metered-cost-note"},
        "steps-missing": {"steps-missing"},
        "tool-state-invalid": {"tool-state-invalid"},
    }

    def test_fixture_suite_covers_each_load_bearing_diagnostic(self) -> None:
        validator = validate_capabilities.Validator(REPO_ROOT)
        golden_text = {
            path: (REPO_ROOT / path).read_text(encoding="utf-8")
            for path in validate_capabilities.GOLDEN_CARDS
        }
        suite = validate_capabilities.build_self_test_fixtures(validator, golden_text)

        for name, expected_codes in self.EXPECTED_FIXTURES.items():
            self.assertIn(name, suite.negatives)
            self.assertLessEqual(expected_codes, suite.negatives[name][1])

    def test_self_test_reports_catalog_and_fixture_negative_controls(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = validate_capabilities.self_test(
                validate_capabilities.Validator(REPO_ROOT)
            )
        payload = json.loads(output.getvalue().splitlines()[0])

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload.get("catalog_negative_controls"), "pass")
        self.assertEqual(payload.get("negative_fixture_manifest"), "pass")


if __name__ == "__main__":
    unittest.main()
