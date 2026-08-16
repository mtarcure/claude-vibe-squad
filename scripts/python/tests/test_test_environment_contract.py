from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXACT_REQUIREMENT = re.compile(r"([A-Za-z0-9_.-]+)==([^ ;]+)")


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def exact_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = EXACT_REQUIREMENT.fullmatch(line)
        if match is None:
            raise AssertionError(f"non-exact requirement in {path.relative_to(ROOT)}: {line}")
        name = canonical_name(match.group(1))
        if name in requirements:
            raise AssertionError(f"duplicate requirement in {path.relative_to(ROOT)}: {name}")
        requirements[name] = match.group(2)
    return requirements


class TestEnvironmentContractTests(unittest.TestCase):
    def test_daemon_dependencies_are_an_exact_subset_of_the_dev_test_surface(self) -> None:
        dev = exact_requirements(ROOT / "requirements-dev.txt")
        daemon = exact_requirements(ROOT / "daemon" / "requirements.txt")

        self.assertTrue(daemon)
        self.assertEqual(
            daemon,
            {name: dev[name] for name in daemon if name in dev},
            "daemon shell tests must not resolve a second or conflicting dependency surface",
        )


if __name__ == "__main__":
    unittest.main()
