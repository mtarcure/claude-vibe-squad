from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daemon.control_plane import (
    DispatchControlPlane,
    FailoverRejected,
    PublicationRejected,
    atomic_write_bytes,
)


def response(task_id: str, body: str = "ok") -> bytes:
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        "status: completed\n"
        "---\n\n"
        f"{body}\n"
    ).encode()


def initialized(tmp_path: Path, task_id: str = "TASK-lease"):
    control = DispatchControlPlane(tmp_path / "control")
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    attempt = control.initialize_task(
        task_id=task_id,
        primary_lane="claude",
        backup_lane="gpt-codex",
        lease_owner="wrapper-primary",
        canonical_artifact_path=canonical,
    )
    return control, canonical, attempt


def test_lease_exclusivity_is_durable_and_deduplicated(tmp_path):
    control, canonical, initial = initialized(tmp_path)

    def acquire():
        return control.initialize_task(
            task_id="TASK-lease",
            primary_lane="claude",
            backup_lane="gpt-codex",
            lease_owner="duplicate-dispatch",
            canonical_artifact_path=canonical,
        )["attempt_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        attempt_ids = list(pool.map(lambda _index: acquire(), range(16)))

    ledger = control.read("TASK-lease")
    assert set(attempt_ids) == {initial["attempt_id"]}
    assert len(ledger["attempts"]) == 1
    assert ledger["attempts"][0]["lease_owner"] == "wrapper-primary"


def test_generation_fencing_prevents_late_primary_clobber(tmp_path):
    control, canonical, primary = initialized(tmp_path, "TASK-fence")
    assert control.record_terminal_signal(
        task_id="TASK-fence",
        attempt_id=primary["attempt_id"],
        signal="process_exit",
        process_confirmed=True,
        valid_artifact=False,
    ) == "HARD_FAILED"
    backup = control.begin_failover(task_id="TASK-fence", lease_owner="wrapper-backup")
    assert backup["generation"] == 2

    atomic_write_bytes(Path(primary["artifact_path"]), response("TASK-fence", "late primary"))
    with pytest.raises(PublicationRejected, match="generation-fenced"):
        control.publish_attempt(task_id="TASK-fence", attempt_id=primary["attempt_id"])
    assert not canonical.exists()

    atomic_write_bytes(Path(backup["artifact_path"]), response("TASK-fence", "backup winner"))
    assert control.publish_attempt(task_id="TASK-fence", attempt_id=backup["attempt_id"]) == canonical
    assert b"backup winner" in canonical.read_bytes()

    with pytest.raises(PublicationRejected):
        control.publish_attempt(task_id="TASK-fence", attempt_id=primary["attempt_id"])
    assert b"backup winner" in canonical.read_bytes()


@pytest.mark.parametrize("signal", ["slow", "silent", "missed_heartbeat", "soft_deadline", "hard_deadline", "unknown"])
def test_ambiguous_signals_surface_and_never_fail_over(tmp_path, signal):
    task_id = f"TASK-{signal}"
    control, _canonical, attempt = initialized(tmp_path, task_id)
    status = control.record_terminal_signal(task_id=task_id, attempt_id=attempt["attempt_id"], signal=signal)
    assert status == "NEEDS_HUMAN"
    with pytest.raises(FailoverRejected, match="requires HARD_FAILED"):
        control.begin_failover(task_id=task_id, lease_owner="backup")
    assert len(control.read(task_id)["attempts"]) == 1


@pytest.mark.parametrize("signal", ["safety_refusal", "policy_refusal", "possible_refusal"])
def test_refusal_and_possible_refusal_never_cross_family(tmp_path, signal):
    task_id = f"TASK-{signal}"
    control, _canonical, attempt = initialized(tmp_path, task_id)
    status = control.record_terminal_signal(task_id=task_id, attempt_id=attempt["attempt_id"], signal=signal)
    assert status in {"REFUSED", "POSSIBLE_REFUSAL"}
    with pytest.raises(FailoverRejected):
        control.begin_failover(task_id=task_id, lease_owner="backup")


def test_late_primary_refusal_vetoes_an_already_started_backup(tmp_path):
    control, canonical, primary = initialized(tmp_path, "TASK-late-refusal")
    control.record_terminal_signal(
        task_id="TASK-late-refusal",
        attempt_id=primary["attempt_id"],
        signal="process_exit",
        process_confirmed=True,
    )
    backup = control.begin_failover(task_id="TASK-late-refusal", lease_owner="backup")
    assert control.record_terminal_signal(
        task_id="TASK-late-refusal",
        attempt_id=primary["attempt_id"],
        signal="safety_refusal",
    ) == "REFUSED"
    atomic_write_bytes(Path(backup["artifact_path"]), response("TASK-late-refusal"))
    with pytest.raises(PublicationRejected, match="refusal veto"):
        control.publish_attempt(task_id="TASK-late-refusal", attempt_id=backup["attempt_id"])
    assert not canonical.exists()


def test_untyped_provider_error_surfaces_but_typed_error_can_fail_over(tmp_path):
    control, _canonical, untyped = initialized(tmp_path, "TASK-untyped")
    assert control.record_terminal_signal(
        task_id="TASK-untyped", attempt_id=untyped["attempt_id"], signal="provider_error"
    ) == "NEEDS_HUMAN"
    with pytest.raises(FailoverRejected):
        control.begin_failover(task_id="TASK-untyped", lease_owner="backup")

    control2, _canonical2, typed = initialized(tmp_path, "TASK-typed")
    assert control2.record_terminal_signal(
        task_id="TASK-typed",
        attempt_id=typed["attempt_id"],
        signal="provider_error",
        typed_error=True,
    ) == "HARD_FAILED"
    assert control2.begin_failover(task_id="TASK-typed", lease_owner="backup")["lane"] == "gpt-codex"


def test_dispatch_ack_failure_is_hard_but_process_exit_with_artifact_is_not(tmp_path):
    control, _canonical, ack = initialized(tmp_path, "TASK-ack")
    assert control.record_terminal_signal(
        task_id="TASK-ack", attempt_id=ack["attempt_id"], signal="dispatch_ack_failure"
    ) == "HARD_FAILED"
    assert control.begin_failover(task_id="TASK-ack", lease_owner="backup")["generation"] == 2

    control2, _canonical2, exited = initialized(tmp_path, "TASK-exit-with-artifact")
    assert control2.record_terminal_signal(
        task_id="TASK-exit-with-artifact",
        attempt_id=exited["attempt_id"],
        signal="process_exit",
        process_confirmed=True,
        valid_artifact=True,
    ) == "NEEDS_HUMAN"
    with pytest.raises(FailoverRejected):
        control2.begin_failover(task_id="TASK-exit-with-artifact", lease_owner="backup")


def gate(subject: bytes, status: str = "PASS", subject_hash: str | None = None) -> dict:
    return {
        "gate_type": "truth",
        "gate_version": "1",
        "subject_id": "subject-1",
        "subject_hash": subject_hash or hashlib.sha256(subject).hexdigest(),
        "subject_version": "1",
        "status": status,
        "evidence_refs": ["evidence-1"],
        "unresolved_items": [],
        "specialist": "content-verifier",
        "reviewer": "reviewer-1",
        "completed_at": "2026-07-13T00:00:00Z",
        "override_actor": "none",
        "override_reason": "none",
    }


def test_publication_gate_rejects_stale_subject_hash(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-stale")
    artifact = response("TASK-stale")
    subject = b"content after review"
    atomic_write_bytes(Path(attempt["artifact_path"]), artifact)
    stale = gate(subject, subject_hash=hashlib.sha256(b"content before review").hexdigest())
    with pytest.raises(PublicationRejected, match="stale"):
        control.publish_attempt(
            task_id="TASK-stale",
            attempt_id=attempt["attempt_id"],
            gate_required=True,
            gate_record=stale,
            subject=subject,
        )
    assert not canonical.exists()


@pytest.mark.parametrize("status", ["HOLD", "FAIL"])
def test_publication_gate_rejects_non_pass(tmp_path, status):
    task_id = f"TASK-gate-{status.lower()}"
    control, canonical, attempt = initialized(tmp_path, task_id)
    subject = b"release subject"
    atomic_write_bytes(Path(attempt["artifact_path"]), response(task_id))
    with pytest.raises(PublicationRejected, match="not PASS"):
        control.publish_attempt(
            task_id=task_id,
            attempt_id=attempt["attempt_id"],
            gate_required=True,
            gate_record=gate(subject, status=status),
            subject=subject,
        )
    assert not canonical.exists()


def test_valid_gate_publishes_and_records_hash(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-gate-pass")
    artifact = response("TASK-gate-pass")
    subject = b"approved release subject"
    atomic_write_bytes(Path(attempt["artifact_path"]), artifact)
    control.publish_attempt(
        task_id="TASK-gate-pass",
        attempt_id=attempt["attempt_id"],
        gate_required=True,
        gate_record=gate(subject),
        subject=subject,
    )
    ledger = control.read("TASK-gate-pass")
    assert canonical.read_bytes() == artifact
    assert ledger["winner_attempt_id"] == attempt["attempt_id"]
    assert ledger["attempts"][0]["artifact_hash"] == hashlib.sha256(artifact).hexdigest()

    atomic_write_bytes(Path(attempt["artifact_path"]), response("TASK-gate-pass", "mutated after publish"))
    with pytest.raises(PublicationRejected, match="mutated"):
        control.publish_attempt(task_id="TASK-gate-pass", attempt_id=attempt["attempt_id"])
    assert canonical.read_bytes() == artifact


def test_mailbox_cli_rewrites_to_staging_then_publishes(tmp_path):
    task_id = "TASK-cli"
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    task_file = tmp_path / f"{task_id}.md"
    task_file.write_text(
        "---\n"
        f"id: {task_id}\n"
        f"return_artifact: {canonical}\n"
        "to_model: claude\n"
        "---\n\nTask body\n"
    )
    cli = Path(__file__).resolve().parents[2] / "bin" / "failover-control.py"
    init = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--state-root",
            str(tmp_path / "control"),
            "init-dispatch",
            "--task-file",
            str(task_file),
            "--primary-lane",
            "claude",
            "--backup-lane",
            "gpt-codex",
            "--lease-owner",
            "test-wrapper",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    attempt = json.loads(init.stdout)
    staging = Path(attempt["artifact_path"])
    assert f"return_artifact: {staging}" in task_file.read_text()
    assert str(canonical) not in task_file.read_text()

    atomic_write_bytes(staging, response(task_id, "published by controller"))
    subprocess.run(
        [
            sys.executable,
            str(cli),
            "--state-root",
            str(tmp_path / "control"),
            "publish",
            "--artifact",
            str(staging),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert b"published by controller" in canonical.read_bytes()
