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


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = REPO_ROOT / "bin/send-task.sh"
INSPECTOR = REPO_ROOT / "scripts/python/capability_dispatch.py"
RECONCILER = REPO_ROOT / "scripts/python/registry_reconciler.py"
VERIFICATION_HELPER = REPO_ROOT / "scripts/python/verification_contract.py"

if str(VERIFICATION_HELPER.parent) not in sys.path:
    sys.path.insert(0, str(VERIFICATION_HELPER.parent))

from verification_contract import verification_contract_sha256  # noqa: E402


def envelope(frontmatter: dict[str, str], body: str = "done") -> str:
    fields = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    return f"---\n{fields}\n---\n\n{body}\n"


class CapabilityDispatchSnapshotTests(unittest.TestCase):
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
        root = Path(tempfile.mkdtemp(prefix="capability-inspector-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
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
        root = Path(tempfile.mkdtemp(prefix="capability-dispatch-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
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
        wrapper = root / "bin/registry-reconciler.sh"
        wrapper.parent.mkdir(parents=True)
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
                    "return_artifact": "_state/result.md",
                },
                "Build the application.",
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}

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


class VerificationContractDispatchTests(unittest.TestCase):
    def _root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="verification-contract-dispatch-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for relative in (
            "shared/registries/skill-tool-registry.tsv",
            "shared/specialist-runtime-map.tsv",
            "scripts/python/verification_contract.py",
        ):
            source = REPO_ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
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
        return subprocess.run(
            args,
            cwd=REPO_ROOT,
            env={**os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
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
                self.assertIn("dispatcher-owned field", result.stderr)
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
        env = {**os.environ, "VAULT_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
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


class CapabilityReconciliationTests(unittest.TestCase):
    def _fixture(
        self,
        echoed_hash: str | None,
        *,
        mutate_card: bool = False,
        mandatory_review: bool = False,
        initial_status: str = "in-flight",
    ) -> tuple[Path, Path, dict[str, str], str, str]:
        root = Path(tempfile.mkdtemp(prefix="capability-reconcile-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
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
        state = root / "_state"
        state.mkdir()
        (state / "active-tasks.json").write_text(
            json.dumps({task_id: entry}), encoding="utf-8"
        )
        response_fields = {
            "id": f"{task_id}-response",
            "in_response_to": task_id,
            "from": "claude",
            "to": "chrono",
            "type": "RESULT",
            "status": "needs_review" if mandatory_review else "complete",
        }
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

    def test_missing_or_wrong_echo_stays_open(self) -> None:
        for label, echo in (("missing", None), ("wrong", "0" * 64)):
            with self.subTest(label=label):
                _root, state, env, task_id, _pinned = self._fixture(echo)
                result = self._reconcile(env, task_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                entry = json.loads((state / "active-tasks.json").read_text())[task_id]
                self.assertEqual(entry["status"], "in-flight")
                self.assertIn("capability_card_sha256", entry["capability_response_issue"])
                self.assertIn("capability-contract-hold", result.stdout)

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

    def test_explicit_review_settlement_cannot_bypass_bad_echo(self) -> None:
        root, _state, env, task_id, _pinned = self._fixture(
            None, mandatory_review=True, initial_status="review-required"
        )
        review = root / "departments/coding/outbox/TASK-REVIEW-9997-response.md"
        review.write_text(
            envelope(
                {
                    "id": "TASK-REVIEW-9997-response",
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


if __name__ == "__main__":
    unittest.main()
