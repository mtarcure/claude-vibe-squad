"""`blank_slate.rehearse` deletes `--workdir` outright. Prove it refuses to.

The guard used to reach the private repository only through `$VAULT_ROOT`. A
plain shell does not export that variable -- `bin/product-hygiene.sh:12` derives
it locally as a default instead -- so in the one context the tool is actually
run from, the refusal the docstring promised did not exist.

Every test here clears the environment first. That is the whole point: a
protection that needs a variable to be set is not a protection, it is a
coincidence.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
sys.path.insert(0, str(EXPORT_DIR))

import blank_slate  # noqa: E402
from blank_slate import BlankSlateError, _assert_safe_workdir, _forbidden_roots  # noqa: E402


#: Every variable the old implementation depended on, unset together.
BARE_ENVIRONMENT = {"CHRONO_VAULT_ROOT": "", "VAULT_ROOT": ""}


def _bare_environment():
    environment = {k: v for k, v in os.environ.items() if k not in BARE_ENVIRONMENT}
    return mock.patch.dict(os.environ, environment, clear=True)


class ForbiddenRootTests(unittest.TestCase):
    def test_private_repository_is_protected_with_no_environment_at_all(self) -> None:
        """The decisive case, and the one the old guard failed.

        With `$VAULT_ROOT` and `$CHRONO_VAULT_ROOT` unset, `_forbidden_roots()`
        previously returned only `~/Obsidian-Chrono`, so a rehearsal pointed at
        the repository itself was accepted and `shutil.rmtree` ran on it.
        """
        with _bare_environment():
            roots = [root for root, _reason in _forbidden_roots()]
            self.assertIn(REPO_ROOT.resolve(), roots)

            for workdir in [
                REPO_ROOT,
                REPO_ROOT / "tools",
                REPO_ROOT / "tools" / "export" / "scratch",
                REPO_ROOT.parent,
            ]:
                with self.subTest(workdir=str(workdir)):
                    with self.assertRaisesRegex(BlankSlateError, "protected root"):
                        _assert_safe_workdir(workdir)

    def test_refusal_names_a_derived_reason_not_an_environment_variable(self) -> None:
        with _bare_environment():
            with self.assertRaises(BlankSlateError) as caught:
                _assert_safe_workdir(REPO_ROOT)
        self.assertIn("repository containing this tool", str(caught.exception))

    def test_a_symlink_into_the_repository_is_resolved_before_the_check(self) -> None:
        with _bare_environment(), tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "innocent-looking"
            link.symlink_to(REPO_ROOT)
            with self.assertRaisesRegex(BlankSlateError, "protected root"):
                _assert_safe_workdir(link)

    def test_environment_variables_only_add_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            vault.mkdir()
            with mock.patch.dict(os.environ, {"CHRONO_VAULT_ROOT": str(vault)}):
                roots = [root for root, _reason in _forbidden_roots()]
                self.assertIn(vault.resolve(), roots)
                self.assertIn(REPO_ROOT.resolve(), roots)
                with self.assertRaisesRegex(BlankSlateError, "protected root"):
                    _assert_safe_workdir(vault / "notes")

    def test_conventional_vault_under_either_home_is_protected(self) -> None:
        """`Path.home()` honours `$HOME`; the passwd database does not. A board
        worker runs with a `$HOME` that is not the operator's, so a guard that
        consults only one of them looks in the wrong place."""
        with tempfile.TemporaryDirectory() as directory:
            fake_home = Path(directory) / "home"
            (fake_home / "Obsidian-Chrono").mkdir(parents=True)
            with _bare_environment():
                os.environ["HOME"] = str(fake_home)
                roots = [root for root, _reason in _forbidden_roots()]
                self.assertIn((fake_home / "Obsidian-Chrono").resolve(), roots)

    def test_an_existing_git_checkout_is_refused_as_a_workdir(self) -> None:
        """Backstop for a repository no derivation knows about."""
        with _bare_environment(), tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "someone-elses-repo"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            with self.assertRaisesRegex(BlankSlateError, "already a git checkout"):
                _assert_safe_workdir(checkout)

    def test_an_ordinary_scratch_directory_is_still_allowed(self) -> None:
        """The guard has to stay usable, or it gets routed around."""
        with _bare_environment(), tempfile.TemporaryDirectory() as directory:
            _assert_safe_workdir(Path(directory) / "rehearsal")


class RehearsalRefusalTests(unittest.TestCase):
    def test_rehearse_refuses_before_it_deletes_anything(self) -> None:
        """`rehearse` calls `shutil.rmtree(workdir)`. Assert the refusal happens
        first, by proving rmtree is never reached."""
        with _bare_environment(), tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate"
            candidate.mkdir()
            (candidate / "README.md").write_text("projected tree\n", encoding="utf-8")

            with mock.patch.object(blank_slate.shutil, "rmtree") as rmtree:
                with self.assertRaisesRegex(BlankSlateError, "protected root"):
                    blank_slate.rehearse(
                        candidate=candidate,
                        public_url="https://example.invalid/repo.git",
                        workdir=REPO_ROOT / "tools" / "export" / "rehearsal-scratch",
                    )
            rmtree.assert_not_called()


if __name__ == "__main__":
    unittest.main()
