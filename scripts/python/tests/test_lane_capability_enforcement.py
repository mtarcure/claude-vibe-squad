from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
sys.path.insert(0, str(PYTHON_DIR))

from lane_capability_enforcement import (  # noqa: E402
    CapabilityDenied,
    cli_args_for_materialized,
    load_json_mcp_servers,
    load_projection,
    materialize_role_config,
    parse_claude_enabled_plugins,
    parse_claude_project_plugin_dirs,
    parse_live_mcp_listing,
    plan_lane,
)
import seatbelt_profile  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


class LaneCapabilityEnforcementTests(unittest.TestCase):
    def _supervisor_denial_record(
        self,
        *,
        lane: str,
        specialist: str,
        canonical_role: Path,
        adapter: Path,
        executable: Path,
    ) -> tuple[int, dict[str, object]]:
        digest = lambda value: hashlib.sha256(value).hexdigest()
        now = int(time.time())
        task_id = f"TASK-2026-07-22-0705-{lane}-deny"
        attempt_id = "d-" + digest(lane.encode())[:32]
        resolved_executable = Path(os.path.realpath(executable))
        authority = {
            "schema": "go-live-authority/v1",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "run_id": "PROJ-SWARM-READY-2026-07-19",
            "author_family": "openai",
            "workload_class": "light-text",
            "specialist": specialist,
            "lane": lane,
            "mode_profile": "project",
            "execution_kind": "lane",
            "repo_root": str(ROOT),
            "pool_root": str(
                ROOT / "_state" / "lane-capability-wiring-2026-07-22" / "tests"
            ),
            "canonical_role_path": str(canonical_role),
            "canonical_role_sha256": digest(canonical_role.read_bytes()),
            "lane_overlay_path": str(adapter),
            "lane_overlay_sha256": digest(adapter.read_bytes()),
            "executable": str(executable),
            "executable_sha256": digest(resolved_executable.read_bytes()),
            "lane_args": [],
            "write_paths": [
                f"_state/lane-capability-wiring-2026-07-22/{lane}.txt"
            ],
            "read_scope": [
                "departments/coding/inbox/"
                "TASK-2026-07-22-0705-lane-capability-wiring.md"
            ],
            "depends_on": [],
            "resources": [],
            "scheduler_concurrency": 1,
            "scheduler_capacities": {},
            "scheduler_settled": {},
            "network_scope": [],
            "action_scope": ["repo-read", "worktree-write"],
            "budgets": {"timeout_seconds": 30},
            "expected_result_path": (
                f"_state/lane-capability-wiring-2026-07-22/{lane}.txt"
            ),
            "expected_outbox_path": (
                f"_state/lane-capability-wiring-2026-07-22/{lane}-response.md"
            ),
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
            "selected_model_sha256": digest(f"{lane}:model".encode()),
            "profile_bundle_sha256": (
                "95438e2cc6b06ab3f12622ad0a0f3e0a"
                "6654e6cf3a7b35f3908b3487f883f376"
            ),
            "active_board_tasks": [],
            "created_at": now,
            "expires_at": now + 300,
            "nonce": digest(f"{attempt_id}:nonce".encode()),
        }
        context = {
            "schema": "go-live-trusted-context/v1",
            "authority": authority,
            "task_prompt": "This launch must deny before any provider call.",
        }
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8"
        ) as stream:
            json.dump(context, stream)
            stream.flush()
            completed = subprocess.run(
                [
                    "/bin/bash",
                    str(ROOT / "bin" / "board-supervisor.sh"),
                    "trusted-launch",
                    stream.name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        return completed.returncode, json.loads(completed.stdout)

    def test_projection_reads_aliases_and_separates_kimi_lead_brokered_mcps(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "adapter.yaml"
            overlay = root / "overlay.md"
            adapter.write_text(
                'capability_mcps: ["playwright","lead:chrono-vault"]\n'
                'tools: ["read_file","run_shell_command"]\n',
                encoding="utf-8",
            )
            overlay.write_text(
                'mcps = ["chrome-devtools","lead:sequential-thinking"]\n',
                encoding="utf-8",
            )
            projection = load_projection(
                lane="kimi",
                specialist="summarizer",
                adapter_path=adapter,
                overlay_path=overlay,
            )
        self.assertEqual(
            projection["mcps"], ["chrome-devtools", "playwright"]
        )
        self.assertEqual(
            projection["brokered_mcps"], ["chrono-vault", "sequential-thinking"]
        )
        self.assertEqual(
            projection["tools"], ["read_file", "run_shell_command"]
        )

    def test_live_inventory_parsers_normalize_native_names_and_status(self) -> None:
        claude = parse_live_mcp_listing(
            lane="claude",
            output=(
                "Checking MCP server health…\n"
                "claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected\n"
                "claude.ai Google Calendar: https://calendarmcp.googleapis.com/mcp/v1 - ✔ Connected\n"
                "claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected\n"
                "plugin:chrono-vault:chrono-vault: /bin/tool - ✔ Connected\n"
                "plugin:chrono-recon:chrono-recon: /bin/tool - ! Needs authentication\n"
                "sequential-thinking: /bin/tool - ⏸ Pending approval (run `claude` to approve)\n"
            ),
        )
        self.assertEqual(
            claude["chrono-vault"]["live_name"],
            "plugin:chrono-vault:chrono-vault",
        )
        self.assertIn("Needs authentication", claude["chrono-recon"]["status"])
        self.assertIn(
            "Pending approval", claude["sequential-thinking"]["status"]
        )
        self.assertEqual(
            claude["claude-ai-google-drive"]["live_name"],
            "claude.ai Google Drive",
        )
        self.assertEqual(
            claude["claude-ai-google-calendar"]["live_name"],
            "claude.ai Google Calendar",
        )
        self.assertEqual(
            claude["claude-ai-gmail"]["live_name"],
            "claude.ai Gmail",
        )
        self.assertEqual(
            claude["claude-ai-google-drive"]["tool_namespace"],
            "claude_ai_Google_Drive",
        )
        self.assertEqual(
            claude["claude-ai-google-calendar"]["tool_namespace"],
            "claude_ai_Google_Calendar",
        )
        self.assertEqual(
            claude["claude-ai-gmail"]["tool_namespace"],
            "claude_ai_Gmail",
        )

        gemini = parse_live_mcp_listing(
            lane="gemini",
            output=(
                "Configured MCP servers:\n"
                "✓ chrono-vault: /bin/tool (stdio) - Connected\n"
                "✓ stitch (from Stitch): https://example.invalid/mcp (http) - Connected\n"
            ),
        )
        self.assertEqual(set(gemini), {"chrono-vault", "stitch"})
        self.assertEqual(gemini["stitch"]["live_name"], "stitch")

    def test_claude_live_inventory_rejects_ambiguous_plugin_names(self) -> None:
        with self.assertRaisesRegex(CapabilityDenied, "ambiguous"):
            parse_live_mcp_listing(
                lane="claude",
                output=(
                    "Checking MCP server health…\n"
                    "plugin:first:shared: /bin/one - ✔ Connected\n"
                    "plugin:second:shared: /bin/two - ✔ Connected\n"
                ),
            )

    def test_claude_live_inventory_rejects_unknown_first_party_rows(self) -> None:
        with self.assertRaisesRegex(CapabilityDenied, "unsafe server name"):
            parse_live_mcp_listing(
                lane="claude",
                output=(
                    "Checking MCP server health…\n"
                    "claude.ai Google Docs: https://example.invalid/mcp - ✔ Connected\n"
                ),
            )

    def test_claude_live_inventory_rejects_tool_namespace_collisions(self) -> None:
        with self.assertRaisesRegex(CapabilityDenied, "ambiguous tool namespace"):
            parse_live_mcp_listing(
                lane="claude",
                output=(
                    "Checking MCP server health…\n"
                    "claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected\n"
                    "claude_ai_Gmail: /bin/tool - ✔ Connected\n"
                ),
            )

    def test_claude_live_inventory_rejects_hosted_logical_name_collisions(
        self,
    ) -> None:
        with self.assertRaisesRegex(CapabilityDenied, "ambiguous server name"):
            parse_live_mcp_listing(
                lane="claude",
                output=(
                    "Checking MCP server health…\n"
                    "claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected\n"
                    "claude-ai-google-drive: /bin/tool - ✔ Connected\n"
                ),
            )

    def test_live_inventory_parsers_reject_missing_headers_and_drifted_rows(
        self,
    ) -> None:
        with self.assertRaisesRegex(CapabilityDenied, "header is missing"):
            parse_live_mcp_listing(
                lane="gemini",
                output="✓ chrono-vault: /bin/tool (stdio) - Connected\n",
            )
        with self.assertRaisesRegex(CapabilityDenied, "unparseable row"):
            parse_live_mcp_listing(
                lane="claude",
                output=(
                    "Checking MCP server health…\n"
                    "plugin:chrono-vault:chrono-vault changed format\n"
                ),
            )

    def test_claude_enabled_plugin_inventory_is_fail_closed(self) -> None:
        self.assertEqual(
            parse_claude_enabled_plugins(
                json.dumps(
                    [
                        {
                            "id": "firecrawl@claude-plugins-official",
                            "enabled": True,
                        },
                        {
                            "id": "disabled@claude-plugins-official",
                            "enabled": False,
                        },
                    ]
                )
            ),
            ("firecrawl",),
        )
        with self.assertRaisesRegex(CapabilityDenied, "wrong schema"):
            parse_claude_enabled_plugins("{}")
        self.assertEqual(
            parse_claude_project_plugin_dirs(
                json.dumps(
                    [
                        {
                            "id": "chrono-media-studio@claude-vibe-squad",
                            "enabled": True,
                            "scope": "project",
                            "installPath": "/tmp/chrono-media-studio",
                        }
                    ]
                )
            ),
            {"chrono-media-studio": "/tmp/chrono-media-studio"},
        )

    def test_claude_emits_plugin_aware_mcp_tool_denials(self) -> None:
        projection = {
            "lane": "claude",
            "specialist": "sample",
            "mcps": ["chrono-vault"],
            "brokered_mcps": [],
            "tools": [],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        configured = {
            "chrono-vault": {
                "live_name": "plugin:chrono-vault:chrono-vault",
                "tool_namespace": "plugin_chrono-vault_chrono-vault",
                "status": "✔ Connected",
            },
            "chrono-recon": {
                "live_name": "plugin:chrono-recon:chrono-recon",
                "tool_namespace": "plugin_chrono-recon_chrono-recon",
                "status": "✔ Connected",
            },
            "sequential-thinking": {
                "live_name": "sequential-thinking",
                "tool_namespace": "sequential-thinking",
                "status": "✔ Connected",
            },
            "claude-ai-gmail": {
                "live_name": "claude.ai Gmail",
                "tool_namespace": "claude_ai_Gmail",
                "status": "✔ Connected",
            },
            "claude-ai-google-drive": {
                "live_name": "claude.ai Google Drive",
                "tool_namespace": "claude_ai_Google_Drive",
                "status": "✔ Connected",
            },
            "claude-ai-google-calendar": {
                "live_name": "claude.ai Google Calendar",
                "tool_namespace": "claude_ai_Google_Calendar",
                "status": "✔ Connected",
            },
        }
        plan = plan_lane(
            lane="claude",
            projection=projection,
            configured_servers=configured,
        )
        self.assertEqual(plan.authorized_mcps, ("chrono-vault",))
        self.assertEqual(
            plan.disabled_mcps,
            (
                "chrono-recon",
                "claude-ai-gmail",
                "claude-ai-google-calendar",
                "claude-ai-google-drive",
                "sequential-thinking",
            ),
        )
        self.assertIsNone(plan.role_config_json)
        self.assertEqual(
            plan.capability_enforcement,
            "claude-cli-disallowed-mcp-tools/v1",
        )
        self.assertEqual(
            plan.cli_args,
            (
                "--disallowedTools",
                (
                    "mcp__plugin_chrono-recon_chrono-recon__*,"
                    "mcp__claude_ai_Gmail__*,"
                    "mcp__claude_ai_Google_Calendar__*,"
                    "mcp__claude_ai_Google_Drive__*,"
                    "mcp__sequential-thinking__*"
                ),
            ),
        )

    def test_claude_requires_an_usable_live_status_for_authorized_mcp(self) -> None:
        projection = {
            "lane": "claude",
            "specialist": "sample",
            "mcps": ["chrono-recon"],
            "brokered_mcps": [],
            "tools": [],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        with self.assertRaisesRegex(CapabilityDenied, "unavailable MCP servers"):
            plan_lane(
                lane="claude",
                projection=projection,
                configured_servers={
                    "chrono-recon": {
                        "live_name": "plugin:chrono-recon:chrono-recon",
                        "status": "! Needs authentication",
                    }
                },
            )

    def test_gemini_emits_native_allowed_server_array(self) -> None:
        projection = {
            "lane": "gemini",
            "specialist": "ui-engineer",
            "mcps": ["chrome-devtools", "playwright"],
            "brokered_mcps": [],
            "tools": ["read_file"],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        configured = {
            "playwright": {"command": "/usr/bin/false"},
            "chrome-devtools": {"command": "/usr/bin/false"},
            "unrelated": {"command": "/usr/bin/false"},
        }
        plan = plan_lane(
            lane="gemini",
            projection=projection,
            configured_servers=configured,
        )
        self.assertEqual(
            plan.cli_args,
            (
                "--allowed-mcp-server-names",
                "chrome-devtools",
                "playwright",
                "--allowed-tools",
                "read_file",
            ),
        )
        self.assertEqual(plan.disabled_mcps, ("unrelated",))
        self.assertEqual(
            plan.capability_enforcement, "gemini-cli-allowed-mcp-names/v1"
        )
        self.assertEqual(plan.available_tools, ("read_file",))

    def test_gemini_project_server_stays_native_and_cli_scoped(self) -> None:
        projection = {
            "lane": "gemini",
            "specialist": "ui-engineer",
            "mcps": ["playwright"],
            "brokered_mcps": [],
            "tools": [],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        server_config = {"command": "/usr/bin/false", "args": []}
        plan = plan_lane(
            lane="gemini",
            projection=projection,
            configured_servers={
                "playwright": {
                    "live_name": "playwright",
                    "status": "Connected",
                    "project_config": server_config,
                }
            },
        )
        self.assertIsNone(plan.role_config_json)
        self.assertEqual(
            plan.cli_args,
            ("--allowed-mcp-server-names", "playwright"),
        )

    def test_kimi_file_config_suppresses_global_servers_and_keeps_lead_mcps_brokered(
        self,
    ) -> None:
        projection = {
            "lane": "kimi",
            "specialist": "summarizer",
            "mcps": [],
            "brokered_mcps": ["chrono-vault", "sequential-thinking"],
            "tools": [],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        configured = {
            "chrono-vault": {"command": "/usr/bin/false"},
            "sequential-thinking": {"command": "/usr/bin/false"},
        }
        plan = plan_lane(
            lane="kimi",
            projection=projection,
            configured_servers=configured,
        )
        self.assertEqual(json.loads(plan.role_config_json), {"mcpServers": {}})
        self.assertEqual(
            plan.cli_args, ("--mcp-config-file", "__ROLE_MCP_CONFIG__")
        )
        self.assertEqual(
            plan.capability_enforcement, "kimi-cli-config-scoped/v1"
        )
        self.assertEqual(
            plan.brokered_mcps, ("chrono-vault", "sequential-thinking")
        )
        self.assertEqual(
            plan.disabled_mcps, ("chrono-vault", "sequential-thinking")
        )

    def test_every_lane_fails_closed_on_missing_authorized_mcp(self) -> None:
        for lane in ("codex", "claude", "gemini", "kimi"):
            with self.subTest(lane=lane):
                projection = {
                    "lane": lane,
                    "specialist": "sample",
                    "mcps": ["missing-server"],
                    "brokered_mcps": [],
                    "tools": [],
                    "skills": [],
                    "sources": [],
                    "schema": "role-capability-projection/v1",
                }
                with self.assertRaisesRegex(
                    CapabilityDenied, "unavailable MCP servers"
                ):
                    plan_lane(
                        lane=lane,
                        projection=projection,
                        configured_servers={},
                    )

    def test_local_tool_names_and_availability_fail_closed(self) -> None:
        unsafe = {
            "lane": "claude",
            "specialist": "sample",
            "mcps": [],
            "brokered_mcps": [],
            "tools": ["bad tool"],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        with self.assertRaisesRegex(CapabilityDenied, "unsafe local tool"):
            plan_lane(
                lane="claude",
                projection=unsafe,
                configured_servers={},
            )

        missing = dict(unsafe)
        missing["tools"] = ["semgrep"]
        with self.assertRaisesRegex(CapabilityDenied, "unavailable local tools"):
            plan_lane(
                lane="claude",
                projection=missing,
                configured_servers={},
                tool_lookup=lambda _name: None,
            )

    def test_materialized_config_is_worktree_local_and_owner_only(self) -> None:
        projection = {
            "lane": "kimi",
            "specialist": "sample",
            "mcps": [],
            "brokered_mcps": [],
            "tools": [],
            "skills": [],
            "sources": [],
            "schema": "role-capability-projection/v1",
        }
        plan = plan_lane(
            lane="kimi",
            projection=projection,
            configured_servers={},
        )
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory)
            path = materialize_role_config(
                plan,
                worktree_root=worktree,
                task_id="TASK-2026-07-22-0705-lane-capability-wiring",
                attempt_id="d-" + "1" * 32,
            )
            self.assertEqual(json.loads(path.read_text()), {"mcpServers": {}})
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                0o600,
            )
            self.assertTrue(path.is_relative_to(worktree.resolve()))
            self.assertEqual(
                cli_args_for_materialized(plan, path),
                ("--mcp-config-file", str(path)),
            )

    @skip_in_host_independent_ci(
        "runs installed Claude and Gemini CLIs against live MCP/plugin inventory"
    )
    def test_all_real_claude_and_gemini_adapters_plan_from_live_inventory(
        self,
    ) -> None:
        cases = (
            (
                "claude",
                Path(seatbelt_profile.LANE_CLI_PATHS["claude"]),
                ROOT / "model-lanes/claude/.claude/agents",
            ),
            (
                "gemini",
                Path("/opt/homebrew/bin/gemini"),
                ROOT / "model-lanes/gemini/.gemini/agents",
            ),
        )
        for lane, executable, adapter_root in cases:
            with self.subTest(lane=lane):
                completed = subprocess.run(
                    [str(executable), "mcp", "list"],
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=str(ROOT / "model-lanes" / lane),
                    timeout=30,
                    env={
                        key: value
                        for key, value in {
                            **os.environ,
                            "NO_COLOR": "1",
                        }.items()
                        if lane != "claude"
                        or key
                        not in {
                            "ANTHROPIC_API_KEY",
                            "CLAUDECODE",
                            "CLAUDE_CODE_CHILD_SESSION",
                            "CLAUDE_CODE_ENTRYPOINT",
                            "CLAUDE_CODE_EXECPATH",
                            "CLAUDE_CODE_SESSION_ID",
                        }
                    },
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                configured = parse_live_mcp_listing(
                    lane=lane,
                    output=(
                        completed.stdout if lane == "claude" else completed.stderr
                    ),
                )
                project_config_path = (
                    ROOT / "model-lanes/claude/.mcp.json"
                    if lane == "claude"
                    else ROOT / "model-lanes/gemini/.gemini/settings.json"
                )
                project_servers = load_json_mcp_servers(project_config_path)
                self.assertFalse(set(project_servers) - set(configured))
                for name, config in project_servers.items():
                    configured[name]["project_config"] = config
                native_tools = set(configured)
                if lane == "claude":
                    plugins = subprocess.run(
                        [str(executable), "plugin", "list", "--json"],
                        check=False,
                        capture_output=True,
                        text=True,
                        cwd=str(ROOT / "model-lanes" / lane),
                        timeout=30,
                        env={
                            key: value
                            for key, value in {
                                **os.environ,
                                "NO_COLOR": "1",
                            }.items()
                            if key
                            not in {
                                "ANTHROPIC_API_KEY",
                                "CLAUDECODE",
                                "CLAUDE_CODE_CHILD_SESSION",
                                "CLAUDE_CODE_ENTRYPOINT",
                                "CLAUDE_CODE_EXECPATH",
                                "CLAUDE_CODE_SESSION_ID",
                            }
                        },
                    )
                    self.assertEqual(plugins.returncode, 0, plugins.stderr)
                    native_tools.update(
                        parse_claude_enabled_plugins(plugins.stdout)
                    )
                adapters = sorted(
                    path
                    for path in adapter_root.glob("*.md")
                    if path.name != "README.md"
                )
                if lane == "claude":
                    self.assertEqual(len(adapters), 71)
                else:
                    self.assertEqual(len(adapters), 26)
                planned = 0
                for adapter in adapters:
                    projection = load_projection(
                        lane=lane,
                        specialist=adapter.stem,
                        adapter_path=adapter,
                        overlay_path=adapter,
                    )
                    plan_lane(
                        lane=lane,
                        projection=projection,
                        configured_servers=configured,
                        tool_lookup=lambda name: (
                            name if name in native_tools else shutil.which(name)
                        ),
                    )
                    planned += 1
                self.assertEqual(planned, len(adapters))


if __name__ == "__main__":
    unittest.main()
