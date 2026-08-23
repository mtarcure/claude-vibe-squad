#!/usr/bin/env python3
"""Plan B Task 8: replace unsound `pgrep -f` / argv-substring process guards.

docs/superpowers/sdd/2026-08-17-plan-B-stop-lying-about-state/task-8-brief.md

A specialist's entire compiled prompt is its own argv -- measured 41,008
bytes on a live `codex exec`, containing the literal text "outbox-watcher.sh"
as plain prose. Every process-liveness/identity predicate in this repo that
tested "does some token merely CONTAIN or EQUAL this text ANYWHERE in a
process's command line" was reachable by that prose, with the worst case
(bin/launch-squad.sh's `watcher_seed()` marker clause) having no VAULT_ROOT
or SQUAD_SESSION scoping at all -- the defect that killed the operator's
live watcher fleet from an isolated regression test earlier in this exact
remediation effort (see task-1-report.md).

The fix in every case is the same shape: replace name/argv matching with
pidfile + `kill -0` (+ output-freshness where the target is expected to
produce output on a fixed cadence) wherever this repo controls the spawn, and
where argv matching is genuinely unavoidable (chrome-profile cleanup in
squad-stop.sh, spawned by third-party MCP tooling this repo does not
control), require an executable-name gate plus an EXACT positional/token
match -- never substring, never token-membership-anywhere-in-argv.

This file drives the exact, verbatim predicate functions extracted from both
scripts (not reimplementations) against:
  1. A ~41KB adversarial "argv" built from realistic prose that contains
     every literal guard string used across every site, with natural
     English contractions (unbalanced apostrophes are exactly what raised
     shlex.ValueError in the pre-fix code) -- required by the brief's Step 4.
  2. Positive controls: the real, legitimate command shapes this repo
     actually spawns must still match, proving the tightening didn't also
     break real detection.
  3. The pidfile-based liveness primitives (pidfile_alive, the poller's
     freshness check) under dead-owner / live-owner / stale-output scenarios.
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
LAUNCH_SQUAD = REPO / "bin" / "launch-squad.sh"
SQUAD_STOP = REPO / "bin" / "squad-stop.sh"
PROCESS_IDENTITY = REPO / "shared" / "process-identity.sh"

TEST_ROOT = "/opt/fixture/Obsidian-Claude-Vibe-Squad"  # matches watcher_seed()'s `root`


def _build_adversarial_argv(min_bytes: int = 41_008) -> str:
    """Realistic prose (a specialist discussing this exact bug, which is
    the real shape this argv size came from) containing every literal guard
    string from every site this task touches, plus natural contractions so
    it also exercises shlex's unbalanced-quote failure path.
    """
    paragraph = (
        "The launcher's watcher fleet doesn't identify its own supervisor "
        "processes safely -- it's matched by scanning every process on the "
        "host for a couple of fragile patterns. One marker it looks for is "
        "the literal text watcher-supervisor:outbox:all, and its sibling is "
        "watcher-supervisor:reconcile-sweep; neither is scoped to a "
        "VAULT_ROOT or a SQUAD_SESSION, so it can't tell one checkout's "
        "fleet from another's. The root watcher itself is spawned as "
        "bin/outbox-watcher.sh all, and there's a companion sweep that runs "
        "scripts/python/swarm_runtime.py reconcile-sweep on a loop; you'll "
        "also see it reference departments/coding/inbox and "
        "departments/coding/outbox when it's deciding which fswatch "
        "processes are its own. Don't forget the poller either -- it's "
        "named vs-lane-status.sh, and it isn't tracked by a pidfile in the "
        "old code, so a week-old corpse satisfies pgrep -f just fine and a "
        "fresh one never starts. Separately, squad-stop.sh's Chrome cleanup "
        "greps for --user-data-dir=/opt/fixture/Caches/ms-playwright/mcp-chrome- "
        "and --user-data-dir=/opt/fixture/.cache/chrome-devtools-mcp/chrome-profile "
        "and just xargs kills whatever pgrep -f hands it -- it's the same "
        "class of bug, and it's why we're not allowed to substring-match an "
        "operator's process list anymore, full stop. "
    )
    text = ""
    while len(text.encode("utf-8")) < min_bytes:
        text += paragraph
    return text


ADVERSARIAL_ARGV = _build_adversarial_argv()

# ---------------------------------------------------------------------------
# `ps`-shaped supervisor fixtures.
#
# These are the EXACT strings `ps -axo pid=,command=` printed for the two live
# supervisor wrappers on this host (with the real root swapped for TEST_ROOT).
# `ps` space-joins the kernel's argv and re-adds NO quoting, so the `bash -c`
# body -- one argv element -- arrives indistinguishable from a dozen separate
# words: 17 of them, not 5.
#
# The fixtures these replace hand-built the command with single quotes around
# the body ("bash -c " "'while true; ...'" " marker path"), which made
# shlex.split() see exactly 5 tokens and satisfied the shipped
# `len(tokens) == 5` clause. `ps` never emits that string, so those two
# positive controls asserted nothing about any real process and passed with
# the clause deleted entirely, while the live fleet went unmatched.
# ---------------------------------------------------------------------------
PS_OUTBOX_SUPERVISOR = (
    'bash -c while true; do bash "$1" all; rc=$?; '
    'echo "watcher supervisor restart: kind=outbox namespace=all rc=$rc" >&2; '
    "sleep 2; done watcher-supervisor:outbox:all "
    f"{TEST_ROOT}/bin/outbox-watcher.sh"
)
PS_RECONCILE_SUPERVISOR = (
    'bash -c while true; do python3 "$1" reconcile-sweep; rc=$?; '
    'echo "watcher supervisor restart: kind=reconcile-sweep rc=$rc" >&2; '
    "sleep 2; done watcher-supervisor:reconcile-sweep "
    f"{TEST_ROOT}/scripts/python/swarm_runtime.py"
)
# macOS Homebrew's framework build: argv[0]'s basename is `Python`, capital P.
PS_HOMEBREW_PYTHON = (
    "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework"
    "/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
)


class WatcherSeedFalsePositiveTests(unittest.TestCase):
    """Drives bin/launch-squad.sh's watcher_seed(), extracted verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        match = re.search(
            r"\ndef watcher_seed\(command: str\) -> bool:.*?\n(?=targets = watcher_roots)",
            text,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError(
                "could not locate watcher_seed() in bin/launch-squad.sh -- "
                "extraction regex is stale, update it to match the current source"
            )
        cls.watcher_seed_src = match.group(0)
        namespace: dict = {"root": TEST_ROOT}
        exec(
            compile("import os\nimport shlex\n" + match.group(0), "<watcher_seed extract>", "exec"),
            namespace,
        )
        cls.watcher_seed = staticmethod(namespace["watcher_seed"])

    def test_41kb_adversarial_argv_matches_nothing(self) -> None:
        self.assertGreaterEqual(len(ADVERSARIAL_ARGV.encode("utf-8")), 41_008)
        # Simulates how `ps -axo command=` actually reports a real
        # `codex exec "<41KB prompt>"` invocation: the shell that ran it
        # consumed the quoting before exec, so the kernel's argv is
        # ["codex", "exec", "<prompt text, no quotes>"], and `ps` displays
        # that space-joined with no quotes re-added -- indistinguishable, as
        # plain text, from many separate words.
        command = f"codex exec {ADVERSARIAL_ARGV}"
        self.assertFalse(self.watcher_seed(command))
        self.assertFalse(self.watcher_seed(f"claude {ADVERSARIAL_ARGV}"))

    def test_a_bash_c_wrapper_carrying_the_41kb_prose_matches_nothing(self) -> None:
        """The adversarial case aimed squarely at the supervisor clause: the
        prose contains every marker and every script path, and it is carried
        by a process whose argv[0]/argv[1] ARE `bash` and `-c`. Only the
        pinned tail keeps it out."""
        self.assertFalse(self.watcher_seed(f"bash -c {ADVERSARIAL_ARGV}"))

    def test_real_outbox_supervisor_wrapper_still_matches(self) -> None:
        """`ps`-shaped, copied from the live fleet (pid 25464): 17
        space-separated words, which is why the shipped `== 5` token count
        could not match it."""
        self.assertTrue(self.watcher_seed(PS_OUTBOX_SUPERVISOR))

    def test_real_reconcile_sweep_supervisor_wrapper_still_matches(self) -> None:
        """`ps`-shaped, copied from the live fleet (pid 25465)."""
        self.assertTrue(self.watcher_seed(PS_RECONCILE_SUPERVISOR))

    def test_real_outbox_root_invocation_still_matches(self) -> None:
        self.assertTrue(self.watcher_seed(f"bash {TEST_ROOT}/bin/outbox-watcher.sh all"))

    def test_real_reconcile_sweep_root_invocation_still_matches(self) -> None:
        self.assertTrue(
            self.watcher_seed(f"python3 {TEST_ROOT}/scripts/python/swarm_runtime.py reconcile-sweep")
        )

    def test_homebrew_framework_python_reconcile_child_still_matches(self) -> None:
        """`ps`-shaped, copied from the live fleet (pid 25467). Its argv[0]
        basename is `Python`, capital P, so the case-SENSITIVE
        `startswith("python")` this replaces left the live reconcile-sweep
        child unmatched -- an orphaned supervisor/child pair that no sweep
        could ever reach."""
        self.assertTrue(
            self.watcher_seed(
                f"{PS_HOMEBREW_PYTHON} {TEST_ROOT}/scripts/python/swarm_runtime.py reconcile-sweep"
            )
        )

    def test_a_vault_root_containing_a_space_still_matches(self) -> None:
        """`~/Google Drive/...` and `~/Obsidian Vaults/...` are ordinary macOS
        clone locations. `ps` cannot re-quote them, so any predicate that
        re-tokenizes the row stops matching this root's own processes -- the
        same false-negative class as the token-count bug (plan-B I3)."""
        spaced = "/opt/fixture/Obsidian Vaults/Claude-Vibe-Squad"
        namespace: dict = {"root": spaced}
        exec(  # noqa: S102 -- same verbatim-extraction technique as setUpClass
            compile(
                "import os\nimport shlex\n" + self.watcher_seed_src,
                "<watcher_seed extract>",
                "exec",
            ),
            namespace,
        )
        seed = namespace["watcher_seed"]
        self.assertTrue(seed(f"bash {spaced}/bin/outbox-watcher.sh all"))
        self.assertTrue(
            seed(
                'bash -c while true; do bash "$1" all; sleep 2; done '
                f"watcher-supervisor:outbox:all {spaced}/bin/outbox-watcher.sh"
            )
        )

    def test_a_different_vault_roots_identical_marker_does_not_match(self) -> None:
        """The pinned tail requires the LAST argv element to be THIS root's
        script path -- a different checkout's real supervisor command,
        replayed against this root, must not match. This is the
        VAULT_ROOT-scoping property itself, and it is what stopped an
        isolated regression test from killing the operator's live fleet.
        """
        other_root = "/opt/other-checkout/Obsidian-Claude-Vibe-Squad"
        command = PS_OUTBOX_SUPERVISOR.replace(
            f"{TEST_ROOT}/bin/outbox-watcher.sh", f"{other_root}/bin/outbox-watcher.sh"
        )
        self.assertFalse(self.watcher_seed(command))

    def test_a_mismatched_marker_and_script_pair_does_not_match(self) -> None:
        """Marker and script path are matched as a PAIR, not independently:
        the outbox marker beside the reconcile script is not a shape this
        launcher ever spawns, so it must not be treated as one of ours."""
        self.assertFalse(
            self.watcher_seed(
                PS_OUTBOX_SUPERVISOR.replace(
                    f"{TEST_ROOT}/bin/outbox-watcher.sh",
                    f"{TEST_ROOT}/scripts/python/swarm_runtime.py",
                )
            )
        )

    def test_extra_positional_argument_breaks_the_match(self) -> None:
        """Exact positional shape, not "these tokens appear somewhere" --
        an extra token after the pinned pair must not still match."""
        self.assertFalse(self.watcher_seed(f"{PS_OUTBOX_SUPERVISOR} extra-token"))

    def test_marker_as_a_prefix_of_a_longer_token_does_not_match(self) -> None:
        """The marker is compared as an EXACT argv element, never a prefix --
        the property the pre-Task-8 `token.startswith(...)` clause lacked."""
        self.assertFalse(
            self.watcher_seed(
                PS_OUTBOX_SUPERVISOR.replace(
                    "watcher-supervisor:outbox:all", "watcher-supervisor:outbox:all-of-them"
                )
            )
        )


class ChromeProfileMatcherFalsePositiveTests(unittest.TestCase):
    """Drives bin/squad-stop.sh's is_mode_spawned_chrome_profile(), extracted verbatim."""

    PROFILE = "/opt/fixture/.cache/chrome-devtools-mcp/chrome-profile"

    @classmethod
    def setUpClass(cls) -> None:
        text = SQUAD_STOP.read_text(encoding="utf-8")
        match = re.search(
            r"\nIDENTITY_TOKEN_LIMIT = .*?\n(?=\n?profile = sys\.argv)",
            text,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError(
                "could not locate is_mode_spawned_chrome_profile() in bin/squad-stop.sh -- "
                "extraction regex is stale, update it to match the current source"
            )
        namespace: dict = {}
        exec(compile("import shlex\n" + match.group(0), "<chrome matcher extract>", "exec"), namespace)
        cls.matches = staticmethod(namespace["is_mode_spawned_chrome_profile"])

    def test_41kb_adversarial_argv_matches_nothing(self) -> None:
        self.assertGreaterEqual(len(ADVERSARIAL_ARGV.encode("utf-8")), 41_008)
        command = f"codex exec {ADVERSARIAL_ARGV}"
        self.assertFalse(self.matches(command, self.PROFILE))

    def test_real_chrome_invocation_still_matches(self) -> None:
        command = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--user-data-dir={self.PROFILE}-abc123 --headless --remote-debugging-port=0"
        )
        self.assertTrue(self.matches(command, self.PROFILE))

    def test_non_chrome_executable_never_matches_even_with_the_exact_flag(self) -> None:
        """The executable-name gate is load-bearing: a non-browser process
        that happens to carry the exact flag text must still be rejected."""
        command = f"python3 some_script.py --user-data-dir={self.PROFILE}-abc123"
        self.assertFalse(self.matches(command, self.PROFILE))

    def test_the_persistent_cdp_chrome_is_recognised_by_its_own_profile(self) -> None:
        """Whole-branch review I4: the same predicate now also answers "which
        process groups must Phase 5 never reap". If it could not recognise the
        persistent CDP browser from the argv bin/chrome-bootstrap.sh actually
        produces, the exclusion would protect nothing while reporting that it
        does."""
        persistent = "/opt/fixture/.chrono/chrome-persistent-profile"
        command = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--user-data-dir={persistent} --remote-debugging-port=9222 "
            "--no-first-run --no-default-browser-check --restore-last-session"
        )
        self.assertTrue(self.matches(command, persistent))
        # And the mode-spawned profiles are not a prefix of it, which is why
        # Phase 3's kill loop cannot reach the persistent browser at all.
        self.assertFalse(self.matches(command, self.PROFILE))

    def test_flag_text_merely_present_in_prose_does_not_match(self) -> None:
        command = (
            f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--some-other-flag=\"references --user-data-dir={self.PROFILE} in a docstring\""
        )
        self.assertFalse(self.matches(command, self.PROFILE))


class PidfileAliveTests(unittest.TestCase):
    """Drives bin/launch-squad.sh's pidfile_alive(), extracted verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        match = re.search(r"\npidfile_alive\(\) \{.*?\n\}\n", text, re.DOTALL)
        if not match:
            raise RuntimeError("could not locate pidfile_alive() in bin/launch-squad.sh")
        cls.function_src = match.group(0)

    def _run(self, script_body: str) -> subprocess.CompletedProcess:
        full = "#!/bin/bash\nset -uo pipefail\n" + self.function_src + "\n" + script_body
        return subprocess.run(["bash", "-c", full], capture_output=True, text=True, timeout=15)

    def test_missing_pidfile_is_not_alive(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "nonexistent.pid"
            result = self._run(f'pidfile_alive "{pidfile}"; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)

    def test_dead_pid_is_not_alive(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "watcher.pid"
            pidfile.write_text(f"{dead.pid}\n", encoding="utf-8")
            result = self._run(f'pidfile_alive "{pidfile}"; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)

    def test_live_pid_is_alive(self) -> None:
        live = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as d:
                pidfile = Path(d) / "watcher.pid"
                pidfile.write_text(f"{live.pid}\n", encoding="utf-8")
                result = self._run(f'pidfile_alive "{pidfile}"; echo "rc=$?"')
                self.assertIn("rc=0", result.stdout)
        finally:
            live.terminate()
            live.wait(timeout=5)

    def test_corrupt_pidfile_is_not_alive(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d) / "watcher.pid"
            pidfile.write_text("not-a-pid\n", encoding="utf-8")
            result = self._run(f'pidfile_alive "{pidfile}"; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)


class _PollerGuardHarness:
    """Shared extraction + fixtures for the two classes below, both of which
    drive bin/launch-squad.sh's vs_lane_status_poller_alive() extracted verbatim.

    Every scenario runs against a throwaway VS_LANE_STATUS_STATUS_DIR *and* a
    throwaway VAULT_ROOT, so the identity check can only ever match a poller the
    test itself spawned under that temp root -- never the operator's live one,
    whose argv names the real checkout.
    """

    # Every function the guard depends on, extracted verbatim from the file that
    # owns it -- the identity predicate from shared/, the rest from the launcher.
    SOURCES = (
        (PROCESS_IDENTITY, "pid_is_vs_lane_status_poller"),
        (LAUNCH_SQUAD, "pidfile_alive"),
        (LAUNCH_SQUAD, "file_mtime_epoch"),
        (PROCESS_IDENTITY, "find_live_vs_lane_status_pollers"),
        (LAUNCH_SQUAD, "write_vs_lane_status_pidfile"),
        (LAUNCH_SQUAD, "vs_lane_status_pidfile_names_live_poller"),
        (LAUNCH_SQUAD, "vs_lane_status_warn_stranded_pollers"),
        (LAUNCH_SQUAD, "vs_lane_status_poller_alive"),
    )

    @classmethod
    def setUpClass(cls) -> None:
        chunks = []
        for path, name in cls.SOURCES:
            match = re.search(
                rf"\n{name}\(\) \{{.*?\n\}}\n", path.read_text(encoding="utf-8"), re.DOTALL
            )
            if not match:
                raise RuntimeError(
                    f"could not locate {name}() in {path} -- extraction regex is "
                    "stale, update it to match the current source"
                )
            chunks.append(match.group(0))
        cls.functions_src = "\n".join(chunks)

    @staticmethod
    def _spawn_fake_poller(vault_root: Path) -> subprocess.Popen:
        """A real live process wearing the launcher's exact spawn shape:
        `bash <VAULT_ROOT>/bin/vs-lane-status.sh`, no extra argv tokens."""
        (vault_root / "bin").mkdir(parents=True, exist_ok=True)
        script = vault_root / "bin" / "vs-lane-status.sh"
        script.write_text("#!/bin/bash\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        return subprocess.Popen(["bash", str(script)])

    def _run(
        self,
        status_dir: Path,
        script_body: str,
        max_age: int | None = None,
        vault_root: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        # vs_lane_status_poller_alive() reads VS_LANE_STATUS_PIDFILE (the pidfile
        # path) and VS_LANE_STATUS_STATUS_DIR (the freshness file's directory)
        # as two separate variables -- matches how bin/launch-squad.sh computes
        # both from the same status dir right before calling this function.
        # VAULT_ROOT is what the poller's argv identity check is scoped to.
        env_prefix = (
            f'VS_LANE_STATUS_STATUS_DIR="{status_dir}"\n'
            f'VS_LANE_STATUS_PIDFILE="{status_dir}/vs-lane-status.pid"\n'
            f'VAULT_ROOT="{vault_root if vault_root is not None else status_dir}"\n'
        )
        if max_age is not None:
            env_prefix += f'VS_LANE_STATUS_FRESHNESS_MAX_AGE="{max_age}"\n'
        full = "#!/bin/bash\nset -uo pipefail\n" + env_prefix + self.functions_src + "\n" + script_body
        environment = None if extra_env is None else {**os.environ, **extra_env}
        return subprocess.run(
            ["bash", "-c", full],
            capture_output=True,
            text=True,
            timeout=15,
            env=environment,
        )


class PollerFreshnessTests(_PollerGuardHarness, unittest.TestCase):
    """Plan B Task 8's scenarios: liveness proven by a pidfile plus fresh output."""

    def test_no_pidfile_is_not_alive(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self._run(Path(d), 'vs_lane_status_poller_alive; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)

    def test_live_pid_with_fresh_output_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            status_dir = Path(d)
            # The pidfile names a process that really is this root's poller --
            # the state a launcher that spawned it leaves behind. A bare `sleep`
            # would not do: liveness is proven by identity, not by "some PID
            # exists".
            live = self._spawn_fake_poller(status_dir)
            try:
                (status_dir / "vs-lane-status.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
                result = self._run(status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"')
                self.assertIn("rc=0", result.stdout)
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_live_pid_with_stale_output_is_not_alive(self) -> None:
        """A hung-but-technically-alive poller is not "running" for our
        purposes -- liveness is proven by fresh output, never by the PID
        merely existing. This is the specific property the brief asked for."""
        live = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as d:
                status_dir = Path(d)
                (status_dir / "vs-lane-status.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                stale = status_dir / "vs-daemon.status"
                stale.write_text("online", encoding="utf-8")
                old = time.time() - 3600
                import os as _os
                _os.utime(stale, (old, old))
                result = self._run(status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', max_age=10)
                self.assertIn("rc=1", result.stdout)
        finally:
            live.terminate()
            live.wait(timeout=5)

    def test_dead_pid_and_fresh_output_but_no_live_poller_still_spawns(self) -> None:
        """Fresh output is NOT by itself proof that a poller is running: the
        last tick of a poller that died two seconds ago is still fresh. With a
        dead pidfile, fresh output, and no live poller anywhere under this
        VAULT_ROOT, the launcher must still spawn. This is the test that stops
        Task 12's fix from degenerating into "trust the mtime" -- which would
        leave the status bar permanently dead while reporting healthy.
        """
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d:
            status_dir = Path(d)
            (status_dir / "vs-lane-status.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
            (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
            result = self._run(status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"')
            self.assertIn("rc=1", result.stdout)

    def test_unreadable_mtime_is_indeterminate_not_ancient(self) -> None:
        """If both stat dialects fail, freshness is unknown. Returning the
        ordinary not-alive status would make the launcher replace a possibly
        healthy poller; epoch zero made that unsafe replacement look justified."""
        with tempfile.TemporaryDirectory() as d:
            status_dir = Path(d)
            (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
            fakebin = status_dir / "fakebin"
            fakebin.mkdir()
            fake_stat = fakebin / "stat"
            fake_stat.write_text("#!/bin/bash\nexit 66\n", encoding="utf-8")
            fake_stat.chmod(0o755)

            result = self._run(
                status_dir,
                'vs_lane_status_poller_alive; echo "rc=$?"',
                extra_env={"PATH": f"{fakebin}:/usr/bin:/bin"},
            )

            self.assertIn("rc=2", result.stdout)
            self.assertIn("freshness is indeterminate", result.stderr)
            # Assert the CLAIM, not the letters: a bare "old" also matches the
            # tempdir path (/var/f-old-ers/...), so this passed for the wrong
            # reason on Linux and failed for the wrong reason on macOS.
            self.assertNotIn("is old", result.stderr)
            self.assertNotIn("too old", result.stderr)
            self.assertNotIn("stale", result.stderr)


class UntrackedLivePollerTests(_PollerGuardHarness, unittest.TestCase):
    """Plan B Task 12: the operator's measured live state -- pidfile naming a
    DEAD pid (75269), a genuinely live poller the pidfile does not name (71022,
    ppid=1, up 2h49m), and a freshness file written 0s ago.

    Task 8 replaced an argv scan with this pidfile because a corpse's argv made
    a fresh poller never start. That introduced the mirror defect: a live poller
    the pidfile does not name is invisible, so `squad up` spawns a second one and
    overwrites the pidfile with the new PID -- permanently orphaning the first,
    beyond the reach of every future `squad up` and `squad stop`.

    Shares _PollerGuardHarness with PollerFreshnessTests deliberately: these
    scenarios must be driven through the exact same extracted function, under
    the same temp-root isolation, as the Task 8 scenarios they extend.
    """

    def _live_state(self, status_dir: Path, vault_root: Path) -> subprocess.Popen:
        """Build the measured live state, with a real process for the poller."""
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        (status_dir / "vs-lane-status.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
        (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
        return self._spawn_fake_poller(vault_root)

    def test_untracked_live_poller_prevents_a_duplicate_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._live_state(status_dir, vault_root)
            try:
                result = self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                self.assertIn(
                    "rc=0",
                    result.stdout,
                    "a demonstrably live poller must read as alive even when the "
                    "pidfile names a corpse -- rc=1 here is the duplicate spawn",
                )
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_untracked_live_poller_is_adopted_into_the_pidfile(self) -> None:
        """Not spawning is only half the fix: the pidfile must end up naming the
        real poller, or `squad stop` still cannot reap it and the leak persists.
        """
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._live_state(status_dir, vault_root)
            try:
                self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                self.assertEqual(
                    (status_dir / "vs-lane-status.pid").read_text(encoding="utf-8").strip(),
                    str(live.pid),
                )
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_untracked_live_poller_is_not_killed_or_signalled(self) -> None:
        """Adoption, not reaping: the guard runs inside `squad up`, and a
        launcher that kills a healthy process it identified by argv is exactly
        the hazard that took out the operator's watcher fleet earlier in this
        plan."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._live_state(status_dir, vault_root)
            try:
                self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                time.sleep(0.3)
                self.assertIsNone(live.poll(), "the adopted poller must still be running")
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_live_poller_with_stale_output_still_spawns(self) -> None:
        """A hung poller is not a running one. Adoption must not override the
        freshness rule Task 8 added -- otherwise a wedged poller keeps the
        status bar frozen forever and the launcher calls that healthy."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._live_state(status_dir, vault_root)
            try:
                stale = status_dir / "vs-daemon.status"
                old = time.time() - 3600
                import os as _os

                _os.utime(stale, (old, old))
                result = self._run(
                    status_dir,
                    'vs_lane_status_poller_alive; echo "rc=$?"',
                    max_age=10,
                    vault_root=vault_root,
                )
                self.assertIn("rc=1", result.stdout)
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_replacing_a_wedged_tracked_poller_names_the_orphan_it_leaves(self) -> None:
        """The residual leak path this fix does NOT close: a tracked poller that
        is alive but wedged still gets replaced, and the spawn overwrites the
        pidfile, orphaning it. Killing it from a launcher is out of scope, but
        creating an orphan in silence is what made Task 12 a manual
        investigation -- so the launcher must at least name the PID it strands.
        """
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._spawn_fake_poller(vault_root)
            try:
                (status_dir / "vs-lane-status.pid").write_text(f"{live.pid}\n", encoding="utf-8")
                stale = status_dir / "vs-daemon.status"
                stale.write_text("online", encoding="utf-8")
                old = time.time() - 3600
                import os as _os

                _os.utime(stale, (old, old))
                result = self._run(
                    status_dir,
                    'vs_lane_status_poller_alive; echo "rc=$?"',
                    max_age=10,
                    vault_root=vault_root,
                )
                self.assertIn("rc=1", result.stdout)
                self.assertIn(str(live.pid), result.stderr)
                self.assertIn("UNTRACKED", result.stderr)
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_replacing_a_wedged_untracked_poller_also_names_it(self) -> None:
        """Fix round 1, minor 3. Same stranding, except the pidfile does not
        name the wedged poller either -- the case the first cut of the warning
        missed, and the one closest to the live defect. Asking the finder rather
        than only the pidfile is what covers it."""
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            live = self._spawn_fake_poller(vault_root)
            try:
                (status_dir / "vs-lane-status.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
                stale = status_dir / "vs-daemon.status"
                stale.write_text("online", encoding="utf-8")
                old = time.time() - 3600
                import os as _os

                _os.utime(stale, (old, old))
                result = self._run(
                    status_dir,
                    'vs_lane_status_poller_alive; echo "rc=$?"',
                    max_age=10,
                    vault_root=vault_root,
                )
                self.assertIn("rc=1", result.stdout)
                self.assertIn(str(live.pid), result.stderr)
                self.assertIn("UNTRACKED", result.stderr)
            finally:
                live.terminate()
                live.wait(timeout=5)

    def test_no_orphan_warning_when_nothing_is_actually_stranded(self) -> None:
        """The warning must fire on a real stranded process only -- a dead PID
        in the pidfile and no live poller strands nothing, and a launcher that
        cried orphan on every cold start would train the operator to ignore it."""
        dead = subprocess.Popen(["true"])
        dead.wait(timeout=5)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            (status_dir / "vs-lane-status.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
            result = self._run(
                status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
            )
            self.assertIn("rc=1", result.stdout)
            self.assertNotIn("UNTRACKED", result.stderr)

    def test_cold_start_with_no_pidfile_and_no_output_still_spawns(self) -> None:
        """The path a fresh clone takes. A live poller belonging to a DIFFERENT
        checkout is running throughout, and must not be mistaken for this one."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr, \
                tempfile.TemporaryDirectory() as other:
            status_dir, vault_root = Path(d), Path(vr)
            foreign = self._spawn_fake_poller(Path(other))
            try:
                result = self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                self.assertIn("rc=1", result.stdout)
            finally:
                foreign.terminate()
                foreign.wait(timeout=5)

    def test_a_foreign_checkouts_live_poller_is_never_adopted(self) -> None:
        """VAULT_ROOT scoping, stated as its own property: another checkout's
        poller is live and its output is fresh here, but it belongs to a
        different root, so this launcher must spawn its own rather than adopt
        someone else's process into its pidfile."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr, \
                tempfile.TemporaryDirectory() as other:
            status_dir, vault_root = Path(d), Path(vr)
            dead = subprocess.Popen(["true"])
            dead.wait(timeout=5)
            (status_dir / "vs-lane-status.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
            (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
            foreign = self._spawn_fake_poller(Path(other))
            try:
                result = self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                self.assertIn("rc=1", result.stdout)
                self.assertEqual(
                    (status_dir / "vs-lane-status.pid").read_text(encoding="utf-8").strip(),
                    str(dead.pid),
                    "a foreign poller must never be written into this root's pidfile",
                )
            finally:
                foreign.terminate()
                foreign.wait(timeout=5)

    def test_recycled_pid_in_the_pidfile_is_repointed_at_the_real_poller(self) -> None:
        """The pidfile names a live process that is NOT the poller (the PID was
        recycled -- this pidfile can sit stale for days, which is why
        squad-stop.sh verifies identity before killing). The real poller is
        running untracked. Same defect class: the pidfile does not name the
        poller, so it must be re-pointed rather than treated as authoritative."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as vr:
            status_dir, vault_root = Path(d), Path(vr)
            impostor = subprocess.Popen(["sleep", "30"])
            live = self._spawn_fake_poller(vault_root)
            try:
                (status_dir / "vs-lane-status.pid").write_text(f"{impostor.pid}\n", encoding="utf-8")
                (status_dir / "vs-daemon.status").write_text("online", encoding="utf-8")
                result = self._run(
                    status_dir, 'vs_lane_status_poller_alive; echo "rc=$?"', vault_root=vault_root
                )
                self.assertIn("rc=0", result.stdout)
                self.assertEqual(
                    (status_dir / "vs-lane-status.pid").read_text(encoding="utf-8").strip(),
                    str(live.pid),
                )
                time.sleep(0.3)
                self.assertIsNone(impostor.poll(), "the unrelated process must not be signalled")
            finally:
                for proc in (impostor, live):
                    proc.terminate()
                    proc.wait(timeout=5)


class PidfileSingleWriterTests(_PollerGuardHarness, unittest.TestCase):
    """Fix round 1, important 1: one file, one writer, one guarantee.

    The adoption path was made rename-atomic while the spawn path -- the far
    more frequent one, taken on every cold start and every respawn -- still used
    a truncating `>` redirect. `squad stop` reading in that window gets an empty
    or partial line, fails its `^[0-9]+$` guard, deletes the pidfile, and the
    just-spawned poller is orphaned: Task 12's leak, through the other door. The
    window is reachable because the poller guard sits outside LAUNCH_LOCK, so
    two near-simultaneous launches can both reach the spawn
    (test_launch_single_coordinator.py, _IsolatedLaunchTestCase.
    _kill_isolated_status_poller, and the launch it describes:
    test_concurrent_squad_up_produces_exactly_one_coordinator).
    """

    # The spawn block is top-level script, not a function, so it cannot be
    # extracted and driven the way every other test here drives its subject --
    # and running the launcher for real is forbidden while the operator's
    # session is live. These two assertions pin the property structurally
    # instead: the writer is what the spawn site calls, and no truncating
    # redirect targets this pidfile anywhere in the file.
    @staticmethod
    def _spawn_block() -> str:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        start = text.find("vs_lane_status_poller_rc=0")
        end = text.find("\nfi\n\n# apply_squad_globals", start)
        if start < 0 or end <= start:
            raise AssertionError("could not locate the complete poller decision/spawn block")
        return text[start : end + len("\nfi")]

    def test_spawn_site_records_the_pid_through_the_atomic_writer(self) -> None:
        spawn_block = self._spawn_block()
        self.assertIn("write_vs_lane_status_pidfile", spawn_block)

    def test_indeterminate_freshness_exits_before_the_spawn_block(self) -> None:
        marker = "SPAWN_OR_WRITE_MUST_NOT_RUN"
        full = (
            "#!/bin/bash\nset -uo pipefail\n"
            "vs_lane_status_poller_alive() { return 2; }\n"
            f'write_vs_lane_status_pidfile() {{ echo "{marker}"; }}\n'
            + self._spawn_block()
            + f'\necho "{marker}"\n'
        )
        result = subprocess.run(
            ["bash", "-c", full], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to replace or adopt", result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_no_truncating_redirect_targets_the_pidfile(self) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        offenders = re.findall(r'^.*>\s*"?\$\{?VS_LANE_STATUS_PIDFILE.*$', text, re.MULTILINE)
        self.assertEqual(
            offenders,
            [],
            "the pidfile must only ever be written by write_vs_lane_status_pidfile "
            f"(staged + renamed); found a direct redirect: {offenders}",
        )

    def test_writer_replaces_an_existing_pidfile_and_leaves_no_staging_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            status_dir = Path(d)
            pidfile = status_dir / "vs-lane-status.pid"
            pidfile.write_text("11111\n", encoding="utf-8")
            result = self._run(status_dir, 'write_vs_lane_status_pidfile 22222; echo "rc=$?"')
            self.assertIn("rc=0", result.stdout)
            self.assertEqual(pidfile.read_text(encoding="utf-8").strip(), "22222")
            self.assertEqual(
                sorted(p.name for p in status_dir.iterdir()),
                ["vs-lane-status.pid"],
                "the staged temp file must be renamed onto the target, not left behind",
            )

    def test_a_failed_identity_source_stops_the_launch(self) -> None:
        """Fix round 1, minor 2. Both scripts run `set -uo pipefail` without -e,
        so an unguarded `source` of a missing shared/process-identity.sh would
        continue with the predicate undefined: every identity call returns 127,
        every real poller reads as "not ours", and the launcher spawns a
        duplicate on every launch while reporting nothing wrong."""
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        match = re.search(
            r'source "\$\{VAULT_ROOT\}/shared/process-identity\.sh"(.{0,400})', text, re.DOTALL
        )
        self.assertIsNotNone(match, "launcher no longer sources shared/process-identity.sh")
        self.assertRegex(
            match.group(1),
            r"^\s*\|\|",
            "the source must have a failure branch, not fall through silently",
        )
        self.assertIn("exit 1", match.group(1))

    def test_writer_reports_failure_instead_of_claiming_it_recorded_the_pid(self) -> None:
        """Both callers warn on a failed write, which is only worth anything if
        the writer actually reports failure rather than returning 0."""
        result = self._run(
            Path("/dev/null/not-a-directory"),
            'write_vs_lane_status_pidfile 33333; echo "rc=$?"',
        )
        self.assertNotIn("rc=0", result.stdout)


class PortableMtimeTests(unittest.TestCase):
    """Drive the launcher's exact BSD/GNU mtime adapter with hostile stat output."""

    @classmethod
    def setUpClass(cls) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        match = re.search(r"\nfile_mtime_epoch\(\) \{.*?\n\}\n", text, re.DOTALL)
        if not match:
            raise RuntimeError("could not locate file_mtime_epoch() in bin/launch-squad.sh")
        cls.function_src = match.group(0)

    def _run(self, stat_body: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / "freshness"
            target.write_text("online", encoding="utf-8")
            fakebin = root / "fakebin"
            fakebin.mkdir()
            fake_stat = fakebin / "stat"
            fake_stat.write_text("#!/bin/bash\n" + stat_body, encoding="utf-8")
            fake_stat.chmod(0o755)
            full = (
                "#!/bin/bash\nset -uo pipefail\n"
                + self.function_src
                + f'\nvalue="$(file_mtime_epoch "{target}")"; rc=$?; '
                + 'printf "value=%s rc=%s\\n" "$value" "$rc"\n'
            )
            return subprocess.run(
                ["bash", "-c", full],
                capture_output=True,
                text=True,
                timeout=15,
                env={**os.environ, "PATH": f"{fakebin}:/usr/bin:/bin"},
            )

    def test_gnu_stat_partial_filesystem_report_is_discarded_before_fallback(self) -> None:
        result = self._run(
            "if [[ \"$1\" == '-f' ]]; then\n"
            "  printf '  File: \\\"%s\\\"\\nBlocks: Total: 123\\n' \"$3\"\n"
            "  exit 1\n"
            "fi\n"
            "if [[ \"$1\" == '-c' ]]; then printf '1234567890\\n'; exit 0; fi\n"
            "exit 64\n"
        )
        self.assertEqual(result.stdout, "value=1234567890 rc=0\n")
        self.assertNotIn("File:", result.stdout + result.stderr)

    def test_successful_nonnumeric_probe_does_not_reach_arithmetic(self) -> None:
        result = self._run(
            "if [[ \"$1\" == '-f' ]]; then printf 'not-an-epoch\\n'; exit 0; fi\n"
            "if [[ \"$1\" == '-c' ]]; then printf '1234567891\\n'; exit 0; fi\n"
            "exit 64\n"
        )
        self.assertEqual(result.stdout, "value=1234567891 rc=0\n")

    def test_total_stat_failure_has_no_synthetic_timestamp(self) -> None:
        result = self._run("exit 66\n")
        self.assertEqual(result.stdout, "value= rc=1\n")


if __name__ == "__main__":
    unittest.main()
