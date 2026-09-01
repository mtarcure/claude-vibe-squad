#!/usr/bin/env python3
"""Generate runtime-map tool summaries from the specialist capability source."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from specialist_capability_source import AVAILABILITY_STATES, atomic_write_text


SOURCE_RELATIVE = Path("model-lanes/specialist-lane-capabilities.v1.json")
RUNTIME_MAP_RELATIVE = Path("shared/specialist-runtime-map.tsv")
SOURCE_SCHEMA = "specialist-lane-capabilities/v1"
TOOL_COLUMNS = ("required_tools", "preferred_tools")
LANE_NAMES = {
    "codex": "gpt-codex",
    "claude": "claude",
    "gemini": "gemini",
    "grok": "grok",
    "kimi": "kimi",
}
# Only these availability states feed the runtime-map tool summary. Every other
# state — including the Wave 1 (2026-07-26) typed states (authored:stub,
# needs-operator-install, platform-unavailable, project-dependency, superseded)
# and the pre-existing non-usable states (uninstalled, probe-failed,
# harness-only, pending-restart-activation) — is intentionally NOT projected: a
# tool that is a stub, OS-impossible, a project dependency, dead, or absent must
# not appear as a live required/preferred tool. This set is a subset of the
# authoritative ``AVAILABILITY_STATES`` enum, asserted below so a renamed or
# typo'd state fails loudly instead of silently dropping out of the summary.
PROJECTABLE_AVAILABILITY = frozenset(
    ("available", "installed-skill-root", "mcp-operation")
)
assert PROJECTABLE_AVAILABILITY <= set(AVAILABILITY_STATES), (
    "PROJECTABLE_AVAILABILITY drifted from the availability enum"
)


class RuntimeToolSummaryError(RuntimeError):
    """Raised when the capability source cannot produce a closed projection."""


def load_payload(root: Path) -> dict[str, Any]:
    path = root / SOURCE_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeToolSummaryError(f"cannot load {path}: {exc}") from exc
    if payload.get("schema") != SOURCE_SCHEMA or payload.get("version") != 1:
        raise RuntimeToolSummaryError("capability source schema/version mismatch")
    return payload


def load_runtime_rows(
    root: Path, runtime_path: Path | None = None
) -> dict[str, dict[str, str]]:
    path = runtime_path or root / RUNTIME_MAP_RELATIVE
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise RuntimeToolSummaryError(f"cannot load {path}: {exc}") from exc
    return {row["specialist"]: row for row in rows}


def server_relations(payload: dict[str, Any]) -> dict[str, frozenset[str]]:
    raw_servers = payload.get("servers")
    if not isinstance(raw_servers, list):
        raise RuntimeToolSummaryError("capability source servers must be a list")
    result: dict[str, frozenset[str]] = {}
    order: list[str] = []
    for raw in raw_servers:
        if not isinstance(raw, dict):
            raise RuntimeToolSummaryError("server relation must be an object")
        identifier = raw.get("id")
        provides = raw.get("provides")
        if not isinstance(identifier, str) or not identifier:
            raise RuntimeToolSummaryError("server relation requires a non-empty id")
        if (
            not isinstance(provides, list)
            or not all(isinstance(item, str) and item for item in provides)
            or provides != sorted(provides, key=str.casefold)
            or len(provides) != len(set(provides))
        ):
            raise RuntimeToolSummaryError(
                f"server {identifier}: provides must be a sorted unique string list"
            )
        if identifier in result:
            raise RuntimeToolSummaryError(f"duplicate server relation {identifier}")
        result[identifier] = frozenset(provides)
        order.append(identifier)
    if order != sorted(order, key=str.casefold):
        raise RuntimeToolSummaryError("server relations must be sorted by id")
    return result


def canonical_server(identifier: str) -> str:
    return identifier.removeprefix("lead:")


def project_payload(
    payload: dict[str, Any],
    runtime_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, tuple[str, ...]]]:
    relations = server_relations(payload)
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in payload.get("entries", []):
        key = (entry.get("specialist"), entry.get("lane"))
        if key in entries:
            raise RuntimeToolSummaryError(f"duplicate source entry {key[0]}:{key[1]}")
        entries[key] = entry

    projection: dict[str, dict[str, tuple[str, ...]]] = {}
    for specialist, row in sorted(runtime_rows.items()):
        lane = LANE_NAMES.get(row.get("primary_lane", ""))
        if lane is None:
            raise RuntimeToolSummaryError(
                f"{specialist}: invalid primary lane {row.get('primary_lane')!r}"
            )
        entry = entries.get((specialist, lane))
        if entry is None or entry.get("coverage") != "full":
            raise RuntimeToolSummaryError(
                f"{specialist}:{lane}: primary source entry must have full coverage"
            )
        levels: dict[str, str] = {}

        def add(identifier: str, requirement: str) -> None:
            canonical = canonical_server(identifier)
            if requirement == "required" or canonical not in levels:
                levels[canonical] = requirement

        for ref in entry.get("mcps", []):
            availability = ref.get("availability")
            if availability not in AVAILABILITY_STATES:
                raise RuntimeToolSummaryError(
                    f"{specialist}:{lane}:{ref.get('id')}: unknown availability {availability!r}"
                )
            if availability in PROJECTABLE_AVAILABILITY:
                add(ref["id"], ref["requirement"])
        for ref in entry.get("tools", []):
            availability = ref.get("availability")
            if availability not in AVAILABILITY_STATES:
                raise RuntimeToolSummaryError(
                    f"{specialist}:{lane}:{ref.get('id')}: unknown availability {availability!r}"
                )
            provider = ref.get("provided_by")
            if ref.get("availability") == "mcp-operation" and not provider:
                raise RuntimeToolSummaryError(
                    f"{specialist}:{lane}:{ref.get('id')}: "
                    "MCP operation lacks provided_by"
                )
            if not provider:
                continue
            if provider not in relations or ref.get("id") not in relations[provider]:
                raise RuntimeToolSummaryError(
                    f"{specialist}:{lane}:{ref.get('id')}: "
                    f"provider relation {provider!r} is not reciprocal"
                )
            if ref.get("availability") in PROJECTABLE_AVAILABILITY:
                add(provider, ref["requirement"])
        required = tuple(
            sorted(
                (identifier for identifier, level in levels.items() if level == "required"),
                key=str.casefold,
            )
        )
        preferred = tuple(
            sorted(
                (identifier for identifier, level in levels.items() if level == "preferred"),
                key=str.casefold,
            )
        )
        projection[specialist] = {
            "required_tools": required,
            "preferred_tools": preferred,
        }
    return projection


def project_runtime_tools(
    root: Path, runtime_path: Path | None = None
) -> dict[str, dict[str, tuple[str, ...]]]:
    return project_payload(
        load_payload(root),
        load_runtime_rows(root, runtime_path),
    )


def format_tool_list(values: tuple[str, ...]) -> str:
    return f"[{', '.join(values)}]" if values else "[]"


def render_runtime_map(
    root: Path, runtime_path: Path | None = None
) -> str:
    path = runtime_path or root / RUNTIME_MAP_RELATIVE
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise RuntimeToolSummaryError("runtime map is empty")
    header = lines[0].split("\t")
    try:
        specialist_index = header.index("specialist")
        required_index = header.index("required_tools")
        preferred_index = header.index("preferred_tools")
    except ValueError as exc:
        raise RuntimeToolSummaryError("runtime map lacks generated tool columns") from exc
    projection = project_runtime_tools(root, path)
    rendered = [lines[0]]
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != len(header):
            raise RuntimeToolSummaryError(f"malformed runtime-map row: {line!r}")
        specialist = fields[specialist_index]
        summary = projection.get(specialist)
        if summary is None:
            raise RuntimeToolSummaryError(
                f"{specialist}: runtime row has no generated projection"
            )
        fields[required_index] = format_tool_list(summary["required_tools"])
        fields[preferred_index] = format_tool_list(summary["preferred_tools"])
        rendered.append("\t".join(fields))
    return "\n".join(rendered) + "\n"


def write_runtime_map(root: Path, runtime_path: Path | None = None) -> None:
    path = runtime_path or root / RUNTIME_MAP_RELATIVE
    atomic_write_text(path, render_runtime_map(root, path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero when the tracked runtime map differs from the projection",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically update the runtime-map generated tool columns",
    )
    args = parser.parse_args(argv)
    if args.check == args.write:
        parser.error("choose exactly one of --check or --write")
    root = Path(args.repo_root).resolve()
    path = root / RUNTIME_MAP_RELATIVE
    try:
        expected = render_runtime_map(root, path)
    except (OSError, RuntimeToolSummaryError) as exc:
        print(f"FAIL runtime-tool-summary: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if path.read_text(encoding="utf-8") != expected:
            print(
                "FAIL runtime-tool-summary: generated tool columns are stale; "
                "run with --write",
                file=sys.stderr,
            )
            return 1
        print("PASS runtime-tool-summary")
        return 0
    atomic_write_text(path, expected)
    print("PASS runtime-tool-summary: updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
