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

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402

# See dispatch_checkout: send-task.sh refuses to dispatch from a linked
# worktree, and that refusal runs before the guards this suite tests -- so
# without this the result depends on checkout shape, not on behaviour.
# The helper returns the root unchanged in a main checkout.
REPO = normal_checkout_root(Path(__file__).resolve().parents[3])
SEND_TASK = REPO / "bin" / "send-task.sh"

# Vault subtrees send-task.sh reads out of the repo. `bin` is deliberately not
# in this list: some tests need a per-file bin so one executable can be omitted.
LINKED_SUBTREES = ("shared", "model-lanes")

MAILBOXES = ("inbox", "active", "outbox", "archive")


def envelope(fields: dict[str, str], body: str = "body") -> str:
    rows = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{rows}\n---\n\n{body}\n"


class SendTaskFixture(unittest.TestCase):
    """A throwaway VAULT_ROOT that borrows the repo's code but not its state."""

    def install_scripts(self, vault: Path) -> None:
        scripts = vault / "scripts"
        scripts.mkdir()
        for entry in (REPO / "scripts").iterdir():
            if entry.name != "python":
                (scripts / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        python_dir = scripts / "python"
        python_dir.mkdir()
        for entry in (REPO / "scripts" / "python").iterdir():
            if entry.name != "host_admission.py":
                (python_dir / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        (python_dir / "host_admission.py").write_text(
            "import hashlib, json, os, sys\n"
            "args = sys.argv[1:]\n"
            "flag = '--candidate' if '--candidate' in args else '--task-file'\n"
            "paths = [args[i + 1] for i, value in enumerate(args) if value == flag]\n"
            "path = os.environ.get('HOST_ADMISSION_TEST_LOG')\n"
            "open(path, 'a').write(json.dumps(args) + '\\n') if path else None\n"
            "hash_path = os.environ.get('HOST_ADMISSION_TEST_HASH_LOG')\n"
            "open(hash_path, 'a').write(hashlib.sha256(open(paths[0], 'rb').read()).hexdigest() + '\\n') if hash_path else None\n"
            "originals = [open(item, 'rb').read() for item in paths]\n"
            "rebound = os.environ.get('HOST_ADMISSION_TEST_REBIND')\n"
            "if rebound == 'aba':\n"
            "    [open(item, 'wb').write(raw + b'\\nB-during-admission\\n') for item, raw in zip(paths, originals)]\n"
            "elif rebound == 'sibling':\n"
            "    [open(item, 'wb').write(raw) for item, raw in zip(paths, reversed(originals))]\n"
            "[open(item, 'wb').write(raw) for item, raw in zip(paths, originals)] if rebound else None\n"
            "vector = args[args.index('--vector-sha256') + 1] if '--vector-sha256' in args else ''\n"
            "if rebound: vector = ('b' if rebound == 'aba' else 'c') * 64\n"
            "denied = os.environ.get('HOST_ADMISSION_TEST_DENY') == '1'\n"
            "print(json.dumps({'admitted': not denied, 'action': 'queue' if denied else 'admit', 'candidate_vector_sha256': vector}))\n"
            "raise SystemExit(75 if denied else 0)\n",
            encoding="utf-8",
        )

    def install_specialist_tree(self, vault: Path) -> None:
        """Give the vault the real specialist + adapter tree the builder reads."""
        specialists = vault / "departments" / "coding" / "specialists"
        specialists.mkdir(exist_ok=True)
        shutil.copy2(
            REPO / "departments/coding/specialists/systems-engineer.md",
            specialists / "systems-engineer.md",
        )
        (vault / "model-lanes").unlink()
        shutil.copytree(REPO / "model-lanes", vault / "model-lanes")

    def shadow_lane_entrypoint(self, vault: Path, claude: Path) -> None:
        """Point the vault's context builder at a chosen `claude` entrypoint.

        `bin/send-task.sh:44-46` prefers a builder the vault ships itself, so
        this is the supported seam for supplying the one *host* artefact the
        real builder demands -- an absolute, executable lane entrypoint. The
        builder module itself is executed unshadowed: packet parsing, scope
        containment, adapter resolution and the capability surface all run
        against the real code, and the real availability check still runs
        against whatever path is injected here. A genuinely absent CLI on a
        real host therefore still fails closed; only the location is supplied.

        Every *other* lane is pointed at a path that does not exist, so the run
        is proven to depend on no installed CLI at all rather than merely
        having one of its four host dependencies papered over. If a later
        change makes the builder consult a second lane's entrypoint, this fails
        on every host instead of only on a bare runner.
        """
        target = vault / "scripts" / "python" / "dispatch_context_builder.py"
        target.unlink()
        target.write_text(
            "import importlib.util, pathlib, sys\n"
            f"spec = importlib.util.spec_from_file_location('trusted_dcb', "
            f"{str(REPO / 'scripts/python/dispatch_context_builder.py')!r})\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "sys.modules[spec.name] = module\n"
            "spec.loader.exec_module(module)\n"
            "module.LANE_CLI_PATHS.update(\n"
            "    {lane: pathlib.Path('/fixture/no-such-' + lane)\n"
            "     for lane in module.LANE_CLI_PATHS}\n"
            ")\n"
            f"module.LANE_CLI_PATHS['claude'] = pathlib.Path({str(claude)!r})\n"
            "raise SystemExit(module.main())\n",
            encoding="utf-8",
        )

    def install_lane_cli_fixture(self, vault: Path) -> Path:
        """A real executable file standing in for the host's lane entrypoint."""
        executable = vault.parent / "fixture-claude"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        return executable

    def shadow_process_truth(self, vault: Path) -> dict[str, str]:
        """Stop racing the spawned child for the detach-abort observation.

        `bin/send-task.sh` proves a detach abort by finding the child already
        gone the first time it samples the process table (bin/send-task.sh:
        2474-2483). The fixture supervisor dies ~4ms after Popen returns, so
        whether that ever happens is a race against the sampler's own cost:
        measured 3-of-5 lost on macOS, where `observe_process` spawns /bin/ps.
        On Linux it reads /proc/<pid>/stat instead, and the child was still
        alive at 8-of-8 near-zero-cost samples -- the abort could not fire on
        the runner at all, so the CI red was never only the missing CLI.

        This shadow answers nothing itself. It waits until the child has
        genuinely exited and then calls the REAL `observe_process`, which
        returns None for its own reason (the zombie fails its `Z` state
        check). `atomic_write_json` and `utc_now` stay real, and everything
        downstream -- the raise, terminate(), the `lexists` descriptor test,
        BOARD_DETACH_ABORT_PROVEN and the settlement -- is untouched
        production code. The wait is bounded: a child that outlives the bound
        yields the real observation, so a supervisor that does NOT abort still
        fails this test loudly instead of defaulting to the wanted answer.
        """
        target = vault / "scripts" / "python" / "board_process_truth.py"
        target.unlink()
        target.write_text(
            "import importlib.util, os, sys, time\n"
            f"spec = importlib.util.spec_from_file_location('trusted_bpt', "
            f"{str(REPO / 'scripts/python/board_process_truth.py')!r})\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "sys.modules[spec.name] = module\n"
            "spec.loader.exec_module(module)\n"
            "globals().update(\n"
            "    {k: v for k, v in vars(module).items() if not k.startswith('__')}\n"
            ")\n"
            "_observe = module.observe_process\n"
            "\n"
            "def observe_process(pid):\n"
            "    if os.environ.get('SENDTASK_TEST_AWAIT_CHILD_EXIT') != '1':\n"
            "        return _observe(pid)\n"
            "    deadline = time.monotonic() + 5.0\n"
            "    identity = _observe(pid)\n"
            "    while identity is not None and time.monotonic() < deadline:\n"
            "        time.sleep(0.005)\n"
            "        identity = _observe(pid)\n"
            "    return identity\n",
            encoding="utf-8",
        )
        return {"SENDTASK_TEST_AWAIT_CHILD_EXIT": "1"}

    def make_vault(self, *, omit_from_bin: str | None = None) -> Path:
        root = Path(tempfile.mkdtemp(prefix="r2-sendtask-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        vault = root / "vault"
        vault.mkdir()
        for name in LINKED_SUBTREES:
            (vault / name).symlink_to(REPO / name)
        self.install_scripts(vault)
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
        extra_fields: dict[str, str] | None = None,
        extra_env: dict[str, str] | None = None,
        dispatch_args: tuple[str, ...] = (),
        packet_in_vault: bool = False,
    ) -> subprocess.CompletedProcess:
        packet = (vault if packet_in_vault else vault.parent) / f"{task_id}.md"
        # `specialist: none` + `direct_lane_work_allowed: true` skips the
        # specialist/adapter/capability gauntlet, so the run reaches the
        # registration and settlement code this suite is about.
        fields = {
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
        fields.update(extra_fields or {})
        packet.write_text(
            envelope(fields),
            encoding="utf-8",
        )
        return subprocess.run(
            [str(SEND_TASK), str(packet), *dispatch_args],
            env={
                **os.environ,
                "VAULT_ROOT": str(vault),
                "SKIP_NUDGE": "1",
                # `vault` is a plain directory, not a git checkout (this fixture
                # borrows the repo's code but not its state), so send-task.sh
                # cannot derive a branch and now refuses to guess one. That
                # refusal is correct for a real checkout in detached HEAD; here
                # it is irrelevant to what these tests exercise, so supply the
                # value explicitly rather than weakening the production guard.
                "SQUAD_BASE_BRANCH": "v2",
                **(extra_env or {}),
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
# Dispatch preflight stdout is a machine channel; stderr is diagnostic
# ─────────────────────────────────────────────────────────────────────────────


class PreflightStreamSeparationTests(SendTaskFixture):
    DIAGNOSTIC = "fixture preflight: benign diagnostic on stderr"
    REFUSAL_REASON = "fixture preflight: exact refusal reason"

    def install_preflight_fixture(
        self,
        vault: Path,
        *,
        exit_code: int,
        decision: str,
        refusal_reason: str = "",
    ) -> None:
        """Replace this test's temp-vault symlink with a preflight fixture."""

        target = vault / "scripts" / "python" / "dispatch_preflight.py"
        target.unlink()  # Test-created symlink only; the shipped helper is untouched.
        target.write_text(
            "import hashlib, json, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "packet = Path(args[args.index('--packet') + 1])\n"
            f"diagnostic = {self.DIAGNOSTIC!r}\n"
            f"decision = {decision!r}\n"
            f"reason = {refusal_reason!r}\n"
            "verdict = {\n"
            "    'schema': 'dispatch-preflight/v1',\n"
            "    'packet_sha256': hashlib.sha256(packet.read_bytes()).hexdigest(),\n"
            "    'decision': decision,\n"
            "    'refusals': ([{'code': 'fixture_refusal', 'message': reason}]\n"
            "                 if reason else []),\n"
            "}\n"
            "print(diagnostic, file=sys.stderr)\n"
            "print(json.dumps(verdict, separators=(',', ':')))\n"
            f"raise SystemExit({exit_code})\n",
            encoding="utf-8",
        )

    def test_benign_preflight_stderr_remains_visible_and_dispatch_continues(
        self,
    ) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        self.install_preflight_fixture(vault, exit_code=0, decision="allow")
        task_id = "TASK-2026-08-11-0370-preflight-stderr"

        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/sendtask-streams/out.md",
            write_scope="[_state/sendtask-streams/]",
            extra_env={"UV_CACHE_DIR": str(vault.parent / "uv-cache")},
        )
        output = completed.stdout + completed.stderr

        # The absent supervisor is a deterministic post-registration sentinel:
        # reaching it proves the benign diagnostic did not create a false
        # preflight refusal, while ensuring this test cannot launch a model CLI.
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("missing board supervisor", output)
        self.assertNotIn("dispatch preflight returned invalid JSON", output)
        self.assertIn(self.DIAGNOSTIC, completed.stderr)
        self.assertNotIn(self.DIAGNOSTIC, completed.stdout)
        self.assertEqual(
            self.registry_entry(vault, task_id)["status"],
            "cancelled",
        )

    def test_real_preflight_refusal_keeps_reason_on_the_die_line(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        self.install_preflight_fixture(
            vault,
            exit_code=3,
            decision="deny",
            refusal_reason=self.REFUSAL_REASON,
        )

        completed = self.dispatch(
            vault,
            task_id="TASK-2026-08-11-0371-preflight-refusal",
            return_artifact="_state/sendtask-streams/refused.md",
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(self.DIAGNOSTIC, completed.stderr.splitlines())
        die_lines = [
            line
            for line in completed.stderr.splitlines()
            if line.startswith("ERROR: dispatch preflight refused:")
        ]
        self.assertEqual(len(die_lines), 1, msg=completed.stderr)
        self.assertIn(self.REFUSAL_REASON, die_lines[0])
        self.assertNotIn(self.DIAGNOSTIC, die_lines[0])


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
    def dispatch_rebound_vector(self, mode: str, rebound: str) -> tuple[Path, subprocess.CompletedProcess, Path]:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        task_id = f"TASK-2026-08-08-91{len(mode):02d}-{mode}-{rebound}"
        log = vault.parent / f"{mode}-{rebound}-admission.jsonl"
        fields: dict[str, str] = {}
        args: tuple[str, ...] = ()
        packet_in_vault = False
        if mode == "fanout":
            fields = {
                "specialist": "skeptic", "to_model": "gpt-codex",
                "source_namespace": "shared", "mode": "project",
                "run_id": "PROJ-P6-REBIND-2026-08-08", "result_type": "normal",
                "mandatory_review": "true", "review_model": "claude",
                "direct_lane_work_allowed": "false",
                "model_override_reason": "hermetic vector-binding fixture",
            }
            args = (
                "--panel", "skeptic,skeptic", "--fanout",
                "--panel-assignment", "inspect first slot",
                "--panel-assignment", "inspect second slot",
            )
            packet_in_vault = True
        elif mode == "swarm":
            specialists = vault / "departments" / "coding" / "specialists"
            specialists.mkdir()
            shutil.copy2(
                REPO / "departments/coding/specialists/code-reviewer.md",
                specialists / "code-reviewer.md",
            )
            fields = {
                "specialist": "code-reviewer", "to_model": "gpt-codex",
                "mode": "bounty", "run_id": "BTY-P6-REBIND-2026-08-08",
                "result_type": "dry_run", "mandatory_review": "true",
                "review_model": "claude", "direct_lane_work_allowed": "false",
            }
            args = ("--swarm", "gpt-codex,claude")
        completed = self.dispatch(
            vault, task_id=task_id, return_artifact=f"_state/{mode}-{rebound}/out.md",
            extra_fields=fields,
            extra_env={
                "HOST_ADMISSION_TEST_LOG": str(log),
                "HOST_ADMISSION_TEST_REBIND": rebound,
            },
            dispatch_args=args,
            packet_in_vault=packet_in_vault,
        )
        return vault, completed, log

    def assert_rebound_vector_rejected(self, mode: str, rebound: str) -> None:
        vault, completed, log = self.dispatch_rebound_vector(mode, rebound)
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("candidate vector binding mismatch", output)
        self.assertFalse((vault / "_state/active-tasks.json").exists())
        self.assertEqual(list((vault / "departments/coding/inbox").iterdir()), [])
        argv = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(argv.count("--candidate"), 1 if mode == "single" else 2)

    def test_aba_rebind_is_rejected_for_single_fanout_and_swarm(self) -> None:
        for mode in ("single", "fanout", "swarm"):
            with self.subTest(mode=mode):
                self.assert_rebound_vector_rejected(mode, "aba")

    def test_sibling_swap_is_rejected_for_fanout_and_swarm(self) -> None:
        for mode in ("fanout", "swarm"):
            with self.subTest(mode=mode):
                self.assert_rebound_vector_rejected(mode, "sibling")

    def test_missing_native_cli_is_typed_before_detach(self) -> None:
        vault = self.make_vault()
        # The negative control for the entrypoint injection that the
        # detach-abort test relies on: the same seam, pointed at a path that
        # does not exist, must still fail closed and type the failure.
        self.shadow_lane_entrypoint(vault, Path("/fixture/no-such-claude"))
        self.install_specialist_tree(vault)
        task_id = "TASK-2026-08-08-9002-cli-missing"
        completed = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/cli-missing/out.md",
            write_scope="[_state/cli-missing/]", extra_fields={
                "specialist": "systems-engineer", "mode": "project",
                "run_id": "PROJ-P6-CLI-MISSING-2026-08-08", "result_type": "normal",
                "mandatory_review": "false", "review_model": "none",
                "model_override_reason": "hermetic missing-CLI fixture",
            },
        )
        output = completed.stdout + completed.stderr
        envelope_path = vault / "departments/coding/outbox" / f"{task_id}-response.md"
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("failure_class: cli_missing", envelope_path.read_text())
        self.assertEqual(self.registry_entry(vault, task_id)["status"], "blocked")
        self.assertFalse(list((vault / "_state/board-dispatch").glob("*.dispatch.json")))
        self.assertNotIn("Board dispatch detached", output)

    def test_external_batch_marker_cannot_skip_single_admission(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        log = vault.parent / "host-admission.jsonl"
        hash_log = vault.parent / "host-admission.sha256"
        task_id = "TASK-2026-08-08-9003-admission-env"
        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/admission-env/out.md",
            extra_env={
                "BOARD_BATCH_ADMITTED": "1",
                "BOARD_PACKET_FINAL": "1",
                "BOARD_PRE_REGISTERED": "1",
                "BOARD_PREPARE_TARGET": "/forged",
                "HOST_ADMISSION_TEST_LOG": str(log),
                "HOST_ADMISSION_TEST_HASH_LOG": str(hash_log),
            },
        )
        self.assertIn("missing board supervisor", completed.stdout + completed.stderr)
        calls = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 1)
        argv = json.loads(calls[0])
        self.assertIn("--repo-root", argv)
        self.assertEqual(argv.count("--candidate"), 1)
        self.assertIn("--vector-sha256", argv)
        delivered = vault / "departments/coding/inbox" / f"{task_id}.md"
        self.assertEqual(
            hash_log.read_text(encoding="utf-8").strip(),
            hashlib.sha256(delivered.read_bytes()).hexdigest(),
        )

    def test_denial_leaves_no_single_packet_or_registry_publication(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        task_id = "TASK-2026-08-08-9004-admission-denied"
        completed = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/denied/out.md",
            extra_env={"HOST_ADMISSION_TEST_DENY": "1"},
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("queued candidate vector", completed.stdout + completed.stderr)
        self.assertFalse((vault / f"departments/coding/inbox/{task_id}.md").exists())
        self.assertFalse((vault / "_state/active-tasks.json").exists())
        self.assertEqual(list(vault.parent.glob(f"{task_id}.working.md.*")), [])

    def test_denied_swarm_vector_publishes_no_registry_or_mailbox_members(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        specialists = vault / "departments/coding/specialists"
        specialists.mkdir()
        shutil.copy2(
            REPO / "departments/coding/specialists/code-reviewer.md",
            specialists / "code-reviewer.md",
        )
        task_id = "TASK-2026-08-08-9005-swarm-denied"
        log = vault.parent / "swarm-admission.jsonl"
        hash_log = vault.parent / "swarm-admission.sha256"
        completed = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/swarm-denied/out.md",
            extra_fields={
                "specialist": "code-reviewer", "to_model": "gpt-codex",
                "mode": "bounty", "run_id": "BTY-P6-DENIED-2026-08-08",
                "result_type": "dry_run", "mandatory_review": "true",
                "review_model": "claude", "direct_lane_work_allowed": "false",
            },
            extra_env={
                "HOST_ADMISSION_TEST_DENY": "1",
                "HOST_ADMISSION_TEST_LOG": str(log),
                "HOST_ADMISSION_TEST_HASH_LOG": str(hash_log),
            },
            dispatch_args=("--swarm", "gpt-codex,claude"),
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("queued candidate vector", output)
        self.assertFalse((vault / "_state/active-tasks.json").exists())
        self.assertEqual(list((vault / "departments/coding/inbox").iterdir()), [])
        argv = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(argv.count("--candidate"), 2)
        packets = [Path(argv[index + 1]) for index, item in enumerate(argv) if item == "--candidate"]
        self.assertEqual(len(hash_log.read_text(encoding="utf-8").splitlines()), 1)
        for packet in packets:
            staged = packet.read_text(encoding="utf-8")
            self.assertIn("verification_contract_sha256:", staged)
            self.assertIn("Hard constraint: no file deletion", staged)

    def test_swarm_publishes_before_registration_and_reuses_exact_prefix(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        specialists = vault / "departments/coding/specialists"
        specialists.mkdir()
        shutil.copy2(
            REPO / "departments/coding/specialists/code-reviewer.md",
            specialists / "code-reviewer.md",
        )
        task_id = "TASK-2026-08-08-9005-swarm-replay"
        inbox = vault / "departments/coding/inbox"
        first_child = inbox / f"{task_id}-swarm-gpt-codex.md"
        conflicting_child = inbox / f"{task_id}-swarm-claude.md"
        conflicting_child.write_text("conflicting packet\n", encoding="utf-8")
        fields = {
            "specialist": "code-reviewer", "to_model": "gpt-codex",
            "mode": "bounty", "run_id": "BTY-P7-SWARM-REPLAY-2026-08-08",
            "result_type": "dry_run", "mandatory_review": "true",
            "review_model": "claude", "direct_lane_work_allowed": "false",
        }
        first = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/swarm-replay/out.md",
            extra_fields=fields, dispatch_args=("--swarm", "gpt-codex,claude"),
        )
        first_output = first.stdout + first.stderr
        self.assertNotEqual(first.returncode, 0, first_output)
        self.assertIn("refusing to replace conflicting swarm child packet", first_output)
        self.assertFalse((vault / "_state/active-tasks.json").exists())
        self.assertTrue(first_child.is_file())
        first_bytes = first_child.read_bytes()

        conflicting_child.unlink()
        second = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/swarm-replay/out.md",
            extra_fields=fields, dispatch_args=("--swarm", "gpt-codex,claude"),
        )
        second_output = second.stdout + second.stderr
        self.assertNotEqual(second.returncode, 0, second_output)
        self.assertIn("Reused exact swarm child", second_output)
        first_after = (
            first_child
            if first_child.exists()
            else vault / "departments/coding/archive" / first_child.name
        )
        self.assertEqual(first_after.read_bytes(), first_bytes)
        registry = json.loads(
            (vault / "_state/active-tasks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(registry),
            {task_id, f"{task_id}-swarm-gpt-codex", f"{task_id}-swarm-claude"},
        )
        children = [
            f"{task_id}-swarm-gpt-codex",
            f"{task_id}-swarm-claude",
        ]
        self.assertTrue(
            all(registry[child]["delivery_state"] == "terminal" for child in children)
        )

        # Simulate a hard sender stop after the first child crossed the start
        # fence but before the second child detached. A retry must skip the
        # first and still attempt the queued sibling.
        registry[children[0]]["status"] = "in-flight"
        registry[children[0]]["delivery_state"] = "in-progress"
        registry[children[1]]["status"] = "in-flight"
        registry[children[1]]["delivery_state"] = "queued"
        (vault / "_state/active-tasks.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        third = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/swarm-replay/out.md",
            extra_fields=fields, dispatch_args=("--swarm", "gpt-codex,claude"),
        )
        third_output = third.stdout + third.stderr
        self.assertNotEqual(third.returncode, 0, third_output)
        self.assertIn("Skipping already-started swarm child", third_output)
        replayed = json.loads(
            (vault / "_state/active-tasks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(replayed[children[1]]["delivery_state"], "terminal")

    def test_denied_fanout_admits_final_vector_before_any_publication(self) -> None:
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        log = vault.parent / "fanout-admission.jsonl"
        task_id = "TASK-2026-08-08-9006-fanout-denied"
        completed = self.dispatch(
            vault, task_id=task_id, return_artifact="_state/fanout-denied/out.md",
            extra_fields={
                "specialist": "skeptic", "to_model": "gpt-codex",
                "source_namespace": "shared",
                "mode": "project", "run_id": "PROJ-P6-DENIED-2026-08-08",
                "result_type": "normal", "mandatory_review": "true",
                "review_model": "claude", "direct_lane_work_allowed": "false",
                "model_override_reason": "hermetic fan-out fixture",
            },
            extra_env={
                "HOST_ADMISSION_TEST_DENY": "1",
                "HOST_ADMISSION_TEST_LOG": str(log),
            },
            dispatch_args=(
                "--panel", "skeptic,skeptic", "--fanout",
                "--panel-assignment", "inspect parser",
                "--panel-assignment", "inspect launcher",
            ),
            packet_in_vault=True,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("queued candidate vector", output)
        self.assertFalse((vault / "_state/active-tasks.json").exists())
        self.assertEqual(list((vault / "departments/coding/inbox").iterdir()), [])
        argv = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(argv.count("--candidate"), 2)
        for index, item in enumerate(argv):
            if item == "--candidate":
                staged = Path(argv[index + 1]).read_text(encoding="utf-8")
                self.assertIn("verification_contract_sha256:", staged)
                self.assertIn("Hard constraint: no file deletion", staged)

    def test_packet_directory_is_synced_before_registry_registration(self) -> None:
        text = SEND_TASK.read_text(encoding="utf-8")
        publication = text.split("# ── copy to source namespace inbox", 1)[1]
        publication = publication.split("# ── central dispatch log", 1)[0]

        file_sync = publication.index("os.fsync(inbox_temp.fileno())")
        rename = publication.index('mv -f "$INBOX_TEMP" "$DEST"')
        directory_open = publication.index(
            "directory_fd = os.open(sys.argv[1], os.O_RDONLY)"
        )
        directory_sync = publication.index("os.fsync(directory_fd)")
        registration = publication.index('--register-task "$TASK_ID"')

        self.assertLess(file_sync, rename)
        self.assertLess(rename, directory_open)
        self.assertLess(directory_open, directory_sync)
        self.assertLess(directory_sync, registration)

    def test_failed_detach_after_claim_terminalizes_only_descriptor_absent_attempt(self) -> None:
        """A proven Popen abort must not strand its exact in-progress attempt."""
        vault = self.make_vault(omit_from_bin="board-supervisor.sh")
        supervisor = vault / "bin" / "board-supervisor.sh"
        supervisor.write_text("not an executable image\n", encoding="utf-8")
        supervisor.chmod(0o755)
        self.install_specialist_tree(vault)
        # This packet reaches the board context build, which is the only step
        # here that wants a host artefact. Supply one, so the run gets to the
        # detach code this test is actually about on a host with no lane CLI.
        self.shadow_lane_entrypoint(vault, self.install_lane_cli_fixture(vault))
        detach_env = self.shadow_process_truth(vault)
        task_id = "TASK-2026-08-07-0001-detach-abort"

        completed = self.dispatch(
            vault,
            task_id=task_id,
            return_artifact="_state/r2detach/out.md",
            write_scope="[_state/r2detach/]",
            extra_env=detach_env,
            extra_fields={
                "specialist": "systems-engineer",
                "model_override_reason": "deterministic detach-abort fixture",
                "mode": "project",
                "run_id": "PROJ-DETACH-ABORT-2026-08-07",
                "result_type": "normal",
                "mandatory_review": "false",
                "review_model": "none",
            },
        )

        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, msg=output)
        self.assertIn("failed to detach board supervisor", output)
        entry = self.registry_entry(vault, task_id)
        self.assertEqual(entry["status"], "cancelled", msg=output)
        self.assertEqual(entry["delivery_state"], "terminal", msg=output)
        self.assertIn("detach", entry.get("never_launched_reason", ""))
        board = vault / "_state" / "board-dispatch"
        self.assertFalse(list(board.glob(f"{task_id}.*.dispatch.json")))

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

    def test_a_live_or_identity_changed_attempt_is_never_closed_by_die(self) -> None:
        """Fail closed: only an exact proven detach abort may be cancelled.

        Asserted against the settle helper's own body rather than the whole
        script: an identical guard already exists in the delivery-start block,
        so a file-wide search would pass without the new code.
        """
        text = SEND_TASK.read_text(encoding="utf-8")
        opener = "settle_registered_task_cancelled() {"
        self.assertIn(opener, text, msg="post-registration settle helper is absent")
        body = text.split(opener, 1)[1].split("\n}\n", 1)[0]
        # The exceptional in-progress release needs first-hand child-stop proof,
        # exact attempt/generation, no worker identity, and no descriptor/receipt.
        for clause in (
            'entry.get("status") != "in-flight"',
            'BOARD_ABORT_PROVEN_VALUE',
            'entry.get("delivery_state") == "in-progress"',
            'entry.get("delivery_attempt_id") == attempt',
            'type(entry.get("delivery_generation")) is int',
            'entry.get("delivery_generation") == generation',
            'item.get("transport") == "board-supervisor"',
            'type(item.get("generation")) is int',
            'not entry.get("delivery_worker_id")',
            '(".dispatch.json", ".receipt.json")',
            'os.path.lexists',
        ):
            self.assertIn(clause, body, msg=f"missing fail-closed clause: {clause}")

    def test_detach_abort_proof_cannot_cross_descriptor_or_generation_fence(self) -> None:
        vault = self.make_vault()
        task, attempt = "TASK-2026-08-07-0002-fenced", "d-exact"
        registry_path = vault / "_state" / "active-tasks.json"
        entry = {
            "status": "in-flight", "delivery_state": "in-progress",
            "delivery_attempt_id": attempt, "delivery_generation": 1,
            "claimed_at": "2026-08-07T00:00:00Z",
            "started_at": "2026-08-07T00:00:00Z",
            "delivery_worker_id": None,
            "delivery_history": [{"event": "in-progress", "transport": "board-supervisor",
                                  "attempt_id": attempt, "generation": 1}],
        }
        registry_path.write_text(json.dumps({task: entry}), encoding="utf-8")
        text = SEND_TASK.read_text(encoding="utf-8")
        body = text.split("settle_registered_task_cancelled() {", 1)[1].split("\n}\n", 1)[0]
        code = body.split("<<'PYEOF' >&2 || true\n", 1)[1].rsplit("\nPYEOF", 1)[0]
        environment = {
            **os.environ, "VAULT_ROOT": str(vault), "SETTLE_REASON_VALUE": "detach failed",
            "BOARD_ABORT_PROVEN_VALUE": "1", "BOARD_ATTEMPT_VALUE": attempt,
            "BOARD_GENERATION_VALUE": "1",
        }
        base = vault / "_state" / "board-dispatch" / f"{task}.{attempt}"
        base.parent.mkdir()
        Path(f"{base}.dispatch.json").write_text("{}\n", encoding="utf-8")
        subprocess.run([sys.executable, "-", str(vault), task], input=code, env=environment,
                       text=True, check=True, capture_output=True)
        self.assertEqual(self.registry_entry(vault, task)["status"], "in-flight")
        Path(f"{base}.dispatch.json").unlink()
        environment["BOARD_GENERATION_VALUE"] = "2"
        subprocess.run([sys.executable, "-", str(vault), task], input=code, env=environment,
                       text=True, check=True, capture_output=True)
        self.assertEqual(self.registry_entry(vault, task)["status"], "in-flight")

        environment["BOARD_GENERATION_VALUE"] = "1"
        for registry_generation, history in (
            (1, None),
            (1, {}),
            (1, [{"event": "in-progress", "transport": "board-supervisor",
                  "attempt_id": "d-other", "generation": 1}]),
            (True, [{"event": "in-progress", "transport": "board-supervisor",
                     "attempt_id": attempt, "generation": 1}]),
        ):
            with self.subTest(registry_generation=registry_generation, history=history):
                fenced = dict(entry)
                fenced["delivery_generation"] = registry_generation
                if history is None:
                    fenced.pop("delivery_history", None)
                else:
                    fenced["delivery_history"] = history
                registry_path.write_text(json.dumps({task: fenced}), encoding="utf-8")
                subprocess.run([sys.executable, "-", str(vault), task], input=code,
                               env=environment, text=True, check=True, capture_output=True)
                self.assertEqual(self.registry_entry(vault, task)["status"], "in-flight")

    def test_pre_registered_board_child_arms_exact_abort_settlement(self) -> None:
        text = SEND_TASK.read_text(encoding="utf-8")
        branch = text.split('if [[ "$BOARD_PRE_REGISTERED" == "1" ]]', 1)[1]
        branch = branch.split("elif REGISTRY_ENTRY_JSON", 1)[0]
        self.assertIn("TASK_REGISTERED=1", branch)


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
        # Settlement publishes the exact task-owned blocked stub at the
        # normalized path, then terminal reconciliation retires it so a
        # replacement task can use the requested artifact path. The audit copy
        # must remain inside the vault even though the registry kept the
        # original absolute spelling.
        retired = artifact.with_name(f"out.md.blocked-{task_id}")
        self.assertFalse(artifact.exists(), msg=output)
        self.assertTrue(retired.is_file(), msg=output)
        self.assertIn(
            f"# Board dispatch blocked — {task_id}",
            retired.read_text(encoding="utf-8"),
        )
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
