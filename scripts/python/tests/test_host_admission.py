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
            {"anthropic", "openai", "google", "moonshot"},
        )
        for lane in ("claude", "codex", "gemini", "kimi"):
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
            (safe_pair(pageouts=101), 3),
            (safe_pair(pressure_level="critical"), 6),
            (safe_pair(pressure_free_percent=10.0), 6),
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, decide((task,), snapshots=snapshots).failed_clauses)
        unknown = replace(task, workload_class="unknown")
        self.assertIn(4, decide((unknown,)).failed_clauses)

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
            ("thrashing: swap is actively growing", dict(swapouts=101), 3),
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

    def test_single_fanout_and_swarm_use_whole_vector_without_public_recursion(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        self.assertIn('board_host_admit "$ACTUAL_TASK_FILE"', sender)
        self.assertIn('board_host_admit "${BOARD_FANOUT_PACKETS[@]}"', sender)
        self.assertIn('board_host_admit "${BOARD_BATCH_TASKS[@]}"', sender)
        self.assertNotIn('bash "$0" "$member_packet"', sender)
        self.assertNotIn('bash "$0" "${INBOX}/${child_id}.md"', sender)
        self.assertIn('send_task_main "$packet"', sender)
        self.assertEqual(sender.count('board_host_admit "${BOARD_FANOUT_PACKETS[@]}"'), 1)
        self.assertEqual(sender.count('board_host_admit "${BOARD_BATCH_TASKS[@]}"'), 1)
        helper = sender.split("dispatch_admitted_child() (", 1)[1].split("\n)\n", 1)[0]
        self.assertNotIn("board_host_admit", helper)
        self.assertLess(
            sender.index('board_host_admit "${BOARD_BATCH_TASKS[@]}"'),
            sender.index('--register-swarm "$TASK_ID"'),
        )
        self.assertLess(
            sender.index('ln "$child_temp" "$child_dest"'),
            sender.index('--register-swarm "$TASK_ID"'),
        )
        self.assertNotIn("mark-swarm-publication-failed", sender)

    def test_final_staging_bytes_are_admitted_immediately_before_publication(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        publication = sender.split("# ── ITEM 4: inject toolkit", 1)[1]
        self.assertLess(
            publication.index('board_host_admit "$ACTUAL_TASK_FILE"'),
            publication.index('DEST="${INBOX}/${TASK_ID}.md"'),
        )
        self.assertIn('prepare_admission_child "$member_packet"', sender)
        self.assertLess(
            sender.index('prepare_admission_child "$member_packet"'),
            sender.index('board_host_admit "${BOARD_FANOUT_PACKETS[@]}"'),
        )
        self.assertIn('cmp -s "$ACTUAL_TASK_FILE" "$INBOX_TEMP"', sender)
        self.assertIn('cmp -s "$child_source" "$child_temp"', sender)
        self.assertIn('cmp -s "$child_source" "$child_dest"', sender)
        self.assertIn("--candidate", sender)
        self.assertIn("--vector-sha256", sender)
        self.assertIn('admitted_packet_bytes "$child_temp" "$swarm_publish_index"', sender)

    def test_external_environment_and_argv_cannot_mark_a_batch_admitted(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        reset = next(line for line in sender.splitlines() if "BOARD_BATCH_ADMITTED=0" in line)
        completed = subprocess.run(
            ["bash", "-c", reset + '\nprintf "%s\\n" "$BOARD_BATCH_ADMITTED"'],
            env={"BOARD_BATCH_ADMITTED": "1", "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual((completed.returncode, completed.stdout), (0, "0\n"))
        arg_parser = sender.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
        self.assertNotIn("BATCH_ADMITTED", arg_parser)

    def test_internal_child_is_subshell_isolated_and_propagates_failure(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        start = sender.index("dispatch_admitted_child() (")
        helper = sender[start:sender.index("\n)\n", start) + 3]
        harness = f'''BOARD_BATCH_ADMITTED=0
BOARD_PRE_REGISTERED=0
BOARD_PACKET_FINAL=0
parent_state=clean
send_task_main() {{
    printf 'child=%s:%s:%s:%s\n' "$BOARD_BATCH_ADMITTED" "$BOARD_PRE_REGISTERED" "$BOARD_PACKET_FINAL" "$1"
    parent_state=changed
    return 23
}}
{helper}
dispatch_admitted_child 1 packet.md 0
status=$?
printf 'parent=%s:%s:%s:%s status=%s\n' "$BOARD_BATCH_ADMITTED" "$BOARD_PRE_REGISTERED" "$BOARD_PACKET_FINAL" "$parent_state" "$status"
'''
        completed = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            ["child=1:1:1:packet.md", "parent=0:0:0:clean status=23"],
        )

    def test_child_reuses_main_without_reexecuting_top_level_setup(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        prefix, main = sender.split("send_task_main() {", 1)
        self.assertIn("source ", prefix)
        self.assertIn("parse_task_frontmatter", main)
        self.assertNotIn("repo-root.sh", main)
        self.assertNotIn("set -euo pipefail", main)
        self.assertNotIn("trap ", main)
        self.assertLess(prefix.index("BOARD_BATCH_ADMITTED=0"), prefix.index("board_host_admit()"))

    def test_production_loc_caps(self) -> None:
        host_lines = (PYTHON_DIR / "host_admission.py").read_text(encoding="utf-8").splitlines()
        # Ratchet follows the shrink: 475 -> 474 when clause 5 merged into clause 6.
        self.assertLessEqual(len(host_lines), 474)
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        # Measured 2026-08-11 after plan-item binding: 2,385 non-blank lines.
        # The seventeen-line increase is the declaration half of the completion
        # protocol -- one optional `plan_item_ids` frontmatter field, validated by
        # the shared scripts/python/plan_item_binding.py and carried into the board
        # dispatch descriptor, which is what lets a closed task mark a plan item.
        # It had to land here because the consuming half (the receipt echo) is
        # worthless without a declaration site. The prior 2,368 baseline came from
        # review-class propagation; the 2,277 before it never described a real
        # state.
        #
        # Measured 2026-08-15: 2,443. The fifty-eight-line increase is two
        # dispatch-time refusals, both closing failures that were previously
        # SILENT -- which is why they belong in the sender rather than downstream:
        #   * structural write_scope. A packet naming .git or .githooks reads as
        #     authorization but is a guaranteed total loss -- the isolation layer
        #     refuses the worker's commit regardless of scope and discards the
        #     WHOLE lane's output. Lane 6200 lost a complete documentation pass.
        #     The segment set is imported from worktree_isolation, never restated.
        #   * linked-worktree dispatch. `_state/` is gitignored, so running from a
        #     worktree created a STUB registry and the write_scope conflict check
        #     compared against one entry instead of ~1,900, reporting "no
        #     conflicts" because it could no longer see any. Lane 6100 also died
        #     at integration when its base branch was rebased underneath it.
        # Roughly two-thirds of the increase is the explanatory comments above
        # each guard; the executable additions are ~20 lines.
        # This remains an exact ratchet baseline with no headroom.
        self.assertLessEqual(sum(bool(line.strip()) for line in sender.splitlines()), 2443)


if __name__ == "__main__":
    unittest.main()
