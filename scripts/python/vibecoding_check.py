#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
#     "httpx>=0.28",
# ]
# ///
"""Vibecoding-check — Layer 2 mode-exit verifier.

Runs deterministic checks before any mode can declare itself "done." Per
spec at `shared/specialists/vibecoding-check.md`.

Universal checks (always):
  1. Typed operator approval record present
  2. Citations resolve (URL 200 / file exists / git ref resolves)
  3. No TODO/FIXME/XXX in modified code
  4. All declared phase-tags emitted

Mode-specific extensions (declared in checks.yaml):
  - project: tests_pass, git_clean, new_code_has_tests, no_destructive_ops
  - bounty: scope_gate_ran, cvss_recorded, poc_reproduces, no_self_inflicted
  - content: voice_consistent, asset_paths_resolve, length_bounds, no_placeholder_text

Usage:
  vibecoding-check.sh --run-id BTY-2026-05-02-1234

Exit codes:
  0  — all checks passed; mode may advance
  1  — tier-1 auto-fix applied; mode may advance
  2  — tier-2 issue; mode should retry the relevant phase
  3  — tier-3 issue; state written; operator surface needed

State files:
  _state/runs/<run-id>/manifest.yaml   — JSON-compatible YAML written by the Lead
  _state/vibecoding-check/<run-id>.md  — written by THIS script for every report
  _state/approvals/<run-id>.md         — operator-owned vibecoding-approval/v1 record
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import uuid
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from verification_contract import (
    LANE_TO_AUTHOR_FAMILY,
    REQUIRED_PHASE_IDS,
    ContractError,
    author_family_for_lane,
    canonical_json_bytes,
    read_packet_contract_echoes,
    read_yaml_frontmatter,
    validate_verification_contract,
    verification_contract_sha256,
)
from repo_root import resolve_vault_root

VAULT_ROOT = resolve_vault_root()
STATE_DIR = VAULT_ROOT / "_state"
RUNS_DIR = STATE_DIR / "runs"
APPROVALS_DIR = STATE_DIR / "approvals"
CHECK_DIR = STATE_DIR / "vibecoding-check"

# Severity ladders
TIER_OK = 0
TIER_AUTOFIX = 1
TIER_RETRY = 2
TIER_OPERATOR = 3

RUN_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,126}[A-Za-z0-9])?$")
APPROVAL_SCHEMA = "vibecoding-approval/v1"
SHELL_METACHAR_RE = re.compile(r"[;&|`$<>\r\n]")
METADATA_IPS = frozenset({ipaddress.ip_address("169.254.169.254")})
KNOWN_AUTHOR_FAMILIES = frozenset(LANE_TO_AUTHOR_FAMILY.values())


@dataclass
class CheckResult:
    name: str
    passed: bool
    tier: int = TIER_OK   # promotion tier on failure (0 = pass)
    detail: str = ""
    auto_fixed: bool = False
    advisory: bool = False


@dataclass
class RunReport:
    run_id: str
    mode: str
    started_at: str
    finished_at: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_tier(self) -> int:
        return max((c.tier for c in self.checks if not c.passed), default=TIER_OK)

    @property
    def passed(self) -> bool:
        return self.overall_tier == TIER_OK


class ManifestContractError(ValueError):
    """A typed manifest violated the dispatcher-pinned contract."""


class CitationPolicyError(ManifestContractError):
    """A citation URL violates the verifier's outbound-network policy."""


@dataclass(frozen=True)
class ApprovalRecord:
    run_id: str
    decision: str
    override_reason: str | None = None
    deletion_approved: bool = False
    deleted_paths: tuple[str, ...] = ()
    deletion_reason: str | None = None
    legacy_exact_approve: bool = False


def validate_run_id(value: object) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise ManifestContractError(
            "run_id must be 1-128 ASCII letters, digits, underscores, or hyphens "
            "and must start and end with a letter or digit"
        )
    return value


def _vault_realpath() -> Path:
    try:
        return VAULT_ROOT.resolve(strict=True)
    except OSError as exc:
        raise ManifestContractError(f"VAULT_ROOT does not resolve: {VAULT_ROOT}") from exc


def _resolve_contained_candidate(
    candidate: Path,
    *,
    allowed_root: Path,
    field_name: str,
    must_exist: bool,
    kind: str | None = None,
    reject_final_symlink: bool = True,
) -> Path:
    """Canonicalize a path and prove it remains under a dedicated vault root."""
    vault = _vault_realpath()
    try:
        root = allowed_root.resolve(strict=must_exist)
        resolved = candidate.resolve(strict=must_exist)
    except OSError as exc:
        raise ManifestContractError(f"{field_name} does not exist: {candidate}") from exc
    if not root.is_relative_to(vault):
        raise ManifestContractError(f"{field_name} allowed root escapes VAULT_ROOT")
    if not resolved.is_relative_to(root):
        raise ManifestContractError(f"{field_name} escapes {allowed_root}")
    if reject_final_symlink and candidate.is_symlink():
        raise ManifestContractError(f"{field_name} must not be a symlink")
    if must_exist and kind == "file" and not resolved.is_file():
        raise ManifestContractError(f"{field_name} must be a regular file")
    if must_exist and kind == "dir" and not resolved.is_dir():
        raise ManifestContractError(f"{field_name} must be a directory")
    return resolved


def _run_state_path(run_id: object, filename: str, *, must_exist: bool) -> Path:
    validated = validate_run_id(run_id)
    return _resolve_contained_candidate(
        RUNS_DIR / validated / filename,
        allowed_root=RUNS_DIR,
        field_name=f"run {filename}",
        must_exist=must_exist,
        kind="file" if must_exist else None,
    )


def _approval_path(run_id: object, *, must_exist: bool) -> Path:
    validated = validate_run_id(run_id)
    return _resolve_contained_candidate(
        APPROVALS_DIR / f"{validated}.md",
        allowed_root=APPROVALS_DIR,
        field_name="approval path",
        must_exist=must_exist,
        kind="file" if must_exist else None,
    )


def _state_output_path(run_id: object) -> Path:
    validated = validate_run_id(run_id)
    vault = _vault_realpath()
    prospective_root = CHECK_DIR.resolve(strict=False)
    if not prospective_root.is_relative_to(vault):
        raise ManifestContractError("vibecoding-check output root escapes VAULT_ROOT")
    if CHECK_DIR.is_symlink():
        raise ManifestContractError("vibecoding-check output root must not be a symlink")
    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    return _resolve_contained_candidate(
        CHECK_DIR / f"{validated}.md",
        allowed_root=CHECK_DIR,
        field_name="vibecoding-check output path",
        must_exist=False,
    )


def resolve_vault_file(value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestContractError(f"{field_name} must be a nonempty path")
    raw = Path(value)
    candidate = raw if raw.is_absolute() else VAULT_ROOT / raw
    return _resolve_contained_candidate(
        candidate,
        allowed_root=VAULT_ROOT,
        field_name=field_name,
        must_exist=True,
        kind="file",
    )


def resolve_vault_candidate(value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestContractError(f"{field_name} must be a nonempty path")
    raw = Path(value)
    candidate = raw if raw.is_absolute() else VAULT_ROOT / raw
    return _resolve_contained_candidate(
        candidate,
        allowed_root=VAULT_ROOT,
        field_name=field_name,
        must_exist=False,
    )


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_canonical(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_active_registry_entry(task_id: str) -> dict[str, Any]:
    registry_path = STATE_DIR / "active-tasks.json"
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    if not isinstance(registry, dict) or not isinstance(registry.get(task_id), dict):
        raise ManifestContractError(f"active registry has no object entry for {task_id}")
    return registry[task_id]


def validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ManifestContractError("manifest must be an object")
    if manifest.get("schema_version") != "verification-run/v1":
        raise ManifestContractError("schema_version must be verification-run/v1")
    for field_name in ("task_id", "run_id", "mode", "result_type", "author_family"):
        if not isinstance(manifest.get(field_name), str) or not manifest[field_name]:
            raise ManifestContractError(f"{field_name} must be a nonempty string")
    validate_run_id(manifest["run_id"])


def check_typed_profile_supported(manifest: dict[str, Any]) -> CheckResult:
    mode = manifest.get("mode")
    if mode in {"project", "bounty"}:
        return CheckResult("typed_profile_supported", True, detail=f"{mode} v1 profile")
    name = "typed_profile_unsupported" if mode in {
        "content", "research", "incident", "maintenance", "outreach", "triage"
    } else "unknown_mode"
    return CheckResult(name, False, TIER_OPERATOR, f"mode {mode!r} has no typed v1 profile")


def check_verification_contract(manifest: dict[str, Any]) -> CheckResult:
    try:
        validate_manifest_shape(manifest)
        task_id = manifest["task_id"]
        entry = load_active_registry_entry(task_id)
        contract = validate_verification_contract(entry.get("verification_contract"))
        digest = entry.get("verification_contract_sha256")
        if not isinstance(digest, str) or verification_contract_sha256(contract) != digest:
            raise ManifestContractError("registry contract object/hash mismatch")
        pinned_family = author_family_for_lane(entry.get("to_model"))
        if contract["author_family"] != pinned_family:
            raise ManifestContractError("registry lane/author-family mismatch")
        echoes = read_packet_contract_echoes(VAULT_ROOT, task_id)
        if any(echo_contract != contract or echo_hash != digest for _, echo_contract, echo_hash in echoes):
            raise ManifestContractError("packet echo differs from registry")
        manifest_contract = validate_verification_contract(manifest.get("verification_contract"))
        manifest_digest = manifest.get("verification_contract_sha256")
        if manifest_contract != contract or manifest_digest != digest:
            raise ManifestContractError("manifest echo differs from registry")
        for field_name in ("task_id", "run_id", "mode", "result_type", "author_family"):
            if manifest.get(field_name) != contract.get(field_name):
                raise ManifestContractError(f"manifest {field_name} differs from pinned contract")
    except (ContractError, ManifestContractError, OSError, ValueError, KeyError, TypeError) as exc:
        return CheckResult("verification_contract_integrity", False, TIER_OPERATOR, str(exc))
    return CheckResult("verification_contract_integrity", True, detail="registry, packet, and manifest echoes match")


def check_verification_coverage(manifest: dict[str, Any]) -> CheckResult:
    contract = manifest.get("verification_contract") or {}
    required = contract.get("required_verification_kinds") or []
    records = manifest.get("verification_records")
    if not isinstance(records, list) or not records:
        return CheckResult("verification_coverage", False, TIER_OPERATOR, "verification_records is empty")
    kinds = [item.get("kind") for item in records if isinstance(item, dict)]
    missing = [kind for kind in required if kind not in kinds]
    if missing:
        return CheckResult("verification_coverage", False, TIER_OPERATOR, f"missing kinds: {missing}")
    try:
        seen: set[str] = set()
        current_subjects: set[str] | None = None
        if "plan" in manifest and "artifact_bundle_sha256" in manifest:
            plan_sha, bundle_sha = _current_hashes(manifest)
            current_subjects = {plan_sha, bundle_sha}
        for index, item in enumerate(records):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in seen:
                raise ManifestContractError(f"verification_records[{index}] has invalid/duplicate id")
            seen.add(item["id"])
            if current_subjects is not None and item.get("subject_sha256") not in current_subjects:
                raise ManifestContractError("verification record is bound to a stale subject")
            if "evidence_ref" in item:
                path = resolve_vault_file(item["evidence_ref"], field_name="verification evidence")
                if hash_file(path) != item.get("evidence_sha256") or item.get("status") != "passed":
                    raise ManifestContractError("verification evidence hash/status mismatch")
    except ManifestContractError as exc:
        return CheckResult("verification_coverage", False, TIER_OPERATOR, str(exc))
    return CheckResult("verification_coverage", True, detail=f"covered {len(required)} required kinds")


def _current_hashes(manifest: dict[str, Any]) -> tuple[str, str]:
    plan = manifest.get("plan")
    if not isinstance(plan, dict):
        raise ManifestContractError("plan must be an object")
    plan_path = resolve_vault_file(plan.get("path"), field_name="plan.path")
    plan_sha = hash_file(plan_path)
    if plan.get("sha256") != plan_sha:
        raise ManifestContractError("plan hash differs from current bytes")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestContractError("artifacts must be nonempty")
    canonical: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "role"}:
            raise ManifestContractError(f"artifacts[{index}] is malformed")
        path = resolve_vault_file(item["path"], field_name=f"artifacts[{index}].path")
        if item["path"] in seen or hash_file(path) != item["sha256"]:
            raise ManifestContractError(f"artifacts[{index}] duplicate or hash mismatch")
        seen.add(item["path"])
        canonical.append(item)
    bundle = hash_canonical(sorted(canonical, key=lambda item: item["path"]))
    if manifest.get("artifact_bundle_sha256") != bundle:
        raise ManifestContractError("artifact_bundle_sha256 mismatch")
    return plan_sha, bundle


def _contract_recall_required(manifest: dict[str, Any]) -> bool:
    """Whether the dispatcher-pinned contract mandates a recall receipt.

    `memory_policy.recall` is dispatcher-owned and mode-specific: project pins
    it "required", bounty pins it "optional" so a cold hunting lane is never
    forced to call recall (see
    `verification_contract.derive_verification_contract_unchecked` and
    `shared/modes/bounty.md`). The bookend honors that pinned value rather than
    demanding a receipt unconditionally in both modes.
    """
    contract = validate_verification_contract(manifest.get("verification_contract"))
    recall = contract["memory_policy"].get("recall")
    if recall not in {"required", "optional"}:
        raise ManifestContractError("memory_policy.recall must be required or optional")
    return recall == "required"


def check_memory_bookends(manifest: dict[str, Any]) -> CheckResult:
    try:
        _plan_sha, bundle = _current_hashes(manifest)
        memory = manifest.get("memory")
        if not isinstance(memory, dict):
            raise ManifestContractError("memory must be an object")
        recall = memory.get("recall")
        # Recall is required-or-optional per the pinned contract, never
        # unconditional: an optional-recall mode (bounty) may omit the receipt,
        # but a receipt that IS present is still fully validated so a disclosed
        # recall can never be malformed.
        if recall is None:
            if _contract_recall_required(manifest):
                raise ManifestContractError("memory.recall is required")
        else:
            if not isinstance(recall, dict):
                raise ManifestContractError("memory.recall must be an object")
            recall_id = recall.get("recall_id")
            if not isinstance(recall_id, str) or str(uuid.UUID(recall_id)) != recall_id:
                raise ManifestContractError("memory recall_id is not a canonical UUID")
            results = recall.get("results")
            if not isinstance(results, list) or recall.get("no_hits") is not (len(results) == 0):
                raise ManifestContractError("memory no_hits/results mismatch")
            applied = recall.get("applied_note_ids")
            receipts = recall.get("usage_receipts")
            if not isinstance(applied, list) or not isinstance(receipts, list):
                raise ManifestContractError("memory usage coverage is malformed")
            if {item.get("note_id") for item in receipts if isinstance(item, dict)} != set(applied):
                raise ManifestContractError("memory usage receipts do not exactly cover applied notes")
        record = memory.get("record")
        record_receipts = record.get("receipts") if isinstance(record, dict) else None
        if not isinstance(record_receipts, list) or not record_receipts:
            raise ManifestContractError("memory.record.receipts is required")
        for receipt in record_receipts:
            if receipt.get("source_task") != manifest.get("task_id") or receipt.get("source_artifact_hash") != bundle:
                raise ManifestContractError("memory record receipt is not current-task/current-bundle bound")
            if manifest.get("mode") == "bounty" and receipt.get("sensitivity") != "restricted":
                raise ManifestContractError("Bounty memory receipts must be restricted")
    except (ManifestContractError, ValueError, TypeError) as exc:
        return CheckResult("memory_bookends", False, TIER_OPERATOR, str(exc))
    return CheckResult("memory_bookends", True)


def check_review_bindings(manifest: dict[str, Any]) -> CheckResult:
    try:
        plan_sha, bundle = _current_hashes(manifest)
        contract = validate_verification_contract(manifest.get("verification_contract"))
        pinned = contract["author_family"]
        if manifest.get("author_family") != pinned:
            raise ManifestContractError("manifest author_family differs from dispatcher pin")
        reviews = manifest.get("reviews")
        if not isinstance(reviews, dict):
            raise ManifestContractError("reviews must be an object")
        for kind, subject in (("plan", plan_sha), ("deliverable", bundle)):
            review = reviews.get(kind)
            if not isinstance(review, dict) or review.get("required") is not True:
                raise ManifestContractError(f"{kind} review cannot be disabled")
            if review.get("author_family") != pinned or review.get("reviewer_family") == pinned:
                raise ManifestContractError(f"{kind} review violates pinned anti-affinity")
            if review.get("verdict") != "pass" or review.get("subject_sha256") != subject:
                raise ManifestContractError(f"{kind} review is stale or not passing")
            path = resolve_vault_file(review.get("evidence_ref"), field_name=f"reviews.{kind}.evidence_ref")
            if hash_file(path) != review.get("evidence_sha256"):
                raise ManifestContractError(f"{kind} review evidence hash mismatch")
            evidence = read_yaml_frontmatter(path)
            expected = {"review_kind": kind, "reviewer_family": review["reviewer_family"], "subject_sha256": subject, "verdict": "pass"}
            if not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in expected.items()):
                raise ManifestContractError(f"{kind} review file does not echo binding")
    except (ManifestContractError, ContractError, OSError, ValueError, TypeError) as exc:
        return CheckResult("review_bindings", False, TIER_OPERATOR, str(exc))
    return CheckResult("review_bindings", True)


def check_artifact_and_gate_bindings(manifest: dict[str, Any]) -> CheckResult:
    try:
        _plan_sha, bundle = _current_hashes(manifest)
        expected = manifest.get("verification_contract", {}).get("expected_gates", [])
        gates = manifest.get("gates")
        if not isinstance(gates, list) or [item.get("gate") for item in gates if isinstance(item, dict)] != list(expected):
            raise ManifestContractError("gates do not exactly match contract expected_gates")
        for gate in gates:
            if gate.get("decision") not in {"approved", "not_triggered"} or gate.get("subject_sha256") != bundle:
                raise ManifestContractError("gate is stale or malformed")
            path = resolve_vault_file(gate.get("evidence_ref"), field_name="gate evidence")
            if hash_file(path) != gate.get("evidence_sha256"):
                raise ManifestContractError("gate evidence hash mismatch")
    except (ManifestContractError, TypeError) as exc:
        return CheckResult("artifact_and_gate_bindings", False, TIER_OPERATOR, str(exc))
    return CheckResult("artifact_and_gate_bindings", True)


def check_action_log_complete(manifest: dict[str, Any]) -> CheckResult:
    actions = manifest.get("actions")
    try:
        if not isinstance(actions, list) or not actions:
            raise ManifestContractError("actions must be nonempty")
        identifiers = [item.get("id") for item in actions if isinstance(item, dict)]
        if len(identifiers) != len(actions) or len(set(identifiers)) != len(identifiers):
            raise ManifestContractError("action IDs must be unique")
        phase_ids = [aid for phase in manifest.get("phase_records", []) for aid in phase.get("action_ids", [])]
        if sorted(phase_ids) != sorted(identifiers) or len(phase_ids) != len(identifiers):
            raise ManifestContractError("phase action_ids do not exactly cover actions")
        if hash_canonical(actions) != manifest.get("action_log_sha256"):
            raise ManifestContractError("action_log_sha256 mismatch")
        for item in actions:
            if item.get("destructive") is not False:
                raise ManifestContractError("destructive action is not authorized in v1 close")
            if manifest.get("mode") == "bounty" and (
                not isinstance(item.get("target"), str) or not item["target"]
            ):
                raise ManifestContractError("every Bounty action must declare its target")
            resolve_vault_file(item.get("evidence_ref"), field_name="action evidence")
    except (ManifestContractError, TypeError) as exc:
        return CheckResult("action_log_complete", False, TIER_OPERATOR, str(exc))
    return CheckResult("action_log_complete", True)


def check_iteration_invalidation(manifest: dict[str, Any]) -> CheckResult:
    iterations = manifest.get("iterations")
    if iterations == []:
        return CheckResult("iteration_invalidation", True)
    try:
        if not isinstance(iterations, list):
            raise ManifestContractError("iterations must be a list")
        for index, item in enumerate(iterations, 1):
            if not isinstance(item, dict) or item.get("index") != index or item.get("route_to") not in {"S2", "S3"}:
                raise ManifestContractError("iteration chain is noncontiguous or has invalid route")
        last = iterations[-1]
        if last.get("to_plan_sha256") != manifest.get("plan", {}).get("sha256") or last.get("to_artifact_bundle_sha256") != manifest.get("artifact_bundle_sha256"):
            raise ManifestContractError("iteration chain does not end at current hashes")
    except (ManifestContractError, TypeError) as exc:
        return CheckResult("iteration_invalidation", False, TIER_OPERATOR, str(exc))
    return CheckResult("iteration_invalidation", True)


def check_external_delivery_blocked(manifest: dict[str, Any]) -> CheckResult:
    delivery = manifest.get("delivery")
    if not isinstance(delivery, dict) or delivery.get("external") is not False or delivery.get("action") not in {"local_package", "local_report", "none"}:
        return CheckResult("external_delivery_blocked", False, TIER_OPERATOR, "external delivery is forbidden in v1")
    if manifest.get("mode") == "bounty" and manifest.get("submission", {}).get("attempted") is not False:
        return CheckResult("external_delivery_blocked", False, TIER_OPERATOR, "Bounty submission must be literal false")
    return CheckResult("external_delivery_blocked", True)


@dataclass(frozen=True)
class NormalizedTarget:
    origin: str
    path: str


def normalize_bounty_target(value: object) -> NormalizedTarget:
    if not isinstance(value, str) or not value:
        raise ManifestContractError("Bounty target must be a nonempty URL")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ManifestContractError("Bounty target must be an absolute https URL without userinfo")
    if parsed.fragment or parsed.query or "*" in value or parsed.port not in (None, 443):
        raise ManifestContractError("Bounty target wildcards, fragments, queries, and nondefault ports are forbidden")
    decoded = unquote(parsed.path or "/")
    segments: list[str] = []
    for segment in decoded.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise ManifestContractError("Bounty target contains traversal")
        segments.append(segment)
    path = "/" + "/".join(segments)
    if (parsed.path or "/").endswith("/") and path != "/":
        path += "/"
    return NormalizedTarget(f"https://{parsed.hostname.lower()}", path)


def _target_allowed(target: object, allowed: list[NormalizedTarget]) -> bool:
    normalized = normalize_bounty_target(target)
    for candidate in allowed:
        prefix = candidate.path.rstrip("/")
        if normalized.origin == candidate.origin and (
            normalized.path.rstrip("/") == prefix or normalized.path.startswith(prefix + "/")
        ):
            return True
    return False


def check_bounty_scope_and_targets(manifest: dict[str, Any]) -> CheckResult:
    try:
        scope = manifest.get("scope")
        if not isinstance(scope, dict) or scope.get("scope_gate_ran") is not True:
            raise ManifestContractError("scope_gate_ran must be literal true")
        raw_allowed = scope.get("allowed_targets")
        if not isinstance(raw_allowed, list) or not raw_allowed:
            raise ManifestContractError("allowed_targets must be nonempty")
        allowed = [normalize_bounty_target(item) for item in raw_allowed]
        evidence = resolve_vault_file(scope.get("evidence_ref"), field_name="scope.evidence_ref")
        if hash_file(evidence) != scope.get("evidence_sha256"):
            raise ManifestContractError("scope evidence hash mismatch")
        targets: list[str] = []
        collections = (
            ("actions", manifest.get("actions", [])),
            ("findings", manifest.get("findings", [])),
            ("negative_results", manifest.get("negative_results", [])),
        )
        for collection_name, collection in collections:
            if not isinstance(collection, list):
                raise ManifestContractError("Bounty target collection must be a list")
            for index, item in enumerate(collection):
                target = item.get("target") if isinstance(item, dict) else None
                if not isinstance(target, str) or not target:
                    raise ManifestContractError(
                        f"{collection_name}[{index}].target must be a nonempty string"
                    )
                targets.append(target)
        for target in targets:
            if not _target_allowed(target, allowed):
                raise ManifestContractError(f"out-of-scope Bounty target: {target}")
    except (ManifestContractError, ValueError) as exc:
        return CheckResult("bounty_scope_and_targets", False, TIER_OPERATOR, str(exc))
    return CheckResult("bounty_scope_and_targets", True)


def check_bounty_no_self_inflicted(manifest: dict[str, Any]) -> CheckResult:
    record = manifest.get("no_self_inflicted")
    try:
        if not isinstance(record, dict) or record.get("passed") is not True:
            raise ManifestContractError("no_self_inflicted.passed must be literal true")
        if record.get("subject_sha256") != manifest.get("action_log_sha256"):
            raise ManifestContractError("no_self_inflicted is stale")
        path = resolve_vault_file(record.get("evidence_ref"), field_name="no_self_inflicted.evidence_ref")
        if hash_file(path) != record.get("evidence_sha256"):
            raise ManifestContractError("no_self_inflicted evidence hash mismatch")
    except ManifestContractError as exc:
        return CheckResult("bounty_no_self_inflicted", False, TIER_OPERATOR, str(exc))
    return CheckResult("bounty_no_self_inflicted", True)


def _pinned_author_family(manifest: dict[str, Any]) -> str:
    """Return the dispatcher-pinned authoring family for this run.

    `check_verification_contract` binds this field to the registry contract and
    the registry contract to the dispatched lane, so it is the one authorship
    claim a worker cannot write for itself. Anti-affinity must be measured
    against it rather than against a finding's own account of who wrote it.
    """
    declared = manifest.get("author_family")
    if declared not in KNOWN_AUTHOR_FAMILIES:
        raise ManifestContractError("manifest author_family is invalid")
    contract = manifest.get("verification_contract")
    pinned = contract.get("author_family") if isinstance(contract, dict) else None
    if pinned is not None and declared != pinned:
        raise ManifestContractError("manifest author_family differs from dispatcher pin")
    return declared


def check_bounty_result_evidence(manifest: dict[str, Any]) -> CheckResult:
    try:
        result_type = manifest.get("result_type")
        findings = manifest.get("findings")
        if not isinstance(findings, list):
            raise ManifestContractError("findings must be a list")
        if result_type == "dry_run":
            if findings:
                raise ManifestContractError("dry_run findings must be empty")
            negatives = manifest.get("negative_results")
            if not isinstance(negatives, list) or not negatives:
                raise ManifestContractError("dry_run requires KILL/negative evidence")
            for item in negatives:
                if item.get("outcome") not in {"killed", "negative"} or item.get("subject_sha256") != manifest.get("action_log_sha256"):
                    raise ManifestContractError("negative result is malformed or stale")
                path = resolve_vault_file(item.get("evidence_ref"), field_name="negative evidence")
                if hash_file(path) != item.get("evidence_sha256"):
                    raise ManifestContractError("negative evidence hash mismatch")
        else:
            if not findings:
                raise ManifestContractError("normal Bounty requires findings")
            # Both anchors are dispatcher-pinned. A finding that supplies its own
            # author_family/author_run_id can otherwise nominate its own family,
            # inside its own run, as the "independent" reproducer and stay green.
            pinned_family = _pinned_author_family(manifest)
            pinned_run_id = validate_run_id(manifest.get("run_id"))
            for finding in findings:
                required = ("id", "title", "target", "cvss_v4", "cvss_v4_score", "artifact_sha256", "author_family", "author_run_id", "reproduction")
                if any(key not in finding for key in required):
                    raise ManifestContractError("normal finding is structurally incomplete")
                author_family = finding["author_family"]
                author_run_id = finding["author_run_id"]
                if author_family not in KNOWN_AUTHOR_FAMILIES:
                    raise ManifestContractError("finding author_family is invalid")
                if author_family != pinned_family:
                    raise ManifestContractError("finding author_family differs from dispatcher pin")
                validate_run_id(author_run_id)
                reproduction = finding["reproduction"]
                if not isinstance(reproduction, dict):
                    raise ManifestContractError("reproduction must be an object")
                reproducer_family = reproduction.get("reproducer_family")
                reproduction_run_id = reproduction.get("reproduction_run_id")
                if (
                    reproducer_family not in KNOWN_AUTHOR_FAMILIES
                    or reproducer_family == author_family
                ):
                    raise ManifestContractError("reproduction violates family/run anti-affinity")
                validate_run_id(reproduction_run_id)
                if reproduction_run_id in (author_run_id, pinned_run_id):
                    raise ManifestContractError("reproduction violates family/run anti-affinity")
                if reproduction.get("status") != "reproduced" or reproduction.get("control_status") != "passed":
                    return CheckResult("bounty_result_evidence", False, TIER_RETRY, "reproduction/control work did not pass")
                if reproduction.get("subject_sha256") != finding.get("artifact_sha256"):
                    raise ManifestContractError("reproduction subject is stale")
                path = resolve_vault_file(reproduction.get("evidence_ref"), field_name="reproduction evidence")
                if hash_file(path) != reproduction.get("evidence_sha256"):
                    raise ManifestContractError("reproduction evidence hash mismatch")
            cvss = check_bounty_cvss(manifest)
            if not cvss.passed:
                return CheckResult("bounty_result_evidence", False, cvss.tier, cvss.detail)
    except (ManifestContractError, TypeError) as exc:
        return CheckResult("bounty_result_evidence", False, TIER_OPERATOR, str(exc))
    return CheckResult("bounty_result_evidence", True)


def check_bounty_no_submit(manifest: dict[str, Any]) -> CheckResult:
    submission = manifest.get("submission")
    try:
        if not isinstance(submission, dict) or submission.get("attempted") is not False:
            raise ManifestContractError("submission.attempted must be literal false")
        path = resolve_vault_file(submission.get("evidence_ref"), field_name="submission.evidence_ref")
        if hash_file(path) != submission.get("evidence_sha256"):
            raise ManifestContractError("no-submit evidence hash mismatch")
    except ManifestContractError as exc:
        return CheckResult("bounty_no_submit", False, TIER_OPERATOR, str(exc))
    return CheckResult("bounty_no_submit", True)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(content)
    try:
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    tmp.rename(path)


def load_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = _run_state_path(run_id, "manifest.yaml", must_exist=False)
    if not manifest_path.exists():
        raise ManifestContractError(f"manifest not found: {manifest_path}")
    manifest_path = _run_state_path(run_id, "manifest.yaml", must_exist=True)
    raw_manifest = manifest_path.read_text(encoding="utf-8")
    try:
        # JSON is a YAML 1.2 subset and is the canonical producer format. It
        # keeps the settlement verifier fully offline and avoids asking uv to
        # resolve this repository's unrelated application dependency graph.
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise ManifestContractError(
                "manifest must be JSON-compatible YAML when PyYAML is unavailable"
            ) from exc
        manifest = yaml.safe_load(raw_manifest) or {}
    if not isinstance(manifest, dict):
        raise ManifestContractError("manifest must be an object")
    return manifest


def _normalize_deleted_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ManifestContractError("deleted_paths entries must be nonempty repo-relative paths")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ManifestContractError("deleted_paths entries must be normalized repo-relative paths")
    return value


def _load_approval_record(run_id: object) -> ApprovalRecord:
    validated = validate_run_id(run_id)
    path = _approval_path(validated, must_exist=True)
    text = path.read_text(encoding="utf-8")

    # Compatibility is intentionally narrow: the historical exact one-line
    # approval remains valid, but prose merely containing the word does not.
    if text.strip() == "APPROVE":
        return ApprovalRecord(
            run_id=validated,
            decision="approve",
            legacy_exact_approve=True,
        )

    try:
        raw = read_yaml_frontmatter(path)
    except ContractError as exc:
        raise ManifestContractError("approval must be a typed YAML-frontmatter record") from exc
    allowed_fields = {
        "schema_version",
        "run_id",
        "decision",
        "override_reason",
        "deletion_approved",
        "deleted_paths",
        "deletion_reason",
    }
    unknown = set(raw) - allowed_fields
    if unknown:
        raise ManifestContractError(f"approval has unknown fields: {sorted(unknown)}")
    if raw.get("schema_version") != APPROVAL_SCHEMA:
        raise ManifestContractError(f"approval schema_version must be {APPROVAL_SCHEMA}")
    if raw.get("run_id") != validated:
        raise ManifestContractError("approval run_id does not match the requested run")
    decision = raw.get("decision")
    if decision not in {"approve", "override"}:
        raise ManifestContractError("approval decision must be approve or override")

    override_reason = raw.get("override_reason")
    if decision == "override":
        if not isinstance(override_reason, str) or not override_reason.strip():
            raise ManifestContractError("override approval requires override_reason")
    elif override_reason is not None:
        raise ManifestContractError("approve decision must not include override_reason")

    deletion_approved = raw.get("deletion_approved", False)
    if not isinstance(deletion_approved, bool):
        raise ManifestContractError("deletion_approved must be a boolean")
    deleted_paths_raw = raw.get("deleted_paths", [])
    if not isinstance(deleted_paths_raw, list):
        raise ManifestContractError("deleted_paths must be an inline JSON list")
    deleted_paths = tuple(_normalize_deleted_path(item) for item in deleted_paths_raw)
    if len(set(deleted_paths)) != len(deleted_paths):
        raise ManifestContractError("deleted_paths contains duplicates")
    deletion_reason = raw.get("deletion_reason")
    if deletion_approved:
        if not deleted_paths:
            raise ManifestContractError("deletion approval requires deleted_paths")
        if not isinstance(deletion_reason, str) or not deletion_reason.strip():
            raise ManifestContractError("deletion approval requires deletion_reason")
    elif deleted_paths or deletion_reason is not None:
        raise ManifestContractError(
            "deleted_paths/deletion_reason require deletion_approved: true"
        )

    return ApprovalRecord(
        run_id=validated,
        decision=decision,
        override_reason=override_reason if isinstance(override_reason, str) else None,
        deletion_approved=deletion_approved,
        deleted_paths=deleted_paths,
        deletion_reason=deletion_reason if isinstance(deletion_reason, str) else None,
    )


# ─── Universal checks ───────────────────────────────────────────────

def check_operator_approval(manifest: dict[str, Any]) -> CheckResult:
    try:
        run_id = validate_run_id(manifest["run_id"])
        approval_path = _approval_path(run_id, must_exist=False)
    except (KeyError, ManifestContractError) as exc:
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail=f"invalid approval path: {exc}",
        )
    if not approval_path.exists():
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail=f"no approval file at {approval_path.relative_to(VAULT_ROOT)}",
        )
    try:
        approval = _load_approval_record(run_id)
    except (ContractError, ManifestContractError, OSError) as exc:
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail=f"approval record rejected: {exc}",
        )
    if approval.decision == "override":
        return CheckResult(
            name="operator_approval", passed=True,
            detail="typed override approval present (non-default; audit trail retained)",
        )
    detail = "legacy exact APPROVE record" if approval.legacy_exact_approve else "typed approval record"
    return CheckResult(name="operator_approval", passed=True, detail=detail)


# Compatibility for the direct security-test reader. The standalone presence
# check was redundant; this stronger check also verifies artifact hashes and gates.
check_artifacts_exist = check_artifact_and_gate_bindings


def check_citations_resolve(manifest: dict[str, Any]) -> CheckResult:
    cites = manifest.get("citations") or []
    if not cites:
        return CheckResult(name="citations_resolve", passed=True,
                           detail="no citations declared")
    bad: list[str] = []
    network_bad: list[str] = []
    for cite in cites:
        if not isinstance(cite, str):
            bad.append(f"{cite!r} → citation must be a string")
            continue
        try:
            cite_scheme = urlsplit(cite).scheme.lower()
        except ValueError as exc:
            bad.append(f"{cite} → malformed URL: {exc}")
            continue
        if cite_scheme in {"http", "https"}:
            try:
                status = _probe_http(cite)
                if status >= 400:
                    network_bad.append(f"{cite} → {status}")
            except CitationPolicyError as exc:
                bad.append(f"{cite} → denied: {exc}")
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, CitationPolicyError):
                    bad.append(f"{cite} → denied: {exc.reason}")
                else:
                    network_bad.append(f"{cite} → {type(exc).__name__}")
            except OSError as e:
                network_bad.append(f"{cite} → {type(e).__name__}")
        elif cite.startswith("git:"):
            ref = cite[4:]
            try:
                subprocess.check_output(
                    [
                        "git",
                        "rev-parse",
                        "--verify",
                        "--end-of-options",
                        f"{ref}^{{object}}",
                    ],
                    stderr=subprocess.DEVNULL,
                    cwd=str(VAULT_ROOT),
                )
            except (subprocess.CalledProcessError, ValueError):
                bad.append(f"{cite} → not a git ref")
        else:
            try:
                path = resolve_vault_candidate(cite, field_name="citation path")
            except ManifestContractError as exc:
                bad.append(f"{cite} → denied: {exc}")
                continue
            if not path.exists():
                bad.append(f"{cite} → file not found")
                continue
            try:
                resolve_vault_file(cite, field_name="citation path")
            except ManifestContractError as exc:
                bad.append(f"{cite} → denied: {exc}")
    if bad:
        # Citation 404 is genuinely ambiguous — could be a real finding with a
        # transient outage. Tier-3 (operator surface) per spec.
        return CheckResult(
            name="citations_resolve", passed=False, tier=TIER_OPERATOR,
            detail=f"{len(bad)} unresolved: " + "; ".join(bad[:3]),
        )
    if network_bad:
        return CheckResult(
            name="citations_resolve", passed=True, tier=TIER_OK, advisory=True,
            detail=f"link liveness advisory: {len(network_bad)} unresolved: " + "; ".join(network_bad[:3]),
        )
    return CheckResult(name="citations_resolve", passed=True,
                       detail=f"{len(cites)} citations all resolve")


@dataclass(frozen=True)
class _ValidatedCitationTarget:
    scheme: str
    hostname: str
    port: int
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address

    @property
    def host_header(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        default_port = 443 if self.scheme == "https" else 80
        return host if self.port == default_port else f"{host}:{self.port}"


def _validate_citation_url(
    url: object, *, expected_scheme: str | None = None
) -> _ValidatedCitationTarget:
    if not isinstance(url, str) or not url or any(ord(ch) < 0x20 for ch in url):
        raise CitationPolicyError("URL must be a nonempty string without control characters")
    if "\\" in url:
        raise CitationPolicyError("backslashes are forbidden in citation URLs")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise CitationPolicyError("citation URL is malformed") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise CitationPolicyError("only absolute http/https citation URLs are allowed")
    if expected_scheme is not None and scheme != expected_scheme:
        raise CitationPolicyError("cross-scheme redirects are forbidden")
    if parsed.username is not None or parsed.password is not None:
        raise CitationPolicyError("citation URL userinfo is forbidden")
    if parsed.fragment:
        raise CitationPolicyError("citation URL fragments are forbidden")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise CitationPolicyError("citation URL has an invalid port") from exc

    host = parsed.hostname.rstrip(".")
    if not host or host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise CitationPolicyError("localhost destinations are forbidden")
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for answer in answers:
        raw_address = answer[4][0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise CitationPolicyError(
                f"DNS returned an invalid address for {host}"
            ) from exc
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise OSError(f"DNS returned no addresses for {host}")
    denied = sorted(
        str(address)
        for address in addresses
        if address in METADATA_IPS or not address.is_global
    )
    if denied:
        raise CitationPolicyError(
            f"destination resolves to non-public address(es): {', '.join(denied)}"
        )
    return _ValidatedCitationTarget(
        scheme=scheme,
        hostname=host,
        port=port,
        ip=addresses[0],
    )


def _open_pinned_socket(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    port: int,
    timeout: Any,
    source_address: tuple[str, int] | None,
) -> socket.socket:
    family = socket.AF_INET6 if isinstance(address, ipaddress.IPv6Address) else socket.AF_INET
    destination: tuple[object, ...]
    if family == socket.AF_INET6:
        destination = (str(address), port, 0, 0)
    else:
        destination = (str(address), port)
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        if source_address is not None:
            sock.bind(source_address)
        sock.connect(destination)
    except Exception:
        sock.close()
        raise
    return sock


class _PinnedConnectionMixin:
    _pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address

    def _create_pinned_connection(
        self,
        address: tuple[str, int],
        timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        return _open_pinned_socket(
            self._pinned_ip,
            address[1],
            timeout,
            source_address,
        )


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
        timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
    ) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(
            host,
            port,
            timeout=timeout,
            source_address=source_address,
            blocksize=blocksize,
        )
        self._create_connection = self._create_pinned_connection


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
        timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        context: Any = None,
        blocksize: int = 8192,
    ) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(
            host,
            port,
            timeout=timeout,
            source_address=source_address,
            context=context,
            blocksize=blocksize,
        )
        self._create_connection = self._create_pinned_connection


def _pin_citation_request(
    request: urllib.request.Request,
    target: _ValidatedCitationTarget,
) -> urllib.request.Request:
    request._vibecoding_citation_target = target
    request.add_unredirected_header("Host", target.host_header)
    return request


def _request_citation_target(
    request: urllib.request.Request,
    *,
    expected_scheme: str,
) -> _ValidatedCitationTarget:
    target = getattr(request, "_vibecoding_citation_target", None)
    if not isinstance(target, _ValidatedCitationTarget):
        raise CitationPolicyError("citation request is missing a validated address pin")
    try:
        parsed = urlsplit(request.full_url)
        port = parsed.port or (443 if expected_scheme == "https" else 80)
    except ValueError as exc:
        raise CitationPolicyError("citation request URL is malformed") from exc
    hostname = parsed.hostname.rstrip(".") if parsed.hostname else ""
    if (
        parsed.scheme.lower() != expected_scheme
        or target.scheme != expected_scheme
        or hostname != target.hostname
        or port != target.port
    ):
        raise CitationPolicyError("citation request does not match its validated address pin")
    return target


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request: urllib.request.Request) -> Any:
        target = _request_citation_target(request, expected_scheme="http")

        def connection_factory(host: str, **kwargs: Any) -> _PinnedHTTPConnection:
            return _PinnedHTTPConnection(host, pinned_ip=target.ip, **kwargs)

        return self.do_open(connection_factory, request)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request: urllib.request.Request) -> Any:
        target = _request_citation_target(request, expected_scheme="https")

        def connection_factory(host: str, **kwargs: Any) -> _PinnedHTTPSConnection:
            return _PinnedHTTPSConnection(host, pinned_ip=target.ip, **kwargs)

        return self.do_open(
            connection_factory,
            request,
            context=self._context,
        )


class _SafeCitationRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        source_scheme = urlsplit(req.full_url).scheme.lower()
        normalized_url = newurl.replace(" ", "%20")
        target = _validate_citation_url(
            normalized_url,
            expected_scheme=source_scheme,
        )
        redirected = super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            normalized_url,
        )
        if redirected is None:
            return None
        return _pin_citation_request(redirected, target)


def _probe_http(url: str) -> int:
    headers = {"User-Agent": "Mozilla/5.0 (vibecoding-check)"}
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SafeCitationRedirectHandler(),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(),
    )
    status = 599
    for method in ("HEAD", "GET"):
        target = _validate_citation_url(url)
        request = _pin_citation_request(
            urllib.request.Request(url, headers=headers, method=method),
            target,
        )
        try:
            with opener.open(request, timeout=15) as response:
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
        if status < 400:
            break
    return status


TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b")
DOC_TODO_ALLOWLIST = re.compile(r"#\s*TODO\(:?\s*future\b", re.IGNORECASE)


def check_no_todo_in_modified(manifest: dict[str, Any]) -> CheckResult:
    modified = manifest.get("modified_code") or []
    if not modified:
        return CheckResult(name="no_todo_in_modified", passed=True,
                           detail="no code files declared modified")
    hits: list[str] = []
    invalid: list[str] = []
    for index, rel in enumerate(modified):
        try:
            path = resolve_vault_candidate(
                rel, field_name=f"modified_code[{index}]"
            )
        except ManifestContractError as exc:
            invalid.append(str(exc))
            continue
        if not path.exists():
            continue
        try:
            path = resolve_vault_file(rel, field_name=f"modified_code[{index}]")
        except ManifestContractError as exc:
            invalid.append(str(exc))
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if TODO_RE.search(line) and not DOC_TODO_ALLOWLIST.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
    if invalid:
        return CheckResult(
            name="no_todo_in_modified", passed=False, tier=TIER_OPERATOR,
            detail=f"{len(invalid)} unsafe modified-code path(s): {invalid[0]}",
        )
    if hits:
        return CheckResult(
            name="no_todo_in_modified", passed=False, tier=TIER_RETRY,
            detail=f"{len(hits)} TODO/FIXME/XXX markers: {hits[0]}{' ...' if len(hits) > 1 else ''}",
        )
    return CheckResult(name="no_todo_in_modified", passed=True,
                       detail=f"{len(modified)} files clean")


def check_phase_tags(manifest: dict[str, Any]) -> CheckResult:
    if manifest.get("schema_version") == "verification-run/v1":
        records = manifest.get("phase_records")
        if not isinstance(records, list):
            return CheckResult("phase_tags", False, TIER_OPERATOR, "phase_records must be a list")
        identifiers = [item.get("phase_id") for item in records if isinstance(item, dict)]
        if identifiers != list(REQUIRED_PHASE_IDS) or len(records) != len(REQUIRED_PHASE_IDS):
            return CheckResult("phase_tags", False, TIER_OPERATOR, "phase_records must contain ordered S0..S7 exactly once")
        try:
            for index, record in enumerate(records):
                if record.get("status") not in {"passed", "killed", "not_applicable"}:
                    raise ManifestContractError(f"phase_records[{index}].status is invalid")
                refs = record.get("evidence_refs")
                if not isinstance(refs, list) or not refs:
                    raise ManifestContractError(f"phase_records[{index}] has no evidence")
                for ref in refs:
                    resolve_vault_file(ref, field_name=f"phase_records[{index}].evidence_refs")
                if not isinstance(record.get("action_ids"), list) or not record["action_ids"]:
                    raise ManifestContractError(f"phase_records[{index}] has no action_ids")
                if record["status"] == "passed" and "disposition_reason" in record:
                    raise ManifestContractError(f"phase_records[{index}] passed with disposition_reason")
                if record["status"] != "passed" and not record.get("disposition_reason"):
                    raise ManifestContractError(f"phase_records[{index}] requires disposition_reason")
        except ManifestContractError as exc:
            return CheckResult("phase_tags", False, TIER_OPERATOR, str(exc))
        return CheckResult("phase_tags", True, detail="ordered S0..S7 evidence records present")
    declared = manifest.get("phase_tags") or []
    if not declared:
        return CheckResult(name="phase_tags", passed=True,
                           detail="no phase_tags declared (single-phase mode)")
    try:
        log_path = _run_state_path(
            manifest["run_id"], "phase-log.txt", must_exist=False
        )
    except (KeyError, ManifestContractError) as exc:
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_OPERATOR,
            detail=f"invalid phase-log path: {exc}",
        )
    if not log_path.exists():
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_RETRY,
            detail=f"no phase-log at {log_path.relative_to(VAULT_ROOT)}",
        )
    try:
        log_path = _run_state_path(
            manifest["run_id"], "phase-log.txt", must_exist=True
        )
    except ManifestContractError as exc:
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_OPERATOR,
            detail=f"unsafe phase-log path: {exc}",
        )
    emitted = [line.strip() for line in log_path.read_text().splitlines() if line.strip()]
    missing = [t for t in declared if t not in emitted]
    if missing:
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_RETRY,
            detail=f"missing phase-tags: {', '.join(missing)}",
        )
    return CheckResult(name="phase_tags", passed=True,
                       detail=f"all {len(declared)} phase-tags emitted")


# ─── Mode-specific checks ──────────────────────────────────────────

def _resolve_test_cwd(value: object) -> Path:
    if value is None:
        candidate = VAULT_ROOT
    elif isinstance(value, str) and value:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else VAULT_ROOT / raw
    else:
        raise ManifestContractError("test_cwd must be a nonempty path string")
    return _resolve_contained_candidate(
        candidate,
        allowed_root=VAULT_ROOT,
        field_name="test_cwd",
        must_exist=True,
        kind="dir",
        reject_final_symlink=False,
    )


def _resolve_command_executable(value: str, cwd: Path) -> Path:
    raw = Path(value)
    if raw.is_absolute() or "/" in value:
        candidate = raw if raw.is_absolute() else cwd / raw
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ManifestContractError(f"test executable does not exist: {value}") from exc
    else:
        found = shutil.which(value)
        if not found:
            raise ManifestContractError(f"test executable is unavailable: {value}")
        resolved = Path(found).resolve(strict=True)
    if not resolved.is_file():
        raise ManifestContractError("test executable must be a regular file")
    return resolved


def _validate_relative_test_selector(value: str, cwd: Path) -> None:
    selector = value.split("::", 1)[0]
    if not selector:
        raise ManifestContractError("test selector must not be empty")
    path = Path(selector)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestContractError("test selectors must not escape test_cwd")
    resolved = (cwd / path).resolve(strict=False)
    if not resolved.is_relative_to(cwd):
        raise ManifestContractError("test selector escapes test_cwd")


def _validate_pytest_args(args: list[str], cwd: Path) -> None:
    exact_flags = {
        "-q",
        "-v",
        "-vv",
        "-x",
        "--exitfirst",
        "--disable-warnings",
        "--strict-config",
        "--strict-markers",
        "--collect-only",
    }
    value_flags = {"-k", "-m"}
    expect_value = False
    for arg in args:
        if expect_value:
            if not arg:
                raise ManifestContractError("pytest option value must not be empty")
            expect_value = False
        elif arg in value_flags:
            expect_value = True
        elif arg in exact_flags or re.fullmatch(r"--maxfail=[0-9]+", arg):
            continue
        elif arg.startswith("-"):
            raise ManifestContractError(f"pytest option is not allowlisted: {arg}")
        else:
            _validate_relative_test_selector(arg, cwd)
    if expect_value:
        raise ManifestContractError("pytest option is missing its value")


def _validate_unittest_args(args: list[str], cwd: Path) -> None:
    flags = {"-q", "-v", "-f", "-b", "-c", "discover"}
    path_value_flags = {"-s", "--start-directory", "-t", "--top-level-directory"}
    scalar_value_flags = {"-p", "--pattern", "-k"}
    expect_path = False
    expect_scalar = False
    for arg in args:
        if expect_path:
            _validate_relative_test_selector(arg, cwd)
            expect_path = False
        elif expect_scalar:
            if not arg:
                raise ManifestContractError("unittest option value must not be empty")
            expect_scalar = False
        elif arg in path_value_flags:
            expect_path = True
        elif arg in scalar_value_flags:
            expect_scalar = True
        elif arg in flags:
            continue
        elif arg.startswith("-"):
            raise ManifestContractError(f"unittest option is not allowlisted: {arg}")
        else:
            _validate_relative_test_selector(arg, cwd)
    if expect_path or expect_scalar:
        raise ManifestContractError("unittest option is missing its value")


def _normalize_test_command(value: object, cwd: Path) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ManifestContractError("test_command must be a nonempty argv array")
    if len(value) > 64:
        raise ManifestContractError("test_command has too many arguments")
    argv: list[str] = []
    for index, arg in enumerate(value):
        if (
            not isinstance(arg, str)
            or not arg
            or len(arg) > 4096
            or any(ord(ch) < 0x20 for ch in arg)
            or SHELL_METACHAR_RE.search(arg)
        ):
            raise ManifestContractError(
                f"test_command[{index}] contains an invalid value or shell metacharacter"
            )
        argv.append(arg)

    executable = _resolve_command_executable(argv[0], cwd)
    current_python = Path(sys.executable).resolve(strict=True)
    repo_test = (VAULT_ROOT / "bin/test").resolve(strict=False)
    pytest_path_raw = shutil.which("pytest")
    pytest_path = (
        Path(pytest_path_raw).resolve(strict=True) if pytest_path_raw else None
    )

    if executable == current_python:
        if len(argv) < 3 or argv[1] != "-m" or argv[2] not in {"pytest", "unittest"}:
            raise ManifestContractError(
                "Python test commands must use -m pytest or -m unittest"
            )
        runner = argv[2]
        runner_args = argv[3:]
    elif pytest_path is not None and executable == pytest_path:
        runner = "pytest"
        runner_args = argv[1:]
    elif executable == repo_test:
        if cwd != _vault_realpath() or argv[1:] not in ([], ["--fast"]):
            raise ManifestContractError(
                "bin/test is allowed only at VAULT_ROOT with no argument or --fast"
            )
        runner = "bin/test"
        runner_args = []
    else:
        raise ManifestContractError(
            "test executable is not allowlisted (bin/test, pytest, or current Python)"
        )

    if runner == "pytest":
        _validate_pytest_args(runner_args, cwd)
    elif runner == "unittest":
        _validate_unittest_args(runner_args, cwd)
    return [str(executable), *argv[1:]]


def _minimal_test_environment(argv: list[str], cwd: Path) -> dict[str, str]:
    path_dirs = [str(Path(argv[0]).parent)]
    for executable_name in ("python3", "git"):
        resolved = shutil.which(executable_name)
        if resolved:
            path_dirs.append(str(Path(resolved).resolve().parent))
    path_dirs.extend(("/usr/bin", "/bin"))
    minimal_path = os.pathsep.join(dict.fromkeys(path_dirs))
    return {
        "PATH": minimal_path,
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def check_project_tests_pass(manifest: dict[str, Any]) -> CheckResult:
    raw_command = manifest.get("test_command")
    if raw_command is None:
        raw_command = [sys.executable, "-m", "pytest", "-x"]
    try:
        cwd = _resolve_test_cwd(manifest.get("test_cwd"))
        cmd = _normalize_test_command(raw_command, cwd)
        env = _minimal_test_environment(cmd, cwd)
    except ManifestContractError as exc:
        return CheckResult(
            name="tests_pass", passed=False, tier=TIER_OPERATOR,
            detail=f"test command rejected: {exc}",
        )
    display = shlex.join(cmd)
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name="tests_pass", passed=False, tier=TIER_RETRY,
                           detail="test command timed out")
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return CheckResult(
            name="tests_pass", passed=False, tier=TIER_RETRY,
            detail=f"test command failed to start: {exc}",
        )
    if result.returncode != 0:
        tail = (result.stdout + "\n" + result.stderr)[-300:].strip()
        return CheckResult(
            name="tests_pass", passed=False, tier=TIER_RETRY,
            detail=f"`{display}` exit {result.returncode}: {tail}",
        )
    return CheckResult(name="tests_pass", passed=True,
                       detail=f"`{display}` exit 0")


def check_project_git_clean(manifest: dict[str, Any]) -> CheckResult:
    """Verify working tree is clean OR only whitespace-trivial changes pending.

    For project mode, declaring 'done' with uncommitted changes likely means
    'incomplete'. Allow operator to override via manifest['allow_dirty_tree']: true.
    """
    if manifest.get("allow_dirty_tree"):
        return CheckResult(name="git_clean", passed=True,
                           detail="dirty tree allowed by manifest override")

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(VAULT_ROOT), timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(name="git_clean", passed=False, tier=TIER_RETRY,
                           detail=f"git status failed: {e}")

    if result.returncode != 0:
        return CheckResult(name="git_clean", passed=False, tier=TIER_RETRY,
                           detail=f"git exit {result.returncode}: {result.stderr.strip()[:200]}")

    dirty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    # Filter out runtime-state files that are gitignored or expected-dirty.
    runtime_paths = ("_state/", "departments/", "chrono/current.md", ".gemini/")
    blocking = [
        line for line in dirty_lines if not any(path in line for path in runtime_paths)
    ]

    if blocking:
        return CheckResult(name="git_clean", passed=False, tier=TIER_RETRY,
                           detail=f"{len(blocking)} uncommitted non-runtime changes: {blocking[0][:120]}")
    return CheckResult(name="git_clean", passed=True,
                       detail=f"{len(dirty_lines)} runtime-only changes (allowed)")


def check_project_new_code_has_tests(manifest: dict[str, Any]) -> CheckResult:
    """Verify new code (.py/.ts/.js/.go/.rs files added in this run's diff) has corresponding test changes.

    Heuristic: if N new source files added since the run's base ref, expect at
    least N/2 test files added/modified. Manifest must include `base_ref`
    (defaults to v1.0-pre-1.1).
    """
    base_ref = manifest.get("base_ref", "v1.0-pre-1.1")
    if (
        not isinstance(base_ref, str)
        or not base_ref
        or len(base_ref) > 256
        or any(ord(ch) < 0x20 for ch in base_ref)
    ):
        return CheckResult(
            name="new_code_has_tests", passed=False, tier=TIER_OPERATOR,
            detail="base_ref must be a nonempty bounded string without control characters",
        )
    try:
        resolved_ref = subprocess.run(
            [
                "git",
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{base_ref}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            cwd=str(VAULT_ROOT),
            timeout=10,
        )
        commit = resolved_ref.stdout.strip()
        if resolved_ref.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            return CheckResult(
                name="new_code_has_tests", passed=False, tier=TIER_RETRY,
                detail="base_ref does not resolve to one commit",
            )
        result = subprocess.run(
            ["git", "diff", "--name-status", f"{commit}..HEAD", "--"],
            capture_output=True, text=True, cwd=str(VAULT_ROOT), timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CheckResult(name="new_code_has_tests", passed=False, tier=TIER_RETRY,
                           detail=f"git diff failed: {e}")

    if result.returncode != 0:
        return CheckResult(name="new_code_has_tests", passed=False, tier=TIER_RETRY,
                           detail=f"git diff exit {result.returncode}")

    src_exts = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".sol", ".java", ".rb")
    new_src: list[str] = []
    test_changes: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        status, path = parts
        is_test = any(t in path for t in ("test_", "_test.", "/tests/", "/test/", "spec_", "_spec."))
        if path.endswith(src_exts):
            if status == "A" and not is_test:
                new_src.append(path)
            if is_test:
                test_changes.append(path)

    if not new_src:
        return CheckResult(name="new_code_has_tests", passed=True,
                           detail="no new source files since base_ref — vacuously satisfied")

    if len(test_changes) >= max(1, len(new_src) // 2):
        return CheckResult(name="new_code_has_tests", passed=True,
                           detail=f"{len(new_src)} new src files, {len(test_changes)} test files modified")

    return CheckResult(
        name="new_code_has_tests", passed=False, tier=TIER_RETRY,
        detail=f"{len(new_src)} new src files but only {len(test_changes)} test files modified",
    )


def check_project_no_destructive_ops(manifest: dict[str, Any]) -> CheckResult:
    """Verify no destructive ops (rm -rf, git reset --hard, drop database, etc.) were
    declared as part of this run's actions.

    Looks at manifest['actions'] (list of action records, each with 'cmd' field).
    Operator can override per-action via 'authorized_destructive': true.
    """
    actions = manifest.get("actions", [])
    if not isinstance(actions, list):
        return CheckResult(name="no_destructive_ops", passed=True,
                           detail="no actions logged in manifest — vacuously satisfied")

    destructive_patterns = (
        "rm -rf", "rm -fr", "git reset --hard", "git push --force", "git push -f",
        "DROP TABLE", "DROP DATABASE", "TRUNCATE",
        "git clean -fd", "git clean -fx",
        "kubectl delete", "terraform destroy",
        "docker system prune -a",
    )

    found: list[str] = []
    for act in actions:
        if not isinstance(act, dict):
            continue
        if act.get("authorized_destructive"):
            continue
        cmd = act.get("cmd", "")
        for pat in destructive_patterns:
            if pat in cmd:
                found.append(f"{pat} in: {cmd[:120]}")
                break

    if found:
        return CheckResult(
            name="no_destructive_ops", passed=False, tier=TIER_OPERATOR,
            detail=f"{len(found)} unauthorized destructive op(s): {found[0]}",
        )
    return CheckResult(name="no_destructive_ops", passed=True,
                       detail=f"checked {len(actions)} actions — none destructive")


CVSS_V4_BASE_METRICS = (
    "AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA",
)
CVSS_V4_METRIC_VALUES = {
    "AV": frozenset("NALP"),
    "AC": frozenset("LH"),
    "AT": frozenset("NP"),
    "PR": frozenset("NLH"),
    "UI": frozenset("NPA"),
    "VC": frozenset("HLN"),
    "VI": frozenset("HLN"),
    "VA": frozenset("HLN"),
    "SC": frozenset("HLN"),
    # Safety (`S`) is a MODIFIED-subsequent value only — it is legal on MSI/MSA
    # below, never on the base SC/SI/SA triad.
    "SI": frozenset("HLN"),
    "SA": frozenset("HLN"),
    "E": frozenset("XAPU"),
    "CR": frozenset("XHML"),
    "IR": frozenset("XHML"),
    "AR": frozenset("XHML"),
    "MAV": frozenset("XNALP"),
    "MAC": frozenset("XLH"),
    "MAT": frozenset("XNP"),
    "MPR": frozenset("XNLH"),
    "MUI": frozenset("XNPA"),
    "MVC": frozenset("XHLN"),
    "MVI": frozenset("XHLN"),
    "MVA": frozenset("XHLN"),
    "MSC": frozenset("XHLN"),
    "MSI": frozenset("XHLNS"),
    "MSA": frozenset("XHLNS"),
    "S": frozenset("XNP"),
    "AU": frozenset("XNY"),
    "R": frozenset("XAUI"),
    "V": frozenset("XDC"),
    "RE": frozenset("XLMH"),
    "U": frozenset(("X", "Clear", "Green", "Amber", "Red")),
}
CVSS_V4_COMPONENT_RE = re.compile(r"(?P<metric>[A-Z]{1,3}):(?P<value>[A-Za-z]+)")
# CVSS:4.0 mandates one canonical metric order in the vector string. Derived from
# the table above rather than restated, so the two cannot drift apart.
CVSS_V4_METRIC_ORDER = tuple(CVSS_V4_METRIC_VALUES)


def is_valid_cvss_v4_vector(vector: str) -> bool:
    """Validate the complete CVSS v4 vector grammar accepted by this verifier."""
    components = vector.split("/")
    if not components or components[0] != "CVSS:4.0":
        return False

    parsed: list[tuple[str, str]] = []
    for component in components[1:]:
        match = CVSS_V4_COMPONENT_RE.fullmatch(component)
        if match is None:
            return False
        metric, value = match.group("metric", "value")
        if metric not in CVSS_V4_METRIC_VALUES or value not in CVSS_V4_METRIC_VALUES[metric]:
            return False
        parsed.append((metric, value))

    metrics = [metric for metric, _value in parsed]
    positions = [CVSS_V4_METRIC_ORDER.index(metric) for metric in metrics]
    return (
        len(metrics) == len(set(metrics))
        and positions == sorted(positions)
        and set(CVSS_V4_BASE_METRICS).issubset(metrics)
    )


def check_bounty_cvss(manifest: dict[str, Any]) -> CheckResult:
    findings = manifest.get("findings") or []
    if not findings:
        return CheckResult(name="cvss_recorded", passed=False, tier=TIER_RETRY,
                           detail="no findings in manifest")

    issues: list[str] = []
    for f in findings:
        title = f.get("title", "?")
        vec = f.get("cvss_v4")
        if not vec:
            issues.append(f"{title}: missing cvss_v4")
            continue
        if not isinstance(vec, str):
            issues.append(f"{title}: cvss_v4 not a string")
            continue
        if not is_valid_cvss_v4_vector(vec):
            issues.append(f"{title}: cvss_v4 not a valid CVSS:4.0 vector")
            continue
        # The normal-finding schema requires a JSON number in [0, 10].
        score = f.get("cvss_v4_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            issues.append(f"{title}: cvss_v4_score not a JSON number")
        elif not (0.0 <= score <= 10.0):
            issues.append(f"{title}: cvss_v4_score {score} out of [0.0, 10.0]")

    if issues:
        return CheckResult(
            name="cvss_recorded", passed=False, tier=TIER_RETRY,
            detail=f"{len(issues)} CVSS validation issue(s): {issues[0]}",
        )
    return CheckResult(name="cvss_recorded", passed=True,
                       detail=f"validated CVSS:4.0 vectors on {len(findings)} findings")


def check_content_no_placeholder(manifest: dict[str, Any]) -> CheckResult:
    placeholder_re = re.compile(r"\[INSERT [^\]]+\]|\[TBD\]|\[PLACEHOLDER\]|TBD\.{3}", re.IGNORECASE)
    artifacts = manifest.get("artifacts") or []
    hits: list[str] = []
    invalid: list[str] = []
    for index, art in enumerate(artifacts):
        value = art.get("path") if isinstance(art, dict) else art
        try:
            path = resolve_vault_candidate(
                value, field_name=f"artifacts[{index}].path"
            )
        except ManifestContractError as exc:
            invalid.append(str(exc))
            continue
        if not path.exists() or path.suffix not in (".md", ".txt"):
            continue
        try:
            path = resolve_vault_file(
                value, field_name=f"artifacts[{index}].path"
            )
        except ManifestContractError as exc:
            invalid.append(str(exc))
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if placeholder_re.search(line):
                hits.append(f"{value}:{lineno}")
    if invalid:
        return CheckResult(
            name="no_placeholder_text", passed=False, tier=TIER_OPERATOR,
            detail=f"{len(invalid)} unsafe artifact path(s): {invalid[0]}",
        )
    if hits:
        return CheckResult(name="no_placeholder_text", passed=False, tier=TIER_RETRY,
                           detail=f"{len(hits)} placeholder markers: {hits[0]}")
    return CheckResult(name="no_placeholder_text", passed=True)


MODE_CHECKS = {
    "project": [
        check_project_tests_pass,
        check_project_git_clean,
        check_project_new_code_has_tests,
        check_project_no_destructive_ops,
    ],
    "bounty": [
        check_bounty_scope_and_targets,
        check_bounty_no_self_inflicted,
        check_bounty_result_evidence,
        check_bounty_no_submit,
    ],
}


# ─── Orchestrator ────────────────────────────────────────────────

def run_all_checks(manifest: dict[str, Any]) -> RunReport:
    started = datetime.now(timezone.utc).isoformat()
    report = RunReport(run_id=manifest["run_id"], mode=manifest.get("mode", "?"),
                       started_at=started, finished_at="")

    profile_result = check_typed_profile_supported(manifest)
    report.checks.append(profile_result)
    contract_result = check_verification_contract(manifest) if profile_result.passed else CheckResult(
        "verification_contract_integrity", False, TIER_OPERATOR, "typed profile unsupported"
    )
    report.checks.append(contract_result)

    for check_fn in (
        check_operator_approval,
        check_citations_resolve,
        check_no_todo_in_modified,
        check_phase_tags,
    ):
        try:
            report.checks.append(check_fn(manifest))
        except Exception as e:
            report.checks.append(CheckResult(
                name=check_fn.__name__, passed=False, tier=TIER_OPERATOR,
                detail=f"check raised: {type(e).__name__}: {e}",
            ))

    if contract_result.passed:
        for common_fn in (
            check_verification_coverage,
            check_memory_bookends,
            check_review_bindings,
            check_artifact_and_gate_bindings,
            check_action_log_complete,
            check_iteration_invalidation,
            check_external_delivery_blocked,
        ):
            try:
                report.checks.append(common_fn(manifest))
            except Exception as e:
                report.checks.append(CheckResult(
                    name=common_fn.__name__, passed=False, tier=TIER_OPERATOR,
                    detail=f"check raised: {type(e).__name__}: {e}",
                ))
    mode = manifest.get("mode", "")
    mode_functions = MODE_CHECKS[mode] if mode in MODE_CHECKS else []
    for fn in mode_functions if contract_result.passed else []:
        try:
            report.checks.append(fn(manifest))
        except Exception as e:
            report.checks.append(CheckResult(
                name=fn.__name__, passed=False, tier=TIER_OPERATOR,
                detail=f"check raised: {type(e).__name__}: {e}",
            ))

    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def render_report(report: RunReport) -> str:
    overall = {
        TIER_OK: "PASS",
        TIER_AUTOFIX: "PASS-AFTER-AUTOFIX",
        TIER_RETRY: "RETRY-NEEDED",
        TIER_OPERATOR: "OPERATOR-SURFACE",
    }[report.overall_tier]

    lines = [
        "---",
        f"run_id: {report.run_id}",
        f"mode: {report.mode}",
        f"verdict: {overall}",
        f"started_at: {report.started_at}",
        f"finished_at: {report.finished_at}",
        f"check_count: {len(report.checks)}",
        f"failed_count: {sum(1 for c in report.checks if not c.passed and not c.advisory)}",
        "---",
        "",
        f"# Vibecoding Check — {report.run_id}",
        "",
        f"**Mode:** {report.mode}",
        f"**Verdict:** **{overall}**",
        "",
        "## Checks",
    ]
    for c in report.checks:
        marker = "⚠" if c.advisory else ("✓" if c.passed else "✗")
        tier_note = "" if c.passed else f" *(tier {c.tier})*"
        lines.append(f"- {marker} **{c.name}**{tier_note}")
        if c.detail:
            lines.append(f"    - {c.detail}")
        if c.auto_fixed:
            lines.append("    - *auto-fixed*")
    lines.append("")
    if report.overall_tier == TIER_OPERATOR:
        lines.append("## Operator action required")
        lines.append("")
        lines.append("Tier-3 issues need human judgment. Surface this in the next morning brief.")
        lines.append(
            f"To override: write a `{APPROVAL_SCHEMA}` record with "
            "`decision: override`, the exact `run_id`, and a nonempty `override_reason`."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run vibecoding-check on a mode run.")
    p.add_argument("--run-id", required=True, help="Run ID (e.g. BTY-2026-05-02-1234)")
    p.add_argument("--quiet", action="store_true", help="Suppress per-check stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_id = validate_run_id(args.run_id)
        manifest = load_manifest(run_id)
        if "run_id" not in manifest:
            manifest["run_id"] = run_id
        elif manifest["run_id"] != run_id:
            raise ManifestContractError(
                "manifest run_id does not match the validated --run-id"
            )
        state_file = _state_output_path(run_id)
    except (ManifestContractError, OSError, ValueError) as exc:
        print(f"vibecoding-check rejected input: {exc}", file=sys.stderr)
        return TIER_OPERATOR

    report = run_all_checks(manifest)
    out_text = render_report(report)
    atomic_write(state_file, out_text)

    if not args.quiet:
        print(out_text)
    print(f"State: {state_file}")
    print(f"Verdict tier: {report.overall_tier} "
          f"({['PASS', 'AUTOFIX', 'RETRY', 'OPERATOR'][report.overall_tier]})")
    return report.overall_tier


if __name__ == "__main__":
    sys.exit(main())
