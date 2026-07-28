from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from tool_surface_attest import (  # noqa: E402
    AttestationError,
    LaunchEvidence,
    OperationEvidence,
    ReconciliationChain,
    attest_launch,
    attest_tool_operation,
    capture_tool_operation,
    reconcile_result,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def real_evidence() -> OperationEvidence:
    return OperationEvidence(
        tool="pytest",
        operation="run focused project test",
        evidence_kind="operation",
        expected_effect="test marker created in authorized temp scope",
        observed_effect="test marker created in authorized temp scope",
        effect_observed=True,
        exit_code=0,
        sandbox_denied=False,
        profile_sha256=SHA_A,
        envelope_sha256=SHA_B,
        evidence_sha256=SHA_C,
        observed_at=1_234,
    )


class ToolSurfaceAttestTests(unittest.TestCase):
    def test_attestation_requires_real_operation_and_expected_effect(self) -> None:
        attestation = attest_tool_operation(
            real_evidence(), expected_profile_sha256=SHA_A, expected_envelope_sha256=SHA_B
        )
        self.assertTrue(attestation.available)
        self.assertEqual(len(attestation.sha256), 64)

        version_only = replace(
            real_evidence(),
            operation="pytest --version",
            evidence_kind="version",
            expected_effect="version output",
            observed_effect="pytest 9",
        )
        with self.assertRaisesRegex(AttestationError, "version/help"):
            attest_tool_operation(
                version_only, expected_profile_sha256=SHA_A, expected_envelope_sha256=SHA_B
            )

    def test_capture_runs_operation_and_observes_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "effect.txt"

            def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(command, capture_output=True, text=True, check=False)

            attestation = capture_tool_operation(
                tool="shell-write-probe",
                operation="write authorized marker",
                command=("/bin/sh", "-c", f"printf observed > {marker}"),
                expected_effect="observed",
                observe_effect=lambda: marker.read_text(encoding="utf-8") if marker.exists() else "",
                profile_sha256=SHA_A,
                envelope_sha256=SHA_B,
                observed_at=1_235,
                runner=runner,
            )

            self.assertTrue(attestation.available)
            self.assertEqual(attestation.observed_effect, "observed")

    def test_launch_attestation_requires_all_stage1_effects(self) -> None:
        evidence = LaunchEvidence(
            envelope_sha256=SHA_A,
            profile_sha256=SHA_B,
            request_sha256=SHA_C,
            scope_sha256=SHA_D,
            supervisor_build_sha256=SHA_E,
            cli_sha256=SHA_F,
            argv_sha256=SHA_A,
            environment_keys_sha256=SHA_B,
            canary_sha256=SHA_C,
            admission_sha256=SHA_D,
            allowed_write=True,
            denied_write=True,
            exact_broker_port=True,
            wrong_port_denied=True,
            descriptor_audit_passed=True,
            inode_audit_passed=True,
            broker_healthy=True,
            observed_at=1_236,
        )
        attestation = attest_launch(evidence, expected_envelope_sha256=SHA_A)
        self.assertEqual(attestation.envelope_sha256, SHA_A)
        self.assertEqual(len(attestation.sha256), 64)

        with self.assertRaisesRegex(AttestationError, "launch effect"):
            attest_launch(replace(evidence, denied_write=False), expected_envelope_sha256=SHA_A)

    def test_reconciliation_rejects_every_broken_link(self) -> None:
        cases = [
            ({"envelope_sha256": ""}, "missing"),
            ({"launch_attestation_sha256": ""}, "missing"),
            ({"tool_attestation_sha256": ""}, "missing"),
            ({"action_log_sha256": ""}, "missing"),
            ({"artifact_bundle_sha256": ""}, "missing"),
            ({"model_history_sha256": ""}, "missing"),
            ({"outbox_sha256": ""}, "missing"),
            ({"generation": 1}, "generation"),
            ({"sandbox_denials": ("denied-write reported success",)}, "sandbox denial"),
            ({"output_paths": ("/repo/private/leak",)}, "outside"),
            ({"review_state": "pending"}, "review"),
            ({"review_subject_sha256": SHA_A}, "review subject"),
            ({"review_family": "openai"}, "anti-affinity"),
        ]
        chain = self._chain()
        for mutation, match in cases:
            with self.subTest(mutation=mutation):
                broken = replace(chain, **mutation)
                with self.assertRaisesRegex(AttestationError, match):
                    self._reconcile(broken)

    def test_reconciliation_accepts_complete_hash_bound_chain(self) -> None:
        chain = self._chain()
        self.assertIs(self._reconcile(chain), chain)

    @staticmethod
    def _chain() -> ReconciliationChain:
        return ReconciliationChain(
            task_id="TASK-2026-07-22-0425-v2-t2p2-launcher",
            attempt_id="d-089b75b4634d4b45a02b903c2f918c8d",
            generation=2,
            envelope_sha256=SHA_A,
            launch_attestation_sha256=SHA_B,
            tool_attestation_sha256=SHA_C,
            action_log_sha256=SHA_D,
            artifact_bundle_sha256=SHA_E,
            model_history_sha256=SHA_F,
            review_subject_sha256=SHA_E,
            review_family="anthropic",
            review_state="approved",
            outbox_sha256=SHA_A,
            output_paths=("/repo/out/result.md", "/repo/out/response.md"),
            sandbox_denials=(),
        )

    @staticmethod
    def _reconcile(chain: ReconciliationChain) -> ReconciliationChain:
        return reconcile_result(
            chain,
            expected_task_id="TASK-2026-07-22-0425-v2-t2p2-launcher",
            expected_attempt_id="d-089b75b4634d4b45a02b903c2f918c8d",
            expected_generation=2,
            expected_envelope_sha256=SHA_A,
            authorized_write_scope=("/repo/out",),
            mandatory_review=True,
            author_family="openai",
        )


if __name__ == "__main__":
    unittest.main()
