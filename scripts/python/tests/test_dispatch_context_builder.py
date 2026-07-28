from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


TASK = (
    ROOT
    / "departments"
    / "coding"
    / "inbox"
    / "TASK-2026-07-23-0905-v2-cutover-build.md"
)
EXPECTED_AUTHORITY_FIELDS = {
    "schema", "task_id", "attempt_id", "generation", "run_id",
    "author_family", "workload_class", "specialist", "lane", "mode_profile",
    "execution_kind", "repo_root", "pool_root", "canonical_role_path",
    "canonical_role_sha256", "lane_overlay_path", "lane_overlay_sha256",
    "executable", "executable_sha256", "lane_args", "write_paths",
    "read_scope", "depends_on", "resources", "scheduler_concurrency",
    "scheduler_capacities", "scheduler_settled", "network_scope",
    "action_scope", "budgets", "expected_result_path",
    "expected_outbox_path", "reconciliation_echo",
    "required_phase_ids", "verification_kinds",
    "operator_gates", "packet_sha256", "plan_sha256",
    "verification_contract_sha256", "selected_model_sha256",
    "profile_bundle_sha256", "active_board_tasks", "created_at",
    "expires_at", "nonce",
}


class DispatchContextBuilderTests(unittest.TestCase):
    def _fake_repo_for_lane(
        self,
        base: Path,
        *,
        lane: str,
        model: str,
    ) -> tuple[Path, Path]:
        root = base / lane
        specialist = f"{lane}-canary"
        namespace = "coding"
        header = (
            ROOT / "shared" / "specialist-runtime-map.tsv"
        ).read_text(encoding="utf-8").splitlines()[0].split("\t")
        row = {field: "none" for field in header}
        row.update(
            {
                "specialist": specialist,
                "source_namespace": namespace,
                "primary_lane": lane,
                "primary_profile": f"{lane}-default",
            }
        )
        runtime_map = root / "shared" / "specialist-runtime-map.tsv"
        runtime_map.parent.mkdir(parents=True)
        runtime_map.write_text(
            "\t".join(header)
            + "\n"
            + "\t".join(row[field] for field in header)
            + "\n",
            encoding="utf-8",
        )
        capability_source = (
            root / "model-lanes" / "specialist-lane-capabilities.v1.json"
        )
        capability_source.parent.mkdir(parents=True)
        capability_source.write_text("{}\n", encoding="utf-8")
        profiles = root / "shared" / "registries" / "profiles.tsv"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            "profile_id\tlane\tmodel_id\teffort\tflags\tusage\n"
            f"{lane}-default\t{lane}\t{lane}-test-model\thigh\tnone\tprimary\n",
            encoding="utf-8",
        )
        role = (
            root
            / "departments"
            / namespace
            / "specialists"
            / f"{specialist}.md"
        )
        role.parent.mkdir(parents=True)
        role.write_text(f"# {specialist}\n", encoding="utf-8")
        adapter = {
            "codex": (
                root
                / "model-lanes"
                / "gpt-codex"
                / ".codex"
                / "agents"
                / f"{specialist}.toml"
            ),
            "claude": (
                root
                / "model-lanes"
                / "claude"
                / ".claude"
                / "agents"
                / f"{specialist}.md"
            ),
            "gemini": (
                root
                / "model-lanes"
                / "gemini"
                / ".gemini"
                / "agents"
                / f"{specialist}.md"
            ),
            "kimi": (
                root
                / "model-lanes"
                / "kimi"
                / ".kimi"
                / "agents"
                / f"{specialist}.yaml"
            ),
        }[lane]
        adapter.parent.mkdir(parents=True)
        adapter.write_text(f"name: {specialist}\n", encoding="utf-8")
        task_id = f"TASK-2026-07-23-998{len(lane)}-{lane}"
        contract = {
            "task_id": task_id,
            "run_id": "RUN-TEST",
            "mode": "project",
            "author_family": "test",
            "required_phase_ids": ["S0", "S7"],
            "required_verification_kinds": ["recipient_contract"],
        }
        contract_text = json.dumps(
            contract, sort_keys=True, separators=(",", ":")
        )
        contract_hash = hashlib.sha256(contract_text.encode("ascii")).hexdigest()
        packet = (
            root
            / "departments"
            / namespace
            / "inbox"
            / f"{task_id}.md"
        )
        packet.parent.mkdir(parents=True)
        packet.write_text(
            "---\n"
            f"id: {task_id}\n"
            f"to_model: {model}\n"
            f"specialist: {specialist}\n"
            f"source_namespace: {namespace}\n"
            "mode: project\n"
            "run_id: RUN-TEST\n"
            "write_scope: [_state/canary/]\n"
            "return_artifact: _state/canary/result.md\n"
            f"verification_contract: {contract_text}\n"
            f"verification_contract_sha256: {contract_hash}\n"
            "---\n\n"
            "Write the result.\n",
            encoding="utf-8",
        )
        return root, packet

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_real_packet_builds_exact_trusted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            context = dcb.build_context(
                root,
                packet,
                attempt_id="d-" + "1" * 32,
                generation=1,
                now=1_784_800_000,
                nonce="2" * 64,
            )

            self.assertEqual(context["schema"], "go-live-trusted-context/v1")
            self.assertEqual(set(context), {"schema", "authority", "task_prompt"})
            authority = context["authority"]
            self.assertEqual(authority["schema"], "go-live-authority/v1")
            self.assertEqual(authority["lane"], "codex")
            self.assertEqual(authority["attempt_id"], "d-" + "1" * 32)
            self.assertEqual(authority["generation"], 1)
            self.assertEqual(
                authority["expected_outbox_path"],
                "departments/coding/outbox/"
                f"{packet.stem}-response.md",
            )
            self.assertEqual(
                authority["expected_result_path"],
                "_state/canary/result.md",
            )
            self.assertEqual(
                tuple(authority["lane_args"]),
                dcb.trusted_lane_args_for(
                    root,
                    lane="codex",
                    specialist="codex-canary",
                ),
            )
            self.assertEqual(
                authority["packet_sha256"],
                hashlib.sha256(packet.read_bytes()).hexdigest(),
            )
            self.assertIn(str(packet.relative_to(root)), authority["read_scope"])
            self.assertIn(packet.stem, context["task_prompt"])

    @skip_in_host_independent_ci(
        "needs all four installed model lane executables"
    )
    def test_exact_authority_context_builds_for_all_four_lanes(self) -> None:
        models = {
            "codex": "gpt-codex",
            "claude": "claude",
            "gemini": "gemini",
            "kimi": "kimi",
        }
        with tempfile.TemporaryDirectory() as directory:
            for lane, model in models.items():
                with self.subTest(lane=lane):
                    root, packet = self._fake_repo_for_lane(
                        Path(directory),
                        lane=lane,
                        model=model,
                    )
                    context = dcb.build_context(
                        root,
                        packet,
                        attempt_id="d-" + "3" * 32,
                        generation=2,
                        now=1_784_800_000,
                        nonce="4" * 64,
                    )
                    authority = context["authority"]
                    self.assertEqual(authority["lane"], lane)
                    self.assertEqual(
                        tuple(authority["lane_args"]),
                        dcb.trusted_lane_args_for(
                            root,
                            lane=lane,
                            specialist=f"{lane}-canary",
                        ),
                    )
                    self.assertIn("--model", authority["lane_args"])
                    expected_model = {
                        "gemini": "gemini-3.6-flash",
                        "kimi": "kimi-code/kimi-for-coding",
                    }.get(lane, f"{lane}-test-model")
                    self.assertIn(expected_model, authority["lane_args"])
                    self.assertEqual(authority["generation"], 2)
                    self.assertEqual(
                        authority["budgets"]["timeout_seconds"],
                        1800,  # safety backstop, not a short deadline (all lanes)
                    )
                    self.assertEqual(set(authority), EXPECTED_AUTHORITY_FIELDS)
                    self.assertEqual(
                        authority["profile_bundle_sha256"],
                        dcb.SETTLED_T1P1_BUNDLE_SHA256,
                    )

    def test_invalid_attempt_and_generation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.build_context(
                    root,
                    packet,
                    attempt_id="fresh-unregistered-attempt",
                    generation=1,
                )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.build_context(
                    root,
                    packet,
                    attempt_id="d-" + "1" * 32,
                    generation=0,
                )

    def test_contract_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            fields, _body = dcb.parse_task_packet(packet)
            fields["verification_contract_sha256"] = "f" * 64
            with self.assertRaises(dcb.DispatchContextError):
                dcb.validate_verification_contract(fields)

    def test_advisory_contract_accepts_empty_phase_array(self) -> None:
        contract = {
            "task_id": "TASK-2026-07-24-9997-advisory-context",
            "run_id": "ADV-TEST",
            "mode": "advisory",
            "required_phase_ids": [],
            "required_verification_kinds": ["artifact_written"],
        }
        contract_text = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        fields = {
            "id": contract["task_id"],
            "verification_contract": contract_text,
            "verification_contract_sha256": hashlib.sha256(
                contract_text.encode("ascii")
            ).hexdigest(),
        }

        self.assertEqual(dcb.validate_verification_contract(fields), contract)

    def test_scope_parser_rejects_traversal_and_absolute_paths(self) -> None:
        for raw in ("[../../outside]", '["/absolute/path"]', "[.]"):
            with self.subTest(raw=raw):
                with self.assertRaises(dcb.DispatchContextError):
                    dcb.parse_scope(raw, field="write_scope")


class OutputBridgeTests(unittest.TestCase):
    @staticmethod
    def _authority(task_id: str) -> dict[str, object]:
        result = "_state/cutover-canary/ok.md"
        return {
            "task_id": task_id,
            "lane": "codex",
            "write_paths": [result],
            "expected_result_path": result,
            "expected_outbox_path": (
                f"departments/coding/outbox/{task_id}-response.md"
            ),
        }

    def test_artifact_is_promoted_before_valid_envelope_and_retry_is_idempotent(self) -> None:
        task_id = "TASK-2026-07-23-9991-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Canary completed.\n",
                encoding="utf-8",
            )

            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(
                (root / "_state" / "cutover-canary" / "ok.md").read_text(),
                "OK\n",
            )
            self.assertTrue(
                (root / "departments" / "coding" / "outbox"
                 / f"{task_id}-response.md").is_file()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["artifact_published"])
            self.assertTrue(receipt["envelope_published"])

            retry = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertTrue(retry["artifact_idempotent"])
            self.assertTrue(retry["envelope_idempotent"])

    def test_invalid_envelope_never_promotes_artifact(self) -> None:
        task_id = "TASK-2026-07-23-9992-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text("---\nstatus: complete\n---\n", encoding="utf-8")

            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(
                    root, worktree, self._authority(task_id)
                )
            self.assertFalse(
                (root / "_state" / "cutover-canary" / "ok.md").exists()
            )

    def test_advisory_completed_envelope_promotes_nonempty_artifact(self) -> None:
        task_id = "TASK-2026-07-24-9996-advisory-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("Independent opinion.\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: completed\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Advisory completed.\n",
                encoding="utf-8",
            )

            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )

            self.assertEqual(receipt["status"], "completed")
            self.assertTrue(receipt["artifact_published"])
            self.assertTrue(receipt["envelope_published"])

    def test_controller_blocked_completion_is_artifact_first(self) -> None:
        task_id = "TASK-2026-07-23-9993-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            receipt = dcb.publish_blocked_completion(
                repo_root=root,
                task_id=task_id,
                lane="codex",
                return_artifact="_state/cutover-canary/blocked.md",
                compatibility_namespace="coding",
                reason="supervisor returned 75",
            )
            self.assertTrue(
                (root / "_state" / "cutover-canary" / "blocked.md").is_file()
            )
            response = (
                root
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            self.assertIn("status: blocked", response.read_text())
            self.assertEqual(receipt["status"], "blocked")

    def test_atomic_publish_never_replaces_an_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "_state" / "cutover-canary" / "ok.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("existing\n", encoding="utf-8")

            with self.assertRaises(dcb.DispatchContextError):
                dcb._atomic_publish(
                    root,
                    "_state/cutover-canary/ok.md",
                    b"replacement\n",
                    label="return artifact",
                )
            self.assertEqual(destination.read_text(encoding="utf-8"), "existing\n")

    def _stage_completion(
        self,
        directory: str,
        task_id: str,
        *,
        envelope_text: str,
        artifact_text: str = "OK\n",
    ) -> tuple[Path, Path]:
        """Lay out a worktree with a real artifact and a raw worker envelope."""
        root = Path(directory) / "main"
        worktree = Path(directory) / "worktree"
        (root / "departments" / "coding" / "outbox").mkdir(parents=True)
        result = worktree / "_state" / "cutover-canary" / "ok.md"
        result.parent.mkdir(parents=True)
        if artifact_text:
            result.write_text(artifact_text, encoding="utf-8")
        envelope = (
            worktree / "departments" / "coding" / "outbox"
            / f"{task_id}-response.md"
        )
        envelope.parent.mkdir(parents=True)
        envelope.write_text(envelope_text, encoding="utf-8")
        return root, worktree

    def test_noncanonical_status_is_normalized_and_promoted(self) -> None:
        # The exact K3-wiring repro: a worker minted `complete_with_scoped_exclusion`
        # over real, complete work. Normalize the status intent to `complete` and
        # promote instead of stranding the finished run.
        task_id = "TASK-2026-07-26-8001-normalize"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete_with_scoped_exclusion\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Wired K3 with one scoped exclusion.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["envelope_published"])
            published = (
                root / "departments" / "coding" / "outbox"
                / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            self.assertIn("status: complete\n", published)
            self.assertNotIn("scoped_exclusion", published)
            # The worker's summary prose survives the normalization.
            self.assertIn("Wired K3 with one scoped exclusion.", published)
            # Retry is idempotent because reconstruction is deterministic.
            retry = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertTrue(retry["envelope_idempotent"])

    def test_missing_and_extra_fields_are_normalized_and_promoted(self) -> None:
        # The offense-track repro: a required field missing AND an unexpected
        # extra field, over complete work. Default the missing field from the
        # trusted launch authority, ignore the extra, and promote.
        task_id = "TASK-2026-07-26-8002-repair"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    # `from` intentionally omitted (missing required field)
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "phase: S7\n"  # unexpected extra field
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Offense skills landed.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["envelope_published"])
            published = (
                root / "departments" / "coding" / "outbox"
                / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            # Missing `from` defaulted from authority (codex lane -> gpt-codex).
            self.assertIn("from: gpt-codex\n", published)
            # Unexpected extra dropped from the canonical envelope.
            self.assertNotIn("phase: S7", published)

    def test_wrong_identity_field_is_repaired_from_authority(self) -> None:
        # A worker that put the wrong lane in `from` should be repaired to the
        # authority value, not stranded.
        task_id = "TASK-2026-07-26-8003-identity"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gemini\n"  # wrong lane; authority says codex
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Done.\n"
                ),
            )
            dcb.bridge_worktree_outputs(root, worktree, self._authority(task_id))
            published = (
                root / "departments" / "coding" / "outbox"
                / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            self.assertIn("from: gpt-codex\n", published)
            self.assertNotIn("from: gemini", published)

    def test_empty_summary_still_blocks(self) -> None:
        # Genuinely-empty report (no summary) is NOT a recoverable metadata
        # deviation; it must still block and never promote the artifact.
        task_id = "TASK-2026-07-26-8004-empty"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "   \n"
                ),
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(
                    root, worktree, self._authority(task_id)
                )
            self.assertFalse(
                (root / "_state" / "cutover-canary" / "ok.md").exists()
            )

    def test_absent_artifact_still_blocks(self) -> None:
        # No return artifact = genuinely-missing work; still blocks even with a
        # perfectly-formed envelope.
        task_id = "TASK-2026-07-26-8005-noartifact"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                artifact_text="",  # no artifact written
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Claims done but wrote nothing.\n"
                ),
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(
                    root, worktree, self._authority(task_id)
                )

    def test_unrecognized_status_defaults_to_needs_review(self) -> None:
        # An unmappable status defaults to needs_review so questionable work
        # surfaces to the controller rather than silently auto-closing.
        task_id = "TASK-2026-07-26-8006-unknown"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: partially_maybe\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Ambiguous outcome.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "needs_review")

    def test_coerce_status_mapping(self) -> None:
        self.assertEqual(dcb._coerce_status("complete"), "complete")
        self.assertEqual(dcb._coerce_status("completed"), "completed")
        self.assertEqual(dcb._coerce_status("needs_review"), "needs_review")
        self.assertEqual(dcb._coerce_status("blocked"), "blocked")
        self.assertEqual(
            dcb._coerce_status("complete_with_scoped_exclusion"), "complete"
        )
        self.assertEqual(dcb._coerce_status("done"), "complete")
        self.assertEqual(dcb._coerce_status("failed"), "blocked")
        self.assertEqual(dcb._coerce_status("blocked_on_review"), "blocked")
        # CC-17: `needs_human` is its own escalation level (an operator decision
        # is owed), not a synonym for `needs_review`. The injected no-delete rule
        # instructs workers to emit it, so downgrading it here silently dropped
        # the escalation. It must survive verbatim.
        self.assertEqual(dcb._coerce_status("needs_human"), "needs_human")
        self.assertEqual(dcb._coerce_status("needs human review"), "needs_human")
        self.assertEqual(dcb._coerce_status("awaiting operator approval"), "needs_human")
        self.assertEqual(dcb._coerce_status(""), "needs_review")
        self.assertEqual(dcb._coerce_status("wat"), "needs_review")


if __name__ == "__main__":
    unittest.main()
