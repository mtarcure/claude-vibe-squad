#!/usr/bin/env python3
"""V2 trusted-launch-path — bin/board-supervisor.sh trusted-launch subcommand.

Tests the real script end-to-end via subprocess (not a reimplementation of
its logic), using /usr/bin/true as the "fresh CLI" stand-in for a real
launch under the exact Stage-1 Seatbelt boundary — the same established
pattern already used by test_runtime_envelope.py in this exact codebase.
Composition correctness (role adopted, own worktree,
parallel-safe via the real scheduler, lineage established, normal env) is
verified against the REAL settled 2.1/2.2/2.3/2.4 modules the script itself
imports, not a parallel reimplementation of them.
"""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import os
import re
import signal
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from held_action_gate import HELD_CATEGORIES  # noqa: E402

SCRIPT = ROOT / "bin" / "board-supervisor.sh"


def _fixture_base_branch(repo_root: Path = ROOT) -> str:
    """Choose a branch name for disposable test repos, including detached CI."""

    branch = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo_root),
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    resolved = branch.stdout.strip()
    if branch.returncode == 0 and resolved:
        return resolved
    if branch.returncode == 1 and not resolved:
        return os.environ.get("SQUAD_BASE_BRANCH") or "v2"
    raise RuntimeError(
        "cannot determine fixture base branch: "
        f"rc={branch.returncode} stderr={branch.stderr.strip()!r}"
    )


BASE_BRANCH = _fixture_base_branch()


def _head_is_detached(repo_root: Path = ROOT) -> bool:
    """True when HEAD names no branch.

    `trusted-launch` request validation refuses a checkout whose branch is not
    the base branch, and a detached HEAD is on no branch at all -- so a run in
    that shape blocks at `request_validation` and never reaches the worker CLI.
    That is correct behaviour, not a defect, but it means an end-to-end test of
    a CLI-nonzero block cannot reach its subject here.
    """

    probe = subprocess.run(
        ["/usr/bin/git", "-C", str(repo_root), "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    return probe.returncode != 0 or not probe.stdout.strip()


HEAD_IS_DETACHED = _head_is_detached()
SETTLED_T1P1_BUNDLE_SHA256 = (
    "95438e2cc6b06ab3f12622ad0a0f3e0a6654e6cf3a7b35f3908b3487f883f376"
)

import dispatch_context_builder as dcb  # noqa: E402
import board_process_truth as process_truth  # noqa: E402
import registry_reconciler as reconciler  # noqa: E402
import seatbelt_profile  # noqa: E402
from scripts.python.tests.ci_host_independence import (  # noqa: E402
    skip_in_host_independent_ci,
)


def _git(args: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {args} failed: {completed.stderr}")


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", BASE_BRANCH], cwd=repo)
    _git(["config", "user.email", "t@example.com"], cwd=repo)
    _git(["config", "user.name", "T"], cwd=repo)
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    return repo


def _write_role_files(root: Path) -> tuple[Path, Path]:
    role = root / "role.md"
    overlay = root / "overlay.md"
    role.write_text("# Systems Engineer\n\nBuild carefully.\n", encoding="utf-8")
    overlay.write_text("# Claude overlay\n\nUse the native lane.\n", encoding="utf-8")
    return role, overlay


def _run_trusted_launch(
    payload: dict[str, object],
    *,
    timeout: float = 40,
    trusted_host_path: str | None = None,
) -> dict[str, object]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        context_path = Path(handle.name)
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LC_ALL": "C",
        "VAULT_ROOT": str(ROOT),
        "TRUSTED_LAUNCH_TEST_MODE": "1",
        "SQUAD_BASE_BRANCH": BASE_BRANCH,
    }
    if trusted_host_path is not None:
        environment["TRUSTED_HOST_PATH"] = trusted_host_path
    try:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    finally:
        context_path.unlink(missing_ok=True)
    try:
        return json.loads(completed.stdout.strip() or completed.stderr.strip())
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"non-JSON output: rc={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from exc


# Issued-token shapes for the credentials this rail actually handles -- the
# managed set in `bin/board-supervisor.sh` (`SOLODIT_API_KEY`, `XAI_API_KEY`,
# `PERPLEXITY_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`) is issued under exactly
# these prefixes. Matched against receipt VALUES only, and deliberately unable
# to match a 64-character sha256 digest, of which the receipt carries many.
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?:sk|xai|pplx)-[A-Za-z0-9._-]{16,}"),
)

# Second prong: any secret this host actually holds, discovered by name shape
# rather than restated from the supervisor's managed list, so a new managed
# credential is covered here without this file having to learn about it.
_SECRET_ENV_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS")


def _string_values(value: object, path: str = "$"):
    """Yield `(json_path, text)` for every string VALUE, never for a key.

    Keys and values live in one flat namespace once a receipt is passed through
    `json.dumps`, which is what made the substring assertion this replaced
    unable to tell the audit field `credential_missing` from a leaked token.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _string_values(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _string_values(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _credential_leaks(receipt: object) -> list[tuple[str, str]]:
    """Every credential VALUE reachable in `receipt`, as `(path, why)` pairs.

    A credential NAME is not a leak: `credential_missing` exists to record which
    managed secrets the store failed to supply, so its values are names by
    design. Only an issued-token shape, or the literal value of a secret this
    host holds, counts.
    """
    live_secrets = {
        name: raw.strip()
        for name, raw in os.environ.items()
        if name.endswith(_SECRET_ENV_SUFFIXES)
        and len(raw.strip()) >= 12
        and not raw.strip().startswith("/")
    }
    leaks: list[tuple[str, str]] = []
    for path, text in _string_values(receipt):
        for pattern in _CREDENTIAL_VALUE_PATTERNS:
            found = pattern.search(text)
            if found:
                leaks.append((path, f"issued-token shape {found.group(0)[:6]}..."))
        for name, secret in live_secrets.items():
            if secret in text:
                leaks.append((path, f"live value of ${name}"))
    return leaks


class TrustedLaunchTests(unittest.TestCase):
    def _fixture_payload(
        self, root: Path, *, task_id: str, attempt_id: str
    ) -> dict[str, object]:
        repo = _init_repo(root)
        role, overlay = _write_role_files(root)
        executable = Path("/usr/bin/true")
        now = int(time.time())

        def digest(value: bytes) -> str:
            return hashlib.sha256(value).hexdigest()

        authority = {
            "schema": "go-live-authority/v1",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": 1,
            "run_id": "PROJ-SWARM-READY-2026-07-19",
            "author_family": "openai",
            "workload_class": "light-text",
            "specialist": "systems-engineer",
            "lane": "claude",
            "mode_profile": "project",
            "execution_kind": "offline-probe",
            "repo_root": str(repo),
            "pool_root": str(root / "pool"),
            "canonical_role_path": str(role),
            "canonical_role_sha256": digest(role.read_bytes()),
            "lane_overlay_path": str(overlay),
            "lane_overlay_sha256": digest(overlay.read_bytes()),
            "executable": str(executable),
            "executable_sha256": digest(executable.read_bytes()),
            "lane_args": [],
            "write_paths": [f"out/{task_id}.txt"],
            "read_scope": ["README.md"],
            "depends_on": [],
            "resources": [],
            "scheduler_concurrency": 2,
            "scheduler_capacities": {},
            "scheduler_settled": {},
            "network_scope": [],
            "action_scope": ["repo-read", "worktree-write"],
            "budgets": {"timeout_seconds": 30},
            "expected_result_path": f"out/{task_id}.txt",
            "expected_outbox_path": f"out/{task_id}-response.md",
            "evidence_outputs": [],
            "reconciliation_echo": {},
            "required_phase_ids": ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"],
            "verification_kinds": ["project_tests", "recipient_contract"],
            # Derived, never restated: the supervisor refuses any packet whose
            # operator_gates differ from HELD_CATEGORIES by even one value, so a
            # literal copy here turns every future gate change into a fixture
            # failure that looks like a policy failure. Restating it is what made
            # the 2026-08-08 vocabulary rename look like 21 broken tests.
            "operator_gates": sorted(HELD_CATEGORIES),
            "packet_sha256": digest(f"{task_id}:packet".encode()),
            "plan_sha256": digest(f"{task_id}:plan".encode()),
            "verification_contract_sha256": digest(f"{task_id}:contract".encode()),
            "selected_model_sha256": digest(b"offline-probe"),
            "profile_bundle_sha256": SETTLED_T1P1_BUNDLE_SHA256,
            "auth_class": "subscription",
            "lane_policy_row_sha256": "a" * 64,
            "capability_surface_sha256": digest(b"capability-surface"),
            "memory_context": {
                "schema": "chrono-vault-context/v1",
                "task_id": task_id,
                "attempt_id": attempt_id,
                "generation": 1,
                "mode": "project",
                "aperture": "none",
                "focus": None,
                "engagement_start": datetime.fromtimestamp(
                    now, tz=timezone.utc
                ).isoformat().replace("+00:00", "Z"),
            },
            "active_board_tasks": [],
            "created_at": now,
            "expires_at": now + 300,
            "nonce": digest(f"{attempt_id}:nonce".encode()),
        }
        return {
            "schema": "go-live-trusted-context/v1",
            "authority": authority,
            "task_prompt": "Run the authenticated inert offline launch probe.",
        }

    def _board_fixture_payload(
        self,
        root: Path,
        *,
        task_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        payload = self._fixture_payload(
            root,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        authority = payload["authority"]
        repo = Path(authority["repo_root"])
        runtime_map = repo / "shared" / "specialist-runtime-map.tsv"
        runtime_map.parent.mkdir(parents=True)
        runtime_map.write_text(
            "specialist\tsource_namespace\tprimary_lane\tprimary_profile\n"
            "systems-engineer\tcoding\tcodex\tcodex.test.high\n",
            encoding="utf-8",
        )
        profiles = repo / "shared" / "registries" / "profiles.tsv"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            "profile_id\tlane\tmodel_id\teffort\tflags\tusage\n"
            "codex.test.high\tcodex\tgpt-test\thigh\tnone\tprimary\n",
            encoding="utf-8",
        )
        lane_capabilities = repo / "model-lanes" / "lane-capabilities.tsv"
        lane_capabilities.parent.mkdir(parents=True)
        source_lines = (ROOT / "model-lanes" / "lane-capabilities.tsv").read_text(
            encoding="utf-8"
        ).splitlines()
        lane_capabilities.write_text(
            "\n".join(
                (
                    source_lines[0],
                    next(
                        line
                        for line in source_lines[1:]
                        if line.split("\t", 1)[0] == "gpt-codex"
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )
        executable = Path(seatbelt_profile.LANE_CLI_PATHS["codex"])
        authority.update(
            {
                "execution_kind": "lane",
                "lane": "codex",
                "executable": str(executable),
                "executable_sha256": hashlib.sha256(
                    Path(os.path.realpath(executable)).read_bytes()
                ).hexdigest(),
                "lane_args": list(
                    dcb.trusted_lane_args_for(
                        repo,
                        lane="codex",
                        specialist="systems-engineer",
                    )
                ),
                "selected_model_sha256": dcb.selected_model_sha256_for(
                    repo,
                    lane="codex",
                    specialist="systems-engineer",
                ),
                **dcb.lane_policy_evidence_for(repo, "codex"),
            }
        )
        return payload

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_board_lane_arguments_are_still_controller_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._board_fixture_payload(
                Path(directory).resolve(),
                task_id="TASK-2026-07-23-9925-board-args",
                attempt_id="d-" + "8" * 32,
            )
            payload["authority"]["lane_args"].append("--untrusted-flag")

            receipt = _run_trusted_launch(payload)

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("closed controller ABI", receipt.get("reason", ""))
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    @skip_in_host_independent_ci("needs the installed Codex lane executable")
    def test_board_selected_model_is_still_controller_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._board_fixture_payload(
                Path(directory).resolve(),
                task_id="TASK-2026-07-23-9935-board-model",
                attempt_id="d-" + "9" * 32,
            )
            payload["authority"]["selected_model_sha256"] = hashlib.sha256(
                b"tampered-model"
            ).hexdigest()

            receipt = _run_trusted_launch(payload)

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("selected model", receipt.get("reason", ""))
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    @skip_in_host_independent_ci(
        "needs the live trusted-launch worktree and supervisor rail"
    )
    def test_a_fresh_launch_adopts_the_role_gets_its_own_worktree_and_a_lineage_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0001-tl-test", attempt_id="d-" + "1" * 32
            )
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertTrue(receipt["role_context_sha256"])
            self.assertTrue(receipt["worktree_root"].startswith(str(root)))
            self.assertTrue(Path(receipt["worktree_root"]).is_dir())
            self.assertTrue(receipt["lineage_sha256"])
            self.assertEqual(receipt["lineage_chain_depth"], 0)

    @skip_in_host_independent_ci(
        "needs the live trusted-launch worktree and supervisor rail"
    )
    def test_the_launch_uses_normal_env_not_broker_custody(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root, task_id="TASK-2026-07-22-0002-tl-test", attempt_id="d-" + "2" * 32
            )
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "launched", receipt)

            # The property: this launch took on no credential custody at all.
            # No broker was required or started, nothing was relayed through
            # one, and the worker ended in a normal trusted-host environment.
            self.assertFalse(receipt["vault_broker_required"], receipt)
            self.assertFalse(receipt["vault_broker_started"], receipt)
            self.assertEqual(receipt["brokered_mcps"], [], receipt)
            self.assertEqual(
                receipt["final_worker_boundary"],
                "trusted-host-normal-env",
                receipt,
            )
            self.assertEqual(
                receipt["authority_mode"],
                "trusted-host-unpinned",
            )
            # ... and no credential VALUE reached the receipt. This replaced
            # `assertNotIn("credential", json.dumps(receipt).lower())`, which
            # searched keys and values as one flat string and so was tripped by
            # the receipt's own audit field `credential_missing` -- a field that
            # carries credential names precisely so a degraded launch stays
            # distinguishable from a healthy one after the fact.
            self.assertEqual(_credential_leaks(receipt), [], receipt)

            # A negative control on the assertion above, run every time: a leak
            # check that cannot go red is not a check. `unhealthy_mcp_status`
            # records verbatim what a failing MCP said, which is the realistic
            # way a token would reach this receipt, so plant one there -- nested,
            # so this also proves the walk recurses -- and require it caught.
            planted = copy.deepcopy(receipt)
            planted["unhealthy_mcp_status"] = {
                "chrono-research-arsenal": "401 rejected key xai-" + "k" * 32
            }
            self.assertTrue(_credential_leaks(planted), planted)

    @skip_in_host_independent_ci(
        "needs live trusted-launch worktrees and board scheduling"
    )
    def test_two_disjoint_launches_get_disjoint_worktrees_and_are_scheduler_parallel_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload_a = self._fixture_payload(
                root,
                task_id="TASK-2026-07-22-0003-tl-alpha",
                attempt_id="d-" + "3" * 32,
            )
            receipt_a = _run_trusted_launch(payload_a)
            self.assertEqual(receipt_a.get("status"), "launched", receipt_a)

            # `dict(...)` is shallow, so the copy this replaced shared ONE
            # `memory_context` object with alpha: rebinding `task_id` /
            # `attempt_id` on the outer authority left the nested context bound
            # to alpha, and `validate_memory_context`
            # (plugins/chrono-vault/clearance.py:207, called at
            # bin/board-supervisor.sh:1373) cross-binds exactly those fields.
            # The product was right to deny it; the cost was that this test died
            # at the authority gate and never reached its own assertion, leaving
            # scheduler parallel-safety unverified. Deep-copy, then rebind every
            # identity-derived field from one pair of names so the two cannot
            # drift apart again.
            beta_task_id = "TASK-2026-07-22-0004-tl-beta"
            beta_attempt_id = "d-" + "4" * 32
            payload_b = copy.deepcopy(payload_a)
            payload_b["authority"]["task_id"] = beta_task_id
            payload_b["authority"]["attempt_id"] = beta_attempt_id
            payload_b["authority"]["memory_context"]["task_id"] = beta_task_id
            payload_b["authority"]["memory_context"]["attempt_id"] = beta_attempt_id
            payload_b["authority"]["nonce"] = hashlib.sha256(
                f"{beta_attempt_id}:nonce".encode()
            ).hexdigest()
            payload_b["authority"]["write_paths"] = [f"out/{beta_task_id}.txt"]
            payload_b["authority"]["expected_result_path"] = f"out/{beta_task_id}.txt"
            payload_b["authority"]["expected_outbox_path"] = (
                f"out/{beta_task_id}-response.md"
            )
            payload_b["authority"]["active_board_tasks"] = [
                {
                    "task_id": receipt_a["task_id"],
                    "write_paths": payload_a["authority"]["write_paths"],
                    "read_paths": payload_a["authority"]["read_scope"],
                    "worktree_root": receipt_a["worktree_root"],
                    "depends_on": [],
                    "resources": [],
                    "metadata_complete": True,
                    "priority": 0,
                }
            ]
            receipt_b = _run_trusted_launch(payload_b)
            self.assertEqual(receipt_b.get("status"), "launched", receipt_b)
            # Both roots must be REAL and disjoint. Inequality of two strings
            # alone would also pass if beta's root were a path that was never
            # created, which is not the property "parallel-safe" claims.
            self.assertTrue(Path(receipt_a["worktree_root"]).is_dir(), receipt_a)
            self.assertTrue(Path(receipt_b["worktree_root"]).is_dir(), receipt_b)
            self.assertNotEqual(receipt_a["worktree_root"], receipt_b["worktree_root"])

    def test_a_colliding_active_task_serializes_rather_than_launching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root,
                task_id="TASK-2026-07-22-0005-tl-collide",
                attempt_id="d-" + "5" * 32,
            )
            # Declare an active task that claims a write path INSIDE where
            # this task's own worktree will land (the pool_root itself),
            # forcing board_router to refuse to parallelize.
            payload["authority"]["active_board_tasks"] = [
                {
                    "task_id": "TASK-2026-07-22-0000-tl-blocker",
                    "write_paths": payload["authority"]["write_paths"],
                    "read_paths": [],
                    "worktree_root": payload["authority"]["repo_root"],
                    "depends_on": [],
                    "resources": [],
                    "metadata_complete": True,
                    "priority": 0,
                }
            ]
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("write-scope collision", json.dumps(receipt).lower())

    @skip_in_host_independent_ci(
        "executes the live trusted-host supervisor launch path"
    )
    def test_trusted_default_runs_the_inert_probe_outside_final_seatbelt(self) -> None:
        # The trusted default consumes the settled Seatbelt canary, then runs
        # its real child on the trusted host. Strict final-Seatbelt execution
        # remains opt-in and is covered by test_golive_integration.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root,
                task_id="TASK-2026-07-22-0006-tl-prodgap",
                attempt_id="d-" + "6" * 32,
            )
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False
            ) as handle:
                json.dump(payload, handle)
                context_path = Path(handle.name)
            try:
                completed = subprocess.run(
                    ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    env={
                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                        "LC_ALL": "C",
                        "VAULT_ROOT": str(ROOT),
                        "SQUAD_BASE_BRANCH": BASE_BRANCH,
                    },
                )
            finally:
                context_path.unlink(missing_ok=True)
            receipt = json.loads(completed.stdout.strip() or completed.stderr.strip())
            self.assertEqual(receipt.get("status"), "launched", receipt)
            self.assertTrue(receipt["cli_exec_succeeded"], receipt)
            self.assertEqual(receipt["returncode"], 0, receipt)
            self.assertEqual(
                receipt["final_worker_boundary"],
                "trusted-host-normal-env",
            )

    def test_missing_context_file_is_denied_not_a_crash(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "trusted-launch", "/nonexistent/path.json"],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LC_ALL": "C",
                "VAULT_ROOT": str(ROOT),
                "TRUSTED_LAUNCH_TEST_MODE": "1",
            },
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout.strip() or completed.stderr.strip())
        self.assertEqual(payload.get("status"), "denied")

    def test_memory_context_is_cross_bound_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root,
                task_id="TASK-2026-07-22-0008-memory-bind",
                attempt_id="d-" + "8" * 32,
            )
            payload["authority"]["memory_context"]["task_id"] = (
                "TASK-2026-07-22-0009-wrong-memory-bind"
            )
            receipt = _run_trusted_launch(payload)
            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn("invalid memory_context", receipt.get("reason", ""))
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    def test_trusted_host_path_with_empty_component_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = self._fixture_payload(
                root,
                task_id="TASK-2026-07-28-0916-path-deny",
                attempt_id="d-" + "7" * 32,
            )

            receipt = _run_trusted_launch(
                payload,
                trusted_host_path="/usr/bin::/bin",
            )

            self.assertEqual(receipt.get("status"), "denied", receipt)
            self.assertIn(
                "only non-empty absolute components",
                receipt.get("reason", ""),
            )
            self.assertFalse(Path(payload["authority"]["pool_root"]).exists())

    def test_the_legacy_prepare_probe_is_absent_from_the_public_surface(self) -> None:
        completed = subprocess.run(
            ["/bin/bash", str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertIn("trusted-launch", completed.stdout)
        self.assertNotIn("board-supervisor.sh prepare", completed.stdout)
        self.assertNotIn("always denies", completed.stdout)

    @skip_in_host_independent_ci("launches the subscription-backed Claude CLI")
    @unittest.skipUnless(
        os.environ.get("RUN_CLAUDE_BYPASS_PROBE") == "1",
        "real subscription-backed Claude bypass probe is opt-in",
    )
    def test_real_claude_bypass_mode_keeps_vault_and_hides_disallowed_mcps(
        self,
    ) -> None:
        executable = Path(seatbelt_profile.LANE_CLI_PATHS["claude"])
        if not executable.is_file():
            self.skipTest("Claude CLI is not installed at the lane entrypoint")
        environment = dict(os.environ)
        for name in (
            "ANTHROPIC_API_KEY",
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_EXECPATH",
            "CLAUDE_CODE_SESSION_ID",
        ):
            environment.pop(name, None)
        prompt = (
            "Real bounded capability proof. Use ToolSearch for 'chrono-vault "
            "recall', then call mcp__plugin_chrono-vault_chrono-vault__recall "
            "once with query 'lane capability scoped proof 0725' and limit 1. "
            "Then use ToolSearch for 'chrono-recon'. Report VAULT_SUCCEEDED only "
            "after a successful tool_result and RECON_UNAVAILABLE only if no "
            "chrono-recon tool is exposed. Finally, use ToolSearch exactly once "
            "for each of these exact queries: 'claude.ai Gmail', 'claude.ai "
            "Google Drive', and 'claude.ai Google Calendar'. Report "
            "GOOGLE_CONNECTORS_UNAVAILABLE only if every one returns no matches. "
            "Do not call a Google connector and do not use any other tool."
        )
        completed = subprocess.run(
            [
                str(executable),
                "-p",
                prompt,
                "--agent",
                "systems-engineer",
                "--model",
                "haiku",
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
                "--dangerously-skip-permissions",
                "--disallowedTools",
                (
                    "Agent,mcp__plugin_chrono-recon_chrono-recon__*,"
                    "mcp__claude_ai_Gmail__*,"
                    "mcp__claude_ai_Google_Drive__*,"
                    "mcp__claude_ai_Google_Calendar__*"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(ROOT / "model-lanes" / "claude"),
            env=environment,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = [
            json.loads(line)
            for line in completed.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        self.assertTrue(
            any(
                event.get("type") == "system"
                and event.get("subtype") == "init"
                and event.get("permissionMode") == "bypassPermissions"
                for event in events
            )
        )
        init_event = next(
            event
            for event in events
            if event.get("type") == "system" and event.get("subtype") == "init"
        )
        init_servers = {
            item.get("name")
            for item in init_event.get("mcp_servers", [])
            if isinstance(item, dict)
        }
        self.assertIn("plugin:chrono-vault:chrono-vault", init_servers)
        self.assertIn("plugin:chrono-recon:chrono-recon", init_servers)
        self.assertIn("claude.ai Gmail", init_servers)
        self.assertIn("claude.ai Google Drive", init_servers)
        self.assertIn("claude.ai Google Calendar", init_servers)
        vault_uses = [
            block
            for event in events
            for block in event.get("message", {}).get("content", [])
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == "mcp__plugin_chrono-vault_chrono-vault__recall"
        ]
        self.assertEqual(len(vault_uses), 1)
        vault_id = vault_uses[0]["id"]
        self.assertTrue(
            any(
                any(
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("tool_use_id") == vault_id
                    and not block.get("is_error", False)
                    for block in event.get("message", {}).get("content", [])
                )
                for event in events
            )
        )
        self.assertTrue(
            any(
                isinstance(event.get("tool_use_result"), dict)
                and event["tool_use_result"].get("query") == "chrono-recon"
                and event["tool_use_result"].get("matches") == []
                for event in events
            )
        )
        self.assertFalse(
            any(
                block.get("name", "").startswith(
                    "mcp__plugin_chrono-recon_chrono-recon__"
                )
                for event in events
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            )
        )
        google_queries = {
            "claude.ai Gmail",
            "claude.ai Google Drive",
            "claude.ai Google Calendar",
        }
        empty_google_queries = {
            event["tool_use_result"].get("query")
            for event in events
            if isinstance(event.get("tool_use_result"), dict)
            and event["tool_use_result"].get("query") in google_queries
            and event["tool_use_result"].get("matches") == []
        }
        self.assertEqual(empty_google_queries, google_queries)
        self.assertFalse(
            any(
                block.get("name", "").startswith("mcp__claude_ai_")
                for event in events
                for block in event.get("message", {}).get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_use"
            )
        )


# --- V113-18: committed work must not need Chrono doing git surgery -----------


def _supervisor_region(marker: str) -> str:
    """The shipped source between `# BEGIN <marker>` and `# END <marker>`.

    Exercising the extracted region rather than a copy is the point: a
    reimplementation here would pass while `bin/board-supervisor.sh` regressed,
    which is the failure mode this whole file exists to avoid. The markers are
    declared load-bearing in the script itself.
    """

    source = SCRIPT.read_text(encoding="utf-8")
    begin = f"# BEGIN {marker}\n"
    end = f"# END {marker}"
    if begin not in source or end not in source:
        raise AssertionError(f"board-supervisor.sh lost the {marker!r} markers")
    return source.split(begin, 1)[1].split(end, 1)[0]


class CommittedWorkRecoveryTests(unittest.TestCase):
    """V113-18 (b): a blocked RETURN path must not strand committed work.

    Three lanes (`w8a`, `w8e`, `wb2`) finished and committed, then lost the
    return path -- two at the lane wall, one on a nested-YAML envelope. Recovery
    meant a human spotting a `PRESERVED WORK` line and running `git cherry-pick`.

    Every test here drives the SHIPPED `recover_committed_work_for_block` over
    real git, through the same `worktree_isolation` the supervisor imports.
    """

    TASK_ID = "TASK-2026-08-28-9918-recovery"
    ATTEMPT_ID = "d-" + "c" * 32
    ARTIFACT = "departments/coding/outbox/response.md"
    SCOPE = ("scripts/python/thing.py", ARTIFACT)

    def setUp(self) -> None:
        # `integrate_worktree_commits` pins its target to SQUAD_BASE_BRANCH, and
        # the disposable fixture repo is created on BASE_BRANCH. Without this the
        # refusal is "integration repo is not checked out on v2", which looks
        # like a product failure and is a fixture failure.
        self._previous_base_branch = os.environ.get("SQUAD_BASE_BRANCH")
        os.environ["SQUAD_BASE_BRANCH"] = BASE_BRANCH

    def tearDown(self) -> None:
        if self._previous_base_branch is None:
            os.environ.pop("SQUAD_BASE_BRANCH", None)
        else:
            os.environ["SQUAD_BASE_BRANCH"] = self._previous_base_branch

    def _namespace(self, repo: Path, handle: object) -> dict:
        """Bind the shipped function to the globals the supervisor gives it."""

        import worktree_isolation as wti

        notes: list[str] = []
        namespace = {
            "os": os,
            "wti": wti,
            "launch_mode": "trusted",
            "execution_kind": "lane",
            "handle": handle,
            "authority": {
                "write_paths": list(self.SCOPE),
                "expected_result_path": self.ARTIFACT,
                "expected_outbox_path": self.ARTIFACT,
            },
            "authorized_delete_paths": (),
            "write_board_note": notes.append,
        }
        exec(_supervisor_region("committed-work-recovery"), namespace)  # noqa: S102
        namespace["_board_notes"] = notes
        return namespace

    def _fixture(self, root: Path):
        import worktree_isolation as wti

        repo = _init_repo(root)
        pool = wti.WorktreePool(repo, root / "pool", base_branch=BASE_BRANCH)
        handle = pool.provision(self.TASK_ID, self.ATTEMPT_ID)
        return repo, handle

    def _worker_commits(self, handle, relative: str, content: str) -> str:
        destination = handle.worktree_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        _git(["add", "--", relative], cwd=handle.worktree_root)
        _git(["commit", "-q", "-m", "worker work"], cwd=handle.worktree_root)
        return subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=str(handle.worktree_root),
            capture_output=True,
            text=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            check=True,
        ).stdout.strip()

    def _branch_head(self, repo: Path) -> str:
        return subprocess.run(
            ["/usr/bin/git", "rev-parse", f"refs/heads/{BASE_BRANCH}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            check=True,
        ).stdout.strip()

    def _reachable(self, repo: Path, commit: str) -> bool:
        return (
            subprocess.run(
                [
                    "/usr/bin/git",
                    "merge-base",
                    "--is-ancestor",
                    commit,
                    f"refs/heads/{BASE_BRANCH}",
                ],
                cwd=str(repo),
                capture_output=True,
                text=True,
                env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            ).returncode
            == 0
        )

    def test_a_failed_return_path_lands_the_workers_committed_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            worker_head = self._worker_commits(
                handle, "scripts/python/thing.py", "the real fix\n"
            )
            before = self._branch_head(repo)
            self.assertFalse(self._reachable(repo, worker_head))

            namespace = self._namespace(repo, handle)
            namespace["_work_recovery_window"][0] = True
            recovery = namespace["recover_committed_work_for_block"]()

            self.assertEqual(recovery["status"], "integrated")
            self.assertEqual(recovery["integrated_paths"], ["scripts/python/thing.py"])
            self.assertNotEqual(self._branch_head(repo), before)
            self.assertTrue(self._reachable(repo, worker_head))
            self.assertEqual(
                (repo / "scripts" / "python" / "thing.py").read_text(encoding="utf-8"),
                "the real fix\n",
            )

    def test_inverted_control_the_same_commit_is_stranded_without_the_window(
        self,
    ) -> None:
        """Break the recovery path; the identical case strands again."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            worker_head = self._worker_commits(
                handle, "scripts/python/thing.py", "the real fix\n"
            )
            before = self._branch_head(repo)

            namespace = self._namespace(repo, handle)
            # The pre-fix supervisor: no window is ever opened, so the block
            # exits 75 with the work reachable only from the attempt branch.
            namespace["_work_recovery_window"][0] = False
            stranded = namespace["recover_committed_work_for_block"]()

            self.assertEqual(stranded["status"], "not-attempted")
            self.assertEqual(self._branch_head(repo), before)
            self.assertFalse(self._reachable(repo, worker_head))
            self.assertFalse((repo / "scripts" / "python" / "thing.py").exists())

            # Restore it: the same fixture, the same commit, now recovered.
            namespace["_work_recovery_window"][0] = True
            recovered = namespace["recover_committed_work_for_block"]()
            self.assertEqual(recovered["status"], "integrated")
            self.assertTrue(self._reachable(repo, worker_head))

    def test_recovery_runs_at_most_once_per_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            self._worker_commits(handle, "scripts/python/thing.py", "the real fix\n")
            namespace = self._namespace(repo, handle)
            namespace["_work_recovery_window"][0] = True

            self.assertEqual(
                namespace["recover_committed_work_for_block"]()["status"], "integrated"
            )
            landed = self._branch_head(repo)
            self.assertEqual(
                namespace["recover_committed_work_for_block"]()["status"],
                "not-attempted",
            )
            self.assertEqual(self._branch_head(repo), landed)

    def test_uncommitted_residue_is_declined_rather_than_half_landed(self) -> None:
        """A lane killed mid-edit must not push an unreviewable file to the branch."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            self._worker_commits(handle, "scripts/python/thing.py", "the real fix\n")
            residue = handle.worktree_root / "scripts" / "python" / "thing.py"
            residue.write_text("half-written when the wall hit\n", encoding="utf-8")
            before = self._branch_head(repo)

            namespace = self._namespace(repo, handle)
            namespace["_work_recovery_window"][0] = True
            declined = namespace["recover_committed_work_for_block"]()

            self.assertEqual(declined["status"], "declined")
            self.assertIn("uncommitted in-scope", declined["reason"])
            self.assertEqual(self._branch_head(repo), before)

    def test_a_worker_that_committed_nothing_recovers_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            before = self._branch_head(repo)
            namespace = self._namespace(repo, handle)
            namespace["_work_recovery_window"][0] = True

            recovery = namespace["recover_committed_work_for_block"]()

            self.assertEqual(recovery["status"], "nothing-to-integrate")
            self.assertEqual(self._branch_head(repo), before)

    def test_out_of_scope_commits_are_still_categorically_refused(self) -> None:
        """Recovery inherits every integration gate; it does not bypass them."""

        with tempfile.TemporaryDirectory() as directory:
            repo, handle = self._fixture(Path(directory))
            self._worker_commits(handle, "bin/not-in-my-scope.sh", "sneaky\n")
            before = self._branch_head(repo)

            namespace = self._namespace(repo, handle)
            namespace["_work_recovery_window"][0] = True
            refused = namespace["recover_committed_work_for_block"]()

            self.assertEqual(refused["status"], "declined")
            self.assertIn("outside the integration scope", refused["reason"])
            self.assertEqual(self._branch_head(repo), before)


class TransportOutputQuarantineTests(unittest.TestCase):
    @staticmethod
    def _namespace() -> dict[str, object]:
        source = SCRIPT.read_text(encoding="utf-8")
        region = source.split("# BEGIN transport-output-quarantine", 1)[1].split(
            "# END transport-output-quarantine", 1
        )[0]
        notes: list[str] = []
        namespace: dict[str, object] = {
            "replace": replace,
            "signal": signal,
            "DispatchContextError": dcb.DispatchContextError,
            "ModeExitVerificationError": dcb.ModeExitVerificationError,
            "CONTROLLER_QUARANTINE_MARKER": reconciler.CONTROLLER_QUARANTINE_MARKER,
            "CLI_DIAGNOSTIC_EXCERPT_BYTES": 2048,
            "write_board_note": notes.append,
            "repo_path": Path("/controller/repo"),
        }
        exec(compile(region, "board-supervisor.sh", "exec"), namespace)
        namespace["notes"] = notes
        return namespace

    @staticmethod
    def _prepared(status: str = "complete") -> dcb.PreparedWorktreeOutputs:
        task_id = "TASK-2026-08-31-1330-quarantine"
        relative = f"departments/coding/outbox/{task_id}-response.md"
        envelope = (
            "---\n"
            f"id: {task_id}-response\n"
            f"in_response_to: {task_id}\n"
            "from: gpt-codex\n"
            "to: chrono\n"
            "type: RESULT\n"
            f"status: {status}\n"
            f"return_artifact: {relative}\n"
            "---\n\n"
            "Worker summary survives quarantine.\n"
        ).encode()
        return dcb.PreparedWorktreeOutputs(
            task_id=task_id,
            result_relative=relative,
            outbox_relative=relative,
            result_bytes=envelope,
            envelope_bytes=envelope,
            status=status,
        )

    def test_worker_status_is_replaced_and_the_fixed_marker_is_published(self) -> None:
        namespace = self._namespace()
        quarantined = namespace["_quarantine_prepared_outputs"](self._prepared())
        text = quarantined.envelope_bytes.decode()
        self.assertEqual(quarantined.status, "needs_review")
        self.assertIn("status: needs_review\n", text)
        self.assertNotIn("status: complete\n", text)
        self.assertIn(
            "controller_quarantine: "
            "validated-artifact-after-cli-transport-failure/v1",
            text,
        )
        self.assertIn("Worker summary survives quarantine.", text)

    def test_real_quarantine_envelope_bytes_match_registry_recognizer(self) -> None:
        namespace = self._namespace()
        produced = namespace["_quarantine_prepared_outputs"](
            self._prepared()
        ).envelope_bytes
        header, boundary, body = produced.decode("utf-8").partition("---\n\n")
        self.assertEqual(boundary, "---\n\n")
        first_line, newline, remaining_body = body.partition("\n")
        self.assertEqual(newline, "\n")

        with tempfile.TemporaryDirectory() as directory:
            response = Path(directory) / "response.md"
            response.write_bytes(produced)
            self.assertTrue(
                reconciler.response_controller_quarantine_active(response)
            )

            near_misses = {
                "marker_not_first": "Worker preface.\n" + body,
                "leading_blank_line": "\n" + body,
                "near_miss_marker": (
                    first_line + "-near-miss" + newline + remaining_body
                ),
            }
            for label, altered_body in near_misses.items():
                with self.subTest(label=label):
                    response.write_text(
                        header + boundary + altered_body,
                        encoding="utf-8",
                    )
                    self.assertFalse(
                        reconciler.response_controller_quarantine_active(response)
                    )

    def test_validated_output_returns_an_authenticated_quarantine_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worker = root / "worker"
            repo.mkdir()
            worker.mkdir()
            prepared = self._prepared()
            worker_response = worker / prepared.outbox_relative
            worker_response.parent.mkdir(parents=True)
            worker_response.write_bytes(prepared.result_bytes)
            authority = {
                "task_id": prepared.task_id,
                "lane": "codex",
                "write_paths": [prepared.outbox_relative],
                "expected_result_path": prepared.result_relative,
                "expected_outbox_path": prepared.outbox_relative,
            }
            namespace = self._namespace()
            namespace["repo_path"] = repo
            namespace["prepare_current_worktree_outputs"] = lambda: (
                dcb.prepare_worktree_outputs(repo, worker, authority)
            )
            namespace["publish_prepared_worktree_outputs"] = (
                dcb.publish_prepared_worktree_outputs
            )

            receipt = namespace["recover_validated_outputs_for_transport_failure"]()

            published = (repo / prepared.outbox_relative).read_text(encoding="utf-8")
            self.assertEqual(
                receipt["controller_quarantine"],
                reconciler.CONTROLLER_QUARANTINE_MARKER,
            )
            self.assertEqual(receipt["response_status"], "needs_review")
            self.assertIn("status: needs_review", published)
            self.assertIn(reconciler.CONTROLLER_QUARANTINE_MARKER, published)
            self.assertNotIn("status: complete", published)

    def test_agycanary_shape_without_an_artifact_has_no_marker(self) -> None:
        namespace = self._namespace()
        published: list[object] = []

        def missing_artifact() -> None:
            raise dcb.DispatchContextError("return artifact is missing")

        namespace["prepare_current_worktree_outputs"] = missing_artifact
        namespace["publish_prepared_worktree_outputs"] = (
            lambda *args: published.append(args)
        )
        self.assertIsNone(
            namespace["recover_validated_outputs_for_transport_failure"]()
        )
        self.assertEqual(published, [])
        self.assertIn("return artifact is missing", namespace["notes"][0])

    def test_diagnostics_bound_both_streams_and_distinguish_signal_and_timeout(self) -> None:
        namespace = self._namespace()
        stdout = namespace["_bounded_cli_stream"]("x" * 3000 + "stdout-cause")
        stderr = namespace["_bounded_cli_stream"]("y" * 3000 + "stderr-cause")
        self.assertLessEqual(len(stdout["excerpt"].encode()), 2048)
        self.assertLessEqual(len(stderr["excerpt"].encode()), 2048)
        self.assertTrue(stdout["truncated"])
        self.assertTrue(stderr["truncated"])
        self.assertTrue(stdout["excerpt"].endswith("stdout-cause"))
        self.assertTrue(stderr["excerpt"].endswith("stderr-cause"))
        self.assertEqual(
            namespace["_termination_diagnostics"]("cli_nonzero", 143),
            {
                "termination_kind": "signal",
                "signal_number": 15,
                "signal_name": "SIGTERM",
            },
        )
        self.assertEqual(
            namespace["_termination_diagnostics"]("cli_nonzero", 173)[
                "termination_kind"
            ],
            "exit",
        )
        self.assertEqual(
            namespace["_termination_diagnostics"]("cli_timeout", None)[
                "termination_kind"
            ],
            "timeout",
        )

    def test_nonzero_and_reaped_timeout_share_recovery_and_stub_skip_is_fenced(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        marker = re.search(
            r'^readonly controller_quarantine_marker="([^"]+)"$',
            source,
            re.MULTILINE,
        )
        self.assertIsNotNone(marker)
        self.assertEqual(
            marker.group(1), reconciler.CONTROLLER_QUARANTINE_MARKER
        )
        launch = source.split("completed = launch_task(", 1)[1].split(
            "observed_memory_ids = set()", 1
        )[0]
        self.assertEqual(
            launch.count("recover_validated_outputs_for_transport_failure()"), 2
        )
        timeout = launch.index("except subprocess.TimeoutExpired")
        self.assertLess(
            timeout,
            launch.index("recover_validated_outputs_for_transport_failure()", timeout),
        )
        detached = source.split('if [[ "${1:-}" == "detached-launch" ]]', 1)[1].split(
            'if [[ "${1:-}" == "trusted-launch" ]]', 1
        )[0]
        quarantine_gate = detached.index(
            'if [[ "$quarantined_response" != "yes" ]]'
        )
        blocked_stub = detached.index('"$context_builder" blocked', quarantine_gate)
        self.assertLess(quarantine_gate, blocked_stub)

    def test_v2_finalizer_preserves_the_authenticated_quarantine_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context.json"
            context.write_text("{}\n", encoding="utf-8")
            descriptor = root / "dispatch.json"
            descriptor.write_text(
                json.dumps(
                    {
                        "task_id": "TASK-2026-08-31-1330-finalizer",
                        "attempt_id": "d-" + "5" * 32,
                        "generation": 1,
                        "context_path": str(context),
                    }
                ),
                encoding="utf-8",
            )
            raw = root / "raw.json"
            raw.write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "response_status": "needs_review",
                        "controller_quarantine": (
                            reconciler.CONTROLLER_QUARANTINE_MARKER
                        ),
                        "cli_exec_succeeded": False,
                        "failure_class": "cli_nonzero",
                    }
                ),
                encoding="utf-8",
            )
            receipt = root / "receipt.json"
            with (
                mock.patch.object(process_truth, "descriptor_error", return_value=None),
                mock.patch.object(process_truth, "_bound", return_value=True),
                mock.patch.object(
                    process_truth, "process_truth", return_value={"state": "live"}
                ),
            ):
                finalized = process_truth.finalize_receipt(
                    raw, descriptor, receipt
                )
            self.assertEqual(finalized["status"], "blocked")
            self.assertEqual(finalized["terminal_outcome"], "needs_review")
            self.assertEqual(
                finalized["controller_quarantine"],
                reconciler.CONTROLLER_QUARANTINE_MARKER,
            )
            self.assertIs(finalized["cli_exec_succeeded"], False)


class BlockedReceiptStaysBlockedTests(unittest.TestCase):
    """The rail: recovery makes work REACHABLE, never settles a blocked receipt."""

    @staticmethod
    def _install_hermetic_launch_stubs(root: Path, executable: Path) -> Path:
        """Stub only the host preflight and approved offline executable.

        The shipped supervisor program still authenticates, provisions, launches
        the real fixture process, classifies its nonzero exit, and authors the
        receipt.  Seatbelt's live-host canary is outside this test's subject and
        cannot run on Linux, so ``sitecustomize`` patches those two imported
        inputs in the supervisor subprocess before its embedded program starts.
        """

        sitecustomize = root / "sitecustomize.py"
        sitecustomize.write_text(
            """\
import hashlib
import os
from pathlib import Path
import subprocess

import launch_hygiene
import seatbelt_profile

fixture_executable = Path(os.environ["TRUSTED_LAUNCH_STUB_CLI"])
seatbelt_profile.OFFLINE_LAUNCH_EXECUTABLES = (
    *seatbelt_profile.OFFLINE_LAUNCH_EXECUTABLES,
    fixture_executable,
)

# Some hermetic runners prohibit creating a new session even though the
# fixture process is already bounded and synchronous.  Keep the shipped
# launcher's Popen path, but remove that one unavailable host operation.
real_popen = subprocess.Popen


def hermetic_popen(*args, **kwargs):
    kwargs.pop("start_new_session", None)
    return real_popen(*args, **kwargs)


subprocess.Popen = hermetic_popen


class HermeticListener:
    def getsockname(self):
        return ("127.0.0.1", 1)

    def close(self):
        return None


def hermetic_preflight(
    task_root,
    *,
    request_sha256="",
    audited_scopes=(),
    retain_launch=False,
):
    if not retain_launch:
        raise AssertionError("trusted-launch fixture must retain its preflight")
    scope_sha256 = hashlib.sha256(
        "\\n".join(str(scope.path) for scope in audited_scopes).encode("utf-8")
    ).hexdigest()
    canary = launch_hygiene.CanaryResult(
        profile_sha256="f" * 64,
        allowed_write=True,
        denied_write=True,
        exact_broker_port=True,
        wrong_port_denied=True,
        fd3_closed=True,
        request_sha256=request_sha256,
        scope_sha256=scope_sha256,
        details=("hermetic trusted-launch classification fixture",),
    )
    compatibility = seatbelt_profile.HostCompatibility(
        sandbox_exec=Path("/usr/bin/true"),
        macos_build="hermetic-fixture",
        canary_sha256="e" * 64,
    )
    profile = seatbelt_profile.CompiledProfile(
        text="",
        sha256=canary.profile_sha256,
        compatibility=compatibility,
    )
    return launch_hygiene.PreparedLaunch(
        profile=profile,
        broker_listener=HermeticListener(),
        canary=canary,
        task_root=Path(task_root),
        environment={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        scopes=tuple(audited_scopes),
        owned_scopes=(),
    )


launch_hygiene.run_preflight_canary = hermetic_preflight
""",
            encoding="utf-8",
        )
        return sitecustomize.parent

    @unittest.skipIf(
        HEAD_IS_DETACHED,
        "request validation refuses a detached checkout before the worker CLI "
        "runs, so a cli_nonzero block is unreachable in this shape",
    )
    def test_a_real_supervisor_block_reports_recovery_and_still_exits_75(self) -> None:
        """End-to-end through the shipped script, not a fixture of it.

        The test-only executable is admitted as an inert offline probe by the
        subprocess fixture, so this drives a genuine provision -> launch ->
        nonzero -> `block_after_provision` run.
        The receipt must now carry a machine-readable `work_recovery` outcome --
        the whole point being that Chrono stops having to notice a log line --
        while the status and the exit code are unchanged.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "nonzero-cli"
            executable.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
            executable.chmod(0o700)
            stub_root = self._install_hermetic_launch_stubs(root, executable)
            payload = TrustedLaunchTests()._fixture_payload(
                root,
                task_id="TASK-2026-08-28-9919-blockpath",
                attempt_id="d-" + "e" * 32,
            )
            payload["authority"]["executable"] = str(executable)
            payload["authority"]["executable_sha256"] = hashlib.sha256(
                Path(os.path.realpath(executable)).read_bytes()
            ).hexdigest()
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                json.dump(payload, handle)
                context_path = Path(handle.name)
            try:
                completed = subprocess.run(
                    ["/bin/bash", str(SCRIPT), "trusted-launch", str(context_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env={
                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                        "LC_ALL": "C",
                        "VAULT_ROOT": str(ROOT),
                        "TRUSTED_LAUNCH_TEST_MODE": "1",
                        "SQUAD_BASE_BRANCH": BASE_BRANCH,
                        "PYTHONPATH": os.pathsep.join((str(stub_root), str(PYTHON_DIR))),
                        "TRUSTED_LAUNCH_STUB_CLI": str(executable),
                    },
                )
            finally:
                context_path.unlink(missing_ok=True)

            receipt = json.loads(completed.stdout.strip() or completed.stderr.strip())
            self.assertEqual(completed.returncode, 75)
            self.assertEqual(receipt["status"], "blocked")
            self.assertEqual(receipt["failure_class"], "cli_nonzero")
            self.assertIn("work_recovery", receipt)
            # An offline probe has no lane integration on the SUCCESS path
            # either, so recovery correctly declines rather than inventing one.
            self.assertEqual(receipt["work_recovery"]["status"], "not-attempted")
            self.assertEqual(
                receipt["work_recovery"]["reason"], "not a trusted lane launch"
            )

    def test_the_block_receipt_reports_recovery_without_changing_status(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        block = source.split("def block_after_provision(", 1)[1].split(
            "\n    sys.exit(75)", 1
        )[0]
        self.assertIn('"status": "blocked"', block)
        self.assertIn('"work_recovery": work_recovery', block)
        self.assertIn('"cli_stdout_excerpt"', block)
        self.assertIn('"cli_stderr_excerpt"', block)
        self.assertIn("_termination_diagnostics", block)
        self.assertIn("payload.update(controller_quarantine)", block)
        self.assertNotIn("sys.exit(0)", block)
        # Nothing on this path may promote the attempt to a launched receipt.
        self.assertNotIn('"status": "launched"', block)

    def test_the_recovery_window_is_opened_and_closed_exactly_once(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(source.count("_work_recovery_window[0] = True"), 1)
        opened = source.index("_work_recovery_window[0] = True")
        closed = source.index("_work_recovery_window[0] = False\n        try:")
        launch = source.index("completed = launch_task(")
        prevalidate = source.index(
            "prepared_outputs = prepare_current_worktree_outputs()", launch
        )
        # Opened before the worker CLI, closed after prevalidation and before
        # integration: exactly the span in which a block means the return path
        # failed rather than the work being judged.
        self.assertLess(opened, launch)
        self.assertLess(launch, prevalidate)
        self.assertLess(prevalidate, closed)

    def test_the_envelope_repair_runs_before_prevalidation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        prepare = source.split("def prepare_current_worktree_outputs():", 1)[1].split(
            "\n    if vault_broker is not None:", 1
        )[0]
        repair = prepare.index("repair_worker_envelope_frontmatter()")
        prevalidate = prepare.index("return prepare_worktree_outputs(")
        self.assertLess(repair, prevalidate)


if __name__ == "__main__":
    unittest.main()
