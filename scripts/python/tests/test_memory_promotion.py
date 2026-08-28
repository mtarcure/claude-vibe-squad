"""Promotion fires at an event, never on a sweep.

A sweep that stops is invisible -- curation and usage both stopped
2026-07-25 and nothing noticed for three weeks, leaving 94.6% of notes
stuck at `candidate`. An event handler fails loudly at the event.

These tests run against a real temp vault (`tempfile.mkdtemp`), never the
operator's `~/Obsidian-Chrono`: promotion writes to memory, so a fixture
that pointed at the live vault would mutate it.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "python"
PLUGIN_ROOT = REPO_ROOT / "plugins" / "chrono-vault"
for _path in (str(SCRIPTS_ROOT), str(PLUGIN_ROOT)):
    if _path not in sys.path:
        sys.path.append(_path)

import memory_metrics  # noqa: E402
import registry_reconciler  # noqa: E402
from memory_promotion import (  # noqa: E402
    PASSING_VERDICTS,
    PROMOTING_OUTCOME,
    SUBSTANTIVE_REVIEW_CLASSES,
    MemoryPromotionError,
    promote_cited_notes,
)

import index as vault_index  # noqa: E402
import lifecycle as vault_lifecycle  # noqa: E402
import notes as vault_notes  # noqa: E402
import recall as vault_recall  # noqa: E402


def frontmatter(path: Path) -> dict[str, object]:
    """Read a note's frontmatter straight off disk, bypassing the index."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError("note is missing opening frontmatter")
    closing_index = text.find("\n---\n", 4)
    if closing_index < 0:
        raise AssertionError("note is missing closing frontmatter")
    parsed: dict[str, object] = {}
    for line in text[4:closing_index].splitlines():
        key, separator, encoded = line.partition(": ")
        if not separator:
            raise AssertionError(f"invalid frontmatter line: {line!r}")
        parsed[key] = json.loads(encoded)
    return parsed


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-promotion-test-"))
        )
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "promotion-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ, {"CHRONO_VAULT_ROOT": str(self.root)}
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        # A bound engagement context would make this a lane process, and
        # lifecycle changes are controller-only. The reconciler is the
        # controller; the fixture must be too.
        os.environ.pop("CHRONO_VAULT_CONTEXT", None)

    # -- fixture helpers ------------------------------------------------

    def _record(self, token: str, *, status: str = "candidate") -> str:
        return vault_notes.record(
            "learning",
            {
                "title": f"{token} promotion learning",
                "body": f"The {token} body is canonical markdown.",
                "component": "reconciler",
                "status": status,
                "keywords": ["promotion"],
                "source_task": "TASK-promotion-fixture",
            },
        )["id"]

    def _recall_for(
        self, token: str, task_ref: str, *, outcome: str | None = "used"
    ) -> list[str]:
        """Recall as `task_ref`, then report an outcome for what came back.

        `outcome=None` recalls without reporting anything -- the shape of a
        worker that was handed a note and never said it helped. That shape
        must NOT promote: promotion requires a positive signal (operator
        decision 2026-08-17), and promoting the returned set was promoting
        whatever the search already liked.
        """
        result = vault_recall.recall(token, filters={"source_task": task_ref})
        note_ids = [item["id"] for item in result["results"]]
        if outcome is not None:
            for note_id in note_ids:
                vault_lifecycle.record_usage(
                    result["recall_id"],
                    note_id,
                    outcome,
                    source_task=task_ref,
                    repo_root=self.root,
                )
        return note_ids

    def _meta_row(self, note_id: str) -> tuple:
        with closing(
            sqlite3.connect(
                f"file:{self.root / 'index' / 'kg.db'}?mode=ro", uri=True
            )
        ) as connection:
            return connection.execute(
                "SELECT status, verified_at_ns FROM meta WHERE id=?", (note_id,)
            ).fetchone()

    def _note_path(self, note_id: str) -> Path:
        return self.root / "notes" / "learning" / f"{note_id}.md"

    # -- the loop closes ------------------------------------------------

    def test_promotes_a_cited_candidate_in_index_and_markdown(self) -> None:
        note_id = self._record("PromoteToken")
        self.assertEqual(self._recall_for("PromoteToken", "TASK-X"), [note_id])

        promoted = promote_cited_notes("TASK-X", "APPROVE", "standard", self.root)

        self.assertEqual(promoted, [note_id])
        status, verified_at_ns = self._meta_row(note_id)
        self.assertEqual(status, "verified")
        self.assertIsNotNone(verified_at_ns)
        stored = frontmatter(self._note_path(note_id))
        self.assertEqual(stored["status"], "verified")
        self.assertIsInstance(stored["verified_at"], str)
        self.assertEqual(stored["updated_at"], stored["verified_at"])
        self.assertEqual(stored["revision"], 2)

    def test_promotion_survives_an_index_rebuild(self) -> None:
        """The index is a rebuildable projection; the markdown is truth."""
        note_id = self._record("RebuildToken")
        self._recall_for("RebuildToken", "TASK-X")
        promote_cited_notes("TASK-X", "APPROVE", "factual", self.root)

        vault_index.rebuild_index()

        status, verified_at_ns = self._meta_row(note_id)
        self.assertEqual(status, "verified")
        self.assertIsNotNone(verified_at_ns)

    def test_promotion_is_visible_to_promotion_throughput(self) -> None:
        """The already-shipped measurement must see this promotion."""
        self._record("MetricToken")
        self._recall_for("MetricToken", "TASK-X")
        self.assertEqual(memory_metrics.promotion_throughput(self.root), 0)

        promote_cited_notes("TASK-X", "APPROVE", "standard", self.root)

        self.assertEqual(memory_metrics.promotion_throughput(self.root), 1)

    # -- every way it must refuse ---------------------------------------

    def test_does_not_promote_on_a_failing_verdict(self) -> None:
        note_id = self._record("RejectToken")
        self._recall_for("RejectToken", "TASK-X")

        self.assertEqual(
            promote_cited_notes("TASK-X", "REJECT", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_does_not_promote_on_a_non_substantive_review_class(self) -> None:
        """A formatting pass says nothing about whether the memory was RIGHT."""
        note_id = self._record("FormatToken")
        self._recall_for("FormatToken", "TASK-X")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "format", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_does_not_promote_a_note_that_was_never_recalled(self) -> None:
        note_id = self._record("UnrecalledToken")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_does_not_promote_a_note_used_under_another_task(self) -> None:
        """The reconciler hands us the authenticated `task_ref`.

        A note another engagement reported using is not this settlement's to
        promote. Under a bound engagement `lifecycle.record_usage` overwrites
        `source_task` from the context, so a worker cannot reach across;
        this pins the reconciler side of that boundary.
        """
        note_id = self._record("OtherTaskToken")
        self._recall_for("OtherTaskToken", "TASK-OTHER")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    # -- promotion requires a POSITIVE signal ---------------------------
    #
    # Operator decision 2026-08-17. Promoting on `recall_returned` promoted
    # every note the search HANDED a worker -- read or not, useful or not.
    # Spec section 8 rejected usage-driven promotion as "promoting whatever
    # BM25 already liked"; returned-set promotion was that objection one
    # step weaker. These four are what make the distinction falsifiable.

    def test_a_recalled_note_with_no_reported_outcome_does_not_promote(self) -> None:
        """Handed to the worker, never reported as helpful. Stays candidate."""
        note_id = self._record("UnjudgedToken")
        self.assertEqual(
            self._recall_for("UnjudgedToken", "TASK-X", outcome=None), [note_id]
        )

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_a_note_reported_not_useful_does_not_promote(self) -> None:
        note_id = self._record("NotUsefulToken")
        self._recall_for("NotUsefulToken", "TASK-X", outcome="not_useful")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_a_note_reported_incorrect_does_not_promote(self) -> None:
        note_id = self._record("IncorrectToken")
        self._recall_for("IncorrectToken", "TASK-X", outcome="incorrect")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_the_same_note_promotes_once_the_outcome_is_reported(self) -> None:
        """The pair: identical fixture, one signal apart.

        Nothing else differs between this and
        `test_a_recalled_note_with_no_reported_outcome_does_not_promote`, so
        the reported outcome is provably the thing that decides.
        """
        note_id = self._record("SignalToken")
        self._recall_for("SignalToken", "TASK-X", outcome=None)
        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )

        self._recall_for("SignalToken", "TASK-X", outcome="used")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root),
            [note_id],
        )
        self.assertEqual(self._meta_row(note_id)[0], "verified")

    def test_does_not_promote_when_the_worker_declared_no_task(self) -> None:
        note_id = self._record("NoTaskToken")
        vault_recall.recall("NoTaskToken")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "candidate")

    def test_an_empty_authenticated_task_ref_promotes_nothing(self) -> None:
        self._record("EmptyRefToken")
        self._recall_for("EmptyRefToken", "TASK-X")

        self.assertEqual(
            promote_cited_notes("", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(
            promote_cited_notes(None, "APPROVE", "standard", self.root), []
        )

    def test_already_verified_note_is_not_re_promoted(self) -> None:
        note_id = self._record("VerifiedToken", status="verified")
        self._recall_for("VerifiedToken", "TASK-X")

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(frontmatter(self._note_path(note_id))["revision"], 1)

    def test_a_superseded_note_is_never_resurrected_by_promotion(self) -> None:
        """Only `candidate` promotes. Anything else is a lifecycle decision
        already made, and promotion must not overturn it."""
        note_id = self._record("SupersededToken")
        replacement = self._record("ReplacementToken", status="verified")
        self._recall_for("SupersededToken", "TASK-X")
        vault_lifecycle.set_status(
            note_id,
            "superseded",
            "replaced in the fixture",
            expected_revision=1,
            supersedes=replacement,
        )

        self.assertEqual(
            promote_cited_notes("TASK-X", "APPROVE", "standard", self.root), []
        )
        self.assertEqual(self._meta_row(note_id)[0], "superseded")

    def test_an_absent_index_raises_rather_than_reporting_success(self) -> None:
        empty = Path(os.path.realpath(tempfile.mkdtemp(prefix="chrono-empty-")))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)

        with self.assertRaises(MemoryPromotionError):
            promote_cited_notes("TASK-X", "APPROVE", "standard", empty)


class LegacyCorpusTests(unittest.TestCase):
    """Every note written before 2026-08-17 lacks `verified_at`.

    The operator's vault holds 2,022 of them. If the parser refused a note
    without the field, the reindex that follows this schema bump would
    quarantine the entire corpus -- so absence must read as null.
    """

    def setUp(self) -> None:
        self.root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-legacy-test-"))
        )
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "legacy-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ, {"CHRONO_VAULT_ROOT": str(self.root)}
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("CHRONO_VAULT_CONTEXT", None)

    def test_a_note_predating_verified_at_indexes_instead_of_quarantining(
        self,
    ) -> None:
        recorded = vault_notes.record(
            "learning",
            {
                "title": "LegacyToken learning",
                "body": "The LegacyToken body is canonical markdown.",
                "component": "reconciler",
                "keywords": ["legacy"],
            },
        )
        note_path = Path(recorded["path"])
        note_path.write_text(
            "\n".join(
                line
                for line in note_path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("verified_at: ")
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertNotIn("verified_at", frontmatter(note_path))

        report = vault_index.rebuild_index()

        self.assertEqual(report["quarantined"], [])
        self.assertEqual(report["indexed"], 1)
        with closing(
            sqlite3.connect(
                f"file:{self.root / 'index' / 'kg.db'}?mode=ro", uri=True
            )
        ) as connection:
            row = connection.execute(
                "SELECT status, verified_at_ns FROM meta WHERE id=?",
                (recorded["id"],),
            ).fetchone()
        self.assertEqual(row, ("candidate", None))

    def test_a_legacy_note_can_still_be_promoted(self) -> None:
        recorded = vault_notes.record(
            "learning",
            {
                "title": "LegacyPromoteToken learning",
                "body": "The LegacyPromoteToken body is canonical markdown.",
                "component": "reconciler",
                "keywords": ["legacy"],
            },
        )
        note_path = Path(recorded["path"])
        note_path.write_text(
            "\n".join(
                line
                for line in note_path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("verified_at: ")
            )
            + "\n",
            encoding="utf-8",
        )
        vault_index.rebuild_index()
        returned = vault_recall.recall(
            "LegacyPromoteToken", filters={"source_task": "TASK-X"}
        )
        vault_lifecycle.record_usage(
            returned["recall_id"],
            recorded["id"],
            "used",
            source_task="TASK-X",
            repo_root=self.root,
        )

        promoted = promote_cited_notes("TASK-X", "APPROVE", "standard", self.root)

        self.assertEqual(promoted, [recorded["id"]])
        self.assertIsInstance(frontmatter(note_path)["verified_at"], str)


class VocabularyTests(unittest.TestCase):
    """The gates must be stated in this repo's real vocabulary, not a
    plausible-looking one. Both sets are pinned to the reconciler."""

    def test_format_is_not_in_the_substantive_set(self) -> None:
        self.assertNotIn("format", SUBSTANTIVE_REVIEW_CLASSES)

    def test_substantive_classes_are_real_reconciler_review_classes(self) -> None:
        self.assertTrue(
            SUBSTANTIVE_REVIEW_CLASSES <= registry_reconciler.REVIEW_CLASSES,
            f"unknown review classes: "
            f"{sorted(SUBSTANTIVE_REVIEW_CLASSES - registry_reconciler.REVIEW_CLASSES)}",
        )

    def test_the_promoting_outcome_is_a_real_vault_outcome(self) -> None:
        """`used` must be the vault's own word, and the only positive one.

        `lifecycle.OUTCOMES` is the enum the server publishes and the
        `usage.outcome` CHECK constraint enforces. A promotion gate spelled
        in a word the vault never writes is a gate that never opens -- the
        C1 shape, in a different column.
        """
        self.assertIn(PROMOTING_OUTCOME, vault_lifecycle.OUTCOMES)
        self.assertEqual(
            vault_lifecycle.OUTCOMES - {PROMOTING_OUTCOME},
            set(memory_metrics.NEGATIVE_OUTCOMES),
        )

    def test_passing_verdicts_match_the_reconcilers_approval_gate(self) -> None:
        """`require_approval_verdict` settles on exactly APPROVE. Accepting a
        verdict it would have refused would promote on work that never
        passed."""
        self.assertEqual(PASSING_VERDICTS, frozenset({"APPROVE"}))


class ReconcilerHookTests(unittest.TestCase):
    """Promotion must never be able to block a receipt.

    It must also never be able to LOOK like it fired when it did not. The
    handler returns `(queue_status, summary)`, and only the promoted case
    carries `MEMORY_PROMOTION_STATUS` -- the status
    `memory_metrics.promotion_events` counts. A skip or a failure stays
    loud in the queue under its own status; what it does not do is inflate
    the alarm that exists to notice promotion has stopped.
    """

    def test_a_promotion_failure_is_reported_not_raised(self) -> None:
        with mock.patch.dict(os.environ, {"CHRONO_VAULT_ROOT": "/nonexistent"}):
            reported = registry_reconciler.memory_promotion_message(
                "TASK-2026-08-17-0001-x", "APPROVE", "standard"
            )
        self.assertIsNotNone(reported)
        status, message = reported
        self.assertIn("memory promotion failed", message)
        self.assertEqual(
            status, registry_reconciler.MEMORY_PROMOTION_FAILED_STATUS
        )
        self.assertNotEqual(status, registry_reconciler.MEMORY_PROMOTION_STATUS)

    def test_an_unset_vault_root_is_reported_not_silent(self) -> None:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name != "CHRONO_VAULT_ROOT"
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            reported = registry_reconciler.memory_promotion_message(
                "TASK-2026-08-17-0001-x", "APPROVE", "standard"
            )
        self.assertIsNotNone(reported)
        status, message = reported
        self.assertIn("CHRONO_VAULT_ROOT", message)
        self.assertEqual(
            status, registry_reconciler.MEMORY_PROMOTION_SKIPPED_STATUS
        )
        self.assertNotEqual(status, registry_reconciler.MEMORY_PROMOTION_STATUS)

    def test_settle_review_calls_the_promotion_hook(self) -> None:
        """The hook is wired into the settlement event, not a sweep."""
        source = (SCRIPTS_ROOT / "registry_reconciler.py").read_text(
            encoding="utf-8"
        )
        settle = source[source.index("def settle_review("):]
        settle = settle[: settle.index("\ndef reopen_task(")]
        self.assertEqual(settle.count("memory_promotion_message("), 1)




RUNTIME_MAP = (
    "\t".join(["specialist", "c2", "c3", "c4", "c5", "c6", "primary_lane"])
    + "\n"
    + "\t".join(["claude-spec", "x", "x", "x", "x", "x", "claude"])
    + "\n"
)
RECONCILER = SCRIPTS_ROOT / "registry_reconciler.py"
TASK = "TASK-2026-08-17-0001-promotion"
REVIEW_TASK = "TASK-PROMOTION-REVIEW"
REVIEW_REF = f"departments/coding/outbox/{REVIEW_TASK}-response.md"


def envelope(fields: dict[str, str], body: str = "done.") -> str:
    lines = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{lines}\n---\n\n{body}\n"


class EndToEndSettlementTests(unittest.TestCase):
    """The whole loop, through the real `--settle-review` entry point.

    Nothing here is stubbed: a real squad repo fixture, a real memory
    vault, the reconciler in a subprocess. Both vaults are temp
    directories -- promotion writes to memory, so pointing this at
    `~/Obsidian-Chrono` would mutate the operator's notes.
    """

    def setUp(self) -> None:
        self.memory_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-e2e-memory-"))
        )
        self.addCleanup(shutil.rmtree, self.memory_root, ignore_errors=True)
        (self.memory_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "promotion-e2e", "schema_version": 1}),
            encoding="utf-8",
        )
        self.squad_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-e2e-squad-"))
        )
        self.addCleanup(shutil.rmtree, self.squad_root, ignore_errors=True)

    def _seed_memory(self, task_ref: str, *, outcome: str | None = "used") -> str:
        """Record a candidate note, have `task_ref` recall it and report on it.

        `outcome=None` leaves the note recalled but unjudged -- the shape
        that must no longer promote.
        """
        with mock.patch.dict(
            os.environ, {"CHRONO_VAULT_ROOT": str(self.memory_root)}
        ):
            os.environ.pop("CHRONO_VAULT_CONTEXT", None)
            note_id = vault_notes.record(
                "learning",
                {
                    "title": "EndToEndToken promotion learning",
                    "body": "The EndToEndToken body is canonical markdown.",
                    "component": "reconciler",
                    "keywords": ["promotion"],
                    "source_task": "TASK-promotion-fixture",
                },
            )["id"]
            returned = vault_recall.recall(
                "EndToEndToken", filters={"source_task": task_ref}
            )
            if outcome is not None:
                vault_lifecycle.record_usage(
                    returned["recall_id"],
                    note_id,
                    outcome,
                    source_task=task_ref,
                    repo_root=self.squad_root,
                )
        self.assertEqual([item["id"] for item in returned["results"]], [note_id])
        return note_id

    def _seed_memory_as_a_dispatched_worker(
        self, task_ref: str, *, outcome: str | None = "used"
    ) -> str:
        """Record a note, then drive it the way production actually drives it.

        The launch prompt `dispatch_context_builder` gives every worker says
        "Pass no filters; the vault enforces this engagement's aperture", and
        the MCP `recall` tool does not expose `source_task` at all -- so no
        production recall can use the shape `_seed_memory` above uses. Until
        this test existed, every promotion test drove the one shape the
        prompt forbids, and the loop was green on a path that could not fire.

        The same prompt then says, for each recalled note that informed the
        work: `record_usage(recall_id=..., note_id=..., outcome="used")`.
        That call is now what promotion joins on, so it is part of the shape
        this fixture has to drive -- a fixture that stopped at recall would
        again be testing a path production does not take.

        Nothing here is declared: BOTH the recall key and the usage key come
        from the same `CHRONO_VAULT_CONTEXT` envelope the broker
        authenticates, which is what makes them unforgeable by a worker.
        """
        context = {
            "schema": "chrono-vault-context/v1",
            "task_id": task_ref,
            "attempt_id": "d-" + "5" * 32,
            "generation": 1,
            "mode": "project",
            "aperture": "default",
            "focus": None,
            "engagement_start": "2026-08-17T00:00:00Z",
        }
        with mock.patch.dict(
            os.environ, {"CHRONO_VAULT_ROOT": str(self.memory_root)}
        ):
            os.environ.pop("CHRONO_VAULT_CONTEXT", None)
            note_id = vault_notes.record(
                "learning",
                {
                    "title": "EndToEndToken promotion learning",
                    "body": "The EndToEndToken body is canonical markdown.",
                    "component": "reconciler",
                    "keywords": ["promotion"],
                    "source_task": "TASK-promotion-fixture",
                },
            )["id"]
            with mock.patch.dict(
                os.environ, {"CHRONO_VAULT_CONTEXT": json.dumps(context)}
            ):
                returned = vault_recall.recall("EndToEndToken")
                if outcome is not None:
                    # No `source_task` argument: the worker does not get to
                    # name the engagement, exactly as in production.
                    recorded_usage = vault_lifecycle.record_usage(
                        returned["recall_id"],
                        note_id,
                        outcome,
                        repo_root=self.squad_root,
                    )
                    self.assertEqual(recorded_usage["source_task"], task_ref)
        self.assertEqual([item["id"] for item in returned["results"]], [note_id])
        return note_id

    def _fixture(self, *, verdict: str, review_class: str) -> dict[str, str]:
        (self.squad_root / "shared").mkdir(parents=True, exist_ok=True)
        (self.squad_root / "shared" / "specialist-runtime-map.tsv").write_text(
            RUNTIME_MAP, encoding="utf-8"
        )
        state = self.squad_root / "_state"
        state.mkdir(parents=True, exist_ok=True)
        entry = {
            "compatibility_namespace": "coding",
            "specialist": "claude-spec",
            "to_model": "claude",
            "source_namespace": "coding",
            "review_model": "gpt-codex",
            "mandatory_review": "true",
            "status": "in-flight",
            "review_class": review_class,
        }
        review_entry = {
            "reviews": TASK,
            "to_model": "gpt-codex",
            "status": "complete",
        }
        (state / "active-tasks.json").write_text(
            json.dumps({TASK: entry, REVIEW_TASK: review_entry}), encoding="utf-8"
        )
        responses = {
            f"departments/coding/outbox/{TASK}-response.md": envelope(
                {
                    "id": f"{TASK}-response",
                    "in_response_to": TASK,
                    "from": "claude",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "needs_review",
                }
            ),
            REVIEW_REF: envelope(
                {
                    "id": f"{REVIEW_TASK}-response",
                    "in_response_to": REVIEW_TASK,
                    "reviews": TASK,
                    "from": "gpt-codex",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "complete",
                    "reviewer_family": "openai",
                    "verdict": verdict,
                },
                body=f"{verdict} - independent review complete.",
            ),
        }
        for relative, content in responses.items():
            destination = self.squad_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        environment = {
            **os.environ,
            "VAULT_ROOT": str(self.squad_root),
            "CHRONO_VAULT_ROOT": str(self.memory_root),
            "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux-for-tests",
            "SQUAD_SESSION": "no-such-session",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        # Every other site in this class pops CHRONO_VAULT_CONTEXT; this one
        # inherited it through `**os.environ` and did not. That made these two
        # tests pass on a developer shell and fail inside a board worktree,
        # because `board-supervisor.sh` exports an engagement envelope for the
        # task the lane is actually running. The reconciler subprocess then
        # attributed the promotion to THAT engagement instead of the fixture's,
        # so the note stayed `candidate` and the assertion read
        # `'candidate' != 'verified'`. Four lanes spent verification time
        # proving it was not their change before this was found.
        environment.pop("CHRONO_VAULT_CONTEXT", None)
        return environment

    def _run(self, env: dict[str, str], *arguments: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(RECONCILER), *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    def _settle(self, env: dict[str, str]) -> dict:
        self._run(env, "--task-id", TASK)
        registry = json.loads(
            (self.squad_root / "_state" / "active-tasks.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry[TASK]["status"], "review-required")
        self._run(env, "--settle-review", TASK, "--review-ref", REVIEW_REF)
        registry = json.loads(
            (self.squad_root / "_state" / "active-tasks.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry[TASK]["status"], "complete")
        return registry[TASK]

    def _stored(self, note_id: str) -> tuple[dict[str, object], tuple]:
        note_path = self.memory_root / "notes" / "learning" / f"{note_id}.md"
        with closing(
            sqlite3.connect(
                f"file:{self.memory_root / 'index' / 'kg.db'}?mode=ro", uri=True
            )
        ) as connection:
            row = connection.execute(
                "SELECT status, verified_at_ns FROM meta WHERE id=?", (note_id,)
            ).fetchone()
        return frontmatter(note_path), row

    def test_settlement_promotes_the_note_in_index_and_markdown(self) -> None:
        note_id = self._seed_memory(TASK)
        env = self._fixture(verdict="APPROVE", review_class="standard")

        self._settle(env)

        stored, (status, verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "verified")
        self.assertIsNotNone(verified_at_ns)
        self.assertEqual(stored["status"], "verified")
        self.assertIsInstance(stored["verified_at"], str)
        queue = (self.squad_root / "_state" / "chrono-queue.md").read_text(
            encoding="utf-8"
        )
        statuses = [
            line.split(" | ")[1]
            for line in queue.splitlines()
            if " | " in line and not line.startswith("#")
        ]
        self.assertIn(registry_reconciler.MEMORY_PROMOTION_STATUS, statuses)
        self.assertIn(note_id, queue)

    def test_registration_projects_packet_review_target_into_registry(self) -> None:
        """The production registrar stores controller-owned review linkage."""
        packet = (
            self.squad_root
            / "departments"
            / "coding"
            / "inbox"
            / f"{REVIEW_TASK}.md"
        )
        packet.parent.mkdir(parents=True, exist_ok=True)
        packet.write_text(
            envelope(
                {
                    "id": REVIEW_TASK,
                    "reviews": TASK,
                    "to_model": "gpt-codex",
                }
            ),
            encoding="utf-8",
        )
        state = self.squad_root / "_state"
        state.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "VAULT_ROOT": str(self.squad_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        self._run(
            env,
            "--register-task",
            REVIEW_TASK,
            "--entry-json",
            json.dumps({"to_model": "gpt-codex", "status": "in-flight"}),
        )

        registry = json.loads(
            (state / "active-tasks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry[REVIEW_TASK]["reviews"], TASK)

    def test_registration_retry_enriches_legacy_review_provenance(self) -> None:
        """A schema-only retry preserves the original dispatch receipts."""
        state = self.squad_root / "_state"
        state.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "VAULT_ROOT": str(self.squad_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        entry = {"to_model": "gpt-codex", "status": "in-flight"}
        first = self._run(
            env,
            "--register-task",
            REVIEW_TASK,
            "--entry-json",
            json.dumps(entry),
        )
        self.assertIn("outcome=registered", first.stdout)
        original = json.loads(
            (state / "active-tasks.json").read_text(encoding="utf-8")
        )[REVIEW_TASK]
        packet = (
            self.squad_root
            / "departments"
            / "coding"
            / "inbox"
            / f"{REVIEW_TASK}.md"
        )
        packet.parent.mkdir(parents=True, exist_ok=True)
        packet.write_text(
            envelope({"id": REVIEW_TASK, "reviews": TASK}), encoding="utf-8"
        )

        retry = self._run(
            env,
            "--register-task",
            REVIEW_TASK,
            "--entry-json",
            json.dumps(entry),
        )

        self.assertIn("outcome=idempotent", retry.stdout)
        enriched = json.loads(
            (state / "active-tasks.json").read_text(encoding="utf-8")
        )[REVIEW_TASK]
        self.assertEqual(enriched["reviews"], TASK)
        for field in (
            "delivery_attempt_id",
            "delivery_generation",
            "delivery_history",
        ):
            self.assertEqual(enriched.get(field), original.get(field))

    def test_late_settlement_recovers_closed_review_from_archived_packet(
        self,
    ) -> None:
        """Closing/archiving a real review cannot strand a late settlement."""
        env = self._fixture(verdict="APPROVE", review_class="standard")
        state = self.squad_root / "_state" / "active-tasks.json"
        registry = json.loads(state.read_text(encoding="utf-8"))
        registry[REVIEW_TASK].pop("reviews")
        registry[REVIEW_TASK]["status"] = "closed"
        state.write_text(json.dumps(registry), encoding="utf-8")
        archived = (
            self.squad_root
            / "departments"
            / "coding"
            / "archive"
            / f"{REVIEW_TASK}.md"
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_text(
            envelope({"id": REVIEW_TASK, "reviews": TASK}), encoding="utf-8"
        )

        settled = self._settle(env)

        self.assertEqual(settled["status"], "complete")
        registry = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(registry[REVIEW_TASK]["status"], "closed")
        self.assertEqual(registry[REVIEW_TASK]["reviews"], TASK)

    def test_packet_lookup_retries_across_the_archive_rename(self) -> None:
        """A close racing settlement does not create a false missing packet."""
        inbox = Path("departments/coding/inbox") / f"{REVIEW_TASK}.md"
        archive = Path("departments/coding/archive") / f"{REVIEW_TASK}.md"
        with (
            mock.patch.object(
                registry_reconciler,
                "task_packet_candidates",
                side_effect=[[inbox], [archive]],
            ),
            mock.patch.object(
                registry_reconciler,
                "read_text",
                side_effect=["", envelope({"id": REVIEW_TASK, "reviews": TASK})],
            ),
        ):
            target = registry_reconciler._packet_review_target(REVIEW_TASK)

        self.assertEqual(target, TASK)

    def test_a_worker_that_passed_no_filters_still_gets_promoted(self) -> None:
        """The loop, driven exactly as the dispatch prompt mandates.

        This is the regression guard for the defect the whole branch
        review turned on: promotion joined on a caller-declared
        `recall_returned.source_task` that no production caller declares
        or can declare, so the live vault had 0 `recall_returned` rows and
        0 `verified_at_ns` stamps while every test was green. If the
        derivation in `recall._recall` is removed, this fails and the
        others do not.
        """
        note_id = self._seed_memory_as_a_dispatched_worker(TASK)
        env = self._fixture(verdict="APPROVE", review_class="standard")

        self._settle(env)

        stored, (status, verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "verified")
        self.assertIsNotNone(verified_at_ns)
        self.assertEqual(stored["status"], "verified")
        queue = (self.squad_root / "_state" / "chrono-queue.md").read_text(
            encoding="utf-8"
        )
        statuses = [
            line.split(" | ")[1]
            for line in queue.splitlines()
            if " | " in line and not line.startswith("#")
        ]
        self.assertIn(registry_reconciler.MEMORY_PROMOTION_STATUS, statuses)
        self.assertIn(note_id, queue)

    def test_a_worker_that_reported_no_outcome_promotes_nothing(self) -> None:
        """The other half of the shape above, through the real entry point.

        Same production-shaped recall, same passing review, one signal
        missing. If promotion ever goes back to joining the returned set,
        this is the test that fails.
        """
        note_id = self._seed_memory_as_a_dispatched_worker(TASK, outcome=None)
        env = self._fixture(verdict="APPROVE", review_class="standard")

        self._settle(env)

        stored, (status, verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "candidate")
        self.assertIsNone(verified_at_ns)
        self.assertEqual(stored["status"], "candidate")
        queue = (self.squad_root / "_state" / "chrono-queue.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("MEMORY-PROMOTION", queue)

    def test_a_worker_that_reported_the_note_unhelpful_promotes_nothing(
        self,
    ) -> None:
        note_id = self._seed_memory_as_a_dispatched_worker(
            TASK, outcome="not_useful"
        )
        env = self._fixture(verdict="APPROVE", review_class="standard")

        self._settle(env)

        _stored, (status, _verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "candidate")

    def test_a_forced_non_approve_settlement_promotes_nothing(self) -> None:
        """An override is the operator closing a task, not a review passing."""
        note_id = self._seed_memory(TASK)
        env = self._fixture(verdict="REJECT", review_class="standard")

        self._run(env, "--task-id", TASK)
        self._run(
            env, "--settle-review", TASK, "--review-ref", REVIEW_REF, "--force"
        )

        stored, (status, verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "candidate")
        self.assertIsNone(verified_at_ns)
        self.assertEqual(stored["status"], "candidate")
        self.assertIsNone(stored["verified_at"])

    def test_a_task_that_never_recalled_promotes_nothing(self) -> None:
        note_id = self._seed_memory("TASK-2026-08-17-0002-somebody-else")
        env = self._fixture(verdict="APPROVE", review_class="standard")

        self._settle(env)

        stored, (status, _verified_at_ns) = self._stored(note_id)
        self.assertEqual(status, "candidate")
        self.assertEqual(stored["status"], "candidate")

    def test_a_reconciler_tree_without_the_promotion_module_still_settles(
        self,
    ) -> None:
        """Two fixtures stage the reconciler's imports by hand.

        `doctor_fixture._RECONCILER_MODULES` and
        `test_capability_dispatch_integrity.install_board_rail_fixture` both
        enumerate them, and neither knows about this module. A module-level
        import here turned every settlement in those trees into an exit-1,
        so the promotion import stays local and inside the guard -- "memory
        bookkeeping cannot break settlement" has to cover a missing module,
        not just a failing promotion.
        """
        note_id = self._seed_memory(TASK)
        env = self._fixture(verdict="APPROVE", review_class="standard")
        staged = self.squad_root / "staged" / "scripts" / "python"
        staged.mkdir(parents=True)
        for module in (
            "board_process_truth.py",
            "dispatch_context_builder.py",
            "registry_reconciler.py",
            "repo_root.py",
            "durable_publish.py",
            "held_action_gate.py",
            "lane_capability_enforcement.py",
            "launch_hygiene.py",
            "plan_item_binding.py",
            "seatbelt_profile.py",
            "specialist_capability_source.py",
            "verification_contract.py",
        ):
            shutil.copy2(SCRIPTS_ROOT / module, staged / module)
        self.assertFalse((staged / "memory_promotion.py").exists())

        for arguments in (
            ("--task-id", TASK),
            ("--settle-review", TASK, "--review-ref", REVIEW_REF),
        ):
            result = subprocess.run(
                [sys.executable, str(staged / "registry_reconciler.py"), *arguments],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

        registry = json.loads(
            (self.squad_root / "_state" / "active-tasks.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registry[TASK]["status"], "complete")
        self.assertEqual(self._stored(note_id)[1][0], "candidate")
        queue = (self.squad_root / "_state" / "chrono-queue.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("memory promotion failed", queue)

    def test_an_unreachable_memory_vault_still_settles_the_task(self) -> None:
        """Memory bookkeeping is never allowed to break task settlement."""
        env = self._fixture(verdict="APPROVE", review_class="standard")
        env["CHRONO_VAULT_ROOT"] = str(self.squad_root / "no-such-vault")

        settled = self._settle(env)

        self.assertEqual(settled["status"], "complete")
        queue = (self.squad_root / "_state" / "chrono-queue.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("memory promotion failed", queue)


if __name__ == "__main__":
    unittest.main()
