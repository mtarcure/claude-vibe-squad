#!/usr/bin/env python3
"""Plan B Task 7: `squad stop` reaps almost nothing it started.

docs/superpowers/sdd/2026-08-17-plan-B-stop-lying-about-state/task-7-brief.md

bin/squad-stop.sh killed only mode-spawned Chrome profiles and the tmux
session. It never reaped:

  - the vs-lane-status.sh live-status poller, started by launch-squad.sh with
    `nohup ... & disown` -- not a pane child, so `tmux kill-session` cannot
    reach it. Proof this was real: a 7-day-old orphaned poller was found on
    this host, writing status files every ~1s the entire time.
  - board specialists, spawned by board-supervisor.sh via
    `subprocess.Popen(..., start_new_session=True)` (board-supervisor.sh:2664)
    -- each becomes its own process-group/session leader, so it never
    receives the SIGHUP tmux delivers to ordinary pane children either. Proof
    this was real: a live specialist was found orphaned for 7 days.

It also hardcoded the literal session name "squad" at every tmux call site
while bin/launch-squad.sh honours SQUAD_SESSION, so under a custom session
name `squad stop` silently printed "No squad session running" and exited 0 --
a no-op that left everything running -- and unconditionally printed
"Squad closed." after `tmux kill-session` regardless of whether the session
actually died.

SAFETY, read before touching any test in this file
----------------------------------------------------
squad-stop.sh's own operator-facing session is named "squad" and this host
has one running with a live Chrono. A prior "isolated" test elsewhere in this
remediation still reached and killed that live session outright, from a
predicate that looked scoped but was not. This file therefore NEVER invokes
bin/squad-stop.sh itself, NEVER calls `tmux kill-session`/`tmux has-session`
against the real default tmux server, and NEVER spawns anything named after
this repo's real scripts. Every new code path added by Task 7 is instead
extracted verbatim (same technique as
scripts/python/tests/test_argv_guard_false_positive.py's
is_mode_spawned_chrome_profile()/pidfile_alive() extraction) and driven
directly: the pure PID-tree walk with synthetic data, and the two reaping
bash functions against real-but-throwaway `sleep` processes this test spawns
and owns itself -- never against tmux, never against anything resembling a
real specialist or poller.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SQUAD_STOP = REPO / "bin" / "squad-stop.sh"
# pid_is_vs_lane_status_poller() moved here in Plan B Task 12, when
# bin/launch-squad.sh started asking the same question from the other side
# (is a live poller running that my pidfile does not name?). squad-stop.sh
# sources it; one shape, one home, so the reaper and the launcher cannot
# disagree about what the poller looks like.
PROCESS_IDENTITY = REPO / "shared" / "process-identity.sh"


def _wait_until(predicate, timeout=5.0, interval=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _read_pid_when_written(pid_file: Path, timeout=5.0):
    """Wait for a PID file to hold a COMPLETE integer, not merely to exist.

    `echo $! > f` opens/truncates f when the redirection is set up and writes
    a moment later, so waiting on `f.exists()` can return a file that is still
    empty and hand `int()` an empty string -- the Linux-CI-only
    `ValueError: invalid literal for int() with base 10: ''` this replaced.
    Existence is not readiness for any file another process is mid-write on.

    The trailing newline `echo` emits is the completeness marker: a read that
    ends in "\\n" saw the whole write, so a short read can never be parsed as a
    valid-but-wrong PID. Returns the PID, or None if it never became parseable
    (callers assert on that rather than crashing on a partial read).
    """
    parsed = {}

    def is_parseable() -> bool:
        try:
            raw = pid_file.read_text(encoding="utf-8")
        except OSError:
            return False
        if not raw.endswith("\n"):
            return False
        text = raw.strip()
        if not text.isdigit():
            return False
        parsed["pid"] = int(text)
        return True

    if not _wait_until(is_parseable, timeout=timeout):
        return None
    return parsed["pid"]


def _pid_alive(pid: int) -> bool:
    """Liveness for a PID this test process is NOT the parent of (e.g. a
    grandchild reaped by init/launchd once orphaned). `os.kill(pid, 0)`
    reports success for our OWN un-reaped zombie children too -- the PID
    slot stays allocated until something calls wait() on it -- so this must
    never be used for a subprocess.Popen this test spawned directly; use
    `proc.poll() is not None` for those instead (poll() performs the reap).
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class DescendantsOfTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's descendants_of(), extracted verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        match = re.search(
            r"\ndef descendants_of\(.*?\n(?=\ndef _live_pid_ppid_pairs)",
            text,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError(
                "could not locate descendants_of() in bin/squad-stop.sh -- "
                "extraction regex is stale, update it to match the current source"
            )
        namespace: dict = {}
        exec(compile(match.group(0), "<descendants_of extract>", "exec"), namespace)
        cls.descendants_of = staticmethod(namespace["descendants_of"])

    def test_multi_generation_descendants_all_found(self) -> None:
        # root(1) -> child(2) -> grandchild(3); root(1) -> child(4)
        pairs = [(2, 1), (3, 2), (4, 1)]
        self.assertEqual(self.descendants_of([1], pairs), {2, 3, 4})

    def test_unrelated_processes_never_included(self) -> None:
        # A completely separate tree (99 -> 100) rooted elsewhere must never
        # show up just because it coexists in the same `ps` snapshot -- the
        # walk is reachability-only, exactly like the pane-scoping property
        # this function exists to provide.
        pairs = [(2, 1), (100, 99)]
        self.assertEqual(self.descendants_of([1], pairs), {2})

    def test_multiple_roots_union_correctly(self) -> None:
        pairs = [(11, 10), (21, 20)]
        self.assertEqual(self.descendants_of([10, 20], pairs), {11, 21})

    def test_root_with_no_children_returns_empty(self) -> None:
        pairs = [(2, 1)]
        self.assertEqual(self.descendants_of([999], pairs), set())

    def test_empty_process_table_returns_empty(self) -> None:
        self.assertEqual(self.descendants_of([1, 2, 3], []), set())

    def test_orphaned_specialist_reachable_through_intermediate_shell(self) -> None:
        # Mirrors the real shape: pane_pid -> board-supervisor.sh (python) ->
        # specialist (its own new session/group, but PPID-linked until the
        # parent dies). The walk must reach it through the intermediate hop.
        pane_pid = 500
        pairs = [(501, pane_pid), (502, 501)]  # 501=board-supervisor, 502=specialist
        self.assertEqual(self.descendants_of([pane_pid], pairs), {501, 502})


class ReapPidfileProcessTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's reap_pidfile_process(), extracted verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        match = re.search(r"\nreap_pidfile_process\(\) \{.*?\n\}\n", text, re.DOTALL)
        if not match:
            raise RuntimeError("could not locate reap_pidfile_process() in bin/squad-stop.sh")
        cls.function_src = match.group(0)

    # Round-1 fix: reap_pidfile_process() now REQUIRES an identity-check
    # callback (3rd arg) and refuses to kill a live PID that fails it. Most
    # tests below only care about the generic pidfile-management behaviour
    # (missing/dead/corrupt file, kill-if-alive), not poller-specific
    # identity, so they use this trivial always-true stub as the callback.
    # The identity check ITSELF (pid_is_vs_lane_status_poller) is exercised
    # for real, against real spawned processes, in
    # PidIsVsLaneStatusPollerTests below.
    ALWAYS_TRUE_STUB = 'always_true() { return 0; }\n'

    def _run(self, script_body: str, identity_src: str | None = None) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            + self.function_src
            + "\n"
            + (identity_src if identity_src is not None else self.ALWAYS_TRUE_STUB)
            + "\n"
            + script_body
        )
        return subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)

    def test_missing_pidfile_is_a_silent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "nope.pid"
            result = self._run(f'reap_pidfile_process "{pidfile}" "thing" always_true; echo "rc=$?"')
            self.assertIn("rc=0", result.stdout)
            self.assertEqual(result.stdout.count("Killing"), 0)

    def test_dead_pid_removes_pidfile_without_killing_anything(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "poller.pid"
            pidfile.write_text(f"{dead.pid}\n", encoding="utf-8")
            result = self._run(f'reap_pidfile_process "{pidfile}" "poller" always_true; echo "rc=$?"')
            self.assertIn("rc=0", result.stdout)
            self.assertEqual(result.stdout.count("Killing"), 0)
            self.assertFalse(pidfile.exists(), "pidfile must be removed even for a dead PID")

    def test_live_pid_is_killed_and_pidfile_removed(self) -> None:
        live = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as d:
                pidfile = Path(d) / "poller.pid"
                pidfile.write_text(f"{live.pid}\n", encoding="utf-8")
                result = self._run(f'reap_pidfile_process "{pidfile}" "poller" always_true; echo "rc=$?"')
                self.assertIn("rc=0", result.stdout)
                self.assertIn(f"Killing poller: {live.pid}", result.stdout)
                self.assertTrue(_wait_until(lambda: live.poll() is not None))
                self.assertFalse(pidfile.exists())
        finally:
            if live.poll() is None:
                live.terminate()
            live.wait(timeout=5)

    def test_live_pid_failing_identity_check_is_not_killed(self) -> None:
        # The core of the round-1 fix: an alive PID whose identity check
        # fails (stale/recycled pidfile) must be left running -- only the
        # pidfile itself is cleaned up.
        live = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as d:
                pidfile = Path(d) / "poller.pid"
                pidfile.write_text(f"{live.pid}\n", encoding="utf-8")
                result = self._run(
                    f'reap_pidfile_process "{pidfile}" "poller" always_false; echo "rc=$?"',
                    identity_src="always_false() { return 1; }\n",
                )
                self.assertIn("rc=0", result.stdout)
                self.assertEqual(result.stdout.count("Killing"), 0)
                self.assertIn("NOT killing", result.stderr)
                time.sleep(0.3)
                self.assertIsNone(live.poll(), "process failing identity check must not be killed")
                self.assertFalse(pidfile.exists(), "pidfile is still removed even when not killing")
        finally:
            if live.poll() is None:
                live.terminate()
            live.wait(timeout=5)

    def test_corrupt_pidfile_removed_without_killing_anything(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "poller.pid"
            pidfile.write_text("not-a-pid\n", encoding="utf-8")
            result = self._run(f'reap_pidfile_process "{pidfile}" "poller" always_true; echo "rc=$?"')
            self.assertIn("rc=0", result.stdout)
            self.assertEqual(result.stdout.count("Killing"), 0)
            self.assertFalse(pidfile.exists())


class PidIsVsLaneStatusPollerTests(unittest.TestCase):
    """Drives shared/process-identity.sh's pid_is_vs_lane_status_poller(),
    extracted verbatim, against real spawned processes -- this is the identity
    check that makes reap_pidfile_process()'s kill decision safe against a
    stale/recycled PID (Plan B Task 7 fix round 1).
    """

    @classmethod
    def setUpClass(cls) -> None:
        text = PROCESS_IDENTITY.read_text(encoding="utf-8")
        match = re.search(
            r"\npid_is_vs_lane_status_poller\(\) \{.*?\n\}\n", text, re.DOTALL
        )
        if not match:
            raise RuntimeError(
                "could not locate pid_is_vs_lane_status_poller() in "
                "shared/process-identity.sh"
            )
        cls.function_src = match.group(0)
        if f"{PROCESS_IDENTITY.name}" not in SQUAD_STOP.read_text(encoding="utf-8"):
            raise RuntimeError(
                "bin/squad-stop.sh no longer sources shared/process-identity.sh -- "
                "this class would be testing a function the reaper does not use"
            )

    def _run(self, vault_root: Path, pid: int) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            f'VAULT_ROOT="{vault_root}"\n'
            + self.function_src
            + f'\npid_is_vs_lane_status_poller {pid}; echo "rc=$?"'
        )
        return subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)

    def test_real_poller_invocation_shape_matches(self) -> None:
        vault_root = Path(tempfile.mkdtemp())
        (vault_root / "bin").mkdir()
        script = vault_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        # Exactly launch-squad.sh's own invocation shape: `bash <script>`.
        proc = subprocess.Popen(["bash", str(script)])
        try:
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=0", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_unrelated_process_at_a_recycled_pid_does_not_match(self) -> None:
        vault_root = Path(tempfile.mkdtemp())
        proc = subprocess.Popen(["sleep", "30"])
        try:
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=1", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_different_vault_root_same_script_name_does_not_match(self) -> None:
        real_root = Path(tempfile.mkdtemp())
        (real_root / "bin").mkdir()
        script = real_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        proc = subprocess.Popen(["bash", str(script)])
        try:
            other_root = Path(tempfile.mkdtemp())  # a DIFFERENT VAULT_ROOT
            result = self._run(other_root, proc.pid)
            self.assertIn("rc=1", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_extra_argument_breaks_the_match(self) -> None:
        vault_root = Path(tempfile.mkdtemp())
        (vault_root / "bin").mkdir()
        script = vault_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        proc = subprocess.Popen(["bash", str(script), "extra-arg"])
        try:
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=1", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_dead_pid_does_not_match(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        vault_root = Path(tempfile.mkdtemp())
        result = self._run(vault_root, dead.pid)
        self.assertIn("rc=1", result.stdout)

    # --- Whole-branch review I3: a checkout path containing a space ---------

    def test_a_vault_root_containing_a_space_still_matches(self) -> None:
        """The repo IS an Obsidian vault, and `~/Library/Mobile Documents/...`,
        `~/Google Drive/My Drive/...` and `~/Obsidian Vaults/...` are ordinary
        macOS clone locations. Nothing in the repo documents a no-spaces
        constraint and no doctor check enforces one.

        `ps -o args=` cannot re-quote such a path, so re-splitting the row on
        IFS made the predicate "two whitespace-separated WORDS" and it stopped
        recognising this root's own poller -- the launcher then spawning a
        duplicate every `squad up`, and the stopper refusing to reap while
        deleting the pidfile that was the only record of it.
        """
        vault_root = Path(tempfile.mkdtemp()) / "Obsidian Vaults" / "Claude Vibe Squad"
        (vault_root / "bin").mkdir(parents=True)
        script = vault_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        self.assertIn(" ", str(vault_root), "test setup: the root must contain a space")
        proc = subprocess.Popen(["bash", str(script)])
        try:
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=0", result.stdout, result.stderr)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_spaced_vault_root_does_not_relax_the_extra_argument_rule(self) -> None:
        """Comparing the tail as one string must not become "starts with the
        script path": a third argv element still breaks the match."""
        vault_root = Path(tempfile.mkdtemp()) / "Obsidian Vaults" / "Claude Vibe Squad"
        (vault_root / "bin").mkdir(parents=True)
        script = vault_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        proc = subprocess.Popen(["bash", str(script), "extra-arg"])
        try:
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=1", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_41kb_argv_quoting_the_poller_path_does_not_match(self) -> None:
        """The property the token form was there for, restated against the
        string form: a specialist's compiled prompt is its own argv (41,008
        bytes measured on a live `codex exec`) and may name this file's paths
        as ordinary prose."""
        vault_root = Path(tempfile.mkdtemp())
        (vault_root / "bin").mkdir()
        script = vault_root / "bin" / "vs-lane-status.sh"
        prose = (
            f"the poller lives at {script} and it isn't tracked by a pidfile, "
            "so a week-old corpse satisfies pgrep -f just fine. "
        )
        argv = prose * (41_008 // len(prose) + 1)
        proc = subprocess.Popen(["bash", "-c", f"sleep 30 # {argv}"])
        try:
            self.assertGreaterEqual(len(argv.encode("utf-8")), 41_008)
            result = self._run(vault_root, proc.pid)
            self.assertIn("rc=1", result.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class PidIdentityTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's pid_start_time()/pid_identity_still_matches(),
    extracted verbatim -- the Phase 3c-snapshot -> Phase 5-kill identity
    re-verification added in Plan B Task 7 fix round 1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        start_match = re.search(r"\npid_start_time\(\) \{.*?\n\}\n", text, re.DOTALL)
        matches_match = re.search(
            r"\npid_identity_still_matches\(\) \{.*?\n\}\n", text, re.DOTALL
        )
        if not start_match or not matches_match:
            raise RuntimeError(
                "could not locate pid_start_time()/pid_identity_still_matches() "
                "in bin/squad-stop.sh"
            )
        cls.function_src = start_match.group(0) + "\n" + matches_match.group(0)

    def _run(self, script_body: str) -> subprocess.CompletedProcess:
        full = "#!/bin/bash\nset -uo pipefail\n" + self.function_src + "\n" + script_body
        return subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)

    def test_live_pid_matches_its_own_recorded_start_time(self) -> None:
        live = subprocess.Popen(["sleep", "30"])
        try:
            result = self._run(
                f'start="$(pid_start_time {live.pid})"\n'
                f'pid_identity_still_matches {live.pid} "$start"; echo "rc=$?"'
            )
            self.assertIn("rc=0", result.stdout)
        finally:
            live.terminate()
            live.wait(timeout=5)

    def test_mismatched_recorded_start_time_fails(self) -> None:
        # Simulates a recycled PID: the live process is real, but the
        # "recorded" start time is deliberately wrong, exactly as it would
        # be if a DIFFERENT process now occupies this PID.
        live = subprocess.Popen(["sleep", "30"])
        try:
            result = self._run(
                f'pid_identity_still_matches {live.pid} "Thu Jan  1 00:00:00 1970"; echo "rc=$?"'
            )
            self.assertIn("rc=1", result.stdout)
        finally:
            live.terminate()
            live.wait(timeout=5)

    def test_empty_recorded_start_time_fails_closed(self) -> None:
        # A PID with no baseline recorded at all (e.g. never actually seen
        # in the Phase 3c snapshot) must never be treated as identity-
        # verified just because it happens to be alive.
        live = subprocess.Popen(["sleep", "30"])
        try:
            result = self._run(f'pid_identity_still_matches {live.pid} ""; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)
        finally:
            live.terminate()
            live.wait(timeout=5)

    def test_dead_pid_fails_regardless_of_recorded_start_time(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        result = self._run(
            f'pid_identity_still_matches {dead.pid} "irrelevant"; echo "rc=$?"'
        )
        self.assertIn("rc=1", result.stdout)


class ReapSurvivorGroupTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's reap_survivor_group(), extracted verbatim.

    Spawns real throwaway `sleep`/`bash` processes this test owns -- never
    anything that looks like a real specialist, and never via tmux.
    """

    # reap_survivor_group() calls pgid_is_protected_chrome(), so both are
    # extracted. Driving the reaper without its guard defined would not fail
    # loudly: `set -uo pipefail` has no -e, an undefined function returns 127,
    # and `if` reads 127 as false -- so every kill would proceed and every
    # test would pass while the protection was absent. That is the exact
    # "guard satisfied by nothing" shape this plan exists to remove.
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

    @staticmethod
    def _chrome_scan_state(protected_pgids: str = "", scan_ok: str = "1") -> str:
        """The two globals capture_protected_chrome_pgids() sets.

        `scan_ok` defaults to 1 -- a scan that ran and answered -- because that
        is the state every kill assertion in this class means to model. A test
        that omitted it would otherwise be driving the failed-scan path, where
        every group is protected and no kill can happen, and would then pass or
        fail for a reason it never stated.
        """
        return (
            f'PROTECTED_CHROME_PGIDS="{protected_pgids}"\n'
            f'PROTECTED_CHROME_SCAN_OK="{scan_ok}"\n'
        )

    def _run(
        self, script_body: str, protected_pgids: str = "", scan_ok: str = "1"
    ) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            + self._chrome_scan_state(protected_pgids, scan_ok)
            + self.function_src
            + "\n"
            + script_body
        )
        return subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)

    def test_already_dead_pid_is_a_silent_noop(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        result = self._run(f'reap_survivor_group {dead.pid} TERM; echo "rc=$?"')
        self.assertIn("rc=0", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_live_process_group_leader_is_terminated(self) -> None:
        # start_new_session=True mirrors board-supervisor.sh:2664's own spawn
        # shape: this process becomes its own process-group/session leader,
        # exactly like a real orphaned specialist.
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            self._run(f'reap_survivor_group {proc.pid} TERM')
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    @staticmethod
    def _spawn_leader_with_group_child(
        child_pid_file: Path, pid_write_delay: float = 0.0
    ) -> subprocess.Popen:
        """A group leader that forks a child sharing its process group.

        `pid_write_delay` widens the empty-PID-file window deterministically
        by doing the truncation the redirection would do anyway, then stalling
        before the write. It is the inverted control for
        _read_pid_when_written(): the race is Linux-CI-only by luck, but with
        the window held open it is reproducible anywhere.
        """
        write_pid = f'echo $! > "{child_pid_file}"'
        if pid_write_delay:
            write_pid = (
                f': > "{child_pid_file}"; sleep {pid_write_delay}; ' + write_pid
            )
        return subprocess.Popen(
            ["bash", "-c", f"sleep 30 & {write_pid}; wait"],
            start_new_session=True,
        )

    def test_an_existing_pid_file_can_still_be_empty(self) -> None:
        # Inverted control for the flake fix. Under a widened write window the
        # replaced code -- wait for existence, then parse -- reads "" and
        # raises the exact ValueError seen on Linux CI, while
        # _read_pid_when_written() returns the real PID from the same file.
        # Without this, the fix would be a change that only ever ran green.
        work_dir = Path(tempfile.mkdtemp())
        child_pid_file = work_dir / "child.pid"
        proc = self._spawn_leader_with_group_child(child_pid_file, pid_write_delay=1.0)
        try:
            self.assertTrue(_wait_until(lambda: child_pid_file.exists()))
            with self.assertRaises(ValueError):
                # The replaced two lines, verbatim.
                int(child_pid_file.read_text(encoding="utf-8").strip())

            child_pid = _read_pid_when_written(child_pid_file)
            self.assertIsNotNone(
                child_pid, "content-wait must survive the widened write window"
            )
            self.assertTrue(_pid_alive(child_pid))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_kill_reaches_the_whole_process_group_not_just_the_leader(self) -> None:
        # A specialist's own subprocess tree must go with it: spawn a group
        # leader that itself forks a child sharing its process group, write
        # the child's real PID out so this test can verify it independently,
        # and confirm TERM aimed at the LEADER's PID kills both.
        work_dir = Path(tempfile.mkdtemp())
        child_pid_file = work_dir / "child.pid"
        proc = self._spawn_leader_with_group_child(child_pid_file)
        try:
            child_pid = _read_pid_when_written(child_pid_file)
            self.assertIsNotNone(child_pid, "child never wrote a parseable PID")
            self.assertTrue(_pid_alive(child_pid), "child sleep must be running before the kill")

            self._run(f'reap_survivor_group {proc.pid} TERM')

            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
            self.assertTrue(
                _wait_until(lambda: not _pid_alive(child_pid)),
                "process-group kill must also reap the leader's own child, "
                "not just the leader PID",
            )
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_kill_escalates_from_term_to_kill_for_a_signal_ignoring_process(self) -> None:
        proc = subprocess.Popen(
            ["bash", "-c", "trap '' TERM; sleep 30"],
            start_new_session=True,
        )
        try:
            self._run(f'reap_survivor_group {proc.pid} TERM')
            # TERM is trapped/ignored -- process must still be alive.
            time.sleep(0.3)
            self.assertTrue(_pid_alive(proc.pid))
            self._run(f'reap_survivor_group {proc.pid} KILL')
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    # --- Round-1 fix additions --------------------------------------------

    def test_refuses_to_kill_own_process_group(self) -> None:
        # Round 1 item 3: a kill-by-group primitive must refuse pgid 0/1/
        # self explicitly. Spawned WITHOUT start_new_session -- this child
        # shares this test process's own pgid by default, exactly the
        # "self" case the guard exists for.
        own_pgid = os.getpgrp()
        proc = subprocess.Popen(["sleep", "30"])
        try:
            self.assertEqual(
                os.getpgid(proc.pid), own_pgid, "test setup: child must share our pgid"
            )
            result = self._run(
                f'SQUAD_STOP_OWN_PGID={own_pgid}\n'
                f'reap_survivor_group {proc.pid} TERM; echo "rc=$?"'
            )
            self.assertIn("rc=1", result.stdout)
            self.assertIn("Refusing to kill process group", result.stderr)
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), "must never kill its own process group")
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)

    def test_refuses_to_kill_pgid_zero_or_one_even_if_reported(self) -> None:
        # Round 1 item 3: pgid<=1 must be refused unconditionally, even
        # if something (a stubbed/misbehaving `ps`) reports it. A real
        # process can never actually carry pgid 0 or 1 as an unprivileged
        # user, so this drives the exact boundary via a stub `ps` on PATH
        # rather than trying to engineer a real process into that state.
        live = subprocess.Popen(["sleep", "30"])
        try:
            stub_dir = Path(tempfile.mkdtemp())
            stub_ps = stub_dir / "ps"
            stub_ps.write_text(
                "#!/bin/bash\n"
                'if [[ "$*" == *"pgid="*"-p"* ]]; then echo 1; else exec /bin/ps "$@"; fi\n',
                encoding="utf-8",
            )
            stub_ps.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self._chrome_scan_state()
                + self.function_src
                + f'\nreap_survivor_group {live.pid} TERM; echo "rc=$?"'
            )
            result = subprocess.run(
                ["bash", "-c", full], capture_output=True, text=True, timeout=15, env=env
            )
            self.assertIn("rc=1", result.stdout)
            self.assertIn("Refusing to kill process group", result.stderr)
            time.sleep(0.3)
            self.assertIsNone(live.poll(), "pgid<=1 must never be killed regardless of report")
        finally:
            if live.poll() is None:
                live.terminate()
            live.wait(timeout=5)

    # --- Whole-branch review I4: the persistent CDP Chrome ------------------

    def test_persistent_chrome_process_group_is_never_reaped(self) -> None:
        """bin/squad-stop.sh:123 states "NEVER kill the operator's main Chrome
        at port 9222". Phase 3 honoured it; Phase 5 group-reaped every
        surviving pane descendant with no such exclusion, and
        bin/chrome-bootstrap.sh `exec`s Chrome directly, so a Chrome started
        from a squad pane IS a pane descendant. Cost when it fired: the
        operator's authenticated bounty sessions.

        Driven against a real live process in its own group, standing in for
        the browser -- never against a real Chrome.
        """
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            pgid = os.getpgid(proc.pid)
            result = self._run(
                f'reap_survivor_group {proc.pid} TERM; echo "rc=$?"',
                protected_pgids=f"{pgid}",
            )
            self.assertIn("rc=1", result.stdout)
            self.assertIn("persistent CDP Chrome", result.stderr)
            time.sleep(0.3)
            self.assertIsNone(
                proc.poll(), "a protected persistent-Chrome group must never be signalled"
            )
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_a_failed_scan_refuses_every_group_rather_than_protecting_none(self) -> None:
        """Fix round 2, N1. An empty PROTECTED_CHROME_PGIDS is ambiguous: it
        means both "the persistent Chrome is not running" and "the scan that
        would have found it failed". Phase 3 runs the same scan and a failure
        there fails SAFE (kills nothing); here it failed UNSAFE (protected
        nothing) and reverted Phase 5 to its pre-fix behaviour in silence.

        This is the enforcement point, so it must not be able to fail open --
        even if the caller-side skip were reordered away.
        """
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            result = self._run(
                f'reap_survivor_group {proc.pid} TERM; echo "rc=$?"',
                protected_pgids="",
                scan_ok="0",
            )
            self.assertIn("rc=1", result.stdout)
            self.assertIn("scan failed", result.stderr)
            time.sleep(0.3)
            self.assertIsNone(
                proc.poll(),
                "with no usable scan, no group can be shown NOT to be the "
                "operator's browser, so nothing may be signalled",
            )
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_a_successful_scan_finding_nothing_still_reaps(self) -> None:
        """The other half of the distinction: "scan ran, no browser" must NOT
        become "refuse everything", or a stop with no Chrome open would reap
        nothing at all -- a component reporting success while doing nothing,
        through the other door."""
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            self._run(
                f'reap_survivor_group {proc.pid} TERM',
                protected_pgids="",
                scan_ok="1",
            )
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_protection_is_membership_not_a_blanket_refusal(self) -> None:
        """The guard must key on THIS group, or it would be a stop that stops
        nothing whenever any persistent Chrome happens to be running."""
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            unrelated = os.getpgid(proc.pid) + 1
            self._run(
                f'reap_survivor_group {proc.pid} TERM',
                protected_pgids=f"{unrelated} 999999",
            )
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_recorded_start_time_mismatch_prevents_the_kill(self) -> None:
        # Round 1 item 2: even a currently-alive, correctly-pgid'd PID must
        # not be killed if the identity check (3rd arg) fails -- proves the
        # re-verification happens INSIDE reap_survivor_group itself, at the
        # point of the kill call, not only in an earlier selection pass.
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            identity_src = self._identity_function_src()
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self._chrome_scan_state()
                + identity_src
                + "\n"
                + self.function_src
                + f'\nreap_survivor_group {proc.pid} TERM "wrong-start-time"; echo "rc=$?"'
            )
            result = subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)
            self.assertIn("rc=0", result.stdout)  # early return, not an error
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), "mismatched recorded start time must block the kill")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_recorded_start_time_match_still_allows_the_kill(self) -> None:
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            identity_src = self._identity_function_src()
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self._chrome_scan_state()
                + identity_src
                + "\n"
                + self.function_src
                + f'\nstart="$(pid_start_time {proc.pid})"\n'
                f'reap_survivor_group {proc.pid} TERM "$start"'
            )
            subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)
            self.assertTrue(_wait_until(lambda: proc.poll() is not None))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    @staticmethod
    def _identity_function_src() -> str:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        start_match = re.search(r"\npid_start_time\(\) \{.*?\n\}\n", text, re.DOTALL)
        matches_match = re.search(
            r"\npid_identity_still_matches\(\) \{.*?\n\}\n", text, re.DOTALL
        )
        if not start_match or not matches_match:
            raise RuntimeError(
                "could not locate pid_start_time()/pid_identity_still_matches() "
                "in bin/squad-stop.sh"
            )
        return start_match.group(0) + "\n" + matches_match.group(0)


class SquadSessionEnvHonoredTests(unittest.TestCase):
    """Real subprocess run of bin/squad-stop.sh, but only against the fast
    "no such session" guard -- read-only tmux calls (`has-session` on a name
    guaranteed not to exist) that can never reach, list, or touch the real
    live "squad" session regardless of what is currently running on this
    host. Proves the SQUAD_SESSION hardcode fix without creating or killing
    any tmux session at all.
    """

    def test_custom_session_name_is_honored_in_the_no_session_message(self) -> None:
        throwaway = "task7-test-nonexistent-2026-08-17-should-never-exist"
        env = dict(os.environ)
        env["SQUAD_SESSION"] = throwaway
        result = subprocess.run(
            ["bash", str(SQUAD_STOP)], capture_output=True, text=True, timeout=30, env=env
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(throwaway, result.stdout)
        self.assertIn("Nothing to stop", result.stdout)
        # Before the fix this always checked the literal "squad" regardless
        # of SQUAD_SESSION, so a real "squad" session running on this host
        # would have made this exact invocation print "Squad close
        # initiated" and proceed to nudge/kill it. Assert that never happens.
        self.assertNotIn("Squad close initiated", result.stdout)


class IdentitySourceFailureTests(unittest.TestCase):
    """Plan B Task 12 fix round 1, minor 2.

    This script runs `set -uo pipefail` without -e on purpose, so an unguarded
    `source` of a missing shared/process-identity.sh continues with the
    predicate undefined. reap_pidfile_process() would then get rc=127 from the
    identity callback and print "alive but no longer identifies as ... (stale/
    recycled PID). Removing the pidfile only." about a process that IS the
    poller -- a confident, specific, wrong reason for deleting the only record
    of the exact process this phase exists to reap.
    """

    def test_the_source_is_failure_guarded(self) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        match = re.search(
            r'source "\$\{VAULT_ROOT\}/shared/process-identity\.sh"(.*)$',
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(match, "squad-stop.sh no longer sources shared/process-identity.sh")
        self.assertIn(
            "||",
            match.group(1),
            "the source must record its failure, not fall through silently",
        )

    def test_the_reap_is_gated_on_the_identity_check_being_available(self) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        call = re.search(
            r"^(?P<indent>\s*)reap_pidfile_process \"\$\{VS_LANE_STATUS_PIDFILE\}\".*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(call, "the poller reap call moved or was removed")
        preceding = text[: call.start()].splitlines()[-6:]
        self.assertTrue(
            any("VS_LANE_STATUS_IDENTITY_READY" in line for line in preceding),
            "the poller reap must be gated on the identity predicate having loaded; "
            f"nothing gates it in the lines just above it: {preceding}",
        )
        # And the unavailable branch must keep the pidfile: it is the only
        # record of the poller, so deleting it while unable to verify the PID
        # destroys the operator's one lead.
        self.assertIn("is left intact", text)


class ProtectedChromeScanTests(unittest.TestCase):
    """Fix round 2, N1: drives capture_protected_chrome_pgids() through the
    REAL scan pipeline, extracted verbatim along with chrome_profile_processes().

    The `python3` on PATH is a stub, so the three outcomes -- found a browser,
    found none, scan itself failed -- are produced by the same pipeline the
    script runs, not by pre-setting the variables it is supposed to derive.
    """

    FUNCTIONS = ("chrome_profile_processes", "capture_protected_chrome_pgids")

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

    def _run_with_python_stub(self, stub_body: str) -> subprocess.CompletedProcess:
        stub_dir = Path(tempfile.mkdtemp())
        stub = stub_dir / "python3"
        stub.write_text(stub_body, encoding="utf-8")
        stub.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'PERSISTENT_CHROME_PROFILE="/nonexistent/chrome-persistent-profile"\n'
            'PROTECTED_CHROME_PGIDS=""\nPROTECTED_CHROME_SCAN_OK=0\n'
            + self.function_src
            + "\ncapture_protected_chrome_pgids\n"
            'echo "rc=$?"\n'
            'echo "scan_ok=${PROTECTED_CHROME_SCAN_OK}"\n'
            'echo "pgids=[${PROTECTED_CHROME_PGIDS}]"\n'
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=30, env=env
        )

    def test_a_failing_scan_is_not_reported_as_an_absent_browser(self) -> None:
        """The defect: `python3` off PATH, or its inner `ps` raising, yields an
        empty string that reads identically to "no Chrome running"."""
        result = self._run_with_python_stub(
            "#!/bin/sh\n"
            'echo "Traceback (most recent call last): CalledProcessError" >&2\n'
            "exit 1\n"
        )
        self.assertIn("scan_ok=0", result.stdout)
        self.assertIn("rc=1", result.stdout)
        self.assertIn("pgids=[]", result.stdout)
        # And it must say so. The pre-fix code reported only on success, so a
        # failed scan produced no output at all.
        self.assertIn("WARNING", result.stderr)
        self.assertIn("reap NOTHING", result.stderr)

    def test_a_scan_that_finds_the_browser_records_its_process_groups(self) -> None:
        result = self._run_with_python_stub(
            "#!/bin/sh\nprintf '%s\\n' '51149 51149' '23378 51149' '44600 51149'\n"
        )
        self.assertIn("scan_ok=1", result.stdout)
        self.assertIn("rc=0", result.stdout)
        # De-duplicated: the helpers share the browser's group.
        self.assertIn("pgids=[51149]", result.stdout)
        self.assertIn("Protecting the operator's persistent CDP Chrome", result.stdout)

    def test_a_scan_that_finds_nothing_is_a_success_with_an_empty_set(self) -> None:
        result = self._run_with_python_stub("#!/bin/sh\nexit 0\n")
        self.assertIn("scan_ok=1", result.stdout)
        self.assertIn("rc=0", result.stdout)
        self.assertIn("pgids=[]", result.stdout)
        self.assertIn("No persistent CDP Chrome is running", result.stdout)
        self.assertNotIn("WARNING", result.stderr)


class PersistentChromePolicyTests(unittest.TestCase):
    """Whole-branch review I4, structural half.

    Phase 5's survivor-selection loop is top-level script, not a function, so
    it cannot be extracted and driven the way reap_survivor_group() is -- and
    running the real stopper is forbidden while the operator's session is
    live. These assertions pin the three properties that make the exclusion
    real: the protected set is captured while the browser is still alive,
    both the selection and the signal consult it, and the profile path is the
    one bin/chrome-bootstrap.sh actually launches.
    """

    def setUp(self) -> None:
        self.text = SQUAD_STOP.read_text(encoding="utf-8")

    def test_protected_set_is_captured_before_the_session_kill(self) -> None:
        capture = self.text.index("PROTECTED_CHROME_PGIDS=")
        kill_session = self.text.index("tmux kill-session")
        self.assertLess(
            capture, kill_session,
            "the persistent Chrome's process groups must be recorded while it is "
            "still findable -- after the session kill the link is gone",
        )

    def test_both_the_selection_and_the_signal_consult_the_guard(self) -> None:
        self.assertGreaterEqual(
            len(re.findall(r"\bpgid_is_protected_chrome ", self.text)), 2,
            "the guard must be consulted at survivor selection AND immediately "
            "before the signal -- reap_survivor_group is called twice per "
            "survivor (TERM then KILL)",
        )

    def test_the_protected_profile_is_the_one_chrome_bootstrap_launches(self) -> None:
        bootstrap = (REPO / "bin" / "chrome-bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn('PROFILE_DIR="$HOME/.chrono/chrome-persistent-profile"', bootstrap)
        self.assertIn(
            'PERSISTENT_CHROME_PROFILE="${HOME}/.chrono/chrome-persistent-profile"',
            self.text,
            "the protected profile path must track bin/chrome-bootstrap.sh's own",
        )

    def test_the_scan_status_is_captured_rather_than_inferred_from_emptiness(self) -> None:
        """Fix round 2, N1. The scan's exit status must be read, not guessed
        from whether it produced output -- and `local scanned="$(...)"` would
        report `local`'s status instead of the pipeline's, swallowing exactly
        the failure the branch exists to catch."""
        capture = re.search(
            r"\ncapture_protected_chrome_pgids\(\) \{.*?\n\}\n", self.text, re.DOTALL
        )
        self.assertIsNotNone(capture, "capture_protected_chrome_pgids() moved or was removed")
        body = capture.group(0)
        self.assertRegex(
            body,
            r'\n\s*local scanned\n',
            "`scanned` must be declared on its own line; combining it with the "
            "assignment makes the `if` test `local`'s exit status, not the scan's",
        )
        self.assertRegex(body, r'if scanned="\$\(chrome_profile_processes')
        self.assertIn("PROTECTED_CHROME_SCAN_OK=1", body)
        self.assertIn("PROTECTED_CHROME_SCAN_OK=0", body)

    def test_a_failed_scan_is_reported_wherever_it_changes_behaviour(self) -> None:
        """Three call sites must distinguish "protected because it IS the
        browser" from "protected because nothing could be ruled out": the guard
        itself, the survivor-selection message, and the refusal at the signal.
        A single message covering both states would tell the operator their
        orphaned specialist is Chrome."""
        self.assertGreaterEqual(
            len(re.findall(r"PROTECTED_CHROME_SCAN_OK", self.text)), 6
        )
        messages = [
            line
            for line in self.text.splitlines()
            if "echo" in line and re.search(r"scan (?:itself )?failed", line)
        ]
        self.assertEqual(
            len(messages), 3,
            "expected an operator-facing message at the capture, at survivor "
            f"selection, and at the signal; found {len(messages)}",
        )

    def test_one_predicate_answers_both_chrome_questions(self) -> None:
        """Kill-the-mode-profiles and protect-the-persistent-one must come
        from the same matcher, or the two phases drift apart again -- which
        is how they ended up with opposite policies in the first place."""
        self.assertGreaterEqual(
            len(re.findall(r"\bchrome_profile_processes ", self.text)), 2
        )
        self.assertEqual(
            len(re.findall(r"def is_mode_spawned_chrome_profile", self.text)), 1,
            "there must be exactly one copy of the Chrome argv predicate",
        )


if __name__ == "__main__":
    unittest.main()
