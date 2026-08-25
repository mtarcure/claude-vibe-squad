#!/usr/bin/env python3
"""Derive and validate the dispatcher-owned verification-contract/v1 object."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _strict_json(raw: str) -> object:
    return json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


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
    # Pathspec magic and glob syntax were two separately-maintained clauses
    # asking one question: is this entry a literal path, or something git would
    # expand into more than one file? They are one clause now. Both forms are
    # still rejected and the diagnostic still names which shapes are refused --
    # the merge removes a duplicated decision, not a refusal.
    if value.startswith(":") or any(
        character in _PATHSPEC_PATTERN_CHARACTERS for character in value
    ):
        raise ContractError(
            "authorized_delete_paths entry must be a literal path, not pathspec "
            f"magic or a pattern: {value!r}"
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


def _collect_gate_list(
    values: list[object], source: Mapping[str, object], key: str, label: str
) -> None:
    """Accumulate one gate field, refusing any non-list value.

    The capability-scoped and admission-scoped gate fields asked the same
    question -- "is this field a list?" -- from two separately-maintained
    clauses. One validator owns it now. ``label`` carries the caller's
    qualified field name, so a rejection still names the exact field that was
    wrong rather than collapsing six diagnostics into one.
    """

    raw = source.get(key)
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ContractError(f"{label} must be a list")
    values.extend(raw)


def _gate_values(admission: Mapping[str, object]) -> list[str]:
    values: list[object] = []
    capability = admission.get("capability", admission.get("capability_snapshot"))
    if isinstance(capability, Mapping):
        for key in ("expected_gates", "operator_gates", "gates"):
            _collect_gate_list(values, capability, key, f"capability.{key}")
    for key in ("runtime_map_gates", "runtime_gates", "expected_gates"):
        _collect_gate_list(values, admission, key, key)
    gates: set[str] = set()
    for value in values:
        if not isinstance(value, str) or value not in _VALID_GATES:
            raise ContractError(f"unknown verification gate: {value!r}")
        gates.add(value)
    return sorted(gates)


def _review_required(admission: Mapping[str, object], dispatch_kind: str) -> bool:
    """Whether the pinned contract records that a deliverable review is OWED.

    This is the on/off half of ``deliverable_review_policy``. Its sibling fields
    ``anti_affinity`` and ``subject`` describe HOW a deliverable review is
    conducted when one happens; this describes WHETHER one is owed at all. The
    code-enforced home for the owed decision is the reconciler
    (``mandatory_review``/``review_triggers`` -> ``cross_family_review_pending``),
    not this contract field -- nothing in the settlement path reads it. It exists
    so a worker reading the pinned contract is told the same thing the reconciler
    will enforce; when it disagreed (hardcoded ``True`` while the four triggers
    said no review was owed) workers returned ``needs_review`` asking for a review
    Chrono never dispatches, and the task sat open forever.

    ``swarm`` members are always reviewed -- ``bin/send-task.sh`` pins every member
    packet ``mandatory_review: true`` -- so the field is forced ``True`` there
    regardless of what the admission carried. That preserves the anti-tamper
    invariant a swarm contract relies on: a member cannot be weakened to skip its
    review, because re-derivation restores ``True`` and the validator's equality
    check rejects any tampered ``False``.

    For ``single``/``panel`` the value comes from the admission's
    ``review_required``. It DEFAULTS to ``True`` only when the key is ABSENT, so
    an un-wired producer and every already-pinned contract derive byte-identically
    to before this field existed -- the change is inert until a producer starts
    passing the trigger decision. Membership is tested rather than ``.get()``
    because a present JSON ``null`` is not an omitted field: canonicalizing it to
    ``True`` was fail-closed but silently rewrote malformed producer input that
    the declared admission type says must be a boolean.
    """

    if dispatch_kind == "swarm":
        return True
    if "review_required" not in admission:
        return True
    raw = admission["review_required"]
    if not isinstance(raw, bool):
        raise ContractError("review_required must be a boolean")
    return raw


def derive_verification_contract(admission: dict[str, object]) -> dict[str, object]:
    if not isinstance(admission, dict):
        raise ContractError("admission must be an object")
    forbidden = sorted(_DERIVATION_RESERVED_FIELDS.intersection(admission))
    if forbidden:
        raise ContractError(
            f"admission contains dispatcher-owned field: {forbidden[0]}"
        )
    contract = derive_verification_contract_unchecked(admission)
    # The admission IS the trusted review decision here, so hand it to the
    # validator as the external expectation instead of letting validation
    # recover the value from the object it is checking.
    return validate_verification_contract(
        contract,
        expected_review_required=_review_required(
            admission, contract["dispatch_kind"]
        ),
    )


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


def validate_verification_contract(
    contract: object, *, expected_review_required: bool | None = None
) -> dict[str, object]:
    """Check a contract against the fixed v1 policy, naming any bad field.

    ``expected_review_required`` is the trusted external review decision, when
    the caller holds one -- derived from a validated admission and its triggers,
    never from the contract under check. With it supplied, a
    ``deliverable_review_policy.required`` that disagrees is rejected. Without
    it, this function can only prove INTERNAL consistency: a tampered
    ``required`` with a recomputed adjacent hash is self-consistent, which is
    exactly the circularity a codex-family review rejected on 2026-08-24.
    Callers on a trust boundary therefore either supply the expectation (the
    derive path does) or compare the whole contract against the locked
    registry pin (`dispatch_context_builder.require_registry_contract_pin`
    does, at dispatch admission).
    """

    if expected_review_required is not None and not isinstance(
        expected_review_required, bool
    ):
        raise ContractError("expected_review_required must be a boolean or None")
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
        raise ContractError(
            f"contract keys mismatch (missing={missing}, extra={extra})"
        )
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
            lane
            for lane, family in LANE_TO_AUTHOR_FAMILY.items()
            if family == author_family
        ),
        "capability": contract.get("capability"),
        "expected_gates": contract.get("expected_gates"),
        "authorized_delete_paths": contract.get("authorized_delete_paths"),
    }
    # `deliverable_review_policy.required` is a derived-from-admission value,
    # not a fixed constant. When the caller supplied the trusted expectation,
    # the re-derivation uses THAT -- recovering the value from the contract
    # under check would make any internally-consistent tamper
    # self-authenticating, which is the circularity the 2026-08-24 review
    # rejected. Recovery remains only for expectation-less callers, where it
    # keeps a legitimate `required: false` from failing its own equality
    # check; those callers prove legitimacy elsewhere (see docstring). The
    # swarm invariant holds on every path: `_review_required` forces True for
    # a swarm contract regardless of the recovered OR expected value, so a
    # member tampered down to `false` re-derives to True and the equality
    # check rejects it (test_swarm_child_cannot_weaken_review...).
    deliverable_policy = contract.get("deliverable_review_policy")
    if expected_review_required is not None:
        admission["review_required"] = expected_review_required
    elif isinstance(deliverable_policy, Mapping) and "required" in deliverable_policy:
        admission["review_required"] = deliverable_policy["required"]
    expected = derive_verification_contract_unchecked(admission)
    if contract != expected:
        # Name the fields. This function's contract is to identify the bad field
        # (F7), but a whole-object comparison collapsed every divergence into one
        # message that named nothing -- leaving an author to diff a 19-key
        # contract by eye to find which value the dispatcher disagreed with.
        # Compare MEMBERSHIP as well as value. `.get()` returns None both for
        # an absent key and for a key explicitly set to null, so an extra
        # `"authorized_delete_paths": null` differed from the policy yet
        # produced an empty field list -- the first version of this fix still
        # named nothing in exactly the case it was written for.
        missing = object()
        differing = sorted(
            key
            for key in set(contract) | set(expected)
            if contract.get(key, missing) != expected.get(key, missing)
        )
        raise ContractError(
            "contract does not match the fixed v1 policy; differing field(s): "
            + ", ".join(differing)
        )
    canonical_json_bytes(contract)
    return contract


def derive_verification_contract_unchecked(
    admission: dict[str, object],
) -> dict[str, object]:
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
    dispatch_kind = admission.get("dispatch_kind", "single")
    if dispatch_kind not in {"single", "panel", "swarm"}:
        raise ContractError("dispatch_kind must be single, panel, or swarm")
    author_family = author_family_for_lane(admission.get("to_model"))
    capability = _capability_from_admission(admission)
    gates = _gate_values(admission)
    review_required = _review_required(admission, dispatch_kind)
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
            "required": review_required,
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
        close = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
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
        if key in parsed:
            raise ContractError(f"packet has duplicate frontmatter field {key}: {path}")
        if value.startswith(("{", "[")):
            try:
                parsed[key] = _strict_json(value)
            except (json.JSONDecodeError, ValueError) as exc:
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
        admission = _strict_json(admission_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"invalid admission JSON: {exc}") from exc
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
