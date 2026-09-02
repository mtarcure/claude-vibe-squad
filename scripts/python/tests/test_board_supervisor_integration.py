#!/usr/bin/env python3
"""Integration regressions for the non-model board supervisor launch seam."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import launch_hygiene  # noqa: E402
import tool_surface_attest  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)
from tool_surface_attest import (  # noqa: E402
    AttestationError,
    ReconciliationChain,
    reconcile_result,
)


HASH = hashlib.sha256(b"integration-fixture").hexdigest()
REPO_ROOT = Path(__file__).resolve().parents[3]


class ReconciliationScopeTests(unittest.TestCase):
    def test_recased_sibling_cannot_alias_authorized_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            authorized = root / "Allowed"
            recased_sibling_output = root / "allowed" / "result.md"
            chain = ReconciliationChain(
                task_id="TASK-case-fold-regression",
                attempt_id="d-0123456789abcdef0123456789abcdef",
                generation=1,
                envelope_sha256=HASH,
                launch_attestation_sha256=HASH,
                tool_attestation_sha256=HASH,
                action_log_sha256=HASH,
                artifact_bundle_sha256=HASH,
                model_history_sha256=HASH,
                review_subject_sha256=HASH,
                review_family="anthropic",
                review_state="approved",
                outbox_sha256=HASH,
                output_paths=(str(recased_sibling_output),),
                sandbox_denials=(),
            )

            with self.assertRaisesRegex(AttestationError, "outside-scope output"):
                reconcile_result(
                    chain,
                    expected_task_id=chain.task_id,
                    expected_attempt_id=chain.attempt_id,
                    expected_generation=chain.generation,
                    expected_envelope_sha256=chain.envelope_sha256,
                    authorized_write_scope=(str(authorized),),
                    mandatory_review=True,
                    author_family="openai",
                )


class BoardSupervisorLaunchTests(unittest.TestCase):
    def test_project_close_verifier_runs_on_bridge_before_commit_marker(self) -> None:
        supervisor = (REPO_ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        bridge = (REPO_ROOT / "scripts/python/dispatch_context_builder.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ModeExitVerificationError", supervisor)
        self.assertIn("publish_prepared_worktree_outputs", supervisor)
        function = bridge.split("def publish_prepared_worktree_outputs(", 1)[1].split(
            "\ndef ", 1
        )[0]
        verifier = function.index("_invoke_project_mode_exit_verifier")
        result = function.index("prepared.result_relative")
        envelope = function.index("prepared.outbox_relative")
        self.assertLess(verifier, result)
        self.assertLess(result, envelope)

    def test_unbound_raw_canary_is_not_treated_as_credential_broker(self) -> None:
        with self.assertRaisesRegex(
            AttestationError,
            "runtime authority, CredentialBroker binding, and inode re-audit",
        ):
            tool_surface_attest._trusted_boundary_receipt(
                object(), {"status": "admitted"}
            )

    def test_usage_error_does_not_require_doctor_log_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            bin_directory = Path(temporary_directory) / "bin"
            bin_directory.mkdir()
            shutil.copy2(REPO_ROOT / "bin" / "board-supervisor.sh", bin_directory)
            self.assertFalse((bin_directory / "doctor-log-home.sh").exists())

            completed = subprocess.run(
                [
                    str(bin_directory / "board-supervisor.sh"),
                    "prepare",
                    "request.json",
                    "standard",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 64, completed.stderr)
            self.assertIn("Usage: board-supervisor.sh trusted-launch", completed.stderr)
            self.assertNotIn("doctor-log-home.sh", completed.stderr)

    def test_valid_launch_fails_loudly_without_doctor_log_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            bin_directory = repository / "bin"
            bin_directory.mkdir()
            shutil.copy2(REPO_ROOT / "bin" / "board-supervisor.sh", bin_directory)
            context_file = repository / "context.json"
            context_file.write_text("{}\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(bin_directory / "board-supervisor.sh"),
                    "trusted-launch",
                    str(context_file),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("doctor-log-home.sh", completed.stderr)
            self.assertNotIn("Usage: board-supervisor.sh", completed.stderr)

    def test_retired_prepare_mode_cannot_invoke_host_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repo"
            bin_directory = repository / "bin"
            python_directory = repository / "scripts" / "python"
            bin_directory.mkdir(parents=True)
            python_directory.mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "bin" / "board-supervisor.sh", bin_directory)
            shutil.copy2(REPO_ROOT / "bin" / "doctor-log-home.sh", bin_directory)
            invoked = repository / "host-admission-invoked"
            (python_directory / "host_admission.py").write_text(
                f"from pathlib import Path\nPath({str(invoked)!r}).touch()\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    str(bin_directory / "board-supervisor.sh"),
                    "prepare",
                    "request.json",
                    "standard",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 64)
            self.assertIn("Usage: board-supervisor.sh trusted-launch", completed.stderr)
            self.assertFalse(invoked.exists())

    @skip_in_host_independent_ci(
        "needs a host-canonical executable and the live supervisor launch seam"
    )
    def test_supervisor_launch_compiles_seals_launches_and_attests(self) -> None:
        @dataclass
        class Canary:
            profile_sha256: str
            request_sha256: str
            scope_sha256: str
            allowed_write: bool = True
            denied_write: bool = True
            exact_broker_port: bool = True
            wrong_port_denied: bool = True
            fd3_closed: bool = True

        @dataclass
        class Profile:
            text: str
            sha256: str

        class Prepared:
            def __init__(self, executable: Path) -> None:
                self.profile = Profile(
                    f'(allow process-exec (literal "{executable}"))\n', HASH
                )
                self.canary = Canary(HASH, HASH, HASH)
                self.environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
                self.closed = False

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            role_path = root / "role.md"
            overlay_path = root / "overlay.md"
            request_path = root / "request.json"
            context_path = root / "runtime.json"
            effect_path = root / "result.md"
            executable = Path("/bin/bash")
            role_path.write_text("# Systems engineer\n", encoding="utf-8")
            overlay_path.write_text("# Codex overlay\n", encoding="utf-8")
            request = {
                "task_id": "TASK-integration-fixture",
                "attempt_id": "d-0123456789abcdef0123456789abcdef",
                "generation": 1,
                "task_root": str(root),
                "write_paths": [str(root)],
            }
            request_path.write_text(json.dumps(request), encoding="utf-8")
            claims = {
                "task_id": request["task_id"],
                "attempt_id": request["attempt_id"],
                "generation": request["generation"],
                "run_id": "integration-run",
                "lane": "claude",
                "author_family": "anthropic",
                "workload_class": "standard",
                "packet_sha256": HASH,
                "plan_sha256": HASH,
                "authority_sha256": HASH,
                "verification_contract_sha256": HASH,
                "selected_model_sha256": HASH,
                "read_scope": [],
                "write_scope": [str(root)],
                "network_scope": [],
                "action_scope": ["write-result"],
                "budgets": {"tokens": 1},
                "expected_result_path": str(effect_path),
                "expected_outbox_path": str(root / "response.md"),
                "required_phase_ids": ["S0", "S1"],
                "verification_kinds": ["project_tests"],
                "operator_gates": [],
            }
            context_path.write_text(
                json.dumps(
                    {
                        "schema": "board-supervisor-runtime-context/v1",
                        "canonical_role_path": str(role_path),
                        "lane_overlay_path": str(overlay_path),
                        "specialist": "systems-engineer",
                        "mode_profile": "project",
                        "executable": str(executable),
                        "lane_args": [],
                        "claims": claims,
                        "tool_evidence": {
                            "tool": "write-result",
                            "operation": "produce task result",
                            "effect_path": str(effect_path),
                            "expected_effect_sha256": hashlib.sha256(
                                b"done"
                            ).hexdigest(),
                        },
                        "ttl_seconds": 60,
                    }
                ),
                encoding="utf-8",
            )
            prepared = Prepared(executable)

            def launch_if_canary_passes(canary_runner, command, **_kwargs):
                self.assertIs(canary_runner(), prepared)
                effect_path.write_bytes(b"done")
                prepared.close()
                return subprocess.CompletedProcess(command, 0, "launched", "")

            fake_hygiene = types.ModuleType("launch_hygiene")
            fake_hygiene._load_task_request = lambda _path: request
            fake_hygiene._request_digest = lambda _request: HASH
            fake_hygiene.audit_writable_scopes = lambda _paths: ()
            fake_hygiene.close_writable_scopes = lambda _scopes: None
            fake_hygiene.run_preflight_canary = lambda *_args, **_kwargs: prepared
            fake_hygiene.launch_if_canary_passes = launch_if_canary_passes

            with (
                mock.patch.dict(sys.modules, {"launch_hygiene": fake_hygiene}),
                mock.patch.object(
                    tool_surface_attest,
                    "_trusted_boundary_receipt",
                    return_value={
                        "authority_authenticated": True,
                        "broker_healthy": True,
                        "inode_audit_passed": True,
                    },
                ),
            ):
                result = tool_surface_attest._supervisor_launch(
                    request_path,
                    context_path,
                    "standard",
                    '{"status":"admitted","receipt":"test"}',
                )

            self.assertEqual(result["status"], "launched")
            self.assertEqual(result["task_id"], request["task_id"])
            self.assertRegex(result["envelope_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(result["launch_attestation_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(result["tool_attestation_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(result["reconciliation_binding_sha256"], r"^[0-9a-f]{64}$")

    def test_strict_launch_scrubs_vault_context_before_hygiene_validation(self) -> None:
        source = (REPO_ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        start = source.index(
            '    prepared.environment["PATH"] = DEFAULT_LANE_PATH'
        )
        end = source.index("    def bounded_real_launcher", start)
        environment_setup = textwrap.dedent(source[start:end])
        prepared = types.SimpleNamespace(
            environment={
                "HOME": "/tmp/home",
                "XDG_CONFIG_HOME": "/tmp/config",
                "XDG_CACHE_HOME": "/tmp/cache",
                "TMPDIR": "/tmp/task",
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
                "CHRONO_VAULT_ROOT": "/private/vault",
                "OBSIDIAN_VAULT_ROOT": "/private/vault",
                "CHRONO_VAULT_CONTEXT": "stale",
                "CHRONO_VAULT_BROKER_TOKEN": "secret",
            }
        )
        namespace = {
            "prepared": prepared,
            "trusted_environment": {"CHRONO_VAULT_CONTEXT": '{"aperture":"none"}'},
            "DEFAULT_LANE_PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "VAULT_ROOT_ALIASES": (
                "CHRONO_VAULT_ROOT",
                "OBSIDIAN_VAULT_ROOT",
            ),
            "VAULT_CONTEXT_ENV": "CHRONO_VAULT_CONTEXT",
            "VAULT_BROKER_TOKEN_ENV": "CHRONO_VAULT_BROKER_TOKEN",
        }

        exec(compile(environment_setup, "board-supervisor.sh", "exec"), namespace)

        launch_hygiene._validate_child_environment(prepared.environment)
        self.assertFalse(
            {
                "CHRONO_VAULT_ROOT",
                "OBSIDIAN_VAULT_ROOT",
                "CHRONO_VAULT_CONTEXT",
                "CHRONO_VAULT_BROKER_TOKEN",
            }
            & set(prepared.environment)
        )


class CodexVaultContextConfigTests(unittest.TestCase):
    @staticmethod
    def _prepare_codex_home():
        source = (REPO_ROOT / "bin" / "board-supervisor.sh").read_text(
            encoding="utf-8"
        )
        start = source.index('GUARDED_MCP_PREFIX = "guarded-"')
        end = source.index("\ndef _validated_trusted_host_path", start)
        # The slice starts below board-supervisor.sh's import block, so every
        # name that block provides has to be handed in here. Miss one and the
        # exec'd code raises NameError at call time -- which is how this class
        # sat RED at 6 errors while the suite it belongs to was reported
        # "pre-existing, not mine" for weeks. Import from the real module
        # rather than restating the value, so the two cannot drift.
        from lane_capability_enforcement import RESEARCH_API_KEY_NAMES

        namespace = {
            "json": json,
            "os": os,
            "Path": Path,
            "re": re,
            "RESEARCH_API_KEY_NAMES": RESEARCH_API_KEY_NAMES,
        }
        exec(compile(source[start:end], "board-supervisor.sh", "exec"), namespace)
        return namespace["_prepare_codex_home"]

    @staticmethod
    def _vault_environment(config_text: str) -> dict[str, str]:
        header = re.search(
            r"(?m)^\s*\[\s*mcp_servers\s*\.\s*chrono-vault\s*\.\s*env\s*\]"
            r"\s*(?:#.*)?$",
            config_text,
        )
        if header is None:
            raise AssertionError("chrono-vault env table is missing")
        block = config_text[header.end() :]
        next_header = re.search(r"(?m)^\s*\[\[?", block)
        if next_header is not None:
            block = block[: next_header.start()]
        return {
            key.strip(): json.loads(value.strip())
            for line in block.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
            for key, value in [line.split("=", 1)]
        }

    def test_codex_home_binds_context_without_clobbering_vault_roots(self) -> None:
        prepare = self._prepare_codex_home()
        vault_context = json.dumps(
            {
                "aperture": "focused",
                "attempt_id": "d-0123456789abcdef0123456789abcdef",
                "generation": 1,
                "schema": "chrono-vault-context/v1",
                "task_id": "TASK-codex-context",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        base_prefix = textwrap.dedent(
            """\
            [mcp_servers.chrono-vault]
            command = "/repo/.venv/bin/python"
            args = ["/repo/plugins/chrono-vault/mcp_server.py"]

            [mcp_servers.chrono-vault.env]
            CHRONO_VAULT_ROOT = "/vault"
            OBSIDIAN_VAULT_ROOT = "/vault"
            """
        )

        for existing_context in (None, '{"stale":true}'):
            with self.subTest(existing_context=existing_context):
                base_text = base_prefix
                if existing_context is not None:
                    base_text += (
                        "CHRONO_VAULT_CONTEXT = "
                        + json.dumps(existing_context)
                        + "\n"
                    )
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    base_home = root / "base"
                    spawn_home = root / "spawn"
                    base_home.mkdir()
                    (base_home / "config.toml").write_text(
                        base_text, encoding="utf-8"
                    )

                    prepare(
                        base_home,
                        root / "missing-repo-config.toml",
                        spawn_home,
                        vault_context,
                    )

                    generated = (spawn_home / "config.toml").read_text(
                        encoding="utf-8"
                    )
                    self.assertEqual(
                        self._vault_environment(generated),
                        {
                            "CHRONO_VAULT_ROOT": "/vault",
                            "OBSIDIAN_VAULT_ROOT": "/vault",
                            "CHRONO_VAULT_CONTEXT": vault_context,
                        },
                    )
                    self.assertEqual(generated.count("CHRONO_VAULT_CONTEXT ="), 1)

    def test_codex_vault_header_formatting_cannot_drop_context(self) -> None:
        prepare = self._prepare_codex_home()
        vault_context = '{"task_id":"TASK-formatted-header"}'
        variants = (
            (
                "[mcp_servers.chrono-vault]  # live",
                "[mcp_servers.chrono-vault.env]  # live environment",
            ),
            (
                "[  mcp_servers . chrono-vault  ]",
                "[ mcp_servers . chrono-vault . env ]",
            ),
        )

        for server_header, env_header in variants:
            with self.subTest(server_header=server_header, env_header=env_header):
                base_text = textwrap.dedent(
                    f"""\
                    {server_header}
                    command = "/repo/.venv/bin/python"

                    {env_header}
                    CHRONO_VAULT_ROOT = "/vault"
                    """
                )
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    base_home = root / "base"
                    spawn_home = root / "spawn"
                    base_home.mkdir()
                    (base_home / "config.toml").write_text(
                        base_text, encoding="utf-8"
                    )

                    prepare(
                        base_home,
                        root / "missing-repo-config.toml",
                        spawn_home,
                        vault_context,
                    )

                    generated = (spawn_home / "config.toml").read_text(
                        encoding="utf-8"
                    )
                    self.assertEqual(
                        self._vault_environment(generated),
                        {
                            "CHRONO_VAULT_ROOT": "/vault",
                            "CHRONO_VAULT_CONTEXT": vault_context,
                        },
                    )

    def test_codex_vault_array_of_tables_is_refused_loudly(self) -> None:
        prepare = self._prepare_codex_home()
        base_text = textwrap.dedent(
            """\
            [[mcp_servers.chrono-vault]]
            command = "/repo/.venv/bin/python"
            """
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_home = root / "base"
            spawn_home = root / "spawn"
            base_home.mkdir()
            (base_home / "config.toml").write_text(base_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "array-of-tables"):
                prepare(
                    base_home,
                    root / "missing-repo-config.toml",
                    spawn_home,
                    '{"task_id":"TASK-array-table"}',
                )
            self.assertFalse(spawn_home.exists())

    def test_codex_home_without_chrono_vault_is_byte_for_byte_unchanged(
        self,
    ) -> None:
        prepare = self._prepare_codex_home()
        base_text = textwrap.dedent(
            """\
            model = "gpt-5.6-sol"

            [mcp_servers.sequential-thinking]
            command = "/usr/local/bin/sequential-thinking"
            """
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_home = root / "base"
            spawn_home = root / "spawn"
            base_home.mkdir()
            (base_home / "config.toml").write_text(base_text, encoding="utf-8")

            prepare(
                base_home,
                root / "missing-repo-config.toml",
                spawn_home,
                '{"task_id":"TASK-must-not-appear"}',
            )

            generated = (spawn_home / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(generated, base_text)
            self.assertNotIn("CHRONO_VAULT_CONTEXT", generated)


class BlockReasonClassificationTests(unittest.TestCase):
    """`failure_class` is the only typed signal a blocked dispatch gives an operator.

    It is derived by substring match, and several reasons append the offending
    file list -- so the evidence can outvote the diagnosis. A real integration
    failure whose file list contained `memory-curator.md` was reported as
    `memory_proof`, which sent the follow-up investigation at the wrong layer.
    """

    @staticmethod
    def _classifier():
        source = (REPO_ROOT / "bin" / "board-supervisor.sh").read_text(encoding="utf-8")
        marker = "def _classify_block_reason(reason):"
        start = source.index(marker)
        end = source.index("\ndef ", start + len(marker))
        namespace: dict[str, object] = {}
        exec(compile(source[start:end], "board-supervisor.sh", "exec"), namespace)
        return namespace["_classify_block_reason"]

    def test_the_offending_file_list_cannot_outvote_the_diagnosis(self) -> None:
        classify = self._classifier()
        reason = (
            "fresh lane code integration failed: worker left uncommitted in-scope "
            "code changes: model-lanes/claude/.claude/agents/memory-curator.md, "
            "model-lanes/claude/.claude/agents/systems-engineer.md"
        )

        self.assertEqual(classify(reason), "integration")

    def test_timeout_words_in_evidence_cannot_outvote_four_diagnoses(self) -> None:
        classify = self._classifier()
        counterexamples = {
            "fresh lane code integration failed: shared/timeouts.md, bin/x.sh": (
                "integration"
            ),
            "worktree isolation failed: _state/timeout-notes.md": "worktree",
            "memory proof failed: shared/vault-timeout.md": "memory_proof",
            "capability denied: tools/deadline.py": "capability",
        }

        for reason, failure_class in counterexamples.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), failure_class)

    def test_generic_launch_tail_distinguishes_timeout_from_timeout_word(self) -> None:
        classify = self._classifier()
        expected = {
            "trusted launch failed: Command '['codex']' timed out after 900 seconds": (
                "timeout"
            ),
            "trusted launch failed: executable returned exit 75": "launch",
            "trusted launch failed: timeout policy file could not be loaded": "launch",
            "fresh lane process cleanup failed: boom": "other",
        }

        for reason, failure_class in expected.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), failure_class)

    def test_timeout_phrase_in_report_filename_is_not_a_timeout_signal(self) -> None:
        classify = self._classifier()

        self.assertEqual(
            classify("trusted launch failed: malformed report: analysis timed out.md"),
            "launch",
        )

    def test_operation_timeout_is_a_timeout_signal(self) -> None:
        classify = self._classifier()

        self.assertEqual(
            classify("trusted launch failed: operation timeout"),
            "timeout",
        )

    def test_a_report_filename_is_not_a_timeout_diagnosis(self) -> None:
        """The filename guard must also cover the *leading* clause.

        The guard added for the generic-launch tail is only consulted when a
        launch clause wraps the evidence. A reason that is itself a filename
        never reaches it, so `analysis timed out.md` was diagnosed `timeout` --
        a report name, not a timeout event. With no diagnostic clause at all
        the only honest class is `other`; wrapped in a launch clause the
        diagnosis stays `launch`.
        """
        classify = self._classifier()
        expected = {
            "analysis timed out.md": "other",
            "trusted launch failed: analysis timed out.md": "launch",
            # the whole family, not just the one reported instance
            "timeouts.md": "other",
            "timeout-notes.md": "other",
            "deadline.json": "other",
            "report timed out.markdown": "other",
            "fresh lane timeout: boom": "timeout",
        }

        for reason, failure_class in expected.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), failure_class)

    def test_the_filename_guard_does_not_disarm_a_real_timeout_diagnosis(self) -> None:
        """Narrowing the leading clause must not cost the timeout class itself."""
        classify = self._classifier()
        expected = {
            "fresh lane timeout: boom": "timeout",
            "timeout": "timeout",
            "deadline exceeded: boom": "timeout",
            "fresh lane cli timed out after 2700s": "timeout",
            "worktree isolation failed: _state/timeout-notes.md": "worktree",
        }

        for reason, failure_class in expected.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), failure_class)

    def test_every_supervisor_block_reason_keeps_its_intended_class(self) -> None:
        classify = self._classifier()
        expected = {
            "role capability config materialization failed: boom": "capability",
            "linked worktree commit scope derivation failed: boom": "worktree",
            "task request validation failed: repository branch is not v2": (
                "request_validation"
            ),
            'Stage-1 canary failed: {"canary": "denied"}': "launch_canary",
            "trusted launch failed: Command '['codex']' timed out after 900 seconds": (
                "timeout"
            ),
            "trusted launch failed: boom": "launch",
            "fresh lane timeout: boom": "timeout",
            "memory proof failed: boom": "memory_proof",
            "response envelope missing: boom": "missing_envelope",
            "fresh lane process cleanup failed: boom": "other",
            "fresh lane code integration failed: boom": "integration",
            "mode-exit verification failed: retry": "verification",
        }
        for reason, failure_class in expected.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), failure_class)

    def test_native_cli_failures_use_exact_transport_classes(self) -> None:
        source = (REPO_ROOT / "bin" / "board-supervisor.sh").read_text(encoding="utf-8")
        launch = source.split("completed = launch_task(", 1)[1].split(
            "observed_memory_ids = set()", 1
        )[0]
        cleanup = launch.index("except ProcessTruthError")
        timeout = launch.index("except subprocess.TimeoutExpired")
        self.assertLess(cleanup, timeout)
        self.assertIn("hold_for_operator_stop", launch[cleanup:timeout])
        self.assertNotIn("block_after_provision", launch[cleanup:timeout])
        self.assertNotIn("cli_timeout", launch[cleanup:timeout])
        self.assertIn("except subprocess.TimeoutExpired", launch)
        self.assertIn('failure_class="cli_timeout"', launch)
        self.assertEqual(source.count("trap_cli_missing(exc)"), 4)
        self.assertIn('failure_class="cli_missing"', launch)
        self.assertIn('failure_class="cli_nonzero"', launch)
        marker = "def trap_cli_missing(exc):"
        helper = marker + source.split(marker, 1)[1].split("\n\n", 1)[0]
        denied = []
        namespace = {"deny": lambda *args: denied.append(args)}
        exec(compile(helper, "board-supervisor.sh", "exec"), namespace)
        for error in (FileNotFoundError("x"), PermissionError("x"), OSError("x")):
            namespace["trap_cli_missing"](error)
        self.assertEqual([args[1] for args in denied], ["cli_missing", "cli_missing"])


if __name__ == "__main__":
    unittest.main()
