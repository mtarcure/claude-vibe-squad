#!/usr/bin/env python3
"""Wave R1 board-reliability regressions (audit CC-03/CC-17, friction F5/F6/F7).

Each class pins one root cause found by the 2026-07-26 repo audit:

* ``PromotionPinEchoTests`` (CC-03) — output promotion rebuilt only seven
  envelope fields, so the capability/swarm/worker pins the reconciler requires
  were discarded and completions were held open forever.
* ``NeverLaunchedReleaseTests`` (F5) — a task that REGISTERED then failed before
  launch stayed ``in-flight`` holding its ``write_scope``.
* ``NonHeadlessRequiredToolTests`` (F6) — a role whose REQUIRED tool is a GUI /
  operator-install artifact was undispatchable on a headless spawn.
* ``WorkerStatusEnumTests`` (CC-17) — ``needs_human`` was instructed, silently
  downgraded, and separately accepted, with no single enum.
* ``ContractAdmissionDiagnosticsTests`` (F7) — admission errors did not name the
  offending frontmatter field.
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import dispatch_context_builder as dcb  # noqa: E402
import verification_contract as _vc  # noqa: E402


def _valid_contract(**overrides: object) -> dict:
    """A schema-current contract, derived rather than hand-written.

    These fixtures used to hand-roll a two-key dict. The contract schema has
    since grown required keys, so the validator rejected the fixture for having
    EVERY key missing and never reached the branch under test -- the assertion
    then failed naming the field the test cared about, which reads like a
    product regression rather than a stale fixture. Deriving keeps the fixture
    current by construction.
    """
    contract = _vc.derive_verification_contract(
        {
            "task_id": "TASK-2026-07-26-9003-x",
            "mode": "project",
            "to_model": "claude",
            "run_id": "none",
            "result_type": "normal",
        }
    )
    contract.update(overrides)
    return contract
import lane_capability_enforcement as lce  # noqa: E402
import registry_reconciler as reconciler  # noqa: E402


CAPABILITY_PIN = "c" * 64
SWARM_PIN = "5" * 64


# ─────────────────────────────────────────────────────────────────────────────
# CC-03 — promotion must carry every reconciliation pin/fence
# ─────────────────────────────────────────────────────────────────────────────


class PromotionPinEchoTests(unittest.TestCase):
    """Promotion -> reconciliation must settle all four response kinds once."""

    task_id = "TASK-2026-07-26-9001-promotion-echo"
    attempt_id = "d-" + "b" * 32

    def _promote(
        self,
        directory: Path,
        *,
        reconciliation_echo: dict[str, str] | None = None,
        worker_frontmatter: str = "",
        status: str = "complete",
    ) -> Path:
        """Run the real promotion bridge and return the published envelope."""

        repo = directory / "repo"
        worker = directory / "worker"
        repo.mkdir()
        worker.mkdir()
        result_relative = "_state/r1/result.md"
        outbox_relative = (
            f"departments/coding/outbox/{self.task_id}-response.md"
        )
        worker_result = worker / result_relative
        worker_envelope = worker / outbox_relative
        worker_result.parent.mkdir(parents=True)
        worker_envelope.parent.mkdir(parents=True)
        worker_result.write_text("promoted artifact\n", encoding="utf-8")
        worker_envelope.write_text(
            "---\n"
            f"id: {self.task_id}-response\n"
            f"in_response_to: {self.task_id}\n"
            "from: claude\n"
            "to: chrono\n"
            "type: RESULT\n"
            f"status: {status}\n"
            f"return_artifact: {result_relative}\n"
            f"{worker_frontmatter}"
            "---\n\n"
            "Promoted summary.\n",
            encoding="utf-8",
        )
        authority: dict[str, object] = {
            "task_id": self.task_id,
            "lane": "claude",
            "write_paths": ["_state/r1/"],
            "expected_result_path": result_relative,
            "expected_outbox_path": outbox_relative,
        }
        if reconciliation_echo is not None:
            authority["reconciliation_echo"] = reconciliation_echo
        prepared = dcb.prepare_worktree_outputs(repo, worker, authority)
        dcb.publish_prepared_worktree_outputs(repo, prepared)
        return repo / outbox_relative

    def test_capability_pin_survives_promotion(self) -> None:
        entry = {"capability_card_sha256": CAPABILITY_PIN}
        with tempfile.TemporaryDirectory() as directory:
            published = self._promote(
                Path(directory),
                reconciliation_echo={"capability_card_sha256": CAPABILITY_PIN},
            )
            self.assertEqual(
                reconciler.capability_response_issue(entry, published), ""
            )
            self.assertEqual(reconciler.response_status(published), "complete")

    def test_swarm_member_pin_survives_promotion(self) -> None:
        entry = {
            "dispatch_kind": "swarm",
            "swarm_role": "member",
            "swarm_spec_sha256": SWARM_PIN,
        }
        with tempfile.TemporaryDirectory() as directory:
            published = self._promote(
                Path(directory),
                reconciliation_echo={"swarm_spec_sha256": SWARM_PIN},
            )
            self.assertEqual(reconciler.swarm_response_issue(entry, published), "")

    def test_legacy_worker_fence_survives_promotion(self) -> None:
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        entry = {
            "delivery_worker_id": "worker-01",
            "worker_assignment_state": "in-progress",
            "lease_expires_at": expiry.isoformat(),
            "delivery_attempt_id": self.attempt_id,
            "delivery_generation": 3,
            "worker_epoch": "e-7",
            "lease_generation": 2,
            "delivery_lane": "claude",
            "replica_index": 1,
            "member_id": "claude:r01",
        }
        echo = {
            "delivery_attempt_id": self.attempt_id,
            "delivery_generation": "3",
            "delivery_worker_id": "worker-01",
            "worker_epoch": "e-7",
            "lease_generation": "2",
            "delivery_lane": "claude",
            "replica_index": "1",
            "member_id": "claude:r01",
        }
        with tempfile.TemporaryDirectory() as directory:
            published = self._promote(
                Path(directory), reconciliation_echo=echo
            )
            self.assertEqual(
                reconciler.worker_response_issue(self.task_id, entry, published),
                "",
            )

    def test_ordinary_single_response_needs_no_echo(self) -> None:
        """An unpinned single dispatch still settles with no extra rows."""

        with tempfile.TemporaryDirectory() as directory:
            published = self._promote(Path(directory), reconciliation_echo={})
            self.assertEqual(reconciler.capability_response_issue({}, published), "")
            self.assertEqual(reconciler.swarm_response_issue({}, published), "")
            self.assertEqual(
                reconciler.worker_response_issue(self.task_id, {}, published), ""
            )

    def test_echo_comes_from_authority_not_worker_metadata(self) -> None:
        """A worker-forged pin must be overwritten by the launch authority."""

        entry = {"capability_card_sha256": CAPABILITY_PIN}
        with tempfile.TemporaryDirectory() as directory:
            published = self._promote(
                Path(directory),
                reconciliation_echo={"capability_card_sha256": CAPABILITY_PIN},
                worker_frontmatter=f"capability_card_sha256: {'0' * 64}\n",
            )
            text = published.read_text(encoding="utf-8")
            self.assertIn(f"capability_card_sha256: {CAPABILITY_PIN}", text)
            self.assertNotIn("0" * 64, text)
            self.assertEqual(
                reconciler.capability_response_issue(entry, published), ""
            )

    def test_echo_rejects_unknown_or_malformed_keys(self) -> None:
        for echo in (
            {"status": "complete"},
            {"capability_card_sha256": "not-hex"},
            {"delivery_lane": "claude\nid: forged"},
        ):
            with self.subTest(echo=echo), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(dcb.DispatchContextError):
                    self._promote(Path(directory), reconciliation_echo=echo)

    def test_build_context_derives_the_echo_from_the_packet(self) -> None:
        """A capability-pinned packet yields a capability echo in the authority."""

        fields = {
            "capability_card_sha256": CAPABILITY_PIN,
            "dispatch_kind": "swarm",
            "swarm_role": "member",
            "swarm_spec_sha256": SWARM_PIN,
        }
        echo = dcb.packet_reconciliation_echo(fields)
        self.assertEqual(
            echo,
            {
                "capability_card_sha256": CAPABILITY_PIN,
                "swarm_spec_sha256": SWARM_PIN,
            },
        )
        self.assertEqual(dcb.packet_reconciliation_echo({}), {})

    def test_swarm_pin_is_only_echoed_for_members(self) -> None:
        """A swarm PARENT must not echo the member-only spec pin."""

        echo = dcb.packet_reconciliation_echo(
            {
                "dispatch_kind": "swarm",
                "swarm_role": "parent",
                "swarm_spec_sha256": SWARM_PIN,
            }
        )
        self.assertNotIn("swarm_spec_sha256", echo)


# ─────────────────────────────────────────────────────────────────────────────
# F5 — a never-launched task must release its write_scope immediately
# ─────────────────────────────────────────────────────────────────────────────


class NeverLaunchedReleaseTests(unittest.TestCase):
    task_id = "TASK-2026-07-26-9002-never-launched"
    attempt_id = "d-" + "c" * 32

    @staticmethod
    @contextmanager
    def _patch_runtime(root: Path, state: Path, registry_path: Path):
        patchers = (
            mock.patch.object(reconciler, "VAULT_ROOT", root),
            mock.patch.object(reconciler, "STATE_DIR", state),
            mock.patch.object(reconciler, "REGISTRY_PATH", registry_path),
            mock.patch.object(
                reconciler, "CHRONO_QUEUE_PATH", state / "chrono-queue.md"
            ),
            mock.patch.object(
                reconciler, "CHRONO_NOTIFY_LOCKDIR", state / "chrono-notify.lockdir"
            ),
            mock.patch.object(
                reconciler,
                "CHRONO_NOTIFY_RECEIPTS_DIR",
                state / "chrono-notify-receipts",
            ),
            mock.patch.object(
                reconciler, "RESPONSE_MIN_AGE", reconciler.timedelta(seconds=0)
            ),
            mock.patch.dict("os.environ", {reconciler.TEST_ISOLATION_ENV: "1"}),
        )
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            yield

    def _registry(self, directory: Path, **overrides: object) -> tuple[Path, Path, Path]:
        root = directory
        state = root / "_state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "board-dispatch").mkdir(parents=True, exist_ok=True)
        registry_path = state / "active-tasks.json"
        queued_at = (
            datetime.now(timezone.utc) - timedelta(minutes=30)
        ).isoformat()
        entry: dict[str, object] = {
            "status": "in-flight",
            "specialist": "systems-engineer",
            "to_model": "claude",
            "compatibility_namespace": "coding",
            "return_artifact": "_state/consults/never-launched.md",
            "write_scope": ["shared/contended-scope"],
            "delivery_attempt_id": self.attempt_id,
            "delivery_generation": 1,
            "delivery_lane": "claude",
            "delivery_state": "queued",
            "delivery_attempt_count": 0,
            "delivery_worker_id": None,
            "claimed_at": None,
            "started_at": None,
            "dispatched_at": queued_at,
            "enqueued_at": queued_at,
        }
        entry.update(overrides)
        registry_path.write_text(
            json.dumps({self.task_id: entry}) + "\n", encoding="utf-8"
        )
        return root, state, registry_path

    def _reconcile(self, root: Path, state: Path, registry_path: Path):
        with self._patch_runtime(root, state, registry_path):
            changed, messages = reconciler.reconcile(self.task_id, dry_run=False)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        return changed, messages, registry[self.task_id]

    def test_never_launched_task_auto_settles_and_releases_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(Path(directory))
            changed, messages, entry = self._reconcile(root, state, registry_path)

            self.assertGreater(changed, 0, messages)
            # Anything other than in-flight releases the write_scope: the
            # send-task conflict check only counts in-flight entries.
            self.assertNotEqual(entry["status"], "in-flight")
            self.assertEqual(entry["status"], "cancelled")
            self.assertEqual(entry["delivery_state"], "terminal")
            self.assertTrue(entry.get("never_launched_reason"))

    def test_a_task_still_inside_the_launch_window_is_left_alone(self) -> None:
        recent = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(
                Path(directory), dispatched_at=recent, enqueued_at=recent
            )
            _changed, _messages, entry = self._reconcile(root, state, registry_path)
            self.assertEqual(entry["status"], "in-flight")

    def test_a_started_task_is_never_auto_cancelled(self) -> None:
        started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(
                Path(directory),
                delivery_state="in-progress",
                delivery_attempt_count=1,
                started_at=started,
                claimed_at=started,
            )
            _changed, _messages, entry = self._reconcile(root, state, registry_path)
            self.assertEqual(entry["status"], "in-flight")

    def test_a_pool_assigned_task_awaiting_its_worker_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(
                Path(directory),
                delivery_worker_id="worker-01",
                worker_epoch="e-1",
                lease_generation=1,
                worker_assignment_state="assigned",
            )
            _changed, _messages, entry = self._reconcile(root, state, registry_path)
            self.assertEqual(entry["status"], "in-flight")

    def test_a_queued_task_that_left_residue_is_left_alone(self) -> None:
        """Residue means it ran; only zero-artifact launches auto-cancel."""

        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(Path(directory))
            artifact = root / "_state" / "consults" / "never-launched.md"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("partial work\n", encoding="utf-8")
            _changed, _messages, entry = self._reconcile(root, state, registry_path)
            self.assertNotEqual(entry["status"], "cancelled")

    def test_a_queued_task_with_an_attempt_worktree_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state, registry_path = self._registry(Path(directory))
            (state / "board-worktrees" / self.attempt_id).mkdir(parents=True)
            _changed, _messages, entry = self._reconcile(root, state, registry_path)
            self.assertEqual(entry["status"], "in-flight")


# ─────────────────────────────────────────────────────────────────────────────
# F6 — a non-headless REQUIRED tool must not gate a headless spawn
# ─────────────────────────────────────────────────────────────────────────────


class NonHeadlessRequiredToolTests(unittest.TestCase):
    projection = {
        "mcps": [],
        "brokered_mcps": [],
        "tools": ["pdftotext", "zotero"],
        "skills": [],
    }

    def _plan(self, **kwargs):
        return lce.plan_lane(
            lane="claude",
            projection=self.projection,
            configured_servers={},
            tool_lookup=lambda name: "/usr/bin/pdftotext" if name == "pdftotext" else None,
            **kwargs,
        )

    def test_host_app_bundle_tool_does_not_deny_a_headless_launch(self) -> None:
        plan = self._plan(
            tool_classes={
                "pdftotext": {"requirement": "required", "evidence": "host-PATH"},
                "zotero": {"requirement": "required", "evidence": "host-app-bundle"},
            }
        )
        self.assertIn("zotero", plan.capability_gaps)
        self.assertNotIn("zotero", plan.available_tools)
        self.assertIn("pdftotext", plan.available_tools)

    def test_operator_install_tool_does_not_deny_a_headless_launch(self) -> None:
        plan = self._plan(
            tool_classes={
                "zotero": {
                    "requirement": "required",
                    "availability": "needs-operator-install",
                    "evidence": "operator-install-required",
                }
            }
        )
        self.assertIn("zotero", plan.capability_gaps)

    def test_a_preferred_missing_tool_never_denies(self) -> None:
        plan = self._plan(
            tool_classes={
                "zotero": {"requirement": "preferred", "evidence": "host-PATH"}
            }
        )
        self.assertIn("zotero", plan.capability_gaps)

    def test_a_genuinely_missing_headless_required_tool_still_denies(self) -> None:
        with self.assertRaises(lce.CapabilityDenied) as caught:
            self._plan(
                tool_classes={
                    "zotero": {"requirement": "required", "evidence": "host-PATH"}
                }
            )
        self.assertIn("zotero", str(caught.exception))

    def test_an_unclassified_missing_tool_still_denies(self) -> None:
        """No classification must stay fail-closed, not fail-open."""

        with self.assertRaises(lce.CapabilityDenied):
            self._plan(tool_classes={})

    def test_real_knowledge_librarian_role_plans_without_denial(self) -> None:
        """The exact F6 repro: knowledge-librarian requires the zotero app bundle."""

        classes = lce.load_tool_classes(
            repo_root=ROOT, lane="claude", specialist="knowledge-librarian"
        )
        self.assertEqual(classes["zotero"]["evidence"], "host-app-bundle")
        plan = lce.plan_lane(
            lane="claude",
            projection={
                "mcps": [],
                "brokered_mcps": [],
                "tools": ["pdftotext", "zotero"],
                "skills": [],
            },
            configured_servers={},
            tool_lookup=lambda name: "/usr/bin/pdftotext"
            if name == "pdftotext"
            else None,
            tool_classes=classes,
        )
        self.assertIn("zotero", plan.capability_gaps)

    def test_codex_runtime_alias_resolves_gpt_codex_tool_classes(self) -> None:
        classes = lce.load_tool_classes(
            repo_root=ROOT, lane="codex", specialist="data-extraction-engineer"
        )
        self.assertEqual(classes["pdftotext"]["requirement"], "required")
        self.assertEqual(classes["pandas"]["requirement"], "preferred")
        self.assertEqual(classes["pandas"]["evidence"], "repo-venv-interpreter")


# ─────────────────────────────────────────────────────────────────────────────
# CC-17 — one worker status enum across toolkit, bridge, watcher, reconciler
# ─────────────────────────────────────────────────────────────────────────────


class WorkerStatusEnumTests(unittest.TestCase):
    def test_needs_human_is_not_silently_downgraded(self) -> None:
        self.assertEqual(dcb._coerce_status("needs_human"), "needs_human")
        self.assertEqual(dcb._coerce_status("needs human"), "needs_human")

    def test_worker_statuses_agree_with_the_reconciler(self) -> None:
        self.assertTrue(
            dcb.WORKER_AUTHORABLE_STATUSES <= reconciler.SETTLEABLE_STATUSES,
            "a worker-authorable status the reconciler cannot settle strands work",
        )
        # `cancelled` is controller-only: a worker must never self-cancel.
        self.assertNotIn("cancelled", dcb.WORKER_AUTHORABLE_STATUSES)
        self.assertIn("cancelled", reconciler.SETTLEABLE_STATUSES)

    def test_dispatch_toolkit_injects_the_same_enum(self) -> None:
        """The injected envelope SCHEMA must offer every worker status.

        Scoped to the fenced schema block (not the whole appended brief), so a
        status merely mentioned further down in the no-delete rule -- the exact
        CC-17 split -- does not satisfy this.
        """

        text = (ROOT / "shared" / "dispatch-toolkit.sh").read_text(encoding="utf-8")
        start = text.index("## Completion contract")
        schema = text[start : text.index("COMPLETION_EOF", start)]
        for status in sorted(dcb.WORKER_AUTHORABLE_STATUSES):
            self.assertIn(
                status,
                schema,
                f"{status} is settleable but never offered to workers",
            )

    def test_the_no_delete_rule_status_is_worker_authorable(self) -> None:
        """The injected no-delete rule tells workers to emit `needs_human`."""

        text = (ROOT / "shared" / "dispatch-toolkit.sh").read_text(encoding="utf-8")
        no_delete = text[text.index("spec-1.5-no-delete-rule") :]
        self.assertIn("needs_human", no_delete)
        self.assertIn("needs_human", dcb.WORKER_AUTHORABLE_STATUSES)

    def test_needs_human_survives_promotion_end_to_end(self) -> None:
        promoter = PromotionPinEchoTests()
        with tempfile.TemporaryDirectory() as directory:
            published = promoter._promote(
                Path(directory), reconciliation_echo={}, status="needs_human"
            )
            self.assertEqual(reconciler.response_status(published), "needs_human")

    def test_protocol_documents_the_single_enum(self) -> None:
        text = (ROOT / "shared" / "protocol.md").read_text(encoding="utf-8")
        for status in sorted(reconciler.SETTLEABLE_STATUSES):
            self.assertIn(status, text)


# ─────────────────────────────────────────────────────────────────────────────
# F7 — contract admission errors must name the offending field
# ─────────────────────────────────────────────────────────────────────────────


class ContractAdmissionDiagnosticsTests(unittest.TestCase):
    def test_missing_contract_names_the_field(self) -> None:
        with self.assertRaises(dcb.DispatchContextError) as caught:
            dcb.validate_verification_contract({"id": "TASK-2026-07-26-9003-x"})
        message = str(caught.exception)
        self.assertIn("verification_contract", message)

    def test_missing_hash_names_the_field(self) -> None:
        # Valid contract, absent hash: the diagnostic must name the hash field.
        contract = _valid_contract()
        with self.assertRaises(dcb.DispatchContextError) as caught:
            dcb.validate_verification_contract(
                {
                    "id": "TASK-2026-07-26-9003-x",
                    "verification_contract": json.dumps(contract),
                }
            )
        self.assertIn("verification_contract_sha256", str(caught.exception))

    def test_missing_phase_arrays_name_the_fields(self) -> None:
        # Valid contract whose phase arrays are EMPTY -- the branch under test
        # is emptiness, not absence.
        contract = _valid_contract(
            required_phase_ids=[], required_verification_kinds=[]
        )
        raw = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        digest = dcb._sha256_bytes(dcb._canonical_json(json.loads(raw)))
        with self.assertRaises(dcb.DispatchContextError) as caught:
            dcb.validate_verification_contract(
                {
                    "id": "TASK-2026-07-26-9003-x",
                    "verification_contract": raw,
                    "verification_contract_sha256": digest,
                }
            )
        message = str(caught.exception)
        self.assertIn("required_phase_ids", message)
        self.assertIn("required_verification_kinds", message)

    def test_required_packet_fields_are_named_individually(self) -> None:
        for missing, present in (
            ("run_id", {"source_namespace": "coding", "mode": "project"}),
            ("mode", {"source_namespace": "coding", "run_id": "none"}),
            ("source_namespace", {"run_id": "none", "mode": "project"}),
        ):
            with self.subTest(missing=missing):
                with self.assertRaises(dcb.DispatchContextError) as caught:
                    dcb.require_packet_fields(present)
                self.assertIn(missing, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
