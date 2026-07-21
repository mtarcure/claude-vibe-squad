#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "python"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from swarm_diff import (  # noqa: E402
    SwarmDiffError,
    build_diff,
    freeze_diff,
    load_taxonomy,
)


SPEC = "a" * 64


class SwarmDiffTests(unittest.TestCase):
    def taxonomy_file(self, root: Path) -> Path:
        path = root / "finding-taxonomy.md"
        path.write_text(
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
        return path

    def finding(self, *, summary: str = "Shared evidence", severity: str = "high") -> dict:
        return {
            "target": "service-a",
            "weakness_class": "access-control",
            "affected_surface": "src/auth.py::authorize",
            "impact_class": "confidentiality-loss",
            "disposition": "confirmed",
            "severity": severity,
            "confidence": "high",
            "summary": summary,
            "evidence": ["evidence/auth.log"],
        }

    def member(
        self,
        lane: str,
        finding: dict | None,
        *,
        status: str = "complete",
        limitations: list[str] | None = None,
    ) -> dict:
        return {
            "schema_version": "swarm-member-result/v1",
            "task_id": f"TASK-PARENT-swarm-{lane}",
            "parent_task_id": "TASK-PARENT",
            "lane": lane,
            "swarm_spec_sha256": SPEC,
            "status": status,
            "findings": [] if finding is None else [finding],
            "coverage": ["auth"],
            "limitations": limitations or [],
        }

    def test_classifies_agreement_divergence_lane_only_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            taxonomy = load_taxonomy(self.taxonomy_file(Path(temp_dir)))
            agreement = build_diff(
                [self.member("claude", self.finding()), self.member("gpt-codex", self.finding())],
                taxonomy,
                SPEC,
            )
            self.assertEqual(len(agreement["agreement"]), 1)
            self.assertEqual(agreement["divergence"], [])
            self.assertTrue(agreement["mandatory_review"])

            divergent = build_diff(
                [
                    self.member("claude", self.finding(summary="A")),
                    self.member("gemini", self.finding(summary="B")),
                    self.member(
                        "kimi", None, status="timed_out", limitations=["deadline reached"]
                    ),
                ],
                taxonomy,
                SPEC,
            )
            self.assertEqual(len(divergent["divergence"]), 1)
            self.assertEqual(divergent["coverage_gaps"][0]["lane"], "kimi")

            rejected = self.finding()
            rejected["disposition"] = "rejected"
            disposition_divergence = build_diff(
                [self.member("claude", self.finding()), self.member("gemini", rejected)],
                taxonomy,
                SPEC,
            )
            self.assertEqual(len(disposition_divergence["divergence"]), 1)

            unique = self.finding()
            unique["affected_surface"] = "src/admin.py::delete"
            lane_only = build_diff(
                [self.member("claude", unique), self.member("gemini", None)], taxonomy, SPEC
            )
            self.assertEqual(lane_only["lane_only"][0]["lane"], "claude")

    def test_rejects_bad_spec_taxonomy_and_spoofed_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            taxonomy = load_taxonomy(self.taxonomy_file(Path(temp_dir)))
            bad_spec = self.member("claude", self.finding())
            bad_spec["swarm_spec_sha256"] = "b" * 64
            with self.assertRaisesRegex(SwarmDiffError, "frozen parent spec"):
                build_diff([bad_spec], taxonomy, SPEC)

            bad_finding = self.finding()
            bad_finding["weakness_class"] = "invented"
            with self.assertRaisesRegex(SwarmDiffError, "unknown weakness"):
                build_diff([self.member("claude", bad_finding)], taxonomy, SPEC)

            spoofed = self.finding()
            spoofed["finding_key"] = "spoofed"
            with self.assertRaisesRegex(SwarmDiffError, "claimed finding_key"):
                build_diff([self.member("claude", spoofed)], taxonomy, SPEC)

    def test_freeze_is_idempotent_and_late_results_cannot_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            taxonomy = self.taxonomy_file(root)
            member = root / "claude.json"
            member.write_text(json.dumps(self.member("claude", self.finding())), encoding="utf-8")
            output = root / "diff.json"

            first, created = freeze_diff(output, [member], taxonomy, SPEC)
            self.assertTrue(created)
            original = output.read_bytes()

            member.write_text(
                json.dumps(self.member("claude", self.finding(summary="late mutation"))),
                encoding="utf-8",
            )
            second, created = freeze_diff(output, [member], taxonomy, SPEC)
            self.assertFalse(created)
            self.assertEqual(first, second)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
