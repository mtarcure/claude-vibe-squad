#!/usr/bin/env python3
"""Tests for the F5 coordination primitive: global delegation lineage cap,
authority intersection, and the checkpoint/continuation state machine.

Written before scripts/python/delegation_lineage.py and
scripts/python/coordination.py exist (TDD RED first).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import delegation_lineage as lineage_mod  # noqa: E402
from delegation_lineage import (  # noqa: E402
    DelegationAuthority,
    DelegationDenied,
    DelegationLineage,
    LineageBudget,
    advance,
    authority_sha256,
    intersect_authority,
    lineage_sha256,
    root_lineage,
)
import coordination as coord_mod  # noqa: E402
from coordination import CoordinationStore  # noqa: E402


DEFAULT_BUDGET = LineageBudget(max_depth=1, max_children_per_delegation=1, max_total_delegations=3)


def _authority(
    *,
    read_paths=(),
    write_paths=(),
    external_targets=(),
    data_class="internal",
    resources=(),
) -> DelegationAuthority:
    return DelegationAuthority(
        read_paths=frozenset(read_paths),
        write_paths=frozenset(write_paths),
        external_targets=frozenset(external_targets),
        data_class=data_class,
        resources=frozenset(resources),
    )


class MutableClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _result_hash(result: dict[str, Any]) -> str:
    """The one true canonicalization coordination.py itself uses to verify a
    settled result's hash -- computed here so tests assert against genuine
    values, not the placeholder "a"*64 the pre-fix code silently accepted
    without ever checking it against the actual result payload."""

    return coord_mod._sha256_text(coord_mod._canonical_json(result))


# --------------------------------------------------------------------------- #
# delegation_lineage.py — global lineage cap
# --------------------------------------------------------------------------- #
class LineageTests(unittest.TestCase):
    def test_root_lineage_seeds_and_includes_requester_in_visited(self) -> None:
        root = root_lineage("TASK-P", "backend-engineer")
        self.assertEqual(root.originating_parent, "TASK-P")
        self.assertEqual(root.chain_depth, 0)
        self.assertEqual(root.visited_specialists, ("backend-engineer",))
        self.assertEqual(root.total_delegations, 0)

    def test_advance_rejects_depth_exceeded(self) -> None:
        root = root_lineage("TASK-P", "backend-engineer")
        hop1 = advance(root, "database-engineer", DEFAULT_BUDGET)
        self.assertEqual(hop1.chain_depth, 1)
        with self.assertRaisesRegex(DelegationDenied, "depth"):
            advance(hop1, "security-analyst", DEFAULT_BUDGET)

    def test_advance_rejects_cycle_revisit(self) -> None:
        root = root_lineage("TASK-P", "backend-engineer")
        budget = LineageBudget(max_depth=5, max_children_per_delegation=1, max_total_delegations=10)
        with self.assertRaisesRegex(DelegationDenied, "cycle"):
            advance(root, "backend-engineer", budget)
        hop1 = advance(root, "database-engineer", budget)
        with self.assertRaisesRegex(DelegationDenied, "cycle"):
            advance(hop1, "database-engineer", budget)

    def test_advance_rejects_global_budget_exhausted(self) -> None:
        root = root_lineage("TASK-P", "s0")
        budget = LineageBudget(max_depth=10, max_children_per_delegation=1, max_total_delegations=2)
        hop1 = advance(root, "s1", budget)
        hop2 = advance(hop1, "s2", budget)
        with self.assertRaisesRegex(DelegationDenied, "budget"):
            advance(hop2, "s3", budget)

    def test_global_cap_does_not_reset_across_simulated_lane_hops(self) -> None:
        """The exact regression this task exists to fix: the OLD per-parent
        cap reset every time a cross-lane hop dispatched a fresh ordinary
        task with its own budget. Here the SAME lineage is carried across
        two conceptual hops (simulating a JSON round-trip through a
        checkpoint -> Chrono -> child -> continuation boundary), and the
        cap must still bite on hop 2 even though hop 2's "parent" (the
        child task from hop 1) is a different task than the root."""
        budget = LineageBudget(max_depth=2, max_children_per_delegation=1, max_total_delegations=1)
        root = root_lineage("TASK-ROOT", "backend-engineer")
        hop1 = advance(root, "database-engineer", budget)
        self.assertEqual(hop1.total_delegations, 1)
        # Round-trip through JSON exactly as it would cross a process/lane boundary.
        carried = lineage_mod.lineage_from_dict(json.loads(json.dumps(lineage_mod.lineage_to_dict(hop1))))
        self.assertEqual(carried, hop1)
        # hop1's own delegation, from a DIFFERENT task_id (its own child task,
        # not the root), must still be denied: total_delegations is GLOBAL,
        # not reset because the acting parent changed.
        with self.assertRaisesRegex(DelegationDenied, "budget"):
            advance(carried, "security-analyst", budget)

    def test_lineage_from_dict_rejects_a_forged_negative_lineage(self) -> None:
        """REJECT defect 1 (HIGH), repro 2: codex admitted a JSON lineage with
        chain_depth=-100 and total_delegations=-100 under max_depth=1 /
        max_total_delegations=0, then persisted it as -99/-99. Strict
        validation must reject this at deserialization, before it can ever
        reach advance() or a cap check."""
        forged = {
            "originating_parent": "TASK-P",
            "chain_depth": -100,
            "visited_specialists": ["backend-engineer"],
            "total_delegations": -100,
        }
        with self.assertRaises(DelegationDenied):
            lineage_mod.lineage_from_dict(forged)

    def test_lineage_from_dict_rejects_inconsistent_depth_and_visited_length(self) -> None:
        # A structurally-forged lineage: non-negative fields individually,
        # but chain_depth does not match len(visited_specialists) - 1, which
        # can never happen for anything produced by root_lineage()/advance().
        forged = {
            "originating_parent": "TASK-P",
            "chain_depth": 0,
            "visited_specialists": ["backend-engineer", "database-engineer", "security-analyst"],
            "total_delegations": 0,
        }
        with self.assertRaises(DelegationDenied):
            lineage_mod.lineage_from_dict(forged)

    def test_lineage_sha256_detects_tamper(self) -> None:
        root = root_lineage("TASK-P", "backend-engineer")
        digest = lineage_sha256(root)
        tampered = DelegationLineage(
            originating_parent=root.originating_parent,
            chain_depth=root.chain_depth,
            visited_specialists=root.visited_specialists,
            total_delegations=root.total_delegations + 1,  # silently bumped
        )
        self.assertNotEqual(lineage_sha256(tampered), digest)


# --------------------------------------------------------------------------- #
# delegation_lineage.py — authority intersection (no escalation)
# --------------------------------------------------------------------------- #
class AuthorityTests(unittest.TestCase):
    def test_intersection_never_exceeds_any_single_input(self) -> None:
        parent = _authority(read_paths=("/repo/a", "/repo/b"), resources=(("git_refs", "refs/heads/v2"),), data_class="internal")
        requester = _authority(read_paths=("/repo/a",), resources=(("git_refs", "refs/heads/v2"),), data_class="internal")
        # requester attempts to REQUEST more than it or the parent hold.
        requested_scope = _authority(
            read_paths=("/repo/a", "/repo/b", "/repo/SECRET"),
            external_targets=("https://evil.example",),
            resources=(("git_refs", "refs/heads/v2"), ("credential_broker", "anything")),
            data_class="restricted",
        )
        target_safety_policy = _authority(read_paths=("/repo/a", "/repo/b"), resources=(("git_refs", "refs/heads/v2"),), data_class="internal")

        effective = intersect_authority(parent, requester, requested_scope, target_safety_policy)

        self.assertEqual(effective.read_paths, frozenset({"/repo/a"}))
        self.assertNotIn("/repo/SECRET", effective.read_paths)
        self.assertEqual(effective.external_targets, frozenset())
        self.assertNotIn(("credential_broker", "anything"), effective.resources)
        self.assertEqual(effective.resources, frozenset({("git_refs", "refs/heads/v2")}))
        # requested restricted, but requester/parent/target are only internal -> stays internal.
        self.assertEqual(effective.data_class, "internal")

    def test_write_paths_are_always_forced_empty(self) -> None:
        parent = _authority(write_paths=("/repo/a",))
        requester = _authority(write_paths=("/repo/a",))
        requested_scope = _authority(write_paths=("/repo/a",))
        target_safety_policy = _authority(write_paths=("/repo/a",))
        effective = intersect_authority(parent, requester, requested_scope, target_safety_policy)
        self.assertEqual(effective.write_paths, frozenset())

    def test_data_class_takes_the_most_restrictive_rank(self) -> None:
        low = _authority(data_class="public")
        high = _authority(data_class="restricted")
        effective = intersect_authority(high, high, high, low)
        self.assertEqual(effective.data_class, "public")

    def test_authority_sha256_is_deterministic_and_order_independent(self) -> None:
        a = _authority(read_paths=("/repo/a", "/repo/b"), resources=(("git_refs", "x"), ("port", "9001")))
        b = _authority(read_paths=("/repo/b", "/repo/a"), resources=(("port", "9001"), ("git_refs", "x")))
        self.assertEqual(authority_sha256(a), authority_sha256(b))


# --------------------------------------------------------------------------- #
# coordination.py — checkpoint / continuation state machine
# --------------------------------------------------------------------------- #
class CoordinationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.clock = MutableClock(1_000.0)
        self.store = CoordinationStore(state_dir=self.state_dir, clock=self.clock)
        self.root = root_lineage("TASK-P", "backend-engineer")
        self.authority = _authority(read_paths=("/repo/a",), data_class="internal")

    def _checkpoint(self, **overrides: Any):
        kwargs: dict[str, Any] = dict(
            parent_task_id="TASK-P",
            parent_attempt_id="d-aaaa",
            parent_generation=1,
            requester_specialist="backend-engineer",
            target_specialist="database-engineer",
            question="What is the current schema for the users table?",
            lineage=self.root,
            budget=DEFAULT_BUDGET,
            authority=self.authority,
            ttl_seconds=300,
        )
        kwargs.update(overrides)
        return self.store.checkpoint(**kwargs)

    def test_checkpoint_denies_before_persisting_when_budget_exceeded(self) -> None:
        exhausted_budget = LineageBudget(max_depth=1, max_children_per_delegation=1, max_total_delegations=0)
        with self.assertRaises(DelegationDenied):
            self._checkpoint(budget=exhausted_budget)
        self.assertEqual(list(self.state_dir.glob("delegation-checkpoints/*.json")), [])

    def test_checkpoint_persists_atomically_before_dispatch(self) -> None:
        record = self._checkpoint()
        self.assertEqual(record["state"], "checkpointed")
        on_disk = self.store.get(record["delegation_id"])
        self.assertEqual(on_disk, record)

    def test_checkpoint_is_idempotent_for_the_same_identity(self) -> None:
        first = self._checkpoint()
        second = self._checkpoint()
        self.assertEqual(first["delegation_id"], second["delegation_id"])
        self.assertEqual(first, second)

    def test_different_authority_produces_a_different_identity(self) -> None:
        # Two genuinely distinct delegations in flight at once -> raise the
        # concurrency cap so this test isolates the identity claim, not
        # the (separately, directly tested) concurrency cap.
        roomy_budget = LineageBudget(max_depth=1, max_children_per_delegation=2, max_total_delegations=3)
        first = self._checkpoint(budget=roomy_budget)
        other_authority = _authority(read_paths=("/repo/a", "/repo/b"), data_class="internal")
        second = self._checkpoint(authority=other_authority, budget=roomy_budget)
        self.assertNotEqual(first["delegation_id"], second["delegation_id"])

    def test_dispatched_transition_is_idempotent(self) -> None:
        record = self._checkpoint()
        dispatched_once = self.store.dispatched(record["delegation_id"])
        dispatched_twice = self.store.dispatched(record["delegation_id"])
        self.assertEqual(dispatched_once["state"], "dispatched")
        self.assertEqual(dispatched_once, dispatched_twice)

    def test_inject_result_settles_and_is_idempotent(self) -> None:
        record = self._checkpoint()
        self.store.dispatched(record["delegation_id"])
        payload = {"status": "complete", "answer": "42"}
        first = self.store.inject_result(
            record["delegation_id"],
            parent_generation=1,
            result=payload,
            result_sha256=_result_hash(payload),
        )
        self.assertEqual(first["state"], "settled")
        # Re-inject the SAME result: no-op, not an error, not double-processed.
        second = self.store.inject_result(
            record["delegation_id"],
            parent_generation=1,
            result=payload,
            result_sha256=_result_hash(payload),
        )
        self.assertEqual(first, second)

    def test_inject_result_fences_a_different_result_for_settled_identity(self) -> None:
        record = self._checkpoint()
        self.store.dispatched(record["delegation_id"])
        settled_payload = {"status": "complete", "answer": "42"}
        self.store.inject_result(
            record["delegation_id"], parent_generation=1,
            result=settled_payload, result_sha256=_result_hash(settled_payload),
        )
        different_payload = {"status": "complete", "answer": "DIFFERENT"}
        with self.assertRaisesRegex(DelegationDenied, "duplicate|stale|mismatch"):
            self.store.inject_result(
                record["delegation_id"], parent_generation=1,
                result=different_payload, result_sha256=_result_hash(different_payload),
            )

    def test_inject_result_rejects_mismatched_parent_generation(self) -> None:
        record = self._checkpoint()
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                record["delegation_id"], parent_generation=2,
                result={"status": "complete", "answer": "42"}, result_sha256="a" * 64,
            )

    def test_inject_result_unknown_delegation_id_raises(self) -> None:
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                "does-not-exist", parent_generation=1,
                result={"status": "complete"}, result_sha256="a" * 64,
            )

    def test_ttl_expiry_marks_stale_and_fences_late_return(self) -> None:
        record = self._checkpoint(ttl_seconds=60)
        self.clock.value = 1_061.0
        expired = self.store.sweep_expired()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["state"], "stale")
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                record["delegation_id"], parent_generation=1,
                result={"status": "complete"}, result_sha256="a" * 64,
            )

    def test_sweep_expired_does_not_touch_settled_or_cancelled(self) -> None:
        settled = self._checkpoint(target_specialist="database-engineer", ttl_seconds=10)
        self.store.dispatched(settled["delegation_id"])
        settled_payload = {"status": "complete"}
        self.store.inject_result(
            settled["delegation_id"], parent_generation=1,
            result=settled_payload, result_sha256=_result_hash(settled_payload),
        )
        cancelled = self._checkpoint(target_specialist="security-analyst", ttl_seconds=10)
        self.store.cancel(cancelled["delegation_id"], reason="operator abort")
        self.clock.value = 1_500.0
        expired = self.store.sweep_expired()
        self.assertEqual(expired, [])
        self.assertEqual(self.store.get(settled["delegation_id"])["state"], "settled")
        self.assertEqual(self.store.get(cancelled["delegation_id"])["state"], "cancelled")

    def test_cancel_mid_chain_then_fences_late_result(self) -> None:
        record = self._checkpoint()
        self.store.dispatched(record["delegation_id"])
        cancelled = self.store.cancel(record["delegation_id"], reason="operator abort")
        self.assertEqual(cancelled["state"], "cancelled")
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                record["delegation_id"], parent_generation=1,
                result={"status": "complete"}, result_sha256="a" * 64,
            )

    def test_cancel_is_idempotent(self) -> None:
        record = self._checkpoint()
        first = self.store.cancel(record["delegation_id"], reason="a")
        second = self.store.cancel(record["delegation_id"], reason="b")
        self.assertEqual(first, second)

    def test_crash_recovery_resumes_correctly_from_a_fresh_store_instance(self) -> None:
        record = self._checkpoint()
        self.store.dispatched(record["delegation_id"])

        # Simulate a process crash: build a BRAND NEW store instance over the
        # same on-disk state directory, with no in-memory state carried over.
        recovered_store = CoordinationStore(state_dir=self.state_dir, clock=self.clock)
        recovered = recovered_store.get(record["delegation_id"])
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["state"], "dispatched")

        # Operations continue correctly from the recovered state.
        recovered_payload = {"status": "complete", "answer": "42"}
        settled = recovered_store.inject_result(
            record["delegation_id"], parent_generation=1,
            result=recovered_payload, result_sha256=_result_hash(recovered_payload),
        )
        self.assertEqual(settled["state"], "settled")

    def test_lineage_denial_from_the_uniform_tree_scenario_prevents_a_checkpoint(self) -> None:
        """End-to-end: the tree-fan-out my own 1425 review flagged must be
        denied at the coordination layer too, not just in raw lineage math."""
        budget = LineageBudget(max_depth=2, max_children_per_delegation=1, max_total_delegations=1)
        first = self._checkpoint(budget=budget)
        # T1 (the delegated child from hop 1) is now the running top-level
        # task and issues its OWN delegation call as its own acting parent
        # (parent_task_id="TASK-CHILD-1" below) -- the concurrency cap is
        # correctly scoped per acting parent, not per lineage root, so this
        # naturally isolates the test to the GLOBAL BUDGET regression.
        self.store.dispatched(first["delegation_id"])
        # first["lineage"] reflects the advanced (post-delegation) lineage.
        child_lineage = lineage_mod.lineage_from_dict(first["lineage"])
        with self.assertRaisesRegex(DelegationDenied, "budget"):
            self.store.checkpoint(
                parent_task_id="TASK-CHILD-1",  # a DIFFERENT acting parent than the root
                parent_attempt_id="d-bbbb",
                parent_generation=1,
                requester_specialist="database-engineer",
                target_specialist="security-analyst",
                question="Another bounded sub-question",
                lineage=child_lineage,
                budget=budget,
                authority=self.authority,
            )

    def test_concurrency_cap_blocks_a_second_simultaneous_delegation_from_the_same_acting_parent(self) -> None:
        budget = LineageBudget(max_depth=1, max_children_per_delegation=1, max_total_delegations=5)
        first = self._checkpoint(target_specialist="database-engineer", budget=budget)
        self.assertEqual(first["state"], "checkpointed")
        with self.assertRaisesRegex(DelegationDenied, "concurrency"):
            self._checkpoint(target_specialist="security-analyst", budget=budget)
        # Settling the first frees the slot for a genuinely new delegation.
        self.store.dispatched(first["delegation_id"])
        first_payload = {"status": "complete"}
        self.store.inject_result(
            first["delegation_id"], parent_generation=1,
            result=first_payload, result_sha256=_result_hash(first_payload),
        )
        second = self._checkpoint(target_specialist="security-analyst", budget=budget)
        self.assertEqual(second["state"], "checkpointed")

    def test_child_delegating_further_does_not_consume_its_ancestors_concurrency_slot(self) -> None:
        """The scoping-by-acting-parent fix: P's own outstanding delegation
        to T1 must NOT block T1 (a different acting parent, same lineage
        root) from independently issuing its own delegation to T2."""
        budget = LineageBudget(max_depth=2, max_children_per_delegation=1, max_total_delegations=5)
        to_t1 = self._checkpoint(target_specialist="database-engineer", budget=budget)
        self.assertEqual(to_t1["state"], "checkpointed")  # still in flight for P
        child_lineage = lineage_mod.lineage_from_dict(to_t1["lineage"])
        to_t2 = self.store.checkpoint(
            parent_task_id="TASK-CHILD-T1",
            parent_attempt_id="d-cccc",
            parent_generation=1,
            requester_specialist="database-engineer",
            target_specialist="security-analyst",
            question="A sub-question from T1",
            lineage=child_lineage,
            budget=budget,
            authority=self.authority,
        )
        self.assertEqual(to_t2["state"], "checkpointed")

    def test_concurrent_checkpoint_attempts_do_not_exceed_the_cap(self) -> None:
        """Real multi-thread race, not a sequential unit-level check: fire
        many concurrent checkpoint() calls from the same acting parent for
        DISTINCT targets against a tight concurrency cap, and confirm the
        lock genuinely serializes the check-then-act sequence so the cap is
        never jointly exceeded -- the same property board_router.py's own
        concurrency tests (which I verified line-by-line in the Task 2.1
        review) establish for its whole-active-set admission."""
        budget = LineageBudget(max_depth=1, max_children_per_delegation=2, max_total_delegations=100)
        results: list[tuple[int, bool]] = []
        lock = threading.Lock()

        def attempt(index: int) -> None:
            try:
                self.store.checkpoint(
                    parent_task_id="TASK-P",
                    parent_attempt_id="d-aaaa",
                    parent_generation=1,
                    requester_specialist="backend-engineer",
                    target_specialist=f"specialist-{index:03d}",
                    question=f"question {index}",
                    lineage=self.root,
                    budget=budget,
                    authority=self.authority,
                )
                admitted = True
            except DelegationDenied:
                admitted = False
            with lock:
                results.append((index, admitted))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(attempt, range(20)))

        admitted_count = sum(1 for _, ok in results if ok)
        self.assertEqual(admitted_count, budget.max_children_per_delegation)
        in_flight = self.store._count_in_flight("TASK-P")
        self.assertEqual(in_flight, budget.max_children_per_delegation)


# --------------------------------------------------------------------------- #
# REJECT-defect regression tests (TASK-2026-07-22-0585-v2-t2p4-fix)
# --------------------------------------------------------------------------- #
class TrustedLedgerRegressionTests(unittest.TestCase):
    """REJECT defect 1 (HIGH): the global cap must be enforced by a trusted,
    supervisor-owned ledger keyed by lineage root -- not by trusting whatever
    total_delegations value a caller's own lineage object happens to carry."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.store = CoordinationStore(state_dir=self.state_dir)
        self.authority = _authority(read_paths=("/repo/a",), data_class="internal")

    def test_sibling_checkpoints_from_the_same_root_never_jointly_exceed_the_global_cap(self) -> None:
        # Codex's exact repro: with max_total_delegations=2, three sequential
        # SIBLING checkpoints from the same root (cancelling each to free the
        # concurrency slot) were all admitted under the pre-fix code, each
        # storing its own branch-local total_delegations=1. The trusted
        # ledger must cap admissions at 2 for the whole root, period.
        budget = LineageBudget(max_depth=1, max_children_per_delegation=1, max_total_delegations=2)
        root = root_lineage("TASK-ROOT", "backend-engineer")
        admitted = 0
        denied = 0
        for index in range(3):
            try:
                record = self.store.checkpoint(
                    parent_task_id="TASK-ROOT",
                    parent_attempt_id="d-aaaa",
                    parent_generation=1,
                    requester_specialist="backend-engineer",
                    target_specialist=f"sibling-{index:03d}",
                    question=f"sibling question {index}",
                    lineage=root,
                    budget=budget,
                    authority=self.authority,
                )
                admitted += 1
                self.store.cancel(record["delegation_id"], reason="free the concurrency slot")
            except DelegationDenied:
                denied += 1
        self.assertEqual(admitted, 2)
        self.assertEqual(denied, 1)

    def test_caller_cannot_rotate_originating_parent_to_bypass_the_global_ledger(self) -> None:
        # Round-2 REJECT (codex): three otherwise-valid checkpoint calls
        # using the SAME real acting parent_task_id, each carrying a
        # DIFFERENTLY-ROTATED lineage.originating_parent, each selected its
        # own fresh ledger file under the round-1 fix -- all three were
        # admitted against max_total_delegations=2. The ledger key must now
        # be bound to a value the caller cannot rotate: every rotated-origin
        # call must be denied outright, and the real root's ledger must
        # remain untouched (so an honest sibling can still use its budget).
        budget = LineageBudget(max_depth=1, max_children_per_delegation=1, max_total_delegations=2)
        denied = 0
        for index in range(3):
            forged_root = root_lineage(f"forged-origin-{index}", "backend-engineer")
            with self.assertRaises(DelegationDenied):
                self.store.checkpoint(
                    parent_task_id="TASK-ROOT",
                    parent_attempt_id="d-aaaa",
                    parent_generation=1,
                    requester_specialist="backend-engineer",
                    target_specialist=f"sibling-{index:03d}",
                    question=f"sibling question {index}",
                    lineage=forged_root,
                    budget=budget,
                    authority=self.authority,
                )
            denied += 1
        self.assertEqual(denied, 3)
        self.assertEqual(self.store._read_root_ledger("TASK-ROOT"), 0)
        self.assertEqual(list(self.state_dir.glob("delegation-checkpoints/*.json")), [])

    def test_a_forged_mid_chain_lineage_that_this_store_never_admitted_is_denied(self) -> None:
        # A depth>0 forgery that never went through root_lineage()/advance()
        # at all -- constructed directly, claiming an arbitrary root. Must
        # be denied for the same reason: this store never persisted it.
        forged = DelegationLineage(
            originating_parent="some-other-root",
            chain_depth=1,
            visited_specialists=("backend-engineer", "database-engineer"),
            total_delegations=1,
        )
        budget = LineageBudget(max_depth=2, max_children_per_delegation=1, max_total_delegations=5)
        with self.assertRaises(DelegationDenied):
            self.store.checkpoint(
                parent_task_id="TASK-CHILD-1",
                parent_attempt_id="d-aaaa",
                parent_generation=1,
                requester_specialist="database-engineer",
                target_specialist="security-analyst",
                question="q",
                lineage=forged,
                budget=budget,
                authority=self.authority,
            )


class ContinuationOrderingAndHashRegressionTests(unittest.TestCase):
    """REJECT defect 2 (HIGH): dispatch-before-settle ordering and a real,
    independently-verified result hash."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.store = CoordinationStore(state_dir=self.state_dir)
        self.root = root_lineage("TASK-P", "backend-engineer")
        self.authority = _authority(read_paths=("/repo/a",), data_class="internal")

    def _checkpoint(self):
        return self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q", lineage=self.root, budget=DEFAULT_BUDGET, authority=self.authority,
        )

    def test_settling_a_never_dispatched_checkpoint_is_denied(self) -> None:
        record = self._checkpoint()
        self.assertEqual(record["state"], "checkpointed")
        payload = {"status": "complete", "answer": "42"}
        with self.assertRaisesRegex(DelegationDenied, "dispatch"):
            self.store.inject_result(
                record["delegation_id"], parent_generation=1,
                result=payload, result_sha256=_result_hash(payload),
            )
        self.assertEqual(self.store.get(record["delegation_id"])["state"], "checkpointed")

    def test_a_claimed_result_hash_that_does_not_match_the_real_result_is_denied(self) -> None:
        # Codex's exact repro: a checkpoint was settled with digest "false"
        # while the actual canonical JSON digest of the result was a real
        # sha256. The claimed hash must be independently verified, not
        # trusted verbatim.
        record = self._checkpoint()
        self.store.dispatched(record["delegation_id"])
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                record["delegation_id"], parent_generation=1,
                result={"status": "complete", "answer": "42"}, result_sha256="false",
            )
        self.assertEqual(self.store.get(record["delegation_id"])["state"], "dispatched")


class IdempotencyGenerationRegressionTests(unittest.TestCase):
    """REJECT defect 3 (HIGH): idempotency must not replay stale settled
    state from a prior parent generation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.store = CoordinationStore(state_dir=self.state_dir)
        self.root = root_lineage("TASK-P", "backend-engineer")
        self.authority = _authority(read_paths=("/repo/a",), data_class="internal")

    def _checkpoint(self, *, parent_attempt_id: str, parent_generation: int):
        return self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id=parent_attempt_id,
            parent_generation=parent_generation,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="identical question", lineage=self.root, budget=DEFAULT_BUDGET,
            authority=self.authority,
        )

    def test_a_replay_at_a_new_generation_does_not_inject_stale_settled_state(self) -> None:
        # Codex's exact repro: create+settle generation 1, then request the
        # "identical" checkpoint at generation 2. The pre-fix identity
        # (parent_task_id, target, question, authority_hash only) collided,
        # and checkpoint() returned the generation-1 settled record verbatim.
        gen1 = self._checkpoint(parent_attempt_id="d-aaaa", parent_generation=1)
        self.store.dispatched(gen1["delegation_id"])
        gen1_payload = {"status": "complete", "answer": "gen-1-answer"}
        settled_gen1 = self.store.inject_result(
            gen1["delegation_id"], parent_generation=1,
            result=gen1_payload, result_sha256=_result_hash(gen1_payload),
        )
        self.assertEqual(settled_gen1["state"], "settled")

        gen2 = self._checkpoint(parent_attempt_id="d-bbbb", parent_generation=2)

        self.assertNotEqual(gen2["delegation_id"], gen1["delegation_id"])
        self.assertEqual(gen2["state"], "checkpointed")
        self.assertIsNone(gen2["result"])


class DelegationIdContainmentRegressionTests(unittest.TestCase):
    """Deferred finding (HIGH, original review): caller-controlled
    delegation IDs were an out-of-store path-traversal write primitive."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.store = CoordinationStore(state_dir=self.state_dir)

    def test_cancel_rejects_a_traversal_delegation_id(self) -> None:
        # The review's exact repro: cancel('../../victim', ...) read and
        # rewrote victim.json two levels outside delegation-checkpoints/.
        (self.state_dir / "delegation-checkpoints").mkdir(parents=True)
        victim = self.state_dir.parent / "victim.json"
        victim.write_text(json.dumps({"sentinel": "untouched"}), encoding="utf-8")
        self.addCleanup(lambda: victim.unlink(missing_ok=True))
        with self.assertRaises(DelegationDenied):
            self.store.cancel("../../victim", "operator abort")
        self.assertEqual(json.loads(victim.read_text(encoding="utf-8")), {"sentinel": "untouched"})

    def test_get_rejects_non_canonical_delegation_ids(self) -> None:
        for bad_id in (
            "../etc/passwd",
            "../../victim",
            "deleg-",
            "deleg-not-hex-chars-here-not-hex!!",
            "deleg-" + "a" * 31,
            "deleg-" + "a" * 33,
            "plain-string",
            "/etc/passwd",
        ):
            with self.assertRaises(DelegationDenied):
                self.store.get(bad_id)

    def test_dispatched_and_inject_result_reject_a_traversal_id(self) -> None:
        # Place real victim files at the exact resolved traversal targets so
        # this genuinely exercises containment, not merely a "not found".
        (self.state_dir / "delegation-checkpoints").mkdir(parents=True)
        victim = self.state_dir.parent / "victim.json"
        victim.write_text(
            json.dumps({"schema": "delegation-checkpoint/v1", "state": "checkpointed"}),
            encoding="utf-8",
        )
        self.addCleanup(lambda: victim.unlink(missing_ok=True))
        with self.assertRaises(DelegationDenied):
            self.store.dispatched("../../victim")
        with self.assertRaises(DelegationDenied):
            self.store.inject_result(
                "../../victim", parent_generation=1,
                result={"status": "complete"}, result_sha256="a" * 64,
            )
        self.assertEqual(json.loads(victim.read_text(encoding="utf-8"))["state"], "checkpointed")

    def test_a_genuine_delegation_id_still_round_trips(self) -> None:
        authority = _authority(read_paths=("/repo/a",), data_class="internal")
        root = root_lineage("TASK-P", "backend-engineer")
        record = self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q", lineage=root, budget=DEFAULT_BUDGET, authority=authority,
        )
        self.assertEqual(self.store.get(record["delegation_id"])["delegation_id"], record["delegation_id"])


class TTLValidationRegressionTests(unittest.TestCase):
    """Deferred finding (MEDIUM, original review): a non-finite TTL never
    expires because ordinary >=/>= comparisons against NaN are always
    False."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.clock = MutableClock(1_000.0)
        self.store = CoordinationStore(state_dir=self.state_dir, clock=self.clock)
        self.root = root_lineage("TASK-P", "backend-engineer")
        self.authority = _authority(read_paths=("/repo/a",), data_class="internal")

    def _checkpoint(self, **overrides: Any):
        kwargs: dict[str, Any] = dict(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q", lineage=self.root, budget=DEFAULT_BUDGET, authority=self.authority,
        )
        kwargs.update(overrides)
        return self.store.checkpoint(**kwargs)

    def test_nan_ttl_is_rejected_before_persisting(self) -> None:
        # The review's exact repro: a checkpoint with a NaN TTL still
        # settled after the clock advanced to 1e100.
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=float("nan"))
        self.assertEqual(list(self.state_dir.glob("delegation-checkpoints/*.json")), [])

    def test_infinite_ttl_is_rejected(self) -> None:
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=float("inf"))

    def test_negative_and_zero_ttl_are_rejected(self) -> None:
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=-1.0)
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=0.0)

    def test_boolean_ttl_is_rejected(self) -> None:
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=True)

    def test_ttl_above_the_explicit_maximum_is_rejected(self) -> None:
        with self.assertRaises(DelegationDenied):
            self._checkpoint(ttl_seconds=coord_mod.MAX_TTL_SECONDS + 1.0)

    def test_a_finite_in_range_ttl_still_expires_normally(self) -> None:
        record = self._checkpoint(ttl_seconds=60)
        self.clock.value = 1_061.0
        expired = self.store.sweep_expired()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["state"], "stale")


class LockRecoveryRegressionTests(unittest.TestCase):
    """Deferred finding (MEDIUM, original review): the lock protocol could
    both flake under contention (a partially-written owner.pid misread as
    stale, stealing an actively-held lock) and permanently strand an
    ownerless lock (a crash between mkdir() and the separate owner.pid
    write was treated as "not stale" forever). Acquisition is now a single
    atomic rename of a fully-prepared staging directory."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"

    def test_a_lock_held_by_a_crashed_process_is_reclaimed_promptly(self) -> None:
        # The REAL crash-recovery path: acquisition is atomic, so a genuine
        # crash (kill -9 mid critical section) always leaves a FULLY
        # POPULATED owner.pid naming a now-dead PID, never a bare
        # directory. Spawn a real subprocess, let it exit (a guaranteed-
        # dead PID), and confirm its abandoned lock is reclaimed promptly.
        import subprocess

        self.state_dir.mkdir(parents=True)
        dead_pid_holder = subprocess.Popen(["true"])
        dead_pid_holder.wait()
        dead_pid = dead_pid_holder.pid

        lock_dir = self.state_dir / "delegation-lock.lockdir"
        lock_dir.mkdir()
        (lock_dir / "owner.pid").write_text(f"{dead_pid}\n", encoding="utf-8")
        started = time.monotonic()
        with coord_mod._store_lock(self.state_dir, timeout_seconds=2.0):
            pass
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)

    def test_a_bare_pre_existing_lock_directory_is_adopted_promptly(self) -> None:
        # An empty pre-existing lock directory (no owner.pid at all) is not
        # a stuck state: os.rename() onto an existing EMPTY directory
        # succeeds (confirmed directly against this filesystem), so the
        # very first acquire attempt cleanly adopts it -- no special
        # reclaim logic needed for this case at all.
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "delegation-lock.lockdir").mkdir()
        started = time.monotonic()
        with coord_mod._store_lock(self.state_dir, timeout_seconds=2.0):
            pass
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)

    def test_a_hand_corrupted_non_empty_lock_directory_times_out_safely(self) -> None:
        # A NON-empty lock directory whose owner.pid entry is corrupted
        # (here: a directory instead of a PID file, so it can never be
        # parsed as a PID) cannot arise from this module's own atomic
        # acquire/release paths -- only from external corruption.
        # Deliberately fails safe (a bounded timeout) rather than
        # reclaiming instantly: an instant-reclaim shortcut on a missing/
        # unreadable owner.pid was tried and stress-tested to a real
        # over-admission bug (a concurrent thread's brand-new, legitimate
        # lock could be torn down by a stale diagnosis made against the
        # OLD, already-gone state). See _store_lock's docstring.
        self.state_dir.mkdir(parents=True)
        lock_dir = self.state_dir / "delegation-lock.lockdir"
        lock_dir.mkdir()
        (lock_dir / "owner.pid").mkdir()
        with self.assertRaises(TimeoutError):
            with coord_mod._store_lock(self.state_dir, timeout_seconds=0.3):
                pass  # pragma: no cover -- must never be entered

    def test_a_lock_held_by_a_live_process_is_never_stolen(self) -> None:
        self.state_dir.mkdir(parents=True)
        lock_dir = self.state_dir / "delegation-lock.lockdir"
        lock_dir.mkdir()
        # This test process's own PID is, by definition, alive.
        (lock_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        with self.assertRaises(TimeoutError):
            with coord_mod._store_lock(self.state_dir, timeout_seconds=0.3):
                pass  # pragma: no cover -- must never be entered

    def test_contended_acquisition_leaves_no_orphaned_staging_directory(self) -> None:
        self.state_dir.mkdir(parents=True)
        lock_dir = self.state_dir / "delegation-lock.lockdir"
        lock_dir.mkdir()
        (lock_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        with self.assertRaises(TimeoutError):
            with coord_mod._store_lock(self.state_dir, timeout_seconds=0.2):
                pass  # pragma: no cover
        leftovers = [p for p in self.state_dir.iterdir() if p.name != "delegation-lock.lockdir"]
        self.assertEqual(leftovers, [])

    def test_acquire_release_reacquire_cycles_leave_no_garbage(self) -> None:
        self.state_dir.mkdir(parents=True)
        for _ in range(10):
            with coord_mod._store_lock(self.state_dir, timeout_seconds=1.0):
                pass
        self.assertEqual(list(self.state_dir.iterdir()), [])


# --------------------------------------------------------------------------- #
# coordination.py — real board_router integration (Task 2.1 reuse, not reimpl)
# --------------------------------------------------------------------------- #
class BoardIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "_state"
        self.store = CoordinationStore(state_dir=self.state_dir)
        self.root = root_lineage("TASK-P", "backend-engineer")

    def test_delegation_board_task_is_a_real_board_router_boardtask(self) -> None:
        import board_router as br

        authority = _authority(read_paths=("/repo/a",), resources=(("git_refs", "refs/heads/v2"),))
        record = self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q", lineage=self.root, budget=DEFAULT_BUDGET, authority=authority,
        )
        board_task = coord_mod.delegation_board_task(record)
        self.assertIsInstance(board_task, br.BoardTask)
        self.assertEqual(board_task.task_id, record["delegation_id"])
        self.assertEqual(board_task.write_paths, ())  # V1 read-only, always empty
        self.assertIn("/repo/a", board_task.read_paths)
        self.assertTrue(board_task.metadata_complete)

    def test_two_read_only_delegation_board_tasks_on_the_same_resource_parallelize(self) -> None:
        """Real-scheduler integration, positive case: board_router treats
        read/read on the same resource as safe (files_conflict's read/read
        rule, mirrored for resource claims) -- and every delegation board
        task is honestly claimed as read-mode, since V1 delegation never
        writes. Two purely-read-only delegates against the same resource
        correctly do NOT need to serialize; this is the settled Task 2.1
        scheduler's own reviewed behavior, exercised here for real, not
        reimplemented."""
        import board_router as br

        claim = (("git_refs", "refs/heads/v2"),)
        authority = _authority(read_paths=("/repo/a",), resources=claim)
        record_a = self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q1", lineage=self.root, budget=DEFAULT_BUDGET, authority=authority,
        )
        another_root = root_lineage("TASK-Q", "frontend-engineer")
        record_b = self.store.checkpoint(
            parent_task_id="TASK-Q", parent_attempt_id="d-bbbb", parent_generation=1,
            requester_specialist="frontend-engineer", target_specialist="security-analyst",
            question="q2", lineage=another_root, budget=DEFAULT_BUDGET, authority=authority,
        )
        task_a = coord_mod.delegation_board_task(record_a)
        task_b = coord_mod.delegation_board_task(record_b)
        self.assertTrue(br.can_parallelize(task_a, task_b))
        result = br.schedule((task_a, task_b), concurrency=4, logical_only=True)
        self.assertEqual(set(result.run_now), {task_a.task_id, task_b.task_id})
        self.assertEqual(result.must_wait, ())

    def test_delegation_board_task_serializes_against_an_active_writer_on_the_same_path(self) -> None:
        """Real-scheduler integration, negative case: a delegation reading a
        path that an ACTIVE task is concurrently writing must serialize --
        proving delegation_board_task() genuinely participates in Task 2.1's
        whole-active-set admission (board_router.schedule()'s
        active_reservations carry-forward), not a mocked stand-in."""
        import board_router as br

        authority = _authority(read_paths=("/repo/shared.py",))
        record = self.store.checkpoint(
            parent_task_id="TASK-P", parent_attempt_id="d-aaaa", parent_generation=1,
            requester_specialist="backend-engineer", target_specialist="database-engineer",
            question="q1", lineage=self.root, budget=DEFAULT_BUDGET, authority=authority,
        )
        delegation_task = coord_mod.delegation_board_task(record)

        writer = br.BoardTask(
            task_id="TASK-WRITER", write_paths=("/repo/shared.py",), metadata_complete=True,
        )
        round_one = br.schedule((writer,), concurrency=4, logical_only=True)
        self.assertEqual(round_one.run_now, ("TASK-WRITER",))

        round_two = br.schedule(
            (delegation_task,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=4,
            logical_only=True,
        )
        self.assertEqual(round_two.run_now, ())
        self.assertEqual(round_two.must_wait, (delegation_task.task_id,))


if __name__ == "__main__":
    unittest.main()
