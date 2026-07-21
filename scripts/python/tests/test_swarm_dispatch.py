from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = ROOT / "bin" / "send-task.sh"


class SwarmDispatchTests(unittest.TestCase):
    def subswarm_directive(self, assignments: tuple[str, str]) -> Path:
        members = []
        for index, assignment in enumerate(assignments, 1):
            members.append(
                {
                    "member_id": f"gpt-codex:sub{index:02d}",
                    "lane": "gpt-codex",
                    "replica_index": index,
                    "role": "auditor",
                    "objective_sha256": hashlib.sha256(assignment.encode()).hexdigest(),
                    "output_path": f"_state/subswarm/TASK-2026-07-18-9999-swarm-test/gpt-codex/sub{index:02d}/result.json",
                    "requires_mcp": False,
                    "tool_mode": "none",
                    "depends_on": [],
                }
            )
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        )
        with handle:
            json.dump(
                {
                    "schema_version": "lead-orchestration-directive/v1",
                    "parent_task_id": "TASK-2026-07-18-9999-swarm-test",
                    "lane": "gpt-codex",
                    "mode": "parallel",
                    "max_concurrency": 2,
                    "members": members,
                },
                handle,
            )
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def packet(
        self,
        *,
        write_scope: str = "[]",
        specialist: str = "exploit-developer",
        to_model: str = "gpt-codex",
        source_namespace: str = "security",
        compatibility_namespace: str | None = "security",
        review_model: str = "claude",
    ) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        )
        with handle:
            compatibility_line = (
                f"compatibility_namespace: {compatibility_namespace}\n"
                if compatibility_namespace is not None
                else ""
            )
            handle.write(
                f"""---
id: TASK-2026-07-18-9999-swarm-test
to_model: {to_model}
specialist: {specialist}
source_namespace: {source_namespace}
{compatibility_line}mode: bounty
run_id: BTY-SWARM-TEST
result_type: dry_run
write_scope: {write_scope}
parallel_safe: true
direct_lane_work_allowed: false
mandatory_review: true
review_model: {review_model}
return_artifact: _state/swarm-test.md
---
Review only the supplied, authorized evidence. Do not perform live execution.
"""
            )
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def run_dispatch(self, packet: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["VAULT_ROOT"] = str(ROOT)
        env["SQUAD_TEST_ISOLATION"] = "1"
        return subprocess.run(
            [str(SEND_TASK), str(packet), *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_dry_run_preflights_real_children_and_is_deterministic(self) -> None:
        packet = self.packet(
            specialist="summarizer",
            to_model="claude",
            source_namespace="shared",
            compatibility_namespace="coding",
        )
        args = ("--swarm", "claude,kimi", "--dry-run")
        first = self.run_dispatch(packet, *args)
        second = self.run_dispatch(packet, *args)

        self.assertEqual(first.returncode, 2, first.stderr)
        self.assertEqual(second.returncode, 2, second.stderr)
        self.assertIn("dispatch_kind=swarm", first.stdout)
        self.assertIn("quorum=all", first.stdout)
        self.assertIn("mandatory_review=true", first.stdout)
        self.assertIn(
            "roles=summarizer,summarizer",
            first.stdout,
        )
        self.assertIn("-swarm-claude", first.stdout)
        self.assertIn("-swarm-kimi", first.stdout)
        digest = re.search(r"swarm_spec_sha256=([0-9a-f]{64})", first.stdout)
        repeated = re.search(r"swarm_spec_sha256=([0-9a-f]{64})", second.stdout)
        self.assertIsNotNone(digest)
        self.assertEqual(digest.group(1), repeated.group(1))

    def test_shared_source_without_compatibility_namespace_resolves_real_mailbox(self) -> None:
        result = self.run_dispatch(
            self.packet(
                specialist="skeptic",
                to_model="claude",
                source_namespace="shared",
                compatibility_namespace=None,
                review_model="gpt-codex",
            ),
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Source namespace: shared", result.stdout)
        self.assertIn("Compatibility mailbox: security", result.stdout)

    def test_code_reviewer_swarm_preflights_ranked_claude_and_codex_adapters(self) -> None:
        result = self.run_dispatch(
            self.packet(
                specialist="code-reviewer",
                to_model="claude",
                source_namespace="coding",
                compatibility_namespace="coding",
                review_model="gpt-codex",
            ),
            "--swarm",
            "claude,gpt-codex",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("dispatch_kind=swarm lanes=claude,gpt-codex", result.stdout)

    def test_read_only_and_dispatch_kind_separation_fail_closed(self) -> None:
        writable = self.run_dispatch(
            self.packet(write_scope="[src]") ,
            "--swarm",
            "gpt-codex,kimi",
            "--dry-run",
        )
        mixed = self.run_dispatch(
            self.packet(),
            "--swarm",
            "gpt-codex,kimi",
            "--panel",
            "exploit-developer,security-analyst",
            "--dry-run",
        )
        self.assertEqual(writable.returncode, 1)
        self.assertIn("read-only", writable.stderr)
        self.assertEqual(mixed.returncode, 1)
        self.assertIn("distinct dispatch kinds", mixed.stderr)

    def test_claude_codex_exploit_pilot_preflights_but_full_four_stays_gated(self) -> None:
        pilot = self.run_dispatch(
            self.packet(),
            "--swarm",
            "claude,gpt-codex",
            "--dry-run",
        )
        self.assertEqual(pilot.returncode, 2, pilot.stderr)
        self.assertIn("dispatch_kind=swarm lanes=claude,gpt-codex", pilot.stdout)
        self.assertIn("roles=exploit-developer,exploit-developer", pilot.stdout)

        full = self.run_dispatch(
            self.packet(),
            "--swarm",
            "gpt-codex,claude,kimi,gemini",
            "--dry-run",
        )
        self.assertEqual(full.returncode, 1)
        self.assertIn(
            "missing Kimi adapter for specialist 'exploit-developer'", full.stderr
        )
        self.assertNotIn("[DRY RUN]", full.stdout)

    def test_new_lane_adapters_pass_ordinary_dispatch_dry_run(self) -> None:
        cases = (
            ("experimental-attacker", "kimi", "security"),
            ("bounty-researcher", "gemini", "research"),
        )
        for specialist, lane, namespace in cases:
            with self.subTest(specialist=specialist, lane=lane):
                result = self.run_dispatch(
                    self.packet(
                        specialist=specialist,
                        to_model=lane,
                        source_namespace=namespace,
                        compatibility_namespace=namespace,
                        review_model="gpt-codex",
                    ),
                    "--dry-run",
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(
                    f"Dispatching TASK-2026-07-18-9999-swarm-test → {lane}/{specialist}",
                    result.stdout,
                )

    def test_subswarm_single_dispatch_binds_directive_and_assignment_text(self) -> None:
        assignments = ("audit schema exhaustiveness", "audit runtime activation boundary")
        directive = self.subswarm_directive(assignments)
        scoped_packet = lambda: self.packet(
            write_scope="[_state/swarm-test.md, _state/subswarm/TASK-2026-07-18-9999-swarm-test/]"
        )
        result = self.run_dispatch(
            scoped_packet(),
            "--subswarm-directive",
            str(directive),
            "--subswarm-assignment",
            f"gpt-codex:sub01={assignments[0]}",
            "--subswarm-assignment",
            f"gpt-codex:sub02={assignments[1]}",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("dispatch_kind=single subswarm_directive_sha256=", result.stdout)
        self.assertIn("members=2 cap=2", result.stdout)
        self.assertIn("swarm-test-member-bundle", result.stdout)

        mismatch = self.run_dispatch(
            scoped_packet(),
            "--subswarm-directive",
            str(directive),
            "--subswarm-assignment",
            "gpt-codex:sub01=mutated objective",
            "--subswarm-assignment",
            f"gpt-codex:sub02={assignments[1]}",
            "--dry-run",
        )
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("objective hash mismatch", mismatch.stderr)

        outside_scope = self.run_dispatch(
            self.packet(write_scope="[_state/swarm-test.md]"),
            "--subswarm-directive",
            str(directive),
            "--subswarm-assignment",
            f"gpt-codex:sub01={assignments[0]}",
            "--subswarm-assignment",
            f"gpt-codex:sub02={assignments[1]}",
            "--dry-run",
        )
        self.assertEqual(outside_scope.returncode, 1)
        self.assertIn("outside packet write_scope", outside_scope.stderr)

    def test_subswarm_cannot_mix_with_panel_or_cross_lane_swarm(self) -> None:
        assignments = ("one", "two")
        directive = self.subswarm_directive(assignments)
        for incompatible in (("--panel", "exploit-developer,security-analyst"), ("--swarm", "claude,gpt-codex")):
            with self.subTest(incompatible=incompatible[0]):
                result = self.run_dispatch(
                    self.packet(),
                    "--subswarm-directive",
                    str(directive),
                    *incompatible,
                    "--dry-run",
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("distinct dispatch mode", result.stderr)


if __name__ == "__main__":
    unittest.main()
