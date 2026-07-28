#!/usr/bin/env python3
"""Tests for the canonical repo-root resolvers.

Covers `scripts/python/repo_root.py`, its shell counterpart
`shared/repo-root.sh`, and the de-personalization invariant those two exist to
enforce: no entry point may carry a hardcoded operator-local repo path.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import repo_root  # noqa: E402

SHELL_RESOLVER = ROOT / "shared" / "repo-root.sh"

# The uniform preamble every converted bin/ wrapper carries.
PREAMBLE_RE = re.compile(
    r'^source "\$\(cd -- "\$\(dirname -- "\$\(readlink -f -- "\$\{BASH_SOURCE\[0\]\}" '
    r'2>/dev/null \|\| printf \'%s\' "\$\{BASH_SOURCE\[0\]\}"\)"\)/\.\." && pwd -P\)'
    r'/shared/repo-root\.sh"$',
    re.MULTILINE,
)

# A path default that pins the repo to one operator's home directory.
HARDCODED_DEFAULT_RE = re.compile(
    r'^[A-Z_]+="\$\{[A-Z_]+:-.*Obsidian-Claude-Vibe-Squad\}"', re.MULTILINE
)


def _shell_vault_root(script: Path, env: dict | None = None) -> str:
    """Run `script` under bash and return the VAULT_ROOT it echoes."""
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    if proc.returncode != 0:
        raise AssertionError(f"{script} failed rc={proc.returncode}: {proc.stderr}")
    return proc.stdout.strip()


class ResolveVaultRootTest(unittest.TestCase):
    """scripts/python/repo_root.resolve_vault_root()."""

    def test_file_fallback_finds_the_repo_root(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULT_ROOT", None)
            self.assertEqual(repo_root.resolve_vault_root(), ROOT)

    def test_fallback_root_actually_contains_the_repo(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULT_ROOT", None)
            root = repo_root.resolve_vault_root()
        self.assertTrue((root / "shared" / "repo-root.sh").is_file())
        self.assertTrue((root / "scripts" / "python" / "repo_root.py").is_file())

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VAULT_ROOT": tmp}):
                self.assertEqual(repo_root.resolve_vault_root(), Path(tmp))

    def test_empty_env_override_falls_back(self):
        with mock.patch.dict(os.environ, {"VAULT_ROOT": ""}):
            self.assertEqual(repo_root.resolve_vault_root(), ROOT)

    def test_missing_env_override_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no-such-root")
            with mock.patch.dict(os.environ, {"VAULT_ROOT": missing}):
                with self.assertRaises(FileNotFoundError):
                    repo_root.resolve_vault_root()

    def test_env_override_is_never_canonicalised(self):
        """Callers prefix-match against VAULT_ROOT; resolving it breaks them.

        Regression guard for the /var -> /private/var rewrite that made
        dispatch_context_builder reject in-vault artifacts as unsafe paths.
        """
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with mock.patch.dict(os.environ, {"VAULT_ROOT": str(link)}):
                self.assertEqual(repo_root.resolve_vault_root(), link)

    def test_symlinked_module_still_resolves_to_the_real_repo(self):
        """A copy of the repo layout reached through a symlinked module file."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "clone"
            (fake_root / "scripts" / "python").mkdir(parents=True)
            module = fake_root / "scripts" / "python" / "repo_root.py"
            shutil.copy(PYTHON_DIR / "repo_root.py", module)
            link_dir = Path(tmp) / "elsewhere"
            link_dir.mkdir()
            link = link_dir / "repo_root.py"
            link.symlink_to(module)

            probe = (
                "import os, sys; os.environ.pop('VAULT_ROOT', None);"
                f"sys.path.insert(0, {str(link_dir)!r});"
                "import repo_root; print(repo_root.resolve_vault_root())"
            )
            out = subprocess.run(
                [sys.executable, "-c", probe], capture_output=True, text=True
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(Path(out.stdout.strip()), fake_root.resolve())


class ShellResolverTest(unittest.TestCase):
    """shared/repo-root.sh."""

    def test_resolver_exists_and_is_shell(self):
        self.assertTrue(SHELL_RESOLVER.is_file())
        self.assertTrue(SHELL_RESOLVER.read_text().startswith("#!"))

    def test_derives_repo_root_when_sourced_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.sh"
            probe.write_text(
                f'set -euo pipefail\nsource "{SHELL_RESOLVER}"\necho "$VAULT_ROOT"\n'
            )
            self.assertEqual(
                Path(_shell_vault_root(probe, {"VAULT_ROOT": ""})), ROOT
            )

    def test_env_override_wins_verbatim(self):
        """The shell resolver must not canonicalise an override either."""
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.sh"
            probe.write_text(
                f'set -euo pipefail\nsource "{SHELL_RESOLVER}"\necho "$VAULT_ROOT"\n'
            )
            self.assertEqual(_shell_vault_root(probe, {"VAULT_ROOT": tmp}), tmp)

    def test_exports_vault_root_to_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.sh"
            probe.write_text(
                f'set -euo pipefail\nsource "{SHELL_RESOLVER}"\n'
                'bash -c \'echo "$VAULT_ROOT"\'\n'
            )
            self.assertEqual(
                Path(_shell_vault_root(probe, {"VAULT_ROOT": ""})), ROOT
            )

    def test_sourced_through_a_symlink(self):
        """The resolver must survive being reached via a symlinked path."""
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "repo-root-link.sh"
            link.symlink_to(SHELL_RESOLVER)
            probe = Path(tmp) / "probe.sh"
            probe.write_text(
                f'set -euo pipefail\nsource "{link}"\necho "$VAULT_ROOT"\n'
            )
            self.assertEqual(
                Path(_shell_vault_root(probe, {"VAULT_ROOT": ""})), ROOT
            )

    def _bad_override_probe(self, tmp: Path, opts: str):
        probe = tmp / "probe.sh"
        probe.write_text(f'{opts}\nsource "{SHELL_RESOLVER}"\necho "$VAULT_ROOT"\n')
        return subprocess.run(
            ["bash", str(probe)],
            capture_output=True,
            text=True,
            env={**os.environ, "VAULT_ROOT": str(tmp / "missing")},
        )

    def test_nonexistent_override_is_always_diagnosed(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._bad_override_probe(Path(tmp), "set -uo pipefail")
            self.assertIn("not a directory", proc.stderr)

    def test_nonexistent_override_aborts_an_errexit_caller(self):
        """The resolver returns nonzero; `set -e` wrappers must abort on it."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._bad_override_probe(Path(tmp), "set -euo pipefail")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("not a directory", proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")


class WrapperPreambleTest(unittest.TestCase):
    """The preamble bin/ wrappers use to reach the resolver."""

    def _replica(self, tmp: Path) -> Path:
        """A minimal repo layout: <tmp>/repo/{shared,bin}."""
        repo = tmp / "repo"
        (repo / "shared").mkdir(parents=True)
        (repo / "bin").mkdir()
        shutil.copy(SHELL_RESOLVER, repo / "shared" / "repo-root.sh")
        preamble = PREAMBLE_RE.search(
            (ROOT / "bin" / "claim-task.sh").read_text()
        )
        assert preamble, "bin/claim-task.sh no longer carries the canonical preamble"
        wrapper = repo / "bin" / "wrapper.sh"
        wrapper.write_text(
            f'set -euo pipefail\n{preamble.group(0)}\necho "$VAULT_ROOT"\n'
        )
        return wrapper

    def test_preamble_derives_the_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = self._replica(Path(tmp))
            self.assertEqual(
                Path(_shell_vault_root(wrapper, {"VAULT_ROOT": ""})),
                (Path(tmp) / "repo").resolve(),
            )

    def test_preamble_survives_symlinked_invocation(self):
        """bin/squad is documented as `ln -s <repo>/bin/squad ~/.local/bin/squad`."""
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = self._replica(Path(tmp))
            elsewhere = Path(tmp) / "local-bin"
            elsewhere.mkdir()
            link = elsewhere / "wrapper"
            link.symlink_to(wrapper)
            self.assertEqual(
                Path(_shell_vault_root(link, {"VAULT_ROOT": ""})),
                (Path(tmp) / "repo").resolve(),
            )

    def test_preamble_honours_the_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = self._replica(Path(tmp))
            self.assertEqual(_shell_vault_root(wrapper, {"VAULT_ROOT": tmp}), tmp)


class NoHardcodedOperatorPathTest(unittest.TestCase):
    """De-personalization invariant for shell entry points under bin/."""

    def _shell_entry_points(self):
        for path in sorted((ROOT / "bin").iterdir()):
            if not path.is_file():
                continue
            try:
                head = path.read_text(errors="ignore").split("\n", 1)[0]
            except OSError:
                continue
            if head.startswith("#!") and ("bash" in head or head.endswith("sh")):
                yield path

    def test_no_wrapper_pins_the_repo_to_an_operator_home(self):
        offenders = [
            f"{p.relative_to(ROOT)}: {m.group(0)}"
            for p in self._shell_entry_points()
            for m in HARDCODED_DEFAULT_RE.finditer(p.read_text(errors="ignore"))
        ]
        self.assertEqual(offenders, [], "hardcoded repo path defaults regressed")

    def test_converted_wrappers_share_one_preamble(self):
        """Every wrapper that sources the resolver uses the canonical form."""
        divergent = []
        for path in self._shell_entry_points():
            text = path.read_text(errors="ignore")
            if "shared/repo-root.sh" not in text:
                continue
            if not PREAMBLE_RE.search(text):
                divergent.append(str(path.relative_to(ROOT)))
        self.assertEqual(divergent, [], "wrapper preamble diverged from canonical")

    def test_a_representative_sample_was_actually_converted(self):
        sample = [
            "claim-task.sh",
            "squad",
            "outbox-watcher.sh",
            "send-task.sh",
            "reconcile-selftest.sh",
            "vs-watch-spawn.sh",
        ]
        for name in sample:
            text = (ROOT / "bin" / name).read_text()
            self.assertRegex(
                text, PREAMBLE_RE, f"bin/{name} lost the resolver preamble"
            )


if __name__ == "__main__":
    unittest.main()
