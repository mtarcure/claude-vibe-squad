#!/usr/bin/env python3
"""Generate or check thin native adapters for every ranked route of a specialist."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "python"))
from lane_adapter_registry import (  # noqa: E402
    AdapterValidationError,
    render_adapter as render_registry_adapter,
    render_kimi_prompt,
    upsert_capability_projection,
    validate_adapter_file,
)
from specialist_capability_source import atomic_write_text  # noqa: E402


RUNTIME_MAP = REPO / "shared" / "specialist-runtime-map.tsv"
PROFILE_REGISTRY = REPO / "shared" / "registries" / "profiles.tsv"
ROUTE_FIELDS = (
    "primary_lane",
    "backup_lane",
    "escalate_lane",
    "review_lane",
    "throughput_lane",
)


def normalize_lane(lane: str) -> str:
    return "codex" if lane == "gpt-codex" else lane


def load_profiles() -> dict[str, dict[str, str]]:
    with PROFILE_REGISTRY.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    profiles = {row["profile_id"]: row for row in rows}
    if len(profiles) != len(rows):
        raise AdapterValidationError("profile registry contains duplicate profile IDs")
    return profiles


def routed_profile_model(
    lane: str,
    row: dict[str, str],
    profiles: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Resolve the first ranked route for a lane to its registry model ID."""

    map_lane = normalize_lane(lane)
    for lane_field in ROUTE_FIELDS:
        if row[lane_field] != map_lane:
            continue
        profile_field = lane_field.removesuffix("_lane") + "_profile"
        profile_id = row[profile_field]
        profile = profiles.get(profile_id)
        if profile is None:
            raise AdapterValidationError(
                f"{row['specialist']}: routed profile {profile_id!r} is missing"
            )
        if profile["lane"] != map_lane:
            raise AdapterValidationError(
                f"{row['specialist']}: profile {profile_id!r} belongs to "
                f"{profile['lane']!r}, not {map_lane!r}"
            )
        model_id = profile["model_id"].strip()
        if not model_id or model_id == "none":
            raise AdapterValidationError(
                f"{row['specialist']}: profile {profile_id!r} does not pin a model_id"
            )
        return profile_id, model_id
    raise AdapterValidationError(
        f"{row['specialist']}: lane {map_lane!r} has no ranked route"
    )


def pin_routed_model(
    lane: str,
    row: dict[str, str],
    profiles: dict[str, dict[str, str]],
    text: str,
) -> str:
    """Apply an exact model only where the native adapter overrides inheritance."""

    if lane != "kimi":
        return text
    _profile_id, model_id = routed_profile_model(lane, row, profiles)
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith("  model:")]
    if len(matches) != 1:
        raise AdapterValidationError(
            f"{row['specialist']}: Kimi adapter must contain exactly one model pin"
        )
    index = matches[0]
    newline = "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"  model: {model_id}{newline}"
    return "".join(lines)


def adapter_model_pin(text: str) -> str:
    pins = [
        line.removeprefix("  model:").strip()
        for line in text.splitlines()
        if line.startswith("  model:")
    ]
    return pins[0] if len(pins) == 1 else ""


def canonical_brief(row: dict[str, str]) -> Path:
    namespace = row["source_namespace"]
    if namespace == "shared":
        return Path("shared") / "specialists" / f"{row['specialist']}.md"
    return Path("departments") / namespace / "specialists" / f"{row['specialist']}.md"


def ranked_lanes(row: dict[str, str]) -> list[str]:
    lanes: list[str] = []
    for field in ROUTE_FIELDS:
        lane = row[field]
        if lane == "none":
            continue
        lane = "gpt-codex" if lane == "codex" else lane
        if lane not in lanes:
            lanes.append(lane)
    return lanes


def target_for(lane: str, specialist: str) -> Path:
    targets = {
        "claude": REPO / "model-lanes" / "claude" / ".claude" / "agents" / f"{specialist}.md",
        "gpt-codex": REPO / "model-lanes" / "gpt-codex" / ".codex" / "agents" / f"{specialist}.toml",
        "gemini": REPO / "model-lanes" / "gemini" / ".gemini" / "agents" / f"{specialist}.md",
        "kimi": REPO / "model-lanes" / "kimi" / ".kimi" / "agents" / f"{specialist}.yaml",
    }
    return targets[lane]


def render(lane: str, row: dict[str, str]) -> str:
    return render_registry_adapter(REPO, lane, row["specialist"])


def load_rows() -> dict[str, dict[str, str]]:
    with RUNTIME_MAP.open(newline="", encoding="utf-8") as handle:
        return {row["specialist"]: row for row in csv.DictReader(handle, delimiter="\t")}


def register_kimi_specialist(specialist: str) -> None:
    main_path = REPO / "model-lanes" / "kimi" / "main.yaml"
    text = main_path.read_text(encoding="utf-8")
    if f"    {specialist}:" in text:
        return
    anchor = "  subagents:\n"
    if anchor not in text:
        raise AdapterValidationError("Kimi main.yaml lacks the subagents registry")
    block = (
        anchor
        + f"    {specialist}:\n"
        + f"      path: ./.kimi/agents/{specialist}.yaml\n"
        + "      description: \"Registry-generated thin specialist adapter.\"\n"
    )
    atomic_write_text(main_path, text.replace(anchor, block, 1))


def adapter_is_valid(
    lane: str,
    row: dict[str, str],
    target: Path,
    profiles: dict[str, dict[str, str]],
) -> tuple[bool, list[str]]:
    if not target.is_file():
        return False, ["missing"]
    try:
        validate_adapter_file(REPO, lane, target)
    except AdapterValidationError as exc:
        return False, [str(exc)]
    if lane == "kimi":
        profile_id, expected_model = routed_profile_model(lane, row, profiles)
        actual_model = adapter_model_pin(target.read_text(encoding="utf-8"))
        if actual_model != expected_model:
            return False, [
                "kimi-model-pin-mismatch:"
                f"profile={profile_id}:expected={expected_model}:actual={actual_model or 'missing'}"
            ]
        main = (REPO / "model-lanes" / "kimi" / "main.yaml").read_text(encoding="utf-8")
        registration = (
            f"    {row['specialist']}:\n"
            f"      path: ./.kimi/agents/{row['specialist']}.yaml"
        )
        if registration not in main:
            return False, ["kimi-main-registration-missing"]
    return True, []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check ranked-route adapter coverage, or create missing thin adapters."
    )
    parser.add_argument("specialists", nargs="+", help="canonical specialist IDs")
    parser.add_argument("--write", action="store_true", help="create missing adapters")
    args = parser.parse_args()

    rows = load_rows()
    profiles = load_profiles()
    failed = False
    for specialist in args.specialists:
        row = rows.get(specialist)
        if row is None:
            print(json.dumps({"specialist": specialist, "status": "unknown"}))
            failed = True
            continue
        brief = REPO / canonical_brief(row)
        if not brief.is_file():
            print(json.dumps({"specialist": specialist, "status": "canonical-brief-missing"}))
            failed = True
            continue
        for lane in ranked_lanes(row):
            target = target_for(lane, specialist)
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    updated = upsert_capability_projection(
                        REPO, lane, specialist, target.read_text(encoding="utf-8")
                    )
                else:
                    updated = render(lane, row)
                updated = pin_routed_model(lane, row, profiles, updated)
                if not target.is_file() or target.read_text(encoding="utf-8") != updated:
                    atomic_write_text(target, updated)
                if lane == "kimi":
                    prompt = REPO / "model-lanes" / "kimi" / ".kimi" / "prompts" / f"{specialist}.md"
                    prompt.parent.mkdir(parents=True, exist_ok=True)
                    rendered_prompt = render_kimi_prompt(REPO, specialist)
                    if not prompt.is_file() or prompt.read_text(encoding="utf-8") != rendered_prompt:
                        atomic_write_text(prompt, rendered_prompt)
                    register_kimi_specialist(specialist)
            valid, issues = adapter_is_valid(lane, row, target, profiles)
            print(
                json.dumps(
                    {
                        "specialist": specialist,
                        "lane": lane,
                        "adapter": str(target.relative_to(REPO)),
                        "status": "pass" if valid else "fail",
                        "issues": issues,
                    },
                    sort_keys=True,
                )
            )
            failed |= not valid
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
