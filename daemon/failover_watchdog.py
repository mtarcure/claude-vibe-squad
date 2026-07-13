#!/usr/bin/env python3
"""Conservative dispatch sensors and one-hop backup redispatch.

The daemon is inert unless FAILOVER_CONTROL_ENABLED=1 or the existing
_state/failover/ENABLED sentinel is present. Ambiguous observations surface for
humans; only a dispatch-ack timeout or confirmed typed operational failure may
advance to the single backup generation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from daemon.control_plane import ControlPlaneError, DispatchControlPlane, FailoverRejected


HARD_RUNTIME_EVENTS = {"provider_error", "operational_error", "process_exit"}
AMBIGUOUS_RUNTIME_EVENTS = {
    "slow",
    "silent",
    "missed_heartbeat",
    "soft_deadline",
    "hard_deadline",
    "unknown",
}
REFUSAL_RUNTIME_EVENTS = {"safety_refusal", "policy_refusal", "possible_refusal"}


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _default_dispatcher(packet: Path, _attempt: dict) -> bool:
    completed = subprocess.run(
        ["bash", str(REPO / "bin" / "nudge-task.sh"), str(packet)],
        cwd=REPO,
        env={**os.environ, "VAULT_ROOT": str(REPO)},
        check=False,
    )
    return completed.returncode == 0


class FailoverWatchdog:
    """Evaluate durable sensor events and deadlines without guessing liveness."""

    def __init__(
        self,
        control: DispatchControlPlane,
        *,
        dispatcher: Callable[[Path, dict], bool] | None = None,
        now: Callable[[], datetime] | None = None,
        lease_owner: str = "failover-watchdog",
    ):
        self.control = control
        self.dispatcher = dispatcher or _default_dispatcher
        self.now = now or (lambda: datetime.now(UTC))
        self.lease_owner = lease_owner

    def _redispatch(self, task_id: str, primary_attempt_id: str) -> dict:
        ledger = self.control.read(task_id)
        primary = next(item for item in ledger["attempts"] if item["attempt_id"] == primary_attempt_id)
        if primary["generation"] != 1 or ledger.get("failover_count", 0) != 0:
            return {"action": "no_failover", "reason": "hop_budget_or_generation"}
        backup = self.control.begin_failover(task_id=task_id, lease_owner=self.lease_owner)
        packet = self.control.prepare_backup_redispatch(task_id=task_id, attempt_id=backup["attempt_id"])
        accepted = self.dispatcher(packet, backup)
        if accepted:
            self.control.record_runtime_event(
                task_id=task_id,
                attempt_id=backup["attempt_id"],
                event="accepted",
            )
        else:
            self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=backup["attempt_id"],
                signal="dispatch_ack_failure",
            )
        return {
            "action": "backup_redispatched",
            "attempt_id": backup["attempt_id"],
            "packet": str(packet),
            "accepted": accepted,
        }

    def _process_event(self, task_id: str, attempt: dict, event: dict) -> dict | None:
        name = event["event"]
        status: str | None = None
        if name in REFUSAL_RUNTIME_EVENTS or name in AMBIGUOUS_RUNTIME_EVENTS:
            status = self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=attempt["attempt_id"],
                signal=name,
            )
        elif name in HARD_RUNTIME_EVENTS:
            status = self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=attempt["attempt_id"],
                signal=name,
                typed_error=bool(event.get("typed_error")),
                process_confirmed=bool(event.get("process_confirmed")),
                valid_artifact=bool(event.get("valid_artifact")),
            )
        else:
            status = self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=attempt["attempt_id"],
                signal="unknown",
            )
        self.control.mark_runtime_event_processed(task_id, attempt["attempt_id"], event["event_id"])
        if status == "HARD_FAILED" and attempt["generation"] == 1:
            return self._redispatch(task_id, attempt["attempt_id"])
        return {"action": "surfaced", "signal": name, "status": status}

    @staticmethod
    def _pid_has_exited(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except (PermissionError, OSError):
            return False
        return False

    def evaluate_task(self, task_id: str) -> list[dict]:
        actions: list[dict] = []
        ledger = self.control.read(task_id)
        if ledger.get("winner_attempt_id"):
            return actions

        # Refusals from an older generation remain a veto, so consume events
        # from every attempt before evaluating the current generation's timers.
        pending = [
            (attempt, event)
            for attempt in ledger["attempts"]
            for event in self.control.pending_runtime_events(task_id, attempt["attempt_id"])
        ]
        # A refusal already present in the durable sensor batch must veto a
        # hard operational event regardless of event arrival ordering.
        pending.sort(key=lambda item: item[1]["event"] not in REFUSAL_RUNTIME_EVENTS)
        for attempt, event in pending:
            result = self._process_event(task_id, attempt, event)
            if result:
                actions.append(result)

        ledger = self.control.read(task_id)
        current = next(
            item for item in ledger["attempts"] if item["attempt_id"] == ledger["current_attempt_id"]
        )
        if ledger.get("winner_attempt_id") or ledger.get("refusal_veto_seen"):
            return actions

        if current.get("terminal_status") not in {None, "NEEDS_HUMAN"}:
            return actions

        pid = current.get("process_pid")
        if pid and current.get("terminal_status") in {None, "NEEDS_HUMAN"} and self._pid_has_exited(int(pid)):
            artifact = Path(current["artifact_path"])
            # Any landed bytes are conservatively surfaced for validation. Only
            # a confirmed exit with no candidate artifact is auto-failable.
            valid_artifact = artifact.exists() and artifact.stat().st_size > 0
            status = self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=current["attempt_id"],
                signal="process_exit",
                process_confirmed=True,
                valid_artifact=valid_artifact,
            )
            if status == "HARD_FAILED" and current["generation"] == 1:
                actions.append(self._redispatch(task_id, current["attempt_id"]))
            else:
                actions.append({"action": "surfaced", "signal": "process_exit", "status": status})
            return actions

        now = self.now()
        dispatched_at = _as_datetime(current["dispatched_at"])
        elapsed = (now - dispatched_at).total_seconds()
        if not current.get("accepted_at") and elapsed >= ledger["dispatch_ack_seconds"]:
            status = self.control.record_terminal_signal(
                task_id=task_id,
                attempt_id=current["attempt_id"],
                signal="dispatch_ack_failure",
            )
            if status == "HARD_FAILED" and current["generation"] == 1:
                actions.append(self._redispatch(task_id, current["attempt_id"]))
            else:
                actions.append({"action": "surfaced", "signal": "dispatch_ack_failure", "status": status})
            return actions

        if current.get("terminal_status") is not None:
            return actions
        if current.get("accepted_at"):
            heartbeat_at = _as_datetime(current.get("last_heartbeat_at") or current["accepted_at"])
            if (now - heartbeat_at).total_seconds() >= ledger["heartbeat_timeout_seconds"]:
                status = self.control.record_terminal_signal(
                    task_id=task_id,
                    attempt_id=current["attempt_id"],
                    signal="missed_heartbeat",
                )
                actions.append({"action": "surfaced", "signal": "missed_heartbeat", "status": status})
                return actions
        if elapsed >= ledger["hard_deadline_seconds"]:
            signal = "hard_deadline"
        elif elapsed >= ledger["soft_deadline_seconds"]:
            signal = "soft_deadline"
        else:
            return actions
        status = self.control.record_terminal_signal(
            task_id=task_id,
            attempt_id=current["attempt_id"],
            signal=signal,
        )
        actions.append({"action": "surfaced", "signal": signal, "status": status})
        return actions

    def run_once(self) -> list[dict]:
        results: list[dict] = []
        for task_id in self.control.list_task_ids():
            try:
                actions = self.evaluate_task(task_id)
            except (ControlPlaneError, FailoverRejected, OSError) as exc:
                results.append({"task_id": task_id, "action": "needs_human", "error": str(exc)})
                continue
            results.extend({"task_id": task_id, **action} for action in actions)
        return results


def enabled(state_root: Path) -> bool:
    return os.environ.get("FAILOVER_CONTROL_ENABLED", "0") == "1" or (state_root / "ENABLED").is_file()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default=str(REPO / "_state" / "failover"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    state_root = Path(args.state_root).expanduser().resolve()
    if not enabled(state_root):
        print(json.dumps({"status": "disabled"}))
        return 0
    watchdog = FailoverWatchdog(DispatchControlPlane(state_root))
    while True:
        print(json.dumps(watchdog.run_once(), sort_keys=True), flush=True)
        if args.once:
            return 0
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
