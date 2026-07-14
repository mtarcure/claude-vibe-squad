from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daemon.control_plane import (
    ControlPlaneError,
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


def stage(path: Path, data: bytes, age_seconds: float = 6.0) -> None:
    atomic_write_bytes(path, data)
    quiescent_time = time.time() - age_seconds
    os.utime(path, (quiescent_time, quiescent_time))


def initialized(tmp_path: Path, task_id: str = "TASK-lease", **options):
    control = DispatchControlPlane(tmp_path / "control")
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    attempt = control.initialize_task(
        task_id=task_id,
        primary_lane="claude",
        backup_lane="gpt-codex",
        lease_owner="wrapper-primary",
        canonical_artifact_path=canonical,
        **options,
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

    stage(Path(primary["artifact_path"]), response("TASK-fence", "late primary"))
    with pytest.raises(PublicationRejected, match="generation-fenced"):
        control.publish_attempt(task_id="TASK-fence", attempt_id=primary["attempt_id"])
    assert not canonical.exists()

    stage(Path(backup["artifact_path"]), response("TASK-fence", "backup winner"))
    assert control.publish_attempt(task_id="TASK-fence", attempt_id=backup["attempt_id"]) == canonical
    assert b"backup winner" in canonical.read_bytes()

    with pytest.raises(PublicationRejected):
        control.publish_attempt(task_id="TASK-fence", attempt_id=primary["attempt_id"])
    assert b"backup winner" in canonical.read_bytes()


@pytest.mark.parametrize("signal", ["slow", "silent", "missed_heartbeat", "soft_deadline", "hard_deadline", "unknown"])
def test_ambiguous_signals_surface_and_never_fail_over(tmp_path, signal):
    task_id = f"TASK-{signal}"
    control, canonical, attempt = initialized(tmp_path, task_id)
    status = control.record_terminal_signal(task_id=task_id, attempt_id=attempt["attempt_id"], signal=signal)
    assert status == "NEEDS_HUMAN"
    with pytest.raises(FailoverRejected, match="requires HARD_FAILED"):
        control.begin_failover(task_id=task_id, lease_owner="backup")
    surfaced = control.read(task_id)["attempts"][0]
    assert surfaced["terminal_status"] is None
    assert surfaced["surface_status"] == "NEEDS_HUMAN"
    assert surfaced["surface_signal"] == signal

    stage(Path(attempt["artifact_path"]), response(task_id, "completed after soft surface"))
    control.publish_attempt(task_id=task_id, attempt_id=attempt["attempt_id"])
    completed = control.read(task_id)["attempts"][0]
    assert completed["terminal_status"] == "SUCCEEDED"
    assert completed["surface_status"] is None
    assert completed["surface_history"][-1]["signal"] == signal
    assert b"completed after soft surface" in canonical.read_bytes()


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
    stage(Path(backup["artifact_path"]), response("TASK-late-refusal"))
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
    surfaced = control2.read("TASK-exit-with-artifact")["attempts"][0]
    assert surfaced["terminal_status"] is None
    assert surfaced["surface_signal"] == "process_exit"
    with pytest.raises(FailoverRejected):
        control2.begin_failover(task_id="TASK-exit-with-artifact", lease_owner="backup")


def test_staging_must_be_quiescent_before_winner_is_frozen(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-quiescence")
    staging = Path(attempt["artifact_path"])
    atomic_write_bytes(staging, response("TASK-quiescence", "frontmatter landed, body still streaming"))
    with pytest.raises(PublicationRejected, match="not quiescent"):
        control.publish_attempt(task_id="TASK-quiescence", attempt_id=attempt["attempt_id"])
    assert not canonical.exists()
    assert control.read("TASK-quiescence")["winner_attempt_id"] is None

    stage(staging, response("TASK-quiescence", "complete response"))
    control.publish_attempt(task_id="TASK-quiescence", attempt_id=attempt["attempt_id"])
    assert b"complete response" in canonical.read_bytes()


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
    control, canonical, attempt = initialized(tmp_path, "TASK-stale", gate_required=True)
    artifact = response("TASK-stale")
    subject = b"content after review"
    stage(Path(attempt["artifact_path"]), artifact)
    stale = gate(subject, subject_hash=hashlib.sha256(b"content before review").hexdigest())
    with pytest.raises(PublicationRejected, match="stale"):
        control.publish_attempt(
            task_id="TASK-stale",
            attempt_id=attempt["attempt_id"],
            gate_record=stale,
            subject=subject,
        )
    assert not canonical.exists()


@pytest.mark.parametrize("status", ["HOLD", "FAIL"])
def test_publication_gate_rejects_non_pass(tmp_path, status):
    task_id = f"TASK-gate-{status.lower()}"
    control, canonical, attempt = initialized(tmp_path, task_id, gate_required=True)
    subject = b"release subject"
    stage(Path(attempt["artifact_path"]), response(task_id))
    with pytest.raises(PublicationRejected, match="not PASS"):
        control.publish_attempt(
            task_id=task_id,
            attempt_id=attempt["attempt_id"],
            gate_record=gate(subject, status=status),
            subject=subject,
        )
    assert not canonical.exists()


def test_valid_gate_publishes_and_records_hash(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-gate-pass", gate_required=True)
    artifact = response("TASK-gate-pass")
    subject = b"approved release subject"
    stage(Path(attempt["artifact_path"]), artifact)
    control.publish_attempt(
        task_id="TASK-gate-pass",
        attempt_id=attempt["attempt_id"],
        gate_record=gate(subject),
        subject=subject,
    )
    ledger = control.read("TASK-gate-pass")
    assert canonical.read_bytes() == artifact
    assert ledger["winner_attempt_id"] == attempt["attempt_id"]
    assert ledger["attempts"][0]["artifact_hash"] == hashlib.sha256(artifact).hexdigest()

    stage(Path(attempt["artifact_path"]), response("TASK-gate-pass", "mutated after publish"))
    with pytest.raises(PublicationRejected, match="mutated"):
        control.publish_attempt(task_id="TASK-gate-pass", attempt_id=attempt["attempt_id"])
    assert canonical.read_bytes() == artifact


def test_ledger_gate_requirement_rejects_missing_record_without_caller_flag(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-gate-missing", gate_required=True)
    subject = b"gated subject"
    stage(Path(attempt["artifact_path"]), response("TASK-gate-missing"))
    with pytest.raises(PublicationRejected, match="publication gate is required"):
        control.publish_attempt(
            task_id="TASK-gate-missing",
            attempt_id=attempt["attempt_id"],
            subject=subject,
        )
    assert not canonical.exists()


def test_ledger_gate_requirement_rejects_missing_fields(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-gate-fields", gate_required=True)
    subject = b"gated subject"
    incomplete = gate(subject)
    incomplete.pop("reviewer")
    stage(Path(attempt["artifact_path"]), response("TASK-gate-fields"))
    with pytest.raises(PublicationRejected, match="missing fields: reviewer"):
        control.publish_attempt(
            task_id="TASK-gate-fields",
            attempt_id=attempt["attempt_id"],
            gate_record=incomplete,
            subject=subject,
        )
    assert not canonical.exists()


def test_primary_backup_collision_degrades_to_no_backup(tmp_path):
    control = DispatchControlPlane(tmp_path / "control")
    attempt = control.initialize_task(
        task_id="TASK-collision",
        primary_lane="claude",
        backup_lane="claude",
        lease_owner="override",
        canonical_artifact_path=tmp_path / "outbox" / "TASK-collision-response.md",
    )
    ledger = control.read("TASK-collision")
    assert ledger["backup_lane"] == "none"
    control.record_terminal_signal(
        task_id="TASK-collision", attempt_id=attempt["attempt_id"], signal="dispatch_ack_failure"
    )
    with pytest.raises(FailoverRejected, match="no configured backup"):
        control.begin_failover(task_id="TASK-collision", lease_owner="backup")


def test_soft_surface_valid_completion_supersedes_without_operator_unlock(tmp_path):
    control, canonical, attempt = initialized(tmp_path, "TASK-soft-superseded")
    control.record_terminal_signal(
        task_id="TASK-soft-superseded", attempt_id=attempt["attempt_id"], signal="missed_heartbeat"
    )
    stage(Path(attempt["artifact_path"]), response("TASK-soft-superseded", "finished normally"))
    control.publish_attempt(task_id="TASK-soft-superseded", attempt_id=attempt["attempt_id"])
    ledger = control.read("TASK-soft-superseded")
    assert ledger["winner_attempt_id"] == attempt["attempt_id"]
    assert ledger["attempts"][0]["terminal_status"] == "SUCCEEDED"
    assert ledger["audit_events"][-1]["type"] == "surface_superseded_by_valid_artifact"
    assert b"finished normally" in canonical.read_bytes()


def test_legacy_terminal_soft_surface_is_migrated_and_publishable(tmp_path):
    task_id = "TASK-legacy-soft-terminal"
    control, canonical, attempt = initialized(tmp_path, task_id)
    ledger_path = control.ledger_path(task_id)
    ledger = json.loads(ledger_path.read_text())
    ledger["attempts"][0]["terminal_status"] = "NEEDS_HUMAN"
    ledger["attempts"][0]["terminal_signal"] = "missed_heartbeat"
    ledger_path.write_text(json.dumps(ledger))

    stage(Path(attempt["artifact_path"]), response(task_id, "recovered stranded completion"))
    control.publish_attempt(task_id=task_id, attempt_id=attempt["attempt_id"])
    recovered = control.read(task_id)["attempts"][0]
    assert recovered["terminal_status"] == "SUCCEEDED"
    assert recovered["surface_history"][-1]["migrated_from_terminal"] is True
    assert b"recovered stranded completion" in canonical.read_bytes()


def test_operator_can_audit_clear_refusal_veto_for_current_attempt(tmp_path):
    control, _canonical, attempt = initialized(tmp_path, "TASK-unlock-refusal")
    control.record_terminal_signal(
        task_id="TASK-unlock-refusal", attempt_id=attempt["attempt_id"], signal="possible_refusal"
    )
    result = control.operator_unlock(
        task_id="TASK-unlock-refusal",
        attempt_id=attempt["attempt_id"],
        actor="chrono-operator",
        reason="human determined text was not a refusal",
        approve_publish=True,
        clear_refusal_veto=True,
    )
    assert result["refusal_veto_seen"] is False
    assert control.read("TASK-unlock-refusal")["audit_events"][-1]["clear_refusal_veto"] is True


@pytest.mark.parametrize("signal", ["safety_refusal", "policy_refusal"])
def test_operator_cannot_clear_genuine_refusal_veto(tmp_path, signal):
    task_id = f"TASK-inviolable-{signal}"
    control, _canonical, attempt = initialized(tmp_path, task_id)
    control.record_terminal_signal(
        task_id=task_id,
        attempt_id=attempt["attempt_id"],
        signal=signal,
    )
    with pytest.raises(ControlPlaneError, match="cannot be cleared"):
        control.operator_unlock(
            task_id=task_id,
            attempt_id=attempt["attempt_id"],
            actor="chrono-operator",
            reason="attempted genuine-refusal override",
            clear_refusal_veto=True,
        )
    ledger = control.read(task_id)
    assert ledger["refusal_veto_seen"] is True
    assert ledger["safety_refusal_seen"] is True
    assert ledger["attempts"][0]["terminal_status"] == "REFUSED"
    rejection = ledger["audit_events"][-1]
    assert rejection["type"] == "operator_unlock_rejected"
    assert rejection["actor"] == "chrono-operator"
    assert rejection["reason"] == "attempted genuine-refusal override"


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

    stage(staging, response(task_id, "published by controller"))
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


@pytest.mark.parametrize(
    ("primary_lane", "frontmatter_extra", "reason"),
    [
        ("none", "return_artifact: /tmp/unused-response.md\n", "to_model:none"),
        ("claude", "", "missing-return-artifact"),
    ],
)
def test_cli_gracefully_skips_non_dispatch_and_missing_return_artifact(
    tmp_path, primary_lane, frontmatter_extra, reason
):
    task_id = f"TASK-skip-{reason.replace(':', '-')}"
    task_file = tmp_path / f"{task_id}.md"
    task_file.write_text(f"---\nid: {task_id}\n{frontmatter_extra}---\n\nTask body\n")
    cli = Path(__file__).resolve().parents[2] / "bin" / "failover-control.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--state-root",
            str(tmp_path / "control"),
            "init-dispatch",
            "--task-file",
            str(task_file),
            "--primary-lane",
            primary_lane,
            "--backup-lane",
            "none",
            "--lease-owner",
            "test-wrapper",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "skipped"
    assert result["reason"] == reason
    assert list((tmp_path / "control" / "ledgers").glob("*.json")) == []


def test_cli_persists_packet_gate_authority_and_operator_unlock(tmp_path):
    task_id = "TASK-cli-gated"
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    task_file = tmp_path / f"{task_id}.md"
    task_file.write_text(
        "---\n"
        f"id: {task_id}\n"
        f"return_artifact: {canonical}\n"
        "publication_gate_required: true\n"
        "---\n\nTask body\n"
    )
    cli = Path(__file__).resolve().parents[2] / "bin" / "failover-control.py"
    base = [sys.executable, str(cli), "--state-root", str(tmp_path / "control")]
    initialized_result = subprocess.run(
        base
        + [
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
    attempt = json.loads(initialized_result.stdout)
    control = DispatchControlPlane(tmp_path / "control")
    assert control.read(task_id)["gate_required"] is True

    control.record_terminal_signal(
        task_id=task_id, attempt_id=attempt["attempt_id"], signal="possible_refusal"
    )
    unlocked = subprocess.run(
        base
        + [
            "operator-unlock",
            "--task-id",
            task_id,
            "--attempt-id",
            attempt["attempt_id"],
            "--actor",
            "chrono-operator",
            "--reason",
            "manual artifact review",
            "--approve-publish",
            "--clear-refusal-veto",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(unlocked.stdout)["terminal_status"] is None
    assert control.read(task_id)["refusal_veto_seen"] is False
    assert control.read(task_id)["audit_events"][-1]["type"] == "operator_unlock"
