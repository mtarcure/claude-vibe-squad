#!/usr/bin/env python3
"""Tests for the dispatcher-owned verification contract."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

from verification_contract import (  # noqa: E402
    CONTRACT_VERSION,
    ContractError,
    author_family_for_lane,
    derive_verification_contract,
    read_packet_contract_echoes,
    read_yaml_frontmatter,
    validate_verification_contract,
    verification_contract_sha256,
)


class VerificationContractTests(unittest.TestCase):
    def admission(
        self,
        *,
        mode: str = "project",
        result_type: str = "normal",
        to_model: str = "gpt-codex",
    ) -> dict[str, object]:
        return {
            "task_id": "TASK-TEST-001",
            "run_id": "PRJ-TEST-001" if mode == "project" else "BTY-TEST-001",
            "mode": mode,
            "result_type": result_type,
            "to_model": to_model,
            "dispatch_kind": "single",
            "capability": {
                "id": "project/web-app" if mode == "project" else "bounty/authorized-red-team",
                "card_sha256": "a" * 64,
                "derived_state": "live",
                "expected_gates": ["production_mutation", "public_release"],
            },
            "runtime_map_gates": ["credential_change"],
        }

    def expected_contract(
        self,
        *,
        mode: str,
        result_type: str,
        author_family: str = "openai",
    ) -> dict[str, object]:
        if mode == "project":
            verification_kinds = ["project_tests", "recipient_contract"]
            bounty_policy = None
        else:
            verification_kinds = (
                ["scope_gate", "no_self_inflicted", "negative_control"]
                if result_type == "dry_run"
                else ["scope_gate", "no_self_inflicted", "poc_reproduction"]
            )
            bounty_policy = {
                "scope_gate_required": True,
                "exact_target_allowlist_required": True,
                "no_self_inflicted_required": True,
                "submission_attempted_allowed": False,
                "normal_finding_requirements": [
                    "cvss_v4",
                    "cross_family_reproduction",
                    "negative_control",
                ],
                "dry_run_requirements": [
                    "empty_findings",
                    "kill_or_negative_evidence",
                    "no_submit_evidence",
                ],
            }
        return {
            "contract_version": CONTRACT_VERSION,
            "task_id": "TASK-TEST-001",
            "run_id": "PRJ-TEST-001" if mode == "project" else "BTY-TEST-001",
            "mode": mode,
            "result_type": result_type,
            "dispatch_kind": "single",
            "author_family": author_family,
            "capability": {
                "id": "project/web-app" if mode == "project" else "bounty/authorized-red-team",
                "card_sha256": "a" * 64,
                "derived_state": "live",
            },
            "required_phase_ids": [f"S{i}" for i in range(8)],
            "required_verification_kinds": verification_kinds,
            "memory_policy": {"recall": "required", "record": "required"},
            "plan_review_policy": {
                "required": True,
                "anti_affinity": "author_family",
                "subject": "plan_sha256",
            },
            "deliverable_review_policy": {
                "required": True,
                "anti_affinity": "author_family",
                "subject": "artifact_bundle_sha256",
            },
            "artifact_policy": {
                "hashes_required": True,
                "bundle_hash_algorithm": "canonical-artifact-list-sha256/v1",
            },
            "action_log_policy": {"required": True},
            "iteration_policy": {
                "routes": ["S2", "S3"],
                "invalidates_on": ["plan_sha256", "artifact_bundle_sha256"],
            },
            "expected_gates": [
                "credential_change",
                "production_mutation",
                "public_release",
            ],
            "external_delivery_policy": {"allowed": False},
            "bounty_policy": bounty_policy,
        }

    def test_canonical_hash_is_key_order_independent_and_value_sensitive(self) -> None:
        first = self.expected_contract(mode="project", result_type="normal")
        reordered = dict(reversed(list(first.items())))
        self.assertEqual(
            verification_contract_sha256(first),
            verification_contract_sha256(reordered),
        )
        changed = dict(first)
        changed["run_id"] = "PRJ-TEST-CHANGED"
        self.assertNotEqual(
            verification_contract_sha256(first),
            verification_contract_sha256(changed),
        )

    def test_derives_exact_project_and_bounty_schemas(self) -> None:
        cases = (
            ("project", "normal"),
            ("bounty", "normal"),
            ("bounty", "dry_run"),
        )
        for mode, result_type in cases:
            with self.subTest(mode=mode, result_type=result_type):
                self.assertEqual(
                    derive_verification_contract(
                        self.admission(mode=mode, result_type=result_type)
                    ),
                    self.expected_contract(mode=mode, result_type=result_type),
                )

    def test_lane_map_is_closed_and_pinned(self) -> None:
        cases = {
            "claude": "claude",
            "gpt-codex": "openai",
            "codex": "openai",
            "gemini": "google",
            "kimi": "kimi",
        }
        for lane, family in cases.items():
            with self.subTest(lane=lane):
                self.assertEqual(author_family_for_lane(lane), family)
                contract = derive_verification_contract(self.admission(to_model=lane))
                self.assertEqual(contract["author_family"], family)
        with self.assertRaises(ContractError):
            author_family_for_lane("unknown")
        admission = self.admission()
        admission["author_family"] = "claude"
        with self.assertRaises(ContractError):
            derive_verification_contract(admission)

    def test_swarm_is_a_first_class_dispatch_kind(self) -> None:
        admission = self.admission()
        admission["dispatch_kind"] = "swarm"
        contract = derive_verification_contract(admission)
        self.assertEqual(contract["dispatch_kind"], "swarm")
        self.assertEqual(validate_verification_contract(contract), contract)

        admission["dispatch_kind"] = "fanout"
        with self.assertRaisesRegex(ContractError, "single, panel, or swarm"):
            derive_verification_contract(admission)

    def test_swarm_child_cannot_weaken_review_memory_or_external_policy(self) -> None:
        admission = self.admission()
        admission["dispatch_kind"] = "swarm"
        baseline = derive_verification_contract(admission)
        mutations = {
            "review": lambda contract: contract["deliverable_review_policy"].update(
                required=False
            ),
            "memory": lambda contract: contract["memory_policy"].update(recall="optional"),
            "external": lambda contract: contract["external_delivery_policy"].update(
                allowed=True
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(policy=name):
                contract = json.loads(json.dumps(baseline))
                mutate(contract)
                with self.assertRaises(ContractError):
                    validate_verification_contract(contract)

    def test_invalid_admissions_are_rejected(self) -> None:
        mutations = {
            "empty run": lambda item: item.update(run_id=""),
            "project dry run": lambda item: item.update(result_type="dry_run"),
            "unknown mode": lambda item: item.update(mode="content"),
            "unknown gate": lambda item: item.update(runtime_map_gates=["made_up_gate"]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                admission = self.admission()
                mutate(admission)
                with self.assertRaises(ContractError):
                    derive_verification_contract(admission)

    def test_noncanonical_hash_policy_extras_and_weakened_policies_are_rejected(self) -> None:
        mutations = {
            "uppercase capability hash": lambda item: item["capability"].update(
                card_sha256="A" * 64
            ),
            "extra policy key": lambda item: item["memory_policy"].update(optional=True),
            "weaken review": lambda item: item["plan_review_policy"].update(required=False),
            "weaken memory": lambda item: item["memory_policy"].update(recall="optional"),
            "weaken external": lambda item: item["external_delivery_policy"].update(
                allowed=True
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                contract = self.expected_contract(mode="project", result_type="normal")
                mutate(contract)
                with self.assertRaises(ContractError):
                    validate_verification_contract(contract)

    def write_packet(
        self,
        root: Path,
        mailbox_state: str,
        contract: dict[str, object],
        digest: str | None = None,
        write_scope: str | None = None,
    ) -> Path:
        path = (
            root
            / "departments"
            / "coding"
            / mailbox_state
            / "TASK-TEST-001.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_scope_line = (
            f"write_scope: {write_scope}\n" if write_scope is not None else ""
        )
        path.write_text(
            "---\n"
            "id: TASK-TEST-001\n"
            f"{write_scope_line}"
            f"verification_contract: {json.dumps(contract, separators=(',', ':'))}\n"
            f"verification_contract_sha256: {digest or verification_contract_sha256(contract)}\n"
            "---\npacket\n",
            encoding="utf-8",
        )
        return path

    def test_packet_contract_echoes_accept_one_or_identical_copies(self) -> None:
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self.write_packet(root, "inbox", contract)
            echoes = read_packet_contract_echoes(root, "TASK-TEST-001")
            self.assertEqual(echoes, [(first, contract, verification_contract_sha256(contract))])
            second = self.write_packet(root, "archive", contract)
            echoes = read_packet_contract_echoes(root, "TASK-TEST-001")
            self.assertEqual([item[0] for item in echoes], [second, first])

    def test_packet_contract_echo_accepts_documented_unquoted_write_scope(self) -> None:
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            packet = self.write_packet(
                root,
                "inbox",
                contract,
                write_scope="[scripts/python/foo.py, bin/bar.sh]",
            )

            echoes = read_packet_contract_echoes(root, "TASK-TEST-001")

            self.assertEqual(
                echoes,
                [(packet, contract, verification_contract_sha256(contract))],
            )

    def test_frontmatter_reader_preserves_sibling_fields_and_raw_yaml_scope(self) -> None:
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            packet = self.write_packet(
                Path(temp_dir),
                "inbox",
                contract,
                write_scope="[scripts/python/foo.py, bin/bar.sh]",
            )

            frontmatter = read_yaml_frontmatter(packet)

            self.assertEqual(frontmatter["id"], "TASK-TEST-001")
            self.assertEqual(
                frontmatter["write_scope"],
                "[scripts/python/foo.py, bin/bar.sh]",
            )
            self.assertEqual(frontmatter["verification_contract"], contract)

    def test_frontmatter_reader_still_rejects_malformed_required_contract(self) -> None:
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            packet = self.write_packet(Path(temp_dir), "inbox", contract)
            packet.write_text(
                packet.read_text(encoding="utf-8").replace(
                    f"verification_contract: {json.dumps(contract, separators=(',', ':'))}",
                    "verification_contract: {not-json}",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "invalid inline JSON"):
                read_yaml_frontmatter(packet)

    def test_packet_contract_echoes_reject_divergent_or_missing_copies(self) -> None:
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ContractError):
                read_packet_contract_echoes(root, "TASK-TEST-001")
            self.write_packet(root, "inbox", contract)
            divergent = dict(contract)
            divergent["run_id"] = "PRJ-DIFFERENT"
            self.write_packet(root, "archive", divergent)
            with self.assertRaises(ContractError):
                read_packet_contract_echoes(root, "TASK-TEST-001")


if __name__ == "__main__":
    unittest.main()
