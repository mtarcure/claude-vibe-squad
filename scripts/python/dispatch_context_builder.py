#!/usr/bin/env python3
"""Build trusted board-dispatch contexts and bridge isolated task results.

The packet supplies task intent. Delivery attempt identity comes from the
registry entry created by ``send-task.sh``. Executable, adapter, role, profile,
and lane arguments are controller-derived and cannot be supplied by a packet.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

try:
    import board_router
    from held_action_gate import HELD_CATEGORIES
    from lane_capability_enforcement import adapter_path_for
    from launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256
    from seatbelt_profile import LANE_CLI_PATHS
except ImportError:  # pragma: no cover - package-context fallback
    from . import board_router  # type: ignore[no-redef]
    from .held_action_gate import HELD_CATEGORIES  # type: ignore[no-redef]
    from .lane_capability_enforcement import adapter_path_for  # type: ignore[no-redef]
    from .launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256  # type: ignore[no-redef]
    from .seatbelt_profile import LANE_CLI_PATHS  # type: ignore[no-redef]


CONTEXT_SCHEMA = "go-live-trusted-context/v1"
AUTHORITY_SCHEMA = "go-live-authority/v1"
TASK_RE = re.compile(r"^TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[A-Za-z0-9][A-Za-z0-9-]*$")
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACES = frozenset(
    {"coding", "security", "content", "sysmgmt", "research", "shared"}
)
MAILBOX_NAMESPACES = frozenset(NAMESPACES - {"shared"})
MODEL_TO_LANE = {
    "gpt-codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "kimi": "kimi",
}
LANE_TO_MODEL = {value: key for key, value in MODEL_TO_LANE.items()}
LANE_NETWORK_SCOPE = {
    "codex": "openai-subscription",
    "claude": "anthropic-subscription",
    "gemini": "google-subscription",
    "kimi": "moonshot-subscription",
}
_TRUSTED_LANE_BASE_ARGS = {
    "codex": (
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
    ),
    "claude": (
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
    ),
    "gemini": (
        "--yolo",
        "--skip-trust",
    ),
    "kimi": (
        "--yolo",
        "--thinking",
    ),
}
_PROVEN_LANE_MODELS = {
    "gemini": "gemini-3.6-flash",
    "kimi": "kimi-code/kimi-for-coding",
}


def timeout_budget_for_mode(mode: str) -> int:
    """Return the bounded backstop; short modes keep ``"timeout_seconds": 1800``."""

    return 3600 if mode == "bounty" else 1800


class DispatchContextError(ValueError):
    """A packet or bridge operation cannot be represented safely."""


def schedule_board_batch(
    repo_root: Path,
    task_files: Sequence[Path],
    *,
    concurrency: int,
    admission_gate: Callable[[tuple[board_router.BoardTask, ...]], bool] | None = None,
    logical_only: bool = False,
) -> board_router.ScheduleResult:
    """Use the settled board scheduler to validate one detached fan-out batch."""

    root = Path(repo_root).resolve(strict=True)
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or concurrency <= 0
        or concurrency > 12
    ):
        raise DispatchContextError("board batch concurrency must be in 1..12")
    if not task_files or len(task_files) > 12:
        raise DispatchContextError("board batch must contain 1..12 task packets")

    tasks: list[board_router.BoardTask] = []
    for task_file in task_files:
        packet = Path(task_file).resolve(strict=True)
        try:
            packet.relative_to(root)
        except ValueError as exc:
            raise DispatchContextError("board batch packet escapes repository") from exc
        fields, _body = parse_task_packet(packet)
        task_id = _unquote(fields.get("id", ""))
        if not TASK_RE.fullmatch(task_id):
            raise DispatchContextError("board batch task id is invalid")
        write_paths = parse_scope(fields.get("write_scope", "[]"), field="write_scope")
        read_paths = parse_scope(fields.get("read_scope", "[]"), field="read_scope")
        try:
            dependencies_raw = json.loads(_unquote(fields.get("depends_on", "[]")))
            resources_raw = json.loads(_unquote(fields.get("resources", "[]")))
            dependencies = tuple(
                board_router.DepEdge(
                    task_id=str(item["task_id"]),
                    generation=int(item["generation"]),
                    artifact_sha256=str(item["artifact_sha256"]),
                )
                for item in dependencies_raw
            )
            resources = tuple(
                board_router.ResourceClaim(
                    resource_class=str(item["resource_class"]),
                    target=str(item.get("target", "")),
                    mode=str(item.get("mode", "write")),
                    units=int(item.get("units", 1)),
                )
                for item in resources_raw
            )
            priority = int(_unquote(fields.get("priority", "0")))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DispatchContextError(
                f"board batch task metadata is invalid: {task_id}"
            ) from exc
        tasks.append(
            board_router.BoardTask(
                task_id=task_id,
                write_paths=write_paths,
                read_paths=read_paths,
                depends_on=dependencies,
                resources=resources,
                worktree_root=str(root),
                metadata_complete=_unquote(fields.get("parallel_safe", "")) == "true",
                priority=priority,
            )
        )
    try:
        return board_router.schedule(
            tuple(tasks),
            concurrency=concurrency,
            admission_gate=admission_gate,
            logical_only=logical_only,
        )
    except ValueError as exc:
        raise DispatchContextError(f"board batch scheduling failed: {exc}") from exc


def build_board_fanout_members(
    repo_root: Path,
    parent_task_file: Path,
    output_dir: Path,
    assignments: Sequence[str],
    verification_contract: Mapping[str, object] | None = None,
) -> tuple[Path, ...]:
    """Materialize isolated advisory member packets for board-native fan-out."""

    root = Path(repo_root).resolve(strict=True)
    parent = Path(parent_task_file).resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise DispatchContextError("fan-out parent packet escapes repository") from exc
    if not 2 <= len(assignments) <= 12:
        raise DispatchContextError("board fan-out requires 2..12 assignments")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or "\n" in item
        or "\r" in item
        for item in assignments
    ):
        raise DispatchContextError("board fan-out assignments must be non-empty single lines")

    fields, body = parse_task_packet(parent)
    parent_id = _unquote(fields.get("id", ""))
    if not TASK_RE.fullmatch(parent_id):
        raise DispatchContextError("fan-out parent task id is invalid")
    if verification_contract is None:
        contract = validate_verification_contract(fields)
    else:
        contract = dict(verification_contract)
        if (
            contract.get("contract_version") != "verification-contract/v1"
            or contract.get("task_id") != parent_id
            or contract.get("run_id") != _unquote(fields.get("run_id", ""))
            or contract.get("mode") != _unquote(fields.get("mode", ""))
        ):
            raise DispatchContextError("supplied fan-out verification contract is invalid")
    original_scope = parse_scope(fields.get("write_scope", "[]"), field="write_scope")
    output = Path(output_dir).resolve(strict=False)
    try:
        output.relative_to(root / "_state" / "board-dispatch")
    except ValueError as exc:
        raise DispatchContextError("fan-out build directory is outside board state") from exc
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise DispatchContextError("fan-out build directory must be empty")

    replaced = {
        "id", "return_artifact", "write_scope", "read_scope",
        "mandatory_review", "review_model", "model_override_reason",
        "dispatch_kind", "panel_id", "panel_mode", "panel_members",
        "panel_member_ids", "panel_policy", "panel_quorum",
        "panel_timeout_seconds", "panel_max_parallel", "panel_return_contract",
        "panel_member_write_scope", "verification_contract",
        "verification_contract_sha256",
    }
    parent_lines = parent.read_text(encoding="utf-8").splitlines()
    closing = parent_lines[1:].index("---") + 1
    base_lines = [
        line
        for line in parent_lines[1:closing]
        if line.partition(":")[0] not in replaced
    ]
    packets: list[Path] = []
    for index, assignment in enumerate(assignments, start=1):
        member_id = f"member-{index}"
        child_id = f"{parent_id}-fanout-{member_id}"
        artifact_dir = f"_state/board-fanout/{parent_id}/{member_id}/"
        artifact = artifact_dir + "artifact.md"
        injected = [
            *base_lines,
            f"id: {child_id}",
            f"write_scope: [{artifact_dir}]",
            f"read_scope: [{', '.join(original_scope)}]",
            f"return_artifact: {artifact}",
            "mandatory_review: false",
            "review_model: none",
            "model_override_reason: board-native fan-out advisory member",
            f"fanout_parent_id: {parent_id}",
            f"fanout_member_id: {member_id}",
        ]
        member_body = (
            body.rstrip()
            + "\n\n## Board-native fan-out member override\n\n"
            + f"You are `{member_id}`. Work only on this advisory assignment: "
            + assignment.strip()
            + "\nDo not implement or coordinate the parent task. Write the isolated "
            + f"artifact `{artifact}` and the canonical response envelope for `{child_id}`. "
            + "Your artifact must contain concise findings, evidence, limitations, and the "
            + "chrono-vault memory id required by the board completion protocol.\n"
        )
        packet_path = output / f"{child_id}.md"
        packet_data = (
            "---\n" + "\n".join(injected) + "\n---\n\n" + member_body
        ).encode("utf-8")
        descriptor = os.open(
            packet_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(packet_data)
            stream.flush()
            os.fsync(stream.fileno())
        packets.append(packet_path)
    return tuple(packets)


@dataclass(frozen=True)
class PreparedWorktreeOutputs:
    task_id: str
    result_relative: str
    outbox_relative: str
    result_bytes: bytes
    envelope_bytes: bytes
    status: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(Path(path).read_bytes())
    except OSError as exc:
        raise DispatchContextError(f"required file is unavailable: {path}: {exc}") from exc


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise DispatchContextError(f"value is not canonical JSON: {exc}") from exc


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_task_packet(path: Path) -> tuple[dict[str, str], str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DispatchContextError(f"task packet is unreadable UTF-8: {exc}") from exc
    if "\x00" in text:
        raise DispatchContextError("task packet contains NUL")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise DispatchContextError("task packet lacks opening frontmatter")
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---"
        ),
        None,
    )
    if closing is None:
        raise DispatchContextError("task packet lacks closing frontmatter")
    fields: dict[str, str] = {}
    for raw_line in lines[1:closing]:
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if (
            not separator
            or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
            or key in fields
        ):
            raise DispatchContextError(f"invalid or duplicate frontmatter row: {line!r}")
        fields[key] = value.strip()
    return fields, "".join(lines[closing + 1 :])


def _safe_relative(value: str, *, field: str) -> str:
    value = _unquote(value)
    if (
        not value
        or value == "."
        or "\x00" in value
        or "\\" in value
        or Path(value).is_absolute()
    ):
        raise DispatchContextError(f"{field} contains an unsafe path: {value!r}")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise DispatchContextError(f"{field} contains traversal: {value!r}")
    return path.as_posix()


def parse_scope(raw: str, *, field: str) -> tuple[str, ...]:
    raw = raw.strip()
    if not raw.startswith("[") or not raw.endswith("]"):
        raise DispatchContextError(f"{field} must be a YAML inline list")
    inner = raw[1:-1].strip()
    if not inner:
        return ()
    values = tuple(
        _safe_relative(part.strip(), field=field)
        for part in inner.split(",")
        if part.strip()
    )
    if not values or len(set(values)) != len(values):
        raise DispatchContextError(f"{field} contains empty or duplicate entries")
    return values


def require_packet_fields(fields: Mapping[str, str]) -> None:
    """Fail with the exact missing frontmatter field names (friction F7).

    A thin hand-authored packet typically omits several of these at once. The
    old message ("source_namespace, run_id, and mode are required") named the
    whole set whether or not a given field was actually absent, so the author
    had to bisect the packet by hand. Name only what is genuinely wrong.
    """

    missing = [
        name
        for name in ("source_namespace", "run_id", "mode")
        if not _unquote(fields.get(name, ""))
    ]
    if missing:
        raise DispatchContextError(
            "task packet is missing required frontmatter field(s): "
            + ", ".join(missing)
        )
    namespace = _unquote(fields.get("source_namespace", ""))
    if namespace not in NAMESPACES:
        raise DispatchContextError(
            f"frontmatter field source_namespace is invalid: {namespace!r} "
            f"(expected one of {', '.join(sorted(NAMESPACES))})"
        )


def validate_verification_contract(fields: Mapping[str, str]) -> dict[str, Any]:
    """Validate the dispatcher-pinned contract, naming any bad field (F7)."""

    raw_contract = fields.get("verification_contract", "")
    declared_hash = _unquote(fields.get("verification_contract_sha256", ""))
    if not str(raw_contract).strip():
        raise DispatchContextError(
            "task packet is missing required frontmatter field: "
            "verification_contract"
        )
    try:
        contract = json.loads(raw_contract)
    except json.JSONDecodeError as exc:
        raise DispatchContextError(f"verification_contract is invalid JSON: {exc}") from exc
    if not isinstance(contract, dict):
        raise DispatchContextError("verification_contract must be an object")
    if not declared_hash:
        raise DispatchContextError(
            "task packet is missing required frontmatter field: "
            "verification_contract_sha256"
        )
    actual_hash = _sha256_bytes(_canonical_json(contract))
    if not SHA256_RE.fullmatch(declared_hash):
        raise DispatchContextError(
            "frontmatter field verification_contract_sha256 is not lowercase "
            f"64-hex: {declared_hash!r}"
        )
    if actual_hash != declared_hash:
        raise DispatchContextError(
            "frontmatter field verification_contract_sha256 does not match "
            f"verification_contract (declared={declared_hash} actual={actual_hash})"
        )
    if contract.get("task_id") != _unquote(fields.get("id", "")):
        raise DispatchContextError(
            "verification_contract.task_id does not match frontmatter field id "
            f"(contract={contract.get('task_id')!r} packet={_unquote(fields.get('id', ''))!r})"
        )
    required_phases = contract.get("required_phase_ids")
    verification_kinds = contract.get("required_verification_kinds")
    advisory = contract.get("mode") == "advisory"
    invalid: list[str] = []
    if (
        not isinstance(required_phases, list)
        or (not advisory and not required_phases)
        or any(not isinstance(item, str) or not item for item in required_phases)
    ):
        invalid.append("required_phase_ids")
    if (
        not isinstance(verification_kinds, list)
        or not verification_kinds
        or any(not isinstance(item, str) or not item for item in verification_kinds)
    ):
        invalid.append("required_verification_kinds")
    if invalid:
        raise DispatchContextError(
            "verification_contract has a missing or malformed nonempty string "
            "array for: " + ", ".join(invalid)
        )
    return contract


def _runtime_row(repo_root: Path, specialist: str) -> dict[str, str]:
    runtime_map = repo_root / "shared" / "specialist-runtime-map.tsv"
    try:
        with runtime_map.open(encoding="utf-8", newline="") as handle:
            rows = [
                row
                for row in csv.DictReader(handle, delimiter="\t")
                if row.get("specialist") == specialist
            ]
    except OSError as exc:
        raise DispatchContextError(f"runtime map is unavailable: {exc}") from exc
    if len(rows) != 1:
        raise DispatchContextError(
            f"runtime map must contain exactly one row for {specialist!r}"
        )
    return rows[0]


def _selected_profile(row: Mapping[str, str], lane: str) -> str:
    matches = []
    for prefix in ("primary", "backup", "escalate", "review", "throughput"):
        row_lane = row.get(f"{prefix}_lane", "")
        if row_lane == lane:
            profile = row.get(f"{prefix}_profile", "")
            if profile and profile != "none":
                matches.append(profile)
    if not matches:
        raise DispatchContextError(
            f"runtime map does not select a {lane} profile"
        )
    # The packet selects a lane, not an escalation tier. Prefer the primary
    # profile whenever that lane is primary; otherwise use the first routed
    # tier in the canonical primary→backup→escalate→review→throughput order.
    return matches[0]


def _profile_row(
    repo_root: Path,
    *,
    lane: str,
    profile_id: str,
) -> dict[str, str]:
    if lane not in _TRUSTED_LANE_BASE_ARGS:
        raise DispatchContextError(f"unsupported trusted lane: {lane!r}")
    path = repo_root / "shared" / "registries" / "profiles.tsv"
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            required = {"profile_id", "lane", "model_id", "effort", "flags", "usage"}
            if not required.issubset(set(reader.fieldnames or ())):
                raise DispatchContextError("profile registry is missing required fields")
            matches = [row for row in reader if row.get("profile_id") == profile_id]
    except OSError as exc:
        raise DispatchContextError(f"profile registry is unavailable: {exc}") from exc
    if len(matches) != 1:
        raise DispatchContextError(
            f"profile registry must contain exactly one row for {profile_id!r}"
        )
    profile = dict(matches[0])
    if profile.get("lane") != lane:
        raise DispatchContextError("selected profile belongs to a different lane")
    if not profile.get("model_id") or profile["model_id"] == "none":
        raise DispatchContextError("selected profile does not pin a model")
    if not profile.get("effort"):
        raise DispatchContextError("selected profile does not pin an effort")
    return profile


def selected_model_sha256_for(
    repo_root: Path,
    *,
    lane: str,
    specialist: str,
) -> str:
    row = _runtime_row(Path(repo_root), specialist)
    profile_id = _selected_profile(row, lane)
    profile = _profile_row(Path(repo_root), lane=lane, profile_id=profile_id)
    return _sha256_bytes(
        _canonical_json({"profile_id": profile_id, "profile": profile})
    )


def trusted_lane_args_for(
    repo_root: Path,
    *,
    lane: str,
    specialist: str,
) -> tuple[str, ...]:
    row = _runtime_row(Path(repo_root), specialist)
    profile_id = _selected_profile(row, lane)
    profile = _profile_row(Path(repo_root), lane=lane, profile_id=profile_id)
    model = profile["model_id"]
    effort = profile["effort"]
    base = _TRUSTED_LANE_BASE_ARGS[lane]
    if lane == "codex":
        return (
            *base,
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
        )
    if lane == "claude":
        return (*base, "--model", model, "--effort", effort)
    if lane == "gemini":
        return (*base, "--model", _PROVEN_LANE_MODELS["gemini"])
    return (*base, "--model", _PROVEN_LANE_MODELS["kimi"])


def _canonical_role(repo_root: Path, row: Mapping[str, str]) -> Path:
    specialist = row["specialist"]
    namespace = row["source_namespace"]
    if namespace == "shared":
        candidate = repo_root / "shared" / "specialists" / f"{specialist}.md"
    else:
        candidate = (
            repo_root
            / "departments"
            / namespace
            / "specialists"
            / f"{specialist}.md"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DispatchContextError(f"canonical role is unavailable or outside repo: {exc}") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise DispatchContextError("canonical role must be a regular non-symlink file")
    return resolved


def _mailbox_namespace(repo_root: Path, task_file: Path, task_id: str) -> str:
    try:
        relative = task_file.resolve(strict=True).relative_to(
            repo_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise DispatchContextError("task packet must be inside the repository") from exc
    parts = relative.parts
    if (
        len(parts) != 4
        or parts[0] != "departments"
        or parts[1] not in MAILBOX_NAMESPACES
        or parts[2] != "inbox"
        or parts[3] != f"{task_id}.md"
    ):
        raise DispatchContextError(
            "task packet must be the exact departments/<namespace>/inbox path"
        )
    return parts[1]


def _contains(scope: str, target: str) -> bool:
    scope_path = PurePosixPath(scope)
    target_path = PurePosixPath(target)
    return scope_path == target_path or scope_path in target_path.parents


def build_context(
    repo_root: Path,
    task_file: Path,
    *,
    attempt_id: str,
    generation: int,
    now: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    packet_path = Path(task_file).resolve(strict=True)
    fields, _body = parse_task_packet(packet_path)
    task_id = _unquote(fields.get("id", ""))
    specialist = _unquote(fields.get("specialist", ""))
    namespace = _unquote(fields.get("source_namespace", ""))
    to_model = _unquote(fields.get("to_model", ""))
    run_id = _unquote(fields.get("run_id", ""))
    mode = _unquote(fields.get("mode", ""))
    return_artifact = _safe_relative(
        fields.get("return_artifact", ""), field="return_artifact"
    )
    canary_autoclean_raw = _unquote(
        fields.get("board_canary_autoclean", "false")
    )
    if canary_autoclean_raw not in {"true", "false"}:
        raise DispatchContextError("board_canary_autoclean must be true or false")
    canary_autoclean = canary_autoclean_raw == "true"
    if not TASK_RE.fullmatch(task_id):
        raise DispatchContextError("task id is invalid")
    if not ATTEMPT_RE.fullmatch(attempt_id):
        raise DispatchContextError("attempt id is not a registry delivery identity")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
        raise DispatchContextError("generation must be a positive integer")
    if not IDENTIFIER_RE.fullmatch(specialist):
        raise DispatchContextError("specialist identifier is invalid")
    require_packet_fields(fields)
    try:
        lane = MODEL_TO_LANE[to_model]
    except KeyError as exc:
        raise DispatchContextError(f"unsupported to_model: {to_model!r}") from exc
    mailbox_namespace = _mailbox_namespace(root, packet_path, task_id)
    row = _runtime_row(root, specialist)
    if row.get("source_namespace") != namespace:
        raise DispatchContextError("packet namespace does not match runtime map")
    profile = _selected_profile(row, lane)
    canonical_role = _canonical_role(root, row)
    try:
        adapter = adapter_path_for(
            repo_root=root, lane=lane, specialist=specialist
        ).resolve(strict=True)
    except Exception as exc:  # noqa: BLE001 - convert capability boundary
        raise DispatchContextError(f"native lane adapter cannot be resolved: {exc}") from exc
    try:
        adapter.relative_to(root)
    except ValueError as exc:
        raise DispatchContextError("native lane adapter escapes repository") from exc
    executable = LANE_CLI_PATHS.get(lane)
    if executable is None:
        raise DispatchContextError(f"no trusted executable for lane {lane}")
    resolved_executable = Path(os.path.realpath(executable))
    if not executable.is_absolute() or not resolved_executable.is_file():
        raise DispatchContextError(f"trusted lane executable is unavailable: {executable}")

    write_scope = parse_scope(fields.get("write_scope", ""), field="write_scope")
    if not any(_contains(scope, return_artifact) for scope in write_scope):
        raise DispatchContextError("return_artifact is outside packet write_scope")
    if canary_autoclean and (
        not task_id.endswith("-board-inventory-canary")
        or len(write_scope) != 1
        or not write_scope[0].startswith("_state/board-canary-")
        or not return_artifact.startswith(write_scope[0])
    ):
        raise DispatchContextError(
            "board canary auto-clean is restricted to isolated inventory canaries"
        )
    explicit_reads = parse_scope(
        fields.get("read_scope", "[]"), field="read_scope"
    )
    required_reads = (
        packet_path.relative_to(root).as_posix(),
        canonical_role.relative_to(root).as_posix(),
        adapter.relative_to(root).as_posix(),
    )
    read_scope = tuple(dict.fromkeys((*explicit_reads, *required_reads)))
    contract = validate_verification_contract(fields)
    if contract.get("run_id") != run_id or contract.get("mode") != mode:
        raise DispatchContextError("verification contract run/mode mismatch")
    author_family = contract.get("author_family")
    if not isinstance(author_family, str) or not author_family:
        raise DispatchContextError("verification contract author_family is invalid")

    capability_source = root / "model-lanes" / "specialist-lane-capabilities.v1.json"
    # Read and hash the capability source at context construction time so a
    # missing controller dependency fails before launch.
    _sha256_file(capability_source)
    plan = {
        "schema": "board-dispatch-plan/v1",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "lane": lane,
        "profile": profile,
        "write_paths": list(write_scope),
        "read_scope": list(read_scope),
        "expected_result_path": return_artifact,
    }
    created_at = int(time.time()) if now is None else now
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at <= 0:
        raise DispatchContextError("creation time must be a positive integer")
    launch_nonce = secrets.token_hex(32) if nonce is None else nonce
    if not SHA256_RE.fullmatch(launch_nonce) or launch_nonce == "0" * 64:
        raise DispatchContextError("nonce must be a nonzero 64-hex value")

    packet_text = packet_path.read_text(encoding="utf-8")
    fanout_member = bool(_unquote(fields.get("fanout_parent_id", "")))
    panel_fanout = _unquote(fields.get("panel_mode", "")) == "fanout"
    task_prompt = (
        "Execute the exact task packet below as a fresh isolated specialist CLI. "
        "Do not claim or redispatch it; this launch is already bound to the registry "
        f"attempt {attempt_id}, generation {generation}. Write the declared return "
        "artifact and response envelope inside this worktree. The supervisor validates "
        "and promotes the artifact first and the envelope last.\n\n"
        # Best-effort, one-attempt memory (2026-07-24): the burn AND a hard task-block came
        # from the memory ceremony being mandatory + fatal. `record_usage` failed live enum
        # validation (its `outcome` enum ['incorrect','not_useful','used'] is NOT declared in
        # the exposed schema, so the model cannot call it correctly) and the prompt told the
        # CLI to settle `blocked` on any memory failure — so trivial telemetry killed the
        # whole implementation before a file was written (TASK-2026-07-24-9102). Memory is now
        # explicitly BEST-EFFORT and never a gate; record_usage is removed. recall+record use
        # exact shapes so they succeed first-try and satisfy any recall/record contract.
        "Durable memory is BEST-EFFORT telemetry — make each call at most ONCE with the exact "
        "shapes below; do NOT search the repo for schemas and do NOT retry on error. A memory "
        "call is NEVER a gate: if any memory call errors, note it in one line in the artifact "
        "and CONTINUE the task. Do NOT settle blocked and do NOT skip implementation because "
        "of a memory bookkeeping failure.\n"
        "- Recall prior context ONCE: `recall(query=\"<task-specific terms>\", limit=5)` — "
        "pass no `filters` unless the runtime supplies accepted filter keys.\n"
        "- Just before the completion envelope, record the outcome ONCE with this exact, "
        "schema-complete shape (every field is valid; UNKNOWN FIELDS ARE REJECTED, so add "
        "no others):\n"
        f'    record(note_type="learning", fields={{"title": "<one-line outcome>", '
        f'"body": "<what/why; reference {task_id} in the text>", "target": "<component or '
        f'target>", "attack_class": "none", "source_task": "{task_id}"}})\n'
        "  For security/bounty work use note_type \"finding\" or \"attempt\" and a real "
        "attack_class. Include the returned memory id in the artifact.\n"
        "- Do NOT call `record_usage` — its outcome enum is not exposed in the schema and has "
        "caused hard blocks; usage bookkeeping is optional and must never gate work.\n\n"
        "## Exact task packet\n\n"
        f"{packet_text.rstrip()}\n"
    )
    if len(task_prompt.encode("utf-8")) > 32768:
        raise DispatchContextError("task packet is too large for trusted launch prompt")

    expected_outbox = (
        f"departments/{mailbox_namespace}/outbox/{task_id}-response.md"
    )
    authority = {
        "schema": AUTHORITY_SCHEMA,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "run_id": run_id,
        "author_family": author_family,
        "workload_class": "cpu-light",
        "specialist": specialist,
        "lane": lane,
        "mode_profile": mode,
        "execution_kind": "lane",
        "repo_root": str(root),
        "pool_root": str(root / "_state" / "board-worktrees"),
        "canonical_role_path": str(canonical_role),
        "canonical_role_sha256": _sha256_file(canonical_role),
        "lane_overlay_path": str(adapter),
        "lane_overlay_sha256": _sha256_file(adapter),
        "executable": str(executable),
        "executable_sha256": _sha256_file(resolved_executable),
        "lane_args": list(
            trusted_lane_args_for(root, lane=lane, specialist=specialist)
        ),
        "write_paths": list(write_scope),
        "read_scope": list(read_scope),
        "depends_on": [],
        "resources": [],
        "scheduler_concurrency": 1,
        "scheduler_capacities": {},
        "scheduler_settled": {},
        "network_scope": [LANE_NETWORK_SCOPE[lane], "role-mcp"],
        "action_scope": ["repo-read", "worktree-write", "role-mcp"],
        "budgets": {
            # Safety BACKSTOP against a truly-hung / runaway spawn — NOT a normal
            # deadline. A short deadline was killing legitimate long tasks; instead
            # Chrono supervises live (dashboard stall visibility) and cancels a stuck
            # spawn. Real tasks finish well within this; the backstop only catches an
            # infinite loop so it can't burn unbounded.
            "timeout_seconds": timeout_budget_for_mode(mode)
        },
        "expected_result_path": return_artifact,
        "expected_outbox_path": expected_outbox,
        # CC-03: the pins/fences the reconciler requires the landed response to
        # echo, snapshotted from trusted launch-time sources (packet frontmatter
        # + the locked registry) so promotion can rebuild them without trusting
        # worker metadata.
        "reconciliation_echo": {
            **packet_reconciliation_echo(fields),
            **registry_reconciliation_echo(
                root, task_id, attempt_id=attempt_id, generation=generation
            ),
        },
        "required_phase_ids": list(contract["required_phase_ids"]),
        "verification_kinds": list(contract["required_verification_kinds"]),
        "operator_gates": sorted(HELD_CATEGORIES),
        "packet_sha256": _sha256_file(packet_path),
        "plan_sha256": _sha256_bytes(_canonical_json(plan)),
        "verification_contract_sha256": _unquote(
            fields["verification_contract_sha256"]
        ),
        "selected_model_sha256": selected_model_sha256_for(
            root,
            lane=lane,
            specialist=specialist,
        ),
        "profile_bundle_sha256": SETTLED_T1P1_BUNDLE_SHA256,
        "active_board_tasks": [],
        "created_at": created_at,
        "expires_at": created_at + 600,
        "nonce": launch_nonce,
    }
    return {
        "schema": CONTEXT_SCHEMA,
        "authority": authority,
        "task_prompt": task_prompt,
    }


def cleanup_canary(
    *,
    repo_root: Path,
    context_file: Path,
) -> dict[str, object]:
    """Remove only an explicitly opted-in, reconciled board canary dispatch."""

    root = Path(repo_root).resolve(strict=True)
    context_path = Path(context_file).resolve(strict=True)
    try:
        context_path.relative_to(root / "_state" / "board-dispatch")
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DispatchContextError(f"canary cleanup context is invalid: {exc}") from exc
    authority = context.get("authority")
    if not isinstance(authority, dict):
        raise DispatchContextError("canary cleanup authority is invalid")
    task_id = authority.get("task_id")
    attempt_id = authority.get("attempt_id")
    generation = authority.get("generation")
    write_paths = authority.get("write_paths")
    result_path = authority.get("expected_result_path")
    if not isinstance(task_id, str) or not TASK_RE.fullmatch(task_id):
        raise DispatchContextError("canary cleanup task identity is invalid")
    if not task_id.endswith("-board-inventory-canary"):
        return {"status": "not-requested"}
    packet_candidates = [
        value
        for value in authority.get("read_scope", [])
        if isinstance(value, str)
        and re.fullmatch(
            rf"departments/[^/]+/inbox/{re.escape(task_id)}\.md",
            value,
        )
    ]
    if len(packet_candidates) != 1:
        raise DispatchContextError("canary cleanup packet identity is ambiguous")
    packet_path = root / packet_candidates[0]
    if (
        packet_path.is_symlink()
        or not packet_path.is_file()
        or _sha256_file(packet_path) != authority.get("packet_sha256")
    ):
        raise DispatchContextError("canary cleanup packet no longer matches authority")
    packet_fields, _packet_body = parse_task_packet(packet_path)
    if _unquote(packet_fields.get("board_canary_autoclean", "false")) != "true":
        return {"status": "not-requested"}
    if (
        not ATTEMPT_RE.fullmatch(str(attempt_id))
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or not isinstance(write_paths, list)
        or len(write_paths) != 1
        or not isinstance(write_paths[0], str)
        or not write_paths[0].startswith("_state/board-canary-")
        or not isinstance(result_path, str)
        or not result_path.startswith(write_paths[0])
    ):
        raise DispatchContextError("canary cleanup authority is not tightly scoped")

    try:
        import registry_reconciler as rr
    except ImportError as exc:
        raise DispatchContextError(
            f"canary cleanup registry controller is unavailable: {exc}"
        ) from exc
    registry_path = root / "_state" / "active-tasks.json"
    if Path(rr.REGISTRY_PATH).resolve() != registry_path.resolve():
        raise DispatchContextError("canary cleanup registry root mismatch")
    with rr.locked_registry():
        registry = rr.load_registry()
        if not isinstance(registry, dict):
            raise DispatchContextError("canary cleanup registry has the wrong schema")
        entry = registry.get(task_id)
        if entry is not None:
            if (
                not isinstance(entry, dict)
                or entry.get("delivery_attempt_id") != attempt_id
                or int(entry.get("delivery_generation") or 0) != generation
            ):
                raise DispatchContextError(
                    "canary cleanup registry identity changed"
                )
            del registry[task_id]
            data = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
            rr.atomic_write(registry_path, data)
        packet_path.unlink()
        packet_directory_fd = os.open(packet_path.parent, os.O_RDONLY)
        try:
            os.fsync(packet_directory_fd)
        finally:
            os.close(packet_directory_fd)
    return {
        "status": "cleaned",
        "task_id": task_id,
        "registry_removed": entry is not None,
        "packet_removed": True,
    }


def _read_contained_regular(
    worktree_root: Path,
    relative: str,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    root = worktree_root.resolve(strict=True)
    candidate = root / _safe_relative(relative, field=label)
    if candidate.is_symlink() or not candidate.is_file():
        raise DispatchContextError(f"{label} is missing, non-regular, or a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        data = candidate.read_bytes()
    except (OSError, ValueError) as exc:
        raise DispatchContextError(f"{label} is unavailable or escapes worktree") from exc
    if not data or len(data) > maximum_bytes:
        raise DispatchContextError(f"{label} is empty or exceeds size bound")
    return data


# ── CC-17: ONE worker status enum ────────────────────────────────────────────
# The single set of statuses a worker CLI may author in its response envelope.
# `shared/dispatch-toolkit.sh` injects exactly this list into every brief (its
# completion contract AND its no-delete rule), `registry_reconciler.py` settles
# exactly these (plus controller-only `cancelled`), and `bin/outbox-watcher.sh`
# presents exactly these. Previously the toolkit offered three, told workers to
# emit a fourth (`needs_human`) in its no-delete rule, this bridge silently
# downgraded that fourth to `needs_review`, and the reconciler accepted it --
# four surfaces, four opinions (audit CC-17).
#
# Escalation semantic, weakest to strongest:
#   complete     -> finished and verified; nothing is owed.
#   needs_review -> finished, but a controller/reviewer must look before it counts.
#   needs_human  -> STOPPED pending an operator DECISION (the no-delete rule, an
#                   operator gate, an approval). Strictly stronger than
#                   needs_review: it is a question, not a deliverable.
#   blocked      -> could not proceed; no usable result.
# `cancelled` is controller-only -- a worker may never self-cancel, so it is
# absent here while remaining settleable by the reconciler.
WORKER_AUTHORABLE_STATUSES = frozenset(
    {"complete", "needs_review", "needs_human", "blocked"}
)

_CANONICAL_ENVELOPE_STATUSES = frozenset(
    {*WORKER_AUTHORABLE_STATUSES, "completed"}
)


def _coerce_status(raw: str) -> str:
    """Map a worker-authored status onto a canonical settleable value.

    Already-canonical values pass through verbatim (the reconciler further
    canonicalizes ``completed`` -> ``complete``). Anything else is coerced by
    intent to the nearest canonical status, defaulting to ``needs_review`` so
    questionable or unmappable work surfaces to the controller rather than
    silently auto-closing. Ordering is by escalation strength: ``blocked``
    intent wins over everything, then ``needs_human`` (an operator decision is
    owed) over a bare review request, so a worker that reports a genuine block
    or a hard operator gate is never quietly downgraded (audit CC-17).
    """

    value = (raw or "").strip()
    if value in _CANONICAL_ENVELOPE_STATUSES:
        return value
    lowered = value.lower()
    if any(token in lowered for token in ("block", "fail", "abort", "error")):
        return "blocked"
    if any(token in lowered for token in ("human", "operator", "approval")):
        return "needs_human"
    if any(token in lowered for token in ("review", "needs", "partial")):
        return "needs_review"
    if any(token in lowered for token in ("complete", "done", "success", "pass", "ok")):
        return "complete"
    return "needs_review"


# ── CC-03: reconciliation pin/fence echoes ───────────────────────────────────
# `registry_reconciler.py` holds a task OPEN until the landed response echoes
# every pin and fence its registry entry carries:
#   * capability_response_issue -> capability_card_sha256
#   * swarm_response_issue      -> swarm_spec_sha256
#   * worker_response_issue     -> the worker-pool delivery fence
# Output promotion rebuilds the envelope from the trusted launch authority, and
# it used to emit only the seven identity rows -- silently discarding every one
# of those echoes, so capability/swarm/worker completions could never settle
# (audit CC-03). These are reconstructed from the AUTHORITY, never from worker
# metadata: a worker must not be able to author the value that proves its own
# response is current.
RECONCILIATION_ECHO_KEYS: dict[str, re.Pattern[str]] = {
    "capability_card_sha256": SHA256_RE,
    "swarm_spec_sha256": SHA256_RE,
    "delivery_attempt_id": re.compile(r"d-[0-9a-f]{32}"),
    "delivery_generation": re.compile(r"[0-9]{1,9}"),
    "delivery_worker_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"),
    "worker_epoch": re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"),
    "lease_generation": re.compile(r"[0-9]{1,9}"),
    "delivery_lane": re.compile(r"[a-z][a-z0-9-]{0,31}"),
    "replica_index": re.compile(r"[0-9]{1,9}"),
    "member_id": re.compile(r"[a-z][a-z0-9-]{0,31}:(?:r|sub)[0-9]{2}"),
}


def validate_reconciliation_echo(raw: object) -> dict[str, str]:
    """Validate a pin/fence echo mapping, fail-closed on anything unexpected.

    Only the known reconciliation keys are permitted, and each value must match
    its shape exactly. This is what stops the echo from becoming a general
    frontmatter-injection channel into the published envelope.
    """

    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise DispatchContextError("reconciliation_echo must be an object")
    echo: dict[str, str] = {}
    for key, value in raw.items():
        pattern = RECONCILIATION_ECHO_KEYS.get(key) if isinstance(key, str) else None
        if pattern is None:
            raise DispatchContextError(
                f"reconciliation_echo has an unsupported key: {key!r}"
            )
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise DispatchContextError(
                f"reconciliation_echo value for {key} is malformed: {value!r}"
            )
        echo[key] = value
    return echo


def packet_reconciliation_echo(fields: Mapping[str, str]) -> dict[str, str]:
    """Derive the capability/swarm pin echoes from the dispatched packet.

    `bin/send-task.sh` injects both pins into the packet frontmatter at dispatch
    time, so the packet -- whose SHA-256 is itself bound into the authority -- is
    a trusted launch-time source for them.
    """

    echo: dict[str, str] = {}
    capability_pin = _unquote(fields.get("capability_card_sha256", ""))
    if capability_pin:
        echo["capability_card_sha256"] = capability_pin
    # The reconciler requires the swarm pin only from a swarm MEMBER; a parent
    # carries the same field but is settled from its children, not an echo.
    if (
        _unquote(fields.get("dispatch_kind", "")) == "swarm"
        and _unquote(fields.get("swarm_role", "")) == "member"
    ):
        swarm_pin = _unquote(fields.get("swarm_spec_sha256", ""))
        if swarm_pin:
            echo["swarm_spec_sha256"] = swarm_pin
    return validate_reconciliation_echo(echo)


def registry_reconciliation_echo(
    repo_root: Path,
    task_id: str,
    *,
    attempt_id: str,
    generation: int,
) -> dict[str, str]:
    """Snapshot the worker-pool delivery fence from the locked registry.

    Only a pool-assigned task carries a fence (`worker_response_issue` returns
    clean when `delivery_worker_id` is unset), so an ordinary board dispatch
    yields an empty mapping. Snapshotting at LAUNCH time preserves staleness
    detection: a requeue advances the registry fence, so a response promoted
    from the superseded attempt no longer matches and is correctly held.
    """

    registry_path = Path(repo_root) / "_state" / "active-tasks.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        return {}
    try:
        import registry_reconciler as rr
    except ImportError:
        # The registry controller is optional at context-build time; an ordinary
        # dispatch needs no fence, and a pool dispatch fails closed downstream
        # (the reconciler keeps it open) rather than launching on a guess.
        return {}
    try:
        with rr.locked_registry():
            registry = rr.load_registry()
            entry = registry.get(task_id) if isinstance(registry, dict) else None
    except (OSError, ValueError):
        return {}
    if not isinstance(entry, dict) or not entry.get("delivery_worker_id"):
        return {}
    if (
        entry.get("delivery_attempt_id") != attempt_id
        or int(entry.get("delivery_generation") or 0) != generation
    ):
        raise DispatchContextError(
            "registry delivery fence does not match the launch attempt"
        )
    echo = {
        "delivery_attempt_id": str(entry.get("delivery_attempt_id") or ""),
        "delivery_generation": str(int(entry.get("delivery_generation") or 1)),
        "delivery_worker_id": str(entry.get("delivery_worker_id") or ""),
        "worker_epoch": str(entry.get("worker_epoch") or ""),
        "lease_generation": str(int(entry.get("lease_generation") or 0)),
        "delivery_lane": str(
            entry.get("delivery_lane") or entry.get("to_model") or ""
        ),
    }
    for optional in ("replica_index", "member_id"):
        if entry.get(optional) is not None:
            echo[optional] = str(entry[optional])
    return validate_reconciliation_echo(echo)


def _render_response_envelope(
    *,
    task_id: str,
    lane: str,
    result_relative: str,
    status: str,
    summary: str,
    reconciliation_echo: Mapping[str, str] | None = None,
) -> bytes:
    """Reconstruct a canonical response envelope from the trusted authority.

    Every identity field is fully determined by the launch authority, so the
    only worker-authored signals carried across are the (already coerced)
    ``status`` intent and the summary prose. Reconciliation pin/fence rows are
    appended from the authority in sorted key order. Rendering is deterministic,
    which keeps re-publication idempotent.
    """

    echo = validate_reconciliation_echo(reconciliation_echo)
    echo_rows = "".join(f"{key}: {echo[key]}\n" for key in sorted(echo))
    body = summary.strip("\n")
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        f"from: {LANE_TO_MODEL[lane]}\n"
        "to: chrono\n"
        "type: RESULT\n"
        f"status: {status}\n"
        f"return_artifact: {result_relative}\n"
        f"{echo_rows}"
        "---\n\n"
        f"{body}\n"
    ).encode("utf-8")


def _parse_response_envelope(data: bytes) -> tuple[dict[str, str], str]:
    """Parse a worker response envelope leniently into (fields, summary).

    The envelope is worker-authored metadata; the valuable, separately-gated
    part is the committed artifact and the integrated code residue. Only
    structurally-malformed frontmatter (not UTF-8, missing/unclosed fence,
    non-conforming or duplicate keys) and a genuinely-empty summary body are
    hard failures here. Field-*set* deviations -- a missing required field or an
    unexpected extra -- are NOT rejected; ``prepare_worktree_outputs`` normalizes
    them against the trusted launch authority rather than stranding a finished
    run. See ``_state/consults/envelope-prevalidation-fix.md``.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DispatchContextError("response envelope is not UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise DispatchContextError("response envelope lacks frontmatter")
    try:
        closing = lines[1:].index("---") + 1
    except ValueError as exc:
        raise DispatchContextError("response envelope frontmatter is unclosed") from exc
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if (
            not separator
            or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
            or key in fields
        ):
            raise DispatchContextError("response envelope has invalid frontmatter")
        fields[key] = _unquote(value)
    summary = "\n".join(lines[closing + 1 :]).strip()
    if not summary:
        raise DispatchContextError("response envelope summary is empty")
    return fields, summary


def _is_board_blocked_stub(data: bytes, task_id: str) -> bool:
    """Match only the exact controller-authored blocked-artifact format."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return re.fullmatch(
        (
            r"blocked\n\n"
            rf"# Board dispatch blocked — {re.escape(task_id)}\n\n"
            r"Controller reason: [^\r\n]{1,2000}\n"
        ),
        text,
    ) is not None


def _validate_destination(
    repo_root: Path,
    relative: str,
    data: bytes,
    *,
    label: str,
    reclaim_board_blocked_stub_for: str | None = None,
) -> Path:
    root = repo_root.resolve(strict=True)
    safe_relative = _safe_relative(relative, field=label)
    destination = root / safe_relative
    current = root
    for part in PurePosixPath(safe_relative).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise DispatchContextError(f"{label} parent is a symlink")
    if destination.is_symlink():
        raise DispatchContextError(f"{label} destination is a symlink")
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise DispatchContextError(f"{label} destination escapes repository") from exc
    if destination.exists():
        if not destination.is_file():
            raise DispatchContextError(f"{label} destination already differs")
        existing = destination.read_bytes()
        if existing != data and not (
            reclaim_board_blocked_stub_for
            and _is_board_blocked_stub(
                existing,
                reclaim_board_blocked_stub_for,
            )
        ):
            raise DispatchContextError(f"{label} destination already differs")
    return destination


def _safe_destination(
    repo_root: Path,
    relative: str,
    data: bytes,
    *,
    label: str,
    reclaim_board_blocked_stub_for: str | None = None,
) -> Path:
    destination = _validate_destination(
        repo_root,
        relative,
        data,
        label=label,
        reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
    )
    root = repo_root.resolve(strict=True)
    current = root
    for part in PurePosixPath(_safe_relative(relative, field=label)).parts[:-1]:
        current = current / part
        current.mkdir(exist_ok=True)
    return destination


def _atomic_publish(
    repo_root: Path,
    relative: str,
    data: bytes,
    *,
    label: str,
    reclaim_board_blocked_stub_for: str | None = None,
) -> tuple[Path, bool]:
    destination = _safe_destination(
        repo_root,
        relative,
        data,
        label=label,
        reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
    )
    reclaim_blocked_stub = False
    if destination.exists():
        if not destination.is_file():
            raise DispatchContextError(f"{label} destination already differs")
        existing = destination.read_bytes()
        if existing == data:
            return destination, True
        reclaim_blocked_stub = bool(
            reclaim_board_blocked_stub_for
            and _is_board_blocked_stub(
                existing,
                reclaim_board_blocked_stub_for,
            )
        )
        if not reclaim_blocked_stub:
            raise DispatchContextError(f"{label} destination already differs")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.bridge.",
        dir=str(destination.parent),
    )
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if reclaim_blocked_stub:
            if (
                destination.is_symlink()
                or not destination.is_file()
                or not _is_board_blocked_stub(
                    destination.read_bytes(),
                    str(reclaim_board_blocked_stub_for),
                )
            ):
                raise DispatchContextError(
                    f"{label} destination changed during blocked-stub reclaim"
                )
            os.replace(temporary_name, destination)
        else:
            try:
                os.link(temporary_name, destination)
            except FileExistsError as exc:
                raise DispatchContextError(
                    f"{label} destination appeared concurrently"
                ) from exc
            os.unlink(temporary_name)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Preserve a failed staging file for inspection; never delete task data.
        raise
    return destination, False


def reclaim_lane_cwd_outputs(
    worktree_root: Path,
    lane_cwd_relative: str,
    relative_paths: Sequence[str],
) -> tuple[str, ...]:
    """Relocate worker outputs written relative to a lane's process cwd.

    Gemini is the one lane whose process cwd is not the worktree root: it runs
    with ``cwd = <worktree>/model-lanes/gemini`` because that directory holds
    the lane ``.gemini`` settings/agents and is the same cwd used to enumerate
    its authorized MCP inventory. Packet paths are worktree-root relative, so a
    worker that resolves ``return_artifact`` against its own cwd lands the file
    at ``<worktree>/<lane_cwd>/<relative>`` and completion prevalidation blocks
    the finished run. Map any such stray output back onto the declared path.

    Only regular, non-symlink files contained in the worktree are moved, and an
    output already present at its declared path always wins -- a stray is never
    allowed to overwrite it. Returns the relative paths actually reclaimed.
    """

    root = Path(worktree_root).resolve(strict=True)
    lane_cwd = root / _safe_relative(lane_cwd_relative, field="lane cwd")
    reclaimed: list[str] = []
    for value in relative_paths:
        relative = _safe_relative(str(value), field="lane output")
        destination = root / relative
        # An output already at the declared path is authoritative.
        if os.path.lexists(destination):
            continue
        source = lane_cwd / relative
        if source.is_symlink() or not source.is_file():
            continue
        try:
            source.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
        except OSError:
            continue
        reclaimed.append(relative)
    return tuple(reclaimed)


def prepare_worktree_outputs(
    repo_root: Path,
    worktree_root: Path,
    authority: Mapping[str, object],
) -> PreparedWorktreeOutputs:
    """Capture validated completion bytes before any integration mutation."""

    task_id = str(authority.get("task_id", ""))
    lane = str(authority.get("lane", ""))
    result_relative = _safe_relative(
        str(authority.get("expected_result_path", "")),
        field="expected_result_path",
    )
    outbox_relative = _safe_relative(
        str(authority.get("expected_outbox_path", "")),
        field="expected_outbox_path",
    )
    write_paths = authority.get("write_paths")
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
        or not isinstance(write_paths, list)
        or any(not isinstance(item, str) for item in write_paths)
        or not any(_contains(item, result_relative) for item in write_paths)
    ):
        raise DispatchContextError("bridge authority identity or write scope is invalid")
    outbox_match = re.fullmatch(
        r"departments/([^/]+)/outbox/([^/]+)-response\.md",
        outbox_relative,
    )
    if (
        not outbox_match
        or outbox_match.group(1) not in MAILBOX_NAMESPACES
        or outbox_match.group(2) != task_id
    ):
        raise DispatchContextError("expected outbox path is not canonical")

    # Validate both sources before publishing either. The envelope is the
    # watcher-visible commit marker and is always published last.
    result_bytes = _read_contained_regular(
        Path(worktree_root),
        result_relative,
        label="return artifact",
        maximum_bytes=8 * 1024 * 1024,
    )
    try:
        result_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DispatchContextError("return artifact is not UTF-8") from exc
    envelope_bytes = _read_contained_regular(
        Path(worktree_root),
        outbox_relative,
        label="response envelope",
        maximum_bytes=256 * 1024,
    )
    envelope, summary = _parse_response_envelope(envelope_bytes)
    # Normalize-and-promote rather than strand: the envelope is worker-authored
    # metadata whose identity fields are fully determined by the trusted launch
    # authority. A completion that carries a real, validated artifact (checked
    # above) and committed residue (integrated by the supervisor) must not be
    # exit-75 stranded on a metadata nit -- a non-canonical status, a missing
    # required field, or an unexpected extra. Reconstruct a canonical envelope
    # from the authority, carrying only the worker's coerced status intent and
    # summary prose across. Genuinely-missing work still blocks: an empty/absent
    # artifact fails _read_contained_regular, an empty summary fails the parser,
    # and uncommitted residue fails integration upstream. See
    # _state/consults/envelope-prevalidation-fix.md.
    canonical_status = _coerce_status(envelope.get("status", ""))
    # CC-03: carry every reconciliation pin/fence across the bridge, taken from
    # the trusted launch authority rather than from anything the worker wrote.
    normalized_bytes = _render_response_envelope(
        task_id=task_id,
        lane=lane,
        result_relative=result_relative,
        status=canonical_status,
        summary=summary,
        reconciliation_echo=validate_reconciliation_echo(
            authority.get("reconciliation_echo")
        ),
    )
    _validate_destination(
        Path(repo_root),
        result_relative,
        result_bytes,
        label="return artifact",
        reclaim_board_blocked_stub_for=task_id,
    )
    _validate_destination(
        Path(repo_root),
        outbox_relative,
        normalized_bytes,
        label="response envelope",
    )
    return PreparedWorktreeOutputs(
        task_id=task_id,
        result_relative=result_relative,
        outbox_relative=outbox_relative,
        result_bytes=result_bytes,
        envelope_bytes=normalized_bytes,
        status=canonical_status,
    )


def validate_worktree_outputs(
    repo_root: Path,
    worktree_root: Path,
    authority: Mapping[str, object],
) -> dict[str, object]:
    """Validate completion sources and destinations without publishing either."""

    prepared = prepare_worktree_outputs(repo_root, worktree_root, authority)
    return {
        "status": prepared.status,
        "artifact_path": str(Path(repo_root) / prepared.result_relative),
        "artifact_sha256": _sha256_bytes(prepared.result_bytes),
        "envelope_path": str(Path(repo_root) / prepared.outbox_relative),
        "envelope_sha256": _sha256_bytes(prepared.envelope_bytes),
    }


def publish_prepared_worktree_outputs(
    repo_root: Path,
    prepared: PreparedWorktreeOutputs,
) -> dict[str, object]:
    """Publish the exact bytes captured before code integration."""

    result_path, result_idempotent = _atomic_publish(
        Path(repo_root),
        prepared.result_relative,
        prepared.result_bytes,
        label="return artifact",
        reclaim_board_blocked_stub_for=prepared.task_id,
    )
    envelope_path, envelope_idempotent = _atomic_publish(
        Path(repo_root),
        prepared.outbox_relative,
        prepared.envelope_bytes,
        label="response envelope",
    )
    return {
        "status": prepared.status,
        "artifact_published": True,
        "artifact_idempotent": result_idempotent,
        "artifact_path": str(result_path),
        "artifact_sha256": _sha256_bytes(prepared.result_bytes),
        "envelope_published": True,
        "envelope_idempotent": envelope_idempotent,
        "envelope_path": str(envelope_path),
        "envelope_sha256": _sha256_bytes(prepared.envelope_bytes),
    }


def bridge_worktree_outputs(
    repo_root: Path,
    worktree_root: Path,
    authority: Mapping[str, object],
) -> dict[str, object]:
    """Backward-compatible one-shot prepare and publish wrapper."""

    return publish_prepared_worktree_outputs(
        repo_root,
        prepare_worktree_outputs(repo_root, worktree_root, authority),
    )


def publish_blocked_completion(
    *,
    repo_root: Path,
    task_id: str,
    lane: str,
    return_artifact: str,
    compatibility_namespace: str,
    reason: str,
) -> dict[str, object]:
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
        or compatibility_namespace not in MAILBOX_NAMESPACES
        or not isinstance(reason, str)
        or not reason.strip()
        or "\x00" in reason
    ):
        raise DispatchContextError("blocked completion identity is invalid")
    artifact_relative = _safe_relative(
        return_artifact, field="return_artifact"
    )
    reason_line = " ".join(reason.strip().split())[:2000]
    artifact_bytes = (
        "blocked\n\n"
        f"# Board dispatch blocked — {task_id}\n\n"
        f"Controller reason: {reason_line}\n"
    ).encode("utf-8")
    outbox_relative = (
        f"departments/{compatibility_namespace}/outbox/{task_id}-response.md"
    )
    envelope_bytes = (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        f"from: {LANE_TO_MODEL[lane]}\n"
        "to: chrono\n"
        "type: RESULT\n"
        "status: blocked\n"
        f"return_artifact: {artifact_relative}\n"
        "---\n\n"
        f"Board dispatch was blocked by the controller: {reason_line}\n"
    ).encode("utf-8")
    if artifact_relative == outbox_relative:
        # The common packet shape declares the outbox response path as its own
        # return_artifact. Writing the bare artifact there first and then the
        # envelope aims two different payloads at one file, so the envelope
        # write trips the no-clobber guard and blocked settlement publishes no
        # envelope at all -- leaving a frontmatter-less file the reconciler
        # reads as status '', which strands the task in-flight holding its
        # write_scope. Publish the envelope alone: it already carries
        # `status: blocked` and the controller reason, so the separate artifact
        # would add nothing. Distinct paths keep the two-write behaviour, and
        # every containment and no-clobber guard still runs on the write below.
        envelope_path, envelope_idempotent = _atomic_publish(
            Path(repo_root),
            outbox_relative,
            envelope_bytes,
            label="blocked response envelope",
        )
        artifact_path, artifact_idempotent = envelope_path, envelope_idempotent
    else:
        artifact_path, artifact_idempotent = _atomic_publish(
            Path(repo_root),
            artifact_relative,
            artifact_bytes,
            label="blocked return artifact",
        )
        envelope_path, envelope_idempotent = _atomic_publish(
            Path(repo_root),
            outbox_relative,
            envelope_bytes,
            label="blocked response envelope",
        )
    return {
        "status": "blocked",
        "artifact_path": str(artifact_path),
        "artifact_idempotent": artifact_idempotent,
        "envelope_path": str(envelope_path),
        "envelope_idempotent": envelope_idempotent,
    }


def _write_context(path: Path, context: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise DispatchContextError("context output already exists")
    data = json.dumps(context, sort_keys=True, indent=2) + "\n"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--task-file", type=Path, required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--generation", type=int, required=True)
    build.add_argument("--output", type=Path)
    blocked = subparsers.add_parser("blocked")
    blocked.add_argument("--repo-root", type=Path, required=True)
    blocked.add_argument("--task-id", required=True)
    blocked.add_argument("--lane", required=True)
    blocked.add_argument("--return-artifact", required=True)
    blocked.add_argument("--compatibility-namespace", required=True)
    blocked.add_argument("--reason", required=True)
    cleanup = subparsers.add_parser("cleanup-canary")
    cleanup.add_argument("--repo-root", type=Path, required=True)
    cleanup.add_argument("--context-file", type=Path, required=True)
    batch = subparsers.add_parser("schedule-batch")
    batch.add_argument("--repo-root", type=Path, required=True)
    batch.add_argument("--task-file", type=Path, action="append", required=True)
    batch.add_argument("--concurrency", type=int, required=True)
    fanout = subparsers.add_parser("build-fanout")
    fanout.add_argument("--repo-root", type=Path, required=True)
    fanout.add_argument("--parent-task-file", type=Path, required=True)
    fanout.add_argument("--output-dir", type=Path, required=True)
    fanout.add_argument("--assignment", action="append", required=True)
    fanout.add_argument("--verification-contract")
    args = parser.parse_args(argv)
    command = args.command or "build"
    try:
        if command == "build":
            context = build_context(
                args.repo_root,
                args.task_file,
                attempt_id=args.attempt_id,
                generation=args.generation,
            )
            if args.output is not None:
                _write_context(args.output, context)
            else:
                print(json.dumps(context, sort_keys=True, indent=2))
        elif command == "blocked":
            receipt = publish_blocked_completion(
                repo_root=args.repo_root,
                task_id=args.task_id,
                lane=args.lane,
                return_artifact=args.return_artifact,
                compatibility_namespace=args.compatibility_namespace,
                reason=args.reason,
            )
            print(json.dumps(receipt, sort_keys=True))
        elif command == "cleanup-canary":
            receipt = cleanup_canary(
                repo_root=args.repo_root,
                context_file=args.context_file,
            )
            print(json.dumps(receipt, sort_keys=True))
        elif command == "schedule-batch":
            result = schedule_board_batch(
                args.repo_root,
                args.task_file,
                concurrency=args.concurrency,
                logical_only=True,
            )
            print(json.dumps({
                "run_now": list(result.run_now),
                "must_wait": list(result.must_wait),
                "reasons": result.reasons,
                "reservation_snapshot_sha256": result.reservation_snapshot_sha256,
            }, sort_keys=True))
        elif command == "build-fanout":
            packets = build_board_fanout_members(
                args.repo_root,
                args.parent_task_file,
                args.output_dir,
                args.assignment,
                (
                    json.loads(args.verification_contract)
                    if args.verification_contract
                    else None
                ),
            )
            print(json.dumps([str(path) for path in packets]))
        else:  # pragma: no cover - argparse owns this
            parser.error("a command is required")
    except DispatchContextError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
