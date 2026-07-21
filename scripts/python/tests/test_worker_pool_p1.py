"""Feature-gated P1 worker assignment, fencing, and recovery tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[3]
RECONCILER = REPO / "scripts/python/registry_reconciler.py"


class WorkerPoolP1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="worker-pool-p1-")
        self.root = Path(self.temp.name)
        (self.root / "_state").mkdir()
        self.env = {
            **os.environ,
            "VAULT_ROOT": str(self.root),
            "STATE_DIR": str(self.root / "_state"),
            "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux",
            "SQUAD_SESSION": "none",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def entry(
        self,
        task_id: str,
        *,
        at: str,
        attempt: str,
        lane: str = "gpt-codex",
        priority: str = "normal",
    ) -> dict:
        return {
            "compatibility_namespace": "coding",
            "source_namespace": "coding",
            "specialist": "systems-engineer",
            "to_model": lane,
            "mandatory_review": "false",
            "review_model": "none",
            "return_artifact": f"_state/{task_id}.md",
            "write_scope": [],
            "status": "in-flight",
            "dispatched_at": at,
            "delivery_state": "queued",
            "delivery_attempt_id": attempt,
            "delivery_generation": 1,
            "delivery_lane": lane,
            "delivery_attempt_count": 0,
            "delivery_retry_count": 0,
            "delivery_max_attempts": 5,
            "delivery_next_attempt_at": at,
            "priority_class": priority,
            "enqueued_at": at,
            "delivery_history": [],
        }

    def write_registry(self, entries: dict) -> None:
        (self.root / "_state/active-tasks.json").write_text(
            json.dumps(entries, indent=2) + "\n", encoding="utf-8"
        )

    def registry(self) -> dict:
        return json.loads((self.root / "_state/active-tasks.json").read_text())

    def run_cli(
        self, *args: str, pooled: bool = True, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if pooled:
            env["SQUAD_WORKER_POOL_ENABLED"] = "1"
        else:
            env.pop("SQUAD_WORKER_POOL_ENABLED", None)
        result = subprocess.run(
            [sys.executable, str(RECONCILER), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def action(self, *args: str, pooled: bool = True) -> dict:
        return json.loads(self.run_cli(*args, pooled=pooled).stdout)

    @staticmethod
    def worker(worker_id: str, lane: str, epoch: str, heartbeat: str) -> dict:
        return {
            "worker_id": worker_id,
            "worker_epoch": epoch,
            "lane": lane,
            "heartbeat_observed_at": heartbeat,
            "available": True,
        }

    def scan(self, workers: list[dict], now: str, *, lease: int = 300) -> dict:
        return self.action(
            "--schedule-workers-json",
            json.dumps(workers),
            "--now",
            now,
            "--lease-seconds",
            str(lease),
        )

    def test_flag_off_preserves_legacy_lane_head_and_schema_is_additive(self):
        at = "2026-07-18T00:00:00+00:00"
        first = self.entry("TASK-a", at=at, attempt="d-a")
        second = self.entry("TASK-b", at=at, attempt="d-b")
        self.write_registry({"TASK-a": first, "TASK-b": second})
        self.assertTrue(
            self.action("--authorize-delivery", "TASK-a", "--now", at, pooled=False)[
                "authorized"
            ]
        )
        blocked = self.action(
            "--authorize-delivery", "TASK-b", "--now", at, pooled=False
        )
        self.assertEqual(blocked["reason"], "lane-head-blocked")

        task = "TASK-register"
        register = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(first), pooled=False
        )
        self.assertIn("outcome=registered", register.stdout)
        stored = self.registry()[task]
        self.assertIsNone(stored["delivery_worker_id"])
        self.assertEqual(stored["lease_generation"], 0)
        self.assertEqual(stored["priority_class"], "normal")

    def test_authoritative_scan_priority_fifo_and_lost_nudge_recovery(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        entries = {
            "TASK-normal": self.entry(
                "TASK-normal", at=now.isoformat(), attempt="d-normal"
            ),
            "TASK-urgent-old": self.entry(
                "TASK-urgent-old",
                at=(now - timedelta(seconds=2)).isoformat(),
                attempt="d-urgent-old",
                priority="urgent",
            ),
            "TASK-urgent-new": self.entry(
                "TASK-urgent-new",
                at=(now - timedelta(seconds=1)).isoformat(),
                attempt="d-urgent-new",
                priority="urgent",
            ),
            "TASK-not-due": self.entry(
                "TASK-not-due",
                at=(now + timedelta(minutes=1)).isoformat(),
                attempt="d-not-due",
                priority="urgent",
            ),
        }
        self.write_registry(entries)
        workers = [
            self.worker("codex-r01", "gpt-codex", "epoch-a", now.isoformat()),
            self.worker("codex-r02", "gpt-codex", "epoch-b", now.isoformat()),
        ]
        first = self.scan(workers, now.isoformat())
        self.assertEqual(
            [item["task_id"] for item in first["new_assignments"]],
            ["TASK-urgent-old", "TASK-urgent-new"],
        )
        self.assertEqual(len(first["work"]), 2)
        second = self.scan(workers, now.isoformat())
        self.assertEqual(second["new_assignments"], [])
        self.assertEqual(len(second["work"]), 2)
        self.assertIsNone(self.registry()["TASK-not-due"].get("delivery_worker_id"))

    def test_failed_post_commit_nudge_cannot_undo_assignment(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-lost-nudge"
        self.write_registry({task: self.entry(task, at=now.isoformat(), attempt="d-one")})
        worker = self.worker("codex-r01", "gpt-codex", "epoch-a", now.isoformat())
        module_env = {**self.env, "SQUAD_WORKER_POOL_ENABLED": "1"}
        with patch.dict(os.environ, module_env, clear=False):
            spec = importlib.util.spec_from_file_location(
                "worker_pool_p1_reconciler", RECONCILER
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            def eaten_nudge(_assignment: dict) -> bool:
                raise RuntimeError("transport dropped")

            first = module.schedule_worker_scan(
                [worker], now_raw=now.isoformat(), nudge_callback=eaten_nudge
            )
            self.assertEqual(first["new_assignments"][0]["task_id"], task)
            self.assertEqual(
                first["nudges"],
                [{
                    "task_id": task,
                    "attempted": True,
                    "succeeded": False,
                    "error": "RuntimeError",
                }],
            )
            self.assertEqual(self.registry()[task]["delivery_worker_id"], "codex-r01")

            recovered = module.schedule_worker_scan(
                [worker], now_raw=now.isoformat()
            )
            self.assertEqual(recovered["new_assignments"], [])
            self.assertEqual([item["task_id"] for item in recovered["work"]], [task])

    def test_concurrent_scans_assign_once_and_increment_lease_once(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-concurrent-scan"
        self.write_registry({task: self.entry(task, at=now.isoformat(), attempt="d-one")})
        workers_json = json.dumps(
            [self.worker("codex-r01", "gpt-codex", "epoch-a", now.isoformat())]
        )

        def race(_index: int) -> dict:
            return self.action(
                "--schedule-workers-json", workers_json, "--now", now.isoformat()
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, range(2)))
        self.assertEqual(
            sum(len(result["new_assignments"]) for result in results), 1
        )
        stored = self.registry()[task]
        self.assertEqual(stored["lease_generation"], 1)
        self.assertEqual(
            [item["event"] for item in stored["delivery_history"]].count(
                "worker-assigned"
            ),
            1,
        )

    def test_heartbeat_renews_only_current_epoch_before_expiry(self):
        start = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-renew"
        self.write_registry({task: self.entry(task, at=start.isoformat(), attempt="d-one")})
        assigned = self.scan(
            [self.worker("codex-r01", "gpt-codex", "epoch-a", start.isoformat())],
            start.isoformat(),
            lease=10,
        )["new_assignments"][0]
        self.assertEqual(
            assigned["lease_expires_at"], (start + timedelta(seconds=10)).isoformat()
        )

        renewed_at = start + timedelta(seconds=5)
        self.scan(
            [self.worker("codex-r01", "gpt-codex", "epoch-a", renewed_at.isoformat())],
            renewed_at.isoformat(),
            lease=10,
        )
        renewed = self.registry()[task]
        self.assertEqual(
            renewed["lease_expires_at"],
            (renewed_at + timedelta(seconds=10)).isoformat(),
        )
        self.assertEqual(
            [item["event"] for item in renewed["delivery_history"]].count(
                "worker-lease-renewed"
            ),
            1,
        )

        stale_at = start + timedelta(seconds=6)
        self.scan(
            [self.worker("codex-r01", "gpt-codex", "epoch-stale", stale_at.isoformat())],
            stale_at.isoformat(),
            lease=10,
        )
        stale = self.registry()[task]
        self.assertEqual(stale["lease_expires_at"], renewed["lease_expires_at"])
        self.assertEqual(stale["heartbeat_observed_at"], renewed["heartbeat_observed_at"])

    def test_two_same_lane_workers_claim_independently_and_fences_fail_closed(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        self.write_registry(
            {
                "TASK-one": self.entry("TASK-one", at=now.isoformat(), attempt="d-one"),
                "TASK-two": self.entry("TASK-two", at=now.isoformat(), attempt="d-two"),
            }
        )
        workers = [
            self.worker("codex-r01", "gpt-codex", "epoch-a", now.isoformat()),
            self.worker("codex-r02", "gpt-codex", "epoch-b", now.isoformat()),
        ]
        assigned = self.scan(workers, now.isoformat())["new_assignments"]
        by_task = {item["task_id"]: item for item in assigned}
        for task_id in ("TASK-one", "TASK-two"):
            fence = by_task[task_id]
            claimed = self.action(
                "--claim-task",
                task_id,
                "--attempt-id",
                fence["delivery_attempt_id"],
                "--worker-id",
                fence["delivery_worker_id"],
                "--worker-epoch",
                fence["worker_epoch"],
                "--lease-generation",
                str(fence["lease_generation"]),
                "--worker-lane",
                fence["delivery_lane"],
                "--now",
                now.isoformat(),
            )
            self.assertEqual(claimed["delivery_state"], "in-progress")

        before = (self.root / "_state/active-tasks.json").read_bytes()
        fence = by_task["TASK-one"]
        stale = self.run_cli(
            "--claim-task",
            "TASK-one",
            "--attempt-id",
            fence["delivery_attempt_id"],
            "--worker-id",
            fence["delivery_worker_id"],
            "--worker-epoch",
            "old-epoch",
            "--lease-generation",
            str(fence["lease_generation"]),
            "--worker-lane",
            fence["delivery_lane"],
            "--now",
            now.isoformat(),
            check=False,
        )
        self.assertEqual(stale.returncode, 3)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())

    def test_duplicate_worker_active_claim_is_rejected(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        one = self.entry("TASK-one", at=now.isoformat(), attempt="d-one")
        two = self.entry("TASK-two", at=now.isoformat(), attempt="d-two")
        for entry in (one, two):
            entry.update(
                delivery_worker_id="codex-r01",
                worker_epoch="epoch-a",
                lease_generation=1,
                lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
                heartbeat_observed_at=now.isoformat(),
                worker_assignment_state="assigned",
            )
        one["delivery_state"] = "in-progress"
        self.write_registry({"TASK-one": one, "TASK-two": two})
        rejected = self.run_cli(
            "--claim-task", "TASK-two", "--attempt-id", "d-two",
            "--worker-id", "codex-r01", "--worker-epoch", "epoch-a",
            "--lease-generation", "1", "--worker-lane", "gpt-codex",
            "--now", now.isoformat(), check=False,
        )
        self.assertEqual(rejected.returncode, 3)
        self.assertIn("already has active task", rejected.stderr)

    def test_claim_checks_worker_epoch_generation_lane_and_expiry(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-all-fences"
        base = self.entry(task, at=now.isoformat(), attempt="d-one")
        base.update(
            delivery_worker_id="codex-r01",
            worker_epoch="epoch-a",
            lease_generation=7,
            lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            heartbeat_observed_at=now.isoformat(),
            worker_assignment_state="assigned",
        )
        cases = (
            ("other-worker", "epoch-a", "7", "gpt-codex", "assignment mismatch"),
            ("codex-r01", "old-epoch", "7", "gpt-codex", "stale worker epoch"),
            ("codex-r01", "epoch-a", "6", "gpt-codex", "stale lease generation"),
            ("codex-r01", "epoch-a", "7", "claude", "worker lane mismatch"),
        )
        for worker_id, epoch, generation, lane, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self.write_registry({task: base})
                before = (self.root / "_state/active-tasks.json").read_bytes()
                result = self.run_cli(
                    "--claim-task", task, "--attempt-id", "d-one",
                    "--worker-id", worker_id, "--worker-epoch", epoch,
                    "--lease-generation", generation, "--worker-lane", lane,
                    "--now", now.isoformat(), check=False,
                )
                self.assertEqual(result.returncode, 3)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(
                    before, (self.root / "_state/active-tasks.json").read_bytes()
                )

        expired = dict(base)
        expired["lease_expires_at"] = (now - timedelta(seconds=1)).isoformat()
        self.write_registry({task: expired})
        result = self.run_cli(
            "--claim-task", task, "--attempt-id", "d-one",
            "--worker-id", "codex-r01", "--worker-epoch", "epoch-a",
            "--lease-generation", "7", "--worker-lane", "gpt-codex",
            "--now", now.isoformat(), check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("worker lease expired", result.stderr)
        self.assertEqual(self.registry()[task]["worker_assignment_state"], "expired")

    def test_expiry_surfaces_without_requeue_until_explicit_hard_signal(self):
        start = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-expiry"
        self.write_registry({task: self.entry(task, at=start.isoformat(), attempt="d-one")})
        workers = [self.worker("codex-r01", "gpt-codex", "epoch-a", start.isoformat())]
        self.scan(workers, start.isoformat(), lease=10)
        expired_at = start + timedelta(seconds=11)
        expired_workers = [
            self.worker("codex-r01", "gpt-codex", "epoch-a", expired_at.isoformat())
        ]
        expired = self.scan(expired_workers, expired_at.isoformat(), lease=10)
        self.assertEqual(expired["surfaced"][0]["reason"], "worker-lease-expired")
        entry = self.registry()[task]
        self.assertEqual(entry["delivery_state"], "terminal")
        self.assertEqual(entry["delivery_worker_id"], "codex-r01")

        refused = self.run_cli(
            "--advance-delivery", task, "--attempt-id", "d-two", "--generation", "2",
            "--lane", "gpt-codex", "--now", expired_at.isoformat(), check=False,
        )
        self.assertEqual(refused.returncode, 3)
        self.assertIn("hard-signal", refused.stderr)
        self.action(
            "--advance-delivery", task, "--attempt-id", "d-two", "--generation", "2",
            "--lane", "gpt-codex", "--hard-signal", "confirmed-worker-exit",
            "--now", expired_at.isoformat(),
        )
        self.assertIsNone(self.registry()[task]["delivery_worker_id"])
        reassigned = self.scan(expired_workers, expired_at.isoformat(), lease=10)
        self.assertEqual(reassigned["new_assignments"][0]["lease_generation"], 2)

    def test_response_requires_exact_live_fence_and_rejects_zombie(self):
        task = "TASK-response-fence"
        future = datetime(2099, 1, 1, tzinfo=UTC)
        entry = self.entry(task, at="2026-07-18T00:00:00+00:00", attempt="d-one")
        entry.update(
            delivery_state="in-progress",
            delivery_worker_id="codex-r01",
            worker_epoch="epoch-a",
            lease_generation=4,
            lease_expires_at=future.isoformat(),
            heartbeat_observed_at="2026-07-18T00:00:00+00:00",
            worker_assignment_state="in-progress",
            member_id="gpt-codex:r01",
            replica_index=1,
        )
        self.write_registry({task: entry})
        response = self.root / f"departments/coding/outbox/{task}-response.md"
        response.parent.mkdir(parents=True)

        def write_response(epoch: str = "epoch-a", target: str = task) -> None:
            response.write_text(
                "---\n"
                f"id: {task}-response\n"
                f"in_response_to: {target}\n"
                "from: gpt-codex\nto: chrono\ntype: RESULT\nstatus: complete\n"
                "delivery_attempt_id: d-one\ndelivery_generation: 1\n"
                f"delivery_worker_id: codex-r01\nworker_epoch: {epoch}\n"
                "lease_generation: 4\ndelivery_lane: gpt-codex\n"
                f"lease_expires_at: {future.isoformat()}\n"
                "member_id: gpt-codex:r01\nreplica_index: 1\n---\n\ndone\n",
                encoding="utf-8",
            )

        write_response(target="TASK-wrong")
        self.run_cli("--task-id", task)
        held = self.registry()[task]
        self.assertEqual(held["status"], "in-flight")
        self.assertIn("in_response_to mismatch", held["worker_response_issue"])

        write_response(epoch="zombie")
        self.run_cli("--task-id", task)
        held = self.registry()[task]
        self.assertIn("worker_epoch mismatch", held["worker_response_issue"])

        write_response()
        self.run_cli("--task-id", task)
        self.assertEqual(self.registry()[task]["status"], "complete")

        entry["lease_expires_at"] = "2020-01-01T00:00:00+00:00"
        entry["worker_assignment_state"] = "in-progress"
        self.write_registry({task: entry})
        response.unlink()
        future = datetime(2020, 1, 1, tzinfo=UTC)
        write_response()
        self.run_cli("--task-id", task)
        zombie = self.registry()[task]
        self.assertEqual(zombie["status"], "in-flight")
        self.assertIn("after worker lease expiry", zombie["worker_response_issue"])

    def test_corrupt_registry_scan_fails_without_replacement(self):
        path = self.root / "_state/active-tasks.json"
        path.write_text("{bad json\n", encoding="utf-8")
        before = path.read_bytes()
        now = "2026-07-18T00:00:00+00:00"
        result = self.run_cli(
            "--schedule-workers-json",
            json.dumps([self.worker("codex-r01", "gpt-codex", "epoch-a", now)]),
            "--now", now,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not valid JSON", result.stderr)
        self.assertEqual(before, path.read_bytes())

    def test_persisted_assignment_stays_fenced_when_flag_is_turned_off(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-drain-first"
        self.write_registry({task: self.entry(task, at=now.isoformat(), attempt="d-one")})
        fence = self.scan(
            [self.worker("codex-r01", "gpt-codex", "epoch-a", now.isoformat())],
            now.isoformat(),
        )["new_assignments"][0]

        blocked = self.action(
            "--authorize-delivery", task, "--now", now.isoformat(), pooled=False
        )
        self.assertEqual(blocked["reason"], "worker-scan-owned")
        missing_fence = self.run_cli(
            "--claim-task", task, "--attempt-id", "d-one", "--now", now.isoformat(),
            pooled=False, check=False,
        )
        self.assertEqual(missing_fence.returncode, 3)
        claimed = self.action(
            "--claim-task", task, "--attempt-id", "d-one",
            "--worker-id", fence["delivery_worker_id"],
            "--worker-epoch", fence["worker_epoch"],
            "--lease-generation", str(fence["lease_generation"]),
            "--worker-lane", fence["delivery_lane"],
            "--now", now.isoformat(), pooled=False,
        )
        self.assertEqual(claimed["delivery_state"], "in-progress")
        refused = self.run_cli(
            "--advance-delivery", task, "--attempt-id", "d-two", "--generation", "2",
            "--lane", "gpt-codex", "--now", now.isoformat(), pooled=False, check=False,
        )
        self.assertEqual(refused.returncode, 3)

    def test_timely_fenced_response_can_be_settled_after_lease_expiry(self):
        task = "TASK-delayed-review"
        expiry = datetime.now(UTC) - timedelta(minutes=1)
        landed = expiry - timedelta(seconds=1)
        entry = self.entry(
            task, at="2026-07-18T00:00:00+00:00", attempt="d-one", lane="claude"
        )
        entry.update(
            specialist="claude-spec",
            mandatory_review="true",
            review_model="gpt-codex",
            delivery_state="in-progress",
            delivery_worker_id="claude-r01",
            worker_epoch="epoch-a",
            lease_generation=1,
            lease_expires_at=expiry.isoformat(),
            heartbeat_observed_at=landed.isoformat(),
            worker_assignment_state="in-progress",
        )
        self.write_registry({task: entry})
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "specialist-runtime-map.tsv").write_text(
            "specialist\tc2\tc3\tc4\tc5\tc6\tprimary_lane\n"
            "claude-spec\tx\tx\tx\tx\tx\tclaude\n",
            encoding="utf-8",
        )
        own = self.root / f"departments/coding/outbox/{task}-response.md"
        own.parent.mkdir(parents=True)
        own.write_text(
            "---\n"
            f"id: {task}-response\nin_response_to: {task}\n"
            "from: claude\nto: chrono\ntype: RESULT\nstatus: complete\n"
            "delivery_attempt_id: d-one\ndelivery_generation: 1\n"
            "delivery_worker_id: claude-r01\nworker_epoch: epoch-a\n"
            "lease_generation: 1\ndelivery_lane: claude\n---\n\ntimely\n",
            encoding="utf-8",
        )
        os.utime(own, (landed.timestamp(), landed.timestamp()))
        self.run_cli("--task-id", task)
        self.assertEqual(self.registry()[task]["status"], "review-required")

        review = self.root / "departments/coding/outbox/REVIEW-delayed-response.md"
        review.write_text(
            "---\nid: REVIEW-delayed-response\n"
            f"in_response_to: {task}\nfrom: gpt-codex\nto: chrono\n"
            "type: RESULT\nstatus: complete\nverdict: APPROVE\n---\n\nreviewed\n",
            encoding="utf-8",
        )
        self.run_cli(
            "--settle-review", task,
            "--review-ref", "departments/coding/outbox/REVIEW-delayed-response.md",
        )
        self.assertEqual(self.registry()[task]["status"], "complete")

    def test_member_identity_is_lane_bound_but_task_id_is_independent(self):
        now = "2026-07-18T00:00:00+00:00"
        task = "TASK-no-worker-name-required"
        entry = self.entry(task, at=now, attempt="d-one")
        entry.update(member_id="gpt-codex:sub02", replica_index=2)
        self.write_registry({task: entry})
        workers = [self.worker("worker-arbitrary", "gpt-codex", "epoch-a", now)]
        assigned = self.scan(workers, now)["new_assignments"][0]
        self.assertEqual(assigned["task_id"], task)
        self.assertEqual(assigned["member_id"], "gpt-codex:sub02")

        bad = self.entry("TASK-bad-member", at=now, attempt="d-bad")
        bad.update(member_id="claude:r01", replica_index=1)
        rejected = self.run_cli(
            "--register-task", "TASK-bad-member", "--entry-json", json.dumps(bad),
            check=False,
        )
        self.assertEqual(rejected.returncode, 3)
        self.assertIn("member_id must", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
