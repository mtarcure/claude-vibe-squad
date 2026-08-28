#!/usr/bin/env python3
"""Resume canary — Phase 1 acceptance gate.

Proves that a confirmed decision, an open task, a superseding decision, and the exact
recent operator request all survive a simulated /compact + restart, recovered ONLY from
the append-only journals + snapshot (no history replay).

`CapsuleFreshnessCanary` guards the second failure mode, which is the one that actually
occurred: the capsule did not crash, it silently went stale for ten days while
`render_capsule` kept succeeding. A test that only asserts "renders without error"
passes throughout that. These assert the capsule's task set against the live registry's
live set, so divergence fails loudly.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
for entry in (str(ROOT), str(PYTHON_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from chrono_state import registry, decisions, compaction, resume  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)

TASK_REF = re.compile(r"\[(TASK-[^\]]+)\]")
OMITTED = re.compile(r"\(\+(\d+) more live")

# The live board writes a dict keyed by task id. EXPECTED_LIVE is written out by hand
# rather than derived from the loader — a canary that computes its expectation with the
# code under test can only prove the code agrees with itself.
LIVE_FIXTURE = {
    "TASK-2026-08-05-0001-alpha": {"status": "in-flight", "specialist": "planner"},
    "TASK-2026-08-05-0002-bravo": {"status": "review-required", "specialist": "skeptic"},
    "TASK-2026-08-05-0003-charlie": {"status": "queued", "specialist": "triage"},
    "TASK-2026-08-05-0004-delta": {"status": "complete", "specialist": "planner"},
    "TASK-2026-08-05-0005-echo": {"status": "closed", "specialist": "planner"},
    "TASK-2026-08-05-0006-foxtrot": {"status": "blocked", "specialist": "planner"},
    "TASK-2026-08-05-0007-golf": {"status": "superseded", "specialist": "planner"},
}
EXPECTED_LIVE = {
    "TASK-2026-08-05-0001-alpha",
    "TASK-2026-08-05-0002-bravo",
    "TASK-2026-08-05-0003-charlie",
}
# Deferred work is itemised in its own capsule section (0230 review: a count
# line is not a task line), so the fixture's blocked task must appear too.
EXPECTED_DEFERRED = {"TASK-2026-08-05-0006-foxtrot"}
DEFERRED_OMITTED = re.compile(r"\(\+(\d+) more deferred")
PENDING_OMITTED = re.compile(r"\((\d+) group\(s\) omitted for the token bound")


class TestResumeCanary(unittest.TestCase):
    def test_decision_task_supersession_survive_compact(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            decisions.DECISIONS_FILE = base / "decisions.jsonl"
            compaction.SNAP_DIR = base / "snap"
            registry.TASKS_DIR = base / "tasks"
            registry.LIVE_REGISTRY = base / "active-tasks.json"
            # Isolation (fix round 2): without this, pending_completions() reads
            # this HOST's real _state/chrono-queue.md — a path that doesn't exist
            # under `base` returns [], matching this test's fixture reality.
            resume.QUEUE_PATH = base / "chrono-queue.md"
            (base / "tasks").mkdir()
            (base / "tasks" / "active.json").write_text(
                '[{"id": "TASK-9", "state": "blocked", "next_action": "retry phase 2"}]'
            )
            # the open task now comes from the registry the board actually feeds
            (base / "active-tasks.json").write_text(
                json.dumps({"TASK-9": {"status": "in-flight", "specialist": "planner"}})
            )

            # confirm a decision, then supersede it (mirrors this very session)
            d1 = decisions.record("cap is 2", "confirmed", ["turn-1"])
            decisions.record(
                "no fixed cap; dynamic gate", "confirmed", ["turn-9"], supersedes=[d1]
            )

            # externalize load-bearing state (what compact-now does before /compact)
            compaction.snapshot(
                "sess-1",
                {"next_action": "resume phase 2", "latest_turn": "write the plan"},
            )

            # --- simulate compact + restart: recover ONLY from files ---
            recovered = compaction.recover("sess-1")
            active = [x["statement"] for x in decisions.active_decisions()]
            live_tasks = [t["id"] for t in registry.load_live_active()]

            self.assertEqual(recovered["next_action"], "resume phase 2")
            self.assertIn("no fixed cap; dynamic gate", active)
            self.assertNotIn("cap is 2", active)
            self.assertIn("TASK-9", live_tasks)

            # the regenerated capsule reflects all of it, source-tagged
            cap = resume.render_capsule("sess-1", recovered["latest_turn"])
            self.assertIn("no fixed cap; dynamic gate", cap)
            self.assertIn("TASK-9", cap)
            self.assertIn("write the plan", cap)


class CapsuleFreshnessCanary(unittest.TestCase):
    """The capsule on disk must equal the live registry's live set, always."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.capsule = self.base / "chrono" / "resume.md"

        # Rebind module state and restore it — these are process-wide globals and a
        # leak here makes unrelated tests order-dependent.
        for module, attr, value in (
            (registry, "LIVE_REGISTRY", self.base / "active-tasks.json"),
            (registry, "TASKS_DIR", self.base / "tasks"),
            (decisions, "DECISIONS_FILE", self.base / "decisions.jsonl"),
            (resume, "CAPSULE_PATH", self.capsule),
            # Isolation (fix round 2): the queue path defaults to a nonexistent
            # file under `self.base`, so every test in this class gets pending=[]
            # (i.e. no dependency on this HOST's real chrono-queue.md) unless it
            # explicitly opts in via write_queue().
            (resume, "QUEUE_PATH", self.base / "chrono-queue.md"),
            # Same trap, same fix: the archived-charter debt block would
            # otherwise read this HOST's real thread-charters/complete and
            # spend real tokens inside a fixture capsule's bound.
            (resume, "ARCHIVED_DEBT_ROOT", self.base),
        ):
            self.addCleanup(setattr, module, attr, getattr(module, attr))
            setattr(module, attr, value)

    def write_registry(self, payload):
        registry.LIVE_REGISTRY.write_text(json.dumps(payload))

    def write_queue(self, lines):
        resume.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        resume.QUEUE_PATH.write_text("\n".join(lines) + "\n")

    def capsule_task_ids(self):
        return set(TASK_REF.findall(self.capsule.read_text()))

    def section_ids(self, heading):
        """Task IDs inside one `## `-delimited capsule section."""
        text = self.capsule.read_text()
        if heading not in text:
            return set()
        body = text.split(heading, 1)[1].split("\n## ", 1)[0]
        return set(TASK_REF.findall(body))

    def test_written_capsule_task_set_matches_the_live_registry(self):
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "ship the capsule repair")
        # read back from disk: this asserts the WRITER, not just the renderer
        self.assertEqual(self.section_ids(resume.TASKS_HEADING), EXPECTED_LIVE)
        self.assertEqual(
            self.section_ids(resume.DEFERRED_HEADING), EXPECTED_DEFERRED
        )
        self.assertEqual(
            self.capsule_task_ids(), EXPECTED_LIVE | EXPECTED_DEFERRED
        )

    def test_regeneration_evicts_a_task_the_board_has_closed(self):
        """The exact 2026-07-24 failure: a closed task frozen into the capsule."""
        stale = "TASK-2026-07-18-0965-arcadia-resweep"
        self.capsule.parent.mkdir(parents=True)
        self.capsule.write_text(
            f"# Chrono resume capsule\n\n{resume.TASKS_HEADING}\n"
            f"- in-flight: await completion / verify [{stale}]\n"
        )
        self.write_registry(LIVE_FIXTURE)

        resume.write_capsule("sess-1", "regenerate")

        self.assertNotIn(stale, self.capsule.read_text())
        self.assertEqual(
            self.capsule_task_ids(), EXPECTED_LIVE | EXPECTED_DEFERRED
        )

    def test_capsule_ignores_the_frozen_bounded_registry(self):
        """Break 2: the bounded active.json is not the board's source of truth."""
        registry.TASKS_DIR.mkdir()
        (registry.TASKS_DIR / "active.json").write_text(
            json.dumps([{"id": "TASK-BOUNDED-STALE", "state": "in-flight"}])
        )
        self.write_registry(LIVE_FIXTURE)

        resume.write_capsule("sess-1", "regenerate")

        self.assertNotIn("TASK-BOUNDED-STALE", self.capsule.read_text())
        self.assertEqual(
            self.capsule_task_ids(), EXPECTED_LIVE | EXPECTED_DEFERRED
        )

    def test_list_shaped_registry_is_understood(self):
        """The file has used both shapes; the list form must not read as empty."""
        self.write_registry(
            [{"id": tid, **rec} for tid, rec in LIVE_FIXTURE.items()]
        )
        resume.write_capsule("sess-1", "regenerate")
        self.assertEqual(
            self.capsule_task_ids(), EXPECTED_LIVE | EXPECTED_DEFERRED
        )

    def test_terminal_records_never_reach_the_capsule(self):
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "regenerate")
        text = self.capsule.read_text()
        for excluded in set(LIVE_FIXTURE) - EXPECTED_LIVE - EXPECTED_DEFERRED:
            self.assertNotIn(excluded, text)

    def test_bound_is_enforced_and_every_omission_is_declared(self):
        """Under the token bound the capsule may drop tasks, but never silently."""
        many = {
            f"TASK-2026-08-05-{i:04d}-bulk": {"status": "in-flight"}
            for i in range(40)
        }
        self.write_registry(many)
        resume.write_capsule("sess-1", "regenerate", max_tokens=60)

        text = self.capsule.read_text()
        shown = self.capsule_task_ids()
        declared = OMITTED.search(text)

        self.assertLessEqual(len(text) // 4, 60)
        self.assertTrue(shown < set(many), "expected the bound to drop something")
        self.assertIsNotNone(declared, "tasks were dropped without declaring it")
        self.assertEqual(len(shown) + int(declared.group(1)), len(many))

    def test_operator_instruction_survives_a_registry_refresh(self):
        """A registry-triggered refresh carries no turn; it must not erase the old one."""
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "the one human line")

        resume.write_capsule("sess-1")  # refresh with no operator turn

        self.assertIn("the one human line", self.capsule.read_text())

    def test_write_is_atomic_and_leaves_no_temp_file(self):
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "regenerate")
        siblings = [p.name for p in self.capsule.parent.iterdir()]
        self.assertEqual(siblings, ["resume.md"])

    def test_an_unknown_status_is_reported_rather_than_dropped(self):
        """A new board status must be loud, not silently absent from the capsule."""
        self.write_registry({"TASK-X": {"status": "quarantined"}})
        self.assertEqual(registry.unclassified_statuses(), {"quarantined"})

    def test_reconciler_writeable_statuses_are_all_classified(self):
        """Every status registry_reconciler.py can write must be in the partition.

        The four below were reproduced as silently vanishing by the 0210 review:
        needs_human (SETTLEABLE_STATUSES), needs_rework (reopen target), timed_out
        (terminal delivery outcome), work-done-no-envelope (SETTLED_WITHOUT_ENVELOPE).
        """
        for status in (
            "needs_human",
            "needs_rework",
            "timed_out",
            "work-done-no-envelope",
        ):
            with self.subTest(status=status):
                self.write_registry({"TASK-R": {"status": status}})
                self.assertEqual(registry.unclassified_statuses(), set())

    def test_deferred_owed_work_is_itemised_with_ids_and_next_actions(self):
        """The 0230 review's second defect: a count line is not a task line.

        A resuming Chrono must be able to act from the capsule alone, so every
        deferred task appears in its own section with its ID and next action —
        through the production writer. Expectations are written out by hand,
        not derived from the code under test.
        """
        needs_human = "TASK-2026-08-05-0301-hotel"
        expected = {
            "TASK-2026-08-05-0302-india": ("needs_rework", "rework and redispatch"),
            "TASK-2026-08-05-0303-juliet": ("needs_rework", "rework and redispatch"),
            "TASK-2026-08-05-0304-kilo": ("timed_out", "investigate timeout"),
            "TASK-2026-08-05-0305-lima": (
                "work-done-no-envelope",
                "verify work, reconcile envelope",
            ),
            "TASK-2026-08-05-0306-mike": ("blocked", "unblock or rework"),
            "TASK-2026-08-05-0307-nova": ("needs_review", "settle review"),
        }
        self.write_registry(
            {
                **{tid: {"status": status} for tid, (status, _) in expected.items()},
                needs_human: {"status": "needs_human"},
            }
        )
        resume.write_capsule("sess-1", "regenerate")
        text = self.capsule.read_text()
        self.assertIn(resume.DEFERRED_HEADING, text)
        section = text.split(resume.DEFERRED_HEADING, 1)[1].split("\n## ", 1)[0]
        for tid, (status, action) in expected.items():
            with self.subTest(task=tid):
                line = next(
                    (row for row in section.splitlines() if f"[{tid}]" in row), None
                )
                self.assertIsNotNone(line, f"{tid} is not itemised")
                self.assertIn(status, line)
                self.assertIn(action, line)
        attention = text.split(resume.THREAD_HEADING, 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"[{needs_human}]", attention)
        self.assertIn("NEEDS HUMAN", attention)
        self.assertNotIn(f"[{needs_human}]", section)

    def test_needs_human_is_pinned_above_a_deep_deferred_queue(self):
        """Queue depth may compress routine work, never the operator question."""
        urgent = "TASK-2026-08-14-0810-leak-audit"
        routine = {
            f"TASK-2026-08-05-{index:04d}-routine": {"status": "needs_review"}
            for index in range(240)
        }
        self.write_registry({**routine, urgent: {"status": "needs_human"}})

        resume.write_capsule("sess-1", "regenerate", max_tokens=220)
        text = self.capsule.read_text()
        attention = text.split(resume.THREAD_HEADING, 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"[{urgent}]", attention)
        self.assertIn("NEEDS HUMAN: operator decision", attention)
        self.assertRegex(text, DEFERRED_OMITTED)

    def test_deferred_drops_under_the_bound_are_declared(self):
        """The bound may bite the deferred list too — never silently.

        Same declared-omission contract as live drops: shown + declared-dropped
        must equal the registry's deferred total.
        """
        many = {
            f"TASK-2026-08-05-{i:04d}-owed": {"status": "needs_rework"}
            for i in range(40)
        }
        self.write_registry(many)
        resume.write_capsule("sess-1", "regenerate", max_tokens=100)

        text = self.capsule.read_text()
        shown = self.capsule_task_ids()
        declared = DEFERRED_OMITTED.search(text)

        self.assertLessEqual(len(text) // 4, 100)
        self.assertTrue(shown < set(many), "expected the bound to drop something")
        self.assertIsNotNone(
            declared, "deferred tasks were dropped without declaring it"
        )
        self.assertEqual(len(shown) + int(declared.group(1)), len(many))

    def _write_archived_charter(self, name, body):
        d = self.base / "_state" / "chrono" / "thread-charters" / "complete"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)

    def test_archived_debt_is_shown_and_never_silently_dropped(self):
        """A charter archived while still owed must survive the token bound.

        The block exists because archiving is a bare `mv` and every other
        reader stops at active/. If the bound could delete it without a word,
        the capsule would be back to the state that lost six queued items —
        an absent heading reading as "nothing is owed".
        """
        self.write_registry({})
        for i in range(6):
            self._write_archived_charter(
                f"owed-{i}.md",
                "## THE ASK\nship it\n\n## OPEN LOOPS\n"
                f"- 2026-08-01T00:00:00Z | QUEUE Q-{i:03d} | thing — why: x; resume: y\n"
                "\n## DONE-WHEN\n- [ ] shipped\n",
            )

        # Roomy budget: the block renders in full.
        resume.write_capsule("sess-1", "regenerate", max_tokens=3000)
        full = self.capsule.read_text()
        self.assertIn(resume.ARCHIVED_DEBT_HEADING, full)
        self.assertIn("owed-0.md", full)

        # Squeezed: it collapses to a declared count, and still never vanishes.
        # NOT asserted: that the capsule then fits an arbitrary bound. Measured
        # 2026-08-23 — with any debt present the floor is ~87 tokens (heading +
        # declared count + the sections that never drop), so a 60-token budget
        # is unreachable by construction. The contract is "collapses and says
        # so", not "fits any number a caller invents".
        resume.write_capsule("sess-1", "regenerate", max_tokens=60)
        tight = self.capsule.read_text()
        self.assertLess(
            len(tight), len(full), "the squeezed capsule must actually be smaller"
        )
        self.assertIn(
            resume.ARCHIVED_DEBT_HEADING,
            tight,
            "archived-debt heading vanished silently under the bound",
        )
        declared = re.search(
            r"\((\d+) archived charter\(s\) still owed, omitted", tight
        )
        self.assertIsNotNone(
            declared, "archived debt was dropped without declaring it"
        )
        self.assertEqual(int(declared.group(1)), 6)

    def test_archived_debt_block_is_silent_when_nothing_is_owed(self):
        """Probation clause: no debt, no block. A check that always fires is noise."""
        self.write_registry({})
        self._write_archived_charter(
            "settled.md",
            "## THE ASK\nship it\n\n## OPEN LOOPS\n"
            "- 2026-08-01T00:00:00Z | FOLD | thing — why: x; resume: y\n"
            "\n## DONE-WHEN\n- [x] shipped\n",
        )
        resume.write_capsule("sess-1", "regenerate", max_tokens=3000)
        self.assertNotIn(resume.ARCHIVED_DEBT_HEADING, self.capsule.read_text())

    def test_pending_drops_under_the_bound_are_declared(self):
        """The bound may bite the pending-completions section too — never silently.

        Fix round 2 controller ruling: unlike the pre-fix behaviour (a silent
        drop indistinguishable from an empty queue), a collapsed pending
        section must always declare what it dropped — the same contract live
        and deferred already keep.
        """
        self.write_registry({})
        self.write_queue(
            [
                f"2026-08-16T00:{i:02d}:00Z | needs_review | ns{i}/TASK-{i} | "
                + ("x" * 40)
                for i in range(40)
            ]
        )
        resume.write_capsule("sess-1", "regenerate", max_tokens=150)

        text = self.capsule.read_text()
        self.assertLessEqual(len(text) // 4, 150)
        self.assertIn(
            resume.QUEUE_HEADING, text, "pending heading must not vanish silently"
        )
        declared = PENDING_OMITTED.search(text)
        self.assertIsNotNone(
            declared, "pending groups were dropped without declaring it"
        )
        self.assertEqual(int(declared.group(1)), 40)

    def test_pending_renders_in_full_when_it_fits(self):
        """The positive control for the round-1 fix: pending is not dead code."""
        self.write_registry({})
        self.write_queue(
            [
                "2026-08-16T00:00:00Z | needs_review | coding/TASK-1 | a",
                "2026-08-16T00:01:00Z | needs_review | coding/TASK-2 | b",
            ]
        )
        resume.write_capsule("sess-1", "regenerate")  # real 3000-token budget

        text = self.capsule.read_text()
        self.assertIn(resume.QUEUE_HEADING, text)
        self.assertIn("- 2 x coding | needs_review", text)
        self.assertIsNone(
            PENDING_OMITTED.search(text), "nothing should be declared omitted"
        )

    def test_an_unknown_status_is_loud_through_the_production_writer(self):
        """The 0210 review's positive control: write_capsule itself must be loud.

        The detector passing in a test while production never calls it is the
        original ten-day failure shape — a clean-looking file, silent stderr,
        owed state gone.
        """
        self.write_registry({"TASK-X": {"status": "quarantined"}})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            resume.write_capsule("sess-1", "regenerate")
        text = self.capsule.read_text()
        self.assertIn("UNCLASSIFIED", text)
        self.assertIn("quarantined", text)
        self.assertIn("quarantined", stderr.getvalue())

    def test_replace_failure_leaves_no_temp_and_preserves_the_old_capsule(self):
        """The 0210 review's fault injection: a failed rename must clean its temp."""
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "the good capsule")
        before = self.capsule.read_text()
        with mock.patch.object(
            resume.os, "replace", side_effect=OSError("injected replace failure")
        ):
            with self.assertRaises(OSError):
                resume.write_capsule("sess-1", "must not land")
        self.assertEqual(self.capsule.read_text(), before)
        self.assertEqual(
            [p.name for p in self.capsule.parent.iterdir()], ["resume.md"]
        )

    def test_cleanup_failure_does_not_mask_the_original_write_error(self):
        """The 0230 review's third defect: an unguarded `tmp.close()` in the
        cleanup path replaced the primary exception and skipped the unlink.

        Both the write and the close fail here; the caller must still see the
        ORIGINAL write error, the temp must still be unlinked, and the old
        capsule must survive.
        """
        self.write_registry(LIVE_FIXTURE)
        resume.write_capsule("sess-1", "the good capsule")
        before = self.capsule.read_text()

        class FaultyTemp:
            def __init__(self, real):
                self._real = real
                self.name = real.name

            def write(self, data):
                raise OSError("injected write failure")

            def close(self):
                raise OSError("injected close failure")

            def __getattr__(self, attr):
                return getattr(self._real, attr)

        real_factory = tempfile.NamedTemporaryFile
        with mock.patch.object(
            resume.tempfile,
            "NamedTemporaryFile",
            lambda *args, **kwargs: FaultyTemp(real_factory(*args, **kwargs)),
        ):
            with self.assertRaises(OSError) as caught:
                resume.write_capsule("sess-1", "must not land")
        self.assertEqual(str(caught.exception), "injected write failure")
        self.assertEqual(self.capsule.read_text(), before)
        self.assertEqual(
            [p.name for p in self.capsule.parent.iterdir()], ["resume.md"]
        )

    def test_missing_registry_yields_an_empty_capsule_not_a_crash(self):
        resume.write_capsule("sess-1", "regenerate")
        self.assertEqual(self.capsule_task_ids(), set())
        self.assertIn("(none)", self.capsule.read_text())


class LiveRegistryClassificationCanary(unittest.TestCase):
    """Runs against the real registry when one is present on this host."""

    @skip_in_host_independent_ci("reads the host's live _state/active-tasks.json")
    def test_every_status_in_the_real_registry_is_classified(self):
        live = Path(registry.LIVE_REGISTRY)
        if not live.exists():
            self.skipTest(f"no live registry at {live}")
        unknown = registry.unclassified_statuses(live)
        self.assertEqual(
            unknown, set(), f"unclassified board statuses would vanish silently: {unknown}"
        )


if __name__ == "__main__":
    unittest.main()
