#!/usr/bin/env python3
"""Every third-party module the daemon imports must be installable from the lock.

Why this exists (measured 2026-08-15): ``fastapi`` and ``watchfiles`` were
imported by ``daemon/main.py``, ``daemon/auth.py``, ``daemon/watcher.py`` and
``daemon/routes/*`` but declared nowhere in ``pyproject.toml``. ``uvicorn`` was
imported directly while resolving only as a transitive dependency of ``mcp``.

The gap was invisible on the maintainer host because those packages happened to
be installed ad hoc, so the daemon always started locally. After the documented
``uv sync``, a fresh clone got::

    ModuleNotFoundError: No module named 'fastapi'

...and nothing caught it: ``bin/squad doctor`` passes on a fresh clone because it
never imports the daemon. A clone-and-run check that never touches the daemon
cannot see a daemon that cannot start.

This test closes that by asserting the *declaration*, not the ambient
environment -- checking "can I import it right now" would pass on any host that
has the package for unrelated reasons, which is precisely how the defect hid.
"""

from __future__ import annotations

import ast
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DAEMON = REPO_ROOT / "daemon"

# Modules that ship with CPython or are first-party here; never declared deps.
_STDLIB = set(sys.stdlib_module_names) | {"daemon", "scripts", "shared", "plugins"}

# Import name -> distribution name, for the cases where they differ. Resolved
# from a static map rather than importlib.metadata on purpose: reading the
# installed environment is exactly how the original defect hid, because the
# maintainer host had packages no lockfile declared.
_DISTRIBUTION_ALIASES = {
    "yaml": "pyyaml",
    "whois": "python-whois",
    "dns": "dnspython",
}


def _top_level_imports(path: Path) -> set[str]:
    """Root module names imported at any level of one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:  # pragma: no cover - a parse failure is another test's job
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: first-party by construction.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


class DeclaredRuntimeDepsTest(unittest.TestCase):
    def _declared(self) -> set[str]:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        names = set()
        for spec in data["project"]["dependencies"]:
            name = spec.split(";")[0]
            for sep in (">=", "<=", "==", "~=", ">", "<", "!="):
                name = name.split(sep)[0]
            names.add(name.strip().lower().replace("_", "-"))
        return names

    def test_every_daemon_third_party_import_is_declared(self):
        declared = self._declared()
        missing: dict[str, set[str]] = {}
        for path in sorted(DAEMON.rglob("*.py")):
            if "tests" in path.parts:  # test-only deps are a separate contract
                continue
            for module in _top_level_imports(path):
                if module in _STDLIB:
                    continue
                dist = _DISTRIBUTION_ALIASES.get(
                    module, module.lower().replace("_", "-")
                )
                if dist in declared:
                    continue
                missing.setdefault(module, set()).add(
                    str(path.relative_to(REPO_ROOT))
                )
        self.assertEqual(
            missing,
            {},
            "daemon imports third-party modules that pyproject.toml does not "
            f"declare, so a fresh `uv sync` yields a daemon that cannot start: {missing}",
        )

    def test_the_check_can_fail(self):
        """The guard must reject an undeclared import, or it proves nothing.

        Mirrors the real check against a module known to be absent from
        pyproject, so a future refactor that quietly stops matching is caught.
        """
        declared = self._declared()
        self.assertNotIn("definitely-not-a-real-dependency", declared)
        fake = {"definitely_not_a_real_dependency"}
        undeclared = {
            m for m in fake
            if m not in _STDLIB and m.lower().replace("_", "-") not in declared
        }
        self.assertEqual(undeclared, fake)

    def test_the_known_regressions_stay_declared(self):
        declared = self._declared()
        for name in ("fastapi", "uvicorn", "watchfiles"):
            self.assertIn(
                name,
                declared,
                f"{name} is imported by the daemon; undeclaring it reproduces the "
                "2026-08-15 fresh-clone failure",
            )


if __name__ == "__main__":
    unittest.main()
