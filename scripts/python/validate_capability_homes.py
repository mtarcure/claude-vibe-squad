#!/usr/bin/env python3
"""Validate specialist capability homes and their derived cross-lane index.

The canonical specialist briefs define role/method/safety behavior.  Concrete
skills, tools, and MCPs live in structured per-lane adapter fields.  This gate
enforces that boundary, preserves a pinned pre-migration capability baseline,
checks declarations against real lane/toolchain inventories, and verifies the
generated specialist-by-lane index byte-for-byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from specialist_capability_source import (
    CapabilitySourceError,
    SOURCE_RELATIVE,
    atomic_write_text,
    available_arrays,
    load_source,
    source_sha256,
    tracked_arrays,
)


LANES = ("gpt-codex", "claude", "gemini", "kimi")
ROUTE_FIELDS = (
    "primary_lane",
    "backup_lane",
    "escalate_lane",
    "review_lane",
    "throughput_lane",
)
CAPABILITY_FIELDS = ("skills", "tools", "mcps")
POLICY_RELATIVE = Path("model-lanes/adapter-capability-policy.json")
INDEX_RELATIVE = Path("model-lanes/generated-specialist-capabilities.json")
LANE_REGISTRY_RELATIVE = Path("model-lanes/lane-capabilities.tsv")
RUNTIME_MAP_RELATIVE = Path("shared/specialist-runtime-map.tsv")
API_CATALOG_RELATIVE = Path("shared/api-catalog.md")
INDEX_SCHEMA = "specialist-adapter-capability-index/v2"


class CapabilityHomeError(RuntimeError):
    """Raised for an invalid capability-home input or configuration."""


def diagnostic(
    check: str,
    path: str,
    identifier: str,
    message: str,
    *,
    line: int = 0,
    kind: str = "",
) -> dict[str, Any]:
    return {
        "check": check,
        "identifier": identifier,
        "kind": kind,
        "line": line,
        "message": message,
        "path": path,
    }


def load_policy(root: Path, policy_path: Path | None = None) -> dict[str, Any]:
    path = policy_path or root / POLICY_RELATIVE
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityHomeError(f"cannot load capability policy {path}: {exc}") from exc
    if policy.get("schema") != "adapter-capability-policy/v1":
        raise CapabilityHomeError("capability policy schema mismatch")
    baseline = str(policy.get("baseline_ref") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise CapabilityHomeError("capability policy baseline_ref must be an exact git SHA")
    pointer = policy.get("generic_pointer_line")
    if not isinstance(pointer, str) or not pointer:
        raise CapabilityHomeError("capability policy requires one exact generic_pointer_line")
    for field in CAPABILITY_FIELDS:
        values = policy.get("identifier_seeds", {}).get(field)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise CapabilityHomeError(f"policy identifier_seeds.{field} must be a string list")
        parity_values = policy.get("parity_identifier_seeds", {}).get(field, values)
        if not isinstance(parity_values, list) or not all(
            isinstance(item, str) for item in parity_values
        ):
            raise CapabilityHomeError(
                f"policy parity_identifier_seeds.{field} must be a string list"
            )
    contextual = policy.get("context_required_tool_seeds", [])
    if not isinstance(contextual, list) or not all(
        isinstance(item, str) and item for item in contextual
    ):
        raise CapabilityHomeError(
            "policy context_required_tool_seeds must be a non-empty string list"
        )
    for rule in policy.get("regex_rules", []):
        if not isinstance(rule, dict) or not all(
            isinstance(rule.get(key), str) for key in ("id", "kind", "pattern")
        ):
            raise CapabilityHomeError("policy regex_rules entries require id/kind/pattern")
        re.compile(rule["pattern"])
    return policy


def _json_string_list(raw: Any, field: str, path: Path) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise CapabilityHomeError(f"{path}: {field} must be an array of strings")
    cleaned = tuple(item.strip() for item in raw)
    if any(not item for item in cleaned):
        raise CapabilityHomeError(f"{path}: {field} contains an empty identifier")
    if len(cleaned) != len(set(cleaned)):
        raise CapabilityHomeError(f"{path}: {field} contains duplicate identifiers")
    return cleaned


def _markdown_frontmatter(text: str, path: Path) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        raise CapabilityHomeError(f"{path}: unterminated Markdown frontmatter")
    result: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if key in CAPABILITY_FIELDS or key in {f"capability_{field}" for field in CAPABILITY_FIELDS}:
            if key in result:
                raise CapabilityHomeError(
                    f"{path}: duplicate top-level capability field {key}"
                )
            try:
                result[key] = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CapabilityHomeError(
                    f"{path}: {key} must use a one-line JSON-compatible array: {exc}"
                ) from exc
        else:
            result[key] = raw.strip('"').strip("'")
    return result


def _yaml_top_level(text: str, path: Path) -> dict[str, Any]:
    """Read only top-level structured arrays from a Kimi YAML adapter."""
    result: dict[str, Any] = {}
    for line in text.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if key in {"capability_source", "capability_source_sha256", "generated_by"}:
            result[key] = raw.strip('"').strip("'")
            continue
        if key in CAPABILITY_FIELDS:
            if key in result:
                raise CapabilityHomeError(
                    f"{path}: duplicate top-level capability field {key}"
                )
            try:
                result[key] = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CapabilityHomeError(
                    f"{path}: {key} must use a one-line JSON-compatible array: {exc}"
                ) from exc
    return result


def _adapter_globs(root: Path) -> Iterable[tuple[str, Path]]:
    locations = (
        ("gpt-codex", root / "model-lanes/gpt-codex/.codex/agents", "*.toml"),
        ("claude", root / "model-lanes/claude/.claude/agents", "*.md"),
        ("gemini", root / "model-lanes/gemini/.gemini/agents", "*.md"),
        ("kimi", root / "model-lanes/kimi/.kimi/agents", "*.yaml"),
    )
    for lane, directory, pattern in locations:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(pattern)):
            if path.stem.lower() == "readme":
                continue
            yield lane, path


def runtime_rows(root: Path) -> dict[str, dict[str, str]]:
    path = root / RUNTIME_MAP_RELATIVE
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise CapabilityHomeError(f"cannot read runtime map {path}: {exc}") from exc
    result = {row.get("specialist", ""): row for row in rows}
    if "" in result or len(result) != len(rows):
        raise CapabilityHomeError("runtime map contains empty or duplicate specialist ids")
    return result


def canonical_brief(row: dict[str, str]) -> Path:
    specialist = row["specialist"]
    namespace = row["source_namespace"]
    if namespace == "shared":
        return Path("shared/specialists") / f"{specialist}.md"
    return Path("departments") / namespace / "specialists" / f"{specialist}.md"


def normalize_lane(raw: str) -> str:
    value = (raw or "").strip()
    return "gpt-codex" if value == "codex" else value


def routed_lanes(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                normalize_lane(row.get(field, ""))
                for field in ROUTE_FIELDS
                if normalize_lane(row.get(field, "")) in LANES
            }
        )
    )


def load_adapters(
    root: Path, rows: dict[str, dict[str, str]]
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    adapters: dict[tuple[str, str], dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for lane, path in _adapter_globs(root):
        specialist = path.stem.replace("_", "-") if lane == "gpt-codex" else path.stem
        if specialist not in rows:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            if lane == "gpt-codex":
                parsed = tomllib.loads(text)
            elif lane in {"claude", "gemini"}:
                parsed = _markdown_frontmatter(text, path)
            else:
                parsed = _yaml_top_level(text, path)
            capabilities = {
                field: _json_string_list(
                    parsed.get(f"capability_{field}" if lane == "gemini" else field),
                    field,
                    path,
                )
                for field in CAPABILITY_FIELDS
            }
        except (OSError, tomllib.TOMLDecodeError, CapabilityHomeError) as exc:
            issues.append(
                diagnostic("adapter-schema", rel, "schema", str(exc), kind="schema")
            )
            continue
        key = (specialist, lane)
        if key in adapters:
            issues.append(
                diagnostic(
                    "adapter-schema",
                    rel,
                    f"{specialist}:{lane}",
                    "duplicate adapter capability home",
                    kind="schema",
                )
            )
            continue
        adapters[key] = {
            "adapter": rel,
            "capability_source": parsed.get("capability_source", ""),
            "capability_source_sha256": parsed.get("capability_source_sha256", ""),
            "lane_native_mirror": parsed.get("generated_by")
            == "lane-capability-registry/v1",
            "lane": lane,
            "specialist": specialist,
            **capabilities,
        }
    return adapters, issues


def _alias(identifier: str, policy: dict[str, Any], kind: str = "") -> str:
    aliases = policy.get("aliases", {})
    mapped = aliases.get(identifier, aliases.get(identifier.lower()))
    if mapped is not None:
        return str(mapped).strip()
    return identifier.lower() if kind == "tools" else identifier


def _seed_capabilities(
    text: str, policy: dict[str, Any], *, tool_section: bool = False
) -> dict[str, set[str]]:
    result = {field: set() for field in CAPABILITY_FIELDS}
    seed_source = policy.get("parity_identifier_seeds", policy["identifier_seeds"])
    contextual_tools = {
        item.lower() for item in policy.get("context_required_tool_seeds", [])
    }
    for kind in CAPABILITY_FIELDS:
        for identifier in seed_source[kind]:
            flags = (
                re.IGNORECASE
                if kind != "skills" and not any(char.isupper() for char in identifier)
                else 0
            )
            pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(identifier)}(?![A-Za-z0-9_.-])"
            if (
                kind == "tools"
                and not tool_section
                and identifier.lower() in contextual_tools
            ):
                pattern = rf"`[^`\n]*{pattern}[^`\n]*`"
            if re.search(pattern, text, flags):
                result[kind].add(_alias(identifier, policy, kind))
    return result


def _section(text: str, heading: str, level: int) -> str:
    marker = "#" * level + " " + heading
    match = re.search(
        rf"(?m)^{re.escape(marker)}(?:[ \t]+\([^\n]*\))?[ \t]*\n", text
    )
    if not match:
        return ""
    remainder = text[match.end() :]
    end = re.search(rf"(?m)^#{{1,{level}}}\s", remainder)
    return remainder[: end.start()] if end else remainder


def _skill_identifiers(section: str) -> set[str]:
    result: set[str] = set()
    for line in section.splitlines():
        # A skill declaration is a bullet whose payload starts with a code
        # identifier.  Backticks in prose-only bullets are status/file refs,
        # not capabilities; an em-dash starts the declaration's description.
        if not re.match(r"^\s*-\s+`", line):
            continue
        declarations = line.split(" — ", 1)[0]
        result.update(
            re.findall(r"`([a-z0-9][a-z0-9_.-]*)`", declarations)
        )
    return result


def _tool_identifiers(section: str, policy: dict[str, Any]) -> set[str]:
    """Return only tools from the policy's reviewed pre-strip lexicon.

    Tool-section bullets frequently begin with prose labels (``Process audit``,
    ``Date / amount normalization``).  Treating the first word as an executable
    creates impossible parity requirements.  The reviewed seed list is the
    extraction grammar: adding a new historical tool is an explicit policy
    change, not a heuristic guess.
    """
    return _seed_capabilities(section, policy, tool_section=True)["tools"]


def extract_baseline_capabilities(text: str, policy: dict[str, Any]) -> dict[str, set[str]]:
    """Extract the reviewed role-specific capability lexicon from a pre-strip brief."""
    result = _seed_capabilities(text, policy)
    result["skills"].update(_skill_identifiers(_section(text, "Skills", 3)))
    # Tool-section parsing uses the same reviewed lexicon.  It supplements the
    # required full-body seed scan; it never infers the bullet's first word.
    for heading in policy.get("tool_section_headings", []):
        result["tools"].update(_tool_identifiers(_section(text, heading, 2), policy))
    return result


def baseline_text(root: Path, baseline_ref: str, relative: Path) -> str:
    command = ["git", "show", f"{baseline_ref}:{relative.as_posix()}"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise CapabilityHomeError(
            f"cannot read baseline {baseline_ref}:{relative}: {result.stderr.strip()}"
        )
    return result.stdout


def load_baseline(
    root: Path, rows: dict[str, dict[str, str]], policy: dict[str, Any]
) -> dict[str, dict[str, set[str]]]:
    baseline_ref = policy["baseline_ref"]
    result: dict[str, dict[str, set[str]]] = {}
    for specialist, row in sorted(rows.items()):
        relative = canonical_brief(row)
        text = baseline_text(root, baseline_ref, relative)
        result[specialist] = extract_baseline_capabilities(text, policy)
    return result


def _frontmatter_scan_lines(
    text: str, exempt_keys: set[str]
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return scan-eligible frontmatter and body lines with original line numbers."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], list(enumerate(lines, start=1))
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return [], list(enumerate(lines, start=1))
    eligible: list[tuple[int, str]] = []
    current_exempt = False
    for index in range(1, end):
        line = lines[index]
        top = re.match(r"^([A-Za-z0-9_-]+):", line)
        if top:
            current_exempt = top.group(1) in exempt_keys
        if not current_exempt:
            eligible.append((index + 1, line))
    return eligible, [(index + 1, lines[index]) for index in range(end + 1, len(lines))]


def _identifier_matches(line: str, identifier: str, kind: str) -> bool:
    flags = re.IGNORECASE if kind != "skills" else 0
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(identifier)}(?![A-Za-z0-9_.-])",
            line,
            flags,
        )
    )


def base_boundary_diagnostics(
    root: Path,
    rows: dict[str, dict[str, str]],
    policy: dict[str, Any],
    baseline: dict[str, dict[str, set[str]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    pointer = policy["generic_pointer_line"]
    exempt = set(policy["frontmatter_exempt_keys"])
    global_ids = {kind: set() for kind in CAPABILITY_FIELDS}
    for kind in CAPABILITY_FIELDS:
        for item in policy["identifier_seeds"][kind]:
            global_ids[kind].add(item)
            global_ids[kind].add(_alias(item, policy, kind))
    compiled_rules = [
        (rule, re.compile(rule["pattern"])) for rule in policy.get("regex_rules", [])
    ]
    for specialist, row in sorted(rows.items()):
        relative = canonical_brief(row)
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(
                diagnostic("base-boundary", relative.as_posix(), "read", str(exc), kind="schema")
            )
            continue
        frontmatter, body = _frontmatter_scan_lines(text, exempt)
        pointer_lines = [line_no for line_no, line in body if line == pointer]
        if len(pointer_lines) != 1:
            issues.append(
                diagnostic(
                    "base-boundary",
                    relative.as_posix(),
                    "generic-adapter-pointer",
                    f"expected exactly one approved generic pointer line, found {len(pointer_lines)}",
                    kind="schema",
                )
            )
        scan_lines = frontmatter + [item for item in body if item[1] != pointer]
        identifiers = {
            kind: global_ids[kind] | set(baseline[specialist][kind])
            for kind in CAPABILITY_FIELDS
        }
        for line_no, line in scan_lines:
            seen: set[tuple[str, str]] = set()
            for kind in CAPABILITY_FIELDS:
                for identifier in sorted(identifiers[kind], key=lambda item: item.lower()):
                    if _identifier_matches(line, identifier, kind):
                        reported = _alias(identifier, policy, kind)
                        key = (kind, reported)
                        if key in seen:
                            continue
                        seen.add(key)
                        issues.append(
                            diagnostic(
                                "base-boundary",
                                relative.as_posix(),
                                reported,
                                "lane-specific capability identifier remains in canonical base",
                                line=line_no,
                                kind=kind,
                            )
                        )
            for rule, compiled in compiled_rules:
                for match in compiled.finditer(line):
                    identifier = match.group(0)
                    key = (rule["kind"], identifier)
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(
                        diagnostic(
                            "base-boundary",
                            relative.as_posix(),
                            identifier,
                            f"lane-specific {rule['id']} remains in canonical base",
                            line=line_no,
                            kind=rule["kind"],
                        )
                    )
    return issues


def migration_parity_diagnostics(
    rows: dict[str, dict[str, str]],
    adapters: dict[tuple[str, str], dict[str, Any]],
    baseline: dict[str, dict[str, set[str]]],
    source_entries: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for specialist, row in sorted(rows.items()):
        lanes = routed_lanes(row)
        declared = {field: set() for field in CAPABILITY_FIELDS}
        for lane in lanes:
            if source_entries is not None:
                tracked = tracked_arrays(source_entries, specialist, lane)
                for field in CAPABILITY_FIELDS:
                    declared[field].update(tracked[field])
            else:
                adapter = adapters.get((specialist, lane))
                if not adapter:
                    continue
                for field in CAPABILITY_FIELDS:
                    declared[field].update(adapter[field])
        for kind in ("skills", "tools"):
            for identifier in sorted(baseline[specialist][kind], key=lambda item: item.lower()):
                # A named MCP supersedes a same-id CLI/tool declaration. This is
                # the intentional de-duplication path for capabilities such as
                # Playwright; parity is about retained access, not preserving a
                # redundant transport classification.
                retained = identifier in declared[kind]
                if kind == "tools" and identifier in declared["mcps"]:
                    retained = True
                if not retained:
                    issues.append(
                        diagnostic(
                            "migration-parity",
                            canonical_brief(row).as_posix(),
                            identifier,
                            "pre-strip capability is absent from every adapter on a routed lane "
                            f"({','.join(lanes) or 'none'})",
                            kind=kind,
                        )
                    )
    return issues


def source_coverage_diagnostics(
    rows: dict[str, dict[str, str]],
    source_entries: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = {
        (specialist, lane)
        for specialist, row in rows.items()
        for lane in routed_lanes(row)
    }
    issues: list[dict[str, Any]] = []
    for specialist, lane in sorted(expected - set(source_entries)):
        issues.append(diagnostic("source-coverage", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}", "routed specialist/lane pair is absent from the authored source", kind="schema"))
    for specialist, lane in sorted(set(source_entries) - expected):
        issues.append(diagnostic("source-coverage", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}", "authored source contains a specialist/lane pair that is not routed", kind="schema"))
    for specialist, row in sorted(rows.items()):
        primary = normalize_lane(row.get("primary_lane", ""))
        entry = source_entries.get((specialist, primary))
        if entry and entry["coverage"] != "full":
            issues.append(diagnostic("source-coverage", SOURCE_RELATIVE.as_posix(), f"{specialist}:{primary}", "primary lane must declare full coverage", kind="schema"))
    return issues


def adapter_source_sync_diagnostics(
    root: Path,
    adapters: dict[tuple[str, str], dict[str, Any]],
    source_entries: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_sha = source_sha256(root)
    issues: list[dict[str, Any]] = []
    for key, entry in sorted(source_entries.items()):
        if not any(entry[field] for field in CAPABILITY_FIELDS) and not entry.get("primary_requirements"):
            continue
        adapter = adapters.get(key)
        specialist, lane = key
        if adapter is None:
            issues.append(diagnostic("adapter-source-sync", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}", "capability-bearing source entry has no physical adapter", kind="schema"))
            continue
        expected = available_arrays(source_entries, specialist, lane)
        for field in CAPABILITY_FIELDS:
            if tuple(adapter[field]) != expected[field]:
                issues.append(diagnostic("adapter-source-sync", adapter["adapter"], f"{specialist}:{lane}:{field}", "derived adapter capability array differs from the authored source", kind=field))
        if adapter.get("capability_source") != SOURCE_RELATIVE.as_posix() or adapter.get("capability_source_sha256") != expected_sha:
            issues.append(diagnostic("adapter-source-sync", adapter["adapter"], f"{specialist}:{lane}:source", "derived adapter lacks the exact capability source pointer/hash", kind="schema"))
    return issues


def load_lane_inventory(root: Path) -> dict[str, dict[str, set[str]]]:
    path = root / LANE_REGISTRY_RELATIVE
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        lane = row["lane"]
        try:
            result[lane] = {
                "tools": set(json.loads(row["adapter_tools"])),
                "mcps": set(json.loads(row["mcp_surface"])),
                "staged_mcps": set(json.loads(row.get("staged_mcp_surface", "[]"))),
                "skills": set(json.loads(row["skills"])),
            }
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            raise CapabilityHomeError(f"invalid lane inventory row {lane}: {exc}") from exc
        grounding = row.get("grounding", "")
        if grounding == "google-search-grounding":
            result[lane]["tools"].add("google_web_search")
    if set(result) != set(LANES):
        raise CapabilityHomeError("lane inventory must contain exactly the four execution lanes")
    return result


def _catalog_identifier(raw: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", raw.lower()).strip("-")


def _catalog_section_name(raw: str) -> str:
    """Normalize numbered API-catalog section headings."""
    return re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", raw.lower()).strip()


def _catalog_lane_tokens(raw: str) -> set[str]:
    lanes = {
        normalize_lane(item)
        for item in re.findall(r"[a-z][a-z0-9-]*", raw.lower())
    }
    return lanes & set(LANES)


def _explicit_catalog_lanes(section: str, block: str) -> set[str] | None:
    """Return an explicit catalog lane restriction, if one is declared.

    An explicit entry-level ``lane``/``lanes`` field wins over the enclosing
    section.  The legacy catalog also has a small number of prose restrictions
    such as ``Claude-lane only``; retain support for those until the catalog is
    fully structured.
    """
    lane_field = re.search(r"(?m)^- lanes?:\s*([^\n]+)$", block)
    if lane_field:
        if lane_field.group(1).strip().lower() == "all":
            return set(LANES)
        return _catalog_lane_tokens(lane_field.group(1))

    only_lane = re.search(
        r"\b(claude|codex|gemini|kimi)(?:/chrono)?(?:[- ]lane|\s+panes?)\s+only\b",
        block,
        re.IGNORECASE,
    )
    if only_lane:
        return {normalize_lane(only_lane.group(1).lower())}

    normalized = _catalog_section_name(section)
    section_defaults = {
        "anthropic / claude": {"claude"},
        "openai / codex": {"gpt-codex"},
        "google / gemini": {"gemini"},
        "moonshot / kimi": {"kimi"},
    }
    if normalized in section_defaults:
        return set(section_defaults[normalized])
    section_lane = re.search(
        r"\b(claude|codex|gemini|kimi) lane\b", normalized, re.IGNORECASE
    )
    if section_lane:
        return {normalize_lane(section_lane.group(1).lower())}
    return None


def registry_tool_lane_restrictions(root: Path) -> dict[str, set[str]]:
    """Return authoritative explicit tool lane sets from the shared registry.

    ``lanes=all`` is intentionally omitted because it is not a restriction.
    Non-runtime values such as ``none`` or ``direct-api`` produce an empty set,
    which prevents route-derived catalog availability from fabricating a lane.
    """
    path = root / "shared/registries/skill-tool-registry.tsv"
    if not path.is_file():
        return {}
    result: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("record_kind") != "tool" or row.get("lanes") == "all":
                continue
            identifier = _catalog_identifier(row.get("name", ""))
            if not identifier:
                continue
            result.setdefault(identifier, set()).update(
                _catalog_lane_tokens(row.get("lanes", ""))
            )
    return result


def verified_catalog_tools(
    root: Path, rows: dict[str, dict[str, str]] | None = None
) -> dict[str, set[str]]:
    """Return conservative, lane-scoped identifiers from verified catalog entries.

    Only complete entry names and explicit single-token aliases are indexed.
    Splitting headings into arbitrary words would incorrectly certify generic
    identifiers such as ``api``, ``model``, or ``claude``.  Specialist metadata
    scopes shared/local entries to the lanes on which those roles actually run;
    vendor sections provide a fail-closed default for native CLI entries.
    """
    text = (root / API_CATALOG_RELATIVE).read_text(encoding="utf-8")
    headings = list(re.finditer(r"(?m)^#{3,4}\s+(.+?)\s*$", text))
    sections = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    result = {lane: set() for lane in LANES}
    registry_restrictions = registry_tool_lane_restrictions(root)
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[match.end() : end]
        verified = re.search(r"(?m)^- verified:\s*([^\n]+)$", block)
        if not verified or not verified.group(1).strip().lower().startswith("yes"):
            continue
        section_name = ""
        for section in sections:
            if section.start() >= match.start():
                break
            section_name = section.group(1)
        explicit_lanes = _explicit_catalog_lanes(section_name, block)
        lanes = set(explicit_lanes or ())
        if explicit_lanes is None:
            specialists = re.search(r"(?m)^- specialists:\s*([^\n]+)$", block)
            if specialists and rows:
                for specialist in re.findall(
                    r"[a-z][a-z0-9-]*", specialists.group(1).lower()
                ):
                    if specialist in rows:
                        lanes.update(routed_lanes(rows[specialist]))
        if not lanes:
            # Catalog entries outside a native-lane section are shared only
            # when their specialist metadata proves a routed lane.
            continue
        heading = re.sub(r"[*]", "", match.group(1)).strip()
        primary = re.split(r"\s+\(", re.sub(r"`", "", heading), maxsplit=1)[0].strip()
        candidates = {_catalog_identifier(primary)}
        candidates.update(
            _catalog_identifier(item)
            for item in re.findall(r"`([A-Za-z0-9][A-Za-z0-9_.-]*)`", heading)
        )
        candidates.update(
            _catalog_identifier(item)
            for item in re.findall(r"\(([A-Za-z0-9][A-Za-z0-9_.-]*)\)", heading)
        )
        explicit_registry_sets = [
            registry_restrictions[candidate]
            for candidate in candidates
            if candidate in registry_restrictions
        ]
        registry_lanes = (
            set.intersection(*explicit_registry_sets)
            if explicit_registry_sets
            else None
        )
        for candidate in candidates:
            if not candidate:
                continue
            # A registry restriction on any identifier/alias in the heading
            # constrains the complete catalog entry, not just that spelling.
            candidate_lanes = lanes if registry_lanes is None else lanes & registry_lanes
            for lane in candidate_lanes:
                result[lane].add(candidate)
    return result


def actual_skill_names(root: Path, lane: str) -> set[str]:
    home = Path.home()
    roots: dict[str, tuple[Path, ...]] = {
        "gpt-codex": (
            root / "model-lanes/gpt-codex/.agents/skills",
            home / ".codex/skills",
            home / ".codex/plugins/cache",
        ),
        "claude": (
            root / "model-lanes/claude/.claude/skills",
            home / ".claude/plugins/cache",
        ),
        "gemini": (
            root / "model-lanes/gemini/.gemini/skills",
            home / ".gemini/extensions",
        ),
        "kimi": (root / "model-lanes/kimi/.kimi/skills",),
    }
    result: set[str] = set()
    for skill_root in roots[lane]:
        if not skill_root.is_dir():
            continue
        for path in skill_root.rglob("SKILL.md"):
            result.add(path.parent.name)
    return result


def shared_registry_capabilities(root: Path) -> dict[str, dict[str, set[str]]]:
    path = root / "shared/registries/skill-tool-registry.tsv"
    result = {
        lane: {field: set() for field in CAPABILITY_FIELDS}
        for lane in LANES
    }
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            name = row.get("name", "")
            lanes = set(LANES) if row.get("lanes") == "all" else {
                normalize_lane(item.strip())
                for item in re.split(r"[|,]", row.get("lanes", ""))
            }
            if row.get("record_kind") == "skill" and row.get("verified_state") in {"authored", "yes"}:
                for lane in lanes & set(LANES):
                    result[lane]["skills"].add(name)
            if row.get("record_kind") == "tool" and row.get("verified_state") in {"yes", "lane-live"}:
                for lane in lanes & set(LANES):
                    if row.get("type", "").startswith("mcp"):
                        result[lane]["mcps"].add(name)
                    if row.get("type") in {"mcp-tool", "provider-native", "plugin-skill-family"}:
                        result[lane]["tools"].add(name)
    return result


def tool_existence_diagnostics(
    root: Path,
    adapters: dict[tuple[str, str], dict[str, Any]],
    *,
    lane_inventory: dict[str, dict[str, set[str]]] | None = None,
    catalog_tools: dict[str, set[str]] | set[str] | None = None,
    skill_names: dict[str, set[str]] | None = None,
    which: Any = shutil.which,
) -> list[dict[str, Any]]:
    inventory = lane_inventory or load_lane_inventory(root)
    if catalog_tools is None:
        catalog = verified_catalog_tools(root, runtime_rows(root))
    elif isinstance(catalog_tools, set):
        catalog = {lane: set(catalog_tools) for lane in LANES}
    else:
        catalog = catalog_tools
    skills = skill_names or {lane: actual_skill_names(root, lane) for lane in LANES}
    issues: list[dict[str, Any]] = []
    for (_specialist, lane), adapter in sorted(adapters.items()):
        for identifier in adapter["mcps"]:
            if identifier not in inventory[lane]["mcps"]:
                issues.append(
                    diagnostic(
                        "tool-existence", adapter["adapter"], identifier,
                        "declared MCP is absent from the lane inventory", kind="mcps"
                    )
                )
        for identifier in adapter["skills"]:
            if identifier not in inventory[lane]["skills"] and identifier not in skills[lane]:
                issues.append(
                    diagnostic(
                        "tool-existence", adapter["adapter"], identifier,
                        "declared skill is absent from lane inventory and installed skill roots",
                        kind="skills",
                    )
                )
        for identifier in adapter["tools"]:
            normalized = identifier.lower()
            shell_capable = (
                "repo-shell" in inventory[lane]["skills"]
                or "run_shell_command" in inventory[lane]["tools"]
            )
            if (
                identifier not in inventory[lane]["tools"]
                and normalized not in catalog.get(lane, set())
                and not (
                    shell_capable
                    and (which(identifier) is not None or which(normalized) is not None)
                )
            ):
                issues.append(
                    diagnostic(
                        "tool-existence", adapter["adapter"], identifier,
                        "declared tool is absent from lane inventory, this lane's exact verified API catalog identifiers, and its shell PATH",
                        kind="tools",
                    )
                )
    return issues


def source_existence_diagnostics(
    root: Path,
    source_entries: dict[tuple[str, str], dict[str, Any]],
    *,
    lane_inventory: dict[str, dict[str, set[str]]] | None = None,
    catalog_tools: dict[str, set[str]] | None = None,
    skill_names: dict[str, set[str]] | None = None,
    which: Any = shutil.which,
) -> list[dict[str, Any]]:
    inventory = lane_inventory or load_lane_inventory(root)
    catalog = catalog_tools or verified_catalog_tools(root, runtime_rows(root))
    installed_skills = skill_names or {lane: actual_skill_names(root, lane) for lane in LANES}
    registry = shared_registry_capabilities(root)
    runtime = runtime_rows(root)
    issues: list[dict[str, Any]] = []
    for (specialist, lane), entry in sorted(source_entries.items()):
        projected = available_arrays(source_entries, specialist, lane)
        for kind in CAPABILITY_FIELDS:
            for identifier in projected[kind]:
                present = False
                if kind == "skills":
                    present = identifier in inventory[lane][kind] or identifier in installed_skills[lane] or identifier in registry[lane][kind]
                elif kind == "mcps":
                    present = identifier in inventory[lane][kind] or identifier in registry[lane][kind]
                else:
                    normalized = identifier.lower()
                    shell_capable = "repo-shell" in inventory[lane]["skills"] or "run_shell_command" in inventory[lane]["tools"]
                    present = identifier in inventory[lane][kind] or identifier in registry[lane][kind] or normalized in catalog.get(lane, set()) or (shell_capable and (which(identifier) is not None or which(normalized) is not None))
                if not present:
                    issues.append(diagnostic("source-existence", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}:{identifier}", "available capability lacks lane-local inventory, registry, installed-skill, catalog, or shell-qualified PATH evidence", kind=kind))
        for kind in CAPABILITY_FIELDS:
            for ref in entry[kind]:
                if ref.availability == "uninstalled" and which(ref.identifier) is not None:
                    issues.append(diagnostic("source-existence", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}:{ref.identifier}", "capability is marked uninstalled but is now present on PATH", kind=kind))
                if ref.availability == "mcp-operation":
                    provider = ref.evidence
                    if provider not in inventory[lane]["mcps"] and provider not in registry[lane]["mcps"]:
                        issues.append(diagnostic("source-existence", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}:{ref.identifier}", f"MCP operation provider {provider!r} is not available on this lane", kind=kind))
                if ref.availability == "pending-restart-activation":
                    if kind != "mcps" or ref.identifier not in inventory[lane]["staged_mcps"]:
                        issues.append(diagnostic("source-existence", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}:{ref.identifier}", "pending-restart MCP lacks the lane staged_mcp_surface declaration", kind=kind))
                if ref.availability == "harness-only" and ref.identifier not in runtime[specialist].get("requires_approval", ""):
                    issues.append(diagnostic("source-existence", SOURCE_RELATIVE.as_posix(), f"{specialist}:{lane}:{ref.identifier}", "harness-only capability lacks a matching runtime-map approval gate", kind=kind))
    return issues


def _tool_list(raw: str) -> tuple[str, ...]:
    value = (raw or "").strip()
    if not value or value == "[]":
        return ()
    if not (value.startswith("[") and value.endswith("]")):
        raise CapabilityHomeError(f"invalid runtime-map capability list: {raw!r}")
    return tuple(item.strip() for item in value[1:-1].split(",") if item.strip())


def required_primary_diagnostics(
    rows: dict[str, dict[str, str]],
    source_entries: dict[tuple[str, str], dict[str, Any]],
    *,
    root: Path | None = None,
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    repo_root = root or Path(__file__).resolve().parents[2]
    inventory = load_lane_inventory(repo_root)
    registry = shared_registry_capabilities(repo_root)
    for specialist, row in sorted(rows.items()):
        if namespace and row.get("source_namespace") != namespace:
            continue
        primary = normalize_lane(row.get("primary_lane", ""))
        entry = source_entries.get((specialist, primary))
        if entry is None:
            continue
        expected = _tool_list(row.get("required_tools", ""))
        plan = entry.get("primary_requirements", ())
        if tuple(item.identifier for item in plan) != expected:
            issues.append(diagnostic("required-primary", SOURCE_RELATIVE.as_posix(), f"{specialist}:{primary}:plan", "typed primary plan does not exactly match runtime-map required_tools", kind="required"))
            continue
        projected = available_arrays(source_entries, specialist, primary)
        for item in plan:
            if item.resolution == "local":
                satisfied = item.capability_id in projected[item.kind]
            else:
                satisfied = (
                    item.provider_lane != primary
                    and (
                        item.capability_id in inventory[item.provider_lane][item.kind]
                        or item.capability_id in registry[item.provider_lane][item.kind]
                    )
                )
            if not satisfied:
                issues.append(diagnostic("required-primary", SOURCE_RELATIVE.as_posix(), f"{specialist}:{primary}:{item.identifier}", "typed required capability is not satisfied by its local kind or explicit provider handoff", kind=item.kind))
    return issues


def render_index(
    root: Path,
    adapters: dict[tuple[str, str], dict[str, Any]],
    policy: dict[str, Any],
    policy_path: Path | None = None,
    lane_inventory: dict[str, dict[str, set[str]]] | None = None,
    source_entries: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> str:
    path = policy_path or root / POLICY_RELATIVE
    inventory = lane_inventory or {
        lane: {field: set() for field in CAPABILITY_FIELDS} for lane in LANES
    }
    if source_entries is not None:
        source_index = []
        for (specialist, lane), entry in sorted(source_entries.items()):
            adapter = adapters.get((specialist, lane), {})
            source_index.append({
                "adapter": adapter.get("adapter"),
                "coverage": entry["coverage"],
                "known_unavailable": {
                    field: [
                        {
                            "availability": ref.availability,
                            "evidence": ref.evidence,
                            "id": ref.identifier,
                            "requirement": ref.requirement,
                        }
                        for ref in entry[field]
                        if ref.availability != "available"
                    ]
                    for field in CAPABILITY_FIELDS
                },
                "lane": lane,
                "limitations": list(entry["limitations"]),
                "mcps": list(available_arrays(source_entries, specialist, lane)["mcps"]),
                "primary_plan": [
                    {
                        "capability_id": item.capability_id,
                        "evidence": item.evidence,
                        "id": item.identifier,
                        "kind": item.kind,
                        "provider_lane": item.provider_lane,
                        "resolution": item.resolution,
                    }
                    for item in entry.get("primary_requirements", ())
                ],
                "skills": list(available_arrays(source_entries, specialist, lane)["skills"]),
                "specialist": specialist,
                "tools": list(available_arrays(source_entries, specialist, lane)["tools"]),
            })
        payload = {
            "baseline_ref": policy["baseline_ref"],
            "generated": True,
            "policy_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "schema": INDEX_SCHEMA,
            "source": SOURCE_RELATIVE.as_posix(),
            "source_sha256": source_sha256(root),
            "entries": source_index,
        }
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    entries = []
    for adapter in adapters.values():
        lane_wide = {
            field: set(inventory[adapter["lane"]][field])
            | {
                item.removeprefix("lead:")
                for item in inventory[adapter["lane"]][field]
            }
            for field in CAPABILITY_FIELDS
        }
        legacy_native_mirror = adapter["lane"] == "gemini" and all(
            set(adapter[field]) <= lane_wide[field] for field in CAPABILITY_FIELDS
        )
        if not adapter.get("lane_native_mirror") and not legacy_native_mirror:
            lane_wide = {field: set() for field in CAPABILITY_FIELDS}
        entries.append(
            {
                "adapter": adapter["adapter"],
                "lane": adapter["lane"],
                "mcps": sorted(set(adapter["mcps"]) - lane_wide["mcps"]),
                "skills": sorted(set(adapter["skills"]) - lane_wide["skills"]),
                "specialist": adapter["specialist"],
                "tools": sorted(set(adapter["tools"]) - lane_wide["tools"]),
            }
        )
    payload = {
        "baseline_ref": policy["baseline_ref"],
        "generated": True,
        "policy_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schema": INDEX_SCHEMA,
        "source": "structured per-lane adapter capability fields; generated native mirrors subtract lane-wide inventory",
        "entries": sorted(entries, key=lambda item: (item["specialist"], item["lane"])),
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def index_freshness_diagnostics(root: Path, expected: str) -> list[dict[str, Any]]:
    path = root / INDEX_RELATIVE
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError:
        actual = ""
    if actual == expected:
        return []
    return [
        diagnostic(
            "index-freshness",
            INDEX_RELATIVE.as_posix(),
            "generated-index",
            "generated capability index is missing or stale; run with --write-index",
            kind="schema",
        )
    ]


def validate_repository(
    root: Path,
    policy_path: Path | None = None,
    only: set[str] | None = None,
    write_index: bool = False,
    namespace: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = load_policy(root, policy_path)
    rows = runtime_rows(root)
    adapters, issues = load_adapters(root, rows)
    baseline = load_baseline(root, rows, policy)
    lane_inventory = load_lane_inventory(root)
    source_entries, _source_payload = load_source(root)
    enabled = only or {"boundary", "parity", "existence", "source", "required", "index"}
    expected_index = render_index(
        root, adapters, policy, policy_path, lane_inventory=lane_inventory, source_entries=source_entries
    )
    if write_index:
        path = root / INDEX_RELATIVE
        atomic_write_text(path, expected_index)
    if "boundary" in enabled:
        boundary_rows = rows if namespace is None else {
            key: value for key, value in rows.items()
            if value.get("source_namespace") == namespace
        }
        issues.extend(base_boundary_diagnostics(root, boundary_rows, policy, baseline))
    if "parity" in enabled:
        parity_rows = rows if namespace is None else {key: value for key, value in rows.items() if value.get("source_namespace") == namespace}
        issues.extend(migration_parity_diagnostics(parity_rows, adapters, baseline, source_entries))
    if "existence" in enabled:
        scoped_source = source_entries if namespace is None else {key: value for key, value in source_entries.items() if rows[key[0]].get("source_namespace") == namespace}
        issues.extend(source_existence_diagnostics(root, scoped_source, lane_inventory=lane_inventory))
    if "source" in enabled:
        issues.extend(source_coverage_diagnostics(rows, source_entries))
        issues.extend(adapter_source_sync_diagnostics(root, adapters, source_entries))
    if "required" in enabled:
        issues.extend(required_primary_diagnostics(rows, source_entries, root=root, namespace=namespace))
    if "index" in enabled:
        issues.extend(index_freshness_diagnostics(root, expected_index))
    issues.sort(
        key=lambda item: (
            item["check"], item["path"], item["line"], item["kind"], item["identifier"]
        )
    )
    summary = {
        "adapters": len(adapters),
        "baseline_ref": policy["baseline_ref"],
        "checks": sorted(enabled),
        "diagnostics": len(issues),
        "index": INDEX_RELATIVE.as_posix(),
        "schema": "capability-home-validation/v1",
        "source_entries": len(source_entries),
        "status": "fail" if issues else "pass",
    }
    return issues, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--policy")
    parser.add_argument(
        "--only",
        help="comma-separated subset: boundary,parity,existence,index",
    )
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--namespace", help="limit boundary/parity/existence/required checks to one source namespace")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    allowed = {"boundary", "parity", "existence", "source", "required", "index"}
    only = None
    if args.only:
        only = {item.strip() for item in args.only.split(",") if item.strip()}
        unknown = only - allowed
        if unknown:
            parser.error(f"unknown --only check(s): {','.join(sorted(unknown))}")
    try:
        issues, summary = validate_repository(
            root,
            Path(args.policy).resolve() if args.policy else None,
            only=only,
            write_index=args.write_index,
            namespace=args.namespace,
        )
    except (
        CapabilityHomeError,
        CapabilitySourceError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(
            json.dumps(
                {"check": "configuration", "message": str(exc), "status": "error"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    for issue in issues:
        print(json.dumps(issue, sort_keys=True, ensure_ascii=False))
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
