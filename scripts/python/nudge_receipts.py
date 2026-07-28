#!/usr/bin/env python3
"""Durable, bounded receipts for Path B tmux nudges.

The receipt is intentionally left unconfirmed after tmux accepts an injection:
process success proves only that tmux accepted the commands, not that the target
lane consumed them. A later scan confirms delivery from the task registry or
resends one stale, still-in-inbox nudge.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator


RECEIPT_SCHEMA = "nudge-receipt/v1"
UNCONFIRMED_STATES = {"prepared", "send-failed", "resending", "sent-unconfirmed"}


class RegistryUnavailable(RuntimeError):
    """Claim state could not be proven, so resend must fail closed."""


def _utc_timestamp(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def _identity_digest(task_id: str, target: str, attempt: str) -> str:
    encoded = json.dumps(
        [task_id, target, attempt], separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_task_prefix(task_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-.")
    return (value or "task")[:80]


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def shared_notify_lock(state_dir: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Acquire the notification lock shared with registry_reconciler Path A."""

    state_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = state_dir / "chrono-notify.lockdir"
    owner_path = lock_dir / "owner.pid"
    deadline = time.monotonic() + timeout_seconds
    acquired = False

    while not acquired:
        try:
            lock_dir.mkdir()
            owner_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
            acquired = True
        except FileExistsError:
            stale = False
            try:
                owner_text = owner_path.read_text(encoding="utf-8").strip()
                stale = not owner_text.isdigit() or not _pid_is_alive(int(owner_text))
            except OSError:
                # A just-created Path A lock may not have written owner.pid yet.
                stale = False
            if stale:
                try:
                    owner_path.unlink(missing_ok=True)
                    lock_dir.rmdir()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for shared notification lock: {lock_dir}")
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            if owner_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                owner_path.unlink(missing_ok=True)
                lock_dir.rmdir()
        except OSError:
            pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class TmuxSender:
    """Inject a literal prompt through a named tmux buffer, then press Enter."""

    def __init__(
        self,
        tmux_bin: str = "tmux",
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tmux_bin = tmux_bin
        self.sleeper = sleeper

    def __call__(self, target: str, message: str, buffer_name: str) -> None:
        subprocess.run(
            [self.tmux_bin, "load-buffer", "-b", buffer_name, "-"],
            input=message,
            text=True,
            check=True,
        )
        # Let a newly launched or just-idled lane finish its prompt transition.
        self.sleeper(0.4)
        subprocess.run(
            [
                self.tmux_bin,
                "paste-buffer",
                "-d",
                "-p",
                "-b",
                buffer_name,
                "-t",
                target,
            ],
            check=True,
        )
        self.sleeper(0.15)
        subprocess.run(
            [self.tmux_bin, "send-keys", "-t", target, "Enter"],
            check=True,
        )


Sender = Callable[[str, str, str], None]


class NudgeReceiptStore:
    def __init__(
        self,
        state_dir: Path,
        registry_path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.receipt_dir = self.state_dir / "dispatch-nudge-receipts"
        self.registry_path = Path(registry_path or self.state_dir / "active-tasks.json")
        self.clock = clock

    def _path(self, task_id: str, target: str, attempt: str) -> Path:
        digest = _identity_digest(task_id, target, attempt)
        return self.receipt_dir / f"{_safe_task_prefix(task_id)}-{digest[:24]}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"receipt is not a JSON object: {path}")
        return value

    def get(self, task_id: str, target: str, attempt: str) -> dict[str, Any] | None:
        with shared_notify_lock(self.state_dir):
            return self._read(self._path(task_id, target, attempt))

    def send(
        self,
        *,
        task_id: str,
        target_lane: str,
        target: str,
        attempt: str,
        task_path: Path,
        message: str,
        sender: Sender,
    ) -> dict[str, Any]:
        """Persist-before-send, suppressing duplicate or confirmed identities."""

        receipt_path = self._path(task_id, target, attempt)
        with shared_notify_lock(self.state_dir):
            existing = self._read(receipt_path)
            if existing is not None:
                return existing

            now = self.clock()
            receipt: dict[str, Any] = {
                "schema": RECEIPT_SCHEMA,
                "task_id": task_id,
                "target_lane": target_lane,
                "target": target,
                "attempt": attempt,
                "task_path": str(Path(task_path).resolve()),
                "message": message,
                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "state": "prepared",
                "created_at": _utc_timestamp(now),
                "created_at_epoch": now,
                "last_attempt_at": _utc_timestamp(now),
                "last_attempt_at_epoch": now,
                "send_count": 0,
                "resend_count": 0,
            }
            _atomic_write_json(receipt_path, receipt)
            try:
                sender(target, message, f"nudge-{_identity_digest(task_id, target, attempt)[:20]}")
            except Exception as exc:
                failed_at = self.clock()
                receipt.update(
                    state="send-failed",
                    last_error=f"{type(exc).__name__}: {exc}",
                    updated_at=_utc_timestamp(failed_at),
                    updated_at_epoch=failed_at,
                )
                _atomic_write_json(receipt_path, receipt)
                raise

            sent_at = self.clock()
            receipt.update(
                state="sent-unconfirmed",
                send_count=1,
                last_attempt_at=_utc_timestamp(sent_at),
                last_attempt_at_epoch=sent_at,
                updated_at=_utc_timestamp(sent_at),
                updated_at_epoch=sent_at,
            )
            _atomic_write_json(receipt_path, receipt)
            return receipt

    def _load_registry(self) -> dict[str, Any]:
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RegistryUnavailable(f"task registry is missing: {self.registry_path}") from exc
        except json.JSONDecodeError as exc:
            raise RegistryUnavailable(f"task registry is malformed: {self.registry_path}") from exc
        if not isinstance(value, dict):
            raise RegistryUnavailable(f"task registry is not a JSON object: {self.registry_path}")
        return value

    @staticmethod
    def _registry_confirms(receipt: dict[str, Any], registry: dict[str, Any]) -> bool:
        record = registry.get(receipt.get("task_id"))
        if not isinstance(record, dict):
            return False
        if record.get("delivery_attempt_id") != receipt.get("attempt"):
            return False
        if record.get("claimed_at") or record.get("started_at"):
            return True
        return record.get("delivery_state") in {
            "claimed",
            "in-progress",
            "complete",
            "needs-review",
            "blocked",
        }

    def resend_due(
        self,
        *,
        stale_after_seconds: float,
        sender: Sender,
        max_resends: int = 1,
    ) -> list[dict[str, Any]]:
        """Confirm known claims and resend each stale unconfirmed identity once."""

        changed: list[dict[str, Any]] = []
        # Snapshot filenames without the notification lock. Each receipt gets a
        # separately bounded critical section so a batch cannot starve Path A.
        receipt_paths = sorted(self.receipt_dir.glob("*.json"))
        for receipt_path in receipt_paths:
            with shared_notify_lock(self.state_dir):
                receipt = self._read(receipt_path)
                if receipt is None or receipt.get("state") not in UNCONFIRMED_STATES:
                    continue

                registry = self._load_registry()
                now = self.clock()
                if self._registry_confirms(receipt, registry):
                    receipt.update(
                        state="confirmed",
                        confirmed_at=_utc_timestamp(now),
                        confirmed_at_epoch=now,
                        confirmation="active-task-registry",
                        updated_at=_utc_timestamp(now),
                        updated_at_epoch=now,
                    )
                    _atomic_write_json(receipt_path, receipt)
                    continue

                task_path = Path(str(receipt.get("task_path", "")))
                if not task_path.is_file():
                    receipt.update(
                        state="closed-packet-missing",
                        updated_at=_utc_timestamp(now),
                        updated_at_epoch=now,
                    )
                    _atomic_write_json(receipt_path, receipt)
                    continue

                last_attempt = float(receipt.get("last_attempt_at_epoch", 0.0))
                if now - last_attempt < stale_after_seconds:
                    continue
                if int(receipt.get("resend_count", 0)) >= max_resends:
                    receipt.update(
                        state="resend-exhausted",
                        updated_at=_utc_timestamp(now),
                        updated_at_epoch=now,
                    )
                    _atomic_write_json(receipt_path, receipt)
                    continue

                receipt.update(
                    state="resending",
                    resend_count=int(receipt.get("resend_count", 0)) + 1,
                    send_count=int(receipt.get("send_count", 0)) + 1,
                    last_attempt_at=_utc_timestamp(now),
                    last_attempt_at_epoch=now,
                    updated_at=_utc_timestamp(now),
                    updated_at_epoch=now,
                )
                _atomic_write_json(receipt_path, receipt)
                try:
                    sender(
                        str(receipt["target"]),
                        str(receipt["message"]),
                        f"nudge-{_identity_digest(str(receipt['task_id']), str(receipt['target']), str(receipt['attempt']))[:20]}",
                    )
                except Exception as exc:
                    receipt.update(
                        state="send-failed",
                        last_error=f"{type(exc).__name__}: {exc}",
                    )
                    _atomic_write_json(receipt_path, receipt)
                    raise
                receipt["state"] = "sent-unconfirmed"
                receipt.pop("last_error", None)
                _atomic_write_json(receipt_path, receipt)
                changed.append(receipt.copy())
        return changed

    def confirm(self, task_id: str, target: str, attempt: str, reason: str) -> bool:
        receipt_path = self._path(task_id, target, attempt)
        with shared_notify_lock(self.state_dir):
            receipt = self._read(receipt_path)
            if receipt is None:
                return False
            if receipt.get("state") == "confirmed":
                return True
            now = self.clock()
            receipt.update(
                state="confirmed",
                confirmed_at=_utc_timestamp(now),
                confirmed_at_epoch=now,
                confirmation=reason,
                updated_at=_utc_timestamp(now),
                updated_at_epoch=now,
            )
            _atomic_write_json(receipt_path, receipt)
            return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--state-dir", required=True, type=Path)
        subparser.add_argument("--registry", type=Path)

    send = subparsers.add_parser("send", help="persist and send one nudge")
    common(send)
    send.add_argument("--task-id", required=True)
    send.add_argument("--target-lane", required=True)
    send.add_argument("--target", required=True)
    send.add_argument("--attempt", required=True)
    send.add_argument("--task-path", required=True, type=Path)
    send.add_argument("--tmux-bin", default="tmux")

    resend = subparsers.add_parser("resend-due", help="confirm or resend stale receipts")
    common(resend)
    resend.add_argument("--stale-after-seconds", type=float, default=60.0)
    resend.add_argument("--max-resends", type=int, default=1)
    resend.add_argument("--tmux-bin", default="tmux")

    confirm = subparsers.add_parser("confirm", help="explicitly confirm one receipt")
    common(confirm)
    confirm.add_argument("--task-id", required=True)
    confirm.add_argument("--target", required=True)
    confirm.add_argument("--attempt", required=True)
    confirm.add_argument("--reason", default="explicit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = NudgeReceiptStore(args.state_dir, args.registry)

    if args.command == "send":
        message = sys.stdin.read()
        if not message:
            raise SystemExit("nudge message must be provided on stdin")
        receipt = store.send(
            task_id=args.task_id,
            target_lane=args.target_lane,
            target=args.target,
            attempt=args.attempt,
            task_path=args.task_path,
            message=message,
            sender=TmuxSender(args.tmux_bin),
        )
        print(json.dumps({"state": receipt["state"], "send_count": receipt["send_count"]}))
        return 0

    if args.command == "resend-due":
        resent = store.resend_due(
            stale_after_seconds=args.stale_after_seconds,
            max_resends=args.max_resends,
            sender=TmuxSender(args.tmux_bin),
        )
        print(json.dumps({"resent": len(resent)}))
        return 0

    confirmed = store.confirm(args.task_id, args.target, args.attempt, args.reason)
    print(json.dumps({"confirmed": confirmed}))
    return 0 if confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
