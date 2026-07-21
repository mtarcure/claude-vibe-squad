#!/usr/bin/env python3
"""Acceptance fixtures for verification-run/v1."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts/python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

import vibecoding_check as checker  # noqa: E402
from verification_contract import (  # noqa: E402
    derive_verification_contract,
    verification_contract_sha256,
)


class SpineFixture:
    def __init__(self, case: unittest.TestCase, *, lane: str = "gpt-codex", mode: str = "project", result_type: str = "normal") -> None:
        self.case = case
        self.root = Path(tempfile.mkdtemp(prefix="spine-fixture-"))
        case.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.state = self.root / "_state"
        self.state.mkdir()
        self.task_id = "TASK-2026-07-17-9500-spine-fixture"
        self.run_id = "PRJ-SPINE-FIXTURE" if mode == "project" else "BTY-SPINE-FIXTURE"
        self.lane = lane
        self.evidence = self.root / "evidence.txt"
        self.evidence.write_text("fixture evidence\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "evidence.txt"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture base"], cwd=self.root, check=True)

        self.contract = derive_verification_contract(
            {
                "task_id": self.task_id,
                "run_id": self.run_id,
                "mode": mode,
                "result_type": result_type,
                "to_model": lane,
                "dispatch_kind": "single",
                "capability": None,
            }
        )
        self.digest = verification_contract_sha256(self.contract)
        self._write_registry(self.task_id, self.contract, self.digest, lane)
        self._write_packet(self.task_id, self.contract, self.digest)
        approvals = self.state / "approvals"
        approvals.mkdir()
        (approvals / f"{self.run_id}.md").write_text("APPROVE\n", encoding="utf-8")
        self.manifest = {
            "schema_version": "verification-run/v1",
            "task_id": self.task_id,
            "run_id": self.run_id,
            "mode": mode,
            "result_type": result_type,
            "author_family": self.contract["author_family"],
            "verification_contract": copy.deepcopy(self.contract),
            "verification_contract_sha256": self.digest,
            "phase_records": [
                {
                    "phase_id": f"S{i}",
                    "status": "passed",
                    "evidence_refs": ["evidence.txt"],
                    "action_ids": [f"ACT-{i}"],
                }
                for i in range(8)
            ],
            "verification_records": [
                {"id": "VER-1", "kind": "project_tests"},
                {"id": "VER-2", "kind": "recipient_contract"},
            ],
            "artifacts": ["evidence.txt"],
            "citations": [],
            "modified_code": [],
        }
        old = (
            checker.VAULT_ROOT,
            checker.STATE_DIR,
            checker.RUNS_DIR,
            checker.APPROVALS_DIR,
            checker.CHECK_DIR,
        )
        checker.VAULT_ROOT = self.root
        checker.STATE_DIR = self.state
        checker.RUNS_DIR = self.state / "runs"
        checker.APPROVALS_DIR = self.state / "approvals"
        checker.CHECK_DIR = self.state / "vibecoding-check"
        case.addCleanup(self._restore, old)

    def complete_common(self) -> dict[str, object]:
        plan = self.root / "plan.txt"
        artifact = self.root / "artifact.txt"
        plan.write_text("approved plan\n")
        artifact.write_text("deliverable\n")
        plan_sha = checker.hash_file(plan)
        artifacts = [
            {"path": "plan.txt", "sha256": plan_sha, "role": "plan"},
            {"path": "artifact.txt", "sha256": checker.hash_file(artifact), "role": "deliverable"},
        ]
        bundle_sha = checker.hash_canonical(sorted(artifacts, key=lambda item: item["path"]))
        reviewer = "claude" if self.contract["author_family"] != "claude" else "openai"
        reviews = {}
        for kind, subject in (("plan", plan_sha), ("deliverable", bundle_sha)):
            path = self.root / f"{kind}-review.md"
            path.write_text(
                "---\n"
                f"review_kind: {kind}\nreviewer_family: {reviewer}\n"
                f"subject_sha256: {subject}\nverdict: pass\n---\nreview\n"
            )
            reviews[kind] = {
                "required": True,
                "author_family": self.contract["author_family"],
                "reviewer_family": reviewer,
                "verdict": "pass",
                "subject_sha256": subject,
                "evidence_ref": path.name,
                "evidence_sha256": checker.hash_file(path),
            }
        actions = [
            {
                "id": f"ACT-{i}", "phase_id": f"S{i}", "kind": "test",
                "target": "artifact.txt", "subject_sha256": bundle_sha,
                "destructive": False, "evidence_ref": "evidence.txt",
            }
            for i in range(8)
        ]
        verification_records = []
        for index, kind in enumerate(self.contract["required_verification_kinds"], 1):
            verification_records.append({
                "id": f"VER-{index}", "kind": kind, "subject_sha256": bundle_sha,
                "verifier_family": "deterministic", "status": "passed",
                "evidence_ref": "evidence.txt", "evidence_sha256": checker.hash_file(self.evidence),
            })
        manifest = copy.deepcopy(self.manifest)
        manifest.update({
            "plan": {"path": "plan.txt", "sha256": plan_sha},
            "artifacts": artifacts,
            "artifact_bundle_sha256": bundle_sha,
            "verification_records": verification_records,
            "reviews": reviews,
            "memory": {
                "recall": {
                    "recall_id": "12345678-1234-4234-8234-123456789abc",
                    "query_sha256": "1" * 64, "tiers_searched": ["active"],
                    "query_error": None, "results": [], "no_hits": True,
                    "applied_note_ids": [], "usage_receipts": [],
                },
                "record": {"receipts": [{
                    "note_id": "mem-123456789abc", "note_type": "learning",
                    "source_task": self.task_id, "source_artifact_hash": bundle_sha,
                    "sensitivity": "restricted" if self.contract["mode"] == "bounty" else "internal", "path": "memory.md",
                    "indexed": True, "index_dirty": False,
                }]},
            },
            "actions": actions,
            "action_log_sha256": checker.hash_canonical(actions),
            "iterations": [], "gates": [],
            "delivery": {
                "external": False, "action": "local_package",
                "subject_sha256": bundle_sha, "receipt_ref": "evidence.txt",
                "receipt_sha256": checker.hash_file(self.evidence),
            },
        })
        return manifest

    def complete_bounty(self, *, result_type: str = "dry_run") -> dict[str, object]:
        manifest = self.complete_common()
        allowed = "https://target.example/scope/"
        for action in manifest["actions"]:
            action["target"] = "https://target.example/scope/item"
        manifest["action_log_sha256"] = checker.hash_canonical(manifest["actions"])
        manifest.update({
            "scope": {
                "scope_gate_ran": True, "allowed_targets": [allowed],
                "evidence_ref": "evidence.txt", "evidence_sha256": checker.hash_file(self.evidence),
            },
            "no_self_inflicted": {
                "passed": True, "subject_sha256": manifest["action_log_sha256"],
                "evidence_ref": "evidence.txt", "evidence_sha256": checker.hash_file(self.evidence),
            },
            "submission": {
                "attempted": False, "evidence_ref": "evidence.txt",
                "evidence_sha256": checker.hash_file(self.evidence),
            },
            "findings": [],
            "negative_results": [{
                "id": "KILL-1", "target": "https://target.example/scope/item",
                "hypothesis": "fixture", "outcome": "negative",
                "subject_sha256": manifest["action_log_sha256"],
                "evidence_ref": "evidence.txt", "evidence_sha256": checker.hash_file(self.evidence),
            }],
        })
        return manifest

    def _restore(self, old: tuple[Path, Path, Path, Path, Path]) -> None:
        (
            checker.VAULT_ROOT,
            checker.STATE_DIR,
            checker.RUNS_DIR,
            checker.APPROVALS_DIR,
            checker.CHECK_DIR,
        ) = old

    def _write_registry(
        self, task_id: str, contract: dict[str, object], digest: str, lane: str
    ) -> None:
        path = self.state / "active-tasks.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        data[task_id] = {
            "to_model": lane,
            "verification_contract": contract,
            "verification_contract_sha256": digest,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        path.with_suffix(".json.lock").touch()

    def _write_packet(
        self, task_id: str, contract: dict[str, object], digest: str
    ) -> None:
        path = self.root / "departments/coding/inbox" / f"{task_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"id: {task_id}\n"
            f"verification_contract: {json.dumps(contract, separators=(',', ':'))}\n"
            f"verification_contract_sha256: {digest}\n"
            "---\nfixture\n",
            encoding="utf-8",
        )


class TypedAdmissionTests(unittest.TestCase):
    def test_contract_hash_mismatch_is_operator_surface(self) -> None:
        mutations = (
            "registry_object",
            "registry_hash",
            "packet_object",
            "packet_hash",
            "manifest_object",
            "manifest_hash",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                fixture = SpineFixture(self)
                manifest = copy.deepcopy(fixture.manifest)
                if mutation.startswith("registry"):
                    registry_path = fixture.state / "active-tasks.json"
                    registry = json.loads(registry_path.read_text())
                    if mutation == "registry_object":
                        registry[fixture.task_id]["verification_contract"]["run_id"] = "PRJ-TAMPER"
                    else:
                        registry[fixture.task_id]["verification_contract_sha256"] = "0" * 64
                    registry_path.write_text(json.dumps(registry))
                elif mutation.startswith("packet"):
                    contract = copy.deepcopy(fixture.contract)
                    digest = fixture.digest
                    if mutation == "packet_object":
                        contract["run_id"] = "PRJ-TAMPER"
                    else:
                        digest = "0" * 64
                    fixture._write_packet(fixture.task_id, contract, digest)
                elif mutation == "manifest_object":
                    manifest["verification_contract"]["run_id"] = "PRJ-TAMPER"
                else:
                    manifest["verification_contract_sha256"] = "0" * 64
                result = checker.check_verification_contract(manifest)
                self.assertEqual(result.name, "verification_contract_integrity")
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_manifest_repointed_to_foreign_contract_is_operator_surface(self) -> None:
        fixture = SpineFixture(self)
        foreign_id = "TASK-2026-07-17-9501-foreign-contract"
        foreign = derive_verification_contract(
            {
                "task_id": foreign_id,
                "run_id": "PRJ-FOREIGN",
                "mode": "project",
                "to_model": "claude",
                "dispatch_kind": "single",
                "capability": None,
            }
        )
        foreign_digest = verification_contract_sha256(foreign)
        fixture._write_registry(foreign_id, foreign, foreign_digest, "claude")
        fixture._write_packet(foreign_id, foreign, foreign_digest)
        manifest = copy.deepcopy(fixture.manifest)
        manifest["task_id"] = foreign_id
        result = checker.check_verification_contract(manifest)
        self.assertEqual(result.name, "verification_contract_integrity")
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_unknown_and_six_unsupported_modes_are_operator_surface(self) -> None:
        for mode in (
            "content",
            "research",
            "incident",
            "maintenance",
            "outreach",
            "triage",
            "unknown",
        ):
            with self.subTest(mode=mode):
                result = checker.check_typed_profile_supported({"mode": mode})
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_empty_verification_coverage_is_operator_surface(self) -> None:
        fixture = SpineFixture(self)
        manifest = copy.deepcopy(fixture.manifest)
        manifest["verification_records"] = []
        result = checker.check_verification_coverage(manifest)
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_removed_required_phase_is_operator_surface(self) -> None:
        fixture = SpineFixture(self)
        for records in ([], fixture.manifest["phase_records"][:4] + fixture.manifest["phase_records"][5:]):
            with self.subTest(count=len(records)):
                manifest = copy.deepcopy(fixture.manifest)
                manifest["phase_records"] = copy.deepcopy(records)
                result = checker.check_phase_tags(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_http_citation_failure_is_advisory_but_file_failure_blocks(self) -> None:
        fixture = SpineFixture(self)
        with mock.patch.object(checker, "_probe_http", side_effect=OSError("offline")):
            result = checker.check_citations_resolve({"citations": ["https://example.invalid"]})
        self.assertTrue(result.passed)
        self.assertTrue(result.advisory)
        report = checker.RunReport("r", "project", "a", "b", [result])
        self.assertEqual(report.overall_tier, checker.TIER_OK)
        missing = checker.check_citations_resolve({"citations": ["missing.txt"]})
        self.assertFalse(missing.passed)
        self.assertEqual(missing.tier, checker.TIER_OPERATOR)


class CommonSpineTests(unittest.TestCase):
    def test_manifest_cannot_disable_required_review(self) -> None:
        for kind in ("plan", "deliverable"):
            with self.subTest(kind=kind):
                fixture = SpineFixture(self)
                manifest = fixture.complete_common()
                manifest["reviews"][kind]["required"] = False
                result = checker.check_review_bindings(manifest)
                self.assertEqual(result.name, "review_bindings")
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)


class BountySpineTests(unittest.TestCase):
    def test_empty_bounty_findings_require_kill_and_no_submit(self) -> None:
        for mutation in ("negative", "no_submit"):
            with self.subTest(mutation=mutation):
                fixture = SpineFixture(self, mode="bounty", result_type="dry_run")
                manifest = fixture.complete_bounty()
                if mutation == "negative":
                    manifest["negative_results"] = []
                else:
                    manifest["submission"].pop("evidence_ref")
                result = checker.check_bounty_result_evidence(manifest) if mutation == "negative" else checker.check_bounty_no_submit(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_out_of_scope_bounty_target_is_operator_surface(self) -> None:
        for area in ("action", "finding", "kill"):
            with self.subTest(area=area):
                fixture = SpineFixture(self, mode="bounty", result_type="dry_run")
                manifest = fixture.complete_bounty()
                if area == "action":
                    manifest["actions"][0]["target"] = "https://evil.example/"
                elif area == "finding":
                    manifest["findings"] = [{"target": "https://evil.example/"}]
                else:
                    manifest["negative_results"][0]["target"] = "https://target.example/scope-escape"
                result = checker.check_bounty_scope_and_targets(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_bounty_literal_false_and_normalization_attacks(self) -> None:
        attacks = (
            "https://*.target.example/scope/", "https://user@target.example/scope/",
            "https://target.example/scope/#fragment", "https://target.example/scope/%2e%2e/admin",
            "http://target.example/scope/", "https://target.example:444/scope/",
        )
        for target in attacks:
            with self.subTest(target=target):
                with self.assertRaises(checker.ManifestContractError):
                    checker.normalize_bounty_target(target)
        fixture = SpineFixture(self, mode="bounty", result_type="dry_run")
        manifest = fixture.complete_bounty()
        manifest["submission"]["attempted"] = "false"
        self.assertEqual(checker.check_bounty_no_submit(manifest).tier, checker.TIER_OPERATOR)
        manifest = fixture.complete_bounty()
        manifest["scope"]["scope_gate_ran"] = "true"
        self.assertEqual(checker.check_bounty_scope_and_targets(manifest).tier, checker.TIER_OPERATOR)
        manifest = fixture.complete_bounty()
        manifest["no_self_inflicted"]["passed"] = "true"
        self.assertEqual(checker.check_bounty_no_self_inflicted(manifest).tier, checker.TIER_OPERATOR)


class PositiveCanaryTests(unittest.TestCase):
    def test_project_canary_complete_trace_bundle_passes(self) -> None:
        fixture = SpineFixture(self)
        manifest = fixture.complete_common()
        source = fixture.root / "tiny.py"
        test_source = fixture.root / "test_tiny.py"
        source.write_text("def add(a, b):\n    return a + b\n")
        test_source.write_text(
            "import unittest\nfrom tiny import add\n"
            "class T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(1, 2), 3)\n"
        )
        subprocess.run(["git", "add", "tiny.py", "test_tiny.py"], cwd=fixture.root, check=True)
        subprocess.run(["git", "commit", "-qm", "tiny implementation"], cwd=fixture.root, check=True)
        manifest.update({
            "test_command": f"{sys.executable} -m unittest test_tiny.py",
            "test_cwd": str(fixture.root), "base_ref": "HEAD^",
            "allow_dirty_tree": True,
        })
        report = checker.run_all_checks(manifest)
        self.assertEqual(report.overall_tier, checker.TIER_OK, checker.render_report(report))
        self.assertEqual([item for item in report.checks if not item.passed], [])

    def test_bounty_dry_run_complete_trace_bundle_passes(self) -> None:
        fixture = SpineFixture(self, mode="bounty", result_type="dry_run")
        manifest = fixture.complete_bounty()
        report = checker.run_all_checks(manifest)
        self.assertEqual(report.overall_tier, checker.TIER_OK, checker.render_report(report))
        self.assertEqual([item for item in report.checks if not item.passed], [])

    def test_iteration_positive_fresh_hashes_pass(self) -> None:
        fixture = SpineFixture(self)
        manifest = fixture.complete_common()
        manifest["iterations"] = [{
            "index": 1, "trigger_ref": "evidence.txt", "route_to": "S3",
            "from_plan_sha256": "2" * 64, "from_artifact_bundle_sha256": "3" * 64,
            "to_plan_sha256": manifest["plan"]["sha256"],
            "to_artifact_bundle_sha256": manifest["artifact_bundle_sha256"],
            "verification_record_ids": [item["id"] for item in manifest["verification_records"]],
            "review_kinds": ["plan", "deliverable"],
        }]
        self.assertTrue(checker.check_iteration_invalidation(manifest).passed)
        for record in manifest["verification_records"]:
            record["subject_sha256"] = "3" * 64
        self.assertFalse(checker.check_verification_coverage(manifest).passed)
        for record in manifest["verification_records"]:
            record["subject_sha256"] = manifest["artifact_bundle_sha256"]
        self.assertTrue(checker.check_verification_coverage(manifest).passed)

    def test_author_family_spoof_to_satisfy_anti_affinity_is_operator_surface(self) -> None:
        fixture = SpineFixture(self, lane="claude")
        manifest = fixture.complete_common()
        manifest["author_family"] = "openai"
        for review in manifest["reviews"].values():
            review["author_family"] = "openai"
            review["reviewer_family"] = "claude"
        result = checker.check_review_bindings(manifest)
        self.assertFalse(result.passed)
        self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_changed_review_subject_is_operator_surface(self) -> None:
        for target in ("plan.txt", "artifact.txt"):
            with self.subTest(target=target):
                fixture = SpineFixture(self)
                manifest = fixture.complete_common()
                (fixture.root / target).write_text("changed after review\n")
                result = checker.check_review_bindings(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_missing_memory_bookend_is_operator_surface(self) -> None:
        for mutation in ("recall", "record"):
            with self.subTest(mutation=mutation):
                fixture = SpineFixture(self)
                manifest = fixture.complete_common()
                if mutation == "recall":
                    manifest["memory"]["recall"] = None
                else:
                    manifest["memory"]["record"]["receipts"] = []
                result = checker.check_memory_bookends(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)

    def test_common_structural_and_external_negatives(self) -> None:
        checks = (
            ("wrong artifact hash", checker.check_artifact_and_gate_bindings,
             lambda m: m["artifacts"][0].update(sha256="0" * 64)),
            ("duplicate action", checker.check_action_log_complete,
             lambda m: m["actions"].append(copy.deepcopy(m["actions"][0]))),
            ("missing verification", checker.check_verification_coverage,
             lambda m: m.update(verification_records=[])),
            ("broken iteration", checker.check_iteration_invalidation,
             lambda m: m.update(iterations=[{"index": 2}])),
            ("external", checker.check_external_delivery_blocked,
             lambda m: m["delivery"].update(external=True)),
        )
        for label, function, mutate in checks:
            with self.subTest(label=label):
                fixture = SpineFixture(self)
                manifest = fixture.complete_common()
                mutate(manifest)
                result = function(manifest)
                self.assertFalse(result.passed)
                self.assertEqual(result.tier, checker.TIER_OPERATOR)


if __name__ == "__main__":
    unittest.main()
