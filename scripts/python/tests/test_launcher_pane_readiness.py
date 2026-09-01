#!/usr/bin/env python3
"""F-01: launch-squad.sh must not send-keys at a shell that is still initializing.

Observed three times on 2026-08-30. bin/launch-squad.sh fires four
`tmux send-keys ... C-m` at the chrono pane back to back with no check that the
pane's shell is ready to consume them. When the shell is still sourcing its rc
files the keystrokes land in the tty buffer and come back fused or with
characters dropped -- `_state/tmux-logs/chrono.log` shows two commands welded
into `export CHRONO_VAULT_CLEARANCE=restrictedROOT=$HOME/...` and
`$HOME/go/bin` eaten down to `$HOME/gbin`.

The fourth send-keys is the one that execs claude. When it arrives mangled the
coordinator never starts, and the failure is SILENT: the launcher still exits 0
and hands back a squad with no coordinator.

These tests drive the guard directly rather than running launch-squad.sh, which
would exec claude. Same technique as test_squad_stop_reaping.py.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "bin" / "launch-squad.sh"

# Extracts the guard's shell function body so a test can source just that
# function without executing the rest of the launcher.
GUARD_EXTRACT = r"/^wait_for_pane_shell()/,/^}$/p"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args], capture_output=True, text=True, check=False
    )


def _extract_guard_to(path: Path) -> None:
    """Write just the guard function to `path` so a test shell can source it.

    Sourcing via process substitution (`source <(sed ...)`) is not reliable
    across the shells this runs under -- it silently defines nothing. A real
    file always works and fails loudly when the extraction is wrong.
    """
    fragment = subprocess.run(
        ["sed", "-n", GUARD_EXTRACT, str(LAUNCHER)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    path.write_text(fragment, encoding="utf-8")


class LauncherGuardIsWiredTests(unittest.TestCase):
    """Static checks -- these run everywhere, no tmux needed."""

    def setUp(self) -> None:
        self.source = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_defines_the_readiness_guard(self) -> None:
        self.assertIn(
            "wait_for_pane_shell()",
            self.source,
            "bin/launch-squad.sh defines no wait_for_pane_shell guard; the four "
            "send-keys at the chrono pane are unguarded (F-01).",
        )

    def test_guard_runs_before_the_first_chrono_send_keys(self) -> None:
        guard_at = self.source.find("wait_for_pane_shell ")
        first_send = self.source.find('send-keys -t "${SESSION}:chrono"')
        self.assertNotEqual(guard_at, -1, "guard is never CALLED, only defined")
        self.assertNotEqual(first_send, -1, "chrono send-keys block not found")
        self.assertLess(
            guard_at,
            first_send,
            "the guard must be called BEFORE the first send-keys at the chrono "
            "pane, otherwise it cannot prevent the race.",
        )

    def test_guard_failure_aborts_instead_of_launching_a_headless_squad(self) -> None:
        """The original bug was silent. A guard that warns and continues repeats it."""
        window = self.source[
            self.source.find("wait_for_pane_shell ") : self.source.find(
                'send-keys -t "${SESSION}:chrono"'
            )
        ]
        self.assertRegex(
            window,
            r"exit\s+1",
            "a failed readiness check must abort the launch; warning and "
            "continuing reproduces the silent-failure mode this fixes.",
        )

    def _guard_body(self) -> str:
        match = re.search(r"^wait_for_pane_shell\(\).*?^\}$", self.source, re.S | re.M)
        self.assertIsNotNone(match, "guard function body not found")
        return match.group(0)

    def test_guard_clears_the_line_editor_before_each_probe(self) -> None:
        """Review finding 1: printf format cycling can fake a clean sentinel.

        If a round's text lands but its C-m is dropped, the next round appends to
        the same input line:
            printf '%s\\n' SENT__printf '%s\\n' SENT
        printf reuses its format for every remaining argument, so that garbage
        still prints a pristine `SENT` on its own line and an exact-match check
        passes -- on precisely the mangling the guard exists to catch. Clearing
        the line editor first makes the input line provably empty, so a fused
        line cannot form.
        """
        body = self._guard_body()
        self.assertIn(
            "C-u",
            body,
            "guard must clear the pane's line editor before each probe, or a "
            "fused input line can still yield a clean-looking sentinel.",
        )

    def test_guard_uses_a_fresh_sentinel_each_round(self) -> None:
        """A sentinel reused across rounds can be matched from stale scrollback."""
        body = self._guard_body()
        loop_at = body.find("while ")
        sentinel_at = body.find("sentinel=")
        self.assertNotEqual(sentinel_at, -1, "no sentinel assignment found")
        self.assertGreater(
            sentinel_at,
            loop_at,
            "the sentinel must be regenerated INSIDE the retry loop; a single "
            "sentinel hoisted above it can be satisfied by an earlier round.",
        )

    def test_failed_guard_tears_down_the_half_built_session(self) -> None:
        """Review finding 2: exit 1 alone re-creates the silent failure.

        The session already exists by this point. Leaving it up means the
        operator's retry hits the `has-session` path, whose window check passes
        for a bare shell, and they get attached to a coordinator-less squad with
        no error -- the original bug, one level up.
        """
        window = self.source[
            self.source.find("wait_for_pane_shell ") : self.source.find(
                'send-keys -t "${SESSION}:chrono"'
            )
        ]
        self.assertIn(
            "kill-session",
            window,
            "a failed readiness check must tear down the session it is "
            "abandoning; otherwise retry silently attaches to a headless squad.",
        )

    def test_guard_does_not_wrap_the_pane_shell(self) -> None:
        """LIFE-03b: claude must stay the pane shell's DIRECT exec child.

        vs-welcome.sh execs claude in place, so the pane shell's $? IS claude's
        exit status. A guard implemented as a wrapper process around the pane
        command would break exit capture and `pgrep -P` coordinator detection.
        """
        match = re.search(
            r"^wait_for_pane_shell\(\).*?^\}$", self.source, re.S | re.M
        )
        self.assertIsNotNone(match, "guard function body not found")
        body = match.group(0)
        for forbidden in ("exec ", "vs-welcome.sh"):
            self.assertNotIn(
                forbidden,
                body,
                f"the guard must not {forbidden.strip()!r} -- it runs launcher-side "
                "only and must not come between the pane shell and claude.",
            )


@unittest.skipUnless(shutil.which("tmux"), "tmux required")
class LauncherGuardBehaviourTests(unittest.TestCase):
    """Live reproduction against a deliberately slow-starting shell."""

    def setUp(self) -> None:
        self.session = f"vstest-{uuid.uuid4().hex[:8]}"
        self.zdotdir = tempfile.mkdtemp(prefix="vs-readiness-")
        self.addCleanup(shutil.rmtree, self.zdotdir, ignore_errors=True)
        self.addCleanup(_tmux, "kill-session", "-t", self.session)
        self.guard = Path(self.zdotdir, "guard.sh")
        _extract_guard_to(self.guard)

    def _start_slow_shell(self, delay_seconds: int = 2) -> None:
        # Reproduces the real condition: .zprofile sourcing secrets.zsh made the
        # shell unready for long enough that the launcher's keystrokes were lost.
        Path(self.zdotdir, ".zshrc").write_text(
            f"sleep {delay_seconds}\n", encoding="utf-8"
        )
        _tmux("new-session", "-d", "-s", self.session, "-x", "200", "-y", "50")
        _tmux(
            "send-keys", "-t", self.session, f"ZDOTDIR={self.zdotdir} exec zsh", "C-m"
        )

    def _capture(self) -> str:
        return _tmux("capture-pane", "-p", "-J", "-t", self.session).stdout

    def test_commands_arrive_intact_after_the_guard_returns(self) -> None:
        self._start_slow_shell()
        marker = "VSMARKER_INTACT"

        guarded = subprocess.run(
            ["bash", "-c", f"source {self.guard}; wait_for_pane_shell {self.session} 30"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            guarded.returncode,
            0,
            f"guard did not report the shell ready. stderr: {guarded.stderr!r}",
        )

        _tmux("send-keys", "-t", self.session, f"printf '%s\\n' {marker}", "C-m")
        subprocess.run(["bash", "-c", "sleep 1"], check=False)
        pane = self._capture()

        # (?m) so ^/$ anchor to a LINE in the pane capture, not the whole buffer.
        # The marker must stand alone on its own line: that is what proves the
        # command was not fused with a neighbour, which is the actual bug.
        self.assertRegex(
            pane,
            rf"(?m)^{marker}$",
            f"command did not arrive intact after the guard returned:\n{pane}",
        )
        # The echoed command must survive whole. In the real failure the echo
        # came back with characters eaten ($HOME/go/bin -> $HOME/gbin) or welded
        # to a neighbouring command, so checking the echo is what detects the
        # actual bug -- the prompt prefix on that line is expected and fine.
        echo_line = next(
            (ln for ln in pane.splitlines() if "printf" in ln and marker in ln), ""
        )
        self.assertTrue(echo_line, f"command echo never appeared:\n{pane}")
        self.assertIn(
            f"printf '%s\\n' {marker}",
            echo_line,
            f"command echo arrived mangled or fused:\n{echo_line!r}",
        )

    def test_guard_reports_failure_when_the_shell_never_becomes_ready(self) -> None:
        """A dead pane must produce a loud non-zero, never a silent pass."""
        _tmux("new-session", "-d", "-s", self.session, "-x", "200", "-y", "50")
        _tmux("send-keys", "-t", self.session, "exec sleep 600", "C-m")

        result = subprocess.run(
            ["bash", "-c", f"source {self.guard}; wait_for_pane_shell {self.session} 3"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(
            result.returncode, 0, "guard passed against a shell that cannot echo"
        )
        self.assertTrue(
            result.stderr.strip(),
            "guard failed silently; it must say why on stderr",
        )


if __name__ == "__main__":
    unittest.main()
