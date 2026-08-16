#!/usr/bin/env python3
"""Load and render the versioned specialist-by-lane capability source."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, NamedTuple


SOURCE_RELATIVE = Path("model-lanes/specialist-lane-capabilities.v1.json")
SOURCE_SCHEMA = "specialist-lane-capabilities/v1"
SURFACE_SCHEMA = "capability-surface/v1"
CAPABILITY_FIELDS = ("skills", "tools", "mcps")
LANES = ("gpt-codex", "claude", "gemini", "kimi")
# Availability states, with their semantics. The single most damaging legacy
# defect was one undifferentiated ``uninstalled`` bucket that conflated "not yet
# installed", "unwritten markdown stub", "Python stdlib", "OS-impossible", and
# "dead/superseded tool" — so a Linux-only kernel tool and a 25-word skill stub
# shared a label and an install could never be reasoned about. The five typed
# states below (added 2026-07-26, Wave 1 registry-accuracy pass) give each of
# those a distinct, honest home. See ``AVAILABILITY_SEMANTICS`` for the
# authoritative per-state meaning and usability; ``shared/api-catalog.md`` §0
# documents the same vocabulary for human readers.
#
# "Usable" means usable-as-live: it is projected into the derived per-lane
# adapters and the runtime-map tool summary, and it must survive the live
# existence gate in ``validate_capability_homes``. Every non-usable state is
# tracked (it stays in the source and lands in the generated index's
# ``known_unavailable``) but is never projected as a live capability.
AVAILABILITY_SEMANTICS = {
    # state: (usable, one-line meaning)
    "available": (True, "live on this lane; existence-proven (inventory/registry/catalog/PATH)"),
    "installed-skill-root": (True, "skill present in an installed skill root (skills only)"),
    "mcp-operation": (False, "an MCP tool operation; projectable via its provider, not usable alone"),
    "harness-only": (False, "a harness capability gated behind a runtime-map approval"),
    "pending-restart-activation": (False, "staged MCP awaiting a lane restart before it can connect"),
    "probe-failed": (False, "a real liveness probe failed; not usable until re-probed"),
    "uninstalled": (False, "genuinely not present on this lane and installable in principle"),
    # --- Wave 1 (2026-07-26) typed replacements for the old catch-all ---
    "authored:stub": (False, "a real markdown skill file exists but is a status:stub draft; not invokable until authored"),
    "needs-operator-install": (False, "installable only by an explicit operator action (large/GUI/licensed/credentialed install)"),
    "platform-unavailable": (False, "OS-impossible on this host (e.g. a Linux-only tool on darwin); can never be installed here"),
    "project-dependency": (False, "a language/stdlib/manifest dependency resolved inside a target project's runtime, not a squad host tool"),
    "superseded": (False, "a dead or duplicated tool that should not be installed; a live capability already covers it"),
}
AVAILABILITY_STATES = tuple(AVAILABILITY_SEMANTICS)
USABLE_AVAILABILITY_STATES = frozenset(
    state for state, (usable, _meaning) in AVAILABILITY_SEMANTICS.items() if usable
)
REQUIREMENT_LEVELS = ("preferred", "required")
COVERAGE_LEVELS = ("full", "partial")
EVIDENCE_KINDS = {
    "chrono-dedup",
    "chrono-media-studio",
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
    # Guarded security MCPs (mcp-context-protector children) are proven by a
    # verified shared-registry record rather than the lane inventory, because
    # `model-lanes/lane-capabilities.tsv` still lists them under
    # `staged_mcp_surface`. Distinct from `verified-registry:claude-mcp`
    # because the guarded trio is declared on both the claude and codex lanes.
    "verified-registry:guarded-mcp",
    # --- Wave 1 (2026-07-26) evidence kinds for the typed availability states ---
    # The old `host-PATH:absent` evidence was applied to skills too, which was a
    # category error: markdown skills are never on the shell PATH. These kinds
    # give each typed state an honest basis (see AVAILABILITY_SEMANTICS).
    "shared-skills:stub",        # authored:stub — a status:stub file exists in shared/skills/
    "platform-incompatible",     # platform-unavailable — OS-impossible on this host
    "project-dependency",        # project-dependency — stdlib/crate/manifest dep, not a host tool
    "superseded",                # superseded — dead/duplicated; a live capability covers it
    "operator-install-required", # needs-operator-install — only an operator can install it
    "lane-not-wired",            # uninstalled — capability is live on another lane but not projected here
    "pending-reprobe",           # uninstalled/probe-failed — prior probe is stale; awaiting a fresh probe
    # --- Wave 3 (2026-07-26) invocation-contract evidence ---
    # `host-PATH` means "a binary of this capability's id spelling answers on the
    # shell PATH". Two Wave 3 capability classes are genuinely installed and
    # genuinely usable but would be *mislabelled* by `host-PATH`, which is the
    # same class of dishonest evidence Wave 1 removed. Each therefore carries an
    # invocation contract instead: the evidence kind names the only interface
    # through which the capability can actually be reached. The paired
    # `shared/api-catalog.md` §12 entry carries the literal command.
    "repo-venv-interpreter",     # available — a Python library importable ONLY via the repo's
                                 # own `<repo>/.venv/bin/python`; host `python3` cannot import it
                                 # and no binary of the id's name exists on PATH
    "host-app-bundle",           # available — installed as a macOS `.app` bundle with no
                                 # PATH-resolvable binary of the id's name; launched via `open -a`
}


class CapabilitySourceError(RuntimeError):
    """Raised when the authored capability source is invalid."""


class CapabilityRef(NamedTuple):
    identifier: str
    requirement: str
    availability: str
    evidence: str
    provided_by: str = ""


def is_usable_capability(kind: str, availability: str) -> bool:
    """Return whether availability evidence makes this capability usable."""
    return availability in USABLE_AVAILABILITY_STATES and (
        availability == "available"
        or (availability == "installed-skill-root" and kind == "skills")
    )


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
    raw_servers = payload.get("servers", [])
    if not isinstance(raw_servers, list):
        raise CapabilitySourceError("capability source servers must be a list")
    servers: dict[str, frozenset[str]] = {}
    server_order: list[str] = []
    for raw_server in raw_servers:
        if not isinstance(raw_server, dict):
            raise CapabilitySourceError("capability source server must be an object")
        server_id = raw_server.get("id")
        if not isinstance(server_id, str) or not server_id:
            raise CapabilitySourceError("capability source server has invalid id")
        provides = _string_list(
            raw_server.get("provides", []), f"server {server_id}.provides"
        )
        if list(provides) != sorted(provides, key=str.casefold):
            raise CapabilitySourceError(f"server {server_id}.provides must be sorted")
        if server_id in servers:
            raise CapabilitySourceError(f"duplicate capability server {server_id}")
        servers[server_id] = frozenset(provides)
        server_order.append(server_id)
    if server_order != sorted(server_order, key=str.casefold):
        raise CapabilitySourceError("capability source servers must be sorted by id")
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
                provided_by = item.get("provided_by", "")
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
                if not is_usable_capability(kind, availability) and requirement != "preferred":
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
                if not isinstance(provided_by, str):
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: provided_by must be a string"
                    )
                if provided_by and kind != "tools":
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: only tools may declare provided_by"
                    )
                if availability == "mcp-operation" and not provided_by:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: MCP operation requires provided_by"
                    )
                if provided_by and (
                    provided_by not in servers
                    or identifier not in servers[provided_by]
                ):
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: provided_by relation is not reciprocal"
                    )
                if availability == "mcp-operation" and evidence != provided_by:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: MCP operation evidence/provider mismatch"
                    )
                if evidence not in EVIDENCE_KINDS:
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: unknown evidence kind {evidence!r}"
                    )
                if availability == "installed-skill-root" and (
                    kind != "skills" or evidence != "installed-skill-root"
                ):
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: installed-skill-root "
                        "availability requires installed skill evidence"
                    )
                # A stub is, by definition, an unfinished markdown skill file;
                # it is meaningless for a tool or MCP. Pin it to skills + the
                # matching evidence so the honest state cannot drift onto a CLI.
                if availability == "authored:stub" and (
                    kind != "skills" or evidence != "shared-skills:stub"
                ):
                    raise CapabilitySourceError(
                        f"{specialist}:{lane}:{identifier}: authored:stub "
                        "availability requires a skills entry with shared-skills:stub evidence"
                    )
                found.append(
                    CapabilityRef(
                        identifier,
                        requirement,
                        availability,
                        evidence,
                        provided_by,
                    )
                )
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
        assigned_mcps = {
            item.identifier: item
            for item in parsed["mcps"]
            if is_usable_capability("mcps", item.availability)
        }
        for operation in parsed["tools"]:
            if operation.provided_by and operation.provided_by not in assigned_mcps:
                raise CapabilitySourceError(
                    f"{specialist}:{lane}:{operation.identifier}: "
                    f"provider {operation.provided_by!r} lacks a usable MCP assignment"
                )
            if (
                operation.provided_by
                and operation.requirement == "required"
                and assigned_mcps[operation.provided_by].requirement != "required"
            ):
                raise CapabilitySourceError(
                    f"{specialist}:{lane}:{operation.identifier}: "
                    "required operation needs a required provider assignment"
                )
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
            if is_usable_capability(kind, item.availability)
        }
        result[kind] = tuple(sorted(values, key=str.casefold))
    return result


def role_surface_payload(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical, executable capability surface for one role lane."""
    usable = {
        kind: sorted(
            {
                ref.identifier
                for ref in entry.get(kind, ())
                if is_usable_capability(kind, ref.availability)
            },
            key=str.casefold,
        )
        for kind in CAPABILITY_FIELDS
    }
    direct_mcps = [item for item in usable["mcps"] if not item.startswith("lead:")]
    brokered_mcps = sorted(
        (item.removeprefix("lead:") for item in usable["mcps"] if item.startswith("lead:")),
        key=str.casefold,
    )
    return {
        "schema": SURFACE_SCHEMA,
        "lane": entry["lane"],
        "skills": usable["skills"],
        "tools": usable["tools"],
        "mcps": direct_mcps,
        "brokered_mcps": brokered_mcps,
    }


def role_surface_sha256(entry: dict[str, Any]) -> str:
    """Hash one canonical role surface without descriptive source metadata."""
    canonical = json.dumps(
        role_surface_payload(entry),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


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
