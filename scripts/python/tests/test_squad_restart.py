#!/usr/bin/env python3
"""Phase 1c: `squad restart` — stop, reap, VERIFY absence, only then launch.

`squad stop && squad up` is not a restart, and the gap is not theoretical:

  - bin/launch-squad.sh's start_daemon() returns early with "✓ Daemon already
    loaded in launchd" when the label is registered from the expected plist, so
    an `up` that follows a stop which failed to boot the daemon out silently
    adopts the OLD daemon process, still running whatever code it was
    bootstrapped with.
  - bin/launch-squad.sh's vs_lane_status_poller_alive() adopts an untracked live
    poller ("Adopting untracked live status poller (PID ...) instead of spawning
    a duplicate") whenever /tmp/vs-daemon.status is fresh. bin/squad-stop.sh
    reaps the poller through ONE pidfile and deliberately refuses to scan the
    process table, so a poller it did not track survives the stop and is then
    adopted by the next up — again on old code.
  - bin/squad's `stop` branch ran `stop_daemon || exit $?`, so a daemon that
    would not boot out aborted the whole stop and left the tmux session up.

Restart therefore has to VERIFY, not assume: the session gone, the daemon gone
from launchd, and no live status poller belonging to THIS root — before it
hands off to the launcher. A stop that prints "✓ Squad closed" while a
coordinator is still alive is the exact failure this verb exists to make
impossible.

SAFETY, read before touching any test in this file
----------------------------------------------------
This host runs the operator's real squad, in a tmux session named "squad",
with a live Chrono in it and a real com.vibesquad.daemon in launchd. A prior
"isolated" test in this repo reached and killed that live session from a
predicate that looked scoped but was not.

So: this file NEVER runs bin/squad against the real repo root, NEVER lets a
real `tmux` or `launchctl` binary see one of its calls, and NEVER spawns
anything under the real VAULT_ROOT. Every behavioural test runs bin/squad with

  * VAULT_ROOT pointed at a throwaway directory holding STUB copies of
    bin/squad-stop.sh and bin/launch-squad.sh that only append to a trace file
    (shared/repo-root.sh honours a VAULT_ROOT override verbatim), and
  * PATH pointed at a throwaway directory whose `tmux` and `launchctl` are
    stubs, so the real ones are unreachable for the whole run.

The only real processes any test here kills are `sleep`-alikes it spawned
itself, named after a script inside its own temporary root.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SQUAD = REPO / "bin" / "squad"
SQUAD_STOP = REPO / "bin" / "squad-stop.sh"
# find_live_vs_lane_status_pollers() lives here, and is the ONLY sound way to
# ask "is a poller belonging to this root still alive?" -- exact-positional argv
# matching, never a substring scan of the process list. bin/launch-squad.sh and
# bin/doctor.sh already ask it; restart's reap-and-verify stage is the third
# caller, so the answer stays in one home (CLAUDE.md rule 10).
PROCESS_IDENTITY = REPO / "shared" / "process-identity.sh"

LAUNCHCTL_STUB = """#!/bin/bash
printf 'launchctl %s\\n' "$*" >> "${SQUAD_TEST_LOG}"
case "$1" in
    print)
        [[ "$(cat "${SQUAD_TEST_DAEMON_STATE}")" == "loaded" ]] && exit 0
        exit 113
        ;;
    bootout)
        if [[ "${SQUAD_TEST_BOOTOUT_REMOVES:-1}" == "1" ]]; then
            printf 'stopped' > "${SQUAD_TEST_DAEMON_STATE}"
        fi
        exit 0
        ;;
esac
exit 0
"""

TMUX_STUB = """#!/bin/bash
printf 'tmux %s\\n' "$*" >> "${SQUAD_TEST_LOG}"
case "$1" in
    has-session)
        [[ "$(cat "${SQUAD_TEST_SESSION_STATE}")" == "up" ]] && exit 0
        exit 1
        ;;
esac
exit 0
"""

SQUAD_STOP_STUB = """#!/bin/bash
printf 'squad-stop %s\\n' "$*" >> "${SQUAD_TEST_LOG}"
# The real bin/squad-stop.sh always writes this report -- truncating it before
# it does anything else, so an empty file means "nothing survived" and an ABSENT
# file means the stop never got far enough to say. The stub models both, because
# restart's verification reads it to name the coordinator and the orphans the
# stop knowingly leaves running.
if [[ "${SQUAD_TEST_STOP_WRITES_REPORT:-1}" == "1" ]]; then
    mkdir -p "$(dirname -- "${SQUAD_STOP_SURVIVOR_REPORT}")"
    printf '%s' "${SQUAD_TEST_SURVIVOR_LINES:-}" > "${SQUAD_STOP_SURVIVOR_REPORT}"
fi
if [[ "${SQUAD_TEST_STOP_CLOSES:-1}" == "1" ]]; then
    printf 'down' > "${SQUAD_TEST_SESSION_STATE}"
fi
exit "${SQUAD_TEST_STOP_RC:-0}"
"""

LAUNCH_SQUAD_STUB = """#!/bin/bash
printf 'launch-squad %s\\n' "$*" >> "${SQUAD_TEST_LOG}"
exit 0
"""

# A stand-in for bin/vs-lane-status.sh inside a throwaway root. Spawned as
# `bash <root>/bin/vs-lane-status.sh`, which is byte-for-byte the invocation
# shape pid_is_vs_lane_status_poller() matches (argv[0] basename `bash`,
# argv[1] the root's poller path, nothing else).
POLLER_STUB = "#!/bin/bash\nsleep 45\n"


def _wait_until(predicate, timeout=5.0, interval=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _write_exec(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


class _StubSquad:
    """A throwaway VAULT_ROOT plus a PATH whose tmux/launchctl are stubs."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "vault"
        self.fake_bin = tmp / "bin"
        self.log = tmp / "trace.log"
        self.daemon_state = tmp / "daemon.state"
        self.session_state = tmp / "session.state"

        self.log.write_text("", encoding="utf-8")
        self.daemon_state.write_text("loaded", encoding="utf-8")
        self.session_state.write_text("up", encoding="utf-8")

        _write_exec(self.root / "bin" / "squad-stop.sh", SQUAD_STOP_STUB)
        _write_exec(self.root / "bin" / "launch-squad.sh", LAUNCH_SQUAD_STUB)
        (self.root / "shared").mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROCESS_IDENTITY, self.root / "shared" / "process-identity.sh")

        _write_exec(self.fake_bin / "launchctl", LAUNCHCTL_STUB)
        _write_exec(self.fake_bin / "tmux", TMUX_STUB)

    def env(self, **overrides: str) -> dict:
        env = dict(os.environ)
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env['PATH']}",
                "VAULT_ROOT": str(self.root),
                # Never the real session name, even though the tmux stub already
                # makes the real server unreachable.
                "SQUAD_SESSION": "squad-restart-selftest",
                "SQUAD_TEST_LOG": str(self.log),
                "SQUAD_TEST_DAEMON_STATE": str(self.daemon_state),
                "SQUAD_TEST_SESSION_STATE": str(self.session_state),
                "SQUAD_DAEMON_VERIFY_ATTEMPTS": "1",
                "SQUAD_DAEMON_VERIFY_DELAY": "0",
                # Restart's reap waits for a TERM to land; keep the suite quick.
                "SQUAD_REAP_GRACE": "0.3",
            }
        )
        env.update(overrides)
        return env

    def run(self, *args: str, **overrides: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(SQUAD), *args],
            env=self.env(**overrides),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def trace(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def index_of(self, prefix: str) -> int:
        for i, line in enumerate(self.trace()):
            if line.startswith(prefix):
                return i
        return -1


class StubSquadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="squad-restart-test-")
        self.addCleanup(self._tmp.cleanup)
        self.squad = _StubSquad(Path(self._tmp.name))


class RestartVerbTests(StubSquadTestCase):
    """The verb exists, and does the four stages in the one order that works."""

    def test_restart_is_a_recognised_subcommand(self) -> None:
        result = self.squad.run("restart")
        self.assertNotIn("unknown subcommand", result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restart_stops_the_daemon_and_the_session_before_launching(self) -> None:
        result = self.squad.run("restart")
        self.assertEqual(result.returncode, 0, result.stderr)
        bootout = self.squad.index_of("launchctl bootout")
        stop = self.squad.index_of("squad-stop")
        launch = self.squad.index_of("launch-squad")
        self.assertGreaterEqual(bootout, 0, self.squad.trace())
        self.assertGreaterEqual(stop, 0, self.squad.trace())
        self.assertGreaterEqual(launch, 0, self.squad.trace())
        self.assertLess(bootout, stop, self.squad.trace())
        self.assertLess(stop, launch, self.squad.trace())

    def test_absence_is_verified_between_the_stop_and_the_launch(self) -> None:
        # The whole point of the verb: `launchctl bootstrap` no-ops on a loaded
        # daemon and the launcher adopts a live poller, so both must be shown
        # ABSENT before the launcher is allowed to run. A verification that ran
        # after the launch, or not at all, would prove nothing.
        self.squad.run("restart")
        trace = self.squad.trace()
        stop = self.squad.index_of("squad-stop")
        launch = self.squad.index_of("launch-squad")
        checks = [
            i
            for i, line in enumerate(trace)
            if line.startswith("tmux has-session") and stop < i < launch
        ]
        self.assertTrue(
            checks,
            f"restart must re-check the session between the stop and the launch: {trace}",
        )
        daemon_checks = [
            i
            for i, line in enumerate(trace)
            if line.startswith("launchctl print") and stop < i < launch
        ]
        self.assertTrue(
            daemon_checks,
            f"restart must re-check the daemon between the stop and the launch: {trace}",
        )

    def test_a_surviving_session_blocks_the_launch(self) -> None:
        result = self.squad.run("restart", SQUAD_TEST_STOP_CLOSES="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.squad.index_of("launch-squad"), -1, self.squad.trace())
        self.assertIn("squad-restart-selftest", result.stderr)

    def test_a_daemon_that_will_not_boot_out_blocks_the_launch(self) -> None:
        result = self.squad.run("restart", SQUAD_TEST_BOOTOUT_REMOVES="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.squad.index_of("launch-squad"), -1, self.squad.trace())
        self.assertIn("com.vibesquad.daemon", result.stderr)

    def test_a_daemon_failure_does_not_abort_the_session_stop(self) -> None:
        # A daemon that refuses to boot out is a REPORT, not a reason to leave
        # the tmux session (and everything under it) running. The stop still
        # runs; the LAUNCH is what the failure blocks, at verification.
        self.squad.run("restart", SQUAD_TEST_BOOTOUT_REMOVES="0")
        self.assertGreaterEqual(self.squad.index_of("squad-stop"), 0, self.squad.trace())

    def test_a_failing_stop_script_still_blocks_the_launch(self) -> None:
        # squad-stop.sh exits 1 when the session survives its kill. Restart must
        # not launch over that, and must not swallow the status either.
        result = self.squad.run(
            "restart", SQUAD_TEST_STOP_RC="1", SQUAD_TEST_STOP_CLOSES="0"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.squad.index_of("launch-squad"), -1, self.squad.trace())

    def test_arguments_are_forwarded_to_the_launcher(self) -> None:
        self.squad.run("restart", "--safe")
        self.assertIn("launch-squad --safe", self.squad.trace())

    def test_restart_is_documented_in_the_help_window_and_the_usage_line(self) -> None:
        source = SQUAD.read_text(encoding="utf-8")
        window = re.search(r"sed -n '(\d+),(\d+)p' \"\$0\"", source)
        self.assertIsNotNone(window, "the help branch no longer has a sed window")
        first, last = int(window.group(1)), int(window.group(2))
        header = source.splitlines()[first - 1 : last]
        self.assertTrue(
            any("restart" in line for line in header),
            "the help window must cover a `squad restart` line; extending the "
            "header without extending the window truncates help silently",
        )
        usage = [line for line in source.splitlines() if line.strip().startswith("echo \"usage:")]
        self.assertTrue(usage, "usage line not found")
        self.assertIn("restart", usage[0])


class PollerReapScopeTests(StubSquadTestCase):
    """Restart reaps THIS root's untracked pollers, and nothing else's."""

    def _spawn_poller(self, root: Path) -> subprocess.Popen:
        script = _write_exec(root / "bin" / "vs-lane-status.sh", POLLER_STUB)
        proc = subprocess.Popen(
            ["bash", str(script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def _cleanup() -> None:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

        self.addCleanup(_cleanup)
        return proc

    def test_an_untracked_poller_for_this_root_is_reaped(self) -> None:
        # bin/squad-stop.sh reaps the poller through one pidfile only. A poller
        # it never tracked survives the stop, keeps /tmp/vs-daemon.status fresh,
        # and the next launch ADOPTS it instead of spawning one on new code.
        proc = self._spawn_poller(self.squad.root)
        self.assertTrue(_pid_alive(proc.pid))

        result = self.squad.run("restart")

        self.assertTrue(
            _wait_until(lambda: proc.poll() is not None),
            "restart must reap a live status poller belonging to this root",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(self.squad.index_of("launch-squad"), 0)

    def test_a_poller_belonging_to_a_different_root_is_left_alone(self) -> None:
        # The measured case: this host carries pollers whose argv roots are
        # /tmp/vs/d-<id>/launch-single-coord-<id>/vault/... -- throwaway
        # worktrees, i.e. a different VAULT_ROOT. Reaping by script NAME would
        # take them (and anything else that merely quotes the path); the
        # exact-positional, root-scoped predicate must not.
        other_root = Path(self._tmp.name) / "other-vault"
        proc = self._spawn_poller(other_root)
        self.assertTrue(_pid_alive(proc.pid))

        result = self.squad.run("restart")

        self.assertEqual(result.returncode, 0, result.stderr)
        time.sleep(0.5)
        self.assertIsNone(
            proc.poll(),
            "restart reaped a poller belonging to a different VAULT_ROOT",
        )


class StopSweepScopeTests(unittest.TestCase):
    """bin/squad-stop.sh's Phase 5 kills by process GROUP. A group can contain
    processes that are not in the pre-kill descendant snapshot, and those are
    exactly the bystanders a stop must not take with it."""

    # Same two functions ReapSurvivorGroupTests extracts in
    # test_squad_stop_reaping.py, and for the same reason: driving the reaper
    # without pgid_is_protected_chrome() defined would not fail loudly -- an
    # undefined function returns 127 and `if` reads that as false. The scope
    # check is INLINE in reap_survivor_group() precisely so it cannot be left
    # out of an extraction the way a third function could be.
    FUNCTIONS = ("pgid_is_protected_chrome", "reap_survivor_group")

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        chunks = []
        for name in cls.FUNCTIONS:
            match = re.search(rf"\n{name}\(\) \{{.*?\n\}}\n", text, re.DOTALL)
            if not match:
                raise RuntimeError(
                    f"could not locate {name}() in bin/squad-stop.sh -- extraction "
                    "regex is stale, update it to match the current source"
                )
            chunks.append(match.group(0))
        cls.function_src = "\n".join(chunks)

    def _run(self, scope: str, body: str) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'PROTECTED_CHROME_PGIDS=""\nPROTECTED_CHROME_SCAN_OK="1"\n'
            f'SQUAD_STOP_SCOPE_PIDS="{scope}"\n'
            + self.function_src
            + "\n"
            + body
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=20
        )

    @staticmethod
    def _leader_with_group_child(pid_file: Path) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", "-c", f'sleep 45 & echo $! > "{pid_file}"; wait'],
            start_new_session=True,
        )

    def _read_child_pid(self, pid_file: Path) -> int:
        parsed = {}

        def ready() -> bool:
            try:
                raw = pid_file.read_text(encoding="utf-8")
            except OSError:
                return False
            if not raw.endswith("\n") or not raw.strip().isdigit():
                return False
            parsed["pid"] = int(raw.strip())
            return True

        self.assertTrue(_wait_until(ready), "child never wrote a parseable PID")
        return parsed["pid"]

    def test_a_group_member_outside_the_snapshot_stops_the_group_kill(self) -> None:
        work = Path(tempfile.mkdtemp())
        pid_file = work / "child.pid"
        proc = self._leader_with_group_child(pid_file)
        try:
            child = self._read_child_pid(pid_file)
            # Only the leader is in the snapshot. The child shares its group but
            # was never identified as ours, so a group kill would be collateral.
            self._run(str(proc.pid), f"reap_survivor_group {proc.pid} KILL")
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            time.sleep(0.4)
            self.assertTrue(
                _pid_alive(child),
                "a process group holding a non-snapshot member must not be "
                "group-killed; narrow to the snapshot PID instead",
            )
        finally:
            for pid in (proc.pid, self._read_child_pid(pid_file)):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_a_group_wholly_inside_the_snapshot_is_still_group_killed(self) -> None:
        # The narrowing must not cost the property Phase 5 exists for: a
        # specialist's own subprocess tree still goes with it.
        work = Path(tempfile.mkdtemp())
        pid_file = work / "child.pid"
        proc = self._leader_with_group_child(pid_file)
        try:
            child = self._read_child_pid(pid_file)
            self._run(f"{proc.pid} {child}", f"reap_survivor_group {proc.pid} TERM")
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            self.assertTrue(
                _wait_until(lambda: not _pid_alive(child)),
                "a group entirely within the snapshot must still be group-killed",
            )
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    # A census that could not run has shown nothing. `ps -axo` failing inside
    # the process substitution is invisible to the `while` loop -- the loop body
    # simply never runs -- so an initially-approved group stays approved and the
    # group kill proceeds over members the census never got to look at. The
    # failure is injected on the `-axo` table dump ALONE; the single-PID `ps -o
    # pgid= -p` lookup still answers, which is what makes this a census failure
    # rather than "ps is gone".
    PS_CENSUS_FAILS = (
        'ps() {\n'
        '    case " $* " in\n'
        '        *" -axo "*) return 1 ;;\n'
        '        *) command ps "$@" ;;\n'
        '    esac\n'
        '}\n'
    )

    def test_a_census_that_cannot_run_must_not_approve_the_group(self) -> None:
        work = Path(tempfile.mkdtemp())
        pid_file = work / "child.pid"
        proc = self._leader_with_group_child(pid_file)
        try:
            child = self._read_child_pid(pid_file)
            self._run(
                str(proc.pid),
                self.PS_CENSUS_FAILS + f"reap_survivor_group {proc.pid} KILL",
            )
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            time.sleep(0.4)
            self.assertTrue(
                _pid_alive(child),
                "an unverifiable group census must count as NOT in scope: the "
                "group kill went ahead on a census that never ran, which is the "
                "fail-open the narrowing exists to remove",
            )
        finally:
            try:
                os.kill(self._read_child_pid(pid_file), 9)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_the_production_sweep_declares_its_scope(self) -> None:
        # An undeclared scope leaves reap_survivor_group() unconstrained, which
        # is the pre-existing behaviour and is correct for the direct drivers
        # above -- but it must be unreachable from the one caller that actually
        # reaps. This assertion is what makes that true.
        text = SQUAD_STOP.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"SQUAD_STOP_SCOPE_PIDS=\"\$\{descendant_pids\}\"",
            "Phase 5 must declare the descendant snapshot as the reap scope",
        )


class LateChildSweepTests(unittest.TestCase):
    """The Phase 5 sweep re-walks the tree it is about to kill.

    The pre-kill snapshot is a photograph. A leader inside it can fork a worker
    AFTER the shutter, and that worker is ours by descent even though no
    snapshot names it -- but it puts its own parent's process group out of
    scope, so both passes narrow to a bare-PID kill of the leader and the worker
    is left an orphan for the next launch to adopt. The sweep therefore
    re-snapshots from the still-live survivors before each pass.

    What it must NOT do is widen to anything that merely SHARES a group: group
    membership is inherited at fork and outlives the parent, so a group holding
    one of ours can also hold a process that was never under our panes -- the
    operator's own long-running audit being the case that actually bit.
    """

    FUNCTIONS = (
        "pid_start_time",
        "pid_identity_still_matches",
        "pgid_is_protected_chrome",
        "descendant_pids_of",
        "reap_survivor_group",
        "reap_descendant_survivors",
    )

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        chunks = []
        for name in cls.FUNCTIONS:
            match = re.search(rf"\n{name}\(\) \{{.*?\n\}}\n", text, re.DOTALL)
            if not match:
                raise RuntimeError(
                    f"could not locate {name}() in bin/squad-stop.sh -- extraction "
                    "regex is stale, update it to match the current source"
                )
            chunks.append(match.group(0))
        cls.function_src = "\n".join(chunks)

    def _run(self, scope: str, body: str) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'PROTECTED_CHROME_PGIDS=""\nPROTECTED_CHROME_SCAN_OK="1"\n'
            f'SQUAD_STOP_SCOPE_PIDS="{scope}"\n'
            'SQUAD_STOP_REAP_GRACE="0.3"\n'
            'SQUAD_STOP_SURVIVOR_REPORT="/dev/null"\n'
            "declare -a descendant_start_time=()\n"
            "record_survivor() { :; }\n"
            + self.function_src
            + "\n"
            + body
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=30
        )

    @staticmethod
    def _read_pid_file(case: unittest.TestCase, pid_file: Path) -> int:
        parsed = {}

        def ready() -> bool:
            try:
                raw = pid_file.read_text(encoding="utf-8")
            except OSError:
                return False
            if not raw.endswith("\n") or not raw.strip().isdigit():
                return False
            parsed["pid"] = int(raw.strip())
            return True

        case.assertTrue(_wait_until(ready), "pid file never became parseable")
        return parsed["pid"]

    @staticmethod
    def _ppid_of(pid: int) -> int:
        out = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        return int(out) if out.isdigit() else -1

    def test_a_child_forked_after_the_snapshot_is_still_reaped(self) -> None:
        # The scope names ONLY the leader -- exactly what a snapshot taken
        # before the fork would have held. The child exists by kill time and
        # descends from the leader, so the sweep must find it rather than
        # narrowing around it and stranding it.
        work = Path(tempfile.mkdtemp())
        pid_file = work / "child.pid"
        proc = subprocess.Popen(
            ["bash", "-c", f'sleep 45 & echo $! > "{pid_file}"; wait'],
            start_new_session=True,
        )
        try:
            child = self._read_pid_file(self, pid_file)
            self.assertTrue(_pid_alive(child))
            self._run(str(proc.pid), f'reap_descendant_survivors "{proc.pid}"')
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            self.assertTrue(
                _wait_until(lambda: not _pid_alive(child)),
                "a worker forked after the snapshot was left running as an "
                "orphan: the sweep never re-walked the tree it was killing",
            )
        finally:
            try:
                os.kill(self._read_pid_file(self, pid_file), 9)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_a_group_sharer_that_is_not_a_descendant_is_left_alone(self) -> None:
        # The bystander shape, built for real: an intermediate shell forks a
        # process into the leader's group and then exits, so the survivor is
        # reparented away and is NOT reachable by any walk from the leader while
        # still sharing its process group. That is the operator's-own-process
        # case, and the sweep must not adopt it.
        work = Path(tempfile.mkdtemp())
        pid_file = work / "bystander.pid"
        proc = subprocess.Popen(
            ["bash", "-c", f'bash -c \'sleep 45 & echo $! > "{pid_file}"\'; exec sleep 45'],
            start_new_session=True,
        )
        try:
            bystander = self._read_pid_file(self, pid_file)
            self.assertTrue(
                _wait_until(lambda: self._ppid_of(bystander) == 1),
                "test setup: the intermediate shell must exit so the bystander "
                "is no longer a descendant of the leader",
            )
            self.assertEqual(
                os.getpgid(bystander),
                os.getpgid(proc.pid),
                "test setup: the bystander must share the leader's process group",
            )
            self._run(str(proc.pid), f'reap_descendant_survivors "{proc.pid}"')
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            time.sleep(0.4)
            self.assertTrue(
                _pid_alive(bystander),
                "the sweep group-killed a process that only SHARED the group -- "
                "the collateral kill the scope narrowing exists to prevent",
            )
        finally:
            try:
                os.kill(self._read_pid_file(self, pid_file), 9)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


class UnreapableSurvivorsAreNamedTests(unittest.TestCase):
    """A stop that reaps NOTHING must not read as a stop that left nothing.

    When the persistent-CDP-Chrome scan fails, pgid_is_protected_chrome()
    protects every group, so survivor SELECTION drops every descendant before
    the sweep ever runs. The stop says so, PID by PID, and tells the operator to
    reap by hand -- and then `squad restart` verified the session, the daemon and
    the pollers, found all three absent, and relaunched over the entire still-live
    squad. Refusing to kill is correct; staying silent about it to the one caller
    that gates a relaunch is not.
    """

    FUNCTIONS = (
        "pid_start_time",
        "pid_identity_still_matches",
        "pgid_is_protected_chrome",
        "record_survivor",
        "select_descendant_survivors",
    )

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        chunks = []
        for name in cls.FUNCTIONS:
            match = re.search(rf"\n{name}\(\) \{{.*?\n\}}\n", text, re.DOTALL)
            if not match:
                raise RuntimeError(
                    f"could not locate {name}() in bin/squad-stop.sh -- extraction "
                    "regex is stale, update it to match the current source"
                )
            chunks.append(match.group(0))
        cls.function_src = "\n".join(chunks)

    def _select(self, pid: int, scan_ok: str, report: Path) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'PROTECTED_CHROME_PGIDS=""\n'
            f'PROTECTED_CHROME_SCAN_OK="{scan_ok}"\n'
            f'SQUAD_STOP_SURVIVOR_REPORT="{report}"\n'
            "declare -a descendant_start_time=()\n"
            + self.function_src
            + "\n"
            f'descendant_start_time[{pid}]="$(pid_start_time {pid})"\n'
            f'printf "SURVIVORS:[%s]\\n" "$(select_descendant_survivors "{pid}")"\n'
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=20
        )

    def test_a_failed_chrome_scan_names_every_descendant_it_would_not_reap(self) -> None:
        work = Path(tempfile.mkdtemp())
        report = work / "survivors.txt"
        proc = subprocess.Popen(["sleep", "45"], start_new_session=True)
        try:
            result = self._select(proc.pid, "0", report)
            self.assertIn("SURVIVORS:[]", result.stdout, result.stderr)
            self.assertTrue(
                report.exists(), "a descendant the stop refused to reap was never recorded"
            )
            self.assertIn(
                str(proc.pid),
                report.read_text(encoding="utf-8"),
                "the stop declined to reap this PID and told the operator so, but "
                "left the one caller that gates a relaunch unable to name it",
            )
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_a_successful_scan_still_selects_the_survivor_and_records_nothing(self) -> None:
        # The inverted control: the recording must not become a blanket "every
        # descendant is a survivor", which would block every relaunch.
        work = Path(tempfile.mkdtemp())
        report = work / "survivors.txt"
        proc = subprocess.Popen(["sleep", "45"], start_new_session=True)
        try:
            result = self._select(proc.pid, "1", report)
            self.assertIn(f"SURVIVORS:[ {proc.pid}]", result.stdout, result.stderr)
            self.assertEqual(
                report.read_text(encoding="utf-8") if report.exists() else "",
                "",
                "a descendant that IS being reaped must not be reported as a survivor",
            )
        finally:
            proc.kill()
            proc.wait(timeout=5)


class SurvivorReportVerificationTests(StubSquadTestCase):
    """`squad restart` must not call a state clean that the stop itself named.

    bin/squad-stop.sh deliberately does not kill an identity-matched
    `background-job` coordinator, and a late child can outlive both its passes.
    Verification that looks only at tmux, launchd and pollers reports a clean
    squad and launches a SECOND coordinator over the survivor. The stop names
    what it left; the verification re-checks those names.
    """

    @staticmethod
    def _command_of(pid: int) -> str:
        return " ".join(
            subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
            ).stdout.split()
        )

    def test_a_live_survivor_named_by_the_stop_blocks_the_launch(self) -> None:
        proc = subprocess.Popen(["sleep", "45"])
        try:
            line = f"survivor {proc.pid} background-job-coordinator {self._command_of(proc.pid)}\n"
            result = self.squad.run("restart", SQUAD_TEST_SURVIVOR_LINES=line)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(
                self.squad.index_of("launch-squad"), -1, self.squad.trace()
            )
            self.assertIn(str(proc.pid), result.stderr)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_a_survivor_that_has_since_exited_does_not_block_the_launch(self) -> None:
        proc = subprocess.Popen(["sleep", "45"])
        dead_pid = proc.pid
        dead_cmd = self._command_of(dead_pid)
        proc.kill()
        proc.wait(timeout=5)
        line = f"survivor {dead_pid} descendant {dead_cmd}\n"
        result = self.squad.run("restart", SQUAD_TEST_SURVIVOR_LINES=line)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(
            self.squad.index_of("launch-squad"), 0, self.squad.trace()
        )

    def test_the_real_writer_and_this_reader_agree(self) -> None:
        # Every other test in this class drives the STUB stop, which only models
        # the report format. This one extracts bin/squad-stop.sh's OWN
        # record_survivor() and runs it against a real process, then hands the
        # file it produced to the real reader -- so the two ends cannot drift
        # apart on spacing, field order, or the empty-command sentinel
        # (CLAUDE.md rule 10). The command deliberately contains spaces, which
        # is where a field-counting reader breaks.
        src = SQUAD_STOP.read_text(encoding="utf-8")
        match = re.search(r"\nrecord_survivor\(\) \{.*?\n\}\n", src, re.DOTALL)
        self.assertIsNotNone(
            match, "record_survivor() is no longer extractable from bin/squad-stop.sh"
        )
        report = Path(self._tmp.name) / "written-by-the-real-writer.txt"
        proc = subprocess.Popen(["bash", "-c", "exec sleep 45"])
        try:
            write = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -uo pipefail\n"
                    f'SQUAD_STOP_SURVIVOR_REPORT="{report}"\n'
                    f"{match.group(0)}\n"
                    f"record_survivor {proc.pid} background-job-coordinator\n",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(write.returncode, 0, write.stderr)
            self.assertIn(str(proc.pid), report.read_text(encoding="utf-8"))

            result = self.squad.run(
                "restart",
                SQUAD_TEST_STOP_WRITES_REPORT="0",
                SQUAD_STOP_SURVIVOR_REPORT=str(report),
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(
                self.squad.index_of("launch-squad"), -1, self.squad.trace()
            )
            self.assertIn(str(proc.pid), result.stderr)
            self.assertIn("background-job-coordinator", result.stderr)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_a_stop_that_wrote_no_report_is_not_treated_as_clean(self) -> None:
        # An absent report is not evidence of an empty one. The stop truncates
        # it before it does anything else, so a missing file means the stop
        # never got far enough to say what it left behind.
        result = self.squad.run("restart", SQUAD_TEST_STOP_WRITES_REPORT="0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.squad.index_of("launch-squad"), -1, self.squad.trace())


class ResumeStateMessageTests(unittest.TestCase):
    def test_the_close_message_names_the_capsule_not_the_archive(self) -> None:
        # CLAUDE.md: `chrono/current.md` is an ARCHIVE, not a resume source, and
        # the one resume contract is regenerate-then-read
        # `_state/chrono/resume.md`. A close message that names the archive
        # points the next session at the wrong file.
        lines = [
            line
            for line in SQUAD_STOP.read_text(encoding="utf-8").splitlines()
            if "Resume state:" in line
        ]
        self.assertTrue(lines, "the close message no longer names a resume state")
        for line in lines:
            self.assertIn("_state/chrono/resume.md", line)
            self.assertNotIn("chrono/current.md", line.replace("_state/chrono/resume.md", ""))


class ShellSyntaxTests(unittest.TestCase):
    def test_the_edited_scripts_parse(self) -> None:
        for script in (SQUAD, SQUAD_STOP):
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["bash", "-n", str(script)], capture_output=True, text=True, timeout=30
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()


class PollerCensusFailsClosedTests(unittest.TestCase):
    """An unrunnable poller census must not read as "no pollers".

    `bin/squad` captured `pollers="$(find_live_vs_lane_status_pollers | tr ...)"`
    and discarded the exit status. If that function is ever renamed or split
    during a refactor of `shared/process-identity.sh`, bash emits
    `command not found`, returns 127, `pollers` is empty -- and verification
    prints a green checkmark, then launches over the live poller it was meant to
    catch.

    Same fail-open shape as the group census in squad-stop.sh: the permissive
    answer is indistinguishable from the verified-clean one.

    Catches: reverting to an unchecked command substitution, or treating a
    non-zero census status as an empty result.
    """

    def _census(self, body: str) -> subprocess.CompletedProcess:
        src = SQUAD.read_text(encoding="utf-8")
        start = src.index("poller_census()")
        end = src.index("\n}", start) + 2
        fn = src[start:end]
        script = (
            f"{body}\n{fn}\n"
            'if poller_census; then echo "RC=0 CENSUS=${POLLER_CENSUS}"; '
            'else echo "RC=$?"; fi\n'
        )
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    def test_a_missing_census_function_is_not_reported_as_clean(self) -> None:
        result = self._census("# find_live_vs_lane_status_pollers deliberately undefined")
        self.assertNotIn(
            "RC=0", result.stdout,
            "an undefined census returned 127 and was reported as 'no pollers'; "
            f"the launch would proceed over a live poller.\n{result.stdout}",
        )

    def test_a_failing_census_is_not_reported_as_clean(self) -> None:
        result = self._census("find_live_vs_lane_status_pollers() { return 3; }")
        self.assertNotIn("RC=0", result.stdout, result.stdout)

    def test_a_genuinely_empty_census_is_clean(self) -> None:
        """Control: no pollers really means no pollers."""
        result = self._census("find_live_vs_lane_status_pollers() { :; }")
        self.assertIn("RC=0", result.stdout, result.stdout)

    def test_a_populated_census_reports_its_pids(self) -> None:
        """Control: real pollers must still be seen."""
        result = self._census(
            "find_live_vs_lane_status_pollers() { printf '111\\n222\\n'; }"
        )
        self.assertIn("111", result.stdout, result.stdout)
