#!/usr/bin/env python3
"""Wave R2 `bin/send-task.sh` dispatch-admission + settlement hardening.

Two defects surfaced by the R1 board-reliability work but left unfixed because
they live outside that packet's write scope (see
``_state/consults/r1-board-reliability.md`` items 3 and 4):

* ``ContractAdmissionReasonTests`` (friction F7 remainder) — the admission
  ``die`` reported a generic "typed verification contract admission failed".
  ``verification_contract.py`` already prints ``verification contract error:
  <reason>`` on stderr, but as a *separate* line: anything that surfaces only
  the dispatcher's own error line (the friction log, a caller capturing the
  last line, a wrapper that reports ``$?``) loses which field was wrong.
* ``PostRegistrationSettlementTests`` (friction F5 residual) — once a task is
  written into ``_state/active-tasks.json`` it holds its ``write_scope``.  A
  ``die`` after that point left it ``in-flight`` until the reconciler's
  ``NEVER_LAUNCHED_GRACE`` backstop (120s) noticed, blocking every later
  dispatch touching the same paths.  Separately, the blocked-settlement escape
  hatch was handed the packet's ``return_artifact`` verbatim, so an absolute
  path made settlement itself fail with "contains an unsafe path" — the task
  then stranded with neither a blocked envelope nor a released scope.

The fixtures below drive the real ``bin/send-task.sh`` against a throwaway
VAULT_ROOT.  Every packet carries an absolute ``return_artifact``, which makes
the board context build fail deterministically, so the board supervisor is
never detached and no model CLI is ever launched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]  # scripts/python/tests -> repo root
SEND_TASK = REPO / "bin" / "send-task.sh"

# Vault subtrees send-task.sh reads out of the repo. `bin` is deliberately not
# in this list: some tests need a per-file bin so one executable can be omitted.
LINKED_SUBTREES = ("shared", "scripts", "model-lanes")

MAILBOXES = ("inbox", "active", "outbox", "archive")


def envelope(fields: dict[str, str], body: str = "body") -> str:
    rows = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{rows}\n---\n\n{body}\n"


class SendTaskFixture(unittest.TestCase):
    """A throwaway VAULT_ROOT that borrows the repo's code but not its state."""

    def make_vault(self, *, omit_from_bin: str | None = None) -> Path:
        root = Path(tempfile.mkdtemp(prefix="r2-sendtask-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        vault = root / "vault"
        vault.mkdir()
        for name in LINKED_SUBTREES:
            (vault / name).symlink_to(REPO / name)
        if omit_from_bin is None:
            (vault / "bin").symlink_to(REPO / "bin")
        else:
            # Link each executable individually so a single one can be absent.
            # `[[ -x "$BOARD_SUPERVISOR" ]]` then fails *after* registration,
            # which is the pre-launch failure this suite needs to observe.
            (vault / "bin").mkdir()
            for entry in (REPO / "bin").iterdir():
                if entry.name != omit_from_bin:
                    (vault / "bin" / entry.name).symlink_to(entry)
        (vault / "_state").mkdir()
        for mailbox in MAILBOXES:
            (vault / "departments" / "coding" / mailbox).mkdir(parents=True)
        return vault

    def dispatch(
        self,
        vault: Path,
        *,
        task_id: str,
        return_artifact: str,
        write_scope: str = "[]",
    ) -> subprocess.CompletedProcess:
        packet = vault.parent / f"{task_id}.md"
        # `specialist: none` + `direct_lane_work_allowed: true` skips the
        # specialist/adapter/capability gauntlet, so the run reaches the
        # registration and settlement code this suite is about.
        packet.write_text(
            envelope(
                {
                    "id": task_id,
                    "to_model": "claude",
                    "specialist": "none",
                    "source_namespace": "coding",
                    "compatibility_namespace": "coding",
                    "parallel_safe": "true",
                    "direct_lane_work_allowed": "true",
                    "write_scope": write_scope,
                    "return_artifact": return_artifact,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.run(
            [str(SEND_TASK), str(packet)],
            env={
                **os.environ,
                "VAULT_ROOT": str(vault),
                "SKIP_NUDGE": "1",
                "FAILOVER_CONTROL_ENABLED": "0",
            },
            capture_output=True,
            text=True,
            timeout=180,
        )

    def registry_entry(self, vault: Path, task_id: str) -> dict:
        registry = json.loads(
            (vault / "_state" / "active-tasks.json").read_text(encoding="utf-8")
        )
        self.assertIn(task_id, registry, msg="task was never registered")
        return registry[task_id]


# ─────────────────────────────────────────────────────────────────────────────
# F7 remainder — the admission die must name the reason
# ─────────────────────────────────────────────────────────────────────────────


class ContractAdmissionReasonTests(unittest.TestCase):
    """The dispatcher's own error line carries the helper's specific reason."""

    def _dispatch_with(self, **overrides: str) -> subprocess.CompletedProcess:
        fields = {
            "id": "TASK-2026-07-26-0000-r2admit",
            "to_model": "claude",
            "specialist": "systems-engineer",
            "source_namespace": "coding",
            "mode": "project",
            "run_id": "PROJ-BOARD-HARDENING-2026-07-26",
            "result_type": "normal",
            "write_scope": "[_state/r2admit/]",
            "read_scope": "[]",
            "parallel_safe": "true",
            "direct_lane_work_allowed": "false",
            "mandatory_review": "false",
            "review_model": "none",
            "model_override_reason": "regression fixture",
            "return_artifact": "_state/r2admit/out.md",
        }
        fields.update(overrides)
        directory = Path(tempfile.mkdtemp(prefix="r2-admit-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        packet = directory / "task.md"
        packet.write_text(envelope(fields), encoding="utf-8")
        # --dry-run: admission runs long before any write, so this asserts on
        # the message without touching the real registry or any mailbox.
        return subprocess.run(
            [str(SEND_TASK), str(packet), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def _admission_error_line(self, completed: subprocess.CompletedProcess) -> str:
        output = completed.stdout + completed.stderr
        lines = [
            line
            for line in output.splitlines()
            if line.startswith("ERROR: typed verification contract admission failed")
        ]
        self.assertEqual(
            len(lines), 1, msg=f"expected exactly one admission die line in:\n{output}"
        )
        return lines[0]

    def test_admission_die_carries_the_specific_reason(self) -> None:
        completed = self._dispatch_with(result_type="bogus")
        self.assertNotEqual(completed.returncode, 0)
        line = self._admission_error_line(completed)
        # The whole point: the reason must be on the die line itself, not only
        # on an adjacent stderr line a caller may never surface.
        self.assertIn("Project supports only result_type normal", line)

    def test_admission_die_reason_is_a_single_line(self) -> None:
        # A multi-line helper failure (argparse usage, traceback) must be
        # folded into one line so the message stays greppable.
        completed = self._dispatch_with(run_id="")
        self.assertNotEqual(completed.returncode, 0)
        line = self._admission_error_line(completed)
        self.assertNotIn("\n", line)
        self.assertGreater(
            len(line),
            len("ERROR: typed verification contract admission failed"),
            msg=f"die line reported no reason at all: {line!r}",
        )

    def test_successful_admission_is_unaffected(self) -> None:
        # Capturing stderr must not corrupt the contract parsed from stdout.
        completed = self._dispatch_with()
        output = completed.stdout + completed.stderr
        self.assertNotIn("typed verification contract admission failed", output)
        self.assertIn("Verification contract: version=verification-contract/v1", output)


# ─────────────────────────────────────────────────────────────────────────────
# F5 residual — a post-registration failure must release the write_scope now
# ─────────────────────────────────────────────────────────────────────────────


class PostRegistrationSettlementTests(SendTaskFixture):
    def test_post_registration_failure_settles_cancelled_synchronously(self) -> None:
        """A pre-launch die releases the scope in-process, not 120s later."""
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        task_id = "TASK-2026-07-26-0001-r2strand"
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/r2strand/out.md",
            write_scope="[_state/r2strand/]",
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("missing board supervisor", output)

        entry = self.registry_entry(vault, task_id)
        self.assertEqual(entry["status"], "cancelled", msg=output)
        # `in-flight` is the only status the dispatcher's conflict check counts,
        # so a terminal status is exactly what "scope released" means here.
        self.assertNotEqual(entry["status"], "in-flight")
        self.assertEqual(entry["delivery_state"], "terminal")
        self.assertTrue(entry.get("never_launched_reason"))

    def test_released_scope_admits_an_immediate_redispatch(self) -> None:
        """The behavioural half: the same write_scope is dispatchable again."""
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        first = self.dispatch(
            vault,
            task_id="TASK-2026-07-26-0002-r2first",
            return_artifact="_state/r2reuse/out.md",
            write_scope="[_state/r2reuse/]",
        )
        self.assertNotEqual(first.returncode, 0)
        second = self.dispatch(
            vault,
            task_id="TASK-2026-07-26-0003-r2second",
            return_artifact="_state/r2reuse/out.md",
            write_scope="[_state/r2reuse/]",
        )
        output = second.stdout + second.stderr
        # The re-dispatch still fails on the missing supervisor, but it must get
        # that far: no scope conflict from the abandoned first attempt.
        self.assertNotIn("CONFLICT", output)
        self.assertIn("write_scope: no conflicts", output)

    def test_a_launched_task_is_never_cancelled_by_the_die_path(self) -> None:
        """Fail closed: only a provably never-launched task may be cancelled.

        Asserted against the settle helper's own body rather than the whole
        script: an identical guard already exists in the delivery-start block,
        so a file-wide search would pass without the new code.
        """
        text = SEND_TASK.read_text(encoding="utf-8")
        opener = "settle_registered_task_cancelled() {"
        self.assertIn(opener, text, msg="post-registration settle helper is absent")
        body = text.split(opener, 1)[1].split("\n}\n", 1)[0]
        # A die after the delivery-start transition (delivery_state=in-progress,
        # claimed_at/started_at set) belongs to the supervisor: leave it alone.
        for clause in (
            'entry.get("status") != "in-flight"',
            'entry.get("delivery_state") != "queued"',
            'entry.get("claimed_at")',
            'entry.get("started_at")',
        ):
            self.assertIn(clause, body, msg=f"missing fail-closed clause: {clause}")

    def test_the_pane_rail_disarms_the_release_before_nudging(self) -> None:
        """Pane mode has no delivery-start fence, so it must disarm explicitly.

        The packet is in the inbox before the nudge and the watcher stays
        authoritative even when the nudge fails, so a die anywhere in the pane
        branch could otherwise cancel a task that is already running.
        """
        text = SEND_TASK.read_text(encoding="utf-8")
        branch = text.split('elif [[ "$SQUAD_DISPATCH_MODE" == "pane"', 1)
        self.assertEqual(len(branch), 2, msg="pane dispatch branch not found")
        pane_branch = branch[1]
        disarm = pane_branch.find("TASK_REGISTERED=0")
        nudge = pane_branch.find("nudge-task.sh")
        self.assertNotEqual(disarm, -1, msg="pane branch never disarms the release")
        self.assertLess(disarm, nudge, msg="pane branch disarms after nudging")


class BlockedSettlementPathTests(SendTaskFixture):
    def test_blocked_settlement_accepts_an_absolute_in_vault_artifact(self) -> None:
        """The exact repro from the R1 consult: '...contains an unsafe path'."""
        vault = self.make_vault()
        task_id = "TASK-2026-07-26-0004-r2unsafe"
        artifact = vault / "_state" / "r2unsafe" / "out.md"
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact=str(artifact),
            write_scope="[]",
        )
        output = completed.stdout + completed.stderr
        # The context build still rejects the absolute path — that is the
        # containment gate doing its job, and it is what triggers settlement.
        # What must no longer happen is settlement failing the same way.
        self.assertIn("board context builder failed", output)
        self.assertNotIn("blocked settlement both failed", output)
        # Settlement published both halves at the normalized relative path.
        self.assertTrue(artifact.is_file(), msg=output)
        envelope_path = (
            vault / "departments" / "coding" / "outbox" / f"{task_id}-response.md"
        )
        self.assertTrue(envelope_path.is_file(), msg=output)
        self.assertIn("status: blocked", envelope_path.read_text(encoding="utf-8"))
        self.assertNotEqual(
            self.registry_entry(vault, task_id)["status"], "in-flight", msg=output
        )

    def test_an_artifact_equal_to_the_outbox_path_settles_as_blocked(self) -> None:
        """Residual R2-A, fixed one layer down by wave R3.

        ``publish_blocked_completion`` used to write the artifact and *then* the
        envelope, so a packet whose ``return_artifact`` **is** the canonical
        outbox response path aimed two payloads at one file and the second write
        collided ("blocked response envelope destination already differs"). No
        envelope was published for the commonest packet shape in the repo. The
        builder now collapses identical paths onto the envelope alone, so this
        end-to-end rail settles properly: the envelope lands, the reconciler
        reads a real ``blocked`` status off it, and the task closes with the
        controller's reason instead of a bare ``cancelled`` from the die path.
        """
        vault = self.make_vault()
        task_id = "TASK-2026-07-26-0006-r2outbox"
        outbox = vault / "departments" / "coding" / "outbox"
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact=str(outbox / f"{task_id}-response.md"),
            write_scope="[_state/r2outbox/]",
        )
        output = completed.stdout + completed.stderr
        self.assertNotIn(
            "blocked response envelope destination already differs", output
        )
        self.assertNotIn("blocked settlement both failed", output)
        envelope_path = outbox / f"{task_id}-response.md"
        self.assertTrue(envelope_path.is_file(), msg=output)
        body = envelope_path.read_text(encoding="utf-8")
        self.assertTrue(body.startswith("---\n"), msg=body[:40])
        self.assertIn("status: blocked", body)
        self.assertIn("context builder failed", body)
        # Settled on the envelope's own status, and the scope is released.
        self.assertEqual(
            self.registry_entry(vault, task_id)["status"], "blocked", msg=output
        )

    def test_an_artifact_outside_the_vault_is_not_rewritten_into_it(self) -> None:
        """Containment: never fabricate an in-repo path for an out-of-repo one."""
        vault = self.make_vault()
        outside = vault.parent / "outside"
        outside.mkdir()
        task_id = "TASK-2026-07-26-0005-r2outside"
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact=str(outside / f"{task_id}-response.md"),
            write_scope="[]",
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertEqual(list(outside.iterdir()), [], msg=f"escaped: {output}")
        # Settlement legitimately cannot publish an envelope for a path it may
        # not rewrite, so the die path is what has to release the scope.
        self.assertEqual(
            self.registry_entry(vault, task_id)["status"], "cancelled", msg=output
        )


if __name__ == "__main__":
    unittest.main()
