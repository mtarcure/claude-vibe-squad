#!/usr/bin/env python3
"""One live, fail-closed host-admission policy for board work."""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass, replace
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
try:
    import board_process_truth as bpt
except ImportError:  # pragma: no cover - package-context fallback
    from . import board_process_truth as bpt  # type: ignore[no-redef]
GIB = 1024**3
MIN_SAMPLE_INTERVAL = 2.0
MAX_SAMPLE_INTERVAL = 5.0
MAX_SAMPLE_AGE = 10.0
SWAP_RATE_LIMITS = (64.0, 32.0)  # (swapins, swapouts), pages per second
FAMILY_TARGET = 4
LANE_FAMILY = {"claude": "anthropic", "codex": "openai", "gpt-codex": "openai",
               "gemini": "google", "grok": "xai", "kimi": "moonshot"}
MODEL_LANE = {"gpt-codex": "codex", "claude": "claude", "gemini": "gemini",
              "grok": "grok", "kimi": "kimi"}
@dataclass(frozen=True)
class WorkloadPolicy:
    p95_rss_bytes: int
    reserve_bytes: int
    pressure_floor_percent: float
    expected_processes: int
    calibrated: bool = True
WORKLOAD_POLICIES: Mapping[str, WorkloadPolicy] = {
    "cpu-light": WorkloadPolicy(512 * 1024**2, 1 * GIB, 15.0, 16),
    "repo-build-test": WorkloadPolicy(1 * GIB, 2 * GIB, 20.0, 64),
    "browser-media": WorkloadPolicy(2 * GIB, 3 * GIB, 25.0, 128),
    "security-untrusted": WorkloadPolicy(3 * GIB, 4 * GIB, 30.0, 128, False),
}
@dataclass(frozen=True)
class Candidate:
    task_id: str
    lane: str
    workload_class: str
    packet_path: Path
    packet_sha256: str
@dataclass(frozen=True)
class LiveAttempt:
    task_id: str
    lane: str
    workload_class: str
class HostStateError(RuntimeError):
    """Exact board process truth is missing, malformed, or unsettled."""
@dataclass(frozen=True)
class HostSnapshot:
    captured_at: float
    physical_bytes: int
    resident_bytes: int
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
@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    failed_clauses: tuple[int, ...]
    reasons: tuple[str, ...]
    snapshot_sha256: str
    candidate_vector_sha256: str = ""
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
    evidence: Sequence[object] = (),
) -> AdmissionDecision:
    canonical = json.dumps(
        [[asdict(snapshot) for snapshot in snapshots], list(evidence)],
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
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        for value in numeric
    ):
        return False
    return (
        snapshot.pressure_level in {"normal", "warn", "critical"}
        and snapshot.physical_bytes > 0
        and snapshot.swap_total_bytes > 0
        and snapshot.swap_free_bytes <= snapshot.swap_total_bytes
        and 0 <= snapshot.pressure_free_percent <= 100
        and snapshot.pid_limit > 0
    )
def _under_admission(
    *,
    candidates: Sequence[Candidate],
    live_attempts: Sequence[LiveAttempt],
    live_snapshot: Callable[[], tuple[HostSnapshot, HostSnapshot] | None],
    now: float | None = None,
) -> AdmissionDecision:
    """Evaluate one whole candidate vector; every unknown queues."""
    if not candidates or len({item.task_id for item in candidates}) != len(candidates):
        return _decision({1: "candidate vector is empty or has duplicate task ids"})
    evidence = [
        {key: str(value) if isinstance(value, Path) else value for key, value in asdict(item).items()}
        for item in (*live_attempts, *candidates)
    ]
    family_counts: dict[str, int] = {}
    policies: list[WorkloadPolicy] = []
    for item in (*live_attempts, *candidates):
        family = LANE_FAMILY.get(item.lane)
        policy = WORKLOAD_POLICIES.get(item.workload_class)
        valid = isinstance(item.task_id, str) and bpt.IDENTIFIER.fullmatch(item.task_id)
        if isinstance(item, Candidate):
            valid = valid and isinstance(item.packet_path, Path) and bpt.SHA256.fullmatch(item.packet_sha256)
        if family is None or policy is None or not valid:
            clause = 4 if policy is None else 1
            return _decision({clause: "candidate or live-attempt authority is invalid"}, evidence=evidence)
        family_counts[family] = family_counts.get(family, 0) + 1
        if isinstance(item, Candidate):
            policies.append(policy)
    over = sorted(name for name, count in family_counts.items() if count > FAMILY_TARGET)
    if over:
        return _decision({1: f"family target {FAMILY_TARGET} exceeded: {','.join(over)}"}, evidence=evidence)
    try:
        snapshots = live_snapshot()
    except Exception as exc:
        return _decision({2: f"telemetry collection failed: {exc}"}, evidence=evidence)
    if not snapshots or len(snapshots) != 2:
        return _decision({2: "two complete telemetry snapshots are required"}, evidence=evidence)
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
        return _decision({2: "telemetry schema or stable host identity is invalid"}, evidence=evidence)
    failed: dict[int, str] = {}
    current_time = time.monotonic() if now is None else now
    interval = second.captured_at - first.captured_at
    age = current_time - second.captured_at
    fresh = 0 <= age <= MAX_SAMPLE_AGE
    if not fresh or not MIN_SAMPLE_INTERVAL <= interval <= MAX_SAMPLE_INTERVAL:
        failed[2] = "telemetry is missing, stale, or outside the 2-5 second interval"
    # 2026-08-30 24x2s samples (16KiB pages): steady swapins <=5.980/s, swapouts=0; 64/s is
    # >10x noise and 31.9x below 2042.5/s load; direct-eviction swapouts use 32/s (pressure >=119.220/s).
    deltas = (second.swapins - first.swapins, second.swapouts - first.swapouts)
    rates = tuple(delta / interval for delta in deltas) if interval > 0 else (0.0, 0.0)
    if min(deltas) < 0 or any(rate > limit for rate, limit in zip(rates, SWAP_RATE_LIMITS)):
        failed[3] = "swap counters regressed" if min(deltas) < 0 else f"swap rates {rates[0]:.3f}/{rates[1]:.3f} exceed 64/32 pages/s"
    selected_reserve = max(policy.reserve_bytes for policy in policies)
    projected = (
        int(second.physical_bytes * (1.0 - second.pressure_free_percent / 100.0))
        + sum(int(policy.p95_rss_bytes * 1.25) for policy in policies)
        + selected_reserve
    )
    pressure_budget = int(second.physical_bytes * 0.85)
    if not all(policy.calibrated for policy in policies) or projected > pressure_budget:
        failed[4] = "workload is uncalibrated or projected resident use exceeds budget"
    # Clause 6 absorbs the former clause 5: that clause compared free space in the
    # CURRENT swap file against max(1 GiB, 10% of swap_total), but macOS swap is
    # dynamic (grown on demand from free disk), so it drifted with uptime instead of
    # measuring capacity. Real pressure is here; growth is clause 3; disk is clause 7.
    if (
        second.pressure_level.lower() == "critical"
        or second.pressure_free_percent < max(policy.pressure_floor_percent for policy in policies)
    ):
        failed[6] = "memory pressure is critical or below the class threshold"
    process_ceiling = int(second.pid_limit * 0.80)
    disk_floor = selected_reserve + GIB
    if (
        second.free_disk_bytes < disk_floor
        or (
            second.process_count
            + sum(policy.expected_processes for policy in policies)
            >= process_ceiling
        )
        or second.load_average_1m > max(float(os.cpu_count() or 1) * 2.0, 4.0)
        or second.runnable_processes > max((os.cpu_count() or 1) * 4, 16)
    ):
        failed[7] = "disk, PID, load, or runnable-process limit failed"
    return _decision(failed, snapshots, evidence)
def discover_live_attempts(repo_root: Path) -> tuple[LiveAttempt, ...]:
    """Count only exact live V2 descriptors without a matching terminal receipt."""
    board = Path(repo_root) / "_state" / "board-dispatch"
    if not board.exists():
        return ()
    if board.is_symlink() or not board.is_dir():
        raise HostStateError("board state root is not a real directory")
    live: list[LiveAttempt] = []
    for path in sorted(board.glob("*.dispatch.json")):
        descriptor = bpt.load_json(path)
        if isinstance(descriptor, dict) and descriptor.get("schema") == bpt.DESCRIPTOR_V1:
            continue
        if error := bpt.descriptor_error(path, descriptor, require_v2=True):
            raise HostStateError(f"{path.name}: {error}")
        if os.path.lexists(receipt_path := Path(descriptor["receipt_path"])):
            if bpt.terminal_outcome(bpt.load_json(receipt_path), descriptor):
                continue
            raise HostStateError(f"{path.name}: receipt is not exactly fenced")
        context = bpt.load_json(descriptor["context_path"])
        if not bpt.context_matches(descriptor, context):
            raise HostStateError(f"{path.name}: context identity mismatch")
        truth = bpt.process_truth(path, descriptor)
        if truth.get("state") != "live":
            raise HostStateError(f"{path.name}: unresolved {truth.get('reason', 'process truth')}")
        authority = context.get("authority")
        lane, workload = authority.get("lane"), authority.get("workload_class")
        if lane not in LANE_FAMILY or workload not in WORKLOAD_POLICIES:
            raise HostStateError(f"{path.name}: lane or workload authority is invalid")
        live.append(LiveAttempt(descriptor["task_id"], lane, workload))
    return tuple(live)
def candidate_from_task(
    path: Path, repo_root: Path, expected_task_id: str, expected_sha256: str
) -> Candidate:
    """Bind admission identity to the exact already-validated packet bytes."""
    packet = Path(path)
    if packet.is_symlink() or not packet.is_file():
        raise HostStateError(f"candidate packet is missing or symlinked: {packet}")
    try:
        from dispatch_context_builder import _parse_task_text, _unquote, dispatcher_workload_class
    except ImportError:  # pragma: no cover - package-context fallback
        from .dispatch_context_builder import (  # type: ignore[no-redef]
            _parse_task_text, _unquote, dispatcher_workload_class)
    raw = packet.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if bpt.IDENTIFIER.fullmatch(expected_task_id) is None \
            or bpt.SHA256.fullmatch(expected_sha256) is None \
            or digest != expected_sha256:
        raise HostStateError(f"candidate expected identity or hash mismatched: {packet}")
    try:
        fields, _body = _parse_task_text(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HostStateError(f"candidate packet is not UTF-8: {packet}") from exc
    task_id = _unquote(fields.get("id", ""))
    lane = MODEL_LANE.get(_unquote(fields.get("to_model", "")))
    workload = dispatcher_workload_class(Path(repo_root), _unquote(fields.get("specialist", "")))
    if task_id != expected_task_id or lane is None:
        raise HostStateError(f"candidate packet identity is invalid: {packet}")
    return Candidate(task_id, lane, workload, packet.resolve(), digest)
def _candidate_vector_sha256(candidates: Sequence[Candidate]) -> str:
    digest = hashlib.sha256()
    for item in candidates:
        for value in (str(item.packet_path), item.task_id, item.packet_sha256):
            digest.update(value.encode("utf-8") + b"\0")
    return digest.hexdigest()
def _binding_changed(candidates: Sequence[Candidate]) -> str | None:
    for item in candidates:
        try:
            changed = item.packet_path.is_symlink() or not item.packet_path.is_file() \
                or hashlib.sha256(item.packet_path.read_bytes()).hexdigest() != item.packet_sha256
        except OSError:
            changed = True
        if changed:
            return item.task_id
    return None
def admit(
    *,
    repo_root: Path,
    candidates: Sequence[Candidate],
    snapshots: tuple[HostSnapshot, HostSnapshot] | None = None,
    now: float | None = None,
) -> AdmissionDecision:
    """Own the board-truth scan and host sampling behind the one public seam."""
    try:
        if changed := _binding_changed(candidates):
            raise HostStateError(f"candidate packet binding changed: {changed}")
        live = discover_live_attempts(repo_root)
    except (HostStateError, OSError, ValueError) as exc:
        return _decision({1: f"authoritative board state failed closed: {exc}"})
    source = (
        (lambda: snapshots)
        if snapshots is not None
        else (lambda: collect_live_snapshots(task_path=Path(repo_root)))
    )
    decision = _under_admission(
        candidates=candidates,
        live_attempts=live,
        live_snapshot=source,
        now=now,
    )
    if decision.admitted and (changed := _binding_changed(candidates)):
        return _decision({1: f"candidate packet changed during telemetry: {changed}"})
    return replace(decision, candidate_vector_sha256=_candidate_vector_sha256(candidates))
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
    free_disk = shutil.disk_usage(task_path).free
    return HostSnapshot(
        captured_at=time.monotonic(),
        physical_bytes=physical,
        resident_bytes=resident,
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
    )

def collect_live_snapshots(
    *,
    task_path: Path,
    interval: float = 2.0,
) -> tuple[HostSnapshot, HostSnapshot]:
    if not MIN_SAMPLE_INTERVAL <= interval <= MAX_SAMPLE_INTERVAL:
        raise ValueError("sample interval must be 2-5 seconds")
    first = collect_snapshot(task_path=task_path)
    time.sleep(interval)
    second = collect_snapshot(task_path=task_path)
    return first, second

def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate", nargs=3, action="append", required=True)
    parser.add_argument("--vector-sha256", required=True)
    args = parser.parse_args(list(argv))
    try:
        candidates = tuple(
            candidate_from_task(Path(path), args.repo_root, task_id, sha256)
            for path, task_id, sha256 in args.candidate
        )
        if _candidate_vector_sha256(candidates) != args.vector_sha256:
            raise HostStateError("candidate vector binding mismatch")
    except (HostStateError, OSError, ValueError) as exc:
        decision = _decision({1: f"candidate parsing failed closed: {exc}"})
    else:
        decision = admit(repo_root=args.repo_root, candidates=candidates)
    print(decision.to_json())
    return 0 if decision.admitted else 75


if __name__ == "__main__":
    raise SystemExit(_main(os.sys.argv[1:]))
