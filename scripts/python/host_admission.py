#!/usr/bin/env python3
"""Live, fail-closed host admission for V2 board-supervised work."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable, Mapping, Sequence


GIB = 1024**3
MIN_SAMPLE_INTERVAL = 2.0
MAX_SAMPLE_INTERVAL = 5.0
MAX_SAMPLE_AGE = 10.0


@dataclass(frozen=True)
class WorkloadPolicy:
    p50_rss_bytes: int
    p95_rss_bytes: int
    reserve_bytes: int
    pressure_floor_percent: float
    expected_processes: int
    calibrated: bool = True


WORKLOAD_POLICIES: Mapping[str, WorkloadPolicy] = {
    "light-text": WorkloadPolicy(400 * 1024**2, 512 * 1024**2, 1 * GIB, 15.0, 16),
    "repo-build-test": WorkloadPolicy(768 * 1024**2, 1 * GIB, 2 * GIB, 20.0, 64),
    "browser-media": WorkloadPolicy(1 * GIB, 2 * GIB, 3 * GIB, 25.0, 128),
    "security-untrusted": WorkloadPolicy(2 * GIB, 3 * GIB, 4 * GIB, 30.0, 128, False),
}


@dataclass(frozen=True)
class HostSnapshot:
    captured_at: float
    physical_bytes: int
    resident_bytes: int
    raw_free_bytes: int
    active_bytes: int
    inactive_bytes: int
    wired_bytes: int
    compressed_bytes: int
    purgeable_bytes: int
    supervisor_rss_bytes: int
    external_baseline_rss_bytes: int
    pressure_free_percent: float
    pressure_level: str
    swap_total_bytes: int
    swap_free_bytes: int
    swapins: int
    pageouts: int
    swapouts: int
    compressions: int
    load_average_1m: float
    runnable_processes: int
    free_disk_bytes: int
    process_count: int
    pid_limit: int
    active_workers: int
    priority_state_known: bool
    higher_priority_queued: bool
    broker_port_available: bool
    provider_budget_available: bool


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    failed_clauses: tuple[int, ...]
    reasons: tuple[str, ...]
    snapshot_sha256: str
    backoff_seconds: int = 5

    @property
    def action(self) -> str:
        return "admit" if self.admitted else "queue"

    def to_json(self) -> str:
        payload = asdict(self)
        payload["action"] = self.action
        return json.dumps(payload, sort_keys=True)


def _decision(
    failed: Mapping[int, str],
    snapshots: Sequence[HostSnapshot] = (),
) -> AdmissionDecision:
    canonical = json.dumps(
        [asdict(snapshot) for snapshot in snapshots],
        sort_keys=True,
        separators=(",", ":"),
    )
    return AdmissionDecision(
        admitted=not failed,
        failed_clauses=tuple(sorted(failed)),
        reasons=tuple(f"clause-{number}: {failed[number]}" for number in sorted(failed)),
        snapshot_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _snapshot_schema_valid(snapshot: HostSnapshot) -> bool:
    numeric = (
        snapshot.captured_at,
        snapshot.physical_bytes,
        snapshot.resident_bytes,
        snapshot.raw_free_bytes,
        snapshot.active_bytes,
        snapshot.inactive_bytes,
        snapshot.wired_bytes,
        snapshot.compressed_bytes,
        snapshot.purgeable_bytes,
        snapshot.supervisor_rss_bytes,
        snapshot.external_baseline_rss_bytes,
        snapshot.pressure_free_percent,
        snapshot.swap_total_bytes,
        snapshot.swap_free_bytes,
        snapshot.swapins,
        snapshot.pageouts,
        snapshot.swapouts,
        snapshot.compressions,
        snapshot.load_average_1m,
        snapshot.runnable_processes,
        snapshot.free_disk_bytes,
        snapshot.process_count,
        snapshot.pid_limit,
        snapshot.active_workers,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        for value in numeric
    ):
        return False
    booleans = (
        snapshot.higher_priority_queued,
        snapshot.priority_state_known,
        snapshot.broker_port_available,
        snapshot.provider_budget_available,
    )
    return (
        all(isinstance(value, bool) for value in booleans)
        and snapshot.priority_state_known
        and snapshot.pressure_level in {"normal", "warn", "critical"}
        and snapshot.physical_bytes > 0
        and snapshot.swap_total_bytes > 0
        and snapshot.swap_free_bytes <= snapshot.swap_total_bytes
        and 0 <= snapshot.pressure_free_percent <= 100
        and snapshot.pid_limit > 0
    )


def under_admission(
    *,
    hard_max: int = 8,
    requested_workers: int = 1,
    live_snapshot: Callable[[], tuple[HostSnapshot, HostSnapshot] | None],
    workload_class: str,
    reserve: int | None = None,
    now: float | None = None,
) -> AdmissionDecision:
    """Evaluate the stable seven-clause predicate; every unknown queues."""

    if isinstance(hard_max, bool) or not isinstance(hard_max, int) or hard_max <= 0 or hard_max > 12:
        return _decision({1: "hard_max must be an integer in 1..12"})
    if (
        isinstance(requested_workers, bool)
        or not isinstance(requested_workers, int)
        or requested_workers <= 0
        or requested_workers > hard_max
    ):
        return _decision({1: "requested_workers must be an integer in 1..hard_max"})
    policy = WORKLOAD_POLICIES.get(workload_class)
    if policy is None:
        return _decision({4: f"unknown workload class {workload_class!r}"})
    try:
        snapshots = live_snapshot()
    except Exception as exc:
        return _decision({2: f"telemetry collection failed: {exc}"})
    if not snapshots or len(snapshots) != 2:
        return _decision({2: "two complete telemetry snapshots are required"})
    first, second = snapshots
    if (
        not isinstance(first, HostSnapshot)
        or not isinstance(second, HostSnapshot)
        or not _snapshot_schema_valid(first)
        or not _snapshot_schema_valid(second)
        or first.physical_bytes != second.physical_bytes
        or first.swap_total_bytes != second.swap_total_bytes
        or first.pid_limit != second.pid_limit
    ):
        return _decision({2: "telemetry schema or stable host identity is invalid"})
    failed: dict[int, str] = {}
    current_time = time.monotonic() if now is None else now

    if (
        second.active_workers + requested_workers > hard_max
        or second.higher_priority_queued
    ):
        failed[1] = "capacity reached or higher-priority work is queued"

    interval = second.captured_at - first.captured_at
    age = current_time - second.captured_at
    fresh = 0 <= age <= MAX_SAMPLE_AGE
    if not fresh or not MIN_SAMPLE_INTERVAL <= interval <= MAX_SAMPLE_INTERVAL:
        failed[2] = "telemetry is missing, stale, or outside the 2-5 second interval"

    if (
        second.swapins > first.swapins
        or second.pageouts > first.pageouts
        or second.swapouts > first.swapouts
        or second.compressions > first.compressions
    ):
        failed[3] = "swapin, pageout, swapout, or compression growth is unsafe"

    selected_reserve = policy.reserve_bytes if reserve is None else reserve
    if isinstance(selected_reserve, bool) or not isinstance(selected_reserve, int) or selected_reserve < 0:
        failed[4] = "reserve must be a non-negative integer"
        selected_reserve = policy.reserve_bytes
    selected_reserve = max(selected_reserve, policy.reserve_bytes)
    projected = (
        second.resident_bytes
        + int(policy.p95_rss_bytes * 1.25 * requested_workers)
        + selected_reserve
    )
    pressure_budget = int(second.physical_bytes * 0.85)
    if not policy.calibrated or projected > pressure_budget:
        failed[4] = "workload is uncalibrated or projected resident use exceeds budget"

    projected_swap_use = max(0, projected - pressure_budget)
    free_swap_after = max(0, second.swap_free_bytes - projected_swap_use)
    minimum_swap = max(GIB, int(second.swap_total_bytes * 0.10))
    if free_swap_after < minimum_swap:
        failed[5] = "projected free swap is below max(1 GiB, 10% configured swap)"

    if (
        second.pressure_level.lower() == "critical"
        or second.pressure_free_percent < policy.pressure_floor_percent
    ):
        failed[6] = "memory pressure is critical or below the class threshold"

    process_ceiling = int(second.pid_limit * 0.80)
    disk_floor = selected_reserve + GIB
    if (
        second.free_disk_bytes < disk_floor
        or (
            second.process_count
            + policy.expected_processes * requested_workers
            >= process_ceiling
        )
        or second.load_average_1m > max(float(os.cpu_count() or 1) * 2.0, 4.0)
        or second.runnable_processes > max((os.cpu_count() or 1) * 4, 16)
        or not second.broker_port_available
        or not second.provider_budget_available
    ):
        failed[7] = "disk, PID, broker-port, or provider-budget limit failed"
    return _decision(failed, snapshots)


def _run(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        timeout=5,
        check=False,
        close_fds=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"telemetry command failed: {command[0]}: {detail}")
    return completed.stdout


def _parse_bytes(value: str, unit: str) -> int:
    scale = {"K": 1024, "M": 1024**2, "G": GIB}[unit.upper()]
    return int(float(value) * scale)


def parse_vm_stat(output: str) -> dict[str, int]:
    page_match = re.search(r"page size of (\d+) bytes", output)
    if not page_match:
        raise ValueError("vm_stat page size missing")
    page_size = int(page_match.group(1))
    fields: dict[str, int] = {"page_size": page_size}
    aliases = {
        "Pages free": "free",
        "Pages active": "active",
        "Pages inactive": "inactive",
        "Pages wired down": "wired",
        "Pages purgeable": "purgeable",
        "Pages occupied by compressor": "compressed",
        "Swapins": "swapins",
        "Pageouts": "pageouts",
        "Swapouts": "swapouts",
        "Compressions": "compressions",
    }
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        target = aliases.get(key.strip())
        if target:
            match = re.search(r"(\d+)", raw_value.replace(".", ""))
            if match:
                fields[target] = int(match.group(1))
    required = set(aliases.values())
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"vm_stat fields missing: {sorted(missing)}")
    return fields


def parse_memory_pressure(output: str) -> tuple[str, float]:
    match = re.search(r"System-wide memory free percentage:\s*(\d+(?:\.\d+)?)%", output)
    if not match:
        raise ValueError("memory_pressure percentage missing")
    lowered = output.lower()
    level = "critical" if "critical" in lowered else "warn" if "warn" in lowered else "normal"
    return level, float(match.group(1))


def parse_swapusage(output: str) -> tuple[int, int]:
    total = re.search(r"total\s*=\s*([0-9.]+)([KMG])", output)
    free = re.search(r"free\s*=\s*([0-9.]+)([KMG])", output)
    if not total or not free:
        raise ValueError("swapusage total/free missing")
    return _parse_bytes(total.group(1), total.group(2)), _parse_bytes(free.group(1), free.group(2))


def collect_snapshot(
    *,
    task_path: Path,
    active_workers: int,
    priority_state_known: bool,
    higher_priority_queued: bool,
    broker_port_available: bool,
    provider_budget_available: bool,
) -> HostSnapshot:
    vm = parse_vm_stat(_run(("/usr/bin/vm_stat",)))
    pressure_level, pressure_free = parse_memory_pressure(_run(("/usr/bin/memory_pressure", "-Q")))
    swap_total, swap_free = parse_swapusage(_run(("/usr/sbin/sysctl", "vm.swapusage")))
    physical = int(_run(("/usr/sbin/sysctl", "-n", "hw.memsize")).strip())
    pid_limit = int(_run(("/usr/sbin/sysctl", "-n", "kern.maxproc")).strip())
    ps_lines = [line for line in _run(("/bin/ps", "-axo", "rss=")).splitlines() if line.strip()]
    process_count = len(ps_lines)
    process_states = [line.strip() for line in _run(("/bin/ps", "-axo", "state=")).splitlines() if line.strip()]
    runnable_processes = sum(state.startswith("R") for state in process_states)
    load_output = _run(("/usr/sbin/sysctl", "-n", "vm.loadavg"))
    load_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", load_output)
    if not load_match:
        raise RuntimeError("vm.loadavg parse failed")
    available_pages = vm["free"] + vm["inactive"] + vm["purgeable"]
    resident = max(0, physical - available_pages * vm["page_size"])
    supervisor_rss = int(_run(("/bin/ps", "-o", "rss=", "-p", str(os.getpid()))).strip()) * 1024
    free_disk = shutil.disk_usage(task_path).free
    page_size = vm["page_size"]
    return HostSnapshot(
        captured_at=time.monotonic(),
        physical_bytes=physical,
        resident_bytes=resident,
        raw_free_bytes=vm["free"] * page_size,
        active_bytes=vm["active"] * page_size,
        inactive_bytes=vm["inactive"] * page_size,
        wired_bytes=vm["wired"] * page_size,
        compressed_bytes=vm["compressed"] * page_size,
        purgeable_bytes=vm["purgeable"] * page_size,
        supervisor_rss_bytes=supervisor_rss,
        external_baseline_rss_bytes=max(0, resident - supervisor_rss),
        pressure_free_percent=pressure_free,
        pressure_level=pressure_level,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        swapins=vm["swapins"],
        pageouts=vm["pageouts"],
        swapouts=vm["swapouts"],
        compressions=vm["compressions"],
        load_average_1m=float(load_match.group(1)),
        runnable_processes=runnable_processes,
        free_disk_bytes=free_disk,
        process_count=process_count,
        pid_limit=pid_limit,
        active_workers=active_workers,
        priority_state_known=priority_state_known,
        higher_priority_queued=higher_priority_queued,
        broker_port_available=broker_port_available,
        provider_budget_available=provider_budget_available,
    )


def collect_live_snapshots(
    *,
    task_path: Path,
    interval: float = 2.0,
    active_workers: int = -1,
    priority_state_known: bool = False,
    higher_priority_queued: bool = False,
    broker_port_available: bool = False,
    provider_budget_available: bool = False,
) -> tuple[HostSnapshot, HostSnapshot]:
    if not MIN_SAMPLE_INTERVAL <= interval <= MAX_SAMPLE_INTERVAL:
        raise ValueError("sample interval must be 2-5 seconds")
    kwargs = {
        "active_workers": active_workers,
        "priority_state_known": priority_state_known,
        "task_path": task_path,
        "higher_priority_queued": higher_priority_queued,
        "broker_port_available": broker_port_available,
        "provider_budget_available": provider_budget_available,
    }
    first = collect_snapshot(**kwargs)
    time.sleep(interval)
    second = collect_snapshot(**kwargs)
    return first, second


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--workload-class", choices=tuple(WORKLOAD_POLICIES), required=True)
    parser.add_argument("--hard-max", type=int, default=8)
    parser.add_argument("--requested-workers", type=int, default=1)
    parser.add_argument("--task-path", type=Path, required=True)
    parser.add_argument("--active-workers", type=int)
    parser.add_argument("--priority-state-known", action="store_true")
    parser.add_argument("--higher-priority-queued", action="store_true")
    parser.add_argument("--broker-port-available", action="store_true")
    parser.add_argument("--provider-budget-available", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args(list(argv))
    decision = under_admission(
        hard_max=args.hard_max,
        requested_workers=args.requested_workers,
        workload_class=args.workload_class,
        live_snapshot=lambda: collect_live_snapshots(
            interval=args.interval,
            task_path=args.task_path,
            active_workers=-1 if args.active_workers is None else args.active_workers,
            priority_state_known=args.priority_state_known,
            higher_priority_queued=args.higher_priority_queued,
            broker_port_available=args.broker_port_available,
            provider_budget_available=args.provider_budget_available,
        ),
    )
    print(decision.to_json())
    return 0 if decision.admitted else 75


if __name__ == "__main__":
    raise SystemExit(_main(os.sys.argv[1:]))
