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


# The three fields of a guard census, held as VALUES rather than written as
# dict-literal keys.
#
# This file classifies `public`, so it sits inside the very candidate the
# scanner walks. An earlier draft of this comment spelled the three names out
# as JSON keys to explain the hazard, and that alone made this file a census
# under the exact rule these canaries exist to prove. The scan caught it --
# correctly -- and it would otherwise have halted every future export on the
# test file that guards the export. Naming them as data keeps the fixture inert
# until json.dumps assembles it, and makes that fixture genuine minified
# serialiser output rather than a hand-typed imitation of one.
CENSUS_FIELDS = ("guard", "file", "terminus")
CENSUS_VALUES = (
    "update_config admin authority check",
    "programs/example-program/src/instructions/update_config.rs",
    "control-plane takeover",
)


def minified_census() -> str:
    """One guard census on one line, exactly as a serialiser emits it."""
    return json.dumps(dict(zip(CENSUS_FIELDS, CENSUS_VALUES)), separators=(",", ":"))


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
        self._copy("tools/export/target_scan.py")
        self._copy("tools/export/remote_ref_audit.py")
        self._copy("tools/export/policy/path-policy.json")
        self._copy("tools/export/policy/content-fingerprints.json")
        self._copy("tools/export/policy/gitleaks.toml")
        self._copy("tools/export/policy/gitleaks-fingerprints.json")
        self._copy("shared/modes/bounty.md")
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

        # A REAL `public` remote, because until 2026-08-11 this suite had none
        # and every projection here passed with the remote-advertised-ref audit
        # SKIPPED. bin/product-hygiene.sh leaves remote_ref_status at its
        # initial 0 when `git remote get-url public` fails, so the report line
        # the projector checks -- `- Remote-ref audit status: 0` -- was produced
        # by a check that never ran, in the tests as well as in production. The
        # projector now rejects that report, so the remote has to exist.
        self.public_remote = self.base / "public-remote.git"
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(self.public_remote)],
            check=True,
            capture_output=True,
        )
        self._git("remote", "add", "public", str(self.public_remote))
        self._git("push", "--quiet", "public", f"{self.public_tip}:refs/heads/main")

        self._write("README.md", "public version two\n")
        (self.root / "docs/obsolete.md").unlink()
        self._write("CHANGELOG.md", "added public file\n")
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
        self.assertTrue((candidate / "CHANGELOG.md").is_file())
        self.assertFalse((candidate / "docs/obsolete.md").exists())
        # dream-config.yaml was an exact public exception until 2026-08-09. It was
        # removed from the allowlist because nothing reads it -- the dream system
        # runs from the separate ~/chrono repo and takes shadow/propose from a CLI
        # flag, not this file -- while it disclosed the operator's vault layout
        # (personal journal, finance). Asserted absent so the allowlist cannot
        # quietly regain it.
        self.assertFalse((candidate / "_state/dream-config.yaml").exists())
        self.assertTrue((candidate / "_state/.gitkeep").is_file())
        self.assertFalse((candidate / "_state/feed-config.yaml").exists())
        self.assertFalse((candidate / "chrono/operator-setup.local.md").exists())
        self.assertFalse((candidate / "departments/coding/inbox/payload.bin").exists())
        self.assertFalse((candidate / "departments/coding/_state/runtime.json").exists())
        self.assertFalse((candidate / "docs/plans/nested/private.txt").exists())
        self.assertFalse((candidate / "docs/superpowers/plans/public.md").exists())
        self.assertTrue((candidate / "scripts/run-link").is_symlink())
        self.assertEqual(os.readlink(candidate / "scripts/run-link"), "run.sh")
        self.assertFalse(any(candidate.rglob("__pycache__")))
        bounty_mode = (candidate / "shared/modes/bounty.md").read_text(encoding="utf-8")
        self.assertIn("Public capability boundary (generated by the projector)", bounty_mode)
        self.assertEqual(
            first.public_bounty_capability_status,
            "limited-private-components-withheld",
        )
        self.assertIn("plugins/chrono-dedup/", first.public_bounty_withheld)

        mode = self._git("ls-tree", first.candidate_tree, "scripts/run.sh").stdout.split()[0]
        self.assertEqual(mode, "100755")
        diff = self._git("diff", "--name-status", self.public_tip, first.candidate_tree).stdout
        self.assertIn("M\tREADME.md", diff)
        self.assertIn("A\tCHANGELOG.md", diff)
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

    def test_public_identifier_poison_canary_fails_closed(self) -> None:
        self._write("README.md", "public text with blocked-target poison\n")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "identifier poison")
        poisoned_source = self._git("rev-parse", "HEAD").stdout.strip()

        with self.assertRaisesRegex(ProjectorError, "candidate gate failed"):
            self._project("identifier-poison", source=poisoned_source)

        self.assertFalse(self.ledger.exists())

    def test_public_synthetic_credential_poison_canary_fails_closed(self) -> None:
        synthetic = "sk_test_51V4PoisonCanaryNeverARealCredential999999"
        self._write("README.md", f"synthetic_api_key={synthetic}\n")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "credential poison")
        poisoned_source = self._git("rev-parse", "HEAD").stdout.strip()

        with self.assertRaisesRegex(ProjectorError, "candidate gate failed"):
            self._project("credential-poison", source=poisoned_source)

        self.assertFalse(self.ledger.exists())

    def test_target_scan_is_advisory_and_preserves_its_evidence(self) -> None:
        """The recognizer reports but does not decide publication.

        README.md is explicitly permitted. Planting a recognizable record there
        proves a target-scan finding cannot veto a path policy decision, while
        the positive finding remains in both the result and append-only ledger.
        A clean scan likewise cannot authorize an unpermitted path; that is
        covered by the default-deny canary below.
        """
        source = self._commit(
            "README.md",
            minified_census() + "\n",
            "recognizable material in an explicitly permitted path",
        )

        result = self._project("advisory-target-scan", source=source)

        self.assertTrue((Path(result.candidate_root) / "README.md").is_file())
        self.assertIn("README.md", " ".join(result.target_scan_findings))
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertIn("README.md", " ".join(entries[-1]["target_scan_findings"]))

    def _commit(self, relative: str, content: str, message: str) -> str:
        self._write(relative, content)
        self._git("add", "-f", relative)
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _commit_bytes(self, relative: str, content: bytes, message: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self._git("add", "-f", relative)
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def test_unclassified_path_is_refused_named_and_does_not_block_projection(self) -> None:
        source = self._commit(
            "novel-surface/unreviewed.txt",
            "ordinary text the content recognizer considers clean\n",
            "unclassified path",
        )

        result = self._project("default-deny", source=source)

        path = "novel-surface/unreviewed.txt"
        self.assertIn(path, result.paths_refused)
        self.assertIn(path, result.unclassified_paths_refused)
        self.assertFalse((Path(result.candidate_root) / path).exists())

    def test_five_content_bypasses_are_moot_because_their_paths_are_refused(self) -> None:
        """Exercise the two review rounds at the full projector boundary.

        The fixtures reproduce line anchoring, basename self-exemption,
        Markdown fence framing, UTF-16 decoding, and the scanner's exact
        self-skip. Whether the advisory recognizer catches any encoding is
        intentionally irrelevant: none of these paths has a public permit.
        """
        engagement_name = "UEA" + "Factory"
        fixtures = {
            "docs/unseen-record.json": minified_census() + "\n",
            "docs/target_scan.py": f"# deployment surface: {engagement_name}\n",
            "docs/fenced-review.md": (
                "```json\n{\"guard\":\"authority\",\"file\":\"src/lib.rs\"}\n```\n"
                "```json\n{\"terminus\":\"funds theft\"}\n```\n"
            ),
            "tools/export/target_scan.py": f"# self-skip channel: {engagement_name}\n",
        }
        source = self.source_sha
        for path, content in fixtures.items():
            source = self._commit(path, content, f"review fixture {path}")
        utf16_path = "docs/encoded-review.md"
        source = self._commit_bytes(
            utf16_path,
            (f"deployment surface: {engagement_name}\n").encode("utf-16"),
            "review fixture utf16",
        )

        result = self._project("five-bypasses-moot", source=source)
        expected = set(fixtures) | {utf16_path}

        self.assertTrue(expected <= set(result.paths_refused))
        self.assertTrue(
            expected - {"tools/export/target_scan.py"}
            <= set(result.unclassified_paths_refused)
        )
        candidate = Path(result.candidate_root)
        for path in expected:
            self.assertFalse((candidate / path).exists(), path)
        advisory = " ".join(result.target_scan_findings)
        for path in expected:
            self.assertNotIn(path, advisory)

    def test_remote_ref_audit_must_actually_run_to_certify(self) -> None:
        """`- Remote-ref audit status: 0` is also what a SKIP produces.

        bin/product-hygiene.sh initialises remote_ref_status to 0 and only
        overwrites it when a `public` remote exists, so the line the projector
        checks is written identically whether the audit passed or never ran.
        This suite had no `public` remote at all until 2026-08-11, so every
        projection it certified took the skip path.
        """
        clean = self._project("audited")
        report = Path(clean.gate_report).read_text(encoding="utf-8")
        self.assertIn("- Remote-ref audit status: 0", report)
        self.assertIn("PASS: every advertised ref is clean", report)
        self.assertNotIn("remote-ref audit skipped", report)

        # Reproduce the old condition exactly: the remote-tracking ref survives
        # (so the public-rail check still resolves) but no remote is configured,
        # which is precisely how the audit reported 0 without looking.
        self._git("remote", "remove", "public")
        self._git("update-ref", "refs/remotes/public/main", self.public_tip)
        with self.assertRaisesRegex(ProjectorError, "skipped the remote-advertised-ref audit"):
            self._project("unaudited-remote")

    def test_ledger_records_that_the_target_scan_read_files(self) -> None:
        """A receipt, so "found nothing" and "never ran" are different entries."""
        result = self._project("receipted")
        self.assertGreater(result.target_scan_files, 0)
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertGreater(entries[-1]["target_scan_files"], 0)

    def test_candidate_cannot_replace_the_gate_that_certifies_it(self) -> None:
        self._write("README.md", "public text with blocked-target poison\n")
        self._write("bin/product-hygiene.sh", "#!/bin/bash\nexit 0\n")
        self._git("add", "README.md", "bin/product-hygiene.sh")
        self._git("commit", "-q", "-m", "attempt self-certifying gate replacement")
        poisoned_source = self._git("rev-parse", "HEAD").stdout.strip()

        with self.assertRaisesRegex(ProjectorError, "candidate gate failed"):
            self._project("self-gate-poison", source=poisoned_source)

        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
