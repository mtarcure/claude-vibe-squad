#!/usr/bin/env python3
"""bin/doctor.sh's fast/--deep split, and the loudness of what it defers.

The launcher gates on doctor under SQUAD_DOCTOR_TIMEOUT (default 45s), and on
2026-08-17 doctor took 141.3s -- 127.3s of it the public-export hygiene gate --
so the only working launch path was SQUAD_SKIP_DOCTOR=1. The fix defers that one
check to --deep. These tests pin the two halves of that bargain:

  1. the fast path really does NOT run it (a guard that runs it anyway is the
     regression that brings the 127s back), and
  2. skipping it is never silent and never a pass -- it is named in the console
     report, in the JSON summary, and in the verdict line.

Both directions are exercised against a real doctor process in a throwaway tree
with a stubbed HOME, following DoctorTargetContractTest in
test_shell_check_tristate.py. Nothing here touches the operator's repository,
processes, tmux server, or doctor logs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402
import doctor_fixture  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

_EMPTY_PS = doctor_fixture.EMPTY_PS

# The whole point of the check under test is that the real one is expensive.
# This stub is instant and records the fact that it was invoked, which is the
# only thing these tests need to observe.
_HYGIENE_SPY = """#!/bin/bash
printf '%s\\n' "$@" >> "$DOCTOR_TEST_HYGIENE_SPY"
echo "Product hygiene audit: runtime=0 mailbox=0 drafts=0 tracked_blockers=0 tracked_scan=scanned drift=0 drift_roots_absent=0 remote_ref=ran-pass"
echo "Log: /dev/null"
exit 0
"""


class DoctorDeepModeTest(unittest.TestCase):
    def run_doctor(self, *args: str, install_hygiene: bool = True):
        """Run a real doctor in a throwaway tree; return (result, summary, spy)."""
        with tempfile.TemporaryDirectory(prefix="doctor-deep-mode-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            doctor_fixture.install_doctor_helpers(ROOT, root)

            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )

            spy = fixture / "hygiene-invocations.txt"
            if install_hygiene:
                hygiene = root / "bin" / "product-hygiene.sh"
                hygiene.write_text(_HYGIENE_SPY, encoding="utf-8")
                hygiene.chmod(0o755)

            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            doctor_fixture.write_stub(local_bin, "ps", _EMPTY_PS)
            # Doctor now gates on the launcher's required-command list, so the
            # fixture supplies it rather than inheriting the maintainer host's
            # answer to "is kimi installed".
            doctor_fixture.stub_launch_dependencies(local_bin, ROOT)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
                "DOCTOR_TEST_HYGIENE_SPY": str(spy),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)

            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh"), *args],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            log_dir = home / ".local/state/chrono-vault/doctor-logs"
            summaries = sorted(log_dir.glob("*-summary.json"))
            self.assertEqual(
                len(summaries),
                1,
                f"doctor did not emit one summary: {result.stdout}{result.stderr}",
            )
            summary = json.loads(summaries[0].read_text(encoding="utf-8"))
            reports = sorted(p for p in log_dir.glob("*.md"))
            self.assertEqual(len(reports), 1, "doctor did not emit one report")
            report = reports[0].read_text(encoding="utf-8")
            invocations = spy.read_text(encoding="utf-8") if spy.exists() else ""
            return result, summary, report, invocations

    def test_fast_path_does_not_run_the_deferred_check(self):
        result, summary, _report, invocations = self.run_doctor()

        # THE regression this pins: the fast path must not pay the 127s.
        self.assertEqual(
            invocations,
            "",
            "fast mode invoked the deferred hygiene gate: " + invocations,
        )
        self.assertEqual(summary["mode"], "fast")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deep_runs_the_deferred_check_with_its_real_arguments(self):
        result, summary, _report, invocations = self.run_doctor("--deep")

        # The control for the test above: with the guard satisfied the very same
        # fixture DOES invoke it, so an always-empty spy cannot make the fast-path
        # assertion pass for the wrong reason.
        self.assertEqual(
            invocations.split(),
            ["--public-export"],
            "deep mode did not invoke the hygiene gate as expected: "
            + repr(invocations),
        )
        self.assertEqual(summary["mode"], "deep")
        self.assertEqual(summary["deep_deferred_count"], 0)
        self.assertEqual(summary["deep_deferred"], [])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deferral_is_loud_in_every_channel_and_never_a_pass(self):
        result, summary, report, _invocations = self.run_doctor()

        # Counted as could-not-determine, never healthy. A silent drop is the
        # failure mode this whole vocabulary exists to prevent.
        self.assertEqual(summary["deep_deferred_count"], 1)
        deferred = summary["deep_deferred"]
        self.assertEqual(len(deferred), 1)
        self.assertIn("--deep", deferred[0])
        self.assertIn(deferred[0], summary["unknowns"])
        self.assertNotIn(deferred[0], summary["skipped"])
        self.assertGreaterEqual(summary["unknown_count"], 1)

        # ...and it does not block a launch: not an issue, not gate-blocking.
        self.assertEqual(summary["issue_count"], 0)
        self.assertEqual(summary["gate_unknown_count"], 0)
        self.assertEqual(result.returncode, 0)

        # Visible on the console the launcher shows...
        self.assertIn("mode: fast", result.stdout)
        self.assertIn("NOT MEASURED IN FAST MODE", result.stdout)
        self.assertIn("not measured in fast mode", result.stdout)
        self.assertIn("--deep", result.stdout)
        # ...in the verdict line itself, so a "healthy" cannot over-claim...
        self.assertIn("NOT measured in this fast run", result.stdout)
        # ...and in the written report.
        self.assertIn("Mode: fast", report)
        self.assertIn("Not measured in fast mode", report)

    def test_deferred_check_absent_tool_still_reports_could_not_run(self):
        """Deferring must not hide a missing checker.

        Fast mode declines to RUN the gate; it does not stop knowing whether the
        gate exists. Reporting "not measured in fast mode" for a tool that is not
        installed would swap a real defect for a scheduling note.
        """
        _result, summary, _report, invocations = self.run_doctor(
            install_hygiene=False
        )
        self.assertEqual(invocations, "")
        self.assertEqual(summary["deep_deferred_count"], 0)
        self.assertIn(
            "public export hygiene could not run",
            summary["unknowns"],
        )

    def test_unknown_argument_is_refused_rather_than_ignored(self):
        """A typo'd flag must not silently deliver the other mode."""
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "bin" / "doctor.sh"), "--dep"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 64, result.stdout + result.stderr)
        self.assertIn("unknown argument", result.stderr)
        self.assertNotIn("VERDICT", result.stdout)


class DoctorDeepModeReachabilityTest(unittest.TestCase):
    """The deferred check must still actually run somewhere, not just be reachable.

    A flag nobody passes is a check that was deleted with extra steps.
    """

    def test_nightly_runs_doctor_in_deep_mode(self):
        nightly = (ROOT / "bin" / "run-nightly.sh").read_text(encoding="utf-8")
        self.assertIn(
            'run_phase "doctor"               "${VAULT_ROOT}/bin/doctor.sh" --deep',
            nightly,
        )

    def test_launcher_gate_still_runs_the_fast_path(self):
        launcher = (ROOT / "bin" / "launch-squad.sh").read_text(encoding="utf-8")
        self.assertIn('"${VAULT_ROOT}/bin/doctor.sh" 2>&1)"', launcher)
        self.assertNotIn("doctor.sh --deep", launcher)

    def test_squad_doctor_forwards_arguments(self):
        squad = (ROOT / "bin" / "squad").read_text(encoding="utf-8")
        self.assertIn('bash "${VAULT_ROOT}/bin/doctor.sh" "${@:2}"', squad)


if __name__ == "__main__":
    unittest.main()
