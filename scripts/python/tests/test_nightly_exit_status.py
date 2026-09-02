"""The nightly must be able to say NO.

bin/run-nightly.sh deliberately keeps running after a phase fails -- the phases
are independent maintenance jobs and one failure must not cost the night its
remaining work. But until 2026-08-31 it also exited 0 unconditionally, so
launchd recorded success on a run whose product-hygiene phase had failed
(_state/nightly-failures/2026-08-31.log, 10:02:50). A nightly that cannot
report failure manufactures evidence of health.

These tests drive the REAL bin/run-nightly.sh, never a copy of its logic, by
pointing VAULT_ROOT at a fixture tree of stub phase scripts. shared/repo-root.sh
honours a pre-set VAULT_ROOT verbatim, and HOME is redirected too, so no phase
of the operator's live squad is invoked and no operator secret is sourced.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[3]
NIGHTLY = ROOT / "bin" / "run-nightly.sh"

# Phase name -> script basename, in invocation order. Mirrors the run_phase
# calls in bin/run-nightly.sh. "weekly-deep" is Sunday-only and is stubbed so
# the suite behaves identically on every weekday.
PHASE_SCRIPTS = (
    ("vault-snapshot", "vault-snapshot.sh"),
    ("doctor", "doctor.sh"),
    ("registry-reconciler", "registry-reconciler.sh"),
    ("memory-audit", "memory-audit.sh"),
    ("sweep-active", "sweep-active.sh"),
    ("browser-keep-alive", "browser-keep-alive.sh"),
    ("prune-board-scratch", "prune-board-worktrees.sh"),
    ("rotate-logs", "rotate-logs.sh"),
    ("system-cleanup", "system-cleanup.sh"),
    ("brain-cleanup", "brain-cleanup.sh"),
    ("morning-brief", "morning-brief.sh"),
    ("weekly-deep", "run-weekly.sh"),
)

# Everything invoked after memory-audit. If a fix for the exit code were
# implemented with `set -e` or an early return, these would stop running.
PHASES_AFTER_MEMORY_AUDIT = tuple(
    name
    for name, _ in PHASE_SCRIPTS[PHASE_SCRIPTS.index(("memory-audit", "memory-audit.sh")) + 1 :]
    if name != "weekly-deep"
)


class NightlyRun:
    """One fixture invocation of the real nightly script."""

    def __init__(
        self,
        returncode: int,
        stdout: str,
        ran: tuple[str, ...],
        arguments: dict[str, str],
        briefs: tuple[str, ...],
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.ran = ran
        self.arguments = arguments
        self.briefs = briefs

    @property
    def today_brief(self) -> str:
        return self.briefs[0] if self.briefs else ""

    @property
    def next_brief(self) -> str:
        return self.briefs[1] if len(self.briefs) > 1 else ""


class NightlyExitStatusTests(unittest.TestCase):
    def run_nightly(self, *, failing: frozenset[str] = frozenset(), absent: frozenset[str] = frozenset()) -> NightlyRun:
        """Run the real script against stub phases.

        `failing` names phases whose stub exits 1; `absent` names phases whose
        stub is not created at all, which is how run_phase's SKIP branch is
        reached.
        """
        with TemporaryDirectory() as raw:
            temp = Path(raw)
            vault = temp / "vault"
            home = temp / "home"
            (vault / "bin").mkdir(parents=True)
            home.mkdir()
            receipts = temp / "phases-that-ran"
            argument_receipts = temp / "phase-arguments"

            # doctor-log-home.sh is sourced from ${VAULT_ROOT}/bin, so the
            # fixture needs the real one rather than a stand-in.
            (vault / "bin" / "doctor-log-home.sh").write_text(
                (ROOT / "bin" / "doctor-log-home.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            for phase_name, script_name in PHASE_SCRIPTS:
                if phase_name in absent:
                    continue
                script = vault / "bin" / script_name
                if phase_name == "morning-brief" and phase_name not in failing:
                    script.write_text(
                        "#!/bin/bash\n"
                        f'printf "%s\\n" "{phase_name}" >> "{receipts}"\n'
                        f'printf "%s\\t%s\\n" "{phase_name}" "$*" >> "{argument_receipts}"\n'
                        f'exec /bin/bash "{ROOT / "bin" / "morning-brief.sh"}" "$@"\n',
                        encoding="utf-8",
                    )
                else:
                    script.write_text(
                        "#!/bin/bash\n"
                        f'printf "%s\\n" "{phase_name}" >> "{receipts}"\n'
                        f'printf "%s\\t%s\\n" "{phase_name}" "$*" >> "{argument_receipts}"\n'
                        f"exit {1 if phase_name in failing else 0}\n",
                        encoding="utf-8",
                    )
                script.chmod(0o755)

            environment = dict(os.environ)
            environment.update(
                VAULT_ROOT=str(vault),
                HOME=str(home),
                CHRONO_DOCTOR_LOG_DIR=str(temp / "doctor-logs"),
                VAULT_SNAPSHOT_DEST=str(temp / "snapshots"),
            )
            completed = subprocess.run(
                ["/bin/bash", str(NIGHTLY)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            ran = tuple(receipts.read_text(encoding="utf-8").split()) if receipts.exists() else ()
            arguments = dict(
                line.split("\t", 1)
                for line in argument_receipts.read_text(encoding="utf-8").splitlines()
            ) if argument_receipts.exists() else {}
            brief_dir = vault / "_state" / "morning-briefs"
            briefs = tuple(
                path.read_text(encoding="utf-8")
                for path in sorted(brief_dir.glob("*.md"))
            )
            return NightlyRun(completed.returncode, completed.stdout, ran, arguments, briefs)

    def test_a_failed_phase_makes_the_whole_run_exit_non_zero(self) -> None:
        """Mutation caught: dropping the exit-status propagation entirely.

        This is the reported defect. product-hygiene failed on 2026-08-31 and
        launchd still recorded a successful run.
        """
        run = self.run_nightly(failing=frozenset({"memory-audit"}))
        self.assertIn("FAIL  phase: memory-audit", run.stdout)
        self.assertNotEqual(
            run.returncode,
            0,
            "a nightly with a failed phase exited 0, so launchd records success",
        )

    def test_remaining_phases_still_run_after_an_early_phase_fails(self) -> None:
        """Mutation caught: 'fixing' the exit code with `set -e` or an early exit.

        Independence is the deliberate design: a failed vault snapshot must not
        cost the night its log rotation.
        """
        run = self.run_nightly(failing=frozenset({"vault-snapshot", "memory-audit"}))
        for phase in PHASES_AFTER_MEMORY_AUDIT:
            self.assertIn(phase, run.ran, f"{phase} stopped running after an earlier failure")

    def test_a_clean_run_still_exits_zero(self) -> None:
        """Mutation caught: making the script unconditionally exit non-zero."""
        run = self.run_nightly()
        self.assertEqual(run.returncode, 0, run.stdout[-2000:])

    def test_product_hygiene_is_not_a_duplicate_fatal_phase(self) -> None:
        """Deep doctor owns nightly publication reporting.

        Default product-hygiene is a strict local cleanup decision and fails
        whenever the daily-driver's ignored runtime/mailbox surfaces exist.
        Public-export mode certifies a projected candidate, not the private
        source tree. Nightly already asks deep doctor to run/report that audit,
        so a second direct hygiene phase makes ordinary live state fatal.
        """
        run = self.run_nightly()
        self.assertEqual(run.arguments["doctor"], "--deep")
        self.assertNotIn("START phase: product-hygiene", run.stdout)

    def test_the_run_names_every_failed_phase_in_a_closing_summary(self) -> None:
        """Mutation caught: exiting non-zero without saying which phase failed.

        The per-phase FAIL line is buried mid-log; the operator and the morning
        brief need the verdict at the end.
        """
        run = self.run_nightly(failing=frozenset({"doctor", "memory-audit"}))
        tail = run.stdout.split("nightly complete")[-1]
        self.assertIn("doctor", tail)
        self.assertIn("memory-audit", tail)

    def test_a_phase_whose_script_is_missing_is_not_reported_as_success(self) -> None:
        """Mutation caught: counting only FAIL and letting SKIP pass as healthy.

        A deleted or non-executable phase script is maintenance that did not
        happen, and it is silent -- exactly the failure mode this suite exists
        for. All 13 phase scripts exist and are executable today, so this costs
        a real run nothing.
        """
        run = self.run_nightly(absent=frozenset({"memory-audit"}))
        self.assertIn("SKIP  phase: memory-audit", run.stdout)
        self.assertNotEqual(
            run.returncode,
            0,
            "a phase that never ran was reported as a successful night",
        )

    def test_the_operator_brief_says_the_night_ran_clean(self) -> None:
        """The launchd exit code is not the operator-facing verdict."""
        run = self.run_nightly()
        self.assertIn(
            "NIGHTLY CLEAN",
            run.today_brief,
            "the operator brief did not render the clean nightly verdict",
        )

    def test_the_operator_brief_names_every_failed_phase(self) -> None:
        """A non-zero exit is useful only if its reader names what failed."""
        run = self.run_nightly(failing=frozenset({"doctor", "memory-audit"}))
        self.assertIn("NIGHTLY PHASE FAILURE", run.today_brief)
        self.assertIn("doctor", run.today_brief)
        self.assertIn("memory-audit", run.today_brief)

    def test_the_next_brief_says_not_run_when_no_next_run_starts(self) -> None:
        """A missing scheduled invocation must not look like a clean night.

        One completed run seeds the next dated brief. We deliberately do not
        invoke the next run, reproducing a nightly that never fired.
        """
        run = self.run_nightly()
        self.assertIn(
            "NIGHTLY NOT RUN",
            run.next_brief,
            "no-run rendered like success because no dead-man brief was seeded",
        )
        self.assertNotIn("NIGHTLY CLEAN", run.next_brief)


if __name__ == "__main__":
    unittest.main()
