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
from unittest import mock


REPO = Path(__file__).resolve().parents[3]
RECONCILER = REPO / "scripts/python/registry_reconciler.py"
PYTHON_ROOT = REPO / "scripts/python"
sys.path.insert(0, str(PYTHON_ROOT))

import dispatch_context_builder as dcb  # noqa: E402
import worktree_isolation as wti  # noqa: E402


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
        self.assertFalse((self.root / review_entry["return_artifact"]).exists())
        self.run_cli(
            "--settle-review", task,
            "--review-ref", f"departments/coding/outbox/{review_task}-response.md",
        )
        self.assertEqual(self.registry()[task]["status"], "complete")


class ResidueHealthGateTests(unittest.TestCase):
    """Outcome, not worker status, decides whether residue may integrate."""

    OUTPUT = (
        "departments/coding/outbox/"
        "TASK-2026-08-30-1803-residuehealth-response.md"
    )
    TASK = "TASK-2026-08-30-1803-residuehealth"
    ATTEMPT = "d-" + "c" * 32

    def git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "/usr/bin/git",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    def provision(
        self, root: Path, *, task_status: str
    ) -> tuple[Path, wti.WorktreeHandle, Path]:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "checkout", "-q", "-b", "v2")
        self.git(repo, "config", "user.name", "Residue Health Test")
        self.git(repo, "config", "user.email", "residue-health@example.invalid")
        (repo / "shared").mkdir()
        (repo / "shared/specialist-runtime-map.tsv").write_text(
            "specialist\tc2\tc3\tc4\tc5\tc6\tprimary_lane\n",
            encoding="utf-8",
        )
        (repo / "candidate-health.txt").write_text("green\n", encoding="utf-8")
        (repo / "_state").mkdir()
        (repo / "_state/active-tasks.json").write_text(
            json.dumps({self.TASK: {"status": task_status}}) + "\n",
            encoding="utf-8",
        )
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-q", "-m", "baseline")
        pool = wti.WorktreePool(repo, root / "pool", base_branch="v2")
        handle = pool.provision(self.TASK, self.ATTEMPT)

        verifier = root / "trusted-health-verifier.sh"
        verifier.write_text(
            "#!/bin/bash\n"
            "if [[ $(<\"${VAULT_ROOT}/candidate-health.txt\") == green ]]; then\n"
            "  echo 'candidate-health: PASS'\n"
            "  exit 0\n"
            "fi\n"
            "echo 'candidate-health: FAIL adapter pins disagree' >&2\n"
            "exit 1\n",
            encoding="utf-8",
        )
        return repo, handle, verifier

    def write_worker_outputs(
        self, handle: wti.WorktreeHandle, *, health: str
    ) -> dict[str, object]:
        (handle.worktree_root / "candidate-health.txt").write_text(
            health + "\n", encoding="utf-8"
        )
        response = handle.worktree_root / self.OUTPUT
        response.parent.mkdir(parents=True)
        response.write_text(
            "---\n"
            f"id: {self.TASK}-response\n"
            f"in_response_to: {self.TASK}\n"
            "from: gpt-codex\n"
            "to: chrono\n"
            "type: RESULT\n"
            "status: complete\n"
            f"return_artifact: {self.OUTPUT}\n"
            "---\n\nworker finished\n",
            encoding="utf-8",
        )
        return {
            "task_id": self.TASK,
            "lane": "codex",
            "write_paths": ["candidate-health.txt", self.OUTPUT],
            "expected_result_path": self.OUTPUT,
            "expected_outbox_path": self.OUTPUT,
            "reconciliation_echo": {},
        }

    def integrate(self, handle: wti.WorktreeHandle) -> None:
        wti.commit_worker_residue(
            handle,
            ("candidate-health.txt", self.OUTPUT),
            exclude_paths=(self.OUTPUT,),
        )
        wti.integrate_worktree_commits(
            handle,
            ("candidate-health.txt", self.OUTPUT),
            exclude_paths=(self.OUTPUT,),
        )

    def test_broken_residue_is_refused_for_superseded_and_complete_tasks(self):
        for task_status in ("superseded", "complete"):
            with self.subTest(task_status=task_status), tempfile.TemporaryDirectory(
                prefix="residue-health-broken-"
            ) as directory:
                repo, handle, verifier = self.provision(
                    Path(directory), task_status=task_status
                )
                authority = self.write_worker_outputs(handle, health="red")
                with mock.patch.object(
                    dcb, "RESIDUE_HEALTH_VERIFIER", verifier, create=True
                ), mock.patch.dict(
                    os.environ, {"SQUAD_BASE_BRANCH": "v2"}, clear=False
                ):
                    try:
                        dcb.prepare_worktree_outputs(
                            repo, handle.worktree_root, authority
                        )
                    except dcb.DispatchContextError as exc:
                        self.assertIn(
                            "candidate tree health check refused residue promotion",
                            str(exc),
                        )
                    else:
                        # This is the literal pre-fix behavior: preparation
                        # accepts the unhealthy candidate, so the supervisor's
                        # next two calls land it on the integration branch.
                        self.integrate(handle)
                        landed = (repo / "candidate-health.txt").read_text(
                            encoding="utf-8"
                        ).strip()
                        self.fail(
                            "broken residue landed after task status "
                            f"{task_status}: candidate-health={landed}"
                        )

                self.assertEqual(
                    (repo / "candidate-health.txt").read_text(encoding="utf-8"),
                    "green\n",
                )

    def test_healthy_complete_task_residue_still_promotes(self):
        with tempfile.TemporaryDirectory(
            prefix="residue-health-good-"
        ) as directory:
            repo, handle, verifier = self.provision(
                Path(directory), task_status="complete"
            )
            authority = self.write_worker_outputs(handle, health="green-v2")
            verifier.write_text(
                verifier.read_text(encoding="utf-8").replace(
                    "== green", "== green-v2"
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                dcb, "RESIDUE_HEALTH_VERIFIER", verifier, create=True
            ), mock.patch.dict(
                os.environ, {"SQUAD_BASE_BRANCH": "v2"}, clear=False
            ):
                prepared = dcb.prepare_worktree_outputs(
                    repo, handle.worktree_root, authority
                )
                self.assertEqual(prepared.status, "complete")
                self.integrate(handle)

            self.assertEqual(
                (repo / "candidate-health.txt").read_text(encoding="utf-8"),
                "green-v2\n",
            )

if __name__ == "__main__":
    unittest.main()
