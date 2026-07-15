from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))


class _FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.settings = types.SimpleNamespace(port=None)

    def tool(self, name: str | None = None):
        del name
        return lambda function: function

    def run(self, **kwargs) -> None:
        del kwargs


fake_httpx = types.ModuleType("httpx")
fake_httpx.HTTPStatusError = type("HTTPStatusError", (Exception,), {})
fake_httpx.RequestError = type("RequestError", (Exception,), {})
fake_mcp = types.ModuleType("mcp")
fake_mcp_server = types.ModuleType("mcp.server")
fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
fake_fastmcp.FastMCP = _FakeFastMCP
sys.modules.setdefault("httpx", fake_httpx)
sys.modules.setdefault("mcp", fake_mcp)
sys.modules.setdefault("mcp.server", fake_mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", fake_fastmcp)

import clearance  # noqa: E402
import mcp_server  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


class ClearancePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-clearance-test-"))
        )
        self.addCleanup(shutil.rmtree, self.vault_root, ignore_errors=True)
        (self.vault_root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "clearance-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.env = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.vault_root),
                "CHRONO_VAULT_CLEARANCE": "internal",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _record(self, token: str, sensitivity: str) -> dict:
        return notes.record(
            "finding",
            {
                "title": f"{token} {sensitivity} evidence",
                "body": f"{token} body has {sensitivity} sensitivity.",
                "target": "push-chain",
                "component": "executor",
                "attack_class": "clearance",
                "status": "verified",
                "sensitivity": sensitivity,
            },
        )

    def test_policy_defaults_to_internal_and_only_exact_restricted_upgrades(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(clearance.lane_clearance(), "internal")
        for invalid in ("", "restricted ", "RESTRICTED", "admin", "*"):
            with self.subTest(invalid=invalid):
                with mock.patch.dict(
                    os.environ,
                    {"CHRONO_VAULT_CLEARANCE": invalid},
                ):
                    self.assertEqual(clearance.lane_clearance(), "internal")
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            self.assertEqual(clearance.lane_clearance(), "restricted")

        self.assertTrue(clearance.can_read("internal", "internal"))
        self.assertTrue(clearance.can_read("internal", "restricted"))
        self.assertFalse(clearance.can_read("restricted", "internal"))
        self.assertTrue(clearance.can_read("restricted", "restricted"))
        self.assertFalse(clearance.can_read("unknown", "restricted"))

    def test_recall_hides_restricted_by_default_and_returns_it_when_authorized(self) -> None:
        internal = self._record("SharedClearanceToken", "internal")
        restricted = self._record("SharedClearanceToken", "restricted")

        default_result = vault_recall.recall("SharedClearanceToken")
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            privileged_result = vault_recall.recall("SharedClearanceToken")

        self.assertEqual(
            [row["id"] for row in default_result["results"]],
            [internal["id"]],
        )
        self.assertEqual(
            {row["id"] for row in privileged_result["results"]},
            {internal["id"], restricted["id"]},
        )
        restricted_row = next(
            row for row in privileged_result["results"] if row["id"] == restricted["id"]
        )
        self.assertEqual(restricted_row["sensitivity"], "restricted")

    def test_internal_note_is_visible_to_both_clearances(self) -> None:
        internal = self._record("InternalEverywhereToken", "internal")

        under_internal = vault_recall.recall("InternalEverywhereToken")
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            under_restricted = vault_recall.recall("InternalEverywhereToken")

        self.assertEqual([row["id"] for row in under_internal["results"]], [internal["id"]])
        self.assertEqual(
            [row["id"] for row in under_restricted["results"]],
            [internal["id"]],
        )

    def test_caller_filter_cannot_upgrade_server_clearance(self) -> None:
        restricted = self._record("NoCallerUpgradeToken", "restricted")

        self.assertEqual(vault_recall.recall("NoCallerUpgradeToken")["results"], [])
        for field in ("clearance", "sensitivity", "include_restricted"):
            with self.subTest(field=field):
                with self.assertRaises(vault_recall.RecallError):
                    vault_recall.recall(
                        "NoCallerUpgradeToken",
                        filters={field: "restricted"},
                    )
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            authorized = vault_recall.recall("NoCallerUpgradeToken")
        self.assertEqual([row["id"] for row in authorized["results"]], [restricted["id"]])

    def test_clearance_filter_runs_before_limit(self) -> None:
        internal = self._record("PreLimitToken", "internal")
        for _ in range(3):
            self._record("PreLimitToken", "restricted")

        result = vault_recall.recall("PreLimitToken", limit=1)

        self.assertEqual([row["id"] for row in result["results"]], [internal["id"]])

    def test_mcp_get_note_refuses_restricted_body_until_authorized(self) -> None:
        restricted = self._record("GetRestrictedToken", "restricted")

        with self.assertRaises(clearance.ClearanceError):
            mcp_server.get_note(restricted["id"])
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            note = mcp_server.get_note(restricted["id"])

        self.assertEqual(note["id"], restricted["id"])
        self.assertIn("GetRestrictedToken", note["body"])

    def test_status_mutation_cannot_return_restricted_note_to_internal_lane(self) -> None:
        restricted = self._record("MutateRestrictedToken", "restricted")
        internal = self._record("MutateInternalToken", "internal")

        with self.assertRaises(clearance.ClearanceError):
            mcp_server.set_status(
                restricted["id"],
                "archived",
                "retired evidence",
                expected_revision=1,
            )
        with self.assertRaises(clearance.ClearanceError):
            mcp_server.set_status(
                internal["id"],
                "superseded",
                "must not link an under-cleared replacement",
                expected_revision=1,
                supersedes=restricted["id"],
            )
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            changed = mcp_server.set_status(
                restricted["id"],
                "archived",
                "retired evidence",
                expected_revision=1,
            )

        self.assertEqual(changed["status"], "archived")
        self.assertEqual(changed["revision"], 2)

    def test_compat_finding_cannot_inherit_restricted_attempt_context(self) -> None:
        attempt = notes.record(
            "attempt",
            {
                "title": "Restricted attempt context",
                "body": "Private target and attack-class context.",
                "target": "private-target",
                "attack_class": "private-class",
                "status": "verified",
                "sensitivity": "restricted",
            },
        )

        with self.assertRaises(ValueError):
            mcp_server.record_finding(
                attempt_id=attempt["id"],
                title="Denied inherited context",
                severity="high",
                description="Must not inherit under internal clearance.",
                evidence="artifact:denied-inheritance",
            )
        with mock.patch.dict(
            os.environ,
            {"CHRONO_VAULT_CLEARANCE": "restricted"},
        ):
            finding_id = mcp_server.record_finding(
                attempt_id=attempt["id"],
                title="Allowed inherited context",
                severity="high",
                description="Restricted lane may inherit the context.",
                evidence="artifact:allowed-inheritance",
            )
            finding = mcp_server.get_note(finding_id)

        self.assertEqual(finding["target"], "private-target")
        self.assertEqual(finding["attack_class"], "private-class")
        self.assertEqual(finding["sensitivity"], "restricted")


if __name__ == "__main__":
    unittest.main()
