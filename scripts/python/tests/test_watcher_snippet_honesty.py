"""The dispatch watcher must not report TERMINAL when it cannot read status.

This test does NOT hand-copy the watcher's shell logic into a Python-side
constant. A reimplementation can stay green while the shipped snippet in
bin/send-task.sh regresses, which is exactly the honesty bug this test
guards against. Instead it extracts the live status-classification block
(the `s=$(...)` computation through the closing `esac`) out of the
`ATTACH A WATCHER` heredoc in bin/send-task.sh at run time, and executes
that extracted text -- unmodified except for supplying VAULT_ROOT/TASK_ID
values through the *same* heredoc-expansion mechanism bin/send-task.sh
itself uses to print the snippet a user pastes and runs.

Two stages of real bash execution are used:

  Stage 1 (heredoc expansion): the extracted lines are dropped into a
  throwaway `cat <<EOF ... EOF` heredoc, with VAULT_ROOT/TASK_ID set as
  ordinary shell variables. This performs exactly the same variable
  substitution and backslash-unescaping that bin/send-task.sh performs
  when it prints the watcher snippet for a human to copy-paste. The
  stdout of stage 1 is therefore byte-for-byte what a real dispatch would
  print for the classification block, given those VAULT_ROOT/TASK_ID
  values.

  Stage 2 (execution): that printed text -- real `case` arms, unedited --
  is executed for real against a test registry file. The silent
  keep-waiting arms (`: ;;`) fall through to a sentinel `echo RETRY` that
  this test appends *after* the extracted block, since the shipped code
  itself intentionally prints nothing on those arms (it just loops). The
  terminal arm's own `echo "TERMINAL status=$s"; exit 0` short-circuits
  before the sentinel is reached, so its wording comes only from the
  shipped code.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEND_TASK_SH = ROOT / "bin" / "send-task.sh"

_HEREDOC_START = "cat <<WATCHER"
_HEREDOC_END = "WATCHER"
_CLASSIFY_START = re.compile(r"^\s*s=\\\$\(python3\b")
_SLEEP_LINE = re.compile(r"^\s*sleep 20\s*$")


def _heredoc_body_lines() -> list[str]:
    """Return the raw lines of the ATTACH A WATCHER heredoc body in
    bin/send-task.sh, unmodified, still containing the `${VAR}` refs and
    `\\$`-escapes exactly as the source file has them.
    """
    lines = SEND_TASK_SH.read_text(encoding="utf-8").splitlines()
    heredoc_start = next(i for i, ln in enumerate(lines) if ln.strip() == _HEREDOC_START)
    heredoc_end = next(
        i for i in range(heredoc_start + 1, len(lines)) if lines[i] == _HEREDOC_END
    )
    return lines[heredoc_start + 1 : heredoc_end]


def _extract_classification_block() -> str:
    """Pull the live status-classification lines out of the ATTACH A
    WATCHER heredoc in bin/send-task.sh: from the `s=$(python3 ...)`
    line up to (but excluding) the `sleep 20` line that follows it.
    Works unchanged whether that block is an `if`-style check or a
    `case` statement -- it does not assume which.
    """
    body = _heredoc_body_lines()
    classify_start = next(i for i, ln in enumerate(body) if _CLASSIFY_START.match(ln))
    classify_end = next(
        i for i in range(classify_start, len(body)) if _SLEEP_LINE.match(body[i])
    )
    block = body[classify_start:classify_end]
    if not block:
        raise AssertionError("extracted classification block is empty")
    return "\n".join(block)


def _extract_full_watcher_body() -> str:
    """Return the ENTIRE ATTACH A WATCHER heredoc body verbatim -- the
    prose header line, the whole `for ... done; echo TIMEOUT; exit 3`
    loop (not just the classification block), and the prose footer line.
    Used to prove the loop-exhaustion path for real, not just its
    classification sub-block.
    """
    body = _heredoc_body_lines()
    if not body:
        raise AssertionError("watcher heredoc body is empty")
    return "\n".join(body)


def _expand_heredoc(body_text: str, **shell_vars: str) -> str:
    """Stage 1: run `body_text` through a real throwaway `cat <<EOF`
    heredoc with `shell_vars` set as ordinary shell variables. This is
    the exact mechanism bin/send-task.sh itself uses to turn `${VAR}`
    refs and `\\$`-escapes into the literal text a human copy-pastes and
    runs. Returns that literal text.
    """
    stage1_script = f"cat <<WATCHER_EXTRACT_EOF\n{body_text}\nWATCHER_EXTRACT_EOF"
    stage1_env = {**os.environ, **shell_vars}
    stage1 = subprocess.run(
        ["bash", "-c", stage1_script],
        capture_output=True,
        text=True,
        check=True,
        env=stage1_env,
    )
    return stage1.stdout


class WatcherSnippetHonesty(unittest.TestCase):
    def setUp(self) -> None:
        self.block = _extract_classification_block()

    def _run(self, registry_text: str) -> str:
        with tempfile.TemporaryDirectory() as d:
            vault_root = Path(d)
            (vault_root / "_state").mkdir()
            (vault_root / "_state" / "active-tasks.json").write_text(
                registry_text, encoding="utf-8"
            )

            # Stage 1: real heredoc expansion, identical mechanism to the
            # one bin/send-task.sh uses to print the snippet a user runs.
            # VAULT_ROOT/TASK_ID are supplied through the subprocess
            # environment (not shell-quoted inline) because the extracted
            # block itself contains literal single quotes (from the
            # python3 -c '...open(\'$VAR\'...)' invocation), which would
            # break naive inline quoting.
            expanded = _expand_heredoc(
                self.block, VAULT_ROOT=str(vault_root), TASK_ID="T1"
            )

            # Stage 2: execute the expanded (real, unedited) classification
            # text. The keep-waiting arms print nothing by design, so a
            # sentinel appended AFTER the block -- never inside it --
            # reports that as RETRY.
            stage2 = subprocess.run(
                ["bash", "-c", expanded + "\necho RETRY\n"],
                capture_output=True,
                text=True,
                check=True,
            )
            return stage2.stdout.strip()

    def test_malformed_registry_yields_retry_not_terminal(self) -> None:
        self.assertEqual(self._run("{ this is not json"), "RETRY")

    def test_missing_task_yields_retry_not_terminal(self) -> None:
        self.assertEqual(self._run(json.dumps({})), "RETRY")

    def test_real_terminal_status_is_reported(self) -> None:
        self.assertEqual(
            self._run(json.dumps({"T1": {"status": "complete"}})),
            "TERMINAL status=complete",
        )

    def test_in_flight_yields_retry(self) -> None:
        self.assertEqual(
            self._run(json.dumps({"T1": {"status": "in-flight"}})), "RETRY"
        )

    def test_loop_exhaustion_yields_timeout_and_exits_3(self) -> None:
        """The *second* stated behaviour change: TIMEOUT must exit 3, not
        0, so a timeout is distinguishable from a real landing. Runs the
        ENTIRE watcher loop (not just the classification sub-block) for
        real, against a registry that never resolves to terminal, so it
        must exhaust its iterations and hit `done; echo TIMEOUT; exit 3`.

        The loop bound and per-iteration sleep are shrunk (`seq 1 200` ->
        `seq 1 2`, `sleep 20` -> `sleep 0`) so the test runs fast. That
        substitution happens AFTER real heredoc expansion (Stage 1), as a
        plain string replace on the already-expanded, already-verbatim
        text -- it edits loop bounds/timing only, never the case-block
        classification logic under test, which is untouched real code.
        """
        full_body = _extract_full_watcher_body()
        with tempfile.TemporaryDirectory() as d:
            vault_root = Path(d)
            (vault_root / "_state").mkdir()
            (vault_root / "_state" / "active-tasks.json").write_text(
                json.dumps({"T1": {"status": "in-flight"}}), encoding="utf-8"
            )
            # Deliberately do NOT create the outbox response file: the
            # LANDED check must keep missing so the loop actually runs to
            # exhaustion instead of exiting early on the first line.

            expanded = _expand_heredoc(
                full_body,
                VAULT_ROOT=str(vault_root),
                TASK_ID="T1",
                COMPAT_NAMESPACE="ns",
            )
            # Drop the prose header/footer lines (e.g. "ATTACH A WATCHER
            # -- this session gets..."), which are not executable bash --
            # everything between them is the real for-loop, unedited.
            exec_lines = "\n".join(expanded.splitlines()[1:-1])
            exec_lines = exec_lines.replace("seq 1 200", "seq 1 2").replace(
                "sleep 20", "sleep 0"
            )

            result = subprocess.run(
                ["bash", "-c", exec_lines], capture_output=True, text=True
            )
            self.assertEqual(result.stdout.strip(), "TIMEOUT")
            self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
