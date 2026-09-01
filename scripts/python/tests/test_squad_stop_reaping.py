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
import shlex
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
# LIFE-01: bin/launch-squad.sh writes the coordinator pidfile that
# bin/squad-stop.sh reads to DISCOVER the live orchestrator instead of
# assuming the squad:chrono pane. The writer (launcher) and reader (stopper)
# share one file format, so a round-trip test keeps them from drifting apart.
LAUNCH_SQUAD = REPO / "bin" / "launch-squad.sh"
# LIFE-01 rework: the coordinator pidfile is now written by bin/vs-welcome.sh --
# the coordinator's own startup, which execs claude, so $$ becomes the claude
# process and the recorded PID + start-time fingerprint are claude's own.
# squad-stop reads them back; the round-trip and semantic tests keep writer and
# reader from drifting apart (CLAUDE.md rule 10).
VS_WELCOME = REPO / "bin" / "vs-welcome.sh"


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


class DescendantStartTimeSnapshotTests(unittest.TestCase):
    """Drives the Phase-3c PID/start-time snapshot under the host /bin/bash.

    macOS still ships Bash 3.2. ``declare -A`` is a Bash-4-only construct;
    this snapshot needs only numeric PID keys, so a sparse indexed array is
    both compatible and semantically exact. The deterministic ``ps`` stub is
    deliberate: this test is about the storage/lookup seam and must not need
    permission to inspect unrelated host processes.
    """

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        start_match = re.search(r"\npid_start_time\(\) \{.*?\n\}\n", text, re.DOTALL)
        matches_match = re.search(
            r"\npid_identity_still_matches\(\) \{.*?\n\}\n", text, re.DOTALL
        )
        snapshot_match = re.search(
            r"\ndeclare -a descendant_start_time=\(\)\n"
            r"if \[\[ -n \"\$\{descendant_pids\}\" \]\]; then.*?\nfi\n",
            text,
            re.DOTALL,
        )
        if not start_match or not matches_match or not snapshot_match:
            raise RuntimeError(
                "could not locate the Bash-3.2 PID snapshot in bin/squad-stop.sh -- "
                "the extraction regex is stale or a Bash-4 declaration returned"
            )
        cls.function_src = start_match.group(0) + "\n" + matches_match.group(0)
        cls.snapshot_src = snapshot_match.group(0)

    def test_numeric_pid_snapshot_populates_and_matches_without_diagnostics(
        self,
    ) -> None:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'ps() { printf "%s\\n" "Sun Aug 30 12:34:56 2026"; }\n'
            "descendant_pids=\"$$\"\n"
            + self.function_src
            + self.snapshot_src
            + '\nrecorded="${descendant_start_time[$$]:-}"\n'
            + 'if pid_identity_still_matches "$$" "$recorded"; then rc=0; else rc=$?; fi\n'
            + 'printf "recorded=[%s]\\nentries=%s\\nidentity_rc=%s\\n" '
            '"$recorded" "${#descendant_start_time[@]}" "$rc"\n'
        )
        result = subprocess.run(
            ["/bin/bash", "-c", full],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "", "the Bash-3.2 declaration must be quiet")
        self.assertIn("recorded=[Sun Aug 30 12:34:56 2026]", result.stdout)
        self.assertIn("entries=1", result.stdout)
        self.assertIn("identity_rc=0", result.stdout)


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


# ===========================================================================
# LIFE-01: shutdown DISCOVERS the live orchestrator instead of assuming the
# squad:chrono pane. Same safety rule as the header: these tests NEVER invoke
# bin/squad-stop.sh, NEVER touch the real tmux server, and NEVER signal a real
# process. Every path is exercised by extracting the new functions verbatim and
# driving them with synthetic pidfiles, stubbed leaf predicates, and disposable
# `sleep`/throwaway processes this test spawns and owns.
# ===========================================================================


def _extract(path: Path, pattern: str, what: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        raise RuntimeError(
            f"could not locate {what} in {path} -- extraction regex is stale, "
            "update it to match the current source"
        )
    return match.group(0)


class ParseCoordinatorPidfileTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's parse_coordinator_pidfile(), extracted
    verbatim, against synthetic pidfiles. Pure file parse -- no process, no
    tmux -- so it is safe to run anywhere."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.function_src = _extract(
            SQUAD_STOP,
            r"\nparse_coordinator_pidfile\(\) \{.*?\n\}\n",
            "parse_coordinator_pidfile()",
        )

    def _parse(self, contents: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "chrono.pid"
            pidfile.write_text(contents, encoding="utf-8")
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self.function_src
                + f'\nout="$(parse_coordinator_pidfile "{pidfile}")"; echo "rc=$?"; echo "out=[$out]"'
            )
            return subprocess.run(
                ["bash", "-c", full], capture_output=True, text=True, timeout=15
            )

    def test_well_formed_pane_pidfile(self) -> None:
        # No start line -> empty start -> "-" sentinel in the fourth field.
        r = self._parse("pid 4242\nshape pane\ntarget squad:chrono\n")
        self.assertIn("rc=0", r.stdout)
        self.assertIn("out=[pane 4242 squad:chrono -]", r.stdout)

    def test_well_formed_background_job_pidfile_empty_target(self) -> None:
        r = self._parse("pid 5353\nshape background-job\ntarget \n")
        self.assertIn("rc=0", r.stdout)
        # A background job has no pane (empty target) and this file records no
        # start fingerprint; both empties become the "-" sentinel so the four
        # positional fields never collapse into three.
        self.assertIn("out=[background-job 5353 - -]", r.stdout)

    def test_order_independent_and_unknown_keys_ignored(self) -> None:
        r = self._parse("noise xyz\ntarget squad:chrono\nshape pane\npid 7\n")
        self.assertIn("rc=0", r.stdout)
        self.assertIn("out=[pane 7 squad:chrono -]", r.stdout)

    def test_start_fingerprint_round_trips_even_though_it_contains_spaces(self) -> None:
        # `start` is a kernel lstart string full of spaces; it must survive as the
        # single LAST field so discover_orchestrator can read it back whole and
        # hand it to pid_identity_still_matches().
        r = self._parse(
            "pid 4242\nshape pane\ntarget squad:chrono\nstart Sat Aug 30 18:16:50 2026\n"
        )
        self.assertIn("rc=0", r.stdout)
        self.assertIn("out=[pane 4242 squad:chrono Sat Aug 30 18:16:50 2026]", r.stdout)

    def test_missing_file_is_rc1(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope.pid"
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self.function_src
                + f'\nparse_coordinator_pidfile "{missing}"; echo "rc=$?"'
            )
            r = subprocess.run(
                ["bash", "-c", full], capture_output=True, text=True, timeout=15
            )
            self.assertIn("rc=1", r.stdout)

    def test_non_numeric_pid_rejected(self) -> None:
        r = self._parse("pid notapid\nshape pane\ntarget squad:chrono\n")
        self.assertIn("rc=1", r.stdout)
        self.assertIn("out=[]", r.stdout)

    def test_unknown_shape_rejected(self) -> None:
        # Only "pane" and "background-job" are valid; anything else means the
        # file is not one this reader understands, so it declines rather than
        # guessing.
        r = self._parse("pid 42\nshape daemon\ntarget squad:chrono\n")
        self.assertIn("rc=1", r.stdout)

    def test_missing_shape_rejected(self) -> None:
        r = self._parse("pid 42\ntarget squad:chrono\n")
        self.assertIn("rc=1", r.stdout)


class CoordinatorPidIsLiveClaudeTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's coordinator_pid_is_live_claude(), extracted
    verbatim, against real disposable processes. This is the identity check
    that keeps discovery from trusting a dead or recycled pidfile PID."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.function_src = _extract(
            SQUAD_STOP,
            r"\ncoordinator_pid_is_live_claude\(\) \{.*?\n\}\n",
            "coordinator_pid_is_live_claude()",
        )

    def _run(self, pid: int) -> subprocess.CompletedProcess:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            + self.function_src
            + f'\ncoordinator_pid_is_live_claude {pid}; echo "rc=$?"'
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=15
        )

    def test_live_claude_executable_matches(self) -> None:
        # A live process whose executable path contains /claude -- exactly what
        # the pane's coordinator child looks like (shared/chrono-pane.sh uses the
        # same */claude* glob). We name a throwaway script `claude` and run it by
        # absolute path so its argv[0] carries `/claude`.
        d = Path(tempfile.mkdtemp())
        fake = d / "claude"
        fake.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        fake.chmod(0o755)
        proc = subprocess.Popen([str(fake)])
        try:
            self.assertTrue(_wait_until(lambda: _pid_alive(proc.pid)))
            self.assertIn("rc=0", self._run(proc.pid).stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_unrelated_live_process_does_not_match(self) -> None:
        proc = subprocess.Popen(["sleep", "30"])
        try:
            self.assertIn("rc=1", self._run(proc.pid).stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_dead_pid_does_not_match(self) -> None:
        proc = subprocess.Popen(["true"])
        proc.wait(timeout=5)
        self.assertIn("rc=1", self._run(proc.pid).stdout)

    def test_non_numeric_pid_does_not_match(self) -> None:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            + self.function_src
            + '\ncoordinator_pid_is_live_claude "notapid"; echo "rc=$?"'
        )
        r = subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)
        self.assertIn("rc=1", r.stdout)


class DiscoverOrchestratorTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's discover_orchestrator() and
    orchestrator_report_line(), extracted verbatim, with the three leaf
    predicates STUBBED. This is the LIFE-01 routing proof: the two positive
    controls (pane, background-job) and the negative control (none) all fall out
    of the same reader, and their operator-facing lines are distinct."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.discover_src = _extract(
            SQUAD_STOP,
            r"\ndiscover_orchestrator\(\) \{.*?\n\}\n",
            "discover_orchestrator()",
        )
        cls.report_src = _extract(
            SQUAD_STOP,
            r"\norchestrator_report_line\(\) \{.*?\n\}\n",
            "orchestrator_report_line()",
        )

    def _discover(self, stubs: str, session: str = "squad", pidfile: str = "/x") -> str:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            f'SESSION="{session}"\nCHRONO_COORDINATOR_PIDFILE="{pidfile}"\n'
            + stubs
            + self.discover_src
            + self.report_src
            + "\ndiscover_orchestrator"
        )
        r = subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    @staticmethod
    def _stubs(
        pf_out: str,
        pf_rc: int,
        live_rc: int,
        pane_ok: str,
        identity_rc: int = 0,
        pane_ready: str = "1",
    ) -> str:
        # pane_ok is a case pattern (e.g. "squad:chrono") the pane predicate
        # returns 0 for; use "__none__" to make it always fail. identity_rc is
        # pid_identity_still_matches()'s result: 0 = still the same process
        # instance, non-0 = recycled/mismatch. pane_ready models CHRONO_PANE_READY
        # -- "1" means shared/chrono-pane.sh loaded, anything else means it did
        # not (so the recorded pane record becomes the independent authority).
        return (
            f'CHRONO_PANE_READY={pane_ready}\n'
            f'parse_coordinator_pidfile(){{ [[ {pf_rc} -eq 0 ]] || return 1; printf "%s\\n" "{pf_out}"; }}\n'
            f'coordinator_pid_is_live_claude(){{ return {live_rc}; }}\n'
            f'pid_identity_still_matches(){{ return {identity_rc}; }}\n'
            f'chrono_pane_has_coordinator(){{ case "$1" in {pane_ok}) return 0;; *) return 1;; esac; }}\n'
        )

    def test_positive_control_pane_hosted_orchestrator(self) -> None:
        # Pidfile names a live, identity-matched coordinator whose pane still
        # hosts it.
        out = self._discover(self._stubs("pane 4242 squad:chrono -", 0, 0, "squad:chrono"))
        self.assertEqual(out, "pane squad:chrono")

    def test_positive_control_background_job_orchestrator(self) -> None:
        # The shape LIFE-01 exists for: a live, identity-matched coordinator with
        # no pane. The reader discovers it from the pidfile even though no pane
        # hosts it.
        out = self._discover(self._stubs("background-job 5353 - -", 0, 0, "__none__"))
        self.assertEqual(out, "background-job 5353")

    def test_fallback_pane_scan_when_no_pidfile(self) -> None:
        # No usable pidfile (pf_rc=1): the backward-compatible path asks the
        # pane directly, so a pre-LIFE-01 session keeps working unchanged.
        out = self._discover(self._stubs("", 1, 1, "squad:chrono"))
        self.assertEqual(out, "pane squad:chrono")

    def test_negative_control_no_orchestrator(self) -> None:
        # No pidfile AND no coordinator in the pane: distinctly "none", never a
        # pane target that would then be nudged into a 60s timeout.
        out = self._discover(self._stubs("", 1, 1, "__none__"))
        self.assertEqual(out, "none")

    def test_stale_pane_pidfile_falls_through(self) -> None:
        # Pidfile says shape=pane but the coordinator no longer holds that pane
        # (exited/moved) and the helper is available (pane_ready=1). It must NOT
        # nudge the stale target; with nothing else live, discovery reports none.
        out = self._discover(self._stubs("pane 4242 squad:chrono -", 0, 0, "__none__"))
        self.assertEqual(out, "none")

    def test_dead_pidfile_pid_falls_through_to_pane_scan(self) -> None:
        # Pidfile PID is no longer a live claude (recycled/dead): ignore the
        # pidfile, fall back to the live pane scan.
        out = self._discover(self._stubs("pane 4242 squad:chrono -", 0, 1, "squad:chrono"))
        self.assertEqual(out, "pane squad:chrono")

    def test_custom_session_name_honored_in_fallback(self) -> None:
        out = self._discover(
            self._stubs("", 1, 1, "mysquad:chrono"), session="mysquad"
        )
        self.assertEqual(out, "pane mysquad:chrono")

    def test_recycled_pid_is_not_reported_as_background_job(self) -> None:
        # Defect 1, the worst of the three: a background-job pidfile whose PID was
        # recycled onto an unrelated live claude worker. is-live-claude PASSES (it
        # IS a live claude) but the start-time fingerprint MISMATCHES
        # (identity_rc=1), so discovery must fall through to none -- never a false
        # live background coordinator that a shutdown would then trust.
        out = self._discover(
            self._stubs("background-job 4242 - -", 0, 0, "__none__", identity_rc=1)
        )
        self.assertEqual(out, "none")

    def test_recycled_pid_pane_shape_falls_through_to_live_scan(self) -> None:
        # Same recycle, pane shape: identity mismatch means the pidfile is ignored
        # and the fresh live pane scan (the tmux authority) answers instead.
        out = self._discover(
            self._stubs("pane 4242 squad:chrono -", 0, 0, "squad:chrono", identity_rc=1)
        )
        self.assertEqual(out, "pane squad:chrono")

    def test_pane_pidfile_is_believed_when_the_pane_helper_failed_to_load(self) -> None:
        # Defect 3 / review P1: an identity-matched live claude recorded shape=pane
        # with a target, but shared/chrono-pane.sh could not load (pane_ready="0"),
        # so the pane predicate cannot confirm the child. The coordinator's own
        # PID+fingerprint IS an independent authority, so discovery trusts the
        # recorded target rather than collapsing a live coordinator into none.
        out = self._discover(
            self._stubs("pane 4242 squad:chrono -", 0, 0, "__none__", pane_ready="0")
        )
        self.assertEqual(out, "pane squad:chrono")

    def test_background_job_requires_a_live_claude(self) -> None:
        # Bounds the background-job claim in the other direction: a dead recorded
        # PID (live_rc=1) is never reported, even with a matching identity stub.
        out = self._discover(self._stubs("background-job 5353 - -", 0, 1, "__none__"))
        self.assertEqual(out, "none")

    def _report(self, shape: str, ref: str, session: str = "squad") -> str:
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            f'SESSION="{session}"\n'
            + self.report_src
            + f'\norchestrator_report_line "{shape}" "{ref}"'
        )
        r = subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)
        return r.stdout.strip()

    def test_three_report_lines_are_distinct(self) -> None:
        # The core LIFE-01 requirement: "no orchestrator" must not read like a
        # nudge timeout, and each outcome must be recognizably different.
        pane = self._report("pane", "squad:chrono")
        bg = self._report("background-job", "5353")
        none = self._report("none", "")
        self.assertEqual(len({pane, bg, none}), 3, "the three outcomes must differ")

    def test_none_report_disclaims_a_timeout(self) -> None:
        none = self._report("none", "")
        self.assertIn("NOT a nudge timeout", none)
        # And the two "found" outcomes must NOT falsely claim a timeout.
        self.assertNotIn("timeout", self._report("pane", "squad:chrono"))
        self.assertNotIn("timeout", self._report("background-job", "5353"))

    def test_background_job_report_says_not_nudgeable(self) -> None:
        bg = self._report("background-job", "5353")
        self.assertIn("BACKGROUND JOB", bg)
        self.assertIn("5353", bg)
        self.assertIn("cannot be nudged", bg)


class CoordinatorPidfileRoundTripTests(unittest.TestCase):
    """The coordinator (bin/vs-welcome.sh) writes the pidfile and the stopper
    (bin/squad-stop.sh) reads it; they must agree on the format AND on the
    start-time fingerprint or discovery silently breaks. Drives vs-welcome.sh's
    write_chrono_coordinator_pidfile() into squad-stop.sh's identity reader, all
    extracted verbatim, so the two ends cannot drift apart (CLAUDE.md rule 10,
    one home). The writer moved out of launch-squad.sh, which planted the pane's
    shell pid from outside -- a record the reader then rejected."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.writer_src = _extract(
            VS_WELCOME,
            r"\nwrite_chrono_coordinator_pidfile\(\) \{.*?\n\}\n",
            "write_chrono_coordinator_pidfile()",
        )
        cls.parse_src = _extract(
            SQUAD_STOP,
            r"\nparse_coordinator_pidfile\(\) \{.*?\n\}\n",
            "parse_coordinator_pidfile()",
        )
        cls.startfp_src = _extract(
            SQUAD_STOP, r"\npid_start_time\(\) \{.*?\n\}\n", "pid_start_time()"
        )
        cls.identity_src = _extract(
            SQUAD_STOP,
            r"\npid_identity_still_matches\(\) \{.*?\n\}\n",
            "pid_identity_still_matches()",
        )
        cls.islive_src = _extract(
            SQUAD_STOP,
            r"\ncoordinator_pid_is_live_claude\(\) \{.*?\n\}\n",
            "coordinator_pid_is_live_claude()",
        )

    def test_a_dead_pid_records_an_empty_start_sentinel_and_still_round_trips(self) -> None:
        # A pid with no live process records an empty start (ps returns nothing),
        # which parses back as the "-" sentinel -- the file still round-trips as
        # four positional fields.
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "sub" / "chrono.pid"  # writer must mkdir -p
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                f'CHRONO_COORDINATOR_PIDFILE="{pidfile}"\n'
                + self.writer_src
                + self.parse_src
                + f'\nwrite_chrono_coordinator_pidfile {dead.pid} "pane" "squad:chrono" || {{ echo "WRITE_FAILED"; exit 1; }}\n'
                'out="$(parse_coordinator_pidfile "$CHRONO_COORDINATOR_PIDFILE")"; echo "out=[$out]"'
            )
            r = subprocess.run(
                ["bash", "-c", full], capture_output=True, text=True, timeout=15
            )
            self.assertNotIn("WRITE_FAILED", r.stdout, r.stderr)
            self.assertIn(f"out=[pane {dead.pid} squad:chrono -]", r.stdout)

    def test_background_job_shape_round_trips(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "chrono.pid"
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                f'CHRONO_COORDINATOR_PIDFILE="{pidfile}"\n'
                + self.writer_src
                + self.parse_src
                + f'\nwrite_chrono_coordinator_pidfile {dead.pid} "background-job" ""\n'
                'out="$(parse_coordinator_pidfile "$CHRONO_COORDINATOR_PIDFILE")"; echo "out=[$out]"'
            )
            r = subprocess.run(
                ["bash", "-c", full], capture_output=True, text=True, timeout=15
            )
            self.assertIn(f"out=[background-job {dead.pid} - -]", r.stdout)

    def test_semantic_round_trip_a_live_claude_is_written_then_accepted(self) -> None:
        # The review's required SEMANTIC round-trip (not just a parse round-trip):
        # the writer records a REAL coordinator PID + start fingerprint, and the
        # reader's own identity checks ACCEPT it. A process named `claude`
        # (matching the */claude* glob) stands in for the coordinator; we spawn
        # and own it, and reap it ourselves.
        d = Path(tempfile.mkdtemp())
        fake = d / "claude"
        fake.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        fake.chmod(0o755)
        proc = subprocess.Popen([str(fake)])
        try:
            self.assertTrue(_wait_until(lambda: _pid_alive(proc.pid)))
            with tempfile.TemporaryDirectory() as td:
                pidfile = Path(td) / "chrono.pid"
                full = (
                    "#!/bin/bash\nset -uo pipefail\n"
                    f'CHRONO_COORDINATOR_PIDFILE="{pidfile}"\n'
                    + self.writer_src
                    + self.parse_src
                    + self.startfp_src
                    + self.identity_src
                    + self.islive_src
                    + f'\nwrite_chrono_coordinator_pidfile {proc.pid} "pane" "squad:chrono" || {{ echo WRITE_FAILED; exit 1; }}\n'
                    'parsed="$(parse_coordinator_pidfile "$CHRONO_COORDINATOR_PIDFILE")"\n'
                    'read -r shape pid target start <<<"$parsed"\n'
                    '[[ "$start" == "-" ]] && start=""\n'
                    'coordinator_pid_is_live_claude "$pid"; echo "islive=$?"\n'
                    'pid_identity_still_matches "$pid" "$start"; echo "identity=$?"\n'
                    'echo "shape=$shape target=$target"\n'
                    '[[ -n "$start" ]] && echo "start_present=1" || echo "start_present=0"\n'
                )
                r = subprocess.run(
                    ["bash", "-c", full], capture_output=True, text=True, timeout=20
                )
                self.assertNotIn("WRITE_FAILED", r.stdout, r.stderr)
                self.assertIn("islive=0", r.stdout, r.stderr)
                self.assertIn("identity=0", r.stdout, r.stderr)
                self.assertIn("shape=pane target=squad:chrono", r.stdout)
                self.assertIn("start_present=1", r.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class DiscoverRecycledPidIntegrationTests(unittest.TestCase):
    """Concrete recycled-PID proof for defect 1, driving the REAL identity leaves
    (not stubs): a live claude worker sits at the PID a now-dead background
    coordinator recorded, but the record carries the OLD coordinator's start
    fingerprint. is-live-claude passes (positive control: the PID really is a live
    claude, so a `none` result is the fingerprint check, not an absent process),
    yet discover_orchestrator reports none. The paired test proves the same path
    DOES discover the worker once the fingerprint matches, so the `none` above is
    a real red-capable check, not a green that can never fail."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.discover_src = _extract(
            SQUAD_STOP, r"\ndiscover_orchestrator\(\) \{.*?\n\}\n", "discover_orchestrator()"
        )
        cls.parse_src = _extract(
            SQUAD_STOP, r"\nparse_coordinator_pidfile\(\) \{.*?\n\}\n", "parse_coordinator_pidfile()"
        )
        cls.islive_src = _extract(
            SQUAD_STOP, r"\ncoordinator_pid_is_live_claude\(\) \{.*?\n\}\n", "coordinator_pid_is_live_claude()"
        )
        cls.startfp_src = _extract(
            SQUAD_STOP, r"\npid_start_time\(\) \{.*?\n\}\n", "pid_start_time()"
        )
        cls.identity_src = _extract(
            SQUAD_STOP, r"\npid_identity_still_matches\(\) \{.*?\n\}\n", "pid_identity_still_matches()"
        )

    def _spawn_fake_claude(self):
        d = Path(tempfile.mkdtemp())
        fake = d / "claude"
        fake.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        fake.chmod(0o755)
        proc = subprocess.Popen([str(fake)])
        self.assertTrue(_wait_until(lambda: _pid_alive(proc.pid)))
        return proc

    def _discover_with_real_leaves(self, pidfile: Path) -> subprocess.CompletedProcess:
        # No pane anywhere (helper stubbed to fail): the ONLY authority is the
        # pidfile PID, which is exactly the background-job case where identity has
        # to carry the whole weight.
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            'SESSION="squad"\nCHRONO_PANE_READY=1\n'
            f'CHRONO_COORDINATOR_PIDFILE="{pidfile}"\n'
            'chrono_pane_has_coordinator(){ return 1; }\n'
            + self.startfp_src
            + self.identity_src
            + self.islive_src
            + self.parse_src
            + self.discover_src
            + '\necho "discover=[$(discover_orchestrator)]"\n'
        )
        return subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=20
        )

    def test_recycled_claude_worker_is_not_a_false_live_background_coordinator(self) -> None:
        proc = self._spawn_fake_claude()
        try:
            with tempfile.TemporaryDirectory() as td:
                pidfile = Path(td) / "chrono.pid"
                stale_start = "Sat Aug 30 00:00:00 2000"  # the dead coordinator's; a value this worker cannot have
                pidfile.write_text(
                    f"pid {proc.pid}\nshape background-job\ntarget \nstart {stale_start}\n",
                    encoding="utf-8",
                )
                # positive control first: this PID really is a live claude.
                islive = subprocess.run(
                    [
                        "bash",
                        "-c",
                        "#!/bin/bash\nset -uo pipefail\n"
                        + self.islive_src
                        + f'\ncoordinator_pid_is_live_claude {proc.pid}; echo "islive=$?"',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertIn("islive=0", islive.stdout, islive.stderr)
                r = self._discover_with_real_leaves(pidfile)
                self.assertIn("discover=[none]", r.stdout, r.stderr)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_a_matching_fingerprint_IS_discovered(self) -> None:
        proc = self._spawn_fake_claude()
        try:
            real_start = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(proc.pid)],
                capture_output=True,
                text=True,
            ).stdout
            real_start = " ".join(real_start.split())  # same normalization as pid_start_time()
            with tempfile.TemporaryDirectory() as td:
                pidfile = Path(td) / "chrono.pid"
                pidfile.write_text(
                    f"pid {proc.pid}\nshape background-job\ntarget \nstart {real_start}\n",
                    encoding="utf-8",
                )
                r = self._discover_with_real_leaves(pidfile)
                self.assertIn(f"discover=[background-job {proc.pid}]", r.stdout, r.stderr)
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class SquadStopWiresDiscoveryTests(unittest.TestCase):
    """Guards against the extracted functions becoming dead code: the real
    bin/squad-stop.sh must actually source shared/chrono-pane.sh and route
    Phase 1 through discover_orchestrator, or these tests would be exercising
    logic the stopper does not use (the trap PidIsVsLaneStatusPollerTests names
    for its own predicate)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SQUAD_STOP.read_text(encoding="utf-8")

    def test_sources_chrono_pane_helper(self) -> None:
        self.assertIn("shared/chrono-pane.sh", self.text)
        self.assertIn("chrono_pane_has_coordinator", self.text)

    def test_phase_one_calls_discover_orchestrator(self) -> None:
        self.assertIn('discovered="$(discover_orchestrator)"', self.text)

    def test_nudge_targets_discovered_ref_not_hardcoded_pane(self) -> None:
        # The nudge must go to the DISCOVERED target, and only in the pane
        # branch -- never unconditionally to a fixed ${SESSION}:chrono.
        self.assertIn('tmux send-keys -l -t "${orch_ref}"', self.text)
        self.assertNotIn('tmux send-keys -l -t "${SESSION}:chrono"', self.text)

    def test_vs_welcome_selects_shape_from_tmux_and_records_its_own_pid(self) -> None:
        # Guards the coordinator-side wiring from becoming dead code: vs-welcome
        # records its OWN pid ($$, which the exec below turns into claude) and
        # picks the shape from the environment -- pane inside tmux, background-job
        # outside. Without the background-job branch, defect 2 (a real background
        # coordinator reported as none) could never be fed a record.
        welcome = VS_WELCOME.read_text(encoding="utf-8")
        self.assertIn('write_chrono_coordinator_pidfile "$$"', welcome)
        self.assertIn('if [[ -n "${TMUX:-}" ]]; then', welcome)
        self.assertIn('_vs_shape="pane"', welcome)
        self.assertIn('_vs_shape="background-job"', welcome)

    def test_the_coordinator_startup_writes_the_pidfile(self) -> None:
        # LIFE-01 rework: the writer moved OUT of launch-squad.sh (which planted
        # the pane's shell pid from outside -- a record squad-stop then rejected)
        # and INTO bin/vs-welcome.sh, the coordinator's own startup, which records
        # its real PID + start fingerprint. One writer, one home.
        welcome = VS_WELCOME.read_text(encoding="utf-8")
        self.assertIn("write_chrono_coordinator_pidfile", welcome)
        self.assertIn("CHRONO_COORDINATOR_PIDFILE", welcome)
        # And launch-squad must no longer define a competing writer.
        launch = LAUNCH_SQUAD.read_text(encoding="utf-8")
        self.assertNotIn("write_chrono_coordinator_pidfile()", launch)


class CoordinatorExitCaptureTests(unittest.TestCase):
    """LIFE-03: bin/vs-welcome.sh must record the coordinator's dying breath so
    the next crash-on-exit is not lost the way the reported one was (a prior
    six-sink search found it in NO durable sink). The capture tees claude's
    stderr into a per-session file prepared by prepare_coordinator_exit_log().

    Like every other class here this NEVER runs bin/vs-welcome.sh itself -- it
    execs claude, and the LIFE-03 hard boundary forbids running it while board
    lanes are live -- so the pure function is extracted verbatim and driven with
    synthetic args, and the tee construct is exercised against a throwaway fake
    `claude` this test writes and owns (never the real one, never via tmux)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prepare_src = _extract(
            VS_WELCOME,
            r"\nprepare_coordinator_exit_log\(\) \{.*?\n\}\n",
            "prepare_coordinator_exit_log()",
        )

    def _run(self, body: str, exit_dir: Path):
        script = "#!/bin/bash\nset -uo pipefail\n" + self.prepare_src + "\n" + body
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "CHRONO_COORDINATOR_EXIT_DIR": str(exit_dir)},
        )

    def test_prepare_writes_an_identifying_header_and_returns_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            exit_dir = Path(d) / "exit"  # writer must mkdir -p
            r = self._run(
                'prepare_coordinator_exit_log "squad" "pane" "squad:chrono" 4242\n',
                exit_dir,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            logpath = r.stdout.strip()
            self.assertTrue(logpath, "expected the capture-file path on stdout")
            p = Path(logpath)
            self.assertTrue(p.is_file(), f"{logpath} was not created")
            # The filename carries session + pid so a crashed session is
            # correlatable to its coordinator without opening the file.
            self.assertTrue(p.name.startswith("squad-"))
            self.assertTrue(p.name.endswith("-4242.log"))
            header = p.read_text(encoding="utf-8")
            self.assertIn("pid 4242", header)
            self.assertIn("shape pane", header)
            self.assertIn("target squad:chrono", header)
            # The delimiter after which claude's own stderr is appended.
            self.assertIn("claude-stderr-follows", header)

    def test_prepare_records_the_none_sentinel_for_a_shapeless_background_job(self) -> None:
        # A background-job coordinator has no pane target; the header must still
        # be well formed rather than emitting an empty/ragged field.
        with tempfile.TemporaryDirectory() as d:
            r = self._run(
                'prepare_coordinator_exit_log "squad" "background-job" "" 5150\n',
                Path(d) / "exit",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            header = Path(r.stdout.strip()).read_text(encoding="utf-8")
            self.assertIn("shape background-job", header)
            self.assertIn("target <none>", header)

    def test_prepare_fails_safe_when_the_durable_dir_cannot_be_made(self) -> None:
        # The whole point of the rc1 contract: a capture that cannot prepare its
        # file returns nonzero and NOTHING on stdout, so vs-welcome falls to the
        # bare exec and the coordinator launches exactly as before. Force the
        # failure by rooting the dir under a regular FILE (mkdir -p must fail
        # "Not a directory") -- deterministic and portable.
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "afile"
            blocker.write_text("a file, not a directory\n", encoding="utf-8")
            r = self._run(
                'if out="$(prepare_coordinator_exit_log squad pane "" 1)"; then\n'
                '  echo "UNEXPECTED_RC0 out=[$out]"\n'
                "else\n"
                '  echo "FAILSAFE_RC1 out=[$out]"\n'
                "fi\n",
                blocker / "sub",
            )
            self.assertIn("FAILSAFE_RC1 out=[]", r.stdout, r.stderr)
            self.assertNotIn("UNEXPECTED_RC0", r.stdout)

    def test_stderr_is_teed_into_the_capture_file_and_the_code_reaches_the_parent(self) -> None:
        # Exercises the launch CONSTRUCT itself -- `exec <claude> 2> >(tee -a LOG
        # >&2)` -- not vs-welcome.sh. A dying claude's stderr must land durably in
        # the file (append, not truncate), AND the child's real exit code must
        # still reach whoever waits on it. In production that waiter is the pane
        # shell (bin/launch-squad.sh), which is why the numeric code lives there,
        # not in this direct-child exec. Fake `claude` is written and owned here.
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "claude"
            fake.write_text(
                "#!/bin/bash\n"
                "echo 'FATAL: coordinator died at shutdown' >&2\n"
                "exit 37\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            log = Path(d) / "capture.log"
            log.write_text("pre-existing-header\n", encoding="utf-8")  # we append
            construct = f'exec "{fake}" 2> >(tee -a "{log}" >&2)'
            r = subprocess.run(
                ["bash", "-c", construct], capture_output=True, text=True, timeout=15
            )
            self.assertEqual(
                r.returncode, 37, "the child's exit code must reach its parent"
            )
            # tee is orphaned when the exec'd child dies; wait for its flush.
            self.assertTrue(
                _wait_until(
                    lambda: "FATAL: coordinator died at shutdown"
                    in log.read_text(encoding="utf-8")
                ),
                f"stderr was not teed into the capture file; got {log.read_text()!r}",
            )
            body = log.read_text(encoding="utf-8")
            self.assertIn("pre-existing-header", body)  # appended, not truncated

    def test_vs_welcome_wires_the_capture_and_keeps_claude_a_direct_exec_child(self) -> None:
        # Guards the wiring from becoming dead code, and guards the single most
        # important invariant: claude is STILL exec'd (both the teed branch and
        # the fail-safe branch), so it stays the pane shell's DIRECT child and
        # `pgrep -P` coordinator detection in shared/chrono-pane.sh -- and thus
        # squad-stop / outbox-watcher / squad-monitor discovery -- is unchanged.
        welcome = VS_WELCOME.read_text(encoding="utf-8")
        self.assertIn("prepare_coordinator_exit_log", welcome)
        self.assertIn('2> >(tee -a "${_vs_exit_log}" >&2)', welcome)
        # Two exec branches: the teed launch and the unteed fail-safe launch.
        self.assertEqual(welcome.count("exec env -u ANTHROPIC_API_KEY"), 2)
        # The pidfile identity ($$ -> claude via exec) is untouched.
        self.assertIn('write_chrono_coordinator_pidfile "$$"', welcome)


class CoordinatorExitCodeCaptureTests(unittest.TestCase):
    """LIFE-03b: vs-welcome.sh tees claude's stderr into a per-session file, but
    it `exec`s claude, so nothing there waits on it and the numeric exit CODE /
    signal cannot be captured. The PANE SHELL in bin/launch-squad.sh runs
    `bash vs-welcome.sh`, which execs claude in place, so the pane shell is
    claude's real parent and its `$?` IS claude's own exit status. This class
    drives the recorder that appends that code -- with a matching header -- to
    the SAME per-session file the stderr capture uses.

    Like every other class here this NEVER runs bin/launch-squad.sh or
    bin/vs-welcome.sh (they exec claude / create the live squad session, and the
    LIFE-03 hard boundary forbids running them while board lanes are live).
    Instead the pure emitter build_coordinator_exit_capture() is extracted
    verbatim, run to PRODUCE the one-line pane command, and that command is then
    evaluated with `$?` preset -- against a throwaway exit dir + pidfile + capture
    file this test writes and owns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.build_src = _extract(
            LAUNCH_SQUAD,
            r"\nbuild_coordinator_exit_capture\(\) \{.*?\n\}\n",
            "build_coordinator_exit_capture()",
        )

    def _emit(self, exit_dir: Path, session: str, pidfile: Path) -> str:
        """Run the extracted emitter to get the exact one-line pane command."""
        call = "build_coordinator_exit_capture {} {} {}".format(
            shlex.quote(str(exit_dir)), shlex.quote(session), shlex.quote(str(pidfile))
        )
        r = subprocess.run(
            ["bash", "-c", self.build_src + "\n" + call + "\n"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def _drive(self, cmd: str, rc: int):
        """Evaluate the emitted command with `$?` preset to rc (as the pane shell
        sees it the instant `bash vs-welcome.sh` returns), and report the
        recorder's OWN exit status back via a marker."""
        driver = "( exit {} ); {}; echo \"REC_RC=$?\"".format(rc, cmd)
        return subprocess.run(
            ["bash", "-c", driver], capture_output=True, text=True, timeout=15
        )

    def _synthetic(self, root: Path, session: str = "squad", pid: int = 71604):
        """A vs-welcome-style capture file (the stderr 'first half') plus the
        coordinator pidfile that names the same pid -- the identity link the pane
        shell follows to find the file to append to."""
        exit_dir = root / "exit"
        exit_dir.mkdir(parents=True)
        capture = exit_dir / f"{session}-20260830T235502Z-{pid}.log"
        capture.write_text(
            "coordinator-session-start 2026-08-30T23:55:02Z\n"
            f"pid {pid}\n"
            "shape pane\n"
            "target squad:chrono\n"
            "start Sun Aug 30 16:55:02 2026\n"
            "claude-stderr-follows ----------\n"
            "PANIC: uncaught TypeError at foo.js:42\n",
            encoding="utf-8",
        )
        pidfile = root / f"{session}.pid"
        pidfile.write_text(
            f"pid {pid}\nshape pane\ntarget squad:chrono\nstart x\n", encoding="utf-8"
        )
        return exit_dir, pidfile, capture

    def test_command_is_a_single_line_for_send_keys(self) -> None:
        # launch-squad.sh appends this after `bash vs-welcome.sh;` in ONE
        # tmux send-keys ... C-m. An embedded newline would execute a partial
        # command in the pane, so the emitter must produce exactly one line.
        with tempfile.TemporaryDirectory() as d:
            cmd = self._emit(Path(d) / "exit", "squad", Path(d) / "squad.pid")
        self.assertNotIn("\n", cmd, "the pane command must be a single line")
        self.assertTrue(cmd.startswith("__vsrc=$?"), "must snapshot $? FIRST")
        self.assertTrue(cmd.rstrip().endswith("|| true"), "must be fail-safe")

    def test_records_a_non_zero_exit_code(self) -> None:
        # "A pane process exiting non-zero leaves the code in the record."
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile, capture = self._synthetic(Path(d))
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 37)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)  # recorder is fail-safe
            body = capture.read_text(encoding="utf-8")
            self.assertIn("coordinator-session-exit ", body)
            self.assertIn("exit-status 37", body)
            self.assertIn("exit-signal none", body)
            # Both halves landed in ONE file and read as one record.
            self.assertIn("claude-stderr-follows", body)
            self.assertLess(
                body.index("claude-stderr-follows"), body.index("coordinator-session-exit")
            )

    def test_records_the_signal_on_a_signal_death(self) -> None:
        # "A pane process killed by a signal records the signal." bash reports a
        # signal death as 128+signum; the recorder decodes that mechanically.
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile, capture = self._synthetic(Path(d))
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 139)  # 128 + 11 (SIGSEGV)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            body = capture.read_text(encoding="utf-8")
            self.assertIn("exit-status 139", body)
            self.assertIn("exit-signal 11", body)  # number is portable
            self.assertIn("SEGV", body)  # kill -l 11 -> SEGV on macOS + Linux

    def test_records_a_clean_exit_without_a_signal(self) -> None:
        # "A clean exit still records normally and is not slowed."
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile, capture = self._synthetic(Path(d))
            cmd = self._emit(exit_dir, "squad", pidfile)
            start = time.monotonic()
            r = self._drive(cmd, 0)
            elapsed = time.monotonic() - start
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            body = capture.read_text(encoding="utf-8")
            self.assertIn("exit-status 0", body)
            self.assertIn("exit-signal none", body)
            self.assertNotIn("exit-status 139", body)
            self.assertLess(elapsed, 5.0, "the clean path must not be slow")

    def test_fail_safe_when_the_capture_path_is_broken(self) -> None:
        # Negative control: break the capture path deliberately (pidfile under a
        # dir that does not exist). The recorder must still return 0 so the pane
        # exits normally, and append nothing anywhere.
        with tempfile.TemporaryDirectory() as d:
            exit_dir, _pidfile, capture = self._synthetic(Path(d))
            before = capture.read_text(encoding="utf-8")
            missing_pidfile = Path(d) / "nope" / "squad.pid"  # parent absent
            cmd = self._emit(exit_dir, "squad", missing_pidfile)
            r = self._drive(cmd, 139)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertEqual(
                capture.read_text(encoding="utf-8"),
                before,
                "a broken capture must not touch any file",
            )

    def test_fail_safe_when_vs_welcome_prepared_no_capture_file(self) -> None:
        # The other negative control: the pidfile exists (vs-welcome ran) but NO
        # capture file was prepared because vs-welcome took its fail-safe bare
        # exec. The recorder finds nothing to append to and still returns 0.
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile, capture = self._synthetic(Path(d))
            capture.unlink()  # no capture file for this run
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 37)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertFalse(
                any(exit_dir.iterdir()), "nothing should be created when no file exists"
            )

    def test_launch_squad_wires_the_capture_after_vs_welcome(self) -> None:
        # Guards the wiring from becoming dead code: launch-squad.sh must BUILD
        # the recorder and append it to the SAME send-keys that runs vs-welcome,
        # so the pane shell -- claude's real parent -- runs it right after claude
        # exits. The `;` (not a wrapper) is what keeps claude a DIRECT exec child.
        launch = LAUNCH_SQUAD.read_text(encoding="utf-8")
        self.assertIn("build_coordinator_exit_capture()", launch)  # defined
        self.assertIn(
            'COORDINATOR_EXIT_CAPTURE="$(build_coordinator_exit_capture', launch
        )
        self.assertIn(
            'bash ${VAULT_ROOT}/bin/vs-welcome.sh; ${COORDINATOR_EXIT_CAPTURE}"',
            launch,
        )
        # The exit dir + pidfile defaults must match vs-welcome's, so both halves
        # of the record land in one file.
        self.assertIn(
            "chrono-coordinator/exit", launch
        )
        self.assertIn(
            "chrono-coordinator/${SESSION}.pid", launch
        )


class CoordinatorPidfileClearTests(unittest.TestCase):
    """LIFE-03c: the coordinator exit recorder in bin/launch-squad.sh also CLEARS
    the coordinator pidfile on the way out -- but ONLY when the recorded process
    is provably gone. It carries a byte-faithful copy of bin/squad-stop.sh's
    pid_start_time / pid_identity_still_matches inside the one-line pane command
    (a fresh pane shell cannot source squad-stop.sh -- that would run the whole
    stop) and reuses THAT identity scheme, rather than inventing a second one.

    Like the sibling classes this NEVER runs bin/launch-squad.sh or vs-welcome.sh
    (they exec claude / create the live squad session). It extracts the pure
    emitter, runs it to produce the one-line pane command, and drives that command
    against throwaway pidfiles + real, self-spawned processes it owns and reaps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.build_src = _extract(
            LAUNCH_SQUAD,
            r"\nbuild_coordinator_exit_capture\(\) \{.*?\n\}\n",
            "build_coordinator_exit_capture()",
        )
        # The canonical identity check, extracted from its one home, so the
        # equivalence test drives the SAME bytes the launch-squad copy mirrors.
        cls.identity_src = _extract(
            SQUAD_STOP,
            r"\npid_start_time\(\) \{.*?\n\}\n",
            "pid_start_time()",
        ) + _extract(
            SQUAD_STOP,
            r"\npid_identity_still_matches\(\) \{.*?\n\}\n",
            "pid_identity_still_matches()",
        )

    def setUp(self) -> None:
        self._procs: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for p in self._procs:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass

    # -- helpers ------------------------------------------------------------
    def _emit(self, exit_dir: Path, session: str, pidfile: Path) -> str:
        call = "build_coordinator_exit_capture {} {} {}".format(
            shlex.quote(str(exit_dir)), shlex.quote(session), shlex.quote(str(pidfile))
        )
        r = subprocess.run(
            ["bash", "-c", self.build_src + "\n" + call + "\n"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def _drive(self, cmd: str, rc: int):
        driver = "( exit {} ); {}; echo \"REC_RC=$?\"".format(rc, cmd)
        return subprocess.run(
            ["bash", "-c", driver], capture_output=True, text=True, timeout=15
        )

    def _spawn_live(self) -> int:
        """A real, long-lived process this test owns; reaped in tearDown."""
        p = subprocess.Popen(["sleep", "60"])
        self._procs.append(p)
        return p.pid

    def _norm_lstart(self, pid: int) -> str:
        """The recorded start fingerprint, via the SAME `ps -o lstart=` pipeline
        vs-welcome.sh / squad-stop.sh use -- so a match is a real match."""
        r = subprocess.run(
            [
                "bash",
                "-c",
                'ps -o lstart= -p "$1" 2>/dev/null | tr -s "[:space:]" " " '
                '| sed "s/^ //; s/ $//"',
                "_",
                str(pid),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.stdout.rstrip("\n")

    def _pidfile(self, root: Path, pid, start: str, *, with_log: bool = True):
        """A vs-welcome-shaped exit dir + pidfile naming `pid` with fingerprint
        `start`. Returns (exit_dir, pidfile)."""
        exit_dir = root / "exit"
        exit_dir.mkdir(parents=True, exist_ok=True)
        if with_log:
            (exit_dir / f"squad-20260830T235502Z-{pid}.log").write_text(
                "coordinator-session-start 2026-08-30T23:55:02Z\n"
                f"pid {pid}\nshape pane\ntarget squad:chrono\n"
                f"start {start}\nclaude-stderr-follows ----------\n",
                encoding="utf-8",
            )
        pidfile = root / "squad.pid"
        pidfile.write_text(
            f"pid {pid}\nshape pane\ntarget squad:chrono\nstart {start}\n",
            encoding="utf-8",
        )
        return exit_dir, pidfile

    # -- proofs -------------------------------------------------------------
    def test_normal_exit_clears_the_pidfile_and_records_the_end(self) -> None:
        # "A coordinator exiting normally leaves NO squad.pid, and its exit
        # record carries the end." The recorded pid is dead (999995 is not live),
        # so its identity cannot match -> the record is stale -> cleared.
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile = self._pidfile(
                Path(d), 999995, "Sun Aug 30 16:55:02 2026"
            )
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 0)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertFalse(pidfile.exists(), "a clean exit must clear squad.pid")
            body = next(exit_dir.glob("*.log")).read_text(encoding="utf-8")
            self.assertIn("coordinator-session-exit ", body)
            self.assertIn("exit-status 0", body)
            self.assertIn("exit-signal none", body)

    def test_signal_death_clears_the_pidfile_and_records_the_signal(self) -> None:
        # "A coordinator killed by a signal does the same -- the record shows the
        # signal." bash reports a signal death as 128+signum.
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile = self._pidfile(
                Path(d), 999994, "Sun Aug 30 16:55:02 2026"
            )
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 139)  # 128 + 11 (SIGSEGV)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertFalse(pidfile.exists(), "a signal death must clear squad.pid")
            body = next(exit_dir.glob("*.log")).read_text(encoding="utf-8")
            self.assertIn("exit-status 139", body)
            self.assertIn("exit-signal 11", body)
            self.assertIn("SEGV", body)

    def test_a_different_live_coordinators_pidfile_is_not_cleared(self) -> None:
        # NEGATIVE CONTROL. A pidfile written for a DIFFERENT, still-live process
        # with its real fingerprint must SURVIVE -- clearing a live coordinator's
        # file is far worse than leaving a stale one.
        live = self._spawn_live()
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile = self._pidfile(
                Path(d), live, self._norm_lstart(live), with_log=False
            )
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 0)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertTrue(
                pidfile.exists(),
                "a live, fingerprint-matched coordinator's pidfile must be kept",
            )

    def test_a_recycled_pid_with_a_stale_fingerprint_is_cleared(self) -> None:
        # The fingerprint is LOAD-BEARING: the recorded PID is alive, but it was
        # recycled onto a different process (its start time no longer matches the
        # recorded one), so the recorded coordinator is gone -> cleared.
        live = self._spawn_live()
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile = self._pidfile(
                Path(d), live, "Wed Jan  1 00:00:00 2020", with_log=False
            )
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 0)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertFalse(
                pidfile.exists(),
                "a live PID whose fingerprint no longer matches is stale -> cleared",
            )

    def test_a_live_pid_without_a_recorded_fingerprint_is_kept(self) -> None:
        # Fail-safe: a live PID we CANNOT positively judge stale (no recorded
        # fingerprint) is left alone rather than risk clearing a live file.
        live = self._spawn_live()
        with tempfile.TemporaryDirectory() as d:
            exit_dir, pidfile = self._pidfile(Path(d), live, "", with_log=False)
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 0)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            self.assertTrue(
                pidfile.exists(),
                "a live but unfingerprintable pidfile must be kept (fail safe)",
            )

    def test_a_broken_clear_still_exits_cleanly(self) -> None:
        # FAIL-SAFE CONTROL. Break the clear deliberately: the recorded pid is
        # dead (so the file WOULD be cleared) but its directory is read-only, so
        # `find -delete` cannot remove it. The recorder must still return 0.
        if os.geteuid() == 0:
            self.skipTest("root ignores directory write permissions")
        with tempfile.TemporaryDirectory() as d:
            pdir = Path(d) / "pdir"
            pdir.mkdir()
            pidfile = pdir / "squad.pid"
            pidfile.write_text(
                "pid 999993\nshape pane\ntarget squad:chrono\n"
                "start Sun Aug 30 16:55:02 2026\n",
                encoding="utf-8",
            )
            exit_dir = Path(d) / "exit"
            exit_dir.mkdir()
            os.chmod(pdir, 0o500)  # no write -> deletion of the file is refused
            try:
                cmd = self._emit(exit_dir, "squad", pidfile)
                r = self._drive(cmd, 0)
                self.assertIn(
                    "REC_RC=0", r.stdout, "a broken clear must not affect exit"
                )
                self.assertTrue(
                    pidfile.exists(), "the clear failed, as this control intends"
                )
            finally:
                os.chmod(pdir, 0o700)

    def test_the_pidfile_parse_is_order_independent(self) -> None:
        # vs-welcome writes pid FIRST today, but the clear must not depend on line
        # order -- parse_coordinator_pidfile does not. A start-first file must
        # still yield the pid (record appended) and the fingerprint (clear runs).
        with tempfile.TemporaryDirectory() as d:
            exit_dir = Path(d) / "exit"
            exit_dir.mkdir()
            (exit_dir / "squad-20260830T235502Z-999992.log").write_text(
                "coordinator-session-start x\npid 999992\nshape pane\n"
                "target squad:chrono\nstart Sun Aug 30 16:55:02 2026\n"
                "claude-stderr-follows ----------\n",
                encoding="utf-8",
            )
            pidfile = Path(d) / "squad.pid"
            pidfile.write_text(
                "start Sun Aug 30 16:55:02 2026\nshape pane\n"
                "target squad:chrono\npid 999992\n",
                encoding="utf-8",
            )
            cmd = self._emit(exit_dir, "squad", pidfile)
            r = self._drive(cmd, 7)
            self.assertIn("REC_RC=0", r.stdout, r.stderr)
            body = next(exit_dir.glob("*.log")).read_text(encoding="utf-8")
            self.assertIn("exit-status 7", body, "pid parsed despite start-first order")
            self.assertFalse(pidfile.exists(), "fingerprint parsed -> dead pid cleared")

    def test_emitted_command_reuses_the_canonical_identity_function(self) -> None:
        # Reuse, not reinvention: the emitted pane command must CALL
        # pid_identity_still_matches (the same name as squad-stop.sh's), not roll
        # a private pid-only or etime-based check.
        with tempfile.TemporaryDirectory() as d:
            cmd = self._emit(Path(d) / "exit", "squad", Path(d) / "squad.pid")
        self.assertIn("pid_identity_still_matches", cmd)
        self.assertIn("pid_start_time", cmd)
        self.assertIn("ps -o lstart=", cmd, "must use the lstart fingerprint")

    def _canonical_verdict(self, pid, start: str) -> int:
        """Run squad-stop.sh's OWN pid_identity_still_matches on (pid,start) and
        return its rc -- 0 = still the recorded live process."""
        script = (
            self.identity_src
            + f'\npid_identity_still_matches {shlex.quote(str(pid))} '
            + f'{shlex.quote(start)}; echo "RC=$?"\n'
        )
        r = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=10
        )
        m = re.search(r"RC=(\d+)", r.stdout)
        self.assertIsNotNone(m, r.stdout + r.stderr)
        return int(m.group(1))

    def test_clear_decision_agrees_with_the_canonical_identity_function(self) -> None:
        # Equivalence guard for the rule-10 duplicate: for a matrix of inputs, the
        # pane command's KEEP/CLEAR must agree with squad-stop.sh's own
        # pid_identity_still_matches verdict -- KEEP iff it says "still live and
        # matched". (The one deliberate exception, a live PID with no recorded
        # fingerprint, is covered by its own fail-safe test above.)
        live = self._spawn_live()
        good_fp = self._norm_lstart(live)
        cases = [
            ("live+match", live, good_fp),
            ("live+mismatch", live, "Wed Jan  1 00:00:00 2020"),
            ("dead", 999991, "Sun Aug 30 16:55:02 2026"),
        ]
        for name, pid, start in cases:
            with self.subTest(case=name):
                verdict_is_live = self._canonical_verdict(pid, start) == 0
                with tempfile.TemporaryDirectory() as d:
                    exit_dir, pidfile = self._pidfile(
                        Path(d), pid, start, with_log=False
                    )
                    cmd = self._emit(exit_dir, "squad", pidfile)
                    r = self._drive(cmd, 0)
                    self.assertIn("REC_RC=0", r.stdout, r.stderr)
                    kept = pidfile.exists()
                    self.assertEqual(
                        kept,
                        verdict_is_live,
                        f"{name}: pane KEEP({kept}) must equal canonical "
                        f"live-verdict({verdict_is_live})",
                    )


if __name__ == "__main__":
    unittest.main()
