"""Capability gates must fail when repository skill artifacts disappear."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


def load_module(name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validate_capabilities = load_module(
    "validate_capabilities_skill_availability",
    "scripts/python/validate_capabilities.py",
)
validate_skill_wiring = load_module(
    "validate_skill_wiring_availability",
    "scripts/python/validate_skill_wiring.py",
)


class RegistrySkillArtifactTests(unittest.TestCase):
    def test_repository_invokable_row_requires_its_declared_skill_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "shared/registries/skill-tool-registry.tsv"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                "name\trecord_kind\ttype\tpath_or_source\n"
                "lost-skill\tskill\tinvokable\t.claude/skills/lost-skill/SKILL.md\n",
                encoding="utf-8",
            )
            runtime = root / "shared/specialist-runtime-map.tsv"
            runtime.write_text("specialist\n", encoding="utf-8")
            catalog = root / "shared/skills/catalog.txt"
            catalog.parent.mkdir(parents=True)
            catalog.write_text("lost-skill\n", encoding="utf-8")

            result = validate_capabilities.Validator(root).validate_catalog_registry()

        self.assertEqual(result["status"], "fail")
        self.assertIn(
            "registry-skill-file-missing",
            {error["code"] for error in result["errors"]},
        )


class SkillDirectoryIntegrityTests(unittest.TestCase):
    def test_skill_directory_without_skill_md_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".claude/skills/empty-skill").mkdir(parents=True)

            exit_code = validate_skill_wiring.run(root, verbose=False)

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
