"""Aperture enforcement at the process-environment layer, not the interface.

``test_apertures.py`` covers the interface: which *operations* an aperture may
call. This file covers the *address*: whether a worker is handed a vault path it
is not entitled to open. The two are the same policy row read for two different
questions, so both files load ``shared/registries/memory-apertures.tsv`` through
``clearance.memory_policies`` and neither restates it.

Every test here is a negative control: it fails if the enforcement it names is
removed. The one exception is flagged in its own docstring — it pins a residual
bypass that is still OPEN, and is written to fail when that bypass is closed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

import clearance  # noqa: E402


# The intent, stated independently of the implementation. Recomputing the
# entitlement from the policy row here would only assert that the code equals
# itself; this table is what a reviewer checks the row against.
EXPECTED_ENTITLEMENT = {
    "rich": clearance.PATH_READ,
    "focused": clearance.PATH_READ,
    "cold": clearance.PATH_WRITE_ONLY,
    "pool_blind": clearance.PATH_WRITE_ONLY,
    "none": clearance.PATH_NONE,
}


class VaultPathEntitlementTests(unittest.TestCase):
    def setUp(self) -> None:
        # Hermetic by construction: this suite runs inside board workers whose
        # own CHRONO_VAULT_CONTEXT would otherwise bind every clearance call.
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_entitlement_matches_the_declared_intent(self) -> None:
        for aperture, expected in EXPECTED_ENTITLEMENT.items():
            with self.subTest(aperture=aperture):
                self.assertEqual(
                    clearance.vault_path_entitlement(aperture), expected
                )

    def test_entitlement_covers_every_canonical_aperture(self) -> None:
        self.assertEqual(
            set(EXPECTED_ENTITLEMENT), set(clearance.memory_policies())
        )

    def test_read_denied_apertures_are_never_entitled_to_read(self) -> None:
        for aperture in ("cold", "pool_blind", "none"):
            with self.subTest(aperture=aperture):
                self.assertNotEqual(
                    clearance.vault_path_entitlement(aperture),
                    clearance.PATH_READ,
                )

    def test_unknown_aperture_is_refused(self) -> None:
        with self.assertRaises(clearance.ClearanceError):
            clearance.vault_path_entitlement("unrestricted")


class WorkerEnvironmentProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temp_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-worker-env-"))
        )
        self.addCleanup(shutil.rmtree, self.temp_root, ignore_errors=True)
        self.vault_root = self.temp_root / "vault"
        self.audit_dir = self.temp_root / "audit"
        self.worker = {
            "CHRONO_VAULT_ROOT": str(self.vault_root),
            "OBSIDIAN_VAULT_ROOT": str(self.vault_root),
            "CHRONO_VAULT_CONTEXT": '{"aperture":"none"}',
            "CHRONO_VAULT_AUDIT_DIR": str(self.audit_dir),
            "PATH": "/usr/bin:/bin",
        }

    def test_no_access_aperture_is_handed_no_vault_path(self) -> None:
        projected = clearance.project_worker_vault_environment(
            self.worker, aperture="none"
        )
        for name in clearance.VAULT_PATH_ENV:
            with self.subTest(variable=name):
                self.assertNotIn(name, projected)

    def test_projection_keeps_everything_that_is_not_a_vault_path(self) -> None:
        projected = clearance.project_worker_vault_environment(
            self.worker, aperture="none"
        )
        # The audit home and the engagement context must survive: the audit
        # trail has to outlive an unresolvable root, and the context is what
        # keeps the interface check bound.
        self.assertEqual(projected["PATH"], "/usr/bin:/bin")
        self.assertEqual(
            projected["CHRONO_VAULT_AUDIT_DIR"],
            str(self.audit_dir),
        )
        self.assertEqual(
            projected["CHRONO_VAULT_CONTEXT"], '{"aperture":"none"}'
        )

    def test_recording_apertures_keep_the_path_they_need(self) -> None:
        # cold and pool_blind may record. Stripping their path would break the
        # write they are entitled to, so this is the non-regression half.
        for aperture in ("rich", "focused", "cold", "pool_blind"):
            with self.subTest(aperture=aperture):
                projected = clearance.project_worker_vault_environment(
                    self.worker, aperture=aperture
                )
                self.assertEqual(
                    projected["CHRONO_VAULT_ROOT"],
                    str(self.vault_root),
                )

    def test_projection_does_not_mutate_the_caller(self) -> None:
        clearance.project_worker_vault_environment(self.worker, aperture="none")
        self.assertIn("CHRONO_VAULT_ROOT", self.worker)

    def test_projection_refuses_a_non_mapping(self) -> None:
        with self.assertRaises(clearance.ClearanceError):
            clearance.project_worker_vault_environment(
                [("CHRONO_VAULT_ROOT", "/tmp")], aperture="none"
            )

    def test_projection_refuses_an_unknown_aperture(self) -> None:
        with self.assertRaises(clearance.ClearanceError):
            clearance.project_worker_vault_environment(
                self.worker, aperture="unrestricted"
            )


class ResidualBypassTests(unittest.TestCase):
    """Pins a bypass that is still OPEN. Read the docstring before "fixing" it.

    A ``cold``/``pool_blind`` worker is handed ``CHRONO_VAULT_ROOT`` because it
    is entitled to ``record``, and nothing stops it reading the corpus at that
    path. This test asserts the bypass reproduces, so the residual is a failing
    fact in CI rather than a sentence in a report that ages out.

    When the broker/sandbox work closes it, this test will fail. That is the
    signal to INVERT it (assert the read is refused), not to delete it.
    """

    def setUp(self) -> None:
        self.root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-residual-"))
        )
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "residual-test", "schema_version": 1}),
            encoding="utf-8",
        )
        note_dir = self.root / "notes" / "finding"
        note_dir.mkdir(parents=True)
        self.note = note_dir / "mem-residual.md"
        self.note.write_text(
            '---\nid: "mem-residual"\ntype: "finding"\nstatus: "verified"\n'
            'sensitivity: "restricted"\n---\n\nPRIOR-FINDING-CANARY\n',
            encoding="utf-8",
        )

    def _bound(self, aperture: str):
        """Bind one lane engagement for the duration of a ``with`` block.

        Returned as a context manager rather than started with ``addCleanup``:
        a deferred ``stop()`` restores whatever ``os.environ`` held when the
        patch was *created*, so starting one inside another cleared patch
        silently restores an empty environment for every later test in the
        run. That cost four unrelated failures in ``test_launch_clearance``,
        which spawns subprocesses and needs ``HOME``.
        """
        return mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.root),
                "CHRONO_VAULT_CONTEXT": json.dumps(
                    {
                        "schema": clearance.CONTEXT_SCHEMA,
                        "task_id": "TASK-2026-08-13-1140-p10b-aperture-isolation",
                        "attempt_id": "d-" + "0" * 32,
                        "generation": 1,
                        "mode": "project",
                        "aperture": aperture,
                        "focus": None,
                        "engagement_start": "2026-08-13T15:47:30Z",
                    },
                    sort_keys=True,
                ),
            },
            clear=True,
        )

    def test_interface_refuses_the_read(self) -> None:
        # Positive control. Without this, a passing bypass test could just mean
        # the aperture was never bound in the first place.
        for aperture in ("cold", "pool_blind"):
            with self.subTest(aperture=aperture), self._bound(aperture):
                for operation in ("recall", "get_note", "browse"):
                    with self.assertRaises(clearance.ClearanceError):
                        clearance.require_memory_operation(operation)

    def test_direct_filesystem_read_still_reaches_the_forbidden_note(self) -> None:
        with self._bound("cold"):
            # The exact primitive: the path the aperture handed over, opened
            # directly. No vault API is involved, so no vault check applies.
            reached = Path(os.environ["CHRONO_VAULT_ROOT"], "notes", "finding")
            bodies = [
                item.read_text(encoding="utf-8") for item in reached.glob("*.md")
            ]
        self.assertTrue(
            any("PRIOR-FINDING-CANARY" in body for body in bodies),
            "residual bypass appears closed -- invert this test, do not delete it",
        )


if __name__ == "__main__":
    unittest.main()
