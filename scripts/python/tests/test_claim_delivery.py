"""Deterministic delivery-claim, redelivery, serialization, and restart tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
RECONCILER = REPO / "scripts/python/registry_reconciler.py"
NUDGE = REPO / "bin/nudge-task.sh"


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
            "delivery_retry_count": 0,
            "delivery_max_attempts": 5,
            "delivery_next_attempt_at": at,
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

        retry["subswarm_directive_sha256"] = "a" * 64
        retry["subswarm_dispatch_sha256"] = "b" * 64
        retry["subswarm_member_bundle"] = "_state/deploy-member-bundle.json"
        retry["subswarm_max_concurrency"] = 2
        conflict = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(retry), check=False
        )
        self.assertEqual(conflict.returncode, 3)
        self.assertIn("conflicting task re-registration", conflict.stderr)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())

        retry.pop("subswarm_directive_sha256")
        retry.pop("subswarm_dispatch_sha256")
        retry.pop("subswarm_member_bundle")
        retry.pop("subswarm_max_concurrency")
        retry["return_artifact"] = "_state/conflicting.md"
        conflict = self.run_cli(
            "--register-task", task, "--entry-json", json.dumps(retry), check=False
        )
        self.assertEqual(conflict.returncode, 3)
        self.assertIn("conflicting task re-registration", conflict.stderr)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())

    def test_dropped_first_delivery_retries_same_attempt_and_claims_once(self):
        task = "TASK-drop-first"
        attempt = "d-stable"
        start = datetime(2026, 7, 17, tzinfo=UTC)
        self.write_registry({task: self.entry(task, at=start.isoformat(), attempt=attempt)})

        first = self.action("--authorize-delivery", task, "--now", start.isoformat())
        too_early = self.action(
            "--authorize-delivery", task, "--now", (start + timedelta(seconds=1)).isoformat()
        )
        retry = self.action(
            "--authorize-delivery", task, "--now", (start + timedelta(seconds=2)).isoformat()
        )
        claimed = self.action(
            "--claim-task",
            task,
            "--attempt-id",
            attempt,
            "--now",
            (start + timedelta(seconds=3)).isoformat(),
        )
        duplicate_claim = self.action(
            "--claim-task", task, "--attempt-id", attempt, "--now", start.isoformat()
        )

        self.assertTrue(first["authorized"])
        self.assertFalse(too_early["authorized"])
        self.assertEqual(too_early["reason"], "not-due")
        self.assertTrue(retry["authorized"])
        self.assertEqual(first["attempt_id"], retry["attempt_id"])
        self.assertEqual(claimed["delivery_state"], "in-progress")
        self.assertTrue(duplicate_claim["idempotent"])
        entry = self.registry()[task]
        self.assertEqual(entry["delivery_attempt_count"], 2)
        self.assertEqual(entry["delivery_retry_count"], 1)
        self.assertEqual(
            [item["event"] for item in entry["delivery_history"]].count("claimed"), 1
        )

    def test_duplicate_authorizations_are_lock_serialized(self):
        task = "TASK-duplicate-nudge"
        at = "2026-07-17T00:00:00+00:00"
        self.write_registry({task: self.entry(task, at=at, attempt="d-one")})

        def authorize(_index: int) -> dict:
            return self.action("--authorize-delivery", task, "--now", at)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(authorize, range(8)))
        self.assertEqual(sum(bool(item["authorized"]) for item in results), 1)
        entry = self.registry()[task]
        self.assertEqual(entry["delivery_attempt_count"], 1)
        self.assertEqual(entry["delivery_attempt_id"], "d-one")

    def test_stale_generation_claim_is_rejected_without_mutation(self):
        task = "TASK-stale-generation"
        at = "2026-07-17T00:00:00+00:00"
        self.write_registry({task: self.entry(task, at=at, attempt="d-gen1")})
        advanced = self.action(
            "--advance-delivery",
            task,
            "--attempt-id",
            "d-gen2",
            "--generation",
            "2",
            "--lane",
            "claude",
            "--now",
            at,
        )
        self.assertEqual(advanced["generation"], 2)
        before = (self.root / "_state/active-tasks.json").read_bytes()
        stale = self.run_cli(
            "--claim-task", task, "--attempt-id", "d-gen1", "--now", at, check=False
        )
        self.assertEqual(stale.returncode, 3)
        self.assertIn("stale delivery attempt", stale.stderr)
        self.assertEqual(before, (self.root / "_state/active-tasks.json").read_bytes())
        current = self.action(
            "--claim-task", task, "--attempt-id", "d-gen2", "--now", at
        )
        self.assertEqual(current["delivery_state"], "in-progress")

    def test_lane_head_blocks_next_until_response_terminalizes_current(self):
        first = "TASK-lane-1"
        second = "TASK-lane-2"
        at = datetime(2026, 7, 17, tzinfo=UTC)
        self.write_registry(
            {
                first: self.entry(first, at=at.isoformat(), attempt="d-first"),
                second: self.entry(
                    second,
                    at=(at + timedelta(seconds=1)).isoformat(),
                    attempt="d-second",
                ),
            }
        )
        self.action("--authorize-delivery", first, "--now", at.isoformat())
        self.action("--claim-task", first, "--attempt-id", "d-first", "--now", at.isoformat())
        blocked = self.action(
            "--authorize-delivery",
            second,
            "--now",
            (at + timedelta(seconds=2)).isoformat(),
        )
        self.assertEqual(blocked["reason"], "lane-head-blocked")
        self.assertEqual(blocked["blocked_by"], first)

        response = self.root / f"departments/coding/outbox/{first}-response.md"
        response.parent.mkdir(parents=True)
        response.write_text(
            f"---\nid: {first}-response\nin_response_to: {first}\nstatus: complete\n---\n\ndone\n",
            encoding="utf-8",
        )
        self.run_cli("--task-id", first)
        self.assertEqual(self.registry()[first]["delivery_state"], "terminal")
        released = self.action(
            "--authorize-delivery",
            second,
            "--now",
            (at + timedelta(seconds=2)).isoformat(),
        )
        self.assertTrue(released["authorized"])

    def test_review_required_legacy_task_does_not_hold_delivery_lane(self):
        review_hold = "TASK-review-hold-legacy"
        successor = "TASK-review-hold-successor"
        at = datetime(2026, 7, 17, tzinfo=UTC)
        legacy = self.entry(
            review_hold,
            lane="claude",
            at=at.isoformat(),
            attempt="d-legacy-unused",
        )
        legacy["status"] = "review-required"
        for key in tuple(legacy):
            if key.startswith("delivery_"):
                legacy.pop(key)
        self.write_registry(
            {
                review_hold: legacy,
                successor: self.entry(
                    successor,
                    lane="claude",
                    at=(at + timedelta(seconds=1)).isoformat(),
                    attempt="d-successor",
                ),
            }
        )

        released = self.action(
            "--authorize-delivery",
            successor,
            "--now",
            (at + timedelta(seconds=2)).isoformat(),
        )

        self.assertTrue(released["authorized"])
        self.assertEqual(self.registry()[review_hold]["status"], "review-required")

    def test_review_required_receipted_task_does_not_hold_delivery_lane(self):
        review_hold = "TASK-review-hold-receipted"
        successor = "TASK-review-hold-receipted-successor"
        at = datetime(2026, 7, 17, tzinfo=UTC)
        delivered = self.entry(
            review_hold,
            lane="claude",
            at=at.isoformat(),
            attempt="d-delivered",
        )
        delivered.update(
            status="review-required",
            delivery_state="terminal",
            delivery_terminal_at=at.isoformat(),
            delivery_next_attempt_at=None,
        )
        self.write_registry(
            {
                review_hold: delivered,
                successor: self.entry(
                    successor,
                    lane="claude",
                    at=(at + timedelta(seconds=1)).isoformat(),
                    attempt="d-successor",
                ),
            }
        )

        released = self.action(
            "--authorize-delivery",
            successor,
            "--now",
            (at + timedelta(seconds=2)).isoformat(),
        )

        self.assertTrue(released["authorized"])
        self.assertEqual(self.registry()[review_hold]["status"], "review-required")

    def test_restart_respects_persisted_backoff_and_retry_bound(self):
        task = "TASK-restart-bounded"
        attempt = "d-restart"
        start = datetime(2026, 7, 17, tzinfo=UTC)
        self.write_registry({task: self.entry(task, at=start.isoformat(), attempt=attempt)})
        due_offsets = [0, 2, 6, 14, 30]
        for offset in due_offsets:
            result = self.action(
                "--authorize-delivery",
                task,
                "--attempt-id",
                attempt,
                "--now",
                (start + timedelta(seconds=offset)).isoformat(),
            )
            self.assertTrue(result["authorized"])
        exhausted = self.action(
            "--authorize-delivery",
            task,
            "--attempt-id",
            attempt,
            "--now",
            (start + timedelta(hours=1)).isoformat(),
        )
        self.assertEqual(exhausted["reason"], "retry-budget-exhausted")
        entry = self.registry()[task]
        self.assertEqual(entry["delivery_attempt_count"], 5)
        self.assertEqual(entry["delivery_retry_count"], 4)


class PromptInjectionTests(DeliveryFixture):
    def test_nudge_prepends_claim_and_duplicate_is_noop(self):
        task = "TASK-prompt-claim"
        at = "2026-07-17T00:00:00+00:00"
        attempt = "d-prompt"
        self.write_registry({task: self.entry(task, at=at, attempt=attempt)})
        (self.root / "bin").mkdir()
        (self.root / "shared").mkdir()
        (self.root / "departments/coding/inbox").mkdir(parents=True)
        (self.root / "shared/lead-windows.sh").write_text(
            'runtime_window_name() { printf "%s\\n" "$1"; }\n', encoding="utf-8"
        )
        wrapper = self.root / "bin/registry-reconciler.sh"
        wrapper.write_text(
            f'#!/bin/bash\nexec "{sys.executable}" "{RECONCILER}" "$@"\n', encoding="utf-8"
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        tmux_log = self.root / "tmux.log"
        fake_tmux = self.root / "fake-tmux"
        fake_tmux.write_text(
            "#!/bin/bash\n"
            "case \"$1\" in\n"
            "  has-session) exit 0 ;;\n"
            "  list-windows) echo gpt-codex; exit 0 ;;\n"
            "  send-keys) printf '%s\\n' \"$*\" >> \"$TMUX_LOG\"; exit 0 ;;\n"
            "esac\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)
        packet = self.root / f"departments/coding/inbox/{task}.md"
        packet.write_text(
            "---\n"
            f"id: {task}\n"
            "to_model: gpt-codex\n"
            "specialist: systems-engineer\n"
            "return_artifact: _state/result.md\n"
            "---\n",
            encoding="utf-8",
        )
        env = {
            **self.env,
            "TMUX_BIN": str(fake_tmux),
            "TMUX_LOG": str(tmux_log),
            "SQUAD_SESSION": "test",
            "DELIVERY_NOW": at,
        }
        first = subprocess.run(
            ["bash", str(NUDGE), str(packet)], env=env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        logged = tmux_log.read_text()
        claim_marker = f"FIRST ACTION REQUIRED: run bash '{self.root}/bin/claim-task.sh' '{task}' '{attempt}'"
        self.assertIn(claim_marker, logged)
        self.assertLess(logged.index("FIRST ACTION REQUIRED"), logged.index("TASK READY"))

        duplicate = subprocess.run(
            ["bash", str(NUDGE), str(packet)], env=env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(duplicate.returncode, 3)
        self.assertEqual(tmux_log.read_text().count("FIRST ACTION REQUIRED"), 1)


if __name__ == "__main__":
    unittest.main()
