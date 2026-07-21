#!/usr/bin/env python3
"""Hermetic P2 hierarchical orchestration and exhaustive-review tests."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from swarm_diff import (  # noqa: E402
    SwarmDiffError,
    build_diff,
    build_orchestration_dispatch,
    decompose_review_subjects,
    load_taxonomy,
    seal_finding_review,
    seal_member_bundle,
    seal_orchestration_directive,
    sha256,
    validate_exhaustive_reviews,
    validate_member_bundle,
)


FEATURE = "SQUAD_SUBSWARM_ORCHESTRATION_ENABLED"


class SubswarmOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feature = patch.dict(
            os.environ,
            {FEATURE: "1", "SQUAD_SUBAGENT_CONCURRENCY_CAP": "16"},
            clear=False,
        )
        self.feature.start()
        self.temp = tempfile.TemporaryDirectory(prefix="subswarm-p2-")
        self.root = Path(self.temp.name)
        self.taxonomy_path = self.root / "finding-taxonomy.md"
        self.taxonomy_path.write_text(
            '# Taxonomy\n\n```json swarm-finding-taxonomy/v1\n'
            + json.dumps(
                {
                    "schema_version": "swarm-finding-taxonomy/v1",
                    "weakness_classes": ["access-control", "injection"],
                    "impact_classes": ["confidentiality-loss", "integrity-loss"],
                    "dispositions": ["confirmed", "rejected"],
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
        self.taxonomy = load_taxonomy(self.taxonomy_path)

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.feature.stop()

    @staticmethod
    def finding(summary: str = "Authorization bypass") -> dict:
        return {
            "target": "service-a",
            "weakness_class": "access-control",
            "affected_surface": "src/auth.py::authorize",
            "impact_class": "confidentiality-loss",
            "disposition": "confirmed",
            "severity": "high",
            "confidence": "high",
            "summary": summary,
            "evidence": ["evidence/auth.log"],
        }

    def directive(
        self,
        lane: str = "gpt-codex",
        *,
        mode: str = "parallel",
        tool_modes: tuple[str, ...] = ("inherited", "none"),
        requires_mcp: tuple[bool, ...] = (True, False),
    ) -> dict:
        members = []
        for index, (tool_mode, needs_mcp) in enumerate(
            zip(tool_modes, requires_mcp, strict=True), 1
        ):
            members.append(
                {
                    "member_id": f"{lane}:sub{index:02d}",
                    "lane": lane,
                    "replica_index": index,
                    "role": "security-analyst" if index == 1 else "skeptic",
                    "objective_sha256": str(index) * 64,
                    "output_path": f"_state/subswarm/TASK-PARENT/{lane}/sub{index:02d}/result.json",
                    "requires_mcp": needs_mcp,
                    "tool_mode": tool_mode,
                    "depends_on": [] if mode == "parallel" or index == 1 else [f"{lane}:sub01"],
                }
            )
        return seal_orchestration_directive(
            {
                "schema_version": "lead-orchestration-directive/v1",
                "parent_task_id": "TASK-PARENT",
                "lane": lane,
                "mode": mode,
                "max_concurrency": 1 if mode == "sequential" else len(members),
                "members": members,
            }
        )

    @staticmethod
    def tool_receipt(mode: str = "inherited") -> dict:
        return {
            "schema_version": "tool-receipt/v1",
            "tool_name": "chrono-vault.recall",
            "mode": mode,
            "request_sha256": "a" * 64,
            "result_sha256": "b" * 64,
            "status": "succeeded",
            "error_code": None,
        }

    @staticmethod
    def gap(kind: str = "missing_result") -> dict:
        return {
            "schema_version": "subswarm-gap/v1",
            "gap_kind": kind,
            "summary": "Typed incomplete path",
            "evidence": ["evidence/gap.json"],
        }

    def raw_bundle(self, directive: dict) -> dict:
        lane = directive["lane"]
        members = []
        for index, directed in enumerate(directive["members"], 1):
            receipts = []
            if directed["requires_mcp"]:
                receipts = [self.tool_receipt(directed["tool_mode"])]
            members.append(
                {
                    "schema_version": "swarm-member-result/v1",
                    "member_id": directed["member_id"],
                    "lane": lane,
                    "replica_index": index,
                    "objective_sha256": directed["objective_sha256"],
                    "status": "complete",
                    "artifact_sha256": str(index + 2) * 64,
                    "completion": {
                        "schema_version": "subswarm-completion/v1",
                        "completed": True,
                        "summary": "Declared assignment completed.",
                    },
                    "findings": [
                        self.finding(
                            "Authorization bypass"
                            if index == 1
                            else "Divergent authorization interpretation"
                        )
                    ],
                    "gaps": [self.gap()] if index == 2 else [],
                    "tool_receipts": receipts,
                    "coverage": ["auth"],
                    "limitations": [],
                }
            )
        return {
            "schema_version": "swarm-member-bundle/v1",
            "parent_task_id": directive["parent_task_id"],
            "lane": lane,
            "orchestration_directive_sha256": directive["directive_sha256"],
            "members": members,
        }

    def sealed_bundle(self, directive: dict | None = None) -> tuple[dict, dict]:
        directive = directive or self.directive()
        return directive, seal_member_bundle(
            self.raw_bundle(directive), self.taxonomy, directive
        )

    def test_member_array_hashes_are_lane_bound_and_exhaustively_decomposed(self) -> None:
        directive, bundle = self.sealed_bundle()
        validated = validate_member_bundle(bundle, self.taxonomy, directive)
        self.assertEqual(validated, bundle)
        self.assertEqual(len({member["result_sha256"] for member in bundle["members"]}), 2)
        decomposition = decompose_review_subjects(bundle, self.taxonomy, directive)
        # Two completions + two findings + one gap + one tool receipt: no class is sampled away.
        self.assertEqual(decomposition["subject_count"], 6)
        self.assertTrue(decomposition["exhaustive"])
        self.assertEqual(
            {subject["kind"] for subject in decomposition["subjects"]},
            {"completion", "finding", "gap", "tool_receipt"},
        )
        self.assertEqual(
            len({subject["subject_sha256"] for subject in decomposition["subjects"]}),
            decomposition["subject_count"],
        )
        for subject in decomposition["subjects"]:
            self.assertTrue(subject["member_id"].startswith("gpt-codex:sub"))
            self.assertEqual(subject["payload"]["item_sha256"], subject["subject_sha256"])

    def test_missing_duplicate_and_mutated_member_or_item_hashes_fail_closed(self) -> None:
        directive, bundle = self.sealed_bundle()
        missing = copy.deepcopy(bundle)
        missing["members"].pop()
        with self.assertRaisesRegex(SwarmDiffError, "every directive member"):
            validate_member_bundle(missing, self.taxonomy, directive)

        duplicate = copy.deepcopy(bundle)
        duplicate["members"][1]["member_id"] = duplicate["members"][0]["member_id"]
        with self.assertRaisesRegex(SwarmDiffError, "duplicate member_id"):
            validate_member_bundle(duplicate, self.taxonomy, directive)

        mutated = copy.deepcopy(bundle)
        mutated["members"][0]["findings"][0]["summary"] = "Unhashed mutation"
        with self.assertRaisesRegex(SwarmDiffError, "result_sha256 mismatch|item_sha256 mismatch"):
            validate_member_bundle(mutated, self.taxonomy, directive)

        wrong_objective = self.raw_bundle(directive)
        wrong_objective["members"][0]["objective_sha256"] = "f" * 64
        with self.assertRaisesRegex(SwarmDiffError, "objective_sha256 differs"):
            seal_member_bundle(wrong_objective, self.taxonomy, directive)

        spoofed = copy.deepcopy(bundle)
        spoofed["members"][1]["findings"][0]["item_sha256"] = (
            spoofed["members"][0]["findings"][0]["item_sha256"]
        )
        with self.assertRaisesRegex(SwarmDiffError, "item_sha256 mismatch|duplicate"):
            validate_member_bundle(spoofed, self.taxonomy, directive)

        no_completion = copy.deepcopy(bundle)
        no_completion["members"][0].pop("completion")
        with self.assertRaisesRegex(SwarmDiffError, "completion subject"):
            validate_member_bundle(no_completion, self.taxonomy, directive)

    def test_completion_keeps_empty_member_visible_and_item_hash_is_task_bound(self) -> None:
        directive = self.directive()
        raw = self.raw_bundle(directive)
        raw["members"][1]["findings"] = []
        raw["members"][1]["gaps"] = []
        raw["members"][1]["tool_receipts"] = []
        bundle = seal_member_bundle(raw, self.taxonomy, directive)
        decomposition = decompose_review_subjects(bundle, self.taxonomy, directive)
        second = [
            subject
            for subject in decomposition["subjects"]
            if subject["member_id"] == "gpt-codex:sub02"
        ]
        self.assertEqual([subject["kind"] for subject in second], ["completion"])

        alternate_core = dict(directive)
        alternate_core.pop("directive_sha256")
        alternate_core["parent_task_id"] = "TASK-OTHER"
        for member in alternate_core["members"]:
            member["output_path"] = member["output_path"].replace(
                "/TASK-PARENT/", "/TASK-OTHER/"
            )
        alternate = seal_orchestration_directive(alternate_core)
        alternate_bundle = seal_member_bundle(
            self.raw_bundle(alternate), self.taxonomy, alternate
        )
        self.assertNotEqual(
            bundle["members"][0]["findings"][0]["item_sha256"],
            alternate_bundle["members"][0]["findings"][0]["item_sha256"],
        )

    def test_exact_cross_family_review_set_rejects_sampling_and_same_family(self) -> None:
        directive, bundle = self.sealed_bundle()
        decomposition = decompose_review_subjects(bundle, self.taxonomy, directive)
        reviews = [
            seal_finding_review(
                {
                    "schema_version": "finding-review/v1",
                    "subject_sha256": subject["subject_sha256"],
                    "reviewer_family": "anthropic",
                    "verdict": "accept",
                    "evidence_checked": [],
                    "rationale": "Reviewed exact hash-bound subject.",
                }
            )
            for subject in decomposition["subjects"]
        ]
        with self.assertRaisesRegex(SwarmDiffError, "missing exhaustive"):
            validate_exhaustive_reviews(decomposition, reviews[:-1], directive)
        self.assertEqual(
            len(validate_exhaustive_reviews(decomposition, reviews, directive)),
            decomposition["subject_count"],
        )
        same_family = copy.deepcopy(reviews)
        raw = dict(same_family[0])
        raw.pop("review_record_sha256")
        raw["reviewer_family"] = "openai"
        same_family[0] = seal_finding_review(raw)
        with self.assertRaisesRegex(SwarmDiffError, "cross-family"):
            validate_exhaustive_reviews(decomposition, same_family, directive)
        unknown = dict(reviews[0])
        unknown.pop("review_record_sha256")
        unknown["reviewer_family"] = "unknown-family"
        with self.assertRaisesRegex(SwarmDiffError, "known author-family"):
            seal_finding_review(unknown)

        duplicate_subject = copy.deepcopy(decomposition)
        duplicate_subject["subjects"].append(
            copy.deepcopy(duplicate_subject["subjects"][0])
        )
        duplicate_subject["subject_count"] += 1
        duplicate_core = dict(duplicate_subject)
        duplicate_core.pop("decomposition_sha256")
        duplicate_subject["decomposition_sha256"] = sha256(duplicate_core)
        with self.assertRaisesRegex(SwarmDiffError, "hashes must be unique"):
            validate_exhaustive_reviews(duplicate_subject, reviews, directive)

        tampered_subject = copy.deepcopy(decomposition)
        tampered_subject["subjects"][0]["lane"] = "claude"
        tampered_core = dict(tampered_subject)
        tampered_core.pop("decomposition_sha256")
        tampered_subject["decomposition_sha256"] = sha256(tampered_core)
        with self.assertRaisesRegex(SwarmDiffError, "lane/member identity mismatch"):
            validate_exhaustive_reviews(tampered_subject, reviews, directive)

        no_completion = copy.deepcopy(decomposition)
        no_completion["subjects"] = [
            subject
            for subject in no_completion["subjects"]
            if not (
                subject["member_id"] == "gpt-codex:sub02"
                and subject["kind"] == "completion"
            )
        ]
        no_completion["subject_count"] -= 1
        no_completion_core = dict(no_completion)
        no_completion_core.pop("decomposition_sha256")
        no_completion["decomposition_sha256"] = sha256(no_completion_core)
        with self.assertRaisesRegex(SwarmDiffError, "exactly one completion"):
            validate_exhaustive_reviews(no_completion, reviews, directive)

    def test_directive_cap_parallel_sequential_and_dispatch_render_are_deterministic(self) -> None:
        parallel = self.directive()
        dispatch = build_orchestration_dispatch(parallel)
        self.assertIn("at most 2 active", dispatch["brief_markdown"])
        self.assertIn(parallel["directive_sha256"], dispatch["brief_markdown"])
        self.assertIn("Actually spawn", dispatch["brief_markdown"])
        self.assertIn("never simulate member work", dispatch["brief_markdown"])
        self.assertIn("do not receive mailbox claims", dispatch["brief_markdown"])
        self.assertIn("bind its SHA-256 as artifact_sha256", dispatch["brief_markdown"])
        self.assertIn("typed gap; never fabricate", dispatch["brief_markdown"])
        self.assertIn("lead alone seals and publishes", dispatch["brief_markdown"])
        self.assertEqual(dispatch, build_orchestration_dispatch(parallel))

        sequential = self.directive(mode="sequential")
        self.assertEqual(sequential["max_concurrency"], 1)
        too_wide = copy.deepcopy(parallel)
        too_wide.pop("directive_sha256")
        too_wide["max_concurrency"] = 3
        with patch.dict(os.environ, {"SQUAD_SUBAGENT_CONCURRENCY_CAP": "2"}, clear=False):
            with self.assertRaisesRegex(SwarmDiffError, "configured per-lead cap"):
                seal_orchestration_directive(too_wide)

        bad_sequential = copy.deepcopy(sequential)
        bad_sequential.pop("directive_sha256")
        bad_sequential["max_concurrency"] = 2
        with self.assertRaisesRegex(SwarmDiffError, "sequential"):
            seal_orchestration_directive(bad_sequential)

        cyclic = copy.deepcopy(parallel)
        cyclic.pop("directive_sha256")
        cyclic["members"][0]["depends_on"] = ["gpt-codex:sub02"]
        cyclic["members"][1]["depends_on"] = ["gpt-codex:sub01"]
        with self.assertRaisesRegex(SwarmDiffError, "contains a cycle"):
            seal_orchestration_directive(cyclic)

        duplicate_output = copy.deepcopy(parallel)
        duplicate_output.pop("directive_sha256")
        duplicate_output["members"][1]["output_path"] = duplicate_output["members"][0]["output_path"]
        with self.assertRaisesRegex(SwarmDiffError, "output_path"):
            seal_orchestration_directive(duplicate_output)

        escaping_output = copy.deepcopy(parallel)
        escaping_output.pop("directive_sha256")
        escaping_output["members"][0]["output_path"] = "../../shared/result.json"
        with self.assertRaisesRegex(SwarmDiffError, "output_path"):
            seal_orchestration_directive(escaping_output)

    def test_five_member_bundle_remains_exhaustive_without_sampling(self) -> None:
        directive = self.directive(
            tool_modes=("none",) * 5,
            requires_mcp=(False,) * 5,
        )
        bundle = seal_member_bundle(self.raw_bundle(directive), self.taxonomy, directive)
        decomposition = decompose_review_subjects(bundle, self.taxonomy, directive)
        self.assertEqual(len(bundle["members"]), 5)
        self.assertEqual(
            {item["member_id"] for item in bundle["members"]},
            {f"gpt-codex:sub{index:02d}" for index in range(1, 6)},
        )
        self.assertTrue(decomposition["exhaustive"])
        self.assertEqual(decomposition["subject_count"], 11)

    def test_gemini_inherited_mcp_and_kimi_lead_broker_policy(self) -> None:
        gemini = self.directive(
            "gemini", tool_modes=("inherited",), requires_mcp=(True,)
        )
        self.assertEqual(gemini["members"][0]["tool_mode"], "inherited")

        with self.assertRaisesRegex(SwarmDiffError, "never assume inherited MCP"):
            self.directive("kimi", tool_modes=("inherited",), requires_mcp=(True,))
        kimi = self.directive(
            "kimi", tool_modes=("lead-brokered",), requires_mcp=(True,)
        )
        dispatch = build_orchestration_dispatch(kimi)
        self.assertIn("Kimi subagents are MCP-free", dispatch["brief_markdown"])
        _, bundle = self.sealed_bundle(kimi)
        self.assertEqual(
            bundle["members"][0]["tool_receipts"][0]["mode"], "lead-brokered"
        )

    def test_default_off_rejects_new_api_but_legacy_diff_is_byte_compatible(self) -> None:
        legacy_members = [
            {
                "schema_version": "swarm-member-result/v1",
                "task_id": "TASK-PARENT-swarm-claude",
                "parent_task_id": "TASK-PARENT",
                "lane": "claude",
                "swarm_spec_sha256": "f" * 64,
                "status": "complete",
                "findings": [self.finding()],
                "coverage": ["auth"],
                "limitations": [],
            }
        ]
        enabled_legacy = build_diff(legacy_members, self.taxonomy, "f" * 64)
        with patch.dict(os.environ, {FEATURE: "0"}, clear=False):
            disabled_legacy = build_diff(legacy_members, self.taxonomy, "f" * 64)
            self.assertEqual(enabled_legacy, disabled_legacy)
            with self.assertRaisesRegex(SwarmDiffError, "disabled"):
                self.directive()

    def test_cli_builds_embeddable_directive_and_decomposes_bundle(self) -> None:
        directive, bundle = self.sealed_bundle()
        directive_core = dict(directive)
        directive_core.pop("directive_sha256")
        directive_input = self.root / "directive-core.json"
        directive_input.write_text(json.dumps(directive_core), encoding="utf-8")
        dispatch_output = self.root / "dispatch.json"
        env = {**os.environ, FEATURE: "1", "SQUAD_SUBAGENT_CONCURRENCY_CAP": "2"}
        built = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "swarm_diff.py"),
                "--build-orchestration-directive",
                str(directive_input),
                "--output",
                str(dispatch_output),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(built.returncode, 0, msg=built.stderr)
        dispatch = json.loads(dispatch_output.read_text())
        self.assertEqual(dispatch["directive"]["directive_sha256"], directive["directive_sha256"])

        directive_path = self.root / "directive.json"
        raw_bundle_path = self.root / "raw-bundle.json"
        bundle_path = self.root / "sealed-bundle.json"
        directive_path.write_text(json.dumps(directive), encoding="utf-8")
        raw_bundle_path.write_text(json.dumps(self.raw_bundle(directive)), encoding="utf-8")
        sealed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "swarm_diff.py"),
                "--seal-member-bundle",
                str(raw_bundle_path),
                "--orchestration-directive",
                str(directive_path),
                "--taxonomy",
                str(self.taxonomy_path),
                "--output",
                str(bundle_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(sealed.returncode, 0, msg=sealed.stderr)
        self.assertEqual(json.loads(bundle_path.read_text()), bundle)
        subjects_output = self.root / "subjects.json"
        decomposed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "swarm_diff.py"),
                "--member-bundle",
                str(bundle_path),
                "--orchestration-directive",
                str(directive_path),
                "--taxonomy",
                str(self.taxonomy_path),
                "--output",
                str(subjects_output),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(decomposed.returncode, 0, msg=decomposed.stderr)
        self.assertEqual(json.loads(subjects_output.read_text())["subject_count"], 6)


if __name__ == "__main__":
    unittest.main()
