#!/usr/bin/env python3
"""Review is packet-triggered and must not demand a review OF a review.

``safety_level`` is a role quality floor, while ``review_triggers`` describes
the change.  These tests keep those axes independent: high-safety roles with an
empty trigger list are admitted, a declared trigger requires an anti-affinity
reviewer, and read-only verdict roles retain their narrow reconciler settlement
exemption.  The verdict set still spans both author families so a genuine
cross-family review has an eligible landing role.

The dispatch tests drive the real ``bin/send-task.sh`` with ``--dry-run``:
trigger validation and anti-affinity run long before any mailbox, registry, or
model-CLI side effect, so these assert on behaviour without touching state.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_host_independence import (  # noqa: E402
    skip_if_trusted_lane_executable_missing,
)
from dispatch_checkout import normal_checkout_root  # noqa: E402

# send-task.sh refuses to dispatch from a linked worktree, and that refusal runs
# before every guard this suite is about -- so without this the result would
# depend on where the repo was checked out, not on the behaviour under test.
REPO = normal_checkout_root(Path(__file__).resolve().parents[3])
SEND_TASK = REPO / "bin" / "send-task.sh"
RUNTIME_MAP = REPO / "shared" / "specialist-runtime-map.tsv"

sys.path.insert(0, str(REPO / "scripts" / "python"))

from registry_reconciler import (  # noqa: E402
    LANE_AUTHOR_FAMILY,
    REVIEW_VERDICT_SPECIALISTS,
    _is_read_only_review_task,
)

REMOVED_SAFETY_GATE = "requires mandatory_review:true"
# `--dry-run` deliberately exits 2 once a packet clears every gate, so a caller
# chaining `--dry-run && <real dispatch>` can never mistake a rehearsal for a
# dispatch. `die` exits 1. Both codes are load-bearing assertions here.
DRY_RUN_ADMITTED = 2
DIE = 1

# specialist -> (mapped primary lane, a source_namespace send-task accepts for
# it).  Using each role's MAPPED lane keeps the packets free of a
# model_override_reason, so trigger handling is isolated from routing checks.
VERDICT_ROLES = {
    "code-reviewer": ("gpt-codex", "coding"),
    "security-analyst": ("gpt-codex", "security"),
    # skeptic lives in the `shared` namespace, which has no mailbox of its own;
    # send-task lets a shared-mapped specialist route through any real mailbox.
    "skeptic": ("claude", "shared"),
}
# Keep both high- and medium-safety verdict roles in the fixture. Their dispatch
# behavior must now be identical when the packet carries no trigger.
HIGH_SAFETY_VERDICT_ROLES = frozenset({"code-reviewer", "security-analyst"})
MEDIUM_SAFETY_VERDICT_ROLES = frozenset({"skeptic"})
# A high-safety role that is NOT a verdict producer: the control proving role
# safety alone no longer creates review work.
HIGH_SAFETY_IMPLEMENTER = ("content-verifier", "gemini", "content")
REVIEW_TARGET = "TASK-2026-07-26-0099-held"


def gated_verdict_roles() -> list[tuple[str, tuple[str, str]]]:
    """The formerly gated verdict roles used as safety-level controls."""
    return [(name, VERDICT_ROLES[name]) for name in sorted(HIGH_SAFETY_VERDICT_ROLES)]


def map_row(specialist: str) -> list[str]:
    for line in RUNTIME_MAP.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if fields and fields[0] == specialist:
            return fields
    raise AssertionError(f"{specialist} is missing from {RUNTIME_MAP}")


def evidence_outputs_for(write_scope: str) -> str:
    """Declare every non-artifact write_scope path as a promoted output.

    ``bin/send-task.sh`` refuses a packet whose write_scope names a git-ignored
    path that is neither the ``return_artifact`` nor listed in
    ``evidence_outputs`` -- such a path has no promotion route, so the work
    would be destroyed at worktree cleanup. These fixtures write under
    ``_state/`` (git-ignored), so the declaration is what makes them dispatchable
    at all. It is incidental to the trigger behaviour under test; without it the
    packet dies before any review-inference code runs.
    """
    return write_scope


def packet(
    *,
    task_id: str,
    specialist: str,
    to_model: str,
    source_namespace: str,
    write_scope: str,
    review_triggers: str = "[]",
    mandatory_review: str = "false",
    review_model: str = "none",
    reviews: str = "none",
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
        "evidence_outputs": evidence_outputs_for(write_scope),
        "read_scope": "[]",
        "parallel_safe": "true",
        "direct_lane_work_allowed": "false",
        "mandatory_review": mandatory_review,
        "review_triggers": review_triggers,
        "review_model": review_model,
        "reviews": reviews,
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
        """The safety controls must track the TSV rather than a stale snapshot."""
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


class TriggerReviewGateTests(unittest.TestCase):
    """``bin/send-task.sh`` derives review from the packet, not role safety."""

    def dispatch(
        self,
        *,
        specialist: str,
        to_model: str,
        source_namespace: str,
        write_scope: str,
        review_triggers: str = "[]",
        mandatory_review: str = "false",
        review_model: str = "none",
        reviews: str = "none",
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
                review_triggers=review_triggers,
                mandatory_review=mandatory_review,
                review_model=review_model,
                reviews=reviews,
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "VAULT_ROOT": str(vault or REPO), "SKIP_NUDGE": "1"}
        if vault is not None:
            # A fixture vault is a plain tempdir, not a git checkout, so
            # send-task.sh cannot derive a branch and now refuses to guess
            # one; supply it explicitly. `REPO` (the `or` fallback above) is
            # the real checkout and derives its actual branch unaided.
            env["SQUAD_BASE_BRANCH"] = "v2"
        completed = subprocess.run(
            [str(SEND_TASK), str(task_file), "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return skip_if_trusted_lane_executable_missing(completed)

    def output(self, completed: subprocess.CompletedProcess) -> str:
        return completed.stdout + completed.stderr

    # ---- no-trigger controls across role safety levels ---------------------
    def test_read_only_verdict_roles_dispatch_without_mandatory_review(self) -> None:
        for specialist, (lane, namespace) in gated_verdict_roles():
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[]",
                    reviews=REVIEW_TARGET,
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(REMOVED_SAFETY_GATE, output)
                self.assertNotIn("read-only review packet", output)
                self.assertIn("[DRY RUN] write_scope=[]", output)

    def test_medium_safety_verdict_roles_dispatch_without_mandatory_review(self) -> None:
        """Medium roles follow the same empty-trigger contract as high roles."""
        for specialist in sorted(MEDIUM_SAFETY_VERDICT_ROLES):
            lane, namespace = VERDICT_ROLES[specialist]
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[]",
                    reviews=REVIEW_TARGET,
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(REMOVED_SAFETY_GATE, output)
                self.assertNotIn("read-only review packet", output)
                self.assertIn("[DRY RUN] write_scope=[]", output)

    # ---- a high-safety implementer is still ordinary without a trigger -----
    def test_high_safety_implementer_without_a_trigger_is_trivial(self) -> None:
        specialist, lane, namespace = HIGH_SAFETY_IMPLEMENTER
        for label, write_scope in (
            ("with-scope", "[_state/reviewer-recursion/out.md]"),
            # Empty scope does not itself create a review trigger.
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
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(REMOVED_SAFETY_GATE, output)
                self.assertIn("[DRY RUN]", output)

    def test_verdict_role_with_a_write_scope_does_not_infer_review(self) -> None:
        for specialist, (lane, namespace) in gated_verdict_roles():
            with self.subTest(specialist=specialist):
                completed = self.dispatch(
                    specialist=specialist,
                    to_model=lane,
                    source_namespace=namespace,
                    write_scope="[_state/reviewer-recursion/out.md]",
                )
                output = self.output(completed)
                self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
                self.assertNotIn(REMOVED_SAFETY_GATE, output)
                self.assertNotIn("read-only review packet", output)

    def test_adversarial_trigger_fires_and_keeps_cross_family_review(self) -> None:
        specialist, lane, namespace = HIGH_SAFETY_IMPLEMENTER
        completed = self.dispatch(
            specialist=specialist,
            to_model=lane,
            source_namespace=namespace,
            write_scope="[]",
            review_triggers="[adversarial_claim]",
            mandatory_review="true",
            review_model="gpt-codex",
        )
        output = self.output(completed)
        self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
        self.assertIn("cross-family review required by", output)
        self.assertIn("adversarial_claim", output)

    def test_adversarial_trigger_rejects_same_family_reviewer(self) -> None:
        specialist, lane, namespace = HIGH_SAFETY_IMPLEMENTER
        completed = self.dispatch(
            specialist=specialist,
            to_model=lane,
            source_namespace=namespace,
            write_scope="[]",
            review_triggers="[adversarial_claim]",
            mandatory_review="true",
            review_model=lane,
        )
        output = self.output(completed)
        self.assertEqual(completed.returncode, DIE, msg=output)
        self.assertIn("review_model to differ from to_model", output)

    def test_unreadable_verdict_set_does_not_recreate_a_safety_default(self) -> None:
        """A missing reconciler module cannot turn role safety into review policy.

        Dispatch no longer imports the reconciler merely to decide whether a
        high-safety role gets a review. Removing that module from a fixture
        therefore cannot resurrect the retired specialist-wide default.
        """
        root = Path(tempfile.mkdtemp(prefix="reviewer-recursion-vault-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        vault = root / "vault"
        vault.mkdir()
        for name in ("shared", "bin", "plugins"):
            source = REPO / name
            if source.exists():
                (vault / name).symlink_to(source)
        shutil.copytree(REPO / "model-lanes", vault / "model-lanes", symlinks=True)
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
            reviews=REVIEW_TARGET,
            vault=vault,
        )
        output = self.output(completed)
        self.assertEqual(completed.returncode, DRY_RUN_ADMITTED, msg=output)
        self.assertNotIn(REMOVED_SAFETY_GATE, output)


if __name__ == "__main__":
    unittest.main()
