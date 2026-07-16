"""Wave-2 dispatcher + reconciler security/correctness fixes.

FIX 1 — send-task.sh rejects a path-traversal task id before any write.
FIX 2 — the reconciler treats a corrupt registry as a hard error: it refuses to
        write (never erasing in-flight tasks) and preserves a diagnostic copy.
FIX 3 — one canonical settleable-status set: unknown/empty/typo statuses keep the
        task open (fail closed); a sanctioned alias canonicalizes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[3]  # scripts/python/tests -> repo root
RECONCILER = REPO / "scripts" / "python" / "registry_reconciler.py"
SEND_TASK = REPO / "bin" / "send-task.sh"
OUTBOX_WATCHER = REPO / "bin" / "outbox-watcher.sh"

RUNTIME_MAP = "\t".join(["specialist", "c2", "c3", "c4", "c5", "c6", "primary_lane"]) + "\n"
RUNTIME_MAP += "\t".join(["claude-spec", "x", "x", "x", "x", "x", "claude"]) + "\n"


def envelope(fm: dict, body: str = "done.") -> str:
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in fm.items()) + "\n---\n\n" + body + "\n"


class Fix1TaskIdTraversal(unittest.TestCase):
    """FIX 1: a crafted task id cannot redirect the inbox write."""

    def _run(self, task_id: str) -> subprocess.CompletedProcess:
        # The id allowlist fires early (before any map lookup or file write), so
        # running against the real repo is a safe, side-effect-free early die.
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(envelope({
                "id": task_id, "to_model": "claude", "specialist": "claude-spec",
                "source_namespace": "coding", "parallel_safe": "true",
                "direct_lane_work_allowed": "true",
            }, "body"))
            path = fh.name
        try:
            return subprocess.run([str(SEND_TASK), path, "--dry-run"],
                                  capture_output=True, text=True, timeout=60)
        finally:
            os.unlink(path)

    def test_traversal_ids_rejected(self):
        for bad in ("../../../tmp/evil", "TASK-2026-07-16-0055-a/b",
                    "TASK-2026-07-16-0055-../x", "TASK-2026-07-16-0055-a.b",
                    "TASK-2026-07-16-0055- space"):
            r = self._run(bad)
            self.assertNotEqual(r.returncode, 0, msg=f"{bad!r} should be rejected")
            self.assertIn("invalid task id", (r.stdout + r.stderr).lower(), msg=f"{bad!r}")

    def test_valid_id_passes_id_gate(self):
        r = self._run("TASK-2026-07-16-0055-wave2sec")
        # A valid id must NOT trip the id allowlist (it may still exit later for
        # unrelated reasons — we only assert the id gate did not reject it).
        self.assertNotIn("invalid task id", (r.stdout + r.stderr).lower())


class ReconcilerFixture:
    def fixture(self, registry_bytes: bytes | None, responses: dict | None = None):
        root = Path(tempfile.mkdtemp(prefix="wave2-"))
        (root / "shared").mkdir(parents=True)
        (root / "shared" / "specialist-runtime-map.tsv").write_text(RUNTIME_MAP, encoding="utf-8")
        state = root / "_state"
        state.mkdir(parents=True)
        if registry_bytes is not None:
            (state / "active-tasks.json").write_bytes(registry_bytes)
        for rel, content in (responses or {}).items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        env = {
            **os.environ, "VAULT_ROOT": str(root), "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux", "SQUAD_SESSION": "none", "PYTHONDONTWRITEBYTECODE": "1",
        }
        return root, state, env

    def reconcile(self, env, task_id="TASK-2026-07-16-0000-probe"):
        return subprocess.run([sys.executable, str(RECONCILER), "--task-id", task_id],
                              env=env, capture_output=True, text=True, timeout=60)

    def register(self, env, task_id, entry_json):
        return subprocess.run([sys.executable, str(RECONCILER),
                               "--register-task", task_id, "--entry-json", entry_json],
                              env=env, capture_output=True, text=True, timeout=60)


class Fix2CorruptRegistry(ReconcilerFixture, unittest.TestCase):
    """FIX 2: corrupt registry is a hard error; never silently reset to empty."""

    def test_malformed_json_is_hard_error_and_preserved(self):
        corrupt = b'{ this is not valid json '
        root, state, env = self.fixture(corrupt)
        r = self.reconcile(env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not valid JSON", r.stderr)
        # original file untouched; diagnostic copy preserved
        self.assertEqual((state / "active-tasks.json").read_bytes(), corrupt)
        self.assertTrue(list(state.glob("active-tasks.json.corrupt.*")))

    def test_non_object_json_is_hard_error(self):
        root, state, env = self.fixture(b'[1, 2, 3]')
        r = self.reconcile(env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a JSON object", r.stderr)
        self.assertEqual((state / "active-tasks.json").read_bytes(), b'[1, 2, 3]')

    def test_register_on_corrupt_registry_does_not_erase(self):
        # THE data-loss scenario: a dispatch registration must NOT replace a
        # corrupt (but recoverable) registry with a one-entry registry.
        corrupt = b'{"in-flight-task": broken'
        root, state, env = self.fixture(corrupt)
        r = self.register(env, "TASK-2026-07-16-0001-new", "{}")
        self.assertEqual(r.returncode, 2)
        self.assertEqual((state / "active-tasks.json").read_bytes(), corrupt)  # not erased
        self.assertTrue(list(state.glob("active-tasks.json.corrupt.*")))

    def test_absent_registry_is_legitimate_empty(self):
        root, state, env = self.fixture(None)  # no file at all
        r = self.reconcile(env)
        self.assertEqual(r.returncode, 0)


class Fix3CanonicalStatus(ReconcilerFixture, unittest.TestCase):
    """FIX 3: only canonical statuses settle; unknown/empty keep the task open."""

    def _entry(self):
        # non-mandatory so it settles to its own response status (no cross-family hold)
        return {"compatibility_namespace": "coding", "specialist": "claude-spec",
                "to_model": "claude", "source_namespace": "coding",
                "review_model": "none", "mandatory_review": "false", "status": "in-flight"}

    def _settle_to(self, response_status: str) -> str:
        t = "TASK-2026-07-16-0002-status"
        resp = {f"departments/coding/outbox/{t}-response.md": envelope({
            "id": f"{t}-response", "in_response_to": t, "from": "claude",
            "to": "chrono", "type": "RESULT", "status": response_status,
        })}
        root, state, env = self.fixture(json.dumps({t: self._entry()}).encode(), resp)
        self.reconcile(env, t)
        return json.loads((state / "active-tasks.json").read_text())[t]["status"]

    def test_typo_status_keeps_task_open(self):
        self.assertEqual(self._settle_to("compelted"), "in-flight")

    def test_empty_status_keeps_task_open(self):
        self.assertEqual(self._settle_to(""), "in-flight")

    def test_canonical_statuses_settle(self):
        self.assertEqual(self._settle_to("complete"), "complete")
        self.assertEqual(self._settle_to("needs_review"), "needs_review")
        self.assertEqual(self._settle_to("blocked"), "blocked")

    def test_sanctioned_alias_canonicalizes(self):
        self.assertEqual(self._settle_to("completed"), "complete")


# ── codex BLOCK re-review regressions (wave2fix1) ──────────────────────────────


class Block1SymlinkedInbox(unittest.TestCase):
    """BLOCK1: a pre-existing inbox symlink pointing OUTSIDE the vault must be
    rejected — comparing dest-parent to the (attacker-controlled) inbox is not
    enough because both resolve through the same symlink."""

    def test_symlinked_inbox_is_rejected_and_nothing_escapes(self):
        root = Path(tempfile.mkdtemp(prefix="wave2-b1-"))
        try:
            outside = root / "outside"
            outside.mkdir()
            vault = root / "vault"
            vault.mkdir()
            for name in ("bin", "shared", "scripts", "model-lanes"):
                (vault / name).symlink_to(REPO / name)
            (vault / "_state").mkdir()
            dept = vault / "departments" / "coding"
            dept.mkdir(parents=True)
            for sub in ("active", "outbox", "archive", "specialists"):
                (dept / sub).mkdir()
            # the specialist-existence gate reads departments/*/specialists/<name>.md
            (dept / "specialists" / "code-reviewer.md").write_text(
                "---\nname: code-reviewer\n---\nstub\n", encoding="utf-8")
            # THE attack: inbox is a symlink to a directory outside the vault
            (dept / "inbox").symlink_to(outside)

            task_id = "TASK-2026-07-16-0245-b1probe"
            pkt = root / f"{task_id}.md"
            # specialist: none (direct-lane) skips the specialist/adapter/safety gauntlet
            # so the test targets the containment check itself, not incidental validation.
            pkt.write_text(envelope({
                "id": task_id, "to_model": "claude", "specialist": "none",
                "source_namespace": "coding", "compatibility_namespace": "coding",
                "parallel_safe": "true", "direct_lane_work_allowed": "true",
                "write_scope": "[]",
                "return_artifact": f"{dept}/outbox/{task_id}-response.md",
            }, "body"), encoding="utf-8")

            env = {**os.environ, "VAULT_ROOT": str(vault), "SKIP_NUDGE": "1",
                   "FAILOVER_CONTROL_ENABLED": "0"}
            r = subprocess.run([str(SEND_TASK), str(pkt)], env=env,
                               capture_output=True, text=True, timeout=120)
            out = r.stdout + r.stderr
            self.assertNotEqual(r.returncode, 0, msg=out)
            self.assertRegex(out, r"expected physical directory|symlinked mailbox")
            # security property: nothing was written into the outside target
            self.assertEqual(list(outside.iterdir()), [], msg=f"escaped: {out}")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_legitimate_real_inbox_still_dispatches(self):
        # guard: the containment fix must NOT reject a normal (real-dir) inbox, even
        # when VAULT_ROOT lives under a symlinked prefix like macOS /tmp->/private/tmp.
        root = Path(tempfile.mkdtemp(prefix="wave2-b1ok-"))
        try:
            vault = root / "vault"
            vault.mkdir()
            for name in ("bin", "shared", "scripts", "model-lanes"):
                (vault / name).symlink_to(REPO / name)
            (vault / "_state").mkdir()
            dept = vault / "departments" / "coding"
            for sub in ("inbox", "active", "outbox", "archive"):
                (dept / sub).mkdir(parents=True)
            task_id = "TASK-2026-07-16-0245-b1okprobe"
            pkt = root / f"{task_id}.md"
            pkt.write_text(envelope({
                "id": task_id, "to_model": "claude", "specialist": "none",
                "source_namespace": "coding", "compatibility_namespace": "coding",
                "parallel_safe": "true", "direct_lane_work_allowed": "true",
                "write_scope": "[]",
                "return_artifact": f"{dept}/outbox/{task_id}-response.md",
            }, "body"), encoding="utf-8")
            env = {**os.environ, "VAULT_ROOT": str(vault), "SKIP_NUDGE": "1",
                   "FAILOVER_CONTROL_ENABLED": "0"}
            r = subprocess.run([str(SEND_TASK), str(pkt)], env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertTrue((dept / "inbox" / f"{task_id}.md").is_file())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_compatibility_namespace_traversal_rejected_before_mailbox_write(self):
        root = Path(tempfile.mkdtemp(prefix="wave2-b1compat-"))
        try:
            vault = root / "vault"
            vault.mkdir()
            task_id = "TASK-2026-07-16-0330-compatprobe"
            pkt = root / f"{task_id}.md"
            pkt.write_text(envelope({
                "id": task_id, "to_model": "none", "specialist": "none",
                "source_namespace": "shared",
                "compatibility_namespace": "../../escaped-compat",
                "parallel_safe": "true", "direct_lane_work_allowed": "true",
                "write_scope": "[]",
            }, "body"), encoding="utf-8")

            env = {**os.environ, "VAULT_ROOT": str(vault), "SKIP_NUDGE": "1",
                   "FAILOVER_CONTROL_ENABLED": "0"}
            r = subprocess.run([str(SEND_TASK), str(pkt)], env=env,
                               capture_output=True, text=True, timeout=60)
            out = r.stdout + r.stderr
            self.assertNotEqual(r.returncode, 0, msg=out)
            self.assertIn("invalid compatibility_namespace", out)
            self.assertFalse((root / "escaped-compat").exists(), msg=out)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_static_mailbox_symlink_components_reject_before_external_write(self):
        for component in ("departments", "mailbox", "inbox"):
            with self.subTest(component=component):
                root = Path(tempfile.mkdtemp(prefix=f"wave2-b1-{component}-"))
                try:
                    vault = root / "vault"
                    outside = root / "outside"
                    vault.mkdir()
                    outside.mkdir()
                    if component == "departments":
                        (vault / "departments").symlink_to(outside)
                    elif component == "mailbox":
                        (vault / "departments").mkdir()
                        (vault / "departments" / "coding").symlink_to(outside)
                    else:
                        dept = vault / "departments" / "coding"
                        dept.mkdir(parents=True)
                        (dept / "inbox").symlink_to(outside)

                    task_id = f"TASK-2026-07-16-0330-{component}probe"
                    pkt = root / f"{task_id}.md"
                    pkt.write_text(envelope({
                        "id": task_id, "to_model": "none", "specialist": "none",
                        "source_namespace": "coding", "compatibility_namespace": "coding",
                        "parallel_safe": "true", "direct_lane_work_allowed": "true",
                        "write_scope": "[]",
                    }, "body"), encoding="utf-8")
                    env = {**os.environ, "VAULT_ROOT": str(vault), "SKIP_NUDGE": "1",
                           "FAILOVER_CONTROL_ENABLED": "0"}

                    r = subprocess.run([str(SEND_TASK), str(pkt)], env=env,
                                       capture_output=True, text=True, timeout=60)
                    out = r.stdout + r.stderr
                    self.assertNotEqual(r.returncode, 0, msg=out)
                    self.assertIn("symlinked mailbox path component", out)
                    self.assertEqual(list(outside.iterdir()), [], msg=out)
                finally:
                    shutil.rmtree(root, ignore_errors=True)


class Med5NulTaskId(unittest.TestCase):
    """MED5: a raw NUL in the id frontmatter is stripped by $(...) and would collide
    to a different valid id — it must be rejected on the raw bytes."""

    def test_nul_in_task_id_is_rejected(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as fh:
            fh.write(
                b"---\nid: TASK-2026-07-16-0245-a\x00b\nto_model: claude\n"
                b"specialist: code-reviewer\nsource_namespace: coding\n"
                b"parallel_safe: true\ndirect_lane_work_allowed: true\n---\n\nbody\n"
            )
            path = fh.name
        try:
            r = subprocess.run([str(SEND_TASK), path, "--dry-run"],
                               capture_output=True, text=True, timeout=60)
            out = (r.stdout + r.stderr).lower()
            self.assertNotEqual(r.returncode, 0, msg=out)
            self.assertIn("nul byte", out)
        finally:
            os.unlink(path)


class Med4InvalidUtf8Registry(ReconcilerFixture, unittest.TestCase):
    """MED4: an invalid-UTF-8 registry must fail closed (exit 2) with a byte-for-byte
    diagnostic, not an uncaught UnicodeDecodeError."""

    def test_invalid_utf8_registry_is_hard_error_and_preserved(self):
        corrupt = b'\xff\xfe\xfd not valid utf-8 { "in-flight":'
        root, state, env = self.fixture(corrupt)
        r = self.reconcile(env)
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("not valid UTF-8", r.stderr)
        self.assertEqual((state / "active-tasks.json").read_bytes(), corrupt)  # not erased
        diags = list(state.glob("active-tasks.json.corrupt.*"))
        self.assertTrue(diags)
        self.assertEqual(diags[0].read_bytes(), corrupt)  # byte-for-byte


class Block2InvalidStatusReviewHold(ReconcilerFixture, unittest.TestCase):
    """BLOCK2: an invalid-status response WITH a fresh return artifact must NOT
    settle a mandatory cross-family task to work-done-no-envelope (which bypasses the
    Option-A hold). It must keep the task open and flag the invalid status."""

    def test_invalid_status_with_artifact_keeps_mandatory_task_open(self):
        t = "TASK-2026-07-16-0245-b2probe"
        entry = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "gpt-codex", "mandatory_review": "true",
            "status": "in-flight",
            "dispatched_at": "2020-01-01T00:00:00+00:00",  # long ago -> grace path open
            "return_artifact": "return.md",
        }
        resp = {f"departments/coding/outbox/{t}-response.md": envelope({
            "id": f"{t}-response", "in_response_to": t, "from": "claude",
            "to": "chrono", "type": "RESULT", "status": "compelted"})}  # typo status
        root, state, env = self.fixture(json.dumps({t: entry}).encode(), resp)
        artifact = root / "return.md"
        artifact.write_text("work output\n", encoding="utf-8")
        old = time.time() - 3600  # aged past the no-envelope grace so the OLD code settled
        os.utime(artifact, (old, old))

        r = self.reconcile(env, t)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        final = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(final["status"], "in-flight")          # NOT work-done-no-envelope
        self.assertNotIn("review_required_by", final)           # never settled to review
        self.assertEqual(final.get("invalid_response_status"), "compelted")

    def test_unready_invalid_response_suppresses_backstop_then_stays_open(self):
        t = "TASK-2026-07-16-0330-ageprobe"
        entry = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "gpt-codex", "mandatory_review": "true",
            "status": "in-flight", "dispatched_at": "2020-01-01T00:00:00+00:00",
            "return_artifact": "return.md",
        }
        rel = f"departments/coding/outbox/{t}-response.md"
        root, state, env = self.fixture(json.dumps({t: entry}).encode(), {
            rel: envelope({"id": f"{t}-response", "in_response_to": t,
                           "from": "claude", "to": "chrono", "type": "RESULT",
                           "status": "compelted"}),
        })
        artifact = root / "return.md"
        artifact.write_text("work output\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(artifact, (old, old))
        env.update({"RESPONSE_MIN_AGE_SECONDS": "300", "NO_ENVELOPE_GRACE_SECONDS": "0",
                    "NO_ENVELOPE_MIN_DISPATCH_AGE_SECONDS": "0"})

        first = self.reconcile(env, t)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        first_entry = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(first_entry["status"], "in-flight")
        self.assertNotIn("missing_envelope_artifact", first_entry)
        self.assertNotIn("invalid_response_status", first_entry)  # not parsed until ready

        response = root / rel
        os.utime(response, (old, old))
        second = self.reconcile(env, t)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        final = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(final["status"], "in-flight")
        self.assertEqual(final.get("invalid_response_status"), "compelted")
        self.assertNotIn("review_required_by", final)

    def test_unready_response_reopens_provisional_backstop_state(self):
        t = "TASK-2026-07-16-0330-reopenprobe"
        entry = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "gpt-codex", "mandatory_review": "true",
            "status": "work-done-no-envelope",
            "work_landed_at": "2020-01-01T00:00:00+00:00",
            "missing_envelope_artifact": "return.md",
            "prior_missing_envelope_status": "work-done-no-envelope",
        }
        rel = f"departments/coding/outbox/{t}-response.md"
        root, state, env = self.fixture(json.dumps({t: entry}).encode(), {
            rel: envelope({"id": f"{t}-response", "in_response_to": t,
                           "from": "claude", "to": "chrono", "type": "RESULT",
                           "status": "compelted"}),
        })
        env["RESPONSE_MIN_AGE_SECONDS"] = "300"

        r = self.reconcile(env, t)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        final = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(final["status"], "in-flight")
        self.assertNotIn("work_landed_at", final)
        self.assertNotIn("missing_envelope_artifact", final)
        self.assertNotIn("prior_missing_envelope_status", final)

    def test_genuinely_absent_response_still_reaches_backstop(self):
        t = "TASK-2026-07-16-0330-absentprobe"
        entry = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "none", "mandatory_review": "false",
            "status": "in-flight", "dispatched_at": "2020-01-01T00:00:00+00:00",
            "return_artifact": "return.md",
        }
        root, state, env = self.fixture(json.dumps({t: entry}).encode())
        artifact = root / "return.md"
        artifact.write_text("work output\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(artifact, (old, old))
        env.update({"NO_ENVELOPE_GRACE_SECONDS": "0",
                    "NO_ENVELOPE_MIN_DISPATCH_AGE_SECONDS": "0"})

        r = self.reconcile(env, t)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        final = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(final["status"], "work-done-no-envelope")

    def test_corrected_canonical_response_clears_invalid_status_diagnostic(self):
        t = "TASK-2026-07-16-0330-correctedprobe"
        entry = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "gpt-codex", "mandatory_review": "true",
            "status": "in-flight", "invalid_response_status": "compelted",
        }
        rel = f"departments/coding/outbox/{t}-response.md"
        root, state, env = self.fixture(json.dumps({t: entry}).encode(), {
            rel: envelope({"id": f"{t}-response", "in_response_to": t,
                           "from": "claude", "to": "chrono", "type": "RESULT",
                           "status": "complete"}),
        })

        r = self.reconcile(env, t)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        final = json.loads((state / "active-tasks.json").read_text())[t]
        self.assertEqual(final["status"], "review-required")
        self.assertNotIn("invalid_response_status", final)


class Block3WatcherNoArchive(unittest.TestCase):
    """BLOCK3: the outbox watcher must NOT archive the actionable packet when the
    shared reconciler did not canonically settle (e.g. unknown status)."""

    def _vault(self, root: Path):
        vault = root / "vault"
        (vault / "bin").mkdir(parents=True)
        (vault / "bin" / "outbox-watcher.sh").symlink_to(OUTBOX_WATCHER)
        # a fast reconciler shim: real reconciler logic, no uv startup cost
        shim = vault / "bin" / "registry-reconciler.sh"
        shim.write_text(f'#!/bin/bash\nexec "{sys.executable}" "{RECONCILER}" "$@"\n',
                        encoding="utf-8")
        shim.chmod(0o755)
        for name in ("shared", "scripts"):
            (vault / name).symlink_to(REPO / name)
        (vault / "_state").mkdir()
        # non-coding namespace: the "coding" watcher spawns a `while true` periodic
        # reconciler that would hold the captured stdout pipe open forever.
        dept = vault / "departments" / "security"
        for sub in ("inbox", "active", "outbox", "archive"):
            (dept / sub).mkdir(parents=True)
        return vault, dept

    def test_unknown_status_response_is_not_archived(self):
        root = Path(tempfile.mkdtemp(prefix="wave2-b3-"))
        try:
            vault, dept = self._vault(root)
            t = "TASK-2026-07-16-0245-b3probe"
            entry = {"compatibility_namespace": "security", "specialist": "claude-spec",
                     "to_model": "claude", "source_namespace": "security",
                     "review_model": "none", "mandatory_review": "false",
                     "status": "in-flight"}
            (vault / "_state" / "active-tasks.json").write_text(json.dumps({t: entry}))
            packet = dept / "active" / f"{t}.md"
            packet.write_text(f"---\nid: {t}\n---\nbody\n", encoding="utf-8")
            resp = dept / "outbox" / f"{t}-response.md"
            resp.write_text(envelope({"id": f"{t}-response", "in_response_to": t,
                                      "from": "claude", "to": "chrono", "type": "RESULT",
                                      "status": "compelted"}), encoding="utf-8")  # unknown
            fakebin = root / "fakebin"
            fakebin.mkdir()
            fsw = fakebin / "fswatch"
            fsw.write_text("#!/bin/bash\nprintf '%s\\0' \"$FAKE_FSWATCH_EMIT\"\n",
                           encoding="utf-8")
            fsw.chmod(0o755)
            env = {**os.environ, "VAULT_ROOT": str(vault), "SQUAD_SESSION": "none",
                   "RESPONSE_MIN_AGE_SECONDS": "0", "FAKE_FSWATCH_EMIT": str(resp),
                   "PATH": f"{fakebin}:{os.environ['PATH']}"}
            env.pop("CHRONO_VAULT_ROOT", None)  # autocapture returns immediately
            r = subprocess.run(["bash", str(vault / "bin" / "outbox-watcher.sh"), "security"],
                               env=env, capture_output=True, text=True, timeout=60)
            out = r.stdout + r.stderr
            self.assertTrue(packet.exists(), msg=f"packet was archived!\n{out}")
            self.assertFalse((dept / "archive" / f"{t}.md").exists(), msg=out)
            self.assertIn("not archiving", out)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
