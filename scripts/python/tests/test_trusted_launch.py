#!/usr/bin/env python3
"""V2 trusted-launch-path — bin/board-supervisor.sh trusted-launch subcommand.

Tests the real script end-to-end via subprocess (not a reimplementation of
its logic), using /usr/bin/true as the "fresh CLI" stand-in for a real
launch under the exact Stage-1 Seatbelt boundary — the same established
pattern already used by test_runtime_envelope.py and test_f2_closure.py in
this exact codebase. Composition correctness (role adopted, own worktree,
parallel-safe via the real scheduler, lineage established, normal env) is
verified against the REAL settled 2.1/2.2/2.3/2.4 modules the script itself
imports, not a parallel reimplementation of them.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

SCRIPT = ROOT / "bin" / "board-supervisor.sh"
SETTLED_T1P1_BUNDLE_SHA256 = "95438e2cc6b06ab3f12622ad0a0f3e0a6654e6cf3a7b35f3908b3487f883f376"

import worktree_isolation as wti  # noqa: E402
import dispatch_context_builder as dcb  # noqa: E402
import seatbelt_profile  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


def _git(args: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {args} failed: {completed.stderr}")


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "v2"], cwd=repo)
    _git(["config", "user.email", "t@example.com"], cwd=repo)
    _git(["config", "user.name", "T"], cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    return repo


def _write_role_files(root: Path) -> tuple[Path, Path]:
    role = root / "role.md"
    overlay = root / "overlay.md"
    role.write_text("# Systems Engineer\n\nBuild carefully.\n", encoding="utf-8")
    overlay.write_text("# Claude overlay\n\nUse the native lane.\n", encoding="utf-8")
    return role, overlay


def _run_trusted_launch(
    payload: dict[str, object],
    *,
    timeout: float = 40,
    trusted_host_path: str | None = None,
) -> dict[str, object]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        context_path = Path(handle.name)
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LC_ALL": "C",
        "VAULT_ROOT": str(ROOT),
        "TRUSTED_LAUNCH_TEST_MODE": "1",
    }
    if trusted_host_path is not None:
        environment["TRUSTED_HOST_PATH"] = trusted_host_path
    try:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    finally:
        context_path.unlink(missing_ok=True)
    try:
        return json.loads(completed.stdout.strip() or completed.stderr.strip())
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"non-JSON output: rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc


class TrustedLaunchTests(unittest.TestCase):
    def _fixture_payload(self, root: Path, *, task_id: str, attempt_id: str) -> dict[str, object]:
        repo = _init_repo(root)
        role, overlay = _write_role_files(root)
        executable = Path("/usr/bin/true")
        now = int(time.time())
        digest = lambda value: hashlib.sha256(value).hexdigest()
        authority = {
            "schema": "go-live-authority/v1",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "run_id": "PROJ-SWARM-READY-2026-07-19",
            "author_family": "openai",
            "workload_class": "light-text",
            "specialist": "systems-engineer",
            "lane": "claude",
            "mode_profile": "project",
            "execution_kind": "offline-probe",
            "repo_root": str(repo),
            "pool_root": str(root / "pool"),
            "canonical_role_path": str(role),
            "canonical_role_sha256": digest(role.read_bytes()),
            "lane_overlay_path": str(overlay),
            "lane_overlay_sha256": digest(overlay.read_bytes()),
            "executable": str(executable),
            "executable_sha256": digest(executable.read_bytes()),
            "lane_args": [],
            "write_paths": [f"out/{task_id}.txt"],
            "read_scope": ["README.md"],
            "depends_on": [],
            "resources": [],
            "scheduler_concurrency": 2,
            "scheduler_capacities": {},
            "scheduler_settled": {},
            "network_scope": [],
            "action_scope": ["repo-read", "worktree-write"],
            "budgets": {"timeout_seconds": 30},
            "expected_result_path": f"out/{task_id}.txt",
            "expected_outbox_path": f"out/{task_id}-response.md",
            "reconciliation_echo": {},
            "required_phase_ids": [
                "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"
            ],
            "verification_kinds": ["project_tests", "recipient_contract"],
            "operator_gates": [
                "credential-change",
                "default-cutover",
                "delete-from-main",
                "outreach",
                "prod-mutation",
                "public-push",
                "release",
                "spend",
            ],
            "packet_sha256": digest(f"{task_id}:packet".encode()),
            "plan_sha256": digest(f"{task_id}:plan".encode()),
            "verification_contract_sha256": digest(
                f"{task_id}:contract".encode()
            ),
            "selected_model_sha256": digest(b"offline-probe"),
            "profile_bundle_sha256": SETTLED_T1P1_BUNDLE_SHA256,
            "active_board_tasks": [],
            "created_at": now,
            "expires_at": now + 300,
            "nonce": digest(f"{attempt_id}:nonce".encode()),
        }
        return {
            "schema": "go-live-trusted-context/v1",
            "authority": authority,
            "task_prompt": "Run the authenticated inert offline launch probe.",
        }

    def _board_fixture_payload(
        self,
        root: Path,
        *,
        task_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        payload = self._fixture_payload(
            root,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        authority = payload["authority"]
        repo = Path(authority["repo_root"])
        runtime_map = repo / "shared" / "specialist-runtime-map.tsv"
        runtime_map.parent.mkdir(parents=True)
        runtime_map.write_text(
            "specialist\tsource_namespace\tprimary_lane\tprimary_profile\n"
            "systems-engineer\tcoding\tcodex\tcodex.test.high\n",
            encoding="utf-8",
        )
        profiles = repo / "shared" / "registries" / "profiles.tsv"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            "profile_id\tlane\tmodel_id\teffort\tflags\tusage\n"
            "codex.test.high\tcodex\tgpt-test\thigh\tnone\tprimary\n",
            encoding="utf-8",
        )
        executable = Path(seatbelt_profile.LANE_CLI_PATHS["codex"])
        authority.update(
            {
                "execution_kind": "lane",
                "lane": "codex",
                "executable": str(executable),
                "executable_sha256": hashlib.sha256(
                    Path(os.path.realpath(executable)).read_bytes()
                ).hexdigest(),
                "lane_args": list(
                    dcb.trusted_lane_args_for(
                        repo,
                        lane="codex",
                        specialist="systems-engineer",
                    )
                ),
                "selected_model_sha256": dcb.selected_model_sha256_for(
                    repo,
                    lane="codex",
                    specialist="systems-engineer",
                ),
            }
        )
        return payload

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_board_lane_arguments_are_still_controller_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._board_fixture_payload(
                Path(directory).resolve(),
                task_id="TASK-2026-07-23-9925-board-args",
                attempt_id="d-" + "8" * 32,
            )
            payload["authority"]["lane_args"].append("--untrusted-flag")

            receipt = _run_trusted_launch(payload)

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("closed controller ABI", receipt.get("reason", ""))
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_board_selected_model_is_still_controller_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._board_fixture_payload(
                Path(directory).resolve(),
                task_id="TASK-2026-07-23-9935-board-model",
                attempt_id="d-" + "9" * 32,
            )
            payload["authority"]["selected_model_sha256"] = hashlib.sha256(
                b"tampered-model"
            ).hexdigest()

            receipt = _run_trusted_launch(payload)

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("selected model", receipt.get("reason", ""))
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    @skip_in_host_independent_ci(
        "needs the live trusted-launch worktree and supervisor rail"
    )
    def test_a_fresh_launch_adopts_the_role_gets_its_own_worktree_and_a_lineage_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0001-tl-test", attempt_id="d-" + "1" * 32
            )
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertTrue(receipt["role_context_sha256"])
            self.assertTrue(receipt["worktree_root"].startswith(str(root)))
            self.assertTrue(Path(receipt["worktree_root"]).is_dir())
            self.assertTrue(receipt["lineage_sha256"])
            self.assertEqual(receipt["lineage_chain_depth"], 0)

    @skip_in_host_independent_ci(
        "needs the live trusted-launch worktree and supervisor rail"
    )
    def test_the_launch_uses_normal_env_not_broker_custody(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0002-tl-test", attempt_id="d-" + "2" * 32
            )
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertNotIn("credential", json.dumps(receipt).lower())
            self.assertEqual(
                receipt["authority_mode"],
                "trusted-host-unpinned",
            )

    @skip_in_host_independent_ci(
        "needs live trusted-launch worktrees and board scheduling"
    )
    def test_two_disjoint_launches_get_disjoint_worktrees_and_are_scheduler_parallel_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload_a = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0003-tl-alpha", attempt_id="d-" + "3" * 32
            )
            receipt_a = _run_trusted_launch(payload_a)
            self.assertEqual(receipt_a.get("status"), "launched", receipt_a)

            payload_b = dict(payload_a)
            payload_b["authority"] = dict(payload_a["authority"])
            payload_b["authority"]["task_id"] = "TASK-2026-07-22-0004-tl-beta"
            payload_b["authority"]["attempt_id"] = "d-" + "4" * 32
            payload_b["authority"]["write_paths"] = [
                "out/TASK-2026-07-22-0004-tl-beta.txt"
            ]
            payload_b["authority"]["expected_result_path"] = (
                "out/TASK-2026-07-22-0004-tl-beta.txt"
            )
            payload_b["authority"]["expected_outbox_path"] = (
                "out/TASK-2026-07-22-0004-tl-beta-response.md"
            )
            payload_b["authority"]["active_board_tasks"] = [
                {
                    "task_id": receipt_a["task_id"],
                    "write_paths": payload_a["authority"]["write_paths"],
                    "read_paths": payload_a["authority"]["read_scope"],
                    "worktree_root": receipt_a["worktree_root"],
                    "depends_on": [],
                    "resources": [],
                    "metadata_complete": True,
                    "priority": 0,
                }
            ]
            receipt_b = _run_trusted_launch(payload_b)
            self.assertEqual(receipt_b.get("status"), "launched", receipt_b)
            self.assertNotEqual(receipt_a["worktree_root"], receipt_b["worktree_root"])

    def test_a_colliding_active_task_serializes_rather_than_launching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0005-tl-collide", attempt_id="d-" + "5" * 32
            )
            # Declare an active task that claims a write path INSIDE where
            # this task's own worktree will land (the pool_root itself),
            # forcing board_router to refuse to parallelize.
            payload["authority"]["active_board_tasks"] = [
                {
                    "task_id": "TASK-2026-07-22-0000-tl-blocker",
                    "write_paths": payload["authority"]["write_paths"],
                    "read_paths": [],
                    "worktree_root": payload["authority"]["repo_root"],
                    "depends_on": [],
                    "resources": [],
                    "metadata_complete": True,
                    "priority": 0,
                }
            ]
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("write-scope collision", json.dumps(receipt).lower())

    @skip_in_host_independent_ci(
        "executes the live trusted-host supervisor launch path"
    )
    def test_trusted_default_runs_the_inert_probe_outside_final_seatbelt(self) -> None:
        # The trusted default consumes the settled Seatbelt canary, then runs
        # its real child on the trusted host. Strict final-Seatbelt execution
        # remains opt-in and is covered by test_golive_integration.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0006-tl-prodgap", attempt_id="d-" + "6" * 32
            )
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                json.dump(payload, handle)
                context_path = Path(handle.name)
            try:
                completed = subprocess.run(
                    ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "VAULT_ROOT": str(ROOT)},
                )
            finally:
                context_path.unlink(missing_ok=True)
            receipt = json.loads(completed.stdout.strip() or completed.stderr.strip())
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertTrue(receipt["cli_exec_succeeded"], receipt)
            self.assertEqual(receipt["returncode"], 0, receipt)
            self.assertEqual(
                receipt["final_worker_boundary"],
                "trusted-host-normal-env",
            )

    def test_missing_context_file_is_denied_not_a_crash(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", "/nonexistent/path.json"],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "VAULT_ROOT": str(ROOT), "TRUSTED_LAUNCH_TEST_MODE": "1"},
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout.strip() or completed.stderr.strip())
        self.assertEqual(payload.get("status"), "denied")

    def test_trusted_host_path_with_empty_component_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root,
                task_id="TASK-2026-07-28-0916-path-deny",
                attempt_id="d-" + "7" * 32,
            )

            receipt = _run_trusted_launch(
                payload,
                trusted_host_path="/usr/bin::/bin",
            )

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn(
                "only non-empty absolute components",
                receipt.get("reason", ""),
            )
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    def test_the_existing_prepare_broker_strict_subcommand_is_unchanged(self) -> None:
        # Hard boundary: the F2 strict machinery stays intact as the opt-in
        # path, not deleted or altered by this task.
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertIn("prepare", completed.stdout)
        self.assertIn("trusted-launch", completed.stdout)

    @skip_in_host_independent_ci("launches the subscription-backed Claude CLI")
    @unittest.skipUnless(
        os.environ.get("RUN_CLAUDE_BYPASS_PROBE") == "1",
        "real subscription-backed Claude bypass probe is opt-in",
    )
    def test_real_claude_bypass_mode_keeps_vault_and_hides_disallowed_mcps(self) -> None:
        executable = Path(seatbelt_profile.LANE_CLI_PATHS["claude"])
        if not executable.is_file():
            self.skipTest("Claude CLI is not installed at the lane entrypoint")
        environment = dict(os.environ)
        for name in (
            "ANTHROPIC_API_KEY",
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_EXECPATH",
            "CLAUDE_CODE_SESSION_ID",
        ):
            environment.pop(name, None)
        prompt = (
            "Real bounded capability proof. Use ToolSearch for 'chrono-vault "
            "recall', then call mcp__plugin_chrono-vault_chrono-vault__recall "
            "once with query 'lane capability scoped proof 0725' and limit 1. "
            "Then use ToolSearch for 'chrono-recon'. Report VAULT_SUCCEEDED only "
            "after a successful tool_result and RECON_UNAVAILABLE only if no "
            "chrono-recon tool is exposed. Finally, use ToolSearch exactly once "
            "for each of these exact queries: 'claude.ai Gmail', 'claude.ai "
            "Google Drive', and 'claude.ai Google Calendar'. Report "
            "GOOGLE_CONNECTORS_UNAVAILABLE only if every one returns no matches. "
            "Do not call a Google connector and do not use any other tool."
        )
        completed = subprocess.run(
            [
                str(executable),
                "-p",
                prompt,
                "--agent",
                "systems-engineer",
                "--model",
                "haiku",
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
                "--dangerously-skip-permissions",
                "--disallowedTools",
                (
                    "Agent,mcp__plugin_chrono-recon_chrono-recon__*,"
                    "mcp__claude_ai_Gmail__*,"
                    "mcp__claude_ai_Google_Drive__*,"
                    "mcp__claude_ai_Google_Calendar__*"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(ROOT / "model-lanes" / "claude"),
            env=environment,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = [
            json.loads(line)
            for line in completed.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        self.assertTrue(
            any(
                event.get("type") == "system"
                and event.get("subtype") == "init"
                and event.get("permissionMode") == "bypassPermissions"
                for event in events
            )
        )
        init_event = next(
            event
            for event in events
            if event.get("type") == "system" and event.get("subtype") == "init"
        )
        init_servers = {
            item.get("name")
            for item in init_event.get("mcp_servers", [])
            if isinstance(item, dict)
        }
        self.assertIn("plugin:chrono-vault:chrono-vault", init_servers)
        self.assertIn("plugin:chrono-recon:chrono-recon", init_servers)
        self.assertIn("claude.ai Gmail", init_servers)
        self.assertIn("claude.ai Google Drive", init_servers)
        self.assertIn("claude.ai Google Calendar", init_servers)
        vault_uses = [
            block
            for event in events
            for block in event.get("message", {}).get("content", [])
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name")
            == "mcp__plugin_chrono-vault_chrono-vault__recall"
        ]
        self.assertEqual(len(vault_uses), 1)
        vault_id = vault_uses[0]["id"]
        self.assertTrue(
            any(
                any(
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("tool_use_id") == vault_id
                    and not block.get("is_error", False)
                    for block in event.get("message", {}).get("content", [])
                )
                for event in events
            )
        )
        self.assertTrue(
            any(
                isinstance(event.get("tool_use_result"), dict)
                and event["tool_use_result"].get("query") == "chrono-recon"
                and event["tool_use_result"].get("matches") == []
                for event in events
            )
        )
        self.assertFalse(
            any(
                block.get("name", "").startswith(
                    "mcp__plugin_chrono-recon_chrono-recon__"
                )
                for event in events
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            )
        )
        google_queries = {
            "claude.ai Gmail",
            "claude.ai Google Drive",
            "claude.ai Google Calendar",
        }
        empty_google_queries = {
            event["tool_use_result"].get("query")
            for event in events
            if isinstance(event.get("tool_use_result"), dict)
            and event["tool_use_result"].get("query") in google_queries
            and event["tool_use_result"].get("matches") == []
        }
        self.assertEqual(empty_google_queries, google_queries)
        self.assertFalse(
            any(
                block.get("name", "").startswith("mcp__claude_ai_")
                for event in events
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            )
        )


if __name__ == "__main__":
    unittest.main()
