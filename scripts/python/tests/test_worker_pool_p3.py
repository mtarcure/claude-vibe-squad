"""Hermetic P3 resource, review-debt, admission, and AIMD guard tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
PYTHON_DIR = REPO / "scripts/python"
RECONCILER = PYTHON_DIR / "registry_reconciler.py"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from worker_pool_policy import (  # noqa: E402
    PolicyError,
    default_worker_targets,
    load_worker_pool_policy,
    supervisor_aimd,
)


class WorkerPoolP3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="worker-pool-p3-")
        self.root = Path(self.temp.name)
        (self.root / "_state").mkdir()
        (self.root / "shared").mkdir()
        self.tsv = self.root / "shared/worker-pool-policy.tsv"
        self.markdown = self.root / "shared/worker-pool-policy.md"
        self.base_tsv = (REPO / "shared/worker-pool-policy.tsv").read_text(encoding="utf-8")
        self.policy = self.write_policy(self.base_tsv)
        self.env = {
            **os.environ,
            "VAULT_ROOT": str(self.root),
            "STATE_DIR": str(self.root / "_state"),
            "SQUAD_WORKER_POOL_ENABLED": "1",
            "SQUAD_WORKER_POOL_GUARDS_ENABLED": "1",
            "SQUAD_WORKER_POOL_POLICY_REVIEW_STATE": "approved",
            "SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256": self.policy.policy_sha256,
            "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux",
            "SQUAD_SESSION": "none",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.now = datetime(2026, 7, 19, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_policy(self, tsv_text: str, *, status: str = "needs_review"):
        self.tsv.write_text(tsv_text, encoding="utf-8")
        tsv_hash = hashlib.sha256(self.tsv.read_bytes()).hexdigest()
        self.markdown.write_text(
            "---\n"
            "schema_version: worker-pool-policy/v1\n"
            "policy_id: p3-test-policy\n"
            f"status: {status}\n"
            "author_family: openai\n"
            "review_model: claude\n"
            "policy_tsv: shared/worker-pool-policy.tsv\n"
            f"policy_tsv_sha256: {tsv_hash}\n"
            "---\n\n# Hermetic reviewed policy fixture\n",
            encoding="utf-8",
        )
        return load_worker_pool_policy(self.markdown, require_approved=status == "approved")

    def entry(
        self,
        task_id: str,
        *,
        lane: str = "gpt-codex",
        at: datetime | None = None,
        priority: str = "normal",
        write_scope: list[str] | None = None,
    ) -> dict:
        timestamp = (at or self.now).isoformat()
        return {
            "compatibility_namespace": "coding",
            "source_namespace": "coding",
            "specialist": "systems-engineer",
            "to_model": lane,
            "mandatory_review": "true",
            "review_model": "claude" if lane == "gpt-codex" else "gpt-codex",
            "return_artifact": f"_state/{task_id}.md",
            "write_scope": [] if write_scope is None else write_scope,
            "status": "in-flight",
            "dispatched_at": timestamp,
            "delivery_state": "queued",
            "delivery_attempt_id": f"d-{task_id}",
            "delivery_generation": 1,
            "delivery_lane": lane,
            "delivery_attempt_count": 0,
            "delivery_retry_count": 0,
            "delivery_max_attempts": 5,
            "delivery_next_attempt_at": timestamp,
            "priority_class": priority,
            "enqueued_at": timestamp,
            "delivery_history": [],
        }

    def active_entry(
        self, task_id: str, worker_id: str, lane: str, *, write_scope: list[str] | None = None
    ) -> dict:
        entry = self.entry(task_id, lane=lane, write_scope=write_scope)
        entry.update(
            delivery_state="in-progress",
            delivery_worker_id=worker_id,
            worker_epoch=f"epoch-{worker_id}",
            lease_generation=1,
            lease_expires_at=(self.now + timedelta(minutes=5)).isoformat(),
            heartbeat_observed_at=self.now.isoformat(),
            worker_assignment_state="in-progress",
        )
        return entry

    def debt_entry(self, task_id: str, family: str) -> dict:
        entry = self.entry(task_id)
        entry.update(
            status="review-required",
            delivery_state="terminal",
            verification_contract={"author_family": family},
        )
        return entry

    def worker(
        self, worker_id: str, lane: str, *, subagents: int = 0,
        available: bool = True, lead_id: str | None = None,
    ) -> dict:
        return {
            "worker_id": worker_id,
            "worker_epoch": f"epoch-{worker_id}",
            "lane": lane,
            "heartbeat_observed_at": self.now.isoformat(),
            "available": available,
            "lead_id": lead_id or worker_id,
            "subagent_count": subagents,
        }

    def write_registry(self, entries: dict[str, dict]) -> None:
        (self.root / "_state/active-tasks.json").write_text(
            json.dumps(entries, indent=2) + "\n", encoding="utf-8"
        )

    def registry(self) -> dict:
        return json.loads((self.root / "_state/active-tasks.json").read_text())

    @staticmethod
    def healthy_host(*, used: int = 1000, memory: bool = False, swap: bool = False, compressor: bool = False) -> dict:
        return {
            "used_memory_mib": used,
            "memory_pressure": memory,
            "swap_active": swap,
            "compressor_pressure": compressor,
        }

    @staticmethod
    def ready_providers(**overrides: str) -> dict[str, str]:
        states = {lane: "ready" for lane in ("claude", "gpt-codex", "gemini", "kimi")}
        states.update(overrides)
        return states

    @staticmethod
    def empty_provider_usage(**overrides: dict[str, int]) -> dict[str, dict[str, int]]:
        usage = {
            lane: {"spent_microusd": 0, "active_requests": 0, "requests_last_minute": 0}
            for lane in ("claude", "gpt-codex", "gemini", "kimi")
        }
        usage.update(overrides)
        return usage

    def scan(
        self,
        workers: list[dict],
        *,
        host: dict | None = None,
        providers: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        result = subprocess.run(
            [
                sys.executable,
                str(RECONCILER),
                "--schedule-workers-json", json.dumps(workers),
                "--worker-policy", str(self.markdown),
                "--host-snapshot-json", json.dumps(host or self.healthy_host()),
                "--provider-states-json", json.dumps(providers or self.ready_providers()),
                "--provider-usage-json", json.dumps(self.empty_provider_usage()),
                "--scan-interval-seconds", "5",
                "--now", self.now.isoformat(),
            ],
            env=env or self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f"scan failed ({result.returncode}): {result.stderr}\n{result.stdout}")
        return result, json.loads(result.stdout) if result.returncode == 0 else None

    def test_policy_cross_hash_strict_keys_and_cross_field_bounds(self):
        self.assertEqual(self.policy.global_worker_cap, 6)
        self.assertEqual(self.policy.status, "needs_review")
        self.assertEqual(self.policy.lanes["gpt-codex"].max_workers, 2)
        self.assertEqual(
            default_worker_targets(self.policy),
            {"claude": 1, "gpt-codex": 1, "gemini": 1, "kimi": 1},
        )

        source_lines = self.base_tsv.splitlines()
        cases = {
            "missing": "\n".join(source_lines[:-1]) + "\n",
            "duplicate": self.base_tsv.replace("\tlane\tkimi\t", "\tlane\tgemini\t"),
            "unknown": self.base_tsv.replace("\tlane\tkimi\t", "\tlane\tother\t"),
            "invalid-bounds": self.base_tsv.replace(
                "\tlane\tgpt-codex\t1\t1\t2\t", "\tlane\tgpt-codex\t2\t1\t2\t"
            ),
            "invalid-timeouts": self.base_tsv.replace(
                "\t14336\t5\t300\t30\t600\t3\t", "\t14336\t31\t300\t30\t600\t3\t"
            ),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(PolicyError):
                    self.write_policy(text)

        self.write_policy(self.base_tsv)
        self.tsv.write_text(self.base_tsv + "# mutation\n", encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "hash"):
            load_worker_pool_policy(self.markdown)

        pending = self.write_policy(self.base_tsv, status="needs_review")
        self.assertEqual(pending.status, "needs_review")
        with self.assertRaisesRegex(PolicyError, "not independently approved"):
            load_worker_pool_policy(self.markdown, require_approved=True)

    def test_policy_approval_hash_is_pinned_by_scheduler(self):
        self.write_registry({"TASK-one": self.entry("TASK-one")})
        unreviewed_env = dict(self.env)
        unreviewed_env.pop("SQUAD_WORKER_POOL_POLICY_REVIEW_STATE")
        result, _ = self.scan(
            [self.worker("codex-1", "gpt-codex")], env=unreviewed_env, check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("review is not approved", result.stderr)
        bad_env = dict(self.env)
        bad_env["SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256"] = "0" * 64
        result, _ = self.scan([self.worker("codex-1", "gpt-codex")], env=bad_env, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not approved", result.stderr)

    def test_queue_cap_includes_not_due_and_never_spills_or_consumes_attempts(self):
        entries = {}
        for index in range(7):
            at = self.now + timedelta(hours=1) if index == 0 else self.now
            entries[f"TASK-{index}"] = self.entry(
                f"TASK-{index}", at=at, priority="urgent" if index == 0 else "normal"
            )
        self.write_registry(entries)
        _, result = self.scan([self.worker("claude-1", "claude")])
        self.assertEqual(result["new_assignments"], [])
        deferred = {item["task_id"]: item for item in result["deferred"]}
        self.assertEqual(deferred["TASK-6"]["reason"], "lane-queue-depth-cap")
        self.assertEqual(deferred["TASK-6"]["stage"], "queue")
        stored = self.registry()
        self.assertEqual(stored["TASK-0"]["worker_queue_state"], "admitted")
        for entry in stored.values():
            self.assertEqual(entry["delivery_attempt_count"], 0)
            self.assertIsNone(entry.get("delivery_worker_id"))
            self.assertEqual(entry["delivery_lane"], "gpt-codex")

        review = self.entry("TASK-review", lane="claude", priority="low")
        review.update(
            specialist="large-context-analyst",
            review_subject_author_family="openai",
            write_scope=[],
        )
        full_lane = {
            f"TASK-author-{index}": self.entry(
                f"TASK-author-{index}", lane="claude", priority="urgent"
            )
            for index in range(6)
        }
        full_lane["TASK-review"] = review
        self.write_registry(full_lane)
        _, prioritized = self.scan([])
        by_task = {item["task_id"]: item for item in prioritized["deferred"]}
        self.assertEqual(by_task["TASK-review"]["stage"], "lease")
        self.assertEqual(by_task["TASK-review"]["reason"], "lane-capacity-unavailable")
        queue_deferred = [
            item for item in prioritized["deferred"]
            if item["stage"] == "queue" and item["reason"] == "lane-queue-depth-cap"
        ]
        self.assertEqual(len(queue_deferred), 1)
        self.assertTrue(queue_deferred[0]["task_id"].startswith("TASK-author-"))
        for entry in self.registry().values():
            self.assertEqual(entry["delivery_attempt_count"], 0)
            self.assertEqual(entry["delivery_lane"], "claude")

    def test_memory_projection_boundary_and_pressure_signals_defer(self):
        cases = (
            (self.healthy_host(used=12736), "projected-memory-high-water"),
            (self.healthy_host(memory=True), "memory-pressure"),
            (self.healthy_host(swap=True), "swap-active"),
            (self.healthy_host(compressor=True), "compressor-pressure"),
        )
        for host, reason in cases:
            with self.subTest(reason=reason):
                self.write_registry({"TASK-memory": self.entry("TASK-memory")})
                _, result = self.scan(
                    [self.worker("codex-1", "gpt-codex")], host=host
                )
                self.assertEqual(result["new_assignments"], [])
                self.assertEqual(result["deferred"][0]["reason"], reason)
                self.assertEqual(self.registry()["TASK-memory"]["delivery_attempt_count"], 0)

    def test_provider_state_and_subagent_cap_defer(self):
        self.write_registry({"TASK-provider": self.entry("TASK-provider")})
        _, blocked = self.scan(
            [self.worker("codex-1", "gpt-codex")],
            providers=self.ready_providers(**{"gpt-codex": "blocked"}),
        )
        self.assertEqual(blocked["deferred"][0]["reason"], "provider-blocked")

        task = self.entry("TASK-subagents")
        task["requested_subagent_count"] = 2
        self.write_registry({"TASK-subagents": task})
        _, capped = self.scan([self.worker("codex-1", "gpt-codex", subagents=3)])
        self.assertEqual(capped["deferred"][0]["reason"], "per-lead-subagent-cap")

        aggregate = self.entry("TASK-aggregate")
        aggregate["requested_subagent_count"] = 1
        self.write_registry({"TASK-aggregate": aggregate})
        _, aggregate_capped = self.scan([
            self.worker("codex-1", "gpt-codex", subagents=2, lead_id="lead-a"),
            self.worker("codex-2", "gpt-codex", subagents=2, lead_id="lead-a"),
        ])
        self.assertEqual(
            aggregate_capped["deferred"][0]["reason"], "per-lead-subagent-cap"
        )

    def test_global_lane_and_reserved_review_capacity_guards(self):
        lane_entries = {
            "ACTIVE-g1": self.active_entry("ACTIVE-g1", "gpt-1", "gpt-codex"),
            "ACTIVE-g2": self.active_entry("ACTIVE-g2", "gpt-2", "gpt-codex"),
            "TASK-lane": self.entry("TASK-lane"),
        }
        self.write_registry(lane_entries)
        workers = [
            self.worker("gpt-1", "gpt-codex"), self.worker("gpt-2", "gpt-codex"),
            self.worker("gpt-3", "gpt-codex"),
        ]
        _, lane_result = self.scan(workers)
        self.assertEqual(
            next(item for item in lane_result["deferred"] if item["task_id"] == "TASK-lane")["reason"],
            "lane-worker-cap",
        )

        entries = {
            "ACTIVE-c1": self.active_entry("ACTIVE-c1", "c1", "claude"),
            "ACTIVE-c2": self.active_entry("ACTIVE-c2", "c2", "claude"),
            "ACTIVE-g1": self.active_entry("ACTIVE-g1", "g1", "gpt-codex"),
            "ACTIVE-g2": self.active_entry("ACTIVE-g2", "g2", "gpt-codex"),
            "ACTIVE-m1": self.active_entry("ACTIVE-m1", "m1", "gemini"),
            "TASK-author": self.entry("TASK-author", lane="kimi"),
        }
        self.write_registry(entries)
        workers = [
            self.worker("c1", "claude"), self.worker("c2", "claude"),
            self.worker("g1", "gpt-codex"), self.worker("g2", "gpt-codex"),
            self.worker("m1", "gemini"), self.worker("k1", "kimi"),
        ]
        _, reserved = self.scan(workers)
        self.assertEqual(
            next(item for item in reserved["deferred"] if item["task_id"] == "TASK-author")["reason"],
            "reserved-review-capacity",
        )

        review = self.entry("TASK-review", lane="kimi")
        review.update(
            specialist="large-context-analyst",
            review_subject_author_family="openai",
            write_scope=[],
        )
        entries.pop("TASK-author")
        entries["TASK-review"] = review
        self.write_registry(entries)
        _, review_result = self.scan(workers)
        self.assertEqual(review_result["new_assignments"][0]["task_id"], "TASK-review")

        entries["ACTIVE-k1"] = self.active_entry("ACTIVE-k1", "k1", "kimi")
        entries["TASK-review"] = review
        self.write_registry(entries)
        workers.append(self.worker("k2", "kimi"))
        _, global_result = self.scan(workers)
        self.assertEqual(
            next(item for item in global_result["deferred"] if item["task_id"] == "TASK-review")["reason"],
            "global-worker-cap",
        )

    def test_review_debt_backpressures_author_but_not_cross_family_reviewer(self):
        author = self.entry("TASK-author")
        review = self.entry("TASK-review", lane="claude", priority="urgent")
        review.update(
            specialist="large-context-analyst",
            review_subject_author_family="openai",
            write_scope=[],
        )
        entries = {
            "TASK-author": author,
            "TASK-review": review,
            "DEBT-1": self.debt_entry("DEBT-1", "openai"),
            "DEBT-2": self.debt_entry("DEBT-2", "openai"),
        }
        self.write_registry(entries)
        _, result = self.scan([
            self.worker("codex-1", "gpt-codex"), self.worker("claude-1", "claude")
        ])
        self.assertEqual(result["new_assignments"][0]["task_id"], "TASK-review")
        self.assertEqual(
            next(item for item in result["deferred"] if item["task_id"] == "TASK-author")["reason"],
            "review-debt-cap",
        )

    def test_write_scope_and_review_anti_affinity_guards(self):
        active = self.active_entry(
            "ACTIVE-write", "claude-1", "claude", write_scope=["scripts"]
        )
        candidate = self.entry("TASK-write", write_scope=["scripts/python"])
        self.write_registry({"ACTIVE-write": active, "TASK-write": candidate})
        _, result = self.scan([
            self.worker("claude-1", "claude"), self.worker("codex-1", "gpt-codex")
        ])
        self.assertEqual(result["deferred"][0]["reason"], "write-scope-conflict")

        same_family = self.entry("TASK-same-review", lane="gpt-codex")
        same_family.update(
            specialist="large-context-analyst",
            review_subject_author_family="openai",
            write_scope=[],
        )
        self.write_registry({"TASK-same-review": same_family})
        _, rejected = self.scan([self.worker("codex-1", "gpt-codex")])
        self.assertEqual(rejected["deferred"][0]["reason"], "review-anti-affinity")

        missing_subject = self.entry("TASK-untyped-review", lane="claude")
        missing_subject.update(specialist="code-reviewer", write_scope=[])
        self.write_registry({"TASK-untyped-review": missing_subject})
        _, untyped = self.scan([self.worker("claude-1", "claude")])
        self.assertEqual(
            untyped["deferred"][0]["reason"], "review-subject-family-required"
        )

    def test_policy_timeouts_are_enforced_and_flag_off_is_exact_p1(self):
        self.write_registry({"TASK-timeout": self.entry("TASK-timeout")})
        _, guarded = self.scan([self.worker("codex-1", "gpt-codex")])
        assignment = guarded["new_assignments"][0]
        self.assertEqual(
            assignment["lease_expires_at"],
            (self.now + timedelta(seconds=300)).isoformat(),
        )
        self.assertEqual(guarded["next_scan_after_seconds"], 5)

        legacy_env = dict(self.env)
        legacy_env.pop("SQUAD_WORKER_POOL_GUARDS_ENABLED")
        legacy_env.pop("SQUAD_WORKER_POOL_POLICY_REVIEW_STATE")
        legacy_env.pop("SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256")
        self.write_registry({"TASK-legacy": self.entry("TASK-legacy")})
        result = subprocess.run(
            [
                sys.executable, str(RECONCILER),
                "--schedule-workers-json", json.dumps([self.worker("codex-1", "gpt-codex")]),
                "--lease-seconds", "17", "--heartbeat-max-age-seconds", "9",
                "--now", self.now.isoformat(),
            ],
            env=legacy_env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        legacy = json.loads(result.stdout)
        self.assertEqual(
            set(legacy),
            {"scan_authoritative", "new_assignments", "work", "surfaced", "nudges"},
        )
        self.assertEqual(
            legacy["new_assignments"][0]["lease_expires_at"],
            (self.now + timedelta(seconds=17)).isoformat(),
        )

    def test_metered_kimi_budget_and_provider_capacity_are_enforced(self):
        kimi = self.entry("TASK-kimi-budget", lane="kimi")
        self.write_registry({"TASK-kimi-budget": kimi})
        exhausted = self.empty_provider_usage(
            kimi={"spent_microusd": 1_000_000, "active_requests": 0,
                  "requests_last_minute": 0}
        )
        result = subprocess.run(
            [
                sys.executable, str(RECONCILER),
                "--schedule-workers-json", json.dumps([self.worker("kimi-1", "kimi")]),
                "--worker-policy", str(self.markdown),
                "--host-snapshot-json", json.dumps(self.healthy_host()),
                "--provider-states-json", json.dumps(self.ready_providers()),
                "--provider-usage-json", json.dumps(exhausted),
                "--scan-interval-seconds", "5", "--now", self.now.isoformat(),
            ], env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["deferred"][0]["reason"],
            "provider-budget-exhausted",
        )

        self.write_registry({"TASK-cap": self.entry("TASK-cap", lane="gpt-codex")})
        capped = self.empty_provider_usage(
            **{"gpt-codex": {"spent_microusd": 0, "active_requests": 2,
                              "requests_last_minute": 0}}
        )
        # Exercise the explicit capacity snapshot through the CLI.
        result = subprocess.run(
            [sys.executable, str(RECONCILER), "--schedule-workers-json",
             json.dumps([self.worker("codex-1", "gpt-codex")]),
             "--worker-policy", str(self.markdown), "--host-snapshot-json",
             json.dumps(self.healthy_host()), "--provider-states-json",
             json.dumps(self.ready_providers()), "--provider-usage-json",
             json.dumps(capped), "--scan-interval-seconds", "5", "--now",
             self.now.isoformat()],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["deferred"][0]["reason"],
            "provider-concurrency-cap",
        )

        self.write_registry({"TASK-rate": self.entry("TASK-rate", lane="gpt-codex")})
        rate_limited = self.empty_provider_usage(
            **{"gpt-codex": {"spent_microusd": 0, "active_requests": 0,
                              "requests_last_minute": 20}}
        )
        result = subprocess.run(
            [sys.executable, str(RECONCILER), "--schedule-workers-json",
             json.dumps([self.worker("codex-1", "gpt-codex")]),
             "--worker-policy", str(self.markdown), "--host-snapshot-json",
             json.dumps(self.healthy_host()), "--provider-states-json",
             json.dumps(self.ready_providers()), "--provider-usage-json",
             json.dumps(rate_limited), "--scan-interval-seconds", "5", "--now",
             self.now.isoformat()],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["deferred"][0]["reason"],
            "provider-rate-limit",
        )

    def test_metered_reservation_is_registry_atomic_and_survives_consumer_crash(self):
        first = self.entry("TASK-kimi-first", lane="kimi")
        first["estimated_cost_microusd"] = 900_000
        self.write_registry({"TASK-kimi-first": first})
        _, assigned = self.scan([self.worker("kimi-1", "kimi")])
        self.assertEqual(assigned["new_assignments"][0]["task_id"], "TASK-kimi-first")
        registry = self.registry()
        self.assertEqual(
            registry["TASK-kimi-first"]["provider_cost_reserved_microusd"], 900_000
        )

        registry["TASK-kimi-first"].update(status="complete", delivery_state="terminal")
        second = self.entry("TASK-kimi-second", lane="kimi")
        second["estimated_cost_microusd"] = 200_000
        registry["TASK-kimi-second"] = second
        self.write_registry(registry)
        _, denied = self.scan([self.worker("kimi-2", "kimi")])
        self.assertEqual(denied["deferred"][0]["reason"], "provider-budget-exhausted")

    def test_claimed_assignment_stops_scan_consumer_redelivery(self):
        self.write_registry({"TASK-claim": self.entry("TASK-claim")})
        _, first = self.scan([self.worker("codex-1", "gpt-codex")])
        self.assertEqual([item["task_id"] for item in first["work"]], ["TASK-claim"])
        registry = self.registry()
        registry["TASK-claim"]["delivery_state"] = "claimed"
        self.write_registry(registry)
        _, second = self.scan([self.worker("codex-1", "gpt-codex")])
        self.assertEqual(second["work"], [])

    def test_supervisor_aimd_adds_one_drains_without_killing_and_handles_global_overflow(self):
        providers = self.ready_providers()
        current = {"claude": 1, "gpt-codex": 1, "gemini": 1, "kimi": 1}
        stable = {lane: 3 for lane in current}
        growth = supervisor_aimd(
            self.policy,
            current_targets=current,
            stable_scans=stable,
            pressure=False,
            provider_states=providers,
            workers=[],
        )
        self.assertEqual(growth["targets"]["claude"], 2)
        self.assertEqual(growth["targets"]["gpt-codex"], 2)
        self.assertTrue(all(growth["targets"][lane] - current[lane] <= 1 for lane in current))
        cli = subprocess.run(
            [
                sys.executable, str(RECONCILER),
                "--plan-worker-targets-json", json.dumps({
                    "current_targets": current,
                    "stable_scans": stable,
                    "pressure": False,
                    "workers": [],
                }),
                "--worker-policy", str(self.markdown),
                "--provider-states-json", json.dumps(providers),
            ],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["default_targets"], current)

        pressure_current = {"claude": 2, "gpt-codex": 2, "gemini": 1, "kimi": 1}
        workers = [
            {"worker_id": "c1", "lane": "claude", "leased": True},
            {"worker_id": "c2", "lane": "claude", "leased": False},
            {"worker_id": "g1", "lane": "gpt-codex", "leased": True},
            {"worker_id": "g2", "lane": "gpt-codex", "leased": False},
        ]
        drained = supervisor_aimd(
            self.policy,
            current_targets=pressure_current,
            stable_scans={lane: 0 for lane in current},
            pressure=True,
            provider_states=providers,
            workers=workers,
        )
        self.assertEqual(drained["targets"]["claude"], 1)
        self.assertTrue(all(not action["kill"] for action in drained["actions"]))
        self.assertIn("drain-idle", {action["action"] for action in drained["actions"]})

        already_at_target = supervisor_aimd(
            self.policy,
            current_targets=pressure_current,
            stable_scans={lane: 0 for lane in current},
            pressure=True,
            provider_states=providers,
            workers=[{"worker_id": "c1", "lane": "claude", "leased": True}],
        )
        self.assertEqual(already_at_target["targets"]["claude"], 1)
        self.assertEqual(already_at_target["actions"], [])

        cap_five = self.base_tsv.replace("\t0\t0\t6\t1\t16384\t", "\t0\t0\t5\t1\t16384\t")
        policy_five = self.write_policy(cap_five)
        overflow = supervisor_aimd(
            policy_five,
            current_targets=pressure_current,
            stable_scans={lane: 0 for lane in current},
            pressure=False,
            provider_states=providers,
            workers=[
                {"worker_id": "g1", "lane": "gpt-codex", "leased": True},
                {"worker_id": "g2", "lane": "gpt-codex", "leased": True},
            ],
        )
        self.assertEqual(sum(overflow["targets"].values()), 5)
        self.assertEqual(overflow["targets"]["gpt-codex"], 1)
        self.assertEqual(overflow["actions"][0]["action"], "mark-draining")
        self.assertFalse(overflow["actions"][0]["kill"])


if __name__ == "__main__":
    unittest.main()
