#!/usr/bin/env python3
"""Plan B Task 1: two concurrent `squad up` must produce exactly one coordinator.

docs/superpowers/sdd/2026-08-17-plan-B-stop-lying-about-state/task-1-brief.md

bin/launch-squad.sh uses `set -uo pipefail` -- no `-e` -- and used to never
check `tmux new-session`'s exit status. Two concurrent `squad up` runs both
pass the `has-session` guard (neither session exists yet), both call
`tmux new-session`, and the loser fell straight through into the winner's
live session and typed `bash vs-welcome.sh` (execs claude) into its pane: a
second live Chrono on top of the first. The fix has two parts, tested here:

  1. An exit-status check on `tmux new-session` (the safe half -- closes the
     bug on its own, zero deadlock risk).
  2. LAUNCH_LOCK, a filesystem mutex serializing the has-session decision, so
     the loser reattaches instead of erroring, AND -- the highest-risk part
     of this remediation per adversarial review -- must never be acquired by
     the `--watcher-fleet-child` re-invocation. If it were, a parent holding
     LAUNCH_LOCK while polling that child's health, and the child blocked
     forever acquiring its own parent's lock, would deadlock forever and no
     fresh `squad up` would ever converge again.

SAFETY, read before touching any test in this file
--------------------------------------------------
`ensure_watcher_fleet()`'s repair path (`stop_watcher_fleet` ->
`watcher_cleanup_pids` -> `watcher_seed`) selects processes by argv. A
throwaway session's `watcher_fleet_healthy()` is unconditionally false the
first time (no window 5 yet), so it ALWAYS reaches `stop_watcher_fleet()`.

When this file was written that match had no VAULT_ROOT scoping at all, and
one test run killed the real, live `squad` session's window 5 outright --
through an "isolated" VAULT_ROOT + fake HOME + isolated TMUX_TMPDIR, none of
which constrain a host-wide argv scan.

VAULT_ROOT scoping landed with Plan B Task 8, so the cross-CHECKOUT blast
radius is closed. The sweep is still deliberately root-wide across SESSIONS
(see "SCOPE OF THE SWEEP" in bin/launch-squad.sh for why), and a throwaway
SQUAD_SESSION against the LIVE checkout is precisely that case -- which is
what these subprocesses are. So the seam below is still mandatory here.

Every subprocess in this file therefore sets SQUAD_SKIP_WATCHER_FLEET=1 (a
seam added to launch-squad.sh for exactly this reason -- see the comment at
the top of `ensure_watcher_fleet()`) and never removes it. The one exception,
`test_watcher_fleet_child_never_blocks_on_launch_lock`, proves the deadlock
property directly and more precisely than an integration run could: it never
starts a coordinator session and never lets `ensure_watcher_fleet()` run at
all, so it needs no such seam.

Independently, and IN ADDITION to the watcher-fleet seam above, every
subprocess also gets: a throwaway SQUAD_SESSION name (never "squad"), an
isolated TMUX_TMPDIR (a wholly separate tmux server -- confirmed empirically
that a fresh server correctly captures the launching process's own
environment, including HOME, into new sessions), an rsync'd isolated
VAULT_ROOT copy of the repo (reflecting this checkout's current file state,
including uncommitted edits under test), and a fake HOME whose only content
is a `claude` stub -- vs-welcome.sh `exec`s the coordinator via the
HARD-CODED path `${HOME}/.local/bin/claude`, not a PATH lookup, so the real
Max-plan `claude` binary is structurally unreachable regardless of PATH.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LAUNCH_SQUAD = REPO / "bin" / "launch-squad.sh"
LAUNCH_DEPENDENCIES = REPO / "shared" / "launch-dependencies.sh"

# `rsync` copies the isolated VAULT_ROOT and `bash` runs the launcher: harness
# dependencies, not launcher ones, so they are named separately from the list
# below and reported separately when missing.
HARNESS_COMMANDS = ("rsync", "bash")


def _launcher_required_commands() -> tuple[str, ...]:
    """Read SQUAD_REQUIRED_COMMANDS out of the launcher's own dependency file.

    Parsed rather than copied (CLAUDE.md rule 10). bin/launch-squad.sh REFUSES
    to start when any of these is absent, so a host without them cannot reach
    a single line this file asserts about -- and a second, drifting copy of the
    list here would eventually gate on the wrong set.
    """
    source = LAUNCH_DEPENDENCIES.read_text(encoding="utf-8")
    match = re.search(r"^SQUAD_REQUIRED_COMMANDS=\(([^)]*)\)", source, re.MULTILINE)
    if match is None:
        raise AssertionError(
            f"{LAUNCH_DEPENDENCIES} no longer declares SQUAD_REQUIRED_COMMANDS=(...); "
            "the skip guard below would gate on an empty list and silently run "
            "these tests on a host that cannot launch."
        )
    commands = tuple(match.group(1).split())
    if not commands:
        raise AssertionError(
            f"{LAUNCH_DEPENDENCIES} declares an empty SQUAD_REQUIRED_COMMANDS"
        )
    return commands


def _missing_launch_prerequisites() -> list[str]:
    missing = [
        f"{name} (launcher)"
        for name in _launcher_required_commands()
        if shutil.which(name) is None
    ]
    missing += [
        f"{name} (harness)"
        for name in HARNESS_COMMANDS
        if shutil.which(name) is None
    ]
    return missing


MISSING_LAUNCH_PREREQUISITES = _missing_launch_prerequisites()

# Large, irrelevant to launch-squad.sh's own logic, or (departments/) freshly
# recreated by the launcher itself for every namespace via `mkdir -p`, so the
# real mailbox content is never needed by anything this file exercises.
RSYNC_EXCLUDES = [".git", "_state", "tools", "moat", "departments", ".claude", ".venv"]

# AF_UNIX socket paths are length-limited (~104 bytes on macOS). Neither the
# project's own scratchpad convention nor $TMPDIR (macOS: a long
# /var/folders/.../T/ path) leaves enough headroom once tmux appends its own
# "/tmux-<uid>/default" suffix, so TMUX_TMPDIR -- and only TMUX_TMPDIR --
# deliberately lives directly under /tmp instead. Nothing else in this file
# writes there.
TMUX_SOCKET_ROOT = Path("/tmp")

# LAUNCH_LOCK's path, relative to VAULT_ROOT. Must match bin/launch-squad.sh's
# own `LAUNCH_LOCK="${VAULT_ROOT}/_state/runtime/vibesquad-launch-${SESSION}.lockdir"`
# exactly, or the deadlock test below holds a directory nothing reads.
#
# It used to be computed as `${TMPDIR:-/tmp}/vibesquad-launch-<session>.lockdir`,
# which is where the lock lived until de47deb6 moved it under VAULT_ROOT
# (TMPDIR varies by invocation context, so a /tmp-derived path silently
# degraded mutual exclusion to none between two launches from different
# contexts). The test kept holding the old path: its entire mechanism -- "hold
# the lock the child would need, prove the child proceeds anyway" -- was inert,
# because a child that DID try to acquire LAUNCH_LOCK would compute the
# VAULT_ROOT path, find it free, and take it instantly. Whole-branch review I1.
LAUNCH_LOCK_RELATIVE = "_state/runtime/vibesquad-launch-{session}.lockdir"


def _make_isolated_vault_root(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a"]
    for name in RSYNC_EXCLUDES:
        cmd += ["--exclude", name]
    cmd += [f"{REPO}/", f"{dest}/"]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
    return dest


def _make_claude_stub_home(dest: Path, marker_file: Path) -> Path:
    """A fake $HOME whose only content is `.local/bin/claude`: a stub that
    records one line to marker_file then sleeps, standing in for the real
    Max-plan claude binary vs-welcome.sh execs via a hard-coded HOME path."""
    bin_dir = dest / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "$$ $(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$CLAUDE_STUB_MARKER"\n'
        "exec sleep 3600\n"
    )
    stub.chmod(0o755)
    marker_file.touch()
    return dest


def _make_isolated_chrono_vault(dest: Path) -> Path:
    """A throwaway private vault root that satisfies the launcher's own gate.

    bin/launch-squad.sh runs `doctor.sh --check-private-vault-root` before it
    does anything else, which is plugins/chrono-vault/vaultroot.py's
    resolve_vault_root(): an absolute existing directory, outside every public
    worktree, holding a `.chrono-vault` sentinel with a non-empty vault_id and
    a positive integer schema_version. Nothing more -- no index, no venv.

    This used to be `Path.home() / "Obsidian-Chrono"`, the operator's REAL
    private vault. That was the one hole left in an isolation harness whose
    module docstring is otherwise entirely about not reaching live state, and
    it made the launcher's first gate depend on a directory that exists on
    exactly one machine: on any host without it (every Linux CI runner) all
    seven tests below died at that gate having asserted nothing.
    """
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".chrono-vault").write_text(
        json.dumps({"vault_id": f"test-launch-{uuid.uuid4().hex[:12]}",
                    "schema_version": 1}),
        encoding="utf-8",
    )
    return dest


@unittest.skipIf(
    MISSING_LAUNCH_PREREQUISITES,
    "bin/launch-squad.sh refuses to start without every command in "
    "shared/launch-dependencies.sh, so it never reaches the behaviour these "
    "tests assert about. Missing here: "
    + ", ".join(MISSING_LAUNCH_PREREQUISITES),
)
class _IsolatedLaunchTestCase(unittest.TestCase):
    """Shared isolation harness for anything that invokes the real
    bin/launch-squad.sh -- see module docstring SAFETY section for why every
    piece of this exists. Subclassed by LaunchSingleCoordinatorTests and by
    ReattachSessionHealthTests (Plan B Task 7 addition, which drives the
    reattach path specifically and needs to create then manipulate a
    session's window composition before re-invoking the launcher)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="launch-single-coord-")
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)

        self.vault_root = _make_isolated_vault_root(tmp / "vault")
        self.marker_file = tmp / "claude-invocations.log"
        self.fake_home = _make_claude_stub_home(tmp / "fake-home", self.marker_file)

        self.session = f"test-launch-race-{uuid.uuid4().hex[:10]}"
        self.tmux_tmpdir = TMUX_SOCKET_ROOT / f"vs-test-tmux-{uuid.uuid4().hex[:10]}"
        self.tmux_tmpdir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._kill_isolated_tmux_server)

        # Plan B Task 8 replaced the live-status poller's old global
        # `pgrep -f 'vs-lane-status.sh'` guard (which would have found the
        # REAL host poller and skipped spawning a second one) with a pidfile
        # under VIBESQUAD_STATUS_DIR. Left at its default (/tmp), an isolated
        # test run would now spawn a genuine, real, un-cleaned-up second
        # poller on this host. Scope it into this test's own tmp dir instead,
        # and kill whatever PID lands in its pidfile on teardown.
        self.status_dir = tmp / "vs-status"
        self.status_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._kill_isolated_status_poller)

        self.chrono_vault_root = _make_isolated_chrono_vault(tmp / "chrono-vault")

        real_home = Path.home()
        self.env = {
            **os.environ,
            "HOME": str(self.fake_home),
            "VAULT_ROOT": str(self.vault_root),
            "TMUX_TMPDIR": str(self.tmux_tmpdir),
            "VIBESQUAD_STATUS_DIR": str(self.status_dir),
            "SQUAD_SESSION": self.session,
            "SQUAD_SKIP_DOCTOR": "1",
            # See module docstring SAFETY section: never omit this.
            "SQUAD_SKIP_WATCHER_FLEET": "1",
            "CHRONO_VAULT_ROOT": str(self.chrono_vault_root),
            "SQUAD_LAUNCHAGENTS_DIR": str(real_home / "Library" / "LaunchAgents"),
            "CLAUDE_STUB_MARKER": str(self.marker_file),
        }

    def _kill_isolated_status_poller(self) -> None:
        # The poller spawn guard is intentionally NOT under LAUNCH_LOCK (see
        # module docstring / task-8-report.md "concerns"), so
        # test_concurrent_squad_up_produces_exactly_one_coordinator's two
        # near-simultaneous launches can each decide independently "not
        # alive yet" and both spawn one; the second write to
        # vs-lane-status.pid clobbers the first PID, leaking the other
        # forever. Reading the pidfile alone caught only one. `pgrep -f` on
        # this test's own unique, freshly-generated isolated vault_root path
        # is safe here (unlike the production anti-pattern Task 8 removed):
        # the search string is a random tmp path that cannot coincide with
        # any unrelated process's argv, so it cannot produce a false match.
        pidfile = self.status_dir / "vs-lane-status.pid"
        pids: set[int] = set()
        if pidfile.exists():
            with contextlib.suppress(ValueError, OSError):
                pids.add(int(pidfile.read_text(encoding="utf-8").strip()))
        found = subprocess.run(
            ["pgrep", "-f", f"{self.vault_root}/bin/vs-lane-status.sh"],
            capture_output=True, text=True, timeout=5,
        )
        for line in found.stdout.splitlines():
            with contextlib.suppress(ValueError):
                pids.add(int(line.strip()))
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)

    def _kill_isolated_tmux_server(self) -> None:
        # This tmux server lives on its own socket dir (self.tmux_tmpdir), a
        # server this test created. It never touches the real default-socket
        # tmux server the live "squad" session runs on.
        subprocess.run(
            ["tmux", "kill-server"],
            env={**os.environ, "TMUX_TMPDIR": str(self.tmux_tmpdir)},
            capture_output=True,
            timeout=10,
        )

    def _tmux_sessions(self) -> list[str]:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            env={**os.environ, "TMUX_TMPDIR": str(self.tmux_tmpdir)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]

    def _marker_lines(self) -> list[str]:
        if not self.marker_file.exists():
            return []
        return [line for line in self.marker_file.read_text().splitlines() if line.strip()]

    def _tmux(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["tmux", *args],
            env={**os.environ, "TMUX_TMPDIR": str(self.tmux_tmpdir)},
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _launch(self, timeout: int = 45) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(LAUNCH_SQUAD)],
            cwd=str(self.vault_root),
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _windows(self) -> list[tuple[str, str]]:
        result = self._tmux(
            "list-windows", "-t", self.session, "-F", "#{window_index}|#{window_name}"
        )
        rows = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            idx, name = line.split("|", 1)
            rows.append((idx, name))
        return rows


class LaunchSingleCoordinatorTests(_IsolatedLaunchTestCase):
    def test_concurrent_squad_up_produces_exactly_one_coordinator(self) -> None:
        """Forces both launches to be PROVABLY racing through the
        LAUNCH_LOCK/has-session decision at the same instant, via
        SQUAD_TEST_RACE_BARRIER (bin/launch-squad.sh, right before the
        LAUNCH_LOCK block) -- not merely started around the same time. An
        unforced version of this test cannot distinguish "the race is
        closed" from "the race never actually happened": if p1 finishes
        before p2 even reaches has-session, p2 just reattaches normally
        either way, with or without the fix, and the test would report the
        same "exactly one coordinator" result regardless. See
        task-1-report.md fix round 1 for the RED-then-GREEN proof against
        the pre-fix script using this identical barrier mechanism.
        """
        barrier_base = Path(self._tmp.name) / "race-barrier"
        env = {**self.env, "SQUAD_TEST_RACE_BARRIER": str(barrier_base)}
        popen_kwargs = dict(
            cwd=str(self.vault_root), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        p1 = subprocess.Popen(["bash", str(LAUNCH_SQUAD)], **popen_kwargs)
        p2 = subprocess.Popen(["bash", str(LAUNCH_SQUAD)], **popen_kwargs)
        try:
            deadline = time.time() + 30
            while True:
                ready = list(barrier_base.parent.glob(f"{barrier_base.name}.ready.*"))
                if len(ready) >= 2:
                    break
                if p1.poll() is not None or p2.poll() is not None:
                    for p in (p1, p2):
                        if p.poll() is None:
                            p.kill()
                    out1, err1 = p1.communicate(timeout=5)
                    out2, err2 = p2.communicate(timeout=5)
                    self.fail(
                        "a launcher exited before both reached the race barrier -- cannot "
                        f"prove forced interleaving\np1 rc={p1.returncode} out={out1!r} err={err1!r}\n"
                        f"p2 rc={p2.returncode} out={out2!r} err={err2!r}"
                    )
                if time.time() > deadline:
                    self.fail(f"both launchers never reached the race barrier within 30s; saw: {ready}")
                time.sleep(0.05)

            # Both processes are now provably paused at the exact same
            # point, immediately before the LAUNCH_LOCK/has-session critical
            # section. Release them to race through it simultaneously.
            (barrier_base.parent / f"{barrier_base.name}.go").touch()

            out1, err1 = p1.communicate(timeout=60)
            out2, err2 = p2.communicate(timeout=60)
        finally:
            for p in (p1, p2):
                if p.poll() is None:
                    p.kill()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        p.wait(timeout=5)

        self.assertEqual(p1.returncode, 0, f"launcher #1 failed:\nSTDOUT:\n{out1}\nSTDERR:\n{err1}")
        self.assertEqual(p2.returncode, 0, f"launcher #2 failed:\nSTDOUT:\n{out2}\nSTDERR:\n{err2}")

        sessions = self._tmux_sessions()
        matching = [s for s in sessions if s == self.session]
        self.assertEqual(
            len(matching), 1,
            f"expected exactly one session named {self.session!r}, tmux has: {sessions}",
        )

        # vs-welcome.sh itself sleeps 1s before exec'ing the (stub) coordinator.
        time.sleep(2.0)
        marker_lines = self._marker_lines()
        self.assertEqual(
            len(marker_lines), 1,
            f"expected exactly one coordinator exec, got {len(marker_lines)}: {marker_lines}",
        )

    def test_cold_start_still_converges(self) -> None:
        """A single fresh launch against a session name that has never
        existed on this (isolated) tmux server must complete and produce a
        coordinator -- the LAUNCH_LOCK half of the deadlock guard. (The
        watcher-fleet-child half is proven separately and more precisely by
        test_watcher_fleet_child_never_blocks_on_launch_lock below, which
        does not depend on SQUAD_SKIP_WATCHER_FLEET.)
        """
        try:
            result = subprocess.run(
                ["bash", str(LAUNCH_SQUAD)],
                cwd=str(self.vault_root),
                env=self.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"squad up did not converge within 45s (possible deadlock): {exc}")

        self.assertEqual(result.returncode, 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        self.assertIn(self.session, self._tmux_sessions())

        time.sleep(2.0)
        marker_lines = self._marker_lines()
        self.assertEqual(
            len(marker_lines), 1,
            f"expected exactly one coordinator exec, got {len(marker_lines)}: {marker_lines}",
        )

    def test_watcher_fleet_child_never_blocks_on_launch_lock(self) -> None:
        """Deterministic proof of the deadlock-guard property itself: the
        `--watcher-fleet-child` re-invocation must never even attempt to
        acquire LAUNCH_LOCK. Pre-hold the exact lock directory the real
        launcher would use (owned by this live test process), then run
        `--watcher-fleet-child` directly and confirm it proceeds to spawn
        its watcher-supervisor loops rather than blocking on the lock this
        test is holding. No tmux session, no coordinator, and no
        ensure_watcher_fleet() call are involved at all -- the
        --watcher-fleet-child fast path (near the top of the script) exits
        before any of that code is reached, so this needs no
        SQUAD_SKIP_WATCHER_FLEET seam and touches nothing system-wide: the
        watcher loops it spawns run against this test's own isolated
        VAULT_ROOT only.
        """
        # The path the child would actually compute: self.env sets VAULT_ROOT
        # to this test's isolated copy, and bin/launch-squad.sh derives
        # LAUNCH_LOCK from it. Holding any other path proves nothing -- see
        # LAUNCH_LOCK_RELATIVE above for the drift this caught.
        launch_lock_dir = self.vault_root / LAUNCH_LOCK_RELATIVE.format(session=self.session)
        launch_lock_dir.mkdir(parents=True, exist_ok=False)
        self.assertIn(
            f'LAUNCH_LOCK="${{VAULT_ROOT}}/{LAUNCH_LOCK_RELATIVE.format(session="${SESSION}")}"',
            LAUNCH_SQUAD.read_text(encoding="utf-8"),
            "the launcher's LAUNCH_LOCK path moved -- this test would be holding "
            "a directory nothing reads, which is exactly the failure it just had",
        )
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", str(launch_lock_dir)], capture_output=True, timeout=10,
        ))
        (launch_lock_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

        proc = subprocess.Popen(
            ["bash", str(LAUNCH_SQUAD), "--watcher-fleet-child"],
            cwd=str(self.vault_root),
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        def _cleanup_child() -> None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
            except Exception:
                pass
            finally:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()

        self.addCleanup(_cleanup_child)

        deadline = time.time() + 15
        spawned = False
        watcher_script = str(self.vault_root / "bin" / "outbox-watcher.sh")
        while time.time() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=5)
                self.fail(
                    f"--watcher-fleet-child exited early (rc={proc.returncode}) instead of "
                    f"running its supervisor loops:\nSTDOUT:\n{out}\nSTDERR:\n{err}"
                )
            check = subprocess.run(
                ["pgrep", "-f", watcher_script], capture_output=True, text=True, timeout=5,
            )
            if check.returncode == 0 and check.stdout.strip():
                spawned = True
                break
            time.sleep(0.2)

        self.assertTrue(
            spawned,
            "watcher-fleet-child never spawned its watcher loop within 15s -- it may be "
            "blocked acquiring LAUNCH_LOCK, which it must never touch (this test holds "
            "that exact lock directory for the whole run)",
        )


class ReattachSessionHealthTests(_IsolatedLaunchTestCase):
    """Plan B Task 7 addition: the reattach path (`if tmux has-session ...`)
    used to verify nothing beyond the watcher window (via
    ensure_watcher_fleet, which only looks at window 5) before attaching.
    Measured evidence: the operator's live session sat for eight days with
    no watcher window at all and a stray, un-managed "zsh" window at index
    1, and `squad up` attached to it without repairing or complaining every
    time. verify_session_windows() (bin/launch-squad.sh, called from the
    reattach branch right after ensure_watcher_fleet) closes this: repair
    what can be repaired (stray default-named windows, reaped inline), fail
    loudly for what cannot (a missing/misnamed coordinator window, or one
    whose pane process is actually gone).
    """

    def test_healthy_reattach_leaves_windows_alone(self) -> None:
        first = self._launch()
        self.assertEqual(first.returncode, 0, f"STDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}")

        second = self._launch()
        self.assertEqual(second.returncode, 0, f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}")
        self.assertIn("already exists", second.stdout)
        self.assertNotIn("Reaping stray", second.stdout)
        self.assertNotIn("ERROR", second.stdout + second.stderr)

        windows = dict(self._windows())
        self.assertEqual(windows.get("0"), "chrono", windows)

    def test_reattach_refuses_when_coordinator_window_is_missing(self) -> None:
        first = self._launch()
        self.assertEqual(first.returncode, 0, f"STDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}")

        rename = self._tmux("rename-window", "-t", f"{self.session}:0", "not-chrono")
        self.assertEqual(rename.returncode, 0, rename.stderr)

        second = self._launch()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("not the chrono coordinator window", second.stdout + second.stderr)
        # Refusal must not silently attach anyway.
        self.assertNotIn("Attaching...", second.stdout)

    def test_reattach_refuses_when_coordinator_pane_process_is_dead(self) -> None:
        first = self._launch()
        self.assertEqual(first.returncode, 0, f"STDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}")

        # remain-on-exit keeps tmux from simply closing the pane/window the
        # instant its process exits, so the "pane exists but its process is
        # gone" code path is actually reachable to test, rather than
        # collapsing into the "window absent" case above.
        remain = self._tmux("set-window-option", "-t", f"{self.session}:chrono", "remain-on-exit", "on")
        self.assertEqual(remain.returncode, 0, remain.stderr)

        pid_result = self._tmux("list-panes", "-t", f"{self.session}:chrono", "-F", "#{pane_pid}")
        pids = [int(p) for p in pid_result.stdout.split() if p.strip()]
        self.assertTrue(pids, "expected at least one chrono pane pid")
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        # Give tmux a moment to notice the process actually exited.
        time.sleep(1.0)

        second = self._launch()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("pane process is gone", second.stdout + second.stderr)
        self.assertNotIn("Attaching...", second.stdout)

    def test_reattach_reaps_stray_default_named_window(self) -> None:
        first = self._launch()
        self.assertEqual(first.returncode, 0, f"STDOUT:\n{first.stdout}\nSTDERR:\n{first.stderr}")

        # No -n and no command: left to tmux's own automatic-rename with a
        # bare default shell running (not e.g. `sleep`, which would name the
        # window "sleep" and correctly NOT match the reap filter), so the
        # window's name becomes whatever shell is actually running in it
        # (matching the real "stray zsh" incident) rather than something
        # this test forced onto it explicitly -- an explicit `-n` name turns
        # automatic-rename off, per tmux's own behavior, verified
        # empirically before writing this test.
        new_window = self._tmux("new-window", "-t", f"{self.session}:")
        self.assertEqual(new_window.returncode, 0, new_window.stderr)
        # The pane's shell needs a moment to actually start and settle
        # tmux's automatic-rename onto its real name ("zsh") -- confirmed
        # empirically it briefly shows a placeholder name first.
        time.sleep(1.5)

        # list-windows -t "session:index" does NOT filter to that one
        # window (confirmed empirically) -- it lists the whole session
        # regardless, so filter in Python instead.
        rows = self._tmux(
            "list-windows", "-t", self.session, "-F", "#{window_index}|#{window_name}|#{automatic-rename}"
        ).stdout.splitlines()
        parsed = [row.split("|") for row in rows if row.strip()]
        stray_idx, stray_name, stray_auto_rename = next(row for row in parsed if row[0] != "0")
        self.assertEqual(
            stray_auto_rename, "1",
            f"test setup assumption failed: the stray window ({stray_name!r}) must still be "
            f"on automatic-rename for this to exercise the reaping path, not the "
            f"'deliberately named/kept' exclusion. All windows: {parsed}",
        )
        self.assertIn(
            stray_name, ("zsh", "bash", "sh"),
            f"test setup assumption failed: expected a bare default-shell name, got {stray_name!r}",
        )

        second = self._launch()
        self.assertEqual(second.returncode, 0, f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}")
        self.assertIn("Reaping stray default-named window", second.stdout)
        self.assertIn("already exists", second.stdout)

        after = dict(self._windows())
        self.assertNotIn(stray_idx, after, f"stray window {stray_idx} should have been reaped: {after}")
        self.assertEqual(after.get("0"), "chrono", after)


if __name__ == "__main__":
    unittest.main()
