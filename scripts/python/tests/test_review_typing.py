#!/usr/bin/env python3
"""Regression tests for typed review work in verification-contract/v1."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts" / "python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

from verification_contract import (  # noqa: E402
    derive_verification_contract,
    validate_verification_contract,
)


class ReviewTypingTests(unittest.TestCase):
    def admission(
        self,
        *,
        result_type: str = "review",
        judged_state_mutation: bool = False,
    ) -> dict[str, object]:
        return {
            "task_id": "TASK-REVIEW-TYPING-001",
            "run_id": "PRJ-REVIEW-TYPING-001",
            "mode": "project",
            "result_type": result_type,
            "to_model": "gpt-codex",
            "dispatch_kind": "single",
            # Simulate a real trigger-bearing review packet. Typing, not the
            # trigger or a specialist name, decides whether review recurses.
            "review_required": True,
            "review_subject_sha256": "a" * 64,
            "review_subject_author_family": "claude",
            "review_family": "openai",
            "review_state": "approved",
            "judged_state_mutation": judged_state_mutation,
        }

    def test_dispatch_shaped_contract_has_no_unsettled_plan_review(self) -> None:
        for review_required in (False, True):
            with self.subTest(review_required=review_required):
                admission = {
                    "task_id": "TASK-PLAN-POLICY-001",
                    "run_id": "PRJ-PLAN-POLICY-001",
                    "mode": "project",
                    "result_type": "normal",
                    "to_model": "gpt-codex",
                    "dispatch_kind": "single",
                    # This field is always present in the live send-task
                    # producer, unlike legacy direct-call fixtures.
                    "review_required": review_required,
                }

                contract = derive_verification_contract(admission)

                self.assertEqual(
                    contract["plan_review_policy"], {"required": False}
                )

    def test_typed_review_or_verification_is_not_reviewed_again(self) -> None:
        for result_type in ("review", "verification"):
            with self.subTest(result_type=result_type):
                contract = derive_verification_contract(
                    self.admission(result_type=result_type)
                )

                self.assertIs(
                    contract["deliverable_review_policy"]["required"], False
                )
                self.assertEqual(contract["review_subject_sha256"], "a" * 64)
                self.assertEqual(
                    contract["review_subject_author_family"], "claude"
                )
                self.assertEqual(contract["review_family"], "openai")
                self.assertEqual(contract["review_state"], "approved")
                self.assertIs(contract["judged_state_mutation"], False)
                self.assertEqual(
                    validate_verification_contract(
                        contract, expected_review_required=True
                    ),
                    contract,
                )

    def test_mutating_review_claim_is_still_reviewed(self) -> None:
        admission = self.admission(judged_state_mutation=True)
        # Even a producer-side no-review decision cannot turn mutation-bearing
        # work into a terminal verification act merely by labelling it review.
        admission["review_required"] = False
        contract = derive_verification_contract(admission)

        self.assertEqual(contract["result_type"], "review")
        self.assertIs(contract["judged_state_mutation"], True)
        self.assertIs(
            contract["deliverable_review_policy"]["required"], True
        )
        self.assertEqual(
            validate_verification_contract(
                contract, expected_review_required=True
            ),
            contract,
        )

    def test_same_family_review_claim_is_still_reviewed(self) -> None:
        admission = self.admission()
        admission["review_required"] = False
        admission["review_subject_author_family"] = "openai"

        contract = derive_verification_contract(admission)

        self.assertIs(
            contract["deliverable_review_policy"]["required"], True
        )


if __name__ == "__main__":
    unittest.main()
