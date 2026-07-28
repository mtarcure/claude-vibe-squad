#!/usr/bin/env python3
"""De-personalization invariant for the Python entry points under scripts/python.

The shell side is covered by `test_repo_root.py`. This module covers the Python
side: every script that computes a repo root must get it from
`repo_root.resolve_vault_root()` rather than a `Path.home()` default that pins
the checkout to one operator's home directory.

Each root is asserted in a subprocess because these roots are module-level
constants -- they are bound once at import, so a same-process test could only
ever observe whichever environment happened to win the first import.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"

# Converted module -> the module-level constant holding its repo root.
CONVERTED: dict[str, str] = {
    "brain_cleanup": "VAULT_ROOT",
    "browser_keep_alive": "VAULT_ROOT",
    "content_processing": "VAULT_ROOT",
    "content_synthesis": "VAULT_ROOT",
    "content_triage": "VAULT_ROOT",
    "cross_day_context": "VAULT_ROOT",
    "feed_sweep": "VAULT_ROOT",
    "mock_spawns": "VAULT",
    "registry_reconciler": "VAULT_ROOT",
    "run_weekly": "VAULT_ROOT",
    "transcription_cache_ttl": "REPO",
    "vibecoding_check": "VAULT_ROOT",
    "weekly_review_runner": "REPO",
}

# validate_specialists.py carries its root as an argparse default inside main(),
# not as a module constant, so it is asserted separately.
ARGPARSE_ROOTED = "validate_specialists"

# A path default that pins the repo to one operator's home directory.
HARDCODED_DEFAULT_RE = re.compile(r'Path\.home\(\)\s*/\s*"Obsidian-Claude-Vibe-Squad"')

# registry_reconciler.canonical_vault_root() keeps its home-relative default by
# design: it is the F12 notify-guard and must stay independent of VAULT_ROOT so a
# hermetic run cannot page the operator's real Chrono pane. See the docstring
# there. Every other occurrence under scripts/python is a regression.
HARDCODED_DEFAULT_ALLOWED = {"registry_reconciler.py"}


def _probe(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    child = {k: v for k, v in os.environ.items() if k != "VAULT_ROOT"}
    child.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(PYTHON_DIR)!r})\n{code}"],
        capture_output=True,
        text=True,
        env=child,
    )


def _module_root(module: str, attr: str, env: dict[str, str] | None = None) -> str:
    """The repo root `module` binds at import, or a skip when its deps are absent.

    The heavier scripts declare PEP 723 dependencies and normally run under
    `uv run`; a bare interpreter cannot import them. Skipping keeps this suite
    honest instead of quietly asserting nothing.
    """
    proc = _probe(f"import {module} as m\nprint(m.{attr})", env)
    if proc.returncode != 0:
        if "ModuleNotFoundError" in proc.stderr:
            raise unittest.SkipTest(f"{module}: {proc.stderr.strip().splitlines()[-1]}")
        raise AssertionError(f"{module} failed to import: {proc.stderr}")
    return proc.stdout.strip()


class ConvertedModuleRootTest(unittest.TestCase):
    """Every converted module resolves its root through the canonical resolver."""

    def test_root_is_derived_from_location_when_env_is_unset(self):
        for module, attr in CONVERTED.items():
            with self.subTest(module=module):
                self.assertEqual(Path(_module_root(module, attr)), ROOT)

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            for module, attr in CONVERTED.items():
                with self.subTest(module=module):
                    root = _module_root(module, attr, {"VAULT_ROOT": tmp})
                    self.assertEqual(Path(root), Path(tmp))

    def test_root_is_not_the_operator_home_checkout(self):
        """The regression this conversion exists to prevent.

        A worktree checkout is not ``~/Obsidian-Claude-Vibe-Squad``; before the
        conversion every one of these modules pointed at the operator's main
        checkout no matter where it was actually running from.
        """
        stale = Path.home() / "Obsidian-Claude-Vibe-Squad"
        if stale == ROOT:
            self.skipTest("tests are running from the operator's home checkout")
        for module, attr in CONVERTED.items():
            with self.subTest(module=module):
                self.assertNotEqual(Path(_module_root(module, attr)), stale)

    def test_validate_specialists_argparse_default(self):
        """Its root is an argparse default, so assert the expression and its value."""
        source = (PYTHON_DIR / f"{ARGPARSE_ROOTED}.py").read_text()
        self.assertIn(
            'parser.add_argument("--root", type=Path, default=resolve_vault_root())',
            source,
        )

        code = f"import {ARGPARSE_ROOTED} as m\nprint(m.resolve_vault_root())\n"
        proc = _probe(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(proc.stdout.strip()), ROOT)

        with tempfile.TemporaryDirectory() as tmp:
            proc = _probe(code, {"VAULT_ROOT": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()), Path(tmp))


class NoHardcodedPythonRootTest(unittest.TestCase):
    """No scripts/python entry point pins the repo to an operator home."""

    def _sources(self):
        return sorted(p for p in PYTHON_DIR.glob("*.py"))

    def test_no_module_carries_a_hardcoded_repo_default(self):
        offenders = sorted(
            p.name
            for p in self._sources()
            if HARDCODED_DEFAULT_RE.search(p.read_text(errors="ignore"))
        )
        self.assertEqual(offenders, sorted(HARDCODED_DEFAULT_ALLOWED))

    def test_the_one_survivor_is_the_notify_guard(self):
        """registry_reconciler's remaining default belongs to canonical_vault_root."""
        text = (PYTHON_DIR / "registry_reconciler.py").read_text()
        guard = text.index("def canonical_vault_root(")
        nxt = text.index("\ndef ", guard + 1)
        self.assertRegex(text[guard:nxt], HARDCODED_DEFAULT_RE)
        self.assertEqual(len(HARDCODED_DEFAULT_RE.findall(text)), 1)

    def test_converted_modules_import_the_canonical_resolver(self):
        for name in sorted(set(CONVERTED) | {ARGPARSE_ROOTED}):
            with self.subTest(module=name):
                text = (PYTHON_DIR / f"{name}.py").read_text()
                self.assertIn("from repo_root import resolve_vault_root", text)


class NotifyGuardIndependenceTest(unittest.TestCase):
    """Converting registry_reconciler.VAULT_ROOT must not disarm the F12 guard."""

    def test_canonical_vault_root_ignores_the_vault_root_override(self):
        code = "import registry_reconciler as m\nprint(m.canonical_vault_root())\n"
        with tempfile.TemporaryDirectory() as tmp:
            proc = _probe(code, {"VAULT_ROOT": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotEqual(Path(proc.stdout.strip()), Path(tmp))

    def test_canonical_vault_root_still_honours_its_own_override(self):
        code = "import registry_reconciler as m\nprint(m.canonical_vault_root())\n"
        with tempfile.TemporaryDirectory() as tmp:
            proc = _probe(code, {"CHRONO_CANONICAL_VAULT_ROOT": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()), Path(tmp))


class LegacyAliasTest(unittest.TestCase):
    """transcription_cache_ttl keeps VIBESQUAD_ROOT as a lower-precedence alias."""

    CODE = "import transcription_cache_ttl as m\nprint(m.REPO)\n"

    def test_legacy_alias_is_used_when_vault_root_is_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _probe(self.CODE, {"VIBESQUAD_ROOT": tmp})
            self.assertEqual(Path(proc.stdout.strip()), Path(tmp))

    def test_vault_root_still_outranks_the_legacy_alias(self):
        with tempfile.TemporaryDirectory() as win:
            with tempfile.TemporaryDirectory() as lose:
                proc = _probe(
                    self.CODE, {"VAULT_ROOT": win, "VIBESQUAD_ROOT": lose}
                )
                self.assertEqual(Path(proc.stdout.strip()), Path(win))


if __name__ == "__main__":
    unittest.main()
