#!/usr/bin/env python3
"""Two dispatch-time TSV field reads must fail closed, not open.

`map_field` (bin/send-task.sh) is `awk '$1 == s {print $idx; exit}'`. On a row
shorter than `idx`, awk prints an empty string and **exits 0** -- verified live
with a two-field fixture -- so the exit code carries no signal and the `|| true`
around every call is irrelevant. bin/send-task.sh:1237-1242 already fails
closed on field 7 (primary_lane -> MAP_MODEL empty => die), but two adjacent
reads did not get the same treatment:

  * field 21 (operator_gate) empty -> defaulted to MAP_OPERATOR_GATE="[]",
    silently requiring NO operator approval.
  * field 4 (safety_level) empty -> a malformed quality-floor row reached later
    routing even though review is now packet-triggered rather than role-derived.

All 69 real rows carry 29 fields today (`awk -F'\t' 'NR>1{print NF}' | sort -u`
prints only 29), so this is latent -- it fires the moment a row is truncated or
hand-edited short, which a public release invites.

This suite drives the REAL bin/send-task.sh against a REAL, truncated
specialist-runtime-map.tsv row through a hermetic fixture root: a copy of
send-task.sh (so `SQUAD_CODE_ROOT` -- derived from the invoked script's own
`readlink -f` path -- resolves INSIDE the fixture, not the real repo) plus a
symlink to the real `scripts/` tree (so every python helper send_task_main
touches on the way to the field-resolution guard -- worktree_isolation,
plan_item_binding -- is the real module, never reimplemented here) plus a
fixture-only `specialist-runtime-map.tsv` and fixture-only specialist
markdown files. Every dispatch passes `--dry-run`, which exits 2 (or dies
earlier) well before any board-registry write, mailbox creation past mkdir,
or supervisor spawn -- so a pre-fix run that does NOT die at the field-
resolution guard is still side-effect-free, just like `test_sendtask_tails.py`
runs the real dispatcher against an isolated root with no board supervisor.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK_SOURCE = REPO_ROOT / "bin" / "send-task.sh"
REPO_ROOT_SH = REPO_ROOT / "shared" / "repo-root.sh"

# Base a fixture row on a real 29-field row (`triage`) so every column an
# earlier guard reads (field 7 primary_lane, field 2 source_namespace) is
# realistic; only the columns this suite is about are perturbed.
REAL_ROW_TAIL = (
    "judgment\t{safety}\t[]\tnone\tclaude\tclaude.fable.xhigh\tcodex\t"
    "codex.sol.high\tclaude\tclaude.fable.max\tescalation.signal.v1\tcodex\t"
    "codex.sol.high\tnone\tnone\tnone\tthroughput.never.v1\t"
    "failover.conservative.v1"
)


def operator_gate_truncated_row(specialist: str) -> str:
    """20 columns: fields 1-20 present, field 21 (operator_gate) and on absent."""
    return f"{specialist}\tshared\t" + REAL_ROW_TAIL.format(safety="low")


def safety_level_empty_row(specialist: str) -> str:
    """29 columns, but field 4 (safety_level) is blank between two tabs."""
    tail = REAL_ROW_TAIL.format(safety="")
    return f"{specialist}\tshared\t{tail}\t[]\tfalse\t[]\t[]\t[]\tfixture row\t[]\t2.0\tfalse"


def control_valid_row(specialist: str) -> str:
    """29 columns, every field populated -- the fixture proves this dispatches
    past the guard instead of dying for an unrelated reason."""
    tail = REAL_ROW_TAIL.format(safety="low")
    return f"{specialist}\tshared\t{tail}\t[]\tfalse\t[]\t[]\t[]\tfixture row\t[]\t2.0\tfalse"


class DispatchGateFailClosedTests(unittest.TestCase):
    OPERATOR_SPECIALIST = "dispatch-gate-fixture-operator"
    SAFETY_SPECIALIST = "dispatch-gate-fixture-safety"
    CONTROL_SPECIALIST = "dispatch-gate-fixture-control"

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dispatch-gate-fixture-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        # A real copy, not a symlink: SQUAD_CODE_ROOT is `readlink -f` of the
        # invoked script's own path, so only a real file here relocates it.
        fixture_bin = self.root / "bin"
        fixture_bin.mkdir()
        shutil.copy2(SEND_TASK_SOURCE, fixture_bin / "send-task.sh")

        fixture_shared = self.root / "shared"
        fixture_shared.mkdir()
        (fixture_shared / "repo-root.sh").symlink_to(REPO_ROOT_SH)
        header = (REPO_ROOT / "shared" / "specialist-runtime-map.tsv").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        rows = [
            header,
            operator_gate_truncated_row(self.OPERATOR_SPECIALIST),
            safety_level_empty_row(self.SAFETY_SPECIALIST),
            control_valid_row(self.CONTROL_SPECIALIST),
        ]
        (fixture_shared / "specialist-runtime-map.tsv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8"
        )

        # Every python helper send_task_main imports off SQUAD_CODE_ROOT
        # (worktree_isolation, plan_item_binding, ...) is the real module.
        (self.root / "scripts").symlink_to(REPO_ROOT / "scripts")

        # VAULT_ROOT: a fixture-only specialist directory (the "unknown
        # specialist" lookup reads from here, not SQUAD_CODE_ROOT) plus an
        # empty departments/ so `find` does not error on a missing path.
        self.vault = self.root / "vault"
        (self.vault / "departments").mkdir(parents=True)
        specialists = self.vault / "shared" / "specialists"
        specialists.mkdir(parents=True)
        for name in (self.OPERATOR_SPECIALIST, self.SAFETY_SPECIALIST, self.CONTROL_SPECIALIST):
            (specialists / f"{name}.md").write_text(
                f"# {name}\n\nUnit-test fixture specialist. Not a real role.\n",
                encoding="utf-8",
            )

    def dispatch(self, specialist: str) -> subprocess.CompletedProcess[str]:
        task_id = "TASK-2026-08-17-0001-gatefixture"
        packet = self.root / f"{task_id}.md"
        packet.write_text(
            "---\n"
            f"id: {task_id}\n"
            "run_id: DISPATCH-GATE-FIXTURE-TEST\n"
            "to_model: claude\n"
            f"specialist: {specialist}\n"
            "source_namespace: shared\n"
            "compatibility_namespace: coding\n"
            "mode: project\n"
            "result_type: normal\n"
            "write_scope: []\n"
            "parallel_safe: false\n"
            "direct_lane_work_allowed: true\n"
            "mandatory_review: false\n"
            "review_model: none\n"
            "reviews: none\n"
            "---\n\n"
            "Fixture packet for the dispatch-gate fail-closed suite.\n",
            encoding="utf-8",
        )
        return subprocess.run(
            ["bash", str(self.root / "bin" / "send-task.sh"), str(packet), "--dry-run"],
            # self.vault is a plain tempdir, not a git checkout, so
            # send-task.sh cannot derive a branch and now refuses to guess
            # one; supply it explicitly rather than weaken that guard.
            env={**os.environ, "VAULT_ROOT": str(self.vault), "SQUAD_BASE_BRANCH": "v2"},
            capture_output=True,
            text=True,
            cwd=str(self.root),
            timeout=60,
        )

    def output(self, completed: subprocess.CompletedProcess[str]) -> str:
        return completed.stdout + completed.stderr

    def test_operator_gate_truncated_before_column_21_must_die(self) -> None:
        """The exact scenario the brief specifies: a row truncated before
        column 21 must refuse dispatch, not silently default operator_gate
        to '[]' (no operator approval required)."""
        completed = self.dispatch(self.OPERATOR_SPECIALIST)
        output = self.output(completed)
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("operator_gate", output, msg=output)
        self.assertIn(self.OPERATOR_SPECIALIST, output, msg=output)

    def test_safety_level_empty_field_must_die(self) -> None:
        """A row with an empty (but present) safety_level column must refuse
        dispatch; trigger-based review does not make a malformed row valid."""
        completed = self.dispatch(self.SAFETY_SPECIALIST)
        output = self.output(completed)
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("safety_level", output, msg=output)
        self.assertIn(self.SAFETY_SPECIALIST, output, msg=output)

    def test_complete_row_does_not_trip_either_new_gate(self) -> None:
        """Control: a fully-populated row must NOT trip either new gate --
        proves the fix is scoped to the missing-field case, not a blanket
        regression on every dispatch. (This fixture has no model-lane adapter
        for the fixture specialist, so the run still dies later at the
        unrelated `validate_native_adapter` check -- that die is expected and
        is not what this test asserts on.)"""
        completed = self.dispatch(self.CONTROL_SPECIALIST)
        output = self.output(completed)
        self.assertNotIn("has no operator_gate", output, msg=output)
        self.assertNotIn("has no safety_level", output, msg=output)


if __name__ == "__main__":
    unittest.main()
