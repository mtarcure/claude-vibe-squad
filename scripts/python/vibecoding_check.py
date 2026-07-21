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
  1. Operator approval token present
  2. Declared artifacts exist
  3. Citations resolve (URL 200 / file exists / git ref resolves)
  4. No TODO/FIXME/XXX in modified code
  5. All declared phase-tags emitted
  6. No unauthorized file deletions in run diff in run log

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
  _state/runs/<run-id>/manifest.yaml   — written by the Lead executing the mode
  _state/vibecoding-check/<run-id>.md  — written by THIS script on tier-2/3
  _state/approvals/<run-id>.md         — written by operator (APPROVE | OVERRIDE)
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
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
    REQUIRED_PHASE_IDS,
    ContractError,
    author_family_for_lane,
    canonical_json_bytes,
    read_packet_contract_echoes,
    read_yaml_frontmatter,
    validate_verification_contract,
    verification_contract_sha256,
)

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
RUNS_DIR = STATE_DIR / "runs"
APPROVALS_DIR = STATE_DIR / "approvals"
CHECK_DIR = STATE_DIR / "vibecoding-check"

# Severity ladders
TIER_OK = 0
TIER_AUTOFIX = 1
TIER_RETRY = 2
TIER_OPERATOR = 3


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


def resolve_vault_file(value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestContractError(f"{field_name} must be a nonempty path")
    raw = Path(value)
    candidate = raw if raw.is_absolute() else VAULT_ROOT / raw
    try:
        resolved = candidate.resolve(strict=True)
        root = VAULT_ROOT.resolve(strict=True)
    except OSError as exc:
        raise ManifestContractError(f"{field_name} does not exist: {value}") from exc
    if not resolved.is_relative_to(root) or candidate.is_symlink() or not resolved.is_file():
        raise ManifestContractError(f"{field_name} must be a regular non-symlink file under VAULT_ROOT")
    return resolved


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


def check_memory_bookends(manifest: dict[str, Any]) -> CheckResult:
    try:
        _plan_sha, bundle = _current_hashes(manifest)
        memory = manifest.get("memory")
        if not isinstance(memory, dict):
            raise ManifestContractError("memory must be an object")
        recall = memory.get("recall")
        if not isinstance(recall, dict):
            raise ManifestContractError("memory.recall is required")
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
        targets = []
        for collection in (manifest.get("actions", []), manifest.get("findings", []), manifest.get("negative_results", [])):
            if not isinstance(collection, list):
                raise ManifestContractError("Bounty target collection must be a list")
            targets.extend(item.get("target") for item in collection if isinstance(item, dict) and item.get("target"))
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
            pinned = manifest.get("verification_contract", {}).get("author_family")
            for finding in findings:
                required = ("id", "title", "target", "cvss_v4", "cvss_v4_score", "artifact_sha256", "author_family", "author_run_id", "reproduction")
                if any(key not in finding for key in required):
                    raise ManifestContractError("normal finding is structurally incomplete")
                reproduction = finding["reproduction"]
                if not isinstance(reproduction, dict) or reproduction.get("reproducer_family") == pinned or reproduction.get("reproduction_run_id") == manifest.get("run_id"):
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
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to load a run manifest") from exc
    manifest_path = RUNS_DIR / run_id / "manifest.yaml"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text()) or {}


# ─── Universal checks ───────────────────────────────────────────────

def check_operator_approval(manifest: dict[str, Any]) -> CheckResult:
    run_id = manifest["run_id"]
    approval_path = APPROVALS_DIR / f"{run_id}.md"
    if not approval_path.exists():
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail=f"no approval file at {approval_path.relative_to(VAULT_ROOT)}",
        )
    text = approval_path.read_text()
    if "APPROVE" not in text and "OVERRIDE" not in text:
        return CheckResult(
            name="operator_approval", passed=False, tier=TIER_OPERATOR,
            detail="approval file present but no APPROVE / OVERRIDE token",
        )
    if "OVERRIDE" in text:
        return CheckResult(
            name="operator_approval", passed=True,
            detail="OVERRIDE token present (non-default; audit trail in approval file)",
        )
    return CheckResult(name="operator_approval", passed=True)


def check_artifacts_exist(manifest: dict[str, Any]) -> CheckResult:
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        return CheckResult(
            name="artifacts_exist", passed=False, tier=TIER_RETRY,
            detail="manifest declares no artifacts",
        )
    missing = []
    for art in artifacts:
        value = art.get("path") if isinstance(art, dict) else art
        path = (VAULT_ROOT / value) if not Path(value).is_absolute() else Path(value)
        if not path.exists():
            missing.append(str(path))
    if missing:
        return CheckResult(
            name="artifacts_exist", passed=False, tier=TIER_RETRY,
            detail=f"{len(missing)} missing: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}",
        )
    return CheckResult(name="artifacts_exist", passed=True,
                       detail=f"{len(artifacts)} artifacts present")


def check_citations_resolve(manifest: dict[str, Any]) -> CheckResult:
    cites = manifest.get("citations") or []
    if not cites:
        return CheckResult(name="citations_resolve", passed=True,
                           detail="no citations declared")
    bad: list[str] = []
    network_bad: list[str] = []
    for cite in cites:
        if cite.startswith(("http://", "https://")):
            try:
                status = _probe_http(cite)
                if status >= 400:
                    network_bad.append(f"{cite} → {status}")
            except OSError as e:
                network_bad.append(f"{cite} → {type(e).__name__}")
        elif cite.startswith("git:"):
            ref = cite[4:]
            try:
                subprocess.check_output(["git", "rev-parse", ref], stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                bad.append(f"{cite} → not a git ref")
        else:
            p = (VAULT_ROOT / cite) if not Path(cite).is_absolute() else Path(cite)
            if not p.exists():
                bad.append(f"{cite} → file not found")
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


def _probe_http(url: str) -> int:
    headers = {"User-Agent": "Mozilla/5.0 (vibecoding-check)"}
    status = 599
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
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
    for rel in modified:
        path = (VAULT_ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if TODO_RE.search(line) and not DOC_TODO_ALLOWLIST.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
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
    log_path = RUNS_DIR / manifest["run_id"] / "phase-log.txt"
    if not log_path.exists():
        return CheckResult(
            name="phase_tags", passed=False, tier=TIER_RETRY,
            detail=f"no phase-log at {log_path.relative_to(VAULT_ROOT)}",
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


def check_no_unauthorized_deletions(manifest: dict[str, Any]) -> CheckResult:
    """Check 6 (universal): no unauthorized file deletions in the run's diff."""
    run_id = manifest["run_id"]
    approval_path = APPROVALS_DIR / f"{run_id}.md"

    try:
        snapshot_keys = [
            str(v)
            for v in (
                manifest.get("task_id"),
                manifest.get("dispatch_task_id"),
                run_id,
            )
            if v and str(v) != "none"
        ]
        snapshot_sha = ""
        for key in snapshot_keys:
            result = subprocess.run(
                ["git", "log", "--oneline", "--grep", f"auto-snapshot: before .*{key}"],
                capture_output=True, text=True, cwd=str(VAULT_ROOT),
            )
            if result.stdout.strip():
                snapshot_sha = result.stdout.split()[0]
                break

        if not snapshot_sha:
            fallback_diff = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=D", "--"],
                capture_output=True, text=True, cwd=str(VAULT_ROOT),
            )
            fallback_deleted = [f.strip() for f in fallback_diff.stdout.splitlines() if f.strip()]
            if not fallback_deleted:
                return CheckResult(
                    name="no_unauthorized_deletions", passed=True, tier=TIER_OK,
                    detail="No dispatch snapshot found; no current working-tree deletions detected.",
                )
            deleted_files = fallback_deleted
        else:
            # Compare the dispatch snapshot against the current working tree. Using
            # HEAD here misses ordinary unstaged deletions, which are the common
            # risk during long-running agent work.
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=D", snapshot_sha, "--"],
                capture_output=True, text=True, cwd=str(VAULT_ROOT),
            )
            deleted_files = [f.strip() for f in diff_result.stdout.splitlines() if f.strip()]

        if not deleted_files:
            return CheckResult(
                name="no_unauthorized_deletions", passed=True, tier=TIER_OK,
                detail="No deletions detected in run diff.",
            )

        if approval_path.exists():
            approval_text = approval_path.read_text()
            deletion_approved = any(
                line.strip().lower() in {
                    "deletion_approved: true",
                    "deletion_approved: yes",
                }
                for line in approval_text.splitlines()
            )
            if deletion_approved or "APPROVE_DELETIONS" in approval_text:
                return CheckResult(
                    name="no_unauthorized_deletions", passed=True, tier=TIER_OK,
                    detail=f"Deletions approved: {deleted_files}",
                )

        return CheckResult(
            name="no_unauthorized_deletions", passed=False, tier=TIER_OPERATOR,
            detail=(
                f"UNAUTHORIZED DELETIONS in run {run_id}:\n"
                + "\n".join(f"  - {f}" for f in deleted_files)
                + "\n\nThe auto-snapshot makes these recoverable."
                + f"\nTo approve: write 'APPROVE_DELETIONS' to _state/approvals/{run_id}.md"
                + "\nTo recover: git checkout <snapshot-sha> -- <file-path>"
            ),
        )
    except Exception as e:
        return CheckResult(
            name="no_unauthorized_deletions", passed=False, tier=TIER_OPERATOR,
            detail=f"Delete-check errored: {e}",
        )


# ─── Mode-specific checks ──────────────────────────────────────────

def check_project_tests_pass(manifest: dict[str, Any]) -> CheckResult:
    cmd = manifest.get("test_command") or "pytest -x"
    cwd = manifest.get("test_cwd") or str(VAULT_ROOT)
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                                text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return CheckResult(name="tests_pass", passed=False, tier=TIER_RETRY,
                           detail="test command timed out")
    if result.returncode != 0:
        return CheckResult(
            name="tests_pass", passed=False, tier=TIER_RETRY,
            detail=f"`{cmd}` exit {result.returncode}: {result.stdout[-300:].strip()}",
        )
    return CheckResult(name="tests_pass", passed=True,
                       detail=f"`{cmd}` exit 0")


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
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", f"{base_ref}..HEAD"],
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


CVSS_V4_VECTOR_RE = re.compile(
    r"^CVSS:4\.0"
    r"(?:/AV:[NALP])"   # Attack Vector
    r"(?:/AC:[LH])"     # Attack Complexity
    r"(?:/AT:[NP])"     # Attack Requirements
    r"(?:/PR:[NLH])"    # Privileges Required
    r"(?:/UI:[NPA])"    # User Interaction
    r"(?:/VC:[HLN])"    # Vulnerable Confidentiality
    r"(?:/VI:[HLN])"    # Vulnerable Integrity
    r"(?:/VA:[HLN])"    # Vulnerable Availability
    r"(?:/SC:[HLN])"    # Subsequent Confidentiality
    r"(?:/SI:[HLN])"    # Subsequent Integrity
    r"(?:/SA:[HLN])"    # Subsequent Availability
    r"(?:/[A-Z][A-Z]?:[A-Z]+)*"  # optional Threat / Environmental / Supplemental
    r"$"
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
        if not CVSS_V4_VECTOR_RE.match(vec):
            issues.append(f"{title}: cvss_v4 not a valid CVSS:4.0 vector")
            continue
        # Optional cvss_v4_score field — if present, must be numeric in [0, 10].
        score = f.get("cvss_v4_score")
        if score is not None:
            try:
                score_f = float(score)
                if not (0.0 <= score_f <= 10.0):
                    issues.append(f"{title}: cvss_v4_score {score_f} out of [0.0, 10.0]")
            except (TypeError, ValueError):
                issues.append(f"{title}: cvss_v4_score not numeric")

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
    for art in artifacts:
        path = (VAULT_ROOT / art) if not Path(art).is_absolute() else Path(art)
        if not path.exists() or path.suffix not in (".md", ".txt"):
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if placeholder_re.search(line):
                hits.append(f"{art}:{lineno}")
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
        check_artifacts_exist,
        check_citations_resolve,
        check_no_todo_in_modified,
        check_phase_tags,
        check_no_unauthorized_deletions,
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
        lines.append("To override: write `OVERRIDE` + `override_reason: <reason>` to the approval file.")
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run vibecoding-check on a mode run.")
    p.add_argument("--run-id", required=True, help="Run ID (e.g. BTY-2026-05-02-1234)")
    p.add_argument("--quiet", action="store_true", help="Suppress per-check stdout")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.run_id)
    if "run_id" not in manifest:
        manifest["run_id"] = args.run_id

    report = run_all_checks(manifest)
    out_text = render_report(report)
    state_file = CHECK_DIR / f"{args.run_id}.md"
    atomic_write(state_file, out_text)

    if not args.quiet:
        print(out_text)
    print(f"State: {state_file}")
    print(f"Verdict tier: {report.overall_tier} "
          f"({['PASS', 'AUTOFIX', 'RETRY', 'OPERATOR'][report.overall_tier]})")
    return report.overall_tier


if __name__ == "__main__":
    sys.exit(main())
