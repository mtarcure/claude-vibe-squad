from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import uuid
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


fake_mcp = types.ModuleType("mcp")
fake_mcp_server = types.ModuleType("mcp.server")
fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
fake_fastmcp.FastMCP = _FakeFastMCP
sys.modules.setdefault("mcp", fake_mcp)
sys.modules.setdefault("mcp.server", fake_mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", fake_fastmcp)

import clearance  # noqa: E402
import lifecycle  # noqa: E402
import mcp_server  # noqa: E402
import notes  # noqa: E402
import recall as vault_recall  # noqa: E402


class MemoryApertureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="chrono-aperture-")))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".chrono-vault").write_text(
            json.dumps({"vault_id": "aperture-test", "schema_version": 1}),
            encoding="utf-8",
        )
        self.environment = mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.root),
                "CHRONO_VAULT_CLEARANCE": "restricted",
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Separate from the vault root: demoting outcomes flag the curation
        # queue under a repo root, and this keeps that write out of the real
        # checkout's `_state/curation-queue.jsonl`.
        self.repo_root = Path(
            os.path.realpath(tempfile.mkdtemp(prefix="chrono-aperture-repo-"))
        )
        self.addCleanup(shutil.rmtree, self.repo_root, ignore_errors=True)

    def _context(
        self,
        aperture: str,
        *,
        mode: str = "project",
        focus: str | None = None,
        start: str = "2026-08-08T12:00:00Z",
    ) -> str:
        return json.dumps(
            {
                "schema": "chrono-vault-context/v1",
                "task_id": "TASK-2026-08-08-1200-aperture",
                "attempt_id": "d-0123456789abcdef0123456789abcdef",
                "generation": 1,
                "mode": mode,
                "aperture": aperture,
                "focus": focus,
                "engagement_start": start,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _record_unbound(
        self,
        token: str,
        *,
        note_type: str = "finding",
        target: str = "alpha",
        status: str = "verified",
        created_at: str = "2026-08-08T10:00:00Z",
    ) -> dict:
        with mock.patch.dict(
            os.environ,
            {
                "CHRONO_VAULT_ROOT": str(self.root),
                "CHRONO_VAULT_CLEARANCE": "restricted",
            },
            clear=True,
        ):
            return notes.record(
                note_type,
                {
                    "title": f"{token} aperture fixture",
                    "body": f"{token} body",
                    "target": target,
                    "attack_class": "memory-policy",
                    "status": status,
                    "sensitivity": "restricted",
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )

    def test_canonical_policy_and_context_are_closed(self) -> None:
        self.assertEqual(
            set(clearance.memory_policies()),
            {"rich", "focused", "default", "cold", "pool_blind", "none"},
        )
        with mock.patch.dict(
            os.environ,
            {clearance.CONTEXT_ENV: self._context("cold")},
        ):
            self.assertEqual(clearance.memory_context()["policy"]["policy_id"], "memory.cold.v1")
        malformed = json.loads(self._context("cold"))
        malformed["aperture"] = "wide-open"
        with mock.patch.dict(
            os.environ,
            {clearance.CONTEXT_ENV: json.dumps(malformed)},
        ):
            with self.assertRaises(clearance.ClearanceError):
                clearance.memory_context()

        bad_policy = self.root / "memory-apertures.tsv"
        bad_policy.write_text(
            clearance.POLICY_PATH.read_text(encoding="utf-8").replace(
                "memory.cold.v1\tcold\tdeny\tallow\tdeny\tdeny\t-\t-\tnone\tnone\tnone\tcandidate\tinternal\trestricted",
                "memory.cold.v1\tcold\tdeny\tallow\tdeny\tdeny\t-\t-\tnone\tnone\tnone\tcandidate\tinternal\twide-open",
            ),
            encoding="utf-8",
        )
        clearance.memory_policies.cache_clear()
        self.addCleanup(clearance.memory_policies.cache_clear)
        with mock.patch.object(clearance, "POLICY_PATH", bad_policy):
            with self.assertRaises(clearance.ClearanceError):
                clearance.memory_policies()

        context = json.loads(self._context("cold"))
        with self.assertRaises(clearance.ClearanceError):
            clearance.validate_memory_context(
                context,
                task_id="TASK-2026-08-08-1201-other",
            )

    def _policy_bytes(
        self,
        *changes: tuple[str, str, str],
    ) -> bytes:
        raw = clearance.POLICY_PATH.read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
        for aperture, field, value in changes:
            row = next(item for item in rows if item["aperture"] == aperture)
            row[field] = value
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=clearance.POLICY_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def _load_rehashed_policy(self, encoded: bytes) -> dict[str, dict[str, str]]:
        policy_path = self.root / "memory-apertures-mutated.tsv"
        policy_path.write_bytes(encoded)
        clearance.memory_policies.cache_clear()
        try:
            with mock.patch.object(clearance, "POLICY_PATH", policy_path), mock.patch.object(
                clearance,
                "POLICY_SHA256",
                hashlib.sha256(encoded).hexdigest(),
            ):
                return clearance.memory_policies()
        finally:
            clearance.memory_policies.cache_clear()

    def test_policy_schema_domains_and_safety_invariants_fail_closed(self) -> None:
        invalid_changes = (
            ("identity", (("pool_blind", "policy_id", "memory.cold.v1"),)),
            ("bounded-token", (("rich", "policy_id", "x" * 129),)),
            ("operation-domain", (("rich", "browse", "sometimes"),)),
            ("status-token", (("rich", "statuses", "candidate|unknown"),)),
            ("type-token", (("rich", "note_types", "finding|unknown"),)),
            ("sensitivity-token", (("rich", "project_write_floor", "secret"),)),
            ("unsorted-set", (("rich", "statuses", "verified|candidate"),)),
            ("duplicate-set", (("rich", "note_types", "finding|finding"),)),
            ("denied-read", (("cold", "statuses", "verified"),)),
            ("denied-record", (("none", "project_write_floor", "internal"),)),
            ("focused-target", (("focused", "focus", "any"),)),
            ("focused-cutoff", (("focused", "written_before", "none"),)),
        )
        for label, changes in invalid_changes:
            with self.subTest(label=label), self.assertRaises(clearance.ClearanceError):
                self._load_rehashed_policy(self._policy_bytes(*changes))

        lines = clearance.POLICY_PATH.read_text(encoding="utf-8").splitlines()
        lines[1] += "\textra-cell"
        overwide = ("\n".join(lines) + "\n").encode("utf-8")
        with self.assertRaises(clearance.ClearanceError):
            self._load_rehashed_policy(overwide)

    def test_rehashed_safe_policy_change_is_not_locked_to_current_decisions(self) -> None:
        policies = self._load_rehashed_policy(
            self._policy_bytes(("rich", "browse", "deny"))
        )
        self.assertEqual(policies["rich"]["browse"], "deny")
        self.assertEqual(
            set(policies), {"rich", "focused", "default", "cold", "pool_blind", "none"}
        )

    def test_cold_pool_blind_and_none_fail_before_vault_io(self) -> None:
        for aperture in ("cold", "pool_blind"):
            with self.subTest(aperture=aperture), mock.patch.dict(
                os.environ,
                {clearance.CONTEXT_ENV: self._context(aperture)},
            ):
                with self.assertRaises(clearance.ClearanceError):
                    vault_recall.recall("forbidden")
                with self.assertRaises(clearance.ClearanceError):
                    mcp_server.recall("forbidden")
                with self.assertRaises(clearance.ClearanceError):
                    mcp_server._kg_alias_recall("forbidden")
                with self.assertRaises(clearance.ClearanceError):
                    lifecycle.get_note("mem-000000000000")

        none_context = self._context("none")
        with mock.patch.dict(
            os.environ,
            {clearance.CONTEXT_ENV: none_context},
            clear=True,
        ):
            with self.assertRaises(clearance.ClearanceError):
                notes.record(
                    "learning",
                    {"title": "denied", "body": "must not touch disk"},
                )
            with self.assertRaises(clearance.ClearanceError):
                mcp_server.record(
                    "learning",
                    {"title": "denied", "body": "must not touch disk"},
                )
            with self.assertRaises(clearance.ClearanceError):
                mcp_server._kg_alias_record_attempt("role", "target", "class")

    def test_bound_record_is_candidate_task_scoped_and_bounty_restricted(self) -> None:
        context = self._context("cold", mode="bounty")
        with mock.patch.dict(os.environ, {clearance.CONTEXT_ENV: context}):
            with self.assertRaises(clearance.ClearanceError):
                notes.record(
                    "learning",
                    {"title": "bad", "body": "bad", "status": "verified"},
                )
            result = notes.record(
                "learning",
                {
                    "title": "bounded",
                    "body": "bounded memory",
                    "created_at": "2000-01-01T00:00:00Z",
                    "updated_at": "2000-01-01T00:00:00Z",
                },
            )
        stored = lifecycle.get_note(result["id"])
        self.assertEqual(stored["status"], "candidate")
        self.assertEqual(stored["sensitivity"], "restricted")
        self.assertEqual(stored["source_task"], "TASK-2026-08-08-1200-aperture")
        self.assertNotEqual(stored["created_at"], "2000-01-01T00:00:00Z")
        self.assertEqual(stored["created_at"], stored["updated_at"])

    def test_bound_usage_feedback_owns_source_task(self) -> None:
        visible = self._record_unbound("UsageToken", target="alpha")
        context = self._context("rich")
        with mock.patch.dict(os.environ, {clearance.CONTEXT_ENV: context}):
            recalled = vault_recall.recall("UsageToken")
            self.assertEqual(recalled["results"][0]["id"], visible["id"])
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.record_usage(
                    recalled["recall_id"],
                    visible["id"],
                    "used",
                    source_task="TASK-2026-08-08-1201-unrelated",
                )
            result = lifecycle.record_usage(
                recalled["recall_id"], visible["id"], "used"
            )
        self.assertEqual(
            result["source_task"], "TASK-2026-08-08-1200-aperture"
        )

    def test_focused_recall_uses_created_at_and_cannot_be_widened(self) -> None:
        visible = self._record_unbound("FocusToken", target="alpha")
        candidate = self._record_unbound(
            "FocusToken", target="alpha", status="candidate"
        )
        attempt = self._record_unbound(
            "FocusToken", target="alpha", note_type="attempt"
        )
        other = self._record_unbound("FocusToken", target="beta")
        late = self._record_unbound(
            "FocusToken",
            target="alpha",
            created_at="2026-08-08T13:00:00Z",
        )
        os.utime(visible["path"], (2_000_000_000, 2_000_000_000))
        context = self._context("focused", focus="alpha")
        with mock.patch.dict(os.environ, {clearance.CONTEXT_ENV: context}):
            result = vault_recall.recall("FocusToken")
            self.assertEqual([row["id"] for row in result["results"]], [visible["id"]])
            for filters in (
                {"target": "beta"},
                {"status": "candidate"},
                {"type": "attempt"},
                {"written_before": "2027-01-01T00:00:00Z", "target": "beta"},
            ):
                self.assertEqual(
                    vault_recall.recall("FocusToken", filters=filters)["results"],
                    [],
                )
            self.assertEqual(lifecycle.get_note(visible["id"])["id"], visible["id"])
            for denied in (candidate, attempt, other, late):
                with self.assertRaises(clearance.ClearanceError):
                    lifecycle.get_note(denied["id"])
            with self.assertRaises(clearance.ClearanceError):
                lifecycle.set_status(visible["id"], "archived", "lane", 1)

    def test_usage_feedback_is_independent_of_the_read_aperture(self) -> None:
        """`record_usage` is a write, and must not inherit `recall`'s denial.

        Until 2026-08-17 it required `recall` permission, which `cold` denies —
        and 2,665 of 2,669 dispatches ran `cold`. So usage telemetry was
        structurally unrecordable for almost every task, while `record` stayed
        allowed, which is why note-writing never broke and the silence went
        unnoticed for 23 days.

        Operator decision 2026-08-17: decouple. Reporting that a note was
        unhelpful discloses nothing — the caller already holds the note id and
        already saw the note it is reporting on, so permitting the outcome write
        reveals no memory it did not have.

        Both halves are asserted in one test because the point is precisely that
        the two permissions are now independent: the write lands, and the read
        stays shut.
        """
        note = self._record_unbound("ColdUsageToken", target="alpha")
        recall_id = str(uuid.uuid4())
        with mock.patch.dict(
            os.environ, {clearance.CONTEXT_ENV: self._context("cold")}
        ):
            # The read half is unchanged and must stay denied.
            with self.assertRaises(clearance.ClearanceError):
                vault_recall.recall("ColdUsageToken")
            with self.assertRaises(clearance.ClearanceError):
                lifecycle.get_note(note["id"])
            # The write half now lands.
            result = lifecycle.record_usage(
                recall_id, note["id"], "not_useful", repo_root=self.repo_root
            )
        self.assertEqual(result["recall_id"], recall_id)
        self.assertEqual(result["note_id"], note["id"])
        self.assertEqual(result["outcome"], "not_useful")
        # The engagement still owns source_task, exactly as it does for `record`.
        self.assertEqual(result["source_task"], "TASK-2026-08-08-1200-aperture")

        connection = sqlite3.connect(self.root / "index" / "kg.db")
        try:
            rows = connection.execute(
                "SELECT recall_id, note_id, outcome, source_task FROM usage"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            rows,
            [(recall_id, note["id"], "not_useful", "TASK-2026-08-08-1200-aperture")],
        )

    def test_usage_feedback_still_denied_where_the_vault_may_not_be_written(
        self,
    ) -> None:
        """Decoupling from `recall` must not decouple it from `record`.

        `none` is the aperture that denies every memory tool and is handed no
        vault path at all; a usage row is still a write, so it stays denied there.
        Lane clearance also still applies: a note above the lane's clearance is
        one the caller could never have been shown, so feedback on it is a claim
        about a note it does not hold.
        """
        note = self._record_unbound("NoneUsageToken", target="alpha")
        recall_id = str(uuid.uuid4())
        # Each assertion names the gate it expects. Without that these would pass
        # for the wrong reason — every denial here raises the same class, so a
        # regression that re-coupled the read aperture would look identical.
        with mock.patch.dict(
            os.environ, {clearance.CONTEXT_ENV: self._context("none")}
        ):
            with self.assertRaises(clearance.ClearanceError) as denied:
                lifecycle.record_usage(recall_id, note["id"], "used")
        self.assertEqual(
            str(denied.exception), "memory record is denied by aperture none"
        )

        with mock.patch.dict(
            os.environ,
            {
                clearance.CONTEXT_ENV: self._context("cold"),
                "CHRONO_VAULT_CLEARANCE": "internal",
            },
        ):
            with self.assertRaises(clearance.ClearanceError) as denied:
                lifecycle.record_usage(recall_id, note["id"], "used")
        self.assertEqual(
            str(denied.exception), "memory note exceeds lane clearance"
        )

    def test_default_aperture_admits_candidate_and_all_three_types(self) -> None:
        policy = clearance.memory_policies()["default"]
        self.assertEqual(set(policy["statuses"].split("|")), {"candidate", "verified"})
        self.assertEqual(
            set(policy["note_types"].split("|")), {"attempt", "finding", "learning"}
        )

    def test_existing_apertures_are_unchanged_by_the_new_row(self) -> None:
        policies = clearance.memory_policies()
        self.assertEqual(policies["focused"]["statuses"], "verified")
        self.assertEqual(policies["rich"]["statuses"], "candidate|verified")
        self.assertEqual(policies["cold"]["statuses"], "-")

    def test_browse_denial_precedes_credentials_and_network(self) -> None:
        context = self._context("cold")
        with mock.patch.dict(os.environ, {clearance.CONTEXT_ENV: context}), mock.patch.object(
            mcp_server,
            "_obsidian_headers",
            side_effect=AssertionError("credential path must not be reached"),
        ):
            with self.assertRaises(clearance.ClearanceError):
                mcp_server.vault_list()
            with self.assertRaises(clearance.ClearanceError):
                mcp_server._obsidian_alias_vault_list()


if __name__ == "__main__":
    unittest.main()
