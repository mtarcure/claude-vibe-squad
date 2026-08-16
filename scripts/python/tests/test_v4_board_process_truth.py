from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
import json
import os
from pathlib import Path
from unittest import mock
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "bin" / "vs-board-snapshot.py"
CANCEL = ROOT / "bin" / "vs-cancel-spawn.sh"
DASHBOARD = ROOT / "bin" / "vs-board-dashboard.py"
SIDEBAR = ROOT / "bin" / "sidebar.sh"
SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"
sys.path.insert(0, str(ROOT / "scripts" / "python"))
import board_process_truth as bpt  # noqa: E402


def _run_snapshot(vault: Path, **extra_env: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SNAPSHOT)],
        env={**environment, "VAULT_ROOT": str(vault)},
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _live_identity(pid: int) -> dict:
    identity = bpt.observe_process(pid)
    assert identity is not None
    return identity


def _attempt_files(vault: Path, task: str, attempt: str) -> dict:
    board = vault / "_state" / "board-dispatch"
    base = board / f"{task}.{attempt}"
    return {
        "base": base,
        "dispatch": Path(f"{base}.dispatch.json"),
        "context": Path(f"{base}.context.json"),
        "log": Path(f"{base}.log"),
        "receipt": Path(f"{base}.receipt.json"),
    }


def _descriptor(
    vault: Path, task: str, attempt: str, pid: int, generation: int = 1
) -> dict:
    paths = _attempt_files(vault, task, attempt)
    return {
        "schema": "board-dispatch-process/v2",
        "task_id": task,
        "attempt_id": attempt,
        "generation": generation,
        "created_at": "2026-08-07T12:34:56Z",
        **_live_identity(pid),
        "context_path": str(paths["context"]),
        "log_path": str(paths["log"]),
        "receipt_path": str(paths["receipt"]),
    }


def _context(
    task: str, attempt: str, generation: int = 1, lane: str = "codex"
) -> dict:
    return {
        "authority": {
            "task_id": task,
            "attempt_id": attempt,
            "generation": generation,
            "lane": lane,
            "specialist": "backend-engineer",
            "lane_args": ["--model", "test-model"],
            "created_at": 1786123456,
        },
        "task_prompt": "# Exact process truth\n",
    }


class BoardProcessTruthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary.name).resolve()
        self.live = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)

    def tearDown(self):
        if self.live.poll() is None:
            self.live.kill()
        self.live.wait()
        self.temporary.cleanup()

    def test_snapshot_ignores_stale_receipt_and_never_uses_mtime_for_start(self):
        task, attempt = "TASK-exact", "d-current"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid, generation=2)
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt, generation=2))
        paths["log"].write_text("", encoding="utf-8")
        _write_json(
            paths["receipt"],
            {
                "schema": "board-dispatch-receipt/v2",
                "task_id": task,
                "attempt_id": attempt,
                "generation": 1,
                "status": "launched",
                "terminal_outcome": "complete",
                "completed_at": "2026-08-07T12:35:56Z",
                "descriptor_sha256": bpt.descriptor_hash(descriptor),
            },
        )
        os.utime(paths["dispatch"], (1, 1))

        result = _run_snapshot(self.vault)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("@SPAWN\tTASK-exact\t", result.stdout)
        self.assertIn("\t1786106096\t", result.stdout)
        self.assertNotIn("@DONE", result.stdout)

        _write_json(
            paths["receipt"],
            {"task_id": task, "attempt_id": attempt, "status": "launched"},
        )
        legacy_result = _run_snapshot(self.vault)
        self.assertEqual(legacy_result.returncode, 0, legacy_result.stderr)
        self.assertIn("@SPAWN\tTASK-exact\t", legacy_result.stdout)
        self.assertNotIn("@DONE", legacy_result.stdout)

    def test_snapshot_rejects_pid_reuse_identity_mismatch_as_defect(self):
        task, attempt = "TASK-reused", "d-reused"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        descriptor["argv_sha256"] = hashlib.sha256(b"different process").hexdigest()
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt))

        result = _run_snapshot(self.vault)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("@SPAWN", result.stdout)
        self.assertIn(
            "@DEFECT\tTASK-reused\td-reused\t1\tprocess_identity_mismatch",
            result.stdout,
        )

    def test_snapshot_accepts_exact_v2_and_legacy_v1_terminal_receipts(self):
        task, attempt = "TASK-done", "d-done"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt))
        _write_json(
            paths["receipt"],
            {
                "schema": "board-dispatch-receipt/v2",
                "task_id": task,
                "attempt_id": attempt,
                "generation": 1,
                "status": "launched",
                "response_status": "complete",
                "terminal_outcome": "complete",
                "completed_at": "2026-08-07T12:35:56Z",
                "descriptor_sha256": bpt.descriptor_hash(descriptor),
            },
        )
        os.utime(paths["receipt"], (2, 2))

        legacy_task, legacy_attempt = "TASK-legacy", "d-legacy"
        legacy = _attempt_files(self.vault, legacy_task, legacy_attempt)
        _write_json(
            legacy["dispatch"],
            {
                "schema": "board-dispatch-process/v1",
                "task_id": legacy_task,
                "attempt_id": legacy_attempt,
                "generation": 1,
                "pid": 99999999,
                "context_path": str(legacy["context"]),
                "log_path": str(legacy["log"]),
                "receipt_path": str(legacy["receipt"]),
            },
        )
        _write_json(legacy["context"], _context(legacy_task, legacy_attempt))
        _write_json(
            legacy["receipt"],
            {
                "task_id": legacy_task,
                "attempt_id": legacy_attempt,
                "status": "launched",
                "response_status": "needs_review",
            },
        )

        result = _run_snapshot(self.vault)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "@DONE\t1786106156\tTASK-done\tcodex\tbackend-engineer\tcomplete",
            result.stdout,
        )
        self.assertIn(
            "@DONE\t0\tTASK-legacy\tcodex\tbackend-engineer\tneeds_review",
            result.stdout,
        )
        self.assertNotIn("@SPAWN", result.stdout)

    def test_terminal_outcome_requires_exact_integer_generations(self):
        task, attempt = "TASK-generation-type", "d-generation-type"
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        receipt = {
            "schema": "board-dispatch-receipt/v2",
            "task_id": task,
            "attempt_id": attempt,
            "generation": 1,
            "terminal_outcome": "complete",
            "completed_at": "2026-08-07T12:35:56Z",
            "descriptor_sha256": bpt.descriptor_hash(descriptor),
        }
        self.assertEqual(bpt.terminal_outcome(receipt, descriptor), "complete")
        for invalid in (True, 1.0):
            with self.subTest(receipt_generation=invalid):
                forged = {**receipt, "generation": invalid}
                self.assertIsNone(bpt.terminal_outcome(forged, descriptor))
            with self.subTest(descriptor_generation=invalid):
                forged_descriptor = {**descriptor, "generation": invalid}
                forged = {
                    **receipt,
                    "descriptor_sha256": bpt.descriptor_hash(forged_descriptor),
                }
                self.assertIsNone(bpt.terminal_outcome(forged, forged_descriptor))
        legacy_descriptor = {
            "schema": "board-dispatch-process/v1",
            "task_id": task,
            "attempt_id": attempt,
            "generation": 1,
        }
        legacy_receipt = {
            "task_id": task,
            "attempt_id": attempt,
            "generation": 1,
            "status": "launched",
        }
        self.assertEqual(
            bpt.terminal_outcome(legacy_receipt, legacy_descriptor), "complete"
        )
        exact_context = {"authority": {**legacy_descriptor}}
        self.assertTrue(bpt.context_matches(legacy_descriptor, exact_context))
        for invalid in (True, 1.0):
            with self.subTest(legacy_receipt_generation=invalid):
                self.assertIsNone(
                    bpt.terminal_outcome(
                        {**legacy_receipt, "generation": invalid}, legacy_descriptor
                    )
                )
            with self.subTest(context_generation=invalid):
                self.assertFalse(
                    bpt.context_matches(
                        legacy_descriptor,
                        {"authority": {**legacy_descriptor, "generation": invalid}},
                    )
                )
            with self.subTest(context_descriptor_generation=invalid):
                self.assertFalse(
                    bpt.context_matches(
                        {**legacy_descriptor, "generation": invalid}, exact_context
                    )
                )

        descriptor_path = _attempt_files(self.vault, task, attempt)["dispatch"]
        for value in (None, False, 1, 1.0, "invalid", [], {}):
            with self.subTest(descriptor_json_type=type(value).__name__):
                self.assertEqual(
                    bpt.descriptor_error(descriptor_path, value),
                    "descriptor_schema",
                )
                self.assertIsNone(bpt.terminal_outcome(receipt, value))
        for value in ([], {}):
            with self.subTest(unhashable_receipt_value=type(value).__name__):
                self.assertIsNone(
                    bpt.terminal_outcome(
                        {**receipt, "terminal_outcome": value}, descriptor
                    )
                )
                self.assertIsNone(
                    bpt.terminal_outcome(
                        {**legacy_receipt, "schema": value}, legacy_descriptor
                    )
                )
                self.assertIsNone(
                    bpt.terminal_outcome(
                        {**legacy_receipt, "status": value}, legacy_descriptor
                    )
                )
        for value in (True, 1.0):
            with self.subTest(pgid=value):
                forged = {**descriptor, "pid": 1, "pgid": value}
                self.assertEqual(
                    bpt.descriptor_error(descriptor_path, forged),
                    "descriptor_process_identity",
                )

    def test_snapshot_fails_closed_for_unhashable_json_fields(self):
        for ordinal, outcome in enumerate(([], {}), start=1):
            task, attempt = f"TASK-json-outcome-{ordinal}", f"d-json-outcome-{ordinal}"
            paths = _attempt_files(self.vault, task, attempt)
            descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
            _write_json(paths["dispatch"], descriptor)
            _write_json(paths["context"], _context(task, attempt))
            _write_json(
                paths["receipt"],
                {
                    "schema": "board-dispatch-receipt/v2",
                    "task_id": task,
                    "attempt_id": attempt,
                    "generation": 1,
                    "terminal_outcome": outcome,
                    "completed_at": "2026-08-07T12:35:56Z",
                    "descriptor_sha256": bpt.descriptor_hash(descriptor),
                },
            )
        for ordinal, schema in enumerate(([], {}), start=1):
            task, attempt = f"TASK-json-schema-{ordinal}", f"d-json-schema-{ordinal}"
            paths = _attempt_files(self.vault, task, attempt)
            descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
            _write_json(paths["dispatch"], {**descriptor, "schema": schema})

        result = _run_snapshot(self.vault)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("@SPAWN\tTASK-json-outcome-"), 2)
        self.assertEqual(result.stdout.count("\tdescriptor_schema"), 2)
        self.assertNotIn("@DONE", result.stdout)

    def test_finalizer_rejects_aliased_generation_and_nonstring_status(self):
        cases = (
            ("missing", {"status": "launched"}, "complete"),
            ("exact", {"generation": 1, "status": "launched"}, "complete"),
            ("bool-generation", {"generation": True, "status": "launched"}, "blocked"),
            ("float-generation", {"generation": 1.0, "status": "launched"}, "blocked"),
            ("response-list", {"status": "launched", "response_status": []}, "blocked"),
            ("response-dict", {"status": "launched", "response_status": {}}, "blocked"),
            ("status-list", {"status": []}, "blocked"),
            ("status-dict", {"status": {}}, "blocked"),
        )
        for ordinal, (label, raw_payload, expected) in enumerate(cases, start=1):
            with self.subTest(label=label):
                task, attempt = f"TASK-finalize-{ordinal}", f"d-finalize-{ordinal}"
                paths = _attempt_files(self.vault, task, attempt)
                descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
                _write_json(paths["dispatch"], descriptor)
                raw = Path(f"{paths['receipt']}.capture")
                _write_json(raw, raw_payload)

                receipt = bpt.finalize_receipt(raw, paths["dispatch"], paths["receipt"])

                self.assertEqual(receipt["terminal_outcome"], expected)
                self.assertEqual(bpt.terminal_outcome(receipt, descriptor), expected)

    def test_cancel_refuses_ambiguous_task_only_selector_without_mtime_choice(self):
        task = "TASK-ambiguous"
        for number in (1, 2):
            attempt = f"d-{number}"
            paths = _attempt_files(self.vault, task, attempt)
            descriptor = {
                "schema": "board-dispatch-process/v2",
                "task_id": task,
                "attempt_id": attempt,
                "generation": number,
                "created_at": "2026-08-07T12:34:56Z",
                "pid": 99999999,
                "pgid": 99999999,
                "process_start_token": "dead",
                "argv_sha256": "0" * 64,
                "context_path": str(paths["context"]),
                "log_path": str(paths["log"]),
                "receipt_path": str(paths["receipt"]),
            }
            _write_json(paths["dispatch"], descriptor)
            _write_json(paths["context"], _context(task, attempt, generation=number))
            os.utime(paths["dispatch"], (number, number))

        result = subprocess.run(
            ["bash", str(CANCEL), task],
            env={**os.environ, "VAULT_ROOT": str(self.vault)},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("exact", (result.stdout + result.stderr).lower())
        self.assertFalse(
            list((self.vault / "_state" / "board-dispatch").glob("*.receipt.json"))
        )

    def test_dashboard_visibly_surfaces_process_truth_defect(self):
        result = subprocess.run(
            [sys.executable, str(DASHBOARD), "--stdin"],
            input="@DEFECT\tTASK-bad\td-bad\t2\tprocess_identity_mismatch\n",
            env={**os.environ, "VAULT_ROOT": str(self.vault), "NO_COLOR": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 process defect(s)", result.stdout)
        self.assertIn("TASK-bad/d-bad: process_identity_mismatch", result.stdout)

    def test_strict_json_and_bad_timestamps_fail_closed_without_snapshot_crash(self):
        board = self.vault / "_state" / "board-dispatch"
        board.mkdir(parents=True)
        duplicate = board / "TASK-duplicate.d-bad.dispatch.json"
        duplicate.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
        overflow = board / "TASK-overflow.d-bad.dispatch.json"
        overflow.write_text('{"schema":"x","value":1e999}\n', encoding="utf-8")
        nested = board / "TASK-nested.d-bad.dispatch.json"
        nested.write_text("[" * 1200 + "]" * 1200, encoding="utf-8")

        task, attempt = "TASK-nan", "d-live"
        paths = _attempt_files(self.vault, task, attempt)
        _write_json(
            paths["dispatch"], _descriptor(self.vault, task, attempt, self.live.pid)
        )
        _write_json(paths["context"], _context(task, attempt))
        paths["receipt"].write_text('{"completed_at":NaN}\n', encoding="utf-8")

        bad_task, bad_attempt = "TASK-time", "d-bad"
        bad = _attempt_files(self.vault, bad_task, bad_attempt)
        malformed = _descriptor(self.vault, bad_task, bad_attempt, self.live.pid)
        malformed["created_at"] = "not-a-timestamp"
        _write_json(bad["dispatch"], malformed)
        _write_json(bad["context"], _context(bad_task, bad_attempt))

        result = _run_snapshot(self.vault)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("descriptor_json_invalid"), 3)
        self.assertIn("@SPAWN\tTASK-nan\t", result.stdout)
        self.assertIn(
            "@DEFECT\tTASK-time\td-bad\t1\tdescriptor_process_identity", result.stdout
        )

    def test_atomic_exclusive_publication_never_replaces_a_winner(self):
        destination = self.vault / "receipt.json"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda value: bpt.atomic_write_json(
                        destination, {"winner": value}, exclusive=True
                    ),
                    (1, 2),
                )
            )
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)
        winner = destination.read_bytes()
        self.assertFalse(
            bpt.atomic_write_json(destination, {"winner": 3}, exclusive=True)
        )
        self.assertEqual(destination.read_bytes(), winner)

    def test_finalize_binds_locked_descriptor_inode_before_publication(self):
        task, attempt = "TASK-swap", "d-live"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        _write_json(paths["dispatch"], descriptor)
        raw = Path(f"{paths['receipt']}.capture")
        _write_json(raw, {"status": "launched"})
        real_locked = bpt._locked

        def lock_then_swap(path):
            locked = real_locked(path)
            replacement = Path(f"{path}.replacement")
            _write_json(replacement, descriptor)
            os.replace(replacement, path)
            return locked

        with mock.patch.object(bpt, "_locked", side_effect=lock_then_swap):
            with self.assertRaises(bpt.ProcessTruthError):
                bpt.finalize_receipt(raw, paths["dispatch"], paths["receipt"])
        self.assertFalse(paths["receipt"].exists())

    def test_finalizer_refuses_dead_v2_process_identity(self):
        task, attempt = "TASK-dead", "d-dead"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        descriptor.update({"pid": 99999999, "pgid": 99999999})
        _write_json(paths["dispatch"], descriptor)
        raw = Path(f"{paths['receipt']}.capture")
        _write_json(raw, {"status": "launched"})

        with self.assertRaises(bpt.ProcessTruthError):
            bpt.finalize_receipt(raw, paths["dispatch"], paths["receipt"])
        self.assertFalse(paths["receipt"].exists())

    def test_descriptor_hash_makes_final_publication_window_swap_inert(self):
        task, attempt = "TASK-late-swap", "d-live"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        replacement = {**descriptor, "created_at": "2026-08-07T12:34:57Z"}
        _write_json(paths["dispatch"], descriptor)
        raw = Path(f"{paths['receipt']}.capture")
        _write_json(raw, {"status": "launched"})
        real_atomic = bpt.atomic_write_json

        def swap_then_publish(path, value, *, exclusive=False):
            _write_json(paths["dispatch"], replacement)
            return real_atomic(path, value, exclusive=exclusive)

        with mock.patch.object(bpt, "atomic_write_json", side_effect=swap_then_publish):
            bpt.finalize_receipt(raw, paths["dispatch"], paths["receipt"])

        receipt = bpt.load_json(paths["receipt"])
        self.assertIsNone(
            bpt.terminal_outcome(receipt, bpt.load_json(paths["dispatch"]))
        )

    def test_cancel_refuses_before_signal_when_exact_reconciler_is_missing(self):
        task, attempt = "TASK-no-reconciler", "d-live"
        paths = _attempt_files(self.vault, task, attempt)
        _write_json(
            paths["dispatch"], _descriptor(self.vault, task, attempt, self.live.pid)
        )
        _write_json(paths["context"], _context(task, attempt))
        paths["log"].write_text("", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(CANCEL), str(paths["log"])],
            env={**os.environ, "VAULT_ROOT": str(self.vault)},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.live.poll())
        self.assertFalse(paths["receipt"].exists())

    def test_cancel_kills_currently_attributable_escaped_session_then_receipts(self):
        child_pid_file = self.vault / "child.pid"
        source = SUPERVISOR.read_text(encoding="utf-8")
        hold_start = source.index("def hold_for_operator_stop(reason):")
        # Slice to the next TOP-LEVEL def, not to the first blank line. The old
        # heuristic truncated the moment the function grew a multi-paragraph
        # docstring, silently emitting invalid Python into the child program --
        # which then died before writing its pid file, and the failure surfaced
        # here as an unrelated missing-file assertion.
        hold_end = source.index("\ndef ", hold_start + 1)
        hold_source = source[hold_start:hold_end]
        program = (
            "from pathlib import Path; import json,os,signal,subprocess,sys\n"
            "write_board_note=lambda text: None\n"
            f"{hold_source}\n"
            "same=subprocess.Popen(['/bin/sleep','30'])\n"
            # This escaped session remains in the live PPID tree and is attributable.
            "escaped=subprocess.Popen(['/bin/sleep','30'], start_new_session=True)\n"
            "Path(sys.argv[1]).write_text(json.dumps([same.pid,escaped.pid]))\n"
            "hold_for_operator_stop('forced cleanup failure')"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", program, str(child_pid_file)],
            start_new_session=True,
        )
        try:
            for _ in range(100):
                if child_pid_file.exists():
                    break
                time.sleep(0.01)
            self.assertTrue(child_pid_file.exists())
            descendant_pids = json.loads(child_pid_file.read_text(encoding="utf-8"))
            task, attempt, generation = "TASK-cancel", "d-live", 3
            paths = _attempt_files(self.vault, task, attempt)
            _write_json(
                paths["dispatch"],
                _descriptor(self.vault, task, attempt, child.pid, generation),
            )
            context = _context(task, attempt, generation)
            context["authority"]["expected_outbox_path"] = (
                f"departments/coding/outbox/{task}-response.md"
            )
            _write_json(paths["context"], context)
            paths["log"].write_text("", encoding="utf-8")
            self.assertFalse(paths["receipt"].exists())
            self.assertEqual(
                bpt.process_truth(paths["dispatch"], bpt.load_json(paths["dispatch"]))[
                    "state"
                ],
                "live",
            )
            reconciler = self.vault / "bin" / "registry-reconciler.sh"
            reconciler.parent.mkdir(parents=True)
            reconciler.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" > "$VAULT_ROOT/reconcile.args"\n',
                encoding="utf-8",
            )
            reconciler.chmod(0o755)

            result = subprocess.run(
                ["bash", str(CANCEL), str(paths["log"])],
                env={
                    **os.environ,
                    "VAULT_ROOT": str(self.vault),
                    "VS_CANCEL_GRACE_SECONDS": "0.1",
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            child.wait(timeout=3)
            receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema"], "board-dispatch-receipt/v2")
            self.assertEqual(
                (receipt["task_id"], receipt["attempt_id"], receipt["generation"]),
                (task, attempt, generation),
            )
            self.assertEqual(receipt["terminal_outcome"], "cancelled")
            self.assertTrue(receipt["completed_at"].endswith("Z"))
            self.assertTrue(
                all(bpt.observe_process(pid) is None for pid in descendant_pids)
            )
            self.assertEqual(
                (self.vault / "reconcile.args").read_text(encoding="utf-8").strip(),
                f"--task-id {task}",
            )

            duplicate = subprocess.run(
                ["bash", str(CANCEL), str(paths["log"])],
                env={**os.environ, "VAULT_ROOT": str(self.vault)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual(
                json.loads(paths["receipt"].read_text(encoding="utf-8")), receipt
            )
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            for descendant_pid in locals().get("descendant_pids", []):
                try:
                    os.kill(descendant_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.wait()

    def test_cancel_terminates_tree_before_authoring_receipt(self):
        source = inspect.getsource(bpt.cancel_attempt)
        self.assertLess(
            source.index("terminate_attributable_tree"),
            source.index('"status": "cancelled"'),
        )

    def test_cancel_refuses_mismatched_live_pid_without_signalling(self):
        child = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
        try:
            task, attempt = "TASK-refuse", "d-live"
            paths = _attempt_files(self.vault, task, attempt)
            descriptor = _descriptor(self.vault, task, attempt, child.pid)
            descriptor["process_start_token"] = "not-this-process"
            _write_json(paths["dispatch"], descriptor)
            _write_json(paths["context"], _context(task, attempt))

            result = subprocess.run(
                ["bash", str(CANCEL), str(paths["log"])],
                env={**os.environ, "VAULT_ROOT": str(self.vault)},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(child.poll())
            self.assertFalse(paths["receipt"].exists())
        finally:
            child.kill()
            child.wait()


class ReapDeadAttemptTests(unittest.TestCase):
    """A dispatch whose process died without a receipt must be resolvable.

    Without a reap path the board wedges permanently: discover_live_attempts()
    fails closed on dead+receiptless descriptors, while cancel_attempt() and
    finalize_receipt() both refuse anything that is not an exact live process.
    SIGKILL cannot be trapped, so a supervisor that "always receipts on exit"
    cannot close this on its own.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary.name).resolve()
        self.live = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)

    def tearDown(self):
        if self.live.poll() is None:
            self.live.kill()
        self.live.wait()
        self.temporary.cleanup()

    def _dead_attempt(self, task="TASK-reap", attempt="d-reap"):
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        descriptor.update({"pid": 99999999, "pgid": 99999999})
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt))
        return paths, descriptor

    def test_reap_publishes_fenced_receipt_for_dead_attempt(self):
        paths, descriptor = self._dead_attempt()
        self.assertEqual(
            bpt.process_truth(paths["dispatch"], descriptor)["reason"],
            "process_not_live",
        )

        receipt = bpt.reap_dead_attempt(paths["dispatch"])

        self.assertTrue(paths["receipt"].exists())
        self.assertEqual(receipt["terminal_outcome"], "failed")
        self.assertEqual(receipt["failure_class"], "process_died_without_receipt")
        # The published receipt must satisfy the exact same fence the admission
        # reader uses, or the board stays wedged despite a receipt existing.
        self.assertEqual(
            bpt.terminal_outcome(bpt.load_json(paths["receipt"]), descriptor),
            "failed",
        )

    def test_reap_unwedges_the_admission_reader(self):
        paths, _ = self._dead_attempt()
        sys.path.insert(0, str(ROOT / "scripts" / "python"))
        import host_admission as ha

        with self.assertRaises(ha.HostStateError):
            ha.discover_live_attempts(self.vault)

        bpt.reap_dead_attempt(paths["dispatch"])

        self.assertEqual(ha.discover_live_attempts(self.vault), ())

    def test_reap_refuses_a_live_attempt(self):
        task, attempt = "TASK-live", "d-live"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt))

        with self.assertRaises(bpt.ProcessTruthError):
            bpt.reap_dead_attempt(paths["dispatch"])
        self.assertFalse(paths["receipt"].exists())

    def test_reap_refuses_pid_reuse_identity_mismatch(self):
        """A recycled PID is ambiguous — reaping it could mask a live process."""
        task, attempt = "TASK-reuse", "d-reuse"
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(self.vault, task, attempt, self.live.pid)
        descriptor["process_start_token"] = "ps:Mon Jan 1 00:00:00 2001"
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], _context(task, attempt))
        self.assertEqual(
            bpt.process_truth(paths["dispatch"], descriptor)["state"], "mismatch"
        )

        with self.assertRaises(bpt.ProcessTruthError):
            bpt.reap_dead_attempt(paths["dispatch"])
        self.assertFalse(paths["receipt"].exists())

    def test_reap_refuses_when_a_receipt_already_exists(self):
        paths, _ = self._dead_attempt()
        _write_json(paths["receipt"], {"schema": "board-dispatch-receipt/v2"})
        original = paths["receipt"].read_bytes()

        with self.assertRaises(bpt.ProcessTruthError):
            bpt.reap_dead_attempt(paths["dispatch"])
        self.assertEqual(paths["receipt"].read_bytes(), original)


if __name__ == "__main__":
    unittest.main()


class OperatorStopIsResumableTests(unittest.TestCase):
    """hold_for_operator_stop must freeze once, not forever.

    It was `while True: os.kill(os.getpid(), signal.SIGSTOP)`, which made SIGCONT
    useless: resuming only looped back into another stop, so the sole exit was
    SIGKILL. On 2026-08-09 that froze a lane in state T for 48 minutes with a live
    descriptor, no receipt, no artifact, and a registry entry stuck in-flight.
    vs-cancel-spawn.sh refused the same attempt for the very identity reason that
    triggered the hold, so the documented tool could not clear it either.

    The freeze itself is correct -- the identity guard fires when a PID may have
    been recycled, and signalling an unverifiable process is worse than stalling.
    These tests pin the three things that were wrong with HOW it stalled.
    """

    def setUp(self) -> None:
        self.text = SUPERVISOR.read_text(encoding="utf-8")

    def _hold_body(self) -> str:
        """The executable body only — the docstring quotes the old bug verbatim."""
        hold = self.text[self.text.index("def hold_for_operator_stop"):]
        hold = hold[: hold.index("\ndef ", 1)]
        # drop the triple-quoted docstring; it contains the string under test
        first = hold.find('"""')
        if first != -1:
            second = hold.find('"""', first + 3)
            if second != -1:
                hold = hold[:first] + hold[second + 3:]
        return hold

    def test_the_stop_is_not_an_infinite_loop(self) -> None:
        hold = self._hold_body()
        self.assertIn("os.kill(os.getpid(), signal.SIGSTOP)", hold)
        self.assertNotIn(
            "while True:", hold,
            "an unresumable stop can only be cleared with SIGKILL",
        )

    def test_the_note_carries_a_recovery_command(self) -> None:
        hold = self._hold_body()
        self.assertIn("reap", hold, "the note must name the command that clears this")
        self.assertIn("SIGCONT", hold, "the note must say resuming is an option")

    def test_resuming_terminalises_instead_of_stranding(self) -> None:
        hold = self._hold_body()
        self.assertIn(
            "block_after_provision(", hold,
            "past the stop it must reach a terminal state; a resumed supervisor "
            "that simply exits leaves the registry stranded in-flight",
        )

    def test_cancel_wrapper_exposes_the_reap_path(self) -> None:
        wrapper = (ROOT / "bin" / "vs-cancel-spawn.sh").read_text(encoding="utf-8")
        self.assertIn("--reap", wrapper)
        self.assertIn("reap \"$VAULT_ROOT\"", wrapper)
