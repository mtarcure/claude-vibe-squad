#!/usr/bin/env python3
"""Hermetic gates for the single board host-admission policy."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402

# See dispatch_checkout: send-task.sh refuses to dispatch from a linked
# worktree, which would make this suite checkout-dependent.
ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import board_process_truth as bpt  # noqa: E402
import host_admission as admission  # noqa: E402


GIB = 1024**3
SHA = "a" * 64


def candidate(
    task_id: str,
    lane: str,
    workload_class: str = "cpu-light",
) -> admission.Candidate:
    return admission.Candidate(
        task_id=task_id,
        lane=lane,
        workload_class=workload_class,
        packet_path=Path(f"/{task_id}.md"),
        packet_sha256=SHA,
    )


def safe_pair(**second_overrides: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
    base = dict(
        captured_at=100.0,
        physical_bytes=16 * GIB,
        resident_bytes=5 * GIB,
        pressure_free_percent=65.0,
        pressure_level="normal",
        swap_total_bytes=12 * GIB,
        swap_free_bytes=8 * GIB,
        swapins=100,
        pageouts=100,
        swapouts=100,
        compressions=100,
        load_average_1m=1.0,
        runnable_processes=2,
        free_disk_bytes=100 * GIB,
        process_count=300,
        pid_limit=4096,
    )
    first = admission.HostSnapshot(**base)
    return first, admission.HostSnapshot(
        **{**base, "captured_at": 103.0, **second_overrides}
    )


def decide(
    candidates: tuple[admission.Candidate, ...],
    *,
    live: tuple[admission.LiveAttempt, ...] = (),
    snapshots: tuple[admission.HostSnapshot, admission.HostSnapshot] | None = None,
) -> admission.AdmissionDecision:
    return admission._under_admission(
        candidates=candidates,
        live_attempts=live,
        live_snapshot=lambda: safe_pair() if snapshots is None else snapshots,
        now=103.0,
    )


class AdmissionPredicateTests(unittest.TestCase):
    def test_missing_telemetry_queues_instead_of_launching(self) -> None:
        result = admission._under_admission(
            candidates=(candidate("TASK-2026-08-08-0001-one", "claude"),),
            live_attempts=(),
            live_snapshot=lambda: None,
            now=103.0,
        )
        self.assertFalse(result.admitted)
        self.assertEqual(result.action, "queue")
        self.assertIn(2, result.failed_clauses)

    def test_safe_single_candidate_admits(self) -> None:
        result = decide((candidate("TASK-2026-08-08-0001-one", "claude"),))
        self.assertTrue(result.admitted, result.reasons)

    def test_each_family_has_the_same_target_four(self) -> None:
        self.assertEqual(admission.FAMILY_TARGET, 4)
        self.assertEqual(
            set(admission.LANE_FAMILY.values()),
            {"anthropic", "openai", "google", "xai", "moonshot"},
        )
        for lane in ("claude", "codex", "gemini", "grok", "kimi"):
            with self.subTest(lane=lane):
                live = tuple(
                    admission.LiveAttempt(f"live-{index}", lane, "cpu-light")
                    for index in range(3)
                )
                result = decide(
                    (
                        candidate("TASK-2026-08-08-0001-one", lane),
                        candidate("TASK-2026-08-08-0002-two", lane),
                    ),
                    live=live,
                )
                self.assertFalse(result.admitted)
                self.assertIn(1, result.failed_clauses)

    def test_family_batch_of_five_fails_before_host_capacity(self) -> None:
        tasks = tuple(
            candidate(f"TASK-2026-08-08-000{index}-batch", "gemini")
            for index in range(1, 6)
        )
        source = mock.Mock(return_value=safe_pair())
        result = admission._under_admission(
            candidates=tasks,
            live_attempts=(),
            live_snapshot=source,
            now=103.0,
        )
        self.assertFalse(result.admitted)
        self.assertIn(1, result.failed_clauses)
        source.assert_not_called()

    def test_global_limit_is_host_derived_for_mixed_batch(self) -> None:
        tasks = (
            candidate("TASK-2026-08-08-0001-a", "claude", "repo-build-test"),
            candidate("TASK-2026-08-08-0002-b", "codex", "repo-build-test"),
            candidate("TASK-2026-08-08-0003-c", "gemini", "repo-build-test"),
            candidate("TASK-2026-08-08-0004-d", "kimi", "repo-build-test"),
        )
        result = decide(
            tasks,
            snapshots=safe_pair(
                resident_bytes=11 * GIB,
                pressure_free_percent=20.0,
            ),
        )
        self.assertFalse(result.admitted)
        self.assertIn(4, result.failed_clauses)

    def test_reclaimable_cache_does_not_create_false_memory_or_swap_denial(self) -> None:
        task = candidate(
            "TASK-2026-08-08-0001-reclaimable",
            "claude",
            "repo-build-test",
        )
        _first, second = safe_pair(
            physical_bytes=16 * GIB,
            resident_bytes=int(12.7 * GIB),
            pressure_free_percent=57.0,
            swap_total_bytes=6 * GIB,
            swap_free_bytes=int(1.13 * GIB),
        )
        snapshots = (replace(second, captured_at=100.0), second)
        result = decide((task,), snapshots=snapshots)
        self.assertTrue(result.admitted, result.reasons)

    def test_process_projection_scales_with_whole_vector(self) -> None:
        tasks = tuple(
            candidate(f"TASK-2026-08-08-000{index}-batch", "claude")
            for index in range(1, 4)
        )
        result = decide(tasks, snapshots=safe_pair(process_count=3240, pid_limit=4096))
        self.assertFalse(result.admitted)
        self.assertIn(7, result.failed_clauses)

    def test_growth_pressure_and_unknown_workload_fail_closed(self) -> None:
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        for snapshots, clause in (
            (safe_pair(swapouts=197), 3),  # +97/3s exceeds the stricter 32 pages/s limit
            (safe_pair(pressure_level="critical"), 6),
            (safe_pair(pressure_free_percent=10.0), 6),
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, decide((task,), snapshots=snapshots).failed_clauses)
        unknown = replace(task, workload_class="unknown")
        self.assertIn(4, decide((unknown,)).failed_clauses)

    def test_clause_three_separates_swap_noise_from_pressure(self) -> None:
        # Fresh steady-host sampling measured <=5.980 swapins/s and 0 swapouts/s.
        # Pin that negative control as 18 pages/3s and the recorded loaded control
        # as 6144 pages/3s (2048/s, approximately 16340 pages/8s).
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        for label, overrides in (
            ("measured swapin noise", dict(swapins=118)),
            ("one-page swapout noise", dict(swapouts=101)),
        ):
            with self.subTest(must_admit=label):
                result = decide((task,), snapshots=safe_pair(**overrides))
                self.assertTrue(result.admitted, result.reasons)
                self.assertNotIn(3, result.failed_clauses, label)
        loaded = decide((task,), snapshots=safe_pair(swapins=6244))
        self.assertFalse(loaded.admitted)
        self.assertIn(3, loaded.failed_clauses)
        for label, overrides in (
            ("pageouts alone", dict(pageouts=101)),
            ("compressions alone", dict(compressions=24306)),
            ("pageouts and compressions together", dict(pageouts=101, compressions=24306)),
        ):
            with self.subTest(must_not_fail=label):
                result = decide((task,), snapshots=safe_pair(**overrides))
                self.assertNotIn(3, result.failed_clauses, label)
        for label, overrides in (
            ("swapins regressed", dict(swapins=99)),
            ("swapouts regressed", dict(swapouts=99)),
        ):
            with self.subTest(must_fail_closed=label):
                self.assertIn(3, decide((task,), snapshots=safe_pair(**overrides)).failed_clauses)

    def test_clause_three_normalizes_two_to_five_second_samples(self) -> None:
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        for interval in (2.0, 5.0):
            with self.subTest(interval=interval, boundary="admit"):
                first, second = safe_pair(
                    captured_at=100.0 + interval,
                    swapins=100 + int(admission.SWAP_RATE_LIMITS[0] * interval),
                    swapouts=100 + int(admission.SWAP_RATE_LIMITS[1] * interval),
                )
                result = admission._under_admission(
                    candidates=(task,), live_attempts=(),
                    live_snapshot=lambda: (first, second), now=100.0 + interval,
                )
                self.assertTrue(result.admitted, result.reasons)
            with self.subTest(interval=interval, boundary="refuse"):
                pressured = replace(second, swapins=second.swapins + 1)
                result = admission._under_admission(
                    candidates=(task,), live_attempts=(),
                    live_snapshot=lambda: (first, pressured), now=100.0 + interval,
                )
                self.assertFalse(result.admitted)
                self.assertIn(3, result.failed_clauses)

    def test_free_swap_file_space_is_not_an_admission_clause(self) -> None:
        # Former clause 5 compared free space in the CURRENT swap file against
        # max(1 GiB, 10% of swap_total). macOS swap is dynamic -- the file is grown
        # on demand out of free disk -- so both sides drifted with uptime rather
        # than describing capacity, and a healthy host was refused for it.
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        starved = decide((task,), snapshots=safe_pair(swap_free_bytes=64 * 1024**2))
        self.assertTrue(starved.admitted, starved.reasons)
        self.assertNotIn(5, starved.failed_clauses)
        # The clause is gone entirely, not merely unreached on this fixture.
        source = (PYTHON_DIR / "host_admission.py").read_text(encoding="utf-8")
        for forbidden in ("failed[5]", "minimum_swap", "free_swap_after", "projected_swap_use"):
            self.assertNotIn(forbidden, source)

    def test_merge_kept_every_genuinely_unsafe_host_refused(self) -> None:
        # No check weakened: each host below would have tripped the old clause 5,
        # and each is still refused -- by the clause that actually measures it.
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        starving = dict(swap_free_bytes=64 * 1024**2)
        for label, overrides, clause in (
            ("swap I/O active: swapping out", dict(swapouts=197), 3),
            ("projection exceeds the pressure budget", dict(pressure_free_percent=18.0), 4),
            ("pressure critical", dict(pressure_level="critical"), 6),
            ("pressure under the class floor", dict(pressure_free_percent=19.0), 6),
            ("no disk left to grow swap into", dict(free_disk_bytes=GIB), 7),
        ):
            with self.subTest(host=label):
                result = decide((task,), snapshots=safe_pair(**{**starving, **overrides}))
                self.assertFalse(result.admitted, label)
                self.assertIn(clause, result.failed_clauses)

    def test_invalid_or_future_dated_telemetry_queues(self) -> None:
        first, second = safe_pair()
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        invalid = decide((task,), snapshots=(first, replace(second, swap_free_bytes=-1)))
        future = admission._under_admission(
            candidates=(task,),
            live_attempts=(),
            live_snapshot=lambda: (first, second),
            now=102.0,
        )
        self.assertIn(2, invalid.failed_clauses)
        self.assertIn(2, future.failed_clauses)


class ExactBoardTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.board = self.root / "_state" / "board-dispatch"
        self.board.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_attempt(
        self, *, terminal: bool = False, malformed: bool = False, legacy: bool = False
    ) -> Path:
        task_id, attempt_id = "TASK-2026-08-08-0001-live", "d-" + "b" * 32
        base = self.board / f"{task_id}.{attempt_id}"
        descriptor_path = Path(f"{base}.dispatch.json")
        descriptor = {
            "schema": bpt.DESCRIPTOR_V1 if legacy else bpt.DESCRIPTOR_V2,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "created_at": "2026-08-08T00:00:00Z",
            "pid": 123,
            "pgid": 123,
            "process_start_token": "fixture",
            "argv_sha256": "c" * 64,
            "context_path": f"{base}.context.json",
            "log_path": f"{base}.log",
            "receipt_path": f"{base}.receipt.json",
        }
        if malformed:
            descriptor["generation"] = True
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        Path(descriptor["context_path"]).write_text(
            json.dumps({
                "authority": {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "generation": 1,
                    "lane": "codex",
                    "workload_class": "cpu-light",
                }
            }),
            encoding="utf-8",
        )
        if terminal:
            receipt = {
                "schema": bpt.RECEIPT_V1 if legacy else bpt.RECEIPT_V2,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "generation": 1,
            }
            if legacy:
                receipt["status"] = "complete"
            else:
                receipt.update({
                    "descriptor_sha256": bpt.descriptor_hash(descriptor),
                    "terminal_outcome": "complete",
                    "completed_at": "2026-08-08T00:01:00Z",
                })
            Path(descriptor["receipt_path"]).write_text(
                json.dumps(receipt),
                encoding="utf-8",
            )
        return descriptor_path

    def test_live_descriptor_counts_and_matching_terminal_receipt_excludes(self) -> None:
        self.write_attempt()
        with mock.patch.object(
            bpt, "process_truth", return_value={"state": "live", "reason": "fixture"}
        ):
            live = admission.discover_live_attempts(self.root)
        self.assertEqual(live, (admission.LiveAttempt(
            "TASK-2026-08-08-0001-live", "codex", "cpu-light"
        ),))

        for path in self.board.iterdir():
            path.unlink()
        self.write_attempt(terminal=True)
        with mock.patch.object(bpt, "process_truth") as truth:
            self.assertEqual(admission.discover_live_attempts(self.root), ())
        truth.assert_not_called()

    def test_legacy_descriptors_are_historical_not_current_capacity_truth(self) -> None:
        self.write_attempt(terminal=True, legacy=True)
        with mock.patch.object(bpt, "process_truth") as truth:
            self.assertEqual(admission.discover_live_attempts(self.root), ())
        truth.assert_not_called()

        for path in self.board.iterdir():
            path.unlink()
        self.write_attempt(legacy=True)
        self.assertEqual(admission.discover_live_attempts(self.root), ())

    def test_registry_labels_are_not_admission_truth(self) -> None:
        (self.root / "_state" / "active-tasks.json").write_text(
            json.dumps({"fake": {"status": "in-flight", "to_model": "claude"}}),
            encoding="utf-8",
        )
        self.assertEqual(admission.discover_live_attempts(self.root), ())

    def test_malformed_or_unsettled_nonlive_descriptor_fails_closed(self) -> None:
        self.write_attempt(malformed=True)
        with self.assertRaises(admission.HostStateError):
            admission.discover_live_attempts(self.root)
        for path in self.board.iterdir():
            path.unlink()
        self.write_attempt()
        with mock.patch.object(
            bpt, "process_truth", return_value={"state": "dead", "reason": "fixture"}
        ):
            with self.assertRaises(admission.HostStateError):
                admission.discover_live_attempts(self.root)

    def test_candidate_packet_is_bound_and_rechecked_before_admission(self) -> None:
        packet = self.root / "task.md"
        packet.write_text(
            "---\nid: TASK-2026-08-08-0002-bound\n"
            "to_model: gpt-codex\nspecialist: backend-engineer\n---\n\nBound candidate.\n",
            encoding="utf-8",
        )
        bound = admission.candidate_from_task(
            packet, ROOT, "TASK-2026-08-08-0002-bound",
            hashlib.sha256(packet.read_bytes()).hexdigest(),
        )
        self.assertEqual((bound.task_id, bound.lane), (
            "TASK-2026-08-08-0002-bound", "codex"
        ))
        accepted = admission.admit(
            repo_root=self.root, candidates=(bound,), snapshots=safe_pair(), now=103.0
        )
        self.assertTrue(accepted.admitted, accepted.reasons)
        packet.write_text(packet.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        refused = admission.admit(
            repo_root=self.root, candidates=(bound,), snapshots=safe_pair(), now=103.0
        )
        self.assertFalse(refused.admitted)
        self.assertIn(1, refused.failed_clauses)

    def test_sender_expected_identity_and_hash_reject_a_prebind_change(self) -> None:
        packet = self.root / "prebind.md"
        original = (
            "---\nid: TASK-2026-08-08-0003-prebind\n"
            "to_model: gpt-codex\nspecialist: backend-engineer\n---\n\nA.\n"
        ).encode()
        packet.write_bytes(original)
        expected_sha256 = hashlib.sha256(original).hexdigest()
        packet.write_bytes(original.replace(b"A.\n", b"B.\n"))
        with self.assertRaises(admission.HostStateError):
            admission.candidate_from_task(
                packet,
                ROOT,
                "TASK-2026-08-08-0003-prebind",
                expected_sha256,
            )

    def test_packet_mutation_during_telemetry_fails_post_sample_rehash(self) -> None:
        packet = self.root / "task.md"
        packet.write_text(
            "---\nid: TASK-2026-08-08-0003-rehash\n"
            "to_model: gpt-codex\nspecialist: backend-engineer\n---\n\nBound.\n",
            encoding="utf-8",
        )
        bound = admission.candidate_from_task(
            packet, ROOT, "TASK-2026-08-08-0003-rehash",
            hashlib.sha256(packet.read_bytes()).hexdigest(),
        )

        def mutate_during_sample(**_kwargs: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
            packet.write_text(packet.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
            return safe_pair()

        with mock.patch.object(admission, "collect_live_snapshots", side_effect=mutate_during_sample):
            refused = admission.admit(repo_root=self.root, candidates=(bound,), now=103.0)
        self.assertFalse(refused.admitted)
        self.assertIn(1, refused.failed_clauses)
        self.assertIn("changed during telemetry", " ".join(refused.reasons))

    def test_admission_and_context_share_dispatcher_workload_classification(self) -> None:
        # `agentops` carries safety_tags [live_target] and is deliberately listed
        # here. It must classify by its capability_class (judgment -> cpu-light),
        # NOT by its safety tag. Until 2026-08-09 a `live_target` short-circuit in
        # dispatcher_workload_class() forced it to `security-untrusted`, a policy
        # that ships calibrated=False and therefore fails admission clause 4 no
        # matter how idle the host is. That took out 15 of 73 specialists,
        # including every offensive role, and the old version of this test asserted
        # the breakage as intended behaviour. Assert the opposite now, so nobody
        # reinstates the short-circuit without a red build.
        expected = {
            "backend-engineer": "repo-build-test",
            "image-designer": "browser-media",
            "security-analyst": "cpu-light",
            "agentops": "cpu-light",
        }
        for index, (specialist, workload) in enumerate(expected.items(), start=4):
            with self.subTest(specialist=specialist):
                packet = self.root / f"task-{index}.md"
                packet.write_text(
                    f"---\nid: TASK-2026-08-08-000{index}-class\n"
                    f"to_model: claude\nspecialist: {specialist}\n---\n\nClassified.\n",
                    encoding="utf-8",
                )
                bound = admission.candidate_from_task(
                    packet, ROOT, f"TASK-2026-08-08-000{index}-class",
                    hashlib.sha256(packet.read_bytes()).hexdigest(),
                )
                self.assertEqual(bound.workload_class, workload)
                self.assertNotEqual(bound.workload_class, "security-untrusted")
                # Whatever else admission decides, it must not be the
                # never-satisfiable calibration refusal.
                self.assertNotIn(4, decide((bound,)).failed_clauses)

        unknown = self.root / "unknown.md"
        unknown.write_text(
            "---\nid: TASK-2026-08-08-0008-unknown\n"
            "to_model: claude\nspecialist: not-a-role\n---\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            admission.candidate_from_task(
                unknown, ROOT, "TASK-2026-08-08-0008-unknown",
                hashlib.sha256(unknown.read_bytes()).hexdigest(),
            )


class ProductionWiringTests(unittest.TestCase):
    def test_conflicting_controls_and_caller_asserted_facts_are_gone(self) -> None:
        host = (PYTHON_DIR / "host_admission.py").read_text(encoding="utf-8")
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        supervisor = (ROOT / "bin" / "board-supervisor.sh").read_text(encoding="utf-8")
        for forbidden in (
            "hard_max", "provider_budget_available", "broker_port_available",
            "priority_state_known", "active_workers",
        ):
            self.assertNotIn(forbidden, host)
        for forbidden in (
            "check_launch_capacity", "board_host_admit_batch",
            "SEND_TASK_SKIP_CAPACITY", "SEND_TASK_MAX_LANES",
            "SEND_TASK_MAX_PER_LANE", "--hard-max",
        ):
            self.assertNotIn(forbidden, sender)
        self.assertNotIn("--hard-max", supervisor)
        router = (PYTHON_DIR / "board_router.py").read_text(encoding="utf-8")
        context_builder = (PYTHON_DIR / "dispatch_context_builder.py").read_text(encoding="utf-8")
        self.assertNotIn("from host_admission import", router)
        self.assertNotIn("host_admission.under_admission", router)
        self.assertNotIn("def under_admission(", host)
        self.assertIn('"workload_class": dispatcher_workload_class(root, specialist)', context_builder)
        self.assertNotIn('"workload_class": "cpu-light"', context_builder)

    def test_single_dispatch_uses_one_admitted_candidate(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        self.assertEqual(sender.count('board_host_admit "$ACTUAL_TASK_FILE"'), 1)
        self.assertNotIn("BOARD_FANOUT", sender)
        self.assertNotIn("BOARD_BATCH_TASKS", sender)
        self.assertNotIn("dispatch_admitted_child", sender)
        self.assertNotIn("--register-swarm", sender)
    def test_final_staging_bytes_are_admitted_immediately_before_publication(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        publication = sender.split("# ── ITEM 4: inject toolkit", 1)[1]
        self.assertLess(
            publication.index('board_host_admit "$ACTUAL_TASK_FILE"'),
            publication.index('DEST="${INBOX}/${TASK_ID}.md"'),
        )
        self.assertIn('cmp -s "$ACTUAL_TASK_FILE" "$INBOX_TEMP"', sender)
        self.assertIn("--candidate", sender)
        self.assertIn("--vector-sha256", sender)
    def test_single_dispatch_main_reuses_top_level_setup(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        prefix, main = sender.split("send_task_main() {", 1)
        self.assertIn("source ", prefix)
        self.assertIn("parse_task_frontmatter", main)
        self.assertNotIn("repo-root.sh", main)
        self.assertNotIn("set -euo pipefail", main)
        self.assertNotIn("trap ", main)
        self.assertNotIn("BOARD_BATCH_ADMITTED", sender)
    def test_production_loc_caps(self) -> None:
        host_lines = (PYTHON_DIR / "host_admission.py").read_text(encoding="utf-8").splitlines()
        # 474 -> 475 on 2026-08-31: adding the grok lane put a fifth entry in
        # MODEL_LANE, which no longer fits one line. That is a feature paying
        # for itself, not drift -- the ratchet moves by exactly the one line the
        # fifth lane costs, and every other cap here is unchanged.
        #
        # 475 -> 494 on 2026-08-31, +19 for the `refuse` verdict, audited line by
        # line rather than raised to match. Every refusal used to be `queue`, so
        # send-task.sh slept its whole 900s budget re-running a decision whose
        # inputs could not change, then died anyway:
        #   +1  the `clearable` field
        #   +5  the doctrine comment on `action`, which is the whole point of
        #       the change and the thing a future reader would otherwise
        #       "simplify" straight back into a two-way verdict
        #   +2  threading `clearable` through _decision (parameter, construction)
        #   +3  zero-swap: a four-line why, less the deleted positivity clause
        #   +5  splitting clause 1's two conditions (vector-alone vs contention)
        #   +3  splitting clause 4's two conditions (calibration vs projection)
        # The nine terminal call sites cost nothing: each stayed one line, inside
        # the 134-char width this file already uses.
        #
        # Comments are 12 of the 19. That is deliberate here and is NOT a licence
        # to comment the cap upward: the next increase should carry code.
        #
        # 494 -> 523 on 2026-09-01, +29, for reading the memory pressure level
        # from `sysctl kern.memorystatus_vm_pressure_level`. Clause 6's critical
        # half had been dead since it was written: it read the level out of
        # `memory_pressure -Q`, whose output on this host names no level, so the
        # parser's `else "normal"` made every reading healthy by default. This
        # increase carries code -- 14 of the 29 lines, against 12 comment and 3
        # blank, inverting the ratio of the raise above:
        #   +2  the 1/2/4 mapping table and the sysctl command tuple
        #   +5  parse_pressure_level
        #   +5  read_pressure_level's body
        #   +2  collect_snapshot reading the sysctl, with the -Q text as fallback
        #   +7  the provenance comment on the mapping. This one is load-bearing:
        #       it records that 1/2/4 comes from dispatch/source.h and NOT from
        #       XNU's 0-based vm_pressure_level_t, which a future reader would
        #       otherwise re-derive from the likelier-looking wrong header and
        #       silently turn a starved host back into a healthy one
        #   +3  why read_pressure_level catches broadly and never raises
        #   +2  why the -Q text is a fallback rather than the source
        #   +3  blank separators
        #
        # 523 -> 527 on 2026-09-01, +4, splitting the invalid-authority verdict.
        # An invalid LIVE-attempt authority shared terminal `refuse` with an
        # invalid candidate, but only the candidate half is terminal: the
        # identical retry re-runs discover_live_attempts, which drops an attempt
        # whose receipt has landed, so the same vector admits once the running
        # work finishes. Doctrine says that queues.
        #   +4  the four-line why on the split
        #   +0  code: the `live` predicate folds onto the existing `clause` line,
        #       and the call site stays one line inside the file's 134-char width
        # This is the all-comment raise the note above warns about, taken with
        # eyes open. `clearable=live` is a single token away from the bug it
        # fixes and nothing else in the file records which half is which -- the
        # sibling splits at clause 1 and clause 4 each carry the same three-line
        # comment for the same reason. The next increase should still carry code.
        self.assertLessEqual(len(host_lines), 527)
        sender_lines = (ROOT / "bin" / "send-task.sh").read_text(
            encoding="utf-8"
        ).splitlines()
        # 1,820 -> 1,963 on 2026-08-31, after auditing every line of the growth
        # rather than raising the ratchet to match. The +143 is six features and
        # one deletion, each verified live in this checkout:
        #   +59  --dry-run wired to the launch validator
        #   +37  review admission hardening (the REVIEWS= contract)
        #   +35  admission QUEUE verdict retries instead of dying
        #    +7  settlement PATH fix (ended a five-task outage)
        #    +6  dry-run parity proof
        #    +5  the grok lane, a fifth model family
        #    -6  an interpreter-resolver workaround, deleted once the
        #        environment was fixed at its source
        # No dead functions: every function in the file is called.
        #
        # This ratchet is doing its job and the answer here is honest growth,
        # NOT permission to keep growing. The file is a shell script carrying
        # frontmatter generation, preflight, admission and dispatch, and it
        # wants decomposing; the next increase should extract, not raise.
        self.assertLessEqual(len(sender_lines), 1963)


class ClearabilityTests(unittest.TestCase):
    """`shared/protocol.md` Boundary-Blocking Doctrine at the dispatch boundary.

    A refusal may only ask the caller to WAIT when waiting can actually clear
    it. Every verdict here used to be `queue`, so `bin/send-task.sh` slept the
    whole `SQUAD_ADMISSION_MAX_WAIT_SECONDS` budget (900s by default) re-running
    a decision whose inputs could not change, then died anyway.
    """

    def test_malformed_candidate_vector_refuses(self) -> None:
        for label, candidates in (
            ("empty vector", ()),
            (
                "duplicate task ids",
                (
                    candidate("TASK-2026-08-08-0001-dup", "claude"),
                    candidate("TASK-2026-08-08-0001-dup", "claude"),
                ),
            ),
            ("unknown lane", (candidate("TASK-2026-08-08-0001-lane", "not-a-lane"),)),
            (
                "unknown workload class",
                (candidate("TASK-2026-08-08-0001-class", "claude", "not-a-class"),),
            ),
            ("task id fails the identifier grammar", (candidate("-bad id", "claude"),)),
        ):
            with self.subTest(host=label):
                result = decide(candidates)
                self.assertFalse(result.admitted, label)
                self.assertEqual(result.action, "refuse", label)
                self.assertFalse(result.clearable, label)

    def test_invalid_live_attempt_authority_queues_rather_than_refusing(self) -> None:
        """The live half of this condition clears itself; the candidate half does not.

        `test_malformed_candidate_vector_refuses` covers candidates only, and a
        candidate is correctly terminal: the same malformed packet is malformed
        again on the identical retry. A LIVE attempt's authority is different --
        the identical retry re-runs `discover_live_attempts`, which drops any
        attempt whose terminal receipt has landed, so the same vector admits
        once the running work finishes. Under the Boundary-Blocking Doctrine
        (`shared/protocol.md`) a condition its owner can clear by waiting must
        queue, not refuse.
        """
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        for label, live in (
            ("unknown lane", admission.LiveAttempt("TASK-2026-08-08-0002-live", "not-a-lane", "cpu-light")),
            ("unknown workload class", admission.LiveAttempt("TASK-2026-08-08-0002-live", "claude", "not-a-class")),
            ("task id fails the identifier grammar", admission.LiveAttempt("-bad id", "claude", "cpu-light")),
        ):
            with self.subTest(live=label):
                result = decide((task,), live=(live,))
                self.assertFalse(result.admitted, label)
                self.assertEqual(result.action, "queue", label)
                self.assertTrue(result.clearable, label)

    def test_uncalibrated_workload_refuses_rather_than_waiting_forever(self) -> None:
        # `calibrated=False` is a property of WORKLOAD_POLICIES, not of the
        # host. No amount of idling flips it, so clause 4's calibration half is
        # terminal even though its projection half is ordinary backpressure.
        result = decide(
            (candidate("TASK-2026-08-08-0001-untrusted", "claude", "security-untrusted"),)
        )
        self.assertFalse(result.admitted)
        self.assertIn(4, result.failed_clauses)
        self.assertEqual(result.action, "refuse")

    def test_family_cap_refuses_only_when_the_vector_alone_exceeds_it(self) -> None:
        # Two different conditions wear one clause number. A vector carrying
        # five same-family candidates can never fit a cap of four, so it is
        # terminal; a vector of one that only exceeds the cap once live attempts
        # are counted is capacity contention, and those live attempts finish.
        over = decide(
            tuple(
                candidate(f"TASK-2026-08-08-000{index}-batch", "claude")
                for index in range(1, 6)
            )
        )
        self.assertEqual(over.action, "refuse")
        self.assertIn(1, over.failed_clauses)
        contended = decide(
            (candidate("TASK-2026-08-08-0009-late", "claude"),),
            live=tuple(
                admission.LiveAttempt(f"live-{index}", "claude", "cpu-light")
                for index in range(admission.FAMILY_TARGET)
            ),
        )
        self.assertFalse(contended.admitted)
        self.assertIn(1, contended.failed_clauses)
        self.assertEqual(contended.action, "queue")

    def test_genuine_host_backpressure_still_queues(self) -> None:
        # Nothing here is weakened into a refusal: each of these clears itself.
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        for label, overrides, clause in (
            ("swap I/O active", dict(swapouts=197), 3),
            ("projection exceeds the budget", dict(pressure_free_percent=18.0), 4),
            ("pressure critical", dict(pressure_level="critical"), 6),
            ("no disk headroom", dict(free_disk_bytes=GIB), 7),
        ):
            with self.subTest(host=label):
                result = decide((task,), snapshots=safe_pair(**overrides))
                self.assertFalse(result.admitted, label)
                self.assertIn(clause, result.failed_clauses, label)
                self.assertEqual(result.action, "queue", label)
        stale = admission._under_admission(
            candidates=(task,), live_attempts=(),
            live_snapshot=lambda: None, now=103.0,
        )
        self.assertEqual(stale.action, "queue")

    def test_board_state_and_binding_failures_refuse(self) -> None:
        # `admit()` fails closed on board truth an operator must repair (a
        # wedged descriptor) and on a packet whose bytes moved under a bound
        # hash. Neither is a wait.
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            missing = admission.Candidate(
                task_id="TASK-2026-08-08-0001-gone",
                lane="claude",
                workload_class="cpu-light",
                packet_path=root / "absent.md",
                packet_sha256="0" * 64,
            )
            result = admission.admit(
                repo_root=root, candidates=(missing,), snapshots=safe_pair(), now=103.0
            )
        self.assertFalse(result.admitted)
        self.assertIn(1, result.failed_clauses)
        self.assertEqual(result.action, "refuse")

    def test_action_and_json_expose_exactly_three_verdicts(self) -> None:
        admitted = decide((candidate("TASK-2026-08-08-0001-one", "claude"),))
        self.assertEqual(admitted.action, "admit")
        payload = json.loads(decide(()).to_json())
        self.assertEqual(payload["action"], "refuse")
        self.assertIs(payload["clearable"], False)
        # send-task.sh retries only on the literal string "queue"; any other
        # verdict dies at once. That contract is what makes `refuse` fast.
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        self.assertIn('"$admission_action" == "queue"', sender)


class ZeroSwapHostTests(unittest.TestCase):
    @staticmethod
    def _pair(**overrides: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
        # safe_pair() overrides only the SECOND sample, which would trip the
        # stable-host-identity check instead of the field under test. Swap
        # totals must match across the pair, so override both.
        second = safe_pair(**overrides)[1]
        return replace(second, captured_at=100.0), second

    def test_zero_total_swap_is_valid_telemetry(self) -> None:
        # macOS reports `vm.swapusage total = 0.00M` on a host that has simply
        # never needed to grow a swap file. The schema check treated that as
        # corrupt telemetry, so a completely healthy machine -- normal pressure,
        # idle load, disk and memory to spare -- could never dispatch at all.
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        result = decide(
            (task,), snapshots=self._pair(swap_total_bytes=0, swap_free_bytes=0)
        )
        self.assertTrue(result.admitted, result.reasons)
        self.assertNotIn(2, result.failed_clauses)

    def test_swap_free_above_total_is_still_invalid(self) -> None:
        # The coherence half of the check is untouched: free swap can never
        # exceed total, at zero or anywhere else, and neither may be negative.
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        for total, free in ((0, 1), (2 * GIB, 3 * GIB), (2 * GIB, -1)):
            with self.subTest(total=total, free=free):
                result = decide(
                    (task,),
                    snapshots=self._pair(swap_total_bytes=total, swap_free_bytes=free),
                )
                self.assertFalse(result.admitted)
                self.assertIn(2, result.failed_clauses)

# The literal output of `/usr/bin/memory_pressure -Q` on this host, captured
# 2026-09-01. That is the exact command collect_snapshot runs. Note what is
# absent: no line names a pressure level. `grep -in "critical|warn|normal"`
# over it returns nothing.
THIS_HOST_MEMORY_PRESSURE_Q = (
    "The system has 17179869184 (1048576 pages with a page size of 16384).\n"
    "System-wide memory free percentage: 66%\n"
)

HERMETIC_HOST_TELEMETRY = {
    ("/usr/bin/vm_stat",): (
        "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
        "Pages free: 1000000.\n"
        "Pages active: 1000000.\n"
        "Pages inactive: 1000000.\n"
        "Pages wired down: 500000.\n"
        "Pages purgeable: 500000.\n"
        "Pages occupied by compressor: 100000.\n"
        "Swapins: 100.\n"
        "Pageouts: 100.\n"
        "Swapouts: 100.\n"
        "Compressions: 100.\n"
    ),
    ("/usr/bin/memory_pressure", "-Q"): THIS_HOST_MEMORY_PRESSURE_Q,
    ("/usr/sbin/sysctl", "vm.swapusage"): (
        "vm.swapusage: total = 4096.00M used = 0.00M free = 4096.00M\n"
    ),
    ("/usr/sbin/sysctl", "-n", "hw.memsize"): f"{16 * GIB}\n",
    ("/usr/sbin/sysctl", "-n", "kern.maxproc"): "4096\n",
    ("/bin/ps", "-axo", "rss="): "100\n200\n",
    ("/bin/ps", "-axo", "state="): "S\nR\n",
    ("/usr/sbin/sysctl", "-n", "vm.loadavg"): "{ 1.00 1.50 2.00 }\n",
}


def hermetic_telemetry_run(command: object) -> str:
    """Return complete healthy telemetry without touching host-only commands."""
    try:
        return HERMETIC_HOST_TELEMETRY[tuple(command)]
    except KeyError as exc:
        raise AssertionError(f"unexpected telemetry command: {tuple(command)!r}") from exc


class MemoryPressureLevelTests(unittest.TestCase):
    """parse_memory_pressure must not invent a level the telemetry never stated.

    It resolved the level with a chain ending `else "normal"`, so ABSENCE of a
    level word was reported as the healthiest possible reading. On this host
    `memory_pressure -Q` never prints a level word at all, which made the
    reading permanently and falsely "normal" -- and made clause 6's
    `pressure_level == "critical"` half dead code that no real telemetry can
    reach. The clause is still exercised at lines 189/273/693, but only with
    synthetic "critical" snapshots, so the suite looked like it covered a gate
    that could not fire.

    Absence now reads "unknown". The gate that actually works on this host is
    clause 6's other half, the free-percentage floor, and these tests pin that
    it still carries the decision.
    """

    @staticmethod
    def _pair(**overrides: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
        second = safe_pair(**overrides)[1]
        return replace(second, captured_at=100.0), second

    def test_absent_level_word_is_not_reported_as_normal(self) -> None:
        """Mutation caught: restoring the `else "normal"` default.

        This is the defect. Reporting unparsed telemetry as the healthiest
        reading is the one answer the parser must never give.
        """
        level, free = admission.parse_memory_pressure(THIS_HOST_MEMORY_PRESSURE_Q)
        self.assertEqual(free, 66.0)
        self.assertNotEqual(level, "normal", "absence of a level was read as healthy")
        self.assertEqual(level, "unknown")

    @unittest.skipUnless(
        sys.platform == "darwin",
        "requires macOS `/usr/bin/memory_pressure`",
    )
    def test_live_host_telemetry_states_no_level(self) -> None:
        """The premise, measured rather than assumed, against the real command.

        If a future macOS starts printing a level under -Q, this test fails and
        whoever sees it can retire the `unknown` path instead of discovering
        years later that the critical gate was never live.
        """
        output = admission._run(("/usr/bin/memory_pressure", "-Q"))
        self.assertIn("System-wide memory free percentage:", output)
        level, _ = admission.parse_memory_pressure(output)
        self.assertEqual(
            level,
            "unknown",
            f"this host now states a pressure level; -Q printed: {output!r}",
        )

    def test_a_stated_level_is_still_read(self) -> None:
        """Mutation caught: collapsing every reading to "unknown".

        Levels are read when the telemetry actually states one, which is what
        keeps clause 6's critical half meaningful on any host that reports it.
        """
        for word, expected in (
            ("critical", "critical"),
            ("warn", "warn"),
            ("normal", "normal"),
        ):
            with self.subTest(word=word):
                output = (
                    f"System-wide memory pressure: {word}\n"
                    "System-wide memory free percentage: 66%\n"
                )
                self.assertEqual(admission.parse_memory_pressure(output)[0], expected)

    def test_an_unknown_level_does_not_make_a_healthy_host_inadmissible(self) -> None:
        """Mutation caught: rejecting "unknown" as corrupt telemetry.

        The level is genuinely unavailable here, not wrong, so refusing to
        dispatch on it would brick every dispatch on this machine -- the same
        defect commit 5ed9d5b7 removed for zero-swap hosts, which is why the
        schema accepts the value rather than the parser lying to satisfy it.
        """
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        result = decide((task,), snapshots=self._pair(pressure_level="unknown"))
        self.assertTrue(result.admitted, result.reasons)
        self.assertNotIn(2, result.failed_clauses)

    def test_unknown_level_still_gates_on_the_free_percentage(self) -> None:
        """Mutation caught: letting "unknown" skip clause 6 entirely.

        With no level to read, the percentage floor is the whole memory gate,
        so it has to keep firing.
        """
        task = candidate("TASK-2026-08-08-0001-one", "claude")
        result = decide(
            (task,),
            snapshots=self._pair(pressure_level="unknown", pressure_free_percent=1.0),
        )
        self.assertFalse(result.admitted)
        self.assertIn(6, result.failed_clauses)


class PressureLevelSysctlTests(unittest.TestCase):
    """The level now comes from the one source on this host that states it.

    `memory_pressure -Q` prints no level, so reading the level from its text
    could only ever yield "unknown" and clause 6's critical half stayed dead.
    `sysctl kern.memorystatus_vm_pressure_level` does state it.

    The 1/2/4 mapping is verified, not assumed:
      - <SDK>/usr/include/dispatch/source.h defines the userspace pressure
        family as DISPATCH_MEMORYPRESSURE_NORMAL 0x01, _WARN 0x02,
        _CRITICAL 0x04.
      - `man 1 memory_pressure` documents exactly two notifiable levels,
        "warn" and "critical", so the system model has three states and is not
        XNU's five-value vm_pressure_level_t (normal/warning/urgent/critical/
        jetsam), whose encoding is 0-based and would disagree.
      - This host reads 1, stably, at 64-66% free and idle. Under the dispatch
        encoding that is "normal"; under the 0-based enum it would be
        "warning", which an idle 66%-free host plainly is not.

    Only 1, 2 and 4 are mapped. Every other value is "unknown" rather than a
    guess, which is also what makes the residual ambiguity safe: if some future
    macOS did switch to the 0-based enum, its normal (0) and critical (3) would
    both read "unknown" and neither would be reported as healthy.
    """

    @staticmethod
    def _pair(**overrides: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
        second = safe_pair(**overrides)[1]
        return replace(second, captured_at=100.0), second

    def test_mapped_levels_match_the_dispatch_header(self) -> None:
        """Mutation caught: renumbering the mapping (e.g. to the 0-based enum)."""
        self.assertEqual(admission.PRESSURE_LEVELS, {1: "normal", 2: "warn", 4: "critical"})
        for value, expected in ((1, "normal"), (2, "warn"), (4, "critical")):
            with self.subTest(value=value):
                self.assertEqual(admission.parse_pressure_level(f"{value}\n"), expected)

    def test_every_unrecognized_value_is_unknown_never_normal(self) -> None:
        """Mutation caught: defaulting an unmapped code to "normal".

        0 and 3 are here deliberately: they are the values the 0-based XNU
        enum would use for normal and critical. Guessing either way would be
        wrong, so neither is guessed.
        """
        for output in ("0", "3", "5", "-1", "", "   ", "garbage", "1 2", "1.5", "0x1"):
            with self.subTest(output=output):
                self.assertEqual(admission.parse_pressure_level(output), "unknown")

    def test_an_unreadable_sysctl_reads_unknown_not_normal(self) -> None:
        """Mutation caught: letting a failed read fall through to health.

        Also pins that a missing sysctl does not raise: raising would fail
        telemetry collection outright and queue every dispatch on clause 2.
        """
        for boom in (
            RuntimeError("telemetry command failed"),
            FileNotFoundError("/usr/sbin/sysctl"),
            PermissionError("denied"),
        ):
            with self.subTest(error=type(boom).__name__):
                with mock.patch.object(admission, "_run", side_effect=boom):
                    self.assertEqual(admission.read_pressure_level(), "unknown")

    @unittest.skipUnless(
        sys.platform == "darwin",
        "requires macOS `/usr/sbin/sysctl` memory-pressure telemetry",
    )
    def test_live_host_reports_a_mapped_level(self) -> None:
        """The premise, measured against the real sysctl on this host."""
        raw = admission._run(("/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"))
        self.assertEqual(raw.strip(), "1", f"host pressure code changed: {raw!r}")
        self.assertEqual(admission.read_pressure_level(), "normal")

    def test_collect_snapshot_takes_its_level_from_the_sysctl(self) -> None:
        """Mutation caught: leaving collect_snapshot on the text level.

        Without this the gate stays dead no matter what the parser returns,
        which is the entire defect.
        """
        with (
            mock.patch.object(admission, "_run", side_effect=hermetic_telemetry_run),
            mock.patch.object(admission, "read_pressure_level", return_value="critical"),
        ):
            snapshot = admission.collect_snapshot(task_path=ROOT)
        self.assertEqual(snapshot.pressure_level, "critical")

    def test_critical_queues_and_never_refuses(self) -> None:
        """Mutation caught: promoting memory backpressure into a refusal.

        Boundary-Blocking Doctrine (shared/protocol.md): a check may block a
        boundary only where the blocked owner can clear it. Waiting clears
        memory pressure, so critical must queue.
        """
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        result = decide((task,), snapshots=self._pair(pressure_level="critical"))
        self.assertFalse(result.admitted)
        self.assertIn(6, result.failed_clauses)
        self.assertEqual(result.action, "queue")


class PressureLevelEndToEndTests(unittest.TestCase):
    """Reach clause 6 the way a real host does, not by hand-building a snapshot.

    Every other test of this clause supplies `pressure_level="critical"`
    directly to safe_pair. That covers the predicate and nothing else, so the
    suite went on looking healthy for the whole time the clause was
    unreachable: no synthetic snapshot can notice that collect_snapshot was
    reading the level from telemetry which never states one.

    These drive the real collection path over complete command-output fixtures.
    Only the pressure sysctl varies; every other command returns stable healthy
    telemetry. The mapping, collect_snapshot's use of it, the schema check and
    the clause all have to agree before the decision comes out right.
    """

    @staticmethod
    def _snapshots_with_sysctl(raw: str) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
        """Real collection path over hermetic telemetry; the sysctl answers `raw`."""

        def run(command: object) -> str:
            if tuple(command) == admission.PRESSURE_LEVEL_SYSCTL:
                return raw
            return hermetic_telemetry_run(command)

        with mock.patch.object(admission, "_run", side_effect=run):
            return admission.collect_live_snapshots(task_path=ROOT, interval=2.0)

    def test_a_critical_sysctl_queues_a_real_dispatch(self) -> None:
        """Mutation caught: disconnecting collect_snapshot from the sysctl.

        Revert collect_snapshot to the -Q text level and this fails at the
        first assertion, because -Q states no level on this host. That is the
        defect, and no hand-built snapshot can catch it.
        """
        first, second = self._snapshots_with_sysctl("4\n")
        self.assertEqual(second.pressure_level, "critical")
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        result = admission._under_admission(
            candidates=(task,), live_attempts=(), live_snapshot=lambda: (first, second)
        )
        self.assertFalse(result.admitted, result.reasons)
        self.assertIn(6, result.failed_clauses)
        # Backpressure the owner clears by waiting, per the Boundary-Blocking
        # Doctrine (shared/protocol.md:697-723). Never a refusal.
        self.assertEqual(result.action, "queue")

    def test_an_unreadable_sysctl_still_admits_a_healthy_host(self) -> None:
        """Mutation caught: turning a failed read into a dispatch-wide block.

        An unreadable sysctl is missing information, not a starved host. If it
        queued, this machine could never dispatch -- 5ed9d5b7's zero-swap bug
        through a different door.
        """
        first, second = self._snapshots_with_sysctl("garbage")
        self.assertEqual(second.pressure_level, "unknown")
        task = candidate("TASK-2026-08-08-0001-one", "claude", "repo-build-test")
        result = admission._under_admission(
            candidates=(task,), live_attempts=(), live_snapshot=lambda: (first, second)
        )
        self.assertTrue(result.admitted, result.reasons)

    @unittest.skipUnless(
        sys.platform == "darwin",
        "requires macOS `/usr/sbin/sysctl`, `/usr/bin/vm_stat`, and `/usr/bin/memory_pressure`",
    )
    def test_the_live_sysctl_reaches_the_snapshot_unchanged(self) -> None:
        """No stub at all: what the host says now is what the snapshot carries."""
        first, second = admission.collect_live_snapshots(task_path=ROOT, interval=2.0)
        self.assertEqual(second.pressure_level, admission.read_pressure_level())
        self.assertIn(second.pressure_level, {"normal", "warn", "critical", "unknown"})
        del first


if __name__ == "__main__":
    unittest.main()
