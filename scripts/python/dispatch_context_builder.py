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
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, NoReturn, Sequence

try:
    from durable_publish import rename_noreplace
    from held_action_gate import HELD_CATEGORIES
    from lane_capability_enforcement import adapter_path_for
    from launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256
    from repo_root import resolve_vault_root
    from seatbelt_profile import DEFAULT_LANE_PATH, LANE_CLI_PATHS
    import specialist_capability_source as scs
    from verification_contract import (
        ContractError as VerificationContractError,
        MODELESS_MODE,
        read_yaml_frontmatter,
        validate_verification_contract as validate_contract_schema,
    )
except ImportError:  # pragma: no cover - package-context fallback
    from .durable_publish import rename_noreplace  # type: ignore[no-redef]
    from .held_action_gate import HELD_CATEGORIES  # type: ignore[no-redef]
    from .lane_capability_enforcement import adapter_path_for  # type: ignore[no-redef]
    from .launch_hygiene import SETTLED_T1P1_BUNDLE_SHA256  # type: ignore[no-redef]
    from .repo_root import resolve_vault_root  # type: ignore[no-redef]
    from .seatbelt_profile import DEFAULT_LANE_PATH, LANE_CLI_PATHS  # type: ignore[no-redef]
    from . import specialist_capability_source as scs  # type: ignore[no-redef]
    from .verification_contract import (  # type: ignore[no-redef]
        ContractError as VerificationContractError,
        MODELESS_MODE,
        read_yaml_frontmatter,
        validate_verification_contract as validate_contract_schema,
    )


CONTEXT_SCHEMA = "go-live-trusted-context/v1"
AUTHORITY_SCHEMA = "go-live-authority/v1"
RESIDUE_HEALTH_VERIFIER = (
    Path(__file__).resolve().parents[2] / "bin" / "validate-specialists.sh"
)
RESIDUE_HEALTH_TIMEOUT_SECONDS = 180
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
# packet measured 32,688-32,730 bytes on CI's 69-character checkout path
# and ~29 bytes-per-embedded-path less on the maintainer's 41-character one.
# That put a valid dispatch 38 bytes under the old ceiling locally and OVER it
# in CI -- so whether a real bounty dispatch was permitted depended on where the
# repository happened to live, and private CI had been red for weeks because of
# it. A ceiling a minimal valid packet cannot clear is not bounding a risk.
#
# 40960 keeps a real bound (the prompt is still ~10k tokens) while leaving
# ~8 KiB of headroom, which is hundreds of characters of additional path depth
# per embedded reference. CI remains the stricter environment because its paths
# are longer.
TRUSTED_LAUNCH_PROMPT_LIMIT = 40960
IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACES = frozenset(
    {"coding", "security", "content", "sysmgmt", "research", "shared"}
)
# One task-id namespace, one mailbox. Source namespaces still locate specialist
# briefs, but they never participate in delivery-path construction. Keeping the
# canonical mailbox under ``departments/coding`` lets the existing ``all``
# watcher drain both this live path and historical per-namespace mailboxes
# during migration without a second compatibility write.
CANONICAL_MAILBOX_ROOT = PurePosixPath("departments/coding")
MAILBOX_TASK_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CLI_TRANSPORT_FAILURE_CLASSES = frozenset({"cli_missing", "cli_nonzero", "cli_timeout"})
# One fact with four homes: `clearance._APERTURES` owns the vocabulary,
# `broker.CONTEXT_APERTURES` and the `case` arm in `bin/send-task.sh` are the
# other copies, and `scripts/python/tests/test_dispatch_memory_default.py`
# pins all four together. An aperture added here but not there is a dispatch
# the broker rejects outright.
MEMORY_APERTURES = frozenset(
    {"rich", "focused", "default", "cold", "pool_blind", "none"}
)
# The apertures whose policy actually returns notes, mirroring the `recall`
# and `get_note` columns of `shared/registries/memory-apertures.tsv`. This
# used to be an inline literal inside `assemble_trusted_launch_prompt`; the
# blind floor needs the same fact, and a second literal would be a copy that
# ages independently (CLAUDE.md rule 10).
# `scripts/python/tests/test_blind_floor.py` pins it against the registry.
READ_PERMITTING_APERTURES = frozenset({"rich", "focused", "default"})
# One bound for the creation-time selector and the promotion-time validator, so
# a packet can never declare evidence that promotion would later refuse to read.
MAXIMUM_EVIDENCE_OUTPUTS = 16
MODEL_TO_LANE = {
    "gpt-codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "grok": "grok",
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
    # The routing identifier remains gemini, while Antigravity's agy CLI uses
    # the operator's OAuth session with provider API keys removed.
    "gemini": "google-oauth",
    "grok": "xai-api-key",
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
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
    ),
    "grok": (
        "--permission-mode",
        "bypassPermissions",
        "--no-subagents",
        "--disable-web-search",
    ),
    "kimi": (
        "--yolo",
        "--thinking",
    ),
}
AGY_EXTERNAL_MCP_MAX_CALLS_FIELD = "external_mcp_max_calls"
AGY_EXTERNAL_MCP_MAX_CALLS_MAX = 10_000


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


def agy_external_mcp_max_calls(fields: Mapping[str, str]) -> int:
    """Return agy's authenticated numeric ceiling for metered MCP calls.

    Antigravity has no per-invocation MCP selector or native spend flag. The
    board can still carry a typed call ceiling in its sealed authority and
    worker projection. Absence therefore fails safe at zero; a packet may opt
    in to a bounded positive integer explicitly.
    """

    raw = _unquote(fields.get(AGY_EXTERNAL_MCP_MAX_CALLS_FIELD, "0"))
    if re.fullmatch(r"(?:0|[1-9][0-9]{0,4})", raw) is None:
        raise DispatchContextError(
            f"{AGY_EXTERNAL_MCP_MAX_CALLS_FIELD} must be a non-negative integer"
        )
    value = int(raw)
    if value > AGY_EXTERNAL_MCP_MAX_CALLS_MAX:
        raise DispatchContextError(
            f"{AGY_EXTERNAL_MCP_MAX_CALLS_FIELD} exceeds the board ceiling"
        )
    return value


class DispatchContextError(ValueError):
    """A packet or bridge operation cannot be represented safely."""


class ModeExitVerificationError(DispatchContextError):
    """A declared mode-close manifest did not earn envelope publication."""


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
        # The blocked-completion CLI still uses an empty return_artifact to mean
        # "publish only the controller envelope". Packet admission is stricter:
        # require_packet_fields() rejects an empty packet value with both the
        # public and internal field names before authority construction.
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
        for name in ("source_namespace", "run_id", "mode", "return_artifact")
        if not _unquote(fields.get(name, "")).strip()
    ]
    if missing:
        message = (
            "task packet is missing required frontmatter field(s): "
            + ", ".join(missing)
        )
        if "return_artifact" in missing:
            message += "; return_artifact supplies the internal expected_result_path"
        raise DispatchContextError(message)
    namespace = _unquote(fields.get("source_namespace", ""))
    if namespace not in NAMESPACES:
        raise DispatchContextError(
            f"frontmatter field source_namespace is invalid: {namespace!r} "
            f"(expected one of {', '.join(sorted(NAMESPACES))})"
        )


def _packet_review_is_owed(fields: Mapping[str, str]) -> bool:
    """Whether the packet's trigger policy owes a different-family review.

    Mirrors the reconciler's owed-decision (`cross_family_review_pending`): a
    review is owed when `mandatory_review` is true OR `review_triggers` is a
    non-empty list. A malformed `review_triggers` value is treated as owed
    (fail-closed), exactly as the reconciler holds a malformed review contract
    rather than downgrading it to no review.
    """

    mandatory = _unquote(fields.get("mandatory_review", "")).strip().lower() == "true"
    raw_triggers = fields.get("review_triggers")
    if raw_triggers is None or not str(raw_triggers).strip():
        return mandatory
    try:
        triggers = parse_scope(str(raw_triggers), field="review_triggers")
    except DispatchContextError:
        return True
    return mandatory or bool(triggers)


def _check_deliverable_review_agreement(
    fields: Mapping[str, str], contract: Mapping[str, Any]
) -> None:
    """Refuse a contract that owes LESS review than the packet's triggers demand.

    The pinned contract's `deliverable_review_policy.required` is the worker-facing
    statement of whether a deliverable review is owed. If the packet's triggers
    fire (`mandatory_review`/`review_triggers`) but the contract says no review is
    required, the worker is told the opposite of what the reconciler enforces and
    the different-family review the triggers demand could be skipped. That is the
    one direction that must never be permitted -- it is the hard boundary of the
    change that made `required` variable in the first place.

    The reverse -- a contract requiring a review the triggers do not -- is the
    historical over-claim this change exists to retire. It is TOLERATED here, not
    rejected: an un-wired producer still emits `required: true` for every packet,
    so hard-rejecting the over-claim would break every routine dispatch before the
    producer is updated. The over-claim is retired at the producer, not policed
    here; policing it would trade one dead board for another.
    """

    policy = contract.get("deliverable_review_policy")
    if not isinstance(policy, Mapping):
        return
    if policy.get("required") is False and _packet_review_is_owed(fields):
        raise DispatchContextError(
            "verification_contract deliverable_review_policy.required is false but "
            "the packet's mandatory_review/review_triggers demand a different-family "
            "review"
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
    invalid: list[str] = []
    if (
        not isinstance(required_phases, list)
        or not required_phases
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
    _check_deliverable_review_agreement(fields, contract)
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
        "gemini": "subscription",
        "grok": "xai-api-key",
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


def canonical_mailbox_relative(
    state: str, task_id: str, *, response: bool = False
) -> str:
    """Return the sole live mailbox path for one task identity."""

    if state not in {"inbox", "active", "outbox", "archive"}:
        raise DispatchContextError(f"mailbox state is invalid: {state!r}")
    if not MAILBOX_TASK_RE.fullmatch(task_id):
        raise DispatchContextError("mailbox task id is invalid")
    filename = f"{task_id}-response.md" if response else f"{task_id}.md"
    return (CANONICAL_MAILBOX_ROOT / state / filename).as_posix()


def _canonicalize_mailbox_response(value: str, task_id: str) -> str:
    """Map a legacy per-namespace response declaration onto the one outbox."""

    if re.fullmatch(r"departments/[^/]+/outbox/?", value):
        return (CANONICAL_MAILBOX_ROOT / "outbox").as_posix()
    match = re.fullmatch(
        r"departments/[^/]+/outbox/([^/]+)-response\.md", value
    )
    if match and match.group(1) == task_id:
        return canonical_mailbox_relative("outbox", task_id, response=True)
    return value


def _validate_mailbox_packet(repo_root: Path, task_file: Path, task_id: str) -> None:
    try:
        relative = task_file.resolve(strict=True).relative_to(
            repo_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise DispatchContextError("task packet must be inside the repository") from exc
    expected = canonical_mailbox_relative("inbox", task_id)
    if relative.as_posix() != expected:
        raise DispatchContextError(
            f"task packet must be the exact unified mailbox path: {expected}"
        )


def _contains(scope: str, target: str) -> bool:
    scope_path = PurePosixPath(scope)
    target_path = PurePosixPath(target)
    return scope_path == target_path or scope_path in target_path.parents


def packet_evidence_outputs(
    fields: Mapping[str, str],
    write_scope: Sequence[str],
    *,
    task_id: str = "",
) -> tuple[dict[str, str], ...]:
    """Return every evidence path the packet declares at creation time.

    One exact declaration is honored, and nothing else -- this never scans a
    worktree, infers evidence, or guesses at what a worker produced.
    ``evidence_outputs`` is a YAML inline list of PoCs, harnesses, logs, and
    other unique outputs.

    Each declared path must be worktree-relative, inside ``write_scope``, and
    distinct. A declared file that the worker did not produce blocks promotion
    upstream rather than being skipped: declaring evidence is a commitment.
    """

    outputs: list[dict[str, str]] = []
    seen: set[str] = set()

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
        for parsed in parse_scope(declared, field="evidence_outputs"):
            relative = (
                _canonicalize_mailbox_response(parsed, task_id)
                if task_id
                else parsed
            )
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


def undeclared_gitignored_write_scope(
    repo_root: Path,
    write_scope: Sequence[str],
    *,
    return_artifact: str,
    evidence_outputs: Sequence[Mapping[str, str]],
) -> tuple[str, ...]:
    """Return ignored write scopes that have no authenticated promotion path.

    The return artifact and exact ``evidence_outputs`` are promoted by the
    controller. Every other write-scope entry is merely permission to edit; if
    Git also ignores it, neither ordinary integration nor Git status can prove
    that the worker produced anything there. A real dispatch must reject that
    silent-loss shape before provisioning a disposable worktree.

    Synthetic unit repositories without Git metadata retain the historical
    pure-context behavior. Production dispatch roots are Git worktrees (their
    ``.git`` may be a directory or a file), and any failure to classify a path
    there fails closed.
    """

    root = Path(repo_root)
    if not (root / ".git").exists():
        return ()
    declared = {
        str(output.get("path") or "")
        for output in evidence_outputs
        if isinstance(output, Mapping)
    }
    extras = tuple(
        path
        for path in write_scope
        if path and path != return_artifact and path not in declared
    )
    ignored: list[str] = []
    for path in extras:
        completed = subprocess.run(
            ("git", "check-ignore", "-q", "--", path),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            ignored.append(path)
        elif completed.returncode != 1:
            detail = " ".join((completed.stderr or "").split())[:400]
            raise DispatchContextError(
                "cannot classify undeclared write_scope against Git ignore rules"
                + (f": {detail}" if detail else "")
            )
    return tuple(ignored)


def resolve_packet_mode(fields: Mapping[str, str]) -> str:
    """Resolve a packet's mode. THIS is the home of the absent-mode rule.

    An absent `mode:` means a deliberate modeless engagement; an explicitly
    EMPTY `mode:` is a malformed row and keeps failing downstream. Only true
    absence defaults.

    The rule used to be restated at three layers -- `bin/send-task.sh`,
    `dispatch_preflight._validate_contract`, and nowhere here -- and the one
    layer that GATED (this module, via `require_packet_fields`) was the one
    that did not have it. A packet omitting `mode:` therefore passed the shell
    dry-run and the preflight and then died at launch, furthest from its
    author. The rule now lives here, at the gate; the other layers are mirrors,
    and `scripts/python/tests/test_dryrun_parity.py` pins them to this function
    so a mirror cannot drift away from it again.
    """

    return fields["mode"] if "mode" in fields else MODELESS_MODE


def resolve_memory_aperture(fields: Mapping[str, str]) -> str:
    """Resolve a packet's memory aperture.

    Changed 2026-08-17 from `cold` to `default` (memory-loop spec §4).
    The old fail-closed default meant 2,665 of 2,669 dispatches ran with
    memory switched off, which made recursive learning structurally
    impossible.

    Blindness is NOT protected by this default any more. It is protected
    by `enforce_blind_floor` below, which `build_context` applies to this
    function's result: a role whose specialist brief declares
    `blind_discovery: true`, dispatched at a target that has a `_blind/`
    dossier path, is forced to `cold` whatever the packet asked for. A
    packet that must not read prior work for some *other* reason still says
    `cold`, `pool_blind`, or `none` itself.
    """

    return _unquote(fields.get("memory_aperture", "")) or "default"


# Which roles must rediscover blind is a judgment about the work, not a
# property of this module, and CLAUDE.md opens by declaring this system
# markdown-first. The fact therefore lives in the specialist brief that
# defines the role -- `blind_discovery: true` in its frontmatter -- and is
# read from there on each dispatch. Marking a new brief floors that role with
# no change here; that is the whole point.
#
# Roles whose job IS rediscovery are marked. Later-stage roles on the SAME
# target legitimately need prior art -- a skeptic, impact-validator, or
# technical-writer cannot do its job blind -- so their briefs stay unmarked by
# design, and Chrono opens their aperture with a reason recorded in the packet
# (memory-loop spec §5).
#
# The read is deliberately UNCACHED, so there is nothing to invalidate. The
# floor runs once per dispatch, immediately before the controller spawns a
# lane CLI, and only after the cheap target/vault/aperture tests below have
# already passed; the 68 briefs total ~330 KB. A cache would buy microseconds
# in exchange for a window in which an operator has marked a brief blind and a
# running controller still floors it open, which is the exact failure this
# floor exists to prevent.
BLIND_DISCOVERY_KEY = "blind_discovery"
_SPECIALIST_BRIEF_GLOBS = (
    "shared/specialists/*.md",
    "departments/*/specialists/*.md",
)


def _brief_blind_declaration(path: Path) -> bool | None:
    """Return a brief's `blind_discovery` value, or None when it cannot say.

    None is not False. It means the frontmatter did not answer the question --
    unreadable, absent, unterminated, duplicated, or holding something that is
    not a boolean -- and every caller turns that into "blind", never into
    "permitted". A brief that parses cleanly and simply omits the key HAS
    answered: no, this is not a rediscovery role. That distinction is why this
    is a tri-state rather than a bool.

    The frontmatter reader is the one this module already imports. A second
    parser here would be a second answer to "what does this brief say", and
    the two would age apart (CLAUDE.md rule 10).
    """

    try:
        frontmatter = read_yaml_frontmatter(path)
    except (VerificationContractError, OSError, ValueError):
        return None
    if BLIND_DISCOVERY_KEY not in frontmatter:
        return False
    declared = frontmatter[BLIND_DISCOVERY_KEY]
    return declared if isinstance(declared, bool) else None


def blind_discovery_declarations(
    repo_root: Path | str | None = None,
) -> dict[str, bool]:
    """Map each specialist role to the blindness its own brief declares.

    A role whose brief is missing, unreadable, or unparseable is ABSENT from
    the result rather than present as False, so that the fail-closed default
    in `role_requires_blind_discovery` applies to it. An unreadable brief
    poisons its role even if a same-named brief elsewhere parsed.

    `repo_root` defaults to `resolve_vault_root()` rather than to
    `build_context`'s argument on purpose: the floor's other input, the vault
    path, is likewise taken from the environment at the call site. Both are
    properties of the installed system, not of the packet, and `send-task.sh`
    passes the same exported `VAULT_ROOT` as `--repo-root`, so the two agree
    in production.
    """

    try:
        root = Path(repo_root) if repo_root is not None else resolve_vault_root()
    except (OSError, ValueError):
        return {}
    declarations: dict[str, bool] = {}
    unreadable: set[str] = set()
    for pattern in _SPECIALIST_BRIEF_GLOBS:
        try:
            paths = sorted(root.glob(pattern))
        except OSError:
            return {}
        for path in paths:
            declared = _brief_blind_declaration(path)
            if declared is None:
                unreadable.add(path.stem)
            else:
                declarations[path.stem] = declared
    for stem in unreadable:
        declarations.pop(stem, None)
    return declarations


def blind_discovery_roles(repo_root: Path | str | None = None) -> frozenset[str]:
    """The roles whose briefs declare `blind_discovery: true`.

    For introspection and validation. The dispatch path asks
    `role_requires_blind_discovery` instead, because a set cannot express the
    difference between "this brief says no" and "this brief could not be
    read", and only the second of those has to fail closed.
    """

    return frozenset(
        role
        for role, declared in blind_discovery_declarations(repo_root).items()
        if declared
    )


def role_requires_blind_discovery(
    role: str, repo_root: Path | str | None = None
) -> bool:
    """Whether `role` must run memory-blind on a target under blind work.

    Fail closed. An unknown role, or one whose brief cannot be read or parsed,
    is treated as blind. Blindness is the entire value of a rediscovery lane:
    a contaminated scout destroys the work it was dispatched to do, while a
    needlessly blinded later-stage role merely does that work with less
    context. Only one of those two mistakes is recoverable, so a missing brief
    has to mean a worker that reads nothing, never one that reads everything.
    """

    return blind_discovery_declarations(repo_root).get(role, True)


def packet_blind_target(fields: Mapping[str, str]) -> str:
    """Return the packet's `target` verbatim, or "" when it declares none.

    Returned unvalidated, deliberately. `target` is not this floor's field:
    it predates the floor and already carries a different vocabulary --
    `examplechain/example-gateway-contracts@0000aaaa...`,
    `shared/specialists/ (8 files)`, `contracts/svm-gateway @ 5a23518e...`.
    An earlier version of this function refused anything that was not a bare
    slug, and since `build_context` calls it on the single path every
    dispatch takes, that turned a naming mismatch into a dead board: the
    live convention raises on the first packet.

    Refusing is not what "never silently drop the floor" requires anyway.
    `_dossier_slug_candidates` below does the honest thing instead -- it
    reads the slugs OUT of whatever the field contains, so a blind target
    still floors when it arrives inside a live-shaped value.
    """

    return _unquote(fields.get("target", ""))


# One `is_dir()` per candidate, so a pathological free-text target cannot
# turn one dispatch into an unbounded stat sweep. Twelve is far more than
# any live `target` produces (the longest observed yields five).
MAX_BLIND_TARGET_CANDIDATES = 12
_SLUG_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9-]+")


def _dossier_slug_candidates(target: str) -> tuple[str, ...]:
    """Every dossier slug `target` could plausibly name, most specific first.

    `target` is free text in practice. A dossier slug is not, so rather than
    demand the field change vocabulary, derive: the value itself, the value
    normalized to one slug, then each slug-shaped run inside it. The floor
    fires if ANY of them has a `_blind/` directory.

    Over-inclusive on purpose. A wrong floor costs a worker its memory for
    one dispatch; a missed floor costs the rediscovery the dispatch exists
    to perform, and only one of those is recoverable -- the same asymmetry
    `role_requires_blind_discovery` fails closed on.

    Every candidate matches `IDENTIFIER_RE` by construction, so no candidate
    can contain `/` or `.` and none can escape the dossiers directory: a
    `target` of `../../etc` yields `etc`, not a traversal.
    """

    if not target:
        return ()
    seen: dict[str, None] = {}
    normalized_whole = "-".join(
        part for part in _SLUG_SEPARATOR_RE.split(target) if part
    ).strip("-").lower()
    for raw in (target, normalized_whole, *_SLUG_SEPARATOR_RE.split(target)):
        candidate = raw.strip("-").lower()
        if candidate and IDENTIFIER_RE.fullmatch(candidate):
            seen.setdefault(candidate, None)
        if len(seen) >= MAX_BLIND_TARGET_CANDIDATES:
            break
    return tuple(seen)


def enforce_blind_floor(
    aperture: str,
    target: str,
    role: str,
    vault_root: Path | str | None,
    *,
    repo_root: Path | str | None = None,
) -> str:
    """Force a read-denying aperture for discovery roles on a blind target.

    Which roles those are is read from the specialist briefs, not decided
    here; see `role_requires_blind_discovery`, which fails closed so an
    unreadable brief blinds its role rather than permitting it.

    Blind means NO memory, not "no memory about this target": recall is not
    target-scoped, and technique learned on another target is still
    contamination for rediscovery here.

    The floor is keyed on the `_blind/` directory the dossier layout already
    uses, so it cannot drift from the evidence layout the way a packet field
    would. It is applied once, where the aperture is *resolved*, so it reaches
    both the authenticated envelope and the launch prompt without becoming
    another site that encodes aperture policy.

    `target` is read for slugs, not matched as one: it is a pre-existing
    free-text field (`_dossier_slug_candidates`), so a value that names a
    blind dossier still floors even when it arrives as
    `example-chain-audit / example-chain-node @ 1111bbbb`, and a value that names
    no dossier at all leaves an ordinary dispatch alone instead of killing
    it.

    Two apertures are deliberately left alone. `pool_blind` and `none` already
    deny reads, and `none` denies strictly more than `cold` does -- it forbids
    `record` too -- so rewriting either to `cold` would *widen* a packet that
    was already blinder than the floor requires.

    An absent `vault_root` is not a bypass. With no `CHRONO_VAULT_ROOT` the
    controller projects no vault path to the worker at all, so recall has
    nothing to open and there is no prior work to be contaminated by.
    """

    # The brief read is last on purpose: the three cheap tests above settle
    # every dispatch that is not already a candidate for the floor, so the
    # common path never touches the filesystem for a roster it will not use.
    if (
        not target
        or not vault_root
        or aperture not in READ_PERMITTING_APERTURES
        or not role_requires_blind_discovery(role, repo_root)
    ):
        return aperture
    dossiers = Path(vault_root) / "Chrono" / "dossiers"
    for slug in _dossier_slug_candidates(target):
        if (dossiers / slug / "_blind").is_dir():
            return "cold"
    return aperture


def packet_memory_contract(fields: Mapping[str, str]) -> tuple[str, str | None]:
    """Validate and return the packet's trusted-launch memory aperture."""

    memory_aperture = resolve_memory_aperture(fields)
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
    return_artifact: str,
    write_scope: Sequence[str],
    *,
    outbox_relative: str = "",
) -> str:
    """State the ways a lane's work gets discarded for non-work reasons.

    Observed 2026-08-15: four lanes died on mechanics rather than the task --
    two CLI timeouts, one scope violation (`worker committed paths outside the
    integration scope`), and one `return artifact is missing, non-regular, or a
    symlink`. In each case the fix itself may have been sound and was thrown
    away. The packet cannot prevent these; the launch prompt can.

    ``outbox_relative`` closes the split-output hole measured 2026-08-26. When
    `return_artifact` and the outbox path differ, the injected packet's
    `write_scope` may name only the artifact, so item 2 can read as a prohibition
    on the one file `prepare_worktree_outputs` also requires. The envelope is not
    a scope violation --
    the supervisor passes both expected paths as `exclude_paths` to
    `commit_worker_residue` and `integrate_worktree_commits` -- so this states
    the exemption instead of leaving the lane to guess.
    """

    if not return_artifact:
        return ""
    scope = ", ".join(f"`{p}`" for p in write_scope) or "(none declared)"
    split_outputs = bool(outbox_relative) and outbox_relative != return_artifact
    ways = "four" if split_outputs else "three"
    envelope_item = (
        (
            f"3. **Your envelope is a SECOND file here: also write `{outbox_relative}`.** In this "
            "dispatch shape `return_artifact` and the response envelope are different paths, and "
            "the envelope is deliberately absent from the write scope in item 2 — writing it is "
            "**not** a scope violation, because the controller excludes it from integration "
            "entirely. A completion carrying a perfect artifact and no envelope is discarded as "
            "`blocked`, with the work already paid for.\n"
        )
        if split_outputs
        else ""
    )
    last_item = "4" if split_outputs else "3"
    return (
        f"## Delivery contract — {ways} ways good work gets discarded\n\n"
        f"1. **`{return_artifact}` must contain your real findings when you exit.** Write it as "
        "a plain file early and keep updating it as you work — not a symlink, not a directory, "
        "not left to the end. The early write is insurance against being killed mid-flight; it "
        "is not the deliverable. An artifact still holding a placeholder, an outline, or "
        "\"in progress\" text when you exit is a FAILED task, discarded exactly as a missing one "
        "is. A lane whose artifact is missing at completion is discarded whole, however good "
        "the fix was.\n"
        f"2. **Write only inside your write scope**: {scope}. Integration refuses a commit touching "
        "anything else and discards the entire attempt — it does not partially apply. If the task "
        "genuinely needs another path, stop and report it: a scope request costs one turn, a scope "
        "violation costs the lane.\n"
        f"{envelope_item}"
        f"{last_item}. **If you are running long, land what is complete and write the artifact "
        "anyway.** A truthful partial naming what remains is a useful result; being killed "
        "mid-flight with no artifact is not.\n"
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
    outbox_relative: str = "",
) -> str:
    """Assemble the exact prompt whose bytes are bounded before launch."""

    if memory_aperture == "none":
        memory_instructions = (
            "This engagement has memory aperture `none`. Do not call recall, record, "
            "get_note, lifecycle, or vault browse tools. Memory is not a task gate."
        )
    else:
        # Read permission per aperture, mirroring the `recall`/`get_note`
        # columns of shared/registries/memory-apertures.tsv. `default` joined
        # this set on 2026-08-17 with the dispatch default: the policy the
        # broker enforces lets a `default` worker recall, and a prompt that
        # told it otherwise would switch memory back off in the only place
        # that actually runs -- the same prose-vs-prompt split that cost 23
        # days of `record_usage` rows (see shared/protocol.md).
        reads_allowed = memory_aperture in READ_PERMITTING_APERTURES
        recall_instruction = (
            '- Recall prior context ONCE: `recall(query="<task-specific terms>", limit=5)`. '
            "Pass no filters; the vault enforces this engagement's aperture."
            if reads_allowed
            else f"- Do not call recall or get_note: aperture `{memory_aperture}` forbids reads."
        )
        # This line used to forbid `record_usage`. That was an emergency fix on
        # 2026-07-25 (`c3aeb5d5`) for an `outcome` enum the server did not publish,
        # which turned a failed call into a whole-task block. `6ebe6802` fixed the
        # enum two days later; the prohibition outlived its cause by 23 days and not
        # one usage row was written in that window. Recording the outcome is the
        # only signal that says whether what recall returned was worth returning,
        # so it is now expected -- and only where the aperture returned notes at
        # all, because an aperture that denies reads yields no recall_id to report.
        usage_instruction = (
            "- Then, for each recalled note that informed the work, record the outcome "
            'with `record_usage(recall_id="<the recall_id recall returned>", '
            'note_id="mem-…", outcome="used"|"not_useful"|"incorrect")`. This is '
            "expected, not optional, for notes you actually consulted -- the unhelpful "
            "ones especially, since nothing else reports them. It is still telemetry: "
            "a failure is noted in the artifact and never gates the task."
            if reads_allowed
            else "- There is no usage outcome to record: this aperture returns no notes."
        )
        memory_instructions = (
            "Durable memory is BEST-EFFORT telemetry. Call each permitted tool once -- "
            "one recall, one record, one usage outcome per note you consulted. Then stop: "
            "never search the repo for schemas, and never retry. A memory error is "
            "never a task gate: note it briefly in the artifact and continue. The server "
            "aperture overrides any generic memory-policy wording in the packet.\n"
            f"{recall_instruction}\n"
            "- Write the return artifact and completion envelope FIRST. Only afterward, "
            "record the outcome once with: "
            f'`record(note_type="learning", fields={{"title":"<one-line outcome>",'
            f'"body":"<two or three short sentences referencing {task_id}>",'
            # One `}` closes `fields=`, the other closed nothing: the rendered example
            # read `...,"attack_class":"none"}})` and taught every worker a call with an
            # unbalanced brace. Found 2026-08-17 while replacing the record_usage
            # prohibition in this same string.
            '"target":"<component or target>","attack_class":"none"})`. '
            "The server binds source_task, candidate status, sensitivity floor, and focused "
            "target; do not add or override them. Do not call set_status.\n"
            f"{usage_instruction}"
        )
    return (
        "Execute the exact task packet below as a fresh isolated specialist CLI. "
        "Do not claim or redispatch it; this launch is already bound to the registry "
        f"attempt {attempt_id}, generation {generation}. Write the declared return "
        "artifact and response envelope inside this worktree. The supervisor validates "
        "and promotes the artifact first and the envelope last.\n\n"
        f"{memory_instructions}\n\n"
        f"{gitignored_read_scope_note(read_scope, canonical_root)}"
        f"{delivery_contract_note(return_artifact, write_scope, outbox_relative=outbox_relative)}\n"
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
    staged: bool = False,
) -> dict[str, Any]:
    """Build one launch context. ``staged=True`` validates a packet that has
    not been published to the unified mailbox yet -- the `--dry-run` preflight.

    Every launch invariant below still runs against the staged bytes. The one
    substitution is the on-disk mailbox-location check, which cannot hold
    before publication: a staged packet is validated against the canonical
    inbox path it WILL occupy instead. `bin/send-task.sh` copies to exactly
    that path unconditionally, so the substituted check is the weaker half of
    the pair; a staged pass therefore does not prove the file is in the
    mailbox, and proves everything else. The `build` subcommand never sets it.
    """

    root = Path(repo_root).resolve(strict=True)
    packet_path = Path(task_file).resolve(strict=True)
    fields, _body = parse_task_packet(packet_path)
    # Absent mode -> modeless, resolved once at the gating layer. See
    # resolve_packet_mode() for why this is the rule's single home.
    fields = {**fields, "mode": resolve_packet_mode(fields)}
    task_id = _unquote(fields.get("id", ""))
    specialist = _unquote(fields.get("specialist", ""))
    namespace = _unquote(fields.get("source_namespace", ""))
    to_model = _unquote(fields.get("to_model", ""))
    run_id = _unquote(fields.get("run_id", ""))
    mode = _unquote(fields.get("mode", ""))
    raw_return_artifact = _safe_relative(
        fields.get("return_artifact", ""), field="return_artifact"
    )
    return_artifact = _canonicalize_mailbox_response(raw_return_artifact, task_id)
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
    if staged:
        packet_relative = canonical_mailbox_relative("inbox", task_id)
    else:
        _validate_mailbox_packet(root, packet_path, task_id)
        packet_relative = packet_path.relative_to(root).as_posix()
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

    raw_write_scope = parse_scope(
        fields.get("write_scope", ""), field="write_scope"
    )
    write_scope = tuple(
        _canonicalize_mailbox_response(path, task_id) for path in raw_write_scope
    )
    if len(set(write_scope)) != len(write_scope):
        raise DispatchContextError(
            "write_scope aliases the same unified mailbox path more than once"
        )
    evidence_outputs = packet_evidence_outputs(
        fields, write_scope, task_id=task_id
    )
    raw_evidence_paths: list[str] = []
    if raw_declared_evidence := fields.get("evidence_outputs", ""):
        raw_evidence_paths.extend(
            parse_scope(raw_declared_evidence, field="evidence_outputs")
        )
    ignored_undeclared = undeclared_gitignored_write_scope(
        root,
        write_scope,
        return_artifact=return_artifact,
        evidence_outputs=evidence_outputs,
    )
    if ignored_undeclared:
        raise DispatchContextError(
            "undeclared git-ignored write_scope path has no promotion route: "
            + ", ".join(ignored_undeclared)
            + "; declare each exact output in evidence_outputs or remove it from write_scope"
        )
    # An EMPTY write_scope means "this task writes only its return artifact".
    #
    # The return artifact is the return CONTRACT, not a granted permission: a
    # task that cannot write its response cannot report at all. A read-only
    # packet therefore declares no writable paths AND still names an artifact,
    # and `any()` over an empty scope is always False, so this check refused
    # exactly that shape. Measured 2026-08-31: 188 real packets in the archive
    # declare `write_scope: []` with a real return_artifact, 79 of them
    # review/audit/read-only roles.
    #
    # `scripts/send-task.sh:221` has been hiding this by injecting the response
    # path as the FIRST scope entry on every generated packet, so only PREPARED
    # packets — the ones reviewers hand-write — ever hit the refusal. That is
    # one rule with two behaviours depending on which door you came through.
    #
    # A DECLARED scope still has to contain the artifact: a packet that grants
    # path A while returning artifact B is genuinely inconsistent, and that is
    # the error this check exists to catch.
    if return_artifact and write_scope and not any(
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
        packet_relative,
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
    # Ground the packet's contract in the admission-time registry pin before
    # any authority is constructed from it. Schema validation above proved
    # only internal consistency, and a packet-local hash can be recomputed
    # after a tamper; the registry entry cannot.
    require_registry_contract_pin(
        root,
        task_id,
        contract=contract,
        declared_sha256=_unquote(fields.get("verification_contract_sha256", "")),
    )

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
    # The blindness floor, applied once where the aperture is resolved rather
    # than at each consumer, so no dispatch path can bypass it: everything
    # downstream -- the authenticated envelope the broker enforces and the
    # launch prompt the worker obeys -- reads the floored value below.
    memory_aperture = enforce_blind_floor(
        memory_aperture,
        packet_blind_target(fields),
        specialist,
        os.environ.get("CHRONO_VAULT_ROOT", "").strip() or None,
    )
    # `focused` is the only aperture permitted to carry a focus, and the
    # supervisor refuses the mismatch outright (`clearance.
    # validate_memory_context`). A floored `focused` packet that kept its focus
    # would therefore not be blinded -- it would be a dead dispatch. This is a
    # no-op on every path except that one, because `packet_memory_contract`
    # already rejects a focus on any other aperture.
    if memory_aperture != "focused":
        memory_focus = None
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
    mailbox_rewrites = {
        raw: normalized
        for raw, normalized in (
            (raw_return_artifact, return_artifact),
            *zip(raw_write_scope, write_scope),
            *zip(
                raw_evidence_paths,
                (str(output.get("path") or "") for output in evidence_outputs),
            ),
        )
        if raw and raw != normalized
    }
    for legacy, canonical in mailbox_rewrites.items():
        packet_text = packet_text.replace(legacy, canonical)
    expected_outbox = canonical_mailbox_relative(
        "outbox", task_id, response=True
    )
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
        # The delivery contract must name the envelope whenever it is a second
        # file; computed here rather than after assembly so the prompt can say so.
        outbox_relative=expected_outbox,
    )
    if len(task_prompt.encode("utf-8")) > TRUSTED_LAUNCH_PROMPT_LIMIT:
        raise DispatchContextError("task packet is too large for trusted launch prompt")

    budgets = {
        # Safety BACKSTOP against a truly-hung / runaway spawn — NOT a normal
        # deadline. A short deadline was killing legitimate long tasks; instead
        # Chrono supervises live (dashboard stall visibility) and cancels a stuck
        # spawn. Real tasks finish well within this; the backstop only catches an
        # infinite loop so it can't burn unbounded.
        "timeout_seconds": timeout_budget_for_mode(mode)
    }
    if lane == "gemini":
        budgets[AGY_EXTERNAL_MCP_MAX_CALLS_FIELD] = agy_external_mcp_max_calls(
            fields
        )

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
        "budgets": budgets,
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
#   * frozen-question provenance -> swarm_spec_sha256
#   * worker_response_issue     -> the legacy assigned-worker delivery fence
# Output promotion rebuilds the envelope from the trusted launch authority, and
# it used to emit only the seven identity rows -- silently discarding every one
# of those echoes, so capability/provenance/worker completions could never settle
# (audit CC-03). A separately dispatched review has the same structural need:
# its own task id belongs in ``in_response_to``, while the controller-authored
# packet's ``reviews`` field names the held subject. These are reconstructed
# from the AUTHORITY, never from worker metadata: a worker must not be able to
# author the value that proves its own response is current or choose which task
# its review settles.
RECONCILIATION_ECHO_KEYS: dict[str, re.Pattern[str]] = {
    "capability_card_sha256": SHA256_RE,
    "swarm_spec_sha256": SHA256_RE,
    "reviews": TASK_RE,
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
    """Derive packet-owned pins and review linkage for the response envelope.

    The packet -- whose SHA-256 is itself bound into the authority -- is a
    trusted launch-time source. In particular, ``reviews`` is a dispatch fact,
    not a field a reviewer should have to remember or be allowed to retarget.
    """

    echo: dict[str, str] = {}
    review_target = _unquote(fields.get("reviews", ""))
    if review_target:
        echo["reviews"] = review_target
    capability_pin = _unquote(fields.get("capability_card_sha256", ""))
    if capability_pin:
        echo["capability_card_sha256"] = capability_pin
    question_pin = _unquote(fields.get("swarm_spec_sha256", ""))
    if question_pin:
        echo["swarm_spec_sha256"] = question_pin
    return validate_reconciliation_echo(echo)


def require_registry_contract_pin(
    repo_root: Path,
    task_id: str,
    *,
    contract: Mapping[str, Any],
    declared_sha256: str,
) -> None:
    """Refuse a packet contract that disagrees with the locked registry pin.

    The registry entry written at admission time carries the full contract
    object AND its digest (`bin/send-task.sh` pins both), and that entry is the
    trusted external record of what was admitted. The packet's copy is not: its
    adjacent self-hash authenticates nothing, because whoever can edit the
    contract can recompute the hash, and the schema validator alone cannot tell
    a legitimate `deliverable_review_policy.required` from a downgrade -- it
    re-derives that value from the object under check
    (`verification_contract.validate_verification_contract`). Comparing here,
    before authority is constructed, grounds dispatch admission in a fact the
    packet cannot rewrite.

    Fails open only when there is nothing to compare -- no registry file, no
    entry for the task, or an entry that predates contract pinning -- mirroring
    `registry_reconciliation_echo`'s availability behavior exactly. A pin that
    is PRESENT and disagrees is always fatal, including a malformed one.
    """

    registry_path = Path(repo_root) / "_state" / "active-tasks.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        return
    try:
        import registry_reconciler as rr
    except ImportError:
        return
    try:
        with rr.locked_registry():
            registry = rr.load_registry()
            entry = registry.get(task_id) if isinstance(registry, dict) else None
    except (OSError, ValueError):
        return
    if not isinstance(entry, dict):
        return
    pinned_contract = entry.get("verification_contract")
    pinned_digest = entry.get("verification_contract_sha256")
    if pinned_digest is not None and pinned_digest != declared_sha256:
        raise DispatchContextError(
            "packet verification_contract_sha256 does not match the locked "
            f"registry pin for {task_id} "
            f"(packet={declared_sha256} registry={pinned_digest})"
        )
    if pinned_contract is not None and pinned_contract != dict(contract):
        raise DispatchContextError(
            "packet verification_contract does not match the locked registry "
            f"pin for {task_id}"
        )


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
    verdict: str = "",
) -> bytes:
    """Reconstruct a canonical response envelope from the trusted authority.

    Every identity field is fully determined by the launch authority, so the
    only worker-authored signals carried across are the (already coerced)
    ``status`` intent, a review's substantive ``verdict``, and the summary
    prose. The review target remains controller-owned in ``reconciliation_echo``.
    Pin/fence/linkage rows are appended from the authority in sorted key order.
    Rendering is deterministic, which keeps re-publication idempotent.
    """

    echo = validate_reconciliation_echo(reconciliation_echo)
    echo_rows = "".join(f"{key}: {echo[key]}\n" for key in sorted(echo))
    failure_row = f"failure_class: {failure_class}\n" if failure_class else ""
    review_verdict = verdict.strip() if isinstance(verdict, str) else ""
    if (
        "\x00" in review_verdict
        or "\n" in review_verdict
        or "\r" in review_verdict
        or len(review_verdict) > 2048
    ):
        raise DispatchContextError("response verdict is malformed")
    verdict_row = f"verdict: {review_verdict}\n" if review_verdict else ""
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
        f"{verdict_row}"
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
# downstream reads a worker-authored identity key: the published envelope is
# re-rendered from the launch authority by _render_response_envelope. ``status``
# and ``verdict`` remain worker-authored outcome signals, not identity.
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


def _is_reclaimable_destination(
    existing: bytes,
    *,
    reclaim_board_blocked_stub_for: str | None,
    reclaim_exact_bytes: bytes | None,
) -> bool:
    """True when overwriting ``existing`` is reconciliation, not clobbering.

    Exactly two provably-same-task shapes qualify: the controller-authored
    blocked stub for this task id, and a byte-exact copy of this same
    completion's validated worktree bytes -- the state left behind when a
    promotion was interrupted between its artifact and envelope writes.
    Anything else (another task's file, edited content, an unknown writer)
    stays refused.
    """

    if reclaim_board_blocked_stub_for and _is_board_blocked_stub(
        existing, reclaim_board_blocked_stub_for
    ):
        return True
    return reclaim_exact_bytes is not None and existing == reclaim_exact_bytes


def _validate_destination(
    repo_root: Path,
    relative: str,
    data: bytes,
    *,
    label: str,
    reclaim_board_blocked_stub_for: str | None = None,
    reclaim_exact_bytes: bytes | None = None,
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
        if existing != data and not _is_reclaimable_destination(
            existing,
            reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
            reclaim_exact_bytes=reclaim_exact_bytes,
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
    reclaim_exact_bytes: bytes | None = None,
) -> Path:
    destination = _validate_destination(
        repo_root,
        relative,
        data,
        label=label,
        reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
        reclaim_exact_bytes=reclaim_exact_bytes,
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
    reclaim_exact_bytes: bytes | None = None,
) -> tuple[Path, bool]:
    destination = _safe_destination(
        repo_root,
        relative,
        data,
        label=label,
        reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
        reclaim_exact_bytes=reclaim_exact_bytes,
    )
    reclaim_existing = False
    if destination.exists():
        if not destination.is_file():
            raise DispatchContextError(f"{label} destination already differs")
        existing = destination.read_bytes()
        if existing == data:
            return destination, True
        reclaim_existing = _is_reclaimable_destination(
            existing,
            reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
            reclaim_exact_bytes=reclaim_exact_bytes,
        )
        if not reclaim_existing:
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
            if reclaim_existing:
                if (
                    destination.is_symlink()
                    or not destination.is_file()
                    or not _is_reclaimable_destination(
                        destination.read_bytes(),
                        reclaim_board_blocked_stub_for=reclaim_board_blocked_stub_for,
                        reclaim_exact_bytes=reclaim_exact_bytes,
                    )
                ):
                    raise DispatchContextError(
                        f"{label} destination changed during reclaim"
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


SYNTHESIZED_ENVELOPE_MARKER = (
    "CONTROLLER-SYNTHESIZED RESPONSE ENVELOPE — the lane wrote and validated its "
    "return artifact but authored no response envelope."
)


def _artifact_summary_excerpt(artifact_text: str, *, limit: int = 600) -> str:
    """Return the artifact's first prose paragraph for a synthesized envelope.

    Frontmatter, headings, fences, tables and quotes are skipped so the summary
    the reconciler surfaces to Chrono says something about the work rather than
    echoing a `# Title` line. An artifact with no prose at all yields "" and the
    caller falls back to the marker alone.
    """

    lines = artifact_text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            lines = lines[lines[1:].index("---") + 2 :]
        except ValueError:
            pass
    paragraph: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(("#", "---", "```", "~~~", "|", ">", "<!--")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
        if sum(len(item) + 1 for item in paragraph) >= limit:
            break
    excerpt = " ".join(paragraph)[:limit].strip()
    # A summary row must survive `_render_response_envelope` and the watcher's
    # frontmatter parser, so no NULs and no accidental `---` fence.
    return excerpt.replace("\x00", "").strip("-").strip()


def _verify_candidate_tree_health(
    worktree_root: Path,
    write_paths: Sequence[str],
    bridge_owned_paths: Sequence[str],
) -> None:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Refuse code residue when the candidate adds a tree-health failure.

    ``board-supervisor.sh`` calls :func:`prepare_worktree_outputs` before it
    calls ``commit_worker_residue`` and ``integrate_worktree_commits``.  This
    is therefore the last in-scope seam where an outcome gate can inspect the
    worker's complete candidate (including uncommitted edits) without having
    to roll back a visible branch mutation.

    The verifier executable comes from the controller's code checkout, while
    ``VAULT_ROOT`` points it at the candidate worktree.  A worker may alter
    the data being validated but cannot replace the validator that judges it.
    Minimal/public fixture trees that do not carry the canonical runtime map
    are outside this repository-specific gate; the production worktree does.
    """

    bridge_owned = frozenset(bridge_owned_paths)
    candidate_scopes = tuple(path for path in write_paths if path not in bridge_owned)
    if not candidate_scopes:
        return

    try:
        candidate_root = Path(worktree_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DispatchContextError(
            f"candidate tree health root is unavailable: {exc}"
        ) from exc
    if not (candidate_root / "shared/specialist-runtime-map.tsv").is_file():
        return

    verifier = Path(RESIDUE_HEALTH_VERIFIER)
    if verifier.is_symlink() or not verifier.is_file():
        raise DispatchContextError(
            f"candidate tree health verifier is unavailable: {verifier}"
        )
    command = ("/bin/bash", str(verifier), "--quiet")
    environment = dict(os.environ)
    environment["VAULT_ROOT"] = str(candidate_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Run repo tooling on the operator's real PATH, which the supervisor already
    # preserves for exactly this purpose.
    #
    # `board-supervisor.sh` hardens its own PATH to /usr/bin:/bin:/usr/sbin:/sbin
    # (a boundary for untrusted input) but captures the incoming one as
    # TRUSTED_HOST_PATH and hands it to the worker launch. This health check is
    # the SAME kind of consumer -- trusted first-party tooling -- and simply was
    # not using the mechanism. Under the hardened PATH, `python3` was macOS 3.9,
    # `validate_capability_homes.py` died importing `tomllib`, and the failure
    # surfaced as "candidate tree health check refused residue promotion". Five
    # consecutive tasks were blocked holding correct work (2026-08-31).
    #
    # DEFAULT_LANE_PATH was tried here first and is NOT equivalent: it omits
    # ~/.cargo/bin, so tool probes then fail on cargo-installed tools such as
    # `anchor`. TRUSTED_HOST_PATH is the operator's actual PATH, so it resolves
    # everything the host really has.
    _trusted_path = os.environ.get("TRUSTED_HOST_PATH", "").strip()
    if _trusted_path:
        environment["PATH"] = _trusted_path
    # Judge the RESIDUE, not the host. This gate decides whether a worker's
    # changes may be promoted, and live capability-home *existence* asks a
    # different question entirely: is every declared tool installed on this
    # machine right now. A worker cannot install or uninstall anything, so that
    # check can only ever fail for reasons the worker is not responsible for.
    #
    # It also cannot pass reliably here. A detached supervisor's PATH is
    # structurally narrower than an interactive shell's -- no Homebrew, no
    # ~/.local/bin, no ~/.cargo/bin -- so the existence probes were judging a
    # machine that does not exist. Measured 2026-08-31 on a real worktree:
    #
    #   restricted PATH, full gate         rc=1, 140 diagnostics
    #   restricted PATH, host-independent   rc=0,   0 diagnostics
    #
    # Five consecutive tasks were blocked here holding correct work.
    #
    # This is a DELIBERATE narrowing, set explicitly rather than inherited. The
    # previous code popped the variable so an ambient value could not weaken the
    # gate, and that concern is still honoured: nothing ambient decides this, the
    # controller does. Live existence keeps its home in the local pre-commit hook
    # (bin/validate-specialists.sh says so in its own INFO line), which runs on a
    # real developer PATH where the answer is meaningful. Everything that can
    # actually detect bad residue -- boundary, parity, index, source, required --
    # still runs on every settlement.
    environment["SQUAD_CI_HOST_INDEPENDENT"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=str(candidate_root),
            env=environment,
            capture_output=True,
            text=True,
            timeout=RESIDUE_HEALTH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DispatchContextError(
            f"candidate tree health check could not execute: {exc}"
        ) from exc
    if completed.returncode == 0:
        return

    # A whole-tree failure is not evidence that this attempt caused it. Compare
    # the exact same validator against the immutable merge-base between the
    # worker and the admitted integration branch. This avoids a second,
    # maintenance-heavy path-to-validator registry while preserving the gate
    # for every diagnostic that is new in the candidate.
    base_branch = os.environ.get("SQUAD_BASE_BRANCH", "").strip()
    base_comparison_error = ""
    base_completed: subprocess.CompletedProcess[str] | None = None
    base_root: Path | None = None
    if not base_branch:
        base_comparison_error = "SQUAD_BASE_BRANCH is unavailable"
    else:
        try:
            merge_base = subprocess.run(
                ("git", "merge-base", "HEAD", f"refs/heads/{base_branch}"),
                cwd=str(candidate_root),
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            base_commit = merge_base.stdout.strip()
            if (
                merge_base.returncode != 0
                or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_commit) is None
            ):
                base_comparison_error = (
                    "cannot derive admitted merge-base: "
                    + (merge_base.stderr.strip() or "git merge-base returned no commit")
                )
            else:
                with tempfile.TemporaryDirectory(
                    prefix="candidate-health-base-"
                ) as directory:
                    base_root = Path(directory) / "base"
                    cloned = subprocess.run(
                        (
                            "git",
                            "clone",
                            "--quiet",
                            "--no-checkout",
                            "--shared",
                            "--",
                            str(candidate_root),
                            str(base_root),
                        ),
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    if cloned.returncode != 0:
                        base_comparison_error = (
                            "cannot materialize admitted base: "
                            + (cloned.stderr.strip() or "git clone failed")
                        )
                    else:
                        checked_out = subprocess.run(
                            ("git", "checkout", "--quiet", "--detach", base_commit),
                            cwd=str(base_root),
                            env=environment,
                            capture_output=True,
                            text=True,
                            timeout=60,
                            check=False,
                        )
                        if checked_out.returncode != 0:
                            base_comparison_error = (
                                "cannot check out admitted base: "
                                + (checked_out.stderr.strip() or "git checkout failed")
                            )
                        else:
                            base_environment = dict(environment)
                            base_environment["VAULT_ROOT"] = str(base_root)
                            base_completed = subprocess.run(
                                command,
                                cwd=str(base_root),
                                env=base_environment,
                                capture_output=True,
                                text=True,
                                timeout=RESIDUE_HEALTH_TIMEOUT_SECONDS,
                                check=False,
                            )
                            if base_completed.returncode != 0:
                                candidate_issues = _health_failure_lines(
                                    completed, candidate_root
                                )
                                base_issues = _health_failure_lines(
                                    base_completed, base_root
                                )
                                introduced = candidate_issues - base_issues
                                if not introduced:
                                    print(
                                        "WARNING: candidate tree health failure is "
                                        "already present at the admitted base; "
                                        "settlement will not block it, and the "
                                        "owning CI/release boundary must clear it",
                                        file=sys.stderr,
                                    )
                                    return
        except (OSError, subprocess.TimeoutExpired) as exc:
            base_comparison_error = f"base comparison could not execute: {exc}"

    # If the base is healthy, the candidate's failure is necessarily new. If
    # both fail, only a candidate-only diagnostic is causal. When the base
    # cannot be measured, causation is unproven and the doctrine requires a
    # warning rather than denial at this boundary.
    if base_comparison_error:
        print(
            "WARNING: candidate tree health failure could not be compared with "
            f"the admitted base ({base_comparison_error}); settlement will not "
            "block it, and the owning CI/release boundary must evaluate it",
            file=sys.stderr,
        )
        return

    combined = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part.strip()
    ).replace("\x00", "")
    # Report the lines that explain the FAILURE, not the last 4000 characters.
    #
    # This validator emits one JSON line per file, and 71 of them pass, so a
    # blind tail is 4000 characters of `"status":"pass"` with the actual cause
    # scrolled off the front. Measured 2026-08-31: five tasks were blocked and
    # every stored error began mid-token ("ile\":\"...") in a run of pass lines.
    # The real cause -- `ModuleNotFoundError: No module named 'tomllib'` -- sat
    # just outside the window each time, so five identical failures read as an
    # unexplained repository-health verdict and were diagnosed by hand.
    #
    # Keep the bound (a validator CAN emit one diagnostic per adapter), but
    # spend it on lines that carry signal, and say plainly when lines were
    # dropped so a truncated report can never again look complete.
    if combined:
        lines = combined.splitlines()
        interesting = [line for line in lines if '"status":"pass"' not in line]
        selected = interesting or lines
        detail = "\n".join(selected)[-4000:]
        dropped = len(lines) - len(selected)
        if dropped > 0:
            detail = f"[{dropped} passing line(s) omitted]\n{detail}"
    else:
        detail = "no output"
    raise DispatchContextError(
        "candidate tree health check refused residue promotion: "
        f"command={' '.join(command)} exit={completed.returncode} output={detail}"
    )


def _health_failure_lines(
    completed: subprocess.CompletedProcess[str], tree_root: Path
) -> frozenset[str]:
    """Return stable, root-independent diagnostics from one failed health run."""

    combined = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part.strip()
    ).replace("\x00", "")
    root_text = str(tree_root)
    stable: set[str] = set()
    for raw_line in combined.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("INFO:", "Total:")):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            stable.add(line.replace(root_text, "<TREE>"))
            continue
        if not isinstance(payload, Mapping):
            stable.add(line.replace(root_text, "<TREE>"))
            continue
        if payload.get("status") == "pass" or payload.get("schema") == (
            "capability-home-validation/v1"
        ):
            continue
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        stable.add(canonical.replace(root_text, "<TREE>"))
    return frozenset(stable)


def prepare_worktree_outputs(
    repo_root: Path,
    worktree_root: Path,
    authority: Mapping[str, object],
) -> PreparedWorktreeOutputs:
    """Capture validated completion bytes before any integration mutation."""

    task_id = str(authority.get("task_id", ""))
    lane = str(authority.get("lane", ""))
    raw_result_relative = _safe_relative(
        str(authority.get("expected_result_path", "")),
        field="expected_result_path",
    )
    result_relative = _canonicalize_mailbox_response(
        raw_result_relative, task_id
    )
    raw_outbox_relative = _safe_relative(
        str(authority.get("expected_outbox_path", "")),
        field="expected_outbox_path",
    )
    outbox_relative = _canonicalize_mailbox_response(
        raw_outbox_relative, task_id
    )
    raw_write_paths = authority.get("write_paths")
    write_paths = (
        [
            _canonicalize_mailbox_response(item, task_id)
            for item in raw_write_paths
        ]
        if isinstance(raw_write_paths, list)
        and all(isinstance(item, str) for item in raw_write_paths)
        else raw_write_paths
    )
    raw_evidence_outputs = authority.get("evidence_outputs", [])
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
        or not isinstance(raw_write_paths, list)
        or any(not isinstance(item, str) for item in raw_write_paths)
        or not isinstance(write_paths, list)
        or not any(_contains(item, result_relative) for item in write_paths)
        or not isinstance(raw_evidence_outputs, list)
        or len(raw_evidence_outputs) > MAXIMUM_EVIDENCE_OUTPUTS
    ):
        raise DispatchContextError(
            "bridge authority identity or write scope is invalid"
        )
    if outbox_relative != canonical_mailbox_relative(
        "outbox", task_id, response=True
    ):
        raise DispatchContextError("expected outbox path is not canonical")

    # Validate both sources before publishing either. The envelope is the
    # watcher-visible commit marker and is always published last.
    result_bytes = _read_contained_regular(
        Path(worktree_root),
        raw_result_relative,
        label="return artifact",
        maximum_bytes=8 * 1024 * 1024,
    )
    try:
        result_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DispatchContextError("return artifact is not UTF-8") from exc
    # A split-output packet declares a `return_artifact` that is not the outbox
    # response path. Measured 2026-08-26: completed work was discarded when the
    # artifact existed but the required envelope did not. The prompt fix in
    # `delivery_contract_note` is the primary path; this is the backstop that does
    # not depend on every lane's instruction-following.
    #
    # This does NOT weaken the gate. Nothing here accepts a missing or empty
    # artifact -- `_read_contained_regular` above still blocks that -- and an
    # envelope that EXISTS but is a symlink, a directory, empty, or oversized
    # still blocks, because that is tamper-shaped rather than forgetful-lane
    # shaped. Only the aliased-path case is exempt: when the two paths are the
    # same file, a missing envelope IS a missing artifact and already blocked.
    synthesized_envelope = result_relative != outbox_relative and not os.path.lexists(
        Path(worktree_root) / raw_outbox_relative
    )
    if synthesized_envelope:
        # Not `complete`: the controller knows the artifact landed, not that the
        # lane considered itself finished. `needs_review` is the same default
        # `_coerce_status` already applies to an unmappable worker status, so
        # questionable work surfaces to the controller instead of auto-closing.
        # `registry_reconciler.resolve_worker_status` then resolves it against
        # the task's trusted review triggers, so no review debt is manufactured
        # or silently discarded.
        canonical_status = "needs_review"
        excerpt = _artifact_summary_excerpt(result_bytes.decode("utf-8"))
        summary = (
            f"{SYNTHESIZED_ENVELOPE_MARKER} Promoted from `{result_relative}`; "
            "status is not a worker completion claim."
            + (f"\n\nArtifact excerpt: {excerpt}" if excerpt else "")
        )
        envelope = {}
    else:
        envelope_bytes = _read_contained_regular(
            Path(worktree_root),
            raw_outbox_relative,
            label="response envelope",
            maximum_bytes=256 * 1024,
        )
        envelope, summary = _parse_response_envelope(envelope_bytes)
        canonical_status = _coerce_status(envelope.get("status", ""))
    # Normalize-and-promote rather than strand: the envelope is worker-authored
    # metadata whose identity fields are fully determined by the trusted launch
    # authority. A completion that carries a real, validated artifact (checked
    # above) and committed residue (integrated by the supervisor) must not be
    # exit-75 stranded on a metadata nit -- a non-canonical status, a missing
    # required field, or an unexpected extra. Reconstruct a canonical envelope
    # from the authority, carrying only the worker's coerced status intent,
    # substantive review verdict, and summary prose across. Genuinely-missing
    # work still blocks: an empty/absent artifact fails _read_contained_regular,
    # an empty summary fails the parser, and uncommitted residue fails
    # integration upstream. See
    # _state/consults/envelope-prevalidation-fix.md.
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
        verdict=envelope.get("verdict", ""),
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
    if result_relative == outbox_relative:
        # The standard packet shape declares the outbox response path as its
        # own return_artifact, so the artifact and the envelope are ONE file.
        # Validating (and later publishing) two different payloads against that
        # one path is the self-collision that blocked every aliased completion:
        # the bridge's own artifact write made the envelope write refuse with
        # "destination already differs" over finished, correct work. The
        # canonical envelope alone is validated here -- it carries the worker's
        # entire summary body plus the trusted pins, so nothing is lost -- and
        # the worker's raw bytes stay reclaimable so a promotion interrupted
        # between the two historic writes reconciles instead of refusing.
        # Mirrors publish_blocked_completion's aliased branch.
        _validate_destination(
            Path(repo_root),
            outbox_relative,
            normalized_bytes,
            label="response envelope",
            reclaim_board_blocked_stub_for=task_id,
            reclaim_exact_bytes=result_bytes,
        )
    else:
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
    _verify_candidate_tree_health(
        Path(worktree_root),
        write_paths,
        (
            result_relative,
            outbox_relative,
            *(output.relative_path for output in prepared_evidence),
        ),
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
    if prepared.result_relative == prepared.outbox_relative:
        # Aliased standard shape: the envelope IS the artifact. Publish the
        # canonical envelope once instead of aiming two payloads at one file
        # (the second write always refused with "destination already differs"
        # once the CC-03 pins made the rendered envelope differ from the raw
        # worker file). The worker's raw bytes remain reclaimable so the state
        # a pre-fix interrupted promotion left behind -- raw response landed,
        # envelope refused -- reconciles on retry instead of stranding again.
        envelope_path, envelope_idempotent = _atomic_publish(
            Path(repo_root),
            prepared.outbox_relative,
            prepared.envelope_bytes,
            label="response envelope",
            reclaim_board_blocked_stub_for=prepared.task_id,
            reclaim_exact_bytes=prepared.result_bytes,
        )
        result_path, result_idempotent = envelope_path, envelope_idempotent
        published_artifact_bytes = prepared.envelope_bytes
    else:
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
        published_artifact_bytes = prepared.result_bytes
    return {
        "status": prepared.status,
        "artifact_published": True,
        "artifact_idempotent": result_idempotent,
        "artifact_path": str(result_path),
        "artifact_sha256": _sha256_bytes(published_artifact_bytes),
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
    compatibility_namespace: str | None = None,
    reason: str,
    failure_class: str | None = None,
    attempt_id: str | None = None,
    generation: int | None = None,
) -> dict[str, object]:
    if (
        not TASK_RE.fullmatch(task_id)
        or lane not in LANE_TO_MODEL
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
    # Retain the keyword/CLI value as a transition-only ABI for supervisors
    # launched before the mailbox cutover. It is deliberately ignored: a
    # caller can no longer select a second outbox path.
    del compatibility_namespace
    outbox_relative = canonical_mailbox_relative(
        "outbox", task_id, response=True
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
    # A dry-run has not published anything yet, so its packet is a staging copy
    # outside the mailbox. Without this the location check alone would refuse
    # every dry-run and the preflight could never be wired at all.
    check.add_argument("--staged", action="store_true")
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
                staged=args.staged,
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
    except OSError as exc:
        parser.error(f"task packet is unreadable: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
