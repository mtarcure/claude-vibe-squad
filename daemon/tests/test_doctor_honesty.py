"""bin/doctor.sh must not report health for a check it could not run.

Three defects found in the 2026-08-11 zero-state release rehearsal, each pinned
here:

1. The projection withholds files doctor's own checks require, so doctor exits 1
   on a public install over `docs/brain-map.md` -- a file that install was never
   meant to carry.
2. Doctor escaped the temporary HOME: lane presence came from the effective-UID
   passwd home, so a fresh install was told the *maintainer's* four CLIs were
   its own, and it printed an auth CLASS where a reader sees an auth RESULT.
3. The process audit took three `/bin/ps: Operation not permitted` errors and
   still wrote healthy absence statements.

The runs below are hermetic: doctor is pointed at a minimal VAULT_ROOT holding
only itself and its two sourced helpers, so every subordinate checker is absent
and answers from the could-not-determine path in milliseconds. No network, no
CLI spawn, no write outside the temporary tree.

`ps` is supplied by a stub in three modes, which is what makes "nothing found"
a measurement rather than a silence:

    deny   every invocation fails the way the sandbox fails it
    empty  the self-probe answers, the enumerations return no rows
    busy   the self-probe answers, the enumerations return a long-running CLI

`empty` and `busy` are each other's positive control: the same code path must
report absence in one and presence in the other. A harness that could not tell
them apart could not support either claim.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "bin" / "doctor.sh"
# Sourced by doctor from its own physical directory / parent, so both have to
# travel with it into the fixture tree.
HELPERS = (
    Path("bin") / "doctor-log-home.sh",
    Path("shared") / "repo-root.sh",
)
VAULTROOT = REPO / "plugins" / "chrono-vault" / "vaultroot.py"

# ps stubs. macOS ps is asked four different ways by doctor; the only shape that
# has to answer truthfully for the liveness probe is `-p <pid>`.
_PS_DENY = """#!/bin/bash
printf '/bin/ps: Operation not permitted\\n' >&2
exit 1
"""

_PS_TABLE = """#!/bin/bash
# Answer the self-probe truthfully so doctor's positive control passes, then
# emit ROWS for every enumeration. An empty ROWS is a real empty process table,
# not a failure to read one.
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-p" ]]; then
        printf '%s\\n' "$arg"
        exit 0
    fi
    prev="$arg"
done
printf '%s' "$ROWS"
exit 0
"""

_BUSY_ROW = "99999     1 12-06:34:59   0.0 claude\n"


class DoctorHonestyTest(unittest.TestCase):
    maxDiff = None

    # ---- fixture -----------------------------------------------------------

    def _fixture(
        self,
        ps_mode: str,
        lanes: tuple[str, ...] = (),
        with_vaultroot: bool = True,
    ) -> tuple[Path, dict[str, str]]:
        base = Path(tempfile.mkdtemp(prefix="vs-doctor-honesty."))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)

        root = base / "root"
        (root / "bin").mkdir(parents=True)
        (root / "shared").mkdir(parents=True)
        shutil.copy2(DOCTOR, root / "bin" / "doctor.sh")
        (root / "bin" / "doctor.sh").chmod(0o755)
        for helper in HELPERS:
            shutil.copy2(REPO / helper, root / helper)
        if with_vaultroot:
            # The real module, so the vault check answers with its real
            # single-line VaultRootError rather than a ModuleNotFoundError
            # traceback. Stdlib-only, so it costs the fixture nothing.
            (root / "plugins" / "chrono-vault").mkdir(parents=True)
            shutil.copy2(VAULTROOT, root / "plugins" / "chrono-vault" / "vaultroot.py")

        # A real git repository that tracks nothing. `docs/brain-map.md` is then
        # absent AND untracked here, which is exactly the shape of a public
        # projection: the file was never carried, as opposed to lost.
        subprocess.run(
            ["git", "init", "-q"], cwd=root, check=True, capture_output=True
        )

        home = base / "home"
        home.mkdir()

        stub_dir = base / "stub-bin"
        stub_dir.mkdir()
        stub = stub_dir / "ps"
        stub.write_text(_PS_DENY if ps_mode == "deny" else _PS_TABLE)
        stub.chmod(0o755)

        for lane in lanes:
            planted = stub_dir / lane
            planted.write_text(f"#!/bin/bash\nprintf 'stub-{lane} 9.9.9\\n'\n")
            planted.chmod(0o755)

        environment = {
            "HOME": str(home),
            "PATH": f"{stub_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "VAULT_ROOT": str(root),
            "TERM": "dumb",
            "LANG": "C",
            "TMPDIR": str(base),
            "ROWS": _BUSY_ROW if ps_mode == "busy" else "",
        }
        return root, environment

    def _run(
        self,
        ps_mode: str,
        lanes: tuple[str, ...] = (),
        extra_env: dict[str, str] | None = None,
        with_vaultroot: bool = True,
    ) -> tuple[int, str, dict]:
        root, environment = self._fixture(ps_mode, lanes, with_vaultroot)
        environment.update(extra_env or {})
        completed = subprocess.run(
            ["bash", str(root / "bin" / "doctor.sh")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        logs = Path(environment["HOME"]) / ".local/state/chrono-vault/doctor-logs"
        reports = sorted(p for p in logs.glob("*.md"))
        self.assertEqual(
            len(reports),
            1,
            f"expected exactly one report under the temporary HOME, got {reports}. "
            f"stderr={completed.stderr[-2000:]}",
        )
        summaries = sorted(logs.glob("*-summary.json"))
        self.assertEqual(len(summaries), 1, f"expected one summary, got {summaries}")
        raw = summaries[0].read_text(encoding="utf-8")
        try:
            summary = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Not an incidental test failure. Every consumer reads this file
            # with a `// 0` jq fallback, so an unparseable summary reports zero
            # issues for a run that found some.
            self.fail(f"doctor wrote a summary that is not valid JSON ({exc}):\n{raw}")
        return completed.returncode, reports[0].read_text(encoding="utf-8"), summary

    # ---- 3: a check that could not run cannot report health ----------------

    def test_summary_carries_a_third_state(self):
        """The vocabulary itself must exist and be counted, not just printed."""
        _, _, summary = self._run("empty")
        self.assertIn(
            "unknown_count",
            summary,
            "doctor's summary has no could-not-determine count: every status "
            "still has only two values",
        )
        self.assertIsInstance(summary["unknown_count"], int)
        self.assertEqual(summary["unknown_count"], len(summary["unknowns"]))

    def test_denied_ps_reports_undetermined_not_healthy(self):
        status, report, summary = self._run("deny")

        self.assertNotIn(
            "No long-running CLI processes detected",
            report,
            "a ps that answered 'Operation not permitted' still produced a "
            "healthy absence statement",
        )
        self.assertIn("COULD NOT DETERMINE", report)
        self.assertTrue(
            any("process audit could not run" in u for u in summary["unknowns"]),
            f"process audit missing from unknowns: {summary['unknowns']}",
        )
        self.assertFalse(
            any("long-running CLI" in h for h in _healthy_lines(report)),
            "a denied process audit contributed a healthy line",
        )
        # A check it could not run must not make the machine look better.
        self.assertEqual(status, 0, "denied ps must not be reported as breakage")

    def test_working_ps_still_determines_both_answers(self):
        """Positive control: absence and presence must be distinguishable.

        Without this, `test_denied_ps_...` would also pass against a doctor that
        simply never reports on processes at all.
        """
        _, empty_report, empty_summary = self._run("empty")
        _, busy_report, _ = self._run("busy")

        self.assertIn("No long-running CLI processes detected", empty_report)
        self.assertFalse(
            any("process audit could not run" in u for u in empty_summary["unknowns"]),
            "a usable ps was reported as undetermined",
        )
        self.assertIn("Long-running CLI processes", busy_report)
        self.assertNotIn("No long-running CLI processes detected", busy_report)

    def test_missing_subordinate_checkers_are_undetermined_not_passed(self):
        """Absent checkers must not read as clean scans."""
        _, report, summary = self._run("empty")
        unknowns = " | ".join(summary["unknowns"])
        for expected in (
            "MCP usability audit could not run",
            "public export hygiene could not run",
            "memory audit could not run",
            "specialist/routing validation could not run",
        ):
            self.assertIn(expected, unknowns, f"missing unknown: {expected}")
        self.assertNotIn("Memory audit passed", report)
        self.assertNotIn("public export hygiene clean", report)

    # ---- 1: withheld files must not decide health --------------------------

    def test_unpublished_brain_map_is_not_an_issue(self):
        status, report, summary = self._run("empty")
        self.assertNotIn(
            "brain map missing",
            summary["issues"],
            "a file this distribution never carried was reported as breakage",
        )
        self.assertTrue(
            any("brain map is private" in s for s in summary["skipped"]),
            f"brain map absent from the not-applicable list: {summary['skipped']}",
        )
        self.assertIn("not applicable here", report)
        self.assertEqual(status, 0)

    def test_zero_state_install_exits_zero(self):
        """The whole point: a clean machine is not a broken machine."""
        status, _, summary = self._run("empty")
        self.assertEqual(
            status,
            0,
            f"zero-state install exited {status}; issues={summary['issues']}",
        )
        self.assertEqual(summary["issue_count"], 0, summary["issues"])
        self.assertEqual(
            summary["gate_unknown_count"], 0, summary["gate_unknowns"]
        )
        self.assertEqual(summary["gate_unknowns"], [])
        # ...and it is not exiting 0 by having nothing to say.
        self.assertGreater(summary["unknown_count"], 0)
        absent_inputs = " | ".join(summary["absent_inputs"])
        for expected in (
            "token-bleed artifact scan has no source directories",
            "dispatch-log token-spend scan has no input",
            "dispatch completion scan has no archive targets",
            "inbox backlog scan has no inbox targets",
        ):
            self.assertIn(
                expected,
                absent_inputs,
                f"zero-state input was hidden instead of reported: {expected}",
            )

    def test_unconfigured_optional_state_warns_rather_than_fails(self):
        _, _, summary = self._run("empty")
        warnings = " | ".join(summary["warnings"])
        self.assertIn("secrets.zsh not configured", warnings)
        self.assertIn("private memory vault not configured", warnings)
        for issue in summary["issues"]:
            self.assertNotIn("secrets.zsh", issue)
            self.assertNotIn("private memory vault", issue)

    def test_multiline_finding_still_yields_parseable_json(self):
        """A summary that fails to parse fails OPEN, which is the worst state.

        On a partial install the vault module itself is missing, so the check's
        message is a Python traceback -- several lines. Raw newlines are illegal
        inside a JSON string, and `jq -r '.issue_count // 0'` answers 0 for a
        file it cannot read, so the morning brief reported no issues for a
        doctor run that exited 1. Measured against HEAD 2026-08-11.
        """
        status, _, summary = self._run(
            "empty",
            extra_env={"CHRONO_VAULT_ROOT": "/nonexistent/vault"},
            with_vaultroot=False,
        )
        self.assertGreater(summary["issue_count"], 0)
        self.assertTrue(
            any("private memory vault invalid" in i for i in summary["issues"]),
            f"a configured-but-broken vault must stay an issue: {summary['issues']}",
        )
        self.assertEqual(status, 1)

    # ---- 2: honour the HOME you were given ---------------------------------

    def test_cli_presence_reports_what_this_home_can_reach(self):
        """A lane planted on the fixture PATH is the one that must be reported.

        Note doctor prepends `/opt/homebrew/bin` to PATH itself, so a
        Homebrew-installed lane is legitimately visible to ANY home on this
        machine -- reporting it is correct, and asserting its absence would only
        pin the test to this host. What may never happen is a lane resolved out
        of the ACCOUNT home while $HOME points somewhere else; that is the
        defect, and the next test pins it.
        """
        _, report, _ = self._run("empty", lanes=("claude",))
        self.assertIn("stub-claude 9.9.9", report)
        self.assertTrue(
            any("claude: " in line and "stub-claude" in line
                for line in _healthy_lines(report)),
            "the planted claude was not reported as this HOME's install",
        )

        # A lane absent from this HOME's PATH must be reported absent, never
        # borrowed from elsewhere. `kimi` is planted nowhere in the fixture.
        _, bare_report, bare_summary = self._run("empty")
        self.assertIn(
            "kimi CLI not installed for this HOME",
            " | ".join(bare_summary["warnings"]),
        )
        self.assertNotIn("stub-claude", bare_report)

    def test_no_lane_is_resolved_out_of_the_account_home(self):
        """The 2026-08-11 defect, stated as an invariant.

        Under a temporary HOME, doctor reported the maintainer's
        ~/.local/bin/claude and ~/.local/bin/kimi as this installation's, because
        lane presence came from the effective-UID passwd home. The PATH-resolved
        section may name no path under that account home once $HOME has moved.
        The dispatch-rail section below it may -- those are explicitly labelled
        authority paths, which is the whole point of separating them.
        """
        _, report, _ = self._run("empty")
        account_home = str(Path(os.path.expanduser("~")).resolve())
        fixture_home = report.split("HOME=", 1)[1].split(")", 1)[0]
        if Path(fixture_home).resolve() == Path(account_home):
            self.skipTest("fixture HOME coincides with the account home")

        section = report.split("Resolved on this HOME's PATH", 1)[1]
        section = section.split("Dispatch-rail view", 1)[0]
        self.assertNotIn(
            account_home,
            section,
            "doctor resolved a lane CLI out of the account home rather than $HOME:\n"
            + section,
        )

    def test_auth_class_is_not_reported_as_an_auth_result(self):
        _, report, summary = self._run("empty")
        self.assertTrue(
            any("authentication state is not verified" in u for u in summary["unknowns"]),
            f"authentication was not reported as undetermined: {summary['unknowns']}",
        )
        self.assertIn("NOT VERIFIED for any lane", report)


def _healthy_lines(report: str) -> list[str]:
    return [line for line in report.splitlines() if line.startswith("- ✓")]


if __name__ == "__main__":
    unittest.main()
