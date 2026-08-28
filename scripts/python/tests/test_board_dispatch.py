from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
from types import MappingProxyType
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402

# See dispatch_checkout: send-task.sh refuses to dispatch from a linked
# worktree, which would make this suite checkout-dependent rather than
# behaviour-dependent.
ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])
sys.path.insert(0, str(ROOT / "scripts" / "python"))
from lane_capability_enforcement import (  # noqa: E402
    CapabilityDenied,
    adapter_path_for,
    load_projection,
    parse_live_mcp_listing,
    plan_lane,
)
from specialist_capability_source import load_source, role_surface_sha256  # noqa: E402
from validate_capability_homes import routed_lanes, runtime_rows  # noqa: E402
from dispatch_context_builder import (  # noqa: E402
    DispatchContextError,
    SYNTHESIZED_ENVELOPE_MARKER,
    assemble_trusted_launch_prompt,
    delivery_contract_note,
    prepare_worktree_outputs,
    publish_prepared_worktree_outputs,
)
from board_process_truth import atomic_write_json, observe_process, utc_now  # noqa: E402

SEND_TASK = ROOT / "bin" / "send-task.sh"
SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"
COMPAT_SEND_TASK = ROOT / "scripts" / "send-task.sh"
LAUNCH_SQUAD = ROOT / "bin" / "launch-squad.sh"


def _success_path_integration_offset(text: str) -> int:
    """Offset of the SUCCESS-path `integrate_worktree_commits`, not the first one.

    V113-18 added a second, earlier call site that lands a blocked attempt's
    committed code when only its return path failed. Two structural tests here
    used `text.index(...)` to mean "the success path integrates here", and that
    assumption broke silently the moment a legitimate second caller appeared
    above it -- one test then compared offsets across two different code paths
    and reported an ordering regression that did not exist.
    """
    return text.index("wti.integrate_worktree_commits(", text.index("prepare_worktree_outputs("))


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

    def test_explicit_pane_mode_is_rejected_before_dispatch(self) -> None:
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
            pane_env = dict(base_env)
            pane_env["SQUAD_DISPATCH_MODE"] = "pane"
            pane = subprocess.run(
                ["bash", str(SEND_TASK), str(path), "--dry-run"],
                env=pane_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(pane.returncode, 1, pane.stderr)
            self.assertIn("pane transport is unsupported", pane.stderr)
            self.assertNotIn("Dispatched", pane.stdout)

    def test_dispatch_mode_is_board_only(self) -> None:
        text = SEND_TASK.read_text(encoding="utf-8")
        self.assertIn('SQUAD_DISPATCH_MODE="${SQUAD_DISPATCH_MODE:-board}"', text)
        self.assertIn('[[ "$SQUAD_DISPATCH_MODE" == "board" ]]', text)
        self.assertIn(
            '["/bin/bash", sys.argv[1], "detached-launch", *sys.argv[7:]]',
            text,
        )
        self.assertIn('"schema": "board-dispatch-process/v2"', text)
        self.assertIn("identity = observe_process(child.pid)", text)
        self.assertIn("start_new_session=True", text)
        self.assertIn('"event": "board-claimed"', text)
        self.assertIn("RESPONSE_MIN_AGE_SECONDS=0", text)
        self.assertIn("settlement-error", text)
        self.assertIn("receipt_path", text)
        self.assertNotIn('supervisor_output="$(timeout', text)
        self.assertNotIn("nohup bash -c", text)
        self.assertNotIn('elif [[ "$SQUAD_DISPATCH_MODE" == "pane"', text)
        self.assertIn("--nudge-pane|--nudge-unavailable) die", text)
        self.assertNotIn("[--nudge-pane", text)
        self.assertIn('"delivery_attempt_id"', text)
        self.assertIn('"delivery_generation"', text)

    def test_ad_hoc_reviewer_transport_is_absent(self) -> None:
        self.assertFalse((ROOT / "bin" / "verify.sh").exists())
        self.assertFalse((ROOT / "scripts" / "python" / "verify.py").exists())

    def test_compatibility_wrapper_authors_project_and_calls_board_dispatch_directly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="compat-board-route-") as raw:
            vault = Path(raw)
            (vault / "bin").mkdir()
            (vault / "shared").mkdir()
            tools = vault / "tools"
            tools.mkdir()
            body = vault / "body.md"
            body.write_text("Do the bounded project task.\n", encoding="utf-8")
            packet_capture = vault / "packet.md"
            argv_capture = vault / "argv.txt"
            tmux_marker = vault / "tmux-called"
            (vault / "shared" / "lead-windows.sh").write_text(
                "COMPATIBILITY_NAMESPACES=(coding security content sysmgmt research)\n"
                'is_compatibility_namespace() { [[ "$1" == coding ]]; }\n'
                "namespace_default_model() { printf 'claude\\n'; }\n",
                encoding="utf-8",
            )
            # A high safety level is deliberately present: review is now a
            # property of this packet's explicit triggers, not this role row.
            runtime_fields = ["sol", "shared", "judgment", "high"]
            runtime_fields.extend(["x", "x", "claude", "x", "x", "x", "x", "x", "x", "gpt-codex"])
            (vault / "shared" / "specialist-runtime-map.tsv").write_text(
                "\t".join(runtime_fields) + "\n", encoding="utf-8"
            )
            hardened = vault / "bin" / "send-task.sh"
            hardened.write_text(
                "#!/bin/bash\n"
                'printf \'%s\\n\' "$@" > "$ARGV_CAPTURE"\n'
                'cp "$1" "$PACKET_CAPTURE"\n',
                encoding="utf-8",
            )
            hardened.chmod(0o755)
            uuidgen = tools / "uuidgen"
            uuidgen.write_text(
                "#!/bin/sh\nprintf '12345678-1234-1234-1234-123456789abc\\n'\n",
                encoding="utf-8",
            )
            uuidgen.chmod(0o755)
            tmux = tools / "tmux"
            tmux.write_text(
                '#!/bin/sh\ntouch "$TMUX_MARKER"\nexit 99\n',
                encoding="utf-8",
            )
            tmux.chmod(0o755)

            omitted_mode = subprocess.run(
                [
                    "bash",
                    str(COMPAT_SEND_TASK),
                    "coding",
                    str(body),
                    "sol",
                    "claude",
                ],
                env={
                    **os.environ,
                    "ARGV_CAPTURE": str(argv_capture),
                    "PACKET_CAPTURE": str(packet_capture),
                    "PATH": f"{tools}:/usr/bin:/bin",
                    "TMUX_MARKER": str(tmux_marker),
                    "VAULT_ROOT": str(vault),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(omitted_mode.returncode, 1, omitted_mode.stderr)
            self.assertIn("missing required --mode", omitted_mode.stdout)
            self.assertFalse(packet_capture.exists())
            self.assertFalse(argv_capture.exists())

            completed = subprocess.run(
                [
                    "bash",
                    str(COMPAT_SEND_TASK),
                    "coding",
                    str(body),
                    "sol",
                    "claude",
                    "--mode",
                    "project",
                ],
                env={
                    **os.environ,
                    "ARGV_CAPTURE": str(argv_capture),
                    "PACKET_CAPTURE": str(packet_capture),
                    "PATH": f"{tools}:/usr/bin:/bin",
                    "TMUX_MARKER": str(tmux_marker),
                    "VAULT_ROOT": str(vault),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(
                argv_capture.exists(), completed.stdout + completed.stderr
            )
            self.assertEqual(
                len(argv_capture.read_text(encoding="utf-8").splitlines()), 1
            )
            packet = packet_capture.read_text(encoding="utf-8")
            self.assertIn("mode: project\n", packet)
            self.assertIn("review_triggers: []\n", packet)
            self.assertIn("mandatory_review: false\n", packet)
            self.assertIn("review_model: none\n", packet)
            self.assertNotIn("mode: advisory", packet)
            self.assertFalse(tmux_marker.exists(), "compatibility wrapper invoked tmux")

            triggered = subprocess.run(
                [
                    "bash",
                    str(COMPAT_SEND_TASK),
                    "coding",
                    str(body),
                    "sol",
                    "claude",
                    "--mode",
                    "project",
                ],
                env={
                    **os.environ,
                    "ARGV_CAPTURE": str(argv_capture),
                    "PACKET_CAPTURE": str(packet_capture),
                    "PATH": f"{tools}:/usr/bin:/bin",
                    "REVIEW_TRIGGERS": "[architecture]",
                    "TMUX_MARKER": str(tmux_marker),
                    "VAULT_ROOT": str(vault),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(triggered.returncode, 0, triggered.stderr)
            triggered_packet = packet_capture.read_text(encoding="utf-8")
            self.assertIn("review_triggers: [architecture]\n", triggered_packet)
            self.assertIn("mandatory_review: true\n", triggered_packet)
            self.assertIn("review_model: gpt-codex\n", triggered_packet)

    def test_public_launch_command_is_unchanged_without_retired_inbox_workers(
        self,
    ) -> None:
        text = LAUNCH_SQUAD.read_text(encoding="utf-8")
        self.assertIn("bash ~/Obsidian-Claude-Vibe-Squad/bin/launch-squad.sh", text)
        self.assertIn("conversation + live four-lane status sidebar", text)
        self.assertIn("watchers/status (outbox notifications + reconciliation)", text)
        for index in range(1, 5):
            self.assertNotIn(f"Ctrl-b + {index}", text)
        self.assertNotIn("inbox-watcher.sh", text)
        self.assertNotIn('"scan-consumer"', text)

    def test_board_completion_captures_memory_best_effort(self) -> None:
        builder = (
            ROOT / "scripts" / "python" / "dispatch_context_builder.py"
        ).read_text(encoding="utf-8")
        # Schema-complete, one-attempt memory (Sol context-diag fix): give the exact
        # valid record shape up front so the model doesn't burn extra turns on invalid
        # filters / repo schema-searches / retries. Memory is BEST-EFFORT and never a gate.
        self.assertIn('record(note_type="learning", fields=', builder)
        self.assertIn("server binds source_task", builder)
        self.assertIn("never search the repo for schemas", builder)
        self.assertIn("Recall prior context ONCE", builder)
        self.assertIn("BEST-EFFORT", builder)
        self.assertNotIn("record one concise durable outcome in chrono-vault", builder)
        # RECORD_USAGE (2026-08-17): this assertion is the inverse of what it was.
        # `c3aeb5d5` forbade record_usage on 2026-07-25 because the server did not
        # publish the `outcome` enum, so a rejected call hard-blocked whole tasks;
        # `6ebe6802` published it two days later and the prohibition was never lifted.
        # It cost 23 days and every usage row in them. The prohibition is now asserted
        # ABSENT so it cannot return silently — if a future edit reintroduces it, this
        # fails rather than going unnoticed for another three weeks.
        self.assertNotIn("Do not call record_usage", builder)
        self.assertIn("record_usage(recall_id=", builder)
        # `set_status` is a different question and stays forbidden: it is
        # controller-only (`plugins/chrono-vault/clearance.py`
        # require_controller_lifecycle), and nothing about the enum defect applied
        # to it. Only the record_usage half was diagnosed stale.
        self.assertIn("Do not call set_status", builder)
        # ORDERING (2026-08-04): "best-effort" was true of the wording and false of the
        # POSITION. `record` used to sit between the artifact and the completion envelope
        # ("Just before the completion envelope, record the outcome ONCE"), and the envelope
        # is the only thing that promotes work. A record call the CLI could not parse killed
        # the turn before the envelope existed and stranded a finished 38 KB advisory in its
        # worktree (TASK-2026-08-06-2860). The supervisor was already tolerant — a missing id
        # yields learning_status="degraded", asserted below — so only the prompt's ordering
        # made telemetry a gate. These two assertions pin the repair: a step that may not gate
        # must not sit upstream of the gate.
        self.assertIn("completion envelope FIRST", builder)
        self.assertNotIn("Just before the completion envelope", builder)
        # The old instruction also held the artifact open waiting for a returned memory id,
        # which is the same ordering trap one level down.
        self.assertIn("completion envelope FIRST", builder)
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("observed_memory_ids", supervisor)
        # memory capture is best-effort, NOT a completion gate (SOL/Fable Phase-2 fix):
        # the block is gone; a missing memory id yields learning_status=degraded, not blocked.
        self.assertNotIn(
            "completion lacks one verified chrono-vault record id", supervisor
        )
        self.assertIn(
            'learning_status = "captured" if completion_memory_id else "degraded"',
            supervisor,
        )
        self.assertIn('"learning_status": globals().get("learning_status"', supervisor)
        self.assertIn('"memory_id": globals().get("completion_memory_id")', supervisor)
        self.assertIn('tool == "record" or tool.endswith("__record")', supervisor)

    def test_dispatch_prompt_expects_usage_only_where_recall_can_return_notes(
        self,
    ) -> None:
        """The prompt text is what a worker obeys, so assert the assembled bytes.

        The source-text assertions above catch a reintroduced prohibition; this
        catches the subtler failure of asking for a usage outcome from an aperture
        that can never produce a recall_id to report one against.
        """

        def prompt(aperture: str) -> str:
            return assemble_trusted_launch_prompt(
                "packet body",
                task_id="TASK-2026-08-17-0001-usage",
                attempt_id="d-" + "0" * 32,
                generation=1,
                memory_aperture=aperture,
            )

        for aperture in ("rich", "focused"):
            with self.subTest(aperture=aperture):
                text = prompt(aperture)
                self.assertIn("record_usage(recall_id=", text)
                self.assertNotIn("Do not call record_usage", text)
                self.assertIn("Do not call set_status", text)
        for aperture in ("cold", "pool_blind"):
            with self.subTest(aperture=aperture):
                text = prompt(aperture)
                self.assertNotIn("record_usage(", text)
                self.assertIn("no usage outcome to record", text)
                self.assertIn("Do not call set_status", text)
        # Aperture `none` takes the separate branch that forbids every memory tool.
        none_text = prompt("none")
        self.assertNotIn("record_usage", none_text)
        self.assertIn("Do not call recall, record", none_text)
        # The `record` example the prompt hands every worker must itself be a
        # well-formed call. It rendered with an unbalanced brace until 2026-08-17
        # (`fields={...}})`), which only the assembled bytes reveal — the source
        # reads `{{` and looks correct. An example that cannot parse is the same
        # defect class that caused the 2026-07-25 emergency in the first place.
        example = [
            line for line in prompt("rich").splitlines() if "record(note_type=" in line
        ][0]
        call = example[example.index("`record(") + 1 : example.index(")`") + 1]
        self.assertEqual(call.count("{"), call.count("}"), call)
        self.assertEqual(call.count("("), call.count(")"), call)

    def test_dispatch_toolkit_is_mode_aware(self) -> None:
        """Mode-blind injection sent bounty doctrine to every task and mode
        instructions to none. The toolkit takes a third argument and gates on it."""
        toolkit = (ROOT / "shared" / "dispatch-toolkit.sh").read_text(encoding="utf-8")
        self.assertIn('MODE="${3:-unknown}"', toolkit)
        self.assertIn('case "$MODE" in', toolkit)
        sender = (ROOT / "bin" / "send-task.sh").read_text(encoding="utf-8")
        self.assertIn(
            'bash "$TOOLKIT" "$MAILBOX_NAMESPACE" "$TO_MODEL" "$MODE" "$SPECIALIST"',
            sender,
        )
        self.assertEqual(sender.count('bash "$TOOLKIT"'), 1)

    def test_phase_contract_is_target_agnostic(self) -> None:
        """The contract ships to every bounty lane regardless of target class,
        so a noun that only fits one class is a defect."""
        contract = (ROOT / "shared" / "templates" / "phase-contract.md").read_text(
            encoding="utf-8"
        )
        for field in (
            "Actor action:",
            "Question:",
            "Oracle:",
            "May receive:",
            "Must not receive:",
            "Evidence form:",
            "Output state:",
            "Before return:",
        ):
            self.assertIn(field, contract)
        for chain_noun in ("value-moving entry", "forge", "anvil", "solidity", "token"):
            self.assertNotIn(chain_noun, contract.lower())

    def test_toolkit_delivers_phase_contract_only_for_bounty(self) -> None:
        """Delivery canary: presence, not quality. Injection used to be mode-blind,
        so bounty doctrine shipped to non-bounty tasks and mode text to none.

        Verified 2026-08-04 against the recovered systems-engineer implementation:
        bounty -> 1 occurrence, project -> 0, and the legacy two-argument caller
        still exits 0.
        """
        import subprocess

        toolkit = ROOT / "shared" / "dispatch-toolkit.sh"
        marker = "Phase contract — read before acting"
        bounty = subprocess.run(
            ["bash", str(toolkit), "security", "claude", "bounty"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=180,
        ).stdout
        project = subprocess.run(
            ["bash", str(toolkit), "security", "claude", "project"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=180,
        ).stdout
        legacy = subprocess.run(
            ["bash", str(toolkit), "security", "claude"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=180,
        )
        self.assertIn(marker, bounty)
        self.assertNotIn(marker, project)
        self.assertEqual(legacy.returncode, 0, "two-argument callers must not break")

    def test_toolkit_gates_security_and_research_doctrine_both_ways(self) -> None:
        """~8 KB of offensive-security + research doctrine (the security toolchain,
        the verdict-discipline rail, and the research add-ons) shipped on EVERY
        dispatch. It has no consumer on a plain low/medium-risk task, so it is now
        injected ONLY where one exists.

        The selector was REJECTED (cross-family review 2026-08-11) for keying on the
        mailbox namespace: `source_namespace` is a storage location, not a risk signal,
        so a high-safety role outside the `security` mailbox (e.g. `smart-contract-engineer`,
        coding namespace) silently lost its toolchain. It now keys on ROLE SAFETY
        SEMANTICS — `safety_level`/`heightened_risk` from the runtime map, resolved by the
        specialist passed as the 4th arg — plus bounty mode.

        Pinned BOTH ways. The costly error is a FALSE NEGATIVE — a risky role silently
        losing its toolchain — so the 'present' side includes the AUDIT case (a security
        specialist in project mode, kept via SAFETY not namespace), a high-risk coding
        specialist in project mode (the exact defect), and the legacy no-specialist call
        (fail-open). The full per-specialist consumer oracle lives in
        test_toolkit_gate_by_safety.py.
        """
        import subprocess

        toolkit = ROOT / "shared" / "dispatch-toolkit.sh"
        SECURITY = "## Security toolchain available to this dispatch"
        VERDICT = "## Verdict discipline"
        RESEARCH = "## Registry-derived research add-ons"
        # The four blocks that are universal AND must never be gated out.
        UNIVERSAL = (
            "## Execution efficiency",
            "## Completion contract",
            "## Hard constraint: no unauthorized file deletion",
            "native subagents for bounded parallel sub-work",
            "subagents: N",
        )

        def render(
            namespace: str, mode: str | None = None, specialist: str | None = None
        ) -> str:
            argv = ["bash", str(toolkit), namespace, "claude"]
            if mode is not None:
                argv.append(mode)
            if specialist is not None:
                argv.append(specialist)
            proc = subprocess.run(
                argv, capture_output=True, text=True, cwd=str(ROOT), timeout=180
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout

        rows = runtime_rows(ROOT)
        content_fixture = next(
            row
            for _specialist, row in sorted(rows.items())
            if row["source_namespace"] == "content"
            and row["safety_level"] in {"low", "medium"}
            and row["heightened_risk"] == "false"
        )
        content_specialist = content_fixture["specialist"]

        # Security toolchain + verdict rail: present iff bounty OR a high-safety /
        # heightened-risk role OR an unresolvable role (fail-open).
        for namespace, mode, specialist in (
            ("security", "bounty", "scout"),
            # AUDIT case: a security specialist in project mode kept via SAFETY, not namespace.
            ("security", "project", "security-analyst"),
            # The exact defect: a high-safety coding role in project mode must keep doctrine.
            ("coding", "project", "smart-contract-engineer"),
            ("coding", "bounty", "backend-engineer"),
            # Legacy no-specialist call: uncertainty must fail OPEN, never silently strip.
            ("security", None, None),
        ):
            with self.subTest(security_present=(namespace, mode, specialist)):
                out = render(namespace, mode, specialist)
                self.assertIn(SECURITY, out)
                self.assertIn(VERDICT, out)
        # Genuinely low/medium, non-heightened roles: the saving is preserved.
        for namespace, mode, specialist in (
            ("coding", "project", "backend-engineer"),  # medium
            ("sysmgmt", "project", "harness-optimizer"),  # medium
            ("content", "project", content_specialist),
            ("research", "project", "research"),  # medium: add-ons but NOT the 6 KB toolchain
        ):
            with self.subTest(security_absent=(namespace, mode, specialist)):
                out = render(namespace, mode, specialist)
                self.assertNotIn(SECURITY, out)
                self.assertNotIn(VERDICT, out)

        # Research add-ons: research namespace keeps them, as does anything security-doctrine.
        for namespace, mode, specialist in (
            ("research", "project", "research"),
            ("security", "project", "security-analyst"),
            ("coding", "bounty", "backend-engineer"),
        ):
            with self.subTest(research_present=(namespace, mode, specialist)):
                self.assertIn(RESEARCH, render(namespace, mode, specialist))
        for namespace, mode, specialist in (
            ("coding", "project", "backend-engineer"),
            ("sysmgmt", "project", "harness-optimizer"),
            ("content", "project", content_specialist),
        ):
            with self.subTest(research_absent=(namespace, mode, specialist)):
                self.assertNotIn(RESEARCH, render(namespace, mode, specialist))

        # The four universal blocks survive a full strip.
        stripped = render("sysmgmt", "project", "harness-optimizer")
        for block in UNIVERSAL:
            self.assertIn(block, stripped)

        # The strip is a real, substantial saving: within ONE specialist (so the mailbox
        # block is identical), a project task is at least ~8 KB lighter than the same
        # specialist in bounty mode, which additionally carries the phase contract.
        self.assertGreater(
            len(render("coding", "bounty", "backend-engineer"))
            - len(render("coding", "project", "backend-engineer")),
            8000,
        )

    def test_toolkit_injects_declared_tool_failure_reporting(self) -> None:
        """A declared tool a worker could not invoke must be reported (Hard Rule 9:
        declared != actual). The requirement lives in the UNIVERSAL Completion contract
        so it reaches every dispatch, reuses the existing `needs_tool` vocabulary as a
        REPORT FIELD, and invents no new envelope status.

        Rendered — not just present in the source file — for lane/mode combinations that
        differ in BOTH lane and mode, because the injection must be namespace/mode-blind.
        """
        import subprocess

        toolkit = ROOT / "shared" / "dispatch-toolkit.sh"

        def render(namespace: str, lane: str, mode: str) -> str:
            proc = subprocess.run(
                ["bash", str(toolkit), namespace, lane, mode],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                timeout=180,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout

        # Two combinations, differing in lane AND (namespace, mode). Ordinary project
        # dispatches and bounty dispatches alike must carry the rule.
        for namespace, lane, mode in (
            ("sysmgmt", "claude", "project"),
            ("coding", "gpt-codex", "bounty"),
        ):
            with self.subTest(combo=(namespace, lane, mode)):
                out = render(namespace, lane, mode)

                # It lives INSIDE the Completion contract, before the no-delete rule —
                # i.e. in the universal block, not somewhere gated out of a plain task.
                contract = out.index("## Completion contract")
                no_delete = out.index("spec-1.5-no-delete-rule")
                heading = out.index("## needs_tool")
                self.assertTrue(
                    contract < heading < no_delete,
                    "declared-tool reporting must sit within the universal Completion contract",
                )

                # Reuses `needs_tool` and is explicit that it is a field, not a 5th status.
                self.assertIn("This is a FIELD, not a status", out)

                # Demands the three per-tool data points the report is worthless without.
                self.assertIn("EXACTLY as your adapter declared", out)  # tool name
                self.assertIn("literal call you attempted", out)  # invocation
                self.assertIn("VERBATIM error", out)  # verbatim error

                # The essential-vs-fallback distinction rides on the EXISTING status enum.
                self.assertIn("status: blocked", out)
                self.assertIn("essential", out)

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

    def test_detached_failure_is_captured_in_receipt_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = "TASK-2026-07-23-9993-capture-failure"
            attempt = "d-capture"
            base = root / f"{task}.{attempt}"
            log = Path(f"{base}.log")
            receipt = Path(f"{base}.receipt.json")
            dispatch = Path(f"{base}.dispatch.json")
            marker = root / "settlement-error"
            missing_context = Path(f"{base}.context.json")
            log.touch()
            environment = {
                **os.environ,
                "BOARD_DISPATCH_DESCRIPTOR_PATH": str(dispatch),
            }
            process = subprocess.Popen(
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
                    task,
                    "codex",
                    "_state/capture-failure/result.md",
                    "coding",
                    "/usr/bin/false",
                ],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            identity = None
            for _ in range(100):
                identity = observe_process(process.pid)
                if identity is not None:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(identity)
            self.assertTrue(
                atomic_write_json(
                    dispatch,
                    {
                        "schema": "board-dispatch-process/v2",
                        "task_id": task,
                        "attempt_id": attempt,
                        "generation": 1,
                        "created_at": utc_now(),
                        **identity,
                        "context_path": str(missing_context),
                        "log_path": str(log),
                        "receipt_path": str(receipt),
                    },
                    exclusive=True,
                )
            )
            stdout, stderr = process.communicate(timeout=15)
            expected = "trusted-launch context file missing"
            self.assertEqual(process.returncode, 70, stdout + stderr)
            self.assertIn(expected, receipt.read_text(encoding="utf-8"))
            self.assertIn(expected, log.read_text(encoding="utf-8"))
            self.assertGreater(receipt.stat().st_size, 0)
            self.assertGreater(log.stat().st_size, 0)
            self.assertTrue(marker.is_file())
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "board-dispatch-receipt/v2")
            self.assertEqual(payload["generation"], 1)
            self.assertEqual(payload["terminal_outcome"], "denied")
            self.assertEqual(payload["status"], "denied")

    def test_detached_runner_streams_then_fsyncs_both_evidence_files(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        detached = text.index('if [[ "${1:-}" == "detached-launch" ]]')
        trusted = text.index('if [[ "${1:-}" == "trusted-launch" ]]')
        body = text[detached:trusted]
        launch = body.index('"$repo_root/bin/board-supervisor.sh" trusted-launch')
        transcript_fd = body.index('exec 4>>"$log_path"')
        # Stream separation: the capture is the machine channel and takes stdout
        # only; stderr goes to the already-open transcript descriptor. `2>&1`
        # here let one diagnostic line terminalise a successful launch as
        # blocked -- see test_receipt_stream_separation.py for the behaviour.
        receipt = body.index('>"$receipt_capture" 2>&4')
        self.assertNotIn('>"$receipt_capture" 2>&1', body)
        status = body.index("supervisor_rc=$?")
        fsync = body.index("os.fsync(descriptor)")
        finalize = body.index("finalize-receipt")
        settlement = body.index('"$context_builder" blocked')
        self.assertLess(transcript_fd, launch)
        self.assertLess(launch, receipt)
        self.assertLess(receipt, status)
        self.assertLess(status, fsync)
        self.assertLess(fsync, finalize)
        self.assertLess(finalize, settlement)
        self.assertNotIn("/usr/bin/tee", body)
        self.assertNotIn("timeout_bin", body)
        self.assertNotIn("--kill-after", body)
        self.assertIn('mktemp "${receipt_path}.capture.XXXXXX"', body)
        self.assertNotIn("BOARD_INHERIT_PROCESS_GROUP", text)
        self.assertIn("start_new_session=True", text)
        self.assertIn("manager.terminate(proc.pid)", text)
        self.assertLess(
            text.index("manager.terminate(proc.pid)"),
            text.index('failure_class="cli_timeout"'),
        )
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
        self.assertIn("limit = 1024 * 1024", text[helper:completed])
        self.assertIn("os.fsync(descriptor)", text[helper:completed])

    def test_claude_global_live_mcp_health_is_reported_not_denied(self) -> None:
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
        self.assertEqual(plan.unhealthy_mcps, ())

        failed = parse_live_mcp_listing(
            lane="claude",
            output=(
                "Checking MCP server health…\n"
                "sequential-thinking: /opt/homebrew/bin/"
                "mcp-server-sequential-thinking - ✘ Failed to connect\n"
            ),
        )
        degraded = plan_lane(
            lane="claude",
            projection=projection,
            configured_servers=failed,
        )
        # A dead server is a fact about the world, not a defect in the plan.
        # The launch proceeds and carries the verbatim status forward.
        self.assertEqual(degraded.authorized_mcps, ("sequential-thinking",))
        self.assertEqual(degraded.unhealthy_mcps, ("sequential-thinking",))
        self.assertEqual(
            degraded.unhealthy_mcp_status,
            (("sequential-thinking", "✘ Failed to connect"),),
        )

    def test_detached_runner_propagates_original_trusted_host_path(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        capture = text.index('trusted_host_path="${TRUSTED_HOST_PATH:-${PATH:-')
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
        self.assertNotIn("resolve_vault_root", body)
        self.assertIn('"CHRONO_VAULT_ROOT", "OBSIDIAN_VAULT_ROOT"', body)
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
        self.assertIn(
            'trusted_environment["CHRONO_VAULT_CONTEXT"] = json.dumps(',
            text,
        )
        self.assertIn(
            'prepared.environment["CHRONO_VAULT_CONTEXT"] = trusted_environment[',
            text,
        )

    def test_utility_credentials_load_once_into_one_shared_snapshot(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        start = source.index("MANAGED_CREDENTIAL_NAMES = (")
        end = source.index("\n\ntrusted_environment =", start)
        body = source[start:end]
        calls: list[str] = []

        def load_solodit_api_key() -> str:
            calls.append("solodit")
            return "synthetic-solodit"

        def load_research_api_keys() -> dict[str, str]:
            calls.append("research")
            return {
                "XAI_API_KEY": "synthetic-xai",
                "PERPLEXITY_API_KEY": "synthetic-perplexity",
            }

        def load_github_mcp_token() -> None:
            calls.append("github")
            return None

        namespace = {
            "MappingProxyType": MappingProxyType,
            "load_solodit_api_key": load_solodit_api_key,
            "load_research_api_keys": load_research_api_keys,
            "load_github_mcp_token": load_github_mcp_token,
        }
        exec(compile(body, "board-supervisor.sh", "exec"), namespace)
        load = namespace["load_managed_credentials"]
        project = namespace["project_worker_credentials"]
        base = {"PATH": "/usr/bin:/bin"}

        snapshot, missing = load("claude", [])
        self.assertEqual(project(base, snapshot), base)
        self.assertEqual(calls, [])
        self.assertEqual(missing, ())

        snapshot, missing = load("claude", ["guarded-solodit"])
        self.assertEqual(
            project(base, snapshot),
            {**base, "SOLODIT_API_KEY": "synthetic-solodit"},
        )
        self.assertEqual(calls, ["solodit"])
        self.assertEqual(missing, ())
        calls.clear()

        snapshot, missing = load("codex", ["chrono-research-arsenal"])
        self.assertEqual(
            project(base, snapshot),
            {
                **base,
                "XAI_API_KEY": "synthetic-xai",
                "PERPLEXITY_API_KEY": "synthetic-perplexity",
            },
        )
        self.assertEqual(calls, ["research"])
        self.assertEqual(missing, ())
        calls.clear()

        # A credential the secret store did not supply is REPORTED, not fatal:
        # the launch degrades and names it so the worker is not left to find out
        # by calling a dead tool.
        snapshot, missing = load("claude", ["github"])
        self.assertEqual(project(base, snapshot), base)
        self.assertEqual(calls, ["github"])
        self.assertEqual(missing, ("GITHUB_PERSONAL_ACCESS_TOKEN",))
        calls.clear()

        # ONE loader call per attempt. `project_worker_credentials` is what runs
        # twice (health probe, then launcher); it must be incapable of reading a
        # secret at all, or the two reads can disagree and the gate passes with a
        # token the worker never gets.
        snapshot, _missing = load("claude", ["guarded-solodit", "github"])
        self.assertEqual(calls, ["solodit", "github"])
        calls.clear()
        probe_environment = project(base, snapshot)
        launch_environment = project(base, snapshot)
        self.assertEqual(calls, [])
        self.assertEqual(probe_environment, launch_environment)
        self.assertEqual(
            probe_environment, {**base, "SOLODIT_API_KEY": "synthetic-solodit"}
        )
        applier = source[
            source.index("def project_worker_credentials(") : end
        ]
        for loader in (
            "load_solodit_api_key(",
            "load_research_api_keys(",
            "load_github_mcp_token(",
            "load_managed_credentials(",
        ):
            self.assertNotIn(loader, applier)
        # The snapshot is immutable, so no later stage can mutate what the gate
        # measured.
        with self.assertRaises(TypeError):
            snapshot["SOLODIT_API_KEY"] = "rotated"

        ambient = {
            **base,
            "SOLODIT_API_KEY": "ambient-solodit",
            "XAI_API_KEY": "ambient-xai",
            "PERPLEXITY_API_KEY": "ambient-perplexity",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ambient-github",
        }
        for worker_lane, authorized in (
            ("claude", ["lead:guarded-solodit", "lead:chrono-research-arsenal"]),
            ("kimi", ["lead:chrono-research-arsenal"]),
            ("gemini", ["guarded-solodit", "chrono-research-arsenal", "github"]),
        ):
            with self.subTest(lane=worker_lane):
                empty, empty_missing = load(worker_lane, authorized)
                self.assertEqual(project(ambient, empty), base)
                self.assertEqual(empty_missing, ())
        self.assertEqual(calls, [])
        self.assertEqual(base, {"PATH": "/usr/bin:/bin"})

    def test_health_probe_and_launcher_share_one_credential_snapshot(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        environment = source.index("def trusted_worker_environment(worker_lane):")
        environment_end = source.index("MANAGED_CREDENTIAL_NAMES = (", environment)
        self.assertNotIn("load_solodit_api_key()", source[environment:environment_end])
        self.assertNotIn(
            "load_research_api_keys()", source[environment:environment_end]
        )

        # The snapshot is read once, before the probe, and the probe measures an
        # environment built from that exact snapshot.
        native_gate = source.index('if execution_kind == "lane" and lane in {"claude"')
        snapshot_load = source.index(
            "credential_snapshot, credential_missing = load_managed_credentials(",
            native_gate,
        )
        probe_environment = source.index(
            "health_probe_environment = project_worker_credentials(", snapshot_load
        )
        mcp_probe = source.index('(str(executable), "mcp", "list")', probe_environment)
        self.assertIn(
            "env=health_probe_environment",
            source[mcp_probe : source.index("parse_live_mcp_listing(", mcp_probe)],
        )
        # A bearer token is for the health probe alone. The local plugin
        # inventory has no use for one and keeps the scrubbed environment.
        plugin_probe = source.index(
            '(str(executable), "plugin", "list", "--json")', mcp_probe
        )
        plugin_call = source[
            plugin_probe : source.index("close_fds=True", plugin_probe)
        ]
        self.assertIn("env=trusted_environment", plugin_call)
        self.assertNotIn("health_probe_environment", plugin_call)

        # The launcher reuses that snapshot; only a lane that never loaded one
        # (codex, whose authorized set is known later) may load here.
        launcher = source.index(
            "    trusted_environment = project_worker_credentials(", mcp_probe
        )
        guard = source.index("if credential_snapshot is None:", mcp_probe)
        self.assertLess(guard, launcher)
        self.assertIn(
            "credential_snapshot,",
            source[launcher : source.index(")", launcher)],
        )
        projection_hash = source.index(
            "capability_projection_bytes = json.dumps(", launcher
        )
        self.assertLess(launcher, projection_hash)

    def test_degraded_launch_is_named_in_receipt_and_worker_context(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn(
            "unhealthy_mcps = list(capability_plan.unhealthy_mcps)", source
        )
        self.assertIn(
            "unhealthy_mcp_status = dict(capability_plan.unhealthy_mcp_status)",
            source,
        )
        receipt = source.index('"capability_enforcement": capability_enforcement')
        receipt_body = source[receipt:]
        self.assertIn('"unhealthy_mcps": unhealthy_mcps,', receipt_body)
        self.assertIn('"unhealthy_mcp_status": unhealthy_mcp_status,', receipt_body)
        self.assertIn('"credential_missing": list(credential_missing),', receipt_body)
        # The worker is told before it spends a call on a dead tool.
        notice = source.index("## Degraded capability notice (measured at launch)")
        self.assertLess(notice, source.index("role = compile_role_context("))
        self.assertIn(
            "trusted_task_prompt = trusted_task_prompt.rstrip() + degraded_notice",
            source,
        )

    def test_supervisor_observes_every_canonical_role_surface(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        start = source.index("def declared_array(")
        end = source.index("\n\nif execution_kind ==", start)
        namespace = {"Path": Path, "json": json, "re": __import__("re")}
        exec(compile(source[start:end], "board-supervisor.sh", "exec"), namespace)
        canonical_surface = namespace["canonical_capability_surface"]
        entries, _ = load_source(ROOT)
        rows = runtime_rows(ROOT)
        expected = {
            (specialist, lane)
            for specialist, row in rows.items()
            for lane in routed_lanes(row)
        }

        self.assertEqual(set(entries), expected)
        self.assertEqual(
            len(entries),
            sum(len(routed_lanes(row)) for row in rows.values()),
        )
        for (specialist, source_lane), entry in entries.items():
            lane = "codex" if source_lane == "gpt-codex" else source_lane
            adapter = adapter_path_for(repo_root=ROOT, lane=lane, specialist=specialist)
            projection = load_projection(
                lane=lane,
                specialist=specialist,
                adapter_path=adapter,
                overlay_path=adapter,
            )
            with self.subTest(specialist=specialist, lane=lane):
                payload = canonical_surface(lane, projection, adapter)
                digest = (
                    __import__("hashlib")
                    .sha256(
                        json.dumps(
                            payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                            allow_nan=False,
                        ).encode("ascii")
                    )
                    .hexdigest()
                )
                self.assertEqual(digest, role_surface_sha256(entry))

        comparison = source.index("capability surface does not match launch authority")
        child_launch = source.index("completed = launch_task(")
        self.assertLess(comparison, child_launch)
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "gemini.md"
            overlay.write_text(
                'capability_mcps: ["direct","lead:marker-broker"]\n',
                encoding="utf-8",
            )
            payload = canonical_surface(
                "gemini",
                {
                    "skills": [],
                    "tools": [],
                    "mcps": ["direct"],
                    "brokered_mcps": ["native-mirror-leak"],
                },
                overlay,
            )
        self.assertEqual(payload["brokered_mcps"], ["marker-broker"])

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
        degraded = plan_lane(
            lane="gemini",
            projection={
                "mcps": ["optional"],
                "brokered_mcps": [],
                "tools": [],
            },
            configured_servers=parsed,
        )
        self.assertEqual(degraded.unhealthy_mcps, ("optional",))
        self.assertEqual(
            degraded.unhealthy_mcp_status, (("optional", "Disconnected"),)
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
        self.assertNotIn("_PROVEN_LANE_MODELS", builder)
        self.assertIn('return (*base, "--model", model)', builder)
        self.assertIn('"--yolo",\n        "--thinking"', builder)
        self.assertIn(
            'str(handle.worktree_root / "model-lanes" / "kimi" / "main.yaml")',
            supervisor,
        )
        self.assertIn('"--add-dir",\n            str(handle.worktree_root)', supervisor)
        self.assertIn("def kimi_role_launcher(", supervisor)
        self.assertIn("kimi_vault_environment=(", supervisor)
        self.assertIn('("CHRONO_VAULT_ROOT", "CHRONO_VAULT_CONTEXT")', supervisor)
        self.assertIn("concise_prompt = (", supervisor)
        self.assertIn("## Main-lead MCP contract", supervisor)
        self.assertIn("capability_plan.authorized_mcps", supervisor)
        self.assertIn("Native `Agent(...)` subagents remain MCP-free", supervisor)
        self.assertIn("lead_allowlist_json.encode", supervisor)
        self.assertIn("lead MCP allowlist exceeds prompt bound", supervisor)
        self.assertNotIn(
            "role_config_json",
            supervisor[supervisor.index("def kimi_role_launcher(") :],
        )
        self.assertIn("def run_with_restored_prompt(", supervisor)
        self.assertNotIn("kimi_config_path", supervisor)
        self.assertNotIn('.kimi" / "mcp.json"', supervisor)
        self.assertIn("repo_root=repo_root", supervisor)
        kimi_launcher = supervisor.index("def kimi_role_launcher(")
        prompt_contract = supervisor.index("## Main-lead MCP contract", kimi_launcher)
        final_command = supervisor.index("kimi_command = (", prompt_contract)
        guarded_write = supervisor.index("run_with_restored_prompt(", final_command)
        self.assertLess(prompt_contract, final_command)
        self.assertLess(final_command, guarded_write)
        self.assertIn("def gemini_ordered_launcher(", supervisor)
        self.assertIn("base_gemini_prompt.rstrip()", supervisor)
        self.assertIn('"--output-format",\n            "stream-json"', supervisor)
        self.assertIn('"--print",\n            "--output-format"', supervisor)
        self.assertIn(
            '30 <= budgets["timeout_seconds"] <= 2700',
            supervisor,
        )
        self.assertIn(
            '"--include-directories",\n            str(handle.worktree_root)',
            supervisor,
        )
        kimi_docs = (ROOT / "model-lanes" / "kimi" / "KIMI.md").read_text()
        self.assertIn("Native `Agent(...)` subagents remain MCP-free", kimi_docs)
        self.assertIn("deterministic local templates", kimi_docs)
        capability_docs = (
            ROOT / "model-lanes" / "adapter-capability-schema.md"
        ).read_text()
        self.assertIn("controller-owned local templates", capability_docs)
        self.assertIn(
            "credential-bearing remote routes are unavailable",
            " ".join(capability_docs.lower().split()),
        )
        for adapter in (ROOT / "model-lanes" / "kimi" / ".kimi" / "agents").glob(
            "*.yaml"
        ):
            self.assertNotIn("mcpServers:", adapter.read_text(encoding="utf-8"))

    def test_kimi_partial_prompt_write_restores_exact_original_bytes(self) -> None:
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        start = supervisor.index("    def run_with_restored_prompt(")
        end = supervisor.index("\n    def gemini_ordered_launcher(", start)
        namespace: dict[str, object] = {}
        exec(textwrap.dedent(supervisor[start:end]), namespace)
        helper = namespace["run_with_restored_prompt"]

        class PartialWritePath:
            def __init__(self, original: bytes) -> None:
                self.value = original
                self.write_count = 0

            def read_bytes(self) -> bytes:
                return self.value

            def write_bytes(self, value: bytes) -> int:
                self.write_count += 1
                if self.write_count == 1:
                    self.value = value[:7]
                    raise OSError("synthetic partial write")
                self.value = bytes(value)
                return len(value)

        original = b"tracked KIMI prompt\r\nwith exact bytes\n"
        prompt_path = PartialWritePath(original)
        callback_called = False

        def callback() -> None:
            nonlocal callback_called
            callback_called = True

        marker = "synthetic-secret-value"
        with self.assertRaises(OSError) as raised:
            helper(prompt_path, f"\n\n{marker}\n", callback)
        self.assertFalse(callback_called)
        self.assertEqual(prompt_path.value, original)
        self.assertEqual(prompt_path.write_count, 2)
        self.assertNotIn(marker, str(raised.exception))

    def test_kimi_receipt_reports_lead_allowlist_without_changing_surface(self) -> None:
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        receipt = supervisor.index('"capability_enforcement": capability_enforcement')
        receipt_body = supervisor[receipt:]
        self.assertIn('"authorized_mcps": authorized_mcps', receipt_body)
        self.assertIn('"brokered_mcps": brokered_mcps', receipt_body)
        self.assertNotIn(
            'capability_projection["brokered_mcps"] = authorized_mcps',
            supervisor,
        )

    def test_codex_worker_gets_only_derived_linked_git_commit_dirs(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        codex = text.index('lane == "codex"')
        # There are TWO integration call sites since V113-18: the success path,
        # and an earlier one that recovers a blocked attempt's committed code.
        # Anchoring on the first textual match silently moved this window above
        # the code it is meant to inspect, so name the success-path call.
        integration = _success_path_integration_offset(text)
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
        self.assertIn('archived_path = inbox_path.parent.parent / "archive"', builder)
        self.assertIn("packet_path.unlink()", builder)
        supervisor = SUPERVISOR.read_text(encoding="utf-8")
        reconcile = supervisor.index('env RESPONSE_MIN_AGE_SECONDS=0 "$reconciler"')
        cleanup = supervisor.index('"$context_builder" cleanup-canary', reconcile)
        self.assertLess(reconcile, cleanup)
        self.assertIn(
            'canary_cleanup_requested = packet_frontmatter.get("board_canary_autoclean") is True',
            supervisor,
        )
    def test_supervisor_rehashes_packet_and_commits_envelope_last(self) -> None:
        text = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("trusted_lane_args_for", text)
        closure = text.index(
            'board_dispatch_context = trusted_context and execution_kind == "lane"'
        )
        lane_args = text.index("controller_lane_args = trusted_lane_args_for(", closure)
        model = text.index(
            "controller_model_sha256 = selected_model_sha256_for(", closure
        )
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
        integration_offset = _success_path_integration_offset(text)
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
        self.assertIn(
            '"artifact_promotions": bridge_receipt["artifact_promotions"]',
            text,
        )

    def test_prepared_completion_publishes_the_exact_preintegration_bytes(self) -> None:
        task_id = "TASK-2026-07-23-9984-prepared-output"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worker = root / "worker"
            repo.mkdir()
            worker.mkdir()
            result_relative = "_state/prepared/result.md"
            outbox_relative = f"departments/coding/outbox/{task_id}-response.md"
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


class SplitOutputEnvelopeTests(unittest.TestCase):
    """Pin the shapes where `expected_result_path` != `expected_outbox_path`.

    The bridge supports a lane-isolated `return_artifact` and a separate outbox
    envelope as a generic output contract. Missing worker-authored envelopes are
    synthesized only when a nonempty artifact proves useful work exists.
    """

    TASK_ID = "TASK-2026-08-26-1800-distinct-output"
    RESULT_RELATIVE = (
        "_state/distinct-output/TASK-2026-08-26-1800/artifact.md"
    )

    def _outbox_relative(self) -> str:
        return f"departments/coding/outbox/{self.TASK_ID}-response.md"

    def _authority(self) -> dict[str, object]:
        return {
            "task_id": self.TASK_ID,
            "lane": "codex",
            "write_paths": [self.RESULT_RELATIVE],
            "expected_result_path": self.RESULT_RELATIVE,
            "expected_outbox_path": self._outbox_relative(),
        }

    def _tree(self, root: Path, *, artifact: str | None) -> tuple[Path, Path]:
        repo = root / "repo"
        worker = root / "worker"
        repo.mkdir()
        worker.mkdir()
        if artifact is not None:
            target = worker / self.RESULT_RELATIVE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact, encoding="utf-8")
        return repo, worker

    def test_missing_envelope_is_synthesized_rather_than_discarding_the_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worker = self._tree(
                Path(directory),
                artifact=(
                    "# Liveness canary\n\n"
                    "HEAD is a1e1305b and python3 is 3.14.6.\n"
                ),
            )

            prepared = prepare_worktree_outputs(repo, worker, self._authority())
            receipt = publish_prepared_worktree_outputs(repo, prepared)

            envelope = (repo / self._outbox_relative()).read_text(encoding="utf-8")
            self.assertEqual(prepared.status, "needs_review")
            self.assertEqual(receipt["status"], "needs_review")
            self.assertIn("status: needs_review", envelope)
            self.assertIn(SYNTHESIZED_ENVELOPE_MARKER, envelope)
            # The excerpt skips the `#` heading and carries real prose, so the
            # summary the reconciler surfaces says something about the work.
            self.assertIn("HEAD is a1e1305b", envelope)
            self.assertNotIn("# Liveness canary", envelope)
            # The artifact is still promoted verbatim to its own declared path.
            self.assertIn(
                "HEAD is a1e1305b",
                (repo / self.RESULT_RELATIVE).read_text(encoding="utf-8"),
            )

    def test_a_worker_authored_envelope_still_wins_over_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worker = self._tree(Path(directory), artifact="worker artifact\n")
            envelope_path = worker / self._outbox_relative()
            envelope_path.parent.mkdir(parents=True, exist_ok=True)
            envelope_path.write_text(
                "---\n"
                f"id: {self.TASK_ID}-response\n"
                f"in_response_to: {self.TASK_ID}\n"
                "from: gpt-codex\n"
                "to: chrono\n"
                "type: RESULT\n"
                "status: complete\n"
                f"return_artifact: {self.RESULT_RELATIVE}\n"
                "---\n\n"
                "Worker-authored summary.\n",
                encoding="utf-8",
            )

            prepared = prepare_worktree_outputs(repo, worker, self._authority())

            self.assertEqual(prepared.status, "complete")
            envelope = prepared.envelope_bytes.decode("utf-8")
            self.assertIn("Worker-authored summary.", envelope)
            self.assertNotIn(SYNTHESIZED_ENVELOPE_MARKER, envelope)

    def test_a_missing_artifact_still_blocks_in_the_split_shape(self) -> None:
        """Synthesis must never manufacture a completion out of nothing."""

        with tempfile.TemporaryDirectory() as directory:
            repo, worker = self._tree(Path(directory), artifact=None)

            with self.assertRaises(DispatchContextError) as caught:
                prepare_worktree_outputs(repo, worker, self._authority())

            self.assertIn("return artifact is missing", str(caught.exception))

    def test_an_empty_artifact_still_blocks_in_the_split_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worker = self._tree(Path(directory), artifact="")

            with self.assertRaises(DispatchContextError):
                prepare_worktree_outputs(repo, worker, self._authority())

    def test_a_present_but_non_regular_envelope_still_blocks(self) -> None:
        """Only an ABSENT envelope is synthesized; a symlink is tamper-shaped."""

        with tempfile.TemporaryDirectory() as directory:
            repo, worker = self._tree(Path(directory), artifact="worker artifact\n")
            envelope_path = worker / self._outbox_relative()
            envelope_path.parent.mkdir(parents=True, exist_ok=True)
            envelope_path.symlink_to(worker / self.RESULT_RELATIVE)

            with self.assertRaises(DispatchContextError) as caught:
                prepare_worktree_outputs(repo, worker, self._authority())

            self.assertIn("response envelope", str(caught.exception))

    def test_the_aliased_single_shape_is_unchanged(self) -> None:
        """A standard packet's artifact IS its envelope; a missing one blocks."""

        task_id = "TASK-2026-08-26-1900-aliased"
        outbox = f"departments/coding/outbox/{task_id}-response.md"
        authority = {
            "task_id": task_id,
            "lane": "codex",
            "write_paths": [outbox],
            "expected_result_path": outbox,
            "expected_outbox_path": outbox,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worker = root / "worker"
            repo.mkdir()
            worker.mkdir()

            with self.assertRaises(DispatchContextError) as caught:
                prepare_worktree_outputs(repo, worker, authority)

            self.assertIn("return artifact is missing", str(caught.exception))

    def test_delivery_contract_names_the_envelope_only_when_it_is_a_second_file(
        self,
    ) -> None:
        outbox = self._outbox_relative()

        split = delivery_contract_note(
            self.RESULT_RELATIVE, [self.RESULT_RELATIVE], outbox_relative=outbox
        )
        aliased = delivery_contract_note(outbox, [outbox], outbox_relative=outbox)

        # The split shape is where the lane cannot infer the envelope from its
        # write scope, so the prompt must name the path and lift the prohibition.
        self.assertIn(outbox, split)
        self.assertIn("SECOND file", split)
        self.assertIn(
            "scope violation, because the controller excludes it from integration",
            split,
        )
        self.assertIn("four ways", split)
        # The aliased shape already lists the envelope as its write scope; adding
        # a second item there would tell every single dispatch to write twice.
        self.assertNotIn("SECOND file", aliased)
        self.assertIn("three ways", aliased)

    def test_the_launch_prompt_carries_the_split_output_envelope_path(self) -> None:
        outbox = self._outbox_relative()

        prompt = assemble_trusted_launch_prompt(
            "---\nid: x\n---\n\nbody\n",
            task_id=self.TASK_ID,
            attempt_id="d-" + "0" * 32,
            generation=1,
            memory_aperture="none",
            return_artifact=self.RESULT_RELATIVE,
            write_scope=[self.RESULT_RELATIVE],
            outbox_relative=outbox,
        )

        self.assertIn(outbox, prompt)
        self.assertIn("SECOND file", prompt)



if __name__ == "__main__":
    unittest.main()


class UnifiedMailboxAgreementTests(unittest.TestCase):
    """Pin the one live mailbox across Python and shell dispatch surfaces."""

    def test_shell_sender_pins_the_same_mailbox_without_namespace_fallback(self) -> None:
        local_root = Path(__file__).resolve().parents[3]
        sender = (local_root / "bin" / "send-task.sh").read_text(encoding="utf-8")
        builder = (local_root / "scripts/python/dispatch_context_builder.py").read_text(
            encoding="utf-8"
        )
        reconciler = (local_root / "scripts/python/registry_reconciler.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('MAILBOX_NAMESPACE="coding"', sender)
        self.assertIn('PurePosixPath("departments/coding")', builder)
        self.assertIn("CANONICAL_MAILBOX_ROOT", reconciler)
        self.assertNotIn("compat_namespace_for_model", sender)
