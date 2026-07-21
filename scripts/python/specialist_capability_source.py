#!/usr/bin/env python3
"""Load and render the versioned specialist-by-lane capability source."""

from __future__ import annotations

import hashlib
import json
import os
import csv
from pathlib import Path
import tempfile
from typing import Any, NamedTuple


SOURCE_RELATIVE = Path("model-lanes/specialist-lane-capabilities.v1.json")
SOURCE_SCHEMA = "specialist-lane-capabilities/v1"
CAPABILITY_FIELDS = ("skills", "tools", "mcps")
LANES = ("gpt-codex", "claude", "gemini", "kimi")
AVAILABILITY_STATES = (
    "available",
    "harness-only",
    "mcp-operation",
    "pending-restart-activation",
    "probe-failed",
    "uninstalled",
)
REQUIREMENT_LEVELS = ("preferred", "required")
COVERAGE_LEVELS = ("full", "partial")
EVIDENCE_KINDS = {
    "chrono-research-arsenal",
    "claude-plugin:legacy-manifest",
    "host-PATH",
    "host-PATH:absent",
    "installed-or-shared-authored",
    "installed-skill-root",
    "lane-inventory",
    "runtime-map:requires_approval",
    "shared-registry:authored",
    "staged-lane-config:validate-staged",
    "verified-registry:claude-mcp",
}


class CapabilitySourceError(RuntimeError):
    """Raised when the authored capability source is invalid."""


class CapabilityRef(NamedTuple):
    identifier: str
    requirement: str
    availability: str
    evidence: str


class PrimaryRequirement(NamedTuple):
    identifier: str
    kind: str
    resolution: str
    capability_id: str
    provider_lane: str
    evidence: str


def source_path(root: Path, override: Path | None = None) -> Path:
    return override or root / SOURCE_RELATIVE


def source_sha256(root: Path, override: Path | None = None) -> str:
    return hashlib.sha256(source_path(root, override).read_bytes()).hexdigest()


def _string_list(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise CapabilitySourceError(f"{label} must be a list of non-empty strings")
    if len(raw) != len(set(raw)):
        raise CapabilitySourceError(f"{label} contains duplicates")
    return tuple(raw)


def load_source(
    root: Path, override: Path | None = None
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    path = source_path(root, override)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilitySourceError(f"cannot load capability source {path}: {exc}") from exc
    if payload.get("schema") != SOURCE_SCHEMA or payload.get("version") != 1:
        raise CapabilitySourceError("capability source schema/version mismatch")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise CapabilitySourceError("capability source entries must be a list")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    seen_order: list[tuple[str, str]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise CapabilitySourceError("capability source entry must be an object")
        specialist = raw.get("specialist")
        lane = raw.get("lane")
        coverage = raw.get("coverage")
        if not isinstance(specialist, str) or not specialist:
            raise CapabilitySourceError("capability source entry has invalid specialist")
        if lane not in LANES:
            raise CapabilitySourceError(f"{specialist}: invalid lane {lane!r}")
        if coverage not in COVERAGE_LEVELS:
            raise CapabilitySourceError(
                f"{specialist}:{lane}: invalid coverage {coverage!r}"
            )
        key = (specialist, lane)
        if key in result:
            raise CapabilitySourceError(f"duplicate capability source entry {specialist}:{lane}")
        limitations = _string_list(raw.get("limitations", []), f"{specialist}:{lane}.limitations")
        if coverage == "partial" and not limitations:
            raise CapabilitySourceError(
                f"{specialist}:{lane}: partial coverage requires an explicit limitation"
            )
        parsed: dict[str, tuple[CapabilityRef, ...]] = {}
        for kind in CAPABILITY_FIELDS:
            refs = raw.get(kind, [])
            if not isinstance(refs, list):
                raise CapabilitySourceError(f"{specialist}:{lane}.{kind} must be a list")
            found: list[CapabilityRef] = []
            for item in refs:
                if not isinstance(item, dict):
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}.{kind} entry must be an object"
                    )
                identifier = item.get("id")
                requirement = item.get("requirement")
                availability = item.get("availability")
                evidence = item.get("evidence")
                if not isinstance(identifier, str) or not identifier:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}.{kind} entry has invalid id"
                    )
                if requirement not in REQUIREMENT_LEVELS:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: invalid requirement"
                    )
                if availability not in AVAILABILITY_STATES:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: invalid availability"
                    )
                if availability != "available" and requirement != "preferred":
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: unavailable capability must be preferred"
                    )
                if availability == "pending-restart-activation" and kind != "mcps":
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: pending-restart capability must be an MCP"
                    )
                if not isinstance(evidence, str) or not evidence:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: evidence is required"
                    )
                if evidence not in EVIDENCE_KINDS:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: unknown evidence kind {evidence!r}"
                    )
                found.append(CapabilityRef(identifier, requirement, availability, evidence))
            identifiers = [item.identifier for item in found]
            if identifiers != sorted(identifiers, key=str.casefold):
                raise CapabilitySourceError(
                    f"{specialist}:{lane}.{kind} must be sorted by id"
                )
            if len(identifiers) != len(set(identifiers)):
                raise CapabilitySourceError(
                    f"{specialist}:{lane}.{kind} contains duplicate ids"
                )
            parsed[kind] = tuple(found)
        result[key] = {
            "specialist": specialist,
            "lane": lane,
            "coverage": coverage,
            "limitations": limitations,
            **parsed,
        }
        seen_order.append(key)
    if seen_order != sorted(seen_order):
        raise CapabilitySourceError("capability source entries must be specialist/lane sorted")
    policy = payload.get("primary_requirement_policy")
    if not isinstance(policy, dict):
        raise CapabilitySourceError("primary_requirement_policy must be an object")
    default = policy.get("default")
    overrides = policy.get("overrides")
    if not isinstance(default, dict) or not isinstance(overrides, dict):
        raise CapabilitySourceError("primary requirement default/overrides must be objects")
    default_ids = set(_string_list(default.get("ids", []), "primary_requirement_policy.default.ids"))
    default_prefixes = _string_list(default.get("prefixes", []), "primary_requirement_policy.default.prefixes")
    if default.get("kind") not in CAPABILITY_FIELDS or default.get("provider_lane") != "primary":
        raise CapabilitySourceError("primary requirement default must be a primary-lane capability kind")
    runtime_path = root / "shared/specialist-runtime-map.tsv"
    try:
        with runtime_path.open(encoding="utf-8", newline="") as handle:
            runtime = list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise CapabilitySourceError(f"cannot read primary requirements {runtime_path}: {exc}") from exc
    primary_keys: set[tuple[str, str]] = set()
    for row in runtime:
        specialist = row.get("specialist", "")
        lane = "gpt-codex" if row.get("primary_lane") == "codex" else row.get("primary_lane", "")
        key = (specialist, lane)
        if key not in result or result[key]["coverage"] != "full":
            raise CapabilitySourceError(f"{specialist}:{lane}: primary plan lacks full source coverage")
        primary_keys.add(key)
        raw_required = (row.get("required_tools") or "").strip()
        if not raw_required or raw_required == "[]":
            identifiers: tuple[str, ...] = ()
        elif raw_required.startswith("[") and raw_required.endswith("]"):
            identifiers = tuple(item.strip() for item in raw_required[1:-1].split(",") if item.strip())
        else:
            raise CapabilitySourceError(f"{specialist}: invalid required_tools list")
        requirements: list[PrimaryRequirement] = []
        for identifier in identifiers:
            rule = overrides.get(identifier)
            if rule is None:
                if identifier not in default_ids and not any(identifier.startswith(prefix) for prefix in default_prefixes):
                    raise CapabilitySourceError(f"{specialist}:{identifier}: no typed primary requirement rule")
                rule = default
            if not isinstance(rule, dict) or rule.get("kind") not in CAPABILITY_FIELDS:
                raise CapabilitySourceError(f"{specialist}:{identifier}: invalid primary requirement kind")
            provider = rule.get("provider_lane")
            provider_lane = lane if provider == "primary" else provider
            if provider_lane not in LANES:
                raise CapabilitySourceError(f"{specialist}:{identifier}: invalid provider lane")
            capability_id = rule.get("capability_id", identifier)
            if not isinstance(capability_id, str) or not capability_id:
                raise CapabilitySourceError(f"{specialist}:{identifier}: invalid capability id")
            if lane == "kimi" and provider_lane == lane and rule["kind"] == "mcps":
                capability_id = str(policy.get("kimi_mcp_prefix", "")) + capability_id
            requirements.append(
                PrimaryRequirement(
                    identifier,
                    rule["kind"],
                    "local" if provider_lane == lane else "handoff",
                    capability_id,
                    provider_lane,
                    "primary_requirement_policy+lane_registry",
                )
            )
        result[key]["primary_requirements"] = tuple(requirements)
    if primary_keys != {key for key, entry in result.items() if entry["coverage"] == "full"}:
        raise CapabilitySourceError("full source entries must match runtime-map primary plans exactly")
    return result, payload


def available_arrays(
    entries: dict[tuple[str, str], dict[str, Any]], specialist: str, lane: str
) -> dict[str, tuple[str, ...]]:
    entry = entries.get((specialist, lane), {})
    result: dict[str, tuple[str, ...]] = {}
    for kind in CAPABILITY_FIELDS:
        values = {
            item.identifier
            for item in entry.get(kind, ())
            if item.availability == "available"
        }
        values.update(
            item.capability_id
            for item in entry.get("primary_requirements", ())
            if item.kind == kind and item.resolution == "local"
        )
        result[kind] = tuple(sorted(values, key=str.casefold))
    return result


def tracked_arrays(
    entries: dict[tuple[str, str], dict[str, Any]], specialist: str, lane: str
) -> dict[str, tuple[str, ...]]:
    entry = entries.get((specialist, lane), {})
    return {
        kind: tuple(item.identifier for item in entry.get(kind, ()))
        for kind in CAPABILITY_FIELDS
    }


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), separators=(",", ":"), ensure_ascii=False)


def toml_capability_lines(
    root: Path,
    entries: dict[tuple[str, str], dict[str, Any]],
    specialist: str,
    lane: str,
) -> str:
    if (specialist, lane) not in entries:
        return ""
    arrays = available_arrays(entries, specialist, lane)
    lines = [
        f'capability_source = "{SOURCE_RELATIVE.as_posix()}"',
        f'capability_source_sha256 = "{source_sha256(root)}"',
    ]
    lines.extend(
        f"{kind} = {_json_array(arrays[kind])}"
        for kind in CAPABILITY_FIELDS
        if arrays[kind]
    )
    return "\n".join(lines) + "\n"


def markdown_capability_lines(
    root: Path,
    entries: dict[tuple[str, str], dict[str, Any]],
    specialist: str,
    lane: str,
    *,
    include_arrays: bool = True,
) -> str:
    if (specialist, lane) not in entries:
        return ""
    arrays = available_arrays(entries, specialist, lane)
    lines = [
        f"capability_source: {SOURCE_RELATIVE.as_posix()}",
        f"capability_source_sha256: {source_sha256(root)}",
    ]
    if include_arrays:
        lines.extend(
            f"{kind}: {_json_array(arrays[kind])}"
            for kind in CAPABILITY_FIELDS
            if arrays[kind]
        )
    return "\n".join(lines) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Write one shared artifact with temp + fsync + rename + directory fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_name, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
