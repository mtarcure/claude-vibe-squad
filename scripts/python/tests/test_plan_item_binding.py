#!/usr/bin/env python3
"""Bind a closed task to the plan items it closes, and refuse to fake completion.

Three properties are under test, in the order the completion protocol states them:

1. A packet MAY declare plan item IDs; declaring none must behave exactly as today.
2. The terminal receipt echoes the DISPATCHER's declaration. A worker cannot add to
   it or widen it, because the echo overwrites the worker's capture rather than
   merging with it.
3. An item marks done only on the full evidence set -- a terminal receipt carrying
   the ID, landed commit ancestry, and a settled anti-affinity APPROVE review. Any
   missing piece leaves the item open.

The negative cases are the point. A completion path that is easier to satisfy than
a failure path is the defect this file exists to prevent.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import board_process_truth as bpt  # noqa: E402
import plan_item_binding as pib  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = REPO_ROOT / "bin" / "send-task.sh"

# Frozen from the two ledger files immediately before commit 38bbec09 deleted
# the optional plans directory. Keeping the real compatibility corpus in this
# test fixture preserves the original ID-shape coverage without making the test
# depend on repository content that is not part of the feature's runtime input.
HISTORICAL_LEDGER_IDS = {
    "v1.1.1-release-plan": tuple(
        """
        P13.50 P13.51 P13.52 P13.56 P13.57 P13.58 P13.53 P13.70 P13.54
        P13.55 P13.62 P13.66 P13.67 P13.69 P13.68 P13.64 P13.65 P14.1
        P13.71 P13.72 P14.3 P14.2 P13.60 P13.61 P10B.2g
        """.split()
    ),
    "v1.1.1-completed-archive": tuple(
        """
        P0.1 P0.2 P0.3 P0.4 P0.5 P0.6 P0.7
        P1.1 P1.2 P1.3 P1.4 P1.5 P1.6 P1.7
        P2.1 P2.2 P2.3 P2.4 P2.5 P2.6 P2.7 P2.8
        P3.1 P3.2 P3.3 P3.4a P3.5 P3.6 P3.7a P3.7b
        P4.1 P4.2 P4.3 P4.4 P4.5 P4.6 P4.7 P4.8 P4.9 P4.9a P4.10
        P5.1 P5.5 P5.7 P5.8
        P6.1 P6.2 P6.3 P6.7
        P7.1 P7.2 P7.3 P7.4 P7.5 P7.6 P7.7
        P8.1 P8.2 P8.3 P8.4 P8.5
        P9.1 P9.2 P9.3 P9.4 P9.5 P9.6
        P10B.5 P11.2 P11.3 P11.5 P11.6 P12.2 P12.3a
        P5.4 P6.4 P6.8 P6.10 P6.11
        P10A.1 P10A.2 P10A.3 P10A.4 P10A.5 P10A.7 P10A.8
        P10B.1 P10B.3 P10B.4 P10B.6 P10B.7 P11.7 P12.3b
        """.split()
    ),
}
HISTORICAL_LEDGER_ITEM_COUNT = 118


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _attempt_files(vault: Path, task: str, attempt: str) -> dict:
    base = vault / "_state" / "board-dispatch" / f"{task}.{attempt}"
    return {
        "dispatch": Path(f"{base}.dispatch.json"),
        "context": Path(f"{base}.context.json"),
        "log": Path(f"{base}.log"),
        "receipt": Path(f"{base}.receipt.json"),
    }


def _descriptor(vault, task, attempt, pid, *, plan_item_ids=None, generation=1) -> dict:
    paths = _attempt_files(vault, task, attempt)
    identity = bpt.observe_process(pid)
    assert identity is not None, "test harness lost its live process"
    descriptor = {
        "schema": "board-dispatch-process/v2",
        "task_id": task,
        "attempt_id": attempt,
        "generation": generation,
        "created_at": "2026-08-11T12:00:00Z",
        **identity,
        "context_path": str(paths["context"]),
        "log_path": str(paths["log"]),
        "receipt_path": str(paths["receipt"]),
    }
    if plan_item_ids is not None:
        descriptor["plan_item_ids"] = plan_item_ids
    return descriptor


class DeclarationTests(unittest.TestCase):
    """A packet MAY declare items. Undeclared packets behave exactly as today."""

    def test_absent_declaration_is_an_empty_list_not_an_error(self):
        # The guard against the obvious failure: most packets declare nothing, and
        # a strict default here would break every existing flow.
        self.assertEqual(pib.canonical_plan_item_ids(None), [])
        self.assertEqual(pib.canonical_plan_item_ids([]), [])

    def test_declaration_preserves_order_and_accepts_real_item_shapes(self):
        self.assertEqual(
            pib.canonical_plan_item_ids(["P4.4", "P3.7b", "P12", "P10A.1", "P10B.7"]),
            ["P4.4", "P3.7b", "P12", "P10A.1", "P10B.7"],
        )

    def test_id_shape_covers_historical_ledger_fixture(self):
        """The shape is derived from the deleted ledger, so preserve its corpus.

        A first draft of PLAN_ITEM_RE omitted the uppercase phase suffix and
        silently made all fourteen P10A/P10B items impossible to declare. The
        failure was invisible -- those items simply never matched. The fixture
        carries all 118 real P-item IDs from the two files as they existed
        immediately before commit 38bbec09, including P10B.2g.
        """
        with tempfile.TemporaryDirectory() as directory:
            plans = Path(directory)
            for name, item_ids in HISTORICAL_LEDGER_IDS.items():
                fixture_lines = [
                    f"- [ ] **{item_id}** Fixture item." for item_id in item_ids
                ]
                fixture_lines.extend(
                    (
                        "- [ ] G1 Release-checklist entry outside the P namespace.",
                        "- [ ] Defer The unnumbered carry-forward action.",
                    )
                )
                (plans / f"{name}.md").write_text(
                    "\n".join(fixture_lines) + "\n", encoding="utf-8"
                )

            checked = 0
            for name in HISTORICAL_LEDGER_IDS:
                path = plans / f"{name}.md"
                for line in path.read_text(encoding="utf-8").splitlines():
                    match = pib.CHECKBOX_RE.match(line)
                    if not match:
                        continue
                    # Strip Markdown emphasis. The 2026-08-15 consolidation
                    # bolded every item id, so the raw token became
                    # "**P13.52" and stopped matching -- the ids had not
                    # drifted, the reader had.
                    token = match.group(1).strip("*`")
                    if token == "Defer":
                        continue
                    # Release-checklist entries (G1-G7, R1-R10, MERGE) are not
                    # declarable plan items. Guard the P namespace strictly.
                    if not (token[:1] == "P" and token[1:2].isdigit()):
                        continue
                    checked += 1
                    self.assertRegex(
                        token, pib.PLAN_ITEM_RE, f"unmatched item id in {name}"
                    )
            self.assertEqual(checked, HISTORICAL_LEDGER_ITEM_COUNT)
            self.assertGreaterEqual(
                checked, 110, "historical fixture shrank; re-derive the ID shape"
            )

    def test_malformed_declarations_fail_closed(self):
        for value in (
            ["P4.4", "P4.4"],  # duplicate
            ["4.4"],  # missing the P
            ["P4.4 "],  # untrimmed
            ["P4.4; rm -rf /"],  # shell/path injection shape
            ["../../etc/passwd"],
            [""],
            ["P" + "9" * 40],
            ["P4.4\nP5.5"],
            [4.4],
            "P4.4",  # a bare string is not a list
            [f"P{index}.1" for index in range(pib.MAX_DECLARED_ITEMS + 1)],
        ):
            with self.subTest(value=value):
                with self.assertRaises(pib.PlanItemBindingError):
                    pib.canonical_plan_item_ids(value)

    def test_send_task_declaration_helper_reports_canonical_json(self):
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "python" / "plan_item_binding.py"),
                "declare",
                "--json",
                '["P4.4","P3.7b"]',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["P4.4", "P3.7b"])

    def test_send_task_declaration_helper_refuses_a_bad_id(self):
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "python" / "plan_item_binding.py"),
                "declare",
                "--json",
                '["not-an-item"]',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_send_task_reads_the_declaration_from_packet_frontmatter(self):
        """The declaration site must actually be wired, not merely available."""
        text = SEND_TASK.read_text(encoding="utf-8")
        self.assertIn('task_frontmatter_field "plan_item_ids"', text)
        self.assertIn("BOARD_PLAN_ITEM_IDS_JSON", text)
        self.assertIn('"plan_item_ids"', text)


class PacketPhaseBindingTests(unittest.TestCase):
    """One packet fact resolves to one canonical declaration at admission."""

    def test_detailed_phase_derives_a_binding_when_declaration_is_absent(self):
        self.assertEqual(
            pib.resolve_packet_plan_item_ids(
                [], phase="P13.52", declaration_present=False
            ),
            ["P13.52"],
        )

    def test_free_form_phase_is_rejected_when_declaration_is_absent(self):
        for phase in ("B1", "V1", "P13.F1", "--help"):
            with self.subTest(phase=phase):
                with self.assertRaises(pib.PlanItemBindingError):
                    pib.resolve_packet_plan_item_ids(
                        [], phase=phase, declaration_present=False
                    )

    def test_explicit_declaration_wins_even_when_empty(self):
        # Presence, not truthiness, carries the override. An explicit [] is a
        # deliberate request to leave this packet unbound.
        self.assertEqual(
            pib.resolve_packet_plan_item_ids(
                [], phase="B1", declaration_present=True
            ),
            [],
        )
        self.assertEqual(
            pib.resolve_packet_plan_item_ids(
                ["P13.54"], phase="P13.52", declaration_present=True
            ),
            ["P13.54"],
        )

    def test_bare_canonical_phase_remains_accepted_but_unbound(self):
        # P13 names a work grouping, not the one detailed item this packet
        # closes. Keeping it unbound avoids turning a common phase label into a
        # claim that any one P13 task completed the whole phase.
        self.assertEqual(
            pib.resolve_packet_plan_item_ids(
                [], phase="P13", declaration_present=False
            ),
            [],
        )

    def test_absent_phase_and_declaration_preserve_legacy_unbound_behavior(self):
        for phase in ("", "none"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    pib.resolve_packet_plan_item_ids(
                        [], phase=phase, declaration_present=False
                    ),
                    [],
                )


class ActivePlanAuthorityTests(unittest.TestCase):
    """Optional discovery and strict cardinality retain separate contracts."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plans = Path(self.temporary.name) / "docs" / "superpowers" / "plans"
        self.plans.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _plan(self, name: str, status_line: str, body: str = "") -> Path:
        path = self.plans / name
        path.write_text(
            f"# {name}\n\n{status_line}\n\n{body}\n", encoding="utf-8"
        )
        return path

    def test_exactly_one_active_authority_passes(self):
        active = self._plan("implementation.md", "**Status:** active")
        self._plan(
            "history.md",
            "**Status:** HISTORICAL",
            "This file refers to the active plan without claiming its status.\n"
            "\n## Recorded task\n\n**Status:** active",
        )
        self._plan(
            "spec.md",
            "**Status:** SPEC",
            "The single active plan is implementation.md.",
        )
        self.assertEqual(
            pib.require_single_active_plan_authority(self.plans), active
        )
        self.assertTrue(active.is_file())

    def test_two_active_authorities_fail_and_name_both_claimants(self):
        first = self._plan("implementation.md", "**Status:** active")
        second = self._plan("handoff.md", "status: ACTIVE")
        with self.assertRaises(pib.PlanItemBindingError) as caught:
            pib.require_single_active_plan_authority(self.plans)
        message = str(caught.exception)
        self.assertIn(first.name, message)
        self.assertIn(second.name, message)

    def test_zero_active_authorities_fails_closed(self):
        self._plan("history.md", "**Status:** historical")
        with self.assertRaisesRegex(
            pib.PlanItemBindingError, "exactly one active plan authority; found 0"
        ):
            pib.require_single_active_plan_authority(self.plans)

    def test_missing_optional_directory_means_no_active_authorities(self):
        missing = self.plans / "not-created"
        self.assertFalse(missing.exists())
        self.assertEqual(pib.active_plan_authorities(missing), [])
        with self.assertRaisesRegex(
            pib.PlanItemBindingError, "exactly one active plan authority; found 0"
        ):
            pib.require_single_active_plan_authority(missing)

    def test_existing_non_directory_path_fails_closed(self):
        not_a_directory = self.plans / "plan.md"
        not_a_directory.write_text("# Not a directory\n", encoding="utf-8")
        with self.assertRaisesRegex(
            pib.PlanItemBindingError, "plans path is not a directory"
        ):
            pib.active_plan_authorities(not_a_directory)

    def test_unreadable_plans_path_fails_closed(self):
        denied = self.plans / "denied"
        with mock.patch.object(Path, "stat", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(
                pib.PlanItemBindingError, "cannot inspect plans path"
            ):
                pib.active_plan_authorities(denied)


class ReceiptEchoTests(unittest.TestCase):
    """The receipt echoes the dispatcher's declaration; a worker cannot widen it."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary.name).resolve()
        self.live = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)

    def tearDown(self):
        if self.live.poll() is None:
            self.live.kill()
        self.live.wait()
        self.temporary.cleanup()

    def _finalize(self, *, declared, captured):
        task, attempt = "TASK-2026-08-11-0640-plan-item-binding", "d-" + "a" * 32
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(
            self.vault, task, attempt, self.live.pid, plan_item_ids=declared
        )
        _write_json(paths["dispatch"], descriptor)
        _write_json(paths["context"], {"authority": {"task_id": task}})
        paths["log"].write_text("", encoding="utf-8")
        raw = self.vault / "capture.json"
        capture = {"status": "launched", "response_status": "complete"}
        if captured is not None:
            capture["plan_item_ids"] = captured
        _write_json(raw, capture)
        return bpt.finalize_receipt(str(raw), str(paths["dispatch"]), paths["receipt"])

    def test_receipt_echoes_the_declared_ids(self):
        receipt = self._finalize(declared=["P4.4"], captured=None)
        self.assertEqual(receipt["plan_item_ids"], ["P4.4"])
        self.assertEqual(receipt["terminal_outcome"], "complete")

    def test_worker_cannot_widen_the_declared_set(self):
        # The load-bearing property. A worker that could name its own completions
        # could mark anything done.
        receipt = self._finalize(
            declared=["P4.4"], captured=["P4.4", "P5.2", "P6.1", "P12.24"]
        )
        self.assertEqual(receipt["plan_item_ids"], ["P4.4"])

    def test_worker_cannot_add_ids_to_an_undeclared_packet(self):
        receipt = self._finalize(declared=None, captured=["P5.2"])
        self.assertEqual(receipt["plan_item_ids"], [])

    def test_worker_cannot_substitute_a_different_item(self):
        receipt = self._finalize(declared=["P4.4"], captured=["P5.2"])
        self.assertEqual(receipt["plan_item_ids"], ["P4.4"])

    def test_undeclared_packet_receipt_is_otherwise_unchanged(self):
        receipt = self._finalize(declared=None, captured=None)
        self.assertEqual(receipt["plan_item_ids"], [])
        self.assertEqual(receipt["terminal_outcome"], "complete")
        self.assertEqual(receipt["schema"], "board-dispatch-receipt/v2")

    def test_a_malformed_descriptor_declaration_is_refused(self):
        task, attempt = "TASK-2026-08-11-0640-plan-item-binding", "d-" + "b" * 32
        paths = _attempt_files(self.vault, task, attempt)
        descriptor = _descriptor(
            self.vault, task, attempt, self.live.pid, plan_item_ids=["not-an-item"]
        )
        _write_json(paths["dispatch"], descriptor)
        self.assertEqual(
            bpt.descriptor_error(str(paths["dispatch"]), descriptor, require_v2=True),
            "descriptor_plan_item_ids",
        )


class _Ledger:
    """A throwaway repo with a plan file, a history file, and real Git history."""

    def __init__(self, root: Path):
        self.root = root
        self.plans = root / "docs" / "superpowers" / "plans"
        self.plans.mkdir(parents=True, exist_ok=True)
        self.plan = self.plans / "plan.md"
        self.history = self.plans / "history.md"
        self.plan.write_text(
            "# Remaining\n"
            "\n"
            "## Remaining detailed items\n"
            "\n"
            "- [ ] P4.4 Log recall/record events with engagement and applied policy,\n"
            "      returning note IDs and a result.\n"
            "- [ ] P5.2 Resolve every required skill to one implementation.\n",
            encoding="utf-8",
        )
        self.history.write_text(
            "# History\n\n## Completed\n\n- [x] P1.1 An earlier item.\n",
            encoding="utf-8",
        )

    def commit(self, task_id: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        run = lambda *args: subprocess.run(  # noqa: E731
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        if not (self.root / ".git").exists():
            run("init", "-q", "-b", "main")
        run("add", "-A")
        run("commit", "-q", "-m", f"board integrate {task_id}")
        return run("rev-parse", "HEAD").stdout.strip()


def _settled_entry(task_id: str, receipt_path: Path, **overrides) -> dict:
    entry = {
        "status": "complete",
        "to_model": "claude",
        "author_family": "claude",
        "review_model": "gpt-codex",
        "mandatory_review": "true",
        "delivery_attempt_id": "d-" + "c" * 32,
        "delivery_generation": 1,
        "terminal_receipt_path": str(receipt_path),
        "review_settled_by": "chrono-explicit",
        "cross_family_review_ref": "departments/coding/outbox/%s-review-response.md" % task_id,
        "verdict": "APPROVE",
        "write_scope": ["docs/superpowers/plans"],
    }
    entry.update(overrides)
    return entry


class MarkingRuleTests(unittest.TestCase):
    """An item marks done only on receipt + commit ancestry + review. Else open."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.ledger = _Ledger(self.root)
        self.task = "TASK-2026-08-11-0290-p4-memory-audit-trail"
        self.receipt = self.root / "_state" / "board-dispatch" / "receipt.json"
        _write_json(
            self.receipt,
            {
                "schema": "board-dispatch-receipt/v2",
                "task_id": self.task,
                "attempt_id": "d-" + "c" * 32,
                "generation": 1,
                "terminal_outcome": "complete",
                "completed_at": "2026-08-11T04:41:50Z",
                "plan_item_ids": ["P4.4"],
            },
        )
        self.commit = self.ledger.commit(self.task)

    def tearDown(self):
        self.temporary.cleanup()

    def _decide(self, entry=None, item="P4.4"):
        return pib.decide(
            item,
            self.task,
            entry if entry is not None else _settled_entry(self.task, self.receipt),
            repo_root=self.root,
            git_ref="HEAD",
        )

    def test_full_evidence_marks_done(self):
        decision = self._decide()
        self.assertTrue(decision.done, decision.missing)
        self.assertEqual(decision.missing, [])
        self.assertEqual(decision.evidence["commit"], self.commit)
        self.assertEqual(decision.evidence["receipt_outcome"], "complete")
        self.assertEqual(decision.evidence["verdict"], "APPROVE")

    def test_receipt_without_review_stays_open(self):
        # The exact live shape of P4.4 today: a terminal receipt and a landed
        # commit, closed by a Chrono attestation rather than a settled review.
        entry = _settled_entry(self.task, self.receipt)
        for key in ("review_settled_by", "cross_family_review_ref", "verdict"):
            entry.pop(key)
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("review_not_settled", decision.missing)

    def test_same_family_review_stays_open(self):
        entry = _settled_entry(self.task, self.receipt, review_model="claude")
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("review_not_cross_family", decision.missing)

    def test_non_approve_verdict_stays_open(self):
        entry = _settled_entry(self.task, self.receipt, verdict="REJECT")
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("review_not_approved", decision.missing)

    def test_missing_commit_ancestry_stays_open(self):
        entry = _settled_entry(self.task, self.receipt)
        decision = pib.decide(
            "P4.4", "TASK-2026-08-11-9999-never-landed", entry,
            repo_root=self.root, git_ref="HEAD",
        )
        self.assertFalse(decision.done)
        self.assertIn("commit_ancestry_missing", decision.missing)

    def test_receipt_that_does_not_declare_the_item_stays_open(self):
        decision = self._decide(item="P5.2")
        self.assertFalse(decision.done)
        self.assertIn("receipt_does_not_declare_item", decision.missing)

    def test_blocked_receipt_stays_open(self):
        _write_json(
            self.receipt,
            {
                "schema": "board-dispatch-receipt/v2",
                "task_id": self.task,
                "attempt_id": "d-" + "c" * 32,
                "generation": 1,
                "terminal_outcome": "blocked",
                "completed_at": "2026-08-11T04:41:50Z",
                "plan_item_ids": ["P4.4"],
            },
        )
        decision = self._decide()
        self.assertFalse(decision.done)
        self.assertIn("receipt_outcome_not_terminal_success", decision.missing)

    def test_receipt_belonging_to_another_attempt_stays_open(self):
        entry = _settled_entry(
            self.task, self.receipt, delivery_attempt_id="d-" + "d" * 32
        )
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("receipt_identity_mismatch", decision.missing)

    def test_absent_receipt_stays_open(self):
        entry = _settled_entry(self.task, self.root / "nope.json")
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("receipt_missing", decision.missing)

    def test_unsettled_task_stays_open(self):
        entry = _settled_entry(self.task, self.receipt, status="in-flight")
        decision = self._decide(entry)
        self.assertFalse(decision.done)
        self.assertIn("task_not_settled", decision.missing)


class LedgerMoveTests(unittest.TestCase):
    """The move appends to history first, then removes from the plan."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.ledger = _Ledger(self.root)
        self.task = "TASK-2026-08-11-0290-p4-memory-audit-trail"
        self.evidence = {
            "task_id": self.task,
            "commit": "0" * 40,
            "receipt_path": "_state/board-dispatch/x.receipt.json",
            "receipt_outcome": "complete",
            "review_ref": "departments/coding/outbox/r-response.md",
            "verdict": "APPROVE",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _move(self, item="P4.4"):
        return pib.move_item(
            item, self.evidence, plan=self.ledger.plan, history=self.ledger.history
        )

    def test_move_transfers_the_exact_item_block(self):
        block = pib.find_item_block(self.ledger.plan.read_text(encoding="utf-8"), "P4.4")
        self.assertTrue(self._move())
        plan = self.ledger.plan.read_text(encoding="utf-8")
        history = self.ledger.history.read_text(encoding="utf-8")
        self.assertNotIn("P4.4", plan)
        self.assertIn("P5.2", plan)
        # The item text crosses unchanged except for the checkbox mark.
        self.assertIn(block.replace("- [ ] P4.4", "- [x] P4.4", 1), history)
        self.assertIn(self.evidence["commit"], history)
        self.assertIn(self.evidence["review_ref"], history)

    def test_move_is_idempotent_on_restart(self):
        self.assertTrue(self._move())
        first = self.ledger.history.read_text(encoding="utf-8")
        self.assertFalse(self._move())
        self.assertEqual(self.ledger.history.read_text(encoding="utf-8"), first)

    def test_move_refuses_an_item_that_is_open_in_neither_file(self):
        with self.assertRaises(pib.PlanItemBindingError):
            self._move(item="P99.9")

    def test_move_refuses_when_history_records_conflicting_evidence(self):
        self.assertTrue(self._move())
        with self.assertRaises(pib.PlanItemBindingError):
            pib.move_item(
                "P4.4",
                {**self.evidence, "commit": "1" * 40},
                plan=self.ledger.plan,
                history=self.ledger.history,
            )

    def test_history_is_written_before_the_plan_is_shortened(self):
        # A crash may leave a duplicate, never a lost item.
        order = []
        original = pib.atomic_write

        def recording(path, text):
            order.append(Path(path).name)
            return original(path, text)

        pib.atomic_write = recording
        try:
            self._move()
        finally:
            pib.atomic_write = original
        self.assertEqual(order, ["history.md", "plan.md"])

    def test_plan_and_history_partition_stays_exclusive(self):
        self._move()
        plan_ids = pib.checkbox_item_ids(self.ledger.plan.read_text(encoding="utf-8"))
        history_ids = pib.checkbox_item_ids(
            self.ledger.history.read_text(encoding="utf-8")
        )
        self.assertEqual(set(plan_ids) & set(history_ids), set())


if __name__ == "__main__":
    unittest.main()
