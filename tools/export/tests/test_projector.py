from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
sys.path.insert(0, str(EXPORT_DIR))

from path_policy import load_policy  # noqa: E402
from projector import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    LEDGER_CONTINUITY_FIRST_RUN,
    LEDGER_CONTINUITY_VERIFIED,
    ProjectorError,
    project,
)
import projector  # noqa: E402


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
        self._write("tools/export/identifier-denylist.txt", "blocked-target\n")
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
            "chrono/operator-setup.local.md",
            "departments/coding/inbox/payload.bin",
            "departments/coding/_state/runtime.json",
            "docs/plans/nested/private.txt",
        )
        self._git("commit", "-q", "-m", "private source")
        self.source_sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.policy_path = self.root / "tools/export/policy/path-policy.json"
        # Both fixtures sit where the tool itself puts them. The denylist is at
        # main()'s default path (policy-denied, so it stays out of the candidate
        # exactly as the old fixture did), and the ledger is DERIVED from
        # projector.DEFAULT_LEDGER_PATH rather than spelled out. Until
        # 2026-08-24 both were hardcoded under a state directory retired long
        # before, and this file was the last code anywhere that still named it:
        # a fixture path is read as an authoritative one by whoever greps for it
        # next. Deriving the ledger also means the suite exercises the real
        # default rather than an override, and cannot drift from it again.
        self.denylist = self.root / "tools/export/identifier-denylist.txt"
        self.ledger = self.root / DEFAULT_LEDGER_PATH

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
            # Each test builds a brand-new tmp rail, so its first projection
            # genuinely has no recorded history to continue. Tests that exercise
            # the guard itself override this.
            "allow_missing_ledger": self.ledger,
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

    def test_a_missing_ledger_refuses_instead_of_passing_vacuously(self) -> None:
        """An absent ledger used to be indistinguishable from a consistent one.

        `_read_last_ledger_entry` returned None for a missing file and
        `_verify_public_rail` compared only when it got a non-None entry, so the
        rail-continuity guard was skipped precisely when the recorded history
        was unavailable -- the one case you least want it skipped. This whole
        suite ran through that branch (its ledger fixture never existed) and
        could not see it.
        """
        self.assertFalse(self.ledger.exists())
        with self.assertRaisesRegex(
            ProjectorError, "continuity check has nothing to compare against"
        ):
            self._project("no-ledger", allow_missing_ledger=None)
        self.assertFalse(self.ledger.exists())

    def test_an_empty_ledger_is_no_history_either(self) -> None:
        """A file that exists but records no public tip is the same vacuum."""
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ProjectorError, "records no public tip"):
            self._project("empty-ledger", allow_missing_ledger=None)

    def test_the_first_run_optout_is_recorded_and_stops_applying(self) -> None:
        """A genuine first export stays possible, and says so in its own history.

        The opt-out permits an ABSENT ledger; it never mutes the comparison. The
        entry it writes is what makes the next run on the same rail verified,
        so the same command cannot keep skipping the guard.
        """
        first = self._project("first-run")
        self.assertEqual(first.ledger_continuity, LEDGER_CONTINUITY_FIRST_RUN)
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(entries[-1]["ledger_continuity"], LEDGER_CONTINUITY_FIRST_RUN)

        second = self._project("second-run")
        self.assertEqual(second.ledger_continuity, LEDGER_CONTINUITY_VERIFIED)
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(entries[-1]["ledger_continuity"], LEDGER_CONTINUITY_VERIFIED)

    def test_a_diverged_ledger_still_raises_even_under_the_optout(self) -> None:
        """The behaviour that already worked, pinned against the new flag."""
        self._project("seed")
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        entries[-1]["public_tip"] = self.source_sha
        self.ledger.write_text(
            "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProjectorError, "ledger/public mismatch"):
            self._project("diverged")

    def test_the_optout_cannot_start_a_second_history_beside_the_tracked_one(self) -> None:
        """The dangerous case is not "missing", it is "missing and not meant to be".

        A typo'd --ledger, a wrong --root and a resurrected retired directory
        all look like an absent ledger while the repository's real publish
        history sits untouched at DEFAULT_LEDGER_PATH. That is a fork, and no
        flag may authorise it -- an opt-out anyone can reach for reflexively is
        not protection.
        """
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(
            json.dumps({"public_tip": self.public_tip}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        typo = self.ledger.with_name("export-ledger.json")
        with self.assertRaisesRegex(ProjectorError, "already keeps its publish history"):
            self._project("forked", ledger_path=typo, allow_missing_ledger=typo)
        self.assertFalse(typo.exists())

    def test_the_optout_must_name_the_ledger_it_authorises(self) -> None:
        with self.assertRaisesRegex(ProjectorError, "must name the ledger it authorises"):
            self._project(
                "mismatched-optout",
                allow_missing_ledger=self.base / "somewhere-else.jsonl",
            )
        self.assertFalse(self.ledger.exists())


    def _seed_ledger(self, path: Path) -> None:
        """A populated ledger whose newest entry names the live public tip.

        Agreement with the rail is what made the residual hole invisible:
        `_read_last_ledger_entry` returns this record, the tip comparison
        passes, and the run reports LEDGER_CONTINUITY_VERIFIED -- about a file
        whose identity nothing ever checked.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"public_tip": self.public_tip}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _ledger_lines(self, path: Path) -> list[str]:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_a_populated_alternate_ledger_cannot_certify_continuity(self) -> None:
        """Agreeing content is not authority.

        Until 2026-08-24 the location check lived inside the absent-ledger
        branch, so it ran only when there was nothing to read. A populated
        alternate whose last entry matched the live tip therefore returned a
        record, never reached any identity check, was reported `verified` and
        was appended to -- indefinitely, while the tracked ledger sat untouched.
        The receipt was materially false: `verified` meant "the file you named
        agreed", not "the publish history agreed".
        """
        self._seed_ledger(self.ledger)
        alternate = self.base / "alternate-export-ledger.jsonl"
        self._seed_ledger(alternate)

        with self.assertRaisesRegex(ProjectorError, "already keeps its publish history"):
            self._project(
                "populated-alternate",
                ledger_path=alternate,
                # Named in the opt-out too, so this pins that no flag reaches
                # the fork case -- not merely that this run forgot to pass one.
                allow_missing_ledger=alternate,
            )

        self.assertEqual(len(self._ledger_lines(alternate)), 1)
        self.assertEqual(len(self._ledger_lines(self.ledger)), 1)

    def test_a_symlinked_ledger_cannot_certify_continuity(self) -> None:
        """The same bypass wearing a symlink, refused on resolved identity.

        Identity is decided on the resolved real path, so a link is neither a
        loophole nor a special case: it is refused when it lands somewhere other
        than the tracked ledger, for exactly the reason a plain path is.
        """
        self._seed_ledger(self.ledger)
        alternate = self.base / "alternate-export-ledger.jsonl"
        self._seed_ledger(alternate)
        link = self.base / "linked-export-ledger.jsonl"
        os.symlink(alternate, link)

        with self.assertRaisesRegex(ProjectorError, "already keeps its publish history"):
            self._project("symlinked-alternate", ledger_path=link, allow_missing_ledger=link)

        self.assertEqual(len(self._ledger_lines(alternate)), 1)

    def test_the_tracked_ledger_still_verifies_and_appends(self) -> None:
        """The guard must refuse a fork without refusing the ordinary run."""
        self._seed_ledger(self.ledger)

        result = self._project("canonical-invocation", allow_missing_ledger=None)

        self.assertEqual(result.ledger_continuity, LEDGER_CONTINUITY_VERIFIED)
        entries = [json.loads(line) for line in self._ledger_lines(self.ledger)]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["candidate_tree"], result.candidate_tree)

    def test_a_repository_with_no_recorded_history_still_publishes(self) -> None:
        """A first run stays possible where there is genuinely nothing to fork.

        The identity precondition has an oracle only while the repository keeps
        a tracked ledger. With none, the explicit path-named opt-out is still
        the way through -- and the entry it writes is what makes the next run
        verified.
        """
        self.assertFalse(self.ledger.exists())

        result = self._project("no-history-first-run", allow_missing_ledger=self.ledger)

        self.assertEqual(result.ledger_continuity, LEDGER_CONTINUITY_FIRST_RUN)
        self.assertEqual(len(self._ledger_lines(self.ledger)), 1)

    def test_a_subdirectory_root_resolves_to_the_same_repository(self) -> None:
        """git accepts a subdirectory as --root; the ledger defaults did not.

        The default ledger and the identity check both hang off the repository
        root, so they have to mean the same directory whichever path inside the
        work tree the operator names. Resolving the top-level once is what makes
        that true, and it also keeps the index writes, which are cwd-relative,
        addressing the paths `git ls-tree` reported.
        """
        self._seed_ledger(self.ledger)

        result = self._project(
            "subdirectory-root",
            root=self.root / "docs",
            allow_missing_ledger=None,
        )

        self.assertEqual(result.ledger_continuity, LEDGER_CONTINUITY_VERIFIED)
        self.assertEqual(len(self._ledger_lines(self.ledger)), 2)

    def _init_repository(self, path: Path) -> Path:
        path.mkdir(parents=True)
        subprocess.run(
            ["git", "init", "--quiet", str(path)], check=True, capture_output=True
        )
        return path

    def test_ambient_git_selectors_cannot_outrank_the_named_root(self) -> None:
        """`--root A` used to run on B whenever a shell had exported `GIT_DIR`.

        _git_top_level inherited the ambient environment, and git prefers the
        environment over its cwd without saying so, so the review's differential
        read `root/policy/ledger/gate -> repo-b/...`. All four of those hang off
        this one derivation, which is why it is pinned directly -- and the whole
        projection is then re-run under the same environment, because stripping
        the selectors for one call while every other git invocation still
        inherited them would move the wrong-root confusion rather than close it.

        Normalising this away would be the opposite of the job: a stale shell
        silently selecting another checkout is the wrong-root class this rail
        exists to expose.
        """
        other = self._init_repository(self.base / "other-repo")
        self._seed_ledger(self.ledger)

        with mock.patch.dict(
            os.environ,
            {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)},
        ):
            self.assertEqual(projector._git_top_level(self.root), self.root.resolve())
            result = self._project("ambient-selectors", allow_missing_ledger=None)

        self.assertEqual(result.ledger_continuity, LEDGER_CONTINUITY_VERIFIED)
        # `.resolve()` on both sides: the result reports the resolved gate
        # report path, and on macOS the tmpdir reaches it through /tmp -> /private/tmp.
        self.assertEqual(Path(result.gate_report).parent, self.base.resolve())
        self.assertEqual(len(self._ledger_lines(self.ledger)), 2)
        self.assertFalse((other / DEFAULT_LEDGER_PATH).exists())

    def test_a_work_tree_that_does_not_contain_the_root_is_refused(self) -> None:
        """The environment is not the only route into somebody else's work tree.

        A `.git` gitfile plus `core.worktree` reaches another checkout with no
        variable set anywhere, so stripping selectors cannot be the whole
        answer. The docstring claims this returns the repository CONTAINING
        `root`; that claim is now checked rather than asserted, and a run that
        cannot honour it stops instead of quietly deriving every path from a
        repository nobody named.
        """
        elsewhere = self._init_repository(self.base / "elsewhere")
        subprocess.run(
            ["git", "-C", str(elsewhere), "config", "core.worktree", str(elsewhere)],
            check=True,
            capture_output=True,
        )
        stray = self.base / "stray"
        stray.mkdir()
        (stray / ".git").write_text(
            f"gitdir: {elsewhere}/.git\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(
            ProjectorError, "does not contain the requested root"
        ):
            projector._git_top_level(stray)

    def test_a_repository_name_ending_in_whitespace_survives(self) -> None:
        """`.strip()` renamed the repository, and nothing downstream objected.

        A directory name ending in a space is legal on every POSIX filesystem.
        Stripping arbitrary whitespace off `rev-parse --show-toplevel` yielded a
        path to a directory that does not exist -- and `Path.resolve()` is
        non-strict, so it returned that path happily and every default the run
        derives hung off it. Only the single newline git terminates its output
        with is removed.
        """
        trailing = self._init_repository(self.base / "repo with a trailing space ")

        top_level = projector._git_top_level(trailing)

        self.assertEqual(top_level, trailing.resolve())
        self.assertTrue(str(top_level).endswith(" "), str(top_level))
        self.assertTrue(top_level.is_dir())

    def test_the_append_follows_the_verified_identity_not_the_link(self) -> None:
        """Checking a symlink and reopening it is a check of a different file.

        Identity is settled on the resolved path, so a link aimed at the tracked
        ledger passes -- and the append then reopened the LINK, which by that
        point could aim anywhere. The swap is performed from inside the run
        because that window, between the identity check and the append, is the
        only place the defect lives: the advisory target scan runs in it.

        `os.replace` rather than unlink-then-relink, because that is the shape
        an attacker gets for free -- atomic, with no interval in which the link
        is absent for the projector to notice.
        """
        self._seed_ledger(self.ledger)
        alternate = self.base / "alternate-export-ledger.jsonl"
        self._seed_ledger(alternate)
        link = self.base / "linked-export-ledger.jsonl"
        os.symlink(self.ledger, link)

        unswapped_scan = projector.target_scan.scan

        def swap_the_link_mid_run(candidate):
            repointed = link.with_name("repointed-link")
            os.symlink(alternate, repointed)
            os.replace(repointed, link)
            return unswapped_scan(candidate)

        with mock.patch.object(projector.target_scan, "scan", swap_the_link_mid_run):
            result = self._project(
                "swapped-link", ledger_path=link, allow_missing_ledger=None
            )

        self.assertEqual(os.readlink(link), str(alternate))
        self.assertEqual(result.ledger_continuity, LEDGER_CONTINUITY_VERIFIED)
        entries = self._ledger_lines(self.ledger)
        self.assertEqual(len(entries), 2)
        self.assertEqual(json.loads(entries[-1])["candidate_tree"], result.candidate_tree)
        self.assertEqual(len(self._ledger_lines(alternate)), 1)


if __name__ == "__main__":
    unittest.main()
