"""Unit tests for fail-closed cross-family review enforcement.

Review files never settle tasks automatically. Each test uses an isolated vault
and exercises the reconciler plus its explicit, lock-serialized Chrono settlement
command.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import dispatch_context_builder as dcb  # noqa: E402

RECONCILER = PYTHON_ROOT / "registry_reconciler.py"

# Minimal runtime map: only column 1 (specialist) and column 7 (primary_lane)
# are read by _specialist_primary_lane. Lanes use the map spelling ("codex").
RUNTIME_MAP = "\t".join(["specialist", "c2", "c3", "c4", "c5", "c6", "primary_lane"]) + "\n"
RUNTIME_MAP += "\t".join(["claude-spec", "x", "x", "x", "x", "x", "claude"]) + "\n"
RUNTIME_MAP += "\t".join(["codex-spec", "x", "x", "x", "x", "x", "codex"]) + "\n"


def envelope(fm: dict, body: str = "done.") -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    return f"---\n{lines}\n---\n\n{body}\n"


def review(
    _target: str,
    from_lane: str,
    body: str,
    status: str = "needs_review",
    ident: str = "REVIEW",
    verdict: str | None = None,
) -> str:
    meta = {
        # A review response answers its own separately dispatched task. The
        # held subject is controller-owned registry provenance, not this
        # worker-authored identity field.
        "id": f"{ident}-response", "in_response_to": ident,
        "from": from_lane, "to": "chrono", "type": "RESULT", "status": status,
    }
    if verdict is not None:
        meta["verdict"] = verdict
    return envelope(meta, body=body)


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
        self,
        env: dict,
        task_id: str,
        review_ref: str,
        expected_returncode: int = 0,
        force: bool = False,
    ) -> subprocess.CompletedProcess:
        command = [
            sys.executable, str(RECONCILER),
            "--settle-review", task_id,
            "--review-ref", review_ref,
        ]
        if force:
            command.append("--force")
        result = subprocess.run(
            command,
            env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected_returncode, msg=result.stderr)
        return result

    def run_reopen(
        self,
        env: dict,
        task_id: str,
        status: str | None = None,
        expected_returncode: int = 0,
    ) -> subprocess.CompletedProcess:
        command = [sys.executable, str(RECONCILER), "--reopen", task_id]
        if status:
            command.extend(["--reopen-status", status])
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, expected_returncode, msg=result.stderr)
        return result

    def run_claim(self, env: dict, task_id: str, attempt_id: str, now: str) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                str(RECONCILER),
                "--claim-task",
                task_id,
                "--attempt-id",
                attempt_id,
                "--now",
                now,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads(result.stdout)

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
            "review_triggers": ["adversarial_claim"],
            # A mandatory-review entry always carries the class its packet
            # declared; registration refuses one that does not, and settlement
            # refuses to guess. `standard` is the class under test here.
            "review_class": "standard",
        }
        base.update(over)
        return base

    def _with_review_provenance(
        self,
        entries: dict,
        review_ref: str,
        target: str,
        lane: str,
        **over,
    ) -> dict:
        """Add the controller-owned registry record for a review response."""
        review_task_id = Path(review_ref).name.removesuffix("-response.md")
        review_entry = {"reviews": target, "to_model": lane}
        review_entry.update(over)
        return {**entries, review_task_id: review_entry}

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

    def test_a2b_equal_lane_mandatory_review_contract_fails_closed(self):
        t = "TASK-2026-07-15-0002-equal-lane"
        entry, queue = self.reconcile(
            {t: self._entry(to_model="claude", review_model="claude")},
            self._own_response(t, "claude", "complete"),
            t,
        )
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(entry["review_required_by"], "claude")
        self.assertIn("invalid mandatory-review anti-affinity", queue)

    def test_a2c_codex_alias_equal_lane_contract_fails_closed(self):
        t = "TASK-2026-07-15-0002-codex-alias"
        entry, queue = self.reconcile(
            {
                t: self._entry(
                    specialist="codex-spec",
                    to_model="codex",
                    review_model="gpt-codex",
                )
            },
            self._own_response(t, "gpt-codex", "complete"),
            t,
        )
        self.assertEqual(entry["status"], "review-required")
        self.assertEqual(entry["review_required_by"], "gpt-codex")
        self.assertIn("invalid mandatory-review anti-affinity", queue)

    def test_a3_review_hold_releases_delivery_lane_without_settling(self):
        held = "TASK-2026-07-15-0002-review-held"
        successor = "TASK-2026-07-15-0002-successor"
        at = "2026-07-17T00:00:00+00:00"
        entries = {
            held: self._entry(dispatched_at=at),
            successor: self._entry(
                status="in-flight",
                dispatched_at="2026-07-17T00:00:01+00:00",
                delivery_state="queued",
                delivery_attempt_id="d-successor",
                delivery_generation=1,
                delivery_lane="claude",
                delivery_attempt_count=0,
                delivery_history=[],
            ),
        }
        _root, state, env = self.fixture(
            entries,
            self._own_response(held, "claude", "needs_review"),
        )

        self.run_reconcile(env, held)
        held_entry, queue = self.result(state, held)
        released = self.run_claim(
            env,
            successor,
            "d-successor",
            "2026-07-17T00:00:02+00:00",
        )

        self.assertEqual(held_entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", held_entry)
        self.assertIn("REVIEW-REQUIRED", queue)
        self.assertEqual(released["delivery_state"], "in-progress")

    def test_b_reviewer_response_requires_explicit_settlement(self):
        t = "TASK-2026-07-15-0003-cccc"
        responses = self._own_response(t, "claude", "needs_review")
        review_ref = "departments/coding/outbox/TASK-REVIEW-0003-response.md"
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE — reviewed.", "complete", "TASK-REVIEW-0003",
            verdict="APPROVE",
        )
        entry, _ = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("cross_family_review_ref", entry)

        entry, queue = self.reconcile(
            self._with_review_provenance(
                {t: self._entry()}, review_ref, t, "gpt-codex"
            ),
            responses,
            t,
            settle_ref=review_ref, settle_runs=2,
        )
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["cross_family_review_ref"], review_ref)
        self.assertEqual(entry["review_ref"], review_ref)
        self.assertEqual(entry["verdict"], "APPROVE")
        self.assertFalse(entry["review_force_override"])
        self.assertEqual(entry["review_settled_by"], "chrono-explicit")
        self.assertIn("review_settled_at", entry)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

    def test_b1_needs_human_response_settles_only_through_valid_review(self):
        """A legitimate operator stop must not bypass or deadlock review."""
        t = "TASK-2026-08-30-needs-human-settlement"
        review_task = "TASK-2026-08-30-needs-human-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "claude", "needs_human")
        responses[review_ref] = review(
            t,
            "gpt-codex",
            "APPROVE — the boundary stop was correct.",
            "complete",
            review_task,
            verdict="APPROVE",
        )
        entries = self._with_review_provenance(
            {t: self._entry(author_family="anthropic")},
            review_ref,
            t,
            "gpt-codex",
        )
        _root, state, env = self.fixture(entries, responses)

        self.run_reconcile(env, t)
        parked, _queue = self.result(state, t)
        self.assertEqual(parked["status"], "review-required")

        # Reopen remains the wrong path: this task was never explicitly settled.
        refused_reopen = self.run_reopen(
            env, t, expected_returncode=2
        )
        self.assertIn("task is not explicitly settled complete", refused_reopen.stderr)

        self.run_settle(env, t, review_ref)
        settled, queue = self.result(state, t)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["verdict"], "APPROVE")
        self.assertEqual(settled["review_settled_by"], "chrono-explicit")
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

    def test_b1a_needs_human_accept_more_path_preserves_family_anti_affinity(self):
        t = "TASK-2026-08-30-needs-human-same-family"
        review_task = "TASK-2026-08-30-needs-human-same-family-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "claude", "needs_human")
        responses[review_ref] = review(
            t,
            "gpt-codex",
            "APPROVE — but from the author's family.",
            "complete",
            review_task,
            verdict="APPROVE",
        )
        entries = self._with_review_provenance(
            {t: self._entry(author_family="openai")},
            review_ref,
            t,
            "gpt-codex",
        )
        _root, state, env = self.fixture(entries, responses)
        self.run_reconcile(env, t)

        refused = self.run_settle(
            env, t, review_ref, expected_returncode=2
        )

        self.assertIn("standard review must be cross-family", refused.stderr)
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

    def test_b1b_needs_human_accept_more_path_rejects_nonapproval(self):
        t = "TASK-2026-08-30-needs-human-reject"
        review_task = "TASK-2026-08-30-needs-human-reject-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "claude", "needs_human")
        responses[review_ref] = review(
            t,
            "gpt-codex",
            "The stop was sound, but the deliverable needs changes.",
            "complete",
            review_task,
            verdict="REJECT",
        )
        entries = self._with_review_provenance(
            {t: self._entry(author_family="anthropic")},
            review_ref,
            t,
            "gpt-codex",
        )
        _root, state, env = self.fixture(entries, responses)
        self.run_reconcile(env, t)

        refused = self.run_settle(
            env, t, review_ref, expected_returncode=2
        )

        self.assertIn("observed REJECT", refused.stderr)
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

    def test_b2_blocking_review_keeps_open(self):
        t = "TASK-2026-07-15-0004-dddd"
        responses = self._own_response(t, "claude", "needs_review")
        responses["departments/coding/outbox/TASK-REVIEW-0004-response.md"] = review(t, "gpt-codex", "CHANGES-NEEDED: found a hole.", "needs_review", "TASK-REVIEW-0004")
        entry, queue = self.reconcile({t: self._entry()}, responses, t)
        self.assertEqual(entry["status"], "review-required")
        self.assertNotIn("review_blocking_ref", entry)
        self.assertIn("REVIEW-REQUIRED", queue)

    def test_b3_matching_explicit_review_echoes_do_not_conflict_with_registry(self):
        t = "TASK-2026-08-27-explicit-review-echoes"
        review_task = "TASK-2026-08-27-explicit-review-task"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = envelope({
            "id": f"{review_task}-response",
            "in_response_to": review_task,
            "reviews": t,
            "from": "gpt-codex",
            "reviewer_family": "openai",
            "to": "chrono",
            "type": "RESULT",
            "status": "complete",
            "verdict": "APPROVE",
        })
        entries = self._with_review_provenance(
            {t: self._entry(author_family="anthropic")},
            review_ref,
            t,
            "gpt-codex",
        )
        _root, state, env = self.fixture(entries, responses)
        self.run_reconcile(env, t)

        self.run_settle(env, t, review_ref)

        settled, _queue = self.result(state, t)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["cross_family_review_ref"], review_ref)

    def test_b4_explicit_review_echoes_cannot_override_registry_provenance(self):
        cases = {
            "target": (
                {"reviews": "TASK-2026-08-27-wrong-held-task"},
                "reviews conflicts with registry provenance",
            ),
            "family": (
                {"reviewer_family": "anthropic"},
                "reviewer_family conflicts with registry reviewer lane",
            ),
        }
        for label, (override, expected) in cases.items():
            with self.subTest(label=label):
                t = f"TASK-2026-08-27-explicit-conflict-{label}"
                review_task = f"TASK-2026-08-27-conflict-review-{label}"
                review_ref = (
                    f"departments/coding/outbox/{review_task}-response.md"
                )
                review_meta = {
                    "id": f"{review_task}-response",
                    "in_response_to": review_task,
                    "reviews": t,
                    "from": "gpt-codex",
                    "reviewer_family": "openai",
                    "to": "chrono",
                    "type": "RESULT",
                    "status": "complete",
                    "verdict": "APPROVE",
                }
                review_meta.update(override)
                responses = self._own_response(t, "claude", "needs_review")
                responses[review_ref] = envelope(review_meta)
                entries = self._with_review_provenance(
                    {t: self._entry(author_family="anthropic")},
                    review_ref,
                    t,
                    "gpt-codex",
                )
                _root, state, env = self.fixture(entries, responses)
                self.run_reconcile(env, t)

                refused = self.run_settle(
                    env, t, review_ref, expected_returncode=2
                )

                self.assertIn(expected, refused.stderr)
                self.assertEqual(
                    self.result(state, t)[0]["status"], "review-required"
                )

    def test_b5_missing_registry_review_target_reports_absence(self):
        t = "TASK-2026-08-27-missing-registry-review-target"
        review_task = "TASK-2026-08-27-missing-registry-review-task"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t,
            "gpt-codex",
            "APPROVE",
            "complete",
            review_task,
            verdict="APPROVE",
        )
        entries = {
            t: self._entry(author_family="anthropic"),
            review_task: {"to_model": "gpt-codex"},
        }
        _root, state, env = self.fixture(entries, responses)
        self.run_reconcile(env, t)

        refused = self.run_settle(env, t, review_ref, expected_returncode=2)

        self.assertIn("registry entry is missing reviews provenance", refused.stderr)
        self.assertNotIn("must target the held task", refused.stderr)
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

    def test_c_in_lane_capability_does_not_override_explicit_needs_review(self):
        t = "TASK-2026-07-15-0005-eeee"
        entry, queue = self.reconcile(
            {t: self._entry(specialist="codex-spec", to_model="gpt-codex", review_model="claude")},
            self._own_response(t, "gpt-codex", "needs_review"), t)
        self.assertEqual(entry["status"], "review-required")
        self.assertIn("REVIEW-REQUIRED", queue)

    def test_c2_cross_family_reported_complete_still_requires_review(self):
        t = "TASK-2026-07-15-0005-eeee-complete"
        entry, queue = self.reconcile(
            {t: self._entry(specialist="codex-spec", to_model="gpt-codex", review_model="claude")},
            self._own_response(t, "gpt-codex", "complete"), t)
        self.assertEqual(entry["status"], "review-required")
        self.assertIn("REVIEW-REQUIRED", queue)

    def test_c3_board_stamps_review_subject_before_explicit_settlement(self):
        t = "TASK-2026-07-19-0001-in-lane-settle-deadlock"
        review_task = "TASK-2026-07-19-0002-deadlock-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        responses = self._own_response(t, "gpt-codex", "needs_review")
        task = self._entry(
            specialist="codex-spec", to_model="gpt-codex", review_model="claude"
        )
        root, state, env = self.fixture(
            self._with_review_provenance(
                {t: task}, review_ref, t, "claude"
            ),
            responses,
        )

        # The worker authors its own review-task identity and substantive
        # verdict, but deliberately does NOT hand-add `reviews:`. The publish
        # bridge may echo the controller-authored packet value; settlement
        # independently treats the matching registry provenance as authority.
        worktree = root / "review-worktree"
        raw_response = worktree / review_ref
        raw_response.parent.mkdir(parents=True)
        raw_text = envelope(
            {
                "id": f"{review_task}-response",
                "in_response_to": review_task,
                "from": "claude",
                "to": "chrono",
                "type": "RESULT",
                "status": "complete",
                "verdict": "APPROVE",
                "return_artifact": review_ref,
            },
            body="APPROVE — independent review complete.",
        )
        self.assertNotIn("\nreviews:", raw_text)
        raw_response.write_text(raw_text, encoding="utf-8")
        prepared = dcb.prepare_worktree_outputs(
            root,
            worktree,
            {
                "task_id": review_task,
                "lane": "claude",
                "write_paths": [review_ref],
                "expected_result_path": review_ref,
                "expected_outbox_path": review_ref,
                "reconciliation_echo": dcb.packet_reconciliation_echo(
                    {"reviews": t}
                ),
            },
        )
        dcb.publish_prepared_worktree_outputs(root, prepared)
        published_review = (root / review_ref).read_text(encoding="utf-8")
        self.assertIn(f"in_response_to: {review_task}\n", published_review)
        self.assertIn(f"reviews: {t}\n", published_review)
        self.assertIn("verdict: APPROVE\n", published_review)

        self.run_reconcile(env, t)
        held, _queue = self.result(state, t)
        self.assertEqual(held["status"], "review-required")

        self.run_settle(env, t, review_ref)

        settled, queue = self.result(state, t)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["cross_family_review_ref"], review_ref)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

    def test_c4_in_lane_needs_review_hold_rejects_same_family_review(self):
        t = "TASK-2026-07-19-in-lane-same-family"
        review_ref = "departments/coding/outbox/TASK-SAME-FAMILY-response.md"
        responses = self._own_response(t, "gpt-codex", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE — self review.",
            "complete", "TASK-SAME-FAMILY", verdict="APPROVE",
        )
        task = self._entry(
            specialist="codex-spec", to_model="gpt-codex", review_model="claude"
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: task}, review_ref, t, "gpt-codex"
            ),
            responses,
        )
        self.run_reconcile(env, t)

        result = self.run_settle(env, t, review_ref, expected_returncode=2)

        self.assertIn("configured review_model", result.stderr)
        held, _queue = self.result(state, t)
        self.assertEqual(held["status"], "review-required")

    def test_d_no_trigger_self_written_response_auto_settles(self):
        t = "TASK-2026-07-15-0006-ffff"
        entry, queue = self.reconcile(
            {t: self._entry(
                mandatory_review="false", review_model="none", review_triggers=[]
            )},
            self._own_response(t, "claude", "complete"), t)
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["review_disposition"], "not-required")
        self.assertIn("auto_reconciled_at", entry)
        self.assertNotIn("REVIEW-REQUIRED", queue)

    def test_d2_no_trigger_needs_human_never_auto_closes(self):
        t = "TASK-2026-07-15-0006-needs-human"
        entry, queue = self.reconcile(
            {t: self._entry(
                mandatory_review="false", review_model="none", review_triggers=[]
            )},
            self._own_response(t, "claude", "needs_human"),
            t,
        )
        self.assertEqual(entry["status"], "needs_human")
        self.assertNotIn("review_disposition", entry)
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

    def test_h2_same_notification_key_never_repeats_after_elapsed_interval(self):
        t = "TASK-2026-07-15-0013-idemp-elapsed"
        responses = self._own_response(t, "claude", "needs_review")
        _root, state, env = self.fixture({t: self._entry()}, responses)
        self.run_reconcile(env, t)

        registry_path = state / "active-tasks.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry[t]["notification_last_emitted_at"] = "2020-01-01T00:00:00+00:00"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        env["NOTIFICATION_REPEAT_SECONDS"] = "0"
        self.run_reconcile(env, t)

        entry, queue = self.result(state, t)
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
        # skeptic is the claude-family member of the set: without it a
        # codex-authored task has no anti-affinity-eligible verdict role.
        for specialist in ("code-reviewer", "security-analyst", "skeptic"):
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
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE", "complete", "TASK-GUARD-REVIEW",
            verdict="APPROVE",
        )
        _root, _state, env = self.fixture({t: self._entry()}, responses)
        result = self.run_settle(env, t, review_ref, expected_returncode=2)
        self.assertIn("task is not review-required", result.stderr)

        blocked = "TASK-2026-07-15-0026-blocked-subject"
        responses = self._own_response(blocked, "claude", "blocked")
        responses[review_ref] = review(
            blocked, "gpt-codex", "APPROVE", "complete", "TASK-GUARD-REVIEW",
            verdict="APPROVE",
        )
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
        responses[first_ref] = review(
            t, "gpt-codex", "APPROVE", "complete", "TASK-FIRST-REVIEW",
            verdict="APPROVE",
        )
        responses[second_ref] = review(
            t, "gpt-codex", "APPROVE", "complete", "TASK-SECOND-REVIEW",
            verdict="APPROVE",
        )
        entries = self._with_review_provenance(
            {t: self._entry()}, first_ref, t, "gpt-codex"
        )
        entries = self._with_review_provenance(
            entries, second_ref, t, "gpt-codex"
        )
        _root, state, env = self.fixture(entries, responses)
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

    def test_t_explicit_settlement_accepts_legacy_needs_review_registry_state(self):
        t = "TASK-2026-07-15-0028-legacy-needs-review"
        review_ref = "departments/coding/outbox/TASK-LEGACY-REVIEW-response.md"
        responses = self._own_response(t, "gpt-codex", "needs_review")
        responses[review_ref] = review(
            t, "claude", "APPROVE", "complete", "TASK-LEGACY-REVIEW",
            verdict="APPROVE",
        )
        legacy = self._entry(
            status="needs_review", specialist="codex-spec",
            to_model="gpt-codex", review_model="claude",
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: legacy}, review_ref, t, "claude"
            ),
            responses,
        )

        self.run_settle(env, t, review_ref)

        entry, queue = self.result(state, t)
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["cross_family_review_ref"], review_ref)
        self.assertEqual(queue.count("REVIEW-SETTLED"), 1)

    def test_u_settlement_requires_structured_approve_unless_forced(self):
        t = "TASK-2026-07-20-verdict-gate"
        review_ref = "departments/coding/outbox/TASK-VERDICT-REVIEW-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "Prose says approve but the structured verdict rejects.",
            "complete", "TASK-VERDICT-REVIEW", verdict="REJECT",
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry()},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=review_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        refused = self.run_settle(env, t, review_ref, expected_returncode=2)
        self.assertIn("verdict must be exactly APPROVE", refused.stderr)
        held, _queue = self.result(state, t)
        self.assertEqual(held["status"], "review-required")

        self.run_settle(env, t, review_ref, force=True)
        settled, queue = self.result(state, t)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["verdict"], "REJECT")
        self.assertEqual(settled["review_ref"], review_ref)
        self.assertTrue(settled["review_force_override"])
        self.assertIn("REVIEW-SETTLED-FORCED", queue)

    def test_u2_settlement_rejects_missing_structured_verdict(self):
        t = "TASK-2026-07-20-verdict-missing"
        review_ref = "departments/coding/outbox/TASK-VERDICT-MISSING-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE appears only in prose.",
            "complete", "TASK-VERDICT-MISSING",
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry()},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=review_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        refused = self.run_settle(env, t, review_ref, expected_returncode=2)
        self.assertIn("observed MISSING", refused.stderr)
        held, _queue = self.result(state, t)
        self.assertEqual(held["status"], "review-required")

    def test_u2a_registry_artifact_approve_is_a_bounded_verdict_fallback(self):
        t = "TASK-2026-08-30-artifact-verdict-approve"
        review_task = "TASK-2026-08-30-artifact-verdict-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        artifact_ref = f"departments/coding/outbox/{review_task}-artifact.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "Structured verdict is in the artifact.",
            "complete", review_task,
        )
        responses[artifact_ref] = envelope(
            {
                "reviews": t,
                "reviewer_family": "openai",
                "author_family": "anthropic",
                "verdict": "APPROVE",
            },
            body="Independent review evidence.",
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry(author_family="anthropic")},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=artifact_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        self.run_settle(env, t, review_ref)

        settled, _queue = self.result(state, t)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["verdict"], "APPROVE")
        self.assertEqual(settled["review_ref"], review_ref)

    def test_u2b_registry_artifact_reject_remains_refused(self):
        t = "TASK-2026-08-30-artifact-verdict-reject"
        review_task = "TASK-2026-08-30-artifact-reject-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        artifact_ref = f"departments/coding/outbox/{review_task}-artifact.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "Blocking review.", "complete", review_task
        )
        responses[artifact_ref] = envelope(
            {"verdict": "REJECT"}, body="Changes are required."
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry()},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=artifact_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        refused = self.run_settle(env, t, review_ref, expected_returncode=2)

        self.assertIn("observed REJECT", refused.stderr)
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

    def test_u2c_response_verdict_preempts_registry_artifact_fallback(self):
        t = "TASK-2026-08-30-response-verdict-precedence"
        review_task = "TASK-2026-08-30-response-verdict-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        artifact_ref = f"departments/coding/outbox/{review_task}-artifact.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "Response says approve.", "complete", review_task,
            verdict="APPROVE",
        )
        responses[artifact_ref] = envelope(
            {"verdict": "REJECT"}, body="Artifact says reject."
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry()},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=artifact_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        settled = self.run_settle(env, t, review_ref)

        self.assertEqual(settled.stderr, "")
        entry, _queue = self.result(state, t)
        self.assertEqual(entry["status"], "complete")
        self.assertEqual(entry["verdict"], "APPROVE")

    def test_u2d_response_cannot_retarget_the_registry_artifact_fallback(self):
        t = "TASK-2026-08-30-artifact-path-authority"
        review_task = "TASK-2026-08-30-artifact-path-review"
        review_ref = f"departments/coding/outbox/{review_task}-response.md"
        artifact_ref = f"departments/coding/outbox/{review_task}-artifact.md"
        asserted_ref = f"departments/coding/outbox/{review_task}-asserted.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = envelope(
            {
                "id": f"{review_task}-response",
                "in_response_to": review_task,
                "from": "gpt-codex",
                "to": "chrono",
                "type": "RESULT",
                "status": "complete",
                "return_artifact": asserted_ref,
            },
            body="Worker asserted a different artifact path.",
        )
        responses[artifact_ref] = envelope(
            {"verdict": "APPROVE"}, body="Registry-owned artifact."
        )
        responses[asserted_ref] = envelope(
            {"verdict": "APPROVE"}, body="Worker-selected artifact."
        )
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: self._entry()},
                review_ref,
                t,
                "gpt-codex",
                return_artifact=artifact_ref,
            ),
            responses,
        )
        self.run_reconcile(env, t)

        refused = self.run_settle(env, t, review_ref, expected_returncode=2)

        self.assertIn(
            "return_artifact conflicts with registry provenance", refused.stderr
        )
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

    def test_u2e_malformed_artifact_frontmatter_fails_closed(self):
        malformed = {
            "duplicate": (
                "---\nverdict: APPROVE\nverdict: APPROVE\n---\n\nevidence\n",
                "duplicated",
            ),
            "nested": (
                "---\nverdict:\n  value: APPROVE\n---\n\nevidence\n",
                "nested content",
            ),
            "malformed": (
                "---\nverdict APPROVE\n---\n\nevidence\n",
                "not a top-level key/value pair",
            ),
        }
        for label, (artifact, expected) in malformed.items():
            with self.subTest(label=label):
                t = f"TASK-2026-08-30-artifact-{label}"
                review_task = f"TASK-2026-08-30-artifact-{label}-review"
                review_ref = (
                    f"departments/coding/outbox/{review_task}-response.md"
                )
                artifact_ref = (
                    f"departments/coding/outbox/{review_task}-artifact.md"
                )
                responses = self._own_response(t, "claude", "needs_review")
                responses[review_ref] = review(
                    t, "gpt-codex", "Artifact parser control.",
                    "complete", review_task,
                )
                responses[artifact_ref] = artifact
                _root, state, env = self.fixture(
                    self._with_review_provenance(
                        {t: self._entry()},
                        review_ref,
                        t,
                        "gpt-codex",
                        return_artifact=artifact_ref,
                    ),
                    responses,
                )
                self.run_reconcile(env, t)

                refused = self.run_settle(
                    env, t, review_ref, expected_returncode=2
                )

                self.assertIn(expected, refused.stderr)
                self.assertEqual(
                    self.result(state, t)[0]["status"], "review-required"
                )

    def test_u2f_artifact_fallback_cannot_bypass_family_anti_affinity(self):
        def run(author_family: str, suffix: str) -> tuple[dict, str]:
            t = f"TASK-2026-08-30-artifact-family-{suffix}"
            review_task = f"TASK-2026-08-30-artifact-family-review-{suffix}"
            review_ref = f"departments/coding/outbox/{review_task}-response.md"
            artifact_ref = f"departments/coding/outbox/{review_task}-artifact.md"
            responses = self._own_response(t, "claude", "needs_review")
            responses[review_ref] = review(
                t, "gpt-codex", "Verdict is in the artifact.",
                "complete", review_task,
            )
            responses[artifact_ref] = envelope(
                {"verdict": "APPROVE"}, body="Artifact approval."
            )
            _root, state, env = self.fixture(
                self._with_review_provenance(
                    {t: self._entry(author_family=author_family)},
                    review_ref,
                    t,
                    "gpt-codex",
                    return_artifact=artifact_ref,
                ),
                responses,
            )
            self.run_reconcile(env, t)
            result = self.run_settle(
                env,
                t,
                review_ref,
                expected_returncode=2 if author_family == "openai" else 0,
            )
            return self.result(state, t)[0], result.stderr

        held, error = run("openai", "same")
        self.assertIn("standard review must be cross-family", error)
        self.assertEqual(held["status"], "review-required")

        settled, error = run("anthropic", "cross")
        self.assertEqual(error, "")
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["verdict"], "APPROVE")

    def test_u3_settlement_rejects_a_different_LANE_of_the_SAME_family(self):
        """Anti-affinity is a FAMILY rule, and the lane check cannot stand in for it.

        `author_family` is not a function of `to_model`: `_entry_author_family`
        prefers an explicit `author_family` (then the pinned
        `verification_contract.author_family`) and only falls back to the lane
        map. So a claude-lane task can carry an openai author pin -- a codex
        artifact reworked on another lane -- and a gpt-codex review then clears
        every lane-level check while being same-family.

        `_validate_standard_review`'s `reviewer_family == author_family` clause
        is the only thing that catches it. Before this test the three
        `must be cross-family` clauses in the reconciler could all be replaced
        with `if False:` and the whole suite plus
        `bin/review-loop-guard-selftest.py` stayed green
        (measured 2026-08-26, TASK-2026-08-27-0430-w9b): the coverage the
        removed subswarm suite claimed for anti-affinity was never here.
        """
        t = "TASK-2026-08-26-same-family-other-lane"
        review_ref = "departments/coding/outbox/TASK-SAME-FAMILY-REVIEW-response.md"
        responses = self._own_response(t, "claude", "needs_review")
        responses[review_ref] = review(
            t, "gpt-codex", "APPROVE", "complete", "TASK-SAME-FAMILY-REVIEW",
            verdict="APPROVE",
        )
        # The reviewer lane (gpt-codex) differs from the executing lane
        # (claude), so nothing upstream of settlement objects.
        same_family = self._entry(author_family="openai")
        _root, state, env = self.fixture(
            self._with_review_provenance(
                {t: same_family}, review_ref, t, "gpt-codex"
            ),
            responses,
        )
        self.run_reconcile(env, t)
        refused = self.run_settle(env, t, review_ref, expected_returncode=2)
        self.assertIn("standard review must be cross-family", refused.stderr)
        held, _queue = self.result(state, t)
        self.assertEqual(held["status"], "review-required")

        # Positive control on the SAME bytes: only the author pin changes, so a
        # pass here proves the refusal above came from the family clause and not
        # from some other defect in the fixture.
        cross = "TASK-2026-08-26-cross-family-other-lane"
        cross_ref = "departments/coding/outbox/TASK-CROSS-FAMILY-REVIEW-response.md"
        cross_responses = self._own_response(cross, "claude", "needs_review")
        cross_responses[cross_ref] = review(
            cross, "gpt-codex", "APPROVE", "complete", "TASK-CROSS-FAMILY-REVIEW",
            verdict="APPROVE",
        )
        _root, cross_state, cross_env = self.fixture(
            self._with_review_provenance(
                {cross: self._entry(author_family="anthropic")},
                cross_ref,
                cross,
                "gpt-codex",
            ),
            cross_responses,
        )
        self.run_reconcile(cross_env, cross)
        self.run_settle(cross_env, cross, cross_ref)
        settled, _queue = self.result(cross_state, cross)
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["verdict"], "APPROVE")

    def test_u4_same_family_is_refused_on_the_security_and_factual_paths_too(self):
        """The other two `must be cross-family` clauses, same defect, same shape.

        `standard`, `security-finding`, and `factual` each have their own
        validator and their own copy of the family clause. All three were
        unasserted together -- disarming all three left this suite and
        `bin/review-loop-guard-selftest.py` green -- so covering only the
        standard path would leave two of the three still free to regress.
        """
        # --- security-finding: independent lane review, same family ----------
        t = "TASK-2026-08-26-security-same-family"
        own_body = self._own_response(t, "claude", "needs_review")
        own_path = f"departments/coding/outbox/{t}-response.md"
        reviewed_hash = hashlib.sha256(
            own_body[own_path].encode("utf-8")
        ).hexdigest()
        security_ref = "departments/coding/outbox/TASK-SEC-SAME-FAMILY-response.md"
        responses = dict(own_body)
        responses[security_ref] = envelope({
            "id": "TASK-SEC-SAME-FAMILY-response", "in_response_to": t,
            "from": "gpt-codex", "to": "chrono", "type": "RESULT",
            "status": "complete", "verdict": "APPROVE",
            "reviewer_family": "openai",
            "reviewed_response_sha256": reviewed_hash,
        }, body="Independent lane review, but the author pin is openai too.")
        entry = self._entry(
            author_family="openai",
            review_class="security-finding",
            review_triggers=["adversarial_claim"],
        )
        _root, state, env = self.fixture({t: entry}, responses)
        self.run_reconcile(env, t)
        refused = self.run_settle(env, t, security_ref, expected_returncode=2)
        self.assertIn("security-finding review must be cross-family", refused.stderr)
        self.assertEqual(self.result(state, t)[0]["status"], "review-required")

        # --- factual: controller attestation, same family --------------------
        f = "TASK-2026-08-26-factual-same-family"
        factual_own = self._own_response(f, "claude", "needs_review")
        factual_own_path = f"departments/coding/outbox/{f}-response.md"
        attested_hash = hashlib.sha256(
            factual_own[factual_own_path].encode("utf-8")
        ).hexdigest()
        factual_ref = "departments/coding/outbox/TASK-FACTUAL-SAME-FAMILY-response.md"
        factual_responses = dict(factual_own)
        factual_responses[factual_ref] = envelope({
            "id": "TASK-FACTUAL-SAME-FAMILY-response", "in_response_to": f,
            "from": "chrono", "type": "REVIEW_ATTESTATION", "status": "complete",
            "verdict": "APPROVE", "review_class": "factual",
            "reviewer_lane": "gpt-codex", "reviewer_family": "openai",
            "attested_response_sha256": attested_hash,
        }, body="Coordinator attested, but against an openai-authored task.")
        factual_entry = self._entry(
            author_family="openai",
            review_class="factual",
            review_triggers=["deciding_measurement"],
        )
        _root, factual_state, factual_env = self.fixture(
            {f: factual_entry}, factual_responses
        )
        self.run_reconcile(factual_env, f)
        factual_refused = self.run_settle(
            factual_env, f, factual_ref, expected_returncode=2
        )
        self.assertIn(
            "factual coordinator attestation must be cross-family",
            factual_refused.stderr,
        )
        self.assertEqual(
            self.result(factual_state, f)[0]["status"], "review-required"
        )

    # ---- attestation binding: hash, authorship, status, lane (5) -----------
    #
    # `_validate_factual_attestation` and `_validate_security_review` each own
    # clauses that no test asserted: both hash bindings, the attestation's
    # `from: chrono` authorship, its `status: complete`, and the security
    # reviewer's lane. The two builders below produce a fixture that settles,
    # so each test can flip exactly one frontmatter field and attribute the
    # refusal to that field alone.

    def _factual_case(
        self,
        task_id: str,
        review_ref: str,
        *,
        entry_over: dict | None = None,
        drop: tuple[str, ...] = (),
        **fm_over,
    ):
        """A factual task held for review, plus a settling Chrono attestation.

        Returns ``(state, env, review_ref)`` already reconciled to
        ``review-required``. ``fm_over`` replaces one attestation frontmatter
        field, so the unmodified call is the positive control for every test
        that mutates a single field out of it.
        """
        own = self._own_response(task_id, "claude", "needs_review")
        own_path = f"departments/coding/outbox/{task_id}-response.md"
        meta = {
            "id": Path(review_ref).name.removesuffix(".md"),
            "in_response_to": task_id,
            "from": "chrono", "type": "REVIEW_ATTESTATION", "status": "complete",
            "verdict": "APPROVE", "review_class": "factual",
            "reviewer_lane": "gpt-codex", "reviewer_family": "openai",
            "attested_response_sha256": hashlib.sha256(
                own[own_path].encode("utf-8")
            ).hexdigest(),
        }
        meta.update(fm_over)
        for key in drop:
            meta.pop(key, None)
        responses = dict(own)
        responses[review_ref] = envelope(
            meta, body="Coordinator read the landed response and attested it."
        )
        entry = self._entry(
            review_class="factual",
            review_triggers=["deciding_measurement"],
            **(entry_over or {}),
        )
        _root, state, env = self.fixture({task_id: entry}, responses)
        self.run_reconcile(env, task_id)
        return state, env, review_ref

    def _security_case(
        self,
        task_id: str,
        review_ref: str,
        *,
        entry_over: dict | None = None,
        drop: tuple[str, ...] = (),
        **fm_over,
    ):
        """A security-finding task held for review, plus a settling lane review.

        Same contract as ``_factual_case``: unmodified it settles, so a single
        overridden field is the whole difference a refusal can come from.
        """
        own = self._own_response(task_id, "claude", "needs_review")
        own_path = f"departments/coding/outbox/{task_id}-response.md"
        meta = {
            "id": Path(review_ref).name.removesuffix(".md"),
            "in_response_to": task_id,
            "from": "gpt-codex", "to": "chrono", "type": "RESULT",
            "status": "complete", "verdict": "APPROVE",
            "reviewer_family": "openai",
            "reviewed_response_sha256": hashlib.sha256(
                own[own_path].encode("utf-8")
            ).hexdigest(),
        }
        meta.update(fm_over)
        for key in drop:
            meta.pop(key, None)
        responses = dict(own)
        responses[review_ref] = envelope(
            meta, body="Independent cross-family lane review of the finding."
        )
        entry = self._entry(
            review_class="security-finding",
            review_triggers=["adversarial_claim"],
            **(entry_over or {}),
        )
        _root, state, env = self.fixture({task_id: entry}, responses)
        self.run_reconcile(env, task_id)
        return state, env, review_ref

    def test_u5_factual_attestation_must_name_the_landed_response_bytes(self):
        """Deleting the `attested_response_sha256` clause of
        `_validate_factual_attestation` settles a response the coordinator
        never read.

        The attestation is the only artifact on the factual path; nothing else
        binds it to the bytes that landed. Replace those two lines with
        `if False:` and a worker may rewrite its response after the coordinator
        has read and attested the previous version -- the swapped bytes settle
        under the old approval. Before this test `attested_response_sha256`
        occurred exactly once in the entire test tree, as a correct value in a
        fixture, so no negative control existed anywhere: the mutation left
        this suite and `bin/review-loop-guard-selftest.py` green (measured
        2026-09-01).
        """
        # Positive control first: identical fixture, correct hash, settles.
        ok = "TASK-2026-08-30-factual-hash-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-HASH-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # The coordinator attested THESE bytes; the worker then landed others.
        superseded = envelope({
            "id": "TASK-2026-08-30-factual-hash-swap-response",
            "in_response_to": "TASK-2026-08-30-factual-hash-swap",
            "from": "claude", "to": "chrono", "type": "RESULT",
            "status": "needs_review",
        }, body="the bytes the coordinator actually read")
        swapped = "TASK-2026-08-30-factual-hash-swap"
        state, env, ref = self._factual_case(
            swapped,
            "departments/coding/outbox/TASK-ATT-HASH-SWAP-response.md",
            attested_response_sha256=hashlib.sha256(
                superseded.encode("utf-8")
            ).hexdigest(),
        )
        refused = self.run_settle(env, swapped, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation response hash mismatch",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, swapped)[0]["status"], "review-required"
        )

    def test_u6_security_review_must_name_the_landed_response_bytes(self):
        """Deleting the `reviewed_response_sha256` clause of
        `_validate_security_review` settles a response the reviewer never read.

        Same defect as the factual path, same absent coverage:
        `reviewed_response_sha256` also occurred exactly once in the test tree
        as a correct fixture value, and replacing the clause with `if False:`
        left this suite and `bin/review-loop-guard-selftest.py` green (measured
        2026-09-01). A security finding settling against unreviewed bytes is
        the sharpest form of it.
        """
        ok = "TASK-2026-08-30-security-hash-ok"
        state, env, ref = self._security_case(
            ok, "departments/coding/outbox/TASK-SEC-HASH-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        superseded = envelope({
            "id": "TASK-2026-08-30-security-hash-swap-response",
            "in_response_to": "TASK-2026-08-30-security-hash-swap",
            "from": "claude", "to": "chrono", "type": "RESULT",
            "status": "needs_review",
        }, body="the bytes the reviewer actually read")
        swapped = "TASK-2026-08-30-security-hash-swap"
        state, env, ref = self._security_case(
            swapped,
            "departments/coding/outbox/TASK-SEC-HASH-SWAP-response.md",
            reviewed_response_sha256=hashlib.sha256(
                superseded.encode("utf-8")
            ).hexdigest(),
        )
        refused = self.run_settle(env, swapped, ref, expected_returncode=2)
        self.assertIn(
            "security-finding review response hash mismatch", refused.stderr
        )
        self.assertEqual(
            self.result(state, swapped)[0]["status"], "review-required"
        )

    def test_u7_factual_attestation_must_be_authored_by_chrono(self):
        """Deleting the `from: chrono` clause of
        `_validate_factual_attestation` lets the executing lane author its own
        approval.

        `from` is the only field that makes the artifact a *coordinator*
        attestation; `reviewer_lane` and `reviewer_family` are declarations the
        author writes about someone else. With the clause replaced by
        `if False:`, a `claude`-authored file that names `gpt-codex`/`openai`
        as its reviewer passes every remaining check -- lane, family
        anti-affinity, and hash all read the declared reviewer, not the author
        -- so the worker self-settles. The suite and
        `bin/review-loop-guard-selftest.py` stayed green (measured 2026-09-01).
        """
        ok = "TASK-2026-08-30-factual-author-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-AUTHOR-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # Authored by the executing lane, still declaring the reviewer's lane
        # and family in frontmatter: a worker approving its own work.
        forged = "TASK-2026-08-30-factual-author-forged"
        state, env, ref = self._factual_case(
            forged,
            "departments/coding/outbox/TASK-ATT-AUTHOR-FORGED-response.md",
            **{"from": "claude"},
        )
        refused = self.run_settle(env, forged, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation must be authored by from: chrono",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, forged)[0]["status"], "review-required"
        )

    def test_u8_factual_attestation_status_must_be_complete(self):
        """Deleting the `status must be complete` clause of
        `_validate_factual_attestation` settles on an unfinished attestation.

        `needs_review` is the exact value the standard path deliberately
        admits (`_validate_standard_review` accepts `complete` or
        `needs_review`), so an attestation that is still open reads as
        acceptable everywhere except this clause. Replace it with `if False:`
        and a coordinator note that has not reached a conclusion closes the
        task; the suite and `bin/review-loop-guard-selftest.py` stayed green
        (measured 2026-09-01).
        """
        ok = "TASK-2026-08-30-factual-status-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-STATUS-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        open_att = "TASK-2026-08-30-factual-status-open"
        state, env, ref = self._factual_case(
            open_att,
            "departments/coding/outbox/TASK-ATT-STATUS-OPEN-response.md",
            status="needs_review",
        )
        refused = self.run_settle(env, open_att, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation status must be complete",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, open_att)[0]["status"], "review-required"
        )

    def test_u9_security_review_must_come_from_the_configured_review_model(self):
        """Deleting the reviewer-lane clause of `_validate_security_review`
        lets any cross-family lane settle a finding assigned to another.

        Family anti-affinity still fires on the mutant, so the hole is
        narrower than the others -- but "some other model looked at it" is not
        the contract. `review_model` names the assigned reviewer, and a
        `gemini` review of a finding routed to `gpt-codex` is cross-family,
        hash-bound, and still not the review that was ordered. With the clause
        replaced by `if False:` it settles, and the suite plus
        `bin/review-loop-guard-selftest.py` stayed green (measured
        2026-09-01).
        """
        ok = "TASK-2026-08-30-security-lane-ok"
        state, env, ref = self._security_case(
            ok, "departments/coding/outbox/TASK-SEC-LANE-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # gemini is cross-family to the anthropic author, so every family
        # check passes; only the assigned-reviewer clause objects.
        unassigned = "TASK-2026-08-30-security-lane-unassigned"
        state, env, ref = self._security_case(
            unassigned,
            "departments/coding/outbox/TASK-SEC-LANE-UNASSIGNED-response.md",
            **{"from": "gemini", "reviewer_family": "google"},
        )
        refused = self.run_settle(env, unassigned, ref, expected_returncode=2)
        self.assertIn(
            "security-finding review must come from the configured review_model",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, unassigned)[0]["status"], "review-required"
        )

    def test_u10_factual_attestation_must_target_the_held_task(self):
        """Deleting the `in_response_to` clause of
        `_validate_factual_attestation` lets an attestation written for
        another task settle this one.

        This clause sits behind the hash binding, so the attacker has to
        supply the held task's own response hash to reach it -- a coordinator
        attestation retargeted, rather than fabricated. Narrow, but the clause
        was unasserted on its own terms: replacing it with `if False:` left
        the pre-existing 49 tests and `bin/review-loop-guard-selftest.py`
        green (measured 2026-09-01). The one place the message appears in this
        file, `test_b5`, asserts it is *absent*, which pins a different guard
        and controls nothing here.
        """
        ok = "TASK-2026-08-30-factual-target-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-TARGET-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # Correct hash for THIS task's landed response, but the attestation
        # names a different task as its subject.
        retargeted = "TASK-2026-08-30-factual-target-retargeted"
        state, env, ref = self._factual_case(
            retargeted,
            "departments/coding/outbox/TASK-ATT-TARGET-OTHER-response.md",
            in_response_to="TASK-2026-08-30-a-completely-different-task",
        )
        refused = self.run_settle(env, retargeted, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation must target the held task",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, retargeted)[0]["status"], "review-required"
        )

    def test_u11_factual_attestation_requires_the_attestation_type(self):
        """Deleting the `type: REVIEW_ATTESTATION` clause of
        `_validate_factual_attestation` lets an ordinary coordinator RESULT
        settle a factual review.

        `type` is what distinguishes an artifact the coordinator issued *as a
        settlement* from any other note it wrote about the task. With the
        clause replaced by `if False:`, a `from: chrono` RESULT settles: every
        remaining check reads a field a status note can carry. The type is
        also half of what keeps the three settlement paths apart -- both
        `_validate_security_review` and `_validate_standard_review` refuse an
        artifact bearing this type, and this is the only clause that requires
        it. Removing it left the pre-existing tests and
        `bin/review-loop-guard-selftest.py` green (measured 2026-09-01).
        """
        ok = "TASK-2026-08-30-factual-type-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-TYPE-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # A coordinator-authored RESULT: right author, not an attestation.
        untyped = "TASK-2026-08-30-factual-type-result"
        state, env, ref = self._factual_case(
            untyped,
            "departments/coding/outbox/TASK-ATT-TYPE-RESULT-response.md",
            type="RESULT",
        )
        refused = self.run_settle(env, untyped, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation requires type: REVIEW_ATTESTATION",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, untyped)[0]["status"], "review-required"
        )

    def test_u12_factual_attestation_must_echo_its_settlement_class(self):
        """Deleting the `review_class: factual` clause of
        `_validate_factual_attestation` lets an attestation issued for a
        weaker class settle a factual task.

        This is the read-side mirror of the defect `_review_class` documents
        on the entry: a settlement that silently accepts a lesser class than
        the one the task demanded. The entry says `factual`, so the factual
        validator runs; without this clause nothing then requires the
        attestation itself to agree, and one written against `standard`
        settles. Removing it left the pre-existing tests and
        `bin/review-loop-guard-selftest.py` green (measured 2026-09-01).
        """
        ok = "TASK-2026-08-30-factual-class-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-CLASS-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # Attested against the weaker class the entry did not ask for.
        downgraded = "TASK-2026-08-30-factual-class-downgraded"
        state, env, ref = self._factual_case(
            downgraded,
            "departments/coding/outbox/TASK-ATT-CLASS-STANDARD-response.md",
            review_class="standard",
        )
        refused = self.run_settle(env, downgraded, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation must echo review_class: factual",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, downgraded)[0]["status"], "review-required"
        )

    # ---- standard-path settlement: the default class (7) -------------------
    #
    # `standard` is the class most tasks settle under; factual and
    # security-finding are the special cases. Nine of its ten clauses had no
    # test naming them. The builder below produces a review that settles, so
    # each test flips exactly one field -- in the response, or in the
    # controller-owned registry provenance -- and attributes the refusal to it.

    def _standard_case(
        self,
        task_id: str,
        review_ref: str,
        *,
        provenance_lane: str = "gpt-codex",
        provenance_target: str | None = None,
        entry_over: dict | None = None,
        drop: tuple[str, ...] = (),
        **fm_over,
    ):
        """A standard-class task held for review, plus a settling lane review.

        Unmodified it settles, so a single overridden field is the whole
        difference a refusal can come from. ``provenance_lane`` and
        ``provenance_target`` edit the registry's review entry -- the
        controller-owned side -- rather than the worker-authored response.
        """
        review_task = Path(review_ref).name.removesuffix("-response.md")
        meta = {
            "id": f"{review_task}-response", "in_response_to": review_task,
            "reviews": task_id, "from": "gpt-codex", "reviewer_family": "openai",
            "to": "chrono", "type": "RESULT", "status": "complete",
            "verdict": "APPROVE",
        }
        meta.update(fm_over)
        for key in drop:
            meta.pop(key, None)
        responses = self._own_response(task_id, "claude", "needs_review")
        responses[review_ref] = envelope(meta)
        entry = self._entry(author_family="anthropic", **(entry_over or {}))
        entries = self._with_review_provenance(
            {task_id: entry},
            review_ref,
            provenance_target if provenance_target is not None else task_id,
            provenance_lane,
        )
        _root, state, env = self.fixture(entries, responses)
        self.run_reconcile(env, task_id)
        return state, env, review_ref

    def test_x1_standard_review_rejects_a_coordinator_attestation(self):
        """Deleting the `requires an independent lane response` clause of
        `_validate_standard_review` lets the coordinator settle a standard
        task with its own attestation.

        This is the clause that keeps the factual path's artifact off the
        default path. Note the honest limit of this control: with the clause
        replaced by `if False:` the mutant still refuses, because
        `must be a RESULT response` catches the type a line later and the
        reviewer-lane clause catches `from: chrono`. It is defense in depth,
        not a lone gate -- so this test asserts the specific message rather
        than the settlement, and goes red on the message alone.
        """
        ok = "TASK-2026-08-30-standard-independent-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-INDEP-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        attested = "TASK-2026-08-30-standard-independent-attested"
        state, env, ref = self._standard_case(
            attested,
            "departments/coding/outbox/TASK-STD-INDEP-ATT-response.md",
            type="REVIEW_ATTESTATION",
            **{"from": "chrono"},
        )
        refused = self.run_settle(env, attested, ref, expected_returncode=2)
        self.assertIn(
            "standard review requires an independent lane response",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, attested)[0]["status"], "review-required"
        )

    def test_x2_standard_review_must_be_a_result_response(self):
        """Deleting the `must be a RESULT response` clause of
        `_validate_standard_review` settles on an envelope that is not a
        result at all.

        A worker-authored envelope of any other type -- a status note, a
        question -- carries `from`, `status` and `verdict` fields that every
        remaining clause reads happily. With this clause replaced by
        `if False:` such an envelope settles the task.
        """
        ok = "TASK-2026-08-30-standard-type-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-TYPE-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        noted = "TASK-2026-08-30-standard-type-status-note"
        state, env, ref = self._standard_case(
            noted,
            "departments/coding/outbox/TASK-STD-TYPE-NOTE-response.md",
            type="STATUS",
        )
        refused = self.run_settle(env, noted, ref, expected_returncode=2)
        self.assertIn("standard review must be a RESULT response", refused.stderr)
        self.assertEqual(
            self.result(state, noted)[0]["status"], "review-required"
        )

    def test_x3_standard_review_provenance_must_target_the_held_task(self):
        """Deleting the `registry provenance targets a different held task`
        clause of `_validate_standard_review` lets a review dispatched for one
        task settle another.

        `test_b5` covers the case where the provenance is *absent*. This is
        the case where it is present and points elsewhere: the registry says
        the review task was dispatched to review a different task, and the
        response omits the optional `reviews` echo entirely, which is what
        isolates this clause: with the echo present the conflict is caught one
        line earlier by `reviews conflicts with registry provenance`, so a
        fixture that leaves it in tests that neighbour instead. Verified by
        mutation: with this clause replaced by `if False:` and no echo to fall
        back on, the review settles a task it was never dispatched to review.
        """
        ok = "TASK-2026-08-30-standard-target-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-TARGET-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        borrowed = "TASK-2026-08-30-standard-target-borrowed"
        state, env, ref = self._standard_case(
            borrowed,
            "departments/coding/outbox/TASK-STD-TARGET-OTHER-response.md",
            provenance_target="TASK-2026-08-30-some-other-held-task",
            drop=("reviews",),
        )
        refused = self.run_settle(env, borrowed, ref, expected_returncode=2)
        self.assertIn(
            "standard review registry provenance targets a different held task",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, borrowed)[0]["status"], "review-required"
        )

    def test_x4_standard_review_response_must_declare_its_author(self):
        """Deleting the `response is missing from` clause of
        `_validate_standard_review` settles an anonymous review.

        Reported honestly, because the mutation says less than the name
        suggests: this guard is **backstopped in every configuration a worker
        can reach**. An empty `from` cannot equal a non-empty registry
        reviewer lane, so `from conflicts with registry reviewer lane` catches
        it; and if the registry lane is empty too, `must come from the
        configured review_model` catches that. Deleting this clause therefore
        changes the *diagnostic*, not the *outcome* -- the observed mutant
        refusal is `... from conflicts with registry reviewer lane:
        expected=gpt-codex observed=`.

        The test is kept for what it does control: an anonymous review is
        refused, and it is refused with the message that names the actual
        defect rather than one that misdescribes it as a lane mismatch.
        """
        ok = "TASK-2026-08-30-standard-author-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-AUTHOR-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        anon = "TASK-2026-08-30-standard-author-missing"
        state, env, ref = self._standard_case(
            anon,
            "departments/coding/outbox/TASK-STD-AUTHOR-NONE-response.md",
            **{"from": ""},
        )
        refused = self.run_settle(env, anon, ref, expected_returncode=2)
        self.assertIn("standard review response is missing from", refused.stderr)
        self.assertEqual(self.result(state, anon)[0]["status"], "review-required")

    def test_x5_standard_review_author_must_match_registry_reviewer_lane(self):
        """Deleting the `from conflicts with registry reviewer lane` clause of
        `_validate_standard_review` lets a response name a lane other than the
        one the review was dispatched to.

        The registry owns which lane was asked to review; the response's `from`
        is a worker assertion about itself. Without this clause the two are
        never compared, so a lane that was never dispatched settles by
        declaring itself the reviewer -- confirmed by mutation.

        The response declares no `reviewer_family`. That is what isolates this
        clause rather than weakening the test: a declared family would be
        caught one clause later by the family-conflict check, and the fixture
        would be exercising that neighbour instead. Omitting it leaves the
        family derived from the registry lane, which is cross-family and
        passes, so only the lane comparison objects.
        """
        ok = "TASK-2026-08-30-standard-lane-echo-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-LANE-ECHO-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        mismatched = "TASK-2026-08-30-standard-lane-echo-mismatch"
        state, env, ref = self._standard_case(
            mismatched,
            "departments/coding/outbox/TASK-STD-LANE-ECHO-BAD-response.md",
            drop=("reviewer_family",),
            **{"from": "gemini"},
        )
        refused = self.run_settle(env, mismatched, ref, expected_returncode=2)
        self.assertIn(
            "standard review response from conflicts with registry reviewer lane",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, mismatched)[0]["status"], "review-required"
        )

    def test_x6_standard_review_must_come_from_the_assigned_reviewer(self):
        """Names the standard-path `must come from the configured review_model`
        message in full, which no existing test does.

        This one tightens a pin rather than closing a hole, and the
        distinction is worth stating. The guard is already controlled:
        deleting it makes the pre-existing `test_c4` fail (measured
        2026-09-01), so it is not free to regress. But `test_c4:633` asserts
        only `'configured review_model'` -- a fragment that appears in *both*
        this message and `_validate_security_review`'s -- and it fails there
        by falling through to `must be cross-family`, not by observing this
        clause. So the existing control cannot say which path refused, or
        that this clause is what refused.

        The review here is genuinely cross-family to the anthropic author, and
        the response agrees with the registry about its own lane, so every
        other clause passes and only the assigned-reviewer clause objects.
        With the clause deleted this fixture settles outright.
        """
        ok = "TASK-2026-08-30-standard-assigned-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-ASSIGNED-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        unassigned = "TASK-2026-08-30-standard-assigned-other"
        state, env, ref = self._standard_case(
            unassigned,
            "departments/coding/outbox/TASK-STD-ASSIGNED-OTHER-response.md",
            provenance_lane="gemini",
            **{"from": "gemini", "reviewer_family": "google"},
        )
        refused = self.run_settle(env, unassigned, ref, expected_returncode=2)
        self.assertIn(
            "standard review must come from the configured review_model",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, unassigned)[0]["status"], "review-required"
        )

    def test_x7_standard_review_status_must_be_terminal_enough_to_settle(self):
        """Deleting the `status must be complete or needs_review` clause of
        `_validate_standard_review` settles on a review that reached neither.

        This path deliberately admits `needs_review` as well as `complete` --
        a reviewer may land a verdict without closing its own task -- which
        makes the clause easy to read as permissive. It is not: everything
        outside those two, `blocked` included, must not settle.
        """
        ok = "TASK-2026-08-30-standard-status-ok"
        state, env, ref = self._standard_case(
            ok, "departments/coding/outbox/TASK-STD-STATUS-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # needs_review is the deliberately-admitted second value: it settles,
        # which is what makes the refusal below attributable to the status
        # itself rather than to the clause being a blanket terminal check.
        lenient = "TASK-2026-08-30-standard-status-needs-review"
        state, env, ref = self._standard_case(
            lenient,
            "departments/coding/outbox/TASK-STD-STATUS-NR-response.md",
            status="needs_review",
        )
        self.run_settle(env, lenient, ref)
        self.assertEqual(self.result(state, lenient)[0]["status"], "complete")

        blocked = "TASK-2026-08-30-standard-status-blocked"
        state, env, ref = self._standard_case(
            blocked,
            "departments/coding/outbox/TASK-STD-STATUS-BLOCKED-response.md",
            status="blocked",
        )
        refused = self.run_settle(env, blocked, ref, expected_returncode=2)
        self.assertIn(
            "standard review status must be complete or needs_review",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, blocked)[0]["status"], "review-required"
        )

    def test_y1_factual_attestation_family_must_be_derived_from_the_lane(self):
        """Deleting the `has invalid reviewer_family` clause of
        `_validate_factual_attestation` lets a same-family review declare
        itself cross-family and settle.

        This does not merely settle one task wrongly -- it defeats the
        cross-family requirement as a property. The clause immediately below
        it consumes `reviewer_family`, and on this path that variable holds
        the value the artifact *declared* about itself, not one derived from
        the lane. This clause is the only thing binding the two. Replace it
        with `if False:` and an attestation whose task and reviewer are both
        openai declares `reviewer_family: anthropic`, the anti-affinity clause
        compares the lie against the author family, and it passes.

        Note the asymmetry with `_validate_security_review`, which derives the
        family it compares and merely *echo-checks* the declared one; see
        `test_y2`. The factual path trusts the declaration, which makes this
        clause materially more load-bearing than its security-path twin.
        """
        # Positive control: an honest cross-family attestation still settles.
        ok = "TASK-2026-08-30-factual-family-ok"
        state, env, ref = self._factual_case(
            ok, "departments/coding/outbox/TASK-ATT-FAMILY-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # Author and reviewer are both openai. The attestation says otherwise.
        forged = "TASK-2026-08-30-factual-family-forged"
        state, env, ref = self._factual_case(
            forged,
            "departments/coding/outbox/TASK-ATT-FAMILY-FORGED-response.md",
            entry_over={"author_family": "openai"},
            reviewer_family="anthropic",
        )
        refused = self.run_settle(env, forged, ref, expected_returncode=2)
        self.assertIn(
            "factual coordinator attestation has invalid reviewer_family",
            refused.stderr,
        )
        self.assertEqual(
            self.result(state, forged)[0]["status"], "review-required"
        )

    def test_y2_security_review_family_must_be_derivable_from_the_lane(self):
        """Deleting the `has invalid reviewer family` clause of
        `_validate_security_review` lets a lane with no known family settle a
        security finding.

        Reported precisely, because this clause guards two things and only one
        of them is load-bearing:

        - **The `not reviewer_family` half is a real gate.** A reviewer lane
          absent from `LANE_AUTHOR_FAMILY` derives the empty family, and the
          anti-affinity clause below compares `"" == author_family`, which is
          false -- so an unrecognized lane reads as cross-family and settles.
          That is what this test proves by mutation.
        - **The echo half is inert, and that is a documented non-finding.**
          Unlike the factual path, the anti-affinity clause here consumes the
          *derived* family, never the declared one. A review that forges
          `reviewer_family` is still judged on its lane's real family, so
          deleting the clause changes the diagnostic, not the outcome. The
          second assertion below pins that refusal without claiming it
          prevents a settlement.
        """
        ok = "TASK-2026-08-30-security-family-ok"
        state, env, ref = self._security_case(
            ok, "departments/coding/outbox/TASK-SEC-FAMILY-OK-response.md"
        )
        self.run_settle(env, ok, ref)
        self.assertEqual(self.result(state, ok)[0]["status"], "complete")

        # A lane the family map does not know. Its derived family is empty,
        # which is not equal to the author's -- so anti-affinity is satisfied
        # by a lane whose family nobody can name.
        unmapped = "TASK-2026-08-30-security-family-unmapped"
        state, env, ref = self._security_case(
            unmapped,
            "departments/coding/outbox/TASK-SEC-FAMILY-UNMAPPED-response.md",
            entry_over={"review_model": "mistral"},
            drop=("reviewer_family",),
            **{"from": "mistral"},
        )
        refused = self.run_settle(env, unmapped, ref, expected_returncode=2)
        self.assertIn(
            "security-finding review has invalid reviewer family", refused.stderr
        )
        self.assertEqual(
            self.result(state, unmapped)[0]["status"], "review-required"
        )

        # The inert half: a forged echo on a mappable lane is refused here,
        # but the anti-affinity clause would have judged it on the derived
        # family anyway. Kept as a diagnostic control, not a settlement one.
        echoed = "TASK-2026-08-30-security-family-forged-echo"
        state, env, ref = self._security_case(
            echoed,
            "departments/coding/outbox/TASK-SEC-FAMILY-ECHO-response.md",
            reviewer_family="anthropic",
        )
        refused = self.run_settle(env, echoed, ref, expected_returncode=2)
        self.assertIn(
            "security-finding review has invalid reviewer family", refused.stderr
        )
        self.assertEqual(
            self.result(state, echoed)[0]["status"], "review-required"
        )

    def test_v_reopen_uses_fixture_registry_and_derives_rework(self):
        t = "TASK-2026-07-20-fixture-reopen"
        settled = self._entry(
            status="complete",
            completed_at="2026-07-20T01:00:00+00:00",
            review_settled_at="2026-07-20T01:00:00+00:00",
            review_settled_by="chrono-explicit",
            review_ref="departments/coding/archive/TASK-REVIEW-response.md",
            cross_family_review_ref="departments/coding/archive/TASK-REVIEW-response.md",
            verdict="REJECT",
        )
        root, state, env = self.fixture({t: settled}, {})
        self.assertTrue(root.name.startswith("review-enforce-"))

        self.run_reopen(env, t)
        entry, queue = self.result(state, t)
        self.assertEqual(entry["status"], "needs_rework")
        self.assertIsNone(entry["completed_at"])
        self.assertEqual(entry["reopen_count"], 1)
        self.assertEqual(entry["reopen_history"][0]["verdict"], "REJECT")
        self.assertIn("REVIEW-REOPENED", queue)

        before = (state / "active-tasks.json").read_bytes()
        self.run_reopen(env, t)
        self.assertEqual(before, (state / "active-tasks.json").read_bytes())

    def test_w_reopen_allows_explicit_needs_review_target(self):
        t = "TASK-2026-07-20-fixture-reopen-explicit"
        root, state, env = self.fixture(
            {
                t: self._entry(
                    status="complete",
                    completed_at="2026-07-20T01:00:00+00:00",
                    verdict="APPROVE",
                )
            },
            {},
        )
        self.assertTrue(root.name.startswith("review-enforce-"))
        self.run_reopen(env, t, "needs_review")
        entry, _queue = self.result(state, t)
        self.assertEqual(entry["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
