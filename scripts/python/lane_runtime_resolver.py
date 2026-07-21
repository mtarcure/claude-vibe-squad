#!/usr/bin/env python3
"""Fail-closed model-lane resolver for headless specialist dispatch.

The V2 shell entrypoint delegates policy resolution, argv construction, and
child-only environment filtering here so secrets are never interpolated into
a shell command or emitted in a receipt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Mapping


LANES = {"codex", "claude", "gemini", "kimi"}
LANE_ALIASES = {"gpt-codex": "codex"}
SPECIALIST_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)
RUNTIME_HEADER = (
    "specialist",
    "source_namespace",
    "capability_class",
    "safety_level",
    "safety_tags",
    "tool_profile",
    "primary_lane",
    "primary_profile",
    "backup_lane",
    "backup_profile",
    "escalate_lane",
    "escalate_profile",
    "escalation_policy",
    "review_lane",
    "review_profile",
    "anti_affinity",
    "throughput_lane",
    "throughput_profile",
    "throughput_policy",
    "failover_policy",
    "operator_gate",
    "heightened_risk",
    "requires_approval",
    "required_tools",
    "preferred_tools",
    "notes",
    "tags",
    "version",
    "operator_model_consult",
)
LEGACY_RUNTIME_HEADER = RUNTIME_HEADER[:-1]
ROUTE_FIELDS = (
    ("primary", "primary_lane", "primary_profile"),
    ("backup", "backup_lane", "backup_profile"),
    ("escalate", "escalate_lane", "escalate_profile"),
    ("review", "review_lane", "review_profile"),
    ("throughput", "throughput_lane", "throughput_profile"),
)


class ResolverError(RuntimeError):
    """A preflight invariant failed; no provider process may be started."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path: Path, label: str) -> str:
    if not path.is_file():
        raise ResolverError(f"{label} does not exist: {path}")
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def _normalized_lane(value: str) -> str:
    lane = LANE_ALIASES.get(value.strip(), value.strip())
    if lane not in LANES:
        raise ResolverError(f"unsupported model lane: {value}")
    return lane


def _safe_repo_path(repo_root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ResolverError(f"{label} escapes repository root: {resolved}") from exc
    return resolved


def _load_runtime_row(repo_root: Path, specialist: str) -> dict[str, str]:
    map_path = repo_root / "shared" / "specialist-runtime-map.tsv"
    text = _read_text(map_path, "runtime map")
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    header = tuple(reader.fieldnames or ())
    if header not in (RUNTIME_HEADER, LEGACY_RUNTIME_HEADER):
        raise ResolverError(
            "runtime map header does not match the canonical 28- or 29-field schema"
        )
    matches = [row for row in reader if row.get("specialist") == specialist]
    if len(matches) != 1:
        raise ResolverError(
            f"expected exactly one runtime-map row for {specialist}; found {len(matches)}"
        )
    if any(value is None for value in matches[0].values()):
        raise ResolverError(f"runtime-map row for {specialist} is malformed")
    row = dict(matches[0])
    row["operator_model_consult"] = row.get("operator_model_consult") or "false"
    if row["operator_model_consult"] not in {"true", "false"}:
        raise ResolverError(
            f"runtime-map row for {specialist} has invalid operator_model_consult"
        )
    return row


def _load_profile(repo_root: Path, profile_id: str, lane: str) -> dict[str, str]:
    path = repo_root / "shared" / "registries" / "profiles.tsv"
    text = _read_text(path, "profile registry")
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    required = {"profile_id", "lane", "model_id", "effort", "flags", "usage"}
    if not required.issubset(set(reader.fieldnames or ())):
        raise ResolverError("profile registry is missing required fields")
    matches = [row for row in reader if row.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise ResolverError(f"expected exactly one profile row for {profile_id}; found {len(matches)}")
    profile = matches[0]
    if profile["lane"] != lane:
        raise ResolverError(
            f"profile {profile_id} belongs to lane {profile['lane']}, not selected lane {lane}"
        )
    if not profile["model_id"] or profile["model_id"] == "none":
        raise ResolverError(f"profile {profile_id} has no pinned model")
    return profile


def _select_route(row: Mapping[str, str], requested_lane: str | None) -> tuple[str, str, str]:
    if requested_lane is None:
        lane = _normalized_lane(row["primary_lane"])
        return lane, "primary", row["primary_profile"]
    lane = _normalized_lane(requested_lane)
    for route_name, lane_field, profile_field in ROUTE_FIELDS:
        if row[lane_field] == lane:
            profile = row[profile_field]
            if not profile or profile == "none":
                raise ResolverError(f"eligible {route_name} route for {lane} has no profile")
            return lane, route_name, profile
    raise ResolverError(f"lane {lane} is not an eligible route for {row['specialist']}")


def _canonical_path(repo_root: Path, namespace: str, specialist: str) -> Path:
    if namespace == "shared":
        path = repo_root / "shared" / "specialists" / f"{specialist}.md"
    else:
        path = repo_root / "departments" / namespace / "specialists" / f"{specialist}.md"
    return _safe_repo_path(repo_root, path, "canonical prompt")


def _adapter_path(repo_root: Path, lane: str, specialist: str) -> Path:
    if lane == "codex":
        path = repo_root / "model-lanes" / "gpt-codex" / ".codex" / "agents" / f"{specialist}.toml"
    elif lane == "claude":
        path = repo_root / "model-lanes" / "claude" / ".claude" / "agents" / f"{specialist}.md"
    elif lane == "gemini":
        path = repo_root / "model-lanes" / "gemini" / ".gemini" / "agents" / f"{specialist}.md"
    else:
        path = repo_root / "model-lanes" / "kimi" / ".kimi" / "agents" / f"{specialist}.yaml"
    return _safe_repo_path(repo_root, path, "native adapter")


def _validate_canonical(text: str, specialist: str, path: Path) -> None:
    identity = _frontmatter(text).get("specialist")
    if identity != specialist:
        raise ResolverError(
            f"canonical prompt identity mismatch at {path}: expected {specialist}, got {identity or 'missing'}"
        )


def _validate_adapter(text: str, lane: str, specialist: str, path: Path) -> str:
    expected = specialist.replace("-", "_") if lane == "codex" else specialist
    if lane == "codex":
        try:
            identity = str(tomllib.loads(text).get("name", ""))
        except tomllib.TOMLDecodeError as exc:
            raise ResolverError(f"invalid Codex adapter TOML at {path}: {exc}") from exc
    elif lane in {"claude", "gemini"}:
        identity = _frontmatter(text).get("name", "")
    else:
        match = re.search(r"(?m)^\s{2}name:\s*['\"]?([^'\"\s#]+)", text)
        identity = match.group(1) if match else ""
        prompt_match = re.search(r"(?m)^\s{2}system_prompt_path:\s*['\"]?([^'\"\s#]+)", text)
        if prompt_match:
            target = _safe_repo_path(path.parents[2], path.parent / prompt_match.group(1), "Kimi system prompt")
            _read_text(target, "Kimi system prompt")
    if identity != expected:
        raise ResolverError(
            f"adapter identity mismatch at {path}: expected {expected}, got {identity or 'missing'}"
        )
    return identity


def _task_context(
    repo_root: Path,
    task_file: str | Path | None,
    specialist: str,
    requested_lane: str | None,
) -> tuple[str, str | None]:
    if task_file is None:
        return f"Execute the {specialist} specialist assignment supplied by the caller.", requested_lane
    candidate = Path(task_file)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    task_path = _safe_repo_path(repo_root, candidate, "task packet")
    task_text = _read_text(task_path, "task packet")
    metadata = _frontmatter(task_text)
    task_specialist = metadata.get("specialist")
    if task_specialist and task_specialist != specialist:
        raise ResolverError(
            f"task specialist {task_specialist} does not match requested specialist {specialist}"
        )
    task_lane = metadata.get("to_model")
    if task_lane:
        normalized_task_lane = _normalized_lane(task_lane)
        if requested_lane and _normalized_lane(requested_lane) != normalized_task_lane:
            raise ResolverError("explicit lane conflicts with task packet to_model")
        requested_lane = normalized_task_lane
    return task_text, requested_lane


def _auth_policy(lane: str, environ: Mapping[str, str]) -> dict[str, object]:
    if lane == "gemini":
        if not environ.get("GEMINI_API_KEY"):
            raise ResolverError("Gemini route requires a non-empty GEMINI_API_KEY")
        return {
            "kind": "api-key",
            "drop": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"],
            "preserve": ["GEMINI_API_KEY"],
            "required": "GEMINI_API_KEY",
        }
    kind = "subscription" if lane in {"codex", "claude"} else "managed-login"
    return {
        "kind": kind,
        "drop": list(PROVIDER_KEYS),
        "preserve": [],
        "required": None,
    }


def _composed_prompt(adapter_text: str, canonical_text: str, task_text: str) -> str:
    return (
        "Use the following validated native adapter and canonical specialist brief. "
        "The task packet remains authoritative for scope.\n\n"
        "<native_adapter>\n"
        + adapter_text
        + "\n</native_adapter>\n\n<canonical_specialist>\n"
        + canonical_text
        + "\n</canonical_specialist>\n\n<task_packet>\n"
        + task_text
        + "\n</task_packet>"
    )


def _build_argv(
    repo_root: Path,
    lane: str,
    specialist: str,
    native_name: str,
    adapter_path: Path,
    adapter_text: str,
    canonical_text: str,
    task_text: str,
    profile: Mapping[str, str],
) -> tuple[list[str], list[str], str, str]:
    root = str(repo_root)
    model = profile["model_id"]
    effort = profile["effort"]
    composed = _composed_prompt(adapter_text, canonical_text, task_text)
    if lane == "codex":
        argv = [
            "codex",
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "-c",
            f'model_reasoning_effort="{effort}"',
            "--model",
            model,
            "--cd",
            root,
            "--add-dir",
            root,
            "exec",
            composed,
        ]
        display = argv[:-1] + [f"<prompt sha256={_sha256_text(composed)}>"]
        return argv, display, "composed-validated", effort
    if lane == "claude":
        agent_definition = json.dumps(
            {
                native_name: {
                    "description": f"Validated repo adapter for {specialist}",
                    "prompt": adapter_text + "\n\n" + canonical_text,
                }
            },
            separators=(",", ":"),
        )
        argv = [
            "claude",
            "--print",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--model",
            model,
            "--fallback-model",
            "claude-opus-4-8,claude-sonnet-5",
            "--effort",
            effort,
            "--add-dir",
            root,
            "--agents",
            agent_definition,
            "--agent",
            native_name,
            task_text,
        ]
        display = list(argv)
        display[display.index(agent_definition)] = f"<agent-definition sha256={_sha256_text(agent_definition)}>"
        display[-1] = f"<prompt sha256={_sha256_text(task_text)}>"
        return argv, display, "native", effort
    if lane == "gemini":
        argv = [
            "gemini",
            "--skip-trust",
            "--approval-mode",
            "default",
            "--model",
            model,
            "--include-directories",
            root,
            "--prompt",
            composed,
        ]
        display = argv[:-1] + [f"<prompt sha256={_sha256_text(composed)}>"]
        return argv, display, "composed-validated", effort
    kimi_prompt = (
        "Follow the canonical specialist brief below, then execute the task packet.\n\n"
        "<canonical_specialist>\n"
        + canonical_text
        + "\n</canonical_specialist>\n\n<task_packet>\n"
        + task_text
        + "\n</task_packet>"
    )
    argv = [
        "kimi",
        "--work-dir",
        root,
        "--add-dir",
        root,
        "--thinking",
        "--model",
        model,
        "--agent-file",
        str(adapter_path),
        "--quiet",
        "--prompt",
        kimi_prompt,
    ]
    display = argv[:-1] + [f"<prompt sha256={_sha256_text(kimi_prompt)}>"]
    return argv, display, "native", "thinking"


def resolve_runtime(
    repo_root: str | Path,
    specialist: str,
    requested_lane: str | None = None,
    task_file: str | Path | None = None,
    expected_source_namespace: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    if not SPECIALIST_RE.fullmatch(specialist):
        raise ResolverError(f"invalid specialist name: {specialist}")
    env = os.environ if environ is None else environ
    task_text, requested_lane = _task_context(root, task_file, specialist, requested_lane)
    row = _load_runtime_row(root, specialist)
    if expected_source_namespace and row["source_namespace"] != expected_source_namespace:
        raise ResolverError(
            f"source namespace mismatch: map={row['source_namespace']} caller={expected_source_namespace}"
        )
    lane, route_field, profile_id = _select_route(row, requested_lane)
    profile = _load_profile(root, profile_id, lane)
    canonical_path = _canonical_path(root, row["source_namespace"], specialist)
    canonical_text = _read_text(canonical_path, "canonical prompt")
    _validate_canonical(canonical_text, specialist, canonical_path)
    adapter_path = _adapter_path(root, lane, specialist)
    adapter_text = _read_text(adapter_path, "native adapter")
    native_name = _validate_adapter(adapter_text, lane, specialist, adapter_path)
    auth = _auth_policy(lane, env)
    argv, display_argv, adapter_mode, reasoning = _build_argv(
        root,
        lane,
        specialist,
        native_name,
        adapter_path,
        adapter_text,
        canonical_text,
        task_text,
        profile,
    )
    return {
        "schema": "lane-runtime-resolver/v2",
        "repo_root": str(root),
        "specialist": specialist,
        "source_namespace": row["source_namespace"],
        "operator_model_consult": row["operator_model_consult"] == "true",
        "lane": lane,
        "route_field": route_field,
        "profile": profile_id,
        "model": profile["model_id"],
        "effort": profile["effort"],
        "profile_flags": profile["flags"],
        "reasoning": reasoning,
        "auth": auth,
        "canonical_prompt": str(canonical_path),
        "canonical_sha256": _sha256_text(canonical_text),
        "adapter": str(adapter_path),
        "adapter_sha256": _sha256_text(adapter_text),
        "adapter_name": native_name,
        "adapter_mode": adapter_mode,
        "task_sha256": _sha256_text(task_text),
        "argv": argv,
        "display_argv": display_argv,
        "cli": argv[0],
        "cli_present": shutil.which(argv[0], path=env.get("PATH")) is not None,
    }


def build_child_environment(
    plan: Mapping[str, object], parent_environment: Mapping[str, str]
) -> dict[str, str]:
    child = dict(parent_environment)
    auth = plan["auth"]
    assert isinstance(auth, dict)
    for key in auth["drop"]:
        child.pop(str(key), None)
    return child


def sanitized_receipt(
    plan: Mapping[str, object], environ: Mapping[str, str]
) -> dict[str, object]:
    auth = plan["auth"]
    assert isinstance(auth, dict)
    required = auth["required"]
    return {
        "schema": plan["schema"],
        "specialist": plan["specialist"],
        "source_namespace": plan["source_namespace"],
        "operator_model_consult": plan["operator_model_consult"],
        "lane": plan["lane"],
        "route_field": plan["route_field"],
        "profile": plan["profile"],
        "model": plan["model"],
        "effort": plan["effort"],
        "profile_flags": plan["profile_flags"],
        "reasoning": plan["reasoning"],
        "auth": {
            "kind": auth["kind"],
            "dropped_env": auth["drop"],
            "preserved_env": auth["preserve"],
            "required_env": required,
            "required_env_present": bool(required and environ.get(str(required))) if required else True,
        },
        "canonical_prompt": plan["canonical_prompt"],
        "canonical_sha256": plan["canonical_sha256"],
        "adapter": plan["adapter"],
        "adapter_sha256": plan["adapter_sha256"],
        "adapter_name": plan["adapter_name"],
        "adapter_mode": plan["adapter_mode"],
        "task_sha256": plan["task_sha256"],
        "cli": plan["cli"],
        "cli_present": plan["cli_present"],
        "argv": plan["display_argv"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--specialist", required=True)
    parser.add_argument("--task-file")
    parser.add_argument("--lane")
    parser.add_argument("--expected-source-namespace")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = resolve_runtime(
            repo_root=args.repo_root,
            specialist=args.specialist,
            requested_lane=args.lane,
            task_file=args.task_file,
            expected_source_namespace=args.expected_source_namespace,
            environ=os.environ,
        )
        receipt = sanitized_receipt(plan, os.environ)
        if args.dry_run:
            print(json.dumps(receipt, sort_keys=True))
            return 0
        if not plan["cli_present"]:
            raise ResolverError(f"selected CLI is not available on PATH: {plan['cli']}")
        print(json.dumps(receipt, sort_keys=True), file=sys.stderr)
        completed = subprocess.run(
            plan["argv"],
            cwd=plan["repo_root"],
            env=build_child_environment(plan, os.environ),
            check=False,
        )
        return completed.returncode
    except ResolverError as exc:
        print(f"lane-runtime-resolver: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
