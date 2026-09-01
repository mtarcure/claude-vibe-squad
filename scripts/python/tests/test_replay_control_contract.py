#!/usr/bin/env python3
"""Executable spec for the finding evidence contract -- the replay/control pair.

Contract home: ``shared/protocol.md`` section "Finding evidence contract -- the
replay/control pair". Two things are proven here:

1. SHAPE (``check_replay_control_pair`` + the ``*ShapeTests``): a returned
   finding's replay/control pair is well-formed or it is not. This never runs
   Forge / LiteSVM / the command -- exactly as ``vibecoding_check.py`` checks
   that records exist without running them. Executing the two commands is the
   coordinator's MANUAL step (protocol.md, "The coordinator executes the pair").

2. NON-GATE (``NonGateIntegrationTests``): the pair lives in the returned
   *finding artifact*, while the ``<id>-response.md`` settlement envelope does
   not explicitly declare ``artifact_bundle_sha256``. These tests drive the
   REAL ``registry_reconciler.reconcile`` and prove that a ``complete`` task
   still settles ``complete`` for every incompleteness case (missing block,
   malformed block, replay exits nonzero, control exits zero) -- only the finding
   evidence is marked incomplete, never the task. A positive control shows the
   same unbacked digest DOES hold when explicitly declared in envelope
   frontmatter, while envelope prose and quoted commands do not declare it.

Why the shape moved off ``artifact_bundle_sha256``: that digest is
``hash_canonical(sorted({path,sha256,role}))`` over a manifest
(``vibecoding_check.py:363-378``), not a Git object, and the reconciler holds an
envelope whose explicit frontmatter field declares it without a reachable manifest
(``registry_reconciler.py`` ``declared_hash_issue``). So the pair binds to
reproducible bytes with a manifest path + a separately pinned Git commit (or
fixture) + a workdir, all in the finding artifact.

Runs under stdlib unittest (pytest is not installed on this host); auto-discovered
by ``bin/test`` via ``unittest discover -s scripts/python/tests -p 'test_*.py'``.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest import mock

# --- import bootstrap: the real reconciler + the proven board-receipt fixtures.
ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(PYTHON_SCRIPTS), str(TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reusing the board-receipt settlement harness (its _v2_entry / _write_v2_descriptor
# / _write_response / _patch_runtime staticmethods) keeps this file's reconciler
# invocation byte-identical to the proven DeclaredHashHoldTests path, and keeps the
# runtime-patch machinery in its one home rather than copied here (root CLAUDE.md
# Hard Rule 10).
import test_registry_reconciler_board_receipt as board_receipt  # noqa: E402

reconciler = board_receipt.reconciler
# NOTE: do NOT bind BoardReceiptSettlementTests to a module global -- unittest's
# loader collects any TestCase subclass reachable by a module-level name, which
# would re-run that whole suite inside this file. Reach it through the module.


EXPECT_PASS = "pass"
EXPECT_FAIL = "fail"

# Sentinel used by the fixtures to DELETE a key from a copied pair.
_DELETE = object()

# A manifest that can bind a bundle digest to bytes: the run manifest or the
# artifact list. Deliberately the SAME shape the reconciler recognises
# (registry_reconciler.py _MANIFEST_NAME_RE), so a block the coordinator can
# actually resolve is exactly the block the shape check accepts.
_MANIFEST_NAME_RE = re.compile(r"(manifest|artifact-list).*\.json$", re.IGNORECASE)
# A pinned Git commit is a full object name: sha1 (40) or sha256 (64) hex. An
# abbreviation is ambiguous and is rejected -- the coordinator must resolve one ref.
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_int(value: Any) -> bool:
    # bool is an int subclass; an exit code is never True/False.
    return isinstance(value, int) and not isinstance(value, bool)


def _repo_relative(value: Any) -> bool:
    """Same guard the reconciler applies to declared paths: not absolute, no `..`."""
    return _nonempty_str(value) and not value.startswith("/") and ".." not in value.split("/")


def _check_binding(binding: Any, violations: list[str]) -> None:
    if not isinstance(binding, dict):
        violations.append("binding must be a mapping")
        return

    manifest = binding.get("manifest")
    if not _nonempty_str(manifest):
        violations.append("binding.manifest must be a non-empty string")
    elif not _repo_relative(manifest):
        violations.append("binding.manifest must be a repo-relative path (not absolute, no '..')")
    elif not _MANIFEST_NAME_RE.search(manifest.split("/")[-1]):
        violations.append(
            "binding.manifest must be a reachable *manifest*.json / *artifact-list*.json the coordinator can verify"
        )

    # A separately pinned checkout identity: a full-hex Git commit, OR a fixture id.
    commit = binding.get("commit")
    fixture = binding.get("fixture")
    has_commit = commit is not None
    has_fixture = _nonempty_str(fixture)
    if not has_commit and not has_fixture:
        violations.append("binding must pin a checkout identity: a full-hex `commit` or an immutable `fixture`")
    if has_commit and not (isinstance(commit, str) and _COMMIT_RE.fullmatch(commit)):
        violations.append("binding.commit must be a full 40- or 64-hex Git commit SHA (no abbreviations)")

    if not _repo_relative(binding.get("workdir")):
        violations.append("binding.workdir must be a repo-relative directory for the commands (not absolute, no '..')")


def check_replay_control_pair(pair: Any) -> list[str]:
    """Return a list of contract violations. Empty list == well-formed.

    Never raises on malformed input: a bad shape is a violation to report, not an
    exception to propagate. This is the executable form of the shape rules in
    ``shared/protocol.md`` § "The finding-artifact shape".
    """
    if not isinstance(pair, dict):
        return ["pair must be a mapping"]

    violations: list[str] = []

    if not _nonempty_str(pair.get("finding")):
        violations.append("pair must carry a non-empty finding identity")

    _check_binding(pair.get("binding"), violations)

    for leg_name in ("replay", "control"):
        leg = pair.get(leg_name)
        if not isinstance(leg, dict):
            violations.append(f"{leg_name} must be a mapping")
            continue
        if not _nonempty_str(leg.get("command")):
            violations.append(f"{leg_name}.command must be a non-empty string")
        if not _nonempty_str(leg.get("observed")):
            violations.append(f"{leg_name}.observed must record a non-empty output excerpt")

    replay = pair.get("replay") if isinstance(pair.get("replay"), dict) else {}
    control = pair.get("control") if isinstance(pair.get("control"), dict) else {}

    if replay.get("expect") != EXPECT_PASS:
        violations.append('replay.expect must be "pass" (the replay must SUCCEED, exit 0)')
    if control.get("expect") != EXPECT_FAIL:
        violations.append('control.expect must be "fail" (the control must FAIL, exit != 0)')

    # The author's observed exit codes must match the claim: replay succeeded,
    # control failed. A block claiming a nonzero replay or a zero control is
    # itself incomplete evidence (see the coordinator verdict below).
    if not (_is_int(replay.get("observed_exit")) and replay.get("observed_exit") == 0):
        violations.append("replay.observed_exit must be the integer 0 (the author saw the replay succeed)")
    if not (_is_int(control.get("observed_exit")) and control.get("observed_exit") != 0):
        violations.append("control.observed_exit must be a nonzero integer (the author saw the control fail)")

    if not _nonempty_str(control.get("removed_condition")):
        violations.append("control.removed_condition must name the single enabling condition removed")

    replay_cmd = replay.get("command")
    control_cmd = control.get("command")
    if _nonempty_str(replay_cmd) and replay_cmd == control_cmd:
        violations.append("control.command is identical to replay.command -- not a control (false twin)")

    return violations


def is_well_formed(pair: Any) -> bool:
    return not check_replay_control_pair(pair)


def coordinator_verdict(replay_exit: int, control_exit: int) -> str:
    """The manual coordinator's verdict rule on OBSERVED exit codes (protocol.md
    step 6). Running the commands is a manual step, not something this module does."""
    if replay_exit != 0:
        return "replay-did-not-reproduce"
    if control_exit == 0:
        return "false-twin"
    return "holds"


# A reference well-formed pair (smart-contract flavour). Any namespace's finding
# has this same shape; only the commands differ (a curl, a unit test, ...). The
# binding names a reachable manifest, a full-hex Git commit and a workdir -- NOT
# an artifact_bundle_sha256 frontmatter declaration in the settlement envelope.
WELL_FORMED: dict[str, Any] = {
    "finding": "reentrancy in Vault.withdraw drains the pool",
    "binding": {
        "manifest": "_state/consults/TASK-run-manifest.json",
        "commit": "0" * 40,
        "workdir": "poc",
    },
    "replay": {
        "command": "forge test --match-test test_reentrancy_drains --fork-block-number 20443111",
        "expect": EXPECT_PASS,
        "observed_exit": 0,
        "observed": "[PASS] test_reentrancy_drains() (gas: 214553)",
    },
    "control": {
        "command": (
            "forge test --match-test test_reentrancy_drains "
            "--fork-block-number 20443111 --match-path test/Patched.t.sol"
        ),
        "expect": EXPECT_FAIL,
        "observed_exit": 1,
        "observed": "[FAIL] test_reentrancy_drains(): nonReentrant guard reverts",
        "removed_condition": "restored the nonReentrant modifier on withdraw()",
    },
}


def _mutate(**overrides: Any) -> dict[str, Any]:
    """Deep-copy WELL_FORMED and apply dotted overrides.

    ``control__expect=EXPECT_PASS`` sets ``pair["control"]["expect"]``. A value of
    ``_DELETE`` removes the leaf key. ``__`` is the path separator (kwargs cannot
    contain dots).
    """
    pair = deepcopy(WELL_FORMED)
    for dotted, value in overrides.items():
        keys = dotted.split("__")
        node: Any = pair
        for key in keys[:-1]:
            node = node[key]
        if value is _DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return pair


# The finding-artifact markdown a worker would return. Carries a 64-hex commit and
# the words "artifact bundle" ON PURPOSE: proving that bundle-flavoured finding
# content is not an explicit settlement-envelope declaration.
def _well_formed_artifact_markdown() -> str:
    return (
        "# Finding: reentrancy in Vault.withdraw\n\n"
        "The artifact bundle for this finding is enumerated in the manifest below.\n\n"
        "## replay-control\n"
        "- finding: reentrancy in Vault.withdraw drains the pool\n"
        "  binding:\n"
        "    manifest: _state/consults/TASK-run-manifest.json\n"
        f"    commit: {'a' * 40}\n"
        "    workdir: poc\n"
        "  replay:\n"
        "    command: forge test --match-test test_reentrancy_drains --fork-block-number 20443111\n"
        "    expect: pass\n"
        "    observed_exit: 0\n"
        "    observed: '[PASS] test_reentrancy_drains()'\n"
        "  control:\n"
        "    command: forge test --match-test test_reentrancy_drains --match-path test/Patched.t.sol\n"
        "    expect: fail\n"
        "    observed_exit: 1\n"
        "    observed: '[FAIL] nonReentrant guard reverts'\n"
        "    removed_condition: restored the nonReentrant modifier on withdraw()\n"
    )


class WellFormedShapeTests(unittest.TestCase):
    def test_reference_pair_is_accepted(self) -> None:
        self.assertEqual(check_replay_control_pair(WELL_FORMED), [])
        self.assertTrue(is_well_formed(WELL_FORMED))

    def test_a_fixture_bound_pair_is_accepted(self) -> None:
        # No Git object: an immutable fixture identity is an allowed checkout id.
        pair = _mutate(binding__commit=_DELETE)
        pair["binding"]["fixture"] = "corpus/2026-08-11-crash-0007"
        self.assertEqual(check_replay_control_pair(pair), [])

    def test_sha256_commit_is_accepted(self) -> None:
        self.assertEqual(check_replay_control_pair(_mutate(binding__commit="b" * 64)), [])


class MalformedShapeRejectedTests(unittest.TestCase):
    """Each case violates exactly one contract rule and must be rejected. One
    deletion / wrong-value mutation per required field (reviewer P1 test-coverage)."""

    def test_missing_control_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(control=_DELETE))
        self.assertTrue(any("control must be a mapping" in v for v in violations), violations)

    def test_control_declared_to_pass_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(control__expect=EXPECT_PASS))
        self.assertTrue(any('control.expect must be "fail"' in v for v in violations), violations)

    def test_replay_declared_to_fail_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(replay__expect=EXPECT_FAIL))
        self.assertTrue(any('replay.expect must be "pass"' in v for v in violations), violations)

    def test_identical_commands_rejected(self) -> None:
        violations = check_replay_control_pair(
            _mutate(control__command=WELL_FORMED["replay"]["command"])
        )
        self.assertTrue(any("false twin" in v for v in violations), violations)

    def test_empty_replay_command_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(replay__command="   "))
        self.assertTrue(
            any("replay.command must be a non-empty string" in v for v in violations), violations
        )

    def test_missing_removed_condition_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(control__removed_condition=_DELETE))
        self.assertTrue(any("removed_condition" in v for v in violations), violations)

    def test_missing_finding_identity_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(finding=_DELETE))
        self.assertTrue(any("finding identity" in v for v in violations), violations)

    def test_missing_replay_observed_excerpt_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(replay__observed=_DELETE))
        self.assertTrue(any("replay.observed" in v for v in violations), violations)

    def test_missing_control_observed_excerpt_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(control__observed=_DELETE))
        self.assertTrue(any("control.observed" in v for v in violations), violations)

    def test_replay_observed_exit_nonzero_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(replay__observed_exit=1))
        self.assertTrue(any("replay.observed_exit must be the integer 0" in v for v in violations), violations)

    def test_control_observed_exit_zero_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(control__observed_exit=0))
        self.assertTrue(any("control.observed_exit must be a nonzero integer" in v for v in violations), violations)

    def test_bool_observed_exit_rejected(self) -> None:
        # True == 1 in Python; an exit code that is a bool is not an exit code.
        violations = check_replay_control_pair(_mutate(replay__observed_exit=False))
        self.assertTrue(any("replay.observed_exit must be the integer 0" in v for v in violations), violations)

    def test_missing_binding_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding=_DELETE))
        self.assertTrue(any("binding must be a mapping" in v for v in violations), violations)

    def test_missing_manifest_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__manifest=_DELETE))
        self.assertTrue(any("binding.manifest must be a non-empty string" in v for v in violations), violations)

    def test_non_manifest_named_path_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__manifest="_state/consults/result.md"))
        self.assertTrue(any("*manifest*.json" in v for v in violations), violations)

    def test_absolute_manifest_path_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__manifest="/etc/run-manifest.json"))
        self.assertTrue(any("repo-relative" in v for v in violations), violations)

    def test_no_checkout_identity_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__commit=_DELETE))
        self.assertTrue(any("checkout identity" in v for v in violations), violations)

    def test_abbreviated_commit_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__commit="0abc123"))
        self.assertTrue(any("full 40- or 64-hex Git commit" in v for v in violations), violations)

    def test_missing_workdir_rejected(self) -> None:
        violations = check_replay_control_pair(_mutate(binding__workdir=_DELETE))
        self.assertTrue(any("binding.workdir" in v for v in violations), violations)

    def test_non_mapping_rejected(self) -> None:
        self.assertEqual(check_replay_control_pair("not a pair"), ["pair must be a mapping"])


class CoordinatorVerdictTests(unittest.TestCase):
    def test_replay_pass_control_fail_holds(self) -> None:
        self.assertEqual(coordinator_verdict(0, 1), "holds")

    def test_replay_fail_does_not_reproduce(self) -> None:
        self.assertEqual(coordinator_verdict(1, 1), "replay-did-not-reproduce")
        self.assertEqual(coordinator_verdict(1, 0), "replay-did-not-reproduce")

    def test_replay_pass_control_pass_is_false_twin(self) -> None:
        self.assertEqual(coordinator_verdict(0, 0), "false-twin")


class ContractHasTeethTests(unittest.TestCase):
    """A vacuous validator would accept everything. Prove it does not: every
    single-rule violation is rejected, and a neutered validator visibly is not."""

    _MUTATIONS = {
        "missing control": {"control": _DELETE},
        "control expects pass": {"control__expect": EXPECT_PASS},
        "replay expects fail": {"replay__expect": EXPECT_FAIL},
        "identical commands": {"control__command": WELL_FORMED["replay"]["command"]},
        "empty replay command": {"replay__command": ""},
        "missing removed_condition": {"control__removed_condition": _DELETE},
        "missing finding": {"finding": _DELETE},
        "missing replay observed": {"replay__observed": _DELETE},
        "replay observed_exit nonzero": {"replay__observed_exit": 2},
        "control observed_exit zero": {"control__observed_exit": 0},
        "missing binding": {"binding": _DELETE},
        "non-manifest path": {"binding__manifest": "_state/consults/result.md"},
        "no checkout identity": {"binding__commit": _DELETE},
        "abbreviated commit": {"binding__commit": "0abc123"},
        "missing workdir": {"binding__workdir": _DELETE},
    }

    def test_every_single_rule_violation_is_rejected(self) -> None:
        for label, override in self._MUTATIONS.items():
            with self.subTest(violation=label):
                self.assertNotEqual(
                    check_replay_control_pair(_mutate(**override)),
                    [],
                    f"validator vacuously accepted a malformed pair ({label})",
                )

    def test_neutered_validator_is_visibly_vacuous(self) -> None:
        # The teeth come from the real logic: swap it for `return []` and a
        # malformed pair is (wrongly) accepted. This is the mutation control the
        # packet requires -- neuter the validator and the suite goes RED.
        with mock.patch(f"{__name__}.check_replay_control_pair", lambda pair: []):
            accepted = check_replay_control_pair(_mutate(control=_DELETE))
        self.assertEqual(accepted, [], "meta-control: the neutered validator should accept anything")


class NonGateIntegrationTests(unittest.TestCase):
    """Drive the REAL reconciler. The acceptance test: a `complete` task settles
    `complete` for every replay/control incompleteness case, because the pair
    lives in the finding artifact and the settlement envelope carries no
    ``artifact_bundle_sha256`` declaration. Positive control below proves the
    hold is reachable, so these greens are not a harness that never holds.
    """

    DIGEST = "d8a30627773a8973ac2bffe88802420675768369ab0f1494ac7d6d282fb54d57"

    def _fixture(self, directory: str, task_id: str, attempt_id: str):
        root = Path(directory)
        state = root / "_state"
        registry_path = state / "active-tasks.json"
        state.mkdir()
        registry_path.write_text(
            json.dumps({task_id: board_receipt.BoardReceiptSettlementTests._v2_entry(task_id, attempt_id)}) + "\n",
            encoding="utf-8",
        )
        board_receipt.BoardReceiptSettlementTests._write_v2_descriptor(state, task_id, attempt_id)
        # The finding artifact == the task's return_artifact (_v2_entry pins it).
        artifact = state / "consults" / "result.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("the deliverable\n", encoding="utf-8")
        response = root / "departments/coding/outbox" / f"{task_id}-response.md"
        board_receipt.BoardReceiptSettlementTests._write_response(response, task_id, "complete", attempt_id=attempt_id)
        return root, state, registry_path, response, artifact

    def _reconcile(self, root, state, registry_path, task_id):
        with board_receipt.BoardReceiptSettlementTests._patch_runtime(root, state, registry_path):
            reconciler.reconcile(task_id, dry_run=False)
        return json.loads(registry_path.read_text(encoding="utf-8"))[task_id]

    def _settle_with_artifact(self, task_id: str, attempt_id: str, artifact_text: str):
        """Envelope has no explicit bundle declaration; the finding artifact
        carries `artifact_text`. Returns the settled registry entry."""
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, _response, artifact = self._fixture(
                directory, task_id, attempt_id
            )
            artifact.write_text(artifact_text, encoding="utf-8")
            return self._reconcile(root, state, registry_path, task_id)

    # --- positive control: the hold IS reachable from this harness -------------
    def test_positive_control_explicit_frontmatter_bundle_hash_still_holds(self) -> None:
        """An explicit frontmatter declaration with no reachable manifest makes
        the real reconciler hold `in-flight`; the negative checks are non-vacuous."""
        task_id = "TASK-2026-08-29-9701-envelope-hash-holds"
        attempt_id = "d-" + "1" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response, _artifact = self._fixture(
                directory, task_id, attempt_id
            )
            text = response.read_text(encoding="utf-8").replace(
                "return_artifact: _state/consults/result.md\n",
                "return_artifact: _state/consults/result.md\n"
                f"artifact_bundle_sha256: {self.DIGEST}\n",
                1,
            )
            response.write_text(text, encoding="utf-8")
            entry = self._reconcile(root, state, registry_path, task_id)
        self.assertEqual(entry["status"], "in-flight")
        self.assertIn("resolves to nothing reachable", entry["declared_hash_issue"])

    def test_bundle_hash_in_quoted_envelope_command_settles_complete(self) -> None:
        task_id = "TASK-2026-08-29-9707-envelope-command-settles"
        attempt_id = "d-" + "7" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response, _artifact = self._fixture(
                directory, task_id, attempt_id
            )
            response.write_text(
                response.read_text(encoding="utf-8")
                + f"\nQuoted command: `checker --label 'artifact bundle {self.DIGEST}'`.\n",
                encoding="utf-8",
            )
            entry = self._reconcile(root, state, registry_path, task_id)
        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)

    # --- the fix: same content in the finding artifact settles complete --------
    def test_pair_in_finding_artifact_settles_complete(self) -> None:
        """The well-formed pair -- carrying a 64-hex commit and the words
        'artifact bundle' -- in the FINDING ARTIFACT does not hold the task,
        because the reconciler reads only the envelope."""
        entry = self._settle_with_artifact(
            "TASK-2026-08-29-9702-artifact-pair-settles",
            "d-" + "2" * 32,
            _well_formed_artifact_markdown(),
        )
        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)

    # --- the four incompleteness cases: task COMPLETE, evidence incomplete -----
    def test_missing_block_task_complete_evidence_incomplete(self) -> None:
        artifact_text = "# Finding\n\nA finding narrative with no replay-control block.\n"
        entry = self._settle_with_artifact(
            "TASK-2026-08-29-9703-missing-block", "d-" + "3" * 32, artifact_text
        )
        self.assertEqual(entry["status"], "complete")           # task COMPLETE
        self.assertNotIn("declared_hash_issue", entry)
        self.assertNotIn("## replay-control", artifact_text)    # evidence incomplete: nothing to run

    def test_malformed_block_task_complete_evidence_incomplete(self) -> None:
        malformed_markdown = _well_formed_artifact_markdown().replace(
            "    expect: fail\n", "    expect: pass\n", 1  # control declared to pass: false twin
        )
        entry = self._settle_with_artifact(
            "TASK-2026-08-29-9704-malformed-block", "d-" + "4" * 32, malformed_markdown
        )
        self.assertEqual(entry["status"], "complete")           # task COMPLETE
        self.assertNotIn("declared_hash_issue", entry)
        # evidence incomplete: the shape check rejects a control declared to pass.
        self.assertNotEqual(check_replay_control_pair(_mutate(control__expect=EXPECT_PASS)), [])

    def test_replay_nonzero_task_complete_evidence_incomplete(self) -> None:
        entry = self._settle_with_artifact(
            "TASK-2026-08-29-9705-replay-nonzero",
            "d-" + "5" * 32,
            _well_formed_artifact_markdown(),
        )
        self.assertEqual(entry["status"], "complete")           # task COMPLETE
        self.assertNotIn("declared_hash_issue", entry)
        # evidence incomplete: a replay that exits nonzero does not reproduce, and
        # a block claiming a nonzero replay observed_exit also fails shape.
        self.assertEqual(coordinator_verdict(1, 1), "replay-did-not-reproduce")
        self.assertNotEqual(check_replay_control_pair(_mutate(replay__observed_exit=1)), [])

    def test_control_zero_task_complete_evidence_incomplete(self) -> None:
        entry = self._settle_with_artifact(
            "TASK-2026-08-29-9706-control-zero",
            "d-" + "6" * 32,
            _well_formed_artifact_markdown(),
        )
        self.assertEqual(entry["status"], "complete")           # task COMPLETE
        self.assertNotIn("declared_hash_issue", entry)
        # evidence incomplete: a control that exits zero is a false twin, and a
        # block claiming a zero control observed_exit also fails shape.
        self.assertEqual(coordinator_verdict(0, 0), "false-twin")
        self.assertNotEqual(check_replay_control_pair(_mutate(control__observed_exit=0)), [])


if __name__ == "__main__":
    unittest.main()
