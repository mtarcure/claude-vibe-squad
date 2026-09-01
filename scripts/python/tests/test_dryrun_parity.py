"""`--dry-run` and the real launch must reach the same verdict (DISP-04).

Two defects made a green dry-run meaningless, and this file is the durable half
of their fix.

1. `bin/send-task.sh --dry-run` exited before the write_scope conflict scan, host
   admission and `dispatch_context_builder.build_context` -- so it asserted only
   that the shell rules passed against a shell variable, and said nothing about
   the launch invariants, which are precisely the set that fails. The builder had
   carried a `check` subcommand written for exactly this since `d35005b2`; it had
   zero callers.
2. The absent-mode rule (`mode:` omitted means modeless) was restated at three
   layers, and the ONE layer that gates -- this builder -- did not have it. A
   packet omitting `mode:` passed both earlier layers and died at launch.

The tests below pin dry-run to the launch validator, pin every mode mirror to the
builder's single home, and keep a negative control on each so a permissive
regression cannot pass as a fix.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
import dispatch_preflight  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_host_independence import (  # noqa: E402
    skip_if_trusted_lane_executable_missing,
    skip_in_host_independent_ci,
)
from verification_contract import derive_verification_contract  # noqa: E402

SEND_TASK = ROOT / "bin" / "send-task.sh"
LANE = "codex"
TO_MODEL = "gpt-codex"
# A real specialist on the Codex lane with no operator gates, so the
# fixture stays about dry-run parity rather than gate policy.
SPECIALIST = "backend-engineer"
NAMESPACE = "coding"
TASK_ID = "TASK-2026-08-29-1620-dryrunparity"
RETURN_ARTIFACT = f"departments/coding/outbox/{TASK_ID}-response.md"


def _lane_cli_available() -> bool:
    """Whether this host has the lane entrypoint `build_context` requires.

    `LANE_CLI_PATHS` is host-pinned by design (`seatbelt_profile`), so the
    subprocess parity tests can only run on a real dispatch host. Skipping is
    honest; faking the executable would make the check prove nothing.
    """

    executable = dcb.LANE_CLI_PATHS[LANE]
    resolved = Path(os.path.realpath(executable))
    return resolved.is_file() and os.access(resolved, os.X_OK)


def build_fixture_repo(
    base: Path,
    *,
    mode_row: str | None = "mode: modeless",
    write_scope: str = f"[{RETURN_ARTIFACT}]",
    return_artifact: str = RETURN_ARTIFACT,
    contract_mode: str = "modeless",
    with_contract: bool = True,
    packet_inside_repo: bool = False,
) -> tuple[Path, Path]:
    """Copy this checkout into a scratch root and author one unpublished packet.

    A copy rather than a synthesized skeleton, because the two halves under test
    read their inputs from DIFFERENT roots: `bin/send-task.sh` resolves the
    runtime map, adapters and lane-registry validators from SQUAD_CODE_ROOT
    (where the script lives), while `build_context` resolves everything from the
    repo root it is handed. A hand-built skeleton satisfies only the second, so
    a parity test built on one would prove nothing about the pair. `_state` is
    excluded so the scratch root has no registry -- the contract pin then fails
    open exactly as it does for a never-registered dry-run packet.

    Returns `(repo_root, packet_path)`. The packet sits OUTSIDE the mailbox by
    default: that is where a real dry-run packet lives, and exercising that
    staged path is half of what these tests are for.

    `with_contract=False` omits the verification contract rows. An AUTHORED
    packet must omit them -- `send-task.sh` refuses a packet that pre-populates
    controller-owned fields and derives them itself -- so the end-to-end dry-run
    tests use that shape, and the builder-level tests use the assembled shape
    the dry-run hands to `check`.
    """

    root = base / "repo"
    shutil.copytree(
        ROOT,
        root,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", "_state", "__pycache__", "*.pyc", "node_modules"
        ),
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "v2", str(root)], check=True, capture_output=True
    )

    contract = derive_verification_contract(
        {
            "task_id": TASK_ID,
            "run_id": "RUN-DRYRUN-PARITY",
            "mode": contract_mode,
            "result_type": "normal",
            "to_model": TO_MODEL,
            "dispatch_kind": "single",
            "capability": None,
            "expected_gates": [],
        }
    )
    contract_text = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    contract_hash = hashlib.sha256(contract_text.encode("ascii")).hexdigest()

    rows = [
        "---",
        f"id: {TASK_ID}",
        f"to_model: {TO_MODEL}",
        f"specialist: {SPECIALIST}",
        f"source_namespace: {NAMESPACE}",
        "run_id: RUN-DRYRUN-PARITY",
        "result_type: normal",
        "parallel_safe: false",
        "direct_lane_work_allowed: false",
        "mandatory_review: false",
        "review_triggers: []",
        "review_model: none",
        f"write_scope: {write_scope}",
        f"return_artifact: {return_artifact}",
    ]
    if not with_contract:
        rows.append("reviews: none")
    if mode_row is not None:
        rows.append(mode_row)
    if with_contract:
        rows.extend(
            (
                f"verification_contract: {contract_text}",
                f"verification_contract_sha256: {contract_hash}",
            )
        )
    rows.extend(("---", "", "Write the result.", ""))
    if packet_inside_repo:
        packet = root / "_staging" / "packet.md"
        packet.parent.mkdir(parents=True)
    else:
        packet = base / "packet.md"
    packet.write_text("\n".join(rows), encoding="utf-8")
    return root, packet


def staged_build(root: Path, packet: Path) -> dict[str, object]:
    return dcb.build_context(
        root, packet, attempt_id="d-" + "0" * 32, generation=1, staged=True
    )


class ModeRuleHasOneHomeTests(unittest.TestCase):
    """The absent-mode rule lives in `resolve_packet_mode`; mirrors follow it."""

    def test_absence_defaults_and_an_explicit_empty_does_not(self) -> None:
        self.assertEqual(dcb.resolve_packet_mode({}), "modeless")
        self.assertEqual(dcb.resolve_packet_mode({"mode": "project"}), "project")
        # Negative control. An explicitly empty row is malformed, not modeless;
        # defaulting it would silently repair a packet its author got wrong.
        self.assertEqual(dcb.resolve_packet_mode({"mode": ""}), "")

    def test_preflight_delegates_to_the_builder_rather_than_restating(self) -> None:
        """`dispatch_preflight` must CALL the home, not agree with it.

        The discriminating control: point the resolver at a DIFFERENT valid
        mode and run preflight's contract validation on a packet that omits
        `mode:` and whose contract declares that same mode. A preflight that
        delegates resolves the diverted mode and the contract agrees; a
        preflight carrying its own copy resolves `modeless`, disagrees with the
        contract, and raises. That is exactly what the previous implementation
        did -- and why comparing the two `modeless` constants proved nothing.

        A valid mode rather than a nonsense sentinel because the resolved mode
        is then checked against the contract; a sentinel fails there for the
        wrong reason and would pass this test without proving delegation.
        """

        original = dcb.resolve_packet_mode
        with tempfile.TemporaryDirectory() as directory:
            # Positive control: undiverted, absent `mode:` still resolves modeless.
            root, packet = build_fixture_repo(Path(directory), mode_row=None)
            fields, body = dcb.parse_task_packet(packet)
            self.assertNotIn("mode", fields)
            contract = dispatch_preflight._validate_contract(
                root, fields, body, packet.read_text(encoding="utf-8")
            )
            self.assertEqual(contract.fields["mode"], dcb.resolve_packet_mode({}))

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), mode_row=None, contract_mode="project"
            )
            fields, body = dcb.parse_task_packet(packet)
            text = packet.read_text(encoding="utf-8")
            dcb.resolve_packet_mode = lambda mapping: "project"
            try:
                diverted = dispatch_preflight._validate_contract(
                    root, fields, body, text
                )
            finally:
                dcb.resolve_packet_mode = original
        self.assertEqual(diverted.fields["mode"], "project")

    def test_send_task_shell_mirror_agrees_with_the_builder(self) -> None:
        """The shell default is a mirror; a drifting copy must fail here.

        `bin/send-task.sh` cannot import the builder for one string, so it keeps
        a literal. This asserts the literal, its mirror comment, and the
        absence-only guard around it -- an unconditional shell default would
        also swallow the malformed empty row the builder rejects above.
        """

        text = SEND_TASK.read_text(encoding="utf-8")
        self.assertIn("resolve_packet_mode() in", text)
        match = re.search(
            r'task_frontmatter_has_field "mode" && MODE_PRESENT=true\n'
            r"if ! \$MODE_PRESENT; then\n"
            r'    MODE="([^"]+)"\n',
            text,
        )
        self.assertIsNotNone(match, "send-task.sh absent-mode default not found")
        assert match is not None
        self.assertEqual(match.group(1), dcb.resolve_packet_mode({}))


class BuilderAcceptsAbsentModeTests(unittest.TestCase):
    """The gating layer now applies the rule the earlier layers already did."""

    def test_packet_without_mode_builds_and_runs_modeless(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(Path(directory), mode_row=None)
            context = staged_build(root, packet)
        self.assertEqual(context["authority"]["memory_context"]["mode"], "modeless")
        # The contract agreement check compares the packet's resolved mode with
        # the contract's; a defaulted mode has to satisfy it, not bypass it.
        self.assertEqual(
            context["authority"]["budgets"]["timeout_seconds"],
            dcb.timeout_budget_for_mode("modeless"),
        )

    def test_explicitly_empty_mode_is_still_refused(self) -> None:
        """Negative control: the default did not make the builder permissive."""

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(Path(directory), mode_row="mode:")
            with self.assertRaisesRegex(
                dcb.DispatchContextError, "missing required frontmatter field"
            ):
                staged_build(root, packet)

    def test_a_wrong_mode_still_fails_contract_agreement(self) -> None:
        """Negative control: absence defaults, disagreement still refuses."""

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), mode_row=None, contract_mode="project"
            )
            with self.assertRaisesRegex(
                dcb.DispatchContextError, "run/mode mismatch"
            ):
                staged_build(root, packet)


class StagedCheckMatchesLaunchTests(unittest.TestCase):
    """`check --staged` must run the launch invariants, not a subset."""

    def _check(self, root: Path, packet: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "python" / "dispatch_context_builder.py"),
                "check",
                "--repo-root",
                str(root),
                "--task-file",
                str(packet),
                "--staged",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_valid_packet_passes_staged_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(Path(directory))
            result = self._check(root, packet)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("preflight OK", result.stdout)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_staged_check_refuses_a_launch_invariant_violation(self) -> None:
        """The bug class: shell-only rules pass, the launch invariant does not.

        `return_artifact` outside `write_scope` is refused by `build_context`
        alone. Before this wiring the dry-run exited 2 (green) on exactly this
        packet and the launch then died. The scope path is a TRACKED one on
        purpose: a git-ignored path trips the shell's own promotion check first
        and would prove nothing about the preflight.
        """

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), write_scope="[docs/unrelated/]"
            )
            result = self._check(root, packet)
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, msg=output)
        self.assertIn("return_artifact is outside packet write_scope", output)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_staged_substitutes_only_the_mailbox_location_check(self) -> None:
        """Positive control on the relaxation itself.

        `staged=True` must weaken exactly one check. Proof: the same packet that
        passes staged is refused unstaged for the location reason alone, and its
        recorded read_scope still names the canonical inbox path it will occupy.
        """

        if not _lane_cli_available():
            self.skipTest("lane CLI absent on this host")
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), packet_inside_repo=True
            )
            context = staged_build(root, packet)
            with self.assertRaisesRegex(
                dcb.DispatchContextError, "exact unified mailbox path"
            ):
                dcb.build_context(
                    root, packet, attempt_id="d-" + "0" * 32, generation=1
                )
        self.assertIn(
            dcb.canonical_mailbox_relative("inbox", TASK_ID),
            context["authority"]["read_scope"],
        )


class StagedAndLaunchAgreeOnTheSameBytesTests(unittest.TestCase):
    """THE parity control: run BOTH halves on one packet and compare.

    Every other test here exercises a single half. That is what let the first
    submission ship a green suite while an injected launch-only rejection went
    undetected: a source assertion that both CLI branches spell
    `build_context(` proves shared spelling, not shared behavior -- and
    `staged` is a control-flow input to that shared function, so spelling is
    precisely the thing that cannot settle it.

    So these tests execute it. One assembled packet is validated staged, the
    IDENTICAL BYTES are copied to the canonical inbox, and the unstaged launch
    builder runs on them with the same attempt id, generation, clock and nonce
    -- every non-deterministic input pinned, so any difference in the two
    contexts is a real divergence and not a timestamp. Acceptance and the full
    context are compared on valid packets; failure class and reason are
    compared on invalid ones.

    Falsification (run before submission, both directions):

    - launch-only mutation -- wrap `dcb.build_context` to raise on a successful
      unstaged call: the valid-packet tests go RED.
    - staged-only mutation -- wrap it to raise on a successful staged call: the
      same tests go RED.

    A parity test that cannot detect divergence is worse than none, because it
    licenses the belief that divergence is impossible.
    """

    ATTEMPT = "d-" + "0" * 32
    GENERATION = 1
    # Pinned clock and nonce. `build_context` stamps `created_at`, `expires_at`
    # and `reconciliation_nonce`; unpinned, the two contexts differ every run
    # for reasons that have nothing to do with parity.
    NOW = 1_780_000_000
    NONCE = "b" * 64

    def _verdict(self, root: Path, path: Path, *, staged: bool) -> tuple:
        """One comparable verdict: accepted context, or failure class + reason.

        Catches `Exception`, not `DispatchContextError`: a divergence that
        changes the exception TYPE is still a divergence, and narrowing here
        would let it escape as an error rather than a comparison failure.
        """

        try:
            context = dcb.build_context(
                root,
                path,
                attempt_id=self.ATTEMPT,
                generation=self.GENERATION,
                now=self.NOW,
                nonce=self.NONCE,
                staged=staged,
            )
        except Exception as exc:  # noqa: BLE001 - the type is part of the verdict
            return ("refuse", type(exc).__name__, str(exc))
        return ("accept", context)

    def _both_halves(self, root: Path, packet: Path) -> tuple[tuple, tuple]:
        """Validate staged, publish the same bytes, validate unstaged."""

        staged = self._verdict(root, packet, staged=True)
        published = root / dcb.canonical_mailbox_relative("inbox", TASK_ID)
        published.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(packet, published)
        # Identical bytes is the whole premise; assert it rather than assume it.
        self.assertEqual(published.read_bytes(), packet.read_bytes())
        launch = self._verdict(root, published, staged=False)
        return staged, launch

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_a_valid_packet_yields_the_identical_launch_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(Path(directory))
            staged, launch = self._both_halves(root, packet)
        # Assert acceptance explicitly. Equality alone would also be satisfied
        # by a mutation that broke both halves into the same refusal.
        self.assertEqual(staged[0], "accept", msg=staged)
        self.assertEqual(launch[0], "accept", msg=launch)
        self.assertEqual(staged, launch)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_a_packet_omitting_mode_yields_the_identical_launch_context(self) -> None:
        """The DISP-01 case, end to end across the seam that used to split."""

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(Path(directory), mode_row=None)
            staged, launch = self._both_halves(root, packet)
        self.assertEqual(staged[0], "accept", msg=staged)
        self.assertEqual(launch[0], "accept", msg=launch)
        self.assertEqual(staged, launch)
        self.assertEqual(
            staged[1]["authority"]["memory_context"]["mode"], "modeless"
        )

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_invalid_packets_fail_the_same_way_on_both_paths(self) -> None:
        """The symmetric half: refusals must agree in class AND reason.

        Equal acceptance alone would be satisfied by a builder that refused
        everything identically. Each shape below is refused by a DIFFERENT
        launch invariant, so this also samples more than one refusal site.
        """

        shapes = {
            "return_artifact outside write_scope": (
                {"write_scope": "[docs/unrelated/]"},
                "return_artifact is outside packet write_scope",
            ),
            "explicitly empty mode row": (
                {"mode_row": "mode:"},
                "missing required frontmatter field",
            ),
            "packet/contract mode disagreement": (
                {"mode_row": None, "contract_mode": "project"},
                "run/mode mismatch",
            ),
        }
        for label, (kwargs, reason) in shapes.items():
            with self.subTest(shape=label):
                with tempfile.TemporaryDirectory() as directory:
                    root, packet = build_fixture_repo(Path(directory), **kwargs)
                    staged, launch = self._both_halves(root, packet)
                self.assertEqual(staged[0], "refuse", msg=staged)
                self.assertEqual(launch[0], "refuse", msg=launch)
                self.assertEqual(staged, launch)
                self.assertIn(reason, staged[2])


class SendTaskDryRunRunsTheLaunchValidatorTests(unittest.TestCase):
    """End-to-end: `--dry-run` and the launch validator reach one verdict."""

    def _dry_run(
        self, root: Path, packet: Path
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["bash", str(SEND_TASK), str(packet), "--dry-run"],
            cwd=root,
            env={
                **os.environ,
                "VAULT_ROOT": str(root),
                "SQUAD_BASE_BRANCH": "v2",
                "SQUAD_DISPATCH_MODE": "board",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            timeout=180,
        )
        return skip_if_trusted_lane_executable_missing(completed)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_dry_run_passes_a_packet_the_launch_validator_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), with_contract=False
            )
            result = self._dry_run(root, packet)
            leftovers = sorted(
                p.name
                for p in packet.parent.glob("packet.*")
                if p != packet
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("launch preflight PASSED", output)
        # A dry-run writes nothing durable; its staging copies are its own.
        self.assertEqual(leftovers, [])

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_dry_run_fails_a_packet_the_launch_validator_refuses(self) -> None:
        """THE regression. Green-dry-run/dead-launch must not come back."""

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory),
                write_scope="[docs/unrelated/]",
                with_contract=False,
            )
            result = self._dry_run(root, packet)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("dry-run launch preflight refused", output)
        self.assertIn("return_artifact is outside packet write_scope", output)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_dry_run_admits_a_packet_that_omits_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), mode_row=None, with_contract=False
            )
            result = self._dry_run(root, packet)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("launch preflight PASSED", output)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_dry_run_measures_the_assembled_prompt_not_the_raw_packet(self) -> None:
        """Proof that the preflight runs on the ASSEMBLED bytes.

        The packet below is ~33 KB -- comfortably under the 40,960-byte
        trusted-launch ceiling on its own. It only breaches the ceiling once the
        contract rows and the injected toolkit block are added, which is exactly
        what launch assembles. A preflight fed the RAW packet, as first
        specified, would pass this green and the launch would then die on it.
        """

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), with_contract=False
            )
            packet.write_text(
                packet.read_text(encoding="utf-8")
                + "filler line to grow the packet body\n" * 900,
                encoding="utf-8",
            )
            raw_bytes = packet.stat().st_size
            result = self._dry_run(root, packet)
        output = result.stdout + result.stderr
        self.assertLess(raw_bytes, dcb.TRUSTED_LAUNCH_PROMPT_LIMIT)
        self.assertEqual(result.returncode, 1, msg=output)
        self.assertIn("too large for trusted launch prompt", output)

    def test_an_unmeasurable_preflight_is_reported_not_greenwashed(self) -> None:
        """The one skip path must announce itself as UNMEASURED.

        A root with no runtime map is not a dispatchable checkout, so the launch
        validator has no inputs to read. That is the ONLY case the dry-run
        declines to run it, and it says so loudly rather than printing a green
        it never measured. Reproduced the way it actually occurs: a bare scratch
        root with a direct-lane packet, which is what a fixture dispatch looks
        like.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / "packet.md"
            packet.write_text(
                "\n".join(
                    (
                        "---",
                        f"id: {TASK_ID}",
                        "run_id: RUN-DRYRUN-PARITY",
                        "to_model: gpt-codex",
                        "specialist: none",
                        "source_namespace: coding",
                        "mode: project",
                        "result_type: normal",
                        f"write_scope: [{RETURN_ARTIFACT}]",
                        f"return_artifact: {RETURN_ARTIFACT}",
                        "parallel_safe: false",
                        "direct_lane_work_allowed: true",
                        "mandatory_review: false",
                        "review_triggers: []",
                        "review_model: none",
                        "reviews: none",
                        "---",
                        "",
                        "Unmeasurable-preflight fixture.",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            self.assertFalse((root / "shared").exists())
            result = self._dry_run(root, packet)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("LAUNCH PREFLIGHT NOT RUN", output)
        self.assertIn("UNMEASURED", output)
        self.assertNotIn("launch preflight PASSED", output)


    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    @unittest.skipUnless(_lane_cli_available(), "lane CLI absent on this host")
    def test_a_validator_that_reaches_no_verdict_is_also_unmeasured(self) -> None:
        """Second UNMEASURED path: the validator ran but returned no verdict.

        A typed refusal (`...: error: <reason>`) is a verdict about the packet
        and must fail the dry-run. A bare non-zero exit is not -- it means the
        validator itself did not get far enough to judge anything. Treating that
        as a pass would recreate the original bug; treating it as a packet
        defect would blame the author for the environment.
        """

        with tempfile.TemporaryDirectory() as directory:
            root, packet = build_fixture_repo(
                Path(directory), with_contract=False
            )
            (root / "scripts" / "python" / "dispatch_context_builder.py").write_text(
                "import sys\nraise SystemExit('validator unavailable in fixture')\n",
                encoding="utf-8",
            )
            result = self._dry_run(root, packet)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, msg=output)
        self.assertIn("LAUNCH PREFLIGHT NOT RUN", output)
        self.assertIn("UNMEASURED", output)
        self.assertNotIn("launch preflight PASSED", output)


class DryRunSharesTheLaunchValidatorTests(unittest.TestCase):
    """Wiring pin: the dry-run must call the builder, not a private copy."""

    def test_dry_run_block_invokes_the_builder_check_subcommand(self) -> None:
        text = SEND_TASK.read_text(encoding="utf-8")
        dry_run_block = text.split("if $DRY_RUN; then", 1)[1].split("\nfi\n", 1)[0]
        self.assertIn('"$DISPATCH_CONTEXT_BUILDER" check', dry_run_block)
        self.assertIn("--staged", dry_run_block)
        # Assembled bytes, not the raw packet: the raw one has no contract row.
        self.assertIn("assemble_dispatch_packet", dry_run_block)
        self.assertIn('--task-file "$ACTUAL_TASK_FILE"', dry_run_block)

    def test_check_and_build_call_the_same_validator(self) -> None:
        """One validator, so the two paths cannot drift apart in the source."""

        source = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        main_body = source.split("def main(", 1)[1]
        build_branch = main_body.split('if command == "build":', 1)[1].split(
            'elif command == "check":', 1
        )
        self.assertIn("build_context(", build_branch[0])
        check_branch = build_branch[1].split('elif command ==', 1)[0]
        self.assertIn("build_context(", check_branch)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
