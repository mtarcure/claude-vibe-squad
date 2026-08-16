"""Production wiring checks for board-worker vault-path projection.

The policy primitive lives in :mod:`clearance`; these tests exercise the
embedded Python from ``bin/board-supervisor.sh`` so a helper-only test cannot
pass while the production rail remains unwired.  The subprocess probes model
the exact bypass primitive: obtain ``CHRONO_VAULT_ROOT`` from the worker's own
environment and open a note beneath it without calling the vault interface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "chrono-vault"
SUPERVISOR = REPO_ROOT / "bin" / "board-supervisor.sh"
sys.path.insert(0, str(PLUGIN_ROOT))

import clearance  # noqa: E402


READ_PROBE = r"""
import os
from pathlib import Path
import sys

try:
    vault_root = os.environ["CHRONO_VAULT_ROOT"]
except KeyError:
    print("READ_DENIED:CHRONO_VAULT_ROOT missing")
    raise SystemExit(23)

note_dir = Path(vault_root, "notes", "finding")
bodies = [path.read_text(encoding="utf-8") for path in note_dir.glob("*.md")]
if any("PRIOR-FINDING-CANARY" in body for body in bodies):
    print("READ_OK:PRIOR-FINDING-CANARY")
    raise SystemExit(0)
print("READ_FAILED:canary absent")
raise SystemExit(24)
"""

WRITE_PROBE = r"""
import os
from pathlib import Path

target = Path(os.environ["CHRONO_VAULT_ROOT"], "notes", "attempt", "record-canary.md")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("RECORD-CANARY\n", encoding="utf-8")
print("WRITE_OK:RECORD-CANARY")
"""


def _production_environment_builder(aperture: str):
    """Compile the production builder and its call-site policy projection."""

    source = SUPERVISOR.read_text(encoding="utf-8")
    start = source.index("def trusted_worker_environment(worker_lane):")
    end = source.index(
        '\n\nmemory_context_value = authority.get("memory_context")', start
    )
    projection_start = source.index(
        "trusted_environment = trusted_worker_environment(lane)"
    )
    projection_end = source.index(
        '\ntrusted_environment["CHRONO_VAULT_CONTEXT"]', projection_start
    )
    projection_code = compile(
        source[projection_start:projection_end], str(SUPERVISOR), "exec"
    )
    namespace = {
        "DEFAULT_LANE_PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "Path": Path,
        "_prepare_codex_home": lambda *_args, **_kwargs: None,
        "_validated_trusted_host_path": lambda: "/usr/bin:/bin:/usr/sbin:/sbin",
        "attempt_id": "",
        "load_gemini_api_key": lambda: "synthetic-gemini-key",
        "memory_context_value": {"aperture": aperture},
        "os": os,
        "project_worker_vault_environment": (
            clearance.project_worker_vault_environment
        ),
        "repo_path": REPO_ROOT,
    }
    exec(compile(source[start:end], str(SUPERVISOR), "exec"), namespace)

    def build(worker_lane: str):
        namespace["lane"] = worker_lane
        exec(projection_code, namespace)
        return namespace["trusted_environment"]

    return build


def _make_vault(root: Path) -> Path:
    vault = root / "private-vault"
    note_dir = vault / "notes" / "finding"
    note_dir.mkdir(parents=True)
    (vault / ".chrono-vault").write_text(
        json.dumps({"vault_id": "wiring-test", "schema_version": 1}),
        encoding="utf-8",
    )
    (note_dir / "mem-canary.md").write_text(
        "---\nsensitivity: restricted\n---\n\nPRIOR-FINDING-CANARY\n",
        encoding="utf-8",
    )
    return vault


def _worker_environment(
    vault: Path, aperture: str, *, lane: str = "claude"
) -> dict[str, str]:
    ambient = {
        "HOME": str(vault.parent),
        "CHRONO_VAULT_ROOT": str(vault),
        "OBSIDIAN_VAULT_ROOT": str(vault),
        "CHRONO_VAULT_AUDIT_DIR": str(vault.parent / "audit"),
        "OPENAI_API_KEY": "must-not-cross",
    }
    with mock.patch.dict(os.environ, ambient, clear=True):
        return _production_environment_builder(aperture)(lane)


def _run_worker(code: str, environment: dict[str, str]):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class ProductionWiringTests(unittest.TestCase):
    def test_policy_projector_is_called_inside_the_production_builder(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        start = source.index("def trusted_worker_environment(worker_lane):")
        end = source.index(
            '\n\nmemory_context_value = authority.get("memory_context")', start
        )
        body = source[start:end]
        projection_start = source.index(
            "trusted_environment = trusted_worker_environment(lane)"
        )
        projection_end = source.index(
            '\ntrusted_environment["CHRONO_VAULT_CONTEXT"]', projection_start
        )
        projection_body = source[projection_start:projection_end]

        self.assertEqual(source.count("project_worker_vault_environment("), 1)
        self.assertNotIn("project_worker_vault_environment(", body)
        self.assertIn(
            "trusted_environment = project_worker_vault_environment(",
            projection_body,
        )
        self.assertIn(
            'aperture=memory_context_value["aperture"]', projection_body
        )
        validation = source.index("memory_context_value = validate_memory_context(")
        environment_build = source.index(
            "trusted_environment = trusted_worker_environment(lane)", validation
        )
        controller_copy = source.index(
            "controller_vault_environment = dict(trusted_environment)",
            environment_build,
        )
        projection = source.index(
            "trusted_environment = project_worker_vault_environment(",
            controller_copy,
        )
        context_export = source.index(
            'trusted_environment["CHRONO_VAULT_CONTEXT"] = json.dumps('
        )
        self.assertLess(validation, environment_build)
        self.assertLess(environment_build, controller_copy)
        self.assertLess(controller_copy, projection)
        self.assertLess(projection, context_export)
        launch_tail = source[projection:]
        self.assertNotIn(
            'trusted_environment["CHRONO_VAULT_ROOT"] =', launch_tail
        )
        self.assertNotIn(
            'trusted_environment["OBSIDIAN_VAULT_ROOT"] =', launch_tail
        )

    def test_none_worker_cannot_repeat_the_exact_direct_read(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aperture-none-") as directory:
            vault = _make_vault(Path(directory))
            for lane in ("claude", "codex", "gemini", "kimi"):
                environment = _worker_environment(vault, "none", lane=lane)
                completed = _run_worker(READ_PROBE, environment)
                for variable in clearance.VAULT_PATH_ENV:
                    with self.subTest(lane=lane, absent=variable):
                        self.assertFalse(
                            variable in environment,
                            f"{variable} unexpectedly present",
                        )
                with self.subTest(lane=lane, oracle="direct-read"):
                    self.assertEqual(completed.returncode, 23, completed)
                    self.assertEqual(
                        completed.stdout.strip(),
                        "READ_DENIED:CHRONO_VAULT_ROOT missing",
                    )

    def test_read_entitled_workers_still_reach_the_vault(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aperture-read-") as directory:
            vault = _make_vault(Path(directory))
            for aperture in ("rich", "focused"):
                with self.subTest(aperture=aperture):
                    environment = _worker_environment(vault, aperture)
                    completed = _run_worker(READ_PROBE, environment)
                    self.assertEqual(completed.returncode, 0, completed)
                    self.assertEqual(
                        completed.stdout.strip(),
                        "READ_OK:PRIOR-FINDING-CANARY",
                    )

    def test_record_entitled_workers_keep_a_usable_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aperture-record-") as directory:
            vault = _make_vault(Path(directory))
            for aperture in ("cold", "pool_blind"):
                with self.subTest(aperture=aperture):
                    environment = _worker_environment(vault, aperture)
                    self.assertEqual(
                        environment["CHRONO_VAULT_ROOT"], str(vault)
                    )
                    completed = _run_worker(WRITE_PROBE, environment)
                    self.assertEqual(completed.returncode, 0, completed)
                    self.assertEqual(
                        completed.stdout.strip(), "WRITE_OK:RECORD-CANARY"
                    )

    def test_non_vault_environment_contract_survives_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aperture-contract-") as directory:
            vault = _make_vault(Path(directory))
            environment = _worker_environment(vault, "none")

        self.assertEqual(environment["HOME"], str(vault.parent))
        self.assertEqual(
            environment["CHRONO_VAULT_AUDIT_DIR"],
            str(vault.parent / "audit"),
        )
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("OPENAI_API_KEY", environment)


def _demo() -> int:
    """Print bounded, synthetic worker evidence for the audit artifact."""

    with tempfile.TemporaryDirectory(prefix="aperture-demo-") as directory:
        vault = _make_vault(Path(directory))
        for aperture, probe in (
            ("none", READ_PROBE),
            ("rich", READ_PROBE),
            ("cold", WRITE_PROBE),
            ("pool_blind", WRITE_PROBE),
        ):
            environment = _worker_environment(vault, aperture)
            completed = _run_worker(probe, environment)
            print(
                json.dumps(
                    {
                        "aperture": aperture,
                        "chrono_vault_root_present": (
                            "CHRONO_VAULT_ROOT" in environment
                        ),
                        "obsidian_vault_root_present": (
                            "OBSIDIAN_VAULT_ROOT" in environment
                        ),
                        "worker_returncode": completed.returncode,
                        "worker_stdout": completed.stdout.strip(),
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--demo"]:
        raise SystemExit(_demo())
    unittest.main()
