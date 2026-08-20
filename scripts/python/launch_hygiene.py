#!/usr/bin/env python3
"""Fail-closed pre-exec normalization for V2 board-supervised workers."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import stat
import subprocess
import sys
from typing import Callable, Mapping, Sequence

try:
    from seatbelt_profile import CompiledProfile, ProfileSpec, compile_profile
except ModuleNotFoundError:  # Package import used by repository-level tests/tools.
    from .seatbelt_profile import CompiledProfile, ProfileSpec, compile_profile
try:
    from board_process_truth import ProcessTruthError, observe_process, terminate_attributable_tree
except ModuleNotFoundError:  # Package import used by repository-level tests/tools.
    from .board_process_truth import ProcessTruthError, observe_process, terminate_attributable_tree


SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
DEFAULT_ENV_ALLOWLIST = ("LANG", "LC_ALL", "PATH", "TERM")
TASK_ID_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
ATTEMPT_ID_RE = re.compile(r"^d-[0-9a-f]{32}$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SETTLED_T1P1_BUNDLE_SHA256 = "95438e2cc6b06ab3f12622ad0a0f3e0a6654e6cf3a7b35f3908b3487f883f376"


class HygieneError(RuntimeError):
    """The worker boundary could not be proven and launch must stop."""


@dataclass(frozen=True)
class AuditedWritableScope:
    path: Path
    root_fd: int
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class ResourceLimits:
    cpu_seconds: int = 30
    file_size_bytes: int = 64 * 1024 * 1024
    open_files: int = 64
    process_count: int = 512

    def validate(self) -> None:
        values = asdict(self)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values.values()):
            raise HygieneError("resource limits must be positive integers")


@dataclass(frozen=True)
class CanaryResult:
    profile_sha256: str
    allowed_write: bool
    denied_write: bool
    exact_broker_port: bool
    wrong_port_denied: bool
    fd3_closed: bool
    request_sha256: str = ""
    scope_sha256: str = ""
    details: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(
            (
                self.allowed_write,
                self.denied_write,
                self.exact_broker_port,
                self.wrong_port_denied,
                self.fd3_closed,
            )
        )

    @classmethod
    def failed(cls, detail: str) -> "CanaryResult":
        return cls("", False, False, False, False, False, details=(detail,))

    def to_json(self) -> str:
        payload = asdict(self)
        payload["passed"] = self.passed
        return json.dumps(payload, sort_keys=True)


@dataclass
class PreparedLaunch:
    """One-use receipt retaining the exact canaried profile and broker socket."""

    profile: CompiledProfile
    broker_listener: socket.socket
    canary: CanaryResult
    task_root: Path
    environment: dict[str, str]
    scopes: tuple[AuditedWritableScope, ...]
    owned_scopes: tuple[AuditedWritableScope, ...]
    consumed: bool = False

    def close(self) -> None:
        self.broker_listener.close()
        close_writable_scopes(self.owned_scopes)


class ProcessGroupReaper:
    """Track and synchronously reap the one process group owned by a launch."""

    def __init__(self) -> None:
        self._groups: set[int] = set()

    @property
    def groups(self) -> tuple[int, ...]:
        return tuple(sorted(self._groups))

    def register(self, pgid: int) -> None:
        if pgid <= 0:
            raise HygieneError("invalid process group")
        self._groups.add(pgid)

    def unregister(self, pgid: int) -> None:
        self._groups.discard(pgid)

    def terminate(self, pgid: int) -> None:
        if pgid not in self._groups:
            return
        try:
            identity = observe_process(pgid)
            if identity is None:
                raise ProcessTruthError("process-tree root disappeared before cleanup")
            terminate_attributable_tree(identity, 1.0)
        except OSError as exc:
            raise ProcessTruthError("process-tree cleanup failed") from exc


def _special_node_label(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "special node"
    return "unsupported node"


def _record_inode(
    seen: dict[tuple[int, int], str],
    current: os.stat_result,
    label: str,
) -> None:
    key = (current.st_dev, current.st_ino)
    previous = seen.get(key)
    if previous is not None and previous != label:
        raise HygieneError(f"cross-scope inode alias: {previous} and {label}")
    seen[key] = label


def _audit_directory_fd(
    directory_fd: int,
    scope_path: Path,
    relative: Path,
    seen: dict[tuple[int, int], str],
) -> None:
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as exc:
        raise HygieneError(f"cannot enumerate writable scope {scope_path}: {exc}") from exc
    for name in names:
        if name in (".", "..") or "/" in name or "\x00" in name:
            raise HygieneError(f"invalid writable-tree entry {name!r}")
        child_relative = relative / name
        label = str(scope_path / child_relative)
        try:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise HygieneError(f"cannot lstat writable-tree entry {label}: {exc}") from exc
        mode = current.st_mode
        if stat.S_ISLNK(mode):
            # Name the path AND the remedy: this audit runs before EVERY board
            # launch over this tree, so a symlink here also blocks the very
            # task that would remove it (measured 2026-08-18: a symlinked
            # skill mirror deadlocked every dispatch touching it, including
            # the removal task). The remedy is therefore host-side by design.
            raise HygieneError(
                f"symlink in writable tree: {label} -- board launches over "
                "this tree are refused while it exists, so the fix cannot be "
                "dispatched as a board task; remove the symlink in the "
                "primary checkout (operator action) and commit, then "
                "re-dispatch"
            )
        if stat.S_ISREG(mode):
            if current.st_nlink > 1:
                raise HygieneError(f"hardlink in writable tree: {label}")
            _record_inode(seen, current, label)
            continue
        if stat.S_ISDIR(mode):
            _record_inode(seen, current, label)
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                opened = os.fstat(child_fd)
            except OSError as exc:
                raise HygieneError(f"no-follow open failed for {label}: {exc}") from exc
            if (opened.st_dev, opened.st_ino, opened.st_mode) != (
                current.st_dev,
                current.st_ino,
                current.st_mode,
            ):
                os.close(child_fd)
                raise HygieneError(f"writable-tree identity changed: {label}")
            try:
                _audit_directory_fd(child_fd, scope_path, child_relative, seen)
            finally:
                os.close(child_fd)
            continue
        raise HygieneError(f"{_special_node_label(mode)} in writable tree: {label}")


def audit_writable_scopes(
    paths: Sequence[Path],
    *,
    high_assurance: bool = False,
    dedicated_volume_attested: bool = False,
) -> tuple[AuditedWritableScope, ...]:
    """Open and audit writable roots using no-follow, dirfd-relative traversal."""

    if not paths:
        raise HygieneError("at least one writable scope is required")
    if high_assurance and not dedicated_volume_attested:
        raise HygieneError("high-assurance writable scopes require dedicated volume attestation")
    scopes: list[AuditedWritableScope] = []
    seen: dict[tuple[int, int], str] = {}
    try:
        for raw in sorted({Path(path) for path in paths}, key=str):
            if not raw.is_absolute():
                raise HygieneError(f"writable scope is not absolute: {raw}")
            try:
                before = os.lstat(raw)
            except OSError as exc:
                raise HygieneError(f"writable scope is unavailable: {raw}: {exc}") from exc
            if stat.S_ISLNK(before.st_mode):
                raise HygieneError(f"writable scope is a symlink: {raw}")
            resolved = Path(os.path.realpath(raw))
            if resolved != raw:
                raise HygieneError(f"writable scope is not canonical: {raw} -> {resolved}")
            if stat.S_ISREG(before.st_mode) and before.st_nlink > 1:
                raise HygieneError(f"hardlink writable scope: {raw}")
            if not stat.S_ISDIR(before.st_mode) and not stat.S_ISREG(before.st_mode):
                raise HygieneError(f"{_special_node_label(before.st_mode)} writable scope: {raw}")
            flags = os.O_RDONLY | os.O_CLOEXEC
            if stat.S_ISDIR(before.st_mode):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                root_fd = os.open(raw, flags)
                opened = os.fstat(root_fd)
            except OSError as exc:
                raise HygieneError(f"no-follow root open failed: {raw}: {exc}") from exc
            if (before.st_dev, before.st_ino, before.st_mode) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
            ):
                os.close(root_fd)
                raise HygieneError(f"writable scope identity changed: {raw}")
            _record_inode(seen, opened, str(raw))
            scope = AuditedWritableScope(
                path=raw,
                root_fd=root_fd,
                device=opened.st_dev,
                inode=opened.st_ino,
                mode=opened.st_mode,
            )
            scopes.append(scope)
            if stat.S_ISDIR(opened.st_mode):
                _audit_directory_fd(root_fd, raw, Path(), seen)
        return tuple(scopes)
    except Exception:
        close_writable_scopes(scopes)
        raise


def reaudit_writable_scopes(scopes: Sequence[AuditedWritableScope]) -> None:
    """Re-check root identities and trees immediately before child execution."""

    seen: dict[tuple[int, int], str] = {}
    for scope in scopes:
        try:
            path_state = os.lstat(scope.path)
            fd_state = os.fstat(scope.root_fd)
        except OSError as exc:
            raise HygieneError(f"writable scope identity unavailable: {scope.path}: {exc}") from exc
        expected = (scope.device, scope.inode, scope.mode)
        if (
            path_state.st_dev,
            path_state.st_ino,
            path_state.st_mode,
        ) != expected or (
            fd_state.st_dev,
            fd_state.st_ino,
            fd_state.st_mode,
        ) != expected:
            raise HygieneError(f"writable scope identity changed before exec: {scope.path}")
        _record_inode(seen, fd_state, str(scope.path))
        if stat.S_ISDIR(fd_state.st_mode):
            _audit_directory_fd(scope.root_fd, scope.path, Path(), seen)


def close_writable_scopes(scopes: Sequence[AuditedWritableScope]) -> None:
    for scope in scopes:
        try:
            os.close(scope.root_fd)
        except OSError:
            pass


def build_task_environment(
    task_root: Path,
    *,
    inherited: Mapping[str, str] | None = None,
    allow_keys: Sequence[str] = DEFAULT_ENV_ALLOWLIST,
    audited_scope: AuditedWritableScope | None = None,
) -> dict[str, str]:
    """Build an environment from empty state and task-local 0700 directories."""

    root = Path(task_root)
    if not root.is_absolute():
        raise HygieneError("task root must be absolute")
    if Path(os.path.realpath(root)) != root:
        raise HygieneError("task root must be canonical and contain no symlink ancestor")
    try:
        root_state = os.lstat(root)
    except OSError as exc:
        raise HygieneError(f"task root must exist before environment creation: {root}: {exc}") from exc
    if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
        raise HygieneError("task root must be a no-follow directory")
    owned_scopes: tuple[AuditedWritableScope, ...] = ()
    if audited_scope is None:
        owned_scopes = audit_writable_scopes((root,))
        audited_scope = owned_scopes[0]
    if (
        audited_scope.path != root
        or not stat.S_ISDIR(audited_scope.mode)
    ):
        close_writable_scopes(owned_scopes)
        raise HygieneError("task environment must be created relative to its audited root fd")
    directories = {
        "HOME": root / "home",
        "XDG_CONFIG_HOME": root / "config",
        "XDG_CACHE_HOME": root / "cache",
        "TMPDIR": root / "tmp",
    }
    try:
        result: dict[str, str] = {}
        for key, directory in directories.items():
            name = directory.name
            try:
                os.mkdir(name, mode=0o700, dir_fd=audited_scope.root_fd)
            except FileExistsError:
                pass
            state = os.stat(
                name,
                dir_fd=audited_scope.root_fd,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
                raise HygieneError(f"task-local directory is not a no-follow directory: {directory}")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            child_fd = os.open(name, flags, dir_fd=audited_scope.root_fd)
            try:
                opened = os.fstat(child_fd)
                if (opened.st_dev, opened.st_ino, opened.st_mode) != (
                    state.st_dev,
                    state.st_ino,
                    state.st_mode,
                ):
                    raise HygieneError(f"task-local directory identity changed: {directory}")
                os.fchmod(child_fd, 0o700)
            finally:
                os.close(child_fd)
            result[key] = str(directory)
        source = inherited or {}
        allowed = set(allow_keys)
        if not allowed.issubset(DEFAULT_ENV_ALLOWLIST):
            raise HygieneError("environment allowlist contains an unsafe key")
        for key in sorted(allowed):
            if key in source:
                value = str(source[key])
                if "\x00" in value or "\n" in value or len(value) > 4096:
                    raise HygieneError(f"unsafe environment value for {key}")
                result[key] = value
        result["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        return result
    finally:
        close_writable_scopes(owned_scopes)


def _validate_child_environment(env: Mapping[str, str]) -> None:
    allowed = {
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "TMPDIR",
        *DEFAULT_ENV_ALLOWLIST,
    }
    unexpected = set(env) - allowed
    if unexpected:
        raise HygieneError(f"child environment contains non-allowlisted keys: {sorted(unexpected)}")
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str) or "\x00" in key or "\x00" in value:
            raise HygieneError("child environment contains an invalid key or value")


def _apply_one_limit(kind: int, requested: int) -> None:
    _, hard = resource.getrlimit(kind)
    soft = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
    resource.setrlimit(kind, (soft, hard))


def _apply_resource_limits(limits: ResourceLimits) -> None:
    limits.validate()
    _apply_one_limit(resource.RLIMIT_CPU, limits.cpu_seconds)
    _apply_one_limit(resource.RLIMIT_FSIZE, limits.file_size_bytes)
    _apply_one_limit(resource.RLIMIT_NOFILE, limits.open_files)
    if hasattr(resource, "RLIMIT_NPROC"):
        _apply_one_limit(resource.RLIMIT_NPROC, limits.process_count)


def _fd_ceiling() -> int:
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY:
        configured = os.sysconf("SC_OPEN_MAX")
        if configured <= 0:
            raise HygieneError("cannot determine descriptor ceiling")
        return int(configured)
    return int(soft)


def _close_ambient_fds() -> None:
    os.closerange(3, _fd_ceiling())


def _assert_no_ambient_fds() -> None:
    ceiling = _fd_ceiling()
    open_fds: list[int] = []
    for descriptor in range(3, ceiling):
        try:
            fcntl.fcntl(descriptor, fcntl.F_GETFD)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise
        else:
            open_fds.append(descriptor)
    if open_fds:
        raise HygieneError(f"ambient descriptors remain before exec: {open_fds}")


def _exec_helper(limits_json: str, scopes_json: str, command: Sequence[str]) -> None:
    values = json.loads(limits_json)
    limits = ResourceLimits(**values)
    scope_records = json.loads(scopes_json)
    scopes = tuple(
        AuditedWritableScope(
            path=Path(record["path"]),
            root_fd=int(record["root_fd"]),
            device=int(record["device"]),
            inode=int(record["inode"]),
            mode=int(record["mode"]),
        )
        for record in scope_records
    )
    reaudit_writable_scopes(scopes)
    close_writable_scopes(scopes)
    _close_ambient_fds()
    _assert_no_ambient_fds()
    _apply_resource_limits(limits)
    if not command:
        raise HygieneError("empty child command")
    os.execvpe(command[0], list(command), dict(os.environ))


def run_sanitized(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: float,
    limits: ResourceLimits = ResourceLimits(),
    profile: CompiledProfile | None = None,
    reaper: ProcessGroupReaper | None = None,
    audited_scopes: Sequence[AuditedWritableScope] = (),
) -> subprocess.CompletedProcess[str]:
    """Run through a single-threaded helper with empty ambient capabilities."""

    limits.validate()
    _validate_child_environment(env)
    if audited_scopes:
        reaudit_writable_scopes(audited_scopes)
    if not command or not Path(command[0]).is_absolute():
        raise HygieneError("child executable must be an absolute path")
    final_command = list(command)
    if profile is not None:
        final_command = [str(SANDBOX_EXEC), "-p", profile.text, *final_command]
    helper = [
        sys.executable,
        str(Path(__file__).resolve()),
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
                for scope in audited_scopes
            ],
            sort_keys=True,
        ),
        "--",
        *final_command,
    ]
    manager = reaper or ProcessGroupReaper()
    process = subprocess.Popen(
        helper,
        cwd=Path(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
        pass_fds=tuple(scope.root_fd for scope in audited_scopes),
        start_new_session=True,
    )
    manager.register(process.pid)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            manager.terminate(process.pid)
            try:
                stdout, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired as drain_exc:
                raise ProcessTruthError(
                    "child pipes remained open after verified process cleanup"
                ) from drain_exc
            exc.stdout, exc.stderr = stdout, stderr
            raise
    finally:
        manager.unregister(process.pid)
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)


def _accept_once(listener: socket.socket) -> bool:
    try:
        connection, _ = listener.accept()
    except (TimeoutError, socket.timeout):
        return False
    else:
        connection.close()
        return True


def _scope_digest(scopes: Sequence[AuditedWritableScope]) -> str:
    records = [
        f"{scope.path}\0{scope.device}\0{scope.inode}\0{scope.mode}\n"
        for scope in scopes
    ]
    return hashlib.sha256("".join(sorted(records)).encode("utf-8")).hexdigest()


def run_preflight_canary(
    task_root: Path,
    *,
    request_sha256: str = "",
    audited_scopes: Sequence[AuditedWritableScope] = (),
    retain_launch: bool = False,
) -> CanaryResult | PreparedLaunch:
    """Run every required effect under one exact Task-1.1 compiled profile."""

    root = Path(task_root)
    if not root.is_absolute() or Path(os.path.realpath(root)) != root:
        raise HygieneError("canary task root must be an existing canonical absolute path")
    try:
        root_state = os.lstat(root)
    except OSError as exc:
        raise HygieneError(f"canary task root is unavailable: {exc}") from exc
    if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
        raise HygieneError("canary task root must be a no-follow directory")
    owned_scopes = audit_writable_scopes((root,))
    combined_scopes = (*audited_scopes, *owned_scopes)
    allowed_target = root / "allowed.txt"
    denied_target = root.parent / f"{root.name}-denied.txt"
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
        listener.listen(1)
        listener.settimeout(0.5)
    exact_port = int(exact_listener.getsockname()[1])
    wrong_port = int(wrong_listener.getsockname()[1])
    try:
        profile = compile_profile(
            ProfileSpec(
                write_paths=(root,),
                executable_paths=(
                    Path("/bin/sh"),
                    Path("/bin/bash"),
                    Path("/usr/bin/nc"),
                ),
                broker_port=exact_port,
            )
        )
        allowed = run_sanitized(
            ["/bin/sh", "-c", 'printf allowed > "$1"', "sh", str(allowed_target)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=combined_scopes,
        )
        denied = run_sanitized(
            ["/bin/sh", "-c", 'printf denied > "$1"', "sh", str(denied_target)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=combined_scopes,
        )
        exact = run_sanitized(
            ["/usr/bin/nc", "-z", "-w", "2", "127.0.0.1", str(exact_port)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=combined_scopes,
        )
        exact_connected = _accept_once(exact_listener)
        wrong = run_sanitized(
            ["/usr/bin/nc", "-z", "-w", "2", "127.0.0.1", str(wrong_port)],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=combined_scopes,
        )
        wrong_connected = _accept_once(wrong_listener)
        descriptor = run_sanitized(
            ["/bin/sh", "-c", "printf inherited-bypass >&3"],
            env=environment,
            cwd=root,
            timeout=5,
            profile=profile,
            audited_scopes=combined_scopes,
        )
        details = (
            f"allowed_rc={allowed.returncode}",
            f"denied_rc={denied.returncode}",
            f"denied_stderr={denied.stderr.strip()}",
            f"exact_rc={exact.returncode}",
            f"wrong_rc={wrong.returncode}",
            f"wrong_stderr={wrong.stderr.strip()}",
            f"fd3_rc={descriptor.returncode}",
            f"fd3_stderr={descriptor.stderr.strip()}",
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
            fd3_closed=(
                descriptor.returncode != 0
                and "Bad file descriptor" in descriptor.stderr
            ),
            request_sha256=request_sha256,
            scope_sha256=_scope_digest(combined_scopes),
            details=details,
        )
        if retain_launch:
            return PreparedLaunch(
                profile=profile,
                broker_listener=exact_listener,
                canary=receipt,
                task_root=root,
                environment=environment,
                scopes=tuple(combined_scopes),
                owned_scopes=tuple(owned_scopes),
            )
        return receipt
    finally:
        if not retain_launch:
            exact_listener.close()
        wrong_listener.close()
        if not retain_launch:
            close_writable_scopes(owned_scopes)


def launch_if_canary_passes(
    canary_runner: Callable[[], CanaryResult | PreparedLaunch],
    command: Sequence[str],
    *,
    expected_profile_sha256: str,
    expected_request_sha256: str,
    expected_scope_sha256: str,
    timeout: float = 30,
    limits: ResourceLimits = ResourceLimits(),
) -> subprocess.CompletedProcess[str]:
    prepared_or_result = canary_runner()
    result = (
        prepared_or_result.canary
        if isinstance(prepared_or_result, PreparedLaunch)
        else prepared_or_result
    )
    if not result.passed:
        if isinstance(prepared_or_result, PreparedLaunch):
            prepared_or_result.close()
        raise HygieneError(f"preflight canary failed: {result.to_json()}")
    if not isinstance(prepared_or_result, PreparedLaunch):
        raise HygieneError("passing canary did not retain a sealed launch object")
    if (
        result.profile_sha256 != expected_profile_sha256
        or result.request_sha256 != expected_request_sha256
        or result.scope_sha256 != expected_scope_sha256
    ):
        prepared_or_result.close()
        raise HygieneError("preflight canary receipt is not bound to the launch profile/request/scopes")
    if prepared_or_result.consumed:
        prepared_or_result.close()
        raise HygieneError("prepared launch receipt has already been consumed")
    if prepared_or_result.profile.sha256 != result.profile_sha256:
        prepared_or_result.close()
        raise HygieneError("retained profile differs from canaried profile")
    if prepared_or_result.broker_listener.fileno() < 0:
        prepared_or_result.close()
        raise HygieneError("retained broker listener is closed")
    reaudit_writable_scopes(prepared_or_result.scopes)
    prepared_or_result.consumed = True
    try:
        return run_sanitized(
            command,
            env=prepared_or_result.environment,
            cwd=prepared_or_result.task_root,
            timeout=timeout,
            limits=limits,
            profile=prepared_or_result.profile,
            audited_scopes=prepared_or_result.scopes,
        )
    finally:
        prepared_or_result.close()


def _load_task_request(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HygieneError(f"invalid task request: {exc}") from exc
    if not isinstance(payload, dict):
        raise HygieneError("task request must be a JSON object")
    required = {
        "task_id",
        "attempt_id",
        "generation",
        "branch",
        "task_root",
        "write_paths",
        "profile_bundle_sha256",
    }
    if set(payload) != required:
        raise HygieneError(f"task request fields must be exactly {sorted(required)}")
    if not isinstance(payload["task_id"], str) or not TASK_ID_RE.fullmatch(payload["task_id"]):
        raise HygieneError("invalid task id")
    if not isinstance(payload["attempt_id"], str) or not ATTEMPT_ID_RE.fullmatch(payload["attempt_id"]):
        raise HygieneError("invalid attempt id")
    if isinstance(payload["generation"], bool) or not isinstance(payload["generation"], int) or payload["generation"] <= 0:
        raise HygieneError("generation must be a positive integer")
    expected_branch = os.environ.get("SQUAD_BASE_BRANCH", "v2")
    if payload["branch"] != expected_branch:
        raise HygieneError(f"supervisor accepts branch {expected_branch} only")
    task_root = Path(str(payload["task_root"]))
    if not task_root.is_absolute() or ".." in task_root.parts:
        raise HygieneError("task root must be absolute and contain no parent traversal")
    try:
        root_state = os.lstat(task_root)
    except OSError as exc:
        raise HygieneError(f"task root must already exist: {exc}") from exc
    if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
        raise HygieneError("task root must be a no-follow directory")
    canonical_root = Path(os.path.realpath(task_root))
    if canonical_root != task_root:
        raise HygieneError(f"task root is not canonical: {task_root} -> {canonical_root}")
    write_paths = payload["write_paths"]
    if (
        not isinstance(write_paths, list)
        or not write_paths
        or any(
            not isinstance(item, str)
            or not Path(item).is_absolute()
            or ".." in Path(item).parts
            for item in write_paths
        )
    ):
        raise HygieneError("write_paths must be canonical absolute paths without parent traversal")
    canonical_write_paths: list[Path] = []
    for raw in write_paths:
        candidate = Path(raw)
        try:
            state = os.lstat(candidate)
        except OSError as exc:
            raise HygieneError(f"declared writable scope must already exist: {candidate}: {exc}") from exc
        if stat.S_ISLNK(state.st_mode):
            raise HygieneError(f"declared writable scope is a symlink: {candidate}")
        canonical = Path(os.path.realpath(candidate))
        if canonical != candidate:
            raise HygieneError(f"declared writable scope is not canonical: {candidate} -> {canonical}")
        canonical_write_paths.append(canonical)
    if not any(
        canonical_root == scope or canonical_root.is_relative_to(scope)
        for scope in canonical_write_paths
    ):
        raise HygieneError("task root must be contained by a declared writable scope")
    digest = str(payload["profile_bundle_sha256"])
    if not HEX_SHA256_RE.fullmatch(digest):
        raise HygieneError("profile bundle hash must be lowercase SHA-256")
    if digest != SETTLED_T1P1_BUNDLE_SHA256:
        raise HygieneError("task request is not bound to the settled Task-1.1 bundle")
    repo_root = Path(__file__).resolve().parents[2]
    branch = subprocess.run(
        ["/usr/bin/git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        timeout=5,
        check=False,
        close_fds=True,
    )
    expected_branch = os.environ.get("SQUAD_BASE_BRANCH", "v2")
    if branch.returncode != 0 or branch.stdout.strip() != expected_branch:
        raise HygieneError(f"repository branch is not {expected_branch}")
    return payload


def _request_digest(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _main(argv: Sequence[str]) -> int:
    if argv and argv[0] == "_exec":
        if len(argv) < 5 or argv[3] != "--":
            raise HygieneError("invalid exec-helper invocation")
        _exec_helper(argv[1], argv[2], argv[4:])
        return 127
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate a sealed task request")
    validate_parser.add_argument("--request", type=Path, required=True)
    field_parser = subparsers.add_parser("field", help="print one validated request field")
    field_parser.add_argument("--request", type=Path, required=True)
    field_parser.add_argument("--name", choices=("task_root",), required=True)
    preflight_parser = subparsers.add_parser("preflight", help="run the exact-profile canary")
    preflight_parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(list(argv))
    try:
        request = _load_task_request(args.request)
        if args.command == "validate":
            print(json.dumps({"status": "valid", "request_sha256": _request_digest(request)}, sort_keys=True))
            return 0
        if args.command == "field":
            print(str(request[args.name]))
            return 0
        scopes = audit_writable_scopes(tuple(Path(path) for path in request["write_paths"]))
        try:
            reaudit_writable_scopes(scopes)
            result = run_preflight_canary(
                Path(str(request["task_root"])),
                request_sha256=_request_digest(request),
                audited_scopes=scopes,
            )
        finally:
            close_writable_scopes(scopes)
        print(result.to_json())
        return 0 if result.passed else 74
    except HygieneError as exc:
        print(json.dumps({"status": "denied", "reason": str(exc)}, sort_keys=True))
        return 74


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
