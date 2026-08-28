#!/usr/bin/env python3
"""Acceptance histories for the OPEN-WORK single-source-of-truth contract.

The 25 fixtures below model the state changes that used to lose work across
tangents, focus changes, closure, restart, and compaction.  Expectations are
written beside each history rather than calculated by the code under test.

Normal execution tests the production writer.  Three opt-in mutation controls
prove the acceptance oracle is strong enough to catch the shipped regressions:

    WORKBOARD_HISTORY_CONTROL=missing-projection # pre-fix OPEN-WORK absence
    WORKBOARD_HISTORY_CONTROL=legacy-file-order  # old capped selection
    WORKBOARD_HISTORY_CONTROL=silent-omission    # omitted-count guard stubbed

Every control must make this file red; none is used by the normal suite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import compaction, decisions, registry, resume, workboard  # noqa: E402


ACTIVE_MARKER = workboard.ACTIVE_MARKER
OPEN_ID = re.compile(r"\[OPEN-WORK-([^\]]+)\]")
BLOCK_OMITTED = re.compile(
    r"\+(\d+) open item\(s\) omitted from this bounded block"
)
BOUND_OMITTED = re.compile(
    r"\((\d+) open item\(s\) omitted for the token bound"
)
CONTROL = os.environ.get("WORKBOARD_HISTORY_CONTROL", "")


def _h(name, events, expected_open, expected_active):
    """Keep fixture expectations visible and independent from the reducer."""
    return {
        "name": name,
        "events": events,
        "expected_open": frozenset(expected_open),
        "expected_active": expected_active,
    }


HISTORIES = (
    _h("01 campaign starts", [("start", "H01-A")], {"H01-A"}, "H01-A"),
    _h(
        "02 tangent mid-campaign",
        [("start", "H02-A"), ("tangent", "H02-B")],
        {"H02-A", "H02-B"},
        "H02-A",
    ),
    _h(
        "03 stacked tangents",
        [("start", "H03-A"), ("tangent", "H03-B"), ("tangent", "H03-C")],
        {"H03-A", "H03-B", "H03-C"},
        "H03-A",
    ),
    _h(
        "04 queued follow-up",
        [("start", "H04-A"), ("queue", "H04-B")],
        {"H04-A", "H04-B"},
        "H04-A",
    ),
    _h(
        "05 explicit focus switch",
        [("start", "H05-A"), ("queue", "H05-B"), ("switch", "H05-B")],
        {"H05-A", "H05-B"},
        "H05-B",
    ),
    _h(
        "06 switch and back",
        [
            ("start", "H06-A"),
            ("tangent", "H06-B"),
            ("switch", "H06-B"),
            ("switch", "H06-A"),
        ],
        {"H06-A", "H06-B"},
        "H06-A",
    ),
    _h(
        "07 tangent while switched",
        [
            ("start", "H07-A"),
            ("tangent", "H07-B"),
            ("switch", "H07-B"),
            ("tangent", "H07-C"),
        ],
        {"H07-A", "H07-B", "H07-C"},
        "H07-B",
    ),
    _h(
        "08 blocked focus hands off",
        [("start", "H08-A"), ("queue", "H08-B"), ("block", "H08-A", "H08-B")],
        {"H08-A", "H08-B"},
        "H08-B",
    ),
    _h(
        "09 blocked item explicitly resumed",
        [
            ("start", "H09-A"),
            ("queue", "H09-B"),
            ("block", "H09-A", "H09-B"),
            ("switch", "H09-A"),
        ],
        {"H09-A", "H09-B"},
        "H09-A",
    ),
    _h(
        "10 active completion advances queue",
        [
            ("start", "H10-A"),
            ("queue", "H10-B"),
            ("complete", "H10-A", "H10-B"),
        ],
        {"H10-B"},
        "H10-B",
    ),
    _h(
        "11 tangent completes without stealing focus",
        [("start", "H11-A"), ("tangent", "H11-B"), ("complete", "H11-B")],
        {"H11-A"},
        "H11-A",
    ),
    _h(
        "12 queued item archives",
        [("start", "H12-A"), ("queue", "H12-B"), ("archive", "H12-B")],
        {"H12-A"},
        "H12-A",
    ),
    _h(
        "13 active item archives with successor",
        [
            ("start", "H13-A"),
            ("queue", "H13-B"),
            ("archive", "H13-A", "H13-B"),
        ],
        {"H13-B"},
        "H13-B",
    ),
    _h(
        "14 plain restart",
        [("start", "H14-A"), ("restart",)],
        {"H14-A"},
        "H14-A",
    ),
    _h(
        "15 restart with parked tangent",
        [("start", "H15-A"), ("tangent", "H15-B"), ("restart",)],
        {"H15-A", "H15-B"},
        "H15-A",
    ),
    _h(
        "16 forced compaction",
        [("start", "H16-A"), ("compact",)],
        {"H16-A"},
        "H16-A",
    ),
    _h(
        "17 compaction with tangent",
        [("start", "H17-A"), ("tangent", "H17-B"), ("compact",)],
        {"H17-A", "H17-B"},
        "H17-A",
    ),
    _h(
        "18 compaction after focus switch",
        [
            ("start", "H18-A"),
            ("queue", "H18-B"),
            ("switch", "H18-B"),
            ("compact",),
        ],
        {"H18-A", "H18-B"},
        "H18-B",
    ),
    _h(
        "19 compaction after block",
        [
            ("start", "H19-A"),
            ("queue", "H19-B"),
            ("block", "H19-A", "H19-B"),
            ("compact",),
        ],
        {"H19-A", "H19-B"},
        "H19-B",
    ),
    _h(
        "20 compaction after completion",
        [
            ("start", "H20-A"),
            ("queue", "H20-B"),
            ("complete", "H20-A", "H20-B"),
            ("compact",),
        ],
        {"H20-B"},
        "H20-B",
    ),
    _h(
        "21 switched tangent completes and focus returns",
        [
            ("start", "H21-A"),
            ("tangent", "H21-B"),
            ("switch", "H21-B"),
            ("complete", "H21-B", "H21-A"),
        ],
        {"H21-A"},
        "H21-A",
    ),
    _h(
        "22 queue switch block and explicit return",
        [
            ("start", "H22-A"),
            ("queue", "H22-B"),
            ("tangent", "H22-C"),
            ("switch", "H22-B"),
            ("block", "H22-B", "H22-C"),
            ("switch", "H22-A"),
        ],
        {"H22-A", "H22-B", "H22-C"},
        "H22-A",
    ),
    _h(
        "23 switch back across two restarts",
        [
            ("start", "H23-A"),
            ("tangent", "H23-B"),
            ("restart",),
            ("switch", "H23-B"),
            ("restart",),
            ("switch", "H23-A"),
        ],
        {"H23-A", "H23-B"},
        "H23-A",
    ),
    _h(
        "24 truncated ledger keeps newest active item",
        [
            ("start", "H24-OLD"),
            *(("queue", f"H24-Q{i:02d}") for i in range(1, 14)),
            ("tangent", "H24-NEXT"),
            ("complete", "H24-OLD", "H24-NEXT"),
        ],
        {
            "H24-Q01", "H24-Q02", "H24-Q03", "H24-Q04", "H24-Q05",
            "H24-Q06", "H24-Q07", "H24-Q08", "H24-Q09", "H24-Q10",
            "H24-Q11", "H24-Q12", "H24-Q13", "H24-NEXT",
        },
        "H24-NEXT",
    ),
    _h(
        "25 cold session after mixed history",
        [
            ("start", "H25-A"),
            ("tangent", "H25-B"),
            ("queue", "H25-C"),
            ("switch", "H25-B"),
            ("block", "H25-B", "H25-A"),
            ("archive", "H25-C"),
            ("compact",),
            ("restart",),
        ],
        {"H25-A", "H25-B"},
        "H25-A",
    ),
)


class WorkboardHistoryAcceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.capsule = self.base / "initial" / "chrono" / "resume.md"
        self.ledger = self.capsule.parent / "OPEN-WORK.md"
        self.capsule.parent.mkdir(parents=True)

        for module, attr, value in (
            (registry, "LIVE_REGISTRY", self.base / "active-tasks.json"),
            (registry, "TASKS_DIR", self.base / "tasks"),
            (decisions, "DECISIONS_FILE", self.base / "decisions.jsonl"),
            (compaction, "SNAP_DIR", self.base / "compaction"),
            (resume, "CAPSULE_PATH", self.capsule),
            (resume, "QUEUE_PATH", self.base / "chrono-queue.md"),
            (resume, "ARCHIVED_DEBT_ROOT", self.base),
        ):
            self.addCleanup(setattr, module, attr, getattr(module, attr))
            setattr(module, attr, value)
        registry.LIVE_REGISTRY.write_text(json.dumps({}))
        self._select_history_paths("initial")

        if CONTROL == "missing-projection":
            patcher = mock.patch.object(resume, "open_work_items", return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)
        elif CONTROL == "legacy-file-order":
            patcher = mock.patch.object(
                resume, "_open_work_lines", side_effect=self._legacy_file_order
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        elif CONTROL == "silent-omission":
            original = resume._open_work_lines

            def silently_drop(items, show_detail):
                return [
                    line
                    for line in original(items, show_detail)
                    if "open item(s) omitted" not in line
                ]

            patcher = mock.patch.object(resume, "_open_work_lines", silently_drop)
            patcher.start()
            self.addCleanup(patcher.stop)
        elif CONTROL:
            self.fail(f"unknown WORKBOARD_HISTORY_CONTROL={CONTROL!r}")

    @staticmethod
    def _legacy_file_order(items, show_detail):
        """The shipped-broken capped selection: oldest rows in file order."""
        if not show_detail:
            return [
                f"- ({len(items)} open item(s) omitted for the token bound — "
                f"regenerate at a higher budget or read {resume.OPEN_WORK_REL})"
            ]
        lines = []
        for item_id, body, next_action in items[: resume.MAX_PROJECTED_OPEN_WORK]:
            row = resume.clip(body or "(no summary)", resume.OPEN_WORK_CLIP)
            if next_action:
                label = "next_action" if ACTIVE_MARKER in body else "resume"
                row += (
                    f"; {label}: "
                    f"{resume.clip(next_action, resume.OPEN_WORK_NEXT_CLIP)}"
                )
            lines.append(f"- {row} [OPEN-WORK-{item_id}]")
        dropped = len(items) - len(lines)
        if dropped:
            lines.append(
                f"- +{dropped} open item(s) omitted from this bounded block — "
                f"read {resume.OPEN_WORK_REL}"
            )
        return lines

    @staticmethod
    def _active_ids(state):
        return {item_id for item_id, status in state.items() if status == "active"}

    def _select_history_paths(self, name):
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        self.capsule = self.base / slug / "chrono" / "resume.md"
        self.ledger = self.capsule.parent / "OPEN-WORK.md"
        self.capsule.parent.mkdir(parents=True, exist_ok=True)
        resume.CAPSULE_PATH = self.capsule
        resume.QUEUE_PATH = self.capsule.parents[1] / "chrono-queue.md"
        resume.ARCHIVED_DEBT_ROOT = self.capsule.parents[2]
        self.event_index = 0

    @staticmethod
    def _resume_action(item_id):
        return f"resume {item_id} from its durable checkpoint"

    def _append(self, kind, **facts):
        self.event_index += 1
        return workboard.append_event(
            kind,
            path=self.ledger,
            event_id=f"EV-{self.event_index:04d}",
            at=f"2026-08-27T00:00:{self.event_index:02d}Z",
            **facts,
        )

    def _section(self, text):
        self.assertIn(
            resume.OPEN_WORK_HEADING,
            text,
            "open work vanished; omission must never read as an empty ledger",
        )
        return text.split(resume.OPEN_WORK_HEADING, 1)[1].split("\n## ", 1)[0]

    def _assert_projection(self, state, expected_active, *, max_tokens=3000):
        projected = workboard.load_workboard(self.ledger, strict=True)
        resume.write_capsule(
            "history", "resume the explicit focus", max_tokens=max_tokens
        )
        text = self.capsule.read_text(encoding="utf-8")
        section = self._section(text)
        expected = set(state)
        parsed_items = resume.open_work_items(self.ledger)
        parsed = {item_id for item_id, _, _ in parsed_items}
        active_parsed = {
            item_id
            for item_id, body, _ in parsed_items
            if ACTIVE_MARKER in (body or "")
        }
        shown = set(OPEN_ID.findall(section))
        active_shown = {
            match.group(1)
            for line in section.splitlines()
            if ACTIVE_MARKER in line and (match := OPEN_ID.search(line))
        }
        declared = BLOCK_OMITTED.search(section) or BOUND_OMITTED.search(section)

        self.assertEqual({item.item_id for item in projected.items}, expected)
        self.assertEqual(projected.active_item_id, expected_active)
        self.assertEqual(projected.next_action, self._resume_action(expected_active))
        self.assertEqual(parsed, expected, "canonical ledger changed its open-item set")
        self.assertLessEqual(shown, expected, "capsule invented an open item")
        if declared:
            self.assertEqual(
                len(shown) + int(declared.group(1)),
                len(expected),
                "capsule omission arithmetic does not preserve the exact open total",
            )
            self.assertIn(str(resume.OPEN_WORK_REL), section)
        else:
            self.assertEqual(shown, expected, "capsule silently dropped an open item")
        self.assertEqual(active_parsed, {expected_active})
        self.assertEqual(len(active_parsed), 1, "canonical ledger must hold one focus")
        # A whole-block token collapse intentionally retains only count+pointer.
        # Whenever rows are itemised (including the 12-row block cap), the sole
        # active row must be among them; that is the shipped file-order defect.
        if not BOUND_OMITTED.search(section):
            self.assertEqual(active_shown, {expected_active})
            self.assertEqual(len(active_shown), 1, "capsule must expose one focus")
        self.assertEqual(
            section.count("next_action:"),
            1,
            "the projection must state exactly one literal next_action",
        )
        self.assertIn(projected.next_action, section)
        return text

    def _apply(self, event, state, session_id):
        kind, *args = event
        before_open = set(state)
        before_active = self._active_ids(state)

        if kind == "start":
            item_id = args[0]
            self.assertFalse(state)
            state[item_id] = "active"
            self._append(
                "start",
                item_id=item_id,
                summary=f"owed: {item_id}",
                why=f"the {item_id} obligation has not reached a terminal event",
                next_action=self._resume_action(item_id),
            )
        elif kind in {"tangent", "queue"}:
            item_id = args[0]
            self.assertNotIn(item_id, state)
            state[item_id] = "queued"
            self._append(
                "queue",
                item_id=item_id,
                summary=f"owed: {item_id}",
                why=f"the {item_id} obligation has not reached a terminal event",
                resume_action=self._resume_action(item_id),
            )
        elif kind == "switch":
            target = args[0]
            self.assertIn(target, state)
            for item_id in before_active:
                state[item_id] = "queued"
            state[target] = "active"
            self._append(
                "switch",
                item_id=target,
                next_action=self._resume_action(target),
            )
        elif kind == "block":
            target, successor = args
            self.assertIn(target, state)
            was_active = state[target] == "active"
            state[target] = "blocked"
            self._append(
                "block",
                item_id=target,
                resume_action=self._resume_action(target),
            )
            if was_active:
                self.assertIn(successor, state)
                state[successor] = "active"
                self._append(
                    "switch",
                    item_id=successor,
                    next_action=self._resume_action(successor),
                )
        elif kind in {"complete", "archive"}:
            target = args[0]
            self.assertIn(target, state)
            was_active = state[target] == "active"
            del state[target]
            self._append(kind, item_id=target)
            if was_active:
                self.assertEqual(len(args), 2, f"{kind} of focus needs a successor")
                successor = args[1]
                self.assertIn(successor, state)
                state[successor] = "active"
                self._append(
                    "switch",
                    item_id=successor,
                    next_action=self._resume_action(successor),
                )
        elif kind == "restart":
            self._append("restart")
        elif kind == "compact":
            self._append("compact")
        else:
            self.fail(f"unknown history event {kind!r}")

        if kind in {"switch", "block", "restart", "compact"}:
            self.assertEqual(set(state), before_open, f"{kind} changed the open set")
        elif kind in {"tangent", "queue", "start"}:
            self.assertEqual(set(state) - before_open, {args[0]})
        elif kind in {"complete", "archive"}:
            self.assertEqual(before_open - set(state), {args[0]})

        self.assertEqual(
            len(self._active_ids(state)),
            1,
            f"{kind} must leave exactly one active item",
        )
        workboard.load_workboard(self.ledger, strict=True)

        if kind == "restart":
            before = workboard.load_workboard(self.ledger, strict=True)
            resume.write_capsule(session_id, "resume the explicit focus")
            after = workboard.load_workboard(self.ledger, strict=True)
            self.assertEqual(
                after.items, before.items, "restart changed canonical open work"
            )
            self.assertEqual(after.next_action, before.next_action)
        elif kind == "compact":
            snapshot = {
                "open_items": sorted(state),
                "active_item": next(iter(self._active_ids(state))),
                "next_action": self._resume_action(next(iter(self._active_ids(state)))),
                "latest_turn": "resume the explicit focus",
            }
            compaction.snapshot(session_id, snapshot)
            self.assertEqual(compaction.recover(session_id), snapshot)
            resume.write_capsule(
                session_id,
                compaction.recover(session_id)["latest_turn"],
            )
            self.assertEqual(
                {
                    item.item_id
                    for item in workboard.load_workboard(self.ledger, strict=True).items
                },
                before_open,
                "forced compaction was treated as a terminal event",
            )

    def _run_history(self, history):
        self._select_history_paths(history["name"])
        state = {}
        session_id = history["name"].split(" ", 1)[0]
        for event in history["events"]:
            self._apply(event, state, session_id)
        self.assertEqual(set(state), set(history["expected_open"]))
        self.assertEqual(self._active_ids(state), {history["expected_active"]})
        text = self._assert_projection(state, history["expected_active"])
        return text, state

    def test_exactly_25_histories_cover_every_required_transition(self):
        self.assertEqual(len(HISTORIES), 25)
        covered = {event[0] for history in HISTORIES for event in history["events"]}
        self.assertTrue(
            {
                "tangent",
                "queue",
                "switch",
                "block",
                "complete",
                "archive",
                "restart",
                "compact",
            }
            <= covered
        )

    def test_every_history_preserves_the_exact_open_set_and_one_focus(self):
        for history in HISTORIES:
            with self.subTest(history=history["name"]):
                self._run_history(history)

    def test_cold_capsule_answers_owed_next_and_why(self):
        history = HISTORIES[-1]
        text, state = self._run_history(history)
        section = self._section(text)
        self.assertEqual(set(OPEN_ID.findall(section)), set(history["expected_open"]))
        self.assertEqual(
            len([line for line in section.splitlines() if ACTIVE_MARKER in line]), 1
        )
        for item_id in state:
            row = next(
                line
                for line in section.splitlines()
                if f"[OPEN-WORK-{item_id}]" in line
            )
            self.assertIn("why:", row)
            if item_id == history["expected_active"]:
                self.assertIn(f"next_action: resume {item_id}", row)
            else:
                self.assertIn(f"resume: resume {item_id}", row)

        tight = self._assert_projection(
            state, history["expected_active"], max_tokens=60
        )
        tight_section = self._section(tight)
        omitted = BOUND_OMITTED.search(tight_section)
        self.assertIsNotNone(omitted, "a squeezed cold capsule must declare omission")
        self.assertEqual(int(omitted.group(1)), len(history["expected_open"]))
        self.assertIn(str(resume.OPEN_WORK_REL), tight_section)

    def test_append_api_preserves_prior_bytes_and_compaction_is_nonterminal(self):
        self._select_history_paths("append-only-control")
        self._append(
            "start",
            item_id="APPEND-A",
            summary="summary mentions ; next: a prose decoy",
            why="the fact remains open",
            next_action="execute the literal fact",
        )
        initial = workboard.load_workboard(self.ledger, strict=True)
        self.assertEqual(initial.next_action, "execute the literal fact")
        before = self.ledger.read_bytes()
        self._append(
            "fold",
            request_id="FOLD-1",
            target_id="APPEND-A",
            summary="incorporate a blocking clarification",
            why="it directly advances the active focus",
            next_action="execute the folded clarification",
        )
        self._append("compact")
        self._append(
            "queue",
            item_id="DROP-1",
            summary="consider a voiced idea later",
            why="the request is separate from the active focus",
            resume_action="decide whether the idea still matters",
        )
        self._append(
            "drop",
            request_id="DROP-1",
            summary="discard a voiced idea",
            why="the operator chose not to track it",
        )
        after = self.ledger.read_bytes()

        self.assertTrue(after.startswith(before), "append_event rewrote prior bytes")
        view = workboard.load_workboard(self.ledger, strict=True)
        self.assertEqual(view.active_item_id, "APPEND-A")
        self.assertEqual(view.next_action, "execute the folded clarification")
        self.assertNotIn("APPEND-A", view.terminal_ids)
        self.assertIn("DROP-1", view.terminal_ids)
        self.assertNotIn(workboard.COMPACTION_KIND, workboard.TERMINAL_KINDS)
        kinds = {
            record.kind
            for record in view.document.records
            if isinstance(record, workboard.WorkEvent)
        }
        self.assertTrue({"fold", "queue", "drop"} <= kinds)

    def test_validator_inverted_controls_reject_each_guarded_break(self):
        with self.subTest(control="missing literal next_action"):
            self._select_history_paths("invalid-missing-next-action")
            self.ledger.write_text(
                "# Open Work\n\n"
                "- workboard-event/v1 event_id=EV-BAD at=2026-08-27T00:00:00Z "
                "kind=start item_id=BAD-A summary=broken why=unfinished\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                workboard.WorkboardConsistencyError, "missing fact.*next_action"
            ):
                workboard.load_workboard(self.ledger, strict=True)

        with self.subTest(control="implicit second active item"):
            self._select_history_paths("invalid-implicit-switch")
            self._append(
                "start",
                item_id="ACTIVE-A",
                summary="first focus",
                why="first focus remains open",
                next_action="continue A",
            )
            self._append(
                "start",
                item_id="ACTIVE-B",
                summary="broken implicit promotion",
                why="second focus should have needed a switch",
                next_action="continue B",
            )
            with self.assertRaisesRegex(
                workboard.WorkboardConsistencyError, "exactly one active item"
            ):
                workboard.load_workboard(self.ledger, strict=True)

        with self.subTest(control="compaction mislabeled terminal"):
            self._select_history_paths("invalid-terminal-set")
            self._append(
                "start",
                item_id="ACTIVE-C",
                summary="survives compaction",
                why="compaction is only a context boundary",
                next_action="continue C",
            )
            self._append("compact")
            with mock.patch.object(
                workboard,
                "TERMINAL_KINDS",
                workboard.TERMINAL_KINDS | {workboard.COMPACTION_KIND},
            ):
                with self.assertRaisesRegex(
                    workboard.WorkboardConsistencyError, "compaction.*nonterminal"
                ):
                    workboard.load_workboard(self.ledger, strict=True)

        with self.subTest(control="duplicate interruption disposition"):
            self._select_history_paths("invalid-duplicate-disposition")
            self._append(
                "start",
                item_id="ACTIVE-D",
                summary="active focus",
                why="the focus remains open",
                next_action="continue D",
            )
            for next_action in ("fold once", "fold twice"):
                self._append(
                    "fold",
                    request_id="REQUEST-DUP",
                    target_id="ACTIVE-D",
                    summary="same interruption",
                    why="the request cannot have two dispositions",
                    next_action=next_action,
                )
            with self.assertRaisesRegex(
                workboard.WorkboardConsistencyError,
                "fold reuses request id REQUEST-DUP",
            ):
                workboard.load_workboard(self.ledger, strict=True)

        with self.subTest(control="multiline fact"):
            with self.assertRaisesRegex(
                workboard.WorkboardConsistencyError, "single-line"
            ):
                workboard.format_event(
                    "start",
                    event_id="EV-MULTILINE",
                    at="2026-08-27T00:00:00Z",
                    item_id="MULTILINE",
                    summary="line one\nline two",
                    why="invalid event shape",
                    next_action="continue",
                )

        with self.subTest(control="indented event silently ignored"):
            self._select_history_paths("invalid-indented-event")
            self.ledger.write_text(
                "# Open Work\n\n"
                "  - workboard-event/v1 event_id=EV-INDENT "
                "at=2026-08-27T00:00:00Z kind=start item_id=INDENT "
                "summary=broken why=hidden next_action=continue\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                workboard.WorkboardConsistencyError, "non-top-level"
            ):
                workboard.load_workboard(self.ledger, strict=True)


class WorkboardMigrationAcceptance(unittest.TestCase):
    """Locked migration controls over the exact legacy/event boundary."""

    LEGACY = (
        "# Open Work\n\n"
        + "\n\n".join(
            before for before, _after in workboard.HEADER_CONTRACT_REPLACEMENTS
        )
        + "\n\nFixture note.\n\n---\n\n"
        "- [x] DONE-1 | completed `evidence.py:7` and the operator's note; "
        "next: retain the evidence\n"
        "- [ ] ACTIVE-1 | **IN PROGRESS — Chrono** preserve quote 'one', "
        "`abc123:9`, and $literal; next: run the exact check\n"
        "- [ ] QUEUE-1 | queued annotation keeps sha `deadbeef` verbatim\n"
        "- [x] Completed historical item without an explicit ID remains exact.\n"
    )

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="workboard-migration-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ledger = self.root / "_state" / "chrono" / "OPEN-WORK.md"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text(self.LEGACY, encoding="utf-8")
        self.ledger.chmod(0o600)

    def _dry_run_and_apply(self):
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(
            workboard.WorkboardMigrationError, "preceding locked dry-run"
        ):
            workboard.migrate_workboard(dry_run=False, path=self.ledger)

        dry_run = workboard.migrate_workboard(dry_run=True, path=self.ledger)
        self.assertEqual(self.ledger.read_bytes(), before, "dry-run wrote the source")
        self.assertEqual(dry_run["outcome"], "dry-run")
        self.assertEqual(dry_run["count_in"], 3)
        self.assertEqual(dry_run["count_out"], 3)
        self.assertEqual(dry_run["dropped"], [])
        self.assertEqual(dry_run["invented"], [])
        self.assertEqual(dry_run["state_changed"], [])
        self.assertEqual(dry_run["text_changed"], [])
        self.assertEqual(dry_run["legacy_checklist_count_in"], 4)
        self.assertEqual(dry_run["legacy_anonymous_rows_preserved"], 1)
        self.assertTrue(dry_run["header_contract_updated"])
        self.assertEqual(
            dry_run["header_contract"], workboard.HEADER_CONTRACT_VERSION
        )
        self.assertEqual(dry_run["active_id_in"], "ACTIVE-1")
        self.assertEqual(dry_run["active_id_out"], "ACTIVE-1")

        applied = workboard.migrate_workboard(
            dry_run=False,
            apply_plan_sha256=dry_run["plan_sha256"],
            path=self.ledger,
        )
        self.assertEqual(applied["outcome"], "applied")
        return before, dry_run, applied

    def test_dry_run_apply_and_applied_byte_census_preserve_every_fact(self):
        before, dry_run, applied = self._dry_run_and_apply()
        self.assertNotEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.ledger.stat().st_mode & 0o777, 0o600)

        audit = workboard.audit_workboard_migration(
            applied["migration_id"], self.ledger
        )
        self.assertTrue(audit["ok"])
        self.assertTrue(audit["state_preserved"])
        self.assertEqual(audit["dropped"], [])
        self.assertEqual(audit["invented"], [])
        self.assertEqual(audit["state_changed"], [])
        self.assertEqual(audit["post_migration_bytes"], 0)
        self.assertEqual(audit["plan_sha256"], dry_run["plan_sha256"])

        projection = workboard.load_workboard(self.ledger, strict=True)
        self.assertEqual(projection.active_item_id, "ACTIVE-1")
        self.assertEqual(projection.next_action, "run the exact check")
        self.assertEqual(
            {item.item_id for item in projection.items}, {"ACTIVE-1", "QUEUE-1"}
        )
        census = workboard.item_census(projection.document)
        self.assertEqual(
            census.checked,
            {"DONE-1": True, "ACTIVE-1": False, "QUEUE-1": False},
        )
        self.assertEqual(
            census.text["ACTIVE-1"],
            "**IN PROGRESS — Chrono** preserve quote 'one', `abc123:9`, "
            "and $literal; next: run the exact check",
        )
        self.assertIn(
            "- [x] Completed historical item without an explicit ID remains exact.\n",
            self.ledger.read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "**Tick items off as they finish",
            self.ledger.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "**Record every state change through",
            self.ledger.read_text(encoding="utf-8"),
        )

    def test_rollback_is_dry_run_gated_and_restores_the_exact_preimage(self):
        before, _dry_run, applied = self._dry_run_and_apply()
        migrated = self.ledger.read_bytes()
        rollback_dry_run = workboard.migrate_workboard(
            dry_run=True,
            rollback_migration_id=applied["migration_id"],
            path=self.ledger,
        )
        self.assertEqual(rollback_dry_run["outcome"], "dry-run")
        self.assertEqual(self.ledger.read_bytes(), migrated)
        rolled_back = workboard.migrate_workboard(
            dry_run=False,
            rollback_migration_id=applied["migration_id"],
            apply_plan_sha256=rollback_dry_run["plan_sha256"],
            path=self.ledger,
        )
        self.assertEqual(rolled_back["outcome"], "rolled-back")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.ledger.stat().st_mode & 0o777, 0o600)

    def test_post_rename_failure_compensates_to_the_exact_original(self):
        before = self.ledger.read_bytes()
        dry_run = workboard.migrate_workboard(dry_run=True, path=self.ledger)
        real_atomic_replace = workboard._atomic_replace_bytes
        failed = False

        def fail_once_after_publish(path, content, mode):
            nonlocal failed
            real_atomic_replace(path, content, mode)
            if content != before and not failed:
                failed = True
                raise OSError("simulated post-rename directory fsync failure")

        with mock.patch.object(
            workboard, "_atomic_replace_bytes", side_effect=fail_once_after_publish
        ):
            with self.assertRaisesRegex(
                workboard.WorkboardMigrationError, "original restored"
            ):
                workboard.migrate_workboard(
                    dry_run=False,
                    apply_plan_sha256=dry_run["plan_sha256"],
                    path=self.ledger,
                )
        self.assertTrue(failed)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_apply_refuses_when_source_changes_after_dry_run(self):
        dry_run = workboard.migrate_workboard(dry_run=True, path=self.ledger)
        changed = self.LEGACY.replace("Fixture note.", "Changed after plan.")
        self.ledger.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(
            workboard.WorkboardMigrationError, "plan changed after dry-run"
        ):
            workboard.migrate_workboard(
                dry_run=False,
                apply_plan_sha256=dry_run["plan_sha256"],
                path=self.ledger,
            )
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), changed)

    def test_apply_plan_hash_binds_the_exact_rendered_body(self):
        before = self.ledger.read_bytes()
        dry_run = workboard.migrate_workboard(dry_run=True, path=self.ledger)
        real_renderer = workboard._migration_events

        def drifted_renderer(row, event_seed, ordinal):
            rendered = real_renderer(row, event_seed, ordinal)
            return rendered.replace(
                workboard.MIGRATION_WHY,
                workboard.MIGRATION_WHY + " (drifted)",
                1,
            )

        with mock.patch.object(
            workboard, "_migration_events", side_effect=drifted_renderer
        ):
            with self.assertRaisesRegex(
                workboard.WorkboardMigrationError, "plan changed after dry-run"
            ):
                workboard.migrate_workboard(
                    dry_run=False,
                    apply_plan_sha256=dry_run["plan_sha256"],
                    path=self.ledger,
                )
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_dry_run_does_not_create_a_missing_parent(self):
        missing = self.root / "absent" / "chrono" / "OPEN-WORK.md"
        self.assertFalse(missing.parent.exists())
        with self.assertRaisesRegex(
            workboard.WorkboardMigrationError, "parent directory does not exist"
        ):
            workboard.migrate_workboard(dry_run=True, path=missing)
        self.assertFalse(missing.parent.exists())

    def test_registry_lock_serializes_append_before_destination_open(self):
        destination = self.ledger.parent / "concurrent.md"
        directory_fd = os.open(self.ledger.parent, os.O_RDONLY)
        self.addCleanup(os.close, directory_fd)
        workboard.fcntl.flock(directory_fd, workboard.fcntl.LOCK_EX)
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import sys; "
                    "from chrono_state import workboard; "
                    "print('ready', flush=True); "
                    "workboard.append_event('queue', path=Path(sys.argv[1]), "
                    "event_id='EV-LOCKED', at='2026-08-27T00:00:00Z', "
                    "item_id='LOCKED-1', summary='serialized writer', "
                    "why='prove the stable registry lock', "
                    "resume_action='continue after migration'); "
                    "print('done', flush=True)"
                ),
                str(destination),
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(PYTHON_DIR),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertEqual(child.stdout.readline().strip(), "ready")
        readable, _writable, _exceptional = select.select(
            [child.stdout], [], [], 0.15
        )
        self.assertEqual(readable, [], "append bypassed the registry lock")
        self.assertFalse(destination.exists(), "append opened before taking the lock")

        workboard.fcntl.flock(directory_fd, workboard.fcntl.LOCK_UN)
        stdout, stderr = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertIn("done", stdout)
        self.assertTrue(destination.is_file())

    def test_inverted_control_drops_one_item_then_restores_and_passes(self):
        before, _dry_run, applied = self._dry_run_and_apply()
        good = self.ledger.read_bytes()
        mutated = "".join(
            line
            for line in good.decode("utf-8").splitlines(keepends=True)
            if "item_id=QUEUE-1" not in line
        ).encode("utf-8")
        mode = self.ledger.stat().st_mode & 0o777
        workboard._atomic_replace_bytes(self.ledger, mutated, mode)
        control = workboard.compare_item_censuses(
            workboard._parse_workboard_text(
                self.ledger, before.decode("utf-8")
            ),
            workboard._parse_workboard_text(
                self.ledger, self.ledger.read_text(encoding="utf-8")
            ),
        )
        self.assertFalse(control["ok"], "the deliberate drop did not fail census")
        self.assertEqual(control["dropped"], ["QUEUE-1"])
        self.assertEqual(control["invented"], [])

        workboard._atomic_replace_bytes(self.ledger, good, mode)
        restored = workboard.audit_workboard_migration(
            applied["migration_id"], self.ledger
        )
        self.assertTrue(restored["ok"])
        self.assertEqual(restored["dropped"], [])
        self.assertEqual(restored["invented"], [])

    def test_rollback_refuses_new_events_but_census_reports_state_change(self):
        _before, _dry_run, applied = self._dry_run_and_apply()
        workboard.append_event(
            "complete",
            path=self.ledger,
            event_id="EV-AFTER-MIGRATION",
            at="2026-08-27T00:01:00Z",
            item_id="QUEUE-1",
        )
        audit = workboard.audit_workboard_migration(
            applied["migration_id"], self.ledger
        )
        self.assertTrue(audit["ok"])
        self.assertFalse(audit["state_preserved"])
        self.assertEqual(
            audit["state_changed"],
            [{"item_id": "QUEUE-1", "before": "unchecked", "after": "checked"}],
        )
        self.assertGreater(audit["post_migration_bytes"], 0)
        with self.assertRaisesRegex(
            workboard.WorkboardMigrationError, "changed after migration"
        ):
            workboard.migrate_workboard(
                dry_run=True,
                rollback_migration_id=applied["migration_id"],
                path=self.ledger,
            )

    def test_migration_requires_one_unchecked_active_item(self):
        for name, replacement, expected in (
            (
                "missing",
                "ACTIVE-1 | no active marker; next: continue",
                "found 0",
            ),
            (
                "second",
                "QUEUE-1 | **IN PROGRESS — Chrono** second active marker",
                "found 2",
            ),
        ):
            with self.subTest(name=name):
                self.ledger.write_text(
                    self.LEGACY.replace(
                        (
                            "ACTIVE-1 | **IN PROGRESS — Chrono** preserve quote "
                            "'one', `abc123:9`, and $literal; next: run the exact check"
                            if name == "missing"
                            else "QUEUE-1 | queued annotation keeps sha `deadbeef` verbatim"
                        ),
                        replacement,
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    workboard.WorkboardMigrationError, expected
                ):
                    workboard.migrate_workboard(dry_run=True, path=self.ledger)


if __name__ == "__main__":
    unittest.main()
