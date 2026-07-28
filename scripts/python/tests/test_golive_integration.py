#!/usr/bin/env python3
"""TDD acceptance for V2 go-live enforcement and launch honesty."""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import held_action_gate as gate  # noqa: E402
import held_effect_executor as effects  # noqa: E402
import seatbelt_profile as seatbelt  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)
from scripts.python.tests.test_trusted_launch import (  # noqa: E402
    SCRIPT,
    SETTLED_T1P1_BUNDLE_SHA256,
    _init_repo,
    _write_role_files,
)


SIGNING_KEY = b"go-live-held-effect-signing-key-material"
AUTHORITY_KEY = b"A" * 32


def _backends(overrides=None):
    values = {
        category: Mock(return_value={"status": "performed"})
        for category in gate.HELD_CATEGORIES
    }
    values.update(overrides or {})
    return values


def _effect_request(category: str) -> effects.HeldEffectRequest:
    effect_name = f"test-{category}"
    effect_payload = {"fixture": category}
    return effects.HeldEffectRequest(
        category=category,
        target=effects.canonical_effect_target(category, effect_name, effect_payload),
        task_id="TASK-2026-07-22-0605-v2-golive-integration",
        attempt_id="d-" + "7" * 32,
        effect_name=effect_name,
        effect_payload=effect_payload,
    )


def _authority_payload(
    root: Path,
    *,
    executable: str = "/usr/bin/true",
    execution_kind: str = "offline-probe",
    lane: str = "claude",
) -> dict[str, object]:
    repo = _init_repo(root)
    role, overlay = _write_role_files(root)
    digest = lambda label: hashlib.sha256(label.encode("utf-8")).hexdigest()
    file_digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    now = int(time.time())
    return {
        "schema": "go-live-authority/v1",
        "task_id": "TASK-2026-07-22-0605-v2-golive-integration",
        "attempt_id": "d-" + "7" * 32,
        "generation": 1,
        "run_id": "PROJ-SWARM-READY-2026-07-19",
        "author_family": "openai",
        "workload_class": "light-text",
        "specialist": "systems-engineer",
        "lane": lane,
        "mode_profile": "project",
        "execution_kind": execution_kind,
        "repo_root": str(repo),
        "pool_root": str(root / "pool"),
        "canonical_role_path": str(role),
        "canonical_role_sha256": file_digest(role),
        "lane_overlay_path": str(overlay),
        "lane_overlay_sha256": file_digest(overlay),
        "executable": executable,
        "executable_sha256": file_digest(Path(os.path.realpath(executable))),
        "lane_args": ["--version"],
        "write_paths": ["."],
        "read_scope": [],
        "depends_on": [],
        "resources": [],
        "scheduler_concurrency": 1,
        "scheduler_capacities": {},
        "scheduler_settled": {},
        "network_scope": [],
        "action_scope": ["trusted:launch"],
        "budgets": {"max_calls": 1},
        "expected_result_path": "result.md",
        "expected_outbox_path": "response.md",
        "reconciliation_echo": {},
        "required_phase_ids": ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"],
        "verification_kinds": ["project_tests", "recipient_contract"],
        "operator_gates": sorted(gate.HELD_CATEGORIES),
        "packet_sha256": digest("packet"),
        "plan_sha256": digest("plan"),
        "verification_contract_sha256": digest("contract"),
        "selected_model_sha256": digest("model"),
        "profile_bundle_sha256": SETTLED_T1P1_BUNDLE_SHA256,
        "active_board_tasks": [],
        "created_at": now - 30,
        "expires_at": now + 300,
        "nonce": digest("nonce"),
    }


def _seal_authority(authority: dict[str, object]) -> dict[str, object]:
    raw = json.dumps(authority, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {
        "schema": "go-live-launch-context/v1",
        "authority": authority,
        "mac_sha256": hmac.new(AUTHORITY_KEY, raw, hashlib.sha256).hexdigest(),
    }


def _run_authority_supervisor(
    context: dict[str, object],
    *,
    extra_env: dict[str, str] | None = None,
):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(context, handle)
        context_path = Path(handle.name)
    read_fd, write_fd = os.pipe()
    authority_fd = 3
    saved_fd = None
    try:
        os.write(write_fd, AUTHORITY_KEY)
        os.close(write_fd)
        if read_fd != authority_fd:
            try:
                saved_fd = os.dup(authority_fd)
            except OSError:
                saved_fd = None
            os.dup2(read_fd, authority_fd)
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LC_ALL": "C",
            "VAULT_ROOT": str(ROOT),
            "BOARD_SUPERVISOR_AUTHORITY_FD": str(read_fd),
        }
        env.update(extra_env or {})

        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
            capture_output=True,
            text=True,
            timeout=40,
            env=env,
            pass_fds=(authority_fd,),
        )
    finally:
        if read_fd != authority_fd:
            if saved_fd is None:
                os.close(authority_fd)
            else:
                os.dup2(saved_fd, authority_fd)
                os.close(saved_fd)
            os.close(read_fd)
        else:
            os.close(read_fd)
        context_path.unlink(missing_ok=True)
    receipt = json.loads(completed.stdout.strip() or completed.stderr.strip())
    return completed, receipt


def _run_unsigned_supervisor(context: dict[str, object]):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(context, handle)
        context_path = Path(handle.name)
    try:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LC_ALL": "C",
                "VAULT_ROOT": str(ROOT),
            },
        )
    finally:
        context_path.unlink(missing_ok=True)
    receipt = json.loads(completed.stdout.strip() or completed.stderr.strip())
    return completed, receipt


class HeldEffectExecutorTests(unittest.TestCase):
    def test_every_category_denies_without_token_before_the_handler_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executor = effects.HeldEffectExecutor(
                store=gate.HeldActionStore(Path(directory)),
                signing_key=SIGNING_KEY,
                now=lambda: 1_100,
                backends=(backends := _backends()),
            )
            for category in sorted(gate.HELD_CATEGORIES):
                with self.subTest(category=category), self.assertRaises(gate.HeldActionDenied):
                    executor.execute(_effect_request(category), token=None)
                backends[category].assert_not_called()

    def test_valid_token_executes_once_and_durable_replay_never_reaches_handler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            request = _effect_request("public-push")
            token = gate.mint_token(
                category=request.category,
                target=request.target,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                issued_at=1_000,
                expires_at=1_300,
                signing_key=SIGNING_KEY,
            )
            first_handler = Mock(return_value={"status": "performed"})
            first_backends = _backends({"public-push": first_handler})
            receipt = effects.HeldEffectExecutor(
                store=gate.HeldActionStore(state),
                signing_key=SIGNING_KEY,
                now=lambda: 1_100,
                backends=first_backends,
            ).execute(request, token=token)
            self.assertEqual(receipt.status, "performed")
            first_handler.assert_called_once_with(request)

            replay_handler = Mock()
            replay_backends = _backends({"public-push": replay_handler})
            with self.assertRaisesRegex(gate.HeldActionDenied, "replay|consumed"):
                effects.HeldEffectExecutor(
                    store=gate.HeldActionStore(state),
                    signing_key=SIGNING_KEY,
                    now=lambda: 1_101,
                    backends=replay_backends,
                ).execute(request, token=token)
            replay_handler.assert_not_called()

    def test_effect_descriptor_tampering_is_denied_before_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = _effect_request("public-push")
            tampered = effects.HeldEffectRequest(
                category=request.category,
                target=request.target,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                effect_name=request.effect_name,
                effect_payload={"fixture": "different-target"},
            )
            handler = Mock()
            executor = effects.HeldEffectExecutor(
                store=gate.HeldActionStore(Path(directory)),
                signing_key=SIGNING_KEY,
                now=lambda: 1_100,
                backends=_backends({"public-push": handler}),
            )
            with self.assertRaisesRegex(ValueError, "exact descriptor"):
                executor.execute(tampered, token=None)
            handler.assert_not_called()

    def test_backend_exception_is_outcome_unknown_and_token_stays_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            request = _effect_request("delete-from-main")
            token = gate.mint_token(
                category=request.category,
                target=request.target,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                issued_at=1_000,
                expires_at=1_300,
                signing_key=SIGNING_KEY,
            )
            failing = Mock(side_effect=RuntimeError("secret backend detail"))
            receipt = effects.HeldEffectExecutor(
                store=gate.HeldActionStore(state),
                signing_key=SIGNING_KEY,
                now=lambda: 1_100,
                backends=_backends({"delete-from-main": failing}),
            ).execute(request, token=token)
            self.assertEqual(receipt.status, "outcome_unknown")
            self.assertTrue(receipt.consumed)
            self.assertNotIn("secret", receipt.result_sha256)

            replay = Mock()
            with self.assertRaisesRegex(gate.HeldActionDenied, "replay|consumed"):
                effects.HeldEffectExecutor(
                    store=gate.HeldActionStore(state),
                    signing_key=SIGNING_KEY,
                    now=lambda: 1_101,
                    backends=_backends({"delete-from-main": replay}),
                ).execute(request, token=token)
            replay.assert_not_called()


class ExecHonestyTests(unittest.TestCase):
    def test_failed_real_spawn_is_blocked_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = _authority_payload(
                Path(directory).resolve(), executable="/usr/bin/false"
            )
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(receipt.get("status"), {"blocked", "denied"})
            self.assertFalse(receipt.get("cli_exec_succeeded", False))

    def test_ambient_mock_flag_cannot_fabricate_cli_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = _authority_payload(
                Path(directory).resolve(), executable="/usr/bin/false"
            )
            completed, receipt = _run_authority_supervisor(
                _seal_authority(authority),
                extra_env={"TRUSTED_LAUNCH_TEST_MODE": "1"},
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(receipt.get("cli_exec_succeeded", False))
            self.assertNotEqual(receipt.get("execution_mode"), "simulated")

    def test_spawn_exception_reflects_retained_blocked_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = _authority_payload(Path(directory).resolve())
            authority["lane_args"] = ["--resume"]
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(receipt.get("status"), "blocked", receipt)
            self.assertEqual(receipt.get("worktree_state"), "retained-blocked")
            self.assertEqual(
                receipt.get("reservation_state"),
                "blocked-awaiting-reconciliation",
            )
            self.assertFalse(receipt.get("cli_exec_succeeded"))


class AuthorityIntegrationTests(unittest.TestCase):
    def test_unsigned_legacy_context_is_denied(self) -> None:
        completed, receipt = _run_unsigned_supervisor(
            {"task_id": "TASK-unsigned-bypass"}
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(receipt.get("status"), "denied")
        self.assertIn("authenticated", receipt.get("reason", ""))

    @skip_in_host_independent_ci(
        "executes the live authenticated supervisor spawn path"
    )
    def test_authenticated_authority_drives_a_real_zero_exit_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = _authority_payload(Path(directory).resolve())
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertEqual(completed.returncode, 0, receipt)
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertTrue(receipt.get("cli_exec_succeeded"), receipt)
            self.assertEqual(receipt.get("execution_mode"), "real")
            self.assertTrue(receipt.get("authority_sha256"))
            self.assertTrue(receipt.get("scheduler_reservation_snapshot_sha256"))

    def test_authority_tamper_is_denied_before_worktree_provision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authority = _authority_payload(root)
            context = _seal_authority(authority)
            authority["specialist"] = "attacker"
            completed, receipt = _run_authority_supervisor(context)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(receipt.get("status"), "denied")
            self.assertIn("authority", receipt.get("reason", "").lower())
            self.assertFalse(Path(authority["pool_root"]).exists())

    def test_authenticated_logical_write_collision_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authority = _authority_payload(root)
            authority["scheduler_concurrency"] = 2
            authority["active_board_tasks"] = [
                {
                    "task_id": "TASK-2026-07-22-0600-active",
                    "write_paths": ["README.md"],
                    "read_paths": [],
                    "depends_on": [],
                    "resources": [],
                    "worktree_root": str(authority["repo_root"]),
                    "metadata_complete": True,
                    "priority": 0,
                }
            ]
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(receipt.get("status"), "denied")
            self.assertIn("scheduler", receipt.get("reason", "").lower())

    def test_lane_authority_cannot_substitute_a_different_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authority = _authority_payload(
                root,
                executable="/usr/bin/true",
                execution_kind="lane",
                lane="kimi",
            )
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(receipt.get("status"), "denied")
            self.assertIn("entrypoint", receipt.get("reason", ""))
            self.assertFalse(Path(authority["pool_root"]).exists())

    def test_lane_authority_cannot_claim_a_held_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = _authority_payload(Path(directory).resolve())
            authority["action_scope"].append("public-push")
            completed, receipt = _run_authority_supervisor(_seal_authority(authority))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(receipt.get("status"), "denied")
            self.assertIn("hold", receipt.get("reason", ""))
            self.assertFalse(Path(authority["pool_root"]).exists())


@unittest.skipUnless(
    sys.platform == "darwin",
    "macOS-only: lane CLI profiles use Seatbelt",
)
class LaneCLISeatbeltTests(unittest.TestCase):
    def test_ordinary_profile_does_not_inherit_lane_or_fork_grants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = seatbelt.compile_profile(
                seatbelt.ProfileSpec(write_paths=(Path(directory).resolve(),)),
                compatibility_verifier=lambda: seatbelt.HostCompatibility(
                    sandbox_exec=seatbelt.CANONICAL_SANDBOX_EXEC,
                    macos_build=next(iter(seatbelt.KNOWN_MACOS_BUILDS)),
                    canary_sha256="a" * 64,
                ),
            )
        for path in seatbelt.LANE_CLI_PATHS.values():
            self.assertNotIn(f'(allow process-exec (literal "{path}"))', profile.text)
            self.assertNotIn(
                f'(allow process-exec (literal "{Path(os.path.realpath(path))}"))',
                profile.text,
            )
        self.assertNotIn("(allow process-fork)", profile.text)

    def test_each_lane_profile_has_only_its_exact_exec_grants(self) -> None:
        for lane, entrypoint in sorted(seatbelt.LANE_CLI_PATHS.items()):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as directory:
                with seatbelt.scoped_lane_launch_profile(lane=lane):
                    profile = seatbelt.compile_profile(
                        seatbelt.ProfileSpec(write_paths=(Path(directory).resolve(),)),
                        compatibility_verifier=lambda: seatbelt.HostCompatibility(
                            sandbox_exec=seatbelt.CANONICAL_SANDBOX_EXEC,
                            macos_build=next(iter(seatbelt.KNOWN_MACOS_BUILDS)),
                            canary_sha256="a" * 64,
                        ),
                    )
                paths = seatbelt.installed_lane_cli_executable_paths(
                    lanes=(lane,), include_offline=False
                )
                for path in paths:
                    self.assertIn(
                        f'(allow process-exec (literal "{Path(os.path.realpath(path))}"))',
                        profile.text,
                    )
                self.assertIn(
                    f'(allow process-exec (literal "{entrypoint}"))', profile.text
                )
                for other_lane, other_entrypoint in seatbelt.LANE_CLI_PATHS.items():
                    if other_lane != lane:
                        self.assertNotIn(
                            f'(allow process-exec (literal "{other_entrypoint}"))',
                            profile.text,
                        )
                self.assertNotIn('(allow process-exec (literal "/usr/bin/git"))', profile.text)
                self.assertNotIn('(allow process-exec (literal "/usr/bin/curl"))', profile.text)
                self.assertEqual(profile.text.count("(allow network-outbound"), 0)
                self.assertNotRegex(profile.text, r"process-exec.*subpath")


if __name__ == "__main__":
    unittest.main()
