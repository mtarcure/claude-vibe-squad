from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts/python/validate_capabilities.py"
SPEC = importlib.util.spec_from_file_location("validate_capabilities", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validate_capabilities = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_capabilities
SPEC.loader.exec_module(validate_capabilities)


class ExplainHintTests(unittest.TestCase):
    def test_explain_output_contains_all_four_one_line_hints(self) -> None:
        codes = (
            "capability-state-overclaim",
            "tool-lane-invalid",
            "metered-cost-contradiction",
            "skill-promotion-needs-2nd-row",
        )
        fixture = {
            "type": "capability",
            "file": "explain-fixture.md",
            "status": "fail",
            "errors": [
                validate_capabilities.Finding(code, "deliberate fixture").as_dict()
                for code in codes
            ],
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = validate_capabilities.emit_results([fixture], explain=True)

        payload = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            [error["code"] for error in payload["errors"]], list(codes)
        )
        for error in payload["errors"]:
            self.assertTrue(error["hint"].startswith("HINT: "))
            self.assertNotIn("\n", error["hint"])

    def test_skill_md_promotion_without_invokable_row_gets_specific_code(self) -> None:
        validator = validate_capabilities.Validator(REPO_ROOT)
        fixture = """---
id: project/skill-promotion-fixture
mode: project
title: Skill promotion fixture
capability_state: live
state_reason: Exercise the promotion diagnostic.
state_evidence: Unit-test fixture.
overlays: []
gates: []
cost_note: —
---
| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake | `Chrono` | — | `accessible-media-authoring` (SKILL.md) | — |
| **S7** Capture | `Chrono` | — | — | — |
"""

        result = validator.validate_text(
            fixture,
            "skill-promotion-fixture.md",
            REPO_ROOT / "skill-promotion-fixture.md",
        )

        self.assertIn(
            "skill-promotion-needs-2nd-row",
            {error["code"] for error in result["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
