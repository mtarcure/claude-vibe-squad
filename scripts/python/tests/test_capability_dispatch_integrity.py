from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = REPO_ROOT / "bin/send-task.sh"
INSPECTOR = REPO_ROOT / "scripts/python/capability_dispatch.py"
RECONCILER = REPO_ROOT / "scripts/python/registry_reconciler.py"
VERIFICATION_HELPER = REPO_ROOT / "scripts/python/verification_contract.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(VERIFICATION_HELPER.parent) not in sys.path:
    sys.path.insert(0, str(VERIFICATION_HELPER.parent))

from scripts.python.tests.supervisor_lifecycle import (  # noqa: E402
    cleanup_supervisors_before_root,
)
import registry_reconciler as rr  # noqa: E402
from verification_contract import verification_contract_sha256  # noqa: E402


class ManagedSupervisorTestCase(unittest.TestCase):
    """Own temp roots and any detached board supervisors launched against them."""

    def _managed_root(self, prefix: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix=prefix))
        # One cleanup owns both operations, making the required ordering
        # structural rather than dependent on unittest's LIFO registration.
        self.addCleanup(cleanup_supervisors_before_root, root)
        return root


REVIEW_TASK_ID = "TASK-REVIEW-9997"


def envelope(frontmatter: dict[str, str], body: str = "done") -> str:
    fields = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    return f"---\n{fields}\n---\n\n{body}\n"


def install_board_rail_fixture(root: Path) -> None:
    for relative in (
        "scripts/python/registry_reconciler.py",
        "scripts/python/repo_root.py",
        "scripts/python/board_process_truth.py",
        # board_process_truth imports this to validate and publish the dispatcher's
        # plan-item declaration; send-task.sh also runs it directly to validate the
        # packet field. Staged for the same reason durable_publish is.
        "scripts/python/plan_item_binding.py",
        "scripts/python/durable_publish.py",
    ):
        source = REPO_ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # Capability dispatch is the subject here; process-table parsing has its own
    # suite. Keep the real process-truth serialization contract, but replace its
    # host probe because the Codex macOS sandbox denies /bin/ps. The spawned
    # supervisor is a fresh session leader, so pid/pgid still fence the exact
    # fixture process that the production detach path launched.
    with (root / "scripts/python/board_process_truth.py").open(
        "a", encoding="utf-8"
    ) as process_truth:
        process_truth.write(
            "\n\ndef observe_process(pid):\n"
            "    try:\n"
            "        pid, pgid = int(pid), os.getpgid(int(pid))\n"
            "    except (TypeError, ValueError, OSError):\n"
            "        return None\n"
            "    argv = ('capability-dispatch-fixture:%s' % pid).encode()\n"
            "    return {\n"
            "        'pid': pid,\n"
            "        'pgid': pgid,\n"
            "        'process_start_token': 'fixture:%s' % pid,\n"
            "        'argv_sha256': hashlib.sha256(argv).hexdigest(),\n"
            "    }\n"
        )

    (root / "scripts/python/host_admission.py").write_text(
        "import json,sys\n"
        "args=sys.argv[1:]\n"
        "vector=args[args.index('--vector-sha256')+1]\n"
        "print(json.dumps({'admitted':True,'action':'admit','candidate_vector_sha256':vector}))\n",
        encoding="utf-8",
    )

    context_builder = root / "scripts/python/dispatch_context_builder.py"
    context_builder.write_text(
        "from pathlib import Path\n"
        "import sys\n\n"
        "if len(sys.argv) < 2 or sys.argv[1] != 'build':\n"
        "    raise SystemExit('fixture supports only board context build')\n"
        "try:\n"
        "    output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "except (ValueError, IndexError):\n"
        "    raise SystemExit('missing --output')\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "output.write_text('{}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    supervisor = root / "bin/board-supervisor.sh"
    supervisor.parent.mkdir(parents=True, exist_ok=True)
    supervisor.write_text(
        "#!/bin/sh\n"
        "[ \"${1:-}\" = \"detached-launch\" ] || exit 64\n"
        ": \"${BOARD_DISPATCH_DESCRIPTOR_PATH:?}\"\n"
        "while [ ! -f \"$BOARD_DISPATCH_DESCRIPTOR_PATH\" ]; do sleep 0.01; done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    supervisor.chmod(0o755)


class CapabilityDispatchSnapshotTests(ManagedSupervisorTestCase):
    def _frontmatter(self, text: str) -> dict[str, object]:
        _start, raw, _body = text.split("---", 2)
        parsed: dict[str, object] = {}
        for line in raw.splitlines():
            if not line or line[0].isspace() or ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            parsed[key] = json.loads(value) if value.startswith(("{", "[")) else value
        return parsed

    def test_degraded_blueprint_requires_exact_typed_acknowledgement(self) -> None:
        root = self._managed_root("capability-inspector-")
        (root / "shared/registries").mkdir(parents=True)
        shutil.copy2(
            REPO_ROOT / "shared/registries/skill-tool-registry.tsv",
            root / "shared/registries/skill-tool-registry.tsv",
        )
        shutil.copy2(
            REPO_ROOT / "shared/specialist-runtime-map.tsv",
            root / "shared/specialist-runtime-map.tsv",
        )
        card = root / "shared/capabilities/project/degraded-fixture.md"
        card.parent.mkdir(parents=True)
        card.write_text(
            """---
id: project/degraded-fixture
mode: project
title: Degraded fixture
capability_state: degraded-blueprint
state_reason: Vercel is not authenticated.
state_evidence: Unit fixture.
overlays: []
gates: []
cost_note: subscription
---
| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake | `Chrono` | — | — | — |
| **S3** Produce | `Chrono` | `Vercel` (local · partial · subscription) | — | — |
| **S7** Capture | `Chrono` | — | — | — |
""",
            encoding="utf-8",
        )

        held = subprocess.run(
            [
                sys.executable,
                str(INSPECTOR),
                "--root",
                str(root),
                "--mode",
                "project",
                "--capability",
                "degraded-fixture",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        allowed = subprocess.run(
            [
                sys.executable,
                str(INSPECTOR),
                "--root",
                str(root),
                "--mode",
                "project",
                "--capability",
                "degraded-fixture",
                "--ack",
                "degraded-blueprint",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(held.returncode, 0, held.stderr)
        self.assertEqual(json.loads(held.stdout)["dispatch_decision"], "hold")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["dispatch_decision"], "allow")

    def test_actual_dispatch_injects_and_registers_snapshot(self) -> None:
        root = self._managed_root("capability-dispatch-")
        for relative in (
            "shared/registries/skill-tool-registry.tsv",
            "shared/specialist-runtime-map.tsv",
            "shared/capabilities/project/web-app.md",
            "scripts/python/capability_dispatch.py",
            "scripts/python/validate_capabilities.py",
            "scripts/python/verification_contract.py",
        ):
            source = REPO_ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        install_board_rail_fixture(root)
        wrapper = root / "bin/registry-reconciler.sh"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(
            f"#!/bin/sh\nexec {sys.executable} {RECONCILER} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        packet = root / "source-task.md"
        task_id = "TASK-2026-07-17-9998-capability-snapshot"
        packet.write_text(
            envelope(
                {
                    "id": task_id,
                    "to_model": "gpt-codex",
                    "specialist": "none",
                    "source_namespace": "shared",
                    "compatibility_namespace": "coding",
                    "mode": "project",
                    "run_id": "PRJ-CAPABILITY-SNAPSHOT",
                    "capability": "web-app",
                    "write_scope": "[]",
                    "parallel_safe": "false",
                    "direct_lane_work_allowed": "true",
                    "mandatory_review": "false",
                    "review_model": "none",
                    "reviews": "none",
                    "return_artifact": "_state/result.md",
                },
                "Build the application.",
            ),
            encoding="utf-8",
        )
        # `root` is a plain tempdir, not a git checkout, so send-task.sh cannot
        # derive a branch and now refuses to guess one; supply it explicitly.
        env = {
            **os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1",
            "SQUAD_BASE_BRANCH": "v2",
        }
        env.pop("SQUAD_DISPATCH_MODE", None)

        result = subprocess.run(
            [str(SEND_TASK), str(packet)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        registry = json.loads((root / "_state/active-tasks.json").read_text())
        entry = registry[task_id]
        delivered = (
            root / f"departments/coding/inbox/{task_id}.md"
        ).read_text(encoding="utf-8")
        delivered_frontmatter = self._frontmatter(delivered)
        self.assertEqual(entry["capability_id"], "project/web-app")
        self.assertEqual(entry["capability_derived_state"], "live")
        self.assertEqual(
            entry["capability_gates"],
            ["public_release", "production_mutation", "credential_change"],
        )
        self.assertRegex(entry["capability_card_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn(
            f"capability_card_sha256: {entry['capability_card_sha256']}", delivered
        )
        self.assertIn("immutable completion contract", delivered)
        self.assertEqual(entry["author_family"], "openai")
        self.assertEqual(delivered_frontmatter["author_family"], "openai")
        self.assertEqual(
            entry["verification_contract"],
            delivered_frontmatter["verification_contract"],
        )
        self.assertEqual(
            entry["verification_contract_sha256"],
            delivered_frontmatter["verification_contract_sha256"],
        )
        emitted = __import__("re").search(
            r"Verification contract: version=verification-contract/v1 sha256=([0-9a-f]{64})",
            result.stdout,
        )
        self.assertIsNotNone(emitted, result.stdout)
        self.assertEqual(emitted.group(1), entry["verification_contract_sha256"])
        self.assertEqual(
            verification_contract_sha256(delivered_frontmatter["verification_contract"]),
            emitted.group(1),
        )


class VerificationContractDispatchTests(ManagedSupervisorTestCase):
    def _root(self) -> Path:
        root = self._managed_root("verification-contract-dispatch-")
        for relative in (
            "shared/registries/skill-tool-registry.tsv",
            "shared/specialist-runtime-map.tsv",
            "scripts/python/verification_contract.py",
        ):
            source = REPO_ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        install_board_rail_fixture(root)
        wrapper = root / "bin/registry-reconciler.sh"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(
            f"#!/bin/sh\nexec {sys.executable} {RECONCILER} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return root

    def _packet(
        self,
        root: Path,
        *,
        task_id: str,
        mode: str = "project",
        run_id: str | None = "PRJ-DISPATCH-TEST",
        result_type: str | None = None,
        reserved: tuple[str, str] | None = None,
    ) -> Path:
        fields = {
            "id": task_id,
            "to_model": "gpt-codex",
            "specialist": "none",
            "source_namespace": "shared",
            "compatibility_namespace": "coding",
            "mode": mode,
            "write_scope": "[]",
            "parallel_safe": "false",
            "direct_lane_work_allowed": "true",
            "mandatory_review": "false",
            "review_model": "none",
            "reviews": "none",
            "return_artifact": "_state/result.md",
        }
        if run_id is not None:
            fields["run_id"] = run_id
        if result_type is not None:
            fields["result_type"] = result_type
        if reserved is not None:
            fields[reserved[0]] = reserved[1]
        packet = root / f"source-{task_id}.md"
        packet.write_text(envelope(fields, "Execute fixture."), encoding="utf-8")
        return packet

    def _dispatch(
        self, root: Path, packet: Path, *, dry_run: bool = False
    ) -> subprocess.CompletedProcess[str]:
        args = [str(SEND_TASK), str(packet)]
        if dry_run:
            args.append("--dry-run")
        # `root` is a plain tempdir, not a git checkout, so send-task.sh cannot
        # derive a branch and now refuses to guess one; supply it explicitly.
        env = {
            **os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1",
            "SQUAD_BASE_BRANCH": "v2",
        }
        env.pop("SQUAD_DISPATCH_MODE", None)
        return subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dispatch_rejects_author_owned_verification_contract_fields(self) -> None:
        values = {
            "author_family": "claude",
            "verification_contract": "{}",
            "verification_contract_sha256": "0" * 64,
        }
        for index, (field, value) in enumerate(values.items()):
            with self.subTest(field=field):
                root = self._root()
                task_id = f"TASK-2026-07-17-98{index:02d}-reserved-{index}"
                result = self._dispatch(
                    root,
                    self._packet(root, task_id=task_id, reserved=(field, value)),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("controller-owned field", result.stderr)
                self.assertFalse((root / "departments/coding/inbox" / f"{task_id}.md").exists())

    def test_result_type_and_run_id_admission(self) -> None:
        cases = (
            ("project normal", "project", "PRJ-NORMAL", None, True),
            ("bounty dry", "bounty", "BTY-DRY", "dry_run", True),
            ("missing run", "project", None, None, False),
            ("project dry", "project", "PRJ-DRY", "dry_run", False),
            ("invalid result", "bounty", "BTY-BAD", "partial", False),
        )
        for index, (label, mode, run_id, result_type, succeeds) in enumerate(cases):
            with self.subTest(label=label):
                root = self._root()
                task_id = f"TASK-2026-07-17-97{index:02d}-result-{index}"
                result = self._dispatch(
                    root,
                    self._packet(
                        root,
                        task_id=task_id,
                        mode=mode,
                        run_id=run_id,
                        result_type=result_type,
                    ),
                )
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                delivered = root / "departments/coding/inbox" / f"{task_id}.md"
                self.assertEqual(delivered.exists(), succeeds)

    def test_typed_dry_run_prints_contract_without_writes(self) -> None:
        root = self._root()
        task_id = "TASK-2026-07-17-9699-contract-dry-run"
        result = self._dispatch(
            root,
            self._packet(root, task_id=task_id),
            dry_run=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertRegex(result.stdout, r"verification-contract/v1.*[0-9a-f]{64}")
        self.assertFalse((root / "_state/active-tasks.json").exists())
        self.assertFalse(
            (root / "departments/coding/inbox" / f"{task_id}.md").exists()
        )

    def test_unrelated_mode_remains_dispatchable_without_v1_contract(self) -> None:
        root = self._root()
        task_id = "TASK-2026-07-17-9698-content-untyped"
        result = self._dispatch(
            root,
            self._packet(root, task_id=task_id, mode="content", run_id=None),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        delivered = (root / "departments/coding/inbox" / f"{task_id}.md").read_text()
        self.assertNotIn("verification_contract:", delivered)
        registry = json.loads((root / "_state/active-tasks.json").read_text())
        self.assertNotIn("verification_contract", registry[task_id])

    def test_same_task_registration_contract_hash_is_identity(self) -> None:
        root = self._root()
        # `root` is a plain tempdir, not a git checkout, so send-task.sh cannot
        # derive a branch and now refuses to guess one; supply it explicitly.
        env = {
            **os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1",
            "SQUAD_BASE_BRANCH": "v2",
        }
        task_id = "TASK-2026-07-17-9697-contract-identity"
        entry = {
            "compatibility_namespace": "coding",
            "specialist": "none",
            "to_model": "gpt-codex",
            "source_namespace": "shared",
            "return_artifact": "_state/result.md",
            "write_scope": [],
            "capability_card_sha256": None,
            "verification_contract_sha256": "1" * 64,
        }

        def register(value: dict[str, object]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(RECONCILER),
                    "--register-task",
                    task_id,
                    "--entry-json",
                    json.dumps(value),
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        first = register(entry)
        identical = register(entry)
        changed = register({**entry, "verification_contract_sha256": "2" * 64})
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(identical.returncode, 0, identical.stderr)
        self.assertNotEqual(changed.returncode, 0)
        registry = json.loads((root / "_state/active-tasks.json").read_text())
        self.assertEqual(registry[task_id]["verification_contract_sha256"], "1" * 64)


class CapabilityReconciliationTests(ManagedSupervisorTestCase):
    #: The launch authority mints this at registry insertion and never puts it
    #: in the packet, so no worker and no replayed file can author it.
    ATTEMPT_ID = "d-" + "9" * 32

    def _fixture(
        self,
        echoed_hash: str | None,
        *,
        mutate_card: bool = False,
        mandatory_review: bool = False,
        initial_status: str = "in-flight",
        authority_fence: bool = True,
    ) -> tuple[Path, Path, dict[str, str], str, str]:
        root = self._managed_root("capability-reconcile-")
        original = b"dispatched card bytes\n"
        pinned = hashlib.sha256(original).hexdigest()
        card = root / "shared/capabilities/project/web-app.md"
        card.parent.mkdir(parents=True)
        card.write_bytes(b"changed card bytes\n" if mutate_card else original)
        task_id = "TASK-2026-07-17-9997-capability-reconcile"
        entry = {
            "compatibility_namespace": "coding",
            "specialist": "test-engineer",
            "to_model": "claude",
            "source_namespace": "coding",
            "review_model": "gpt-codex" if mandatory_review else "none",
            "mandatory_review": "true" if mandatory_review else "false",
            "status": initial_status,
            "capability_id": "project/web-app",
            "capability_card_path": "shared/capabilities/project/web-app.md",
            "capability_card_sha256": pinned,
            "capability_derived_state": "live",
            "capability_gates": ["public_release"],
        }
        if authority_fence:
            entry["delivery_attempt_id"] = self.ATTEMPT_ID
            entry["delivery_generation"] = 1
        if mandatory_review:
            # `--settle-review` refuses an entry with no explicit review_class,
            # so a fixture that exercises that path must carry one.
            entry["review_class"] = "standard"
        state = root / "_state"
        state.mkdir()
        registry: dict[str, dict[str, object]] = {task_id: entry}
        if mandatory_review:
            # `_standard_review_provenance` reads the reviewer lane and the
            # reviewed target from the REVIEW task's own registry entry, never
            # from the review response, so the fixture must register it.
            registry[REVIEW_TASK_ID] = {
                "compatibility_namespace": "coding",
                "to_model": "gpt-codex",
                "reviews": task_id,
                "status": "complete",
                "review_class": "standard",
            }
        (state / "active-tasks.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        response_fields = {
            "id": f"{task_id}-response",
            "in_response_to": task_id,
            "from": "claude",
            "to": "chrono",
            "type": "RESULT",
            "status": "needs_review" if mandatory_review else "complete",
        }
        if authority_fence:
            response_fields["delivery_attempt_id"] = self.ATTEMPT_ID
            response_fields["delivery_generation"] = "1"
        if echoed_hash is not None:
            response_fields["capability_card_sha256"] = (
                pinned if echoed_hash == "PINNED" else echoed_hash
            )
        response = root / f"departments/coding/outbox/{task_id}-response.md"
        response.parent.mkdir(parents=True)
        response.write_text(envelope(response_fields), encoding="utf-8")
        env = {
            **os.environ,
            "VAULT_ROOT": str(root),
            "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux",
            "SQUAD_SESSION": "none",
            "PYTHONDONTWRITEBYTECODE": "1",
            # `root` is a plain tempdir, not a git checkout; see the other
            # three env dicts in this file for why this is required now.
            "SQUAD_BASE_BRANCH": "v2",
        }
        return root, state, env, task_id, pinned

    def _reconcile(self, env: dict[str, str], task_id: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RECONCILER), "--task-id", task_id],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_matching_echo_settles_against_dispatched_snapshot(self) -> None:
        _root, state, env, task_id, pinned = self._fixture("PINNED")

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["response_capability_card_sha256"], pinned)
        self.assertFalse(entry["capability_card_drift"])

    def test_wrong_echo_stays_open(self) -> None:
        """A MISMATCHED pin is evidence the response ran under another snapshot.

        Settlement question 1 -- "is this the current admitted attempt?" --
        owns this. The response asserts a card the registry never dispatched,
        so it is not the admitted attempt and must not settle. This is the
        surviving half of the former ``test_missing_or_wrong_echo_stays_open``.
        """
        _root, state, env, task_id, _pinned = self._fixture("0" * 64)

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "in-flight")
        self.assertIn("mismatch", entry["capability_response_issue"])
        self.assertIn("capability-contract-hold", result.stdout)

    def test_missing_echo_settles_and_records_absence(self) -> None:
        """An ABSENT pin echo the AUTHORITY wrote is telemetry, not a question.

        This replaces the ``missing`` half of the former
        ``test_missing_or_wrong_echo_stays_open``. The fixture carries the
        launch authority's attempt fence, which is what makes the absence
        attributable: the echo row is written by the authority, never by the
        worker (``dispatch_context_builder.packet_reconciliation_echo`` reads
        it from the packet, and a worker-authored value is discarded), so an
        absent row here is a defect in our own promotion path that no finished
        worker can go back and clear. It fails every clause of the
        block-a-boundary rule in ``shared/protocol.md``, and the registry's own
        ``capability_card_sha256`` -- not the echo -- is what settlement
        already treats as authoritative for which card was dispatched.

        That reasoning holds only where the authority is provable, which is why
        the fence is in the fixture rather than assumed: see
        ``test_missing_echo_blocks_when_no_authority_fence_proves_the_row``,
        which pins the other half. Coverage is not dropped either way --
        ``test_wrong_echo_stays_open`` keeps the mismatch hold, and the absence
        is asserted to be recorded and announced rather than silently ignored.
        """
        _root, state, env, task_id, pinned = self._fixture(None)

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("capability_response_issue", entry)
        self.assertIn("capability_card_sha256", entry["capability_echo_absence"])
        self.assertIn("capability-echo-absent", result.stdout)
        # The registry pin, not the missing echo, remains authoritative.
        self.assertEqual(entry["response_capability_card_sha256"], pinned)

    def test_missing_echo_blocks_when_no_authority_fence_proves_the_row(self) -> None:
        """The absence waiver is scoped to the rail that earns it.

        `shared/protocol.md` promises that a worker cannot author the echo, but
        it promises it "on the board rail" only, and the V1 compatibility rail
        does not carry that promise. There, `landed_response` validates nothing
        on the response -- not `id`, not `in_response_to`, not `type`, not the
        attempt fence, and it does not reject duplicate frontmatter keys -- and
        `worker_response_issue` returns early for any entry with no
        `delivery_worker_id`, which is every entry in the live registry. So on
        that rail the pin echo was the ONLY thing binding a landed response to
        the dispatched attempt, and waiving its absence waives all of it.

        What is provable either way is the attempt fence: the launch authority
        mints `delivery_attempt_id` at registry insertion and never puts it in
        the packet, so a response that echoes it back exactly was written by
        the authority. Absence is an advisory when that proof is present -- the
        board rail always carries it, and so does the authority's own blocked
        completion -- and blocks when it is not.
        """
        _root, state, env, task_id, _pinned = self._fixture(None, authority_fence=False)

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "in-flight")
        self.assertIn("capability_card_sha256", entry["capability_response_issue"])
        self.assertNotIn("capability_echo_absence", entry)
        self.assertIn("capability-contract-hold", result.stdout)
        self.assertNotIn("response_capability_card_sha256", entry)

    def test_duplicate_echo_keys_cannot_manufacture_authority_proof(self) -> None:
        """Last-value-wins parsing must not be a way to fake the fence.

        `strip_frontmatter` keeps the LAST value for a repeated key unless the
        caller asks it to reject duplicates, and the V1 rail's response
        selection does not ask. A response carrying the fence twice is
        therefore not a response the authority rendered, and it must not buy
        the absence waiver.
        """
        root, state, env, task_id, _pinned = self._fixture(None)
        response = root / f"departments/coding/outbox/{task_id}-response.md"
        text = response.read_text(encoding="utf-8")
        self.assertIn(f"delivery_attempt_id: {self.ATTEMPT_ID}\n", text)
        response.write_text(
            text.replace(
                f"delivery_attempt_id: {self.ATTEMPT_ID}\n",
                f"delivery_attempt_id: d-{'0' * 32}\ndelivery_attempt_id: {self.ATTEMPT_ID}\n",
                1,
            ),
            encoding="utf-8",
        )

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "in-flight")
        self.assertIn("capability_card_sha256", entry["capability_response_issue"])

    def test_current_card_drift_is_surfaced_but_pin_still_settles(self) -> None:
        _root, state, env, task_id, pinned = self._fixture(
            "PINNED", mutate_card=True
        )

        result = self._reconcile(env, task_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["capability_card_sha256"], pinned)
        self.assertTrue(entry["capability_card_drift"])
        self.assertNotEqual(entry["capability_card_current_sha256"], pinned)
        self.assertIn("capability-card-drift", result.stdout)

    def test_explicit_review_settlement_cannot_bypass_mismatched_echo(self) -> None:
        """Renamed and re-aimed from ``..._cannot_bypass_bad_echo``.

        The security property under test is unchanged: an explicit
        ``--settle-review`` must not settle a response that ran under a
        different capability snapshot. Only the fixture moves, from an absent
        echo to a mismatched one, because absence is no longer a settlement
        question anywhere -- see
        ``test_missing_echo_settles_and_records_absence``.
        """
        root, _state, env, task_id, _pinned = self._fixture(
            "0" * 64, mandatory_review=True, initial_status="review-required"
        )
        review = root / f"departments/coding/outbox/{REVIEW_TASK_ID}-response.md"
        review.write_text(
            envelope(
                {
                    "id": f"{REVIEW_TASK_ID}-response",
                    "in_response_to": task_id,
                    "from": "gpt-codex",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "complete",
                },
                "APPROVE",
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(RECONCILER),
                "--settle-review",
                task_id,
                "--review-ref",
                str(review),
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match dispatched capability snapshot", result.stderr)

    def test_explicit_review_settlement_is_not_deadlocked_by_an_absent_echo(self) -> None:
        """An authority-caused absence must not wedge the manual path.

        `--settle-review` is the escape hatch Chrono uses when a held task
        needs an operator-read review to close. If an absent echo blocked here
        too, the deadlock would have no exit at all -- the worker is finished
        and cannot re-emit the row, and the manual override would refuse for
        the same reason. The mismatch case above still refuses, and so does an
        absence with no authority fence behind it
        (``test_explicit_review_settlement_refuses_an_unproven_absent_echo``).
        """
        root, state, env, task_id, _pinned = self._fixture(
            None, mandatory_review=True, initial_status="review-required"
        )
        review = root / f"departments/coding/outbox/{REVIEW_TASK_ID}-response.md"
        review.write_text(
            envelope(
                {
                    "id": f"{REVIEW_TASK_ID}-response",
                    "in_response_to": task_id,
                    "from": "gpt-codex",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "complete",
                    # `review_verdict` reads the structured frontmatter field;
                    # body prose is never a verdict.
                    "verdict": "APPROVE",
                },
                "APPROVE",
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(RECONCILER),
                "--settle-review",
                task_id,
                "--review-ref",
                str(review),
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "complete")
        self.assertIn("capability_card_sha256", entry["capability_echo_absence"])


    def test_explicit_review_settlement_refuses_an_unproven_absent_echo(self) -> None:
        """`--settle-review` shares `capability_pin_echo`, so it shares the rule.

        The companion test above it keeps the manual path un-deadlocked for an
        absence the authority itself caused. This one holds the other edge: an
        absent echo on a response nothing proves the authority wrote is not a
        deadlock to escape, it is an unidentified response, and the manual
        override must not launder it into a settlement.
        """
        root, state, env, task_id, _pinned = self._fixture(
            None,
            mandatory_review=True,
            initial_status="review-required",
            authority_fence=False,
        )
        review = root / f"departments/coding/outbox/{REVIEW_TASK_ID}-response.md"
        review.write_text(
            envelope(
                {
                    "id": f"{REVIEW_TASK_ID}-response",
                    "in_response_to": task_id,
                    "from": "gpt-codex",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "complete",
                    "verdict": "APPROVE",
                },
                "APPROVE",
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(RECONCILER),
                "--settle-review",
                task_id,
                "--review-ref",
                str(review),
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match dispatched capability snapshot", result.stderr)
        entry = json.loads((state / "active-tasks.json").read_text())[task_id]
        self.assertEqual(entry["status"], "review-required")


class RegistryReconcilerContractTests(unittest.TestCase):
    """General registration/reconciliation contracts, folded from a stale swarm module."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / "_state" / "active-tasks.json"
        self.patches = [
            patch.dict(os.environ, {rr.TEST_ISOLATION_ENV: "1"}),
            patch.object(rr, "VAULT_ROOT", self.root),
            patch.object(rr, "STATE_DIR", self.root / "_state"),
            patch.object(rr, "REGISTRY_PATH", self.registry),
            patch.object(
                rr,
                "CHRONO_QUEUE_PATH",
                self.root / "_state" / "chrono-queue.md",
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_isolation_signal_prevents_live_tmux_notification(self) -> None:
        with patch.object(rr.subprocess, "run") as run:
            self.assertFalse(rr.nudge_chrono("fixture notification"))
        run.assert_not_called()

    def test_missing_review_class_is_refused_not_defaulted_to_standard(self) -> None:
        entry = {
            "compatibility_namespace": "coding",
            "specialist": "backend-engineer",
            "to_model": "claude",
            "mandatory_review": "true",
            "review_model": "gpt-codex",
            "status": "in-flight",
        }
        with self.assertRaisesRegex(ValueError, "missing an explicit review_class"):
            rr.register_task("TASK-NO-CLASS", dict(entry))
        for invalid in ("", "   ", None, "standrad", "security_finding", "SECURITY"):
            with self.subTest(review_class=invalid):
                with self.assertRaises(ValueError):
                    rr.register_task(
                        "TASK-BAD-CLASS", {**entry, "review_class": invalid}
                    )

    def test_equivalent_review_class_retry_is_idempotent_not_conflicting(self) -> None:
        entry = {
            "compatibility_namespace": "coding",
            "specialist": "backend-engineer",
            "to_model": "claude",
            "mandatory_review": "true",
            "review_model": "gpt-codex",
            "review_class": " FACTUAL ",
            "status": "in-flight",
        }
        self.assertTrue(rr.register_task("TASK-RETRY-CLASS", dict(entry)))
        stored = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(stored["TASK-RETRY-CLASS"]["review_class"], "factual")
        self.assertFalse(
            rr.register_task("TASK-RETRY-CLASS", {**entry, "review_class": "factual"})
        )

    def test_unreadable_review_class_holds_review_instead_of_settling(self) -> None:
        entry = {
            "specialist": "code-reviewer",
            "to_model": "claude",
            "review_model": "gpt-codex",
            "mandatory_review": "true",
            "write_scope": [],
        }
        self.assertFalse(
            rr.cross_family_review_pending({**entry, "review_class": "standard"})[0]
        )
        self.assertTrue(rr.cross_family_review_pending(dict(entry))[0])
        self.assertTrue(
            rr.cross_family_review_pending({**entry, "review_class": "bogus"})[0]
        )
        with self.assertRaisesRegex(ValueError, "review_class"):
            rr._review_class(entry)

    def test_close_task_is_audited_and_idempotent(self) -> None:
        task_id = "TASK-STALE"
        reason = "superseded by TASK-SETTLED"
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(
            json.dumps(
                {
                    task_id: {
                        "compatibility_namespace": "coding",
                        "status": "needs_review",
                    }
                }
            ),
            encoding="utf-8",
        )

        self.assertTrue(rr.close_task(task_id, reason))
        self.assertFalse(rr.close_task(task_id, reason))
        entry = json.loads(self.registry.read_text(encoding="utf-8"))[task_id]
        self.assertEqual(entry["status"], "superseded")
        self.assertEqual(entry["closure_reason"], reason)
        self.assertEqual(entry["closed_from_status"], "needs_review")
        self.assertEqual(entry["lifecycle_closed_by"], "chrono-explicit")
        self.assertTrue(entry["lifecycle_closed_at"])
        self.assertEqual(len(entry["closure_history"]), 1)
        self.assertEqual(entry["closure_history"][0]["reason"], reason)
        with self.assertRaisesRegex(ValueError, "already terminal"):
            rr.close_task(task_id, "different reason")


class WorkerFenceLeaseTests(unittest.TestCase):
    """The lease clause of the worker fence, which no response can satisfy.

    ``bin/send-task.sh`` initialises ``delivery_worker_id`` and
    ``lease_expires_at`` to ``None`` and the reconciler ``setdefault``s both.
    Only the scheduler writes a lease, and ``lease_expires_at`` is not among
    ``dispatch_context_builder.RECONCILIATION_ECHO_KEYS``, so no promoted
    envelope can ever carry one. A finished response can therefore neither
    cause nor clear its absence, which is the third clause of the
    block-a-boundary rule in ``shared/protocol.md``.
    """

    TASK_ID = "TASK-2026-08-31-0001-worker-lease"
    ATTEMPT_ID = "d-" + "a" * 32

    def _response(self, **extra: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="worker-fence-lease-"))
        self.addCleanup(shutil.rmtree, root, True)
        fields = {
            "id": f"{self.TASK_ID}-response",
            "in_response_to": self.TASK_ID,
            "from": "claude",
            "to": "chrono",
            "type": "RESULT",
            "status": "complete",
            "delivery_attempt_id": self.ATTEMPT_ID,
            "delivery_worker_id": "claude-r01",
            "worker_epoch": "epoch-2",
            "delivery_lane": "claude",
            "delivery_generation": "3",
            "lease_generation": "2",
        }
        fields.update(extra)
        path = root / f"{self.TASK_ID}-response.md"
        path.write_text(envelope(fields), encoding="utf-8")
        return path

    def _entry(self, **extra: object) -> dict[str, object]:
        entry: dict[str, object] = {
            "delivery_worker_id": "claude-r01",
            "worker_assignment_state": "in-progress",
            "delivery_attempt_id": self.ATTEMPT_ID,
            "worker_epoch": "epoch-2",
            "delivery_generation": 3,
            "lease_generation": 2,
            "delivery_lane": "claude",
        }
        entry.update(extra)
        return entry

    def test_absent_lease_does_not_block_a_matching_fence(self) -> None:
        entry = self._entry()
        self.assertIsNone(entry.get("lease_expires_at"))
        self.assertEqual(
            rr.worker_response_issue(self.TASK_ID, entry, self._response()), ""
        )

    def test_absent_lease_is_reported_as_a_registry_defect(self) -> None:
        """Absence must warn, not vanish: it is our bug, not the worker's."""
        self.assertIn("lease_expires_at", rr.worker_lease_absence(self._entry()))
        self.assertEqual(
            rr.worker_lease_absence(
                self._entry(lease_expires_at="2099-01-01T00:00:00+00:00")
            ),
            "",
        )
        # An unassigned task has no lease to be missing.
        self.assertEqual(rr.worker_lease_absence({}), "")

    def test_absent_lease_does_not_weaken_the_rest_of_the_fence(self) -> None:
        for label, override, expected in (
            ("epoch", {"worker_epoch": "epoch-9"}, "worker_epoch mismatch"),
            ("attempt", {"delivery_attempt_id": "d-" + "b" * 32},
             "delivery_attempt_id mismatch"),
            ("generation", {"delivery_generation": "2"},
             "delivery_generation mismatch"),
            ("target", {"in_response_to": "TASK-2026-08-31-0002-other"},
             "in_response_to mismatch"),
        ):
            with self.subTest(label=label):
                self.assertIn(
                    expected,
                    rr.worker_response_issue(
                        self.TASK_ID, self._entry(), self._response(**override)
                    ),
                )

    def test_expired_lease_still_holds(self) -> None:
        """Do not weaken the case the lease actually owns."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(
            rr.worker_response_issue(
                self.TASK_ID, self._entry(lease_expires_at=past), self._response()
            ),
            "response landed after worker lease expiry",
        )

    def test_live_lease_settles(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.assertEqual(
            rr.worker_response_issue(
                self.TASK_ID, self._entry(lease_expires_at=future), self._response()
            ),
            "",
        )

    def test_terminal_assignment_still_holds_without_a_lease(self) -> None:
        for state in ("expired", "silent"):
            with self.subTest(state=state):
                self.assertIn(
                    "terminal",
                    rr.worker_response_issue(
                        self.TASK_ID,
                        self._entry(worker_assignment_state=state),
                        self._response(),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
