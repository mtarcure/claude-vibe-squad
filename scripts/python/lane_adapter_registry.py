#!/usr/bin/env python3
"""Render and validate thin specialist adapters against one lane capability registry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from specialist_capability_source import (
    CapabilitySourceError,
    SOURCE_RELATIVE,
    available_arrays,
    load_source,
    source_sha256,
)


CAPABILITY_HEADER = (
    "lane",
    "cli",
    "adapter_format",
    "adapter_tools",
    "mcp_surface",
    "staged_mcp_surface",
    "skills",
    "child_mcp_policy",
    "grounding",
    "auth_policy",
    "probe_receipt",
    "version",
)
ROUTE_FIELDS = (
    "primary_lane",
    "backup_lane",
    "escalate_lane",
    "review_lane",
    "throughput_lane",
)
GEMINI_GENERATED_ROLES = (
    "asset-provenance-and-rights-auditor",
    "brand-voice",
    "content-verifier",
    "editor",
    "frontend-engineer",
    "game-designer",
    "interactive-audio-designer",
    "learning-coach",
    "level-narrative-designer",
    "localization-specialist",
    "research",
    "scout",
    "technical-artist",
    "ui-engineer",
)
CODEX_GENERATED_ROLES = ("code-reviewer", "impact-validator")
KIMI_GENERATED_ROLES = ("data-extraction-engineer",)
SWARM_CRITICAL_ROLES = (
    "exploit-developer",
    "security-analyst",
    "skeptic",
    "experimental-attacker",
    "impact-validator",
    "code-reviewer",
)
GENERATED_MARKER = "lane-capability-registry/v1"
PROJECTION_BEGIN = "BEGIN SPECIALIST CAPABILITY PROJECTION"
PROJECTION_END = "END SPECIALIST CAPABILITY PROJECTION"


class AdapterValidationError(RuntimeError):
    pass


class CapabilityRow(NamedTuple):
    lane: str
    cli: str
    adapter_format: str
    adapter_tools: tuple[str, ...]
    mcp_surface: tuple[str, ...]
    staged_mcp_surface: tuple[str, ...]
    skills: tuple[str, ...]
    child_mcp_policy: str
    grounding: str
    auth_policy: str
    probe_receipt: str
    version: str


def _json_tuple(value: str, field: str, lane: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AdapterValidationError(f"invalid {field} JSON for lane {lane}: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise AdapterValidationError(f"{field} for lane {lane} must be a JSON string list")
    if len(parsed) != len(set(parsed)):
        raise AdapterValidationError(f"{field} for lane {lane} contains duplicates")
    return tuple(parsed)


def load_capability_registry(path: str | Path) -> dict[str, CapabilityRow]:
    registry_path = Path(path)
    with registry_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != CAPABILITY_HEADER:
            raise AdapterValidationError("lane capability registry header mismatch")
        result: dict[str, CapabilityRow] = {}
        for raw in reader:
            lane = raw["lane"]
            if lane in result:
                raise AdapterValidationError(f"duplicate lane capability row: {lane}")
            if lane not in {"gpt-codex", "claude", "gemini", "kimi"}:
                raise AdapterValidationError(f"unknown lane capability row: {lane}")
            if not raw["probe_receipt"]:
                raise AdapterValidationError(f"lane {lane} is missing a probe receipt")
            result[lane] = CapabilityRow(
                lane=lane,
                cli=raw["cli"],
                adapter_format=raw["adapter_format"],
                adapter_tools=_json_tuple(raw["adapter_tools"], "adapter_tools", lane),
                mcp_surface=_json_tuple(raw["mcp_surface"], "mcp_surface", lane),
                staged_mcp_surface=_json_tuple(
                    raw["staged_mcp_surface"], "staged_mcp_surface", lane
                ),
                skills=_json_tuple(raw["skills"], "skills", lane),
                child_mcp_policy=raw["child_mcp_policy"],
                grounding=raw["grounding"],
                auth_policy=raw["auth_policy"],
                probe_receipt=raw["probe_receipt"],
                version=raw["version"],
            )
    if set(result) != {"gpt-codex", "claude", "gemini", "kimi"}:
        raise AdapterValidationError("lane capability registry must contain exactly four lanes")
    return result


def _runtime_rows(repo_root: Path) -> dict[str, dict[str, str]]:
    path = repo_root / "shared" / "specialist-runtime-map.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result = {row["specialist"]: row for row in rows}
    if len(result) != len(rows):
        raise AdapterValidationError("runtime map contains duplicate specialists")
    return result


def canonical_brief(row: dict[str, str]) -> Path:
    if row["source_namespace"] == "shared":
        return Path("shared") / "specialists" / f"{row['specialist']}.md"
    return Path("departments") / row["source_namespace"] / "specialists" / f"{row['specialist']}.md"


def _registry_sha(repo_root: Path) -> str:
    return hashlib.sha256(
        (repo_root / "model-lanes" / "lane-capabilities.tsv").read_bytes()
    ).hexdigest()


def capability_projection(repo_root: str | Path, lane: str, specialist: str) -> str:
    root = Path(repo_root)
    entries, _payload = load_source(root)
    arrays = available_arrays(entries, specialist, lane)
    source_hash = source_sha256(root)
    assignment = " = " if lane == "gpt-codex" else ": "
    role_prefix = "capability_" if lane == "gemini" else ""
    lines = [
        f"# {PROJECTION_BEGIN}",
        f"capability_source{assignment}{json.dumps(SOURCE_RELATIVE.as_posix()) if lane == 'gpt-codex' else SOURCE_RELATIVE.as_posix()}",
        f"capability_source_sha256{assignment}{json.dumps(source_hash) if lane == 'gpt-codex' else source_hash}",
    ]
    for field in ("skills", "tools", "mcps"):
        if arrays[field]:
            lines.append(
                f"{role_prefix}{field}{assignment}{json.dumps(list(arrays[field]), separators=(',', ':'))}"
            )
    lines.append(f"# {PROJECTION_END}")
    return "\n".join(lines) + "\n"


def upsert_capability_projection(
    repo_root: str | Path,
    lane: str,
    specialist: str,
    existing: str,
) -> str:
    """Replace only the generated capability block and preserve adapter policy/prose."""
    projection = capability_projection(repo_root, lane, specialist)
    lines = existing.splitlines(keepends=True)
    begin = next((i for i, line in enumerate(lines) if PROJECTION_BEGIN in line), None)
    end = next((i for i, line in enumerate(lines) if PROJECTION_END in line), None)
    replacement = projection.splitlines(keepends=True)
    if begin is not None or end is not None:
        if begin is None or end is None or end < begin:
            raise AdapterValidationError(f"{specialist}: malformed capability projection sentinel")
        return "".join(lines[:begin] + replacement + lines[end + 1 :])

    legacy = {"capability_source", "capability_source_sha256"}
    if lane == "gemini":
        legacy.update(f"capability_{field}" for field in ("skills", "tools", "mcps"))
    else:
        legacy.update(("skills", "tools", "mcps"))
    filtered = [
        line
        for line in lines
        if not any(re.match(rf"^{re.escape(key)}\s*[:=]", line) for key in legacy)
    ]
    if lane in {"claude", "gemini"}:
        closing = next((i for i in range(1, len(filtered)) if filtered[i].strip() == "---"), None)
        if closing is None:
            raise AdapterValidationError(f"{specialist}: Markdown adapter lacks closing frontmatter")
        filtered[closing:closing] = replacement
    elif lane == "gpt-codex":
        insertion = next((i for i, line in enumerate(filtered) if line.startswith("developer_instructions")), len(filtered))
        filtered[insertion:insertion] = replacement
    else:
        insertion = next((i for i, line in enumerate(filtered) if line.startswith("agent:")), len(filtered))
        filtered[insertion:insertion] = replacement
    return "".join(filtered)


def render_adapter(repo_root: str | Path, lane: str, specialist: str) -> str:
    root = Path(repo_root)
    rows = _runtime_rows(root)
    row = rows.get(specialist)
    if row is None:
        raise AdapterValidationError(f"unknown specialist: {specialist}")
    registry = load_capability_registry(root / "model-lanes" / "lane-capabilities.tsv")
    capability = registry[lane]
    brief = canonical_brief(row).as_posix()
    registry_sha = _registry_sha(root)
    source_entries, _source_payload = load_source(root)
    source_hash = source_sha256(root)
    role_capabilities = available_arrays(source_entries, specialist, lane)
    projection = capability_projection(root, lane, specialist)
    marker = f"generated_by={GENERATED_MARKER} registry_sha256={registry_sha}"
    if lane == "gpt-codex":
        return (
            f"# {marker}\n"
            f'name = "{specialist.replace("-", "_")}\"\n'
            f'description = "Thin Codex adapter for {specialist}; canonical brief is authoritative.\"\n'
            'model_reasoning_effort = "high"\n'
            'sandbox_mode = "workspace-write"\n'
            f"{projection}"
            'developer_instructions = """\n'
            f"You are the `{specialist}` specialist in the `gpt-codex` lane.\n\n"
            f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
            "Lane capability profile is `gpt-codex` from `model-lanes/lane-capabilities.tsv`. "
            "This adapter declares no native tool allowlist; verify the runtime-discovered tool and MCP surface before use. "
            "A registry capability is a ceiling, not task authorization.\n\n"
            "Execute only the assigned packet, remain read-only unless its write scope explicitly permits changes, and preserve every operator gate.\n"
            '"""\n'
        )
    if lane == "gemini":
        tools = json.dumps(list(capability.adapter_tools), separators=(",", ":"))
        gemini_role_lines = "".join(
            f"capability_{field}: {json.dumps(list(role_capabilities[field]), separators=(',', ':'))}\n"
            for field in ("skills", "tools", "mcps")
            if role_capabilities[field]
        )
        return (
            "---\n"
            f"name: {specialist}\n"
            f'description: "Thin Gemini adapter for {specialist}; canonical brief is authoritative."\n'
            "kind: local\n"
            f"tools: {tools}\n"
            "model: inherit\n"
            "max_turns: 30\n"
            f"generated_by: {GENERATED_MARKER}\n"
            f"capability_registry_sha256: {registry_sha}\n"
            f"# {PROJECTION_BEGIN}\n"
            f"capability_source: {SOURCE_RELATIVE.as_posix()}\n"
            f"capability_source_sha256: {source_hash}\n"
            f"{gemini_role_lines}"
            f"# {PROJECTION_END}\n"
            "---\n\n"
            f"# Specialist Adapter: {specialist}\n\n"
            f"You are the `{specialist}` specialist in the `gemini` lane.\n\n"
            f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
            "Lane capability profile is `gemini` from `model-lanes/lane-capabilities.tsv`. "
            "The frontmatter tool list is the complete adapter-native allowlist. Google Search grounding and configured child MCPs "
            "must be verified in the current runtime before use; availability never grants spend or external-action authority.\n\n"
            "Execute only the assigned packet, stay inside write scope, and preserve every operator gate.\n"
        )
    if lane == "claude":
        return (
            "---\n"
            f"name: {specialist}\n"
            f'description: "Thin Claude adapter for {specialist}; canonical brief is authoritative."\n'
            "model: inherit\n"
            f"generated_by: {GENERATED_MARKER}\n"
            f"capability_registry_sha256: {registry_sha}\n"
            f"{projection}"
            "---\n\n"
            f"# Specialist Adapter: {specialist}\n\n"
            f"You are the `{specialist}` specialist in the `claude` lane.\n\n"
            f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
            "Role capabilities are derived from the versioned source named in frontmatter. Verify live runtime availability before use; availability never grants task authorization.\n\n"
            "Execute only the assigned packet, stay inside write scope, and preserve every operator gate.\n"
        )
    if lane == "kimi":
        return (
            f"# {marker}\n"
            "version: 1\n"
            f"{projection}"
            "agent:\n"
            f"  name: {specialist}\n"
            "  extend: default\n"
            f'  description: "Thin Kimi adapter for {specialist}; canonical brief is authoritative."\n'
            f"  system_prompt_path: ../prompts/{specialist}.md\n"
            "  model: kimi-code/kimi-for-coding-highspeed\n"
        )
    raise AdapterValidationError(f"generation is not enabled for lane {lane}")


def render_kimi_prompt(repo_root: str | Path, specialist: str) -> str:
    root = Path(repo_root)
    row = _runtime_rows(root).get(specialist)
    if row is None:
        raise AdapterValidationError(f"unknown specialist: {specialist}")
    brief = canonical_brief(row).as_posix()
    registry_sha = _registry_sha(root)
    return (
        f"<!-- generated_by={GENERATED_MARKER} registry_sha256={registry_sha} -->\n"
        f"# Specialist Adapter: {specialist}\n\n"
        f"You are the `{specialist}` specialist in the `kimi` lane only through its ranked route.\n\n"
        f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
        "Lane capability profile is `kimi` from `model-lanes/lane-capabilities.tsv`. MCP tools are unavailable inside Kimi "
        "subagents. Work only from a frozen, provenance-bearing corpus supplied by the main Kimi lane; return any MCP or external "
        "retrieval need to the lead as `subagent_mcp_gap` and never pretend the tool ran.\n\n"
        "Execute only the assigned packet, stay inside write scope, and preserve every operator gate.\n"
    )


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", text)
    return match.group(1).strip() if match else ""


def validate_adapter_file(
    repo_root: str | Path,
    lane: str,
    adapter_path: str | Path,
    capability: CapabilityRow | None = None,
) -> None:
    root = Path(repo_root)
    path = Path(adapter_path)
    text = path.read_text(encoding="utf-8")
    specialist = path.stem
    rows = _runtime_rows(root)
    row = rows.get(specialist)
    if row is None:
        raise AdapterValidationError(f"adapter has unknown specialist identity: {specialist}")
    if capability is None:
        capability = load_capability_registry(
            root / "model-lanes" / "lane-capabilities.tsv"
        )[lane]
    brief = canonical_brief(row).as_posix()
    source_entries, _source_payload = load_source(root)
    source_hash = source_sha256(root)
    source_entry = source_entries.get((specialist, lane))
    capability_bearing = bool(
        source_entry
        and (
            any(source_entry[field] for field in ("skills", "tools", "mcps"))
            or source_entry.get("primary_requirements")
        )
    )
    if lane == "gemini":
        if _frontmatter_value(text, "name") != specialist:
            raise AdapterValidationError(f"Gemini adapter identity mismatch: {specialist}")
        raw_tools = _frontmatter_value(text, "tools")
        try:
            declared = json.loads(raw_tools)
        except json.JSONDecodeError as exc:
            raise AdapterValidationError(f"invalid Gemini tools declaration: {exc}") from exc
        allowed = set(capability.adapter_tools)
        if capability.grounding == "google-search-grounding":
            # Gemini exposes grounding as google_web_search in older native
            # adapters even though it is not part of the local edit-tool list.
            allowed.add("google_web_search")
        forbidden = sorted(set(declared) - allowed)
        if forbidden:
            raise AdapterValidationError(
                f"Gemini adapter {specialist} declares unavailable tool(s): {','.join(forbidden)}"
            )
        if brief not in text:
            raise AdapterValidationError(f"Gemini adapter {specialist} lacks canonical pointer {brief}")
        if capability_bearing and (
            _frontmatter_value(text, "capability_source") != SOURCE_RELATIVE.as_posix()
            or _frontmatter_value(text, "capability_source_sha256") != source_hash
        ):
            raise AdapterValidationError(f"Gemini adapter {specialist} has stale capability source metadata")
        expected_arrays = available_arrays(source_entries, specialist, lane)
        for field in ("skills", "tools", "mcps"):
            raw = _frontmatter_value(text, f"capability_{field}")
            actual = tuple(json.loads(raw)) if raw else ()
            if capability_bearing and actual != expected_arrays[field]:
                raise AdapterValidationError(f"Gemini adapter {specialist} has stale capability {field} projection")
        return
    if lane == "gpt-codex":
        data = tomllib.loads(text)
        expected = specialist.replace("-", "_")
        if data.get("name") != expected:
            raise AdapterValidationError(f"Codex adapter identity mismatch: {specialist}")
        if brief not in text:
            raise AdapterValidationError(f"Codex adapter {specialist} lacks canonical pointer {brief}")
        if capability_bearing and (data.get("capability_source") != SOURCE_RELATIVE.as_posix() or data.get("capability_source_sha256") != source_hash):
            raise AdapterValidationError(f"Codex adapter {specialist} has stale capability source metadata")
        expected_arrays = available_arrays(source_entries, specialist, lane)
        for field in ("skills", "tools", "mcps"):
            if capability_bearing and tuple(data.get(field, ())) != expected_arrays[field]:
                raise AdapterValidationError(f"Codex adapter {specialist} has stale {field} projection")
        return
    if lane == "claude":
        if _frontmatter_value(text, "name") != specialist:
            raise AdapterValidationError(f"Claude adapter identity mismatch: {specialist}")
        if brief not in text:
            raise AdapterValidationError(f"Claude adapter {specialist} lacks canonical pointer {brief}")
        if capability_bearing and (_frontmatter_value(text, "capability_source") != SOURCE_RELATIVE.as_posix() or _frontmatter_value(text, "capability_source_sha256") != source_hash):
            raise AdapterValidationError(f"Claude adapter {specialist} has stale capability source metadata")
        expected_arrays = available_arrays(source_entries, specialist, lane)
        for field in ("skills", "tools", "mcps"):
            raw = _frontmatter_value(text, field)
            actual = tuple(json.loads(raw)) if raw else ()
            if capability_bearing and actual != expected_arrays[field]:
                raise AdapterValidationError(f"Claude adapter {specialist} has stale {field} projection")
        return
    if lane == "kimi":
        if not re.search(rf"(?m)^\s{{2}}name:\s*{re.escape(specialist)}$", text):
            raise AdapterValidationError(f"Kimi adapter identity mismatch: {specialist}")
        pointer = _frontmatter_value(text, "  system_prompt_path")
        if not pointer:
            match = re.search(r"(?m)^\s{2}system_prompt_path:\s*(\S+)$", text)
            pointer = match.group(1) if match else ""
        target = (path.parent / pointer).resolve()
        if not target.is_file():
            raise AdapterValidationError(f"Kimi system prompt is missing: {target}")
        prompt = target.read_text(encoding="utf-8")
        if brief not in prompt and brief not in text:
            raise AdapterValidationError(f"Kimi adapter {specialist} lacks canonical pointer {brief}")
        if capability_bearing and (_frontmatter_value(text, "capability_source") != SOURCE_RELATIVE.as_posix() or _frontmatter_value(text, "capability_source_sha256") != source_hash):
            raise AdapterValidationError(f"Kimi adapter {specialist} has stale capability source metadata")
        expected_arrays = available_arrays(source_entries, specialist, lane)
        for field in ("skills", "tools", "mcps"):
            raw = _frontmatter_value(text, field)
            actual = tuple(json.loads(raw)) if raw else ()
            if capability_bearing and actual != expected_arrays[field]:
                raise AdapterValidationError(f"Kimi adapter {specialist} has stale {field} projection")
        # Native prompt adapters must state the lead-broker boundary. Older
        # direct canonical pointers contain no independent capability claim and
        # are therefore validated by identity/pointer only.
        if "../prompts/" in pointer and "MCP tools are unavailable inside Kimi subagents" not in prompt:
            raise AdapterValidationError(f"Kimi adapter {specialist} lacks lead-broker MCP policy")
        return
    raise AdapterValidationError(f"validation is not enabled for lane {lane}")


def _target(root: Path, lane: str, specialist: str) -> Path:
    if lane == "gpt-codex":
        return root / "model-lanes" / "gpt-codex" / ".codex" / "agents" / f"{specialist}.toml"
    if lane == "claude":
        return root / "model-lanes" / "claude" / ".claude" / "agents" / f"{specialist}.md"
    if lane == "gemini":
        return root / "model-lanes" / "gemini" / ".gemini" / "agents" / f"{specialist}.md"
    return root / "model-lanes" / "kimi" / ".kimi" / "agents" / f"{specialist}.yaml"


def _ranked_gaps(root: Path, lane: str, rows: dict[str, dict[str, str]]) -> list[str]:
    map_lane = "codex" if lane == "gpt-codex" else lane
    gaps = []
    for specialist, row in rows.items():
        if map_lane in {row[field] for field in ROUTE_FIELDS} and not _target(
            root, lane, specialist
        ).is_file():
            gaps.append(specialist)
    return sorted(gaps)


def repository_report(repo_root: str | Path) -> dict[str, object]:
    root = Path(repo_root)
    rows = _runtime_rows(root)
    mismatches: list[str] = []
    for lane, roles in (
        ("gemini", GEMINI_GENERATED_ROLES),
        ("gpt-codex", CODEX_GENERATED_ROLES),
        ("kimi", KIMI_GENERATED_ROLES),
    ):
        for role in roles:
            path = _target(root, lane, role)
            if not path.is_file():
                mismatches.append(f"missing:{lane}:{role}")
                continue
            try:
                text = path.read_text(encoding="utf-8")
                if upsert_capability_projection(root, lane, role, text) != text:
                    mismatches.append(f"projection:{lane}:{role}")
                    continue
                validate_adapter_file(root, lane, path)
            except AdapterValidationError as exc:
                mismatches.append(f"invalid:{lane}:{role}:{exc}")
    for role in KIMI_GENERATED_ROLES:
        prompt = root / "model-lanes" / "kimi" / ".kimi" / "prompts" / f"{role}.md"
        if not prompt.is_file() or prompt.read_text(encoding="utf-8") != render_kimi_prompt(
            root, role
        ):
            mismatches.append(f"prompt:kimi:{role}")
        main = (root / "model-lanes" / "kimi" / "main.yaml").read_text(encoding="utf-8")
        if not re.search(rf"(?m)^\s{{4}}{re.escape(role)}:$", main):
            mismatches.append(f"registration:kimi:{role}")
    physical_lanes: dict[str, list[str]] = {}
    for role in SWARM_CRITICAL_ROLES:
        valid_lanes: list[str] = []
        for lane in ("gpt-codex", "claude", "gemini", "kimi"):
            target = _target(root, lane, role)
            if not target.is_file():
                continue
            try:
                validate_adapter_file(root, lane, target)
            except (AdapterValidationError, OSError, tomllib.TOMLDecodeError):
                continue
            valid_lanes.append(lane)
        physical_lanes[role] = valid_lanes
    return {
        "schema": "lane-adapter-coverage/v1",
        "generated_mismatches": sorted(mismatches),
        "ranked_gaps": {
            "gemini": _ranked_gaps(root, "gemini", rows),
            "kimi": _ranked_gaps(root, "kimi", rows),
        },
        "physical_lanes": physical_lanes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--validate-adapter")
    parser.add_argument("--lane", choices=("gpt-codex", "claude", "gemini", "kimi"))
    args = parser.parse_args(argv)
    try:
        if args.validate_adapter:
            if not args.lane:
                raise AdapterValidationError("--validate-adapter requires --lane")
            validate_adapter_file(args.repo_root, args.lane, args.validate_adapter)
            print(json.dumps({"adapter": args.validate_adapter, "lane": args.lane, "status": "pass"}, sort_keys=True))
            return 0
        report = repository_report(args.repo_root)
    except (
        AdapterValidationError,
        CapabilitySourceError,
        OSError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"lane-adapter-registry: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return int(
        bool(report["generated_mismatches"])
        or bool(report["ranked_gaps"]["gemini"])
        or bool(report["ranked_gaps"]["kimi"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
