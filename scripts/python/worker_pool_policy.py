#!/usr/bin/env python3
"""Strict parser and deterministic guard logic for worker-pool-policy/v1."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable


SCHEMA_VERSION = "worker-pool-policy/v1"
LANES = ("claude", "gpt-codex", "gemini", "kimi")
PROVIDER_STATES = frozenset({"ready", "blocked", "throttled"})
POLICY_COLUMNS = (
    "schema_version", "record_kind", "key", "min_workers",
    "default_workers", "max_workers", "queue_depth_cap", "review_debt_cap",
    "subagent_concurrency_cap", "worker_memory_estimate_mib",
    "global_worker_cap", "reserved_review_workers", "host_memory_mib",
    "memory_high_water_mib", "nudge_scan_interval_seconds",
    "lease_timeout_seconds", "heartbeat_timeout_seconds",
    "drain_timeout_seconds", "stable_window_scans",
    "provider_budget_microusd", "provider_concurrency_cap",
    "provider_rate_limit_per_minute", "default_task_cost_microusd",
    "provider_guard",
)
MARKDOWN_KEYS = frozenset({
    "schema_version", "policy_id", "status", "author_family", "review_model",
    "policy_tsv", "policy_tsv_sha256",
})
INTEGER_FIELDS = frozenset(POLICY_COLUMNS[3:-1])
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class PolicyError(ValueError):
    """The reviewed policy surface is malformed, stale, or unsafe."""


@dataclass(frozen=True)
class LanePolicy:
    lane: str
    min_workers: int
    default_workers: int
    max_workers: int
    queue_depth_cap: int
    review_debt_cap: int
    subagent_concurrency_cap: int
    worker_memory_estimate_mib: int
    provider_budget_microusd: int
    provider_concurrency_cap: int
    provider_rate_limit_per_minute: int
    default_task_cost_microusd: int
    provider_guard: str


@dataclass(frozen=True)
class WorkerPoolPolicy:
    policy_id: str
    status: str
    author_family: str
    review_model: str
    policy_tsv: str
    tsv_sha256: str
    markdown_sha256: str
    policy_sha256: str
    global_worker_cap: int
    reserved_review_workers: int
    host_memory_mib: int
    memory_high_water_mib: int
    queue_depth_cap: int
    review_debt_cap: int
    nudge_scan_interval_seconds: int
    lease_timeout_seconds: int
    heartbeat_timeout_seconds: int
    drain_timeout_seconds: int
    stable_window_scans: int
    lanes: dict[str, LanePolicy]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise PolicyError("policy markdown requires frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise PolicyError("policy markdown frontmatter is unterminated")
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or ":" not in line:
            raise PolicyError("policy markdown frontmatter must be flat key/value data")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in result:
            raise PolicyError(f"duplicate policy markdown key: {key}")
        result[key] = value
    unknown = set(result) - MARKDOWN_KEYS
    missing = MARKDOWN_KEYS - set(result)
    if unknown or missing:
        raise PolicyError(
            f"policy markdown keys mismatch: missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    return result


def _int_row(row: dict[str, str], field: str) -> int:
    raw = row[field]
    if not re.fullmatch(r"0|[1-9][0-9]*", raw):
        raise PolicyError(f"{row['key']}.{field} must be a canonical nonnegative integer")
    return int(raw)


def _zero(row: dict[str, str], fields: Iterable[str]) -> None:
    for field in fields:
        if _int_row(row, field) != 0:
            raise PolicyError(f"{row['key']}.{field} must be zero for {row['record_kind']} rows")


def _canonical_policy_payload(meta: dict[str, str], global_row: dict[str, str], lane_rows: dict[str, dict[str, str]]) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy_id": meta["policy_id"],
        "status": meta["status"],
        "author_family": meta["author_family"],
        "review_model": meta["review_model"],
        "policy_tsv": meta["policy_tsv"],
        "policy_tsv_sha256": meta["policy_tsv_sha256"],
        "global": global_row,
        "lanes": [lane_rows[lane] for lane in LANES],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def load_worker_pool_policy(markdown_path: Path, *, require_approved: bool = False) -> WorkerPoolPolicy:
    markdown_path = markdown_path.resolve()
    markdown_bytes = markdown_path.read_bytes()
    meta = _parse_frontmatter(markdown_bytes.decode("utf-8"))
    if meta["schema_version"] != SCHEMA_VERSION:
        raise PolicyError(f"unsupported policy schema: {meta['schema_version']}")
    if meta["status"] not in {"needs_review", "approved"}:
        raise PolicyError("policy status must be needs_review or approved")
    if require_approved and meta["status"] != "approved":
        raise PolicyError("worker-pool policy is not independently approved")
    if meta["author_family"] != "openai" or meta["review_model"] != "claude":
        raise PolicyError("policy review metadata must require Claude anti-affinity")
    tsv_rel = PurePosixPath(meta["policy_tsv"])
    if tsv_rel.is_absolute() or ".." in tsv_rel.parts:
        raise PolicyError("policy_tsv must be a repository-relative path")
    repo_root = markdown_path.parents[1]
    tsv_path = (repo_root / Path(*tsv_rel.parts)).resolve()
    if repo_root not in tsv_path.parents:
        raise PolicyError("policy_tsv resolves outside the repository")
    tsv_bytes = tsv_path.read_bytes()
    tsv_sha = _sha256(tsv_bytes)
    if not HEX64_RE.fullmatch(meta["policy_tsv_sha256"]):
        raise PolicyError("policy_tsv_sha256 must be lowercase 64-hex")
    if tsv_sha != meta["policy_tsv_sha256"]:
        raise PolicyError("policy TSV hash does not match reviewed markdown")

    reader = csv.DictReader(tsv_bytes.decode("utf-8").splitlines(), delimiter="\t")
    if tuple(reader.fieldnames or ()) != POLICY_COLUMNS:
        raise PolicyError("policy TSV header mismatch")
    rows = list(reader)
    if len(rows) != 1 + len(LANES):
        raise PolicyError("policy TSV must contain one global row and every known lane exactly once")
    by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        if None in row or set(row) != set(POLICY_COLUMNS) or any(value is None for value in row.values()):
            raise PolicyError("policy TSV row width mismatch")
        if row["schema_version"] != SCHEMA_VERSION:
            raise PolicyError("every policy TSV row must use worker-pool-policy/v1")
        key = row["key"]
        if key in by_key:
            raise PolicyError(f"duplicate policy row: {key}")
        if row["record_kind"] not in {"global", "lane"}:
            raise PolicyError(f"unknown record_kind: {row['record_kind']}")
        for field in INTEGER_FIELDS:
            _int_row(row, field)
        by_key[key] = row
    if set(by_key) != {"global", *LANES}:
        raise PolicyError(f"policy keys mismatch: {sorted(by_key)}")
    global_row = by_key["global"]
    if global_row["record_kind"] != "global" or global_row["provider_guard"] != "none":
        raise PolicyError("global policy row is malformed")
    lane_rows = {lane: by_key[lane] for lane in LANES}
    if any(row["record_kind"] != "lane" for row in lane_rows.values()):
        raise PolicyError("lane policy rows must declare record_kind=lane")
    _zero(global_row, (
        "min_workers", "default_workers", "max_workers",
        "subagent_concurrency_cap", "worker_memory_estimate_mib",
        "provider_budget_microusd", "provider_concurrency_cap",
        "provider_rate_limit_per_minute", "default_task_cost_microusd",
    ))
    for row in lane_rows.values():
        _zero(row, (
            "global_worker_cap", "reserved_review_workers", "host_memory_mib",
            "memory_high_water_mib", "nudge_scan_interval_seconds",
            "lease_timeout_seconds", "heartbeat_timeout_seconds",
            "drain_timeout_seconds", "stable_window_scans",
        ))
        if row["provider_guard"] not in {"capacity", "metered"}:
            raise PolicyError(f"{row['key']}.provider_guard must be capacity or metered")

    global_cap = _int_row(global_row, "global_worker_cap")
    review_reserve = _int_row(global_row, "reserved_review_workers")
    host_memory = _int_row(global_row, "host_memory_mib")
    high_water = _int_row(global_row, "memory_high_water_mib")
    queue_cap = _int_row(global_row, "queue_depth_cap")
    debt_cap = _int_row(global_row, "review_debt_cap")
    scan = _int_row(global_row, "nudge_scan_interval_seconds")
    lease = _int_row(global_row, "lease_timeout_seconds")
    heartbeat = _int_row(global_row, "heartbeat_timeout_seconds")
    drain = _int_row(global_row, "drain_timeout_seconds")
    stable = _int_row(global_row, "stable_window_scans")
    if global_cap < 1 or not 1 <= review_reserve < global_cap:
        raise PolicyError("global cap must exceed a positive reserved review capacity")
    if not 0 < high_water < host_memory:
        raise PolicyError("memory high-water must be positive and below host memory")
    if queue_cap < global_cap or debt_cap < 1:
        raise PolicyError("global queue/debt caps are too small")
    if not 1 <= scan <= 60 or not scan < heartbeat < lease <= drain:
        raise PolicyError("scan/heartbeat/lease/drain timeouts are not safely bounded")
    if stable < 2:
        raise PolicyError("stable_window_scans must be at least two")

    lanes: dict[str, LanePolicy] = {}
    for lane, row in lane_rows.items():
        minimum = _int_row(row, "min_workers")
        default = _int_row(row, "default_workers")
        maximum = _int_row(row, "max_workers")
        lane_queue = _int_row(row, "queue_depth_cap")
        lane_debt = _int_row(row, "review_debt_cap")
        subagents = _int_row(row, "subagent_concurrency_cap")
        estimate = _int_row(row, "worker_memory_estimate_mib")
        budget = _int_row(row, "provider_budget_microusd")
        provider_concurrency = _int_row(row, "provider_concurrency_cap")
        provider_rate = _int_row(row, "provider_rate_limit_per_minute")
        default_cost = _int_row(row, "default_task_cost_microusd")
        if not 0 <= minimum <= default <= maximum <= global_cap:
            raise PolicyError(f"invalid worker bounds for {lane}")
        if lane_queue < maximum or lane_queue > queue_cap:
            raise PolicyError(f"invalid queue cap for {lane}")
        if not 1 <= lane_debt <= debt_cap:
            raise PolicyError(f"invalid review-debt cap for {lane}")
        if subagents < 1 or estimate < 1 or estimate > high_water:
            raise PolicyError(f"invalid subagent or memory estimate for {lane}")
        if provider_concurrency < 1 or provider_rate < provider_concurrency:
            raise PolicyError(f"invalid provider capacity limits for {lane}")
        if row["provider_guard"] == "metered":
            if budget < 1 or not 1 <= default_cost <= budget:
                raise PolicyError(f"invalid metered provider budget for {lane}")
        elif budget != 0 or default_cost != 0:
            raise PolicyError(f"capacity-only provider {lane} must have zero budget/cost")
        lanes[lane] = LanePolicy(
            lane, minimum, default, maximum, lane_queue, lane_debt,
            subagents, estimate, budget, provider_concurrency, provider_rate,
            default_cost, row["provider_guard"],
        )
    if sum(lane.min_workers for lane in lanes.values()) > global_cap:
        raise PolicyError("sum of lane minima exceeds global worker cap")
    if sum(lane.default_workers for lane in lanes.values()) > global_cap:
        raise PolicyError("sum of lane defaults exceeds global worker cap")
    if sum(lane.queue_depth_cap for lane in lanes.values()) > queue_cap:
        raise PolicyError("sum of lane queue caps exceeds global queue cap")

    policy_sha = _sha256(_canonical_policy_payload(meta, global_row, lane_rows))
    return WorkerPoolPolicy(
        policy_id=meta["policy_id"], status=meta["status"],
        author_family=meta["author_family"], review_model=meta["review_model"],
        policy_tsv=meta["policy_tsv"], tsv_sha256=tsv_sha,
        markdown_sha256=_sha256(markdown_bytes), policy_sha256=policy_sha,
        global_worker_cap=global_cap, reserved_review_workers=review_reserve,
        host_memory_mib=host_memory, memory_high_water_mib=high_water,
        queue_depth_cap=queue_cap, review_debt_cap=debt_cap,
        nudge_scan_interval_seconds=scan, lease_timeout_seconds=lease,
        heartbeat_timeout_seconds=heartbeat, drain_timeout_seconds=drain,
        stable_window_scans=stable, lanes=lanes,
    )


def validate_host_snapshot(snapshot: Any) -> dict[str, Any]:
    expected = {"used_memory_mib", "memory_pressure", "swap_active", "compressor_pressure"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected:
        raise PolicyError("host snapshot keys mismatch")
    used = snapshot["used_memory_mib"]
    if isinstance(used, bool) or not isinstance(used, int) or used < 0:
        raise PolicyError("used_memory_mib must be a nonnegative integer")
    for field in expected - {"used_memory_mib"}:
        if not isinstance(snapshot[field], bool):
            raise PolicyError(f"{field} must be boolean")
    return dict(snapshot)


def validate_provider_states(states: Any) -> dict[str, str]:
    if not isinstance(states, dict) or set(states) != set(LANES):
        raise PolicyError("provider state must name every lane exactly once")
    if any(value not in PROVIDER_STATES for value in states.values()):
        raise PolicyError("provider state must be ready, blocked, or throttled")
    return dict(states)


def validate_provider_usage(usage: Any) -> dict[str, dict[str, int]]:
    expected = {"spent_microusd", "active_requests", "requests_last_minute"}
    if not isinstance(usage, dict) or set(usage) != set(LANES):
        raise PolicyError("provider usage must name every lane exactly once")
    result: dict[str, dict[str, int]] = {}
    for lane, raw in usage.items():
        if not isinstance(raw, dict) or set(raw) != expected:
            raise PolicyError(f"{lane} provider usage keys mismatch")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in raw.values()
        ):
            raise PolicyError(
                f"{lane} provider usage values must be nonnegative integers"
            )
        result[lane] = dict(raw)
    return result


def write_scopes_conflict(first: Any, second: Any) -> bool:
    def normalize(raw: Any) -> list[PurePosixPath]:
        if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
            raise PolicyError("write_scope must be a string array")
        paths: list[PurePosixPath] = []
        for value in raw:
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise PolicyError("write_scope paths must be nonempty repository-relative paths")
            paths.append(path)
        return paths
    left, right = normalize(first), normalize(second)
    for one in left:
        for two in right:
            if one == two or one in two.parents or two in one.parents:
                return True
    return False


def default_worker_targets(policy: WorkerPoolPolicy) -> dict[str, int]:
    """Return the deterministic reviewed bootstrap target for every lane."""
    targets = {lane: policy.lanes[lane].default_workers for lane in LANES}
    if sum(targets.values()) > policy.global_worker_cap:
        raise PolicyError("reviewed default worker targets exceed global cap")
    return targets


def supervisor_aimd(
    policy: WorkerPoolPolicy,
    *,
    current_targets: dict[str, int],
    stable_scans: dict[str, int],
    pressure: bool,
    provider_states: dict[str, str],
    workers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a target/drain plan; never signals termination of a leased worker."""
    validate_provider_states(provider_states)
    if set(current_targets) != set(LANES) or set(stable_scans) != set(LANES):
        raise PolicyError("AIMD state must name every lane exactly once")
    worker_ids: set[str] = set()
    for worker in workers:
        if not isinstance(worker, dict) or set(worker) != {"worker_id", "lane", "leased"}:
            raise PolicyError("AIMD worker records require worker_id, lane, and leased")
        if worker["worker_id"] in worker_ids or worker["lane"] not in LANES or not isinstance(worker["leased"], bool):
            raise PolicyError("invalid AIMD worker record")
        worker_ids.add(worker["worker_id"])
    targets: dict[str, int] = {}
    for lane in LANES:
        bounds = policy.lanes[lane]
        current = current_targets[lane]
        stable_count = stable_scans[lane]
        if isinstance(current, bool) or not isinstance(current, int) or not bounds.min_workers <= current <= bounds.max_workers:
            raise PolicyError(f"invalid AIMD target for {lane}")
        if isinstance(stable_count, bool) or not isinstance(stable_count, int) or stable_count < 0:
            raise PolicyError(f"invalid stable scan count for {lane}")
        lane_pressure = pressure or provider_states[lane] in {"blocked", "throttled"}
        target = current
        if lane_pressure and current > bounds.min_workers:
            target = max(bounds.min_workers, current // 2)
            if target == current:
                target = current - 1
        elif not lane_pressure and stable_count >= policy.stable_window_scans and current < bounds.max_workers:
            target = current + 1
        targets[lane] = target
    overflow = max(0, sum(targets.values()) - policy.global_worker_cap)
    if overflow:
        for lane in reversed(LANES):
            removable = min(overflow, targets[lane] - policy.lanes[lane].min_workers)
            targets[lane] -= removable
            overflow -= removable
            if not overflow:
                break
    actions: list[dict[str, Any]] = []
    for lane in LANES:
        lane_workers = sorted(
            (worker for worker in workers if worker["lane"] == lane),
            key=lambda item: (item["leased"], item["worker_id"]),
        )
        excess = max(0, len(lane_workers) - targets[lane])
        for worker in lane_workers[:excess]:
            actions.append({
                "worker_id": worker["worker_id"], "lane": lane,
                "action": "mark-draining" if worker["leased"] else "drain-idle",
                "kill": False,
            })
    return {
        "schema_version": "worker-pool-supervisor-plan/v1",
        "policy_sha256": policy.policy_sha256,
        "default_targets": default_worker_targets(policy),
        "targets": targets,
        "actions": actions,
        "drain_timeout_seconds": policy.drain_timeout_seconds,
    }
