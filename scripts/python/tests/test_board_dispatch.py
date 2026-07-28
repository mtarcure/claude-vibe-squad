from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "python"))
from lane_capability_enforcement import (  # noqa: E402
    CapabilityDenied,
    parse_live_mcp_listing,
    plan_lane,
)
from dispatch_context_builder import (  # noqa: E402
    build_board_fanout_members,
    prepare_worktree_outputs,
    publish_prepared_worktree_outputs,
    schedule_board_batch,
)
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)

SEND_TASK = ROOT / "bin" / "send-task.sh"
SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"


class BoardDispatchShellTests(unittest.TestCase):
    def test_shell_entrypoints_are_syntax_valid(self) -> None:
        for script in (SEND_TASK, SUPERVISOR):
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    ["bash", "-n", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_unset_mode_and_explicit_pane_have_identical_dry_run_behavior(self) -> None:
        packet = """---
id: TASK-2026-07-23-9994-dryrun
to_model: gpt-codex
specialist: systems-engineer
source_namespace: coding
mode: project
run_id: PROJ-SWARM-READY-2026-07-19
result_type: normal
write_scope: [_state/dryrun/]
parallel_safe: true
direct_lane_work_allowed: true
mandatory_review: false
review_model: none
return_artifact: _state/dryrun/ok.md
---

Dry-run dispatch test only.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.md"
            path.write_text(packet, encoding="utf-8")
            base_env = os.environ.copy()
            base_env["VAULT_ROOT"] = str(ROOT)
            unset_env = dict(base_env)
            unset_env.pop("SQUAD_DISPATCH_MODE", None)
            pane_env = dict(base_env)
            pane_env["SQUAD_DISPATCH_MODE"] = "pane"
            unset = subprocess.run(
                ["bash", str(SEND_TASK), str(path), "--dry-run"],
                env=unset_env,
                capture_output=True,
                text=True,
                check=False,
            )
            pane = subprocess.run(
                ["bash", str(SEND_TASK), str(path), "--dry-run"],
                env=pane_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(unset.returncode, 2, unset.stderr)
            self.assertEqual(pane.returncode, 2, pane.stderr)
            self.assertEqual(unset.stdout, pane.stdout)
            self.assertEqual(unset.stderr, pane.stderr)

    def test_dispatch_mode_defaults_to_board_pane_is_rollback(self) -> None:
        text = SEND_TASK.read_text(encoding="utf-8")
        # Phase 3 cutover: fresh-CLI board dispatch is now the default; pane remains
        # as an explicit rollback path (SQUAD_DISPATCH_MODE=pane).
        self.assertIn('SQUAD_DISPATCH_MODE="${SQUAD_DISPATCH_MODE:-board}"', text)
        self.assertIn('case "$SQUAD_DISPATCH_MODE" in', text)
        self.assertIn('[sys.argv[1], "detached-launch", *sys.argv[2:]]', text)
        self.assertIn("start_new_session=True", text)
        self.assertIn('"event": "board-claimed"', text)
        self.assertIn('RESPONSE_MIN_AGE_SECONDS=0', text)
        self.assertIn('settlement-error', text)
        self.assertIn('receipt_path', text)
        self.assertNotIn('supervisor_output="$(timeout', text)
        self.assertNotIn("nohup bash -c", text)
        self.assertIn('"$SQUAD_DISPATCH_MODE" == "pane"', text)
        self.assertIn('"delivery_attempt_id"', text)
        self.assertIn('"delivery_generation"', text)

    def test_board_batch_scheduler_admits_only_disjoint_scopes(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "_state") as directory:
            root = Path(directory)
            packets = []
            for index, scope in enumerate(
                ("_state/batch/a/", "_state/batch/b/", "_state/batch/a/")
            ):
                packet = root / f"packet-{index}.md"
                packet.write_text(
                    "---\n"
                    f"id: TASK-2026-07-23-99{index}0-batch-member\n"
                    f"write_scope: [{scope}]\n"
                    "read_scope: []\n"
                    "parallel_safe: true\n"
                    "---\n",
                    encoding="utf-8",
                )
                packets.append(packet)
            result = schedule_board_batch(
                ROOT,
                packets,
                concurrency=3,
                logical_only=True,
            )
            self.assertEqual(len(result.run_now), 2)
            self.assertEqual(len(result.must_wait), 1)
            self.assertIn("scope collision", next(iter(result.reasons.values())))

    @skip_in_host_independent_ci("needs the live board-dispatch state root")
    def test_board_fanout_builds_twelve_unique_isolated_members(self) -> None:
        task_id = "TASK-2026-07-23-9979-fanout-build"
        with tempfile.TemporaryDirectory(dir=ROOT / "_state") as source_directory:
            source = Path(source_directory) / "parent.md"
            source.write_text(
                "---\n"
                f"id: {task_id}\n"
                "to_model: gpt-codex\n"
                "specialist: systems-engineer\n"
                "source_namespace: coding\n"
                "mode: project\n"
                "run_id: PROJ-SWARM-READY-2026-07-19\n"
                "write_scope: [_state/fanout-parent/]\n"
                "return_artifact: _state/fanout-parent/result.md\n"
                "---\n\nParent objective.\n",
                encoding="utf-8",
            )
            with tempfile.TemporaryDirectory(
                dir=ROOT / "_state" / "board-dispatch"
            ) as holder:
                output = Path(holder) / "members"
                packets = build_board_fanout_members(
                    ROOT,
                    source,
                    output,
                    [f"assignment {index}" for index in range(12)],
                    verification_contract={
                        "contract_version": "verification-contract/v1",
                        "task_id": task_id,
                        "run_id": "PROJ-SWARM-READY-2026-07-19",
                        "mode": "project",
                    },
                )
                self.assertEqual(len(packets), 12)
                self.assertEqual(len({packet.name for packet in packets}), 12)
                for index, packet in enumerate(packets, start=1):
                    text = packet.read_text(encoding="utf-8")
                    self.assertIn(f"fanout_member_id: member-{index}", text)
                    self.assertIn(
                        f"/member-{index}/]",
                        text,
                    )

    def test_board_completion_captures_memory_best_effort(self) -> None:
        builder = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        # Schema-complete, one-attempt memory (Sol context-diag fix): give the exact
        # valid record shape up front so the model doesn't burn extra turns on invalid
        # filters / repo schema-searches / retries. Memory is now BEST-EFFORT and never a
        # gate; record_usage is removed (its undeclared enum hard-blocked whole tasks — 2026-07-24).
        self.assertIn('record(note_type="learning", fields=', builder)
        self.assertIn('"source_task"', builder)
        self.assertIn("the repo for schemas and do NOT retry", builder)
        self.assertIn("Recall prior context ONCE", builder)
        self.assertIn("BEST-EFFORT", builder)
        self.assertIn("Do NOT call `record_usage`", builder)
        self.assertIn("memory id in the artifact", builder)
        self.assertNotIn("record one concise durable outcome in chrono-vault", builder)
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("observed_memory_ids", supervisor)
        # memory capture is best-effort, NOT a completion gate (SOL/Fable Phase-2 fix):
        # the block is gone; a missing memory id yields learning_status=degraded, not blocked.
        self.assertNotIn("completion lacks one verified chrono-vault record id", supervisor)
        self.assertIn(
            'learning_status = "captured" if completion_memory_id else "degraded"',
            supervisor,
        )
        self.assertIn('"learning_status": globals().get("learning_status"', supervisor)
        self.assertIn('"memory_id": globals().get("completion_memory_id")', supervisor)
        self.assertIn('tool == "record" or tool.endswith("__record")', supervisor)

    def test_board_supervisor_removes_inbox_packet_on_success(self) -> None:
        # F3.2 transport XOR: a successful board dispatch removes its own pane-inbox
        # packet supervisor-side (send-task must NOT — it races the detached supervisor
        # which reads the packet as its authenticated launch file).
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("packet_path.unlink()", supervisor)
        self.assertIn("terminally settled successfully", supervisor)
        sender = SEND_TASK.read_text(encoding="utf-8")
        # send-task must not carry a post-detach rm of the inbox packet
        self.assertNotIn('rm -f "$DEST"', sender)

    def test_board_swarm_and_fanout_use_fresh_child_transport(self) -> None:
        sender = SEND_TASK.read_text(encoding="utf-8")
        self.assertIn("schedule-batch", sender)
        self.assertIn("BOARD_PRE_REGISTERED=1 SQUAD_DISPATCH_MODE=board", sender)
        self.assertIn("BOARD_FANOUT_CHILD_IDS_CSV", sender)
        self.assertIn("Board fan-out detached", sender)
        self.assertIn("PANEL_LIMIT=12", sender)
        self.assertIn('board_host_admit_batch "$PANEL_COUNT"', sender)
        self.assertIn('board_host_admit_batch "$SWARM_COUNT"', sender)
        self.assertIn("--requested-workers", sender)
        self.assertIn("Board fan-out collected", sender)
        self.assertIn("member-results.md", sender)
        self.assertNotIn(
            '&& { $PANEL_ENABLED || $SWARM_ENABLED || $SUBSWARM_ENABLED; }',
            sender,
        )
        builder = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        # deadline is a safety backstop (30 min), not a short kill-deadline — Chrono
        # supervises live and cancels stuck spawns instead of a premature timeout.
        self.assertIn('"timeout_seconds": 1800', builder)
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("worktree_autocleaned=", supervisor)
        self.assertIn("-fanout-member-", supervisor)
        self.assertIn("worktree remove --force", supervisor)

    def test_detached_failure_is_captured_in_receipt_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "board.log"
            receipt = root / "board.receipt.json"
            marker = root / "settlement-error"
            missing_context = root / "missing-context.json"
            log.touch()
            receipt.touch()
            completed = subprocess.run(
                [
                    "bash",
                    str(SUPERVISOR),
                    "detached-launch",
                    str(missing_context),
                    str(log),
                    str(receipt),
                    str(marker),
                    "/usr/bin/false",
                    str(root),
                    "TASK-2026-07-23-9993-capture-failure",
                    "codex",
                    "_state/capture-failure/result.md",
                    "coding",
                    "/usr/bin/false",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            expected = "trusted-launch context file missing"
            self.assertEqual(completed.returncode, 70)
            self.assertIn(expected, receipt.read_text(encoding="utf-8"))
            self.assertIn(expected, log.read_text(encoding="utf-8"))
            self.assertGreater(receipt.stat().st_size, 0)
            self.assertGreater(log.stat().st_size, 0)
            self.assertTrue(marker.is_file())
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["status"], "denied")

    def test_detached_runner_streams_then_fsyncs_both_evidence_files(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        detached = text.index('if [[ "${1:-}" == "detached-launch" ]]')
        trusted = text.index('if [[ "${1:-}" == "trusted-launch" ]]')
        body = text[detached:trusted]
        launch = body.index('"$timeout_bin" --kill-after=30 1860')
        transcript_fd = body.index('exec 4>>"$log_path"')
        receipt = body.index('>"$receipt_path" 2>&1')
        status = body.index("supervisor_rc=$?")
        fsync = body.index("os.fsync(descriptor)")
        settlement = body.index('"$context_builder" blocked')
        self.assertLess(transcript_fd, launch)
        self.assertLess(launch, receipt)
        self.assertLess(receipt, status)
        self.assertLess(status, fsync)
        self.assertLess(fsync, settlement)
        self.assertNotIn("/usr/bin/tee", body)
        self.assertIn('receipt.get("task_id") != expected_task', body)
        self.assertIn('receipt.get("attempt_id") != expected_attempt', body)

    def test_trusted_launch_has_bounded_private_child_transcript_channel(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        helper = text.index("def write_board_transcript(stdout, stderr):")
        completed = text.index(
            'write_board_transcript(completed.stdout or "", completed.stderr or "")'
        )
        nonzero = text.index("if completed.returncode != 0:", completed)
        self.assertLess(helper, completed)
        self.assertLess(completed, nonzero)
        self.assertIn('limit = 1024 * 1024', text[helper:completed])
        self.assertIn("os.fsync(descriptor)", text[helper:completed])

    def test_claude_global_live_mcp_is_available_only_when_healthy(self) -> None:
        connected = parse_live_mcp_listing(
            lane="claude",
            output=(
                "Checking MCP server health…\n"
                "sequential-thinking: /opt/homebrew/bin/"
                "mcp-server-sequential-thinking - ✔ Connected\n"
            ),
        )
        projection = {
            "mcps": ["sequential-thinking"],
            "brokered_mcps": [],
            "tools": [],
        }
        plan = plan_lane(
            lane="claude",
            projection=projection,
            configured_servers=connected,
        )
        self.assertEqual(plan.authorized_mcps, ("sequential-thinking",))
        self.assertIsNone(plan.role_config_json)

        failed = parse_live_mcp_listing(
            lane="claude",
            output=(
                "Checking MCP server health…\n"
                "sequential-thinking: /opt/homebrew/bin/"
                "mcp-server-sequential-thinking - ✘ Failed to connect\n"
            ),
        )
        with self.assertRaisesRegex(
            CapabilityDenied,
            r"sequential-thinking \(✘ Failed to connect\)",
        ):
            plan_lane(
                lane="claude",
                projection=projection,
                configured_servers=failed,
            )

    def test_detached_runner_propagates_original_trusted_host_path(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        capture = text.index(
            'trusted_host_path="${TRUSTED_HOST_PATH:-${PATH:-'
        )
        narrow = text.index('PATH="/usr/bin:/bin:/usr/sbin:/sbin"')
        detached = text.index('if [[ "${1:-}" == "detached-launch" ]]')
        handoff = text.index(
            'TRUSTED_HOST_PATH="$trusted_host_path" BOARD_TRANSCRIPT_FD=4',
            detached,
        )
        trusted = text.index('if [[ "${1:-}" == "trusted-launch" ]]')
        python_handoff = text.index(
            'TRUSTED_HOST_PATH="$trusted_host_path"',
            trusted,
        )
        self.assertLess(capture, narrow)
        self.assertLess(detached, handoff)
        self.assertLess(handoff, trusted)
        self.assertLess(trusted, python_handoff)

    def test_trusted_worker_keeps_keychain_identity_not_api_keys(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        environment = text.index("def trusted_worker_environment(worker_lane):")
        projection = text.index("capability_projection = {", environment)
        body = text[environment:projection]
        self.assertIn('"USER", "LOGNAME"', body)
        self.assertIn('if worker_lane == "gemini":', body)
        self.assertIn(
            'environment["GEMINI_API_KEY"] = load_gemini_api_key()',
            body,
        )
        self.assertIn('"ANTHROPIC_API_KEY"', body)
        self.assertIn('"OPENAI_API_KEY"', body)
        self.assertIn('"GOOGLE_API_KEY"', body)
        self.assertIn("environment.pop(key, None)", body)
        self.assertNotIn('environment["ANTHROPIC_API_KEY"] =', body)
        self.assertNotIn('environment["OPENAI_API_KEY"] =', body)
        self.assertNotIn('environment["GOOGLE_API_KEY"] =', body)

    def test_gemini_parser_ignores_only_known_residual_auth_diagnostics(self) -> None:
        parsed = parse_live_mcp_listing(
            lane="gemini",
            output=(
                "Configured MCP servers:\n"
                "Error authenticating with Gemini API\n"
                "✓ perplexity: uvx perplexity-mcp (stdio) - Connected\n"
                "✗ optional: uvx optional-mcp (stdio) - Disconnected\n"
            ),
        )
        self.assertEqual(set(parsed), {"perplexity", "optional"})
        self.assertEqual(parsed["optional"]["status"], "Disconnected")
        with self.assertRaisesRegex(CapabilityDenied, "optional \\(Disconnected\\)"):
            plan_lane(
                lane="gemini",
                projection={
                    "mcps": ["optional"],
                    "brokered_mcps": [],
                    "tools": [],
                },
                configured_servers=parsed,
            )
        with self.assertRaisesRegex(CapabilityDenied, "unparseable row"):
            parse_live_mcp_listing(
                lane="gemini",
                output=(
                    "Configured MCP servers:\n"
                    "unexpected diagnostic\n"
                    "✓ perplexity: uvx perplexity-mcp (stdio) - Connected\n"
                ),
            )

    def test_gemini_and_kimi_match_proven_launcher_contract(self) -> None:
        builder = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn('"gemini": "gemini-3.6-flash"', builder)
        self.assertIn('"kimi": "kimi-code/kimi-for-coding"', builder)
        self.assertIn('"--yolo",\n        "--thinking"', builder)
        self.assertIn(
            'str(handle.worktree_root / "model-lanes" / "kimi" / "main.yaml")',
            supervisor,
        )
        self.assertIn('"--add-dir",\n            str(handle.worktree_root)', supervisor)
        self.assertIn("def kimi_role_launcher(", supervisor)
        self.assertIn("concise_prompt = (", supervisor)
        self.assertIn(
            "base_kimi_prompt.rstrip()",
            supervisor,
        )
        self.assertIn("def gemini_ordered_launcher(", supervisor)
        self.assertIn("base_gemini_prompt.rstrip()", supervisor)
        self.assertIn('"--output-format",\n            "stream-json"', supervisor)
        self.assertIn('"--print",\n            "--output-format"', supervisor)
        self.assertIn(
            '30 <= budgets["timeout_seconds"] <= 1800',
            supervisor,
        )
        self.assertIn(
            '"--include-directories",\n            str(handle.worktree_root)',
            supervisor,
        )

    def test_codex_worker_gets_only_derived_linked_git_commit_dirs(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        codex = text.index('lane == "codex"')
        integration = text.index("wti.integrate_worktree_commits(")
        body = text[codex:integration]
        self.assertIn("wti.linked_worktree_commit_write_dirs(handle)", body)
        self.assertIn('("--add-dir", str(git_write_dir))', body)
        self.assertNotIn('("--add-dir", str(repo_path))', body)

    def test_board_canary_cleanup_is_explicit_and_tightly_scoped(self) -> None:
        builder = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"board_canary_autoclean"', builder)
        self.assertIn('task_id.endswith("-board-inventory-canary")', builder)
        self.assertIn('write_paths[0].startswith("_state/board-canary-")', builder)
        self.assertIn("packet_path.unlink()", builder)
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        reconcile = supervisor.index(
            'env RESPONSE_MIN_AGE_SECONDS=0 "$reconciler"'
        )
        cleanup = supervisor.index('"$context_builder" cleanup-canary', reconcile)
        self.assertLess(reconcile, cleanup)

    def test_supervisor_rehashes_packet_and_commits_envelope_last(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("trusted_lane_args_for", text)
        closure = text.index(
            'board_dispatch_context = trusted_context and execution_kind == "lane"'
        )
        lane_args = text.index("controller_lane_args = trusted_lane_args_for(", closure)
        model = text.index("controller_model_sha256 = selected_model_sha256_for(", closure)
        packet = text.index("packet_scope_pattern = re.compile(", closure)
        timeout = text.index("launch_timeout = float(budgets", closure)
        self.assertLess(closure, lane_args)
        self.assertLess(closure, model)
        self.assertLess(closure, packet)
        self.assertLess(closure, timeout)
        self.assertIn(
            'deny("inbox packet content does not match authenticated authority")',
            text,
        )
        self.assertIn("publish_prepared_worktree_outputs(", text)
        prevalidate_offset = text.index("prepare_worktree_outputs(")
        integration_offset = text.index("wti.integrate_worktree_commits(")
        bridge_offset = text.index(
            "bridge_receipt = publish_prepared_worktree_outputs("
        )
        receipt_offset = text.index(
            '"status": "launched"',
            bridge_offset,
        )
        self.assertLess(prevalidate_offset, integration_offset)
        self.assertLess(integration_offset, bridge_offset)
        self.assertLess(bridge_offset, receipt_offset)
        self.assertIn('"worktree_integration": asdict(integration_receipt)', text)

    def test_prepared_completion_publishes_the_exact_preintegration_bytes(self) -> None:
        task_id = "TASK-2026-07-23-9984-prepared-output"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worker = root / "worker"
            repo.mkdir()
            worker.mkdir()
            result_relative = "_state/prepared/result.md"
            outbox_relative = (
                "departments/coding/outbox/"
                f"{task_id}-response.md"
            )
            worker_result = worker / result_relative
            worker_envelope = worker / outbox_relative
            worker_result.parent.mkdir(parents=True)
            worker_envelope.parent.mkdir(parents=True)
            worker_result.write_text("captured result\n", encoding="utf-8")
            worker_envelope.write_text(
                "---\n"
                f"id: {task_id}-response\n"
                f"in_response_to: {task_id}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                f"return_artifact: {result_relative}\n"
                "---\n\n"
                "Captured summary.\n",
                encoding="utf-8",
            )
            authority = {
                "task_id": task_id,
                "lane": "codex",
                "write_paths": ["_state/prepared/"],
                "expected_result_path": result_relative,
                "expected_outbox_path": outbox_relative,
            }

            prepared = prepare_worktree_outputs(repo, worker, authority)
            worker_result.write_text("mutated result\n", encoding="utf-8")
            worker_envelope.write_text("mutated envelope\n", encoding="utf-8")
            receipt = publish_prepared_worktree_outputs(repo, prepared)

            self.assertEqual(
                (repo / result_relative).read_text(encoding="utf-8"),
                "captured result\n",
            )
            self.assertIn(
                "Captured summary.",
                (repo / outbox_relative).read_text(encoding="utf-8"),
            )
            self.assertEqual(receipt["status"], "complete")


if __name__ == "__main__":
    unittest.main()
