#!/usr/bin/env python3
"""Fail-closed F2 lane launcher and non-observability receipt helpers."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Mapping, Sequence

from broker_adapters import build_adapter, materialize_adapter
from cred_broker import (
    BrokerHTTPServer,
    Budget,
    CredentialBroker,
    HandleScope,
    RealHTTPSProviderTransport,
    SupervisorAuthority,
)
from launch_hygiene import (
    CanaryResult,
    HygieneError,
    PreparedLaunch,
    ResourceLimits,
    _request_digest,
    _scope_digest,
    _load_task_request,
    audit_writable_scopes,
    build_task_environment,
    close_writable_scopes,
    reaudit_writable_scopes,
    run_sanitized,
)
from seatbelt_profile import ProfileSpec, compile_profile


SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
GEMINI_NODE = Path("/opt/homebrew/bin/node")
GEMINI_ENTRYPOINT = Path(
    "/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js"
)
NODE_OPENSSL_CONFIG = Path("/opt/homebrew/etc/openssl@3/openssl.cnf")
# Populated only after a bounded real-call receipt succeeds. The 2026-07-22
# Gemini proof attempt was denied, so every lane remains fail-closed.
SUPPORTED_LIVE_LANES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ObservationReport:
    raw_secret_observed: bool
    opaque_handle_observed: bool
    surface_sha256: str
    secret_fingerprint_sha256: str
    handle_fingerprint_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_secret_observed": self.raw_secret_observed,
            "opaque_handle_observed": self.opaque_handle_observed,
            "surface_sha256": self.surface_sha256,
            "secret_fingerprint_sha256": self.secret_fingerprint_sha256,
            "handle_fingerprint_sha256": self.handle_fingerprint_sha256,
        }


def scan_observation_surface(
    *,
    provider_secret: str,
    opaque_handle: str,
    environment: Mapping[str, str],
    argv: Sequence[str],
    files: Mapping[Path, str],
    stdout: str,
    stderr: str,
    process_snapshot: str,
) -> ObservationReport:
    """Return only booleans and hashes; never retain raw observation values."""

    if not provider_secret or not opaque_handle:
        raise ValueError("secret and opaque handle must be non-empty")
    surface = json.dumps(
        {
            "environment": dict(environment),
            "argv": list(argv),
            "files": {str(path): content for path, content in files.items()},
            "stdout": stdout,
            "stderr": stderr,
            "process_snapshot": process_snapshot,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return ObservationReport(
        raw_secret_observed=provider_secret in surface,
        opaque_handle_observed=opaque_handle in surface,
        surface_sha256=hashlib.sha256(surface.encode()).hexdigest(),
        secret_fingerprint_sha256=hashlib.sha256(provider_secret.encode()).hexdigest(),
        handle_fingerprint_sha256=hashlib.sha256(opaque_handle.encode()).hexdigest(),
    )


class SpendLedger:
    """One-call-per-lane shared micro-dollar ceiling."""

    def __init__(self, *, ceiling_micros: int) -> None:
        if isinstance(ceiling_micros, bool) or not isinstance(ceiling_micros, int) or not 1 <= ceiling_micros < 1_000_000:
            raise ValueError("spend ceiling must be an integer below one dollar")
        self.ceiling_micros = ceiling_micros
        self._costs: dict[str, int] = {}

    @property
    def total_micros(self) -> int:
        return sum(self._costs.values())

    def reserve(self, maximum_micros: int) -> None:
        if isinstance(maximum_micros, bool) or not isinstance(maximum_micros, int) or maximum_micros <= 0:
            raise ValueError("reservation must be a positive integer")
        if self.total_micros + maximum_micros > self.ceiling_micros:
            raise RuntimeError("shared spend ceiling would be exceeded")

    def record(self, lane: str, cost_micros: int) -> None:
        if lane in self._costs:
            raise RuntimeError("duplicate provider call record")
        self.reserve(cost_micros)
        self._costs[lane] = cost_micros

    def to_dict(self) -> dict[str, object]:
        return {
            "ceiling_micros": self.ceiling_micros,
            "total_micros": self.total_micros,
            "lane_costs_micros": dict(sorted(self._costs.items())),
        }


@dataclass(frozen=True)
class LaneRuntime:
    lane: str
    executable: Path
    entrypoint: Path
    read_paths: tuple[Path, ...]
    read_literal_paths: tuple[Path, ...]
    read_alias_paths: tuple[Path, ...]
    library_paths: tuple[Path, ...]
    executable_paths: tuple[Path, ...]
    executable_sha256: str
    entrypoint_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_file(path: Path, *, executable: bool) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise HygieneError("lane runtime path must be absolute")
    try:
        before = os.lstat(candidate)
        resolved = Path(os.path.realpath(candidate))
        after = os.stat(resolved)
    except OSError as exc:
        raise HygieneError("lane runtime path is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) and candidate == resolved:
        raise HygieneError("lane runtime symlink did not resolve")
    if not stat.S_ISREG(after.st_mode) or after.st_mode & 0o022:
        raise HygieneError("lane runtime must be a non-writable regular file")
    if executable and not os.access(resolved, os.X_OK):
        raise HygieneError("lane runtime executable is not executable")
    check = os.stat(resolved)
    if (after.st_dev, after.st_ino, after.st_mode) != (
        check.st_dev,
        check.st_ino,
        check.st_mode,
    ):
        raise HygieneError("lane runtime changed identity during audit")
    return resolved


def _homebrew_native_dependencies(
    executable: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    """Resolve the pinned CLI runtime's dylibs to exact immutable file grants."""

    node_root = executable.parents[1]
    pending = [executable]
    audited: set[Path] = set()
    dependencies: set[Path] = set()
    dependency_roots: set[Path] = set()
    aliases: set[Path] = set()
    while pending:
        binary = pending.pop()
        if binary in audited:
            continue
        audited.add(binary)
        inspected = subprocess.run(
            ["/usr/bin/otool", "-L", str(binary)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if inspected.returncode != 0:
            raise HygieneError("unable to audit lane runtime native dependencies")
        for line in inspected.stdout.splitlines()[1:]:
            reference = line.strip().split(" ", 1)[0]
            if not reference:
                continue
            if reference.startswith(("/usr/lib/", "/System/Library/")):
                continue
            if reference.startswith("/opt/homebrew/"):
                candidate = Path(reference)
                if candidate.is_relative_to(Path("/opt/homebrew/opt")):
                    aliases.add(candidate)
                    parent = candidate.parent
                    while parent != Path("/opt/homebrew/opt"):
                        aliases.add(parent)
                        parent = parent.parent
            elif reference.startswith("@loader_path/"):
                candidate = binary.parent / reference.removeprefix("@loader_path/")
            elif reference.startswith("@executable_path/"):
                candidate = executable.parent / reference.removeprefix("@executable_path/")
            elif reference.startswith("@rpath/"):
                name = reference.removeprefix("@rpath/")
                choices = (
                    binary.parent / name,
                    binary.parent.parent / "lib" / name,
                    node_root / "lib" / name,
                )
                candidate = next((path for path in choices if path.exists()), Path())
                if candidate == Path():
                    raise HygieneError("unresolved lane runtime rpath dependency")
            else:
                raise HygieneError("unreviewed lane runtime dependency origin")
            resolved = _trusted_file(candidate, executable=False)
            if not resolved.is_relative_to(Path("/opt/homebrew/Cellar")):
                raise HygieneError("lane runtime dependency escaped Homebrew Cellar")
            relative = resolved.relative_to(Path("/opt/homebrew/Cellar"))
            if len(relative.parts) < 3:
                raise HygieneError("lane runtime dependency has no pinned Cellar version")
            package_root = (
                Path("/opt/homebrew/Cellar") / relative.parts[0] / relative.parts[1]
            ).resolve(strict=True)
            package_state = os.stat(package_root)
            if not stat.S_ISDIR(package_state.st_mode) or package_state.st_mode & 0o022:
                raise HygieneError("lane runtime dependency root is mutable")
            dependency_roots.add(package_root)
            if resolved not in dependencies:
                dependencies.add(resolved)
                pending.append(resolved)
    return (
        tuple(sorted((*dependencies, *dependency_roots), key=str)),
        tuple(sorted(aliases, key=str)),
        tuple(sorted(dependencies, key=str)),
    )


def _runtime_read_literals(paths: Sequence[Path]) -> tuple[Path, ...]:
    literals: set[Path] = set()
    for path in paths:
        parent = path.parent
        while parent != Path("/"):
            literals.add(parent)
            parent = parent.parent
    return tuple(sorted(literals, key=str))


def resolve_lane_runtime(lane: str) -> LaneRuntime:
    if lane != "gemini":
        raise HygieneError("subscription lane session transports are not F2-proven")
    executable = _trusted_file(GEMINI_NODE, executable=True)
    entrypoint = _trusted_file(GEMINI_ENTRYPOINT, executable=False)
    package_root = GEMINI_ENTRYPOINT.parents[1].resolve(strict=True)
    if not entrypoint.is_relative_to(package_root):
        raise HygieneError("Gemini entrypoint escaped its pinned package root")
    native_dependencies, native_aliases, native_libraries = (
        _homebrew_native_dependencies(executable)
    )
    openssl_config = _trusted_file(NODE_OPENSSL_CONFIG, executable=False)
    read_paths = (
        package_root,
        executable.parents[1],
        openssl_config,
        *native_dependencies,
    )
    return LaneRuntime(
        lane=lane,
        executable=executable,
        entrypoint=entrypoint,
        read_paths=read_paths,
        read_literal_paths=_runtime_read_literals(read_paths),
        read_alias_paths=native_aliases,
        library_paths=native_libraries,
        executable_paths=(executable,),
        executable_sha256=_sha256_file(executable),
        entrypoint_sha256=_sha256_file(entrypoint),
    )


def _accept_once(listener: socket.socket) -> bool:
    try:
        connection, _address = listener.accept()
    except (TimeoutError, socket.timeout):
        return False
    connection.close()
    return True


def prepare_lane_launch(
    request_payload: Mapping[str, object],
    runtime: LaneRuntime,
) -> PreparedLaunch:
    root = Path(str(request_payload["task_root"]))
    declared = tuple(Path(str(path)) for path in request_payload["write_paths"])
    outer_paths = tuple(path for path in declared if path != root)
    outer_scopes = audit_writable_scopes(outer_paths) if outer_paths else ()
    owned_scopes = audit_writable_scopes((root,))
    scopes = (*outer_scopes, *owned_scopes)
    environment = build_task_environment(
        root,
        inherited={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        allow_keys=("PATH", "LC_ALL"),
        audited_scope=owned_scopes[0],
    )
    exact_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    wrong_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for listener in (exact_listener, wrong_listener):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.settimeout(0.5)
    exact_port = int(exact_listener.getsockname()[1])
    wrong_port = int(wrong_listener.getsockname()[1])
    allowed_target = root / ".f2-canary-allowed"
    denied_target = root.parent / f".{root.name}-f2-canary-denied"
    try:
        profile = compile_profile(
            ProfileSpec(
                read_paths=runtime.read_paths,
                lane_read_literal_paths=(
                    *runtime.read_literal_paths,
                    *_runtime_read_literals((root,)),
                ),
                lane_read_alias_paths=runtime.read_alias_paths,
                lane_library_paths=runtime.library_paths,
                write_paths=(root,),
                executable_paths=(
                    Path("/bin/sh"),
                    Path("/bin/bash"),
                    Path("/usr/bin/nc"),
                ),
                lane_executable_paths=runtime.executable_paths,
                allow_fork=True,
                allow_sysctl_read=True,
                broker_port=exact_port,
            )
        )
        allowed = run_sanitized(
            ["/bin/sh", "-c", 'printf allowed > "$1"', "sh", str(allowed_target)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=scopes,
        )
        denied = run_sanitized(
            ["/bin/sh", "-c", 'printf denied > "$1"', "sh", str(denied_target)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=scopes,
        )
        exact = run_sanitized(
            ["/usr/bin/nc", "-z", "-w", "2", "127.0.0.1", str(exact_port)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=scopes,
        )
        exact_connected = _accept_once(exact_listener)
        wrong = run_sanitized(
            ["/usr/bin/nc", "-z", "-w", "2", "127.0.0.1", str(wrong_port)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=scopes,
        )
        wrong_connected = _accept_once(wrong_listener)
        descriptor = run_sanitized(
            ["/bin/sh", "-c", "printf inherited-bypass >&3"],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=scopes,
        )
        receipt = CanaryResult(
            profile_sha256=profile.sha256,
            allowed_write=allowed.returncode == 0 and allowed_target.read_bytes() == b"allowed",
            denied_write=(
                denied.returncode != 0
                and not denied_target.exists()
                and "Operation not permitted" in denied.stderr
            ),
            exact_broker_port=exact.returncode == 0 and exact_connected,
            wrong_port_denied=wrong.returncode != 0 and not wrong_connected,
            fd3_closed=descriptor.returncode != 0 and "Bad file descriptor" in descriptor.stderr,
            request_sha256=_request_digest(request_payload),
            scope_sha256=_scope_digest(scopes),
            details=(
                f"allowed_rc={allowed.returncode}",
                f"allowed_stderr={allowed.stderr.strip()}",
                f"denied_rc={denied.returncode}",
                f"denied_stderr={denied.stderr.strip()}",
                f"exact_rc={exact.returncode}",
                f"wrong_rc={wrong.returncode}",
                f"fd3_rc={descriptor.returncode}",
            ),
        )
        if not receipt.passed:
            raise HygieneError(
                "exact lane profile canary failed: " + ", ".join(receipt.details)
            )
        return PreparedLaunch(
            profile=profile,
            broker_listener=exact_listener,
            canary=receipt,
            task_root=root,
            environment=environment,
            scopes=scopes,
            owned_scopes=(*outer_scopes, *owned_scopes),
        )
    except Exception:
        exact_listener.close()
        close_writable_scopes(scopes)
        raise
    finally:
        wrong_listener.close()


def _observed_process(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    profile_text: str,
    scopes: Sequence[object],
    timeout: float,
) -> tuple[subprocess.CompletedProcess[str], str]:
    reaudit_writable_scopes(scopes)
    limits = ResourceLimits(cpu_seconds=60, open_files=128, process_count=256)
    helper = [
        sys.executable,
        str(Path(__file__).with_name("launch_hygiene.py")),
        "_exec",
        json.dumps(asdict(limits), sort_keys=True),
        json.dumps(
            [
                {
                    "path": str(scope.path),
                    "root_fd": scope.root_fd,
                    "device": scope.device,
                    "inode": scope.inode,
                    "mode": scope.mode,
                }
                for scope in scopes
            ],
            sort_keys=True,
        ),
        "--",
        str(SANDBOX_EXEC),
        "-p",
        profile_text,
        *command,
    ]
    process = subprocess.Popen(
        helper,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
        pass_fds=tuple(scope.root_fd for scope in scopes),
        start_new_session=True,
    )
    snapshots: list[str] = []
    deadline = time.monotonic() + min(timeout, 3.0)
    while process.poll() is None and time.monotonic() < deadline:
        observed = subprocess.run(
            ["/bin/ps", "eww", "-p", str(process.pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            close_fds=True,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        )
        if observed.returncode == 0 and observed.stdout:
            snapshots.append(observed.stdout)
        time.sleep(0.05)
    try:
        stdout, stderr = process.communicate(timeout=max(0.1, timeout - 3.0))
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate(timeout=2)
        raise HygieneError("lane CLI timed out") from exc
    return (
        subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr),
        "".join(snapshots),
    )


def _observed_acp_process(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    profile_text: str,
    scopes: Sequence[object],
    broker_endpoint: str,
    opaque_handle: str,
    prompt: str,
    timeout: float,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Drive the Gemini CLI's native ACP gateway flow over NDJSON stdio."""

    reaudit_writable_scopes(scopes)
    limits = ResourceLimits(cpu_seconds=60, open_files=128, process_count=256)
    helper = [
        sys.executable,
        str(Path(__file__).with_name("launch_hygiene.py")),
        "_exec",
        json.dumps(asdict(limits), sort_keys=True),
        json.dumps(
            [
                {
                    "path": str(scope.path),
                    "root_fd": scope.root_fd,
                    "device": scope.device,
                    "inode": scope.inode,
                    "mode": scope.mode,
                }
                for scope in scopes
            ],
            sort_keys=True,
        ),
        "--",
        str(SANDBOX_EXEC),
        "-p",
        profile_text,
        *command,
    ]
    process = subprocess.Popen(
        helper,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
        pass_fds=tuple(scope.root_fd for scope in scopes),
        start_new_session=True,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise HygieneError("ACP stdio could not be established")
    stdout_lines: list[str] = []
    snapshots: list[str] = []
    deadline = time.monotonic() + timeout

    def request_acp(identifier: int, method: str, params: Mapping[str, object]) -> dict[str, object]:
        message = {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()
        while time.monotonic() < deadline:
            observed = subprocess.run(
                ["/bin/ps", "eww", "-p", str(process.pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                close_fds=True,
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
            )
            if observed.returncode == 0 and observed.stdout:
                snapshots.append(observed.stdout)
            readable, _writable, _exceptional = select.select(
                [process.stdout], [], [], min(0.25, max(0.0, deadline - time.monotonic()))
            )
            if not readable:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            stdout_lines.append(line)
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != identifier:
                continue
            if "error" in response:
                raise HygieneError(f"Gemini ACP request {method} was denied")
            result = response.get("result", {})
            if not isinstance(result, dict):
                raise HygieneError("Gemini ACP response had an invalid result")
            return result
        raise HygieneError(f"Gemini ACP request {method} timed out")

    try:
        request_acp(1, "initialize", {"protocolVersion": 1})
        request_acp(
            2,
            "authenticate",
            {
                "methodId": "gateway",
                "_meta": {
                    "api-key": opaque_handle,
                    "gateway": {"baseUrl": broker_endpoint},
                },
            },
        )
        session = request_acp(3, "session/new", {"cwd": str(cwd), "mcpServers": []})
        session_id = session.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise HygieneError("Gemini ACP did not return a session identifier")
        request_acp(
            4,
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
        )
        process.stdin.close()
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        remaining_stdout = process.stdout.read()
        if remaining_stdout:
            stdout_lines.append(remaining_stdout)
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        raise
    return (
        subprocess.CompletedProcess(
            list(command), process.returncode, "".join(stdout_lines), stderr
        ),
        "".join(snapshots),
    )


def _task_file_observation(root: Path, secret: str) -> tuple[bool, str]:
    digest = hashlib.sha256()
    observed = False
    for path in sorted(root.rglob("*"), key=str):
        try:
            state = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(state.st_mode) or state.st_size > 8 * 1024 * 1024:
            continue
        data = path.read_bytes()
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        observed = observed or secret.encode() in data
    return observed, digest.hexdigest()


def launch_gemini(
    request_path: Path,
    *,
    model: str,
    prompt: str,
    max_cost_micros: int,
    transport: RealHTTPSProviderTransport | None = None,
) -> dict[str, object]:
    payload = _load_task_request(request_path)
    runtime = resolve_lane_runtime("gemini")
    provider_secret = os.environ.get("GEMINI_API_KEY", "")
    if not provider_secret:
        raise HygieneError("supervisor Gemini credential is unavailable")
    ledger = SpendLedger(ceiling_micros=999_999)
    ledger.reserve(max_cost_micros)
    prepared = prepare_lane_launch(payload, runtime)
    broker_server: BrokerHTTPServer | None = None
    handle = ""
    try:
        authority_material = "\0".join(
            (
                str(payload["task_id"]),
                str(payload["attempt_id"]),
                str(payload["generation"]),
                "gemini",
                model,
                prepared.profile.sha256,
                prepared.canary.request_sha256,
                prepared.canary.scope_sha256,
            )
        )
        authority_sha256 = hashlib.sha256(authority_material.encode()).hexdigest()
        authority = SupervisorAuthority(
            task_id=str(payload["task_id"]),
            attempt_id=str(payload["attempt_id"]),
            generation=int(payload["generation"]),
            lane="gemini",
            authority_sha256=authority_sha256,
            profile_sha256=prepared.profile.sha256,
            request_sha256=prepared.canary.request_sha256,
            scope_sha256=prepared.canary.scope_sha256,
        )
        selected_transport = transport or RealHTTPSProviderTransport("gemini")
        broker = CredentialBroker(
            expected_authority=authority,
            provider_secrets={"gemini": provider_secret},
            provider_transports={"gemini": selected_transport},
        )
        broker_server = BrokerHTTPServer.from_prepared_launch(prepared, broker)
        handle = broker.mint_handle(
            HandleScope(
                task_id=str(payload["task_id"]),
                attempt_id=str(payload["attempt_id"]),
                generation=int(payload["generation"]),
                lane="gemini",
                authority_sha256=authority_sha256,
                profile_sha256=prepared.profile.sha256,
                request_sha256=prepared.canary.request_sha256,
                scope_sha256=prepared.canary.scope_sha256,
                actions=("model:gemini",),
                targets=(model,),
                budget=Budget(1, 200_000, 8, max_cost_micros, 1024 * 1024),
            ),
            ttl_seconds=120,
        )
        broker_server.start()
        adapter = build_adapter(
            "gemini",
            broker_server.base_url,
            handle,
            Path(prepared.environment["HOME"]),
            runtime.executable,
        )
        materialize_adapter(adapter)
        command = (
            *adapter.argv,
            str(runtime.entrypoint),
            "--acp",
            "--model",
            model,
            "--yolo",
            "--skip-trust",
        )
        completed, process_snapshot = _observed_acp_process(
            command,
            env=prepared.environment,
            cwd=prepared.task_root,
            profile_text=prepared.profile.text,
            scopes=prepared.scopes,
            broker_endpoint=f"{broker_server.base_url}/v1/model/gemini",
            opaque_handle=handle,
            prompt=prompt,
            timeout=60,
        )
        adapter_files = {path: path.read_text(encoding="utf-8") for path in adapter.files}
        observation = scan_observation_surface(
            provider_secret=provider_secret,
            opaque_handle=handle,
            environment=prepared.environment,
            argv=command,
            files=adapter_files,
            stdout=completed.stdout,
            stderr=completed.stderr,
            process_snapshot=process_snapshot,
        )
        task_secret_observed, task_tree_sha256 = _task_file_observation(
            prepared.task_root,
            provider_secret,
        )
        serialized_logs = json.dumps(broker.action_logs, sort_keys=True, separators=(",", ":"))
        log_secret_observed = provider_secret in serialized_logs
        allowed_logs = [record for record in broker.action_logs if record.get("decision") == "allow"]
        if len(allowed_logs) != 1:
            decisions = [
                {"decision": record.get("decision"), "action": record.get("action")}
                for record in broker.action_logs
            ]
            raise HygieneError(
                "exactly one provider allow receipt is required; "
                f"cli_rc={completed.returncode}; decisions={decisions}; "
                f"stderr={completed.stderr[-2000:]}"
            )
        cost_micros = int(allowed_logs[0]["cost_micros"])
        ledger.record("gemini", cost_micros)
        if completed.returncode != 0:
            raise HygieneError("Gemini CLI did not complete successfully")
        if observation.raw_secret_observed or task_secret_observed or log_secret_observed:
            raise HygieneError("raw provider credential was observable outside the broker")
        receipt = {
            "status": "f2-closed",
            "lane": "gemini",
            "model": model,
            "profile_sha256": prepared.profile.sha256,
            "request_sha256": prepared.canary.request_sha256,
            "scope_sha256": prepared.canary.scope_sha256,
            "authority_sha256": authority_sha256,
            "canary": asdict(prepared.canary),
            "runtime": asdict(runtime),
            "observation": observation.to_dict(),
            "task_tree_raw_secret_observed": task_secret_observed,
            "task_tree_sha256": task_tree_sha256,
            "action_log_sha256": hashlib.sha256(serialized_logs.encode()).hexdigest(),
            "action_log": broker.action_logs,
            "spend": ledger.to_dict(),
            "cli_stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
            "cli_stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        }
        return json.loads(json.dumps(receipt, default=str))
    finally:
        if broker_server is not None:
            broker_server.close()
        prepared.close()


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    launch = subparsers.add_parser("launch")
    launch.add_argument("--request", type=Path, required=True)
    launch.add_argument("--lane", choices=tuple(sorted(SUPPORTED_LIVE_LANES)), required=True)
    launch.add_argument("--model", required=True)
    launch.add_argument("--prompt", default="Reply exactly: ok. Do not use tools.")
    launch.add_argument("--max-cost-micros", type=int, default=250_000)
    args = parser.parse_args(list(argv))
    try:
        if args.lane != "gemini":
            raise HygieneError("lane is not F2-closed")
        receipt = launch_gemini(
            args.request,
            model=args.model,
            prompt=args.prompt,
            max_cost_micros=args.max_cost_micros,
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (HygieneError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "denied", "reason": str(exc)}, sort_keys=True))
        return 74


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
