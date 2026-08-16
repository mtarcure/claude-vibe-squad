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
    atomic_write_text,
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
    "accessibility-engineer",
    "bounty-researcher",
    "growth-and-search-analyst",
    "image-designer",
    "interactive-audio-designer",
    "music-composer",
    "research",
    "social-strategist",
    "sound-designer",
    "video-director",
    "video-editor",
    "voice-agent-builder",
    "voice-narrator",
)
KIMI_GENERATED_ROLES: tuple[str, ...] = ()
ADVISOR_GENERATED_ROLES = ("fable", "sol")
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
GEMINI_AGENT_REQUIRED_FIELDS = frozenset({"name", "description"})
GEMINI_AGENT_ALLOWED_FIELDS = GEMINI_AGENT_REQUIRED_FIELDS | frozenset(
    {
        "kind",
        "display_name",
        "tools",
        "mcp_servers",
        "model",
        "temperature",
        "max_turns",
        "timeout_mins",
    }
)
GEMINI_AGENT_NATIVE_TOOLS = (
    "read_file",
    "replace",
    "write_file",
    "run_shell_command",
    "glob",
    "grep_search",
)


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


def canonical_brief(repo_root: str | Path, row: dict[str, str]) -> Path:
    shared = Path("shared") / "specialists" / f"{row['specialist']}.md"
    if row["source_namespace"] == "shared" or (Path(repo_root) / shared).is_file():
        return shared
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
        if lane == "gemini":
            filtered[closing + 1 : closing + 1] = [
                "\n",
                "<!--\n",
                *replacement,
                "-->\n",
            ]
        else:
            filtered[closing:closing] = replacement
    elif lane == "gpt-codex":
        insertion = next((i for i, line in enumerate(filtered) if line.startswith("developer_instructions")), len(filtered))
        filtered[insertion:insertion] = replacement
    else:
        insertion = next((i for i, line in enumerate(filtered) if line.startswith("agent:")), len(filtered))
        filtered[insertion:insertion] = replacement
    return "".join(filtered)


def migrate_gemini_adapter(
    repo_root: str | Path,
    specialist: str,
    existing: str,
) -> str:
    """Move Gemini capability metadata out of strict frontmatter, preserving prose."""

    lines = existing.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise AdapterValidationError(
            f"{specialist}: Gemini adapter lacks opening frontmatter"
        )
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing is None:
        raise AdapterValidationError(
            f"{specialist}: Gemini adapter lacks closing frontmatter"
        )

    retained_frontmatter: list[str] = []
    for line in lines[1:closing]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if match is None or match.group(1) not in GEMINI_AGENT_ALLOWED_FIELDS:
            continue
        if match.group(1) == "tools":
            retained_frontmatter.append(
                "tools: "
                + json.dumps(
                    list(GEMINI_AGENT_NATIVE_TOOLS),
                    separators=(",", ":"),
                )
                + "\n"
            )
        else:
            retained_frontmatter.append(line)

    body = lines[closing + 1 :]
    begin = next(
        (
            index
            for index, line in enumerate(body)
            if PROJECTION_BEGIN in line
        ),
        None,
    )
    end = next(
        (
            index
            for index, line in enumerate(body)
            if PROJECTION_END in line
        ),
        None,
    )
    if begin is not None or end is not None:
        if begin is None or end is None or end < begin:
            raise AdapterValidationError(
                f"{specialist}: malformed Gemini capability projection sentinel"
            )
        wrapper_start = begin
        while wrapper_start > 0 and not body[wrapper_start].lstrip().startswith(
            "<!--"
        ):
            wrapper_start -= 1
        if not body[wrapper_start].lstrip().startswith("<!--"):
            wrapper_start = begin
        wrapper_end = end
        while wrapper_end + 1 < len(body) and body[
            wrapper_end
        ].strip() != "-->":
            wrapper_end += 1
        if body[wrapper_end].strip() != "-->":
            wrapper_end = end
        body = body[:wrapper_start] + body[wrapper_end + 1 :]

    body_text = "".join(body).lstrip("\n")
    projection = capability_projection(repo_root, "gemini", specialist)
    marker = (
        f"generated_by={GENERATED_MARKER} "
        f"registry_sha256={_registry_sha(Path(repo_root))}"
    )
    return (
        "---\n"
        + "".join(retained_frontmatter)
        + "---\n\n"
        + f"<!-- {marker}\n"
        + projection
        + "-->\n\n"
        + body_text
    )


def _legacy_adapter_body(
    lane: str,
    specialist: str,
    brief: str,
    *,
    variant: str | None = None,
) -> str:
    """Render the historical body shape from centralized live policy text.

    Adapter-fold overlays use this style marker only to preserve the corpus
    shape. They never replay a captured body, so edits here propagate to every
    folded legacy context.
    """

    if variant == "compact-v1":
        common = (
            f"You are the `{specialist}` specialist in the `{lane}` lane.\n\n"
            f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter. "
            "Verify runtime tools before relying on them; a routing-map entry is not proof that a tool is callable. "
            "Stay inside the packet's scope and operator gates.\n"
        )
    elif variant is None:
        common = (
            f"You are the `{specialist}` specialist running inside the `{lane}` model lane.\n\n"
            f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
            "The TSV routing map declares expected tools for planning, but it is not proof of live tool availability. "
            "Verify tools/MCPs in your current runtime before relying on them. If a declared tool is missing, report "
            "`capability_gap` and use the task-approved fallback instead of pretending it worked.\n\n"
            "Execute the task packet assigned by Chrono. Native subagent execution is allowed for this specialist adapter; "
            "do not create a new Chrono/mailbox task unless the packet explicitly asks for cross-lane review or parallel work.\n\n"
            "Stay inside the packet's write scope. Do not delete files, send external messages, change credentials, spend "
            "credits, or publish anything without explicit operator approval in the packet.\n"
        )
    else:
        raise AdapterValidationError(f"unknown legacy body variant: {variant}")
    if lane == "gpt-codex":
        return 'developer_instructions = """\n' + common + '"""\n'
    if lane in {"claude", "gemini"}:
        heading = specialist.replace("-", " ").title()
        return f"# Specialist Adapter: {heading}\n\n{common}"
    raise AdapterValidationError(f"legacy body style is not defined for lane {lane}")


def render_adapter(
    repo_root: str | Path,
    lane: str,
    specialist: str,
    *,
    legacy_style: bool = False,
    legacy_variant: str | None = None,
) -> str:
    root = Path(repo_root)
    rows = _runtime_rows(root)
    row = rows.get(specialist)
    if row is None:
        raise AdapterValidationError(f"unknown specialist: {specialist}")
    registry = load_capability_registry(root / "model-lanes" / "lane-capabilities.tsv")
    capability = registry[lane]
    brief = canonical_brief(root, row).as_posix()
    registry_sha = _registry_sha(root)
    source_entries, _source_payload = load_source(root)
    source_hash = source_sha256(root)
    role_capabilities = available_arrays(source_entries, specialist, lane)
    projection = capability_projection(root, lane, specialist)
    marker = f"generated_by={GENERATED_MARKER} registry_sha256={registry_sha}"
    if lane == "gpt-codex":
        instructions = (
            _legacy_adapter_body(
                lane, specialist, brief, variant=legacy_variant
            )
            if legacy_style
            else (
                'developer_instructions = """\n'
                f"You are the `{specialist}` specialist in the `gpt-codex` lane.\n\n"
                f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
                "Lane capability profile is `gpt-codex` from `model-lanes/lane-capabilities.tsv`. "
                "This adapter declares no native tool allowlist; verify the runtime-discovered tool and MCP surface before use. "
                "A registry capability is a ceiling, not task authorization.\n\n"
                "Execute only the assigned packet, remain read-only unless its write scope explicitly permits changes, and preserve every operator gate.\n"
                '"""\n'
            )
        )
        return (
            f"# {marker}\n"
            f'name = "{specialist.replace("-", "_")}\"\n'
            f'description = "Thin Codex adapter for {specialist}; canonical brief is authoritative.\"\n'
            'model_reasoning_effort = "high"\n'
            'sandbox_mode = "workspace-write"\n'
            f"{projection}"
            f"{instructions}"
        )
    if lane == "gemini":
        # Gemini's strict agent schema accepts actual native tool names and
        # ``mcp_<server>_*`` patterns, not bare MCP server labels such as
        # ``playwright``. Per-role MCPs stay in the external capability
        # projection and are enforced by the trusted launcher.
        tools = json.dumps(list(GEMINI_AGENT_NATIVE_TOOLS), separators=(",", ":"))
        gemini_role_lines = "".join(
            f"capability_{field}: {json.dumps(list(role_capabilities[field]), separators=(',', ':'))}\n"
            for field in ("skills", "tools", "mcps")
            if role_capabilities[field]
        )
        body = (
            _legacy_adapter_body(
                lane, specialist, brief, variant=legacy_variant
            )
            if legacy_style
            else (
                f"# Specialist Adapter: {specialist}\n\n"
                f"You are the `{specialist}` specialist in the `gemini` lane.\n\n"
                f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
                "Lane capability profile is `gemini` from `model-lanes/lane-capabilities.tsv`. "
                "The frontmatter tool list is the complete adapter-native allowlist. Google Search grounding and configured child MCPs "
                "must be verified in the current runtime before use; availability never grants spend or external-action authority.\n\n"
                "Execute only the assigned packet, stay inside write scope, and preserve every operator gate.\n"
            )
        )
        return (
            "---\n"
            f"name: {specialist}\n"
            f'description: "Thin Gemini adapter for {specialist}; canonical brief is authoritative."\n'
            "kind: local\n"
            f"tools: {tools}\n"
            "model: inherit\n"
            "max_turns: 30\n"
            "---\n\n"
            f"<!-- {marker}\n"
            f"# {PROJECTION_BEGIN}\n"
            f"capability_source: {SOURCE_RELATIVE.as_posix()}\n"
            f"capability_source_sha256: {source_hash}\n"
            f"{gemini_role_lines}"
            f"# {PROJECTION_END}\n"
            "-->\n\n"
            f"{body}"
        )
    if lane == "claude":
        body = (
            _legacy_adapter_body(
                lane, specialist, brief, variant=legacy_variant
            )
            if legacy_style
            else (
                f"# Specialist Adapter: {specialist}\n\n"
                f"You are the `{specialist}` specialist in the `claude` lane.\n\n"
                f"Canonical specialist instructions live at `{brief}`. Read that file at task start and follow it over this adapter.\n\n"
                "Role capabilities are derived from the versioned source named in frontmatter. Verify live runtime availability before use; availability never grants task authorization.\n\n"
                "Execute only the assigned packet, stay inside write scope, and preserve every operator gate.\n"
            )
        )
        return (
            "---\n"
            f"name: {specialist}\n"
            f'description: "Thin Claude adapter for {specialist}; canonical brief is authoritative."\n'
            "model: inherit\n"
            f"generated_by: {GENERATED_MARKER}\n"
            f"capability_registry_sha256: {registry_sha}\n"
            f"{projection}"
            "---\n\n"
            f"{body}"
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
    brief = canonical_brief(root, row).as_posix()
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


def _markdown_frontmatter_keys(text: str) -> frozenset[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AdapterValidationError("Markdown adapter lacks opening frontmatter")
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise AdapterValidationError(
            "Markdown adapter lacks closing frontmatter"
        ) from exc
    keys: set[str] = set()
    for line in lines[1:closing]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if match:
            keys.add(match.group(1))
    return frozenset(keys)


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
    brief = canonical_brief(root, row).as_posix()
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
        allowed = set(GEMINI_AGENT_NATIVE_TOOLS)
        if capability.grounding == "google-search-grounding":
            # Gemini exposes grounding as google_web_search in older native
            # adapters even though it is not part of the local edit-tool list.
            allowed.add("google_web_search")
        forbidden = sorted(set(declared) - allowed)
        if forbidden:
            raise AdapterValidationError(
                f"Gemini adapter {specialist} declares unavailable tool(s): {','.join(forbidden)}"
            )
        frontmatter_keys = _markdown_frontmatter_keys(text)
        missing_fields = sorted(GEMINI_AGENT_REQUIRED_FIELDS - frontmatter_keys)
        extra_fields = sorted(frontmatter_keys - GEMINI_AGENT_ALLOWED_FIELDS)
        if missing_fields:
            raise AdapterValidationError(
                f"Gemini adapter {specialist} lacks required agent field(s): "
                f"{','.join(missing_fields)}"
            )
        if extra_fields:
            raise AdapterValidationError(
                f"Gemini adapter {specialist} declares unsupported agent field(s): "
                f"{','.join(extra_fields)}"
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


def generated_marker_files(repo_root: str | Path) -> list[tuple[str, Path]]:
    """Return every lane file that claims registry ownership via the marker."""

    root = Path(repo_root)
    marker = GENERATED_MARKER.encode()
    generated: list[tuple[str, Path]] = []
    for lane in ("gpt-codex", "claude", "gemini", "kimi"):
        lane_root = root / "model-lanes" / lane
        for path in sorted(lane_root.rglob("*")):
            if path.is_file() and marker in path.read_bytes():
                generated.append((lane, path))
    return generated


def sync_derived_adapters(repo_root: str | Path) -> dict[str, int]:
    """Atomically refresh every capability projection and blank-advisor overlay."""

    root = Path(repo_root)
    source_entries, _payload = load_source(root)
    refreshed = 0
    created = 0
    for specialist, lane in sorted(source_entries):
        target = _target(root, lane, specialist)
        if specialist in ADVISOR_GENERATED_ROLES and lane in {
            "claude",
            "gpt-codex",
        }:
            rendered = render_adapter(root, lane, specialist)
            if not target.is_file():
                created += 1
        elif target.is_file():
            existing = target.read_text(encoding="utf-8")
            rendered = (
                migrate_gemini_adapter(root, specialist, existing)
                if lane == "gemini"
                else upsert_capability_projection(root, lane, specialist, existing)
            )
        else:
            raise AdapterValidationError(
                f"capability source adapter is missing: {lane}/{specialist}"
            )
        atomic_write_text(target, rendered)
        refreshed += 1

    for specialist in ADVISOR_GENERATED_ROLES:
        for lane in ("claude", "gpt-codex"):
            fields = (
                {"model_reasoning_effort": "high"}
                if lane == "gpt-codex"
                else {}
            )
            overlay = (
                root
                / "shared"
                / "lane-role-overlay"
                / "v1"
                / lane
                / f"{specialist}.json"
            )
            atomic_write_text(
                overlay,
                json.dumps(
                    {
                        "fields": fields,
                        "lane": lane,
                        "schema": "lane-role-overlay/v1",
                        "specialist": specialist,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )

    from validate_capability_homes import (
        INDEX_RELATIVE,
        load_adapters,
        load_lane_inventory,
        load_policy,
        render_index,
        runtime_rows,
    )

    policy = load_policy(root)
    rows = runtime_rows(root)
    adapters, _issues = load_adapters(root, rows)
    atomic_write_text(
        root / INDEX_RELATIVE,
        render_index(
            root,
            adapters,
            policy,
            lane_inventory=load_lane_inventory(root),
            source_entries=source_entries,
        ),
    )
    return {"adapters_refreshed": refreshed, "adapters_created": created}


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
    kimi_prompt_root = root / "model-lanes" / "kimi" / ".kimi" / "prompts"
    for lane, path in generated_marker_files(root):
        role = path.stem
        if path == _target(root, lane, role):
            try:
                text = path.read_text(encoding="utf-8")
                expected = (
                    migrate_gemini_adapter(root, role, text)
                    if lane == "gemini"
                    else upsert_capability_projection(root, lane, role, text)
                )
                if expected != text:
                    mismatches.append(f"projection:{lane}:{role}")
                validate_adapter_file(root, lane, path)
            except AdapterValidationError as exc:
                mismatches.append(f"invalid:{lane}:{role}:{exc}")
            continue
        if lane == "kimi" and path.parent == kimi_prompt_root:
            try:
                if path.read_text(encoding="utf-8") != render_kimi_prompt(root, role):
                    mismatches.append(f"prompt:kimi:{role}")
            except AdapterValidationError as exc:
                mismatches.append(f"invalid:kimi-prompt:{role}:{exc}")
            continue
        relative = path.relative_to(root).as_posix()
        mismatches.append(f"unrecognized-generated-file:{lane}:{relative}")
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
    parser.add_argument(
        "--sync-gemini",
        action="store_true",
        help="Regenerate every registry-managed Gemini agent definition",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--validate-adapter")
    parser.add_argument("--lane", choices=("gpt-codex", "claude", "gemini", "kimi"))
    args = parser.parse_args(argv)
    try:
        if args.sync_gemini:
            root = Path(args.repo_root)
            for specialist in GEMINI_GENERATED_ROLES:
                target = _target(root, "gemini", specialist)
                if target.is_file():
                    rendered = migrate_gemini_adapter(
                        root,
                        specialist,
                        target.read_text(encoding="utf-8"),
                    )
                else:
                    rendered = render_adapter(root, "gemini", specialist)
                target.write_text(
                    rendered,
                    encoding="utf-8",
                )
            print(
                json.dumps(
                    {
                        "lane": "gemini",
                        "regenerated": len(GEMINI_GENERATED_ROLES),
                        "status": "synced",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.validate_adapter:
            if not args.lane:
                raise AdapterValidationError("--validate-adapter requires --lane")
            validate_adapter_file(args.repo_root, args.lane, args.validate_adapter)
            print(json.dumps({"adapter": args.validate_adapter, "lane": args.lane, "status": "pass"}, sort_keys=True))
            return 0
        if not args.check:
            sync_derived_adapters(args.repo_root)
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
