from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import registry_reconciler as rr  # noqa: E402
from swarm_diff import SwarmDiffError, load_taxonomy, validate_member_result  # noqa: E402
from verification_contract import (  # noqa: E402
    derive_verification_contract,
    verification_contract_sha256,
)


SPEC = "a" * 64
PARENT = "TASK-SWARM"


class RegistryReconcilerSwarmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / "_state" / "active-tasks.json"
        self.patches = [
            patch.dict(os.environ, {rr.TEST_ISOLATION_ENV: "1"}),
            patch.object(rr, "VAULT_ROOT", self.root),
            patch.object(rr, "STATE_DIR", self.root / "_state"),
            patch.object(rr, "REGISTRY_PATH", self.registry),
            patch.object(rr, "CHRONO_QUEUE_PATH", self.root / "_state" / "chrono-queue.md"),
            patch.object(rr, "RUNTIME_MAP_PATH", self.root / "shared" / "specialist-runtime-map.tsv"),
            patch.object(rr, "RESPONSE_MIN_AGE", rr.timedelta(seconds=0)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_isolation_signal_prevents_live_tmux_notification(self) -> None:
        with patch.object(rr.subprocess, "run") as run:
            self.assertFalse(rr.nudge_chrono("fixture notification"))
        run.assert_not_called()

    def test_canonical_taxonomy_rejects_noncanonical_affected_surface(self) -> None:
        taxonomy = load_taxonomy(ROOT / "shared" / "finding-taxonomy.md")
        member = {
            "schema_version": "swarm-member-result/v1",
            "task_id": "TASK-SURFACE-swarm-claude",
            "parent_task_id": "TASK-SURFACE",
            "lane": "claude",
            "swarm_spec_sha256": SPEC,
            "status": "complete",
            "findings": [
                {
                    "target": "authorized-target",
                    "weakness_class": "access-control",
                    "affected_surface": "../src/auth.py::authorize",
                    "impact_class": "confidentiality-loss",
                    "disposition": "confirmed",
                    "severity": "high",
                    "confidence": "high",
                    "summary": "fixture",
                    "evidence": ["evidence/auth.log"],
                }
            ],
            "coverage": ["auth"],
            "limitations": [],
        }
        canonical = json.loads(json.dumps(member))
        canonical["findings"][0]["affected_surface"] = "src/auth.py::authorize"
        self.assertEqual(
            validate_member_result(canonical, taxonomy, SPEC)["findings"][0][
                "affected_surface"
            ],
            "src/auth.py::authorize",
        )
        for invalid in (
            "../src/auth.py::authorize",
            "./src/auth.py::authorize",
            "/src/auth.py::authorize",
            r"src\auth.py::authorize",
            "src/auth.py:42",
            "https://target.test/auth::authorize",
        ):
            with self.subTest(affected_surface=invalid):
                candidate = json.loads(json.dumps(member))
                candidate["findings"][0]["affected_surface"] = invalid
                with self.assertRaisesRegex(SwarmDiffError, "affected_surface"):
                    validate_member_result(candidate, taxonomy, SPEC)

    def contract(self, task_id: str, lane: str) -> dict:
        return derive_verification_contract(
            {
                "task_id": task_id,
                "run_id": "PRJ-SWARM-TEST",
                "mode": "project",
                "result_type": "normal",
                "to_model": lane,
                "dispatch_kind": "swarm",
            }
        )

    def entries(self) -> tuple[dict, dict[str, dict]]:
        children = [f"{PARENT}-swarm-claude", f"{PARENT}-swarm-gemini"]
        taxonomy = self.root / "shared" / "finding-taxonomy.md"
        taxonomy.parent.mkdir(parents=True, exist_ok=True)
        taxonomy.write_text(
            '# Finding taxonomy\n```json swarm-finding-taxonomy/v1\n'
            + json.dumps(
                {
                    "schema_version": "swarm-finding-taxonomy/v1",
                    "weakness_classes": ["access-control"],
                    "impact_classes": ["confidentiality-loss"],
                    "dispositions": ["confirmed", "rejected", "inconclusive"],
                    "severities": ["critical", "high", "medium", "low", "info", "none"],
                    "confidences": ["high", "medium", "low"],
                    "affected_surface_pattern": r"^(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+(?:::[A-Za-z_][A-Za-z0-9_.$<>-]*)?$",
                    "finding_key_fields": [
                        "target",
                        "weakness_class",
                        "affected_surface",
                        "impact_class",
                    ],
                }
            )
            + "\n```\n",
            encoding="utf-8",
        )
        parent = {
            "compatibility_namespace": "security",
            "specialist": "exploit-developer",
            "dispatch_kind": "swarm",
            "swarm_role": "parent",
            "swarm_spec_sha256": SPEC,
            "swarm_children": children,
            "swarm_member_results": {
                "claude": "_state/swarm/claude.json",
                "gemini": "_state/swarm/gemini.json",
            },
            "swarm_diff_path": "_state/swarm/diff.json",
            "swarm_taxonomy_path": "shared/finding-taxonomy.md",
            "return_artifact": "_state/swarm/final.md",
            "expected_response_path": f"departments/security/outbox/{PARENT}-response.md",
            "status": "in-flight",
            "mandatory_review": "true",
        }
        members: dict[str, dict] = {}
        for lane, child_id in zip(("claude", "gemini"), children):
            contract = self.contract(child_id, lane)
            members[child_id] = {
                "compatibility_namespace": "security",
                "specialist": "exploit-developer",
                "to_model": lane,
                "source_namespace": "security",
                "review_model": "gpt-codex" if lane != "gpt-codex" else "claude",
                "mandatory_review": "true",
                "return_artifact": f"_state/swarm/{lane}.md",
                "write_scope": [],
                "status": "in-flight",
                "dispatch_kind": "swarm",
                "swarm_role": "member",
                "swarm_parent_id": PARENT,
                "swarm_spec_sha256": SPEC,
                "verification_contract": contract,
                "verification_contract_sha256": verification_contract_sha256(contract),
            }
        return parent, members

    def test_atomic_registration_is_idempotent_and_rejects_partial_prior_state(self) -> None:
        parent, members = self.entries()
        self.assertTrue(rr.register_swarm(PARENT, parent, members))
        self.assertFalse(rr.register_swarm(PARENT, parent, members))
        written = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(set(written), {PARENT, *members})

        self.registry.write_text(json.dumps({PARENT: parent}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "partial prior swarm"):
            rr.register_swarm(PARENT, parent, members)

    def test_publication_failure_marks_all_unpublished_children(self) -> None:
        parent, members = self.entries()
        rr.register_swarm(PARENT, parent, members)
        unpublished = [f"{PARENT}-swarm-claude", f"{PARENT}-swarm-gemini"]
        self.assertTrue(
            rr.mark_swarm_publication_failed(PARENT, unpublished, "mailbox failure")
        )
        self.assertFalse(
            rr.mark_swarm_publication_failed(PARENT, unpublished, "mailbox failure")
        )
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertTrue(all(registry[child]["status"] == "blocked" for child in unpublished))

    def test_parent_freezes_diff_and_requires_explicit_review(self) -> None:
        parent, members = self.entries()
        members[f"{PARENT}-swarm-claude"]["status"] = "complete"
        members[f"{PARENT}-swarm-gemini"]["status"] = "complete"
        rr.register_swarm(PARENT, parent, members)

        sidecar = self.root / "_state" / "swarm" / "claude.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(
                {
                    "schema_version": "swarm-member-result/v1",
                    "task_id": f"{PARENT}-swarm-claude",
                    "parent_task_id": PARENT,
                    "lane": "claude",
                    "swarm_spec_sha256": SPEC,
                    "status": "complete",
                    "findings": [],
                    "coverage": ["auth"],
                    "limitations": [],
                }
            ),
            encoding="utf-8",
        )
        gemini_sidecar = self.root / "_state" / "swarm" / "gemini.json"
        gemini_sidecar.write_text(
            json.dumps(
                {
                    "schema_version": "swarm-member-result/v1",
                    "task_id": f"{PARENT}-swarm-gemini",
                    "parent_task_id": PARENT,
                    "lane": "gemini",
                    "swarm_spec_sha256": SPEC,
                    "status": "complete",
                    "findings": [],
                    "coverage": ["auth"],
                    "limitations": [],
                }
            ),
            encoding="utf-8",
        )

        changed, messages = rr.reconcile(PARENT, dry_run=False)
        self.assertEqual(changed, 1)
        self.assertTrue(any("swarm-review-required" in item for item in messages))
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(registry[PARENT]["status"], rr.REVIEW_REQUIRED)
        self.assertTrue(registry[PARENT]["swarm_frozen_at"])
        diff = json.loads((self.root / "_state" / "swarm" / "diff.json").read_text())
        self.assertEqual(diff["schema_version"], "swarm-diff/v1")
        self.assertEqual(diff["coverage_gaps"], [])
        artifact = (self.root / "_state" / "swarm" / "final.md").read_text()
        self.assertIn(diff["diff_sha256"], artifact)
        envelope = (
            self.root / "departments" / "security" / "outbox" / f"{PARENT}-response.md"
        ).read_text()
        self.assertIn("status: needs_review", envelope)
        self.assertIn(f"swarm_bundle_sha256: {diff['diff_sha256']}", envelope)

        original = json.dumps(diff, sort_keys=True)
        frozen_members = registry[PARENT]["swarm_frozen_members"]
        registry[f"{PARENT}-swarm-claude"]["status"] = "needs_review"
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        changed, _ = rr.reconcile(PARENT, dry_run=False)
        self.assertEqual(changed, 0)
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(registry[PARENT]["swarm_frozen_members"], frozen_members)
        frozen = json.loads((self.root / "_state" / "swarm" / "diff.json").read_text())
        self.assertEqual(json.dumps(frozen, sort_keys=True), original)

        review = (
            self.root
            / "departments"
            / "security"
            / "outbox"
            / "TASK-SWARM-INDEPENDENT-REVIEW-response.md"
        )
        review.write_text("---\nstatus: complete\n---\nreviewed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing swarm_bundle_sha256"):
            rr.settle_review(PARENT, str(review))
        review.write_text(
            f"---\nstatus: complete\nswarm_bundle_sha256: {'b' * 64}\n---\nreviewed\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "mismatch"):
            rr.settle_review(PARENT, str(review))
        review.write_text(
            "---\nstatus: complete\nverdict: APPROVE\n"
            f"swarm_bundle_sha256: {diff['diff_sha256']}\n---\nreviewed\n",
            encoding="utf-8",
        )
        self.assertTrue(rr.settle_review(PARENT, str(review)))
        self.assertFalse(rr.settle_review(PARENT, str(review)))
        controller = (
            self.root / "departments" / "security" / "outbox" / f"{PARENT}-response.md"
        ).read_text()
        self.assertIn("status: complete", controller)
        self.assertIn("review_ref: departments/security/outbox/", controller)

    def test_child_response_must_echo_swarm_spec(self) -> None:
        _parent, members = self.entries()
        child = members[f"{PARENT}-swarm-claude"]
        response = self.root / "response.md"
        response.write_text("---\nstatus: complete\n---\n", encoding="utf-8")
        self.assertEqual(rr.swarm_response_issue(child, response), "missing swarm_spec_sha256 echo")
        response.write_text(
            f"---\nstatus: complete\nswarm_spec_sha256: {SPEC}\n---\n", encoding="utf-8"
        )
        self.assertEqual(rr.swarm_response_issue(child, response), "")

    def test_insufficient_author_families_blocks_parent(self) -> None:
        parent, members = self.entries()
        members[f"{PARENT}-swarm-claude"]["status"] = "complete"
        members[f"{PARENT}-swarm-gemini"]["status"] = "timed_out"
        rr.register_swarm(PARENT, parent, members)
        self._write_sidecars_and_responses()

        changed, messages = rr.reconcile(PARENT, dry_run=False)
        self.assertEqual(changed, 1)
        self.assertTrue(any("swarm-blocked" in item for item in messages))
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(registry[PARENT]["status"], "blocked")
        self.assertEqual(registry[PARENT]["swarm_valid_author_families"], ["claude"])
        envelope = (
            self.root / "departments" / "security" / "outbox" / f"{PARENT}-response.md"
        ).read_text()
        self.assertIn("status: blocked", envelope)

    def test_malformed_sidecar_becomes_gap_instead_of_diff_hold(self) -> None:
        parent, members = self.entries()
        for member in members.values():
            member["status"] = "complete"
        rr.register_swarm(PARENT, parent, members)
        self._write_sidecars_and_responses()
        (self.root / "_state" / "swarm" / "gemini.json").write_text(
            '{"schema_version":"swarm-member-result/v1","swarm_spec_sha256":"wrong"}',
            encoding="utf-8",
        )

        changed, messages = rr.reconcile(PARENT, dry_run=False)
        self.assertEqual(changed, 1)
        self.assertFalse(any("swarm-diff-hold" in item for item in messages))
        diff = json.loads((self.root / "_state" / "swarm" / "diff.json").read_text())
        self.assertEqual(diff["coverage_gaps"][0]["lane"], "gemini")
        self.assertIn("invalid member sidecar", diff["coverage_gaps"][0]["limitations"][0])

    def test_registration_rejects_weakened_child_contract(self) -> None:
        parent, members = self.entries()
        child = members[f"{PARENT}-swarm-claude"]
        child["verification_contract"]["memory_policy"]["recall"] = "optional"
        child["verification_contract_sha256"] = verification_contract_sha256(
            child["verification_contract"]
        )
        with self.assertRaisesRegex(ValueError, "invalid swarm member verification contract"):
            rr.register_swarm(PARENT, parent, members)

    def _write_sidecars_and_responses(self) -> None:
        for lane in ("claude", "gemini"):
            sidecar = self.root / "_state" / "swarm" / f"{lane}.json"
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(
                json.dumps(
                    {
                        "schema_version": "swarm-member-result/v1",
                        "task_id": f"{PARENT}-swarm-{lane}",
                        "parent_task_id": PARENT,
                        "lane": lane,
                        "swarm_spec_sha256": SPEC,
                        "status": "complete",
                        "findings": [],
                        "coverage": ["auth"],
                        "limitations": [],
                    }
                ),
                encoding="utf-8",
            )
            response = (
                self.root
                / "departments"
                / "security"
                / "outbox"
                / f"{PARENT}-swarm-{lane}-response.md"
            )
            response.parent.mkdir(parents=True, exist_ok=True)
            response.write_text(
                f"---\nstatus: complete\nswarm_spec_sha256: {SPEC}\n---\nmember done\n",
                encoding="utf-8",
            )

    def _assert_callback_order(self, order: tuple[str, str]) -> None:
        parent, members = self.entries()
        rr.register_swarm(PARENT, parent, members)
        self._write_sidecars_and_responses()

        first = f"{PARENT}-swarm-{order[0]}"
        second = f"{PARENT}-swarm-{order[1]}"
        changed, _ = rr.reconcile(first, dry_run=False)
        self.assertGreaterEqual(changed, 1)
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(registry[first]["status"], rr.REVIEW_REQUIRED)
        self.assertEqual(registry[PARENT]["status"], "in-flight")

        changed, messages = rr.reconcile(second, dry_run=False)
        self.assertGreaterEqual(changed, 2)  # child hold plus parent freeze
        self.assertTrue(any("swarm-review-required" in item for item in messages))
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(registry[second]["status"], rr.REVIEW_REQUIRED)
        self.assertEqual(registry[PARENT]["status"], rr.REVIEW_REQUIRED)

        changed, _ = rr.reconcile(second, dry_run=False)
        self.assertEqual(changed, 0)

    def test_child_callbacks_advance_parent_claude_then_gemini(self) -> None:
        self._assert_callback_order(("claude", "gemini"))

    def test_child_callbacks_advance_parent_gemini_then_claude(self) -> None:
        self._assert_callback_order(("gemini", "claude"))


if __name__ == "__main__":
    unittest.main()
