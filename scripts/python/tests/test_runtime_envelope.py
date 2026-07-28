from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest


PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from runtime_envelope import (  # noqa: E402
    EnvelopeError,
    RuntimeEnvelopeClaims,
    launch_task,
    seal_runtime_envelope,
    verify_runtime_envelope,
)
from role_context_compiler import compile_role_context  # noqa: E402


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def claims() -> RuntimeEnvelopeClaims:
    return RuntimeEnvelopeClaims(
        task_id="TASK-2026-07-22-0425-v2-t2p2-launcher",
        attempt_id="d-089b75b4634d4b45a02b903c2f918c8d",
        generation=2,
        run_id="PROJ-SWARM-READY-2026-07-19",
        lane="gpt-codex",
        author_family="openai",
        workload_class="repo-build-test",
        packet_sha256=SHA_A,
        role_context_sha256=SHA_B,
        overlay_sha256=SHA_C,
        plan_sha256=SHA_A,
        authority_sha256=SHA_B,
        verification_contract_sha256=SHA_C,
        selected_model_sha256=SHA_A,
        read_scope=("/repo/docs",),
        write_scope=("/repo/out",),
        network_scope=("127.0.0.1:41321",),
        action_scope=("file:write", "broker:call"),
        budgets={"max_calls": 4, "max_cost_micros": 1},
        expected_result_path="/repo/out/result.md",
        expected_outbox_path="/repo/out/response.md",
        required_phase_ids=("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"),
        verification_kinds=("project_tests", "recipient_contract"),
        operator_gates=("production_mutation",),
        stage1_profile_sha256=SHA_B,
        stage1_request_sha256=SHA_A,
        stage1_scope_sha256=SHA_C,
        reconciliation_nonce="nonce-42",
        created_at=1_000,
        expires_at=2_000,
    )


class RuntimeEnvelopeTests(unittest.TestCase):
    def test_envelope_seals_deterministically_and_verifies(self) -> None:
        key = b"supervisor-secret-key-material"
        first = seal_runtime_envelope(claims(), key)
        second = seal_runtime_envelope(claims(), key)

        self.assertEqual(first, second)
        self.assertEqual(first.schema, "task-runtime-envelope/v1")
        verified = verify_runtime_envelope(
            first,
            key,
            expected_task_id=claims().task_id,
            expected_attempt_id=claims().attempt_id,
            expected_generation=2,
            now=1_500,
        )
        self.assertEqual(verified, claims())
        self.assertNotIn("supervisor-secret", repr(first))

    def test_envelope_rejects_tampering_stale_generation_and_expiry(self) -> None:
        key = b"supervisor-secret-key-material"
        sealed = seal_runtime_envelope(claims(), key)

        with self.assertRaisesRegex(EnvelopeError, "MAC"):
            verify_runtime_envelope(replace(sealed, mac_sha256="0" * 64), key, now=1_500)
        with self.assertRaisesRegex(EnvelopeError, "generation"):
            verify_runtime_envelope(sealed, key, expected_generation=3, now=1_500)
        with self.assertRaisesRegex(EnvelopeError, "expired"):
            verify_runtime_envelope(sealed, key, now=2_001)

    def test_envelope_rejects_noncanonical_or_incomplete_claims(self) -> None:
        key = b"supervisor-secret-key-material"
        with self.assertRaises(EnvelopeError):
            seal_runtime_envelope(replace(claims(), write_scope=()), key)
        with self.assertRaises(EnvelopeError):
            seal_runtime_envelope(replace(claims(), stage1_profile_sha256=""), key)
        with self.assertRaisesRegex(EnvelopeError, "canonical absolute"):
            seal_runtime_envelope(replace(claims(), write_scope=("../escape",)), key)

    def test_advisory_allows_artifact_written_without_phase_ids(self) -> None:
        key = b"supervisor-secret-key-material"
        advisory = replace(
            claims(),
            run_id="ADV-TEST-001",
            required_phase_ids=(),
            verification_kinds=("artifact_written",),
        )

        sealed = seal_runtime_envelope(advisory, key)

        self.assertEqual(
            verify_runtime_envelope(sealed, key, now=1_500),
            advisory,
        )
        with self.assertRaisesRegex(EnvelopeError, "required phase id"):
            seal_runtime_envelope(
                replace(claims(), required_phase_ids=()),
                key,
            )

    def test_launch_task_binds_role_envelope_and_stage1_receipt(self) -> None:
        key = b"supervisor-secret-key-material"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            role_path = root / "role.md"
            overlay_path = root / "overlay.md"
            role_path.write_text("# Role\n\nBuild.\n", encoding="utf-8")
            overlay_path.write_text("# Lane\n\nUse Codex.\n", encoding="utf-8")
            role = compile_role_context(
                role_path,
                overlay_path,
                specialist="systems-engineer",
                lane="gpt-codex",
            )
            bound_claims = replace(claims(), role_context_sha256=role.sha256)
            envelope = seal_runtime_envelope(bound_claims, key)
            captured: dict[str, object] = {}

            def fake_launcher(canary_runner: object, command: object, **kwargs: object) -> str:
                captured["canary_runner"] = canary_runner
                captured["command"] = command
                captured.update(kwargs)
                return "launched"

            canary_runner = lambda: None
            result = launch_task(
                envelope,
                key,
                role,
                executable=Path("/usr/bin/true"),
                canary_runner=canary_runner,
                expected_task_id=bound_claims.task_id,
                expected_attempt_id=bound_claims.attempt_id,
                expected_generation=bound_claims.generation,
                now=1_500,
                launcher=fake_launcher,
            )

            self.assertEqual(result, "launched")
            command = captured["command"]
            self.assertEqual(command[:2], ("/usr/bin/true", "exec"))
            self.assertIn(role.prompt, command[-1])
            self.assertIn(envelope.envelope_sha256, command[-1])
            self.assertIs(captured["canary_runner"], canary_runner)
            self.assertEqual(captured["expected_profile_sha256"], SHA_B)
            self.assertEqual(captured["expected_request_sha256"], SHA_A)
            self.assertEqual(captured["expected_scope_sha256"], SHA_C)

            with self.assertRaisesRegex(EnvelopeError, "resume"):
                launch_task(
                    envelope,
                    key,
                    role,
                    executable=Path("/usr/bin/true"),
                    canary_runner=canary_runner,
                    expected_task_id=bound_claims.task_id,
                    expected_attempt_id=bound_claims.attempt_id,
                    expected_generation=bound_claims.generation,
                    now=1_500,
                    lane_args=("--resume",),
                    launcher=fake_launcher,
                )

            with self.assertRaisesRegex(EnvelopeError, "role context"):
                launch_task(
                    envelope,
                    key,
                    replace(role, sha256=SHA_A),
                    executable=Path("/usr/bin/true"),
                    canary_runner=canary_runner,
                    expected_task_id=bound_claims.task_id,
                    expected_attempt_id=bound_claims.attempt_id,
                    expected_generation=bound_claims.generation,
                    now=1_500,
                    launcher=fake_launcher,
                )


if __name__ == "__main__":
    unittest.main()
