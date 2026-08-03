#!/usr/bin/env python3
"""Derive and validate the dispatcher-owned verification-contract/v1 object."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

CONTRACT_VERSION = "verification-contract/v1"
SUPPORTED_TYPED_MODES = frozenset({"project", "bounty", "advisory"})
REQUIRED_PHASE_IDS = tuple(f"S{i}" for i in range(8))
LANE_TO_AUTHOR_FAMILY = {
    "claude": "claude",
    "gpt-codex": "openai",
    "codex": "openai",
    "gemini": "google",
    "kimi": "kimi",
}

_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VALID_GATES = frozenset(
    {
        "destructive_action",
        "external_delivery",
        "human_approval",
        "live_dispatch",
        "network_access",
        "operator_approval",
        "paid_tool",
        "production_mutation",
        "public_release",
        "credential_change",
        "cleanup",
        "delete",
        "live_outreach",
        "malware_detonation",
        "offensive_execution",
        "paid_media",
        "secrets_access",
        "bounty_authorization",
    }
)
_DERIVATION_RESERVED_FIELDS = frozenset(
    {"author_family", "verification_contract", "verification_contract_sha256"}
)
# Pathspec magic and glob metacharacters. An authorized deletion target is a
# literal file path, never a pattern: a pattern would let one approved entry
# stand for an unbounded set of files at integration time, which is exactly the
# authority inflation the enumerated design exists to prevent.
_PATHSPEC_PATTERN_CHARACTERS = frozenset("*?[]\\")
_MAX_AUTHORIZED_DELETE_PATHS = 512


class ContractError(ValueError):
    """Raised when a verification contract or its admission is invalid."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the single canonical JSON representation used by the spine."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical-JSON serializable: {exc}") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def author_family_for_lane(to_model: object) -> str:
    if not isinstance(to_model, str) or to_model not in LANE_TO_AUTHOR_FAMILY:
        raise ContractError(f"unsupported to_model lane: {to_model!r}")
    return LANE_TO_AUTHOR_FAMILY[to_model]


def verification_contract_sha256(contract: dict[str, object]) -> str:
    return sha256_hex(canonical_json_bytes(contract))


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a nonempty string")
    return value


def _capability_from_admission(admission: Mapping[str, object]) -> dict[str, object]:
    raw = admission.get("capability", admission.get("capability_snapshot"))
    if raw is None:
        return {"id": None, "card_sha256": None, "derived_state": None}
    if not isinstance(raw, Mapping):
        raise ContractError("capability must be an object or null")
    capability_id = raw.get("id", raw.get("capability_id"))
    card_sha256 = raw.get("card_sha256", raw.get("capability_card_sha256"))
    derived_state = raw.get("derived_state", raw.get("capability_state"))
    if capability_id is not None:
        _nonempty_string(capability_id, "capability.id")
    if card_sha256 is not None and (
        not isinstance(card_sha256, str) or not _LOWER_SHA256.fullmatch(card_sha256)
    ):
        raise ContractError("capability.card_sha256 must be lowercase 64-hex or null")
    if derived_state is not None and derived_state not in {
        "live",
        "lane-gated",
        "degraded-blueprint",
        "needs_tool",
    }:
        raise ContractError("capability.derived_state is invalid")
    return {
        "id": capability_id,
        "card_sha256": card_sha256,
        "derived_state": derived_state,
    }


def normalize_authorized_delete_path(value: object) -> str:
    """Validate one operator-authorized deletion target, file-precise.

    Deletion authority is enumerated, never inferred: this accepts exactly one
    canonical, repo-relative, literal FILE path. Directory entries (trailing
    slash), globs, pathspec magic, traversal, and absolute paths are all
    rejected here so the contract itself cannot carry an entry that stands for
    more than one file. Whether the path is *actually* a blob rather than a
    tree is re-checked against the immutable base tree at integration time,
    where a git object store is available.
    """

    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError("authorized_delete_paths entry is empty or invalid")
    if value.startswith("/"):
        raise ContractError(
            f"authorized_delete_paths entry must be repo-relative: {value!r}"
        )
    if value.startswith(":"):
        raise ContractError(
            f"authorized_delete_paths entry must not use pathspec magic: {value!r}"
        )
    if any(character in _PATHSPEC_PATTERN_CHARACTERS for character in value):
        raise ContractError(
            f"authorized_delete_paths entry must be a literal path, not a pattern: {value!r}"
        )
    if value.endswith("/"):
        raise ContractError(
            f"authorized_delete_paths entry must name a file, not a directory: {value!r}"
        )
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ContractError(
            f"authorized_delete_paths entry is not a canonical path: {value!r}"
        )
    return value


def _authorized_delete_paths(admission: Mapping[str, object]) -> list[str]:
    raw = admission.get("authorized_delete_paths")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContractError("authorized_delete_paths must be a list of file paths")
    if len(raw) > _MAX_AUTHORIZED_DELETE_PATHS:
        raise ContractError(
            f"authorized_delete_paths exceeds {_MAX_AUTHORIZED_DELETE_PATHS} entries"
        )
    normalized = [normalize_authorized_delete_path(entry) for entry in raw]
    if len(set(normalized)) != len(normalized):
        raise ContractError("authorized_delete_paths contains duplicate entries")
    return sorted(normalized)


def _gate_values(admission: Mapping[str, object]) -> list[str]:
    values: list[object] = []
    capability = admission.get("capability", admission.get("capability_snapshot"))
    if isinstance(capability, Mapping):
        for key in ("expected_gates", "operator_gates", "gates"):
            raw = capability.get(key)
            if raw is not None:
                if not isinstance(raw, list):
                    raise ContractError(f"capability.{key} must be a list")
                values.extend(raw)
    for key in ("runtime_map_gates", "runtime_gates", "expected_gates"):
        raw = admission.get(key)
        if raw is not None:
            if not isinstance(raw, list):
                raise ContractError(f"{key} must be a list")
            values.extend(raw)
    gates: set[str] = set()
    for value in values:
        if not isinstance(value, str) or value not in _VALID_GATES:
            raise ContractError(f"unknown verification gate: {value!r}")
        gates.add(value)
    return sorted(gates)


def derive_verification_contract(admission: dict[str, object]) -> dict[str, object]:
    if not isinstance(admission, dict):
        raise ContractError("admission must be an object")
    forbidden = sorted(_DERIVATION_RESERVED_FIELDS.intersection(admission))
    if forbidden:
        raise ContractError(f"admission contains dispatcher-owned field: {forbidden[0]}")

    mode = admission.get("mode")
    if mode not in SUPPORTED_TYPED_MODES:
        raise ContractError(f"unsupported typed mode: {mode!r}")
    task_id = _nonempty_string(admission.get("task_id"), "task_id")
    run_id = _nonempty_string(admission.get("run_id"), "run_id")
    result_type = admission.get("result_type") or "normal"
    if mode == "project" and result_type != "normal":
        raise ContractError("Project supports only result_type normal")
    if mode == "bounty" and result_type not in {"normal", "dry_run"}:
        raise ContractError("Bounty result_type must be normal or dry_run")
    if mode == "advisory" and result_type != "normal":
        raise ContractError("Advisory supports only result_type normal")
    dispatch_kind = admission.get("dispatch_kind", "single")
    if dispatch_kind not in {"single", "panel", "swarm"}:
        raise ContractError("dispatch_kind must be single, panel, or swarm")
    author_family = author_family_for_lane(admission.get("to_model"))

    if mode == "project":
        verification_kinds = ["project_tests", "recipient_contract"]
        bounty_policy: dict[str, object] | None = None
        required_phase_ids = list(REQUIRED_PHASE_IDS)
        memory_policy = {"recall": "required", "record": "required"}
        plan_review_policy = {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "plan_sha256",
        }
    elif mode == "bounty":
        verification_kinds = (
            ["scope_gate", "no_self_inflicted", "negative_control"]
            if result_type == "dry_run"
            else ["scope_gate", "no_self_inflicted", "poc_reproduction"]
        )
        bounty_policy = {
            "scope_gate_required": True,
            "exact_target_allowlist_required": True,
            "no_self_inflicted_required": True,
            "submission_attempted_allowed": False,
            "normal_finding_requirements": [
                "cvss_v4",
                "cross_family_reproduction",
                "negative_control",
            ],
            "dry_run_requirements": [
                "empty_findings",
                "kill_or_negative_evidence",
                "no_submit_evidence",
                "primitive_ledger",
            ],
        }
        required_phase_ids = list(REQUIRED_PHASE_IDS)
        # `recall` is OPTIONAL in bounty mode, deliberately. A cold lane cannot both call
        # recall and stay uncontaminated: no filter excludes prior *runs*, because
        # `written_before` compartments only same-run notes and so includes every earlier
        # campaign. Four lanes on one run received a sealed run's kill conclusions this
        # way despite never opening the quarantined directory, and one leaked claim was
        # also factually wrong. Requiring the call mandated the contamination. Recording
        # stays required: writing findings biases nobody. If a lane does call recall, the
        # mode requires it to disclose verbatim what came back.
        memory_policy = {"recall": "optional", "record": "required"}
        plan_review_policy = {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "plan_sha256",
        }
    else:
        verification_kinds = ["artifact_written"]
        bounty_policy = None
        required_phase_ids = []
        memory_policy = {"recall": "optional", "record": "optional"}
        plan_review_policy = {"required": False}

    contract: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "mode": mode,
        "result_type": result_type,
        "dispatch_kind": dispatch_kind,
        "author_family": author_family,
        "capability": _capability_from_admission(admission),
        "required_phase_ids": required_phase_ids,
        "required_verification_kinds": verification_kinds,
        "memory_policy": memory_policy,
        "plan_review_policy": plan_review_policy,
        "deliverable_review_policy": {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "artifact_bundle_sha256",
        },
        "artifact_policy": {
            "hashes_required": True,
            "bundle_hash_algorithm": "canonical-artifact-list-sha256/v1",
        },
        "action_log_policy": {"required": True},
        "iteration_policy": {
            "routes": ["S2", "S3"],
            "invalidates_on": ["plan_sha256", "artifact_bundle_sha256"],
        },
        "expected_gates": _gate_values(admission),
        "external_delivery_policy": {"allowed": False},
        "bounty_policy": bounty_policy,
    }
    _apply_authorized_delete_paths(contract, _authorized_delete_paths(admission), mode)
    if mode == "advisory":
        for project_or_bounty_key in (
            "deliverable_review_policy",
            "artifact_policy",
            "action_log_policy",
            "iteration_policy",
            "bounty_policy",
        ):
            contract.pop(project_or_bounty_key)
    return validate_verification_contract(contract)


def _apply_authorized_delete_paths(
    contract: dict[str, object],
    authorized_delete_paths: list[str],
    mode: object,
) -> None:
    """Attach the enumerated deletion authority, present iff non-empty.

    The key is omitted rather than emitted as ``[]`` for the overwhelmingly
    common no-deletion case. That keeps every already-dispatched contract
    byte-identical (and so keeps its pinned ``verification_contract_sha256``
    valid), and it makes the canonical form self-enforcing: a contract that
    carries an explicit empty list re-derives to one that omits the key, so the
    validator's equality check rejects it.
    """

    if not authorized_delete_paths:
        return
    if mode == "advisory":
        raise ContractError("advisory mode cannot authorize deletions")
    contract["authorized_delete_paths"] = authorized_delete_paths


def validate_verification_contract(contract: object) -> dict[str, object]:
    if not isinstance(contract, dict):
        raise ContractError("verification contract must be an object")
    mode = contract.get("mode")
    required_keys = {
        "contract_version",
        "task_id",
        "run_id",
        "mode",
        "result_type",
        "dispatch_kind",
        "author_family",
        "capability",
        "required_phase_ids",
        "required_verification_kinds",
        "memory_policy",
        "plan_review_policy",
        "expected_gates",
        "external_delivery_policy",
    }
    if mode != "advisory":
        required_keys.update(
            {
                "deliverable_review_policy",
                "artifact_policy",
                "action_log_policy",
                "iteration_policy",
                "bounty_policy",
            }
        )
    if "authorized_delete_paths" in contract:
        # Optional-when-empty: only a delete-carrying contract has the key at
        # all. Its VALUE is still fully re-derived and equality-checked below,
        # so admitting the key here only improves the error message.
        required_keys.add("authorized_delete_paths")
    if set(contract) != required_keys:
        missing = sorted(required_keys - set(contract))
        extra = sorted(set(contract) - required_keys)
        raise ContractError(f"contract keys mismatch (missing={missing}, extra={extra})")
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ContractError("contract_version is not verification-contract/v1")

    result_type = contract.get("result_type")
    author_family = contract.get("author_family")
    if author_family not in set(LANE_TO_AUTHOR_FAMILY.values()):
        raise ContractError("author_family is invalid")
    admission: dict[str, object] = {
        "task_id": contract.get("task_id"),
        "run_id": contract.get("run_id"),
        "mode": mode,
        "result_type": result_type,
        "dispatch_kind": contract.get("dispatch_kind"),
        "to_model": next(
            lane for lane, family in LANE_TO_AUTHOR_FAMILY.items() if family == author_family
        ),
        "capability": contract.get("capability"),
        "expected_gates": contract.get("expected_gates"),
        "authorized_delete_paths": contract.get("authorized_delete_paths"),
    }
    expected = derive_verification_contract_unchecked(admission)
    if contract != expected:
        raise ContractError("contract does not match the fixed v1 policy")
    canonical_json_bytes(contract)
    return contract


def derive_verification_contract_unchecked(admission: dict[str, object]) -> dict[str, object]:
    """Re-derive for validation without recursively invoking the validator."""

    mode = admission.get("mode")
    if mode not in SUPPORTED_TYPED_MODES:
        raise ContractError(f"unsupported typed mode: {mode!r}")
    task_id = _nonempty_string(admission.get("task_id"), "task_id")
    run_id = _nonempty_string(admission.get("run_id"), "run_id")
    result_type = admission.get("result_type") or "normal"
    if mode == "project" and result_type != "normal":
        raise ContractError("Project supports only result_type normal")
    if mode == "bounty" and result_type not in {"normal", "dry_run"}:
        raise ContractError("Bounty result_type must be normal or dry_run")
    if mode == "advisory" and result_type != "normal":
        raise ContractError("Advisory supports only result_type normal")
    dispatch_kind = admission.get("dispatch_kind")
    if dispatch_kind not in {"single", "panel", "swarm"}:
        raise ContractError("dispatch_kind must be single, panel, or swarm")
    author_family = author_family_for_lane(admission.get("to_model"))
    capability = _capability_from_admission(admission)
    gates = _gate_values(admission)
    if mode == "project":
        verification_kinds = ["project_tests", "recipient_contract"]
        bounty_policy = None
        required_phase_ids = list(REQUIRED_PHASE_IDS)
        memory_policy = {"recall": "required", "record": "required"}
        plan_review_policy = {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "plan_sha256",
        }
    elif mode == "bounty":
        verification_kinds = (
            ["scope_gate", "no_self_inflicted", "negative_control"]
            if result_type == "dry_run"
            else ["scope_gate", "no_self_inflicted", "poc_reproduction"]
        )
        bounty_policy = {
            "scope_gate_required": True,
            "exact_target_allowlist_required": True,
            "no_self_inflicted_required": True,
            "submission_attempted_allowed": False,
            "normal_finding_requirements": [
                "cvss_v4",
                "cross_family_reproduction",
                "negative_control",
            ],
            "dry_run_requirements": [
                "empty_findings",
                "kill_or_negative_evidence",
                "no_submit_evidence",
                "primitive_ledger",
            ],
        }
        required_phase_ids = list(REQUIRED_PHASE_IDS)
        # `recall` is OPTIONAL in bounty mode, deliberately. A cold lane cannot both call
        # recall and stay uncontaminated: no filter excludes prior *runs*, because
        # `written_before` compartments only same-run notes and so includes every earlier
        # campaign. Four lanes on one run received a sealed run's kill conclusions this
        # way despite never opening the quarantined directory, and one leaked claim was
        # also factually wrong. Requiring the call mandated the contamination. Recording
        # stays required: writing findings biases nobody. If a lane does call recall, the
        # mode requires it to disclose verbatim what came back.
        memory_policy = {"recall": "optional", "record": "required"}
        plan_review_policy = {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "plan_sha256",
        }
    else:
        verification_kinds = ["artifact_written"]
        bounty_policy = None
        required_phase_ids = []
        memory_policy = {"recall": "optional", "record": "optional"}
        plan_review_policy = {"required": False}
    contract: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "mode": mode,
        "result_type": result_type,
        "dispatch_kind": dispatch_kind,
        "author_family": author_family,
        "capability": capability,
        "required_phase_ids": required_phase_ids,
        "required_verification_kinds": verification_kinds,
        "memory_policy": memory_policy,
        "plan_review_policy": plan_review_policy,
        "deliverable_review_policy": {
            "required": True,
            "anti_affinity": "author_family",
            "subject": "artifact_bundle_sha256",
        },
        "artifact_policy": {
            "hashes_required": True,
            "bundle_hash_algorithm": "canonical-artifact-list-sha256/v1",
        },
        "action_log_policy": {"required": True},
        "iteration_policy": {
            "routes": ["S2", "S3"],
            "invalidates_on": ["plan_sha256", "artifact_bundle_sha256"],
        },
        "expected_gates": gates,
        "external_delivery_policy": {"allowed": False},
        "bounty_policy": bounty_policy,
    }
    _apply_authorized_delete_paths(contract, _authorized_delete_paths(admission), mode)
    if mode == "advisory":
        for project_or_bounty_key in (
            "deliverable_review_policy",
            "artifact_policy",
            "action_log_policy",
            "iteration_policy",
            "bounty_policy",
        ):
            contract.pop(project_or_bounty_key)
    return contract


def read_yaml_frontmatter(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read packet {path}: {exc}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(f"packet has no YAML frontmatter: {path}")
    try:
        close = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ContractError(f"packet frontmatter is unterminated: {path}") from exc
    parsed: dict[str, object] = {}
    for line in lines[1:close]:
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        if value.startswith(("{", "[")):
            try:
                parsed[key] = json.loads(value)
            except json.JSONDecodeError as exc:
                if key == "verification_contract":
                    raise ContractError(
                        f"packet frontmatter field {key} is invalid inline JSON: {path}"
                    ) from exc
                # Sibling packet fields are YAML and may legitimately use forms
                # (for example an unquoted write_scope flow list) that are not JSON.
                parsed[key] = value
        elif value in {"true", "false", "null"}:
            parsed[key] = json.loads(value)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            parsed[key] = value[1:-1]
        else:
            parsed[key] = value
    return parsed


def read_packet_contract_echoes(
    root: Path, task_id: str
) -> list[tuple[Path, dict[str, object], str]]:
    _nonempty_string(task_id, "task_id")
    paths: list[Path] = []
    for state in ("inbox", "active", "archive"):
        paths.extend(root.glob(f"departments/*/{state}/{task_id}.md"))
    paths = sorted(set(paths))
    if not paths:
        raise ContractError(f"no dispatched packet echo found for {task_id}")
    echoes: list[tuple[Path, dict[str, object], str]] = []
    identity: tuple[bytes, str] | None = None
    for path in paths:
        frontmatter = read_yaml_frontmatter(path)
        raw_contract = frontmatter.get("verification_contract")
        contract = validate_verification_contract(raw_contract)
        digest = frontmatter.get("verification_contract_sha256")
        if not isinstance(digest, str) or not _LOWER_SHA256.fullmatch(digest):
            raise ContractError(f"packet contract hash is not lowercase 64-hex: {path}")
        if verification_contract_sha256(contract) != digest:
            raise ContractError(f"packet contract hash mismatch: {path}")
        current = (canonical_json_bytes(contract), digest)
        if identity is not None and current != identity:
            raise ContractError(f"divergent packet contract echo: {path}")
        identity = current
        echoes.append((path, contract, digest))
    return echoes


def _derive_cli(admission_json: str) -> dict[str, object]:
    try:
        admission = json.loads(admission_json)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid admission JSON: {exc.msg}") from exc
    contract = derive_verification_contract(admission)
    return {
        "verification_contract": contract,
        "verification_contract_sha256": verification_contract_sha256(contract),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    derive_parser = subparsers.add_parser("derive")
    derive_parser.add_argument("--admission-json", required=True)
    args = parser.parse_args(argv)
    try:
        result = _derive_cli(args.admission_json)
    except ContractError as exc:
        print(f"verification contract error: {exc}", file=sys.stderr)
        return 2
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
