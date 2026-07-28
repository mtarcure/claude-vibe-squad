#!/usr/bin/env python3
"""Authoritative supervisor-side executor for every Rule-6 held effect.

The worker may describe an effect, but only a supervisor-owned instance of
``HeldEffectExecutor`` owns the HMAC key, durable consumption ledger, and
registered effect handlers. Authorization and one-shot consumption always
happen before a handler is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Mapping

from held_action_gate import (
    HELD_CATEGORIES,
    HeldActionStore,
    HeldActionToken,
    authorize,
)


EFFECT_SCHEMA = "held-effect/v1"


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"held effect is not canonical JSON: {exc}") from exc


def _valid_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(marker in value for marker in ("\x00", "\n", "\r"))
    ):
        raise ValueError(f"invalid {label}")
    return value


def canonical_effect_target(
    category: str,
    effect_name: str,
    effect_payload: Mapping[str, object],
) -> str:
    """Bind operator approval to the exact typed effect, not a display label."""

    if category not in HELD_CATEGORIES:
        raise ValueError("unknown held-effect category")
    _valid_text(effect_name, "effect name")
    if not isinstance(effect_payload, Mapping):
        raise ValueError("effect payload must be an object")
    descriptor = {
        "schema": EFFECT_SCHEMA,
        "category": category,
        "effect_name": effect_name,
        "effect_payload": dict(effect_payload),
    }
    return f"{EFFECT_SCHEMA}:{hashlib.sha256(_canonical_json(descriptor)).hexdigest()}"


@dataclass(frozen=True)
class HeldEffectRequest:
    category: str
    target: str
    task_id: str
    attempt_id: str
    effect_name: str
    effect_payload: Mapping[str, object]

    def validate(self) -> None:
        if self.category not in HELD_CATEGORIES:
            raise ValueError("unknown held-effect category")
        _valid_text(self.target, "effect target")
        _valid_text(self.task_id, "task id")
        _valid_text(self.attempt_id, "attempt id")
        _valid_text(self.effect_name, "effect name")
        expected_target = canonical_effect_target(
            self.category,
            self.effect_name,
            self.effect_payload,
        )
        if self.target != expected_target:
            raise ValueError("held-effect target is not bound to its exact descriptor")

    @property
    def sha256(self) -> str:
        self.validate()
        return hashlib.sha256(
            _canonical_json(
                {
                    "schema": EFFECT_SCHEMA,
                    "category": self.category,
                    "target": self.target,
                    "task_id": self.task_id,
                    "attempt_id": self.attempt_id,
                    "effect_name": self.effect_name,
                    "effect_payload": dict(self.effect_payload),
                }
            )
        ).hexdigest()


@dataclass(frozen=True)
class HeldEffectReceipt:
    status: str
    category: str
    target: str
    token_id: str
    request_sha256: str
    result_sha256: str
    consumed: bool


class HeldEffectExecutor:
    """Supervisor-owned authorization/dispatch boundary for held effects."""

    def __init__(
        self,
        *,
        store: HeldActionStore,
        signing_key: bytes,
        now: Callable[[], int],
        backends: Mapping[
            str, Callable[[HeldEffectRequest], Mapping[str, object]]
        ],
    ) -> None:
        if not isinstance(store, HeldActionStore):
            raise TypeError("held-effect store has the wrong type")
        if not isinstance(signing_key, bytes) or len(signing_key) < 16:
            raise ValueError("held-effect signing key must contain at least 16 bytes")
        if not callable(now):
            raise TypeError("held-effect clock must be callable")
        if (
            not isinstance(backends, Mapping)
            or set(backends) != HELD_CATEGORIES
            or any(not callable(handler) for handler in backends.values())
        ):
            raise ValueError("held-effect backends must cover exactly the eight categories")
        self._store = store
        self._signing_key = signing_key
        self._now = now
        self._backends = dict(backends)

    def execute(
        self,
        request: HeldEffectRequest,
        *,
        token: HeldActionToken | None,
    ) -> HeldEffectReceipt:
        if not isinstance(request, HeldEffectRequest):
            raise TypeError("held-effect request has the wrong type")
        request.validate()

        # This is deliberately before handler validation/invocation. A direct
        # no-token attempt reaches no effect surface, regardless of what it
        # supplies as a purported handler.
        now = self._now()
        authorize(
            category=request.category,
            target=request.target,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            token=token,
            store=self._store,
            signing_key=self._signing_key,
            now=now,
        )
        assert token is not None  # authorize() established this and consumed it.
        try:
            result = self._backends[request.category](request)
        except Exception:  # noqa: BLE001 - effect may have happened before failure
            # Consumption is intentionally durable. Retrying an effect whose
            # backend outcome is uncertain is more dangerous than requiring
            # reconciliation, and backend exception text may contain secrets.
            status = "outcome_unknown"
            result = {"status": status, "error_class": "backend-exception"}
        else:
            if not isinstance(result, Mapping):
                status = "outcome_unknown"
                result = {"status": status, "error_class": "invalid-receipt"}
            elif result.get("status") == "performed":
                status = "performed"
            elif result.get("status") == "failed":
                status = "failed"
            else:
                status = "outcome_unknown"
                result = {"status": status, "error_class": "invalid-receipt"}
        return HeldEffectReceipt(
            status=status,
            category=request.category,
            target=request.target,
            token_id=token.token_id,
            request_sha256=request.sha256,
            result_sha256=hashlib.sha256(_canonical_json(dict(result))).hexdigest(),
            consumed=True,
        )


__all__ = [
    "EFFECT_SCHEMA",
    "HeldEffectExecutor",
    "HeldEffectReceipt",
    "HeldEffectRequest",
    "canonical_effect_target",
]
