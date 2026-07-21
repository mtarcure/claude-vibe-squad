#!/usr/bin/env python3
"""Hermetic regression tests for delivery/review loop guards."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(tempfile.mkdtemp(prefix="review-loop-guard."))
STATE = FIXTURE / "_state"
OUTBOX = FIXTURE / "departments" / "coding" / "outbox"
STATE.mkdir(parents=True)
OUTBOX.mkdir(parents=True)

os.environ.update(
    {
        "VAULT_ROOT": str(FIXTURE),
        "STATE_DIR": str(STATE),
        "RESPONSE_MIN_AGE_SECONDS": "0",
        "NOTIFICATION_REPEAT_SECONDS": "3600",
        "SQUAD_TEST_ISOLATION": "1",
    }
)

spec = importlib.util.spec_from_file_location(
    "registry_reconciler_under_test", REPO / "scripts" / "python" / "registry_reconciler.py"
)
assert spec and spec.loader
reconciler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconciler)

FACTUAL = "TASK-2099-01-01-1001-factual"
SECURITY = "TASK-2099-01-01-1002-security"
QUEUED = "TASK-2099-01-01-1003-queued"
now = datetime.now(timezone.utc).isoformat()


def task_entry(
    *,
    lane: str,
    family: str,
    review_class: str,
    generation: int,
    state: str = "in-progress",
) -> dict[str, object]:
    return {
        "compatibility_namespace": "coding",
        "specialist": "systems-engineer",
        "to_model": lane,
        "source_namespace": "coding",
        "review_model": "claude",
        "mandatory_review": "true",
        "review_class": review_class,
        "author_family": family,
        "dispatched_at": now,
        "status": "in-flight",
        "delivery_state": state,
        "delivery_attempt_id": f"attempt-{generation}",
        "delivery_generation": generation,
        "delivery_lane": lane,
        "delivery_attempt_count": 1 if state != "queued" else 0,
        "delivery_max_attempts": 5,
        "delivery_next_attempt_at": now,
        "write_scope": [],
    }


registry = {
    FACTUAL: task_entry(
        lane="kimi", family="moonshot", review_class="factual", generation=7
    ),
    SECURITY: task_entry(
        lane="gpt-codex", family="openai", review_class="security-finding", generation=3
    ),
    QUEUED: {
        **task_entry(
            lane="gemini", family="google", review_class="standard", generation=1, state="queued"
        ),
        "mandatory_review": "false",
        "review_model": "none",
    },
}
reconciler.atomic_write(reconciler.REGISTRY_PATH, json.dumps(registry, indent=2) + "\n")


def write_response(task_id: str, body: str = "Fixture result.") -> Path:
    path = OUTBOX / f"{task_id}-response.md"
    reconciler.atomic_write(
        path,
        f"---\nstatus: needs_review\nin_response_to: {task_id}\n---\n\n{body}\n",
    )
    return path


factual_response = write_response(FACTUAL)
security_response = write_response(SECURITY, "Security finding fixture.")

# Explicit factual policy cannot inherit GPT/Codex's in-lane Claude-tool exemption.
factual_in_lane_capable = task_entry(
    lane="gpt-codex", family="openai", review_class="factual", generation=1
)
assert reconciler.cross_family_review_pending(factual_in_lane_capable) == (
    True,
    "gpt-codex",
    "claude",
)

# First reconciliation transitions both tasks to a delivery-terminal review hold.
first_changes, first_messages = reconciler.reconcile(None, False)
assert first_changes > 0, first_messages
held = reconciler.load_registry()
for task_id in (FACTUAL, SECURITY):
    entry = held[task_id]
    assert entry["status"] == reconciler.REVIEW_REQUIRED
    assert entry["delivery_state"] == "terminal"
assert held[FACTUAL]["notification_key"] == f"{FACTUAL}|review-required|7"
assert held[SECURITY]["notification_key"] == f"{SECURITY}|review-required|3"

# A second watcher/reconcile cycle is idempotent for the same state/generation.
queue_before = reconciler.CHRONO_QUEUE_PATH.read_text()
second_changes, second_messages = reconciler.reconcile(None, False)
queue_after = reconciler.CHRONO_QUEUE_PATH.read_text()
assert second_changes == 0, second_messages
assert queue_after == queue_before
assert queue_after.count(f"| REVIEW-REQUIRED | coding/{FACTUAL} |") == 1
assert queue_after.count(f"| REVIEW-REQUIRED | coding/{SECURITY} |") == 1
print("PASS notification dedup keys task/state/generation and suppresses watcher-cycle repeats")

# Terminal review work cannot be authorized, claimed, or advanced to redelivery.
authorization = reconciler.authorize_delivery(FACTUAL)
assert authorization == {
    "authorized": False,
    "reason": "status-review-required",
    "task_id": FACTUAL,
    "attempt_id": "attempt-7",
}
try:
    reconciler.claim_task(FACTUAL, "attempt-7")
except ValueError as exc:
    assert "terminal" in str(exc)
else:
    raise AssertionError("review-required task was claimable")
try:
    reconciler.advance_delivery(FACTUAL, "attempt-8", 8, "kimi")
except ValueError as exc:
    assert "delivery is closed" in str(exc)
else:
    raise AssertionError("review-required task advanced to a new delivery generation")

# Positive control: genuinely queued/unclaimed work still uses bounded delivery and claim receipts.
queued_auth = reconciler.authorize_delivery(QUEUED)
assert queued_auth["authorized"] is True
claim = reconciler.claim_task(QUEUED, "attempt-1")
assert claim["delivery_state"] == "in-progress" and claim["idempotent"] is False
print("PASS only queued in-flight work redelivers; terminal review work cannot authorize/claim/advance")

# Factual coordinator attestation must be controller-authored, cross-family, and response-hash-bound.
factual_hash = hashlib.sha256(factual_response.read_bytes()).hexdigest()
factual_attestation = OUTBOX / "FACTUAL-ATTESTATION-response.md"
reconciler.atomic_write(
    factual_attestation,
    "---\n"
    f"in_response_to: {FACTUAL}\n"
    "from: chrono\n"
    "type: REVIEW_ATTESTATION\n"
    "status: complete\n"
    "review_class: factual\n"
    "reviewer_lane: claude\n"
    "reviewer_family: anthropic\n"
    f"attested_response_sha256: {factual_hash}\n"
    "---\n\nCoordinator checked the factual probe evidence.\n",
)
assert reconciler.settle_review(FACTUAL, str(factual_attestation)) is True
factual_settled = reconciler.load_registry()[FACTUAL]
assert factual_settled["status"] == "complete"
assert factual_settled["review_settled_by"] == "chrono-factual-attestation"
assert reconciler.settle_review(FACTUAL, str(factual_attestation)) is False
print("PASS factual review_class settles idempotently through cross-family coordinator attestation")

# Negative control: the same coordinator path can never settle a security finding.
security_hash = hashlib.sha256(security_response.read_bytes()).hexdigest()
security_attestation = OUTBOX / "SECURITY-ATTESTATION-response.md"
reconciler.atomic_write(
    security_attestation,
    "---\n"
    f"in_response_to: {SECURITY}\n"
    "from: chrono\n"
    "type: REVIEW_ATTESTATION\n"
    "status: complete\n"
    "review_class: factual\n"
    "reviewer_lane: claude\n"
    "reviewer_family: anthropic\n"
    f"attested_response_sha256: {security_hash}\n"
    "---\n",
)
try:
    reconciler.settle_review(SECURITY, str(security_attestation))
except ValueError as exc:
    assert "independent lane review" in str(exc)
else:
    raise AssertionError("coordinator attestation settled a security finding")
assert reconciler.load_registry()[SECURITY]["status"] == reconciler.REVIEW_REQUIRED

independent_review = OUTBOX / "SECURITY-INDEPENDENT-REVIEW-response.md"
reconciler.atomic_write(
    independent_review,
    "---\n"
    f"in_response_to: {SECURITY}\n"
    "from: claude\n"
    "type: RESULT\n"
    "status: complete\n"
    "reviewer_family: anthropic\n"
    f"reviewed_response_sha256: {security_hash}\n"
    "---\n\nIndependent cross-family security review.\n",
)
assert reconciler.settle_review(SECURITY, str(independent_review)) is True
security_settled = reconciler.load_registry()[SECURITY]
assert security_settled["status"] == "complete"
assert security_settled["review_settled_by"] == "chrono-explicit-independent"
print("PASS security-finding rejects coordinator attestation and requires independent cross-family review")

shutil.rmtree(FIXTURE)
print("SELFTEST PASS fixture-cleaned")
