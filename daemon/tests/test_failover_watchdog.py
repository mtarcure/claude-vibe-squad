from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daemon.control_plane import DispatchControlPlane, FailoverRejected
from daemon.failover_watchdog import FailoverWatchdog


def packet(task_id: str, canonical: Path, body: bytes = b"\nDo the exact work.\n") -> bytes:
    return (
        "---\n"
        f"id: {task_id}\n"
        "to_model: claude\n"
        "specialist: ai-engineer\n"
        "source_namespace: coding\n"
        "compatibility_namespace: coding\n"
        f"return_artifact: {canonical}\n"
        "---\n"
    ).encode() + body


def body_bytes(value: bytes) -> bytes:
    lines = value.splitlines(keepends=True)
    closing = next(index for index, line in enumerate(lines[1:], 1) if line.rstrip(b"\r\n") == b"---")
    return b"".join(lines[closing + 1 :])


def initialized(tmp_path: Path, task_id: str, **timers):
    control = DispatchControlPlane(tmp_path / "state")
    canonical = tmp_path / "outbox" / f"{task_id}-response.md"
    redispatch = tmp_path / "inbox" / f"{task_id}.md"
    template = packet(task_id, canonical)
    primary = control.initialize_task(
        task_id=task_id,
        primary_lane="claude",
        backup_lane="gpt-codex",
        lease_owner="primary",
        canonical_artifact_path=canonical,
        packet_template=template,
        redispatch_path=redispatch,
        **timers,
    )
    return control, primary, template, redispatch


def after(attempt: dict, seconds: int) -> datetime:
    return datetime.fromisoformat(attempt["dispatched_at"]).astimezone(UTC) + timedelta(seconds=seconds)


def test_ack_timeout_hard_signal_redispatches_fenced_backup(tmp_path):
    control, primary, template, redispatch = initialized(
        tmp_path, "TASK-hard-ack", dispatch_ack_seconds=45
    )
    dispatched: list[tuple[Path, dict]] = []

    def dispatch(path: Path, attempt: dict) -> bool:
        dispatched.append((path, attempt))
        return True

    watchdog = FailoverWatchdog(
        control,
        dispatcher=dispatch,
        now=lambda: after(primary, 46),
    )
    actions = watchdog.evaluate_task("TASK-hard-ack")

    ledger = control.read("TASK-hard-ack")
    backup = ledger["attempts"][1]
    assert actions[-1]["action"] == "backup_redispatched"
    assert ledger["failover_count"] == 1
    assert backup["generation"] == 2
    assert backup["lane"] == "gpt-codex"
    assert backup["accepted_at"] is not None
    assert len(dispatched) == 1
    assert dispatched[0][0] == redispatch
    assert dispatched[0][1]["attempt_id"] == backup["attempt_id"]
    generated = redispatch.read_bytes()
    assert body_bytes(generated) == body_bytes(template)
    assert b"to_model: gpt-codex\n" in generated
    assert f"return_artifact: {backup['artifact_path']}\n".encode() in generated
    assert f"failover_attempt_id: {backup['attempt_id']}\n".encode() in generated


@pytest.mark.parametrize("event", ["slow", "silent", "unknown"])
def test_ambiguous_runtime_event_surfaces_without_failover(tmp_path, event):
    control, primary, _template, _redispatch = initialized(tmp_path, f"TASK-{event}")
    control.record_runtime_event(
        task_id=f"TASK-{event}", attempt_id=primary["attempt_id"], event=event
    )
    actions = FailoverWatchdog(control, dispatcher=lambda *_: True).evaluate_task(f"TASK-{event}")
    ledger = control.read(f"TASK-{event}")
    assert actions == [{"action": "surfaced", "signal": event, "status": "NEEDS_HUMAN"}]
    assert len(ledger["attempts"]) == 1
    assert ledger["attempts"][0]["terminal_status"] == "NEEDS_HUMAN"


@pytest.mark.parametrize(
    ("timer", "seconds", "expected"),
    [("heartbeat", 31, "missed_heartbeat"), ("soft", 1201, "soft_deadline"), ("hard", 2401, "hard_deadline")],
)
def test_ambiguous_timers_never_redispatch(tmp_path, timer, seconds, expected):
    task_id = f"TASK-{timer}-timer"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    observed = after(primary, seconds)
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="accepted",
        occurred_at=observed if timer != "heartbeat" else after(primary, 0),
    )
    actions = FailoverWatchdog(
        control,
        dispatcher=lambda *_: pytest.fail("ambiguous timer dispatched backup"),
        now=lambda: observed,
    ).evaluate_task(task_id)
    assert actions[-1]["signal"] == expected
    assert actions[-1]["status"] == "NEEDS_HUMAN"
    assert len(control.read(task_id)["attempts"]) == 1


def test_typed_provider_error_redispatches_but_second_hop_is_forbidden(tmp_path):
    task_id = "TASK-one-hop"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="provider_error",
        typed_error=True,
    )
    watchdog = FailoverWatchdog(control, dispatcher=lambda *_: True)
    watchdog.evaluate_task(task_id)
    backup = control.read(task_id)["attempts"][1]
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=backup["attempt_id"],
        event="operational_error",
        typed_error=True,
    )
    watchdog.evaluate_task(task_id)
    ledger = control.read(task_id)
    assert len(ledger["attempts"]) == 2
    assert ledger["failover_count"] == 1
    assert ledger["attempts"][1]["terminal_status"] == "HARD_FAILED"
    with pytest.raises(FailoverRejected, match="hop budget"):
        control.begin_failover(task_id=task_id, lease_owner="third-hop")


def test_confirmed_process_exit_without_artifact_redispatches(tmp_path):
    task_id = "TASK-confirmed-exit"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="process_exit",
        process_confirmed=True,
        valid_artifact=False,
    )
    actions = FailoverWatchdog(control, dispatcher=lambda *_: True).evaluate_task(task_id)
    assert actions[-1]["action"] == "backup_redispatched"
    assert len(control.read(task_id)["attempts"]) == 2


def test_refusal_event_vetoes_later_ack_timeout(tmp_path):
    task_id = "TASK-refusal-veto"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="possible_refusal",
    )
    watchdog = FailoverWatchdog(
        control,
        dispatcher=lambda *_: pytest.fail("refusal dispatched backup"),
        now=lambda: after(primary, 60),
    )
    watchdog.evaluate_task(task_id)
    ledger = control.read(task_id)
    assert ledger["refusal_veto_seen"] is True
    assert len(ledger["attempts"]) == 1


def test_refusal_veto_precedes_hard_event_in_same_sensor_batch(tmp_path):
    task_id = "TASK-refusal-batch-veto"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="provider_error",
        typed_error=True,
    )
    control.record_runtime_event(
        task_id=task_id,
        attempt_id=primary["attempt_id"],
        event="policy_refusal",
    )
    FailoverWatchdog(
        control,
        dispatcher=lambda *_: pytest.fail("batched refusal dispatched backup"),
    ).evaluate_task(task_id)
    ledger = control.read(task_id)
    assert ledger["refusal_veto_seen"] is True
    assert len(ledger["attempts"]) == 1


def test_failed_backup_nudge_is_hard_failed_without_oscillation(tmp_path):
    task_id = "TASK-backup-nudge-fails"
    control, primary, _template, _redispatch = initialized(tmp_path, task_id)
    watchdog = FailoverWatchdog(
        control,
        dispatcher=lambda *_: False,
        now=lambda: after(primary, 46),
    )
    watchdog.evaluate_task(task_id)
    ledger = control.read(task_id)
    assert len(ledger["attempts"]) == 2
    assert ledger["attempts"][1]["terminal_signal"] == "dispatch_ack_failure"
    assert ledger["attempts"][1]["terminal_status"] == "HARD_FAILED"
    watchdog.evaluate_task(task_id)
    assert len(control.read(task_id)["attempts"]) == 2
