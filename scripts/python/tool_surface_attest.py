#!/usr/bin/env python3
"""Hash-bound tool-operation attestation and terminal reconciliation checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Callable, Sequence


TOOL_ATTESTATION_SCHEMA = "tool-surface-attestation/v1"
LAUNCH_ATTESTATION_SCHEMA = "launch-attestation/v1"
RECONCILIATION_SCHEMA = "task-reconciliation-chain/v1"
SUPERVISOR_CONTEXT_SCHEMA = "board-supervisor-runtime-context/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")


class AttestationError(ValueError):
    """Evidence is insufficient or the reconciliation chain is broken."""


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
        raise AttestationError(f"evidence is not canonical JSON: {exc}") from exc


def _hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        if value == "":
            raise AttestationError(f"missing {label} link")
        raise AttestationError(f"invalid {label} hash")


def _text(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise AttestationError(f"invalid {label}")


@dataclass(frozen=True)
class OperationEvidence:
    tool: str
    operation: str
    evidence_kind: str
    expected_effect: str
    observed_effect: str
    effect_observed: bool
    exit_code: int
    sandbox_denied: bool
    profile_sha256: str
    envelope_sha256: str
    evidence_sha256: str
    observed_at: int

    def validate(self) -> None:
        for value, label in (
            (self.tool, "tool"),
            (self.operation, "operation"),
            (self.evidence_kind, "evidence kind"),
            (self.expected_effect, "expected effect"),
            (self.observed_effect, "observed effect"),
        ):
            _text(value, label)
        if not isinstance(self.effect_observed, bool) or not isinstance(self.sandbox_denied, bool):
            raise AttestationError("evidence booleans have the wrong type")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise AttestationError("exit code must be an integer")
        if isinstance(self.observed_at, bool) or not isinstance(self.observed_at, int) or self.observed_at < 0:
            raise AttestationError("observation time must be a non-negative integer")
        _hash(self.profile_sha256, "profile")
        _hash(self.envelope_sha256, "envelope")
        _hash(self.evidence_sha256, "evidence")


@dataclass(frozen=True)
class ToolAttestation:
    schema: str
    tool: str
    operation: str
    expected_effect: str
    observed_effect: str
    profile_sha256: str
    envelope_sha256: str
    evidence_sha256: str
    observed_at: int
    available: bool
    sha256: str


@dataclass(frozen=True)
class LaunchEvidence:
    envelope_sha256: str
    profile_sha256: str
    request_sha256: str
    scope_sha256: str
    supervisor_build_sha256: str
    cli_sha256: str
    argv_sha256: str
    environment_keys_sha256: str
    canary_sha256: str
    admission_sha256: str
    allowed_write: bool
    denied_write: bool
    exact_broker_port: bool
    wrong_port_denied: bool
    descriptor_audit_passed: bool
    inode_audit_passed: bool
    broker_healthy: bool
    observed_at: int


@dataclass(frozen=True)
class LaunchAttestation:
    schema: str
    envelope_sha256: str
    profile_sha256: str
    request_sha256: str
    scope_sha256: str
    evidence_sha256: str
    observed_at: int
    sha256: str


def attest_launch(
    evidence: LaunchEvidence,
    *,
    expected_envelope_sha256: str,
) -> LaunchAttestation:
    """Hash-bind a fresh launch only after every Stage-1 effect passes."""

    if not isinstance(evidence, LaunchEvidence):
        raise AttestationError("launch evidence has the wrong type")
    _hash(expected_envelope_sha256, "expected envelope")
    for value, label in (
        (evidence.envelope_sha256, "envelope"),
        (evidence.profile_sha256, "profile"),
        (evidence.request_sha256, "request"),
        (evidence.scope_sha256, "scope"),
        (evidence.supervisor_build_sha256, "supervisor build"),
        (evidence.cli_sha256, "CLI"),
        (evidence.argv_sha256, "argv"),
        (evidence.environment_keys_sha256, "environment keys"),
        (evidence.canary_sha256, "canary"),
        (evidence.admission_sha256, "admission"),
    ):
        _hash(value, label)
    if evidence.envelope_sha256 != expected_envelope_sha256:
        raise AttestationError("launch is bound to the wrong runtime envelope")
    effects = (
        evidence.allowed_write,
        evidence.denied_write,
        evidence.exact_broker_port,
        evidence.wrong_port_denied,
        evidence.descriptor_audit_passed,
        evidence.inode_audit_passed,
        evidence.broker_healthy,
    )
    if any(not isinstance(effect, bool) for effect in effects) or not all(effects):
        raise AttestationError("required launch effect was not observed")
    if (
        isinstance(evidence.observed_at, bool)
        or not isinstance(evidence.observed_at, int)
        or evidence.observed_at < 0
    ):
        raise AttestationError("launch observation time must be a non-negative integer")
    evidence_payload = asdict(evidence)
    evidence_sha256 = hashlib.sha256(_canonical_json(evidence_payload)).hexdigest()
    payload = {
        "schema": LAUNCH_ATTESTATION_SCHEMA,
        "envelope_sha256": evidence.envelope_sha256,
        "profile_sha256": evidence.profile_sha256,
        "request_sha256": evidence.request_sha256,
        "scope_sha256": evidence.scope_sha256,
        "evidence_sha256": evidence_sha256,
        "observed_at": evidence.observed_at,
    }
    return LaunchAttestation(
        **payload,
        sha256=hashlib.sha256(_canonical_json(payload)).hexdigest(),
    )


def _reject_compatibility_only(evidence_kind: str, operation: str) -> None:
    compatibility_only = evidence_kind.casefold() in {
        "version",
        "help",
        "compatibility",
    }
    lowered_operation = operation.casefold()
    if compatibility_only or "--version" in lowered_operation or lowered_operation.endswith(" --help"):
        raise AttestationError("version/help output is not a tool operation attestation")


def attest_tool_operation(
    evidence: OperationEvidence,
    *,
    expected_profile_sha256: str,
    expected_envelope_sha256: str,
) -> ToolAttestation:
    """Attest availability only from a successful operation and observed effect."""

    if not isinstance(evidence, OperationEvidence):
        raise AttestationError("operation evidence has the wrong type")
    evidence.validate()
    _hash(expected_profile_sha256, "expected profile")
    _hash(expected_envelope_sha256, "expected envelope")
    _reject_compatibility_only(evidence.evidence_kind, evidence.operation)
    if evidence.profile_sha256 != expected_profile_sha256:
        raise AttestationError("operation ran under the wrong lane profile")
    if evidence.envelope_sha256 != expected_envelope_sha256:
        raise AttestationError("operation is bound to the wrong runtime envelope")
    if evidence.sandbox_denied:
        raise AttestationError("sandbox denial cannot be treated as tool success")
    if evidence.exit_code != 0:
        raise AttestationError("tool operation did not succeed")
    if not evidence.effect_observed or evidence.observed_effect != evidence.expected_effect:
        raise AttestationError("expected operation effect was not observed")
    payload = {
        "schema": TOOL_ATTESTATION_SCHEMA,
        "tool": evidence.tool,
        "operation": evidence.operation,
        "expected_effect": evidence.expected_effect,
        "observed_effect": evidence.observed_effect,
        "profile_sha256": evidence.profile_sha256,
        "envelope_sha256": evidence.envelope_sha256,
        "evidence_sha256": evidence.evidence_sha256,
        "observed_at": evidence.observed_at,
        "available": True,
    }
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return ToolAttestation(**payload, sha256=digest)


def capture_tool_operation(
    *,
    tool: str,
    operation: str,
    command: Sequence[str],
    expected_effect: str,
    observe_effect: Callable[[], str],
    profile_sha256: str,
    envelope_sha256: str,
    observed_at: int,
    runner: Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]],
    sandbox_denied: bool = False,
) -> ToolAttestation:
    """Run a profile-bound operation and attest only its observed effect.

    ``runner`` is supplied by the supervisor and must execute through the exact
    Stage-1 prepared-launch seam.  Only digests of command/stdout/stderr are
    retained, so tool output cannot accidentally become credential evidence.
    """

    _text(tool, "tool")
    _text(operation, "operation")
    _text(expected_effect, "expected effect")
    _hash(profile_sha256, "profile")
    _hash(envelope_sha256, "envelope")
    _reject_compatibility_only("operation", operation)
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)) or not command:
        raise AttestationError("tool operation command must be a non-empty sequence")
    normalized_command: list[str] = []
    for argument in command:
        if (
            not isinstance(argument, str)
            or not argument
            or any(marker in argument for marker in ("\x00", "\n", "\r"))
        ):
            raise AttestationError("tool operation command contains an invalid argument")
        normalized_command.append(argument)
    if not Path(normalized_command[0]).is_absolute():
        raise AttestationError("tool operation executable must be absolute")
    if not callable(runner) or not callable(observe_effect):
        raise AttestationError("tool operation runner/effect observer must be callable")
    if not isinstance(sandbox_denied, bool):
        raise AttestationError("sandbox denial classifier must be boolean")
    try:
        completed = runner(tuple(normalized_command))
    except Exception as exc:
        raise AttestationError(f"tool operation runner failed: {exc}") from exc
    if not isinstance(completed, subprocess.CompletedProcess):
        raise AttestationError("tool operation runner returned the wrong receipt type")
    if not isinstance(completed.stdout, str) or not isinstance(completed.stderr, str):
        raise AttestationError("tool operation runner must capture text output")
    try:
        observed_effect = observe_effect()
    except Exception as exc:
        raise AttestationError(f"tool operation effect observation failed: {exc}") from exc
    if not isinstance(observed_effect, str):
        raise AttestationError("tool operation effect observer returned the wrong type")
    evidence_payload = {
        "tool": tool,
        "operation": operation,
        "command_sha256": hashlib.sha256(_canonical_json(normalized_command)).hexdigest(),
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "expected_effect": expected_effect,
        "observed_effect": observed_effect,
        "exit_code": completed.returncode,
        "sandbox_denied": sandbox_denied,
        "profile_sha256": profile_sha256,
        "envelope_sha256": envelope_sha256,
        "observed_at": observed_at,
    }
    evidence = OperationEvidence(
        tool=tool,
        operation=operation,
        evidence_kind="operation",
        expected_effect=expected_effect,
        observed_effect=observed_effect,
        effect_observed=observed_effect == expected_effect,
        exit_code=completed.returncode,
        sandbox_denied=sandbox_denied,
        profile_sha256=profile_sha256,
        envelope_sha256=envelope_sha256,
        evidence_sha256=hashlib.sha256(_canonical_json(evidence_payload)).hexdigest(),
        observed_at=observed_at,
    )
    return attest_tool_operation(
        evidence,
        expected_profile_sha256=profile_sha256,
        expected_envelope_sha256=envelope_sha256,
    )


@dataclass(frozen=True)
class ReconciliationChain:
    task_id: str
    attempt_id: str
    generation: int
    envelope_sha256: str
    launch_attestation_sha256: str
    tool_attestation_sha256: str
    action_log_sha256: str
    artifact_bundle_sha256: str
    model_history_sha256: str
    review_subject_sha256: str
    review_family: str
    review_state: str
    outbox_sha256: str
    output_paths: tuple[str, ...]
    sandbox_denials: tuple[str, ...]

    @property
    def sha256(self) -> str:
        payload = asdict(self)
        payload["schema"] = RECONCILIATION_SCHEMA
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_path(path: str) -> str:
    _text(path, "output path")
    if not os.path.isabs(path):
        raise AttestationError("output path must be absolute")
    # ``normcase`` follows the host path model.  An unconditional ``casefold``
    # aliases distinct POSIX paths (for example ``Allowed`` and ``allowed``),
    # which can turn a re-cased sibling into an apparently authorized child.
    return os.path.normcase(os.path.realpath(path))


def _within_scope(path: str, scope: str) -> bool:
    try:
        return os.path.commonpath((path, scope)) == scope
    except ValueError:
        return False


def reconcile_result(
    chain: ReconciliationChain,
    *,
    expected_task_id: str,
    expected_attempt_id: str,
    expected_generation: int,
    expected_envelope_sha256: str,
    authorized_write_scope: tuple[str, ...],
    mandatory_review: bool,
    author_family: str,
) -> ReconciliationChain:
    """Validate every terminal link before the board may accept an outbox result."""

    if not isinstance(chain, ReconciliationChain):
        raise AttestationError("reconciliation chain has the wrong type")
    if not TASK_RE.fullmatch(chain.task_id) or chain.task_id != expected_task_id:
        raise AttestationError("task link mismatch")
    if not ATTEMPT_RE.fullmatch(chain.attempt_id) or chain.attempt_id != expected_attempt_id:
        raise AttestationError("attempt link mismatch")
    if (
        isinstance(chain.generation, bool)
        or not isinstance(chain.generation, int)
        or chain.generation != expected_generation
    ):
        raise AttestationError("stale generation")
    for value, label in (
        (chain.envelope_sha256, "envelope"),
        (chain.launch_attestation_sha256, "launch attestation"),
        (chain.tool_attestation_sha256, "tool attestation"),
        (chain.action_log_sha256, "action log"),
        (chain.artifact_bundle_sha256, "artifact bundle"),
        (chain.model_history_sha256, "model history"),
        (chain.review_subject_sha256, "review subject"),
        (chain.outbox_sha256, "outbox"),
    ):
        _hash(value, label)
    if chain.envelope_sha256 != expected_envelope_sha256:
        raise AttestationError("sealed envelope link mismatch")
    if chain.sandbox_denials:
        raise AttestationError("sandbox denial was treated as a successful result")
    if not isinstance(chain.output_paths, tuple) or not chain.output_paths:
        raise AttestationError("missing reconciled output paths")
    if not isinstance(authorized_write_scope, tuple) or not authorized_write_scope:
        raise AttestationError("missing authorized write scope")
    scopes = tuple(_canonical_path(scope) for scope in authorized_write_scope)
    for output in chain.output_paths:
        canonical_output = _canonical_path(output)
        if not any(_within_scope(canonical_output, scope) for scope in scopes):
            raise AttestationError(f"outside-scope output: {output}")
    _text(author_family, "author family")
    if mandatory_review:
        if chain.review_state.casefold() not in {"approved", "complete"}:
            raise AttestationError("mandatory review is not approved")
        if chain.review_subject_sha256 != chain.artifact_bundle_sha256:
            raise AttestationError("review subject does not match artifact bundle")
        if not chain.review_family:
            raise AttestationError("missing review family")
        if chain.review_family.casefold() == author_family.casefold():
            raise AttestationError("review violates author-family anti-affinity")
    return chain


def _load_supervisor_context(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttestationError(f"invalid supervisor runtime context: {exc}") from exc
    required = {
        "schema",
        "canonical_role_path",
        "lane_overlay_path",
        "specialist",
        "mode_profile",
        "executable",
        "lane_args",
        "claims",
        "tool_evidence",
        "ttl_seconds",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise AttestationError("supervisor runtime context has the wrong fields")
    if payload["schema"] != SUPERVISOR_CONTEXT_SCHEMA:
        raise AttestationError("unsupported supervisor runtime context")
    return payload


def _trusted_boundary_receipt(prepared: object, admission: dict[str, object]) -> dict[str, bool]:
    """Require evidence not supplied by the current raw canary listener.

    Task 1.2's current ``PreparedLaunch`` proves the Seatbelt effects but does
    not authenticate the companion runtime context, bind its listener to a
    CredentialBroker, or expose a signed inode re-audit receipt. Treating any
    of those facts as true here would fabricate launch authority/evidence. The
    seam is explicit so their owners can supply one typed receipt later.
    """

    raise AttestationError(
        "trusted runtime authority, CredentialBroker binding, and inode re-audit receipt are unavailable"
    )


def _supervisor_launch(
    request_path: Path,
    runtime_context_path: Path,
    workload_class: str,
    admission_json: str,
) -> dict[str, object]:
    """Compile, seal, boundary-launch, and bind evidence for one fresh CLI."""

    try:
        admission = json.loads(admission_json)
    except json.JSONDecodeError as exc:
        raise AttestationError("admission receipt is not JSON") from exc
    if not isinstance(admission, dict) or admission.get("status") != "admitted":
        raise AttestationError("live admission did not admit the task")
    context = _load_supervisor_context(runtime_context_path)
    if not isinstance(context["claims"], dict):
        raise AttestationError("runtime claims must be an object")

    from launch_hygiene import (
        _load_task_request,
        _request_digest,
        audit_writable_scopes,
        close_writable_scopes,
        launch_if_canary_passes,
        run_preflight_canary,
    )
    from role_context_compiler import compile_role_context
    from runtime_envelope import (
        RuntimeEnvelopeClaims,
        launch_task,
        seal_runtime_envelope,
        verify_runtime_envelope,
    )

    request = _load_task_request(request_path)
    if request["task_id"] != context["claims"].get("task_id"):
        raise AttestationError("runtime context task does not match Stage-1 request")
    if request["attempt_id"] != context["claims"].get("attempt_id"):
        raise AttestationError("runtime context attempt does not match Stage-1 request")
    if request["generation"] != context["claims"].get("generation"):
        raise AttestationError("runtime context generation does not match Stage-1 request")
    if context["claims"].get("workload_class") != workload_class:
        raise AttestationError("runtime context workload class mismatch")

    lane_args = context["lane_args"]
    if not isinstance(lane_args, list) or any(not isinstance(item, str) for item in lane_args):
        raise AttestationError("lane_args must be a list of strings")
    executable = Path(str(context["executable"]))
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or Path(os.path.realpath(executable)) != executable
        or not os.access(executable, os.X_OK)
    ):
        raise AttestationError("fresh lane executable must be an existing canonical executable")
    ttl_seconds = context["ttl_seconds"]
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
        raise AttestationError("runtime context TTL must be in 1..300 seconds")

    audited_scopes = audit_writable_scopes(tuple(Path(path) for path in request["write_paths"]))
    prepared = None
    try:
        request_sha256 = _request_digest(request)
        prepared = run_preflight_canary(
            Path(str(request["task_root"])),
            request_sha256=request_sha256,
            audited_scopes=audited_scopes,
            retain_launch=True,
        )
        executable_grant = f'(allow process-exec (literal "{executable}"))'
        if executable_grant not in prepared.profile.text:
            raise AttestationError(
                "retained Stage-1 profile does not authorize the fresh lane executable"
            )
        canary = prepared.canary
        trusted_boundary = _trusted_boundary_receipt(prepared, admission)
        if trusted_boundary != {
            "authority_authenticated": True,
            "broker_healthy": True,
            "inode_audit_passed": True,
        }:
            raise AttestationError("trusted launch boundary receipt is incomplete")

        # Do not read supervisor-side role/overlay paths until the scheduler's
        # runtime authority has been authenticated by the trusted receipt.
        role = compile_role_context(
            Path(str(context["canonical_role_path"])),
            Path(str(context["lane_overlay_path"])),
            specialist=str(context["specialist"]),
            lane=str(context["claims"].get("lane", "")),
            mode_profile=str(context["mode_profile"]),
        )

        now = int(time.time())
        claims_payload = dict(context["claims"])
        for tuple_field in (
            "read_scope",
            "write_scope",
            "network_scope",
            "action_scope",
            "required_phase_ids",
            "verification_kinds",
            "operator_gates",
        ):
            if tuple_field in claims_payload:
                claims_payload[tuple_field] = tuple(claims_payload[tuple_field])
        claims_payload.update(
            role_context_sha256=role.sha256,
            overlay_sha256=role.lane_overlay_sha256,
            stage1_profile_sha256=prepared.canary.profile_sha256,
            stage1_request_sha256=prepared.canary.request_sha256,
            stage1_scope_sha256=prepared.canary.scope_sha256,
            reconciliation_nonce=secrets.token_hex(32),
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        claims = RuntimeEnvelopeClaims(**claims_payload)
        signing_key = secrets.token_bytes(32)
        envelope = seal_runtime_envelope(claims, signing_key)
        authenticated_claims = verify_runtime_envelope(
            envelope,
            signing_key,
            expected_task_id=claims.task_id,
            expected_attempt_id=claims.attempt_id,
            expected_generation=claims.generation,
            now=now,
        )

        tool_evidence = context["tool_evidence"]
        if not isinstance(tool_evidence, dict) or set(tool_evidence) != {
            "tool", "operation", "effect_path", "expected_effect_sha256"
        }:
            raise AttestationError("tool evidence contract has the wrong fields")
        effect_path = Path(str(tool_evidence["effect_path"]))
        canonical_effect = _canonical_path(str(effect_path))
        if not any(
            _within_scope(canonical_effect, _canonical_path(scope))
            for scope in authenticated_claims.write_scope
        ):
            raise AttestationError("tool evidence path is outside the authorized write scope")
        if effect_path.exists():
            raise AttestationError("tool evidence path must not pre-exist the fresh launch")
        _hash(str(tool_evidence["expected_effect_sha256"]), "expected tool effect")

        captured: dict[str, object] = {}

        def boundary_launcher(canary_runner, command, **kwargs):
            nonlocal prepared
            captured["command"] = tuple(command)
            captured["environment_keys"] = tuple(sorted(prepared.environment))
            try:
                return launch_if_canary_passes(canary_runner, command, **kwargs)
            finally:
                # launch_if_canary_passes owns and closes the one-use receipt.
                prepared = None

        completed = launch_task(
            envelope,
            signing_key,
            role,
            executable=executable,
            canary_runner=lambda: prepared,
            expected_task_id=claims.task_id,
            expected_attempt_id=claims.attempt_id,
            expected_generation=claims.generation,
            now=now,
            lane_args=tuple(lane_args),
            launcher=boundary_launcher,
        )
        if not isinstance(completed, subprocess.CompletedProcess):
            raise AttestationError("fresh lane launcher returned the wrong receipt type")
        try:
            observed_effect = hashlib.sha256(effect_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise AttestationError(f"tool operation effect was not produced: {exc}") from exc
        command = captured["command"]
        evidence_payload = {
            "command": command,
            "returncode": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
            "effect_sha256": observed_effect,
        }
        operation_evidence = OperationEvidence(
            tool=str(tool_evidence["tool"]),
            operation=str(tool_evidence["operation"]),
            evidence_kind="operation",
            expected_effect=str(tool_evidence["expected_effect_sha256"]),
            observed_effect=observed_effect,
            effect_observed=observed_effect == tool_evidence["expected_effect_sha256"],
            exit_code=completed.returncode,
            sandbox_denied=False,
            profile_sha256=claims.stage1_profile_sha256,
            envelope_sha256=envelope.envelope_sha256,
            evidence_sha256=hashlib.sha256(_canonical_json(evidence_payload)).hexdigest(),
            observed_at=int(time.time()),
        )
        tool_attestation = attest_tool_operation(
            operation_evidence,
            expected_profile_sha256=claims.stage1_profile_sha256,
            expected_envelope_sha256=envelope.envelope_sha256,
        )
        canary_payload = asdict(canary)
        launch_evidence = LaunchEvidence(
            envelope_sha256=envelope.envelope_sha256,
            profile_sha256=claims.stage1_profile_sha256,
            request_sha256=claims.stage1_request_sha256,
            scope_sha256=claims.stage1_scope_sha256,
            supervisor_build_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            cli_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            argv_sha256=hashlib.sha256(_canonical_json(command)).hexdigest(),
            environment_keys_sha256=hashlib.sha256(
                _canonical_json(captured["environment_keys"])
            ).hexdigest(),
            canary_sha256=hashlib.sha256(_canonical_json(canary_payload)).hexdigest(),
            admission_sha256=hashlib.sha256(admission_json.encode("utf-8")).hexdigest(),
            allowed_write=canary.allowed_write,
            denied_write=canary.denied_write,
            exact_broker_port=canary.exact_broker_port,
            wrong_port_denied=canary.wrong_port_denied,
            descriptor_audit_passed=canary.fd3_closed,
            inode_audit_passed=trusted_boundary["inode_audit_passed"],
            broker_healthy=trusted_boundary["broker_healthy"],
            observed_at=int(time.time()),
        )
        launch_attestation = attest_launch(
            launch_evidence,
            expected_envelope_sha256=envelope.envelope_sha256,
        )
        binding_payload = {
            "task_id": claims.task_id,
            "attempt_id": claims.attempt_id,
            "generation": claims.generation,
            "envelope_sha256": envelope.envelope_sha256,
            "launch_attestation_sha256": launch_attestation.sha256,
            "tool_attestation_sha256": tool_attestation.sha256,
            "reconciliation_nonce": claims.reconciliation_nonce,
        }
        return {
            "status": "launched",
            **binding_payload,
            "reconciliation_binding_sha256": hashlib.sha256(
                _canonical_json(binding_payload)
            ).hexdigest(),
        }
    finally:
        if prepared is not None:
            prepared.close()
        close_writable_scopes(audited_scopes)


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    launch_parser = subparsers.add_parser("supervisor-launch")
    launch_parser.add_argument("--request", type=Path, required=True)
    launch_parser.add_argument("--runtime-context", type=Path, required=True)
    launch_parser.add_argument("--workload-class", required=True)
    launch_parser.add_argument("--admission-json", required=True)
    args = parser.parse_args(list(argv))
    try:
        result = _supervisor_launch(
            args.request,
            args.runtime_context,
            args.workload_class,
            args.admission_json,
        )
    except (AttestationError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "denied", "reason": str(exc)}, sort_keys=True))
        return 74
    print(json.dumps(result, sort_keys=True))
    return 0


__all__ = [
    "TOOL_ATTESTATION_SCHEMA",
    "LAUNCH_ATTESTATION_SCHEMA",
    "RECONCILIATION_SCHEMA",
    "AttestationError",
    "LaunchEvidence",
    "LaunchAttestation",
    "OperationEvidence",
    "ToolAttestation",
    "ReconciliationChain",
    "attest_launch",
    "attest_tool_operation",
    "capture_tool_operation",
    "reconcile_result",
]


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
