#!/usr/bin/env python3
"""Single-source code and live-host ceilings for lead-internal sub-swarms."""

from __future__ import annotations

import math
import os
from typing import Mapping, Any

from worker_pool_policy import PolicyError, validate_host_snapshot


SUBAGENT_CONCURRENCY_ENV = "SQUAD_SUBAGENT_CONCURRENCY_CAP"
DEFAULT_SUBAGENT_CODE_CEILING = 16
MAX_SUBAGENT_CODE_CEILING = 64
CAPACITY_SCHEMA = "subswarm-capacity/v1"


class CapacityError(ValueError):
    """Raised when a code-ceiling or host-capacity input is unsafe."""


def subagent_code_ceiling(environ: Mapping[str, str] | None = None) -> int:
    """Return the configurable per-lane code ceiling from one authoritative parser."""

    environ = os.environ if environ is None else environ
    raw = environ.get(SUBAGENT_CONCURRENCY_ENV, str(DEFAULT_SUBAGENT_CODE_CEILING))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise CapacityError(f"{SUBAGENT_CONCURRENCY_ENV} must be an integer") from exc
    if not 1 <= value <= MAX_SUBAGENT_CODE_CEILING:
        raise CapacityError(
            f"{SUBAGENT_CONCURRENCY_ENV} must be between 1 and {MAX_SUBAGENT_CODE_CEILING}"
        )
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CapacityError(f"{field} must be a positive integer")
    return value


def compute_subswarm_capacity(
    *,
    code_ceiling: int,
    member_count: int,
    requested_concurrency: int,
    host_snapshot: object,
    host_memory_mib: int,
    memory_high_water_mib: int,
    worker_memory_estimate_mib: int,
    logical_cpu_count: int,
    one_minute_load: float,
) -> dict[str, object]:
    """Compute an honest live-host ceiling and effective concurrency.

    Total logical members may exceed the host ceiling: they are queued by the DAG
    scheduler. Admission fails only when live pressure leaves no safe slot.
    """

    code_ceiling = _positive_int(code_ceiling, "code_ceiling")
    member_count = _positive_int(member_count, "member_count")
    requested_concurrency = _positive_int(
        requested_concurrency, "requested_concurrency"
    )
    host_memory_mib = _positive_int(host_memory_mib, "host_memory_mib")
    memory_high_water_mib = _positive_int(
        memory_high_water_mib, "memory_high_water_mib"
    )
    worker_memory_estimate_mib = _positive_int(
        worker_memory_estimate_mib, "worker_memory_estimate_mib"
    )
    logical_cpu_count = _positive_int(logical_cpu_count, "logical_cpu_count")
    if memory_high_water_mib >= host_memory_mib:
        raise CapacityError("memory_high_water_mib must be below host_memory_mib")
    if requested_concurrency > member_count:
        raise CapacityError("requested_concurrency cannot exceed member_count")
    if requested_concurrency > code_ceiling:
        raise CapacityError("requested_concurrency exceeds code_ceiling")
    if isinstance(one_minute_load, bool) or not isinstance(one_minute_load, (int, float)) \
        or not math.isfinite(one_minute_load) or one_minute_load < 0:
        raise CapacityError("one_minute_load must be a finite nonnegative number")
    try:
        snapshot = validate_host_snapshot(host_snapshot)
    except PolicyError as exc:
        raise CapacityError(str(exc)) from exc

    memory_headroom_mib = max(
        0, memory_high_water_mib - int(snapshot["used_memory_mib"])
    )
    memory_slots = memory_headroom_mib // worker_memory_estimate_mib
    # Leave at least one logical CPU for the lead/controller and account for
    # already-runnable host load. Model subprocesses are mostly I/O-bound, so
    # this is a concurrency guard rather than a CPU allocation promise.
    cpu_slots = max(0, logical_cpu_count - max(1, math.ceil(one_minute_load)))
    pressure_reasons = [
        field
        for field in ("memory_pressure", "swap_active", "compressor_pressure")
        if snapshot[field]
    ]
    host_ceiling = min(code_ceiling, member_count, memory_slots, cpu_slots)
    if pressure_reasons:
        host_ceiling = 0
    effective = min(requested_concurrency, host_ceiling)
    reasons = list(pressure_reasons)
    if not pressure_reasons and memory_slots < 1:
        reasons.append("insufficient-memory-headroom")
    if not pressure_reasons and cpu_slots < 1:
        reasons.append("insufficient-cpu-headroom")
    return {
        "schema_version": CAPACITY_SCHEMA,
        "admitted": effective >= 1,
        "code_ceiling": code_ceiling,
        "host_ceiling": host_ceiling,
        "effective_concurrency": effective,
        "member_count": member_count,
        "requested_concurrency": requested_concurrency,
        "memory_slots": memory_slots,
        "cpu_slots": cpu_slots,
        "host_memory_mib": host_memory_mib,
        "memory_high_water_mib": memory_high_water_mib,
        "used_memory_mib": snapshot["used_memory_mib"],
        "worker_memory_estimate_mib": worker_memory_estimate_mib,
        "logical_cpu_count": logical_cpu_count,
        "one_minute_load": float(one_minute_load),
        "pressure_reasons": reasons,
    }
