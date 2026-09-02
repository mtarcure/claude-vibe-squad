"""Pin the Kimi skill-loading contract established by the 2026-09-01 live probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_PYTHON = REPO_ROOT / "scripts/python"
if str(SCRIPTS_PYTHON) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PYTHON))


def load_validator():
    path = REPO_ROOT / "scripts/python/validate_skill_wiring.py"
    spec = importlib.util.spec_from_file_location("validate_skill_wiring_kimi_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class KimiSkillLoadingContractTests(unittest.TestCase):
    def test_kimi_is_in_per_lane_reach_via_explicit_skills_dir(self) -> None:
        lanes = {lane: (cwd, convention, evidence) for lane, cwd, convention, evidence in validator.LANE_REACH}

        self.assertIn("kimi", lanes)
        cwd, convention, evidence = lanes["kimi"]
        self.assertEqual(cwd, ".")
        self.assertEqual(convention, validator.AGENTS_SKILLS_REL)
        self.assertIn("--skills-dir", evidence)
        self.assertIn("live probe", evidence)

    def test_kimi_launcher_override_is_a_hard_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = root / validator.SUPERVISOR_REL
            supervisor.parent.mkdir(parents=True)
            supervisor.write_text("kimi launch without an explicit skill override\n", encoding="utf-8")
            self.assertTrue(validator.check_kimi_launcher(root))

            supervisor.write_text(
                "kimi launch --skills-dir .agents/skills\n",
                encoding="utf-8",
            )
            self.assertEqual(validator.check_kimi_launcher(root), [])

    def test_named_policy_and_validator_reject_the_stale_noop_story(self) -> None:
        policy = (REPO_ROOT / "model-lanes/SKILL-HOMES.md").read_text(encoding="utf-8")
        source = (REPO_ROOT / "scripts/python/validate_skill_wiring.py").read_text(encoding="utf-8")

        self.assertIn("explicit override of default project discovery", policy)
        self.assertIn("in-session /help listed injected canary", source)
        self.assertNotIn("HAS NO SKILL TOOL", source)
        self.assertNotIn("accepted by the CLI and does nothing", source)


if __name__ == "__main__":
    unittest.main()
