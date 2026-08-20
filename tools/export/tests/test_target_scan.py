"""target_scan must catch a guard census, and must not report a silent pass.

Two failures are being pinned here, and they are different in kind.

The first is coverage. `tools/radar/mutation-sbf/` -- 21 guards of a
third-party live Solana program, each with the verbatim source of the guard and
a weakened replacement -- matched NOTHING in this scanner, because no single
line of it is incriminating. `guard` appears in an MCP validator, `terminus` in
the moat schema and a dozen skills. The record only exists as a conjunction.

The second is liveness. `scan()` returned a bare list, so "clean" and "walked
nothing" were the same answer, and `main` printed the same reassuring line for
both.

This file is in target_scan.SHAPE_EXEMPT: it carries fixture text for every
conjunction, so without the exemption the scanner flags its own test suite and
the export halts on it -- which teaches everyone to route around the gate.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
sys.path.insert(0, str(EXPORT_DIR))

import target_scan  # noqa: E402
import target_scan_public  # noqa: E402
from path_policy import load_policy  # noqa: E402
from target_scan import scan  # noqa: E402


GUARD_CENSUS = """{
  "target_repo_pin": "0f1e2d3c",
  "mutants": [
    {
      "id": "G01",
      "guard": "claim_reward: the epoch id must match the epoch account",
      "file": "programs/example-program/src/instructions/claim.rs",
      "old": "require!(args.epoch_id == ctx.accounts.epoch.epoch_id, Error::Invalid);",
      "new": "require!(true, Error::Invalid);",
      "terminus": "funds theft"
    }
  ]
}
"""

CAMPAIGN_RESULT = """{
  "results": [
    {"id": "G01", "status": "SURVIVED", "killing_tests": []}
  ]
}
"""


def _configured_literal_target() -> str:
    """Derive a check-1 fixture without copying an engagement identifier here."""
    for pattern in target_scan.TARGET_NAMES:
        match = re.fullmatch(r"\\b([A-Za-z0-9_]+)\\b", pattern)
        if match:
            return match.group(1)
    raise AssertionError("TARGET_NAMES needs one literal-pattern fixture")


class PublicCiTargetScanTests(unittest.TestCase):
    """Pin both the public workflow wiring and its positive control."""

    command = ("python3", "tools/export/target_scan_public.py", ".")

    def _write_candidate_scanner(self, root: Path) -> None:
        destination = root / "tools/export/target_scan_public.py"
        destination.parent.mkdir(parents=True)
        destination.write_text(
            (EXPORT_DIR / "target_scan_public.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    def _run_public_step(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command,
            cwd=root,
            capture_output=True,
            text=True,
        )

    def test_public_workflow_runs_the_standalone_scanner_on_its_checkout(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/public-validate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- name: No engagement-target material", workflow)
        self.assertIn(f"run: {' '.join(self.command)}", workflow)
        self.assertIn(
            "if: github.repository == 'mtarcure/claude-vibe-squad'",
            workflow,
            "the public-tree scan must not run against the private repository",
        )

    def test_policy_keeps_the_private_and_public_scanners_split(self) -> None:
        policy = load_policy(EXPORT_DIR / "policy/path-policy.json")
        private = policy.decision("tools/export/target_scan.py")
        self.assertEqual(private.classification, "private")
        self.assertEqual(
            (private.policy_section, private.policy_pattern),
            ("deny", "tools/export/target_scan.py"),
        )

        public = policy.decision("tools/export/target_scan_public.py")
        self.assertEqual(public.classification, "public")
        self.assertEqual(
            (public.policy_section, public.policy_pattern),
            ("public", "tools/export/**"),
        )

    def test_public_step_fails_on_a_planted_disclosure_then_passes_clean(self) -> None:
        """Run the shipped check-2 workflow command red then green."""
        policy = load_policy(EXPORT_DIR / "policy/path-policy.json")
        self.assertEqual(policy.classify("README.md"), "public")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_candidate_scanner(root)
            planted = root / "README.md"
            planted.write_text(
                "# Public project\n\n"
                "action.sequence: synthetic input -> synthetic control\n",
                encoding="utf-8",
            )

            dirty = self._run_public_step(root)
            self.assertEqual(dirty.returncode, 1, dirty.stdout + dirty.stderr)
            self.assertIn("ENGAGEMENT-TARGET MATERIAL", dirty.stderr)
            self.assertIn("README.md:3", dirty.stderr)

            planted.write_text("# Public project\n", encoding="utf-8")
            clean = self._run_public_step(root)

        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertIn("target-shape scan clean", clean.stdout)
        self.assertIn("2 file(s)", clean.stdout)


class ScannerSplitTests(unittest.TestCase):
    """The public copy carries checks 2-4; private keeps checks 1-4."""

    def test_check_two_through_four_rule_data_stays_in_sync(self) -> None:
        shared_names = (
            "PRIMITIVE_TEXT",
            "PRIMITIVE_PARSED_FIELDS",
            "RECORD_FIELD_SHAPE",
            "ENGAGEMENT_CITATION",
            "RECORD_TOKEN_SHAPE",
            "SKIP_DIRS",
            "SHAPE_CHECKS",
            "SHAPE_EXEMPT",
        )
        for name in shared_names:
            with self.subTest(rule=name):
                self.assertEqual(
                    getattr(target_scan_public, name),
                    getattr(target_scan, name),
                )

    def test_private_and_public_scanners_agree_on_checks_two_through_four(self) -> None:
        configured_name = _configured_literal_target()
        campaign_reference = (
            "_state/" + "bounty/" + "synthetic-2026-08-15/evidence.md"
        )
        disclosure = (
            f"deployment surface: {configured_name}\n"
            "action.sequence: synthetic input -> synthetic control\n"
            '{"guard":"authority","file":"src/lib.rs",'
            '"terminus":"control-plane takeover"}\n'
            f"evidence: {campaign_reference}\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "disclosure.md").write_text(disclosure, encoding="utf-8")
            public_result = target_scan_public.scan(root)
            private_result = target_scan.scan(root)

        public_kinds = {finding.split()[0] for finding in public_result.findings}
        private_kinds = {finding.split()[0] for finding in private_result.findings}
        self.assertEqual(public_kinds, {"primitive", "record", "engagement"})
        self.assertEqual(
            private_kinds,
            {"target-name", "primitive", "record", "engagement"},
        )
        self.assertEqual(
            [
                finding
                for finding in private_result.findings
                if not finding.startswith("target-name")
            ],
            public_result.findings,
        )
        self.assertEqual(private_result.files_scanned, public_result.files_scanned)

    def test_public_scanner_contains_no_configured_engagement_identifier(self) -> None:
        public_source = (EXPORT_DIR / "target_scan_public.py").read_text(
            encoding="utf-8"
        )
        leaked_patterns = [
            pattern
            for pattern in target_scan.TARGET_NAMES
            if re.search(pattern, public_source, re.I)
        ]
        self.assertEqual(leaked_patterns, [])
        self.assertFalse(hasattr(target_scan_public, "TARGET_NAMES"))
        self.assertNotRegex(
            public_source,
            r"(?m)^\s*(?:from\s+target_scan\s+import|import\s+target_scan\b)",
        )

    def test_private_scan_still_checks_the_public_scanner_for_target_names(self) -> None:
        configured_name = _configured_literal_target()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "tools/export/target_scan_public.py"
            destination.parent.mkdir(parents=True)
            destination.write_text(
                (EXPORT_DIR / "target_scan_public.py").read_text(encoding="utf-8")
                + f"\n# synthetic leak canary: {configured_name}\n",
                encoding="utf-8",
            )
            result = target_scan.scan(root)

        self.assertEqual(
            {finding.split()[0] for finding in result.findings},
            {"target-name"},
        )
        self.assertEqual(result.paths_skipped, ())
        self.assertEqual(result.files_scanned, 1)


class RecordShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_guard_census_is_caught_though_no_single_line_is(self) -> None:
        self._write("tools/newrig/campaign/mutants.json", GUARD_CENSUS)
        result = scan(self.root)
        labels = " ".join(result.findings)
        self.assertIn("guard-weakening census", labels)
        self.assertIn("third-party repository pin", labels)
        self.assertGreater(result.files_scanned, 0)

    def test_a_mutation_campaign_scoreboard_is_caught(self) -> None:
        self._write("tools/newrig/campaign/results.json", CAMPAIGN_RESULT)
        self.assertIn("mutation-campaign result", " ".join(scan(self.root).findings))

    def test_the_conjunction_is_what_fires_not_the_individual_fields(self) -> None:
        """Precision matters more than reach here: this scanner's own comments
        record that a guard which cries wolf gets switched off.

        Each field below appears in ordinary tracked files -- `guard` in
        plugins/security-mcp-stack/validate_staged.py, `terminus` in
        moat/schemas/Verdict.schema.json and moat/pipeline/manual-slice.mjs.
        None of them may be a finding on its own.
        """
        self._write("a/schema.json", '{\n  "guard": "mcp-context-protector"\n}\n')
        self._write("b/verdict.json", '{\n  "terminus": {"class": "code_exec"}\n}\n')
        self._write("c/diff.json", '{\n  "old": "one",\n  "new": "two"\n}\n')
        self._write("d/manifest.json", '{\n  "file": "src/lib.rs"\n}\n')

        result = scan(self.root)
        self.assertEqual(result.findings, [], "single fields must not be findings")
        self.assertEqual(result.files_scanned, 4)

    def test_a_guard_and_terminus_in_one_file_still_needs_a_quoted_source(self) -> None:
        """moat/pipeline/manual-slice.mjs carries `guard:` and `terminus:` and is
        ordinary pipeline code. The third clause is what separates it from a
        census: a census points at the source it weakens."""
        self._write("e/pipeline.mjs", "const x = {\n  terminus: {},\n  guard: errors,\n};\n")
        self.assertEqual(scan(self.root).findings, [])

    def test_the_same_record_is_caught_however_it_was_serialised(self) -> None:
        """Layout is not a property of the record.

        Each file below carries the identical three fields and the identical
        meaning. The pretty-printed one was caught; the rest walked through the
        complete projector, because the rule was written about where a key sits
        on a line rather than about what the document declares. Minified JSON is
        simply what `json.dumps` emits without `indent=`.
        """
        variants = {
            "pretty.json": '{\n  "guard": "signer check",\n'
                           '  "file": "programs/next/src/lib.rs",\n'
                           '  "terminus": "funds theft"\n}\n',
            "minified.json": '{"guard":"signer check",'
                             '"file":"programs/next/src/lib.rs",'
                             '"terminus":"funds theft"}\n',
            "flow.yaml": "record: {guard: signer check, "
                         "file: programs/next/src/lib.rs, terminus: funds theft}\n",
            "fenced.md": '# notes\n\n```json\n'
                         '{"guard":"a","file":"b.rs","terminus":"c"}\n```\n',
            # A JSON key spelled with an escape. Every JSON reader on earth sees
            # a `guard` field here; no regex over the raw bytes does. This is the
            # case that makes the parse worth having on top of the text pass.
            "escaped.json": '{"\\u0067uard":"a","file":"b.rs","terminus":"c"}\n',
        }
        for name, text in variants.items():
            with self.subTest(serialisation=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / name).write_text(text, encoding="utf-8")
                    result = scan(root)
                self.assertEqual(result.files_scanned, 1)
                self.assertIn("guard-weakening census", " ".join(result.findings))

    def test_a_minified_primitive_record_is_caught_by_the_parse(self) -> None:
        """The primitive fields are line-anchored too, so a parse backs them up."""
        self._write(
            "docs/primitive.json",
            '{"witness":"src/Example.sol:820","quote":"require(ok);",'
            '"action.sequence":"deposit -> withdraw"}\n',
        )
        kinds = {finding.split()[0] for finding in scan(self.root).findings}
        self.assertEqual(kinds, {"primitive"})

    def test_a_parameter_list_is_not_a_record(self) -> None:
        """The precision budget the parse-only primitive rule is paying for.

        `,`-delimited name-colon pairs are also how Python spells an annotated
        parameter list. Resolving the single-field primitive rules textually
        flags tools/primitive-schema/validate_primitive_ledger.py, which is our
        own validator for that schema -- and a scan that cries wolf on the
        repository's own tools is a scan somebody switches off.
        """
        self._write(
            "tools/example/validator.py",
            "def quote_matches(self, witness: str, quote: str) -> bool:\n    return True\n",
        )
        result = scan(self.root)
        self.assertEqual(result.findings, [])
        self.assertEqual(result.files_scanned, 1)

    def test_a_field_name_in_running_prose_is_not_a_field(self) -> None:
        """What the `^\\s*` anchor was bought for, kept without the anchor."""
        self._write(
            "docs/prose.md",
            "The guard: nothing else reads it. The terminus: also nothing. "
            "The file: none of them.\n",
        )
        self.assertEqual(scan(self.root).findings, [])

    def test_a_dated_campaign_directory_citation_is_caught(self) -> None:
        campaign_reference = (
            "_state/" + "bounty/" + "synthetic-2026-08-15/evidence.md"
        )
        self._write("docs/citation.md", f"evidence: {campaign_reference}\n")
        kinds = {finding.split()[0] for finding in scan(self.root).findings}
        self.assertEqual(kinds, {"engagement"})

    def test_the_bare_campaign_prefix_is_not_a_real_engagement_citation(self) -> None:
        bare_prefix = "_state/" + "bounty/" + "<campaign>/evidence.md"
        self._write("docs/product.md", f"example: {bare_prefix}\n")
        self.assertEqual(scan(self.root).findings, [])


class LivenessReceiptTests(unittest.TestCase):
    def test_an_empty_tree_reports_zero_files_rather_than_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = scan(Path(directory))
            self.assertEqual(result.findings, [])
            self.assertEqual(
                result.files_scanned,
                0,
                "callers distinguish 'nothing found' from 'nothing read' on this",
            )

    def test_cli_refuses_to_print_clean_for_a_tree_it_did_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(EXPORT_DIR / "target_scan.py"), directory],
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertNotIn("clean", completed.stdout)
        self.assertIn("0 readable files", completed.stderr)

    def test_cli_exit_codes_separate_findings_from_a_clean_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ordinary.md").write_text("# A tool's README\n", encoding="utf-8")
            clean = subprocess.run(
                [sys.executable, str(EXPORT_DIR / "target_scan.py"), directory],
                capture_output=True, text=True,
            )
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            self.assertIn("1 file(s)", clean.stdout)

            (root / "mutants.json").write_text(GUARD_CENSUS, encoding="utf-8")
            dirty = subprocess.run(
                [sys.executable, str(EXPORT_DIR / "target_scan.py"), directory],
                capture_output=True, text=True,
            )
        self.assertEqual(dirty.returncode, 1, dirty.stdout + dirty.stderr)


class ExemptionTests(unittest.TestCase):
    def test_shape_exemptions_still_get_the_target_name_check(self) -> None:
        """An exemption suppresses the SHAPE checks only. A real engagement name
        smuggled into an exempt file is still caught -- otherwise the exemption
        list is a publication channel."""
        # Assembled at runtime, never written literally. A real engagement name
        # in this file's own source is a target-name hit on this file -- and the
        # exemption above is SHAPE-only, exactly so that it is. The first run of
        # the wired-in projector caught this in a fixture and refused to project
        # the whole repository, which is the gate working.
        engagement_name = _configured_literal_target()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exempt = root / "tools/primitive-schema/README.md"
            exempt.parent.mkdir(parents=True)
            exempt.write_text(
                "quote: field definition\n"
                "witness: field definition\n"
                f"The {engagement_name} contract is the deployment surface.\n",
                encoding="utf-8",
            )
            result = scan(root)

        kinds = {finding.split()[0] for finding in result.findings}
        self.assertEqual(kinds, {"target-name"}, result.findings)

    def test_the_self_skip_is_a_path_not_a_basename(self) -> None:
        """A basename exemption is a filename anyone can adopt.

        `SKIP_FILES = {"target_scan.py"}` skipped by `path.name`, so any file
        called that was exempt from the WHOLE scan -- target names included. A
        reviewer put a real configured engagement name in `docs/target_scan.py`
        and projected the tree clean. The exemption is for this one file, and
        the only thing that identifies this one file is where it lives.
        """
        engagement_name = _configured_literal_target()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("tools/export/target_scan.py", "docs/target_scan.py"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {engagement_name}\n", encoding="utf-8")
            result = scan(root)

        self.assertEqual(
            [finding.split()[1] for finding in result.findings], ["docs/target_scan.py:1"]
        )
        # The skip is reported rather than inferred. A skipped file leaves no
        # mark on `files_scanned` -- the count stays healthy on the strength of
        # every other file -- which is precisely how the basename hole stayed
        # invisible through a passing gate and a positive ledger receipt.
        self.assertEqual(result.paths_skipped, ("tools/export/target_scan.py",))
        self.assertEqual(result.files_scanned, 1)

    def test_the_scanner_still_does_not_flag_itself(self) -> None:
        """The exemption has to keep doing its job: this file necessarily
        contains every pattern it hunts for, and the candidate carries a copy."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "tools/export/target_scan.py"
            destination.parent.mkdir(parents=True)
            destination.write_text(
                (EXPORT_DIR / "target_scan.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            result = scan(root)
        self.assertEqual(result.findings, [])
        self.assertEqual(result.paths_skipped, ("tools/export/target_scan.py",))

    def test_every_self_skip_names_a_file_that_exists(self) -> None:
        """Same reasoning as the shape exemptions: a skip whose file moved is a
        hole that still reads as a considered decision."""
        missing = [
            relative
            for relative in sorted(target_scan.SKIP_PATHS)
            if not (REPO_ROOT / relative).is_file()
        ]
        self.assertEqual(missing, [])

    def test_every_shape_exemption_names_a_file_that_exists(self) -> None:
        """A stale exemption is an unearned hole: it stops protecting a file
        that moved while still reading as a considered decision."""
        missing = [
            relative
            for relative in sorted(target_scan.SHAPE_EXEMPT)
            if not (REPO_ROOT / relative).is_file()
        ]
        self.assertEqual(missing, [])


#: How a target name may join two words. Matched as literal pattern text, so
#: the fixtures below are derived from the configured rule rather than typed.
SEPARATOR_CLASSES = (r"[\s_-]?", r"\s?")


def _configured_separator_targets() -> list[tuple[str, list[str]]]:
    """Derive the separator spellings of each two-word target name.

    Nothing here types an engagement identifier. `path-policy.json` classifies
    this file `public`, and it is NOT exempt from the target-name check, so a
    literal fixture would be the very disclosure the rule exists to catch --
    the first draft of this test did exactly that. Same discipline as
    `_configured_literal_target`, extended to two-word patterns.
    """
    derived: list[tuple[str, list[str]]] = []
    for pattern in target_scan.TARGET_NAMES:
        if not (pattern.startswith(r"\b") and pattern.endswith(r"\b")):
            continue
        inner = pattern[2:-2]
        for separator in SEPARATOR_CLASSES:
            head, found, tail = inner.partition(separator)
            if not found or not head.isalnum() or not tail.isalnum():
                continue
            derived.append(
                (pattern, [f"{head}-{tail}", f"{head} {tail}", f"{head}_{tail}", head + tail])
            )
            break
    return derived


class SeparatorSpellingTests(unittest.TestCase):
    """An engagement name respelled with a separator is the same disclosure.

    The pattern here was `\\bpush\\s?chain\\b` -- written for the engagement it
    names, and blind to the hyphenated spelling the tree actually carried. It
    read as coverage because the unhyphenated forms DID match, so any file
    containing one of those was flagged and the hyphen-only lines in it were
    not. Measured 2026-08-18 on the real candidate: six findings became eight
    once the separator class was widened, and the two recovered lines each
    named the engagement outright.

    Pinned as a property of every configured name rather than as one fixture,
    so the next engagement's identifier inherits it and a name added back in
    the single-whitespace shape fails here.
    """

    def test_there_is_a_separator_pattern_to_test(self) -> None:
        """Positive control. Without it this whole class passes vacuously the
        day the derivation stops recognising the pattern shape."""
        self.assertNotEqual(_configured_separator_targets(), [])

    def test_no_configured_target_name_is_blind_to_a_separator(self) -> None:
        blind = [
            (pattern, form)
            for pattern, forms in _configured_separator_targets()
            for form in forms
            if not re.search(pattern, form, re.I)
        ]
        self.assertEqual(blind, [], "a separator respelling is the same identifier")

    def test_the_separator_spelling_is_reported_by_a_real_scan(self) -> None:
        """End to end, not just the regex: the hyphenated form on its own line,
        with no other spelling anywhere in the tree to carry the finding."""
        for pattern, forms in _configured_separator_targets():
            hyphenated = forms[0]
            with self.subTest(pattern=pattern):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "note.md").write_text(
                        f"reviewed the {hyphenated}-node build\n", encoding="utf-8"
                    )
                    result = scan(root)
                self.assertEqual(
                    [finding.split()[0] for finding in result.findings], ["target-name"]
                )
                self.assertEqual(result.files_scanned, 1)


class UnreadFileReceiptTests(unittest.TestCase):
    """A file the scan could not decode must not vanish from the receipt.

    `except (UnicodeDecodeError, OSError): continue` dropped undecodable files
    with no trace. `files_scanned` stays healthy on the strength of every other
    file, and `paths_skipped` listed only exemptions, so the ledger recorded a
    scan of 1305 files over a 1310-file candidate and nothing said the other
    five had gone unread. That is the same shape of hole the basename
    self-exemption was: a check that did not run, reported as one that did.
    """

    def _tree(self, root: Path) -> None:
        (root / "readable.md").write_text("# ordinary\n", encoding="utf-8")
        # Invalid UTF-8, which is what every binary media asset in the public
        # candidate looks like to this scanner.
        (root / "media.gif").write_bytes(b"GIF89a\xff\xfe\x00\x80payload")

    def test_an_undecodable_file_is_named_in_the_receipt(self) -> None:
        for scanner in (target_scan, target_scan_public):
            with self.subTest(scanner=scanner.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self._tree(root)
                    result = scanner.scan(root)

                self.assertEqual(result.files_scanned, 1)
                self.assertEqual(len(result.paths_skipped), 1)
                entry = result.paths_skipped[0]
                self.assertTrue(entry.startswith("media.gif "), entry)
                self.assertIn("unread", entry)
                self.assertIn("UnicodeDecodeError", entry)

    def test_the_receipt_accounts_for_every_file_walked(self) -> None:
        """The arithmetic is the point: scanned + skipped == walked. Without it
        a caller has no way to tell a complete scan from a partial one."""
        for scanner in (target_scan, target_scan_public):
            with self.subTest(scanner=scanner.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self._tree(root)
                    exempt = root / "tools/export/target_scan.py"
                    exempt.parent.mkdir(parents=True)
                    exempt.write_text("# placeholder\n", encoding="utf-8")
                    walked = sum(1 for path in root.rglob("*") if path.is_file())
                    result = scanner.scan(root)

                self.assertEqual(
                    result.files_scanned + len(result.paths_skipped),
                    walked,
                    f"receipt does not reconcile: {result.files_scanned} scanned + "
                    f"{len(result.paths_skipped)} skipped != {walked} walked",
                )


class FlaggedMaterialRegressionTests(unittest.TestCase):
    def test_the_flagged_engagement_directory_is_caught_while_it_exists(self) -> None:
        """Pins the actual incident. Whether this material may be disclosed at
        all is an operator decision in progress, so the directory may legitimately
        go away -- but while it is here, the scanner must see it."""
        flagged = REPO_ROOT / "tools/radar/mutation-sbf"
        if not flagged.is_dir():
            self.skipTest("flagged engagement directory has been resolved by the operator")
        result = scan(flagged)
        self.assertGreater(result.files_scanned, 0)
        caught = {finding.split()[1] for finding in result.findings}
        self.assertIn("mutants.json", caught)
        self.assertIn("results.json", caught)


if __name__ == "__main__":
    unittest.main()
