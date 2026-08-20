#!/usr/bin/env python3
"""What `bin/launch-squad.sh` would tell tmux, without a tmux server.

`apply_squad_globals()` is pure emission: every line in it is a `tmux` call and
nothing else. So the function can be extracted, run with a STUB `tmux` on an
otherwise-empty PATH, and its argv stream asserted -- which is the only way to
regression-test the status bar without launching a session on top of whatever
the operator is running. A real `tmux` is unreachable from these tests by
construction: PATH contains the stub directory and nothing else.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "bin" / "launch-squad.sh"

STUB_TMUX = """#!/bin/bash
printf 'tmux'
for a in "$@"; do printf ' [%s]' "$a"; done
printf '\\n'
"""


def extract_function(source: str, name: str) -> str:
    """Return the text of a top-level `name() { ... }` shell function."""
    lines = source.splitlines()
    start = lines.index(f"{name}() {{")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1]) + "\n"


def emitted_tmux_calls() -> list[list[str]]:
    """Run apply_squad_globals() against a stub tmux; return one list per call."""
    body = extract_function(LAUNCHER.read_text(encoding="utf-8"), "apply_squad_globals")
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        stub_dir = base / "stub"
        stub_dir.mkdir()
        stub = stub_dir / "tmux"
        stub.write_text(STUB_TMUX, encoding="utf-8")
        stub.chmod(0o755)
        driver = base / "driver.sh"
        driver.write_text(
            "set -uo pipefail\n"
            + body
            + "\napply_squad_globals\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["/bin/bash", str(driver)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                "PATH": str(stub_dir),
                "SESSION": "stub-session",
                "CHRONO_DOCTOR_LOG_DIR_SHELL": "/stub/doctor-logs",
                "HOME": str(base),
            },
        )
    calls = []
    for line in completed.stdout.splitlines():
        if not line.startswith("tmux "):
            continue
        calls.append(re.findall(r"\[(.*?)\](?= \[|$)", line))
    return calls


def conditional_branches(value: str) -> list[list[str]]:
    """Split every `#{?cond,then,else}` in `value` into its top-level parts.

    tmux splits a conditional on top-level commas and makes NO exception for the
    comma inside a `#[fg=colour74,bold]` style spec -- a style with a comma in a
    branch silently truncates the conditional. A well-formed conditional has
    exactly three parts; anything else means the format does not say what it
    looks like it says.
    """
    groups = []
    index = 0
    while (start := value.find("#{?", index)) != -1:
        depth = 1  # the `#{?` we just matched is the group we are inside
        parts = [""]
        position = start + 3  # first character of the condition
        while position < len(value):
            char = value[position]
            if value.startswith("#{", position):
                depth += 1
                parts[-1] += "#{"
                position += 2
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    break
                parts[-1] += char
            elif char == "," and depth == 1:
                parts.append("")
            else:
                parts[-1] += char
            position += 1
        groups.append(parts)
        index = position + 1
    return groups


def option_value(calls: list[list[str]], option: str) -> str | None:
    """Last `set-option -g <option> <value>` seen, or None."""
    found = None
    for call in calls:
        if call[:2] == ["set-option", "-g"] and len(call) >= 4 and call[2] == option:
            found = call[3]
    return found


class StatusBarEmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calls = emitted_tmux_calls()

    def test_status_bar_is_one_row(self) -> None:
        """The second row was a permanent terminal row of never-changing text."""
        self.assertEqual(option_value(self.calls, "status"), "1")

    def test_second_row_is_unset_not_merely_unrendered(self) -> None:
        """A server configured by an older launch still carries the old value."""
        self.assertIn(["set-option", "-gu", "status-format[1]"], self.calls)
        for call in self.calls:
            self.assertNotEqual(
                call[:3],
                ["set-option", "-g", "status-format[1]"],
                "row 1 must be unset, never re-set to a new static string",
            )

    def test_no_emitted_string_advertises_lane_windows(self) -> None:
        """There are no lane windows: lanes are panes in the chrono window."""
        blob = "\n".join(" ".join(call) for call in self.calls)
        self.assertNotIn("C-b <n>: lanes", blob)
        self.assertNotRegex(blob, r"C-b <n>")

    def test_every_command_substitution_is_a_bare_cat(self) -> None:
        """tmux forks a shell per `#()` per render. The cost was never network
        work, it was process creation, so nothing heavier than `cat` may sit on
        the render path."""
        rendered = [
            option_value(self.calls, option)
            for option in ("status-left", "status-right", "pane-border-format")
        ]
        for value in rendered:
            self.assertIsNotNone(value)
            for body in re.findall(r"#\((.*?)\)", value):
                self.assertRegex(
                    body,
                    r"^cat [^|;&`$]*$",
                    f"only a plain `cat` belongs on the render path, got: {body}",
                )

    def test_status_interval_is_not_once_a_second(self) -> None:
        interval = option_value(self.calls, "status-interval")
        self.assertIsNotNone(interval)
        self.assertGreaterEqual(int(interval), 5)

    def test_doctor_segment_is_one_token_from_the_poller(self) -> None:
        """It was five counters and 68 of 163 columns, in the brightest colour
        on the bar, for a value that changes once a day."""
        right = option_value(self.calls, "status-right")
        self.assertIn("cat /tmp/vs-doctor.status", right)
        for gone in ("pass:", "could-not-run", "not-applicable", "healthy_count"):
            self.assertNotIn(gone, right)
        # The poller colours its own token so that amber can be reserved for a
        # real issue count; a hardcoded amber prefix here would defeat that.
        self.assertNotIn("colour214", right)

    def test_narrow_clients_get_a_short_form(self) -> None:
        """`status-right-length 180` on a 163-column client meant tmux chose
        where to cut. Each side now names what it drops."""
        for option in ("status-left", "status-right"):
            value = option_value(self.calls, option)
            with self.subTest(option):
                self.assertIn("#{client_width}", value)
                # `#{>=:80,120}` is TRUE -- tmux(1) documents that form as a
                # STRING comparison, so it hands a narrow terminal the wide
                # layout. Numeric comparison lives behind `e`.
                self.assertIn("#{e|>=:#{client_width},120}", value)
                self.assertNotIn("#{>=:#{client_width}", value)
                branches = conditional_branches(value)
                self.assertTrue(branches, "no conditional found")
                for parts in branches:
                    # cond, then, else -- and no more. A fourth part means a
                    # comma inside a branch split the conditional.
                    self.assertEqual(
                        len(parts),
                        3,
                        f"{option} conditional has {len(parts)} parts: {parts}",
                    )
                    for branch in parts[1:]:
                        self.assertNotIn(
                            ",",
                            branch,
                            "a literal comma in a branch truncates the conditional",
                        )

    def test_the_swarm_capsule_is_what_the_narrow_form_drops(self) -> None:
        right = option_value(self.calls, "status-right")
        parts = conditional_branches(right)[0]
        wide, narrow = parts[1], parts[2]
        self.assertIn("vs-swarm.status", wide)
        self.assertNotIn("vs-swarm.status", narrow)
        # The doctor token and the clock sit outside the conditional: they are
        # short, and they are the two things that must survive any width.
        self.assertIn("vs-doctor.status", right[right.index("}", right.index("#{?")) :])

    def test_cheatsheet_is_a_popup_on_an_unshadowed_key(self) -> None:
        binds = [call for call in self.calls if call[0] == "bind-key"]
        popup = [call for call in binds if "display-popup" in call]
        self.assertEqual(len(popup), 1, f"expected exactly one popup bind, got {popup}")
        self.assertEqual(popup[0][1], "g", "`g` is not a default tmux prefix binding")
        text = popup[0][-1]
        self.assertIn("PANES in the chrono window", text)
        self.assertIn("C-b 0", text)
        self.assertIn("C-b 5", text)
        # `?` is tmux's own list-keys and must keep working; the popup points at
        # it rather than replacing it.
        self.assertIn("C-b ?", text)
        self.assertNotIn(
            ["bind-key", "?"],
            [call[:2] for call in binds],
            "C-b ? is tmux's list-keys and must not be shadowed",
        )


if __name__ == "__main__":
    unittest.main()
