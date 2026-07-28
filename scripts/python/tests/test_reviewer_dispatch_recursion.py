#!/usr/bin/env python3
"""The high-safety gate must not demand a review OF a review.

Two linked defects made cross-family review packets undispatchable:

* ``bin/send-task.sh`` dies when a ``safety_level: high`` specialist carries
  ``mandatory_review: false``.  Every verdict-producing role was high-safety, so
  dispatching a REVIEW required the review itself to be reviewed -- an infinite
  regress.  ``registry_reconciler._is_read_only_review_task`` already encoded
  the correct exemption (verdict role + explicitly empty write scope); the
  dispatcher simply never honoured it.
* ``REVIEW_VERDICT_SPECIALISTS`` held only ``code-reviewer`` and
  ``security-analyst``, both mapped to the gpt-codex lane.  A codex-authored
  task needs an anti-affinity (non-openai) reviewer, so it had NO eligible
  read-only verdict role at all.  ``skeptic`` -- the canonical claude-lane
  judgment role -- closes that hole.

Safety level and verdict-role membership are INDEPENDENT axes, and this file
must keep them apart.  The operator-ratified safety audit (514ff18) then
downgraded ``skeptic`` high -> medium -- attacking the same regress from the
other side, since a medium role never meets the gate at all.  ``skeptic``
remains a verdict role and remains exempt in the reconciler, because
``_is_read_only_review_task`` keys on the ROLE SET and an empty write scope,
never on ``safety_level``.  So the gate assertions below iterate
``HIGH_SAFETY_VERDICT_ROLES`` (the roles that actually reach the branch) while
the role-set assertions iterate the full ``REVIEW_VERDICT_SPECIALISTS``.

The dispatch tests drive the real ``bin/send-task.sh`` with ``--dry-run``:
admission and the high-safety gate both run long before any mailbox, registry,
or model-CLI side effect, so these assert on behaviour without touching state.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]  # scripts/python/tests -> repo root
SEND_TASK = REPO / "bin" / "send-task.sh"
RUNTIME_MAP = REPO / "shared" / "specialist-runtime-map.tsv"

sys.path.insert(0, str(REPO / "scripts" / "python"))

from registry_reconciler import (  # noqa: E402
    LANE_AUTHOR_FAMILY,
    REVIEW_VERDICT_SPECIALISTS,
    _is_read_only_review_task,
)

HIGH_SAFETY_GATE = "requires mandatory_review:true"
# `--dry-run` deliberately exits 2 once a packet clears every gate, so a caller
# chaining `--dry-run && <real dispatch>` can never mistake a rehearsal for a
# dispatch. `die` exits 1. Both codes are load-bearing assertions here.
DRY_RUN_ADMITTED = 2
DIE = 1

# specialist -> (mapped primary lane, a source_namespace send-task accepts for
# it).  Using each role's MAPPED lane keeps the packets free of a
# model_override_reason, so the only gate under test is the high-safety one.
VERDICT_ROLES = {
    "code-reviewer": ("gpt-codex", "coding"),
    "security-analyst": ("gpt-codex", "security"),
    # skeptic lives in the `shared` namespace, which has no mailbox of its own;
    # send-task lets a shared-mapped specialist route through any real mailbox.
    "skeptic": ("claude", "security"),
}
# Both the exemption and the `die` live INSIDE send-task.sh's
# `MAP_SAFETY == high` branch, so only the high-safety verdict roles reach
# either one.  A medium verdict role is admitted by the ordinary path without
# the branch ever running -- it can neither be gated nor exempted.  Gate
# assertions therefore iterate this subset; `test_the_verdict_partition_matches
# _the_runtime_map` is what fails loudly if a safety_level edit moves a role
# across the line again.
HIGH_SAFETY_VERDICT_ROLES = frozenset({"code-reviewer", "security-analyst"})
MEDIUM_SAFETY_VERDICT_ROLES = frozenset({"skeptic"})
# A high-safety role that is NOT a verdict producer: the control for every
# "still gated" assertion.
HIGH_SAFETY_IMPLEMENTER = ("content-verifier", "claude", "content")


def gated_verdict_roles() -> list[tuple[str, tuple[str, str]]]:
    """The verdict roles whose dispatch actually exercises the high-safety gate."""
    return [(name, VERDICT_ROLES[name]) for name in sorted(HIGH_SAFETY_VERDICT_ROLES)]


def map_row(specialist: str) -> list[str]:
    for line in RUNTIME_MAP.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if fields and fields[0] == specialist:
            return fields
    raise AssertionError(f"{specialist} is missing from {RUNTIME_MAP}")


def packet(
    *,
    task_id: str,
    specialist: str,
    to_model: str,
    source_namespace: str,
    write_scope: str,
) -> str:
    fields = {
        "id": task_id,
        "to_model": to_model,
        "specialist": specialist,
        "source_namespace": source_namespace,
        "mode": "project",
        "run_id": "PROJ-BOARD-HARDENING-2026-07-26",
        "result_type": "normal",
        "write_scope": write_scope,
        "read_scope": "[]",
        "parallel_safe": "true",
        "direct_lane_work_allowed": "false",
        "mandatory_review": "false",
        "review_model": "none",
        "return_artifact": "_state/reviewer-recursion/out.md",
        "success_criteria": "[]",
        "out_of_scope": "[]",
    }
    rows = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{rows}\n---\n\nRead-only review probe.\n"


class VerdictRoleSetTests(unittest.TestCase):
    """The role set itself: complete, cross-family, and narrowly applied."""

    def test_skeptic_is_a_verdict_role(self) -> None:
        self.assertIn("skeptic", REVIEW_VERDICT_SPECIALISTS)

    def test_skeptic_maps_to_a_medium_safety_claude_judgment_role(self) -> None:
        # The set is only sound if the runtime map really routes skeptic as a
        # claude-lane judgment role -- otherwise it names a specialist that
        # could not run a review dispatch at all.
        #
        # safety_level is deliberately NOT part of that soundness argument.
        # `_is_read_only_review_task` grants the reconciler's read-only-settle
        # exemption on verdict-set MEMBERSHIP plus an empty write scope; it
        # never reads safety_level.  So the operator-ratified medium (514ff18)
        # leaves skeptic a fully valid cross-family reviewer -- it simply
        # dispatches through the ordinary path instead of the exemption.
        fields = map_row("skeptic")
        self.assertEqual(fields[2], "judgment", msg="capability_class")
        self.assertEqual(fields[3], "medium", msg="safety_level")
        self.assertEqual(fields[6], "claude", msg="primary_lane")

    def test_the_verdict_partition_matches_the_runtime_map(self) -> None:
        """The gate fixtures must track the TSV, not a snapshot of it.

        A safety_level edit landing without a matching fixture edit is exactly
        what stranded three assertions here before: they iterated every verdict
        role and asserted gate behaviour a downgraded role can no longer show.
        Fail on the partition itself so the next such edit names its cause.
        """
        self.assertEqual(
            HIGH_SAFETY_VERDICT_ROLES | MEDIUM_SAFETY_VERDICT_ROLES,
            set(REVIEW_VERDICT_SPECIALISTS),
            msg="every verdict role must sit in exactly one safety partition",
        )
        for specialist in sorted(REVIEW_VERDICT_SPECIALISTS):
            with self.subTest(specialist=specialist):
                expected = (
                    "high" if specialist in HIGH_SAFETY_VERDICT_ROLES else "medium"
                )
                self.assertEqual(map_row(specialist)[3], expected, msg="safety_level")

    def test_the_set_spans_both_review_families(self) -> None:
        """Anti-affinity needs a verdict role on EITHER side of the hop.

        With only codex-mapped roles a codex-authored task had no read-only
        reviewer it could legally route to.
        """
        families = set()
        for specialist in REVIEW_VERDICT_SPECIALISTS:
            lane = map_row(specialist)[6]
            lane = "gpt-codex" if lane == "codex" else lane
            families.add(LANE_AUTHOR_FAMILY[lane])
        self.assertGreaterEqual(
            len(families), 2, msg=f"verdict roles are single-family: {families}"
        )
        self.assertIn("anthropic", families)
        self.assertIn("openai", families)

    def test_read_only_classification_still_requires_an_empty_scope(self) -> None:
        for specialist in sorted(REVIEW_VERDICT_SPECIALISTS):
            with self.subTest(specialist=specialist):
                self.assertTrue(
                    _is_read_only_review_task(
                        {"specialist": specialist, "write_scope": []}
                    )
                )
                self.assertFalse(
                    _is_read_only_review_task(
                        {"specialist": specialist, "write_scope": ["bin/send-task.sh"]}
                    )
                )
        self.assertFalse(
            _is_read_only_review_task(
                {"specialist": HIGH_SAFETY_IMPLEMENTER[0], "write_scope": []}
            )
        )


class HighSafetyGateExemptionTests(unittest.TestCase):
    """``bin/send-task.sh`` honours the reconciler's read-only exemption."""

    def dispatch(
        self,
        *,
        specialist: str,
        to_model: str,
        source_namespace: str,
        write_scope: str,
        vault: Path | None = None,
    ) -> subprocess.CompletedProcess:
        directory = Path(tempfile.mkdtemp(prefix="reviewer-recursion-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        task_file = directory / "task.md"
        task_file.write_text(
            packet(
                task_id="TASK-2026-07-26-0100-revrec",
                specialist=specialist,
                to_model=to_model,
                source_namespace=source_namespace,
                write_scope=write_scope,
            ),
            encoding="utf-8",
        )
        return subprocess.run(
            [str(SEND_TASK), str(task_file), "--dry-run"],
            env={**os.environ, "VAULT_ROOT": str(vault or REPO), "SKIP_NUDGE": "1"},
            capture_output=True,
            text=True,
            timeout=180,
        )

    def output(self, completed: subprocess.CompletedProcess) -> str:
        return completed.stdout + completed.stderr

    # ---- (a) a read-only verdict packet dispatches without the die ---------
    def test_read_only_verdict_roles_dispatch_without_mandatory_review(self) -> None:
        for specialist, (lane, namespace) in gated_verdict_roles():
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[]",
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(HIGH_SAFETY_GATE, output)
                self.assertIn("read-only review packet", output)
                self.assertIn("[DRY RUN] write_scope=[]", output)

    # ---- (a') a MEDIUM verdict role never meets the gate at all ------------
    def test_medium_safety_verdict_roles_dispatch_without_mandatory_review(self) -> None:
        """Read-only review dispatch stays open for a downgraded verdict role.

        The exemption is not what admits these -- the whole gate is nested
        under ``safety_level: high``, so a medium role is admitted by the
        ordinary path and reaches NEITHER branch.  Asserting the absence of
        both messages is what distinguishes "admitted below the gate" from
        "admitted by the exemption"; asserting only the exit code would pass
        either way and would not notice a re-upgrade.
        """
        for specialist in sorted(MEDIUM_SAFETY_VERDICT_ROLES):
            lane, namespace = VERDICT_ROLES[specialist]
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[]",
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(HIGH_SAFETY_GATE, output)
                self.assertNotIn("read-only review packet", output)
                self.assertIn("[DRY RUN] write_scope=[]", output)

    # ---- (b) a high-safety IMPLEMENTER is untouched ------------------------
    def test_high_safety_implementer_still_requires_mandatory_review(self) -> None:
        specialist, lane, namespace = HIGH_SAFETY_IMPLEMENTER
        for label, write_scope in (
            ("with-scope", "[_state/reviewer-recursion/]"),
            # The exemption keys on the ROLE too: an empty scope alone must not
            # buy a non-verdict specialist a pass.
            ("empty-scope", "[]"),
        ):
            with self.subTest(label=label):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope=write_scope,
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DIE, msg=output)
                self.assertIn(
                    f"high-safety specialist '{specialist}' {HIGH_SAFETY_GATE}", output
                )

    # ---- (c) a verdict role that WRITES is not exempt ----------------------
    def test_verdict_role_with_a_write_scope_is_still_gated(self) -> None:
        for specialist, (lane, namespace) in gated_verdict_roles():
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[_state/reviewer-recursion/]",
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DIE, msg=output)
                self.assertIn(
                    f"high-safety specialist '{specialist}' {HIGH_SAFETY_GATE}", output
                )
                self.assertNotIn("read-only review packet", output)

    # ---- the exemption fails CLOSED ---------------------------------------
    def test_unreadable_verdict_set_denies_the_exemption(self) -> None:
        """No reconciler module -> no exemption, not a silently open gate.

        The dispatcher reads the role set out of ``registry_reconciler`` so the
        two can never drift.  That import is also the failure mode worth
        pinning: if it cannot be resolved the gate must keep firing.
        """
        root = Path(tempfile.mkdtemp(prefix="reviewer-recursion-vault-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        vault = root / "vault"
        vault.mkdir()
        for name in ("shared", "model-lanes", "bin", "plugins"):
            source = REPO / name
            if source.exists():
                (vault / name).symlink_to(source)
        # `departments` is COPIED, not linked: send-task.sh locates a specialist
        # with `find "$VAULT_ROOT/departments" ... -type f`, which neither
        # descends a symlinked start point nor matches a symlinked leaf. Copying
        # also keeps the run's `mkdir -p` on the mailbox off the real repo.
        shutil.copytree(REPO / "departments", vault / "departments", symlinks=True)
        (vault / "_state").mkdir()
        # Link each scripts/python entry individually so exactly one module can
        # be absent while every other validator send-task.sh calls still works.
        (vault / "scripts").mkdir()
        for entry in (REPO / "scripts").iterdir():
            if entry.name != "python":
                (vault / "scripts" / entry.name).symlink_to(entry)
        (vault / "scripts" / "python").mkdir()
        for entry in (REPO / "scripts" / "python").iterdir():
            if entry.name != "registry_reconciler.py":
                (vault / "scripts" / "python" / entry.name).symlink_to(entry)

        completed = self.dispatch(
            specialist="code-reviewer",
            to_model="gpt-codex",
            source_namespace="coding",
            write_scope="[]",
            vault=vault,
        )
        output = self.output(completed)
        self.assertEqual(completed.returncode, DIE, msg=output)
        self.assertIn(
            f"high-safety specialist 'code-reviewer' {HIGH_SAFETY_GATE}", output
        )


if __name__ == "__main__":
    unittest.main()
