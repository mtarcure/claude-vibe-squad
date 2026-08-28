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

from held_action_gate import HELD_CATEGORIES  # noqa: E402
from verification_contract import (  # noqa: E402
    CONTRACT_VERSION,
    ContractError,
    _VALID_GATES,
    _derive_cli,
    author_family_for_lane,
    derive_verification_contract,
    read_packet_contract_echoes,
    read_yaml_frontmatter,
    validate_verification_contract,
    verification_contract_sha256,
)


class VerificationContractTests(unittest.TestCase):
    def test_valid_gate_vocabulary_contains_every_controller_held_category(
        self,
    ) -> None:
        self.assertLessEqual(
            HELD_CATEGORIES,
            _VALID_GATES,
            "verification-contract gates must include every controller-held category",
        )

    def admission(
        self,
        *,
        mode: str = "project",
        result_type: str = "normal",
        to_model: str = "gpt-codex",
    ) -> dict[str, object]:
        run_prefix = {
            "project": "PRJ",
            "bounty": "BTY",
        }.get(mode, "UNK")
        capability_id = {
            "project": "project/web-app",
            "bounty": "bounty/authorized-red-team",
        }.get(mode, "unknown/mode")
        return {
            "task_id": "TASK-TEST-001",
            "run_id": f"{run_prefix}-TEST-001",
            "mode": mode,
            "result_type": result_type,
            "to_model": to_model,
            "dispatch_kind": "single",
            "capability": {
                "id": capability_id,
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
            required_phase_ids = [f"S{i}" for i in range(8)]
            memory_policy = {"recall": "required", "record": "required"}
            plan_review_policy = {
                "required": True,
                "anti_affinity": "author_family",
                "subject": "plan_sha256",
            }
        elif mode == "bounty":
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
                    "primitive_ledger",
                ],
            }
            required_phase_ids = [f"S{i}" for i in range(8)]
            # Bounty deliberately diverges from project here: `recall` is OPTIONAL.
            # A cold lane cannot both call recall and stay uncontaminated, because no
            # filter excludes prior *runs* -- `written_before` compartments only
            # same-run notes. Requiring the call mandated the contamination. `record`
            # stays required; writing findings biases nobody. Project mode above keeps
            # `recall: required`, so this asymmetry is intentional, not drift.
            memory_policy = {"recall": "optional", "record": "required"}
            plan_review_policy = {
                "required": True,
                "anti_affinity": "author_family",
                "subject": "plan_sha256",
            }
        run_prefix = {"project": "PRJ", "bounty": "BTY"}[mode]
        capability_id = {
            "project": "project/web-app",
            "bounty": "bounty/authorized-red-team",
        }[mode]
        contract = {
            "contract_version": CONTRACT_VERSION,
            "task_id": "TASK-TEST-001",
            "run_id": f"{run_prefix}-TEST-001",
            "mode": mode,
            "result_type": result_type,
            "dispatch_kind": "single",
            "author_family": author_family,
            "capability": {
                "id": capability_id,
                "card_sha256": "a" * 64,
                "derived_state": "live",
            },
            "required_phase_ids": required_phase_ids,
            "required_verification_kinds": verification_kinds,
            "memory_policy": memory_policy,
            "plan_review_policy": plan_review_policy,
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
        return contract

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

    def modeless_admission(self) -> dict[str, object]:
        # Ordinary internal work that declared no mode: no capability card, no
        # gates. The controller has already translated the packet's ABSENCE of a
        # mode into the affirmative `modeless` token by this point.
        return {
            "task_id": "TASK-TEST-001",
            "run_id": "MDL-TEST-001",
            "mode": "modeless",
            "result_type": "normal",
            "to_model": "claude",
            "dispatch_kind": "single",
        }

    def test_modeless_derives_project_shaped_contract_tagged_modeless(self) -> None:
        contract = derive_verification_contract(self.modeless_admission())
        # The one field that makes the third state visible and un-confusable.
        self.assertEqual(contract["mode"], "modeless")
        # Body is the ordinary internal-work shape (identical to project's).
        self.assertEqual(
            contract["required_verification_kinds"],
            ["project_tests", "recipient_contract"],
        )
        self.assertEqual(
            contract["memory_policy"], {"recall": "required", "record": "required"}
        )
        self.assertIsNone(contract["bounty_policy"])
        # No capability card resolved -> no mode-specific tool projection.
        self.assertEqual(
            contract["capability"],
            {"id": None, "card_sha256": None, "derived_state": None},
        )
        self.assertEqual(validate_verification_contract(contract), contract)
        # Modeless is EXACTLY project-shaped except for the mode tag: flipping the
        # single mode field yields the byte-identical project contract, and the
        # pinned hash moves with the tag. This documents that the divergence that
        # matters (write floor, budget, capability) lives at the OTHER two owners,
        # not in the contract body.
        project = derive_verification_contract(
            {**self.modeless_admission(), "mode": "project"}
        )
        self.assertEqual({**contract, "mode": "project"}, project)
        self.assertNotEqual(
            verification_contract_sha256(contract),
            verification_contract_sha256(project),
        )

    def test_modeless_rejects_dry_run_and_capability_card(self) -> None:
        # dry_run is a bounty-only affordance; modeless takes project's narrower
        # latitude and is refused it.
        with self.assertRaisesRegex(ContractError, "modeless result_type"):
            derive_verification_contract(
                {**self.modeless_admission(), "result_type": "dry_run"}
            )
        # Capability cards are mode-scoped; a modeless packet may resolve none.
        with self.assertRaisesRegex(ContractError, "modeless dispatch cannot carry"):
            derive_verification_contract(
                {
                    **self.modeless_admission(),
                    "capability": {
                        "id": "project/web-app",
                        "card_sha256": "a" * 64,
                        "derived_state": "live",
                    },
                }
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

    def test_removed_transport_dispatch_kinds_are_rejected(self) -> None:
        for dispatch_kind in ("panel", "swarm", "fanout"):
            with self.subTest(dispatch_kind=dispatch_kind):
                admission = self.admission()
                admission["dispatch_kind"] = dispatch_kind
                with self.assertRaisesRegex(ContractError, "dispatch_kind must be single"):
                    derive_verification_contract(admission)

    def test_contract_cannot_weaken_memory_or_external_policy(self) -> None:
        baseline = derive_verification_contract(self.admission())
        mutations = {
            "memory": lambda contract: contract["memory_policy"].update(
                recall="optional"
            ),
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

    def test_review_required_defaults_true_when_producer_omits_it(self) -> None:
        # Backward compatibility: an admission that never mentions review_required
        # (every producer, until send-task is wired) derives byte-identically to
        # the historical contract whose review demand was hardcoded True.
        admission = self.admission()
        self.assertNotIn("review_required", admission)
        contract = derive_verification_contract(admission)
        self.assertIs(contract["deliverable_review_policy"]["required"], True)
        self.assertEqual(
            contract,
            self.expected_contract(mode="project", result_type="normal"),
        )

    def test_routine_packet_derives_no_deliverable_review_demand(self) -> None:
        # The fix: a routine packet (review_triggers: []) whose producer passes
        # review_required=False derives a contract that does NOT demand a review.
        # On the pre-fix code the field was hardcoded True, so this assertion
        # failed. The contract must still round-trip through the validator, which
        # is the property the pre-fix code could not offer for a False value.
        admission = self.admission()
        admission["review_required"] = False
        contract = derive_verification_contract(admission)
        self.assertIs(contract["deliverable_review_policy"]["required"], False)
        self.assertEqual(contract["deliverable_review_policy"]["anti_affinity"], "author_family")
        self.assertEqual(contract["deliverable_review_policy"]["subject"], "artifact_bundle_sha256")
        self.assertEqual(validate_verification_contract(contract), contract)
        # The hash MOVES when the demand flips -- callers that pin it must
        # re-derive, they cannot assume the old digest.
        self.assertNotEqual(
            verification_contract_sha256(contract),
            verification_contract_sha256(
                derive_verification_contract(self.admission())
            ),
        )

    def test_triggered_packet_still_requires_review(self) -> None:
        admission = self.admission()
        admission["review_required"] = True
        contract = derive_verification_contract(admission)
        self.assertIs(contract["deliverable_review_policy"]["required"], True)
        self.assertEqual(validate_verification_contract(contract), contract)

    def test_review_required_must_be_boolean(self) -> None:
        admission = self.admission()
        admission["review_required"] = "yes"
        with self.assertRaisesRegex(ContractError, "review_required must be a boolean"):
            derive_verification_contract(admission)

    def test_explicit_null_review_required_is_rejected_not_canonicalized(self) -> None:
        # Membership, not `.get()`: an admission carrying an explicit JSON null
        # is malformed producer input, not an omitted field. Canonicalizing it
        # to True was fail-closed but silently rewrote a value the declared
        # admission type says must be a boolean.
        admission = self.admission()
        admission["review_required"] = None
        with self.assertRaisesRegex(ContractError, "review_required must be a boolean"):
            derive_verification_contract(admission)
        # The same null smuggled into a pinned contract's policy is rejected by
        # the validator rather than recovered as "absent, default True".
        contract = derive_verification_contract(self.admission())
        contract["deliverable_review_policy"]["required"] = None
        with self.assertRaisesRegex(ContractError, "review_required must be a boolean"):
            validate_verification_contract(contract)

    def test_validator_grounds_review_required_in_the_trusted_expectation(self) -> None:
        # The reviewer-rejected circularity: recovering `required` from the
        # object under check let a downgrade with a recomputed adjacent hash
        # self-authenticate. With the trusted expectation supplied, the
        # downgrade is rejected for a single-task contract. Without an expectation
        # the validator can only check internal consistency -- that residual is
        # pinned below on purpose, and it is why dispatch admission separately
        # compares the packet contract to the locked registry pin
        # (dispatch_context_builder.require_registry_contract_pin).
        admission = self.admission()
        admitted = derive_verification_contract(admission)
        self.assertIs(admitted["deliverable_review_policy"]["required"], True)

        tampered = json.loads(json.dumps(admitted))
        tampered["deliverable_review_policy"]["required"] = False
        # Internal-consistency-only validation accepts the tamper: this
        # assertion documents the boundary the grounding exists for,
        # not a desired property.
        self.assertEqual(validate_verification_contract(tampered), tampered)
        with self.assertRaisesRegex(ContractError, "deliverable_review_policy"):
            validate_verification_contract(tampered, expected_review_required=True)

        # A legitimate False -- one the trusted admission was actually
        # created with -- still validates, so the mechanism stays usable once
        # the producer starts passing the trigger decision.
        legitimate_admission = self.admission()
        legitimate_admission["review_required"] = False
        legitimate = derive_verification_contract(legitimate_admission)
        self.assertIs(legitimate["deliverable_review_policy"]["required"], False)
        self.assertEqual(
            validate_verification_contract(
                legitimate, expected_review_required=False
            ),
            legitimate,
        )
        with self.assertRaisesRegex(ContractError, "deliverable_review_policy"):
            validate_verification_contract(
                legitimate, expected_review_required=True
            )
        with self.assertRaisesRegex(ContractError, "expected_review_required"):
            validate_verification_contract(admitted, expected_review_required=1)

    def test_invalid_admissions_are_rejected(self) -> None:
        mutations = {
            "empty run": lambda item: item.update(run_id=""),
            "project dry run": lambda item: item.update(result_type="dry_run"),
            "unknown mode": lambda item: item.update(mode="content"),
            "unknown gate": lambda item: item.update(
                runtime_map_gates=["made_up_gate"]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                admission = self.admission()
                mutate(admission)
                with self.assertRaises(ContractError):
                    derive_verification_contract(admission)

    def test_noncanonical_hash_policy_extras_and_weakened_policies_are_rejected(
        self,
    ) -> None:
        mutations = {
            "uppercase capability hash": lambda item: item["capability"].update(
                card_sha256="A" * 64
            ),
            "extra policy key": lambda item: item["memory_policy"].update(
                optional=True
            ),
            "weaken review": lambda item: item["plan_review_policy"].update(
                required=False
            ),
            "weaken memory": lambda item: item["memory_policy"].update(
                recall="optional"
            ),
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
        path = root / "departments" / "coding" / mailbox_state / "TASK-TEST-001.md"
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
            self.assertEqual(
                echoes, [(first, contract, verification_contract_sha256(contract))]
            )
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

    def test_frontmatter_reader_preserves_sibling_fields_and_raw_yaml_scope(
        self,
    ) -> None:
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

    def test_json_and_frontmatter_inputs_reject_ambiguous_values(self) -> None:
        for raw in ('{"mode":"project","mode":"bounty"}', '{"value":1e400}'):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ContractError, "invalid admission JSON"),
            ):
                _derive_cli(raw)
        contract = self.expected_contract(mode="project", result_type="normal")
        with tempfile.TemporaryDirectory() as temp_dir:
            packet = self.write_packet(Path(temp_dir), "inbox", contract)
            packet.write_text(
                packet.read_text(encoding="utf-8").replace(
                    "id: TASK-TEST-001\n", "id: TASK-TEST-001\nid: TASK-OTHER\n"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "duplicate frontmatter"):
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
