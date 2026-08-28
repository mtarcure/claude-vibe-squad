#!/usr/bin/env python3
"""Tests for the `## Open work` capsule section (V1.1.3 wave 1, w1b).

`_state/chrono/OPEN-WORK.md` is documented as the single list of everything raised
and not yet done, and `chrono/CLAUDE.md` instructs Chrono to read it at session
start. The capsule — the one artifact a session is guaranteed to regenerate and
read — projected seven other sources and not this one: `resume.py` named the path
exactly once, inside a prose advice string. Owed work was therefore invisible to
the resume path, which is the mechanical reason follow-ups stall when attention
moves.

These prove the section renders owed items with their next action, that the block
cap and the token bound may both bite but never silently, and that an unreadable
ledger is loud rather than indistinguishable from "nothing is owed".
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from chrono_state import decisions, registry, resume  # noqa: E402

BOUND_OMITTED = re.compile(r"\((\d+) open item\(s\) omitted for the token bound")
BLOCK_OMITTED = re.compile(r"\+(\d+) open item\(s\) omitted from this bounded block")
SHOWN_ID = re.compile(r"\[OPEN-WORK-(OWED-\d+)\]")


class OpenWorkProjection(unittest.TestCase):
    """Every source is rebound under a temp root.

    Isolation matters more here than usual: the host's real ledger carries
    `TASK-...` strings in its prose, so a capsule that leaked into a fixture
    would pollute the freshness canary's task-set equality assertions.
    `CAPSULE_PATH` is the single lever — `open_work_items()` derives its default
    from it, exactly as `active_thread_charters()` does for the charter rail.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.capsule = self.base / "chrono" / "resume.md"
        self.capsule.parent.mkdir(parents=True)
        self.ledger = self.capsule.parent / "OPEN-WORK.md"
        for module, attr, value in (
            (registry, "LIVE_REGISTRY", self.base / "active-tasks.json"),
            (registry, "TASKS_DIR", self.base / "tasks"),
            (decisions, "DECISIONS_FILE", self.base / "decisions.jsonl"),
            (resume, "CAPSULE_PATH", self.capsule),
            (resume, "QUEUE_PATH", self.base / "chrono-queue.md"),
            (resume, "ARCHIVED_DEBT_ROOT", self.base),
        ):
            self.addCleanup(setattr, module, attr, getattr(module, attr))
            setattr(module, attr, value)
        registry.LIVE_REGISTRY.write_text(json.dumps({}))

    def write_ledger(self, *lines):
        self.ledger.write_text(
            "# Open Work\n\n"
            "Format: `- [ ] <id> | <one line> - <why>; next: <action>`\n\n"
            + "\n".join(lines)
            + "\n"
        )

    def section(self, text):
        self.assertIn(resume.OPEN_WORK_HEADING, text)
        return text.split(resume.OPEN_WORK_HEADING, 1)[1].split("\n## ", 1)[0]

    def test_open_items_reach_the_written_capsule_with_their_next_action(self):
        """The defect this section exists to fix: owed work absent from the capsule.

        Asserted through `write_capsule` and read back from disk, so this covers
        the production writer and not just the renderer.
        """
        self.write_ledger(
            "- [ ] AUD-01 | bounty close has no executable contract for either "
            "exit; next: decide whether to add a typed campaign_outcome",
            "- [ ] CI-02 | a reaping test is flaky on Linux CI only; "
            "next: gate it or fix the race - do NOT mask it",
        )
        resume.write_capsule("sess-1", "regenerate")
        text = self.capsule.read_text()
        section = self.section(text)

        self.assertIn("[OPEN-WORK-AUD-01]", section)
        self.assertIn("[OPEN-WORK-CI-02]", section)
        self.assertIn("bounty close has no executable contract", section)
        # The `next:` clause is the actionable half: a resuming Chrono must be
        # able to act from the capsule alone, so it must survive the clip.
        self.assertIn("next: decide whether to add a typed campaign_outcome", section)
        self.assertIn("next: gate it or fix the race", section)
        # Nothing was dropped, so nothing may claim to have been.
        self.assertIsNone(BOUND_OMITTED.search(text))
        self.assertIsNone(BLOCK_OMITTED.search(text))

    def test_the_token_bound_collapses_the_section_but_never_silently(self):
        """A dropped section must declare itself. An absent heading would read as
        "nothing is owed" - the exact ambiguity this section exists to kill, and
        the same contract the pending-completions and archived-debt blocks keep.

        NOT asserted: that the squeezed capsule fits an arbitrary bound. With any
        open work present the floor is the heading plus the declared count plus
        the sections that never drop, so a caller's chosen number is not always
        reachable. The contract is "collapses and says so".
        """
        self.write_ledger(
            *[
                f"- [ ] OWED-{i:03d} | owed thing number {i} " + "x" * 200
                + f"; next: do owed thing {i}"
                for i in range(30)
            ]
        )
        resume.write_capsule("sess-1", "regenerate", max_tokens=3000)
        roomy = self.capsule.read_text()
        self.assertIn("[OPEN-WORK-OWED-029]", roomy)

        resume.write_capsule("sess-1", "regenerate", max_tokens=60)
        tight = self.capsule.read_text()

        self.assertLess(len(tight), len(roomy), "the squeezed capsule must be smaller")
        self.assertIn(
            resume.OPEN_WORK_HEADING,
            tight,
            "the open-work heading vanished silently under the token bound",
        )
        self.assertNotIn("[OPEN-WORK-OWED-000]", tight)
        declared = BOUND_OMITTED.search(tight)
        self.assertIsNotNone(declared, "open work was dropped without declaring it")
        self.assertEqual(int(declared.group(1)), 30)
        self.assertIn("_state/chrono/OPEN-WORK.md", tight)

    def test_the_block_cap_declares_its_remainder_before_the_bound_bites(self):
        """The per-block cap bites first on a long ledger; it declares too.

        shown + declared-dropped must equal the ledger's open total, the same
        arithmetic the live and deferred omission lines keep.
        """
        count = resume.MAX_PROJECTED_OPEN_WORK + 7
        self.write_ledger(
            *[
                f"- [ ] OWED-{i:03d} | short owed thing {i}; next: do it"
                for i in range(count)
            ]
        )
        resume.write_capsule("sess-1", "regenerate", max_tokens=3000)
        text = self.capsule.read_text()

        shown = SHOWN_ID.findall(text)
        declared = BLOCK_OMITTED.search(text)
        self.assertEqual(len(shown), resume.MAX_PROJECTED_OPEN_WORK)
        self.assertIsNotNone(declared, "capped items were dropped without declaring it")
        self.assertEqual(len(shown) + int(declared.group(1)), count)

    def test_truncated_block_prioritises_in_progress_then_recency(self):
        """Explicit in-progress items outrank ordinary entries under the cap.

        The ledger is append-only, so reverse file order is its available
        recency signal. In-progress entries outrank that signal; recency breaks
        ties within the in-progress and remaining groups.
        """
        regular_count = resume.MAX_PROJECTED_OPEN_WORK + 2
        self.write_ledger(
            "- [ ] OWED-000 | oldest active item "
            "**IN PROGRESS — lane-old**",
            *[
                f"- [ ] OWED-{i:03d} | ordinary owed thing {i}; next: do it"
                for i in range(1, regular_count + 1)
            ],
            "- [ ] OWED-999 | newest active item "
            "**IN PROGRESS — lane-new**",
        )
        resume.write_capsule("sess-1", "regenerate", max_tokens=3000)
        text = self.capsule.read_text()
        shown = SHOWN_ID.findall(self.section(text))

        self.assertEqual(len(shown), resume.MAX_PROJECTED_OPEN_WORK)
        self.assertEqual(shown[:2], ["OWED-999", "OWED-000"])
        self.assertEqual(shown[2], f"OWED-{regular_count:03d}")
        self.assertNotIn("OWED-001", shown)
        declared = BLOCK_OMITTED.search(text)
        self.assertIsNotNone(declared)
        self.assertEqual(
            len(shown) + int(declared.group(1)), regular_count + 2
        )

    def test_ticked_items_are_not_projected(self):
        """What is owed is what is unticked. A finished line is not owed work."""
        self.write_ledger(
            "- [x] AUD-04 | done 2026-08-24, the ledger default is fixed",
            "- [ ] AUD-09 | bounty.md is 927 lines; next: decide what to cut",
        )
        resume.write_capsule("sess-1", "regenerate")
        text = self.capsule.read_text()
        self.assertIn("[OPEN-WORK-AUD-09]", text)
        self.assertNotIn("AUD-04", text)

    def test_an_absent_ledger_renders_no_heading_and_does_not_raise(self):
        """Absence is silence - the contract the pending-completions section keeps."""
        self.assertFalse(self.ledger.exists())
        resume.write_capsule("sess-1", "regenerate")
        self.assertNotIn(resume.OPEN_WORK_HEADING, self.capsule.read_text())

    def test_a_present_but_unreadable_ledger_is_loud_not_silent(self):
        """A read failure must never be mistaken for "nothing is owed"."""
        self.ledger.write_bytes(b"- [ ] X-1 | \xff\xfe not valid utf-8\n")
        resume.write_capsule("sess-1", "regenerate")
        section = self.section(self.capsule.read_text())
        self.assertIn("unreadable", section)

    def test_a_ledger_that_is_a_directory_is_loud_not_silent(self):
        """The other present-but-unreadable shape, and an OSError not a ValueError."""
        self.ledger.mkdir()
        resume.write_capsule("sess-1", "regenerate")
        section = self.section(self.capsule.read_text())
        self.assertIn("unreadable", section)


class OpenWorkParsing(unittest.TestCase):
    """`open_work_items` in isolation: the shapes the live ledger actually holds."""

    def parse(self, body):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "OPEN-WORK.md"
            path.write_text(body)
            return resume.open_work_items(path)

    def test_the_documented_format_yields_id_body_and_next_action(self):
        items = self.parse(
            "- [ ] AUD-01 | the thing is broken - why it matters; next: fix it\n"
        )
        self.assertEqual(
            items, [("AUD-01", "the thing is broken - why it matters", "fix it")]
        )

    def test_a_line_without_an_id_still_projects_with_no_source_id(self):
        items = self.parse("- [ ] a bare owed line with no id; next: do the thing\n")
        self.assertEqual(items, [(None, "a bare owed line with no id", "do the thing")])

    def test_a_sentence_separated_next_clause_is_recognised(self):
        """Hand-written entries use `. Next:` as well as the format's `; next:`."""
        items = self.parse(
            "- [ ] STD-04 | three questions are unanswered. Next: operator decides\n"
        )
        self.assertEqual(items[0][2], "operator decides")

    def test_the_last_next_marker_wins_over_a_mid_sentence_one(self):
        """A mid-sentence mention must not steal the real trailing action."""
        items = self.parse(
            "- [ ] X-1 | read the next: chapter first; next: the real action\n"
        )
        self.assertEqual(items[0][2], "the real action")

    def test_an_item_with_no_next_clause_keeps_its_whole_body(self):
        items = self.parse("- [ ] X-2 | owed, with no stated action\n")
        self.assertEqual(items, [("X-2", "owed, with no stated action", None)])

    def test_nested_checkboxes_are_not_counted_as_top_level_items(self):
        """Detail written under an item is not a second owed item."""
        items = self.parse(
            "- [ ] X-3 | the owed item; next: do it\n"
            "  - [ ] a sub-detail that is not its own ledger entry\n"
        )
        self.assertEqual([item[0] for item in items], ["X-3"])

    def test_a_missing_file_is_empty_not_an_exception(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(resume.open_work_items(Path(d) / "nope.md"), [])


if __name__ == "__main__":
    unittest.main()
