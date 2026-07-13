#!/usr/bin/env python3
"""CLI bridge between mailbox shell scripts and daemon.control_plane."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from daemon.control_plane import (  # noqa: E402
    ControlPlaneError,
    DispatchControlPlane,
    atomic_write_bytes,
    validate_publication_gate,
)


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ControlPlaneError(f"task packet has no YAML frontmatter: {path}")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ControlPlaneError("task packet frontmatter must be a mapping")
    return data


def _rewrite_return_artifact(path: Path, staging: str) -> None:
    text = path.read_text()
    rewritten, count = re.subn(
        r"(?m)^return_artifact:[^\n]*$",
        f"return_artifact: {staging}",
        text,
        count=1,
    )
    if count != 1:
        raise ControlPlaneError("task packet must contain exactly one return_artifact field")
    atomic_write_bytes(path, rewritten.encode())


def _json_file(path: str | None) -> dict | None:
    if not path:
        return None
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ControlPlaneError(f"JSON record must be an object: {path}")
    return value


def command_init(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    task_file = Path(args.task_file).expanduser().resolve()
    packet_template = task_file.read_bytes()
    metadata = _frontmatter(task_file)
    task_id = str(metadata.get("id") or "")
    canonical = str(metadata.get("return_artifact") or "")
    if not task_id:
        raise ControlPlaneError("task packet requires id")
    if args.primary_lane == "none":
        return {"task_id": task_id, "status": "skipped", "reason": "to_model:none"}
    if not canonical:
        return {"task_id": task_id, "status": "skipped", "reason": "missing-return-artifact"}
    packet_gate_required = metadata.get("publication_gate_required", metadata.get("gate_required", False))
    if not isinstance(packet_gate_required, bool):
        raise ControlPlaneError("publication_gate_required/gate_required must be a boolean")
    namespace = str(metadata.get("compatibility_namespace") or metadata.get("source_namespace") or "")
    if args.redispatch_path:
        redispatch_path = Path(args.redispatch_path).expanduser().resolve()
    elif namespace:
        redispatch_path = REPO / "departments" / namespace / "inbox" / f"{task_id}.md"
    else:
        redispatch_path = task_file
    attempt = control.initialize_task(
        task_id=task_id,
        primary_lane=args.primary_lane,
        backup_lane=args.backup_lane,
        lease_owner=args.lease_owner,
        canonical_artifact_path=canonical,
        lease_seconds=args.lease_seconds,
        effective_model=args.effective_model,
        gate_required=bool(args.gate_required or packet_gate_required),
        gate_record_path=metadata.get("publication_gate_record"),
        gate_subject_path=metadata.get("publication_gate_subject"),
        quiescence_seconds=args.quiescence_seconds,
        packet_template=packet_template,
        redispatch_path=redispatch_path,
        dispatch_ack_seconds=args.dispatch_ack_seconds,
        heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
        soft_deadline_seconds=args.soft_deadline_seconds,
        hard_deadline_seconds=args.hard_deadline_seconds,
    )
    _rewrite_return_artifact(task_file, attempt["artifact_path"])
    return attempt


def command_signal(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    status = control.record_terminal_signal(
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        signal=args.signal,
        typed_error=args.typed_error,
        process_confirmed=args.process_confirmed,
        valid_artifact=args.valid_artifact,
    )
    result = {"task_id": args.task_id, "attempt_id": args.attempt_id, "terminal_status": status}
    if args.auto_failover:
        if status != "HARD_FAILED":
            result["failover"] = "not_allowed"
        else:
            backup = control.begin_failover(
                task_id=args.task_id,
                lease_owner=args.lease_owner,
                lease_seconds=args.lease_seconds,
                effective_model=args.effective_model,
            )
            result["failover_attempt"] = backup
            if args.redispatch:
                packet = control.prepare_backup_redispatch(
                    task_id=args.task_id, attempt_id=backup["attempt_id"]
                )
                result["redispatch_path"] = str(packet)
                if args.nudge:
                    completed = subprocess.run(
                        ["bash", str(REPO / "bin" / "nudge-task.sh"), str(packet)],
                        cwd=REPO,
                        env={**os.environ, "VAULT_ROOT": str(REPO)},
                        check=False,
                    )
                    result["dispatch_accepted"] = completed.returncode == 0
                    if completed.returncode == 0:
                        control.record_runtime_event(
                            task_id=args.task_id,
                            attempt_id=backup["attempt_id"],
                            event="accepted",
                        )
                    else:
                        control.record_terminal_signal(
                            task_id=args.task_id,
                            attempt_id=backup["attempt_id"],
                            signal="dispatch_ack_failure",
                        )
    return result


def command_event(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    return control.record_runtime_event(
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        event=args.event,
        typed_error=args.typed_error,
        process_confirmed=args.process_confirmed,
        valid_artifact=args.valid_artifact,
        process_pid=args.process_pid,
    )


def command_failover(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    return control.begin_failover(
        task_id=args.task_id,
        lease_owner=args.lease_owner,
        lease_seconds=args.lease_seconds,
        effective_model=args.effective_model,
    )


def _ids_from_staging(path: Path) -> tuple[str, str]:
    if path.suffix != ".md" or len(path.parts) < 2:
        raise ControlPlaneError("staging path must end in <task_id>/<attempt_id>.md")
    return path.parent.name, path.stem


def command_publish(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    artifact = Path(args.artifact).expanduser().resolve()
    task_id, attempt_id = _ids_from_staging(artifact)
    override = None
    if args.override_actor or args.override_reason or args.operator_authorized:
        override = {
            "authorized": args.operator_authorized,
            "actor": args.override_actor,
            "reason": args.override_reason,
        }
    canonical = control.publish_attempt(
        task_id=task_id,
        attempt_id=attempt_id,
        artifact_path=artifact,
        gate_required=args.gate_required,
        gate_record=_json_file(args.gate_record),
        subject=Path(args.subject).read_bytes() if args.subject else None,
        operator_override=override,
    )
    return {"task_id": task_id, "attempt_id": attempt_id, "canonical_artifact_path": str(canonical)}


def command_gate_check(args: argparse.Namespace, _control: DispatchControlPlane) -> dict:
    record = _json_file(args.gate_record)
    validate_publication_gate(Path(args.subject).read_bytes(), record)
    return {"gate": "PASS", "subject": str(Path(args.subject).resolve())}


def command_operator_unlock(args: argparse.Namespace, control: DispatchControlPlane) -> dict:
    return control.operator_unlock(
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        actor=args.actor,
        reason=args.reason,
        approve_publish=args.approve_publish,
        clear_refusal_veto=args.clear_refusal_veto,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", help="override _state/failover root")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-dispatch", help="create the primary lease and rewrite packet output to staging")
    init.add_argument("--task-file", required=True)
    init.add_argument("--primary-lane", required=True)
    init.add_argument("--backup-lane", required=True)
    init.add_argument("--lease-owner", required=True)
    init.add_argument("--lease-seconds", type=int, default=1800)
    init.add_argument("--effective-model")
    init.add_argument("--gate-required", action="store_true")
    init.add_argument("--quiescence-seconds", type=float, default=5.0)
    init.add_argument("--redispatch-path")
    init.add_argument("--dispatch-ack-seconds", type=int, default=45)
    init.add_argument("--heartbeat-timeout-seconds", type=int, default=30)
    init.add_argument("--soft-deadline-seconds", type=int, default=1200)
    init.add_argument("--hard-deadline-seconds", type=int, default=2400)
    init.set_defaults(handler=command_init)

    signal = sub.add_parser("signal", help="record a typed or ambiguous terminal observation")
    signal.add_argument("--task-id", required=True)
    signal.add_argument("--attempt-id", required=True)
    signal.add_argument("--signal", required=True)
    signal.add_argument("--typed-error", action="store_true")
    signal.add_argument("--process-confirmed", action="store_true")
    signal.add_argument("--valid-artifact", action="store_true")
    signal.add_argument("--auto-failover", action="store_true")
    signal.add_argument("--redispatch", action="store_true")
    signal.add_argument("--nudge", action="store_true")
    signal.add_argument("--lease-owner", default="chrono-control-plane")
    signal.add_argument("--lease-seconds", type=int, default=1800)
    signal.add_argument("--effective-model")
    signal.set_defaults(handler=command_signal)

    event = sub.add_parser("event", help="persist an accepted, heartbeat, or runtime sensor event")
    event.add_argument("--task-id", required=True)
    event.add_argument("--attempt-id", required=True)
    event.add_argument("--event", required=True)
    event.add_argument("--typed-error", action="store_true")
    event.add_argument("--process-confirmed", action="store_true")
    event.add_argument("--valid-artifact", action="store_true")
    event.add_argument("--process-pid", type=int)
    event.set_defaults(handler=command_event)

    failover = sub.add_parser("failover", help="CAS-advance to the backup after a hard terminal signal")
    failover.add_argument("--task-id", required=True)
    failover.add_argument("--lease-owner", required=True)
    failover.add_argument("--lease-seconds", type=int, default=1800)
    failover.add_argument("--effective-model")
    failover.set_defaults(handler=command_failover)

    publish = sub.add_parser("publish", help="validate and CAS-publish an attempt staging artifact")
    publish.add_argument("--artifact", required=True)
    publish.add_argument("--gate-required", action="store_true")
    publish.add_argument("--gate-record")
    publish.add_argument("--subject")
    publish.add_argument("--operator-authorized", action="store_true")
    publish.add_argument("--override-actor")
    publish.add_argument("--override-reason")
    publish.set_defaults(handler=command_publish)

    gate = sub.add_parser("gate-check", help="validate a release subject against its gate record")
    gate.add_argument("--subject", required=True)
    gate.add_argument("--gate-record", required=True)
    gate.set_defaults(handler=command_gate_check)

    unlock = sub.add_parser("operator-unlock", help="audit a human decision to unlock a surfaced attempt")
    unlock.add_argument("--task-id", required=True)
    unlock.add_argument("--attempt-id", required=True)
    unlock.add_argument("--actor", required=True)
    unlock.add_argument("--reason", required=True)
    unlock.add_argument("--approve-publish", action="store_true")
    unlock.add_argument("--clear-refusal-veto", action="store_true")
    unlock.set_defaults(handler=command_operator_unlock)

    inspect = sub.add_parser("inspect", help="read one durable ledger")
    inspect.add_argument("--task-id", required=True)
    inspect.set_defaults(handler=lambda args, control: control.read(args.task_id))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.handler(args, DispatchControlPlane(args.state_root))
    except (ControlPlaneError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
