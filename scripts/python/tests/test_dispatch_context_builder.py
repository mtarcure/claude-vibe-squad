from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
from verification_contract import derive_verification_contract  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


TASK = (
    ROOT
    / "departments"
    / "coding"
    / "inbox"
    / "TASK-2026-07-23-0905-v2-cutover-build.md"
)
EXPECTED_AUTHORITY_FIELDS = {
    "schema",
    "task_id",
    "attempt_id",
    "generation",
    "run_id",
    "author_family",
    "workload_class",
    "specialist",
    "lane",
    "mode_profile",
    "execution_kind",
    "repo_root",
    "pool_root",
    "canonical_role_path",
    "canonical_role_sha256",
    "lane_overlay_path",
    "lane_overlay_sha256",
    "executable",
    "executable_sha256",
    "lane_args",
    "write_paths",
    "read_scope",
    "depends_on",
    "resources",
    "scheduler_concurrency",
    "scheduler_capacities",
    "scheduler_settled",
    "network_scope",
    "action_scope",
    "budgets",
    "expected_result_path",
    "expected_outbox_path",
    "evidence_outputs",
    "reconciliation_echo",
    "required_phase_ids",
    "verification_kinds",
    "operator_gates",
    "packet_sha256",
    "plan_sha256",
    "verification_contract_sha256",
    "selected_model_sha256",
    "profile_bundle_sha256",
    "capability_surface_sha256",
    "auth_class",
    "lane_policy_row_sha256",
    "memory_context",
    "active_board_tasks",
    "created_at",
    "expires_at",
    "nonce",
}


class DispatchContextBuilderTests(unittest.TestCase):
    def test_lane_network_scopes_report_the_truthful_auth_class(self) -> None:
        self.assertEqual(
            dcb.LANE_NETWORK_SCOPE,
            {
                "codex": "openai-subscription",
                "claude": "anthropic-subscription",
                "gemini": "gemini-api-key",
                "kimi": "moonshot-subscription",
            },
        )

    def test_every_lane_launches_its_selected_profile_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for lane in ("codex", "claude", "gemini", "kimi"):
                with self.subTest(lane=lane):
                    root, _packet = self._fake_repo_for_lane(
                        Path(directory), lane=lane, model=lane
                    )
                    args = dcb.trusted_lane_args_for(
                        root, lane=lane, specialist=f"{lane}-canary"
                    )
                    self.assertEqual(
                        args[args.index("--model") + 1], f"{lane}-test-model"
                    )

    def test_lane_inventory_uses_approved_paths_profiles_and_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            approved = {
                lane: base / "approved" / lane
                for lane in ("claude", "codex", "gemini", "kimi")
            }
            calls = []

            def fake_version(path: Path) -> str:
                calls.append(path)
                return f"{path.name} 9.9"

            with (
                mock.patch.dict(os.environ, {"PATH": str(base / "wrong-path")}),
                mock.patch.dict(dcb.LANE_CLI_PATHS, approved, clear=True),
            ):
                rows = dcb.lane_runtime_inventory(ROOT, version_reader=fake_version)

        by_lane = {row["lane"]: row for row in rows}
        self.assertEqual(calls, list(approved.values()))
        self.assertEqual(
            {lane: row["auth_class"] for lane, row in by_lane.items()},
            {
                "claude": "subscription",
                "codex": "subscription",
                "gemini": "gemini-api-key",
                "kimi": "managed-login",
            },
        )
        self.assertEqual(
            {
                lane: {item["profile_id"] for item in row["selections"]}
                for lane, row in by_lane.items()
            },
            {
                "claude": {
                    "claude.fable.max",
                    "claude.fable.xhigh",
                    "claude.opus5.high",
                    "claude.opus5.max",
                    "claude.opus5.xhigh",
                },
                "codex": {"codex.sol.high", "codex.sol.ultra"},
                "gemini": {"gemini.flash.default", "gemini.pro.deep"},
                "kimi": {
                    "kimi.k2.7.bulk",
                    "kimi.k3.256k",
                    "kimi.k3.high",
                    "kimi.k3.max",
                },
            },
        )
        for row in rows:
            self.assertEqual(row["literal_executable"], str(approved[row["lane"]]))
            self.assertTrue(row["version"].endswith("9.9"))
            for selection in row["selections"]:
                self.assertEqual(
                    selection["registry_model"], selection["effective_model"]
                )
        self.assertNotIn("google-subscription", json.dumps(rows))

    def test_lane_version_probe_is_exact_and_secret_free(self) -> None:
        completed = mock.Mock(returncode=0, stdout="approved 1.2\nignored\n")
        with (
            mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "secret-sentinel",
                    "GEMINI_API_KEY": "secret-sentinel",
                },
            ),
            mock.patch.object(dcb.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(dcb._lane_version(Path("/approved/cli")), "approved 1.2")
        self.assertEqual(run.call_args.args[0], ("/approved/cli", "--version"))
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertNotIn("GEMINI_API_KEY", run.call_args.kwargs["env"])

    def test_doctor_consumes_inventory_instead_of_path_lookup(self) -> None:
        doctor = (ROOT / "bin/doctor.sh").read_text(encoding="utf-8")
        cli_block = doctor.split("# --- 1. CLI presence + login ---", 1)[1].split(
            "# --- 2. MCP reachability", 1
        )[0]
        self.assertIn("lane-inventory", cli_block)
        self.assertNotIn('command -v "$cli"', cli_block)
        self.assertNotIn('"$cli" --version', cli_block)

    def test_lane_inventory_command_uses_the_hermetic_probe(self) -> None:
        with (
            mock.patch.object(dcb, "_lane_version", return_value="fake 1.0"),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(dcb.main(["lane-inventory", "--repo-root", str(ROOT)]), 0)
        self.assertEqual(output.call_count, 4)
        self.assertTrue(all("\t" in call.args[0] for call in output.call_args_list))

    def _fake_repo_for_lane(
        self,
        base: Path,
        *,
        lane: str,
        model: str,
        specialist: str | None = None,
    ) -> tuple[Path, Path]:
        root = base / lane
        specialist = specialist or f"{lane}-canary"
        namespace = "coding"
        header = (
            (ROOT / "shared" / "specialist-runtime-map.tsv")
            .read_text(encoding="utf-8")
            .splitlines()[0]
            .split("\t")
        )
        row = {field: "none" for field in header}
        row.update(
            {
                "specialist": specialist,
                "source_namespace": namespace,
                "capability_class": "implementation",
                "safety_tags": "[]",
                "primary_lane": lane,
                "primary_profile": f"{lane}-default",
            }
        )
        runtime_map = root / "shared" / "specialist-runtime-map.tsv"
        runtime_map.parent.mkdir(parents=True)
        runtime_map.write_text(
            "\t".join(header) + "\n" + "\t".join(row[field] for field in header) + "\n",
            encoding="utf-8",
        )
        capability_source = (
            root / "model-lanes" / "specialist-lane-capabilities.v1.json"
        )
        capability_source.parent.mkdir(parents=True)
        capability_source.write_text(
            json.dumps(
                {
                    "schema": "specialist-lane-capabilities/v1",
                    "version": 1,
                    "servers": [],
                    "entries": [
                        {
                            "specialist": specialist,
                            "lane": "gpt-codex" if lane == "codex" else lane,
                            "coverage": "full",
                            "limitations": [],
                            "skills": [],
                            "tools": [],
                            "mcps": [],
                        }
                    ],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        lane_capabilities = root / "model-lanes" / "lane-capabilities.tsv"
        source_lines = (
            (ROOT / "model-lanes" / "lane-capabilities.tsv")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        source_lane = "gpt-codex" if lane == "codex" else lane
        lane_capabilities.write_text(
            "\n".join(
                (
                    source_lines[0],
                    next(
                        line
                        for line in source_lines[1:]
                        if line.split("\t", 1)[0] == source_lane
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )
        profiles = root / "shared" / "registries" / "profiles.tsv"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            "profile_id\tlane\tmodel_id\teffort\tflags\tusage\n"
            f"{lane}-default\t{lane}\t{lane}-test-model\thigh\tnone\tprimary\n",
            encoding="utf-8",
        )
        role = root / "departments" / namespace / "specialists" / f"{specialist}.md"
        role.parent.mkdir(parents=True)
        role.write_text(f"# {specialist}\n", encoding="utf-8")
        adapter = {
            "codex": (
                root
                / "model-lanes"
                / "gpt-codex"
                / ".codex"
                / "agents"
                / f"{specialist}.toml"
            ),
            "claude": (
                root
                / "model-lanes"
                / "claude"
                / ".claude"
                / "agents"
                / f"{specialist}.md"
            ),
            "gemini": (
                root
                / "model-lanes"
                / "gemini"
                / ".gemini"
                / "agents"
                / f"{specialist}.md"
            ),
            "kimi": (
                root
                / "model-lanes"
                / "kimi"
                / ".kimi"
                / "agents"
                / f"{specialist}.yaml"
            ),
        }[lane]
        adapter.parent.mkdir(parents=True)
        adapter.write_text(f"name: {specialist}\n", encoding="utf-8")
        task_id = f"TASK-2026-07-23-998{len(lane)}-{lane}"
        contract = derive_verification_contract(
            {
                "task_id": task_id,
                "run_id": "RUN-TEST",
                "mode": "project",
                "result_type": "normal",
                "to_model": model,
                "dispatch_kind": "single",
                "capability": None,
                "expected_gates": [],
            }
        )
        contract_text = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        contract_hash = hashlib.sha256(contract_text.encode("ascii")).hexdigest()
        packet = root / "departments" / namespace / "inbox" / f"{task_id}.md"
        packet.parent.mkdir(parents=True)
        packet.write_text(
            "---\n"
            f"id: {task_id}\n"
            f"to_model: {model}\n"
            f"specialist: {specialist}\n"
            f"source_namespace: {namespace}\n"
            "mode: project\n"
            "run_id: RUN-TEST\n"
            "write_scope: [_state/canary/]\n"
            "return_artifact: _state/canary/result.md\n"
            f"verification_contract: {contract_text}\n"
            f"verification_contract_sha256: {contract_hash}\n"
            "---\n\n"
            "Write the result.\n",
            encoding="utf-8",
        )
        return root, packet

    def test_ordinary_board_context_carries_attempt_generation_fence(self) -> None:
        attempt_id = "d-" + "9" * 32
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory), lane="codex", model="gpt-codex"
            )
            with mock.patch.dict(dcb.LANE_CLI_PATHS, {"codex": Path("/bin/sh")}):
                context = dcb.build_context(
                    root,
                    packet,
                    attempt_id=attempt_id,
                    generation=2,
                    now=1_784_800_000,
                    nonce="8" * 64,
                )
            authority = context["authority"]
            self.assertEqual(
                {
                    key: authority[key]
                    for key in ("auth_class", "lane_policy_row_sha256")
                },
                dcb.lane_policy_evidence_for(root, "codex"),
            )
            entry = dcb.scs.load_source(root)[0][("codex-canary", "gpt-codex")]
            self.assertEqual(
                authority["capability_surface_sha256"],
                dcb.scs.role_surface_sha256(entry),
            )
            worktree = Path(directory) / "worktree"
            artifact = worktree / authority["expected_result_path"]
            artifact.parent.mkdir(parents=True)
            artifact.write_text("result\n", encoding="utf-8")
            envelope = worktree / authority["expected_outbox_path"]
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\nstatus: complete\n---\n\nfinished\n", encoding="utf-8"
            )
            normalized = dcb.prepare_worktree_outputs(
                root, worktree, authority
            ).envelope_bytes.decode("utf-8")

        self.assertEqual(
            context["authority"]["reconciliation_echo"],
            {
                "delivery_attempt_id": attempt_id,
                "delivery_generation": "2",
            },
        )
        self.assertEqual(normalized.count(f"delivery_attempt_id: {attempt_id}\n"), 1)
        self.assertEqual(normalized.count("delivery_generation: 2\n"), 1)
        self.assertNotIn("delivery_worker_id:", normalized)

    def test_lane_policy_evidence_is_exact_and_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _packet = self._fake_repo_for_lane(
                Path(directory), lane="codex", model="gpt-codex"
            )
            policy = root / "model-lanes" / "lane-capabilities.tsv"
            first = dcb.lane_policy_evidence_for(root, "codex")
            policy.write_text(
                policy.read_text(encoding="utf-8").replace(
                    "\t1\n",
                    "\t2\n",
                ),
                encoding="utf-8",
            )
            second = dcb.lane_policy_evidence_for(root, "codex")
            self.assertNotEqual(
                first["lane_policy_row_sha256"], second["lane_policy_row_sha256"]
            )
            policy.write_text(
                policy.read_text(encoding="utf-8").replace(
                    "subscription-drop-provider-keys",
                    "managed-login-drop-provider-keys",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(dcb.DispatchContextError, "auth policy"):
                dcb.lane_policy_evidence_for(root, "codex")

    def test_canary_cleanup_accepts_the_reconciled_archive_packet(self) -> None:
        import registry_reconciler as rr

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = "TASK-2026-08-08-0001-board-inventory-canary"
            packet = root / "departments/coding/archive" / f"{task}.md"
            packet.parent.mkdir(parents=True)
            packet.write_text(
                "---\nboard_canary_autoclean: true\n---\n", encoding="utf-8"
            )
            attempt = "d-" + "a" * 32
            authority = {
                "task_id": task,
                "attempt_id": attempt,
                "generation": 1,
                "write_paths": ["_state/board-canary-test/"],
                "expected_result_path": "_state/board-canary-test/result.md",
                "read_scope": [f"departments/coding/inbox/{task}.md"],
                "packet_sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
            }
            context = root / "_state/board-dispatch/canary.context.json"
            context.parent.mkdir(parents=True)
            context.write_text(json.dumps({"authority": authority}), encoding="utf-8")
            malformed_registry = {
                task: {
                    "delivery_attempt_id": attempt,
                    "delivery_generation": [],
                    "status": "complete",
                }
            }
            in_progress_registry = {
                task: {
                    "delivery_attempt_id": attempt,
                    "delivery_generation": 1,
                    "status": "in-flight",
                }
            }
            failed_registry = {
                task: {
                    "delivery_attempt_id": attempt,
                    "delivery_generation": 1,
                    "status": "complete",
                }
            }
            committed_registry = {
                task: {
                    "delivery_attempt_id": attempt,
                    "delivery_generation": 1,
                    "status": "complete",
                }
            }
            writes = []

            def write_registry(*args):
                self.assertTrue(packet.exists())
                writes.append(args)
                if len(writes) == 1:
                    raise OSError("forced registry write failure")

            lock = mock.MagicMock()
            with (
                mock.patch.object(
                    rr, "REGISTRY_PATH", root / "_state/active-tasks.json"
                ),
                mock.patch.object(rr, "locked_registry", return_value=lock),
                mock.patch.object(
                    rr,
                    "load_registry",
                    side_effect=[
                        malformed_registry,
                        in_progress_registry,
                        failed_registry,
                        committed_registry,
                    ],
                ),
                mock.patch.object(rr, "atomic_write", side_effect=write_registry),
            ):
                with self.assertRaisesRegex(
                    dcb.DispatchContextError, "identity changed"
                ):
                    dcb.cleanup_canary(repo_root=root, context_file=context)
                self.assertTrue(packet.exists())
                with self.assertRaisesRegex(dcb.DispatchContextError, "not terminal"):
                    dcb.cleanup_canary(repo_root=root, context_file=context)
                self.assertTrue(packet.exists())
                with self.assertRaisesRegex(OSError, "forced registry write failure"):
                    dcb.cleanup_canary(repo_root=root, context_file=context)
                self.assertTrue(packet.exists())
                receipt = dcb.cleanup_canary(repo_root=root, context_file=context)
            self.assertEqual(receipt["status"], "cleaned")
            self.assertFalse(packet.exists())
            self.assertNotIn(task, committed_registry)
            self.assertEqual(len(writes), 2)

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_real_packet_builds_exact_trusted_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            context = dcb.build_context(
                root,
                packet,
                attempt_id="d-" + "1" * 32,
                generation=1,
                now=1_784_800_000,
                nonce="2" * 64,
            )

            self.assertEqual(context["schema"], "go-live-trusted-context/v1")
            self.assertEqual(set(context), {"schema", "authority", "task_prompt"})
            authority = context["authority"]
            self.assertEqual(authority["schema"], "go-live-authority/v1")
            self.assertEqual(authority["lane"], "codex")
            self.assertEqual(authority["attempt_id"], "d-" + "1" * 32)
            self.assertEqual(authority["generation"], 1)
            self.assertEqual(
                authority["expected_outbox_path"],
                f"departments/coding/outbox/{packet.stem}-response.md",
            )
            self.assertEqual(
                authority["expected_result_path"],
                "_state/canary/result.md",
            )
            self.assertEqual(
                tuple(authority["lane_args"]),
                dcb.trusted_lane_args_for(
                    root,
                    lane="codex",
                    specialist="codex-canary",
                ),
            )
            self.assertEqual(
                authority["packet_sha256"],
                hashlib.sha256(packet.read_bytes()).hexdigest(),
            )
            self.assertIn(str(packet.relative_to(root)), authority["read_scope"])
            self.assertIn(packet.stem, context["task_prompt"])

    def test_exact_authority_context_builds_for_all_four_lanes(self) -> None:
        models = {
            "codex": "gpt-codex",
            "claude": "claude",
            "gemini": "gemini",
            "kimi": "kimi",
        }
        with tempfile.TemporaryDirectory() as directory:
            for lane, model in models.items():
                with self.subTest(lane=lane):
                    root, packet = self._fake_repo_for_lane(
                        Path(directory),
                        lane=lane,
                        model=model,
                    )
                    with mock.patch.dict(
                        dcb.LANE_CLI_PATHS, {lane: Path("/bin/sh")}, clear=True
                    ):
                        context = dcb.build_context(
                            root,
                            packet,
                            attempt_id="d-" + "3" * 32,
                            generation=2,
                            now=1_784_800_000,
                            nonce="4" * 64,
                        )
                    authority = context["authority"]
                    self.assertEqual(authority["lane"], lane)
                    self.assertEqual(
                        {
                            key: authority[key]
                            for key in ("auth_class", "lane_policy_row_sha256")
                        },
                        dcb.lane_policy_evidence_for(root, lane),
                    )
                    self.assertEqual(
                        tuple(authority["lane_args"]),
                        dcb.trusted_lane_args_for(
                            root,
                            lane=lane,
                            specialist=f"{lane}-canary",
                        ),
                    )
                    self.assertIn("--model", authority["lane_args"])
                    self.assertIn(f"{lane}-test-model", authority["lane_args"])
                    self.assertEqual(authority["generation"], 2)
                    self.assertEqual(
                        authority["budgets"]["timeout_seconds"],
                        2700,  # safety backstop, not a short deadline (all lanes)
                    )
                    self.assertEqual(set(authority), EXPECTED_AUTHORITY_FIELDS)
                    self.assertEqual(
                        authority["profile_bundle_sha256"],
                        dcb.SETTLED_T1P1_BUNDLE_SHA256,
                    )

    def test_memory_aperture_defaults_to_default_and_focused_requires_exact_target(
        self,
    ) -> None:
        # Changed 2026-08-17 (memory-loop spec §4): a packet with no
        # `memory_aperture` used to resolve to `cold`, which is why 2,665 of
        # 2,669 measured dispatches ran memory-blind. The equality below is
        # exact on purpose -- it must fail if the default is put back to
        # `cold`, and it must fail on any other aperture too, so do not
        # relax it to "is a member of MEMORY_APERTURES".
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory), lane="codex", model="gpt-codex"
            )
            with mock.patch.dict(
                dcb.LANE_CLI_PATHS, {"codex": Path("/bin/sh")}, clear=True
            ):
                omitted = dcb.build_context(
                    root,
                    packet,
                    attempt_id="d-" + "5" * 32,
                    generation=1,
                    now=1_784_800_000,
                    nonce="6" * 64,
                )
            self.assertEqual(
                omitted["authority"]["memory_context"]["aperture"], "default"
            )
            self.assertIsNone(omitted["authority"]["memory_context"]["focus"])
            # The prompt has to agree with the policy the broker enforces.
            # `memory.default.v1` permits recall, so a launch prompt telling
            # the worker otherwise would switch memory back off in the only
            # place that runs.
            self.assertIn("Recall prior context ONCE", omitted["task_prompt"])
            self.assertNotIn(
                "Do not call recall or get_note", omitted["task_prompt"]
            )

            original = packet.read_text(encoding="utf-8")
            packet.write_text(
                original.replace(
                    "\n---\n\nWrite the result.",
                    "\nmemory_aperture: focused\n---\n\nWrite the result.",
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                dcb.LANE_CLI_PATHS, {"codex": Path("/bin/sh")}, clear=True
            ), self.assertRaisesRegex(
                dcb.DispatchContextError, "exact memory_focus"
            ):
                dcb.build_context(
                    root,
                    packet,
                    attempt_id="d-" + "5" * 32,
                    generation=1,
                    now=1_784_800_000,
                    nonce="6" * 64,
                )

            packet.write_text(
                packet.read_text(encoding="utf-8").replace(
                    "memory_aperture: focused\n",
                    "memory_aperture: focused\nmemory_focus: exact-project\n",
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                dcb.LANE_CLI_PATHS, {"codex": Path("/bin/sh")}, clear=True
            ):
                focused = dcb.build_context(
                    root,
                    packet,
                    attempt_id="d-" + "5" * 32,
                    generation=1,
                    now=1_784_800_000,
                    nonce="6" * 64,
                )
            self.assertEqual(
                focused["authority"]["memory_context"]["focus"],
                "exact-project",
            )
            self.assertIn("Recall prior context ONCE", focused["task_prompt"])

    def test_invalid_attempt_and_generation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.build_context(
                    root,
                    packet,
                    attempt_id="fresh-unregistered-attempt",
                    generation=1,
                )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.build_context(
                    root,
                    packet,
                    attempt_id="d-" + "1" * 32,
                    generation=0,
                )

    def test_contract_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _root, packet = self._fake_repo_for_lane(
                Path(directory),
                lane="codex",
                model="gpt-codex",
            )
            fields, _body = dcb.parse_task_packet(packet)
            fields["verification_contract_sha256"] = "f" * 64
            with self.assertRaises(dcb.DispatchContextError):
                dcb.validate_verification_contract(fields)

    def test_advisory_contract_accepts_empty_phase_array(self) -> None:
        contract = derive_verification_contract(
            {
                "task_id": "TASK-2026-07-24-9997-advisory-context",
                "run_id": "ADV-TEST",
                "mode": "advisory",
                "result_type": "normal",
                "to_model": "gpt-codex",
                "dispatch_kind": "single",
                "capability": None,
                "expected_gates": [],
            }
        )
        contract_text = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        fields = {
            "id": contract["task_id"],
            "verification_contract": contract_text,
            "verification_contract_sha256": hashlib.sha256(
                contract_text.encode("ascii")
            ).hexdigest(),
        }

        self.assertEqual(dcb.validate_verification_contract(fields), contract)

    def test_scope_parser_rejects_traversal_and_absolute_paths(self) -> None:
        for raw in ("[../../outside]", '["/absolute/path"]', "[.]"):
            with self.subTest(raw=raw):
                with self.assertRaises(dcb.DispatchContextError):
                    dcb.parse_scope(raw, field="write_scope")

    def test_ordinary_packet_can_declare_evidence_outputs(self) -> None:
        """Ordinary evidence is the majority case, not a swarm-only sidecar.

        Selecting only `swarm_member_result` left every ordinary PoC, harness,
        and log unprotected: TASK-2026-08-11-0180's evidence bundle was never
        promoted, its worktree is pruned, and its declared bundle hash is now
        permanently unverifiable. A packet declares exact files; nothing here
        scans a worktree or infers evidence.
        """

        poc = "_state/v4-audit/example/poc.py"
        log = "_state/v4-audit/example/repro.log"
        self.assertEqual(
            dcb.packet_evidence_outputs(
                {"evidence_outputs": f"[{poc}, {log}]"},
                ("_state/v4-audit/example/",),
            ),
            (
                {"path": poc, "role": "declared-evidence", "declared_by": "evidence_outputs"},
                {"path": log, "role": "declared-evidence", "declared_by": "evidence_outputs"},
            ),
        )
        # A swarm member may declare both its sidecar and ordinary evidence.
        sidecar = "_state/swarm/TASK-example/claude/member-result.json"
        self.assertEqual(
            [
                output["declared_by"]
                for output in dcb.packet_evidence_outputs(
                    {
                        "dispatch_kind": "swarm",
                        "swarm_role": "member",
                        "swarm_member_result": sidecar,
                        "evidence_outputs": f"[{poc}]",
                    },
                    ("_state/swarm/TASK-example/claude/", "_state/v4-audit/example/"),
                )
            ],
            ["swarm_member_result", "evidence_outputs"],
        )
        for raw, scope, expected in (
            (f"[{poc}]", ("_state/other/",), "outside packet write_scope"),
            (f"[{poc}, {poc}]", ("_state/v4-audit/example/",), "duplicate"),
            ("[_state/v4-audit/example/]", ("_state/v4-audit/example/",), "exact files"),
            (f"[../{poc}]", ("_state/v4-audit/example/",), "evidence_outputs"),
            (f"{poc}", ("_state/v4-audit/example/",), "inline list"),
        ):
            with self.subTest(evidence_outputs=raw):
                with self.assertRaisesRegex(dcb.DispatchContextError, expected):
                    dcb.packet_evidence_outputs({"evidence_outputs": raw}, scope)
        over_bound = ", ".join(
            f"_state/v4-audit/example/poc{index}.py"
            for index in range(dcb.MAXIMUM_EVIDENCE_OUTPUTS + 1)
        )
        with self.assertRaisesRegex(dcb.DispatchContextError, "at most"):
            dcb.packet_evidence_outputs(
                {"evidence_outputs": f"[{over_bound}]"}, ("_state/v4-audit/example/",)
            )

    def test_packet_evidence_selection_reuses_only_the_existing_swarm_sidecar(
        self,
    ) -> None:
        relative = "_state/swarm/TASK-example/gpt-codex/member-result.json"
        fields = {
            "dispatch_kind": "swarm",
            "swarm_role": "member",
            "swarm_member_result": relative,
        }
        self.assertEqual(
            dcb.packet_evidence_outputs(
                fields, ("_state/swarm/TASK-example/gpt-codex/",)
            ),
            (
                {
                    "path": relative,
                    "role": "swarm-member-result",
                    "declared_by": "swarm_member_result",
                },
            ),
        )
        self.assertEqual(dcb.packet_evidence_outputs({}, ("_state/",)), ())
        with self.assertRaisesRegex(dcb.DispatchContextError, "outside"):
            dcb.packet_evidence_outputs(fields, ("_state/other/",))


class OutputBridgeTests(unittest.TestCase):
    @staticmethod
    def _authority(task_id: str) -> dict[str, object]:
        result = "_state/cutover-canary/ok.md"
        return {
            "task_id": task_id,
            "lane": "codex",
            "write_paths": [result],
            "expected_result_path": result,
            "expected_outbox_path": (
                f"departments/coding/outbox/{task_id}-response.md"
            ),
        }

    def test_artifact_is_promoted_before_valid_envelope_and_retry_is_idempotent(
        self,
    ) -> None:
        task_id = "TASK-2026-07-23-9991-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Canary completed.\n",
                encoding="utf-8",
            )

            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(
                (root / "_state" / "cutover-canary" / "ok.md").read_text(),
                "OK\n",
            )
            self.assertTrue(
                (
                    root
                    / "departments"
                    / "coding"
                    / "outbox"
                    / f"{task_id}-response.md"
                ).is_file()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["artifact_published"])
            self.assertTrue(receipt["envelope_published"])

            retry = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertTrue(retry["artifact_idempotent"])
            self.assertTrue(retry["envelope_idempotent"])

    def _stage_project_close(
        self,
        directory: str,
        *,
        task_id: str,
        run_id: str,
    ) -> tuple[Path, Path, dict[str, object], str]:
        root = Path(directory) / "main"
        worktree = Path(directory) / "worktree"
        (root / "departments" / "coding" / "outbox").mkdir(parents=True)
        result_relative = "_state/cutover-canary/close.md"
        result = worktree / result_relative
        result.parent.mkdir(parents=True)
        result.write_text("Project close package.\n", encoding="utf-8")
        manifest_relative = f"_state/runs/{run_id}/manifest.yaml"
        manifest = worktree / manifest_relative
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"schema_version":"verification-run/v1"}\n', encoding="utf-8")
        envelope = (
            worktree / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
        )
        envelope.parent.mkdir(parents=True)
        envelope.write_text(
            "---\n"
            f"id: {task_id}-response\n"
            f"in_response_to: {task_id}\n"
            "from: gpt-codex\n"
            "to: chrono\n"
            "type: RESULT\n"
            "status: complete\n"
            f"return_artifact: {result_relative}\n"
            "---\n\n"
            "Project close completed.\n",
            encoding="utf-8",
        )
        authority = {
            **self._authority(task_id),
            "expected_result_path": result_relative,
            "attempt_id": "d-" + "c" * 32,
            "generation": 1,
            "run_id": run_id,
            "mode_profile": "project",
            "write_paths": [result_relative, manifest_relative],
            "evidence_outputs": [
                {
                    "path": manifest_relative,
                    "role": "mode-exit-manifest",
                    "declared_by": "evidence_outputs",
                }
            ],
        }
        return root, worktree, authority, manifest_relative

    def test_project_close_pass_record_releases_result_and_envelope(self) -> None:
        task_id = "TASK-2026-08-11-0771-project-close-pass"
        run_id = "V4-PROJECT-CLOSE-PASS"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, authority, manifest_relative = self._stage_project_close(
                directory, task_id=task_id, run_id=run_id
            )
            prepared = dcb.prepare_worktree_outputs(root, worktree, authority)
            resolved_root = root.resolve()
            result = resolved_root / str(authority["expected_result_path"])
            envelope = resolved_root / str(authority["expected_outbox_path"])
            state_record = resolved_root / "_state" / "vibecoding-check" / f"{run_id}.md"
            state_text = (
                "---\n"
                f"run_id: {run_id}\n"
                "mode: project\n"
                "verdict: PASS\n"
                "---\n\n"
                "# Project close PASS canary\n"
            )

            def passing_verifier(command, **kwargs):
                self.assertEqual(command[0], "/bin/bash")
                self.assertTrue((resolved_root / manifest_relative).is_file())
                self.assertFalse(result.exists())
                self.assertFalse(envelope.exists())
                state_record.parent.mkdir(parents=True)
                state_record.write_text(state_text, encoding="utf-8")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"State: {state_record}\nVerdict tier: 0 (PASS)\n",
                    stderr="",
                )

            with mock.patch.object(dcb.subprocess, "run", side_effect=passing_verifier):
                receipt = dcb.publish_prepared_worktree_outputs(root, prepared)

            self.assertEqual(state_record.read_text(encoding="utf-8"), state_text)
            self.assertTrue(result.is_file())
            self.assertTrue(envelope.is_file())
            self.assertEqual(
                receipt["mode_exit_verification"]["verdict"],
                "PASS",
            )

    def test_project_close_retry_record_blocks_result_and_envelope(self) -> None:
        task_id = "TASK-2026-08-11-0772-project-close-retry"
        run_id = "V4-PROJECT-CLOSE-RETRY"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, authority, manifest_relative = self._stage_project_close(
                directory, task_id=task_id, run_id=run_id
            )
            prepared = dcb.prepare_worktree_outputs(root, worktree, authority)
            resolved_root = root.resolve()
            result = resolved_root / str(authority["expected_result_path"])
            envelope = resolved_root / str(authority["expected_outbox_path"])
            state_record = resolved_root / "_state" / "vibecoding-check" / f"{run_id}.md"
            state_text = (
                "---\n"
                f"run_id: {run_id}\n"
                "mode: project\n"
                "verdict: RETRY-NEEDED\n"
                "---\n\n"
                "# Project close RETRY canary\n"
            )

            def failing_verifier(command, **kwargs):
                self.assertTrue((resolved_root / manifest_relative).is_file())
                self.assertFalse(result.exists())
                self.assertFalse(envelope.exists())
                state_record.parent.mkdir(parents=True)
                state_record.write_text(state_text, encoding="utf-8")
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout=f"State: {state_record}\nVerdict tier: 2 (RETRY)\n",
                    stderr="",
                )

            with (
                mock.patch.object(dcb.subprocess, "run", side_effect=failing_verifier),
                self.assertRaisesRegex(
                    dcb.ModeExitVerificationError,
                    "blocked settlement.*RETRY-NEEDED",
                ),
            ):
                dcb.publish_prepared_worktree_outputs(root, prepared)

            self.assertEqual(state_record.read_text(encoding="utf-8"), state_text)
            self.assertTrue((resolved_root / manifest_relative).is_file())
            self.assertFalse(result.exists())
            self.assertFalse(envelope.exists())

    def test_invalid_envelope_never_promotes_artifact(self) -> None:
        task_id = "TASK-2026-07-23-9992-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text("---\nstatus: complete\n---\n", encoding="utf-8")

            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(root, worktree, self._authority(task_id))
            self.assertFalse((root / "_state" / "cutover-canary" / "ok.md").exists())

    def test_advisory_completed_envelope_promotes_nonempty_artifact(self) -> None:
        task_id = "TASK-2026-07-24-9996-advisory-bridge"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("Independent opinion.\n", encoding="utf-8")
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: completed\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Advisory completed.\n",
                encoding="utf-8",
            )

            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )

            self.assertEqual(receipt["status"], "completed")
            self.assertTrue(receipt["artifact_published"])
            self.assertTrue(receipt["envelope_published"])

    def test_controller_blocked_completion_is_artifact_first(self) -> None:
        task_id = "TASK-2026-07-23-9993-bridge"
        attempt_id = "d-" + "7" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            receipt = dcb.publish_blocked_completion(
                repo_root=root,
                task_id=task_id,
                lane="codex",
                return_artifact="_state/cutover-canary/blocked.md",
                compatibility_namespace="coding",
                reason="supervisor returned 75",
                failure_class="cli_missing",
                attempt_id=attempt_id,
                generation=3,
            )
            self.assertTrue(
                (root / "_state" / "cutover-canary" / "blocked.md").is_file()
            )
            response = (
                root / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            )
            response_text = response.read_text()
            self.assertIn("status: blocked", response_text)
            self.assertIn("failure_class: cli_missing", response_text)
            self.assertIn(f"delivery_attempt_id: {attempt_id}", response_text)
            self.assertIn("delivery_generation: 3", response_text)
            self.assertEqual(receipt["status"], "blocked")

    def test_cli_transport_failure_classes_are_closed(self) -> None:
        self.assertEqual(
            dcb.CLI_TRANSPORT_FAILURE_CLASSES,
            frozenset({"cli_missing", "cli_nonzero", "cli_timeout"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(dcb.DispatchContextError):
                dcb.publish_blocked_completion(
                    repo_root=root,
                    task_id="TASK-2026-08-08-9001-cli-class",
                    lane="codex",
                    return_artifact="_state/cli-class/blocked.md",
                    compatibility_namespace="coding",
                    reason="not a transport failure",
                    failure_class="launch",
                )

    def test_atomic_publish_never_replaces_an_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "_state" / "cutover-canary" / "ok.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("existing\n", encoding="utf-8")

            with self.assertRaises(dcb.DispatchContextError):
                dcb._atomic_publish(
                    root,
                    "_state/cutover-canary/ok.md",
                    b"replacement\n",
                    label="return artifact",
                )
            self.assertEqual(destination.read_text(encoding="utf-8"), "existing\n")

    def test_declared_evidence_is_promoted_with_creation_hash_and_provenance(
        self,
    ) -> None:
        task_id = "TASK-2026-08-11-0301-evidence-bridge"
        attempt_id = "d-" + "8" * 32
        run_id = "V4-EVIDENCE-CREATION-TEST"
        sidecar_relative = (
            f"_state/swarm/{task_id}/gpt-codex/member-result.json"
        )
        original_sidecar = b'{"schema_version":"swarm-member-result/v1"}\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            sidecar = worktree / sidecar_relative
            sidecar.parent.mkdir(parents=True)
            sidecar.write_bytes(original_sidecar)
            envelope = (
                worktree
                / "departments"
                / "coding"
                / "outbox"
                / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Evidence completed.\n",
                encoding="utf-8",
            )
            authority = {
                **self._authority(task_id),
                "attempt_id": attempt_id,
                "generation": 3,
                "run_id": run_id,
                "write_paths": [
                    "_state/cutover-canary/ok.md",
                    f"_state/swarm/{task_id}/gpt-codex/",
                ],
                "evidence_outputs": [
                    {
                        "path": sidecar_relative,
                        "role": "swarm-member-result",
                        "declared_by": "swarm_member_result",
                    }
                ],
            }

            prepared = dcb.prepare_worktree_outputs(root, worktree, authority)
            # Publication must use the bytes captured and hashed at creation,
            # not a later cleanup-time reread of a mutable worktree path.
            sidecar.write_bytes(b'{"tampered_after_prepare":true}\n')
            receipt = dcb.publish_prepared_worktree_outputs(root, prepared)

            promoted = root / sidecar_relative
            self.assertEqual(promoted.read_bytes(), original_sidecar)
            self.assertEqual(len(receipt["artifact_promotions"]), 1)
            promotion = receipt["artifact_promotions"][0]
            self.assertEqual(promotion["schema"], "artifact-promotion/v1")
            self.assertEqual(promotion["role"], "swarm-member-result")
            self.assertEqual(promotion["declared_by"], "swarm_member_result")
            self.assertEqual(promotion["source_path"], sidecar_relative)
            self.assertEqual(promotion["destination_path"], sidecar_relative)
            self.assertEqual(
                promotion["content_sha256"], hashlib.sha256(original_sidecar).hexdigest()
            )
            self.assertEqual(promotion["size_bytes"], len(original_sidecar))
            self.assertEqual(
                promotion["producer"],
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "generation": 3,
                    "run_id": run_id,
                },
            )

    def test_ordinary_packet_evidence_is_promoted_from_creation_bound_bytes(
        self,
    ) -> None:
        """The full P3.5 path for an ordinary (non-swarm) packet.

        The packet declares a PoC and a repro log; both are read and hashed at
        preparation, before integration or worktree cleanup can touch them, and
        published from those captured bytes with producer provenance. Mutating
        the worktree copies after preparation must not change what is promoted.
        """

        task_id = "TASK-2026-08-11-0501-ordinary-evidence"
        attempt_id = "d-" + "a" * 32
        run_id = "V4-ORDINARY-EVIDENCE-TEST"
        poc_relative = "_state/v4-audit/p3-r2/poc.py"
        log_relative = "_state/v4-audit/p3-r2/repro.log"
        original = {
            poc_relative: b"print('proof of concept')\n",
            log_relative: b"repro: 1 of 1 attempts reproduced\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            for relative, data in original.items():
                path = worktree / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            envelope = (
                worktree / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: claude\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Ordinary evidence completed.\n",
                encoding="utf-8",
            )
            authority = {
                **self._authority(task_id),
                "attempt_id": attempt_id,
                "generation": 2,
                "run_id": run_id,
                "write_paths": ["_state/cutover-canary/ok.md", "_state/v4-audit/p3-r2/"],
                "evidence_outputs": [
                    {
                        "path": relative,
                        "role": "declared-evidence",
                        "declared_by": "evidence_outputs",
                    }
                    for relative in original
                ],
            }

            prepared = dcb.prepare_worktree_outputs(root, worktree, authority)
            for relative in original:
                (worktree / relative).write_bytes(b"mutated after preparation\n")
            receipt = dcb.publish_prepared_worktree_outputs(root, prepared)

            promotions = {
                promotion["source_path"]: promotion
                for promotion in receipt["artifact_promotions"]
            }
            self.assertEqual(set(promotions), set(original))
            for relative, data in original.items():
                self.assertEqual((root / relative).read_bytes(), data)
                promotion = promotions[relative]
                self.assertEqual(promotion["schema"], "artifact-promotion/v1")
                self.assertEqual(promotion["role"], "declared-evidence")
                self.assertEqual(promotion["declared_by"], "evidence_outputs")
                self.assertEqual(promotion["destination_path"], relative)
                self.assertEqual(
                    promotion["content_sha256"], hashlib.sha256(data).hexdigest()
                )
                self.assertEqual(
                    promotion["producer"],
                    {
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "generation": 2,
                        "run_id": run_id,
                    },
                )

    def test_declared_ordinary_evidence_that_is_absent_blocks_completion(self) -> None:
        """Declaring evidence is a commitment, not a hint.

        A missing declared file blocks before anything is published, which is
        what stops a run from settling green while its evidence strands in a
        worktree that is about to be pruned.
        """

        task_id = "TASK-2026-08-11-0502-absent-evidence"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            worktree = Path(directory) / "worktree"
            (root / "departments" / "coding" / "outbox").mkdir(parents=True)
            result = worktree / "_state" / "cutover-canary" / "ok.md"
            result.parent.mkdir(parents=True)
            result.write_text("OK\n", encoding="utf-8")
            envelope = (
                worktree / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            )
            envelope.parent.mkdir(parents=True)
            envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: claude\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                "return_artifact: _state/cutover-canary/ok.md\n"
                "---\n\n"
                "Summary.\n",
                encoding="utf-8",
            )
            authority = {
                **self._authority(task_id),
                "attempt_id": "d-" + "b" * 32,
                "generation": 1,
                "run_id": "V4-ABSENT-EVIDENCE-TEST",
                "write_paths": ["_state/cutover-canary/ok.md", "_state/v4-audit/p3-r2/"],
                "evidence_outputs": [
                    {
                        "path": "_state/v4-audit/p3-r2/never-written.py",
                        "role": "declared-evidence",
                        "declared_by": "evidence_outputs",
                    }
                ],
            }
            with self.assertRaises(dcb.DispatchContextError):
                dcb.prepare_worktree_outputs(root, worktree, authority)
            self.assertFalse((root / "_state" / "cutover-canary" / "ok.md").exists())

    def test_concurrent_no_clobber_publish_uses_rename_and_preserves_loser(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "_state/swarm/race/member-result.json"
            barrier = threading.Barrier(2)
            original_safe_destination = dcb._safe_destination

            def synchronized_destination(*args, **kwargs):
                destination = original_safe_destination(*args, **kwargs)
                barrier.wait(timeout=5)
                return destination

            def publish(data: bytes):
                try:
                    return (
                        "published",
                        dcb._atomic_publish(
                            root,
                            relative,
                            data,
                            label="swarm member record",
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - race result under test
                    return ("lost", exc)

            contenders = (b'{"writer":"alpha"}\n', b'{"writer":"beta"}\n')
            with (
                mock.patch.object(
                    dcb, "_safe_destination", side_effect=synchronized_destination
                ),
                # The contract is temp + fsync + no-replace RENAME. The old
                # hard-link publisher fails this test even if it happens not to
                # clobber during one scheduler interleaving.
                mock.patch.object(
                    dcb.os,
                    "link",
                    side_effect=AssertionError("hard-link publication is forbidden"),
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                outcomes = list(executor.map(publish, contenders))

            self.assertEqual([item[0] for item in outcomes].count("published"), 1)
            self.assertEqual([item[0] for item in outcomes].count("lost"), 1)
            losing_error = next(item[1] for item in outcomes if item[0] == "lost")
            self.assertIsInstance(losing_error, dcb.DispatchContextError)
            destination = root / relative
            winner = destination.read_bytes()
            loser = next(data for data in contenders if data != winner)
            staging = list(destination.parent.glob(f".{destination.name}.bridge.*"))
            self.assertEqual(len(staging), 1)
            self.assertEqual(staging[0].read_bytes(), loser)

    def _stage_completion(
        self,
        directory: str,
        task_id: str,
        *,
        envelope_text: str,
        artifact_text: str = "OK\n",
    ) -> tuple[Path, Path]:
        """Lay out a worktree with a real artifact and a raw worker envelope."""
        root = Path(directory) / "main"
        worktree = Path(directory) / "worktree"
        (root / "departments" / "coding" / "outbox").mkdir(parents=True)
        result = worktree / "_state" / "cutover-canary" / "ok.md"
        result.parent.mkdir(parents=True)
        if artifact_text:
            result.write_text(artifact_text, encoding="utf-8")
        envelope = (
            worktree / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
        )
        envelope.parent.mkdir(parents=True)
        envelope.write_text(envelope_text, encoding="utf-8")
        return root, worktree

    def test_noncanonical_status_is_normalized_and_promoted(self) -> None:
        # The exact K3-wiring repro: a worker minted `complete_with_scoped_exclusion`
        # over real, complete work. Normalize the status intent to `complete` and
        # promote instead of stranding the finished run.
        task_id = "TASK-2026-07-26-8001-normalize"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete_with_scoped_exclusion\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Wired K3 with one scoped exclusion.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["envelope_published"])
            published = (
                root / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            self.assertIn("status: complete\n", published)
            self.assertNotIn("scoped_exclusion", published)
            # The worker's summary prose survives the normalization.
            self.assertIn("Wired K3 with one scoped exclusion.", published)
            # Retry is idempotent because reconstruction is deterministic.
            retry = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertTrue(retry["envelope_idempotent"])

    def test_missing_and_extra_fields_are_normalized_and_promoted(self) -> None:
        # The offense-track repro: a required field missing AND an unexpected
        # extra field, over complete work. Default the missing field from the
        # trusted launch authority, ignore the extra, and promote.
        task_id = "TASK-2026-07-26-8002-repair"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    # `from` intentionally omitted (missing required field)
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "phase: S7\n"  # unexpected extra field
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Offense skills landed.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["envelope_published"])
            published = (
                root / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            # Missing `from` defaulted from authority (codex lane -> gpt-codex).
            self.assertIn("from: gpt-codex\n", published)
            # Unexpected extra dropped from the canonical envelope.
            self.assertNotIn("phase: S7", published)

    def test_wrong_identity_field_is_repaired_from_authority(self) -> None:
        # A worker that put the wrong lane in `from` should be repaired to the
        # authority value, not stranded.
        task_id = "TASK-2026-07-26-8003-identity"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gemini\n"  # wrong lane; authority says codex
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Done.\n"
                ),
            )
            dcb.bridge_worktree_outputs(root, worktree, self._authority(task_id))
            published = (
                root / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
            ).read_text(encoding="utf-8")
            self.assertIn("from: gpt-codex\n", published)
            self.assertNotIn("from: gemini", published)

    def test_empty_summary_still_blocks(self) -> None:
        # Genuinely-empty report (no summary) is NOT a recoverable metadata
        # deviation; it must still block and never promote the artifact.
        task_id = "TASK-2026-07-26-8004-empty"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "   \n"
                ),
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(root, worktree, self._authority(task_id))
            self.assertFalse((root / "_state" / "cutover-canary" / "ok.md").exists())

    def test_absent_artifact_still_blocks(self) -> None:
        # No return artifact = genuinely-missing work; still blocks even with a
        # perfectly-formed envelope.
        task_id = "TASK-2026-07-26-8005-noartifact"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                artifact_text="",  # no artifact written
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: complete\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Claims done but wrote nothing.\n"
                ),
            )
            with self.assertRaises(dcb.DispatchContextError):
                dcb.bridge_worktree_outputs(root, worktree, self._authority(task_id))

    def test_unrecognized_status_defaults_to_needs_review(self) -> None:
        # An unmappable status defaults to needs_review so questionable work
        # surfaces to the controller rather than silently auto-closing.
        task_id = "TASK-2026-07-26-8006-unknown"
        with tempfile.TemporaryDirectory() as directory:
            root, worktree = self._stage_completion(
                directory,
                task_id,
                envelope_text=(
                    "---\n"
                    f"id: {task_id}-response\n"
                    f"in_response_to: {task_id}\n"
                    "from: gpt-codex\n"
                    "to: chrono\n"
                    "type: RESULT\n"
                    "status: partially_maybe\n"
                    "return_artifact: _state/cutover-canary/ok.md\n"
                    "---\n\n"
                    "Ambiguous outcome.\n"
                ),
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority(task_id)
            )
            self.assertEqual(receipt["status"], "needs_review")

    def test_coerce_status_mapping(self) -> None:
        self.assertEqual(dcb._coerce_status("complete"), "complete")
        self.assertEqual(dcb._coerce_status("completed"), "completed")
        self.assertEqual(dcb._coerce_status("needs_review"), "needs_review")
        self.assertEqual(dcb._coerce_status("blocked"), "blocked")
        self.assertEqual(
            dcb._coerce_status("complete_with_scoped_exclusion"), "complete"
        )
        self.assertEqual(dcb._coerce_status("done"), "complete")
        self.assertEqual(dcb._coerce_status("failed"), "blocked")
        self.assertEqual(dcb._coerce_status("blocked_on_review"), "blocked")
        # CC-17: `needs_human` is its own escalation level (an operator decision
        # is owed), not a synonym for `needs_review`. The injected no-delete rule
        # instructs workers to emit it, so downgrading it here silently dropped
        # the escalation. It must survive verbatim.
        self.assertEqual(dcb._coerce_status("needs_human"), "needs_human")
        self.assertEqual(dcb._coerce_status("needs human review"), "needs_human")
        self.assertEqual(
            dcb._coerce_status("awaiting operator approval"), "needs_human"
        )
        self.assertEqual(dcb._coerce_status(""), "needs_review")
        self.assertEqual(dcb._coerce_status("wat"), "needs_review")


class AliasedOutputBridgeTests(unittest.TestCase):
    """The standard packet shape: return_artifact IS the outbox envelope path.

    Regression for the 2026-08-18 board incident: ~a dozen consecutive
    completions auto-closed `blocked` with "response envelope destination
    already differs" over finished, correct work. The bridge published the raw
    artifact first and the pin-carrying envelope second at the SAME aliased
    path, colliding with its own first write.
    """

    TASK_ID = "TASK-2026-08-18-9001-aliased"
    ATTEMPT_ID = "d-" + "a" * 32
    OUTBOX_RELATIVE = f"departments/coding/outbox/{TASK_ID}-response.md"

    @classmethod
    def _authority(cls) -> dict[str, object]:
        return {
            "task_id": cls.TASK_ID,
            "lane": "codex",
            "write_paths": [cls.OUTBOX_RELATIVE],
            "expected_result_path": cls.OUTBOX_RELATIVE,
            "expected_outbox_path": cls.OUTBOX_RELATIVE,
            # Live board launches always carry the CC-03 fence, which is what
            # guarantees the rendered envelope differs from the worker's raw
            # file. The original fixtures omitted it and never saw this bug.
            "reconciliation_echo": {
                "delivery_attempt_id": cls.ATTEMPT_ID,
                "delivery_generation": "1",
            },
        }

    @classmethod
    def _raw_response_text(cls) -> str:
        return (
            "---\n"
            f"id: {cls.TASK_ID}-response\n"
            f"in_response_to: {cls.TASK_ID}\n"
            "from: gpt-codex\n"
            "to: chrono\n"
            "type: RESULT\n"
            "status: complete\n"
            f"return_artifact: {cls.OUTBOX_RELATIVE}\n"
            "---\n\n"
            "Aliased completion: the full report body.\n"
        )

    def _stage(self, directory: str) -> tuple[Path, Path, Path]:
        root = Path(directory) / "main"
        worktree = Path(directory) / "worktree"
        (root / "departments" / "coding" / "outbox").mkdir(parents=True)
        response = worktree / self.OUTBOX_RELATIVE
        response.parent.mkdir(parents=True)
        response.write_text(self._raw_response_text(), encoding="utf-8")
        return root, worktree, root / self.OUTBOX_RELATIVE

    def test_aliased_completion_promotes_one_canonical_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, destination = self._stage(directory)
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertTrue(receipt["artifact_published"])
            self.assertTrue(receipt["envelope_published"])
            self.assertEqual(receipt["artifact_path"], receipt["envelope_path"])
            self.assertEqual(
                receipt["artifact_sha256"], receipt["envelope_sha256"]
            )
            published = destination.read_text(encoding="utf-8")
            # Canonical: trusted pins present, worker prose preserved.
            self.assertIn(f"delivery_attempt_id: {self.ATTEMPT_ID}\n", published)
            self.assertIn("delivery_generation: 1\n", published)
            self.assertIn("status: complete\n", published)
            self.assertIn("Aliased completion: the full report body.", published)
            # Retry is idempotent because rendering is deterministic.
            retry = dcb.bridge_worktree_outputs(root, worktree, self._authority())
            self.assertTrue(retry["artifact_idempotent"])
            self.assertTrue(retry["envelope_idempotent"])

    def test_aliased_promotion_reclaims_interrupted_artifact_write(self) -> None:
        # The exact state the pre-fix bug left behind: the worker's raw
        # response landed at the destination (artifact write succeeded), the
        # envelope write refused, the task auto-closed blocked. A re-promotion
        # of the same completion must reconcile, not refuse.
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, destination = self._stage(directory)
            destination.write_text(self._raw_response_text(), encoding="utf-8")
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority()
            )
            self.assertTrue(receipt["envelope_published"])
            published = destination.read_text(encoding="utf-8")
            self.assertIn(f"delivery_attempt_id: {self.ATTEMPT_ID}\n", published)

    def test_aliased_promotion_reclaims_prior_blocked_stub(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, destination = self._stage(directory)
            destination.write_text(
                "blocked\n\n"
                f"# Board dispatch blocked — {self.TASK_ID}\n\n"
                "Controller reason: earlier generation refused\n",
                encoding="utf-8",
            )
            receipt = dcb.bridge_worktree_outputs(
                root, worktree, self._authority()
            )
            self.assertTrue(receipt["envelope_published"])
            self.assertIn(
                f"delivery_attempt_id: {self.ATTEMPT_ID}\n",
                destination.read_text(encoding="utf-8"),
            )

    def test_aliased_promotion_still_refuses_unrelated_destination(self) -> None:
        # The clobber protection is intact: bytes that are neither this task's
        # own raw response nor its blocked stub stay refused.
        with tempfile.TemporaryDirectory() as directory:
            root, worktree, destination = self._stage(directory)
            destination.write_text(
                "---\nid: someone-else\n---\n\nAnother task's file.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                dcb.DispatchContextError,
                "response envelope destination already differs",
            ):
                dcb.bridge_worktree_outputs(root, worktree, self._authority())
            self.assertIn(
                "Another task's file.",
                destination.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
