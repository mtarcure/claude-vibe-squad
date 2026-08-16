"""Audit trail for recall/record (ledger P4.4).

Every recall and record must emit one event carrying the five ledger fields, and
the trail must make four states distinguishable: a recall that matched nothing, a
recall that ran against an empty store, a recall that ran against a broken root,
and a recall that never ran (absence of an event). These tests fail without the
audit wiring in `audit.py`, `recall.py`, and `notes.py`.
"""
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


# notes/recall import cleanly without mcp, but mcp_server needs a stub; keep it
# available so the whole plugin can be imported the way the other suites do.
fake_mcp = types.ModuleType("mcp")
fake_mcp_server = types.ModuleType("mcp.server")
fake_fastmcp = types.ModuleType("mcp.server.fastmcp")


class _FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, name: str | None = None):
        del name
        return lambda function: function

    def run(self, **kwargs) -> None:
        del kwargs


fake_fastmcp.FastMCP = _FakeFastMCP
sys.modules.setdefault("mcp", fake_mcp)
sys.modules.setdefault("mcp.server", fake_mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", fake_fastmcp)

import audit  # noqa: E402
import index as vault_index  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


TASK_ID = "TASK-2026-08-11-1200-audit"
ATTEMPT_ID = "d-0123456789abcdef0123456789abcdef"


def _sentinel(root: Path, vault_id: str) -> None:
    (root / ".chrono-vault").write_text(
        json.dumps({"vault_id": vault_id, "schema_version": 1}),
        encoding="utf-8",
    )


def _context(aperture: str, *, mode: str = "project", focus: str | None = None) -> str:
    return json.dumps(
        {
            "schema": "chrono-vault-context/v1",
            "task_id": TASK_ID,
            "attempt_id": ATTEMPT_ID,
            "generation": 1,
            "mode": mode,
            "aperture": aperture,
            "focus": focus,
            "engagement_start": "2026-08-11T12:00:00Z",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class AuditTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="chrono-audit-root-")))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _sentinel(self.root, "audit-test")
        self.audit_dir = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-audit-trail-"))
        )
        self.addCleanup(shutil.rmtree, self.audit_dir, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _env(self, *, root: Path | None, audit_dir: Path, aperture: str | None):
        values = {"CHRONO_VAULT_AUDIT_DIR": str(audit_dir)}
        if root is not None:
            values["CHRONO_VAULT_ROOT"] = str(root)
        if aperture is not None:
            values["CHRONO_VAULT_CONTEXT"] = _context(aperture)
        return mock.patch.dict(os.environ, values, clear=True)

    def _events(self, audit_dir: Path, operation: str) -> list[dict]:
        directory = audit_dir / operation
        if not directory.exists():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("evt-*.json"))
        ]

    def _record(self, *, root: Path, audit_dir: Path, aperture: str, **fields) -> dict:
        payload = {
            "title": fields.pop("title", "alpha finding"),
            "body": fields.pop("body", "alpha body detail\n"),
            "target": fields.pop("target", "example-chain"),
            "attack_class": fields.pop("attack_class", "forged-inbound"),
        }
        payload.update(fields)
        with self._env(root=root, audit_dir=audit_dir, aperture=aperture):
            return notes.record("finding", payload)

    # -- headline: four distinguishable states ---------------------------
    def test_no_match_empty_store_broken_root_and_never_ran_are_distinct(self) -> None:
        # (a) matched nothing: a populated, readable store, query hits nothing.
        a_dir = self.audit_dir / "a"
        self._record(root=self.root, audit_dir=a_dir, aperture="rich")
        with self._env(root=self.root, audit_dir=a_dir, aperture="rich"):
            vault_recall.recall("zqxjnonexistenttoken")
        a_events = self._events(a_dir, "recall")
        self.assertEqual(len(a_events), 1)
        self.assertEqual(a_events[0]["result"], audit.NO_MATCH)
        self.assertEqual(a_events[0]["returned_note_ids"], [])

        # (c1) empty store: a valid root with a sentinel but no index built yet.
        empty_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-audit-empty-"))
        )
        self.addCleanup(shutil.rmtree, empty_root, ignore_errors=True)
        _sentinel(empty_root, "empty-store")
        c1_dir = self.audit_dir / "c1"
        with self._env(root=empty_root, audit_dir=c1_dir, aperture="rich"):
            vault_recall.recall("anything at all")
        c1_events = self._events(c1_dir, "recall")
        self.assertEqual(len(c1_events), 1)
        self.assertEqual(c1_events[0]["result"], audit.EMPTY_STORE)

        # (c2) broken root: CHRONO_VAULT_ROOT unset. recall raises (unchanged),
        # but the event still lands because the audit dir is resolved
        # independently of the vault root.
        c2_dir = self.audit_dir / "c2"
        with self._env(root=None, audit_dir=c2_dir, aperture=None):
            with self.assertRaises(Exception):
                vault_recall.recall("anything at all")
        c2_events = self._events(c2_dir, "recall")
        self.assertEqual(len(c2_events), 1)
        self.assertEqual(c2_events[0]["result"], audit.UNAVAILABLE)

        # (b) never ran: an audit dir into which recall was never called.
        never_dir = self.audit_dir / "b"
        self.assertEqual(self._events(never_dir, "recall"), [])

        # The three present results and the absent one are mutually distinct.
        present = {
            a_events[0]["result"],
            c1_events[0]["result"],
            c2_events[0]["result"],
        }
        self.assertEqual(present, {audit.NO_MATCH, audit.EMPTY_STORE, audit.UNAVAILABLE})

    def test_broken_root_raises_but_event_is_written(self) -> None:
        # Pin the exact behaviour the headline relies on: an unset root raises
        # (unchanged) yet still produces an `unavailable` event, so case (c) can
        # never collapse into "never ran".
        broken_dir = self.audit_dir / "broken"
        with self._env(root=None, audit_dir=broken_dir, aperture=None):
            with self.assertRaises(Exception):
                vault_recall.recall("probe")
        events = self._events(broken_dir, "recall")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["result"], audit.UNAVAILABLE)
        self.assertEqual(events[0]["returned_note_ids"], [])

    # -- five required fields --------------------------------------------
    def test_recall_event_has_the_five_ledger_fields(self) -> None:
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="rich"):
            self._record_inline()
            response = vault_recall.recall("MsgExecutePayload")
        events = self._events(self.audit_dir, "recall")
        self.assertEqual(len(events), 1)
        event = events[0]
        for field in audit.REQUIRED_FIELDS:
            self.assertIn(field, event)
        self.assertEqual(event["result"], audit.MATCHED)
        self.assertEqual(event["applied_policy"], "rich")
        self.assertEqual(event["engagement"]["task_id"], TASK_ID)
        self.assertTrue(event["request_hash"].startswith("sha256:"))
        # returned note ids and the recall_id correlate the event to the caller.
        self.assertEqual(
            event["returned_note_ids"],
            [row["id"] for row in response["results"]],
        )
        self.assertEqual(event["recall_id"], response["recall_id"])

    def _record_inline(self) -> dict:
        return notes.record(
            "finding",
            {
                "title": "MsgExecutePayload forged inbound",
                "body": "The message type reaches the privileged executor.\n",
                "target": "example-chain",
                "attack_class": "forged-inbound",
            },
        )

    def test_record_event_has_the_five_fields_and_new_note_id(self) -> None:
        result = self._record(root=self.root, audit_dir=self.audit_dir, aperture="rich")
        events = self._events(self.audit_dir, "record")
        self.assertEqual(len(events), 1)
        event = events[0]
        for field in audit.REQUIRED_FIELDS:
            self.assertIn(field, event)
        self.assertEqual(event["result"], audit.RECORDED)
        self.assertEqual(event["returned_note_ids"], [result["id"]])
        self.assertEqual(event["applied_policy"], "rich")
        self.assertEqual(event["engagement"]["task_id"], TASK_ID)
        self.assertTrue(event["request_hash"].startswith("sha256:"))

    # -- applied policy is the real aperture vocabulary ------------------
    def test_denied_record_and_recall_report_the_aperture(self) -> None:
        # cold: record allowed, recall denied. Both events carry aperture "cold".
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="cold"):
            notes.record(
                "finding",
                {
                    "title": "cold aperture note",
                    "body": "written under cold\n",
                    "target": "example-chain",
                    "attack_class": "forged-inbound",
                },
            )
            with self.assertRaises(Exception):
                vault_recall.recall("cold")
        record_events = self._events(self.audit_dir, "record")
        recall_events = self._events(self.audit_dir, "recall")
        self.assertEqual(len(record_events), 1)
        self.assertEqual(record_events[0]["result"], audit.RECORDED)
        self.assertEqual(record_events[0]["applied_policy"], "cold")
        self.assertEqual(len(recall_events), 1)
        self.assertEqual(recall_events[0]["result"], audit.DENIED)
        self.assertEqual(recall_events[0]["applied_policy"], "cold")
        self.assertEqual(recall_events[0]["returned_note_ids"], [])

    def test_unbound_process_reports_unbound_policy(self) -> None:
        self._record(root=self.root, audit_dir=self.audit_dir, aperture=None)
        events = self._events(self.audit_dir, "record")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["applied_policy"], audit.UNBOUND)
        self.assertIsNone(events[0]["engagement"])

    # -- never store note content ----------------------------------------
    def test_events_never_contain_note_content(self) -> None:
        secret_title = "UNIQUE_TITLE_TOKEN_zzq"
        secret_body = "SUPER_SECRET_BODY_VALUE_7f3a9"
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="rich"):
            notes.record(
                "finding",
                {
                    "title": f"{secret_title} forged inbound",
                    "body": f"{secret_body} reaches the executor.\n",
                    "target": "example-chain",
                    "attack_class": "forged-inbound",
                },
            )
            vault_recall.recall(secret_title)
        raw = "\n".join(
            path.read_text(encoding="utf-8")
            for operation in ("record", "recall")
            for path in (self.audit_dir / operation).glob("evt-*.json")
        )
        self.assertNotIn(secret_body, raw)
        self.assertNotIn(secret_title, raw)
        # ...but the trail is not empty: ids and a hash were still recorded.
        self.assertIn("sha256:", raw)

    # -- half-wired index surfaces as a distinct result ------------------
    def test_recorded_unindexed_when_index_update_fails(self) -> None:
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="rich"):
            with mock.patch.object(
                vault_index, "upsert", side_effect=RuntimeError("boom")
            ):
                result = notes.record(
                    "finding",
                    {
                        "title": "unindexed finding",
                        "body": "note lands, index does not\n",
                        "target": "example-chain",
                        "attack_class": "forged-inbound",
                    },
                )
        self.assertTrue(result["index_dirty"])
        events = self._events(self.audit_dir, "record")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["result"], audit.RECORDED_UNINDEXED)
        self.assertEqual(events[0]["returned_note_ids"], [result["id"]])

    # -- auditing never gates the operation ------------------------------
    def test_audit_write_failure_does_not_break_recall(self) -> None:
        self._record(root=self.root, audit_dir=self.audit_dir, aperture="rich")
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="rich"):
            with mock.patch.object(
                audit, "_write_event", side_effect=OSError("disk full")
            ):
                # recall must still return normally even though the event failed.
                response = vault_recall.recall("alpha")
        self.assertIn("results", response)
        self.assertNotIn("_audit_result", response)

    def test_audit_result_marker_never_leaks_to_callers(self) -> None:
        with self._env(root=self.root, audit_dir=self.audit_dir, aperture="rich"):
            self._record_inline()
            matched = vault_recall.recall("MsgExecutePayload")
            missed = vault_recall.recall("zqxjnonexistenttoken")
        self.assertNotIn("_audit_result", matched)
        self.assertNotIn("_audit_result", missed)


if __name__ == "__main__":
    unittest.main()
