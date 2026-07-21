#!/usr/bin/env python3
"""Default-off worker scan consumer and always-on reconcile backstop."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from typing import Callable

from subswarm_capacity import compute_subswarm_capacity, subagent_code_ceiling
from swarm_diff import SwarmDiffError, validate_orchestration_directive
from worker_pool_policy import LANES, load_worker_pool_policy


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
POLICY_PATH = VAULT_ROOT / "shared/worker-pool-policy.md"
RUNTIME_STATE = STATE_DIR / "worker-pool-runtime.json"


def _run_text(command: list[str], timeout: float = 10) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout


def _mib(value: int) -> int:
    return max(0, value // (1024 * 1024))


def sample_macos_host(
    fallback_ceiling_mib: int,
    high_water_mib: int,
    *,
    run_text: Callable[[list[str], float], str] = _run_text,
) -> dict[str, object]:
    """Return the strict scheduler snapshot from live macOS counters.

    Sampling failure is fail-closed: the documented static host ceiling is
    reported as used and pressure is asserted, so no new lease is admitted.
    """
    try:
        total_bytes = int(run_text(["/usr/sbin/sysctl", "-n", "hw.memsize"], 5).strip())
        vm = run_text(["/usr/bin/vm_stat"], 5)
        pressure = run_text(["/usr/bin/memory_pressure", "-Q"], 5)
        swap = run_text(["/usr/sbin/sysctl", "-n", "vm.swapusage"], 5)
        page_match = re.search(r"page size of (\d+) bytes", vm)
        if not page_match:
            raise ValueError("vm_stat page size missing")
        page_size = int(page_match.group(1))
        pages: dict[str, int] = {}
        for label, raw in re.findall(r"^([^:]+):\s+([0-9]+)\.\s*$", vm, re.MULTILINE):
            pages[label.strip()] = int(raw)
        available_pages = sum(
            pages.get(label, 0)
            for label in (
                "Pages free", "Pages inactive", "Pages speculative",
                "Pages purgeable",
            )
        )
        total_mib = _mib(total_bytes)
        available_mib = _mib(available_pages * page_size)
        used_mib = max(0, total_mib - available_mib)
        compressed_mib = _mib(
            pages.get("Pages occupied by compressor", 0) * page_size
        )
        pressure_match = re.search(r"free percentage:\s*(\d+)%", pressure)
        if not pressure_match:
            raise ValueError("memory_pressure percentage missing")
        free_percent = int(pressure_match.group(1))
        swap_match = re.search(r"used\s*=\s*([0-9.]+)M", swap)
        if not swap_match:
            raise ValueError("swap usage missing")
        swap_used_mib = float(swap_match.group(1))
        return {
            "used_memory_mib": used_mib,
            "memory_pressure": used_mib >= high_water_mib or free_percent < 10,
            "swap_active": swap_used_mib > 0,
            "compressor_pressure": compressed_mib >= max(1024, total_mib // 4),
        }
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {
            "used_memory_mib": fallback_ceiling_mib,
            "memory_pressure": True,
            "swap_active": True,
            "compressor_pressure": True,
        }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _exclusive_json(path: Path, value: object) -> None:
    """Create one immutable scheduler output; never clobber an existing replica."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def live_subswarm_capacity(
    directive: dict[str, object],
    *,
    host_snapshot: dict[str, object] | None = None,
    host_memory_mib: int | None = None,
    memory_high_water_mib: int | None = None,
    worker_memory_estimate_mib: int | None = None,
    logical_cpu_count: int | None = None,
    one_minute_load: float | None = None,
) -> dict[str, object]:
    """Bind a sealed directive to a fresh fail-closed host admission snapshot."""

    lane = str(directive["lane"])
    policy = load_worker_pool_policy(POLICY_PATH)
    host_memory_mib = policy.host_memory_mib if host_memory_mib is None else host_memory_mib
    memory_high_water_mib = (
        policy.memory_high_water_mib
        if memory_high_water_mib is None
        else memory_high_water_mib
    )
    worker_memory_estimate_mib = (
        policy.lanes[lane].worker_memory_estimate_mib
        if worker_memory_estimate_mib is None
        else worker_memory_estimate_mib
    )
    if host_snapshot is None:
        host_snapshot = sample_macos_host(host_memory_mib, memory_high_water_mib)
    logical_cpu_count = os.cpu_count() if logical_cpu_count is None else logical_cpu_count
    if not logical_cpu_count:
        logical_cpu_count = 1
    if one_minute_load is None:
        try:
            one_minute_load = os.getloadavg()[0]
        except OSError:
            # Fail closed through the CPU formula when load sampling is absent.
            one_minute_load = float(logical_cpu_count)
    return compute_subswarm_capacity(
        code_ceiling=subagent_code_ceiling(),
        member_count=len(directive["members"]),
        requested_concurrency=int(directive["max_concurrency"]),
        host_snapshot=host_snapshot,
        host_memory_mib=host_memory_mib,
        memory_high_water_mib=memory_high_water_mib,
        worker_memory_estimate_mib=worker_memory_estimate_mib,
        logical_cpu_count=logical_cpu_count,
        one_minute_load=one_minute_load,
    )


def _run_subswarm_member(
    member: dict[str, object],
    command: list[str],
    *,
    repo_root: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    started_ns = time.time_ns()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env={
                **os.environ,
                "SQUAD_SUBSWARM_MEMBER_ID": str(member["member_id"]),
                "SQUAD_SUBSWARM_OUTPUT_PATH": str(member["output_path"]),
                "SQUAD_SUBSWARM_OBJECTIVE_SHA256": str(member["objective_sha256"]),
            },
        )
        status = "complete" if result.returncode == 0 else "failed"
        returncode: int | None = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timed_out"
        returncode = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
    finished_ns = time.time_ns()
    return {
        "schema_version": "subswarm-replica-output/v1",
        "member_id": member["member_id"],
        "lane": member["lane"],
        "replica_index": member["replica_index"],
        "objective_sha256": member["objective_sha256"],
        "output_path": member["output_path"],
        "status": status,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "started_ns": started_ns,
        "finished_ns": finished_ns,
    }


def run_subswarm_directive(
    directive_value: object,
    command_map: object,
    *,
    evidence_output: Path,
    repo_root: Path = VAULT_ROOT,
    host_snapshot: dict[str, object] | None = None,
    host_memory_mib: int | None = None,
    memory_high_water_mib: int | None = None,
    worker_memory_estimate_mib: int | None = None,
    logical_cpu_count: int | None = None,
    one_minute_load: float | None = None,
    timeout_seconds: float = 300,
) -> dict[str, object]:
    """Run a sealed mixed DAG with live host admission and isolated outputs."""

    directive = validate_orchestration_directive(directive_value)
    if not isinstance(command_map, dict) or set(command_map) != {
        member["member_id"] for member in directive["members"]
    }:
        raise RuntimeError("command map must name every directive member exactly once")
    normalized_commands: dict[str, list[str]] = {}
    for member_id, command in command_map.items():
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item for item in command
        ):
            raise RuntimeError(f"command for {member_id} must be a nonempty argv list")
        normalized_commands[member_id] = list(command)
    if timeout_seconds <= 0:
        raise RuntimeError("timeout_seconds must be positive")

    capacity = live_subswarm_capacity(
        directive,
        host_snapshot=host_snapshot,
        host_memory_mib=host_memory_mib,
        memory_high_water_mib=memory_high_water_mib,
        worker_memory_estimate_mib=worker_memory_estimate_mib,
        logical_cpu_count=logical_cpu_count,
        one_minute_load=one_minute_load,
    )
    if not capacity["admitted"]:
        raise RuntimeError(
            "subswarm host admission denied: "
            + ",".join(str(item) for item in capacity["pressure_reasons"])
        )
    concurrency = int(capacity["effective_concurrency"])
    by_id = {str(member["member_id"]): member for member in directive["members"]}
    pending = set(by_id)
    completed: dict[str, dict[str, object]] = {}
    running: dict[Future[dict[str, object]], str] = {}
    peak_concurrency = 0
    repo_root = repo_root.resolve()

    def persist(result: dict[str, object]) -> None:
        relative = Path(str(result["output_path"]))
        target = (repo_root / relative).resolve()
        if repo_root not in target.parents:
            raise RuntimeError(f"replica output escaped repository: {relative}")
        _exclusive_json(target, result)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while pending or running:
            progressed = False
            for member_id in sorted(tuple(pending)):
                if len(running) >= concurrency:
                    break
                member = by_id[member_id]
                dependencies = list(member["depends_on"])
                if not all(dependency in completed for dependency in dependencies):
                    continue
                if any(completed[dependency]["status"] != "complete" for dependency in dependencies):
                    now = time.time_ns()
                    blocked = {
                        "schema_version": "subswarm-replica-output/v1",
                        "member_id": member["member_id"],
                        "lane": member["lane"],
                        "replica_index": member["replica_index"],
                        "objective_sha256": member["objective_sha256"],
                        "output_path": member["output_path"],
                        "status": "blocked",
                        "returncode": None,
                        "stdout": "",
                        "stderr": "dependency_failed",
                        "started_at": None,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "started_ns": None,
                        "finished_ns": now,
                    }
                    persist(blocked)
                    completed[member_id] = blocked
                    pending.remove(member_id)
                    progressed = True
                    continue
                future = executor.submit(
                    _run_subswarm_member,
                    member,
                    normalized_commands[member_id],
                    repo_root=repo_root,
                    timeout_seconds=timeout_seconds,
                )
                running[future] = member_id
                pending.remove(member_id)
                peak_concurrency = max(peak_concurrency, len(running))
                progressed = True
            if running:
                finished, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in finished:
                    member_id = running.pop(future)
                    result = future.result()
                    persist(result)
                    completed[member_id] = result
                    progressed = True
            if pending and not running and not progressed:
                raise RuntimeError("subswarm DAG scheduler made no progress")

    evidence = {
        "schema_version": "subswarm-runtime-evidence/v1",
        "directive_sha256": directive["directive_sha256"],
        "lane": directive["lane"],
        "member_count": len(directive["members"]),
        "peak_concurrency": peak_concurrency,
        "capacity": capacity,
        "members": [completed[member_id] for member_id in sorted(completed)],
    }
    _exclusive_json(evidence_output, evidence)
    return evidence


def _worker_epochs() -> dict[str, str]:
    try:
        raw = json.loads(RUNTIME_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    epochs = raw.get("worker_epochs") if isinstance(raw, dict) else None
    if not isinstance(epochs, dict) or set(epochs) != set(LANES) \
        or any(not isinstance(value, str) or not value for value in epochs.values()):
        epochs = {lane: f"runtime-{uuid.uuid4().hex}" for lane in LANES}
        _atomic_json(RUNTIME_STATE, {"worker_epochs": epochs})
    return epochs


def _tmux_windows() -> set[str]:
    tmux = os.environ.get("TMUX_BIN", "tmux")
    session = os.environ.get("SQUAD_SESSION", "squad")
    output = _run_text([tmux, "list-windows", "-t", session, "-F", "#{window_name}"], 5)
    return {line.strip() for line in output.splitlines() if line.strip()}


def live_workers(now: datetime) -> list[dict[str, object]]:
    windows = _tmux_windows()
    epochs = _worker_epochs()
    return [
        {
            "worker_id": f"{lane}-lead",
            "worker_epoch": epochs[lane],
            "lane": lane,
            "heartbeat_observed_at": now.isoformat(),
            "available": True,
            "lead_id": f"{lane}-lead",
            "subagent_count": 0,
        }
        for lane in LANES if lane in windows
    ]


def _json_env(name: str, default: object) -> object:
    raw = os.environ.get(name)
    return default if raw is None else json.loads(raw)


def _task_path(task_id: str) -> Path:
    matches = sorted(
        path
        for state in ("inbox", "active")
        for path in (VAULT_ROOT / "departments").glob(f"*/{state}/{task_id}.md")
    )
    if len(matches) != 1:
        raise RuntimeError(f"expected one live packet for {task_id}, found {len(matches)}")
    return matches[0]


def deliver_fence(fence: dict[str, object]) -> None:
    """Deliver a committed worker fence directly; never reauthorize legacy delivery."""
    task_id = str(fence["task_id"])
    lane = str(fence["delivery_lane"])
    packet = _task_path(task_id)
    claim = (
        f"bash '{VAULT_ROOT}/bin/claim-task.sh' '{task_id}' "
        f"'{fence['delivery_attempt_id']}' '{fence['delivery_worker_id']}' "
        f"'{fence['worker_epoch']}' '{fence['lease_generation']}' '{lane}'"
    )
    message = (
        f"WORKER ASSIGNMENT: first run {claim}. If rejected, STOP. Then open and process "
        f"this exact task packet: {packet}. Complete its packet contract. Do not create "
        "another Chrono/mailbox task unless explicitly authorized by the packet."
    )
    tmux = os.environ.get("TMUX_BIN", "tmux")
    session = os.environ.get("SQUAD_SESSION", "squad")
    subprocess.run([tmux, "send-keys", "-l", "-t", f"{session}:{lane}", message], check=True)
    subprocess.run([tmux, "send-keys", "-t", f"{session}:{lane}", "Enter"], check=True)


def scan_once(now: datetime | None = None) -> dict[str, object]:
    if os.environ.get("SQUAD_WORKER_POOL_ENABLED", "0") != "1":
        return {"enabled": False, "delivered": []}
    if os.environ.get("SQUAD_WORKER_POOL_GUARDS_ENABLED", "0") != "1":
        raise RuntimeError("worker runtime requires SQUAD_WORKER_POOL_GUARDS_ENABLED=1")
    now = now or datetime.now(timezone.utc)
    policy = load_worker_pool_policy(POLICY_PATH)
    if os.environ.get("SQUAD_WORKER_POOL_POLICY_REVIEW_STATE") != "approved" \
        or os.environ.get("SQUAD_WORKER_POOL_POLICY_APPROVED_SHA256") != policy.policy_sha256:
        raise RuntimeError("worker runtime requires the approved reviewed policy hash")
    host = sample_macos_host(policy.host_memory_mib, policy.memory_high_water_mib)
    states = _json_env("SQUAD_PROVIDER_STATES_JSON", {lane: "ready" for lane in LANES})
    usage = _json_env(
        "SQUAD_PROVIDER_USAGE_JSON",
        {
            lane: {"spent_microusd": 0, "active_requests": 0, "requests_last_minute": 0}
            for lane in LANES
        },
    )
    command = [
        sys.executable, str(VAULT_ROOT / "scripts/python/registry_reconciler.py"),
        "--schedule-workers-json", json.dumps(live_workers(now)),
        "--worker-policy", str(POLICY_PATH),
        "--host-snapshot-json", json.dumps(host),
        "--provider-states-json", json.dumps(states),
        "--provider-usage-json", json.dumps(usage),
        "--scan-interval-seconds", str(policy.nudge_scan_interval_seconds),
        "--now", now.isoformat(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "worker scan failed")
    scan = json.loads(result.stdout)
    delivered: list[str] = []
    errors: list[dict[str, str]] = []
    for fence in scan.get("work", []):
        try:
            deliver_fence(fence)
            delivered.append(str(fence["task_id"]))
        except (OSError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append({"task_id": str(fence.get("task_id", "")), "error": str(exc)})
    return {"enabled": True, "delivered": delivered, "errors": errors, "scan": scan}


def reconcile_once() -> dict[str, object]:
    timeout = float(os.environ.get("SQUAD_RECONCILE_SWEEP_TIMEOUT_SECONDS", "30"))
    command = [str(VAULT_ROOT / "bin/registry-reconciler.sh")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"ok": result.returncode == 0, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "host-snapshot",
            "scan-consumer",
            "reconcile-sweep",
            "subswarm-capacity",
            "subswarm-run",
        ),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--directive", type=Path)
    parser.add_argument("--command-map", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args()
    if args.mode == "host-snapshot":
        policy = load_worker_pool_policy(POLICY_PATH)
        print(json.dumps(sample_macos_host(policy.host_memory_mib, policy.memory_high_water_mib), sort_keys=True))
        return 0
    if args.mode in {"subswarm-capacity", "subswarm-run"}:
        if args.directive is None:
            parser.error(f"{args.mode} requires --directive")
        try:
            directive = validate_orchestration_directive(
                json.loads(args.directive.read_text(encoding="utf-8"))
            )
            if args.mode == "subswarm-capacity":
                print(json.dumps(live_subswarm_capacity(directive), sort_keys=True))
                return 0
            if args.command_map is None or args.evidence_output is None:
                parser.error("subswarm-run requires --command-map and --evidence-output")
            commands = json.loads(args.command_map.read_text(encoding="utf-8"))
            evidence = run_subswarm_directive(
                directive,
                commands,
                evidence_output=args.evidence_output,
                timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(evidence, sort_keys=True))
            return 0
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, SwarmDiffError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
    while True:
        try:
            result = scan_once() if args.mode == "scan-consumer" else reconcile_once()
            print(json.dumps(result, sort_keys=True), flush=True)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr, flush=True)
            if args.once:
                return 2
        if args.once:
            return 0
        if args.mode == "scan-consumer" and os.environ.get("SQUAD_WORKER_POOL_ENABLED", "0") == "1":
            interval = load_worker_pool_policy(POLICY_PATH).nudge_scan_interval_seconds
        elif args.mode == "scan-consumer":
            interval = 5
        else:
            interval = int(os.environ.get("SQUAD_RECONCILE_SWEEP_SECONDS", "60"))
        time.sleep(max(1, interval))


if __name__ == "__main__":
    raise SystemExit(main())
