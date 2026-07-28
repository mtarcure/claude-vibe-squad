from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import vaultroot  # noqa: E402


class ResolveVaultRootTests(unittest.TestCase):
    def test_rejects_unset_environment_variable(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.resolve_vault_root()

    def test_rejects_relative_path(self) -> None:
        with mock.patch.dict(os.environ, {"CHRONO_VAULT_ROOT": "./x"}):
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.resolve_vault_root()

    def test_rejects_unresolved_environment_expression(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": "${CHRONO_VAULT_ROOT}"},
        ):
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.resolve_vault_root()

    def test_rejects_symlink_into_public_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            link = Path(temp_dir) / "vault-link"
            link.symlink_to(vaultroot.REPO_ROOT, target_is_directory=True)

            with mock.patch.dict(
                os.environ,
                {"CHRONO_VAULT_ROOT": str(link)},
            ):
                with self.assertRaises(vaultroot.VaultRootError):
                    vaultroot.resolve_vault_root()

    def test_rejects_path_under_public_repo(self) -> None:
        public_descendant = vaultroot.REPO_ROOT / "plugins"
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_ROOT": str(public_descendant)},
        ):
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.resolve_vault_root()

    def test_rejects_missing_directory_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "does-not-exist"
            with mock.patch.dict(
                os.environ,
                {"CHRONO_VAULT_ROOT": str(missing)},
            ):
                with self.assertRaises(vaultroot.VaultRootError):
                    vaultroot.resolve_vault_root()
            self.assertFalse(missing.exists())

    def test_rejects_external_directory_without_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                os.environ,
                {"CHRONO_VAULT_ROOT": temp_dir},
            ):
                with self.assertRaises(vaultroot.VaultRootError):
                    vaultroot.resolve_vault_root()

    def test_valid_external_directory_returns_realpath(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sentinel = {"vault_id": "test-private-vault", "schema_version": 1}
            (root / ".chrono-vault").write_text(json.dumps(sentinel), encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"CHRONO_VAULT_ROOT": str(root)},
            ):
                resolved = vaultroot.resolve_vault_root()

            self.assertEqual(resolved, Path(os.path.realpath(root)))
            self.assertEqual(vaultroot.read_sentinel(resolved), sentinel)

    def test_does_not_reject_safe_prefix_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            public_root = parent / "public"
            private_root = parent / "public-safe"
            public_root.mkdir()
            private_root.mkdir()
            (private_root / ".chrono-vault").write_text(
                json.dumps({"vault_id": "prefix-safe", "schema_version": 1}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(vaultroot, "PUBLIC_ROOTS", [public_root]),
                mock.patch.dict(
                    os.environ,
                    {"CHRONO_VAULT_ROOT": str(private_root)},
                ),
            ):
                self.assertEqual(
                    vaultroot.resolve_vault_root(),
                    Path(os.path.realpath(private_root)),
                )


class ReadSentinelTests(unittest.TestCase):
    def test_rejects_missing_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.read_sentinel(Path(temp_dir))

    def test_rejects_sentinel_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".chrono-vault").write_text(
                json.dumps({"vault_id": "incomplete"}),
                encoding="utf-8",
            )
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.read_sentinel(root)

    def test_rejects_non_positive_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".chrono-vault").write_text(
                json.dumps({"vault_id": "invalid-schema", "schema_version": 0}),
                encoding="utf-8",
            )
            with self.assertRaises(vaultroot.VaultRootError):
                vaultroot.read_sentinel(root)


if __name__ == "__main__":
    unittest.main()
