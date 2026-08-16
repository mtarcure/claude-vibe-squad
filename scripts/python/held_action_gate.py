#!/usr/bin/env python3
"""V2 trusted-launch-path — the Rule-6 held-action authorization boundary.

Operator threat-model reframe (2026-07-22): on this dedicated single-user
host the lanes are trusted and run with normal env/credentials by default;
F2 credential-broker custody is demoted to an opt-in mode for untrusted-input
work, not the go-live gate. The boundary that actually matters is this one:
a task cannot perform an irreversible, external, or spend-bearing action
without a validated, one-shot, target-bound operator-approval token. This
module is that checkpoint — the authorization backstop that replaces the old
subagent tool-restriction for Rules 5/6 now that every task is a full
top-level model instance.

Composes the same primitives already reviewed and proven elsewhere this
session rather than inventing new ones: an HMAC-signed, MAC-verified token
(matching runtime_envelope.py's sealed claims), and a durable, mkdir-locked,
atomic-write consumption ledger (matching coordination.py's CoordinationStore).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Iterator


# The controller-held effect categories, spelled in the canonical `operator_gate`
# vocabulary that `shared/lane-policy.tsv` defines and `validate_specialists.py`
# enforces against the runtime map. One vocabulary, one spelling: a specialist
# row may only declare a gate the controller actually holds, and
# `test_held_action_gate.py` pins exact equality among this set, that vocabulary,
# and the Hard Rule 6 policy list so the three surfaces cannot drift.
#
# This set was hyphen-cased until 2026-08-08, which made it share zero values
# with the vocabulary it was supposed to correspond to. Reconciling the spelling
# exposed three gates -- cleanup, malware_detonation, offensive_execution -- that
# specialist rows declared as operator-gated while the controller held none of
# them; `cleanup` is named in Hard Rule 6 by name. `release` merged into
# `public_release`: both meant "publication", and two names for one effect is how
# a grant for one silently reads as a grant for the other.
HELD_CATEGORIES = frozenset(
    {
        "cleanup",
        "credential_change",
        "delete",
        "live_outreach",
        "malware_detonation",
        "offensive_execution",
        "paid_media",
        "production_mutation",
        "public_release",
    }
)

TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
TOKEN_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class HeldActionDenied(RuntimeError):
    """A held-category action was attempted without a valid one-shot token."""


def _valid_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class HeldActionToken:
    token_id: str
    category: str
    target: str
    task_id: str
    attempt_id: str
    issued_at: int
    expires_at: int
    mac: str


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _claims_payload(
    *, token_id: str, category: str, target: str, task_id: str, attempt_id: str, issued_at: int, expires_at: int
) -> dict[str, object]:
    return {
        "token_id": token_id,
        "category": category,
        "target": target,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def _mac(signing_key: bytes, payload: dict[str, object]) -> str:
    if not isinstance(signing_key, bytes) or len(signing_key) < 16:
        raise ValueError("held-action signing key must contain at least 16 bytes")
    return hmac.new(signing_key, _canonical_json(payload), hashlib.sha256).hexdigest()


def mint_token(
    *,
    category: str,
    target: str,
    task_id: str,
    attempt_id: str,
    issued_at: int,
    expires_at: int,
    signing_key: bytes,
) -> HeldActionToken:
    """Mint a one-shot, target-bound token for exactly one held-category action.

    Minting authority belongs to the operator-approval flow, not this
    module — this function exists so that flow (and this module's own
    tests) have a correct, reusable way to produce a validly-signed token,
    not to grant this module any approval power of its own.
    """

    if category not in HELD_CATEGORIES:
        raise ValueError(f"cannot mint a token for a non-held category: {category!r}")
    _valid_text(target, "target")
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    if not ATTEMPT_RE.fullmatch(attempt_id):
        raise ValueError("invalid attempt id")
    for value, label in ((issued_at, "issued_at"), (expires_at, "expires_at")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
    if expires_at <= issued_at:
        raise ValueError("expires_at must be later than issued_at")
    token_id = hashlib.sha256(os.urandom(32)).hexdigest()
    payload = _claims_payload(
        token_id=token_id,
        category=category,
        target=target,
        task_id=task_id,
        attempt_id=attempt_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return HeldActionToken(**payload, mac=_mac(signing_key, payload))


def verify_token(
    token: HeldActionToken,
    *,
    signing_key: bytes,
    expected_category: str,
    expected_target: str,
    expected_task_id: str,
    expected_attempt_id: str,
    now: int,
) -> HeldActionToken:
    """Authenticate and freshness/binding-check a token, failing closed.

    Pure check — does not consume the token's one-shot slot. Callers that
    need consumption must go through ``HeldActionStore.check_and_consume``.
    """

    if not isinstance(token, HeldActionToken):
        raise HeldActionDenied("token has the wrong type")
    if not TOKEN_ID_RE.fullmatch(token.token_id):
        raise HeldActionDenied("invalid token id")
    payload = _claims_payload(
        token_id=token.token_id,
        category=token.category,
        target=token.target,
        task_id=token.task_id,
        attempt_id=token.attempt_id,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
    )
    try:
        expected_mac = _mac(signing_key, payload)
    except ValueError as exc:
        raise HeldActionDenied(str(exc)) from exc
    if not hmac.compare_digest(expected_mac, token.mac):
        raise HeldActionDenied("token signature mismatch")
    if token.category not in HELD_CATEGORIES:
        raise HeldActionDenied("token category is not a held category")
    if token.category != expected_category:
        raise HeldActionDenied("token category does not match the requested action")
    if token.target != expected_target:
        raise HeldActionDenied("token target does not match the requested action")
    if token.task_id != expected_task_id:
        raise HeldActionDenied("token task does not match the requesting task")
    if token.attempt_id != expected_attempt_id:
        raise HeldActionDenied("token attempt does not match the requesting attempt")
    if isinstance(now, bool) or not isinstance(now, int):
        raise HeldActionDenied("verification time must be an integer")
    if now < token.issued_at:
        raise HeldActionDenied("token is not yet valid")
    if now > token.expires_at:
        raise HeldActionDenied("token has expired")
    return token


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def _store_lock(state_dir: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Mkdir-based mutex with stale-owner detection (matches coordination.py)."""

    lock_dir = state_dir / ".held-action.lockdir"
    owner_file = lock_dir / "owner.pid"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir(parents=True)
        except FileExistsError:
            # A lock_dir that exists but has no owner.pid YET is NOT stale —
            # it means another thread/process just won the mkdir() race and
            # hasn't written its pid file (a real race, reproduced live):
            # treating "not written yet" as "abandoned" lets a second thread
            # rmdir the lock out from under its legitimate new owner, whose
            # own owner_file.write_text() then fails with FileNotFoundError.
            # Only a MALFORMED owner file (ValueError) or one naming a
            # genuinely dead PID counts as stale; a missing file means busy.
            # Additionally require the lock_dir itself to be older than a
            # short grace period before ever reclaiming it — belt-and-
            # suspenders against any interleaving this reasoning missed:
            # a lock that is definitionally too young to be abandoned is
            # never torn down out from under a still-acquiring owner.
            stale = False
            try:
                owner_pid = int(owner_file.read_text(encoding="utf-8").strip())
            except FileNotFoundError:
                stale = False
            except (OSError, ValueError):
                stale = True
            else:
                stale = not _pid_is_alive(owner_pid)
            if stale:
                try:
                    lock_age = time.time() - lock_dir.stat().st_mtime
                except OSError:
                    lock_age = float("inf")
                if lock_age < 1.0:
                    stale = False
            if stale:
                try:
                    owner_file.unlink()
                except OSError:
                    pass
                try:
                    lock_dir.rmdir()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise HeldActionDenied("timed out acquiring the held-action store lock")
            time.sleep(0.02)
            continue
        else:
            break
    try:
        owner_file.write_text(str(os.getpid()), encoding="utf-8")
        yield
    finally:
        try:
            owner_file.unlink()
        except OSError:
            pass
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload).decode("ascii") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class HeldActionStore:
    """Durable, mkdir-locked, one-shot consumption ledger for held-action tokens."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._consumed_dir = self._state_dir / "consumed"

    def _receipt_path(self, token_id: str) -> Path:
        return self._consumed_dir / f"{token_id}.json"

    def check_and_consume(
        self,
        token: HeldActionToken,
        *,
        signing_key: bytes,
        expected_category: str,
        expected_target: str,
        expected_task_id: str,
        expected_attempt_id: str,
        now: int,
    ) -> HeldActionToken:
        """Verify the token, then atomically consume its one-shot slot.

        A token that fails verification is never marked consumed — a
        mistaken (e.g. mistyped-target) attempt must not permanently burn a
        legitimately-issued token.
        """

        verified = verify_token(
            token,
            signing_key=signing_key,
            expected_category=expected_category,
            expected_target=expected_target,
            expected_task_id=expected_task_id,
            expected_attempt_id=expected_attempt_id,
            now=now,
        )
        with _store_lock(self._state_dir):
            receipt_path = self._receipt_path(verified.token_id)
            if receipt_path.exists():
                raise HeldActionDenied("token already consumed (replay)")
            _atomic_write_json(
                receipt_path,
                {
                    "token_id": verified.token_id,
                    "category": verified.category,
                    "target": verified.target,
                    "task_id": verified.task_id,
                    "attempt_id": verified.attempt_id,
                    "consumed_at": now,
                },
            )
        return verified


def authorize(
    *,
    category: str,
    target: str,
    task_id: str,
    attempt_id: str,
    token: HeldActionToken | None,
    store: HeldActionStore,
    signing_key: bytes,
    now: int,
) -> None:
    """The single entrypoint a caller uses before a held-category action.

    Raises ``ValueError`` if ``category`` is not one of the 9 held
    categories — a caller-side bug, not an authorization decision, since
    trusted in-scope work should never route through this function at all.
    Raises ``HeldActionDenied`` if no valid, unconsumed, exactly-matching
    one-shot token is presented.
    """

    if category not in HELD_CATEGORIES:
        raise ValueError(
            f"authorize() called for a non-held category ({category!r}); "
            "trusted in-scope work must not route through the held-action gate"
        )
    if token is None:
        raise HeldActionDenied(f"held action {category!r} requires an operator-approval token")
    store.check_and_consume(
        token,
        signing_key=signing_key,
        expected_category=category,
        expected_target=target,
        expected_task_id=task_id,
        expected_attempt_id=attempt_id,
        now=now,
    )


__all__ = [
    "HELD_CATEGORIES",
    "HeldActionDenied",
    "HeldActionToken",
    "HeldActionStore",
    "mint_token",
    "verify_token",
    "authorize",
]
