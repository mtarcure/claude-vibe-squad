"""What autocapture is allowed to write into semantic memory (spec 12).

Three stages, and the tests are grouped the same way:

1. a mechanical, model-free filter that only ever rejects;
2. distillation of the survivors into the fields recall actually weights;
3. an unconditional raw spool, so a rejection never destroys the material.

Every test here is hermetic: the distiller is injected, never invoked.
`ModelIdentityTests` is the one exception and it only reads a registry file.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import autocapture  # noqa: E402
from autocapture import AutocaptureRefused, DistillationFailed, capture  # noqa: E402

# A distiller stub for the tests that need the pipeline to reach the write
# without caring what distillation produced.
_DISTILLED = {
    "title": "A distilled claim about the capture pipeline",
    "body": "The distilled body stands in for a real lane's output.",
    "aliases": ["capture pipeline"],
    "keywords": ["autocapture"],
    "attack_class": "",
}


class MechanicalFilterTests(unittest.TestCase):
    """Stage 1. No model call is spent deciding whether `APPROVE` is knowledge."""

    def test_refuses_to_write_without_an_attributable_role(self) -> None:
        with self.assertRaises(AutocaptureRefused):
            capture(role=None, title="something", body="a real learning")

    def test_refuses_the_unknown_specialist_placeholder(self) -> None:
        # 32.7% of the vault carried this placeholder. A note nobody wrote is
        # a note nobody can be asked about.
        with self.assertRaises(AutocaptureRefused) as raised:
            capture(
                role="unknown-specialist",
                title="dispatch",
                body="A genuinely substantive paragraph about a real root cause "
                "that would otherwise be worth keeping around.",
            )
        self.assertEqual(str(raised.exception), "unattributed")

    def test_refuses_a_body_that_is_only_operational_residue(self) -> None:
        with self.assertRaises(AutocaptureRefused):
            capture(
                role="scout",
                title="dispatch",
                body="TASK-2026-01-01-0001 packet lane receipt _state/foo",
            )

    def test_refuses_a_bare_verdict(self) -> None:
        with self.assertRaises(AutocaptureRefused) as raised:
            capture(role="skeptic", title="verdict", body="APPROVE")
        self.assertEqual(str(raised.exception), "bare_verdict")

    def test_refuses_pure_error_text(self) -> None:
        with self.assertRaises(AutocaptureRefused) as raised:
            capture(
                role="agentops",
                title="dispatch",
                body=(
                    "Command '('/opt/fixture/bin/claude', '-p', '...')' "
                    "timed out after 900 seconds\n"
                    "Traceback (most recent call last)\n"
                    '  File "/x/y.py", line 12\n'
                    "TimeoutExpired: exited with code 124\n"
                ),
            )
        self.assertEqual(str(raised.exception), "operational_error")

    def test_keeps_a_substantive_body_that_merely_mentions_a_task_id(self) -> None:
        note = capture(
            role="scout",
            title="ImportError root cause",
            body="ImportError on X was caused by Y; the fix was Z. "
            "Seen while running TASK-2026-01-01-0001.",
        )
        self.assertIn("ImportError", note["body"])
        self.assertEqual(note["role"], "scout")

    def test_plumbing_is_judged_by_dominance_not_by_presence(self) -> None:
        # `packet` and `lane` are ordinary vocabulary here, so their presence
        # carries no signal. A note about dispatch that names all five markers
        # is kept; a note that is nothing BUT the markers is not.
        substantive = (
            "TASK-2026-08-18-9999 packet lane receipt. The demotion queue "
            "writes to _state/curation-queue.jsonl. Flagging uses record_usage "
            "outcomes and never invalidates a note automatically; a human "
            "reads the queue. The earlier silent stall happened because the "
            "sweep had no event trigger, so it stopped for three weeks."
        )
        self.assertEqual(
            sum(1 for marker in autocapture.PLUMBING_MARKERS if marker in substantive),
            len(autocapture.PLUMBING_MARKERS),
        )
        self.assertIsNone(
            autocapture._refusal_reason("systems-engineer", "t", substantive)
        )
        residue = "TASK-2026-01-01-0001 packet lane receipt _state/foo"
        self.assertEqual(
            autocapture._refusal_reason("systems-engineer", "t", residue),
            "plumbing_residue",
        )

    def test_refuses_a_controller_failure_report(self) -> None:
        # 12.5% of live captures are this: the controller describing its own
        # dispatch failing, filed under the specialist who never ran.
        with self.assertRaises(AutocaptureRefused) as raised:
            capture(
                role="agentops",
                title="dispatch",
                body=(
                    "Board dispatch was blocked by the controller: detached "
                    "board supervisor status blocked exit 75; inspect the "
                    "supervisor log and re-queue once the lane is clear."
                ),
            )
        self.assertEqual(str(raised.exception), "controller_failure_report")


class ModelIdentityTests(unittest.TestCase):
    """The distillation model id is read, never guessed."""

    def test_model_id_comes_from_the_profile_registry(self) -> None:
        registry = REPO_ROOT / autocapture.PROFILE_REGISTRY
        self.assertTrue(registry.is_file(), registry)
        rows = registry.read_text(encoding="utf-8").splitlines()
        header = rows[0].split("\t")
        expected = next(
            row.split("\t")[header.index("model_id")]
            for row in rows[1:]
            if row.split("\t")[header.index("profile_id")]
            == autocapture.DISTILL_PROFILE
        )
        self.assertEqual(autocapture._distill_model_id(), expected)

    def test_a_missing_profile_fails_loudly(self) -> None:
        with mock.patch.object(autocapture, "DISTILL_PROFILE", "nope.not.a.profile"):
            with self.assertRaises(DistillationFailed):
                autocapture._distill_model_id()


class DistilledOutputTests(unittest.TestCase):
    """Stage 2 normalisation. Model output is untrusted text, not a schema."""

    def test_a_null_title_is_a_refusal_not_a_failure(self) -> None:
        with self.assertRaises(AutocaptureRefused):
            autocapture._normalize_distilled({"title": None})

    def test_empty_or_non_string_fields_fail_loudly(self) -> None:
        for payload in (
            {"title": 7, "body": "x"},
            {"title": "   ", "body": "x"},
            {"title": "a real claim", "body": ""},
        ):
            with self.assertRaises(DistillationFailed):
                autocapture._normalize_distilled(payload)

    def test_terms_are_bounded_deduplicated_and_cleaned(self) -> None:
        normalized = autocapture._normalize_distilled(
            {
                "title": "Curation queue never invalidates automatically",
                "body": "It flags; a human decides.",
                "attack_class": "None",
                "aliases": ["a", "a", "b", 3, "c", "d", "e", "f", "g"],
                "keywords": ["k" + str(index) for index in range(20)],
            }
        )
        self.assertEqual(normalized["aliases"], ["a", "b", "c", "d", "e"])
        self.assertEqual(len(normalized["keywords"]), autocapture.MAX_DISTILLED_KEYWORDS)
        # "none" is the distiller saying "not attack-shaped", not a category.
        self.assertEqual(normalized["attack_class"], "")

    def test_json_is_recovered_from_chatty_output(self) -> None:
        parsed = autocapture._parse_distilled(
            'Sure, here you go:\n```json\n{"title": "a claim", "body": "why"}\n```\n'
        )
        self.assertEqual(parsed["title"], "a claim")

    def test_output_without_json_fails_loudly(self) -> None:
        with self.assertRaises(DistillationFailed):
            autocapture._parse_distilled("I could not do that.")


class CapturePipelineTests(unittest.TestCase):
    """Stages 1-3 end to end, with the lane replaced by a stub."""

    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-quality-vault-"))
        )
        self.mailbox_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-quality-mailbox-"))
        )
        self.episodic_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-quality-episodic-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.mailbox_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.episodic_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "quality-test", "schema_version": 1}),
            encoding="utf-8",
        )
        # The episodic spool lives at REPO_ROOT/_state/episodic (Task 12),
        # never in the vault -- redirect it so this suite never writes into
        # the real repo's _state/ tree.
        self.episodic_patch = mock.patch.object(
            autocapture, "_episodic_root", lambda: self.episodic_root
        )
        self.episodic_patch.start()
        self.addCleanup(self.episodic_patch.stop)
        # Same reason `_episodic_root` is patched rather than REPO_ROOT: this
        # suite must never write into the real repo's _state/ tree. Outside
        # `episodic_root`, because `_spooled()` globs every .jsonl there.
        self.failure_log = self.mailbox_root / "autocapture-failures.jsonl"
        self.failure_patch = mock.patch.object(
            autocapture, "_failure_log_path", lambda: self.failure_log
        )
        self.failure_patch.start()
        self.addCleanup(self.failure_patch.stop)
        self.env = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_AUTOCAPTURE_DISTILL": "on",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _write_response(self, *, task_id: str, body: str, verdict: str = "") -> Path:
        outbox = self.mailbox_root / "departments" / "coding" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{task_id}-response.md"
        path.write_text(
            "---\n"
            f"in_response_to: {json.dumps(task_id)}\n"
            'specialist: "systems-engineer"\n'
            'status: "complete"\n'
            'mode: "build"\n'
            f"verdict: {json.dumps(verdict)}\n"
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return path

    def _notes(self) -> list[Path]:
        directory = self.vault_root / "notes" / "learning"
        return sorted(directory.glob("*.md")) if directory.exists() else []

    def _spooled(self) -> list[dict]:
        if not self.episodic_root.exists():
            return []
        entries: list[dict] = []
        for path in sorted(self.episodic_root.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    SUBSTANTIVE = (
        "The outbox watcher backgrounds autocapture, so a slow distillation "
        "call costs the watcher nothing. Verified by reading the call site: "
        "the invocation is suffixed with an ampersand."
    )

    def test_distillation_fills_the_high_weight_retrieval_fields(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0001-quality", body=self.SUBSTANTIVE
        )
        seen: list[dict] = []

        def fake(capture_fields, context):
            seen.append({"capture": capture_fields, "context": context})
            return {
                "title": "Autocapture runs off the watcher's critical path",
                "body": "The watcher backgrounds the call, so latency is free.",
                "aliases": ["watcher blocking", "capture latency"],
                "keywords": ["outbox-watcher", "autocapture", "latency"],
                "attack_class": "",
            }

        result = autocapture.capture_response(str(path), distiller=fake)

        self.assertTrue(result["captured"], result)
        self.assertEqual(seen[0]["context"]["role"], "systems-engineer")
        frontmatter = self._frontmatter(self._notes()[0])
        # title carries BM25 weight 8.0 -- it must be a claim, not a dump.
        self.assertEqual(
            frontmatter["title"], "Autocapture runs off the watcher's critical path"
        )
        self.assertLess(len(frontmatter["title"]), autocapture.MAX_TITLE_CHARS)
        # aliases 6.0, keywords 3.0.
        self.assertEqual(
            frontmatter["aliases"], ["watcher blocking", "capture latency"]
        )
        self.assertIn("outbox-watcher", frontmatter["keywords"])
        # Provenance keywords survive distillation; nothing else can supply them.
        self.assertIn("specialist-systems-engineer", frontmatter["keywords"])
        self.assertIn("status-complete", frontmatter["keywords"])
        # No distilled attack_class means the routing slug stays, never empty.
        self.assertEqual(frontmatter["attack_class"], "build-systems-engineer")

    def test_a_distilled_attack_class_wins_over_the_routing_slug(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0002-quality", body=self.SUBSTANTIVE
        )
        result = autocapture.capture_response(
            str(path),
            distiller=lambda fields, context: {
                "title": "Stale receipts wedge the lane",
                "body": "A dead dispatch without a receipt blocks all dispatch.",
                "aliases": [],
                "keywords": [],
                "attack_class": "dispatch-deadlock",
            },
        )
        self.assertTrue(result["captured"], result)
        self.assertEqual(
            self._frontmatter(self._notes()[0])["attack_class"], "dispatch-deadlock"
        )

    def test_distillation_failure_is_loud_and_keeps_the_raw_capture(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0003-quality", body=self.SUBSTANTIVE
        )

        def broken(capture_fields, context):
            raise DistillationFailed("distiller timed out after 120s")

        result = autocapture.capture_response(str(path), distiller=broken)

        self.assertFalse(result["captured"])
        self.assertEqual(
            result["reason"], "distillation_failed:distiller timed out after 120s"
        )
        # The semantic note is not written -- and the material is not lost.
        self.assertEqual(self._notes(), [])
        spooled = self._spooled()
        self.assertEqual(len(spooled), 1)
        self.assertIn("outbox watcher backgrounds", spooled[0]["raw_body"])
        self.assertEqual(spooled[0]["specialist"], "systems-engineer")

    def test_a_distillation_failure_is_counted_where_a_metric_can_see_it(self) -> None:
        """I5: the write path now depends on a live model lane.

        A `DistillationFailed` writes no note. Until this existed the only
        signal was `main()` exiting 1 into a watcher that discarded stdout
        and stderr -- no reason in any log, no metric, no doctor check, and
        nothing in spec §11's four measurements that would move. That is
        the 2026-07-25 shape ("a lane loses its credential and the store
        quietly stops filling") reintroduced by the fix for it.
        """
        path = self._write_response(
            task_id="TASK-2026-08-18-0050-quality", body=self.SUBSTANTIVE
        )

        def broken(capture_fields, context):
            raise DistillationFailed("distiller exited 1: not authenticated")

        result = autocapture.capture_response(str(path), distiller=broken)

        self.assertFalse(result["captured"])
        rows = [
            json.loads(line)
            for line in self.failure_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 1)
        self.assertIn("not authenticated", rows[0]["reason"])
        self.assertIn("TASK-2026-08-18-0050-quality", rows[0]["response_path"])
        self.assertRegex(rows[0]["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_a_refusal_is_not_counted_as_a_write_path_failure(self) -> None:
        """The filter working is not the lane breaking."""
        path = self._write_response(
            task_id="TASK-2026-08-18-0051-quality", body="APPROVE"
        )

        autocapture.capture_response(str(path))

        self.assertFalse(self.failure_log.exists())

    def test_a_failure_to_record_a_failure_never_crashes_the_capture(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0052-quality", body=self.SUBSTANTIVE
        )

        def broken(capture_fields, context):
            raise DistillationFailed("distiller timed out after 120s")

        # A path that cannot be opened for writing -- a real failure of the
        # append itself, not a stubbed-out module (stubbing `jsonl` wholesale
        # would also break the episodic spool, which is a different promise).
        unwritable = self.mailbox_root / "not-a-file"
        unwritable.mkdir()
        with mock.patch.object(
            autocapture, "_failure_log_path", lambda: unwritable
        ):
            result = autocapture.capture_response(str(path), distiller=broken)

        self.assertEqual(
            result["reason"], "distillation_failed:distiller timed out after 120s"
        )

    def test_a_refusal_still_spools_the_raw_capture(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0004-quality", body="APPROVE"
        )

        result = autocapture.capture_response(
            str(path),
            distiller=lambda fields, context: self.fail("filter should reject first"),
        )

        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "refused:bare_verdict")
        self.assertEqual(self._notes(), [])
        self.assertEqual(len(self._spooled()), 1)

    def test_the_spool_is_written_before_anything_can_reject(self) -> None:
        # Ordering is the whole guarantee: if screening ran first, a refusal
        # would destroy the material it refused.
        path = self._write_response(
            task_id="TASK-2026-08-18-0005-quality", body="APPROVE"
        )
        order: list[str] = []
        real_spool = autocapture._spool_episodic
        real_screen = autocapture.capture

        def spool(payload):
            order.append("spool")
            return real_spool(payload)

        def screen(**kwargs):
            order.append("screen")
            return real_screen(**kwargs)

        with mock.patch.object(autocapture, "_spool_episodic", spool):
            with mock.patch.object(autocapture, "capture", screen):
                autocapture.capture_response(str(path))
        self.assertEqual(order, ["spool", "screen"])

    def test_a_replayed_response_never_reaches_the_distiller(self) -> None:
        """The watcher replays every response on startup. Restarts must be free.

        `scan_existing_responses()` walks 1,571 response files and
        backgrounds one autocapture each, unthrottled. With distillation
        ahead of the duplicate check that is ~1,165 concurrent `gemini`
        subprocesses per `squad up`, each held up to 120s and every one
        discarded milliseconds later as a duplicate.
        """
        path = self._write_response(
            task_id="TASK-2026-08-18-0031-quality", body=self.SUBSTANTIVE
        )
        first = autocapture.capture_response(
            str(path), distiller=lambda fields, context: _DISTILLED
        )
        self.assertTrue(first["captured"], first)

        replay = autocapture.capture_response(
            str(path),
            distiller=lambda fields, context: self.fail(
                "a duplicate must be rejected before any model call"
            ),
        )

        self.assertFalse(replay["captured"])
        self.assertEqual(replay["reason"], "duplicate")
        self.assertEqual(replay["note_id"], first["note_id"])
        # Task 12's ruling stands: the episodic tier records the second
        # event, because a retry IS a genuine second event.
        self.assertEqual(len(self._spooled()), 2)

    def test_the_duplicate_check_runs_before_the_mechanical_filter(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0032-quality", body=self.SUBSTANTIVE
        )
        autocapture.capture_response(
            str(path), distiller=lambda fields, context: _DISTILLED
        )
        order: list[str] = []
        real_find = autocapture._find_duplicate
        real_screen = autocapture.capture

        def find(*args, **kwargs):
            order.append("dedupe")
            return real_find(*args, **kwargs)

        def screen(**kwargs):
            order.append("screen")
            return real_screen(**kwargs)

        with mock.patch.object(autocapture, "_find_duplicate", find):
            with mock.patch.object(autocapture, "capture", screen):
                autocapture.capture_response(str(path))
        self.assertEqual(order, ["dedupe"])

    def _write_restricted_response(self, *, task_id: str, body: str) -> Path:
        """A response in the `security` namespace: `restricted` by label."""
        outbox = self.mailbox_root / "departments" / "security" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{task_id}-response.md"
        path.write_text(
            "---\n"
            f"in_response_to: {json.dumps(task_id)}\n"
            'specialist: "security-analyst"\n'
            'status: "complete"\n'
            'mode: "bounty"\n'
            'verdict: ""\n'
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return path

    def test_restricted_evidence_is_not_shipped_to_the_distiller(self) -> None:
        """Egress for the class the `restricted` label exists to compartment.

        `distill()` sends up to MAX_DISTILL_INPUT_CHARS of the response
        body to an external provider. Autocapture was a purely local
        parse-and-write before it existed, so shipping unreported bounty
        evidence there is a new egress path -- and it must not be the
        default nobody chose.
        """
        path = self._write_restricted_response(
            task_id="TASK-2026-08-18-0040-quality", body=self.SUBSTANTIVE
        )

        result = autocapture.capture_response(
            str(path),
            distiller=lambda fields, context: self.fail(
                "restricted evidence must not leave the machine by default"
            ),
        )

        self.assertTrue(result["captured"], result)
        frontmatter = self._frontmatter(self._notes()[0])
        self.assertEqual(frontmatter["sensitivity"], "restricted")

    def test_restricted_distillation_is_available_by_explicit_opt_in(self) -> None:
        path = self._write_restricted_response(
            task_id="TASK-2026-08-18-0041-quality", body=self.SUBSTANTIVE
        )
        seen: list[dict] = []

        with mock.patch.dict(
            os.environ, {"CHRONO_AUTOCAPTURE_DISTILL_RESTRICTED": "on"}
        ):
            result = autocapture.capture_response(
                str(path),
                distiller=lambda fields, context: (
                    seen.append(fields) or _DISTILLED
                ),
            )

        self.assertTrue(result["captured"], result)
        self.assertEqual(len(seen), 1)

    def test_the_global_off_switch_still_wins_over_the_restricted_opt_in(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CHRONO_AUTOCAPTURE_DISTILL": "off",
                "CHRONO_AUTOCAPTURE_DISTILL_RESTRICTED": "on",
            },
        ):
            self.assertFalse(autocapture._distillation_enabled("restricted"))
            self.assertFalse(autocapture._distillation_enabled("internal"))

    def test_internal_captures_are_unaffected_by_the_restricted_gate(self) -> None:
        with mock.patch.dict(os.environ, {"CHRONO_AUTOCAPTURE_DISTILL": "on"}):
            os.environ.pop("CHRONO_AUTOCAPTURE_DISTILL_RESTRICTED", None)
            self.assertTrue(autocapture._distillation_enabled("internal"))
            self.assertFalse(autocapture._distillation_enabled("restricted"))

    def test_distillation_can_be_turned_off_without_losing_the_filter(self) -> None:
        path = self._write_response(
            task_id="TASK-2026-08-18-0006-quality", body=self.SUBSTANTIVE
        )
        with mock.patch.dict(os.environ, {"CHRONO_AUTOCAPTURE_DISTILL": "off"}):
            kept = autocapture.capture_response(
                str(path),
                distiller=lambda fields, context: self.fail("must not distil"),
            )
            refused = autocapture.capture_response(
                str(
                    self._write_response(
                        task_id="TASK-2026-08-18-0007-quality", body="APPROVE"
                    )
                ),
                distiller=lambda fields, context: self.fail("must not distil"),
            )
        self.assertTrue(kept["captured"], kept)
        self.assertEqual(refused["reason"], "refused:bare_verdict")

    def test_main_exits_non_zero_only_when_distillation_breaks(self) -> None:
        refused = self._write_response(
            task_id="TASK-2026-08-18-0008-quality", body="APPROVE"
        )
        with mock.patch.dict(os.environ, {"CHRONO_AUTOCAPTURE_DISTILL": "off"}):
            # A refusal is the filter working, not a fault: exit 0.
            self.assertEqual(autocapture.main([str(refused)]), 0)
        broken = self._write_response(
            task_id="TASK-2026-08-18-0009-quality", body=self.SUBSTANTIVE
        )
        with mock.patch.object(
            autocapture,
            "distill",
            mock.Mock(side_effect=DistillationFailed("lane unreachable")),
        ):
            self.assertEqual(autocapture.main([str(broken)]), 1)

    @staticmethod
    def _frontmatter(path: Path) -> dict:
        lines = path.read_text(encoding="utf-8").splitlines()
        closing = lines.index("---", 1)
        return {
            line.partition(": ")[0]: json.loads(line.partition(": ")[2])
            for line in lines[1:closing]
            if line.partition(": ")[1]
        }


class AttributionRecoveryTests(unittest.TestCase):
    """Every source that can name the author is tried before refusing."""

    def setUp(self) -> None:
        self.mailbox_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-attribution-"))
        )
        self.addCleanup(shutil.rmtree, self.mailbox_root, ignore_errors=True)

    def _response_path(self, namespace: str, task_id: str) -> Path:
        outbox = self.mailbox_root / "departments" / namespace / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{task_id}-response.md"
        path.write_text("---\nstatus: complete\n---\n\nbody\n", encoding="utf-8")
        return path

    def test_a_packet_in_a_sibling_department_is_found(self) -> None:
        # A packet whose source_namespace differs from its
        # compatibility_namespace is filed under the former while its response
        # lands in the latter's outbox. Same-department lookup cannot see it.
        task_id = "TASK-2026-08-18-0100-cross"
        path = self._response_path("sysmgmt", task_id)
        shared = self.mailbox_root / "departments" / "shared" / "archive"
        shared.mkdir(parents=True)
        (shared / f"{task_id}.md").write_text(
            "---\n"
            f"id: {task_id}\n"
            "specialist: skeptic\n"
            "source_namespace: shared\n"
            "compatibility_namespace: sysmgmt\n"
            "mode: project\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )
        resolved = autocapture._resolve_packet_fields(path, task_id)
        self.assertEqual(resolved["specialist"], "skeptic")
        self.assertEqual(autocapture._resolve_specialist({}, resolved), "skeptic")

    def test_the_board_record_attributes_a_capture_whose_packet_is_gone(self) -> None:
        task_id = "TASK-2026-08-18-0101-pruned"
        path = self._response_path("coding", task_id)
        self.assertEqual(autocapture._resolve_packet_fields(path, task_id), {})

        board_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-attribution-board-"))
        )
        self.addCleanup(shutil.rmtree, board_root, ignore_errors=True)
        (board_root / "_state").mkdir()
        (board_root / autocapture.BOARD_TASK_RECORD).write_text(
            json.dumps({task_id: {"specialist": "release-manager", "mode": "project"}}),
            encoding="utf-8",
        )
        with mock.patch.object(autocapture, "REPO_ROOT", board_root):
            board_fields = autocapture._resolve_board_fields(task_id)
        self.assertEqual(board_fields["specialist"], "release-manager")
        self.assertEqual(
            autocapture._resolve_specialist({}, {}, board_fields), "release-manager"
        )

    def test_an_unreadable_board_record_degrades_to_unattributed(self) -> None:
        missing = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-attribution-empty-"))
        )
        self.addCleanup(shutil.rmtree, missing, ignore_errors=True)
        with mock.patch.object(autocapture, "REPO_ROOT", missing):
            self.assertEqual(autocapture._resolve_board_fields("TASK-x"), {})
        self.assertEqual(
            autocapture._resolve_specialist({}, {}, {}), "unknown-specialist"
        )


if __name__ == "__main__":
    unittest.main()
