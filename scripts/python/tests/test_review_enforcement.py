"""Unit tests for fail-closed cross-family review enforcement.

Review files never settle tasks automatically. Each test uses an isolated vault
and exercises the reconciler plus its explicit, lock-serialized Chrono settlement
command.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RECONCILER = Path(__file__).resolve().parents[1] / "registry_reconciler.py"

# Minimal runtime map: only column 1 (specialist) and column 7 (primary_lane)
# are read by _specialist_primary_lane. Lanes use the map spelling ("codex").
RUNTIME_MAP = "\t".join(["specialist", "c2", "c3", "c4", "c5", "c6", "primary_lane"]) + "\n"
RUNTIME_MAP += "\t".join(["claude-spec", "x", "x", "x", "x", "x", "claude"]) + "\n"
RUNTIME_MAP += "\t".join(["codex-spec", "x", "x", "x", "x", "x", "codex"]) + "\n"


def envelope(fm: dict, body: str = "done.") -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    return f"---\n{lines}\n---\n\n{body}\n"


def review(target: str, from_lane: str, body: str, status: str = "needs_review", ident: str = "REVIEW") -> str:
    return envelope({
        "id": f"{ident}-response", "in_response_to": target,
        "from": from_lane, "to": "chrono", "type": "RESULT", "status": status,
    }, body=body)


class ReviewEnforcementTest(unittest.TestCase):
    def fixture(self, entries: dict, responses: dict, mtimes: dict | None = None):
        root = Path(tempfile.mkdtemp(prefix="review-enforce-"))
        (root / "shared").mkdir(parents=True)
        (root / "shared" / "specialist-runtime-map.tsv").write_text(RUNTIME_MAP, encoding="utf-8")
        state = root / "_state"
        state.mkdir(parents=True)
        (state / "active-tasks.json").write_text(json.dumps(entries), encoding="utf-8")
        for rel_path, content in responses.items():
            dest = root / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            if mtimes and rel_path in mtimes:
                os.utime(dest, (mtimes[rel_path], mtimes[rel_path]))
        env = {
            **os.environ,
            "VAULT_ROOT": str(root),
            "RESPONSE_MIN_AGE_SECONDS": "0",
            "TMUX_BIN": "/nonexistent/tmux-for-tests",
            "SQUAD_SESSION": "no-such-session",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return root, state, env

    def run_reconcile(self, env: dict, task_id: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(RECONCILER), "--task-id", task_id],
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    def run_settle(
        self, env: dict, task_id: str, review_ref: str, expected_returncode: int = 0
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [
                sys.executable, str(RECONCILER),
                "--settle-review", task_id,
                "--review-ref", review_ref,
            ],
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected_returncode, msg=result.stderr)
        return result

    def result(self, state: Path, task_id: str) -> tuple[dict, str]:
        registry = json.loads((state / "active-tasks.json").read_text(encoding="utf-8"))
        queue_path = state / "chrono-queue.md"
        queue = queue_path.read_text(encoding="utf-8") if queue_path.exists() else ""
        return registry[task_id], queue

    def reconcile(
        self,
        entries: dict,
        responses: dict,
        task_id: str,
        runs: int = 1,
        mtimes: dict | None = None,
        settle_ref: str | None = None,
        settle_runs: int = 1,
    ) -> tuple[dict, str]:
        _root, state, env = self.fixture(entries, responses, mtimes)
        for _ in range(runs):
            self.run_reconcile(env, task_id)
        if settle_ref:
            for _ in range(settle_runs):
                self.run_settle(env, task_id, settle_ref)
        return self.result(state, task_id)

    def _own_response(self, task_id: str, from_lane: str, status: str) -> dict:
        return {
            f"departments/coding/outbox/{task_id}-response.md": envelope({
                "id": f"{task_id}-response", "in_response_to": task_id,
                "from": from_lane, "to": "chrono", "type": "RESULT", "status": status,
            }),
        }

    def _entry(self, **over) -> dict:
        base = {
            "compatibility_namespace": "coding", "specialist": "claude-spec",
            "to_model": "claude", "source_namespace": "coding",
            "review_model": "gpt-codex", "mandatory_review": "true", "status": "in-flight",
        }
        base.update(over)
        return base

    # ---- baseline (7) ------------------------------------------------------
    def test_a_cross_family_own_response_stays_review_required(self):
        t = "TASK-2026-07-15-0001-aaaa"
        entry, queue = self.reconcile({t: self._entry()}, self._own_response(t, "claude", "needs_review"), t)
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(entry["review_required_by"], "gpt-codex")
        self.assertIn("REVIEW-REQUIRED", queue)
        self.assertIn(t, queue)

    def test_a2_self_reported_complete_is_still_blocked(self):
        t = "TASK-2026-07-15-0002-bbbb"
        entry, queue = self.reconcile({t: self._entry()}, self._own_response(t, "claude", "complete"), t)
        self.assertEqual(entry["status"], "review-required")
        self.assertIn("REVIEW-REQUIRED", queue)

    def test_b_reviewer_response_requires_explicit_settlement(self):
        t = "TASK-2026-07-15-0003-cccc"
        responses = self._own_response(t, "claude", "needs_review")
        review_ref = "departments/coding/outbox/TASK-REVIEW-0003-response.md"
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE — reviewed.", "complete", "TASK-REVIEW-0003"
        )
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", entry)

        entry, queue = self.reconcile(
            {t: self._entry()}, responses, t,
            settle_ref=review_ref, settle_runs=2,
        )
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["cross_family_review_ref"], review_ref)
        self.assertEqual(entry["review_settled_by"], "chrono-explicit")
        self.assertIn("review_settled_at", entry)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

    def test_b2_blocking_review_keeps_open(self):
        t = "TASK-2026-07-15-0004-dddd"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-0004-response.md"] = review(t, "gpt-codex", "CHANGES-NEEDED: found a hole.", "needs_review", "TASK-REVIEW-0004")
        entry, queue = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("review_blocking_ref", entry)
        self.assertIn("REVIEW-REQUIRED", queue)

    def test_c_same_family_in_lane_settles_normally(self):
        t = "TASK-2026-07-15-0005-eeee"
        entry, queue = self.reconcile(
            {t: self._entry(specialist="codex-spec", to_model="gpt-codex", review_model="claude")},
            self._own_response(t, "gpt-codex", "needs_review"), t)
        self.assertEqual(entry["status"], "needs_review")
        self.assertNotIn("REVIEW-REQUIRED", queue)

    def test_d_non_mandatory_unaffected(self):
        t = "TASK-2026-07-15-0006-ffff"
        entry, queue = self.reconcile(
            {t: self._entry(mandatory_review="false", review_model="none")},
            self._own_response(t, "claude", "complete"), t)
        self.assertEqual(entry["status"], "complete")
        self.assertNotIn("REVIEW-REQUIRED", queue)

    def test_e_unrelated_reviewer_response_stays_open(self):
        t = "TASK-2026-07-15-0007-9999"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-OTHER-response.md"] = review("TASK-2026-07-15-9999-other", "gpt-codex", "APPROVE — different task entirely.", "complete", "TASK-REVIEW-OTHER")
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")

    # ---- adversarial regressions (6) — codex BLOCK findings ----------------
    # BLOCK 1a: unrelated response that MENTIONS the task id in its body must not settle
    def test_f_body_mention_spoof_does_not_settle(self):
        t = "TASK-2026-07-15-0010-spoof"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-UNRELATED-response.md"] = review(
            "TASK-2026-07-15-9999-other", "gpt-codex",
            f"No review performed. {t} remains pending; this response is about another task.",
            "complete", "TASK-UNRELATED")
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", entry)

    # BLOCK 1b: structurally-targeted reviewer response with NO structured verdict must not settle
    def test_f2_targeted_but_no_verdict_does_not_settle(self):
        t = "TASK-2026-07-15-0011-noverdict"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-NV-response.md"] = review(
            t, "gpt-codex", "Acknowledged receipt; will review later.", "complete", "TASK-REVIEW-NV")
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")

    # BLOCK 2: review file content and filename order have no automatic authority
    def test_g_approve_sorts_before_block_stays_open(self):
        t = "TASK-2026-07-15-0012-conflict"
        responses = self._own_response(t, "claude", "needs_review")
        approve = "departments/coding/outbox/TASK-AAAA-response.md"   # sorts first
        block = "departments/coding/outbox/TASK-ZZZZ-response.md"     # sorts last
        responses[approve] = review(t, "gpt-codex", "APPROVE — looks good.", "complete", "TASK-AAAA")
        responses[block] = review(t, "gpt-codex", "BLOCK — real hole.", "blocked", "TASK-ZZZZ")
        # BLOCK is at least as new as the APPROVE -> unresolved -> stays open regardless of filename order
        entry, _ = self.reconcile({t: self._entry()}, responses, t,
                                  mtimes={approve: 1_000_000, block: 1_000_050})
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("review_blocking_ref", entry)

    # fix 3: repeated blocking reconciles emit exactly one REVIEW-REQUIRED line
    def test_h_repeated_blocking_emits_once(self):
        t = "TASK-2026-07-15-0013-idemp"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-IDEMP-response.md"] = review(t, "gpt-codex", "CHANGES-NEEDED: fix it.", "needs_review", "TASK-REVIEW-IDEMP")
        entry, queue = self.reconcile({t: self._entry()}, responses, t, runs=2)
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(queue.count("REVIEW-REQUIRED"), 1, msg=queue)

    # fix 4 remains closed because even well-formed approval prose cannot auto-settle
    def test_i_approval_citing_resolved_changes_stays_held(self):
        t = "TASK-2026-07-15-0014-resolved"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-RES-response.md"] = review(
            t, "gpt-codex",
            "## Verdict: APPROVE\n\nThe prior CHANGES-NEEDED findings are now resolved; no BLOCK remains.",
            "needs_review", "TASK-REVIEW-RES")
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", entry)

    # fix 5/6: specialist mapped gpt-codex but overridden to gemini is ENFORCED (no in-lane exemption)
    def test_j_mapped_codex_but_overridden_is_enforced(self):
        t = "TASK-2026-07-15-0015-override"
        entry, queue = self.reconcile(
            {t: self._entry(specialist="codex-spec", to_model="gemini", review_model="claude")},
            self._own_response(t, "gemini", "needs_review"), t)
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(entry["review_required_by"], "claude")

    # fix 6: unknown execution lane (no map entry, empty to_model) fails CLOSED -> open
    def test_k_unknown_lane_fails_closed(self):
        t = "TASK-2026-07-15-0016-unknown"
        entry, _ = self.reconcile(
            {t: self._entry(specialist="ghost-spec", to_model="")},
            self._own_response(t, "claude", "needs_review"), t)
        self.assertEqual(entry["status"], "review-required")

    # ---- parser-removal regressions ---------------------------------------
    def test_l_contradictory_verdicts_have_no_automatic_authority(self):
        cases = {
            "body-conflict": review(
                "TARGET", "gpt-codex",
                "APPROVE — first.\n\nBLOCK — unresolved.", "complete", "TASK-AMBIG",
            ),
            "frontmatter-conflict": envelope({
                "id": "TASK-FM-response", "in_response_to": "TARGET",
                "from": "gpt-codex", "to": "chrono", "type": "RESULT",
                "status": "complete", "verdict": "APPROVE",
            }, body="BLOCK — unresolved."),
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                t = f"TASK-2026-07-15-0020-{label}"
                responses = self._own_response(t, "claude", "needs_review")
                content = content.replace("TARGET", t)
                responses[f"departments/coding/outbox/{label}-response.md"] = content
                entry, _ = self.reconcile({t: self._entry()}, responses, t)
                self.assertEqual(entry["status"], "review-required")
                self.assertNotIn("cross_family_review_ref", entry)

    def test_m_nonreview_and_nonterminal_envelopes_cannot_settle(self):
        cases = {
            "note-no-status": {
                "type": "NOTE", "body": "APPROVE — not a result.",
            },
            "in-flight": {
                "type": "RESULT", "status": "in-flight", "body": "APPROVE — draft.",
            },
            "cancelled": {
                "type": "RESULT", "status": "cancelled", "body": "APPROVE — stale.",
            },
        }
        for label, values in cases.items():
            with self.subTest(label=label):
                t = f"TASK-2026-07-15-0021-{label}"
                meta = {
                    "id": f"TASK-{label}-response", "in_response_to": t,
                    "reviews": t, "from": "gpt-codex", "to": "chrono",
                    "type": values["type"],
                }
                if "status" in values:
                    meta["status"] = values["status"]
                responses = self._own_response(t, "claude", "needs_review")
                responses[f"departments/coding/outbox/TASK-{label}-response.md"] = envelope(
                    meta, body=values["body"]
                )
                entry, _ = self.reconcile({t: self._entry()}, responses, t)
                self.assertEqual(entry["status"], "review-required")
                self.assertNotIn("cross_family_review_ref", entry)

    def test_n_mtime_cannot_supersede_a_block(self):
        t = "TASK-2026-07-15-0022-mtime"
        approve = "departments/coding/outbox/TASK-OLD-APPROVE-response.md"
        block = "departments/coding/outbox/TASK-REAL-BLOCK-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[approve] = review(t, "gpt-codex", "APPROVE — touched.", "complete", "TASK-OLD-APPROVE")
        responses[block] = review(t, "gpt-codex", "BLOCK — unresolved.", "blocked", "TASK-REAL-BLOCK")
        entry, _ = self.reconcile(
            {t: self._entry()}, responses, t,
            mtimes={approve: 1_700_000_001, block: 1_700_000_000},
        )
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", entry)

    def test_o_late_block_file_cannot_follow_an_auto_settle(self):
        t = "TASK-2026-07-15-0023-late-block"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-APP-response.md"] = review(
            t, "gpt-codex", "APPROVE — initial.", "complete", "TASK-APP"
        )
        root, state, env = self.fixture({t: self._entry()}, responses)
        self.run_reconcile(env, t)
        entry, _ = self.result(state, t)
        self.assertEqual(entry["status"], "review-required")

        block = root / "departments/coding/outbox/TASK-LATE-BLOCK-response.md"
        block.write_text(
            review(t, "gpt-codex", "BLOCK — later defect.", "blocked", "TASK-LATE-BLOCK"),
            encoding="utf-8",
        )
        self.run_reconcile(env, t)
        entry, queue = self.result(state, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(queue.count("REVIEW-REQUIRED"), 1)

    # ---- review-of-review regress and explicit control-plane settlement ---
    def test_p_read_only_reviewer_roles_do_not_require_review_of_review(self):
        for specialist in ("code-reviewer", "security-analyst"):
            for response_status in ("complete", "needs_review"):
                with self.subTest(specialist=specialist, status=response_status):
                    t = f"TASK-2026-07-15-0024-{specialist}-{response_status}"
                    entry, queue = self.reconcile(
                        {t: self._entry(specialist=specialist, write_scope=[])},
                        self._own_response(t, "claude", response_status), t,
                    )
                    self.assertEqual(entry["status"], response_status)
                    self.assertNotIn("REVIEW-REQUIRED", queue)

    def test_q_review_of_review_exemption_is_narrow(self):
        cases = {
            "reviewer-with-write": self._entry(
                specialist="code-reviewer", write_scope=["scripts/python/example.py"]
            ),
            "non-review-empty": self._entry(specialist="claude-spec", write_scope=[]),
            "string-empty": self._entry(specialist="security-analyst", write_scope="[]"),
            "missing-scope": self._entry(specialist="security-analyst"),
            "unknown-reviewer-lane": self._entry(
                specialist="code-reviewer", write_scope=[], to_model=""
            ),
        }
        for label, task_entry in cases.items():
            with self.subTest(label=label):
                t = f"TASK-2026-07-15-0025-{label}"
                entry, _ = self.reconcile(
                    {t: task_entry}, self._own_response(t, "claude", "complete"), t
                )
                self.assertEqual(entry["status"], "review-required")

    def test_r_explicit_settlement_rejects_invalid_lifecycle_and_refs(self):
        t = "TASK-2026-07-15-0026-guards"
        review_ref = "departments/coding/outbox/TASK-GUARD-REVIEW-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(t, "gpt-codex", "APPROVE", "complete", "TASK-GUARD-REVIEW")
        _root, _state, env = self.fixture({t: self._entry()}, responses)
        result = self.run_settle(env, t, review_ref, expected_returncode=2)
        self.assertIn("task is not review-required", result.stderr)

        blocked = "TASK-2026-07-15-0026-blocked-subject"
        responses = self._own_response(blocked, "claude", "blocked")
        responses[review_ref] = review(blocked, "gpt-codex", "APPROVE", "complete", "TASK-GUARD-REVIEW")
        _root, _state, env = self.fixture({blocked: self._entry()}, responses)
        self.run_reconcile(env, blocked)
        result = self.run_settle(env, blocked, review_ref, expected_returncode=2)
        self.assertIn("task response status cannot be settled", result.stderr)

        invalid_ref_task = "TASK-2026-07-15-0026-invalid-ref"
        responses = self._own_response(invalid_ref_task, "claude", "needs_review")
        responses["shared/not-a-review.md"] = "not a response\n"
        _root, _state, env = self.fixture({invalid_ref_task: self._entry()}, responses)
        self.run_reconcile(env, invalid_ref_task)
        result = self.run_settle(
            env, invalid_ref_task, "shared/not-a-review.md", expected_returncode=2
        )
        self.assertIn("must name an outbox/archive response", result.stderr)

        own_ref_task = "TASK-2026-07-15-0026-own-ref"
        own_ref = f"departments/coding/outbox/{own_ref_task}-response.md"
        responses = self._own_response(own_ref_task, "claude", "needs_review")
        _root, _state, env = self.fixture({own_ref_task: self._entry()}, responses)
        self.run_reconcile(env, own_ref_task)
        result = self.run_settle(env, own_ref_task, own_ref, expected_returncode=2)
        self.assertIn("must not be the task's own response", result.stderr)

    def test_s_explicit_settlement_is_locked_idempotent_and_conflict_safe(self):
        t = "TASK-2026-07-15-0027-settle-idempotent"
        first_ref = "departments/coding/outbox/TASK-FIRST-REVIEW-response.md"
        second_ref = "departments/coding/outbox/TASK-SECOND-REVIEW-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[first_ref] = review(t, "gpt-codex", "APPROVE", "complete", "TASK-FIRST-REVIEW")
        responses[second_ref] = review(t, "gpt-codex", "APPROVE", "complete", "TASK-SECOND-REVIEW")
        _root, state, env = self.fixture({t: self._entry()}, responses)
        self.run_reconcile(env, t)

        command = [
            sys.executable, str(RECONCILER), "--settle-review", t,
            "--review-ref", first_ref,
        ]
        processes = [
            subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        results = [process.communicate(timeout=60) + (process.returncode,) for process in processes]
        self.assertTrue(all(returncode == 0 for _stdout, _stderr, returncode in results), results)
        entry, queue = self.result(state, t)
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["cross_family_review_ref"], first_ref)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

        before_retry = (state / "active-tasks.json").read_bytes()
        self.run_settle(env, t, first_ref)
        after_retry = (state / "active-tasks.json").read_bytes()
        self.assertEqual(before_retry, after_retry)
        _entry, queue = self.result(state, t)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

        result = self.run_settle(env, t, second_ref, expected_returncode=2)
        self.assertIn("different review ref", result.stderr)


if __name__ == "__main__":
    unittest.main()
