from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
sys.path.insert(0, str(EXPORT_DIR))

from path_policy import load_policy  # noqa: E402
from projector import ProjectorError, project  # noqa: E402


class ProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "private"
        self.root.mkdir()
        self._git("init", "-q")
        self._git("checkout", "-q", "-b", "main")
        self._git("config", "user.name", "Projector Test")
        self._git("config", "user.email", "projector@example.invalid")

        self._copy("bin/product-hygiene.sh")
        self._copy("tools/export/path_policy.py")
        self._copy("tools/export/content_scan.py")
        self._copy("tools/export/gitleaks_filter.py")
        self._copy("tools/export/projector.py")
        self._copy("tools/export/policy/path-policy.json")
        self._copy("tools/export/policy/content-fingerprints.json")
        self._copy("tools/export/policy/gitleaks.toml")
        self._copy("tools/export/policy/gitleaks-fingerprints.json")
        self._copy(".gitignore")
        self._write("README.md", "public version one\n")
        self._write("docs/obsolete.md", "remove in source\n")
        self._write("_state/dream-config.yaml", "inputs: []\n")
        self._write("_state/.gitkeep", "")
        self._git("add", "-f", ".")
        self._git("commit", "-q", "-m", "public base")
        self.public_tip = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("update-ref", "refs/remotes/public/main", self.public_tip)
        self._git("branch", "public-export", self.public_tip)

        self._write("README.md", "public version two\n")
        (self.root / "docs/obsolete.md").unlink()
        self._write("docs/new.md", "added public file\n")
        self._write("docs/superpowers/plans/public.md", "public superpowers plan\n")
        self._write("_state/feed-config.yaml", "feeds: [private]\n")
        self._write("_state/repo-split-2026-07-16/identifier-denylist.txt", "blocked-target\n")
        self._write("chrono/operator-setup.local.md", "blocked-target private facts\n")
        self._write("departments/coding/inbox/payload.bin", "private mailbox\n")
        self._write("departments/coding/_state/runtime.json", "{}\n")
        self._write("docs/plans/nested/private.txt", "private plan\n")
        self._write(
            "moat/fixtures/purity/deny/credential.mjs",
            'export const apiKey = "api_key='
            + "sk_test_51"
            + "SyntheticCredentialValue9999"
            + '";\n',
        )
        self._write("scripts/run.sh", "#!/bin/sh\nexit 0\n")
        (self.root / "scripts/run.sh").chmod(0o755)
        os.symlink("run.sh", self.root / "scripts/run-link")
        self._git("add", "-A", "--", ".")
        self._git(
            "add",
            "-f",
            "_state/feed-config.yaml",
            "_state/repo-split-2026-07-16/identifier-denylist.txt",
            "chrono/operator-setup.local.md",
            "departments/coding/inbox/payload.bin",
            "departments/coding/_state/runtime.json",
            "docs/plans/nested/private.txt",
        )
        self._git("commit", "-q", "-m", "private source")
        self.source_sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.policy_path = self.root / "tools/export/policy/path-policy.json"
        self.denylist = self.root / "_state/repo-split-2026-07-16/identifier-denylist.txt"
        self.ledger = self.root / "_state/repo-split-2026-07-16/export-ledger.jsonl"

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        )

    def _write(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _copy(self, relative_path: str) -> None:
        source = REPO_ROOT / relative_path
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _project(self, candidate_name: str, **overrides):
        arguments = {
            "root": self.root,
            "source": self.source_sha,
            "candidate_root": self.base / candidate_name,
            "policy_path": self.policy_path,
            "identifier_denylist": self.denylist,
            "ledger_path": self.ledger,
            "gate_report": self.base / f"{candidate_name}-gate.md",
            "public_ref": "refs/remotes/public/main",
            "public_export_ref": "refs/heads/public-export",
            "expected_public_tip": self.public_tip,
            "environment": {"GITLEAKS_TIMEOUT": "30"},
        }
        arguments.update(overrides)
        return project(**arguments)

    def test_projection_is_deterministic_and_preserves_public_tree_semantics(self) -> None:
        first = self._project("candidate-a")
        second = self._project("candidate-b")
        self.assertEqual(first.candidate_tree, second.candidate_tree)

        candidate = Path(first.candidate_root)
        self.assertEqual((candidate / "README.md").read_text(), "public version two\n")
        self.assertTrue((candidate / "docs/new.md").is_file())
        self.assertFalse((candidate / "docs/obsolete.md").exists())
        self.assertTrue((candidate / "_state/dream-config.yaml").is_file())
        self.assertTrue((candidate / "_state/.gitkeep").is_file())
        self.assertFalse((candidate / "_state/feed-config.yaml").exists())
        self.assertFalse((candidate / "chrono/operator-setup.local.md").exists())
        self.assertFalse((candidate / "departments/coding/inbox/payload.bin").exists())
        self.assertFalse((candidate / "departments/coding/_state/runtime.json").exists())
        self.assertFalse((candidate / "docs/plans/nested/private.txt").exists())
        self.assertTrue((candidate / "docs/superpowers/plans/public.md").is_file())
        self.assertTrue((candidate / "scripts/run-link").is_symlink())
        self.assertEqual(os.readlink(candidate / "scripts/run-link"), "run.sh")

        mode = self._git("ls-tree", first.candidate_tree, "scripts/run.sh").stdout.split()[0]
        self.assertEqual(mode, "100755")
        diff = self._git("diff", "--name-status", self.public_tip, first.candidate_tree).stdout
        self.assertIn("M\tREADME.md", diff)
        self.assertIn("A\tdocs/new.md", diff)
        self.assertIn("D\tdocs/obsolete.md", diff)

        tree_paths = self._git("ls-tree", "-r", "--name-only", first.candidate_tree).stdout.splitlines()
        policy = load_policy(self.policy_path)
        self.assertTrue(tree_paths)
        self.assertEqual({policy.classify(path) for path in tree_paths}, {"public"})
        ledger_entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(len(ledger_entries), 2)
        self.assertEqual({entry["candidate_tree"] for entry in ledger_entries}, {first.candidate_tree})

    def test_dirty_source_and_public_tip_mismatch_fail_closed(self) -> None:
        self._write("README.md", "dirty\n")
        with self.assertRaisesRegex(ProjectorError, "source is dirty"):
            self._project("dirty-candidate")
        self._git("restore", "README.md")

        self._git("update-ref", "refs/remotes/public/main", self.source_sha)
        with self.assertRaisesRegex(ProjectorError, "public tip mismatch"):
            self._project("mismatch-candidate")

    def test_scanner_unavailable_fails_closed_without_ledger_entry(self) -> None:
        missing = self.base / "missing-gitleaks"
        with self.assertRaisesRegex(ProjectorError, "candidate gate failed"):
            self._project(
                "scanner-failure",
                environment={"GITLEAKS_BIN": str(missing), "GITLEAKS_TIMEOUT": "30"},
            )
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
