#!/usr/bin/env python3
"""Plan D Task 2: the runtime states doctor could not see.

Doctor detected NONE of the four real failures found on 2026-08-16. This suite
covers the ones whose absence was structural rather than accidental:

  * a watcher fleet dead for EIGHT DAYS behind a session that was present the
    whole time -- doctor counted SESSIONS (`tmux list-sessions | wc -l`) and the
    string `list-windows` appeared zero times in its 1,390 lines.

Each test drives a real bin/doctor.sh whose view of the world is supplied
entirely by stubs on the fixture's own PATH.

SAFETY, read before touching anything here
------------------------------------------
Not one test in this file may reach the operator's live tmux session. They do
not need to: doctor prepends ``$HOME/.local/bin`` to PATH, so a `tmux` stub
placed there WINS over the real binary and doctor's every tmux call is answered
from an environment variable. No test starts a tmux server, on the default
socket or any other, and none sends a signal to any process. Earlier in this
plan's session an agent's supposedly-isolated test killed the operator's entire
live watcher fleet; the stub is what makes that impossible here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402
import doctor_fixture  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

# A tmux whose entire world is three environment variables. It never contacts a
# server, so it cannot see -- or disturb -- the operator's session.
TMUX_SCRIPTED = """#!/bin/bash
[[ "${DOCTOR_TEST_TMUX_SERVER:-0}" == "1" ]] || exit 1
case "$1" in
    ls|list-sessions) printf 'squad: 3 windows (attached)\\n' ;;
    has-session) [[ "${DOCTOR_TEST_TMUX_SESSION:-1}" == "1" ]] || exit 1 ;;
    list-windows) printf '%s' "${DOCTOR_TEST_TMUX_WINDOWS:-}" ;;
    list-panes) : ;;
    *) exit 1 ;;
esac
exit 0
"""

# What bin/launch-squad.sh actually builds, as shared/lead-windows.sh names it.
HEALTHY_WINDOWS = "chrono\nzsh\nwatchers/status\n"

# A ps whose entire process table is DOCTOR_TEST_POLLER_PIDS. It answers the
# three shapes doctor asks for -- the `-o pid= -p $$` liveness canary, the
# `-eo pid=,comm=` candidate table, and the `-o args= -p PID` identity read --
# and reports an empty table for every other format, so no test can observe or
# report on the host's real processes.
PS_SCRIPTED = """#!/bin/bash
fmt=""
want=""
prev=""
for argument in "$@"; do
    case "$prev" in
        -o|-eo) fmt="$argument" ;;
        -p) want="$argument" ;;
    esac
    prev="$argument"
done
if [[ -n "$want" ]]; then
    if [[ "$fmt" == "args=" ]]; then
        for pid in ${DOCTOR_TEST_POLLER_PIDS:-}; do
            if [[ "$pid" == "$want" ]]; then
                printf 'bash %s\\n' "${DOCTOR_TEST_POLLER_SCRIPT:-}"
                exit 0
            fi
        done
        exit 1
    fi
    printf '%s\\n' "$want"
    exit 0
fi
if [[ "$fmt" == "pid=,comm=" ]]; then
    for pid in ${DOCTOR_TEST_POLLER_PIDS:-}; do
        printf '%s /bin/bash\\n' "$pid"
    done
fi
exit 0
"""

# ps is installed but answers nothing, including its own liveness canary --
# the `/bin/ps: Operation not permitted` shape that made a DENIED check look
# healthier than a working one.
PS_DENIED = """#!/bin/bash
printf '/bin/ps: Operation not permitted\\n' >&2
exit 1
"""


class DoctorFixtureRunner(unittest.TestCase):
    """Shared throwaway-tree runner. Subclasses add the state under test."""

    def run_doctor(self, *, env: dict[str, str] | None = None, setup=None):
        with tempfile.TemporaryDirectory(prefix="doctor-runtime-liveness-") as temp:
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
            doctor_fixture.write_stub(local_bin, "tmux", TMUX_SCRIPTED)

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
            if setup is not None:
                setup(root, local_bin, environment)
            environment.update(env or {})

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
            return result, summary, reports[0].read_text(encoding="utf-8")


class DoctorTmuxWindowCompositionTest(DoctorFixtureRunner):
    """A present session is not a working session.

    THE check that would have caught eight days of dead detection: the fleet
    lived in a window, doctor counted sessions, and the count never moved.
    """

    def test_expected_windows_present_is_healthy(self):
        """Positive control -- without it, an always-failing check would pass."""
        result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_WINDOWS": HEALTHY_WINDOWS,
            }
        )
        self.assertEqual(summary["issues"], [], result.stdout)
        self.assertIn("exactly one 'chrono' window", report)
        self.assertIn("exactly one 'watchers/status' window", report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_watchers_window_is_a_blocking_issue(self):
        """The 2026-08-16 state: session up, detection dead for eight days."""
        result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_WINDOWS": "chrono\nzsh\n",
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "watchers/status" in issue and "MISSING" in issue
                for issue in summary["issues"]
            ),
            summary["issues"],
        )
        # The session count must not be what rescues the verdict.
        self.assertIn("tmux running", " ".join(summary["warnings"]) + _report)

    def test_missing_chrono_window_is_a_blocking_issue(self):
        result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_WINDOWS": "zsh\nwatchers/status\n",
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any("'chrono'" in issue and "MISSING" in issue for issue in summary["issues"]),
            summary["issues"],
        )

    def test_duplicate_window_is_a_blocking_issue(self):
        """Two launches converging on one session is a singleton violation."""
        result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_WINDOWS": "chrono\nchrono\nwatchers/status\n",
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "'chrono' appears 2 times" in issue for issue in summary["issues"]
            ),
            summary["issues"],
        )

    def test_no_session_is_loud_and_never_a_pass(self):
        """The launcher runs this gate BEFORE it creates the session.

        So "not running" must stay non-blocking -- and must still refuse to
        read as a pass, because nobody looked at the composition.
        """
        result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_SESSION": "0",
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "window composition was NOT checked" in entry
                for entry in summary["absent_inputs"]
            ),
            summary["absent_inputs"],
        )
        self.assertTrue(
            any(
                "window composition was NOT checked" in entry
                for entry in summary["unknowns"]
            ),
            "an unchecked composition was not counted as could-not-determine",
        )

    def test_empty_window_listing_is_gate_blocking_unknown(self):
        """Fail closed: a session that answers nothing is not a clean session."""
        result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_TMUX_SERVER": "1",
                "DOCTOR_TEST_TMUX_WINDOWS": "",
            }
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "window composition could not be listed" in entry
                for entry in summary["gate_unknowns"]
            ),
            summary["gate_unknowns"],
        )
        self.assertEqual(summary["issues"], [])

    def test_expected_window_names_come_from_the_launcher_helper(self):
        """One home for the names: doctor must ask, never restate.

        A doctor carrying its own "watchers/status" literal would keep passing
        after the launcher renamed the window, which is the same class of defect
        as the dependency list it just stopped copying.
        """
        doctor = (ROOT / "bin" / "doctor.sh").read_text(encoding="utf-8")
        self.assertIn("shared/lead-windows.sh", doctor)
        self.assertIn('"$(lead_window_name watchers)"', doctor)
        self.assertIn('"$(runtime_window_name chrono)"', doctor)
        self.assertNotIn('"watchers/status"', doctor)


class DoctorStatusPollerSingletonTest(DoctorFixtureRunner):
    """Exactly one status poller, counted without ever matching argv text.

    "Duplicate coordinators" was one of the four 2026-08-16 failures and doctor
    had no singleton detection at all. The counting MECHANISM is the whole
    subject here: a `pgrep -c` would count a specialist's 41KB compiled prompt
    that merely mentions this repository's filenames, which is how the
    operator's live watcher fleet was killed.

    SAFETY: every case answers doctor's ps calls from a stub and points
    VIBESQUAD_STATUS_DIR at the fixture, so the real /tmp/vs-lane-status.pid is
    never read, written, or relied on, and no signal is ever sent.
    """

    def poller_env(self, root: Path, status_dir: Path, pids: str) -> dict[str, str]:
        return {
            "DOCTOR_TEST_POLLER_PIDS": pids,
            "DOCTOR_TEST_POLLER_SCRIPT": str(root / "bin" / "vs-lane-status.sh"),
            "VIBESQUAD_STATUS_DIR": str(status_dir),
        }

    def run_with_pollers(self, *, pids: str, pidfile: str | None):
        state: dict[str, object] = {}

        def setup(root: Path, local_bin: Path, environment: dict[str, str]) -> None:
            doctor_fixture.write_stub(local_bin, "ps", PS_SCRIPTED)
            status_dir = Path(environment["TMPDIR"]) / "status"
            status_dir.mkdir(parents=True, exist_ok=True)
            if pidfile is not None:
                (status_dir / "vs-lane-status.pid").write_text(
                    pidfile + "\n", encoding="utf-8"
                )
            environment.update(self.poller_env(root, status_dir, pids))
            state["status_dir"] = status_dir

        return self.run_doctor(setup=setup)

    def test_exactly_one_tracked_poller_is_healthy(self):
        """Positive control: the state a working launch leaves behind."""
        result, summary, report = self.run_doctor(
            setup=lambda root, local_bin, env: (
                doctor_fixture.write_stub(local_bin, "ps", PS_SCRIPTED),
                (Path(env["TMPDIR"]) / "status").mkdir(parents=True, exist_ok=True),
                (Path(env["TMPDIR"]) / "status" / "vs-lane-status.pid").write_text(
                    "4242\n", encoding="utf-8"
                ),
                env.update(
                    self.poller_env(root, Path(env["TMPDIR"]) / "status", "4242")
                ),
            )
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("One live vs-lane-status.sh poller", report)
        self.assertEqual(
            [w for w in summary["warnings"] if "poller" in w],
            [],
            summary["warnings"],
        )

    def test_two_pollers_is_a_singleton_violation(self):
        """The duplicate case: `squad stop` reaps one and orphans the rest."""
        result, summary, _report = self.run_with_pollers(pids="4242 9191", pidfile="4242")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "2 status pollers running" in warning and "expected exactly 1" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        self.assertIn("9191", " ".join(summary["warnings"]))

    def test_dead_poller_behind_a_pidfile_is_reported(self):
        """A pidfile is not a heartbeat: the status bar freezes, silently."""
        _result, summary, _report = self.run_with_pollers(pids="", pidfile="4242")
        self.assertTrue(
            any(
                "status poller is dead" in warning and "4242" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_untracked_poller_is_reported_even_when_the_count_is_right(self):
        """The live-but-unnamed poller Plan B Task 12 found on this very host."""
        _result, summary, _report = self.run_with_pollers(pids="4242", pidfile="75269")
        self.assertTrue(
            any(
                "untracked" in warning and "4242" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_never_launched_installation_is_absent_input_not_a_warning(self):
        """A fresh clone has no poller and no pidfile. That is not a fault."""
        result, summary, _report = self.run_with_pollers(pids="", pidfile=None)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "none was ever recorded" in entry
                for entry in summary["absent_inputs"]
            ),
            summary["absent_inputs"],
        )

    def test_denied_ps_reports_unknown_never_a_count(self):
        """Fail closed: an unreadable process table is not zero pollers."""
        _result, summary, _report = self.run_doctor(
            setup=lambda root, local_bin, env: (
                doctor_fixture.write_stub(local_bin, "ps", PS_DENIED),
                env.update({"VIBESQUAD_STATUS_DIR": str(Path(env["TMPDIR"]) / "status")}),
            )
        )
        self.assertTrue(
            any(
                "status poller count could not be established" in entry
                for entry in summary["unknowns"]
            ),
            summary["unknowns"],
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "pollers running" in w], []
        )

    def test_the_count_never_matches_argv_text(self):
        """The mechanism, pinned: no pgrep, no substring scan, one home.

        An earlier draft of this task proposed `pgrep -c`. This is the assertion
        that would have caught it before it reached the operator's machine.
        """
        doctor = (ROOT / "bin" / "doctor.sh").read_text(encoding="utf-8")
        # Comment lines are stripped, not searched: the prohibition is on what
        # doctor RUNS, and the comment explaining why it does not run pgrep is
        # the part worth keeping.
        executable_lines = "\n".join(
            line
            for line in doctor.splitlines()
            if not line.lstrip().startswith("#")
        )
        for forbidden in ("pgrep", "ps -ef", "-o args= -A"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, executable_lines)
        # It asks the one function that owns the identity question...
        self.assertIn("find_live_vs_lane_status_pollers", doctor)
        identity = (ROOT / "shared" / "process-identity.sh").read_text(encoding="utf-8")
        self.assertIn("find_live_vs_lane_status_pollers()", identity)
        # ...and the launcher no longer carries a second copy of it (its
        # comment saying where the function went is not a second copy).
        launcher = "\n".join(
            line
            for line in (ROOT / "bin" / "launch-squad.sh")
            .read_text(encoding="utf-8")
            .splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("find_live_vs_lane_status_pollers()", launcher)
        self.assertIn("find_live_vs_lane_status_pollers", launcher)


class DoctorStatusFileFreshnessTest(DoctorFixtureRunner):
    """Existence cannot tell a live poller from a seven-day-old corpse.

    Both leave byte-identical /tmp/vs-*.status files, and the tmux status bar
    renders the dead one exactly as confidently as the live one. `/tmp/vs-`
    appeared zero times in doctor before this check.
    """

    def status_setup(self, *, ages: dict[str, int], pollers: str = ""):
        def setup(root: Path, local_bin: Path, environment: dict[str, str]) -> None:
            doctor_fixture.write_stub(local_bin, "ps", PS_SCRIPTED)
            status_dir = Path(environment["TMPDIR"]) / "status"
            status_dir.mkdir(parents=True, exist_ok=True)
            now = time.time()
            for name, age in ages.items():
                target = status_dir / name
                target.write_text("idle\n", encoding="utf-8")
                os.utime(target, (now - age, now - age))
            environment.update(
                {
                    "VIBESQUAD_STATUS_DIR": str(status_dir),
                    "DOCTOR_TEST_POLLER_PIDS": pollers,
                    "DOCTOR_TEST_POLLER_SCRIPT": str(
                        root / "bin" / "vs-lane-status.sh"
                    ),
                }
            )

        return setup

    def test_fresh_status_files_are_healthy(self):
        """Positive control -- a check that always warned would pass without it."""
        result, summary, report = self.run_doctor(
            setup=self.status_setup(
                ages={"vs-daemon.status": 1, "vs-lane-chrono.status": 2},
                pollers="4242",
            )
        )
        self.assertIn("vs-*.status file was written within 10s", report)
        self.assertEqual(
            [w for w in summary["warnings"] if "stale" in w], [], summary["warnings"]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_files_with_no_live_writer_are_reported(self):
        """The 2026-08-16 state: the status bar rendering a dead poller's values."""
        _result, summary, _report = self.run_doctor(
            setup=self.status_setup(
                ages={"vs-daemon.status": 604800, "vs-swarm.status": 1},
            )
        )
        self.assertTrue(
            any(
                "stale status file" in warning and "no live writer" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        # The age has to be in the report; "stale" without a number is not
        # actionable, and a week and eleven seconds are different findings.
        # Matched loosely on purpose: the file ages by a second or two between
        # os.utime and doctor's date +%s, and pinning the exact integer would
        # make this test fail for a reason that has nothing to do with the
        # behaviour under test.
        aged = re.search(r"oldest (\d+)s", " ".join(summary["warnings"]))
        self.assertIsNotNone(aged, summary["warnings"])
        self.assertGreaterEqual(int(aged.group(1)), 604800)

    def test_live_poller_with_stale_output_is_reported_as_wedged(self):
        """The worst state: every PID check says running, the bar is frozen."""
        _result, summary, _report = self.run_doctor(
            setup=self.status_setup(
                ages={"vs-daemon.status": 900}, pollers="4242"
            )
        )
        self.assertTrue(
            any(
                "alive but its output is stale" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_no_status_files_is_absent_input(self):
        _result, summary, _report = self.run_doctor(setup=self.status_setup(ages={}))
        self.assertTrue(
            any(
                "no status files exist yet" in entry
                for entry in summary["absent_inputs"]
            ),
            summary["absent_inputs"],
        )

    def test_undateable_status_file_is_gate_blocking_unknown(self):
        """Fail closed: a file whose age cannot be read is not a fresh file."""
        stat_denied = "#!/bin/bash\nexit 1\n"

        def setup(root: Path, local_bin: Path, environment: dict[str, str]) -> None:
            self.status_setup(ages={"vs-daemon.status": 1})(
                root, local_bin, environment
            )
            doctor_fixture.write_stub(local_bin, "stat", stat_denied)

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "status file age could not be read" in entry
                for entry in summary["gate_unknowns"]
            ),
            summary["gate_unknowns"],
        )

    def test_freshness_bound_matches_the_launcher(self):
        """One fact, two files, a validator (CLAUDE.md rule 10).

        The launcher's copy lives inside vs_lane_status_poller_alive(), which
        doctor cannot source, so the default is spelled twice. This is what
        keeps the two from drifting into disagreeing about what "wedged" means.
        """
        launcher = (ROOT / "bin" / "launch-squad.sh").read_text(encoding="utf-8")
        doctor = (ROOT / "bin" / "doctor.sh").read_text(encoding="utf-8")
        needle = 'VS_LANE_STATUS_FRESHNESS_MAX_AGE:-10'
        self.assertIn(needle, launcher)
        self.assertIn(needle, doctor)


class DoctorBrowserSummaryFreshnessTest(DoctorFixtureRunner):
    """A date-stamped file is not a current one.

    Doctor read `.reachable` out of a summary another process wrote and never
    probed port 9222, so a file written at 00:05 satisfied a 23:59 run --
    "Chrome CDP reachable" for a browser closed twenty hours earlier.

    Plan D Task 6 moved REACHABILITY to a live GET /json/version, and left this
    file as the source of per-platform tab detail, which one request cannot
    supply. The bound these tests pin therefore now governs the tab detail --
    and the claim they exist to prevent is stronger than before: the file's own
    `reachable` field can no longer become a reachability verdict at any age.
    """

    SUMMARY = json.dumps(
        {
            "reachable": True,
            "platforms_open": 3,
            "platforms_expired": [],
            "platforms_missing": [],
        }
    )

    def summary_setup(self, *, age: int):
        def setup(root: Path, local_bin: Path, environment: dict[str, str]) -> None:
            doctor_fixture.write_stub(local_bin, "ps", PS_SCRIPTED)
            environment["VIBESQUAD_STATUS_DIR"] = str(
                Path(environment["TMPDIR"]) / "status"
            )
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logs = root / "_state" / "cleanup-logs"
            logs.mkdir(parents=True, exist_ok=True)
            target = logs / f"{today}-browser-summary.json"
            target.write_text(self.SUMMARY, encoding="utf-8")
            now = time.time()
            os.utime(target, (now - age, now - age))

        return setup

    def test_fresh_summary_is_still_read(self):
        """Positive control: the bound must not disable the check outright."""
        _result, summary, report = self.run_doctor(setup=self.summary_setup(age=60))
        self.assertIn("3 session tab(s) open", report)
        self.assertEqual(
            [u for u in summary["unknowns"] if "browser tab detail is stale" in u],
            [],
        )

    def test_stale_summary_is_unknown_not_reachable(self):
        """Twenty hours later the same file is not evidence about now."""
        _result, summary, report = self.run_doctor(
            setup=self.summary_setup(age=72000)
        )
        self.assertTrue(
            any(
                "browser tab detail is stale" in entry
                for entry in summary["unknowns"]
            ),
            summary["unknowns"],
        )
        # ...and the claim it would have made is gone, not merely accompanied.
        # This summary says reachable=true; nothing in the report may repeat it.
        self.assertNotIn("3 session tab(s) open", report)
        self.assertNotIn("browser CDP reachable", " ".join(summary["warnings"]))

    def test_the_bound_is_configurable_and_enforced(self):
        """A bound nobody can move is a bound nobody can verify."""
        _result, summary, report = self.run_doctor(
            setup=self.summary_setup(age=60),
            env={"DOCTOR_BROWSER_SUMMARY_MAX_AGE": "10"},
        )
        self.assertNotIn("3 session tab(s) open", report)
        self.assertTrue(
            any(
                "browser tab detail is stale" in entry
                for entry in summary["unknowns"]
            ),
            summary["unknowns"],
        )

    def test_a_reachable_summary_never_becomes_a_reachability_verdict(self):
        """The original defect, pinned at its root rather than by its age.

        This fixture's `curl` stub answers nothing, so the live probe finds the
        port shut. The summary claims reachable=true and is one minute old --
        the most favourable case the old code had — and it still must not
        produce a reachable verdict, because it is not evidence about the port.
        """
        _result, summary, report = self.run_doctor(setup=self.summary_setup(age=60))
        self.assertNotIn("Chrome CDP reachable", report)
        self.assertTrue(
            any("CDP not reachable" in warning for warning in summary["warnings"]),
            summary["warnings"],
        )


class DoctorNotificationSpineTest(DoctorFixtureRunner):
    """A queue entry without a receipt is USUALLY correct, not a severed spine.

    The first version of this check asserted "some receipt is newer than the
    newest queue entry". On the operator's tree that was false by design and
    would have stayed false forever: registry_reconciler.emit_event() appends
    the queue unconditionally and only then decides whether to nudge, and
    note_long_running() appends without ever nudging at all -- 64 of 242 live
    entries, every one correctly receiptless. A permanently-firing finding is
    the class Plan D Task 5 exists to REMOVE.

    The rule these tests pin instead: every queue entry in the window that owed
    a delivered nudge has a receipt naming its task ref. Owed means (a) not a
    `long-running:` notice and (b) passing the reconciler's own registry gate.
    """

    REGISTERED_TASK = "coding/TASK-2026-08-17-0001-registered"
    OTHER_TASK = "coding/TASK-2026-08-17-0002-elsewhere"

    def spine_setup(
        self,
        *,
        entries=((0, "REVIEW-REQUIRED", REGISTERED_TASK),),
        receipts=((REGISTERED_TASK, "REVIEW-REQUIRED"),),
        registry_task: str | None = REGISTERED_TASK,
        canonical_elsewhere: bool = False,
        break_reconciler: bool = False,
        make_receipts_dir: bool = True,
        make_queue: bool = True,
    ):
        """``entries``: (age_hours, status, task_ref). ``receipts``: (ref, state).

        ``canonical_elsewhere`` puts the canonical registry OUTSIDE the tree
        under examination, which is the only way to exercise the registry gate:
        when the operating registry IS a canonical one -- the operator's own
        configuration -- the reconciler's predicate short-circuits to True by
        construction, so on that host the gate is a no-op and `long-running:` is
        the exclusion doing the work.
        """

        def setup(root: Path, local_bin: Path, environment: dict[str, str]) -> None:
            doctor_fixture.write_stub(local_bin, "ps", PS_SCRIPTED)
            environment["VIBESQUAD_STATUS_DIR"] = str(
                Path(environment["TMPDIR"]) / "status"
            )
            doctor_fixture.install_reconciler(ROOT, root)
            if break_reconciler:
                (root / "scripts" / "python" / "registry_reconciler.py").write_text(
                    "raise SystemExit('reconciler unavailable')\n", encoding="utf-8"
                )

            state = root / "_state"
            state.mkdir(parents=True, exist_ok=True)
            if make_queue:
                now = datetime.now(timezone.utc)
                lines = [
                    "# Chrono Queue",
                    "# timestamp | status | namespace/task-id | summary",
                    "",
                ]
                for age_hours, status, task_ref in entries:
                    stamp = (now - timedelta(hours=age_hours)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    lines.append(f"{stamp} | {status} | {task_ref} | fixture entry")
                (state / "chrono-queue.md").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )

            receipt_dir = state / "chrono-notify-receipts"
            if make_receipts_dir:
                receipt_dir.mkdir(parents=True, exist_ok=True)
                for task_ref, receipt_state in receipts:
                    doctor_fixture.write_receipt(receipt_dir, task_ref, receipt_state)

            registry = {}
            if registry_task is not None:
                registry[registry_task.rsplit("/", 1)[-1]] = {"state": "settled"}
            if canonical_elsewhere:
                canonical = Path(environment["TMPDIR"]) / "canonical"
                (canonical / "_state" / "tasks").mkdir(parents=True, exist_ok=True)
                (canonical / "_state" / "tasks" / "active.json").write_text(
                    json.dumps(registry), encoding="utf-8"
                )
                environment["CHRONO_CANONICAL_VAULT_ROOT"] = str(canonical)
            else:
                # Mirrors the operator's host, where VAULT_ROOT and the
                # canonical vault are the same tree.
                (state / "tasks").mkdir(parents=True, exist_ok=True)
                (state / "tasks" / "active.json").write_text(
                    json.dumps(registry), encoding="utf-8"
                )
                environment["CHRONO_CANONICAL_VAULT_ROOT"] = str(root)

        return setup

    # --- the regression that matters -------------------------------------

    def test_unregistered_tasks_alone_produce_no_finding(self):
        """Today's live state: queue entries the system owed no nudge for.

        The rejected formulation called this a severed spine and would have said
        so on every run, forever.
        """
        result, summary, _report = self.run_doctor(
            setup=self.spine_setup(
                entries=((0, "REVIEW-REQUIRED", self.OTHER_TASK),),
                receipts=(),
                registry_task=self.REGISTERED_TASK,
                canonical_elsewhere=True,
            )
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "spine" in w], [], summary["warnings"]
        )
        self.assertEqual(summary["issues"], [])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # ...and it says so out loud rather than passing silently.
        self.assertTrue(
            any("owed no delivery" in entry for entry in summary["absent_inputs"]),
            summary["absent_inputs"],
        )

    def test_the_registry_gate_is_load_bearing_not_incidental(self):
        """Control for the test above: same tree, task IS in that registry.

        Without this, "no finding" could come from the fixture being wrong
        rather than from the gate, and the negative control would prove nothing.
        """
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(
                entries=((0, "REVIEW-REQUIRED", self.OTHER_TASK),),
                receipts=(),
                registry_task=self.OTHER_TASK,
                canonical_elsewhere=True,
            )
        )
        self.assertTrue(
            any(
                "1 of 1 owed nudge(s) never delivered" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_long_running_notices_never_owe_a_receipt(self):
        """64 of 242 live entries. note_long_running never calls nudge_chrono."""
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(
                entries=((0, "long-running:unknown", self.REGISTERED_TASK),),
                receipts=(),
            )
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "spine" in w], [], summary["warnings"]
        )
        self.assertTrue(
            any("owed no delivery" in entry for entry in summary["absent_inputs"]),
            summary["absent_inputs"],
        )

    def test_a_delivered_state_remap_still_counts_as_delivered(self):
        """bin/outbox-watcher.sh queues `needs_review`, nudges `review-required`.

        Recomputing the receipt PATH from the queue's status would miss every
        outbox-watcher fallback entry permanently -- a false positive with the
        same shape as the one this rewrite removes. Matching on the task ref
        recorded inside the receipt is what makes the check producer-agnostic.
        """
        _result, summary, report = self.run_doctor(
            setup=self.spine_setup(
                entries=((0, "needs_review", self.REGISTERED_TASK),),
                receipts=((self.REGISTERED_TASK, "review-required"),),
            )
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "spine" in w], [], summary["warnings"]
        )
        # Asserting only the absence of a warning would pass with the whole
        # check deleted. The entry must be counted as owed AND reconciled.
        self.assertIn("1 chrono-queue entries that owed a delivered nudge", report)

    def test_entries_outside_the_window_do_not_fire(self):
        """Liveness, not history: a gap from last week has already aged out."""
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(
                entries=((72, "REVIEW-REQUIRED", self.REGISTERED_TASK),),
                receipts=(),
            )
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "spine" in w], [], summary["warnings"]
        )
        # As above: the check must have RUN and found nothing owed, not been
        # absent. This is what distinguishes windowing from not looking.
        self.assertTrue(
            any("owed no delivery" in entry for entry in summary["absent_inputs"]),
            summary["absent_inputs"],
        )

    # --- and it must still fire when a delivery really was missed ---------

    def test_owed_delivery_without_a_receipt_is_reported(self):
        """A registered task's completion that never reached the chrono pane."""
        result, summary, report = self.run_doctor(
            setup=self.spine_setup(
                entries=((0, "REVIEW-REQUIRED", self.REGISTERED_TASK),),
                receipts=(),
            )
        )
        self.assertTrue(
            any(
                "1 of 1 owed nudge(s) never delivered" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        # The entry has to be named; a bare count is not actionable.
        self.assertIn(self.REGISTERED_TASK, report)
        # Degraded-and-recoverable, not a broken install: the queue is the
        # durable record and doctor gates the launch that would repair this.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_owed_and_delivered_is_healthy(self):
        """Positive control -- without it, a check that never fires would pass."""
        _result, _summary, report = self.run_doctor(setup=self.spine_setup())
        self.assertIn("owed a delivered nudge in the last 24h has its receipt", report)

    def test_one_missing_among_several_is_still_reported(self):
        """A partial outage must not be averaged away by its healthy neighbours."""
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(
                entries=(
                    (0, "REVIEW-REQUIRED", self.REGISTERED_TASK),
                    (1, "complete", self.OTHER_TASK),
                ),
                receipts=((self.REGISTERED_TASK, "REVIEW-REQUIRED"),),
            )
        )
        self.assertTrue(
            any(
                "1 of 2 owed nudge(s) never delivered" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    # --- fail closed ------------------------------------------------------

    def test_broken_reconciler_is_gate_blocking_unknown(self):
        """The reconciler defines what is owed. Without it, nothing is known."""
        result, summary, _report = self.run_doctor(
            setup=self.spine_setup(break_reconciler=True)
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "notification spine reconciliation did not complete" in entry
                for entry in summary["gate_unknowns"]
            ),
            summary["gate_unknowns"],
        )

    def test_no_queue_is_absent_input(self):
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(make_queue=False)
        )
        self.assertTrue(
            any("no queue to reconcile" in entry for entry in summary["absent_inputs"]),
            summary["absent_inputs"],
        )

    def test_no_receipts_directory_is_absent_input(self):
        _result, summary, _report = self.run_doctor(
            setup=self.spine_setup(make_receipts_dir=False)
        )
        self.assertTrue(
            any(
                "never written a receipt" in entry
                for entry in summary["absent_inputs"]
            ),
            summary["absent_inputs"],
        )

    # --- the fixture must not be able to agree with itself ----------------

    def test_fixture_event_key_matches_the_reconcilers_own(self):
        """The receipt builder mirrors a format it does not own.

        If that mirror drifted, every test above would build receipts the check
        cannot match and the suite would fail for a reason that has nothing to
        do with doctor.
        """
        sys.path.insert(0, str(ROOT / "scripts" / "python"))
        import registry_reconciler  # noqa: E402

        for task_ref, state in (
            (self.REGISTERED_TASK, "REVIEW-REQUIRED"),
            ("a/b", "x"),
            ("ns/TASK-with|pipe", "needs_review"),
        ):
            with self.subTest(task_ref=task_ref):
                self.assertEqual(
                    doctor_fixture.notification_event_key(task_ref, state),
                    registry_reconciler.notification_event_key(task_ref, state),
                )


if __name__ == "__main__":
    unittest.main()
