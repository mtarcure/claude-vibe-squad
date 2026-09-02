#!/usr/bin/env python3
"""Sealed supervisor envelope for one fresh board-native CLI launch."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence

from role_context_compiler import CompiledRoleContext, RoleContextError, verify_role_context


ENVELOPE_SCHEMA = "task-runtime-envelope/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
_FRESH_LANE_COMMAND = {
    "codex": "exec",
    "gpt-codex": "exec",
    "claude": "-p",
    "gemini": "-p",
    "grok": "-p",
    "kimi": "-p",
}
_RESUME_ARGUMENTS = frozenset({"resume", "--resume", "--continue", "continue"})
PROJECTED_SKILL_CONTRACT_MAX_BYTES = 4096


class EnvelopeError(ValueError):
    """The runtime envelope is incomplete, stale, expired, or unauthentic."""


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
        raise EnvelopeError(f"envelope is not canonical JSON: {exc}") from exc


def _valid_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        raise EnvelopeError(f"invalid {label}")
    return value


def _validate_hash(value: str, label: str, *, optional: bool = False) -> None:
    if optional and value == "":
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise EnvelopeError(f"invalid {label} hash")


def _validate_string_tuple(values: tuple[str, ...], label: str, *, required: bool = True) -> None:
    if not isinstance(values, tuple) or (required and not values):
        raise EnvelopeError(f"{label} must be a non-empty tuple")
    if len(values) != len(set(values)):
        raise EnvelopeError(f"duplicate {label}")
    for value in values:
        _valid_text(value, label)


def _validate_path_tuple(values: tuple[str, ...], label: str, *, required: bool = True) -> None:
    _validate_string_tuple(values, label, required=required)
    for value in values:
        if not os.path.isabs(value) or os.path.normpath(value) != value:
            raise EnvelopeError(f"{label} entries must be canonical absolute paths")


@dataclass(frozen=True)
class RuntimeEnvelopeClaims:
    task_id: str
    attempt_id: str
    generation: int
    run_id: str
    lane: str
    author_family: str
    workload_class: str
    packet_sha256: str
    role_context_sha256: str
    overlay_sha256: str
    plan_sha256: str
    authority_sha256: str
    verification_contract_sha256: str
    selected_model_sha256: str
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    network_scope: tuple[str, ...]
    action_scope: tuple[str, ...]
    budgets: Mapping[str, int]
    expected_result_path: str
    expected_outbox_path: str
    required_phase_ids: tuple[str, ...]
    verification_kinds: tuple[str, ...]
    operator_gates: tuple[str, ...]
    stage1_profile_sha256: str
    stage1_request_sha256: str
    stage1_scope_sha256: str
    reconciliation_nonce: str
    created_at: int
    expires_at: int
    launch_attestation_sha256: str = ""
    tool_attestation_sha256: str = ""
    artifact_bundle_sha256: str = ""
    model_history_sha256: str = ""
    review_subject_sha256: str = ""
    review_family: str = ""
    review_state: str = ""

    def validate(self) -> None:
        if not isinstance(self.task_id, str) or not TASK_RE.fullmatch(self.task_id):
            raise EnvelopeError("invalid task id")
        if not isinstance(self.attempt_id, str) or not ATTEMPT_RE.fullmatch(self.attempt_id):
            raise EnvelopeError("invalid attempt id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation <= 0:
            raise EnvelopeError("generation must be a positive integer")
        for value, label in (
            (self.run_id, "run id"),
            (self.lane, "lane"),
            (self.author_family, "author family"),
            (self.workload_class, "workload class"),
            (self.expected_result_path, "expected result path"),
            (self.expected_outbox_path, "expected outbox path"),
            (self.reconciliation_nonce, "reconciliation nonce"),
        ):
            _valid_text(value, label)
        for value, label in (
            (self.packet_sha256, "packet"),
            (self.role_context_sha256, "role context"),
            (self.overlay_sha256, "overlay"),
            (self.plan_sha256, "plan"),
            (self.authority_sha256, "authority"),
            (self.verification_contract_sha256, "verification contract"),
            (self.selected_model_sha256, "selected model"),
            (self.stage1_profile_sha256, "Stage-1 profile"),
            (self.stage1_request_sha256, "Stage-1 request"),
            (self.stage1_scope_sha256, "Stage-1 scope"),
        ):
            _validate_hash(value, label)
        for value, label in (
            (self.launch_attestation_sha256, "launch attestation"),
            (self.tool_attestation_sha256, "tool attestation"),
            (self.artifact_bundle_sha256, "artifact bundle"),
            (self.model_history_sha256, "model history"),
            (self.review_subject_sha256, "review subject"),
        ):
            _validate_hash(value, label, optional=True)
        _validate_path_tuple(self.read_scope, "read scope", required=False)
        _validate_path_tuple(self.write_scope, "write scope")
        _validate_string_tuple(self.network_scope, "network scope", required=False)
        _validate_string_tuple(self.action_scope, "action scope")
        _validate_string_tuple(
            self.required_phase_ids,
            "required phase id",
            required=self.verification_kinds != ("artifact_written",),
        )
        _validate_string_tuple(self.verification_kinds, "verification kind")
        _validate_string_tuple(self.operator_gates, "operator gate", required=False)
        for value, label in (
            (self.expected_result_path, "expected result path"),
            (self.expected_outbox_path, "expected outbox path"),
        ):
            if not os.path.isabs(value) or os.path.normpath(value) != value:
                raise EnvelopeError(f"{label} must be a canonical absolute path")
        if not any(
            os.path.commonpath((self.expected_result_path, scope)) == scope
            for scope in self.write_scope
        ):
            raise EnvelopeError("expected result path is outside the authorized write scope")
        if not isinstance(self.budgets, Mapping) or not self.budgets:
            raise EnvelopeError("budgets must be a non-empty mapping")
        for name, value in self.budgets.items():
            _valid_text(name, "budget name")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EnvelopeError("budget values must be non-negative integers")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, int) or self.created_at < 0:
            raise EnvelopeError("created_at must be a non-negative integer")
        if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, int) or self.expires_at <= self.created_at:
            raise EnvelopeError("expires_at must be later than created_at")
        if self.review_family:
            _valid_text(self.review_family, "review family")
        if self.review_state:
            _valid_text(self.review_state, "review state")

    def to_payload(self) -> dict[str, object]:
        self.validate()
        payload = asdict(self)
        for field_name in (
            "read_scope",
            "write_scope",
            "network_scope",
            "action_scope",
            "required_phase_ids",
            "verification_kinds",
            "operator_gates",
        ):
            payload[field_name] = list(payload[field_name])
        payload["budgets"] = dict(sorted(self.budgets.items()))
        return payload


@dataclass(frozen=True)
class SealedRuntimeEnvelope:
    schema: str
    payload_json: str
    payload_sha256: str
    mac_sha256: str
    envelope_sha256: str

    def worker_projection(self) -> dict[str, object]:
        """Return claims visible to a worker, never the supervisor MAC."""

        return {
            "schema": self.schema,
            "payload": json.loads(self.payload_json),
            "payload_sha256": self.payload_sha256,
            "envelope_sha256": self.envelope_sha256,
        }


def projected_skill_contract(skills: tuple[str, ...]) -> str:
    """Make projected methodologies explicit without claiming native delivery."""

    _validate_string_tuple(skills, "projected skill", required=False)
    if not skills:
        return ""
    encoded = json.dumps(
        list(skills), separators=(",", ":"), ensure_ascii=True
    )
    if len(encoded.encode("ascii")) > PROJECTED_SKILL_CONTRACT_MAX_BYTES:
        raise EnvelopeError("projected skill contract exceeds its byte limit")
    return (
        "\n\n## Projected specialist methodologies\n\n"
        f"Authenticated projected skill names: `{encoded}`.\n"
        "This list is an assignment, not proof that the runtime loaded the "
        "skill bodies. Before task execution, resolve every projected "
        "methodology by its runtime skill mechanism and follow the ones that "
        "apply. If any name cannot be resolved, stop and report "
        "`capability_gap` instead of silently proceeding without it. In the "
        "result, report `skills_resolved`, `skills_applied`, and `skill_gaps`.\n"
        "\n"
    )


def _key(signing_key: bytes) -> bytes:
    if not isinstance(signing_key, bytes) or len(signing_key) < 16:
        raise EnvelopeError("supervisor signing key must contain at least 16 bytes")
    return signing_key


def seal_runtime_envelope(
    claims: RuntimeEnvelopeClaims, signing_key: bytes
) -> SealedRuntimeEnvelope:
    if not isinstance(claims, RuntimeEnvelopeClaims):
        raise EnvelopeError("claims have the wrong type")
    payload_bytes = _canonical_json(claims.to_payload())
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    mac_sha256 = hmac.new(_key(signing_key), payload_bytes, hashlib.sha256).hexdigest()
    envelope_sha256 = hashlib.sha256(
        ENVELOPE_SCHEMA.encode("ascii") + b"\n" + payload_bytes + b"\n" + mac_sha256.encode("ascii")
    ).hexdigest()
    return SealedRuntimeEnvelope(
        schema=ENVELOPE_SCHEMA,
        payload_json=payload_bytes.decode("ascii"),
        payload_sha256=payload_sha256,
        mac_sha256=mac_sha256,
        envelope_sha256=envelope_sha256,
    )


def _claims_from_payload(payload: Mapping[str, object]) -> RuntimeEnvelopeClaims:
    converted = dict(payload)
    for field_name in (
        "read_scope",
        "write_scope",
        "network_scope",
        "action_scope",
        "required_phase_ids",
        "verification_kinds",
        "operator_gates",
    ):
        value = converted.get(field_name)
        if not isinstance(value, list):
            raise EnvelopeError(f"invalid serialized {field_name}")
        converted[field_name] = tuple(value)
    try:
        claims = RuntimeEnvelopeClaims(**converted)
    except TypeError as exc:
        raise EnvelopeError(f"runtime envelope claim schema mismatch: {exc}") from exc
    claims.validate()
    return claims


def verify_runtime_envelope(
    envelope: SealedRuntimeEnvelope,
    signing_key: bytes,
    *,
    expected_task_id: str | None = None,
    expected_attempt_id: str | None = None,
    expected_generation: int | None = None,
    now: int | None = None,
) -> RuntimeEnvelopeClaims:
    """Authenticate and freshness-check a sealed envelope, failing closed."""

    if not isinstance(envelope, SealedRuntimeEnvelope) or envelope.schema != ENVELOPE_SCHEMA:
        raise EnvelopeError("unsupported runtime envelope")
    try:
        raw_payload = envelope.payload_json.encode("ascii")
        decoded = json.loads(envelope.payload_json)
    except (UnicodeEncodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError("runtime envelope payload is not canonical JSON") from exc
    if not isinstance(decoded, dict) or _canonical_json(decoded) != raw_payload:
        raise EnvelopeError("runtime envelope payload is not canonical JSON")
    if hashlib.sha256(raw_payload).hexdigest() != envelope.payload_sha256:
        raise EnvelopeError("runtime envelope payload hash mismatch")
    expected_mac = hmac.new(_key(signing_key), raw_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_mac, envelope.mac_sha256):
        raise EnvelopeError("runtime envelope MAC mismatch")
    expected_envelope_hash = hashlib.sha256(
        ENVELOPE_SCHEMA.encode("ascii") + b"\n" + raw_payload + b"\n" + envelope.mac_sha256.encode("ascii")
    ).hexdigest()
    if not hmac.compare_digest(expected_envelope_hash, envelope.envelope_sha256):
        raise EnvelopeError("runtime envelope hash mismatch")
    claims = _claims_from_payload(decoded)
    if expected_task_id is not None and claims.task_id != expected_task_id:
        raise EnvelopeError("task id does not match launch authority")
    if expected_attempt_id is not None and claims.attempt_id != expected_attempt_id:
        raise EnvelopeError("attempt id does not match launch authority")
    if expected_generation is not None and claims.generation != expected_generation:
        raise EnvelopeError("stale generation")
    if now is not None:
        if isinstance(now, bool) or not isinstance(now, int):
            raise EnvelopeError("verification time must be an integer")
        if now < claims.created_at:
            raise EnvelopeError("runtime envelope is not yet valid")
        if now > claims.expires_at:
            raise EnvelopeError("runtime envelope expired")
    return claims


def _fresh_cli_command(
    *,
    lane: str,
    executable: Path,
    prompt: str,
    lane_args: Sequence[str],
) -> tuple[str, ...]:
    """Build a non-resuming CLI command for one supported model lane."""

    executable_text = str(executable)
    if not Path(executable_text).is_absolute() or any(
        marker in executable_text for marker in ("\x00", "\n", "\r")
    ):
        raise EnvelopeError("fresh CLI executable must be an absolute safe path")
    verb = _FRESH_LANE_COMMAND.get(lane)
    if verb is None:
        raise EnvelopeError(f"unsupported fresh CLI lane: {lane}")
    normalized_args: list[str] = []
    for argument in lane_args:
        if (
            not isinstance(argument, str)
            or not argument
            or any(marker in argument for marker in ("\x00", "\n", "\r"))
        ):
            raise EnvelopeError("fresh CLI arguments contain an invalid value")
        if argument.casefold() in _RESUME_ARGUMENTS or argument.casefold().startswith("--resume="):
            raise EnvelopeError("fresh CLI launch cannot resume an existing session")
        normalized_args.append(argument)
    if verb == "exec":
        return (executable_text, verb, *normalized_args, prompt)
    return (executable_text, verb, prompt, *normalized_args)


def launch_task(
    envelope: SealedRuntimeEnvelope,
    signing_key: bytes,
    role_context: CompiledRoleContext,
    *,
    executable: Path,
    canary_runner: Callable[[], object],
    expected_task_id: str,
    expected_attempt_id: str,
    expected_generation: int,
    now: int,
    lane_args: Sequence[str] = (),
    projected_skills: Sequence[str] = (),
    timeout: float = 30,
    launcher: Callable[..., object] | None = None,
) -> object:
    """Launch a fresh CLI through the exact Stage-1 canary/profile boundary.

    The supervisor authenticates the envelope and role-context binding before
    constructing the worker's read-only projection.  The default launcher is
    Task 1.2's one-use ``launch_if_canary_passes`` seam, which consumes a
    retained ``PreparedLaunch`` and executes under its exact Seatbelt profile.
    """

    claims = verify_runtime_envelope(
        envelope,
        signing_key,
        expected_task_id=expected_task_id,
        expected_attempt_id=expected_attempt_id,
        expected_generation=expected_generation,
        now=now,
    )
    try:
        verify_role_context(role_context)
    except RoleContextError as exc:
        raise EnvelopeError(f"invalid role context: {exc}") from exc
    if role_context.sha256 != claims.role_context_sha256:
        raise EnvelopeError("role context does not match sealed envelope")
    if role_context.lane != claims.lane:
        raise EnvelopeError("role context lane does not match sealed envelope")

    projection_json = _canonical_json(envelope.worker_projection()).decode("ascii")
    skill_contract = projected_skill_contract(tuple(projected_skills))
    prompt = (
        f"{role_context.prompt.rstrip()}\n\n"
        f"{skill_contract.lstrip()}"
        "## Read-only task runtime envelope\n\n"
        f"```json\n{projection_json}\n```\n"
    )
    command = _fresh_cli_command(
        lane=claims.lane,
        executable=Path(executable),
        prompt=prompt,
        lane_args=lane_args,
    )
    if launcher is None:
        from launch_hygiene import launch_if_canary_passes

        launcher = launch_if_canary_passes
    return launcher(
        canary_runner,
        command,
        expected_profile_sha256=claims.stage1_profile_sha256,
        expected_request_sha256=claims.stage1_request_sha256,
        expected_scope_sha256=claims.stage1_scope_sha256,
        timeout=timeout,
    )


__all__ = [
    "ENVELOPE_SCHEMA",
    "EnvelopeError",
    "RuntimeEnvelopeClaims",
    "SealedRuntimeEnvelope",
    "projected_skill_contract",
    "seal_runtime_envelope",
    "verify_runtime_envelope",
    "launch_task",
]
