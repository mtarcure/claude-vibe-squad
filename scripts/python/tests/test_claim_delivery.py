"""Deterministic registration, claim, and legacy-fence compatibility tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
RECONCILER = REPO / "scripts/python/registry_reconciler.py"


class DeliveryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="delivery-claim-")
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

    def entry(self, task_id: str, *, lane: str = "gpt-codex", at: str, attempt: str) -> dict:
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
            "delivery_history": [
                {
                    "event": "queued",
                    "at": at,
                    "attempt_id": attempt,
                    "generation": 1,
                    "lane": lane,
                }
            ],
        }

    def write_registry(self, entries: dict) -> None:
        (self.root / "_state/active-tasks.json").write_text(
            json.dumps(entries, indent=2) + "\n", encoding="utf-8"
        )

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(RECONCILER), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result

    def action(self, *args: str) -> dict:
        return json.loads(self.run_cli(*args).stdout)

    def registry(self) -> dict:
        return json.loads((self.root / "_state/active-tasks.json").read_text())


class ClaimAndRedeliveryTests(DeliveryFixture):
    def test_registration_retry_is_cas_idempotent_and_conflict_rejects(self):
        task = "TASK-register-cas"
        at = "2026-07-17T00:00:00+00:00"
        original = self.entry(task, at=at, attempt="d-original")
        registered = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(original)
        )
        self.assertIn("outcome=registered", registered.stdout)
        before = (self.root / "_state/active-tasks.json").read_bytes()

        retry = self.entry(task, at="2026-07-17T00:01:00+00:00", attempt="d-new")
        idempotent = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(retry)
        )
        self.assertIn("outcome=idempotent", idempotent.stdout)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())

        retry["return_artifact"] = "_state/conflicting.md"
        conflict = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(retry), check=False
        )
        self.assertEqual(conflict.returncode, 3)
        self.assertIn("conflicting task re-registration", conflict.stderr)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())

    def test_claim_is_idempotent_lane_ordered_and_stale_attempt_rejected(self):
        at = datetime(2026, 7, 17, tzinfo=UTC)
        first, second = "TASK-lane-1", "TASK-lane-2"
        self.write_registry({
            first: self.entry(first, at=at.isoformat(), attempt="d-first"),
            second: self.entry(
                second, at=(at + timedelta(seconds=1)).isoformat(), attempt="d-second"
            ),
        })
        before = (self.root / "_state/active-tasks.json").read_bytes()
        stale = self.run_cli(
            "--claim-task", first, "--attempt-id", "d-stale", "--now", at.isoformat(),
            check=False,
        )
        self.assertEqual(stale.returncode, 3)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())
        blocked = self.run_cli(
            "--claim-task", second, "--attempt-id", "d-second", "--now", at.isoformat(),
            check=False,
        )
        self.assertIn("not the head", blocked.stderr)
        claimed = self.action(
            "--claim-task", first, "--attempt-id", "d-first", "--now", at.isoformat()
        )
        duplicate = self.action(
            "--claim-task", first, "--attempt-id", "d-first", "--now", at.isoformat()
        )
        self.assertFalse(claimed["idempotent"])
        self.assertTrue(duplicate["idempotent"])
        response = self.root / f"departments/coding/outbox/{first}-response.md"
        response.parent.mkdir(parents=True)
        response.write_text(
            f"---\nin_response_to: {first}\nstatus: complete\n---\n\ndone\n",
            encoding="utf-8",
        )
        self.run_cli("--task-id", first)
        released = self.action(
            "--claim-task", second, "--attempt-id", "d-second", "--now", at.isoformat()
        )
        self.assertEqual(released["delivery_state"], "in-progress")
        history = self.registry()[first]["delivery_history"]
        self.assertEqual([item["event"] for item in history].count("claimed"), 1)
    def test_legacy_worker_claim_fences_duplicate_and_expiry(self):
        now = datetime(2026, 7, 18, tzinfo=UTC)
        task = "TASK-worker-fence"
        base = self.entry(task, at=now.isoformat(), attempt="d-one")
        base.update(
            delivery_worker_id="codex-r01", worker_epoch="epoch-a", lease_generation=7,
            lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            worker_assignment_state="assigned",
        )
        def claim(task_id: str, **over: str) -> subprocess.CompletedProcess[str]:
            values = {
                "attempt": "d-one", "worker": "codex-r01", "epoch": "epoch-a",
                "lease": "7", "lane": "gpt-codex", **over,
            }
            return self.run_cli(
                "--claim-task", task_id, "--attempt-id", values["attempt"],
                "--worker-id", values["worker"], "--worker-epoch", values["epoch"],
                "--lease-generation", values["lease"], "--worker-lane", values["lane"],
                "--now", now.isoformat(), check=False,
            )
        self.write_registry({task: base})
        for key, value, message in (
            ("worker", "other", "assignment mismatch"),
            ("epoch", "old", "stale worker epoch"),
            ("lease", "6", "stale lease generation"),
            ("lane", "claude", "worker lane mismatch"),
        ):
            with self.subTest(message=message):
                before = (self.root / "_state/active-tasks.json").read_bytes()
                result = claim(task, **{key: value})
                self.assertEqual(result.returncode, 3)
                self.assertIn(message, result.stderr)
                self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())
        self.assertEqual(json.loads(claim(task).stdout)["delivery_state"], "in-progress")
        duplicate = self.entry("TASK-worker-duplicate", at=now.isoformat(), attempt="d-two")
        duplicate.update({key: base[key] for key in (
            "delivery_worker_id", "worker_epoch", "lease_generation",
            "lease_expires_at", "worker_assignment_state",
        )})
        self.write_registry({
            task: {**base, "delivery_state": "in-progress"},
            "TASK-worker-duplicate": duplicate,
        })
        self.assertIn(
            "already has active task", claim("TASK-worker-duplicate", attempt="d-two").stderr
        )
        expired = {**base, "lease_expires_at": (now - timedelta(seconds=1)).isoformat()}
        self.write_registry({task: expired})
        self.assertIn("worker lease expired", claim(task).stderr)
        self.assertEqual(self.registry()[task]["worker_assignment_state"], "expired")
    def test_legacy_member_identity_remains_lane_bound(self):
        at = "2026-07-18T00:00:00+00:00"
        valid = self.entry("TASK-member", at=at, attempt="d-one")
        valid.update(member_id="gpt-codex:sub02", replica_index=2)
        self.run_cli("--register-task", "TASK-member", "--entry-json", json.dumps(valid))
        self.assertEqual(self.registry()["TASK-member"]["member_id"], "gpt-codex:sub02")
        invalid = self.entry("TASK-bad-member", at=at, attempt="d-two")
        invalid.update(member_id="claude:r01", replica_index=1)
        rejected = self.run_cli(
            "--register-task", "TASK-bad-member", "--entry-json", json.dumps(invalid),
            check=False,
        )
        self.assertIn("member_id must", rejected.stderr)
    def test_preexpiry_worker_response_can_settle_review_after_expiry(self):
        task = "TASK-delayed-review"
        expiry = datetime.now(UTC) - timedelta(minutes=1)
        landed = expiry - timedelta(seconds=1)
        entry = self.entry(task, lane="claude", at="2026-07-18T00:00:00+00:00", attempt="d-one")
        entry.update(
            specialist="claude-spec", mandatory_review="true", review_model="gpt-codex",
            review_class="standard",
            delivery_state="in-progress", delivery_worker_id="claude-r01",
            worker_epoch="epoch-a", lease_generation=1, lease_expires_at=expiry.isoformat(),
            worker_assignment_state="in-progress",
        )
        self.write_registry({task: entry})
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "specialist-runtime-map.tsv").write_text(
            "specialist\tc2\tc3\tc4\tc5\tc6\tprimary_lane\n"
            "claude-spec\tx\tx\tx\tx\tx\tclaude\n", encoding="utf-8",
        )
        own = self.root / f"departments/coding/outbox/{task}-response.md"
        own.parent.mkdir(parents=True)
        own.write_text(
            f"---\nin_response_to: {task}\nfrom: claude\nstatus: complete\n"
            "delivery_attempt_id: d-one\ndelivery_generation: 1\n"
            "delivery_worker_id: claude-r01\nworker_epoch: epoch-a\n"
            "lease_generation: 1\ndelivery_lane: claude\n---\n\ntimely\n",
            encoding="utf-8",
        )
        os.utime(own, (landed.timestamp(), landed.timestamp()))
        self.run_cli("--task-id", task)
        self.assertEqual(self.registry()[task]["status"], "review-required")
        review_task = "TASK-delayed-review-verdict"
        review_entry = self.entry(
            review_task,
            lane="gpt-codex",
            at=landed.isoformat(),
            attempt="d-review",
        )
        review_entry["reviews"] = task
        self.run_cli(
            "--register-task",
            review_task,
            "--entry-json",
            json.dumps(review_entry),
        )
        review = self.root / f"departments/coding/outbox/{review_task}-response.md"
        review.write_text(
            f"---\nin_response_to: {task}\nfrom: gpt-codex\ntype: RESULT\nstatus: complete\n"
            "verdict: APPROVE\n---\n\nreviewed\n", encoding="utf-8",
        )
        self.run_cli(
            "--settle-review", task,
            "--review-ref", f"departments/coding/outbox/{review_task}-response.md",
        )
        self.assertEqual(self.registry()[task]["status"], "complete")

if __name__ == "__main__":
    unittest.main()
