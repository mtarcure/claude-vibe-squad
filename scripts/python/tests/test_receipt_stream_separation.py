"""The board receipt is a machine channel; diagnostics must not reach it.

`bin/board-supervisor.sh` detached-launch captures the trusted-launch child's
stdout and hands the whole capture to `finalize_receipt`, which terminalises
whatever it can bind to the attempt. Until 2026-08-10 that capture also received
the child's stderr (`>"$receipt_capture" 2>&1`), so:

* one diagnostic line ahead of an otherwise valid receipt made the capture
  unparseable, and a SUCCESSFUL launch terminalised as `blocked`; and
* an exception raised before the launch handler printed a raw traceback rather
  than a receipt, which the finalizer reduced to the single anonymous string
  `invalid launch receipt` -- losing exception type, message and location from
  the machine channel entirely.

These tests pin all three halves of the repair: the streams are separated at the
real production redirect, an early crash still produces a structured receipt that
names the exception, and an unusable capture still fails closed but now says why.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"
sys.path.insert(0, str(ROOT / "scripts" / "python"))
import board_process_truth as bpt  # noqa: E402


# The one string the finalizer must never publish again. Every capture it
# refuses now carries a reason that distinguishes it from the other refusals.
ANONYMOUS = "invalid launch receipt"

# A context file that EXISTS (so the shell hands off to the embedded Python)
# but that no launch mode accepts, so the child reaches deny() and prints one
# structured receipt on stdout. Using a missing file instead would short-circuit
# in the shell and never start Python at all.
REJECTED_CONTEXT = {"schema": "not-a-launch-context"}
REJECTED_REASON = "go-live-trusted-context/v1"


def _live_attempt(vault, task, attempt, pid):
    """One live, exactly-observed attempt: (descriptor, dispatch, receipt)."""
    board = vault / "_state" / "board-dispatch"
    board.mkdir(parents=True, exist_ok=True)
    base = board / f"{task}.{attempt}"
    dispatch = Path(f"{base}.dispatch.json")
    receipt = Path(f"{base}.receipt.json")
    identity = bpt.observe_process(pid)
    assert identity is not None, "test fixture process is not observable"
    descriptor = {
        "schema": "board-dispatch-process/v2",
        "task_id": task,
        "attempt_id": attempt,
        "generation": 1,
        "created_at": bpt.utc_now(),
        **identity,
        "context_path": str(Path(f"{base}.context.json")),
        "log_path": str(Path(f"{base}.log")),
        "receipt_path": str(receipt),
    }
    dispatch.write_text(json.dumps(descriptor) + "\n", encoding="utf-8")
    return descriptor, dispatch, receipt


class ReceiptChannelPurityTests(unittest.TestCase):
    """The real trusted-launch child, run for real, with real stderr noise."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.context = self.root / "context.json"
        self.context.write_text(json.dumps(REJECTED_CONTEXT), encoding="utf-8")

    def _run_trusted_launch(self, **extra_env):
        """Invoke the production trusted-launch entry point, streams separate."""
        environment = {**os.environ, **extra_env}
        environment.pop("BOARD_TRANSCRIPT_FD", None)
        return subprocess.run(
            ["bash", str(SUPERVISOR), "trusted-launch", str(self.context)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def test_child_stdout_is_exactly_one_receipt_even_under_stderr_noise(self):
        # PYTHONVERBOSE makes the interpreter narrate every import on stderr.
        # It is real, ambient, environment-driven noise flowing through the exact
        # production path -- not an injected test hook.
        result = self._run_trusted_launch(PYTHONVERBOSE="1")

        self.assertEqual(result.returncode, 74, result.stderr[-2000:])
        self.assertTrue(result.stderr.strip(), "expected genuine stderr diagnostics")
        self.assertIn("import ", result.stderr)

        # The whole of stdout parses as ONE object. This is the property the
        # capture depends on, and it is what `2>&1` used to destroy.
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "denied")
        self.assertIn(REJECTED_REASON, receipt["reason"])
        self.assertNotIn("import ", result.stdout)


class FinalizerReasonTests(unittest.TestCase):
    """`finalize_receipt` still fails closed -- but never anonymously."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.live = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
        self.addCleanup(self._stop_fixture_process)
        self.counter = 0

    def _stop_fixture_process(self):
        self.live.terminate()
        self.live.wait(timeout=10)

    def _finalize(self, capture_bytes):
        """Publish one attempt whose capture holds exactly `capture_bytes`."""
        self.counter += 1
        _descriptor, dispatch, receipt = _live_attempt(
            self.vault,
            f"TASK-receipt-channel-{self.counter}",
            f"d-receipt-channel-{self.counter}",
            self.live.pid,
        )
        capture = Path(f"{receipt}.capture")
        capture.write_bytes(capture_bytes)
        return bpt.finalize_receipt(capture, dispatch, receipt)

    def test_clean_launch_receipt_is_preserved(self):
        published = self._finalize(b'{"status":"launched"}\n')

        self.assertEqual(published["status"], "launched")
        self.assertEqual(published["terminal_outcome"], "complete")

    def test_one_stderr_line_ahead_of_a_launch_receipt_is_the_defect(self):
        # The audit's headline scenario, held as a pinned regression: this is the
        # capture shape `2>&1` produced, and it must terminalise as blocked (fail
        # closed) while naming the contamination rather than hiding it. The
        # production redirect is what stops this shape from ever being built --
        # see ReceiptChannelPurityTests.
        published = self._finalize(
            b'WARNING: something noisy\n{"status":"launched"}\n'
        )

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("not one JSON object", published["reason"])
        self.assertIn("WARNING: something noisy", published["reason"])

    def test_empty_capture_names_the_missing_receipt(self):
        published = self._finalize(b"")

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("empty", published["reason"])

    def test_oversized_capture_names_the_bound_it_broke(self):
        published = self._finalize(b"x" * (bpt.MAX_JSON_BYTES + 1))

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("over the", published["reason"])
        self.assertIn(str(bpt.MAX_JSON_BYTES), published["reason"])

    def test_foreign_attempt_receipt_names_the_mismatched_field(self):
        published = self._finalize(
            json.dumps({"status": "launched", "task_id": "TASK-somebody-else"}).encode()
        )

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("different attempt", published["reason"])
        self.assertIn("TASK-somebody-else", published["reason"])

    def test_non_string_status_names_the_offending_field(self):
        published = self._finalize(json.dumps({"status": []}).encode())

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("status is not a string", published["reason"])

    def test_untrusted_capture_bytes_are_bounded_and_printable(self):
        published = self._finalize(b"\x00\x07" + b"A" * 4000 + b"\xff not json")

        self.assertEqual(published["terminal_outcome"], "blocked")
        reason = published["reason"]
        self.assertLessEqual(len(reason), bpt.INVALID_RECEIPT_REASON_LIMIT)
        self.assertTrue(all(item.isprintable() for item in reason), repr(reason))


class DetachedLaunchTests(unittest.TestCase):
    """End-to-end through the real `detached-launch` transport."""

    def _detached(self, extra_env, timeout=180):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        task = "TASK-2026-08-10-9994-receipt-channel"
        attempt = "d-receipt-channel"
        base = root / f"{task}.{attempt}"
        log = Path(f"{base}.log")
        receipt = Path(f"{base}.receipt.json")
        dispatch = Path(f"{base}.dispatch.json")
        marker = root / "settlement-error"
        context = Path(f"{base}.context.json")
        context.write_text(json.dumps(REJECTED_CONTEXT), encoding="utf-8")
        log.touch()

        process = subprocess.Popen(
            [
                "bash",
                str(SUPERVISOR),
                "detached-launch",
                str(context),
                str(log),
                str(receipt),
                str(marker),
                "/usr/bin/false",  # context builder: blocked publication fails
                str(root),
                task,
                "codex",
                "_state/receipt-channel/result.md",
                "coding",
                "/usr/bin/false",  # reconciler
            ],
            env={
                **os.environ,
                "BOARD_DISPATCH_DESCRIPTOR_PATH": str(dispatch),
                **extra_env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(process.kill)
        identity = None
        for _ in range(200):
            identity = bpt.observe_process(process.pid)
            if identity is not None:
                break
            time.sleep(0.005)
        self.assertIsNotNone(identity)
        self.assertTrue(
            bpt.atomic_write_json(
                dispatch,
                {
                    "schema": "board-dispatch-process/v2",
                    "task_id": task,
                    "attempt_id": attempt,
                    "generation": 1,
                    "created_at": bpt.utc_now(),
                    **identity,
                    "context_path": str(context),
                    "log_path": str(log),
                    "receipt_path": str(receipt),
                },
                exclusive=True,
            )
        )
        process.communicate(timeout=timeout)
        return json.loads(receipt.read_text(encoding="utf-8")), log.read_text(
            encoding="utf-8", errors="replace"
        )

    def test_stderr_noise_no_longer_terminalises_a_launch_as_blocked(self):
        published, log = self._detached({"PYTHONVERBOSE": "1"})

        # The receipt keeps the child's real, specific outcome...
        self.assertEqual(published["status"], "denied")
        self.assertEqual(published["terminal_outcome"], "denied")
        self.assertIn(REJECTED_REASON, published["reason"])
        self.assertNotIn(ANONYMOUS, published["reason"])
        # ...and the diagnostics are relocated to the transcript, not dropped.
        self.assertIn("import ", log)

    def test_early_exception_becomes_a_receipt_naming_the_exception(self):
        shadow_directory = tempfile.TemporaryDirectory()
        self.addCleanup(shadow_directory.cleanup)
        shadow = Path(shadow_directory.name)
        # `hmac` is imported by the trusted-launch heredoc and by nothing on the
        # detached transport's own Python path, so shadowing it raises inside the
        # child exactly where an unexpected initialisation failure would, and
        # nowhere else.
        (shadow / "hmac.py").write_text(
            'raise RuntimeError("board test: forced early import failure")\n',
            encoding="utf-8",
        )

        published, log = self._detached({"PYTHONPATH": str(shadow)})

        self.assertEqual(published["terminal_outcome"], "blocked")
        self.assertNotIn(ANONYMOUS, published["reason"])
        self.assertIn("uncaught exception", published["reason"])
        self.assertIn("RuntimeError", published["reason"])
        self.assertIn("board test: forced early import failure", published["reason"])
        # The traceback survives on the human channel.
        self.assertIn("Traceback (most recent call last)", log)


class SupervisorChannelDisciplineTests(unittest.TestCase):
    """Structural pins on which stream each kind of output is allowed to use."""

    def test_detached_capture_takes_stdout_only(self):
        text = SUPERVISOR.read_text(encoding="utf-8")
        detached = text.index('if [[ "${1:-}" == "detached-launch" ]]')
        trusted = text.index('if [[ "${1:-}" == "trusted-launch" ]]')
        body = text[detached:trusted]
        self.assertIn('>"$receipt_capture" 2>&4', body)
        self.assertNotIn('>"$receipt_capture" 2>&1', body)
        self.assertLess(body.index('exec 4>>"$log_path"'), body.index("2>&4"))

    def test_no_structured_receipt_is_written_to_stderr(self):
        # These two denials printed a receipt to stderr and were readable only
        # because the detached wrapper merged the streams. With the streams
        # separated they would land in the transcript and leave the machine
        # channel empty, so a specific denial would present as an unexplained
        # empty capture.
        offenders = [
            line.strip()
            for line in SUPERVISOR.read_text(encoding="utf-8").splitlines()
            if '{"status":' in line and ">&2" in line
        ]
        self.assertEqual(offenders, [])

    def test_uncaught_exception_funnel_is_installed_before_every_other_import(self):
        text = SUPERVISOR.read_text(encoding="utf-8")
        heredoc = text.index("exec \"$python_bin\" - \"$context_file\" <<'PYEOF'")
        body = text[heredoc:]
        install = body.index("sys.excepthook = _uncaught_launch_exception")
        for module in ("import hashlib", "import hmac", "import subprocess"):
            self.assertLess(install, body.index(module), module)
        # os._exit, because an excepthook cannot raise its way out of the process.
        self.assertIn("os._exit(75)", body[:install])


if __name__ == "__main__":
    unittest.main()
