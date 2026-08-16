#!/usr/bin/env python3
"""Hermetic 100-cycle coverage for board output settlement and replay safety."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import dispatch_context_builder as dcb  # noqa: E402
import registry_reconciler as rr  # noqa: E402


UTC = timezone.utc
SCENARIOS = (
    "success",
    "blocked",
    "cancelled",
    "unsafe-artifact",
    "missing-artifact",
    "missing-envelope",
    "late-result",
    "stale-receipt",
    "stale-worker-response",
    "sibling-artifact",
)
_OMIT = object()


@dataclass(frozen=True)
class CycleSpec:
    ordinal: int
    scenario: str
    task_id: str
    attempt_id: str
    generation: int
    artifact_rel: str
    envelope_rel: str


class RegistryLifecycleMatrixTests(unittest.TestCase):
    """Exercise 100 isolated task lifecycles through production functions."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="registry-life-100-")
        self.addCleanup(self._temporary.cleanup)
        self.base = Path(self._temporary.name)
        self.vault = self.base / "vault"
        self.state = self.vault / "_state"
        self.registry_path = self.state / "active-tasks.json"
        self.worktrees = self.base / "worktrees"
        self.outside = self.base / "outside"
        for directory in (self.state, self.worktrees, self.outside):
            directory.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text("{}\n", encoding="utf-8")
        runtime_map = self.vault / "shared" / "specialist-runtime-map.tsv"
        runtime_map.parent.mkdir(parents=True)
        runtime_map.write_text(
            "specialist\tc2\tc3\tc4\tc5\tc6\tprimary_lane\n"
            "systems-engineer\tx\tx\tx\tx\tx\tclaude\n",
            encoding="utf-8",
        )

        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        patchers = (
            mock.patch.object(rr, "VAULT_ROOT", self.vault),
            mock.patch.object(rr, "STATE_DIR", self.state),
            mock.patch.object(rr, "REGISTRY_PATH", self.registry_path),
            mock.patch.object(rr, "CHRONO_QUEUE_PATH", self.state / "chrono-queue.md"),
            mock.patch.object(
                rr, "CHRONO_NOTIFY_LOCKDIR", self.state / "chrono-notify.lockdir"
            ),
            mock.patch.object(
                rr,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                self.state / "chrono-notify-receipts",
            ),
            mock.patch.object(
                rr, "LONG_RUNNING_NOTED_DIR", self.state / "long-running-noted"
            ),
            mock.patch.object(rr, "RUNTIME_MAP_PATH", runtime_map),
            mock.patch.object(rr, "RESPONSE_MIN_AGE", timedelta(0)),
            mock.patch.object(rr, "NO_ENVELOPE_GRACE", timedelta(0)),
            mock.patch.object(rr, "NO_ENVELOPE_MIN_DISPATCH_AGE", timedelta(0)),
            mock.patch.object(rr, "NEVER_LAUNCHED_GRACE", timedelta(seconds=1)),
            mock.patch.object(rr, "pane_snapshot", return_value=("idle", "fixture-idle")),
            mock.patch.object(
                rr.subprocess,
                "run",
                side_effect=AssertionError("lifecycle matrix escaped to a host subprocess"),
            ),
            mock.patch.dict(
                os.environ,
                {
                    rr.TEST_ISOLATION_ENV: "1",
                    "CHRONO_CANONICAL_VAULT_ROOT": str(self.vault),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                clear=False,
            ),
        )
        for patcher in patchers:
            self._stack.enter_context(patcher)

        self.guarded_writes: list[Path] = []
        real_atomic_write = rr.atomic_write
        resolved_vault = self.vault.resolve()

        def guarded_atomic_write(path: Path, content: str) -> None:
            resolved = Path(path).resolve(strict=False)
            try:
                resolved.relative_to(resolved_vault)
            except ValueError as exc:  # pragma: no cover - assertion seam
                raise AssertionError(f"write escaped fixture vault: {resolved}") from exc
            self.guarded_writes.append(resolved)
            real_atomic_write(path, content)

        self._stack.enter_context(mock.patch.object(rr, "atomic_write", guarded_atomic_write))
        self._sentinels: dict[str, tuple[Path, bytes, int]] = {}

    @staticmethod
    def _spec(ordinal: int, scenario: str) -> CycleSpec:
        task_id = f"TASK-2026-08-07-{ordinal:04d}-life-{scenario}"
        return CycleSpec(
            ordinal=ordinal,
            scenario=scenario,
            task_id=task_id,
            attempt_id=f"d-{ordinal + 1:032x}",
            generation=2 if scenario in {"stale-receipt", "stale-worker-response"} else 1,
            artifact_rel=f"_state/lifecycle/{ordinal:04d}-{scenario}.md",
            envelope_rel=f"departments/coding/outbox/{task_id}-response.md",
        )

    def _base_entry(self, spec: CycleSpec, **overrides: object) -> dict[str, object]:
        dispatched = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        entry: dict[str, object] = {
            "status": "in-flight",
            "specialist": "systems-engineer",
            "to_model": "claude",
            "review_model": "none",
            "mandatory_review": "false",
            "compatibility_namespace": "coding",
            "source_namespace": "coding",
            "return_artifact": spec.artifact_rel,
            "write_scope": [spec.artifact_rel],
            "delivery_attempt_id": spec.attempt_id,
            "delivery_generation": spec.generation,
            "delivery_lane": "claude",
            "delivery_state": "in-progress",
            "delivery_attempt_count": 1,
            "dispatched_at": dispatched,
            "enqueued_at": dispatched,
            "claimed_at": dispatched,
            "started_at": dispatched,
        }
        entry.update(overrides)
        return entry

    def _register(self, spec: CycleSpec, **overrides: object) -> None:
        self.assertTrue(rr.register_task(spec.task_id, self._base_entry(spec, **overrides)))
        inbox = self.vault / "departments" / "coding" / "inbox" / f"{spec.task_id}.md"
        inbox.parent.mkdir(parents=True, exist_ok=True)
        inbox.write_text(f"---\nid: {spec.task_id}\n---\n", encoding="utf-8")
        sentinel = self.state / "lifecycle-siblings" / f"{spec.task_id}.md"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel_bytes = f"unrelated sibling for {spec.task_id}\n".encode()
        sentinel.write_bytes(sentinel_bytes)
        self._sentinels[spec.task_id] = (
            sentinel,
            sentinel_bytes,
            sentinel.stat().st_ino,
        )

    def _entry(self, task_id: str) -> dict[str, object]:
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return registry[task_id]

    def _artifact_bytes(self, spec: CycleSpec) -> bytes:
        return f"artifact for {spec.task_id}\n".encode()

    def _raw_envelope(self, spec: CycleSpec, status: str = "complete") -> str:
        return (
            "---\n"
            f"id: {spec.task_id}-response\n"
            f"in_response_to: {spec.task_id}\n"
            "from: claude\n"
            "to: chrono\n"
            "type: RESULT\n"
            f"status: {status}\n"
            f"return_artifact: {spec.artifact_rel}\n"
            "---\n\n"
            f"summary for {spec.task_id}\n"
        )

    def _prepare(
        self,
        spec: CycleSpec,
        *,
        tag: str,
        artifact_bytes: bytes | None = None,
        reconciliation_echo: dict[str, str] | None = None,
    ) -> dcb.PreparedWorktreeOutputs:
        worktree = self.worktrees / f"{spec.ordinal:04d}-{tag}"
        worktree.mkdir(parents=True)
        if artifact_bytes is None:
            artifact_bytes = self._artifact_bytes(spec)
        artifact = worktree / spec.artifact_rel
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(artifact_bytes)
        envelope = worktree / spec.envelope_rel
        envelope.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_text(self._raw_envelope(spec), encoding="utf-8")
        authority: dict[str, object] = {
            "task_id": spec.task_id,
            "lane": "claude",
            "write_paths": [spec.artifact_rel],
            "expected_result_path": spec.artifact_rel,
            "expected_outbox_path": spec.envelope_rel,
        }
        if reconciliation_echo is not None:
            authority["reconciliation_echo"] = reconciliation_echo
        return dcb.prepare_worktree_outputs(self.vault, worktree, authority)

    def _write_receipt(
        self,
        spec: CycleSpec,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        generation: object = _OMIT,
        filename_attempt: str | None = None,
    ) -> Path:
        payload: dict[str, object] = {
            "status": "failed",
            "task_id": task_id if task_id is not None else spec.task_id,
            "attempt_id": attempt_id if attempt_id is not None else spec.attempt_id,
            "failure_class": "request_validation",
            "reason": f"fixture failure for {spec.scenario}",
            "returncode": 75,
        }
        if generation is _OMIT:
            payload["generation"] = spec.generation
        elif generation is not None:
            payload["generation"] = generation
        board = self.state / "board-dispatch"
        board.mkdir(parents=True, exist_ok=True)
        receipt = board / (
            f"{spec.task_id}.{filename_attempt or spec.attempt_id}.receipt.json"
        )
        receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    def _byte_manifest(self) -> dict[str, tuple[str, str]]:
        manifest: dict[str, tuple[str, str]] = {}
        for path in sorted(self.vault.rglob("*")):
            relative = str(path.relative_to(self.vault))
            if path.is_symlink():
                manifest[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                manifest[relative] = (
                    "file",
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return manifest

    def _assert_stable(self, spec: CycleSpec) -> None:
        before_registry = self.registry_path.read_bytes()
        before_manifest = self._byte_manifest()
        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertEqual(changed, 0, messages)
        self.assertEqual(self.registry_path.read_bytes(), before_registry)
        self.assertEqual(self._byte_manifest(), before_manifest)

    def _assert_fence(self, spec: CycleSpec, entry: dict[str, object]) -> None:
        self.assertEqual(entry["delivery_attempt_id"], spec.attempt_id)
        self.assertEqual(entry["delivery_generation"], spec.generation)

    def _assert_archived(self, spec: CycleSpec) -> None:
        inbox = self.vault / "departments" / "coding" / "inbox" / f"{spec.task_id}.md"
        archive = self.vault / "departments" / "coding" / "archive" / f"{spec.task_id}.md"
        self.assertFalse(inbox.exists())
        self.assertTrue(archive.is_file())

    def _assert_general_sibling_unchanged(self, spec: CycleSpec) -> None:
        sentinel, expected, inode = self._sentinels[spec.task_id]
        self.assertTrue(sentinel.is_file())
        self.assertEqual(sentinel.read_bytes(), expected)
        self.assertEqual(sentinel.stat().st_ino, inode)

    def _drive_receipt_close(self, spec: CycleSpec) -> None:
        first_changed, first_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(first_changed, 0, first_messages)
        first = self._entry(spec.task_id)
        self.assertEqual(first["status"], "blocked")
        self.assertEqual(first["delivery_state"], "terminal")
        self._assert_fence(spec, first)

        second_changed, second_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(second_changed, 0, second_messages)
        closed = self._entry(spec.task_id)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["closed_from_status"], "blocked")
        self.assertEqual(len(closed["closure_history"]), 1)
        terminal_events = [
            item
            for item in closed.get("delivery_history", [])
            if item.get("event") == "terminal"
        ]
        self.assertEqual(len(terminal_events), 1)
        self._assert_fence(spec, closed)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_success(self, spec: CycleSpec) -> None:
        self._register(spec)
        prepared = self._prepare(spec, tag="success")
        first = dcb.publish_prepared_worktree_outputs(self.vault, prepared)
        self.assertFalse(first["artifact_idempotent"])
        self.assertFalse(first["envelope_idempotent"])
        retry = dcb.publish_prepared_worktree_outputs(self.vault, prepared)
        self.assertTrue(retry["artifact_idempotent"])
        self.assertTrue(retry["envelope_idempotent"])

        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(changed, 0, messages)
        entry = self._entry(spec.task_id)
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["delivery_state"], "terminal")
        self.assertEqual((self.vault / spec.artifact_rel).read_bytes(), prepared.result_bytes)
        self._assert_fence(spec, entry)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_blocked(self, spec: CycleSpec) -> None:
        self._register(spec)
        result = dcb.publish_blocked_completion(
            repo_root=self.vault,
            task_id=spec.task_id,
            lane="claude",
            return_artifact=spec.artifact_rel,
            compatibility_namespace="coding",
            reason="fixture controller block",
        )
        self.assertEqual(result["status"], "blocked")
        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(changed, 0, messages)
        entry = self._entry(spec.task_id)
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(entry["delivery_state"], "terminal")
        artifact = self.vault / spec.artifact_rel
        retired = artifact.with_name(f"{artifact.name}.blocked-{spec.task_id}")
        self.assertFalse(artifact.exists())
        self.assertTrue(retired.is_file())
        self._assert_fence(spec, entry)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_cancelled(self, spec: CycleSpec) -> None:
        self._register(
            spec,
            delivery_state="queued",
            delivery_attempt_count=0,
            claimed_at=None,
            started_at=None,
            delivery_worker_id=None,
        )
        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(changed, 0, messages)
        cancelled = self._entry(spec.task_id)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["delivery_state"], "terminal")
        self.assertTrue(cancelled["never_launched_reason"])
        self._assert_fence(spec, cancelled)
        self._assert_archived(spec)

        # A result that lands after controller cancellation is retained as evidence
        # but cannot reopen or rewrite the terminal registry lifecycle.
        prepared = self._prepare(spec, tag="late-after-cancel")
        dcb.publish_prepared_worktree_outputs(self.vault, prepared)
        self._assert_stable(spec)
        after = self._entry(spec.task_id)
        self.assertEqual(after["status"], "cancelled")
        self.assertNotIn("response_path", after)

    def _case_unsafe_artifact(self, spec: CycleSpec) -> None:
        repeat = spec.ordinal // len(SCENARIOS)
        outside = self.outside / f"unsafe-{spec.ordinal:04d}.md"
        outside_bytes = f"outside sentinel {spec.task_id}\n".encode()
        outside.write_bytes(outside_bytes)
        unsafe = (
            f"../outside/{outside.name}"
            if repeat % 2 == 0
            else str(outside)
        )
        self._register(spec, return_artifact=unsafe, write_scope=[unsafe])

        worktree = self.worktrees / f"{spec.ordinal:04d}-unsafe"
        envelope = worktree / spec.envelope_rel
        envelope.parent.mkdir(parents=True)
        envelope.write_text(self._raw_envelope(spec), encoding="utf-8")
        authority = {
            "task_id": spec.task_id,
            "lane": "claude",
            "write_paths": [unsafe],
            "expected_result_path": unsafe,
            "expected_outbox_path": spec.envelope_rel,
        }
        with self.assertRaisesRegex(
            dcb.DispatchContextError,
            "unsafe path|contains traversal|must be relative",
        ):
            dcb.prepare_worktree_outputs(self.vault, worktree, authority)
        self.assertFalse((self.vault / spec.envelope_rel).exists())

        if repeat < 5:
            # With no fenced receipt, an unsafe external file is not evidence of
            # landed work and must never trigger work-done-no-envelope.
            before = self.registry_path.read_bytes()
            changed, messages = rr.reconcile(spec.task_id, dry_run=False)
            self.assertEqual(changed, 0, messages)
            self.assertEqual(self.registry_path.read_bytes(), before)
            entry = self._entry(spec.task_id)
            self.assertEqual(entry["status"], "in-flight")
            self.assertNotIn("missing_envelope_artifact", entry)
            self._assert_stable(spec)
        else:
            # The current terminal receipt remains authoritative even though its
            # untrusted artifact path is unusable.
            self._write_receipt(spec)
            self._drive_receipt_close(spec)
        self.assertEqual(outside.read_bytes(), outside_bytes)

    def _case_missing_artifact(self, spec: CycleSpec) -> None:
        self._register(spec)
        worktree = self.worktrees / f"{spec.ordinal:04d}-missing-artifact"
        envelope = worktree / spec.envelope_rel
        envelope.parent.mkdir(parents=True)
        envelope.write_text(self._raw_envelope(spec), encoding="utf-8")
        authority = {
            "task_id": spec.task_id,
            "lane": "claude",
            "write_paths": [spec.artifact_rel],
            "expected_result_path": spec.artifact_rel,
            "expected_outbox_path": spec.envelope_rel,
        }
        with self.assertRaisesRegex(dcb.DispatchContextError, "return artifact"):
            dcb.prepare_worktree_outputs(self.vault, worktree, authority)
        self.assertFalse((self.vault / spec.artifact_rel).exists())
        self.assertFalse((self.vault / spec.envelope_rel).exists())
        self._write_receipt(spec)
        self._drive_receipt_close(spec)

    def _publish_artifact_only(
        self, spec: CycleSpec, *, tag: str
    ) -> dcb.PreparedWorktreeOutputs:
        prepared = self._prepare(spec, tag=tag)
        artifact, idempotent = dcb._atomic_publish(  # noqa: SLF001
            self.vault,
            prepared.result_relative,
            prepared.result_bytes,
            label="return artifact",
        )
        self.assertFalse(idempotent)
        self.assertEqual(artifact.read_bytes(), prepared.result_bytes)
        self.assertFalse((self.vault / spec.envelope_rel).exists())
        return prepared

    def _case_missing_envelope(self, spec: CycleSpec) -> None:
        self._register(spec)
        prepared = self._publish_artifact_only(spec, tag="missing-envelope")
        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(changed, 0, messages)
        entry = self._entry(spec.task_id)
        self.assertEqual(entry["status"], rr.SETTLED_WITHOUT_ENVELOPE)
        self.assertEqual(entry["delivery_state"], "terminal")
        self.assertEqual((self.vault / spec.artifact_rel).read_bytes(), prepared.result_bytes)
        self._assert_fence(spec, entry)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_late_result(self, spec: CycleSpec) -> None:
        self._register(spec)
        prepared = self._publish_artifact_only(spec, tag="late-result")
        first_changed, first_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(first_changed, 0, first_messages)
        provisional = self._entry(spec.task_id)
        self.assertEqual(provisional["status"], rr.SETTLED_WITHOUT_ENVELOPE)

        published = dcb.publish_prepared_worktree_outputs(self.vault, prepared)
        self.assertTrue(published["artifact_idempotent"])
        self.assertFalse(published["envelope_idempotent"])
        second_changed, second_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(second_changed, 0, second_messages)
        complete = self._entry(spec.task_id)
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(
            complete["prior_missing_envelope_status"],
            rr.SETTLED_WITHOUT_ENVELOPE,
        )
        terminal_events = [
            item
            for item in complete.get("delivery_history", [])
            if item.get("event") == "terminal"
        ]
        self.assertEqual(len(terminal_events), 1)
        self._assert_fence(spec, complete)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_stale_receipt(self, spec: CycleSpec) -> None:
        self._register(spec)
        repeat = spec.ordinal // len(SCENARIOS)
        stale_attempt = f"d-{spec.ordinal + 1001:032x}"
        variants = (
            {"task_id": f"TASK-2026-08-07-{spec.ordinal:04d}-wrong-task"},
            {"attempt_id": stale_attempt},
            {"generation": 1},
            {"generation": True},
            {"generation": None},
            {"attempt_id": stale_attempt, "generation": 1, "filename_attempt": stale_attempt},
            {"task_id": f"TASK-2026-08-07-{spec.ordinal:04d}-wrong-again"},
            {"attempt_id": stale_attempt},
            {"generation": None},
            {"generation": 1},
        )
        self._write_receipt(spec, **variants[repeat])
        before = self.registry_path.read_bytes()
        changed, messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertEqual(changed, 0, messages)
        self.assertEqual(self.registry_path.read_bytes(), before)
        held = self._entry(spec.task_id)
        self.assertEqual(held["status"], "in-flight")
        self.assertEqual(held["delivery_state"], "in-progress")
        self._assert_fence(spec, held)

        self._write_receipt(spec)
        self._drive_receipt_close(spec)

    def _worker_echo(
        self,
        spec: CycleSpec,
        *,
        attempt_id: str,
        generation: int,
    ) -> dict[str, str]:
        return {
            "delivery_attempt_id": attempt_id,
            "delivery_generation": str(generation),
            "delivery_worker_id": "claude-r01",
            "worker_epoch": "epoch-2",
            "lease_generation": "2",
            "delivery_lane": "claude",
        }

    def _case_stale_worker_response(self, spec: CycleSpec) -> None:
        self._register(
            spec,
            delivery_worker_id="claude-r01",
            worker_assignment_state="in-progress",
            worker_epoch="epoch-2",
            lease_generation=2,
            lease_expires_at="2099-01-01T00:00:00+00:00",
        )
        repeat = spec.ordinal // len(SCENARIOS)
        stale_attempt = f"d-{spec.ordinal + 2001:032x}"
        if repeat % 2 == 0:
            stale_echo = self._worker_echo(
                spec, attempt_id=stale_attempt, generation=spec.generation
            )
            expected_issue = "delivery_attempt_id mismatch"
        else:
            stale_echo = self._worker_echo(
                spec, attempt_id=spec.attempt_id, generation=spec.generation - 1
            )
            expected_issue = "delivery_generation mismatch"
        stale = self._prepare(
            spec,
            tag="stale-worker",
            reconciliation_echo=stale_echo,
        )
        dcb.publish_prepared_worktree_outputs(self.vault, stale)

        first_changed, first_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(first_changed, 0, first_messages)
        held = self._entry(spec.task_id)
        self.assertEqual(held["status"], "in-flight")
        self.assertEqual(held["delivery_state"], "in-progress")
        self.assertIn(expected_issue, held["worker_response_issue"])
        self._assert_fence(spec, held)
        self._assert_stable(spec)

        stale_evidence = self.state / "stale-responses" / f"{spec.task_id}-generation-1.md"
        stale_evidence.parent.mkdir(parents=True, exist_ok=True)
        (self.vault / spec.envelope_rel).replace(stale_evidence)
        current = self._prepare(
            spec,
            tag="current-worker",
            reconciliation_echo=self._worker_echo(
                spec,
                attempt_id=spec.attempt_id,
                generation=spec.generation,
            ),
        )
        published = dcb.publish_prepared_worktree_outputs(self.vault, current)
        self.assertTrue(published["artifact_idempotent"])
        self.assertFalse(published["envelope_idempotent"])
        second_changed, second_messages = rr.reconcile(spec.task_id, dry_run=False)
        self.assertGreater(second_changed, 0, second_messages)
        complete = self._entry(spec.task_id)
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(complete["delivery_state"], "terminal")
        self.assertNotIn("worker_response_issue", complete)
        self.assertTrue(stale_evidence.is_file())
        self._assert_fence(spec, complete)
        self._assert_archived(spec)
        self._assert_stable(spec)

    def _case_sibling_artifact(self, spec: CycleSpec) -> None:
        self._register(spec)
        other_task = f"TASK-2026-08-07-{spec.ordinal:04d}-sibling-owner"
        collision = self.vault / spec.artifact_rel
        collision.parent.mkdir(parents=True, exist_ok=True)
        other_bytes = (
            "blocked\n\n"
            f"# Board dispatch blocked — {other_task}\n\n"
            "Controller reason: belongs to a sibling task\n"
        ).encode()
        collision.write_bytes(other_bytes)
        collision_inode = collision.stat().st_ino

        with self.assertRaisesRegex(
            dcb.DispatchContextError, "return artifact destination already differs"
        ):
            self._prepare(spec, tag="sibling-collision")
        self.assertFalse((self.vault / spec.envelope_rel).exists())
        self._write_receipt(spec)
        self._drive_receipt_close(spec)
        self.assertEqual(collision.read_bytes(), other_bytes)
        self.assertEqual(collision.stat().st_ino, collision_inode)
        self.assertFalse(
            collision.with_name(f"{collision.name}.blocked-{spec.task_id}").exists()
        )

    def test_100_cycle_lifecycle_matrix(self) -> None:
        handlers = {
            "success": self._case_success,
            "blocked": self._case_blocked,
            "cancelled": self._case_cancelled,
            "unsafe-artifact": self._case_unsafe_artifact,
            "missing-artifact": self._case_missing_artifact,
            "missing-envelope": self._case_missing_envelope,
            "late-result": self._case_late_result,
            "stale-receipt": self._case_stale_receipt,
            "stale-worker-response": self._case_stale_worker_response,
            "sibling-artifact": self._case_sibling_artifact,
        }
        counts: Counter[str] = Counter()
        started = time.monotonic()
        for ordinal in range(100):
            scenario = SCENARIOS[ordinal % len(SCENARIOS)]
            spec = self._spec(ordinal, scenario)
            with self.subTest(cycle=ordinal, scenario=scenario):
                handlers[scenario](spec)
                self._assert_general_sibling_unchanged(spec)
                counts[scenario] += 1
        elapsed = time.monotonic() - started

        self.assertEqual(sum(counts.values()), 100)
        self.assertEqual(counts, Counter({scenario: 10 for scenario in SCENARIOS}))
        self.assertTrue(self.guarded_writes)
        self.assertLess(elapsed, 30.0)
        print(
            "lifecycle-matrix "
            f"cycles={sum(counts.values())} "
            f"counts={json.dumps(dict(sorted(counts.items())), sort_keys=True)} "
            f"elapsed_seconds={elapsed:.3f}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
