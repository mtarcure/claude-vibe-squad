#!/usr/bin/env python3
"""Regression tests for board-receipt terminal settlement."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import registry_reconciler as reconciler  # noqa: E402
import dispatch_context_builder as dcb  # noqa: E402


class BoardReceiptSettlementTests(unittest.TestCase):
    @staticmethod
    def _v2_entry(task_id: str, attempt_id: str, **extra: object) -> dict[str, object]:
        generation = int(extra.pop("delivery_generation", 1))
        entry: dict[str, object] = {
            "status": "in-flight",
            "specialist": "sol",
            "to_model": "gpt-codex",
            "compatibility_namespace": "coding",
            "return_artifact": "_state/consults/result.md",
            "write_scope": ["_state/consults/result.md"],
            "delivery_attempt_id": attempt_id,
            "delivery_generation": generation,
            "delivery_state": "in-progress",
            "delivery_history": [
                {
                    "event": "in-progress",
                    "transport": "board-supervisor",
                    "attempt_id": attempt_id,
                    "generation": generation,
                }
            ],
            "dispatched_at": "2026-08-07T12:00:00+00:00",
        }
        entry.update(extra)
        return entry

    @staticmethod
    def _write_v2_descriptor(
        state: Path, task_id: str, attempt_id: str, generation: int = 1
    ) -> Path:
        board = state / "board-dispatch"
        board.mkdir(parents=True, exist_ok=True)
        base = board / f"{task_id}.{attempt_id}"
        descriptor = Path(f"{base}.dispatch.json")
        descriptor.write_text(
            json.dumps(
                {
                    "schema": "board-dispatch-process/v2",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "generation": generation,
                    "created_at": "2026-08-07T12:00:01Z",
                    "pid": 12345,
                    "pgid": 12345,
                    "process_start_token": "test:1",
                    "argv_sha256": "a" * 64,
                    "context_path": f"{base}.context.json",
                    "log_path": f"{base}.log",
                    "receipt_path": f"{base}.receipt.json",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return descriptor

    @staticmethod
    def _write_response(
        path: Path,
        task_id: str,
        status: str = "complete",
        *,
        attempt_id: str,
        generation: int = 1,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"id: {task_id}-response\n"
            f"in_response_to: {task_id}\n"
            "from: gpt-codex\n"
            "to: chrono\n"
            "type: RESULT\n"
            f"status: {status}\n"
            "return_artifact: _state/consults/result.md\n"
            f"delivery_attempt_id: {attempt_id}\n"
            f"delivery_generation: {generation}\n"
            "---\n\n"
            "Board result.\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_v2_receipt(
        descriptor: Path,
        *,
        completed_at: str,
        terminal_outcome: str = "complete",
        generation: int | None = None,
        descriptor_sha256: str | None = None,
    ) -> Path:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
        canonical_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        receipt = descriptor.with_name(
            descriptor.name.removesuffix(".dispatch.json") + ".receipt.json"
        )
        receipt.write_text(
            json.dumps(
                {
                    "schema": "board-dispatch-receipt/v2",
                    "task_id": payload["task_id"],
                    "attempt_id": payload["attempt_id"],
                    "generation": (
                        payload["generation"] if generation is None else generation
                    ),
                    "status": "launched",
                    "terminal_outcome": terminal_outcome,
                    "completed_at": completed_at,
                    "descriptor_sha256": descriptor_sha256 or canonical_hash,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return receipt

    @staticmethod
    @contextmanager
    def _patch_runtime(root: Path, state: Path, registry_path: Path):
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry_path),
            mock.patch.object(
                reconciler,
                "CHRONO_QUEUE_PATH",
                state / "chrono-queue.md",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_LOCKDIR",
                state / "chrono-notify.lockdir",
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                state / "chrono-notify-receipts",
            ),
            mock.patch.object(
                reconciler,
                "RESPONSE_MIN_AGE",
                reconciler.timedelta(seconds=0),
            ),
            mock.patch.dict(
                "os.environ",
                {reconciler.TEST_ISOLATION_ENV: "1"},
            ),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield

    def test_pruner_apply_retains_unresolved_board_receipt(self) -> None:
        """The deferred event needs its pass-one receipt to survive pass two."""

        task_id = "TASK-2026-08-26-1210-unresolved-receipt"
        attempt_id = "d-" + "9" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            (state / "board-worktrees").mkdir(parents=True)
            entry = self._v2_entry(task_id, attempt_id, status="blocked")
            registry_path.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
            )
            descriptor = self._write_v2_descriptor(state, task_id, attempt_id)
            receipt = self._write_v2_receipt(
                descriptor,
                completed_at="2026-01-01T00:00:00Z",
                terminal_outcome="failed",
            )
            entry["terminal_receipt_path"] = str(receipt.relative_to(root))
            registry_path.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
            )
            os.utime(receipt, (1, 1))

            # Run the production pruner source through its destructive branch
            # in an isolated vault. Redirect its one host-global scratch root
            # so this regression cannot touch another lane's /tmp state.
            pruner_source = (ROOT / "bin/prune-board-worktrees.sh").read_text(
                encoding="utf-8"
            )
            scratch_literal = 'pathlib.Path("/tmp/vs")'
            self.assertIn(scratch_literal, pruner_source)
            pruner_source = pruner_source.replace(
                scratch_literal,
                'pathlib.Path("_state/test-board-scratch")',
                1,
            )
            fixture_pruner = root / "bin/prune-board-worktrees.sh"
            fixture_pruner.parent.mkdir(parents=True)
            fixture_pruner.write_text(pruner_source, encoding="utf-8")
            fixture_helper = root / "shared/repo-root.sh"
            fixture_helper.parent.mkdir(parents=True)
            fixture_helper.write_bytes((ROOT / "shared/repo-root.sh").read_bytes())
            fixture_dispatch_log = root / "scripts/python/dispatch_log.py"
            fixture_dispatch_log.parent.mkdir(parents=True)
            fixture_dispatch_log.write_bytes(
                (ROOT / "scripts/python/dispatch_log.py").read_bytes()
            )

            environment = os.environ.copy()
            environment["VAULT_ROOT"] = str(root)
            applied = subprocess.run(
                ["bash", str(fixture_pruner), "--apply"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertIn("pruned 0", applied.stdout)
            self.assertTrue(
                receipt.is_file(),
                "pruner deleted an unresolved receipt required by the next "
                f"reconcile pass\nstdout={applied.stdout}\nstderr={applied.stderr}",
            )

    def test_blocked_receipt_closes_unpromoted_worktree_response_and_releases_scope(
        self,
    ) -> None:
        task_id = "TASK-2026-07-24-9998-blocked-board-receipt"
        attempt_id = "d-" + "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            board_dir = state / "board-dispatch"
            board_dir.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: {
                            "status": "in-flight",
                            "specialist": "sol",
                            "to_model": "gpt-codex",
                            "compatibility_namespace": "coding",
                            "return_artifact": "_state/consults/blocked.md",
                            "write_scope": ["shared/locked-scope"],
                            "delivery_attempt_id": attempt_id,
                            "delivery_generation": 1,
                            "delivery_state": "in-progress",
                            "dispatched_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipt_path = board_dir / f"{task_id}.{attempt_id}.receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "reason": "completion prevalidation failed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            worktree_response = (
                state
                / "board-worktrees"
                / attempt_id
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            worktree_response.parent.mkdir(parents=True)
            worktree_response.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: blocked\n"
                "return_artifact: _state/consults/blocked.md\n"
                "---\n\n"
                "Blocked before output promotion.\n",
                encoding="utf-8",
            )

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = registry[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], "blocked")
            self.assertEqual(
                entry["terminal_receipt_path"],
                str(receipt_path.relative_to(root)),
            )
            active_scopes = [
                scope
                for candidate in registry.values()
                if candidate.get("status") == "in-flight"
                for scope in candidate.get("write_scope", [])
            ]
            self.assertNotIn("shared/locked-scope", active_scopes)

    def test_advisory_completed_response_settles_terminal_and_releases_scope(
        self,
    ) -> None:
        task_id = "TASK-2026-07-24-9994-advisory-completed"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: {
                            "status": "in-flight",
                            "specialist": "sol",
                            "to_model": "gpt-codex",
                            "compatibility_namespace": "coding",
                            "return_artifact": "_state/consults/advisory.md",
                            "write_scope": ["_state/consults/advisory.md"],
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = state / "consults" / "advisory.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("Independent opinion.\n", encoding="utf-8")
            response = (
                root
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            response.parent.mkdir(parents=True)
            response.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: completed\n"
                "return_artifact: _state/consults/advisory.md\n"
                "---\n\n"
                "Advisory completed.\n",
                encoding="utf-8",
            )

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertGreater(changed, 0, messages)
            self.assertEqual(registry[task_id]["status"], "complete")
            self.assertFalse(
                any(
                    entry.get("status") == "in-flight"
                    for entry in registry.values()
                )
            )

    def test_v2_exact_fresh_response_beats_newer_wrong_namespace(self) -> None:
        task_id = "TASK-2026-08-07-1001-exact-response"
        attempt_id = "d-" + "1" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps({task_id: self._v2_entry(task_id, attempt_id)}) + "\n",
                encoding="utf-8",
            )
            self._write_v2_descriptor(state, task_id, attempt_id)
            exact = root / "departments/coding/outbox" / f"{task_id}-response.md"
            decoy = root / "departments/security/outbox" / f"{task_id}-response.md"
            self._write_response(
                exact, task_id, "complete", attempt_id=attempt_id
            )
            self._write_response(
                decoy, task_id, "blocked", attempt_id=attempt_id
            )
            os.utime(decoy, (2_000_000_000, 2_000_000_000))

            with self._patch_runtime(root, state, registry_path), mock.patch.object(
                reconciler, "RESPONSE_MIN_AGE", reconciler.timedelta(hours=1)
            ):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], "complete")
            self.assertEqual(
                entry["response_path"],
                f"departments/coding/outbox/{task_id}-response.md",
            )

    def test_v2_exact_path_with_wrong_identity_stays_open(self) -> None:
        task_id = "TASK-2026-08-07-1002-wrong-identity"
        attempt_id = "d-" + "2" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps({task_id: self._v2_entry(task_id, attempt_id)}) + "\n",
                encoding="utf-8",
            )
            self._write_v2_descriptor(state, task_id, attempt_id)
            response = root / "departments/coding/outbox" / f"{task_id}-response.md"
            self._write_response(
                response,
                "TASK-2026-08-07-9999-other",
                attempt_id=attempt_id,
            )

            with self._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "in-flight")

    def test_v2_stale_same_task_attempt_generation_response_stays_open(self) -> None:
        task_id = "TASK-2026-08-07-1002-stale-generation"
        current_attempt = "d-" + "a" * 32
        stale_attempt = "d-" + "b" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: self._v2_entry(
                            task_id,
                            current_attempt,
                            delivery_generation=2,
                        )
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_v2_descriptor(
                state, task_id, current_attempt, generation=2
            )
            response = root / "departments/coding/outbox" / f"{task_id}-response.md"
            self._write_response(
                response,
                task_id,
                attempt_id=stale_attempt,
                generation=1,
            )

            with self._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "in-flight")

            self._write_response(
                response,
                task_id,
                attempt_id=current_attempt,
                generation=2,
            )
            with self._patch_runtime(root, state, registry_path), mock.patch.object(
                reconciler, "RESPONSE_MIN_AGE", reconciler.timedelta(days=1)
            ):
                reconciler.reconcile(task_id, dry_run=False)
            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "complete")

    def test_board_history_without_current_attempt_never_falls_back_to_v1(self) -> None:
        current_attempt = "d-" + "c" * 32
        stale_attempt = "d-" + "d" * 32
        cases = {
            "missing-attempt": ({"generation": 2}, "missing"),
            "mismatched-attempt": (
                {"attempt_id": stale_attempt, "generation": 1},
                "malformed",
            ),
            "bool-generation": (
                {"attempt_id": current_attempt, "generation": True},
                "symlink",
            ),
            "zero-generation": (
                {"attempt_id": current_attempt, "generation": 0},
                "missing",
            ),
        }
        for ordinal, (case, (marker, descriptor_state)) in enumerate(
            cases.items(), start=1
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-11{ordinal:02d}-marker-{case}"
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                entry = self._v2_entry(
                    task_id, current_attempt, delivery_generation=2
                )
                entry["delivery_history"] = [
                    {
                        "event": "in-progress",
                        "transport": "board-supervisor",
                        **marker,
                    }
                ]
                registry_path.write_text(
                    json.dumps({task_id: entry}) + "\n", encoding="utf-8"
                )
                if descriptor_state != "missing":
                    descriptor = self._write_v2_descriptor(
                        state, task_id, current_attempt, generation=2
                    )
                    if descriptor_state == "malformed":
                        descriptor.write_text("{}\n", encoding="utf-8")
                    else:
                        target = descriptor.with_name("descriptor-target.json")
                        descriptor.replace(target)
                        descriptor.symlink_to(target)
                decoy = (
                    root
                    / "departments/security/archive"
                    / f"{task_id}-response.md"
                )
                self._write_response(
                    decoy,
                    task_id,
                    attempt_id=stale_attempt,
                    generation=1,
                )
                artifact = root / "_state/consults/result.md"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("legacy backstop decoy\n", encoding="utf-8")

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                settled = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(settled["status"], "in-flight")

    def test_explicit_v1_controls_remain_compatible(self) -> None:
        current_attempt = "d-" + "6" * 32
        for control in ("no-descriptor", "v1-descriptor", "v1-marker"):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as directory:
                marker_present = control == "v1-marker"
                task_id = (
                    "TASK-2026-08-07-1201-v1-" + control
                )
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                entry = self._v2_entry(task_id, current_attempt)
                if control != "no-descriptor":
                    descriptor = self._write_v2_descriptor(
                        state, task_id, current_attempt
                    )
                    payload = json.loads(descriptor.read_text(encoding="utf-8"))
                    payload["schema"] = "board-dispatch-process/v1"
                    descriptor.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                if not marker_present:
                    entry["delivery_history"] = []
                registry_path.write_text(
                    json.dumps({task_id: entry}) + "\n", encoding="utf-8"
                )
                response = (
                    root
                    / "departments/security/archive"
                    / f"{task_id}-response.md"
                )
                self._write_response(
                    response,
                    task_id,
                    "complete" if control != "no-descriptor" else "blocked",
                    attempt_id=current_attempt,
                )

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                settled = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(
                    settled["status"],
                    "complete" if control != "no-descriptor" else "blocked",
                )

    def test_process_v1_generation_two_cannot_downgrade(self) -> None:
        task_id = "TASK-2026-08-07-1202-v1-generation-two"
        attempt_id = "d-" + "8" * 32
        stale_attempt = "d-" + "1" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            entry = self._v2_entry(task_id, attempt_id, delivery_generation=2)
            registry_path.write_text(
                json.dumps({task_id: entry}) + "\n", encoding="utf-8"
            )
            descriptor = self._write_v2_descriptor(
                state, task_id, attempt_id, generation=2
            )
            payload = json.loads(descriptor.read_text(encoding="utf-8"))
            payload["schema"] = "board-dispatch-process/v1"
            descriptor.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            self._write_response(
                root / "departments/security/archive" / f"{task_id}-response.md",
                task_id,
                attempt_id=stale_attempt,
                generation=1,
            )

            with self._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)

            settled = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(settled["status"], "in-flight")

    def test_exact_v2_descriptor_never_downgrades_on_missing_history(self) -> None:
        attempt_id = "d-" + "7" * 32
        history_cases = {
            "missing": None,
            "empty": [],
            "non-list": {},
        }
        for ordinal, (case, history) in enumerate(history_cases.items(), start=1):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-125{ordinal}-v2-history-{case}"
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                entry = self._v2_entry(task_id, attempt_id)
                if history is None:
                    entry.pop("delivery_history")
                else:
                    entry["delivery_history"] = history
                registry_path.write_text(
                    json.dumps({task_id: entry}) + "\n", encoding="utf-8"
                )
                self._write_v2_descriptor(state, task_id, attempt_id)
                decoy = (
                    root
                    / "departments/security/archive"
                    / f"{task_id}-response.md"
                )
                self._write_response(
                    decoy,
                    task_id,
                    "blocked",
                    attempt_id="d-" + "1" * 32,
                    generation=9,
                )

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                settled = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(settled["status"], "in-flight")

    def test_controller_blocked_response_needs_descriptor_but_settles_with_one(self) -> None:
        for descriptor_present in (False, True):
            with self.subTest(descriptor_present=descriptor_present), tempfile.TemporaryDirectory() as directory:
                task_id = (
                    "TASK-2026-08-07-1002-blocked-"
                    + ("descriptor" if descriptor_present else "missing")
                )
                attempt_id = "d-" + "e" * 32
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps({task_id: self._v2_entry(task_id, attempt_id)})
                    + "\n",
                    encoding="utf-8",
                )
                if descriptor_present:
                    self._write_v2_descriptor(state, task_id, attempt_id)
                context = state / "board-dispatch" / f"{task_id}.{attempt_id}.context.json"
                context.parent.mkdir(parents=True, exist_ok=True)
                context.write_text(
                    json.dumps(
                        {
                            "schema": dcb.CONTEXT_SCHEMA,
                            "authority": {
                                "schema": dcb.AUTHORITY_SCHEMA,
                                "task_id": task_id,
                                "attempt_id": attempt_id,
                                "generation": 1,
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                fence = dcb.blocked_context_fence(root, context, task_id)
                dcb.publish_blocked_completion(
                    repo_root=root,
                    task_id=task_id,
                    lane="codex",
                    return_artifact="_state/consults/result.md",
                    compatibility_namespace="coding",
                    reason="fixture controller block",
                    attempt_id=fence[0],
                    generation=fence[1],
                )

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(
                    entry["status"],
                    "blocked" if descriptor_present else "in-flight",
                )

    def test_v2_frontmatter_rejects_every_duplicate_authority_key(self) -> None:
        attempt_id = "d-" + "8" * 32
        canonical = {
            "id": "{task_id}-response",
            "in_response_to": "{task_id}",
            "type": "RESULT",
            "status": "complete",
            "delivery_attempt_id": attempt_id,
            "delivery_generation": "1",
        }
        for ordinal, (key, value) in enumerate(canonical.items(), start=1):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-13{ordinal:02d}-duplicate-{key.replace('_', '-')}"
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps({task_id: self._v2_entry(task_id, attempt_id)})
                    + "\n",
                    encoding="utf-8",
                )
                self._write_v2_descriptor(state, task_id, attempt_id)
                response = root / "departments/coding/outbox" / f"{task_id}-response.md"
                self._write_response(response, task_id, attempt_id=attempt_id)
                exact_value = value.format(task_id=task_id)
                text = response.read_text(encoding="utf-8").replace(
                    f"{key}: {exact_value}\n",
                    f"{key}: stale-or-forged\n{key}: {exact_value}\n",
                    1,
                )
                response.write_text(text, encoding="utf-8")

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(entry["status"], "in-flight")

    def test_strict_v2_receipt_outranks_stale_exact_response(self) -> None:
        for receipt_state in ("bad-hash", "bad-generation", "valid"):
            with self.subTest(receipt_state=receipt_state), tempfile.TemporaryDirectory() as directory:
                valid_receipt = receipt_state == "valid"
                task_id = (
                    "TASK-2026-08-07-1401-receipt-preempts"
                    if valid_receipt
                    else "TASK-2026-08-07-1402-receipt-mismatch"
                )
                attempt_id = "d-" + "f" * 32
                stale_attempt = "d-" + "0" * 32
                completed_at = "2026-08-07T14:00:00.123456Z"
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps(
                        {
                            task_id: self._v2_entry(
                                task_id,
                                attempt_id,
                                delivery_generation=2,
                            )
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                descriptor = self._write_v2_descriptor(
                    state, task_id, attempt_id, generation=2
                )
                self._write_v2_receipt(
                    descriptor,
                    completed_at=completed_at,
                    generation=1 if receipt_state == "bad-generation" else None,
                    descriptor_sha256=(
                        "0" * 64 if receipt_state == "bad-hash" else None
                    ),
                )
                response = root / "departments/coding/outbox" / f"{task_id}-response.md"
                self._write_response(
                    response,
                    task_id,
                    attempt_id=stale_attempt,
                    generation=1,
                )
                os.utime(response, (2_000_000_000, 2_000_000_000))

                with self._patch_runtime(root, state, registry_path):
                    first_changed, first_messages = reconciler.reconcile(
                        task_id, dry_run=False
                    )
                    first = json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )[task_id]
                    if valid_receipt:
                        self.assertGreater(first_changed, 0, first_messages)
                        self.assertEqual(first["status"], "complete")
                        self.assertEqual(first["completed_at"], completed_at)
                        reconciler.reconcile(task_id, dry_run=False)
                        second = json.loads(
                            registry_path.read_text(encoding="utf-8")
                        )[task_id]
                        self.assertEqual(second["status"], "closed")
                        stable_changed, stable_messages = reconciler.reconcile(
                            task_id, dry_run=False
                        )
                        self.assertEqual(stable_changed, 0, stable_messages)
                    else:
                        self.assertEqual(first["status"], "in-flight")

    def test_v2_receipt_outcomes_do_not_use_v1_aliases(self) -> None:
        outcomes = (
            ("completed", "in-flight"),
            ("canceled", "in-flight"),
            ([], "in-flight"),
            ({}, "in-flight"),
            ("complete", "complete"),
            ("failed", "blocked"),
        )
        for ordinal, (outcome, expected) in enumerate(outcomes, start=1):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-145{ordinal}-receipt-outcome"
                attempt_id = "d-" + "2" * 32
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps({task_id: self._v2_entry(task_id, attempt_id)})
                    + "\n",
                    encoding="utf-8",
                )
                descriptor = self._write_v2_descriptor(
                    state, task_id, attempt_id
                )
                self._write_v2_receipt(
                    descriptor,
                    completed_at="2026-08-07T14:30:00Z",
                    terminal_outcome=outcome,
                )

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(entry["status"], expected)

    def test_v2_receipt_generation_requires_exact_integer(self) -> None:
        for ordinal, (generation, expected) in enumerate(
            ((True, "in-flight"), (1.0, "in-flight"), (1, "complete")), start=1
        ):
            with self.subTest(generation=generation), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-146{ordinal}-receipt-generation"
                attempt_id = "d-" + "3" * 32
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps({task_id: self._v2_entry(task_id, attempt_id)})
                    + "\n",
                    encoding="utf-8",
                )
                descriptor = self._write_v2_descriptor(
                    state, task_id, attempt_id
                )
                self._write_v2_receipt(
                    descriptor,
                    completed_at="2026-08-07T14:31:00Z",
                    generation=generation,
                )

                with self._patch_runtime(root, state, registry_path):
                    reconciler.reconcile(task_id, dry_run=False)

                entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(entry["status"], expected)

    def test_v1_receipt_rejects_float_generation_and_container_schema(self) -> None:
        cases = (
            ("valid", "board-dispatch-receipt/v1", 1, True),
            ("float-generation", "board-dispatch-receipt/v1", 1.0, False),
            ("list-schema", [], 1, False),
            ("dict-schema", {}, 1, False),
        )
        for label, receipt_schema, generation, accepted in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-1470-v1-receipt-{label}"
                attempt_id = "d-" + "4" * 32
                state = Path(directory) / "_state"
                board = state / "board-dispatch"
                board.mkdir(parents=True)
                receipt = board / f"{task_id}.{attempt_id}.receipt.json"
                receipt.write_text(
                    json.dumps(
                        {
                            "schema": receipt_schema,
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "generation": generation,
                            "status": "complete",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                entry = {
                    "delivery_attempt_id": attempt_id,
                    "delivery_generation": 1,
                }

                with mock.patch.object(reconciler, "STATE_DIR", state):
                    landed = reconciler.terminal_board_receipt(
                        task_id, entry, schema="v1"
                    )

                self.assertEqual(landed[0] is not None, accepted)

    def test_malformed_registry_status_does_not_crash_hold_projection(self) -> None:
        for ordinal, status in enumerate(([], {}), start=1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-147{ordinal}-malformed-status"
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps({task_id: {"status": status}}) + "\n",
                    encoding="utf-8",
                )

                with self._patch_runtime(root, state, registry_path):
                    changed, _messages = reconciler.reconcile(task_id, dry_run=True)

                self.assertGreaterEqual(changed, 0)

    def test_v2_receipt_uses_payload_completed_at_not_mtime(self) -> None:
        task_id = "TASK-2026-08-07-1003-receipt-time"
        attempt_id = "d-" + "3" * 32
        completed_at = "2026-08-07T12:34:56.123456Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps({task_id: self._v2_entry(task_id, attempt_id)}) + "\n",
                encoding="utf-8",
            )
            descriptor = self._write_v2_descriptor(state, task_id, attempt_id)
            descriptor_payload = json.loads(descriptor.read_text(encoding="utf-8"))
            descriptor_sha256 = hashlib.sha256(
                json.dumps(
                    descriptor_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            receipt = descriptor.with_name(f"{task_id}.{attempt_id}.receipt.json")
            receipt.write_text(
                json.dumps(
                    {
                        "schema": "board-dispatch-receipt/v2",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "generation": 1,
                        "status": "launched",
                        "terminal_outcome": "complete",
                        "completed_at": completed_at,
                        "descriptor_sha256": descriptor_sha256,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(receipt, (1_000_000_000, 1_000_000_000))

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], "complete")
            self.assertEqual(entry["completed_at"], completed_at)

    def test_v2_receipt_with_duplicate_identity_key_stays_open(self) -> None:
        task_id = "TASK-2026-08-07-1003-duplicate-receipt"
        attempt_id = "d-" + "7" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps({task_id: self._v2_entry(task_id, attempt_id)}) + "\n",
                encoding="utf-8",
            )
            descriptor = self._write_v2_descriptor(state, task_id, attempt_id)
            descriptor_payload = json.loads(descriptor.read_text(encoding="utf-8"))
            descriptor_sha256 = hashlib.sha256(
                json.dumps(
                    descriptor_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            receipt = descriptor.with_name(f"{task_id}.{attempt_id}.receipt.json")
            receipt.write_text(
                "{"
                '"schema":"board-dispatch-receipt/v2",'
                f'"task_id":"TASK-other","task_id":"{task_id}",'
                f'"attempt_id":"{attempt_id}","generation":1,'
                '"status":"launched","terminal_outcome":"complete",'
                '"completed_at":"2026-08-07T12:34:56Z",'
                f'"descriptor_sha256":"{descriptor_sha256}"'
                "}\n",
                encoding="utf-8",
            )

            with self._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "in-flight")

            receipt.write_text(
                json.dumps(
                    {
                        "schema": "board-dispatch-receipt/v2",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "generation": 1,
                        "status": "launched",
                        "terminal_outcome": "complete",
                        "completed_at": "2026-08-07T12:34:56Z",
                        "descriptor_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with self._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)
            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "in-flight")

    def test_v2_artifact_only_and_missing_descriptor_never_settle(self) -> None:
        for descriptor_state in ("valid", "missing", "malformed", "duplicate", "symlink"):
            with self.subTest(descriptor_state=descriptor_state), tempfile.TemporaryDirectory() as directory:
                task_id = f"TASK-2026-08-07-1004-{descriptor_state}"
                attempt_id = "d-" + "4" * 32
                root = Path(directory)
                state = root / "_state"
                registry_path = state / "active-tasks.json"
                state.mkdir()
                registry_path.write_text(
                    json.dumps(
                        {
                            task_id: self._v2_entry(
                                task_id,
                                attempt_id,
                                dispatched_at="2020-01-01T00:00:00+00:00",
                            )
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if descriptor_state != "missing":
                    descriptor = self._write_v2_descriptor(state, task_id, attempt_id)
                    if descriptor_state == "malformed":
                        descriptor.write_text("{}\n", encoding="utf-8")
                    elif descriptor_state == "duplicate":
                        descriptor.write_text(
                            descriptor.read_text(encoding="utf-8").replace(
                                '{"schema":',
                                '{"schema":"board-dispatch-process/v1","schema":',
                                1,
                            ),
                            encoding="utf-8",
                        )
                    elif descriptor_state == "symlink":
                        target = descriptor.with_name("descriptor-target.json")
                        descriptor.replace(target)
                        descriptor.symlink_to(target)
                artifact = root / "_state/consults/result.md"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("orphaned artifact\n", encoding="utf-8")
                os.utime(artifact, (1_700_000_000, 1_700_000_000))

                with self._patch_runtime(root, state, registry_path), mock.patch.object(
                    reconciler, "NO_ENVELOPE_GRACE", reconciler.timedelta(0)
                ), mock.patch.object(
                    reconciler, "NO_ENVELOPE_MIN_DISPATCH_AGE", reconciler.timedelta(0)
                ), mock.patch.object(
                    reconciler, "pane_snapshot", return_value=("idle", "idle")
                ):
                    reconciler.reconcile(task_id, dry_run=False)

                entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
                self.assertEqual(entry["status"], "in-flight")

    def test_v2_worker_fence_does_not_infer_lease_outcome_from_mtime(self) -> None:
        task_id = "TASK-2026-08-07-1005-worker-mtime"
        attempt_id = "d-" + "5" * 32
        worker_fields = {
            "delivery_worker_id": "worker-1",
            "worker_epoch": "epoch-1",
            "worker_assignment_state": "assigned",
            "lease_generation": 7,
            "lease_expires_at": "2020-01-01T00:00:00+00:00",
            "delivery_lane": "gpt-codex",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps(
                    {task_id: self._v2_entry(task_id, attempt_id, **worker_fields)}
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_v2_descriptor(state, task_id, attempt_id)
            response = root / "departments/coding/outbox" / f"{task_id}-response.md"
            self._write_response(response, task_id, attempt_id=attempt_id)
            text = response.read_text(encoding="utf-8").replace(
                "return_artifact: _state/consults/result.md\n",
                "return_artifact: _state/consults/result.md\n"
                "delivery_worker_id: worker-1\n"
                "worker_epoch: epoch-1\n"
                "lease_generation: 7\n"
                "delivery_lane: gpt-codex\n",
            )
            response.write_text(text, encoding="utf-8")
            landed = time.time() - 10
            os.utime(response, (landed, landed))

            with self._patch_runtime(root, state, registry_path):
                changed, messages = reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertGreater(changed, 0, messages)
            self.assertEqual(entry["status"], "complete")
            self.assertNotIn("worker_response_issue", entry)


class ReceiptFailureDiagnosticsTests(unittest.TestCase):
    """A terminal receipt's failure_class must survive into the registry.

    Ten distinct failure classes exist on disk (launch, request_validation,
    memory_proof, worktree, ...) and every one of them reached the registry as
    an undifferentiated ``blocked``, so a toolchain gate and a policy denial
    were indistinguishable without opening the receipt JSON by hand.
    """

    def _write(self, payload: object) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        receipt = tmp / "receipt.json"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        return receipt

    def test_extracts_failure_class_reason_and_returncode(self) -> None:
        receipt = self._write(
            {
                "failure_class": "cli_nonzero",
                "reason": "trusted launch failed:\n  Command 'codex exec'",
                "returncode": 74,
            }
        )
        self.assertEqual(
            reconciler.receipt_failure_diagnostics(receipt),
            {
                "failure_class": "cli_nonzero",
                # Newlines and runs of whitespace collapse so the registry
                # stays single-line readable.
                "reason": "trusted launch failed: Command 'codex exec'",
                "returncode": 74,
            },
        )

    def test_reason_is_capped(self) -> None:
        receipt = self._write({"reason": "x" * 5000})
        diagnostics = reconciler.receipt_failure_diagnostics(receipt)
        self.assertEqual(
            len(diagnostics["reason"]),
            reconciler.RECEIPT_DIAGNOSTIC_REASON_LIMIT,
        )

    def test_absent_and_malformed_fields_are_omitted_not_guessed(self) -> None:
        # `returncode: None` is the common real shape and must not become 0;
        # a bool must not pass the int check.
        receipt = self._write(
            {"failure_class": "  ", "reason": "", "returncode": None}
        )
        self.assertEqual(reconciler.receipt_failure_diagnostics(receipt), {})
        self.assertEqual(
            reconciler.receipt_failure_diagnostics(
                self._write({"returncode": True})
            ),
            {},
        )

    def test_fails_open_on_unreadable_or_non_dict_receipt(self) -> None:
        # Diagnostics are a convenience; losing them must never block a
        # reconcile, which is the operation that frees write_scope.
        self.assertEqual(
            reconciler.receipt_failure_diagnostics(Path("/nonexistent/x.json")),
            {},
        )
        self.assertEqual(
            reconciler.receipt_failure_diagnostics(self._write(["not", "dict"])),
            {},
        )
        bad = self._write({})
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(reconciler.receipt_failure_diagnostics(bad), {})

    def test_apply_reports_change_only_when_values_move(self) -> None:
        # Site 2 gates the registry write on this bool: if it lies, the
        # diagnostics are computed and then silently dropped.
        entry: dict[str, object] = {}
        self.assertTrue(
            reconciler.apply_receipt_diagnostics(entry, {"failure_class": "launch"})
        )
        self.assertEqual(entry["terminal_receipt_failure_class"], "launch")
        self.assertFalse(
            reconciler.apply_receipt_diagnostics(entry, {"failure_class": "launch"})
        )
        self.assertTrue(
            reconciler.apply_receipt_diagnostics(entry, {"failure_class": "worktree"})
        )

    def test_closure_reason_names_the_failure_class(self) -> None:
        entry: dict[str, object] = {}
        reconciler.auto_close_terminal_receipt(
            "TASK-2026-08-02-0001-diagnostics",
            entry,
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            "blocked",
            "blocked",
            {"failure_class": "request_validation", "returncode": 1, "reason": "bad packet"},
        )
        self.assertEqual(
            entry["closure_reason"],
            "terminal board receipt=blocked failure_class=request_validation "
            "rc=1: bad packet",
        )
        self.assertEqual(entry["status"], "closed")

    def test_closure_reason_unchanged_when_receipt_carries_nothing(self) -> None:
        # 33 receipts on disk have no failure_class; those must keep the
        # original string so existing consumers see no drift.
        entry: dict[str, object] = {}
        reconciler.auto_close_terminal_receipt(
            "TASK-2026-08-02-0002-no-diagnostics",
            entry,
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            "blocked",
            "blocked",
        )
        self.assertEqual(entry["closure_reason"], "terminal board receipt=blocked")


class PreservedWorkSurfacingTests(unittest.TestCase):
    """A terminal failure must say whether work survived, and name its ref.

    On 2026-08-11 three deliverables failed to reach the branch and every
    notification described only the TRANSPORT -- "blocked: CLI timed out",
    "blocked: response envelope has invalid frontmatter". Both true, neither
    saying whether anything was in it, so a reader concludes nothing was
    produced. The census proved otherwise: preservation had worked in all three
    cases, and one of them held 298 insertions on a reachable private branch.
    The bytes survived; nothing announced them.
    """

    REF = "refs/heads/worktree/TASK-2026-08-11-0730-fresh-install/d-" + "d" * 32
    COMMIT = "36d3486f32bb8be3810274f0c301b9f62da2527a"

    def _receipt(self, payload: object) -> Path:
        receipt = Path(tempfile.mkdtemp()) / "receipt.json"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        return receipt

    def _preserved_payload(self, **overrides: object) -> dict[str, object]:
        evidence = {
            "status": "preserved_existing",
            "evidence_ref": self.REF,
            "evidence_commit": self.COMMIT,
            "evidence_location": f"{self.REF}@{self.COMMIT}",
            "worktree_location": "",
            "preserved_path_count": 5,
            "worktree_retained_required": False,
        }
        evidence.update(overrides)
        return {
            "failure_class": "cli_timeout",
            "reason": "fresh lane CLI timed out after 1800 seconds",
            "evidence_preservation": evidence,
        }

    def test_diagnostics_lift_the_ref_the_receipt_already_carries(self) -> None:
        diagnostics = reconciler.receipt_failure_diagnostics(
            self._receipt(self._preserved_payload())
        )
        self.assertEqual(diagnostics["evidence_ref"], self.REF)
        self.assertEqual(diagnostics["evidence_commit"], self.COMMIT)
        self.assertEqual(diagnostics["evidence_status"], "preserved_existing")
        self.assertEqual(diagnostics["evidence_preserved_path_count"], 5)
        self.assertIs(diagnostics["evidence_worktree_retained_required"], False)
        # The pre-existing triage fields must keep working unchanged.
        self.assertEqual(diagnostics["failure_class"], "cli_timeout")

    def test_a_receipt_without_evidence_lifts_nothing(self) -> None:
        diagnostics = reconciler.receipt_failure_diagnostics(
            self._receipt({"failure_class": "cli_timeout"})
        )
        self.assertEqual(diagnostics, {"failure_class": "cli_timeout"})

    def test_stale_evidence_is_cleared_rather_than_named_wrongly(self) -> None:
        # A previous attempt's ref carried forward would send a reader to a
        # branch that does not hold their work: a confident wrong answer, which
        # is worse than the silence this change exists to end.
        entry: dict[str, object] = {}
        reconciler.apply_receipt_diagnostics(
            entry, {"evidence_ref": self.REF, "failure_class": "cli_timeout"}
        )
        self.assertEqual(entry["terminal_receipt_evidence_ref"], self.REF)
        self.assertTrue(
            reconciler.apply_receipt_diagnostics(entry, {"failure_class": "launch"})
        )
        self.assertNotIn("terminal_receipt_evidence_ref", entry)
        self.assertEqual(entry["terminal_receipt_failure_class"], "launch")

    def test_recovered_code_and_retained_outputs_are_reported_compositionally(self) -> None:
        # Measured 2026-08-28 on TASK-2026-08-28-2140-recov1, a deliberate
        # no-envelope run: the receipt carried work_recovery.status=integrated
        # and the commit was on `main`, while a distinct response envelope was
        # still present only in the attempt worktree. Both records are true for
        # different subsets of the same blocked attempt.
        payload = self._preserved_payload(
            status="error",
            evidence_ref="",
            evidence_commit="",
            worktree_location="/tmp/wt",
            worktree_retained_required=True,
            reason="explicit evidence outputs contain duplicates",
        )
        payload["work_recovery"] = {
            "status": "integrated",
            "integration_commit": "d" * 40,
            "integrated_paths": ["docs/probe-recovery-marker.md"],
        }
        diagnostics = reconciler.receipt_failure_diagnostics(self._receipt(payload))
        statement = reconciler.preserved_work_statement("TASK-X", {}, diagnostics)
        self.assertIn("RECOVERED WORK", statement)
        self.assertIn("d" * 40, statement)
        self.assertIn("docs/probe-recovery-marker.md", statement)
        self.assertIn("PRESERVED WORK (error)", statement)
        self.assertIn("explicit evidence outputs contain duplicates", statement)
        self.assertIn("NOT on a branch", statement)
        self.assertIn("/tmp/wt", statement)
        self.assertIn("do not prune", statement)
        self.assertNotIn("nothing is stranded", statement)
        # The rail: recovery must not read as settlement.
        self.assertIn("stays blocked", statement)

    def test_recovered_code_and_out_of_scope_residue_are_both_reported(self) -> None:
        payload = self._preserved_payload(
            status="preserved",
            worktree_location="/tmp/wt-out-of-scope",
            worktree_retained_required=True,
            out_of_scope_paths=["notes/operator-draft.md"],
            out_of_scope_path_count=1,
        )
        payload["work_recovery"] = {
            "status": "integrated",
            "integration_commit": "e" * 40,
            "integrated_paths": ["scripts/python/thing.py"],
        }
        diagnostics = reconciler.receipt_failure_diagnostics(self._receipt(payload))
        statement = reconciler.preserved_work_statement("TASK-X", {}, diagnostics)
        self.assertIn("RECOVERED WORK", statement)
        self.assertIn("scripts/python/thing.py", statement)
        self.assertIn("e" * 40, statement)
        self.assertIn("PRESERVED WORK (preserved)", statement)
        self.assertIn(self.REF, statement)
        self.assertIn(self.COMMIT, statement)
        self.assertIn("notes/operator-draft.md", statement)
        self.assertIn("/tmp/wt-out-of-scope", statement)
        self.assertIn("do not prune", statement)
        self.assertNotIn("nothing is stranded", statement)
        self.assertIn("stays blocked", statement)

    def test_statement_names_the_branch_and_how_to_read_it(self) -> None:
        diagnostics = reconciler.receipt_failure_diagnostics(
            self._receipt(self._preserved_payload())
        )
        statement = reconciler.preserved_work_statement("TASK-X", {}, diagnostics)
        self.assertIn(self.REF, statement)
        self.assertIn(self.COMMIT, statement)
        self.assertIn("5 path(s)", statement)
        self.assertIn("git show", statement)

    def test_statement_names_a_retained_worktree_when_no_branch_exists(self) -> None:
        diagnostics = reconciler.receipt_failure_diagnostics(
            self._receipt(
                self._preserved_payload(
                    status="retained_bounded",
                    evidence_ref="",
                    evidence_commit="",
                    worktree_location="/tmp/pool/d-abc",
                    worktree_retained_required=True,
                )
            )
        )
        statement = reconciler.preserved_work_statement("TASK-X", {}, diagnostics)
        self.assertIn("/tmp/pool/d-abc", statement)
        self.assertIn("NOT on a branch", statement)
        self.assertIn("do not prune", statement)

    def test_recording_nothing_still_names_a_ref_to_check(self) -> None:
        """The exact TASK-2026-08-11-0180 shape.

        `_terminal_evidence` returns None when the attempt worktree directory is
        already gone, so that receipt carries no evidence at all -- which is why
        its bundle was called "permanently unverifiable". The branch survived.
        Its name is derivable from the registry alone, so the notification can
        hand the reader a ref to check instead of an implied "nothing exists".
        """
        attempt_id = "d-cd2e54faca1948a3a948e7c96685adc3"
        entry = {"delivery_attempt_id": attempt_id}
        statement = reconciler.preserved_work_statement(
            "TASK-2026-08-11-0180-orphan-supervisor-leak", entry, {}
        )
        self.assertIn(
            f"refs/heads/worktree/TASK-2026-08-11-0180-orphan-supervisor-leak/{attempt_id}",
            statement,
        )
        self.assertIn("NOT RECORDED", statement)
        self.assertIn("before concluding nothing was produced", statement)

    def test_statement_is_never_empty_even_with_no_attempt_id(self) -> None:
        statement = reconciler.preserved_work_statement("TASK-X", {}, {})
        self.assertTrue(statement.strip())
        self.assertIn("do not conclude", statement)

    def test_never_launched_task_is_not_reported_as_awaiting_review(self) -> None:
        """A task that never ran reads as finished. Say so loudly.

        Four dispatches died this way on 2026-08-14 -- two packet errors, two
        flaky MCP-enumeration timeouts -- and every one reported
        `review-required`, which is what a COMPLETED task awaiting a reviewer
        reports. Only the missing artifact gave them away.
        """
        entry = {
            "delivery_attempt_count": 0,
            "delivery_state": "terminal",
            "status": "review-required",
            "started_at": None,
            "delivery_worker_id": None,
        }
        statement = reconciler.preserved_work_statement("TASK-N", entry, {})
        self.assertIn("NEVER LAUNCHED", statement)
        self.assertIn("produced NOTHING", statement)

    def test_honest_zero_attempt_outcomes_are_not_flagged(self) -> None:
        """superseded/cancelled/blocked already say nothing ran -- do not shout."""
        for status in ("superseded", "cancelled", "blocked"):
            entry = {
                "delivery_attempt_count": 0,
                "delivery_state": "terminal",
                "status": status,
                "started_at": None,
                "delivery_worker_id": None,
            }
            self.assertEqual(reconciler.never_ran_statement(entry), "", status)

    def test_a_task_that_launched_is_never_flagged_as_never_launched(self) -> None:
        """The negative control: one attempt means it ran."""
        entry = {
            "delivery_attempt_count": 1,
            "delivery_state": "terminal",
            "status": "review-required",
            "started_at": "2026-08-14T00:00:00+00:00",
            "delivery_worker_id": "w-1",
        }
        self.assertEqual(reconciler.never_ran_statement(entry), "")

    def test_promoted_artifact_is_named_instead_of_claiming_nothing_recorded(
        self,
    ) -> None:
        """A promoted artifact is gitignored, so git advice can never find it.

        Four terminal receipts on 2026-08-13 said "NOT RECORDED" and pointed at
        `git log` while a finished artifact -- 36KB in one case -- sat promoted
        on disk under `_state/`. The receipt has no evidence block because the
        work is not in git, which is the normal, successful case.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = "_state/v4-audit/example/TASK-Y.md"
            target = root / artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("finished report", encoding="utf-8")
            entry = {"return_artifact": artifact, "delivery_attempt_id": "d-" + "e" * 32}
            with mock.patch.object(
                reconciler, "canonical_vault_root", return_value=root
            ):
                statement = reconciler.preserved_work_statement("TASK-Y", entry, {})
        self.assertIn("PROMOTED ARTIFACT", statement)
        self.assertIn(artifact, statement)
        self.assertIn(str(len("finished report")), statement)
        self.assertNotIn("NOT RECORDED", statement)

    def test_missing_promoted_artifact_still_reports_not_recorded(self) -> None:
        """The negative control: absent artifact must NOT be softened."""
        with tempfile.TemporaryDirectory() as directory:
            entry = {
                "return_artifact": "_state/v4-audit/example/absent.md",
                "delivery_attempt_id": "d-" + "f" * 32,
            }
            with mock.patch.object(
                reconciler, "canonical_vault_root", return_value=Path(directory)
            ):
                statement = reconciler.preserved_work_statement("TASK-Z", entry, {})
        self.assertIn("NOT RECORDED", statement)
        self.assertIn("no promoted artifact is on disk", statement)
        self.assertIn("before concluding nothing was produced", statement)

    def test_terminal_failure_notification_names_the_preserved_ref(self) -> None:
        """End to end: the nudge Chrono actually reads must carry the ref."""
        task_id = "TASK-2026-08-11-9601-timeout-surfacing"
        attempt_id = "d-" + "d" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "_state"
            registry_path = state / "active-tasks.json"
            state.mkdir()
            registry_path.write_text(
                json.dumps(
                    {
                        task_id: BoardReceiptSettlementTests._v2_entry(
                            task_id, attempt_id
                        )
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            descriptor = BoardReceiptSettlementTests._write_v2_descriptor(
                state, task_id, attempt_id
            )
            receipt = BoardReceiptSettlementTests._write_v2_receipt(
                descriptor,
                completed_at="2026-08-11T03:00:00Z",
                terminal_outcome="failed",
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload.update(self._preserved_payload())
            receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            emitted: list[tuple[str, str, str, str]] = []
            with BoardReceiptSettlementTests._patch_runtime(
                root, state, registry_path
            ), mock.patch.object(
                reconciler,
                "emit_event",
                side_effect=lambda *args: emitted.append(args) or True,
            ):
                reconciler.reconcile(task_id, dry_run=False)
                first = json.loads(registry_path.read_text(encoding="utf-8"))[
                    task_id
                ]
                self.assertEqual(first["status"], "blocked")
                # The receipt status is recorded first; the one operator event
                # is emitted only once the existing second pass records its
                # close disposition.
                reconciler.reconcile(task_id, dry_run=False)
                reconciler.reconcile(task_id, dry_run=False)

            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]
            self.assertEqual(entry["status"], "closed")
            # The registry keeps the durable record...
            self.assertEqual(entry["terminal_receipt_evidence_ref"], self.REF)
            self.assertEqual(entry["terminal_receipt_evidence_commit"], self.COMMIT)
            # ...and the operator-facing nudge states it, which is the part that
            # was missing while the data sat in the receipt unread.
            self.assertEqual(len(emitted), 1, emitted)
            self.assertEqual(emitted[0][0], "AUTO-CLOSED")
            summary, nudge = emitted[0][2], emitted[0][3]
            self.assertIn(self.REF, nudge)
            self.assertIn(self.COMMIT, nudge)
            self.assertIn("PRESERVED WORK", nudge)
            self.assertIn(self.REF, summary)


class DeclaredHashHoldTests(unittest.TestCase):
    """A declared hash that resolves to nothing must hold, never pass.

    TASK-2026-08-11-0180 settled `complete` while declaring an artifact bundle
    whose manifest was never reachable, under a contract whose review subject
    WAS that bundle hash. The review that approved it reviewed a subject nobody
    could open. A hash pointing at bytes no one can produce reads as rigour and
    carries none.
    """

    DIGEST = "d8a30627773a8973ac2bffe88802420675768369ab0f1494ac7d6d282fb54d57"

    def _fixture(self, directory: str, task_id: str, attempt_id: str):
        root = Path(directory)
        state = root / "_state"
        registry_path = state / "active-tasks.json"
        state.mkdir()
        registry_path.write_text(
            json.dumps(
                {task_id: BoardReceiptSettlementTests._v2_entry(task_id, attempt_id)}
            )
            + "\n",
            encoding="utf-8",
        )
        BoardReceiptSettlementTests._write_v2_descriptor(state, task_id, attempt_id)
        artifact = state / "consults" / "result.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("the deliverable\n", encoding="utf-8")
        response = root / "departments/coding/outbox" / f"{task_id}-response.md"
        BoardReceiptSettlementTests._write_response(
            response, task_id, "complete", attempt_id=attempt_id
        )
        return root, state, registry_path, response

    @staticmethod
    def _declare_in_frontmatter(response: Path, digest: str) -> None:
        text = response.read_text(encoding="utf-8").replace(
            "return_artifact: _state/consults/result.md\n",
            "return_artifact: _state/consults/result.md\n"
            f"artifact_bundle_sha256: {digest}\n",
            1,
        )
        response.write_text(text, encoding="utf-8")

    @staticmethod
    def _declare_in_prose(response: Path, text: str) -> None:
        response.write_text(
            response.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8"
        )

    def _reconcile(self, root, state, registry_path, task_id):
        with BoardReceiptSettlementTests._patch_runtime(root, state, registry_path):
            reconciler.reconcile(task_id, dry_run=False)
        return json.loads(registry_path.read_text(encoding="utf-8"))[task_id]

    def test_unresolvable_frontmatter_hash_holds_instead_of_settling(self) -> None:
        task_id = "TASK-2026-08-11-9611-unresolvable-bundle"
        attempt_id = "d-" + "1" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_frontmatter(response, self.DIGEST)
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "in-flight")
        self.assertIn(self.DIGEST, entry["declared_hash_issue"])
        self.assertIn("resolves to nothing reachable", entry["declared_hash_issue"])

    def test_the_hold_never_drops_the_response(self) -> None:
        """The whole lesson of TASK-2026-08-11-0490: rejecting an envelope
        destroyed a complete deliverable. This check holds and reports; it must
        leave both the envelope and the artifact exactly where they are."""
        task_id = "TASK-2026-08-11-9612-hold-not-drop"
        attempt_id = "d-" + "2" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_frontmatter(response, self.DIGEST)
            before = response.read_bytes()
            artifact = state / "consults" / "result.md"
            artifact_before = artifact.read_bytes()

            entry = self._reconcile(root, state, registry_path, task_id)

            self.assertTrue(response.is_file(), "the response envelope was dropped")
            self.assertEqual(response.read_bytes(), before)
            self.assertTrue(artifact.is_file(), "the deliverable was dropped")
            self.assertEqual(artifact.read_bytes(), artifact_before)
        self.assertEqual(entry["status"], "in-flight")
        self.assertEqual(
            entry["response_path"],
            f"departments/coding/outbox/{task_id}-response.md",
        )

    def test_a_reachable_manifest_lets_the_response_settle(self) -> None:
        task_id = "TASK-2026-08-11-9613-resolvable-bundle"
        attempt_id = "d-" + "3" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_frontmatter(response, self.DIGEST)
            manifest = state / "consults" / "run-manifest.json"
            manifest.write_text(
                json.dumps({"artifact_bundle_sha256": self.DIGEST}), encoding="utf-8"
            )
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)

    def test_the_hold_clears_once_the_manifest_lands(self) -> None:
        # Hold, not reject: the task must be recoverable without a re-dispatch.
        task_id = "TASK-2026-08-11-9614-hold-clears"
        attempt_id = "d-" + "4" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_frontmatter(response, self.DIGEST)
            held = self._reconcile(root, state, registry_path, task_id)
            self.assertEqual(held["status"], "in-flight")

            (state / "consults" / "artifact-list.json").write_text(
                json.dumps({"artifact_bundle_sha256": self.DIGEST}), encoding="utf-8"
            )
            settled = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(settled["status"], "complete")
        self.assertNotIn("declared_hash_issue", settled)

    def test_a_bundle_hash_named_only_in_prose_is_still_checked(self) -> None:
        # The real TASK-2026-08-11-0180 declared its bundle in the body, not
        # the frontmatter, and that is precisely where it escaped scrutiny.
        task_id = "TASK-2026-08-11-9615-prose-bundle"
        attempt_id = "d-" + "5" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_prose(
                response,
                f"Run the mandatory review of artifact bundle `{self.DIGEST}`.",
            )
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "in-flight")
        self.assertIn(self.DIGEST, entry["declared_hash_issue"])

    def test_an_unrelated_digest_in_prose_is_not_a_bundle_claim(self) -> None:
        # Responses quote commit hashes, contract hashes and blob hashes
        # constantly. Holding a task over one of those is a false accusation,
        # not a safety margin.
        task_id = "TASK-2026-08-11-9616-unrelated-digest"
        attempt_id = "d-" + "6" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_prose(
                response,
                f"Verification contract sha256 `{self.DIGEST}` and plan {'a' * 64}.",
            )
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)

    def test_a_bundle_claim_written_as_an_ordinary_sentence_is_checked(self) -> None:
        # Humans mostly do not backtick the digest. An earlier matcher only
        # spanned non-hex characters between the phrase and the digest, so
        # "artifact bundle hash is X" slipped through while "artifact bundle
        # `X`" did not -- a gap that would have re-created the original defect.
        task_id = "TASK-2026-08-11-9618-prose-sentence"
        attempt_id = "d-" + "8" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_prose(
                response, f"The artifact bundle hash is {self.DIGEST} for review."
            )
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "in-flight")
        self.assertIn(self.DIGEST, entry["declared_hash_issue"])

    def test_an_exhausted_scan_budget_fails_open_instead_of_accusing(self) -> None:
        # A hold must rest on evidence that the digest is unbacked, never on our
        # own timeout. "I could not look" is not "you lied".
        task_id = "TASK-2026-08-11-9619-scan-budget"
        attempt_id = "d-" + "9" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, response = self._fixture(
                directory, task_id, attempt_id
            )
            self._declare_in_frontmatter(response, self.DIGEST)
            (state / "consults" / "decoy.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(
                reconciler, "DECLARED_HASH_SCAN_FILE_LIMIT", 0
            ), BoardReceiptSettlementTests._patch_runtime(root, state, registry_path):
                reconciler.reconcile(task_id, dry_run=False)
            entry = json.loads(registry_path.read_text(encoding="utf-8"))[task_id]

        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)

    def test_a_response_declaring_no_hash_is_untouched(self) -> None:
        task_id = "TASK-2026-08-11-9617-no-hash"
        attempt_id = "d-" + "7" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path, _response = self._fixture(
                directory, task_id, attempt_id
            )
            entry = self._reconcile(root, state, registry_path, task_id)

        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("declared_hash_issue", entry)


if __name__ == "__main__":
    unittest.main()
