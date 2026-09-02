from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


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
            "model-lanes/specialist-lane-capabilities.v1.json",
        ):
            self._copy(relative)
        source = ROOT / "model-lanes/specialist-lane-capabilities.v1.json"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        grep = subprocess.run(
            ["git", "grep", "-lz", digest, "--"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        self.coupled_hash_pinners = tuple(
            path.decode()
            for path in grep.stdout.split(b"\0")
            if path and path.decode() != source.relative_to(ROOT).as_posix()
        )
        for relative in self.coupled_hash_pinners:
            self._copy(relative)
        (self.repo / "_state").mkdir(exist_ok=True)
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, stdout=subprocess.DEVNULL
        )
        subprocess.run(
            ["git", "add", "."], cwd=self.repo, check=True, stdout=subprocess.DEVNULL
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Dispatch Preflight Test",
                "-c",
                "user.email=dispatch-preflight@example.invalid",
                "commit",
                "-qm",
                "baseline",
            ],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def _packet(
        self,
        *,
        specialist: str,
        acknowledgement: bool = False,
        corrupt_contract_hash: bool = False,
        body: str = ORCHESTRATOR_BLINDNESS_SHAPE,
        write_scope: tuple[str, ...] | None = None,
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
        return_artifact = "_state/v4-runtime/orchestration/result.md"
        declared_scope = write_scope or ("_state/v4-runtime/orchestration/",)
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
            f"write_scope: [{', '.join(declared_scope)}]\n"
            "read_scope: []\n"
            f"return_artifact: {return_artifact}\n"
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
        # Ratchet, not a target. Raised 665 -> 682 for `_scan_failed_advisory`:
        # the two advisory handlers used to answer a crashed scan with `()`,
        # which is the same answer a clean packet gets.
        module = ROOT / "scripts" / "python" / "dispatch_preflight.py"
        nonblank = sum(bool(line.strip()) for line in module.read_text().splitlines())
        self.assertLessEqual(nonblank, 682)

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

    def test_acknowledged_owner_warning_and_dirty_advisory_can_coexist(self) -> None:
        target = self.repo / "shared/specialists/triage.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\ndirty\n", encoding="utf-8"
        )
        packet = self._packet(
            specialist="technical-writer",
            acknowledgement=True,
            body=ORCHESTRATOR_BLINDNESS_SHAPE,
            write_scope=(
                "_state/v4-runtime/orchestration/result.md",
                "shared/specialists/triage.md",
            ),
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(
            [item["code"] for item in verdict.warnings],
            [preflight.OWNER_MISMATCH, preflight.DIRTY_WRITE_SCOPE],
        )
        self.assertRegex(verdict.ack_sha256 or "", r"^[0-9a-f]{64}$")

    def test_coupled_hash_pin_ordinary_packet_stays_silent(self) -> None:
        artifact = "_state/v4-runtime/orchestration/result.md"
        packet = self._packet(
            specialist="harness-optimizer",
            body="Update `shared/specialists/triage.md` to clarify the route.",
            write_scope=(artifact, "shared/specialists/triage.md"),
        )
        self.assertEqual(preflight.authoring_warnings(self.repo, packet), ())

    def test_dirty_tracked_write_scope_warns_but_allows(self) -> None:
        target = self.repo / "shared/specialists/triage.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\ndirty\n", encoding="utf-8"
        )
        artifact = "_state/v4-runtime/orchestration/result.md"
        packet = self._packet(
            specialist="harness-optimizer",
            body="Update `shared/specialists/triage.md` to clarify the route.",
            write_scope=(artifact, "shared/specialists/triage.md"),
        )
        verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.exit_code, preflight.EXIT_PASS)
        self.assertEqual(
            [item["code"] for item in verdict.warnings],
            [preflight.DIRTY_WRITE_SCOPE],
        )
        self.assertEqual(
            verdict.warnings[0]["paths"], ["shared/specialists/triage.md"]
        )

    def test_empty_scope_does_not_treat_every_dirty_path_as_in_scope(self) -> None:
        target = self.repo / "shared/specialists/triage.md"
        target.write_text(
            target.read_text(encoding="utf-8") + "\ndirty\n", encoding="utf-8"
        )
        packet = self._packet(
            specialist="harness-optimizer",
            body="Inspect the current dispatch design and report the result.",
            write_scope=(),
        )
        packet.write_text(
            packet.read_text(encoding="utf-8").replace(
                "write_scope: [_state/v4-runtime/orchestration/]", "write_scope: []"
            ).replace(
                "return_artifact: _state/v4-runtime/orchestration/result.md",
                'return_artifact: ""',
            ),
            encoding="utf-8",
        )
        self.assertEqual(preflight.authoring_warnings(self.repo, packet), ())

    def test_advisory_failure_is_fail_open_but_not_fail_silent(self) -> None:
        """A crashed advisory scan still allows dispatch, and now says it crashed.

        This used to assert `warnings == ()` -- the same verdict a clean packet
        produces, so a scan that never ran was indistinguishable from a scan
        that found nothing. Fail-open is about the decision, not the reporting.
        """
        packet = self._packet(
            specialist="harness-optimizer",
            body="Update `shared/specialists/triage.md` to clarify the route.",
        )
        with mock.patch.object(
            preflight, "_git_paths", side_effect=RuntimeError("diagnostic failed")
        ):
            verdict = preflight.evaluate_packet(self.repo, packet)
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.exit_code, preflight.EXIT_PASS)
        self.assertEqual(
            [warning["code"] for warning in verdict.warnings],
            [preflight.ADVISORY_SCAN_FAILED],
        )
        self.assertIn("diagnostic failed", verdict.warnings[0]["message"])

    def test_malformed_advisory_output_is_fail_open(self) -> None:
        packet = self._packet(specialist="harness-optimizer")
        with mock.patch.object(
            preflight,
            "authoring_warnings",
            return_value=({"gate": "advisory"},),
        ):
            status = preflight.main(
                [
                    "--repo-root",
                    str(self.repo),
                    "--packet",
                    str(packet),
                    "--authoring-warnings-only",
                ]
            )
        self.assertEqual(status, preflight.EXIT_PASS)

    def test_coupled_hash_pin_prints_in_dry_and_live_paths_without_gating(self) -> None:
        artifact = "_state/v4-runtime/orchestration/result.md"
        source = "model-lanes/specialist-lane-capabilities.v1.json"
        pinners = list(self.coupled_hash_pinners)
        self.assertTrue(pinners, "fixture must include a tracked digest pinner")
        packet = self._packet(
            specialist="harness-optimizer",
            body=f"Update `{source}` to change a projected capability.",
            write_scope=(artifact, source),
        )
        live_stdout, live_stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(live_stdout), redirect_stderr(live_stderr):
            live_status = preflight.main(
                ["--repo-root", str(self.repo), "--packet", str(packet)]
            )
        dry_stdout, dry_stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(dry_stdout), redirect_stderr(dry_stderr):
            dry_status = preflight.main(
                [
                    "--repo-root",
                    str(self.repo),
                    "--packet",
                    str(packet),
                    "--authoring-warnings-only",
                ]
            )
        self.assertEqual((dry_status, live_status), (preflight.EXIT_PASS,) * 2)
        rendered_live = json.loads(live_stdout.getvalue())
        self.assertEqual(rendered_live["decision"], "allow")
        warning = next(
            item
            for item in rendered_live["warnings"]
            if item["code"] == preflight.COUPLED_HASH_PIN
        )
        self.assertEqual(warning["source_path"], source)
        self.assertEqual(warning["missing_count"], len(pinners))
        # `paths` is a deliberate SAMPLE -- dispatch_preflight caps it at
        # `missing[:10]` so a warning cannot dump 166 paths into a dispatch
        # envelope. `missing_count` above already pins the true total, so
        # comparing the sample to the full list asserted the cap did not exist.
        # It only passed while the fixture happened to have fewer than ten
        # pinners; regenerating the capability source took it to 166.
        self.assertEqual(warning["paths"], pinners[:10])
        self.assertLessEqual(len(warning["paths"]), 10)
        self.assertFalse(warning["blocking"])
        self.assertEqual(dry_stdout.getvalue(), "")
        for rendered in (dry_stderr.getvalue(), live_stderr.getvalue()):
            self.assertIn(f"[{preflight.COUPLED_HASH_PIN}]", rendered)
            self.assertIn(pinners[0], rendered)

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

        wrapper = (ROOT / "scripts" / "send-task.sh").read_text(encoding="utf-8")
        dry_advisory = wrapper.index("--authoring-warnings-only")
        hardened = wrapper.index('"${HARDENED_DISPATCH}" "${DISPATCH_ARGS[@]}"')
        self.assertLess(dry_advisory, hardened)
        advisory_block = wrapper[dry_advisory - 300 : dry_advisory + 100]
        self.assertIn('[[ "${DRY_RUN}" == "true"', advisory_block)
        self.assertIn("|| true", advisory_block)


if __name__ == "__main__":
    unittest.main()
