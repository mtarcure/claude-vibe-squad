#!/usr/bin/env python3
"""Deterministically collate strict swarm-member-result/v1 sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from subswarm_capacity import CapacityError, subagent_code_ceiling


MEMBER_SCHEMA = "swarm-member-result/v1"
DIFF_SCHEMA = "swarm-diff/v1"
ORCHESTRATION_DIRECTIVE_SCHEMA = "lead-orchestration-directive/v1"
MEMBER_BUNDLE_SCHEMA = "swarm-member-bundle/v1"
REVIEW_SUBJECTS_SCHEMA = "subswarm-review-subjects/v1"
REVIEW_ITEM_SCHEMA = "subswarm-review-item/v1"
FINDING_REVIEW_SCHEMA = "finding-review/v1"
SUBSWARM_FEATURE_FLAG = "SQUAD_SUBSWARM_ORCHESTRATION_ENABLED"
SUBSWARM_CONCURRENCY_CAP = "SQUAD_SUBAGENT_CONCURRENCY_CAP"
COMPLETE_STATUSES = frozenset({"complete", "needs_review"})
MEMBER_STATUSES = COMPLETE_STATUSES | frozenset(
    {"blocked", "needs_human", "cancelled", "timed_out"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEMBER_ID = re.compile(r"^(claude|gpt-codex|gemini|kimi):sub(\d{2})$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LANE_FAMILY = {
    "claude": "anthropic",
    "gpt-codex": "openai",
    "gemini": "google",
    "kimi": "moonshot",
}
_TAXONOMY_JSON = re.compile(
    r"```json(?:\s+swarm-finding-taxonomy/v1)?\s*\n(\{.*?\})\s*```", re.S
)


class SwarmDiffError(ValueError):
    """Raised when a member result or taxonomy violates the swarm contract."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SwarmDiffError(f"not canonical-JSON serializable: {exc}") from exc


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_subswarm_enabled() -> None:
    if os.environ.get(SUBSWARM_FEATURE_FLAG, "0") != "1":
        raise SwarmDiffError(
            f"hierarchical orchestration is disabled; set {SUBSWARM_FEATURE_FLAG}=1"
        )


def _sha256_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SwarmDiffError(f"{field} must be lowercase 64-hex")
    return value


def _subagent_cap() -> int:
    try:
        return subagent_code_ceiling()
    except CapacityError as exc:
        raise SwarmDiffError(str(exc)) from exc


def load_taxonomy(path: Path) -> dict[str, Any]:
    """Load the fenced swarm-finding-taxonomy/v1 JSON object."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SwarmDiffError(f"cannot read taxonomy {path}: {exc}") from exc
    match = _TAXONOMY_JSON.search(text)
    if not match:
        raise SwarmDiffError("taxonomy must contain a fenced JSON object")
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SwarmDiffError(f"taxonomy JSON is invalid: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != "swarm-finding-taxonomy/v1":
        raise SwarmDiffError("taxonomy schema_version must be swarm-finding-taxonomy/v1")
    values: dict[str, Any] = {}
    for source, target in (
        ("weakness_classes", "weakness"),
        ("impact_classes", "impact_class"),
        ("dispositions", "disposition"),
        ("severities", "severity"),
        ("confidences", "confidence"),
    ):
        items = raw.get(source)
        if not isinstance(items, list) or not items or not all(
            isinstance(item, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", item)
            for item in items
        ):
            raise SwarmDiffError(f"taxonomy {source} must be a nonempty token list")
        if len(items) != len(set(items)):
            raise SwarmDiffError(f"taxonomy {source} contains duplicates")
        values[target] = frozenset(items)
    pattern = raw.get("affected_surface_pattern")
    if not isinstance(pattern, str) or not pattern:
        raise SwarmDiffError("taxonomy affected_surface_pattern must be a nonempty regex")
    try:
        values["affected_surface_pattern"] = re.compile(pattern)
    except re.error as exc:
        raise SwarmDiffError(f"taxonomy affected_surface_pattern is invalid: {exc}") from exc
    if raw.get("finding_key_fields") != [
        "target",
        "weakness_class",
        "affected_surface",
        "impact_class",
    ]:
        raise SwarmDiffError("taxonomy finding_key_fields does not match the v1 key contract")
    return values


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SwarmDiffError(f"{field} must be a nonempty string")
    return value.strip()


def finding_key(finding: dict[str, Any]) -> str:
    """Hash the locked trimmed fields joined by ASCII unit separator (0x1f)."""

    parts = [
        _string(finding.get("target"), "finding.target"),
        _string(finding.get("weakness_class"), "finding.weakness_class"),
        _string(finding.get("affected_surface"), "finding.affected_surface"),
        _string(finding.get("impact_class"), "finding.impact_class"),
    ]
    canonical = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_member_result(
    value: object,
    taxonomy: dict[str, Any],
    expected_spec_sha256: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SwarmDiffError("member result must be an object")
    required = {
        "schema_version",
        "task_id",
        "parent_task_id",
        "lane",
        "swarm_spec_sha256",
        "status",
        "findings",
        "coverage",
        "limitations",
    }
    if set(value) != required:
        raise SwarmDiffError(
            f"member keys mismatch (missing={sorted(required - set(value))}, "
            f"extra={sorted(set(value) - required)})"
        )
    if value["schema_version"] != MEMBER_SCHEMA:
        raise SwarmDiffError(f"schema_version must be {MEMBER_SCHEMA}")
    for field in ("task_id", "parent_task_id", "lane"):
        _string(value[field], field)
    digest = value["swarm_spec_sha256"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise SwarmDiffError("swarm_spec_sha256 must be lowercase 64-hex")
    if digest != expected_spec_sha256:
        raise SwarmDiffError("swarm_spec_sha256 does not match the frozen parent spec")
    if value["status"] not in MEMBER_STATUSES:
        raise SwarmDiffError(f"invalid member status: {value['status']!r}")
    for field in ("coverage", "limitations"):
        if not isinstance(value[field], list) or not all(
            isinstance(item, str) and item.strip() for item in value[field]
        ):
            raise SwarmDiffError(f"{field} must be a list of nonempty strings")
    if not isinstance(value["findings"], list):
        raise SwarmDiffError("findings must be a list")

    normalized_findings: list[dict[str, Any]] = []
    for index, finding in enumerate(value["findings"]):
        if not isinstance(finding, dict):
            raise SwarmDiffError(f"findings[{index}] must be an object")
        required_finding = {
            "target",
            "weakness_class",
            "affected_surface",
            "impact_class",
            "disposition",
            "severity",
            "confidence",
            "summary",
            "evidence",
        }
        optional_finding = {"finding_key"}
        if not required_finding.issubset(finding) or set(finding) - required_finding - optional_finding:
            raise SwarmDiffError(f"findings[{index}] keys violate the finding schema")
        weakness = _string(finding["weakness_class"], "finding.weakness_class")
        impact = _string(finding["impact_class"], "finding.impact_class")
        if weakness not in taxonomy["weakness"]:
            raise SwarmDiffError(f"unknown weakness taxonomy value: {weakness}")
        if impact not in taxonomy["impact_class"]:
            raise SwarmDiffError(f"unknown impact class: {impact}")
        for field in ("disposition", "severity", "confidence"):
            if finding[field] not in taxonomy[field]:
                raise SwarmDiffError(f"invalid {field}: {finding[field]!r}")
        surface = _string(finding["affected_surface"], "finding.affected_surface")
        if not taxonomy["affected_surface_pattern"].fullmatch(surface):
            raise SwarmDiffError(f"affected_surface violates taxonomy pattern: {surface!r}")
        _string(finding["summary"], "finding.summary")
        if not isinstance(finding["evidence"], list) or not all(
            isinstance(item, str) and item.strip() for item in finding["evidence"]
        ):
            raise SwarmDiffError("finding.evidence must be a list of nonempty strings")
        key = finding_key(finding)
        if "finding_key" in finding and finding["finding_key"] != key:
            raise SwarmDiffError(f"claimed finding_key does not match canonical key: {key}")
        normalized = {key_: finding[key_] for key_ in sorted(required_finding)}
        normalized["finding_key"] = key
        normalized_findings.append(normalized)

    normalized = dict(value)
    normalized["findings"] = sorted(
        normalized_findings,
        key=lambda item: (item["finding_key"], item["severity"], item["summary"]),
    )
    normalized["coverage"] = sorted(set(value["coverage"]))
    normalized["limitations"] = sorted(set(value["limitations"]))
    return normalized


def _normalize_orchestration_directive_core(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SwarmDiffError("orchestration directive must be an object")
    required = {
        "schema_version",
        "parent_task_id",
        "lane",
        "mode",
        "max_concurrency",
        "members",
    }
    if set(value) != required:
        raise SwarmDiffError("orchestration directive keys mismatch")
    if value["schema_version"] != ORCHESTRATION_DIRECTIVE_SCHEMA:
        raise SwarmDiffError(
            f"directive schema_version must be {ORCHESTRATION_DIRECTIVE_SCHEMA}"
        )
    parent_task_id = _string(value["parent_task_id"], "parent_task_id")
    if not _TASK_ID.fullmatch(parent_task_id):
        raise SwarmDiffError("parent_task_id is unsafe for replica output paths")
    lane = _string(value["lane"], "lane")
    if lane not in _LANE_FAMILY:
        raise SwarmDiffError(f"unsupported directive lane: {lane}")
    mode = value["mode"]
    if mode not in {"parallel", "sequential"}:
        raise SwarmDiffError("directive mode must be parallel or sequential")
    maximum = value["max_concurrency"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise SwarmDiffError("max_concurrency must be a positive integer")
    if maximum > _subagent_cap():
        raise SwarmDiffError("max_concurrency exceeds the configured per-lead cap")
    if mode == "sequential" and maximum != 1:
        raise SwarmDiffError("sequential orchestration requires max_concurrency=1")
    if not isinstance(value["members"], list) or not value["members"]:
        raise SwarmDiffError("directive members must be a nonempty list")

    normalized_members: list[dict[str, Any]] = []
    member_ids: set[str] = set()
    for index, member in enumerate(value["members"]):
        required_member = {
            "member_id",
            "lane",
            "replica_index",
            "role",
            "objective_sha256",
            "output_path",
            "requires_mcp",
            "tool_mode",
            "depends_on",
        }
        if not isinstance(member, dict) or set(member) != required_member:
            raise SwarmDiffError(f"directive members[{index}] keys mismatch")
        member_id = _string(member["member_id"], "member_id")
        match = _MEMBER_ID.fullmatch(member_id)
        if not match or match.group(1) != lane or member["lane"] != lane:
            raise SwarmDiffError("member_id must be <lane>:subNN and match directive lane")
        if member_id in member_ids:
            raise SwarmDiffError(f"duplicate directive member_id: {member_id}")
        member_ids.add(member_id)
        replica_index = member["replica_index"]
        if (
            isinstance(replica_index, bool)
            or not isinstance(replica_index, int)
            or replica_index < 1
            or replica_index != int(match.group(2))
        ):
            raise SwarmDiffError("replica_index must match member_id subNN")
        role = _string(member["role"], "member.role")
        objective_sha256 = _sha256_string(
            member["objective_sha256"], "member.objective_sha256"
        )
        output_path = _string(member["output_path"], "member.output_path")
        expected_output = (
            f"_state/subswarm/{parent_task_id}/{lane}/"
            f"sub{replica_index:02d}/result.json"
        )
        if output_path != expected_output:
            raise SwarmDiffError(
                f"member.output_path must equal isolated path {expected_output}"
            )
        if not isinstance(member["requires_mcp"], bool):
            raise SwarmDiffError("member.requires_mcp must be boolean")
        tool_mode = member["tool_mode"]
        if tool_mode not in {"inherited", "lead-brokered", "none"}:
            raise SwarmDiffError("member.tool_mode is invalid")
        if lane == "kimi" and tool_mode == "inherited":
            raise SwarmDiffError("Kimi subagents must never assume inherited MCP")
        if member["requires_mcp"] and tool_mode == "none":
            raise SwarmDiffError("MCP-requiring member needs inherited or lead-brokered tools")
        if lane == "kimi" and member["requires_mcp"] and tool_mode != "lead-brokered":
            raise SwarmDiffError("Kimi MCP work must be lead-brokered")
        depends_on = member["depends_on"]
        if not isinstance(depends_on, list) or not all(
            isinstance(item, str) and item.strip() for item in depends_on
        ):
            raise SwarmDiffError("member.depends_on must be a string list")
        if len(depends_on) != len(set(depends_on)) or member_id in depends_on:
            raise SwarmDiffError("member.depends_on contains a duplicate or self reference")
        normalized_members.append(
            {
                "member_id": member_id,
                "lane": lane,
                "replica_index": replica_index,
                "role": role,
                "objective_sha256": objective_sha256,
                "output_path": output_path,
                "requires_mcp": member["requires_mcp"],
                "tool_mode": tool_mode,
                "depends_on": sorted(depends_on),
            }
        )
    if maximum > len(normalized_members):
        raise SwarmDiffError("max_concurrency cannot exceed member count")
    unknown_dependencies = {
        dependency
        for member in normalized_members
        for dependency in member["depends_on"]
        if dependency not in member_ids
    }
    if unknown_dependencies:
        raise SwarmDiffError(
            f"directive contains unknown dependencies: {sorted(unknown_dependencies)}"
        )
    dependency_graph = {
        member["member_id"]: set(member["depends_on"])
        for member in normalized_members
    }
    resolved: set[str] = set()
    while len(resolved) < len(dependency_graph):
        ready = {
            member_id
            for member_id, dependencies in dependency_graph.items()
            if member_id not in resolved and dependencies <= resolved
        }
        if not ready:
            raise SwarmDiffError("directive dependency graph contains a cycle")
        resolved.update(ready)
    return {
        "schema_version": ORCHESTRATION_DIRECTIVE_SCHEMA,
        "parent_task_id": parent_task_id,
        "lane": lane,
        "mode": mode,
        "max_concurrency": maximum,
        "members": sorted(normalized_members, key=lambda item: item["member_id"]),
    }


def seal_orchestration_directive(value: object) -> dict[str, Any]:
    """Normalize and hash a default-off lead-internal orchestration directive."""
    _require_subswarm_enabled()
    core = _normalize_orchestration_directive_core(value)
    return {**core, "directive_sha256": sha256(core)}


def validate_orchestration_directive(value: object) -> dict[str, Any]:
    _require_subswarm_enabled()
    if not isinstance(value, dict) or "directive_sha256" not in value:
        raise SwarmDiffError("orchestration directive requires directive_sha256")
    supplied = _sha256_string(value["directive_sha256"], "directive_sha256")
    core = dict(value)
    core.pop("directive_sha256")
    sealed = seal_orchestration_directive(core)
    if supplied != sealed["directive_sha256"]:
        raise SwarmDiffError("orchestration directive hash mismatch")
    return sealed


def render_orchestration_directive(value: object) -> str:
    """Render the bounded directive block inserted into a lead's task context."""
    directive = validate_orchestration_directive(value)
    kimi_rule = (
        "Kimi subagents are MCP-free; every authorized MCP operation is performed "
        "by the lead and returned as a hash-bound lead-brokered tool receipt."
        if directive["lane"] == "kimi"
        else "Use only each member's declared inherited/lead-brokered/none tool mode."
    )
    encoded = json.dumps(directive, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        "## Lead-internal orchestration directive\n\n"
        f"Actually spawn only the {len(directive['members'])} declared logical members "
        "through this lane's native subagent runtime; never simulate member work. "
        "Give each spawned member its exact declared objective and require it to echo "
        "the matching objective_sha256. Execute through the machine DAG scheduler and "
        "capture each result only at its declared output_path. "
        f"Run with "
        f"at most {directive['max_concurrency']} active at once. Subagents do not "
        "receive mailbox claims, leases, independent outboxes, or settlement authority. "
        "No member may spawn another registered orchestration tier. "
        "Preserve each raw native child result and bind its SHA-256 as artifact_sha256. "
        "Represent a failed or malformed child honestly with a non-complete status and "
        "typed gap; never fabricate a result. The lead alone seals and publishes exactly "
        "one canonical swarm-member-bundle/v1 response. "
        f"{kimi_rule}\n\n```json lead-orchestration-directive/v1\n{encoded}\n```\n"
    )


def _normalize_bundle_finding(
    finding: object, taxonomy: dict[str, Any], member_id: str
) -> dict[str, Any]:
    if not isinstance(finding, dict):
        raise SwarmDiffError("bundle finding must be an object")
    base = dict(finding)
    base.pop("item_sha256", None)
    fake = {
        "schema_version": MEMBER_SCHEMA,
        "task_id": f"internal-{member_id}",
        "parent_task_id": "internal-parent",
        "lane": member_id.split(":", 1)[0],
        "swarm_spec_sha256": "0" * 64,
        "status": "complete",
        "findings": [base],
        "coverage": [],
        "limitations": [],
    }
    return validate_member_result(fake, taxonomy, "0" * 64)["findings"][0]


def _review_item_hash(
    parent_task_id: str,
    directive_sha256: str,
    member_id: str,
    kind: str,
    payload: dict[str, Any],
) -> str:
    return sha256(
        {
            "schema_version": REVIEW_ITEM_SCHEMA,
            "parent_task_id": parent_task_id,
            "orchestration_directive_sha256": directive_sha256,
            "member_id": member_id,
            "kind": kind,
            "payload": payload,
        }
    )


def _normalize_gap(value: object) -> dict[str, Any]:
    required = {"schema_version", "gap_kind", "summary", "evidence"}
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("gap keys mismatch")
    if value["schema_version"] != "subswarm-gap/v1":
        raise SwarmDiffError("gap schema_version must be subswarm-gap/v1")
    gap_kind = _string(value["gap_kind"], "gap_kind")
    if not _TOKEN.fullmatch(gap_kind):
        raise SwarmDiffError("gap_kind must be a lowercase token")
    summary = _string(value["summary"], "gap.summary")
    evidence = value["evidence"]
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence
    ):
        raise SwarmDiffError("gap.evidence must be a list of nonempty strings")
    return {
        "schema_version": "subswarm-gap/v1",
        "gap_kind": gap_kind,
        "summary": summary,
        "evidence": sorted(set(evidence)),
    }


def _normalize_completion(value: object, status: str) -> dict[str, Any]:
    required = {"schema_version", "completed", "summary"}
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("completion keys mismatch")
    if value["schema_version"] != "subswarm-completion/v1":
        raise SwarmDiffError("completion schema_version must be subswarm-completion/v1")
    if not isinstance(value["completed"], bool):
        raise SwarmDiffError("completion.completed must be boolean")
    expected = status in COMPLETE_STATUSES
    if value["completed"] is not expected:
        raise SwarmDiffError("completion.completed does not match member status")
    return {
        "schema_version": "subswarm-completion/v1",
        "completed": expected,
        "summary": _string(value["summary"], "completion.summary"),
    }


def _normalize_tool_receipt(value: object, lane: str, tool_mode: str) -> dict[str, Any]:
    required = {
        "schema_version",
        "tool_name",
        "mode",
        "request_sha256",
        "result_sha256",
        "status",
        "error_code",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("tool receipt keys mismatch")
    if value["schema_version"] != "tool-receipt/v1":
        raise SwarmDiffError("tool receipt schema_version must be tool-receipt/v1")
    mode = value["mode"]
    if mode not in {"inherited", "lead-brokered"} or mode != tool_mode:
        raise SwarmDiffError("tool receipt mode must match the directive member")
    if lane == "kimi" and mode != "lead-brokered":
        raise SwarmDiffError("Kimi tool receipts must be lead-brokered")
    status = value["status"]
    if status not in {"succeeded", "failed", "refused"}:
        raise SwarmDiffError("invalid tool receipt status")
    error_code = value["error_code"]
    if error_code is not None and (
        not isinstance(error_code, str) or not _TOKEN.fullmatch(error_code)
    ):
        raise SwarmDiffError("tool receipt error_code must be null or a token")
    return {
        "schema_version": "tool-receipt/v1",
        "tool_name": _string(value["tool_name"], "tool_name"),
        "mode": mode,
        "request_sha256": _sha256_string(value["request_sha256"], "request_sha256"),
        "result_sha256": _sha256_string(value["result_sha256"], "result_sha256"),
        "status": status,
        "error_code": error_code,
    }


def _seal_internal_member(
    value: object,
    taxonomy: dict[str, Any],
    directive_member: dict[str, Any],
    parent_task_id: str,
    directive_sha256: str,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "member_id",
        "lane",
        "replica_index",
        "objective_sha256",
        "status",
        "artifact_sha256",
        "completion",
        "findings",
        "gaps",
        "tool_receipts",
        "coverage",
        "limitations",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("internal member keys mismatch")
    if value["schema_version"] != MEMBER_SCHEMA:
        raise SwarmDiffError(f"internal member schema_version must be {MEMBER_SCHEMA}")
    member_id = directive_member["member_id"]
    if (
        value["member_id"] != member_id
        or value["lane"] != directive_member["lane"]
        or value["replica_index"] != directive_member["replica_index"]
    ):
        raise SwarmDiffError("internal member identity differs from directive")
    objective_sha256 = _sha256_string(
        value["objective_sha256"], "member.objective_sha256"
    )
    if objective_sha256 != directive_member["objective_sha256"]:
        raise SwarmDiffError("internal member objective_sha256 differs from directive")
    if value["status"] not in MEMBER_STATUSES:
        raise SwarmDiffError("invalid internal member status")
    _sha256_string(value["artifact_sha256"], "artifact_sha256")
    for field in ("coverage", "limitations"):
        if not isinstance(value[field], list) or not all(
            isinstance(item, str) and item.strip() for item in value[field]
        ):
            raise SwarmDiffError(f"member.{field} must be a nonempty-string list")
    if not all(isinstance(value[field], list) for field in ("findings", "gaps", "tool_receipts")):
        raise SwarmDiffError("findings, gaps, and tool_receipts must be lists")

    findings = []
    for raw in value["findings"]:
        payload = _normalize_bundle_finding(raw, taxonomy, member_id)
        findings.append(
            {
                **payload,
                "item_sha256": _review_item_hash(
                    parent_task_id,
                    directive_sha256,
                    member_id,
                    "finding",
                    payload,
                ),
            }
        )
    gaps = []
    for raw in value["gaps"]:
        payload = _normalize_gap(raw)
        gaps.append(
            {
                **payload,
                "item_sha256": _review_item_hash(
                    parent_task_id, directive_sha256, member_id, "gap", payload
                ),
            }
        )
    receipts = []
    for raw in value["tool_receipts"]:
        payload = _normalize_tool_receipt(
            raw, directive_member["lane"], directive_member["tool_mode"]
        )
        receipts.append(
            {
                **payload,
                "item_sha256": _review_item_hash(
                    parent_task_id,
                    directive_sha256,
                    member_id,
                    "tool_receipt",
                    payload,
                ),
            }
        )
    completion_payload = _normalize_completion(value["completion"], value["status"])
    completion = {
        **completion_payload,
        "item_sha256": _review_item_hash(
            parent_task_id,
            directive_sha256,
            member_id,
            "completion",
            completion_payload,
        ),
    }
    if directive_member["requires_mcp"] and not receipts and not gaps:
        raise SwarmDiffError("MCP-requiring member must return a tool receipt or typed gap")
    all_hashes = [
        item["item_sha256"] for item in [completion, *findings, *gaps, *receipts]
    ]
    if len(all_hashes) != len(set(all_hashes)):
        raise SwarmDiffError("duplicate review item hash within member")
    return {
        "schema_version": MEMBER_SCHEMA,
        "member_id": member_id,
        "lane": directive_member["lane"],
        "replica_index": directive_member["replica_index"],
        "objective_sha256": objective_sha256,
        "status": value["status"],
        "artifact_sha256": value["artifact_sha256"],
        "completion": completion,
        "findings": sorted(findings, key=lambda item: item["item_sha256"]),
        "gaps": sorted(gaps, key=lambda item: item["item_sha256"]),
        "tool_receipts": sorted(receipts, key=lambda item: item["item_sha256"]),
        "coverage": sorted(set(value["coverage"])),
        "limitations": sorted(set(value["limitations"])),
    }


def seal_member_bundle(
    value: object,
    taxonomy: dict[str, Any],
    directive: object,
) -> dict[str, Any]:
    """Canonicalize and hash one lead-authored internal member array."""
    _require_subswarm_enabled()
    normalized_directive = validate_orchestration_directive(directive)
    required = {
        "schema_version",
        "parent_task_id",
        "lane",
        "orchestration_directive_sha256",
        "members",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("member bundle keys mismatch")
    if value["schema_version"] != MEMBER_BUNDLE_SCHEMA:
        raise SwarmDiffError(f"bundle schema_version must be {MEMBER_BUNDLE_SCHEMA}")
    if (
        value["parent_task_id"] != normalized_directive["parent_task_id"]
        or value["lane"] != normalized_directive["lane"]
        or value["orchestration_directive_sha256"]
        != normalized_directive["directive_sha256"]
    ):
        raise SwarmDiffError("bundle identity/directive hash mismatch")
    if not isinstance(value["members"], list):
        raise SwarmDiffError("bundle members must be a list")
    directive_members = {
        item["member_id"]: item for item in normalized_directive["members"]
    }
    supplied_ids = [
        item.get("member_id") if isinstance(item, dict) else None
        for item in value["members"]
    ]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise SwarmDiffError("duplicate member_id in bundle")
    if set(supplied_ids) != set(directive_members):
        raise SwarmDiffError("bundle must contain every directive member exactly once")
    members = []
    all_item_hashes: list[str] = []
    for raw in value["members"]:
        member_id = raw["member_id"]
        core = _seal_internal_member(
            raw,
            taxonomy,
            directive_members[member_id],
            value["parent_task_id"],
            value["orchestration_directive_sha256"],
        )
        result = {**core, "result_sha256": sha256(core)}
        members.append(result)
        all_item_hashes.extend(
            item["item_sha256"]
            for item in [
                result["completion"],
                *result["findings"],
                *result["gaps"],
                *result["tool_receipts"],
            ]
        )
    if len(all_item_hashes) != len(set(all_item_hashes)):
        raise SwarmDiffError("duplicate review item hash across bundle")
    core = {
        "schema_version": MEMBER_BUNDLE_SCHEMA,
        "parent_task_id": value["parent_task_id"],
        "lane": value["lane"],
        "orchestration_directive_sha256": value[
            "orchestration_directive_sha256"
        ],
        "members": sorted(members, key=lambda item: item["member_id"]),
    }
    return {**core, "result_sha256": sha256(core)}


def validate_member_bundle(
    value: object,
    taxonomy: dict[str, Any],
    directive: object,
) -> dict[str, Any]:
    _require_subswarm_enabled()
    if not isinstance(value, dict) or "result_sha256" not in value:
        raise SwarmDiffError("member bundle requires result_sha256")
    supplied_bundle_hash = _sha256_string(value["result_sha256"], "bundle.result_sha256")
    raw_core = dict(value)
    raw_core.pop("result_sha256")
    raw_members = raw_core.get("members")
    if not isinstance(raw_members, list):
        raise SwarmDiffError("bundle members must be a list")
    unsealed_members = []
    supplied_member_hashes: dict[str, str] = {}
    for member in raw_members:
        if not isinstance(member, dict) or "result_sha256" not in member:
            raise SwarmDiffError("every internal member requires result_sha256")
        member_id = str(member.get("member_id") or "")
        supplied_member_hashes[member_id] = _sha256_string(
            member["result_sha256"], "member.result_sha256"
        )
        unsealed = dict(member)
        unsealed.pop("result_sha256")
        completion = unsealed.get("completion")
        if not isinstance(completion, dict) or "item_sha256" not in completion:
            raise SwarmDiffError("every internal member requires a completion subject")
        _sha256_string(completion["item_sha256"], "completion.item_sha256")
        completion_core = dict(completion)
        completion_core.pop("item_sha256")
        unsealed["completion"] = completion_core
        for field, kind in (
            ("findings", "finding"),
            ("gaps", "gap"),
            ("tool_receipts", "tool_receipt"),
        ):
            items = unsealed.get(field)
            if not isinstance(items, list):
                raise SwarmDiffError(f"member.{field} must be a list")
            stripped = []
            for item in items:
                if not isinstance(item, dict) or "item_sha256" not in item:
                    raise SwarmDiffError("every review item requires item_sha256")
                _sha256_string(item["item_sha256"], "item_sha256")
                item_core = dict(item)
                item_core.pop("item_sha256")
                stripped.append(item_core)
            unsealed[field] = stripped
        unsealed_members.append(unsealed)
    raw_core["members"] = unsealed_members
    expected = seal_member_bundle(raw_core, taxonomy, directive)
    if expected["result_sha256"] != supplied_bundle_hash:
        raise SwarmDiffError("member bundle result_sha256 mismatch")
    expected_members = {item["member_id"]: item for item in expected["members"]}
    for member_id, expected_member in expected_members.items():
        if supplied_member_hashes.get(member_id) != expected_member["result_sha256"]:
            raise SwarmDiffError(f"member result_sha256 mismatch: {member_id}")
    for member in raw_members:
        member_id = member["member_id"]
        if (
            member["completion"]["item_sha256"]
            != expected_members[member_id]["completion"]["item_sha256"]
        ):
            raise SwarmDiffError(f"completion item_sha256 mismatch: {member_id}")
        for field, kind in (
            ("findings", "finding"),
            ("gaps", "gap"),
            ("tool_receipts", "tool_receipt"),
        ):
            actual = [item["item_sha256"] for item in member[field]]
            wanted = [item["item_sha256"] for item in expected_members[member_id][field]]
            if sorted(actual) != sorted(wanted):
                raise SwarmDiffError(f"{kind} item_sha256 mismatch: {member_id}")
    if value != expected:
        raise SwarmDiffError("member bundle is not in canonical member/item order")
    return expected


def decompose_review_subjects(
    value: object,
    taxonomy: dict[str, Any],
    directive: object,
) -> dict[str, Any]:
    """Decompose every completion, finding, gap, and tool receipt without sampling."""
    bundle = validate_member_bundle(value, taxonomy, directive)
    subjects: list[dict[str, Any]] = []
    for member in bundle["members"]:
        item_groups = (
            ([member["completion"]], "completion"),
            (member["findings"], "finding"),
            (member["gaps"], "gap"),
            (member["tool_receipts"], "tool_receipt"),
        )
        for items, kind in item_groups:
            for item in items:
                subjects.append(
                    {
                        "subject_sha256": item["item_sha256"],
                        "member_id": member["member_id"],
                        "lane": member["lane"],
                        "replica_index": member["replica_index"],
                        "kind": kind,
                        "payload": item,
                    }
                )
    subjects.sort(key=lambda item: (item["member_id"], item["kind"], item["subject_sha256"]))
    hashes = [item["subject_sha256"] for item in subjects]
    if len(hashes) != len(set(hashes)):
        raise SwarmDiffError("review subject hashes must be globally unique")
    core = {
        "schema_version": REVIEW_SUBJECTS_SCHEMA,
        "parent_task_id": bundle["parent_task_id"],
        "lane": bundle["lane"],
        "member_ids": [member["member_id"] for member in bundle["members"]],
        "orchestration_directive_sha256": bundle[
            "orchestration_directive_sha256"
        ],
        "member_bundle_sha256": bundle["result_sha256"],
        "exhaustive": True,
        "subject_count": len(subjects),
        "subjects": subjects,
    }
    return {**core, "decomposition_sha256": sha256(core)}


def seal_finding_review(value: object) -> dict[str, Any]:
    required = {
        "schema_version",
        "subject_sha256",
        "reviewer_family",
        "verdict",
        "evidence_checked",
        "rationale",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SwarmDiffError("finding review keys mismatch")
    if value["schema_version"] != FINDING_REVIEW_SCHEMA:
        raise SwarmDiffError(f"review schema_version must be {FINDING_REVIEW_SCHEMA}")
    core = {
        "schema_version": FINDING_REVIEW_SCHEMA,
        "subject_sha256": _sha256_string(value["subject_sha256"], "subject_sha256"),
        "reviewer_family": _string(value["reviewer_family"], "reviewer_family"),
        "verdict": value["verdict"],
        "evidence_checked": value["evidence_checked"],
        "rationale": _string(value["rationale"], "rationale"),
    }
    if core["verdict"] not in {"accept", "reject", "needs_revision", "unverifiable"}:
        raise SwarmDiffError("invalid finding review verdict")
    if not isinstance(core["evidence_checked"], list) or not all(
        isinstance(item, str) and _SHA256.fullmatch(item)
        for item in core["evidence_checked"]
    ):
        raise SwarmDiffError("evidence_checked must be a SHA-256 list")
    if core["reviewer_family"] not in set(_LANE_FAMILY.values()):
        raise SwarmDiffError("reviewer_family must be a known author-family token")
    core["evidence_checked"] = sorted(set(core["evidence_checked"]))
    return {**core, "review_record_sha256": sha256(core)}


def validate_exhaustive_reviews(
    decomposition: object,
    reviews: Iterable[object],
    directive: object,
) -> list[dict[str, Any]]:
    """Require exactly one cross-family verdict for every decomposed subject."""
    _require_subswarm_enabled()
    normalized_directive = validate_orchestration_directive(directive)
    required_decomposition = {
        "schema_version",
        "parent_task_id",
        "lane",
        "member_ids",
        "orchestration_directive_sha256",
        "member_bundle_sha256",
        "exhaustive",
        "subject_count",
        "subjects",
        "decomposition_sha256",
    }
    if (
        not isinstance(decomposition, dict)
        or set(decomposition) != required_decomposition
        or decomposition.get("schema_version") != REVIEW_SUBJECTS_SCHEMA
    ):
        raise SwarmDiffError("invalid review-subject decomposition")
    claimed = decomposition.get("decomposition_sha256")
    core = dict(decomposition)
    core.pop("decomposition_sha256", None)
    if claimed != sha256(core) or decomposition.get("exhaustive") is not True:
        raise SwarmDiffError("review-subject decomposition hash/exhaustive flag is invalid")
    subjects = decomposition.get("subjects")
    if not isinstance(subjects, list) or decomposition.get("subject_count") != len(subjects):
        raise SwarmDiffError("review-subject count mismatch")
    required_subject = {
        "subject_sha256",
        "member_id",
        "lane",
        "replica_index",
        "kind",
        "payload",
    }
    lane = str(decomposition.get("lane") or "")
    member_ids = decomposition.get("member_ids")
    expected_member_ids = [
        member["member_id"] for member in normalized_directive["members"]
    ]
    if (
        lane not in _LANE_FAMILY
        or not isinstance(member_ids, list)
        or not member_ids
        or len(member_ids) != len(set(member_ids))
        or member_ids != expected_member_ids
        or decomposition.get("parent_task_id")
        != normalized_directive["parent_task_id"]
        or lane != normalized_directive["lane"]
        or decomposition.get("orchestration_directive_sha256")
        != normalized_directive["directive_sha256"]
    ):
        raise SwarmDiffError("review-subject member_ids are invalid")
    completion_members: list[str] = []
    for subject in subjects:
        if not isinstance(subject, dict) or set(subject) != required_subject:
            raise SwarmDiffError("review subject keys mismatch")
        if (
            not isinstance(subject["payload"], dict)
            or subject["payload"].get("item_sha256") != subject["subject_sha256"]
        ):
            raise SwarmDiffError("review subject payload hash mismatch")
        payload_core = dict(subject["payload"])
        payload_core.pop("item_sha256")
        if subject["kind"] not in {
            "completion",
            "finding",
            "gap",
            "tool_receipt",
        } or subject["subject_sha256"] != _review_item_hash(
            normalized_directive["parent_task_id"],
            normalized_directive["directive_sha256"],
            subject["member_id"],
            subject["kind"],
            payload_core,
        ):
            raise SwarmDiffError("review subject canonical item hash mismatch")
        match = _MEMBER_ID.fullmatch(str(subject["member_id"] or ""))
        if (
            subject["lane"] != lane
            or subject["member_id"] not in member_ids
            or not match
            or match.group(1) != lane
            or subject["replica_index"] != int(match.group(2))
        ):
            raise SwarmDiffError("review subject lane/member identity mismatch")
        if subject["kind"] == "completion":
            completion_members.append(subject["member_id"])
    expected_list = [item["subject_sha256"] for item in subjects]
    if len(expected_list) != len(set(expected_list)):
        raise SwarmDiffError("review subject hashes must be unique")
    if sorted(completion_members) != sorted(member_ids):
        raise SwarmDiffError("every declared member requires exactly one completion subject")
    expected = set(expected_list)
    author_family = _LANE_FAMILY[lane]
    normalized: list[dict[str, Any]] = []
    observed: set[str] = set()
    for raw in reviews:
        if not isinstance(raw, dict) or "review_record_sha256" not in raw:
            raise SwarmDiffError("review requires review_record_sha256")
        supplied = raw["review_record_sha256"]
        core_review = dict(raw)
        core_review.pop("review_record_sha256")
        review = seal_finding_review(core_review)
        if supplied != review["review_record_sha256"]:
            raise SwarmDiffError("finding review hash mismatch")
        subject = review["subject_sha256"]
        if subject in observed:
            raise SwarmDiffError("duplicate finding review subject")
        if subject not in expected:
            raise SwarmDiffError("finding review targets an unknown subject")
        if not author_family or review["reviewer_family"] == author_family:
            raise SwarmDiffError("finding review must be cross-family")
        observed.add(subject)
        normalized.append(review)
    missing = expected - observed
    if missing:
        raise SwarmDiffError(f"missing exhaustive finding reviews: {sorted(missing)}")
    return sorted(normalized, key=lambda item: item["subject_sha256"])


def build_diff(
    member_results: Iterable[dict[str, Any]],
    taxonomy: dict[str, Any],
    swarm_spec_sha256: str,
) -> dict[str, Any]:
    if not _SHA256.fullmatch(swarm_spec_sha256):
        raise SwarmDiffError("expected swarm spec hash must be lowercase 64-hex")
    members = [
        validate_member_result(item, taxonomy, swarm_spec_sha256)
        for item in member_results
    ]
    members.sort(key=lambda item: (item["lane"], item["task_id"]))
    if not members:
        raise SwarmDiffError("at least one member result is required")
    lanes = [item["lane"] for item in members]
    if len(lanes) != len(set(lanes)):
        raise SwarmDiffError("member lanes must be unique")
    parents = {item["parent_task_id"] for item in members}
    if len(parents) != 1:
        raise SwarmDiffError("all members must name the same parent_task_id")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        for finding in member["findings"]:
            attributed = dict(finding)
            attributed["lane"] = member["lane"]
            attributed["task_id"] = member["task_id"]
            grouped.setdefault(finding["finding_key"], []).append(attributed)

    agreement: list[dict[str, Any]] = []
    divergence: list[dict[str, Any]] = []
    lane_only: list[dict[str, Any]] = []
    for key in sorted(grouped):
        findings = sorted(grouped[key], key=lambda item: (item["lane"], item["task_id"]))
        finding_lanes = sorted({item["lane"] for item in findings})
        if len(finding_lanes) == 1:
            lane_only.append({"finding_key": key, "lane": finding_lanes[0], "findings": findings})
            continue
        variants = {
            canonical_json_bytes(
                {
                    name: item[name]
                    for name in (
                        "disposition",
                        "severity",
                        "confidence",
                        "summary",
                        "evidence",
                    )
                }
            )
            for item in findings
        }
        record = {"finding_key": key, "lanes": finding_lanes, "findings": findings}
        if len(variants) == 1:
            agreement.append(record)
        else:
            divergence.append(record)

    coverage_gaps = [
        {
            "lane": member["lane"],
            "task_id": member["task_id"],
            "status": member["status"],
            "limitations": member["limitations"],
        }
        for member in members
        if member["status"] not in COMPLETE_STATUSES or member["limitations"]
    ]
    member_refs = [
        {
            "lane": member["lane"],
            "task_id": member["task_id"],
            "status": member["status"],
            "result_sha256": sha256(member),
        }
        for member in members
    ]
    result: dict[str, Any] = {
        "schema_version": DIFF_SCHEMA,
        "parent_task_id": next(iter(parents)),
        "swarm_spec_sha256": swarm_spec_sha256,
        "members": member_refs,
        "agreement": agreement,
        "divergence": divergence,
        "lane_only": lane_only,
        "coverage_gaps": coverage_gaps,
        "mandatory_review": True,
    }
    result["diff_sha256"] = sha256(result)
    return result


def freeze_diff(
    output: Path,
    member_paths: Iterable[Path],
    taxonomy_path: Path,
    swarm_spec_sha256: str,
) -> tuple[dict[str, Any], bool]:
    """Create a diff once. Existing valid output is immutable and returned unchanged."""

    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SwarmDiffError(f"existing frozen diff is unreadable: {exc}") from exc
        if not isinstance(existing, dict) or existing.get("schema_version") != DIFF_SCHEMA:
            raise SwarmDiffError("existing frozen diff does not use swarm-diff/v1")
        if existing.get("swarm_spec_sha256") != swarm_spec_sha256:
            raise SwarmDiffError("existing frozen diff belongs to a different swarm spec")
        claimed = existing.get("diff_sha256")
        unhashed = dict(existing)
        unhashed.pop("diff_sha256", None)
        if claimed != sha256(unhashed):
            raise SwarmDiffError("existing frozen diff hash is invalid")
        return existing, False

    taxonomy = load_taxonomy(taxonomy_path)
    members: list[dict[str, Any]] = []
    for path in member_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SwarmDiffError(f"cannot read member result {path}: {exc}") from exc
        members.append(value)
    diff = build_diff(members, taxonomy, swarm_spec_sha256)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    return diff, True


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SwarmDiffError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SwarmDiffError(f"{label} must be a JSON object")
    return value


def _freeze_json_output(output: Path, value: dict[str, Any]) -> bool:
    """Atomically create immutable canonical output, accepting identical retries."""
    encoded = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        try:
            existing = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise SwarmDiffError(f"existing output is unreadable: {exc}") from exc
        if existing != encoded:
            raise SwarmDiffError("existing frozen output differs from requested output")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(output)
    return True


def build_orchestration_dispatch(value: object) -> dict[str, Any]:
    """Build deterministic JSON/Markdown dispatcher material from a directive core."""
    _require_subswarm_enabled()
    if isinstance(value, dict) and "directive_sha256" in value:
        directive = validate_orchestration_directive(value)
    else:
        directive = seal_orchestration_directive(value)
    core = {
        "schema_version": "lead-orchestration-dispatch/v1",
        "directive": directive,
        "brief_markdown": render_orchestration_directive(directive),
    }
    return {**core, "dispatch_sha256": sha256(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--member-result", action="append", type=Path)
    action.add_argument("--member-bundle", type=Path)
    action.add_argument("--seal-member-bundle", type=Path)
    action.add_argument("--build-orchestration-directive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--swarm-spec-sha256")
    parser.add_argument("--orchestration-directive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.build_orchestration_directive:
            raw = _load_json_object(
                args.build_orchestration_directive, "orchestration directive"
            )
            result = build_orchestration_dispatch(raw)
            created = _freeze_json_output(args.output, result)
        elif args.seal_member_bundle:
            if not args.taxonomy or not args.orchestration_directive:
                parser.error(
                    "--seal-member-bundle requires --taxonomy and --orchestration-directive"
                )
            raw_bundle = _load_json_object(args.seal_member_bundle, "raw member bundle")
            directive = _load_json_object(
                args.orchestration_directive, "orchestration directive"
            )
            result = seal_member_bundle(
                raw_bundle, load_taxonomy(args.taxonomy), directive
            )
            created = _freeze_json_output(args.output, result)
        elif args.member_bundle:
            if not args.taxonomy or not args.orchestration_directive:
                parser.error(
                    "--member-bundle requires --taxonomy and --orchestration-directive"
                )
            bundle = _load_json_object(args.member_bundle, "member bundle")
            directive = _load_json_object(
                args.orchestration_directive, "orchestration directive"
            )
            result = decompose_review_subjects(
                bundle, load_taxonomy(args.taxonomy), directive
            )
            created = _freeze_json_output(args.output, result)
        else:
            if not args.taxonomy or not args.swarm_spec_sha256:
                parser.error(
                    "--member-result requires --taxonomy and --swarm-spec-sha256"
                )
            result, created = freeze_diff(
                args.output,
                args.member_result or [],
                args.taxonomy,
                args.swarm_spec_sha256,
            )
    except SwarmDiffError as exc:
        print(f"swarm-diff: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"created": created, "diff": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
