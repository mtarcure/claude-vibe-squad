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
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping, NoReturn, Sequence

try:
    import board_router
    from durable_publish import rename_noreplace
    from held_action_gate import HELD_CATEGORIES
    from lane_capability_enforcement import adapter_path_for
    from launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256
    from seatbelt_profile import DEFAULT_LANE_PATH, LANE_CLI_PATHS
    import specialist_capability_source as scs
    from verification_contract import (
        ContractError as VerificationContractError,
        read_yaml_frontmatter,
        validate_verification_contract as validate_contract_schema,
    )
except ImportError:  # pragma: no cover - package-context fallback
    from . import board_router  # type: ignore[no-redef]
    from .durable_publish import rename_noreplace  # type: ignore[no-redef]
    from .held_action_gate import HELD_CATEGORIES  # type: ignore[no-redef]
    from .lane_capability_enforcement import adapter_path_for  # type: ignore[no-redef]
    from .launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256  # type: ignore[no-redef]
    from .seatbelt_profile import DEFAULT_LANE_PATH, LANE_CLI_PATHS  # type: ignore[no-redef]
    from . import specialist_capability_source as scs  # type: ignore[no-redef]
    from .verification_contract import (  # type: ignore[no-redef]
        ContractError as VerificationContractError,
        read_yaml_frontmatter,
        validate_verification_contract as validate_contract_schema,
    )


CONTEXT_SCHEMA = "go-live-trusted-context/v1"
AUTHORITY_SCHEMA = "go-live-authority/v1"
TASK_RE = re.compile(
    r"^TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[A-Za-z0-9][A-Za-z0-9-]*$"
)
ATTEMPT_RE = re.compile(r"^d-[0-9a-f]{32}$")
# Hard ceiling on the assembled trusted-launch prompt (injected briefing +
# packet). The briefing differs per lane, so this bounds the SUM, never the
# packet alone -- a packet size that launched on one family proves nothing
# about another.
#
# Raised from 32768 on 2026-08-16 after measurement, not to quiet a test.
# The assembled prompt embeds ABSOLUTE paths, so the same logical packet has a
# different size in different checkouts. A minimal, entirely legitimate bounty
# swarm child measured 32,688-32,730 bytes on CI's 69-character checkout path
# and ~29 bytes-per-embedded-path less on the maintainer's 41-character one.
# That put a valid dispatch 38 bytes under the old ceiling locally and OVER it
# in CI -- so whether a real bounty dispatch was permitted depended on where the
# repository happened to live, and private CI had been red for weeks because of
# it. A ceiling a minimal valid packet cannot clear is not bounding a risk.
#
# 40960 keeps a real bound (the prompt is still ~10k tokens) while leaving
# ~8 KiB of headroom, which is hundreds of characters of additional path depth
# per embedded reference. The swarm dispatch suites are the regression guard,
# and CI is the stricter environment because its paths are longer.
TRUSTED_LAUNCH_PROMPT_LIMIT = 40960
IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACES = frozenset(
    {"coding", "security", "content", "sysmgmt", "research", "shared"}
)
MAILBOX_NAMESPACES = frozenset(NAMESPACES - {"shared"})
CLI_TRANSPORT_FAILURE_CLASSES = frozenset({"cli_missing", "cli_nonzero", "cli_timeout"})
MEMORY_APERTURES = frozenset({"rich", "focused", "cold", "pool_blind", "none"})
# One bound for the creation-time selector and the promotion-time validator, so
# a packet can never declare evidence that promotion would later refuse to read.
MAXIMUM_EVIDENCE_OUTPUTS = 16
MODEL_TO_LANE = {
    "gpt-codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "kimi": "kimi",
}
LANE_TO_MODEL = {value: key for key, value in MODEL_TO_LANE.items()}
WORKLOAD_CLASS_BY_CAPABILITY = {
    "implementation": "repo-build-test",
    "media_production": "browser-media",
    "code_review": "cpu-light",
    "content_text": "cpu-light",
    "extraction": "cpu-light",
    "game_design": "cpu-light",
    "judgment": "cpu-light",
    "research_synthesis": "cpu-light",
    "security_defense": "cpu-light",
    "security_reasoning": "cpu-light",
}
LANE_NETWORK_SCOPE = {
    "codex": "openai-subscription",
    "claude": "anthropic-subscription",
    # Gemini remains a native-CLI lane, but its supported authentication is
    # the explicit API-key exception rather than subscription OAuth.
    "gemini": "gemini-api-key",
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


def timeout_budget_for_mode(mode: str) -> int:
    """Return the bounded backstop; non-bounty modes use ``"timeout_seconds": 2700``.

    Raised from 1800 to 2700 for non-bounty modes on 2026-08-10, operator-approved,
    from measured distribution rather than from the wall deaths. Across 52 dispatches
    over two days: median successful run 12m, but 11 of 45 successes landed in the
    20-30m band -- crowding the ceiling, so any retry or slow tool call truncated
    legitimate work. The four tasks that DIED at 1800s were over-scoped packets, and
    a larger wall would not have saved them; only right-sizing does that.
    Bounty stays at 3600.
    """

    return 3600 if mode == "bounty" else 2700


class DispatchContextError(ValueError):
    """A packet or bridge operation cannot be represented safely."""


class ModeExitVerificationError(DispatchContextError):
    """A declared mode-close manifest did not earn envelope publication."""


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
        not isinstance(item, str) or not item.strip() or "\n" in item or "\r" in item
        for item in assignments
    ):
        raise DispatchContextError(
            "board fan-out assignments must be non-empty single lines"
        )

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
            raise DispatchContextError(
                "supplied fan-out verification contract is invalid"
            )
    original_scope = parse_scope(fields.get("write_scope", "[]"), field="write_scope")
    output = Path(output_dir).resolve(strict=False)
    try:
        output.relative_to(root / "_state" / "board-dispatch")
    except ValueError as exc:
        raise DispatchContextError(
            "fan-out build directory is outside board state"
        ) from exc
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise DispatchContextError("fan-out build directory must be empty")

    replaced = {
        "id",
        "return_artifact",
        "write_scope",
        "read_scope",
        "mandatory_review",
        "review_model",
        "model_override_reason",
        "dispatch_kind",
        "panel_id",
        "panel_mode",
        "panel_members",
        "panel_member_ids",
        "panel_policy",
        "panel_quorum",
        "panel_timeout_seconds",
        "panel_max_parallel",
        "panel_return_contract",
        "panel_member_write_scope",
        "verification_contract",
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
class PreparedEvidenceOutput:
    relative_path: str
    role: str
    declared_by: str
    data: bytes
    content_sha256: str


@dataclass(frozen=True)
class PreparedWorktreeOutputs:
    task_id: str
    result_relative: str
    outbox_relative: str
    result_bytes: bytes
    envelope_bytes: bytes
    status: str
    mode: str = ""
    attempt_id: str = ""
    generation: int = 0
    run_id: str = ""
    evidence_outputs: tuple[PreparedEvidenceOutput, ...] = ()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(Path(path).read_bytes())
    except OSError as exc:
        raise DispatchContextError(
            f"required file is unavailable: {path}: {exc}"
        ) from exc


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
    return _parse_task_text(text)


def _parse_task_text(text: str) -> tuple[dict[str, str], str]:
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
        if not separator or not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in fields:
            raise DispatchContextError(
                f"invalid or duplicate frontmatter row: {line!r}"
            )
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
        # A read-only verdict role (write_scope: []) legitimately has no
        # return_artifact -- its verdict lives in the outbox envelope. Rejecting
        # the empty string here made that role, which send-task.sh explicitly
        # exempts from mandatory_review to avoid an infinite review regress,
        # undispatchable: it passed validation and then died in the builder.
        if field == "return_artifact" and value == "":
            return ""
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
            "task packet is missing required frontmatter field: verification_contract"
        )
    try:
        contract = validate_contract_schema(json.loads(raw_contract))
    except (json.JSONDecodeError, VerificationContractError) as exc:
        raise DispatchContextError(f"verification_contract is invalid: {exc}") from exc
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


def dispatcher_workload_class(repo_root: Path, specialist: str) -> str:
    """Classify only from the canonical runtime map; unknowns fail closed.

    Workload class is a RESOURCE model -- how much memory and how many processes
    an attempt is expected to need. It is deliberately not derived from safety
    tags. `live_target` used to short-circuit to the `security-untrusted` policy
    here, and that conflated two unrelated axes with a concrete cost: that policy
    ships `calibrated=False`, an uncalibrated policy fails host-admission clause 4
    unconditionally, and on 2026-08-08 the runtime map began tagging 15 of 73
    specialists `live_target`. Every offensive role -- exploit-developer,
    experimental-attacker, red-team-operator, scout, impact-validator -- became
    categorically undispatchable, reported as "projected resident use exceeds
    budget" on a host with 75% memory free.

    The 15 were never one resource shape either: some are `implementation`
    (repo-build-test) and some `judgment`/`security_reasoning` (cpu-light).

    Nothing is weakened by removing it, because the tag enforced nothing else --
    measured 2026-08-09, this line was `live_target`'s ONLY consumer in the entire
    codebase. Risk for these roles is carried where it belongs and still is:
    `safety_level: high`, `heightened_risk: true`,
    `requires_approval: [Write, Bash, WebFetch]`, and `operator_gate` entries such
    as red-team-operator's `[offensive_execution, production_mutation]`.
    """

    row = _runtime_row(Path(repo_root), specialist)
    safety_raw = row.get("safety_tags", "")
    if not safety_raw.startswith("[") or not safety_raw.endswith("]"):
        raise DispatchContextError("runtime-map safety_tags are invalid")
    safety_tags = [item.strip() for item in safety_raw[1:-1].split(",") if item.strip()]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", item) for item in safety_tags):
        raise DispatchContextError("runtime-map safety_tags are invalid")
    capability_class = row.get("capability_class", "")
    try:
        return WORKLOAD_CLASS_BY_CAPABILITY[capability_class]
    except KeyError as exc:
        raise DispatchContextError(
            f"runtime-map capability class is unmeasured: {capability_class!r}"
        ) from exc


def _selected_profile(row: Mapping[str, str], lane: str) -> str:
    matches = []
    for prefix in ("primary", "backup", "escalate", "review", "throughput"):
        row_lane = row.get(f"{prefix}_lane", "")
        if row_lane == lane:
            profile = row.get(f"{prefix}_profile", "")
            if profile and profile != "none":
                matches.append(profile)
    if not matches:
        raise DispatchContextError(f"runtime map does not select a {lane} profile")
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
                raise DispatchContextError(
                    "profile registry is missing required fields"
                )
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


def _trusted_lane_args(lane: str, profile: Mapping[str, str]) -> tuple[str, ...]:
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
    return (*base, "--model", model)


def trusted_lane_args_for(
    repo_root: Path, *, lane: str, specialist: str
) -> tuple[str, ...]:
    return _trusted_lane_args(
        lane,
        _profile_row(
            Path(repo_root),
            lane=lane,
            profile_id=_selected_profile(
                _runtime_row(Path(repo_root), specialist), lane
            ),
        ),
    )


def _lane_version(executable: Path) -> str:
    environment = {
        "PATH": DEFAULT_LANE_PATH,
        "NO_COLOR": "1",
        "HOME": os.environ.get("HOME", ""),
    }
    completed = subprocess.run(
        (str(executable), "--version"),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=environment,
        timeout=5,
        close_fds=True,
    )
    if (
        completed.returncode != 0
        or not (lines := completed.stdout.splitlines())
        or not lines[0].strip()
    ):
        raise DispatchContextError("lane version probe failed")
    return lines[0].replace("\t", " ")[:256]


def lane_policy_evidence_for(repo_root: Path, lane: str) -> dict[str, str]:
    path = Path(repo_root) / "model-lanes/lane-capabilities.tsv"
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = [
                row
                for row in csv.DictReader(stream, delimiter="\t")
                if MODEL_TO_LANE.get(row.get("lane", ""), row.get("lane", "")) == lane
            ]
    except OSError as exc:
        raise DispatchContextError(f"lane policy is unavailable: {exc}") from exc
    if len(rows) != 1:
        raise DispatchContextError(f"lane policy must contain exactly one {lane!r} row")
    policy = rows[0].get("auth_policy", "")
    auth_class = policy.removesuffix("-drop-provider-keys").removesuffix("-only")
    expected = {
        "codex": "subscription",
        "claude": "subscription",
        "gemini": "gemini-api-key",
        "kimi": "managed-login",
    }.get(lane)
    if auth_class != expected:
        raise DispatchContextError("lane auth policy is outside the closed contract")
    return {
        "auth_class": auth_class,
        "lane_policy_row_sha256": _sha256_bytes(_canonical_json(rows[0])),
    }


def lane_runtime_inventory(
    repo_root: Path,
    *,
    version_reader: Callable[[Path], str] | None = None,
) -> tuple[dict[str, Any], ...]:
    try:
        with (repo_root / "shared/specialist-runtime-map.tsv").open(
            newline=""
        ) as stream:
            runtime_rows = list(csv.DictReader(stream, delimiter="\t"))
    except OSError as exc:
        raise DispatchContextError(
            f"lane inventory source is unavailable: {exc}"
        ) from exc
    results = []
    for lane, executable in LANE_CLI_PATHS.items():
        policy_evidence = lane_policy_evidence_for(repo_root, lane)
        selections = {}
        for row in runtime_rows:
            for tier in ("primary", "backup", "escalate", "review", "throughput"):
                profile_id = (
                    row.get(f"{tier}_profile")
                    if row.get(f"{tier}_lane") == lane
                    else None
                )
                if not profile_id or profile_id == "none":
                    continue
                profile = _profile_row(repo_root, lane=lane, profile_id=profile_id)
                args = _trusted_lane_args(lane, profile)
                selections[profile_id] = {
                    "profile_id": profile_id,
                    "registry_model": profile["model_id"],
                    "effective_model": args[args.index("--model") + 1],
                }
        try:
            version = (version_reader or _lane_version)(executable)
        except (OSError, subprocess.SubprocessError, DispatchContextError):
            version = ""
        results.append(
            {
                "lane": lane,
                "literal_executable": str(executable),
                "resolved_executable": os.path.realpath(executable),
                "version": version,
                "installed": bool(version),
                "auth_class": policy_evidence["auth_class"],
                "selections": tuple(selections[key] for key in sorted(selections)),
            }
        )
    return tuple(results)


def _canonical_role(repo_root: Path, row: Mapping[str, str]) -> Path:
    specialist = row["specialist"]
    namespace = row["source_namespace"]
    if namespace == "shared":
        candidate = repo_root / "shared" / "specialists" / f"{specialist}.md"
    else:
        candidate = (
            repo_root / "departments" / namespace / "specialists" / f"{specialist}.md"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DispatchContextError(
            f"canonical role is unavailable or outside repo: {exc}"
        ) from exc
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


def packet_evidence_outputs(
    fields: Mapping[str, str],
    write_scope: Sequence[str],
) -> tuple[dict[str, str], ...]:
    """Return every evidence path the packet declares at creation time.

    Two exact declarations are honored, and nothing else -- this never scans a
    worktree, infers evidence, or guesses at what a worker produced:

    ``swarm_member_result``
        The swarm member sidecar. Valid only for a swarm member.
    ``evidence_outputs``
        A YAML inline list of PoCs, harnesses, logs, and other unique outputs,
        valid for **every** packet shape. Ordinary evidence is the majority
        case and the one that has actually been stranding in pruned worktrees;
        selecting only the swarm sidecar left the common case unprotected.

    Each declared path must be worktree-relative, inside ``write_scope``, and
    distinct. A declared file that the worker did not produce blocks promotion
    upstream rather than being skipped: declaring evidence is a commitment.
    """

    outputs: list[dict[str, str]] = []
    seen: set[str] = set()

    raw = _unquote(fields.get("swarm_member_result", ""))
    if raw:
        if (
            _unquote(fields.get("dispatch_kind", "")) != "swarm"
            or _unquote(fields.get("swarm_role", "")) != "member"
        ):
            raise DispatchContextError(
                "swarm_member_result is valid only for a swarm member"
            )
        relative = _safe_relative(raw, field="swarm_member_result")
        if not any(_contains(scope, relative) for scope in write_scope):
            raise DispatchContextError(
                "swarm_member_result is outside packet write_scope"
            )
        seen.add(relative)
        outputs.append(
            {
                "path": relative,
                "role": "swarm-member-result",
                "declared_by": "swarm_member_result",
            }
        )

    declared = _unquote(fields.get("evidence_outputs", "")).strip()
    if declared:
        # `_safe_relative` normalizes a trailing slash away, so a directory has
        # to be rejected from the raw text: a scope is a prefix, an evidence
        # output is one exact file whose bytes are hashed at creation.
        for raw_part in declared.strip("[]").split(","):
            if raw_part.strip().endswith("/"):
                raise DispatchContextError(
                    "evidence_outputs must name exact files, not directories: "
                    + raw_part.strip()
                )
        for relative in parse_scope(declared, field="evidence_outputs"):
            if relative in seen:
                raise DispatchContextError(
                    f"evidence_outputs declares a duplicate path: {relative}"
                )
            if not any(_contains(scope, relative) for scope in write_scope):
                raise DispatchContextError(
                    f"evidence_outputs path is outside packet write_scope: {relative}"
                )
            seen.add(relative)
            outputs.append(
                {
                    "path": relative,
                    "role": "declared-evidence",
                    "declared_by": "evidence_outputs",
                }
            )

    if len(outputs) > MAXIMUM_EVIDENCE_OUTPUTS:
        raise DispatchContextError(
            f"a packet may declare at most {MAXIMUM_EVIDENCE_OUTPUTS} evidence outputs"
        )
    return tuple(outputs)


def packet_memory_contract(fields: Mapping[str, str]) -> tuple[str, str | None]:
    """Validate and return the packet's trusted-launch memory aperture."""

    memory_aperture = _unquote(fields.get("memory_aperture", "")) or "cold"
    if memory_aperture not in MEMORY_APERTURES:
        raise DispatchContextError("memory_aperture is invalid")
    memory_focus = _unquote(fields.get("memory_focus", "")) or None
    if memory_focus is not None and (
        len(memory_focus) > 256
        or any(character in memory_focus for character in "\x00\r\n")
    ):
        raise DispatchContextError("memory_focus is invalid")
    if (memory_aperture == "focused") != (memory_focus is not None):
        raise DispatchContextError("focused memory requires one exact memory_focus")
    return memory_aperture, memory_focus


def gitignored_read_scope_note(
    read_scope: Sequence[str], canonical_root: str
) -> str:
    """Tell the worker where gitignored read_scope entries actually resolve.

    `_state/` is gitignored, so it does not exist in the worker's worktree. A
    read_scope naming `_state/...` is therefore unreachable at that relative
    path, and workers have burned turns rediscovering that the artifacts live
    in the primary checkout. The authorization is unchanged -- this only says
    where the authorized paths are.
    """

    absent = [p for p in read_scope if isinstance(p, str) and p.startswith("_state/")]
    if not absent:
        return ""
    listed = ", ".join(f"`{p}`" for p in sorted(dict.fromkeys(absent)))
    return (
        "## Where your gitignored read scope resolves\n\n"
        f"{listed} — these are under `_state/`, which is **gitignored and therefore absent from "
        "your worktree**. Read them from the primary checkout at "
        f"`{canonical_root}/` (for example `{canonical_root}/{sorted(absent)[0]}`). "
        "Your authorization is unchanged; this only tells you where the authorized paths are, "
        "so you do not spend turns discovering that the relative path does not exist.\n"
    )


def delivery_contract_note(
    return_artifact: str, write_scope: Sequence[str]
) -> str:
    """State the three ways a lane's work gets discarded for non-work reasons.

    Observed 2026-08-15: four lanes died on mechanics rather than the task --
    two CLI timeouts, one scope violation (`worker committed paths outside the
    integration scope`), and one `return artifact is missing, non-regular, or a
    symlink`. In each case the fix itself may have been sound and was thrown
    away. The packet cannot prevent these; the launch prompt can.
    """

    if not return_artifact:
        return ""
    scope = ", ".join(f"`{p}`" for p in write_scope) or "(none declared)"
    return (
        "## Delivery contract — three ways good work gets discarded\n\n"
        f"1. **Write `{return_artifact}` as a plain file EARLY**, then update it as you go. Not a "
        "symlink, not a directory, and not left to the end. A lane whose artifact is missing at "
        "completion is discarded whole, however good the fix was.\n"
        f"2. **Write only inside your write scope**: {scope}. Integration refuses a commit touching "
        "anything else and discards the entire attempt — it does not partially apply. If the task "
        "genuinely needs another path, stop and report it: a scope request costs one turn, a scope "
        "violation costs the lane.\n"
        "3. **If you are running long, land what is complete and write the artifact anyway.** A "
        "truthful partial naming what remains is a useful result; being killed mid-flight with no "
        "artifact is not.\n"
    )


def assemble_trusted_launch_prompt(
    packet_text: str,
    *,
    task_id: str,
    attempt_id: str,
    generation: int,
    memory_aperture: str,
    read_scope: Sequence[str] = (),
    canonical_root: str = "",
    return_artifact: str = "",
    write_scope: Sequence[str] = (),
) -> str:
    """Assemble the exact prompt whose bytes are bounded before launch."""

    if memory_aperture == "none":
        memory_instructions = (
            "This engagement has memory aperture `none`. Do not call recall, record, "
            "get_note, lifecycle, or vault browse tools. Memory is not a task gate."
        )
    else:
        recall_instruction = (
            '- Recall prior context ONCE: `recall(query="<task-specific terms>", limit=5)`. '
            "Pass no filters; the vault enforces this engagement's aperture."
            if memory_aperture in {"rich", "focused"}
            else f"- Do not call recall or get_note: aperture `{memory_aperture}` forbids reads."
        )
        memory_instructions = (
            "Durable memory is BEST-EFFORT telemetry. Make each permitted call at most "
            "once, never search the repo for schemas, and never retry. A memory error is "
            "never a task gate: note it briefly in the artifact and continue. The server "
            "aperture overrides any generic memory-policy wording in the packet.\n"
            f"{recall_instruction}\n"
            "- Write the return artifact and completion envelope FIRST. Only afterward, "
            "record the outcome once with: "
            f'`record(note_type="learning", fields={{"title":"<one-line outcome>",'
            f'"body":"<two or three short sentences referencing {task_id}>",'
            '"target":"<component or target>","attack_class":"none"}})`. '
            "The server binds source_task, candidate status, sensitivity floor, and focused "
            "target; do not add or override them. Do not call record_usage or set_status."
        )
    return (
        "Execute the exact task packet below as a fresh isolated specialist CLI. "
        "Do not claim or redispatch it; this launch is already bound to the registry "
        f"attempt {attempt_id}, generation {generation}. Write the declared return "
        "artifact and response envelope inside this worktree. The supervisor validates "
        "and promotes the artifact first and the envelope last.\n\n"
        f"{memory_instructions}\n\n"
        f"{gitignored_read_scope_note(read_scope, canonical_root)}"
        f"{delivery_contract_note(return_artifact, write_scope)}\n"
        "## Exact task packet\n\n"
        f"{packet_text.rstrip()}\n"
    )


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
    canary_autoclean_raw = _unquote(fields.get("board_canary_autoclean", "false"))
    if canary_autoclean_raw not in {"true", "false"}:
        raise DispatchContextError("board_canary_autoclean must be true or false")
    canary_autoclean = canary_autoclean_raw == "true"
    if not TASK_RE.fullmatch(task_id):
        raise DispatchContextError("task id is invalid")
    if not ATTEMPT_RE.fullmatch(attempt_id):
        raise DispatchContextError("attempt id is not a registry delivery identity")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation <= 0
    ):
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
        raise DispatchContextError(
            f"native lane adapter cannot be resolved: {exc}"
        ) from exc
    try:
        adapter.relative_to(root)
    except ValueError as exc:
        raise DispatchContextError("native lane adapter escapes repository") from exc
    executable = LANE_CLI_PATHS.get(lane)
    if executable is None:
        raise DispatchContextError(f"no trusted executable for lane {lane}")
    resolved_executable = Path(os.path.realpath(executable))
    if (
        not executable.is_absolute()
        or not resolved_executable.is_file()
        or not os.access(resolved_executable, os.X_OK)
    ):
        raise DispatchContextError(
            f"trusted lane executable is unavailable: {executable}"
        )

    write_scope = parse_scope(fields.get("write_scope", ""), field="write_scope")
    evidence_outputs = packet_evidence_outputs(fields, write_scope)
    # A read-only verdict role declares no artifact and an empty write_scope;
    # `any()` over an empty scope is always False, so this containment check
    # rejected it unconditionally. Nothing to contain means nothing to check.
    if return_artifact and not any(
        _contains(scope, return_artifact) for scope in write_scope
    ):
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
    explicit_reads = parse_scope(fields.get("read_scope", "[]"), field="read_scope")
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

    source_lane = LANE_TO_MODEL[lane]
    try:
        capability_entries, _ = scs.load_source(root)
        capability_entry = capability_entries[(specialist, source_lane)]
        capability_surface_sha256 = scs.role_surface_sha256(capability_entry)
    except (scs.CapabilitySourceError, KeyError) as exc:
        raise DispatchContextError(
            "specialist capability surface is unavailable"
        ) from exc
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
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, int)
        or created_at <= 0
    ):
        raise DispatchContextError("creation time must be a positive integer")
    launch_nonce = secrets.token_hex(32) if nonce is None else nonce
    if not SHA256_RE.fullmatch(launch_nonce) or launch_nonce == "0" * 64:
        raise DispatchContextError("nonce must be a nonzero 64-hex value")

    memory_aperture, memory_focus = packet_memory_contract(fields)
    memory_context = {
        "schema": "chrono-vault-context/v1",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "mode": mode,
        "aperture": memory_aperture,
        "focus": memory_focus,
        "engagement_start": datetime.fromtimestamp(
            created_at, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z"),
    }
    packet_text = packet_path.read_text(encoding="utf-8")
    task_prompt = assemble_trusted_launch_prompt(
        packet_text,
        task_id=task_id,
        attempt_id=attempt_id,
        generation=generation,
        memory_aperture=memory_aperture,
        read_scope=read_scope,
        canonical_root=root.as_posix(),
        return_artifact=return_artifact,
        write_scope=write_scope,
    )
    if len(task_prompt.encode("utf-8")) > TRUSTED_LAUNCH_PROMPT_LIMIT:
        raise DispatchContextError("task packet is too large for trusted launch prompt")

    expected_outbox = f"departments/{mailbox_namespace}/outbox/{task_id}-response.md"
    authority = {
        "schema": AUTHORITY_SCHEMA,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "run_id": run_id,
        "author_family": author_family,
        "workload_class": dispatcher_workload_class(root, specialist),
        "specialist": specialist,
        "lane": lane,
        **lane_policy_evidence_for(root, lane),
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
        "evidence_outputs": list(evidence_outputs),
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
        "capability_surface_sha256": capability_surface_sha256,
        "memory_context": memory_context,
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
    inbox_path = root / packet_candidates[0]
    archived_path = inbox_path.parent.parent / "archive" / inbox_path.name
    matching_packets = [
        path
        for path in (inbox_path, archived_path)
        if not path.is_symlink()
        and path.is_file()
        and _sha256_file(path) == authority.get("packet_sha256")
    ]
    if len(matching_packets) != 1:
        raise DispatchContextError("canary cleanup packet no longer matches authority")
    packet_path = matching_packets[0]
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
        if (
            not isinstance(entry, dict)
            or entry.get("delivery_attempt_id") != attempt_id
            or type(entry.get("delivery_generation")) is not int
            or entry.get("delivery_generation") != generation
            or entry.get("status") != "complete"
        ):
            raise DispatchContextError(
                "canary cleanup registry identity changed or is not terminal"
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
        raise DispatchContextError(
            f"{label} is unavailable or escapes worktree"
        ) from exc
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

_CANONICAL_ENVELOPE_STATUSES = frozenset({*WORKER_AUTHORABLE_STATUSES, "completed"})

# Exact historical spellings that existing workers may still emit. Keep this
# closed: fuzzy matching lets failure prose inherit a successful status merely
# because it contains text such as ``complete``, ``done``, or even ``ok``.
_RECOGNIZED_STATUS_SPELLINGS = {
    **{status: status for status in _CANONICAL_ENVELOPE_STATUSES},
    "complete_with_scoped_exclusion": "complete",
    "done": "complete",
    "failed": "blocked",
    "blocked_on_review": "blocked",
    "needs human": "needs_human",
    "needs human review": "needs_human",
    "awaiting operator approval": "needs_human",
}


def _coerce_status(raw: str) -> str:
    """Map a worker-authored status onto a canonical settleable value.

    Canonical values and a closed set of historical spellings are recognized
    exactly (case-insensitively); the reconciler further canonicalizes
    ``completed`` -> ``complete``. Anything else defaults to ``needs_review``
    so questionable or unmappable work surfaces to the controller rather than
    silently auto-closing. Never infer status intent from a substring of prose.
    """

    value = (raw or "").strip().lower()
    return _RECOGNIZED_STATUS_SPELLINGS.get(value, "needs_review")


# ── CC-03: reconciliation pin/fence echoes ───────────────────────────────────
# `registry_reconciler.py` holds a task OPEN until the landed response echoes
# every pin and fence its registry entry carries:
#   * capability_response_issue -> capability_card_sha256
#   * swarm_response_issue      -> swarm_spec_sha256
#   * worker_response_issue     -> the legacy assigned-worker delivery fence
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
    """Snapshot the delivery fence, plus legacy assigned-worker fields, at launch."""

    echo = {
        "delivery_attempt_id": attempt_id,
        "delivery_generation": str(generation),
    }

    registry_path = Path(repo_root) / "_state" / "active-tasks.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        return validate_reconciliation_echo(echo)
    try:
        import registry_reconciler as rr
    except ImportError:
        return validate_reconciliation_echo(echo)
    try:
        with rr.locked_registry():
            registry = rr.load_registry()
            entry = registry.get(task_id) if isinstance(registry, dict) else None
    except (OSError, ValueError):
        return validate_reconciliation_echo(echo)
    if not isinstance(entry, dict):
        return validate_reconciliation_echo(echo)
    if (
        entry.get("delivery_attempt_id") != attempt_id
        or type(entry.get("delivery_generation")) is not int
        or entry.get("delivery_generation") != generation
    ):
        raise DispatchContextError(
            "registry delivery fence does not match the launch attempt"
        )
    if not entry.get("delivery_worker_id"):
        return validate_reconciliation_echo(echo)
    echo.update(
        {
            "delivery_worker_id": str(entry.get("delivery_worker_id") or ""),
            "worker_epoch": str(entry.get("worker_epoch") or ""),
            "lease_generation": str(int(entry.get("lease_generation") or 0)),
            "delivery_lane": str(
                entry.get("delivery_lane") or entry.get("to_model") or ""
            ),
        }
    )
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
    failure_class: str | None = None,
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
    failure_row = f"failure_class: {failure_class}\n" if failure_class else ""
    body = summary.strip("\n")
    return (
        "---\n"
        f"id: {task_id}-response\n"
        f"in_response_to: {task_id}\n"
        f"from: {LANE_TO_MODEL[lane]}\n"
        "to: chrono\n"
        "type: RESULT\n"
        f"status: {status}\n"
        f"{failure_row}"
        f"return_artifact: {result_relative}\n"
        f"{echo_rows}"
        "---\n\n"
        f"{body}\n"
    ).encode("utf-8")


# Deliberately the same key charset as `bin/outbox-watcher.sh::frontmatter_field`.
# The two parsers read the SAME envelope on either side of promotion, so a shape
# one accepts and the other rejects is an inconsistency, not a safety margin --
# and this side is the destructive one (a rejection here strands the finished
# artifact, where the watcher merely holds the envelope in place). Nothing
# downstream reads a worker-authored key other than `status`: the published
# envelope is re-rendered from the launch authority by _render_response_envelope.
FLAT_FRONTMATTER_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def _frontmatter_records(text: str) -> list[str]:
    """Split text into awk's record model: `\\n` only, no empty trailing record.

    `str.splitlines` also splits on `\\v`, `\\f`, `\\x1c`-`\\x1e`, `\\x85` and the
    Unicode separators, which awk does not. Line numbers cited in a diagnostic
    have to mean the same line in both parsers, so the split has to match.
    """

    records = text.split("\n")
    if records and records[-1] == "":
        records.pop()
    return records


def _parse_flat_frontmatter(
    records: list[str], *, subject: str
) -> tuple[dict[str, str], int]:
    """Parse flat-scalar frontmatter, naming what is wrong and where.

    Behavioural twin of `bin/outbox-watcher.sh::frontmatter_field`, down to the
    rejection sentences -- `scripts/python/tests/test_envelope_parser_pair.py`
    drives the shipped awk program and this function over the same fixtures and
    fails if they diverge on either verdict or wording.

    Nested mappings stay rejected: the flat-scalar contract is deliberate and
    other consumers depend on it. What changes is that the worker is told which
    key nested and on which line, which is repairable, rather than that its
    frontmatter is "invalid", which is not.

    Returns (fields, closing_line_number), the latter 1-based.
    """

    def reject(message: str) -> NoReturn:
        raise DispatchContextError(f"{subject} {message}")

    if not records:
        reject("frontmatter is empty; an exact --- delimiter is required at line 1")
    if records[0] != "---":
        reject("frontmatter must begin with an exact --- delimiter at line 1")

    fields: dict[str, str] = {}
    declared_at: dict[str, int] = {}
    empty_key = ""
    empty_line = 0
    closing = 0
    for number, line in enumerate(records[1:], start=2):
        if line == "---":
            closing = number
            break
        # Blank and comment rows do not end an empty-key lookahead: an indented
        # child after either still belongs to that empty key.
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t\v\f\r":
            if empty_key:
                reject(
                    f"frontmatter key {empty_key!r} at line {empty_line} has "
                    f"nested content at line {number}; flat scalar values are "
                    "required"
                )
            reject(
                f"frontmatter line {number} is indented; top-level flat scalar "
                "key/value pairs are required"
            )
        key, separator, value = line.partition(":")
        if not separator:
            reject(
                f"frontmatter line {number} is not a top-level key/value pair; "
                "flat scalar values are required"
            )
        if not FLAT_FRONTMATTER_KEY_RE.fullmatch(key):
            reject(f"frontmatter line {number} has an invalid key")
        if key in declared_at:
            reject(
                f"frontmatter key {key!r} is duplicated at line {number} (first "
                f"declared at line {declared_at[key]}); one flat scalar per key "
                "is required"
            )
        declared_at[key] = number
        fields[key] = _unquote(value)
        empty_key = "" if value.strip() else key
        empty_line = 0 if value.strip() else number
    if not closing:
        reject("frontmatter is unclosed; an exact --- delimiter is required")
    return fields, closing


def _parse_response_envelope(data: bytes) -> tuple[dict[str, str], str]:
    """Parse a worker response envelope leniently into (fields, summary).

    The envelope is worker-authored metadata; the valuable, separately-gated
    part is the committed artifact and the integrated code residue. Only
    structurally-malformed frontmatter (not UTF-8, missing/unclosed fence,
    non-conforming or duplicate keys, a nested mapping) and a genuinely-empty
    summary body are hard failures here. Field-*set* deviations -- a missing
    required field or an unexpected extra -- are NOT rejected;
    ``prepare_worktree_outputs`` normalizes them against the trusted launch
    authority rather than stranding a finished run. See
    ``_state/consults/envelope-prevalidation-fix.md``.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DispatchContextError("response envelope is not UTF-8") from exc
    records = _frontmatter_records(text)
    fields, closing = _parse_flat_frontmatter(records, subject="response envelope")
    summary = "\n".join(records[closing:]).strip()
    if not summary:
        raise DispatchContextError("response envelope summary is empty")
    return fields, summary


def _is_board_blocked_stub(data: bytes, task_id: str) -> bool:
    """Match only the exact controller-authored blocked-artifact format."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return (
        re.fullmatch(
            (
                r"blocked\n\n"
                rf"# Board dispatch blocked — {re.escape(task_id)}\n\n"
                r"Controller reason: [^\r\n]{1,2000}\n"
            ),
            text,
        )
        is not None
    )


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
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
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
                    rename_noreplace(
                        Path(temporary_name).name,
                        destination.name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                except FileExistsError as exc:
                    # The synced staging file is the losing writer's durable
                    # record. Sync the directory before surfacing the conflict;
                    # never unlink evidence from a failed publication race.
                    os.fsync(directory_fd)
                    raise DispatchContextError(
                        f"{label} destination appeared concurrently"
                    ) from exc
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
    raw_evidence_outputs = authority.get("evidence_outputs", [])
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
        or not isinstance(write_paths, list)
        or any(not isinstance(item, str) for item in write_paths)
        or not any(_contains(item, result_relative) for item in write_paths)
        or not isinstance(raw_evidence_outputs, list)
        or len(raw_evidence_outputs) > MAXIMUM_EVIDENCE_OUTPUTS
    ):
        raise DispatchContextError(
            "bridge authority identity or write scope is invalid"
        )
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
    prepared_evidence: list[PreparedEvidenceOutput] = []
    evidence_paths: set[str] = set()
    total_evidence_bytes = 0
    for index, raw_output in enumerate(raw_evidence_outputs):
        if not isinstance(raw_output, Mapping) or set(raw_output) != {
            "path",
            "role",
            "declared_by",
        }:
            raise DispatchContextError(
                f"evidence_outputs[{index}] has the wrong schema"
            )
        relative = _safe_relative(
            str(raw_output["path"]), field=f"evidence_outputs[{index}].path"
        )
        role = str(raw_output["role"])
        declared_by = str(raw_output["declared_by"])
        if (
            relative in evidence_paths
            or relative in {result_relative, outbox_relative}
            or not IDENTIFIER_RE.fullmatch(role)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", declared_by)
            or not any(_contains(scope, relative) for scope in write_paths)
        ):
            raise DispatchContextError(
                f"evidence_outputs[{index}] is duplicate, malformed, or out of scope"
            )
        data = _read_contained_regular(
            Path(worktree_root),
            relative,
            label=f"evidence output {relative}",
            maximum_bytes=8 * 1024 * 1024,
        )
        total_evidence_bytes += len(data)
        if total_evidence_bytes > 32 * 1024 * 1024:
            raise DispatchContextError("evidence outputs exceed aggregate size bound")
        evidence_paths.add(relative)
        prepared_evidence.append(
            PreparedEvidenceOutput(
                relative_path=relative,
                role=role,
                declared_by=declared_by,
                data=data,
                content_sha256=_sha256_bytes(data),
            )
        )
    attempt_id = str(authority.get("attempt_id", ""))
    generation = authority.get("generation", 0)
    run_id = str(authority.get("run_id", ""))
    mode = str(authority.get("mode_profile", ""))
    if prepared_evidence and (
        not ATTEMPT_RE.fullmatch(attempt_id)
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation <= 0
        or not run_id
        or run_id != run_id.strip()
        or any(character in run_id for character in ("\x00", "\n", "\r"))
    ):
        raise DispatchContextError(
            "evidence promotion producer provenance is invalid"
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
    for output in prepared_evidence:
        _validate_destination(
            Path(repo_root),
            output.relative_path,
            output.data,
            label=f"evidence output {output.relative_path}",
        )
    return PreparedWorktreeOutputs(
        task_id=task_id,
        result_relative=result_relative,
        outbox_relative=outbox_relative,
        result_bytes=result_bytes,
        envelope_bytes=normalized_bytes,
        status=canonical_status,
        mode=mode,
        attempt_id=attempt_id,
        generation=int(generation) if isinstance(generation, int) else 0,
        run_id=run_id,
        evidence_outputs=tuple(prepared_evidence),
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


def _project_mode_exit_manifest(
    prepared: PreparedWorktreeOutputs,
) -> PreparedEvidenceOutput | None:
    """Return the authenticated Project-close manifest declaration, if any."""

    if prepared.mode != "project" or not prepared.run_id:
        return None
    expected = f"_state/runs/{prepared.run_id}/manifest.yaml"
    return next(
        (
            output
            for output in prepared.evidence_outputs
            if output.relative_path == expected
        ),
        None,
    )


def _verifier_failure_detail(
    completed: subprocess.CompletedProcess[str],
    *,
    record_path: Path,
) -> str:
    verdict = "missing"
    if record_path.is_file() and not record_path.is_symlink():
        try:
            verdict = str(read_yaml_frontmatter(record_path).get("verdict") or "missing")
        except (OSError, VerificationContractError):
            verdict = "unreadable"
    combined = " ".join(
        ((completed.stdout or "") + "\n" + (completed.stderr or "")).split()
    )[-600:]
    return (
        f"exit={completed.returncode} verdict={verdict} "
        f"record={record_path}{' output=' + combined if combined else ''}"
    )


def _invoke_project_mode_exit_verifier(
    repo_root: Path,
    prepared: PreparedWorktreeOutputs,
) -> dict[str, object] | None:
    """Run the canonical full verifier before publishing a close envelope.

    The exact manifest evidence path is the activation signal. It is part of
    the authenticated launch authority, so neither the worker nor this bridge
    infers that an ordinary phase task is a mode close.
    """

    if _project_mode_exit_manifest(prepared) is None:
        return None
    root = Path(repo_root).resolve(strict=True)
    code_root = Path(__file__).resolve().parents[2]
    wrapper = code_root / "bin" / "vibecoding-check.sh"
    if not wrapper.is_file() or wrapper.is_symlink():
        raise ModeExitVerificationError(
            f"mode-exit verifier wrapper is unavailable: {wrapper}"
        )
    record_relative = _safe_relative(
        f"_state/vibecoding-check/{prepared.run_id}.md",
        field="mode-exit verifier record",
    )
    record_path = root / record_relative
    command = (
        "/bin/bash",
        str(wrapper),
        "--run-id",
        prepared.run_id,
        "--quiet",
    )
    environment = dict(os.environ)
    environment["VAULT_ROOT"] = str(root)
    environment["UV_CACHE_DIR"] = environment.get("UV_CACHE_DIR") or "/tmp/uv-cache"
    # Dependency resolution must use the prewarmed cache or fail closed. It may
    # not turn a settlement gate into an unbounded network operation.
    environment["UV_OFFLINE"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            env=environment,
            capture_output=True,
            text=True,
            timeout=660,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ModeExitVerificationError(
            f"mode-exit verifier failed to execute: {exc}"
        ) from exc

    accepted = {
        0: ("PASS", "Verdict tier: 0 (PASS)"),
        1: ("PASS-AFTER-AUTOFIX", "Verdict tier: 1 (AUTOFIX)"),
    }
    expected = accepted.get(completed.returncode)
    combined_output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    if expected is None:
        raise ModeExitVerificationError(
            "mode-exit verifier blocked settlement: "
            + _verifier_failure_detail(completed, record_path=record_path)
        )
    expected_verdict, expected_handshake = expected
    try:
        report = read_yaml_frontmatter(record_path)
    except (OSError, VerificationContractError) as exc:
        raise ModeExitVerificationError(
            "mode-exit verifier returned a success code without a readable report: "
            f"{record_path}: {exc}"
        ) from exc
    state_handshake = f"State: {record_path}"
    if (
        report.get("run_id") != prepared.run_id
        or report.get("mode") != prepared.mode
        or report.get("verdict") != expected_verdict
        or expected_handshake not in combined_output
        or state_handshake not in combined_output
    ):
        raise ModeExitVerificationError(
            "mode-exit verifier success handshake/report mismatch: "
            + _verifier_failure_detail(completed, record_path=record_path)
        )
    return {
        "schema": "mode-exit-verification/v1",
        "command": list(command),
        "returncode": completed.returncode,
        "verdict": expected_verdict,
        "record_path": record_relative,
    }


def publish_prepared_worktree_outputs(
    repo_root: Path,
    prepared: PreparedWorktreeOutputs,
) -> dict[str, object]:
    """Publish captured bytes, gating a declared Project close before commit.

    Ordinary packets are unchanged. A Project close opts in through the
    already-authenticated evidence-output rail by declaring the exact
    ``_state/runs/<run-id>/manifest.yaml`` file. Evidence is published first so
    the canonical checker can resolve the manifest and every newly-produced
    file it references. The return artifact and watcher-visible envelope remain
    withheld until the full checker writes a matching PASS report.
    """

    promotions: list[dict[str, object]] = []
    for output in prepared.evidence_outputs:
        destination, idempotent = _atomic_publish(
            Path(repo_root),
            output.relative_path,
            output.data,
            label=f"evidence output {output.relative_path}",
        )
        promotions.append(
            {
                "schema": "artifact-promotion/v1",
                "role": output.role,
                "declared_by": output.declared_by,
                "source_path": output.relative_path,
                "destination_path": destination.relative_to(
                    Path(repo_root).resolve(strict=True)
                ).as_posix(),
                "content_sha256": output.content_sha256,
                "size_bytes": len(output.data),
                "idempotent": idempotent,
                "producer": {
                    "task_id": prepared.task_id,
                    "attempt_id": prepared.attempt_id,
                    "generation": prepared.generation,
                    "run_id": prepared.run_id,
                },
            }
        )
    mode_exit = _invoke_project_mode_exit_verifier(Path(repo_root), prepared)
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
        "artifact_promotions": promotions,
        "mode_exit_verification": mode_exit,
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
    failure_class: str | None = None,
    attempt_id: str | None = None,
    generation: int | None = None,
) -> dict[str, object]:
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
        or compatibility_namespace not in MAILBOX_NAMESPACES
        or not isinstance(reason, str)
        or not reason.strip()
        or "\x00" in reason
        or (
            failure_class is not None
            and failure_class not in CLI_TRANSPORT_FAILURE_CLASSES
        )
        or ((attempt_id is None) != (generation is None))
        or (
            attempt_id is not None
            and (
                not ATTEMPT_RE.fullmatch(attempt_id)
                or isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation < 1
            )
        )
    ):
        raise DispatchContextError("blocked completion identity is invalid")
    artifact_relative = _safe_relative(return_artifact, field="return_artifact")
    reason_line = " ".join(reason.strip().split())[:2000]
    artifact_bytes = (
        "blocked\n\n"
        f"# Board dispatch blocked — {task_id}\n\n"
        f"Controller reason: {reason_line}\n"
    ).encode("utf-8")
    outbox_relative = (
        f"departments/{compatibility_namespace}/outbox/{task_id}-response.md"
    )
    echo = (
        {
            "delivery_attempt_id": attempt_id,
            "delivery_generation": str(generation),
        }
        if attempt_id is not None
        else {}
    )
    envelope_bytes = _render_response_envelope(
        task_id=task_id,
        lane=lane,
        result_relative=artifact_relative,
        status="blocked",
        summary=f"Board dispatch was blocked by the controller: {reason_line}",
        reconciliation_echo=echo,
        failure_class=failure_class,
    )
    if not artifact_relative or artifact_relative == outbox_relative:
        # `not artifact_relative` is the read-only verdict role (write_scope: []
        # and no return_artifact): there is no artifact to publish, so the
        # envelope alone IS the result. Without this the blocked path tried to
        # publish to '' and died on the unsafe-path guard, which made a blocked
        # verdict task unsettleable.
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


def blocked_context_fence(
    repo_root: Path, context_file: Path, task_id: str
) -> tuple[str, int]:
    """Read the blocked envelope fence from the trusted launch context."""
    root = Path(repo_root).resolve(strict=True)
    context_path = Path(context_file)
    if not context_path.is_absolute():
        context_path = root / context_path
    if context_path.is_symlink() or not context_path.is_file():
        raise DispatchContextError("blocked context is missing or non-regular")
    context_path = context_path.resolve(strict=True)
    try:
        relative = context_path.relative_to(root)
    except ValueError as exc:
        raise DispatchContextError("blocked context escapes repository") from exc
    if relative.parts[:2] != ("_state", "board-dispatch"):
        raise DispatchContextError("blocked context is outside board dispatch state")
    try:
        context = json.loads(
            _read_contained_regular(
                root,
                relative.as_posix(),
                label="blocked context",
                maximum_bytes=512 * 1024,
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchContextError("blocked context is invalid") from exc
    authority = context.get("authority") if isinstance(context, dict) else None
    attempt_id = authority.get("attempt_id") if isinstance(authority, dict) else None
    generation = authority.get("generation") if isinstance(authority, dict) else None
    if (
        not isinstance(context, dict)
        or context.get("schema") != CONTEXT_SCHEMA
        or not isinstance(authority, dict)
        or authority.get("schema") != AUTHORITY_SCHEMA
        or authority.get("task_id") != task_id
        or not isinstance(attempt_id, str)
        or not ATTEMPT_RE.fullmatch(attempt_id)
        or isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise DispatchContextError("blocked context delivery identity is invalid")
    return attempt_id, generation


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
    # Preflight for --dry-run. build_context() is pure -- it writes nothing and
    # returns a dict -- so the whole validation can be run against a real packet
    # without registering, archiving or launching anything.
    check = subparsers.add_parser("check")
    check.add_argument("--repo-root", type=Path, required=True)
    check.add_argument("--task-file", type=Path, required=True)
    blocked = subparsers.add_parser("blocked")
    blocked.add_argument("--repo-root", type=Path, required=True)
    blocked.add_argument("--task-id", required=True)
    blocked.add_argument("--lane", required=True)
    blocked.add_argument("--return-artifact", required=True)
    blocked.add_argument("--compatibility-namespace", required=True)
    blocked.add_argument("--reason", required=True)
    blocked.add_argument(
        "--failure-class", choices=sorted(CLI_TRANSPORT_FAILURE_CLASSES)
    )
    blocked.add_argument("--attempt-id")
    blocked.add_argument("--generation", type=int)
    blocked.add_argument("--context-file", type=Path)
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
    inventory = subparsers.add_parser("lane-inventory")
    inventory.add_argument("--repo-root", type=Path, required=True)
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
        elif command == "check":
            # Same validation the real launch performs, with a placeholder
            # identity: the attempt id never reaches disk because nothing is
            # written. Any DispatchContextError propagates to the handler below
            # and exits non-zero, which is exactly what --dry-run needs.
            context = build_context(
                args.repo_root,
                args.task_file,
                attempt_id="d-" + "0" * 32,
                generation=1,
            )
            # build_context() has already enforced the trusted-launch bound and
            # every other launch invariant by this point; reaching here means the
            # packet would launch. The assembled prompt is not returned, so report
            # the packet size only rather than a headroom figure we cannot measure.
            packet = len(Path(args.task_file).read_bytes())
            print(f"preflight OK: packet {packet} bytes would launch")
        elif command == "blocked":
            attempt_id, generation = args.attempt_id, args.generation
            if args.context_file is not None:
                if attempt_id is not None or generation is not None:
                    raise DispatchContextError(
                        "blocked identity must come from either flags or context"
                    )
                attempt_id, generation = blocked_context_fence(
                    args.repo_root, args.context_file, args.task_id
                )
            receipt = publish_blocked_completion(
                repo_root=args.repo_root,
                task_id=args.task_id,
                lane=args.lane,
                return_artifact=args.return_artifact,
                compatibility_namespace=args.compatibility_namespace,
                reason=args.reason,
                failure_class=args.failure_class,
                attempt_id=attempt_id,
                generation=generation,
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
            print(
                json.dumps(
                    {
                        "run_now": list(result.run_now),
                        "must_wait": list(result.must_wait),
                        "reasons": result.reasons,
                        "reservation_snapshot_sha256": result.reservation_snapshot_sha256,
                    },
                    sort_keys=True,
                )
            )
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
        elif command == "lane-inventory":
            for row in lane_runtime_inventory(args.repo_root):
                selections = ";".join(
                    f"{item['profile_id']}:{item['registry_model']}->{item['effective_model']}"
                    for item in row["selections"]
                )
                print(
                    "\t".join(
                        (
                            row["lane"],
                            str(row["installed"]).lower(),
                            row["literal_executable"],
                            row["resolved_executable"],
                            row["version"] or "unavailable",
                            row["auth_class"],
                            selections,
                        )
                    )
                )
        else:  # pragma: no cover - argparse owns this
            parser.error("a command is required")
    except DispatchContextError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
