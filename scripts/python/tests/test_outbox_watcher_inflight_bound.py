"""The auto-capture throttle must not be able to hang the watcher.

`autocapture_dispatch` drains its in-flight window with

    while [[ "$#" -ge "${AUTOCAPTURE_MAX_INFLIGHT}" ]]; do wait "$1"; shift; done

`[[ "$#" -ge 0 ]]` is always true and `shift` on an empty positional list
cannot advance, so a bound of `0` -- the value an operator naturally reaches
for to turn auto-capture off -- spun that loop forever, taking the whole
watcher with it. A non-numeric value did the same, because `[[ -ge ]]`
evaluates an unparseable operand as 0.

These tests do NOT restate the loop in Python. A reimplementation can stay
green while the shipped code regresses, and this defect survived a review
wave precisely because nothing executed the real thing. They EXTRACT the
live block from `bin/outbox-watcher.sh` -- from the `AUTOCAPTURE_MAX_INFLIGHT`
assignment through the end of `autocapture_dispatch` -- and run it under
`/bin/bash`, which is bash 3.2 on macOS and the interpreter the watcher's own
shebang selects. The only thing supplied is a stub
`autocapture_response_best_effort`; nothing else is edited.

Every run is wrapped in `timeout`/`gtimeout` where available and in a hard
`subprocess` timeout regardless, so a regression fails the test instead of
hanging the suite. No response file, no vault, and no model call is involved.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WATCHER = ROOT / "bin" / "outbox-watcher.sh"

_BLOCK_START = "AUTOCAPTURE_MAX_INFLIGHT_DEFAULT="
_BLOCK_END = "release_chrono_queue_lock() {"

# Long enough that a genuinely slow machine is not called a hang, short
# enough that a hang is reported rather than waited out.
HANG_SECONDS = 5


def shipped_block() -> str:
    """The live throttle block out of bin/outbox-watcher.sh, unmodified."""
    lines = WATCHER.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith(_BLOCK_START)
    )
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].startswith(_BLOCK_END)
    )
    block = "\n".join(lines[start:end])
    if "autocapture_dispatch()" not in block:
        raise AssertionError(
            "extraction missed autocapture_dispatch; the watcher moved"
        )
    return block


class InflightBoundTests(unittest.TestCase):
    def _run(self, value: str | None, dispatches: int = 4):
        """Run the shipped block with the knob set, and report what happened."""
        assignment = (
            "" if value is None else f"export CHRONO_AUTOCAPTURE_MAX_INFLIGHT={value!r}\n"
        )
        script = (
            "set -u\n"
            + assignment
            # Stands in for the real capture: records the call, exits at once.
            # The hang under test is in the DRAIN loop, not in the work.
            + 'autocapture_response_best_effort() { echo "dispatched:$1" >>"$LOG"; }\n'
            + shipped_block()
            + "\n"
            + "\n".join(
                f'autocapture_dispatch "/tmp/response-{i}.md"'
                for i in range(dispatches)
            )
            + "\nwait\n"
            + 'echo "REACHED-END"\n'
        )
        runner = shutil.which("timeout") or shutil.which("gtimeout")
        command = ["/bin/bash", "-c", script]
        if runner:
            command = [runner, str(HANG_SECONDS), *command]
        log = Path(
            subprocess.run(
                ["mktemp"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        self.addCleanup(log.unlink, missing_ok=True)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=HANG_SECONDS * 4,
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LOG": str(log)},
            )
        except subprocess.TimeoutExpired:
            self.fail(
                f"CHRONO_AUTOCAPTURE_MAX_INFLIGHT={value!r} hung the watcher: "
                "the drain loop never terminated"
            )
        self.assertNotEqual(
            result.returncode,
            124,
            f"CHRONO_AUTOCAPTURE_MAX_INFLIGHT={value!r} hung the watcher "
            f"(timed out after {HANG_SECONDS}s)",
        )
        self.assertIn(
            "REACHED-END",
            result.stdout,
            f"the block did not run to completion: {result.stdout}{result.stderr}",
        )
        captured = log.read_text(encoding="utf-8") if log.exists() else ""
        return result, captured.splitlines()

    def test_the_default_dispatches_and_terminates(self) -> None:
        """The baseline: unset knob, every response captured, no hang."""
        _result, dispatched = self._run(None, dispatches=4)
        self.assertEqual(len(dispatched), 4, dispatched)

    def test_an_explicit_bound_dispatches_and_terminates(self) -> None:
        _result, dispatched = self._run("2", dispatches=6)
        self.assertEqual(len(dispatched), 6, dispatched)

    def test_zero_disables_auto_capture_instead_of_hanging(self) -> None:
        """`0` is what an operator sets to turn auto-capture off.

        Before the knob was validated this was an infinite loop: the whole
        watcher wedged on an ordinary config edit. It must terminate, and it
        must do the thing the value asks for -- fork nothing.
        """
        result, dispatched = self._run("0", dispatches=4)
        self.assertEqual(dispatched, [], "0 must dispatch nothing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_malformed_value_falls_back_loudly_instead_of_hanging(self) -> None:
        """A typo must not switch memory capture off, and must not hang.

        `[[ -ge ]]` reads an unparseable operand as 0, so `bogus` hit the
        same infinite loop `0` did. The safe direction for a malformed
        throttle is "keep capturing under the default", said out loud.
        """
        result, dispatched = self._run("bogus", dispatches=4)
        self.assertEqual(len(dispatched), 4, "a typo must not disable capture")
        self.assertIn("CHRONO_AUTOCAPTURE_MAX_INFLIGHT", result.stderr)
        self.assertIn("bogus", result.stderr)

    def test_a_negative_value_falls_back_loudly_instead_of_hanging(self) -> None:
        result, dispatched = self._run("-1", dispatches=4)
        self.assertEqual(len(dispatched), 4, dispatched)
        self.assertIn("CHRONO_AUTOCAPTURE_MAX_INFLIGHT", result.stderr)

    def test_an_empty_value_falls_back_to_the_default(self) -> None:
        """`FOO=` is `${FOO:-8}`'s default case, not a malformed one."""
        result, dispatched = self._run("", dispatches=4)
        self.assertEqual(len(dispatched), 4, dispatched)
        self.assertNotIn("is not a whole number", result.stderr)

    def test_the_watcher_still_calls_this_function(self) -> None:
        """A bound nothing invokes is not a bound. Pins the live call site."""
        source = WATCHER.read_text(encoding="utf-8")
        self.assertIn('autocapture_dispatch "$path"', source)


if __name__ == "__main__":
    unittest.main()
