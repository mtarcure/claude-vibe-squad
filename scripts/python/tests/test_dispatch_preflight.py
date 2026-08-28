from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_preflight as preflight  # noqa: E402
from verification_contract import derive_verification_contract  # noqa: E402


ORCHESTRATOR_BLINDNESS_SHAPE = """
Audit squad-wide prompt and generated-adapter hygiene. Analyze the routing owner
mismatch that assigned harness script drift to a documentation specialist.
Compare the canonical specialist boundaries and design a mandatory dispatch
preflight that prevents the same mismatch before publication.
""".strip()


class DispatchPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self._copy_sources()

    def _copy(self, relative: str) -> None:
        source = ROOT / relative
        destination = self.repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _copy_sources(self) -> None:
        for relative in (
            "shared/specialist-runtime-map.tsv",
            "shared/registries/profiles.tsv",
            "shared/specialists/triage.md",
            "shared/specialists/prompt-engineer.md",
            "departments/sysmgmt/specialists/harness-optimizer.md",
            "departments/content/specialists/technical-writer.md",
        ):
            self._copy(relative)
        (self.repo / "_state").mkdir(exist_ok=True)

    def _packet(
        self,
        *,
        specialist: str,
        acknowledgement: bool = False,
        corrupt_contract_hash: bool = False,
        body: str = ORCHESTRATOR_BLINDNESS_SHAPE,
    ) -> Path:
        source_namespace = {
            "technical-writer": "content",
            "harness-optimizer": "sysmgmt",
        }[specialist]
        suffix = "tech" if specialist == "technical-writer" else "harness"
        if acknowledgement:
            suffix += "-ack"
        task_id = f"TASK-2026-08-10-0771-{suffix}"
        contract = derive_verification_contract(
            {
                "task_id": task_id,
                "run_id": "V4-PREFLIGHT-TEST",
                "mode": "project",
                "result_type": "normal",
                "to_model": "claude",
                "dispatch_kind": "single",
                "capability": None,
                "expected_gates": [],
            }
        )
        contract_text = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        contract_hash = hashlib.sha256(contract_text.encode("ascii")).hexdigest()
        if corrupt_contract_hash:
            contract_hash = "0" * 64
        ack = (
            f"{preflight.ACK_FIELD}: [{preflight.OWNER_MISMATCH}]\n"
            if acknowledgement
            else ""
        )
        packet = self.repo / "packets" / f"{task_id}.md"
        packet.parent.mkdir(exist_ok=True)
        packet.write_text(
            "---\n"
            f"id: {task_id}\n"
            "run_id: V4-PREFLIGHT-TEST\n"
            "to_model: claude\n"
            f"specialist: {specialist}\n"
            f"source_namespace: {source_namespace}\n"
            f"compatibility_namespace: {source_namespace}\n"
            "mode: project\n"
            "result_type: normal\n"
            "write_scope: [_state/v4-runtime/orchestration/]\n"
            "read_scope: []\n"
            "return_artifact: _state/v4-runtime/orchestration/result.md\n"
            "parallel_safe: false\n"
            "direct_lane_work_allowed: true\n"
            "mandatory_review: false\n"
            "review_model: none\n"
            f"{ack}"
            f"verification_contract: {contract_text}\n"
            f"verification_contract_sha256: {contract_hash}\n"
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return packet

    def test_preflight_module_stays_small(self) -> None:
        module = ROOT / "scripts" / "python" / "dispatch_preflight.py"
        nonblank = sum(bool(line.strip()) for line in module.read_text().splitlines())
        self.assertLessEqual(nonblank, 490)

    def test_exact_contract_violation_is_refused(self) -> None:
        packet = self._packet(
            specialist="technical-writer", corrupt_contract_hash=True
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.exit_code, preflight.EXIT_REFUSE)
        self.assertEqual(verdict.refusals[0]["code"], "exact_contract_violation")
        self.assertIn("does not match", verdict.refusals[0]["message"])

    def test_owner_mismatch_requires_packet_acknowledgement(self) -> None:
        packet = self._packet(specialist="technical-writer")
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "needs_ack")
        self.assertEqual(verdict.exit_code, preflight.EXIT_ACK_REQUIRED)
        self.assertEqual(len(verdict.warnings), 1)
        warning = verdict.warnings[0]
        self.assertEqual(warning["code"], "owner_mismatch")
        self.assertEqual(warning["selected_specialist"], "technical-writer")
        self.assertEqual(warning["recommended_specialist"], "harness-optimizer")
        self.assertFalse(warning["acknowledged"])
        self.assertEqual(
            warning["required_ack"],
            "dispatch_preflight_ack: [owner_mismatch]",
        )

    def test_packet_acknowledgement_allows_the_warning(self) -> None:
        packet = self._packet(
            specialist="technical-writer", acknowledgement=True
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.exit_code, preflight.EXIT_PASS)
        self.assertTrue(verdict.warnings[0]["acknowledged"])
        self.assertRegex(verdict.warning_set_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertRegex(verdict.ack_sha256 or "", r"^[0-9a-f]{64}$")

    def test_same_shape_owned_by_harness_optimizer_is_clean(self) -> None:
        dispatch_log = self.repo / "_state" / "dispatch-log.jsonl"
        dispatch_log.write_text(
            "".join(
                json.dumps(
                    {
                        "specialist": "harness-optimizer",
                        "model_lane": "claude",
                    }
                )
                + "\n"
                for _ in range(60)
            ),
            encoding="utf-8",
        )
        packet = self._packet(specialist="harness-optimizer")
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.warnings, ())
        route = next(
            item for item in verdict.informational if item["code"] == "route_resolution"
        )
        self.assertEqual(route["profile_id"], "claude.fable.xhigh")
        self.assertEqual(route["registry_model"], route["effective_model"])
        concentration = next(
            item
            for item in verdict.informational
            if item["code"] == "recent_dispatch_concentration"
        )
        self.assertEqual(concentration["gate"], "informational")
        self.assertEqual(concentration["window_records"], 50)
        self.assertEqual(concentration["selected_specialist_count"], 50)

    def test_verdict_binding_rejects_changed_packet_bytes(self) -> None:
        packet = self._packet(
            specialist="technical-writer", acknowledgement=True
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertTrue(preflight.verdict_matches_packet(verdict, packet))
        packet.write_bytes(packet.read_bytes() + b"\nchanged after verdict\n")
        self.assertFalse(preflight.verdict_matches_packet(verdict, packet))
        rebound = preflight.evaluate_packet(self.repo, packet)
        self.assertNotEqual(verdict.packet_sha256, rebound.packet_sha256)
        self.assertNotEqual(verdict.ack_sha256, rebound.ack_sha256)

    def test_oversized_final_prompt_is_an_exact_refusal(self) -> None:
        packet = self._packet(
            specialist="harness-optimizer",
            body="x" * (preflight.context_builder.TRUSTED_LAUNCH_PROMPT_LIMIT + 1),
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("too large", verdict.refusals[0]["message"])

    def test_cli_emits_the_bound_warning_verdict_and_nonzero_status(self) -> None:
        packet = self._packet(specialist="technical-writer")
        output = io.StringIO()
        with redirect_stdout(output):
            status = preflight.main(
                ["--repo-root", str(self.repo), "--packet", str(packet)]
            )
        rendered = json.loads(output.getvalue())
        self.assertEqual(status, preflight.EXIT_ACK_REQUIRED)
        self.assertEqual(rendered["schema"], "dispatch-preflight/v1")
        self.assertEqual(rendered["decision"], "needs_ack")
        self.assertEqual(
            rendered["packet_sha256"], hashlib.sha256(packet.read_bytes()).hexdigest()
        )

    def test_send_task_invokes_preflight_before_single_host_admission(self) -> None:
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        host_admit = sender.split("board_host_admit() {", 1)[1].split("\n}", 1)[0]
        invocation = host_admit.index('python3 "$DISPATCH_PREFLIGHT"')
        packet_digest = host_admit.index('digest="$(shasum -a 256')
        binding = host_admit.index('[[ "$digest" == "$preflight_hash" ]]')
        host_policy = host_admit.index("host_admission.py")
        self.assertLess(invocation, packet_digest)
        self.assertLess(packet_digest, binding)
        self.assertLess(binding, host_policy)
        self.assertEqual(sender.count('python3 "$DISPATCH_PREFLIGHT"'), 1)

        common = sender.index('board_host_admit "$ACTUAL_TASK_FILE"')
        inbox_publish = sender.index("# ── copy to unified board inbox", common)
        self.assertLess(common, inbox_publish)
        self.assertEqual(sender.count('board_host_admit "$ACTUAL_TASK_FILE"'), 1)


if __name__ == "__main__":
    unittest.main()
