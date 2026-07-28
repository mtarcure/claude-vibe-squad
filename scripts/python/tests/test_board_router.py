#!/usr/bin/env python3
"""Invariant tests for the V2 board router / parallel-safety scheduler."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import board_router as br  # noqa: E402


def task(
    task_id: str,
    *,
    write=(),
    read=(),
    depends_on=(),
    resources=(),
    worktree_root="",
    metadata_complete=True,
    priority=0,
) -> "br.BoardTask":
    return br.BoardTask(
        task_id=task_id,
        write_paths=tuple(write),
        read_paths=tuple(read),
        depends_on=tuple(depends_on),
        resources=tuple(resources),
        worktree_root=worktree_root,
        metadata_complete=metadata_complete,
        priority=priority,
    )


class FileDisjointnessTests(unittest.TestCase):
    def test_same_string_overlapping_write_scope_serializes(self) -> None:
        a = task("TASK-A", write=("/repo/x.py",))
        b = task("TASK-B", write=("/repo/x.py",))
        self.assertFalse(br.can_parallelize(a, b))

    def test_normalized_parent_child_write_collision_serializes(self) -> None:
        # string-inequality but /repo/pkg contains /repo/pkg/mod.py
        a = task("TASK-A", write=("/repo/pkg",))
        b = task("TASK-B", write=("/repo/pkg/mod.py",))
        self.assertFalse(br.can_parallelize(a, b))

    def test_relative_and_dotdot_components_are_canonicalized(self) -> None:
        a = task("TASK-A", write=("/repo/pkg/../pkg/x.py",))
        b = task("TASK-B", write=("/repo/pkg/x.py",))
        self.assertFalse(br.can_parallelize(a, b))

    def test_symlink_alias_write_collision_serializes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            real.mkdir()
            link = Path(d) / "link"
            link.symlink_to(real)
            a = task("TASK-A", write=(str(real / "f.txt"),))
            b = task("TASK-B", write=(str(link / "f.txt"),))
            self.assertFalse(br.can_parallelize(a, b))

    def test_hardlink_alias_write_collision_serializes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / "original.txt"
            original.write_text("x", encoding="utf-8")
            alias = Path(d) / "alias.txt"
            os.link(original, alias)  # distinct names, same inode
            a = task("TASK-A", write=(str(original),))
            b = task("TASK-B", write=(str(alias),))
            self.assertFalse(br.can_parallelize(a, b))

    def test_read_read_on_same_path_is_safe(self) -> None:
        a = task("TASK-A", read=("/repo/shared.txt",))
        b = task("TASK-B", read=("/repo/shared.txt",))
        self.assertTrue(br.can_parallelize(a, b))

    def test_read_write_on_same_path_serializes(self) -> None:
        a = task("TASK-A", write=("/repo/shared.txt",))
        b = task("TASK-B", read=("/repo/shared.txt",))
        self.assertFalse(br.can_parallelize(a, b))

    def test_distinct_worktree_disjoint_writes_parallelize(self) -> None:
        a = task("TASK-A", write=("/wt/a/src/x.py",), worktree_root="/wt/a")
        b = task("TASK-B", write=("/wt/b/src/x.py",), worktree_root="/wt/b")
        self.assertTrue(br.can_parallelize(a, b))


class DependencyTests(unittest.TestCase):
    def test_direct_dependency_edge_serializes(self) -> None:
        a = task("TASK-A", depends_on=(br.DepEdge("TASK-B", 1, "b" * 64),))
        b = task("TASK-B")
        self.assertFalse(br.can_parallelize(a, b))
        self.assertFalse(br.can_parallelize(b, a))  # either direction

    def test_transitive_dependency_serializes(self) -> None:
        a = task("TASK-A", depends_on=(br.DepEdge("TASK-B", 1, "b" * 64),))
        b = task("TASK-B", depends_on=(br.DepEdge("TASK-C", 1, "c" * 64),))
        c = task("TASK-C")
        index = br.build_dependency_index((a, b, c))
        # A and C have no direct edge but A transitively depends on C.
        self.assertFalse(br.can_parallelize(a, c, dependency_index=index))

    def test_prerequisite_at_wrong_generation_serializes(self) -> None:
        a = task("TASK-A", depends_on=(br.DepEdge("TASK-B", 2, "b" * 64),))
        # settled at generation 1, not 2 -> unmet -> A waits
        result = br.schedule(
            (a,), concurrency=4, settled={"TASK-B": (1, "b" * 64)}, logical_only=True
        )
        self.assertNotIn("TASK-A", result.run_now)
        self.assertIn("TASK-A", result.must_wait)

    def test_prerequisite_at_wrong_hash_serializes(self) -> None:
        a = task("TASK-A", depends_on=(br.DepEdge("TASK-B", 1, "b" * 64),))
        result = br.schedule(
            (a,), concurrency=4, settled={"TASK-B": (1, "d" * 64)}, logical_only=True
        )
        self.assertNotIn("TASK-A", result.run_now)

    def test_settled_prerequisite_at_exact_gen_hash_is_runnable(self) -> None:
        a = task("TASK-A", write=("/repo/a.py",), depends_on=(br.DepEdge("TASK-B", 1, "b" * 64),))
        result = br.schedule(
            (a,), concurrency=4, settled={"TASK-B": (1, "b" * 64)}, logical_only=True
        )
        self.assertIn("TASK-A", result.run_now)


class SharedResourceTests(unittest.TestCase):
    def _writers(self, resource_class: str, target: str = ""):
        a = task("TASK-A", write=("/wt/a/x",), worktree_root="/wt/a",
                 resources=(br.ResourceClaim(resource_class, target, "write"),))
        b = task("TASK-B", write=("/wt/b/x",), worktree_root="/wt/b",
                 resources=(br.ResourceClaim(resource_class, target, "write"),))
        return a, b

    def test_shared_registry_writers_serialize(self) -> None:
        a, b = self._writers("task_registry")
        self.assertFalse(br.can_parallelize(a, b))

    def test_shared_vault_writers_serialize(self) -> None:
        a, b = self._writers("vault_db")
        self.assertFalse(br.can_parallelize(a, b))

    def test_shared_git_refs_writers_serialize(self) -> None:
        a, b = self._writers("git_refs", "refs/heads/v2")
        self.assertFalse(br.can_parallelize(a, b))

    def test_shared_outbox_writers_serialize(self) -> None:
        a, b = self._writers("outbox")
        self.assertFalse(br.can_parallelize(a, b))

    def test_shared_board_state_writers_serialize(self) -> None:
        a, b = self._writers("board_state")
        self.assertFalse(br.can_parallelize(a, b))

    def test_distinct_targets_do_not_conflict(self) -> None:
        a = task("TASK-A", write=("/wt/a/x",), worktree_root="/wt/a",
                 resources=(br.ResourceClaim("port", "8001", "write"),))
        b = task("TASK-B", write=("/wt/b/x",), worktree_root="/wt/b",
                 resources=(br.ResourceClaim("port", "8002", "write"),))
        self.assertTrue(br.can_parallelize(a, b))

    def test_shared_resource_read_read_is_safe(self) -> None:
        a = task("TASK-A", write=("/wt/a/x",), worktree_root="/wt/a",
                 resources=(br.ResourceClaim("cache", "pip", "read"),))
        b = task("TASK-B", write=("/wt/b/x",), worktree_root="/wt/b",
                 resources=(br.ResourceClaim("cache", "pip", "read"),))
        self.assertTrue(br.can_parallelize(a, b))


class ScheduleAdmissionTests(unittest.TestCase):
    def _independent(self, task_id: str, **kw):
        # disjoint files, no deps, no resources unless given
        return task(task_id, write=(f"/wt/{task_id}/x",), worktree_root=f"/wt/{task_id}", **kw)

    def test_three_way_cumulative_conflict_third_waits(self) -> None:
        # capacity-2 counting resource; each task needs 1 unit -> pairwise safe, triple unsafe
        res = (br.ResourceClaim("provider_quota", "claude", "count", 1),)
        a = self._independent("TASK-A", resources=res, priority=0)
        b = self._independent("TASK-B", resources=res, priority=1)
        c = self._independent("TASK-C", resources=res, priority=2)
        # pairwise all safe
        caps = {("provider_quota", "claude"): 2}
        self.assertTrue(br.can_parallelize(a, b, capacities=caps))
        self.assertTrue(br.can_parallelize(a, c, capacities=caps))
        self.assertTrue(br.can_parallelize(b, c, capacities=caps))
        result = br.schedule((a, b, c), concurrency=8, capacities=caps, logical_only=True)
        self.assertEqual(set(result.run_now), {"TASK-A", "TASK-B"})
        self.assertEqual(set(result.must_wait), {"TASK-C"})

    def test_lock_acquisition_failure_rolls_back_cleanly(self) -> None:
        # Task needs [free_res, full_res]; the second fails -> first must be released,
        # so a later task that only needs free_res still gets it.
        caps = {("provider_quota", "claude"): 1, ("port", "9001"): 1}
        holder = self._independent("TASK-HOLD", resources=(br.ResourceClaim("provider_quota", "claude", "count", 1),), priority=0)
        greedy = self._independent(
            "TASK-GREEDY",
            resources=(br.ResourceClaim("port", "9001", "write"), br.ResourceClaim("provider_quota", "claude", "count", 1)),
            priority=1,
        )
        later = self._independent("TASK-LATER", resources=(br.ResourceClaim("port", "9001", "write"),), priority=2)
        result = br.schedule(
            (holder, greedy, later), concurrency=8, capacities=caps, logical_only=True
        )
        # HOLD takes the quota; GREEDY can't get quota (full) so it rolls back its port claim;
        # LATER must therefore still be able to take the port.
        self.assertIn("TASK-HOLD", result.run_now)
        self.assertIn("TASK-GREEDY", result.must_wait)
        self.assertIn("TASK-LATER", result.run_now)  # proves the port was rolled back, not half-held

    def test_missing_resource_metadata_serializes(self) -> None:
        good1 = self._independent("TASK-G1", priority=1)
        good2 = self._independent("TASK-G2", priority=2)
        ambiguous = self._independent("TASK-AMBIG", metadata_complete=False, priority=0)
        self.assertFalse(br.can_parallelize(ambiguous, good1))
        result = br.schedule((ambiguous, good1, good2), concurrency=8, logical_only=True)
        # ambiguous never shares a run slot with any other task
        if "TASK-AMBIG" in result.run_now:
            self.assertEqual(set(result.run_now), {"TASK-AMBIG"})

    def test_unknown_resource_class_serializes(self) -> None:
        weird = self._independent("TASK-WEIRD", resources=(br.ResourceClaim("teleporter", "", "write"),))
        good = self._independent("TASK-GOOD")
        self.assertTrue(br.is_ambiguous(weird))
        self.assertFalse(br.can_parallelize(weird, good))

    def test_two_disjoint_independent_tasks_parallelize(self) -> None:
        a = self._independent("TASK-A")
        b = self._independent("TASK-B")
        self.assertTrue(br.can_parallelize(a, b))
        result = br.schedule((a, b), concurrency=4, logical_only=True)
        self.assertEqual(set(result.run_now), {"TASK-A", "TASK-B"})
        self.assertEqual(result.must_wait, ())

    def test_more_ready_than_bound_caps_run_now(self) -> None:
        tasks = tuple(self._independent(f"TASK-{i}", priority=i) for i in range(5))
        result = br.schedule(tasks, concurrency=2, logical_only=True)
        self.assertEqual(len(result.run_now), 2)
        self.assertEqual(len(result.must_wait), 3)
        # deterministic: lowest-priority ids first
        self.assertEqual(set(result.run_now), {"TASK-0", "TASK-1"})

    def test_schedule_is_deterministic(self) -> None:
        tasks = tuple(self._independent(f"TASK-{i}", priority=0) for i in range(5))
        r1 = br.schedule(tasks, concurrency=3, logical_only=True)
        r2 = br.schedule(tuple(reversed(tasks)), concurrency=3, logical_only=True)
        self.assertEqual(r1.run_now, r2.run_now)

    def test_active_exclusive_resource_blocks_next_round(self) -> None:
        claim = (br.ResourceClaim("git_refs", "refs/heads/v2", "write"),)
        active = self._independent("TASK-ACTIVE", resources=claim)
        ready = self._independent("TASK-READY", resources=claim)
        round_one = br.schedule((active,), concurrency=4, logical_only=True)
        result = br.schedule(
            (ready,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=4,
            logical_only=True,
        )
        self.assertEqual(result.run_now, ())
        self.assertEqual(result.must_wait, ("TASK-READY",))
        self.assertEqual(result.reservations, round_one.reservations)

    def test_active_path_alias_blocks_next_round(self) -> None:
        active = task("TASK-ACTIVE", write=("/repo/shared.py",))
        ready = task("TASK-READY", write=("/repo/shared.py",))
        round_one = br.schedule((active,), concurrency=4, logical_only=True)
        result = br.schedule(
            (ready,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=4,
            logical_only=True,
        )
        self.assertEqual(result.run_now, ())

    def test_active_count_capacity_limits_next_round(self) -> None:
        claim = (br.ResourceClaim("provider_quota", "provider", "count", 1),)
        active = self._independent("TASK-ACTIVE", resources=claim)
        ready_a = self._independent("TASK-A", resources=claim, priority=0)
        ready_b = self._independent("TASK-B", resources=claim, priority=1)
        round_one = br.schedule(
            (active,),
            concurrency=4,
            capacities={("provider_quota", "provider"): 2},
            logical_only=True,
        )
        result = br.schedule(
            (ready_a, ready_b),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=4,
            capacities={("provider_quota", "provider"): 2},
            logical_only=True,
        )
        self.assertEqual(result.run_now, ("TASK-A",))
        self.assertEqual(result.must_wait, ("TASK-B",))

    def test_global_concurrency_counts_active_plus_new(self) -> None:
        active = self._independent("TASK-ACTIVE")
        ready_a = self._independent("TASK-A", priority=0)
        ready_b = self._independent("TASK-B", priority=1)
        round_one = br.schedule((active,), concurrency=2, logical_only=True)
        result = br.schedule(
            (ready_a, ready_b),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=2,
            logical_only=True,
        )
        self.assertEqual(result.run_now, ("TASK-A",))
        self.assertEqual(result.must_wait, ("TASK-B",))

    def test_worktree_relative_alias_resolves_against_each_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            worktree_a = root / "a"
            worktree_b = root / "b"
            worktree_a.mkdir()
            worktree_b.mkdir()
            (worktree_a / "shared.py").write_text("x", encoding="utf-8")
            active = task(
                "TASK-ACTIVE",
                write=("shared.py",),
                worktree_root=str(worktree_a),
            )
            ready = task(
                "TASK-READY",
                write=("../a/shared.py",),
                worktree_root=str(worktree_b),
            )
            self.assertFalse(br.can_parallelize(active, ready))

    def test_duplicate_and_non_string_task_ids_fail_closed(self) -> None:
        duplicate_a = self._independent("TASK-DUP", priority=0)
        duplicate_b = task("TASK-DUP", write=("/other/path",), priority=1)
        result = br.schedule(
            (duplicate_a, duplicate_b),
            concurrency=2,
            logical_only=True,
        )
        self.assertEqual(result.run_now, ())
        self.assertEqual(result.must_wait, ("TASK-DUP", "TASK-DUP"))
        with self.assertRaisesRegex(ValueError, "task id"):
            br.schedule((task(7),), concurrency=1, logical_only=True)

    def test_malformed_metadata_and_resource_targets_fail_closed(self) -> None:
        malformed_complete = self._independent(
            "TASK-COMPLETE",
            metadata_complete="false",
        )
        malformed_target = self._independent(
            "TASK-TARGET",
            resources=(br.ResourceClaim("port", 8000, "write"),),
        )
        string_target = self._independent(
            "TASK-STRING-TARGET",
            resources=(br.ResourceClaim("port", "8000", "write"),),
        )
        self.assertTrue(br.is_ambiguous(malformed_complete))
        self.assertTrue(br.is_ambiguous(malformed_target))
        self.assertFalse(br.can_parallelize(malformed_target, string_target))
        result = br.schedule(
            (malformed_complete, malformed_target, string_target),
            concurrency=3,
            logical_only=True,
        )
        self.assertEqual(result.run_now, ("TASK-STRING-TARGET",))

    def test_admission_is_fail_closed_without_valid_gate(self) -> None:
        ready = self._independent("TASK-READY")
        self.assertEqual(br.schedule((ready,), concurrency=1).run_now, ())
        self.assertEqual(
            br.schedule(
                (ready,),
                concurrency=1,
                admission_gate=lambda _: "yes",
            ).run_now,
            (),
        )

        def broken_gate(_: tuple[br.BoardTask, ...]) -> bool:
            raise RuntimeError("host probe unavailable")

        self.assertEqual(
            br.schedule((ready,), concurrency=1, admission_gate=broken_gate).run_now,
            (),
        )
        self.assertEqual(
            br.schedule((ready,), concurrency=1, logical_only=True).run_now,
            ("TASK-READY",),
        )

    def test_admission_receives_active_plus_new_and_reservations_are_deterministic(self) -> None:
        active = self._independent("TASK-ACTIVE")
        ready = self._independent("TASK-READY")
        round_one = br.schedule((active,), concurrency=2, logical_only=True)
        batches: list[tuple[str, ...]] = []

        def gate(tasks: tuple[br.BoardTask, ...]) -> bool:
            batches.append(tuple(item.task_id for item in tasks))
            return True

        first = br.schedule(
            (ready,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=2,
            admission_gate=gate,
        )
        second = br.schedule(
            (ready,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            concurrency=2,
            admission_gate=gate,
        )
        self.assertEqual(batches, [("TASK-ACTIVE", "TASK-READY")] * 2)
        self.assertEqual(first.run_now, ("TASK-READY",))
        self.assertEqual(
            tuple(reservation.task_id for reservation in first.reservations),
            ("TASK-ACTIVE", "TASK-READY"),
        )
        self.assertEqual(first.reservations, second.reservations)
        self.assertEqual(
            first.reservation_snapshot_sha256,
            second.reservation_snapshot_sha256,
        )
        self.assertTrue(all(reservation.token.startswith("resv-") for reservation in first.reservations))

    def test_reservation_release_requires_complete_snapshot_and_typed_transition(self) -> None:
        active = self._independent("TASK-ACTIVE")
        ready = self._independent("TASK-READY")
        round_one = br.schedule((active,), concurrency=1, logical_only=True)
        with self.assertRaisesRegex(ValueError, "snapshot hash mismatch"):
            br.schedule(
                (ready,),
                active_reservations=(),
                active_snapshot_sha256=round_one.reservation_snapshot_sha256,
                concurrency=1,
                logical_only=True,
            )
        with self.assertRaisesRegex(ValueError, "snapshot hash is required"):
            br.schedule(
                (ready,),
                active_reservations=round_one.reservations,
                concurrency=1,
                logical_only=True,
            )
        release = br.ReservationRelease(
            token=round_one.reservations[0].token,
            outcome="settled",
        )
        round_two = br.schedule(
            (ready,),
            active_reservations=round_one.reservations,
            active_snapshot_sha256=round_one.reservation_snapshot_sha256,
            release_events=(release,),
            concurrency=1,
            logical_only=True,
        )
        self.assertEqual(round_two.run_now, ("TASK-READY",))
        with self.assertRaisesRegex(ValueError, "settled or cancelled"):
            br.schedule(
                (),
                active_reservations=round_two.reservations,
                active_snapshot_sha256=round_two.reservation_snapshot_sha256,
                release_events=(
                    br.ReservationRelease(
                        token=round_two.reservations[0].token,
                        outcome="forgotten",
                    ),
                ),
                concurrency=1,
                logical_only=True,
            )


if __name__ == "__main__":
    unittest.main()
