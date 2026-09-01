#!/usr/bin/env python3
"""Plan D Task 3: doctor must gate on the commands `squad up` gates on.

README's Quickstart runs ``squad doctor`` immediately before ``squad up``, so
doctor is the documented pre-flight for the launcher's hard dependency gate.
Measured 2026-08-17 against bin/doctor.sh's 1,390 lines: the strings ``fswatch``,
``uv`` and ``curl`` appeared ZERO times, while bin/launch-squad.sh exits 1
without them. A cloner missing fswatch therefore read a green health report and
then could not launch -- the pre-flight passing for the launch it pre-flights.

These tests pin both halves:

  1. every command on the shared list is actually probed, and a missing one is
     an ISSUE (exit 1), not a warning the exit code ignores; and
  2. the launcher and doctor read the SAME list, so it cannot drift back apart.

SAFETY: doctor runs in a throwaway tree with a stubbed HOME. Every dependency,
including tmux, is stubbed on the fixture's own PATH (doctor prepends
``$HOME/.local/bin``), so nothing here reaches the operator's repository, tmux
server, processes or doctor logs. bin/launch-squad.sh is READ, never run.
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


# The negative control cannot be built by DELETING a stub: doctor prepends
# /opt/homebrew/bin to PATH unconditionally, so a masked `fswatch` still
# resolves to the maintainer's real one and the test would pass for the wrong
# reason (measured: all nine "missing" subtests exited 0). Instead the fixture
# gets its OWN required-command list of names no host can supply, one stubbed
# and one not -- which exercises the same loop over a list whose answers this
# test controls completely.
_PROBE_PRESENT = "vs-doctor-probe-present"
_PROBE_ABSENT = "vs-doctor-probe-absent"
_SENTINEL_LIST = f"""#!/usr/bin/env bash
SQUAD_REQUIRED_COMMANDS=({_PROBE_PRESENT} {_PROBE_ABSENT})
SQUAD_REQUIRED_COMMANDS_HINT='sentinel remedy line'
"""


class DoctorLaunchDependencyParityTest(unittest.TestCase):
    def run_doctor(self, *, sentinel_list: bool = False):
        with tempfile.TemporaryDirectory(prefix="doctor-dep-parity-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            doctor_fixture.install_doctor_helpers(ROOT, root)
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )

            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            doctor_fixture.write_stub(local_bin, "ps", doctor_fixture.EMPTY_PS)
            doctor_fixture.stub_launch_dependencies(local_bin, ROOT)
            if sentinel_list:
                (root / "shared" / "launch-dependencies.sh").write_text(
                    _SENTINEL_LIST, encoding="utf-8"
                )
                doctor_fixture.write_stub(local_bin, _PROBE_PRESENT)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)

            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh")],
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
            reports = sorted(log_dir.glob("[0-9]*.md"))
            self.assertEqual(len(reports), 1, "doctor did not emit one report")
            report = reports[0].read_text(encoding="utf-8")
            return result, summary, report

    def test_complete_install_passes_the_dependency_gate(self):
        """The positive control: with every dependency present, no issue.

        Without it, a check that could never fire would satisfy the test below
        for the wrong reason.
        """
        result, summary, report = self.run_doctor()
        self.assertEqual(summary["issues"], [], result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Every command `squad up` requires", report)

    def test_a_missing_dependency_is_a_blocking_issue(self):
        """The cloner's actual situation: one required command is not installed.

        WARN would not do. bin/launch-squad.sh answers this state with exit 1,
        and a pre-flight whose exit code disagrees with the launch it precedes
        is the defect being fixed, not a stylistic choice.
        """
        result, summary, report = self.run_doctor(sentinel_list=True)

        self.assertEqual(
            result.returncode, 1, result.stdout + result.stderr
        )
        self.assertTrue(
            any(
                "missing launch dependencies" in issue and _PROBE_ABSENT in issue
                for issue in summary["issues"]
            ),
            f"the absent command was not reported as an issue: {summary['issues']}",
        )
        # ...and only the absent one. A check that named every entry whenever
        # any entry was missing would be useless to the reader.
        self.assertNotIn(
            _PROBE_PRESENT,
            " ".join(summary["issues"]),
            "a present command was reported missing",
        )
        # The remedy travels with the diagnosis, from the same shared file.
        self.assertIn("squad up` will exit 1", result.stdout)
        self.assertIn("sentinel remedy line", report)

    def test_every_command_on_the_real_list_is_actually_probed(self):
        """A check that probed a SUBSET is how `uv` and `curl` stayed invisible.

        Reads the report line back and requires each shared-list entry by name,
        so adding a dependency to shared/launch-dependencies.sh cannot leave
        doctor silently not looking for it.
        """
        _result, _summary, report = self.run_doctor()
        probed = [
            line for line in report.splitlines() if "Every command `squad up`" in line
        ]
        self.assertEqual(len(probed), 1, report)
        for command in doctor_fixture.launch_dependencies(ROOT):
            with self.subTest(command=command):
                self.assertIn(command, probed[0])

    def test_unreadable_dependency_list_is_unknown_not_healthy(self):
        """Fail closed: an unrunnable gate must never read as nothing-missing."""
        with tempfile.TemporaryDirectory(prefix="doctor-dep-parity-gone-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            doctor_fixture.install_doctor_helpers(ROOT, root)
            (root / "shared" / "launch-dependencies.sh").unlink()
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )
            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            doctor_fixture.write_stub(local_bin, "ps", doctor_fixture.EMPTY_PS)
            doctor_fixture.stub_launch_dependencies(local_bin, ROOT)
            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)
            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            log_dir = home / ".local/state/chrono-vault/doctor-logs"
            summary = json.loads(
                sorted(log_dir.glob("*-summary.json"))[0].read_text(encoding="utf-8")
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertTrue(
                any(
                    "launch dependency parity could not be checked" in entry
                    for entry in summary["gate_unknowns"]
                ),
                summary["gate_unknowns"],
            )
            self.assertEqual(summary["issues"], [])


class LaunchDependencyListHasOneHomeTest(unittest.TestCase):
    """The launcher and doctor must READ the list, never restate it."""

    def test_launcher_iterates_the_shared_list(self):
        launcher = (ROOT / "bin" / "launch-squad.sh").read_text(encoding="utf-8")
        self.assertIn("shared/launch-dependencies.sh", launcher)
        self.assertIn('for dep in "${SQUAD_REQUIRED_COMMANDS[@]}"', launcher)
        # The literal list the shared file replaced must not linger anywhere.
        self.assertNotIn("for dep in tmux fswatch jq curl", launcher)

    def test_doctor_iterates_the_shared_list(self):
        doctor = (ROOT / "bin" / "doctor.sh").read_text(encoding="utf-8")
        self.assertIn("shared/launch-dependencies.sh", doctor)
        self.assertIn('for _dep in "${SQUAD_REQUIRED_COMMANDS[@]}"', doctor)

    def test_readme_quickstart_names_every_required_command(self):
        """The third reader of this list is a human following the Quickstart."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart = readme.split("## Quickstart", 1)[1][:1200]
        for command in doctor_fixture.launch_dependencies(ROOT):
            if command in ("claude", "codex", "gemini", "grok", "kimi"):
                continue  # named as model-lane products rather than shell commands
            with self.subTest(command=command):
                self.assertIn(command, quickstart)


if __name__ == "__main__":
    unittest.main()
