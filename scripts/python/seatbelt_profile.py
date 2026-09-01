#!/usr/bin/env python3
"""Fail-closed compiler for the V2 per-task macOS Seatbelt profile."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import pwd
import stat
import subprocess
from typing import Callable, Iterable, Sequence


class SeatbeltProfileError(RuntimeError):
    """Base class for profile compilation failures."""


class ProfileValidationError(SeatbeltProfileError):
    """A requested grant cannot be represented safely."""


class PathIdentityError(ProfileValidationError):
    """A declared path changed identity while it was normalized."""


class SandboxCompatibilityError(SeatbeltProfileError):
    """The host cannot safely enforce the compiled Seatbelt profile."""


def _validate_account_home(
    account_home: str | os.PathLike[str],
    *,
    effective_uid: int,
    environment_home: str | None,
) -> Path:
    """Validate one passwd-derived lexical home without trusting the environment."""

    try:
        lexical_home = Path(account_home)
    except (TypeError, ValueError) as exc:
        raise ProfileValidationError(
            "effective-UID account home is invalid"
        ) from exc
    if (
        not lexical_home.is_absolute()
        or lexical_home == Path("/")
        or any(ord(character) < 32 for character in str(lexical_home))
    ):
        raise ProfileValidationError(
            "effective-UID account home must be an absolute non-root path "
            "without control characters"
    )
    try:
        account_before = os.stat(lexical_home)
        canonical_home = lexical_home.resolve(strict=True)
        account_after = os.stat(canonical_home)
    except (OSError, RuntimeError) as exc:
        raise ProfileValidationError(
            f"effective-UID account home is unavailable: {lexical_home}"
        ) from exc
    if (
        account_before.st_dev,
        account_before.st_ino,
    ) != (
        account_after.st_dev,
        account_after.st_ino,
    ):
        raise PathIdentityError(
            "effective-UID account home changed identity during validation"
        )
    if (
        canonical_home == Path("/")
        or not stat.S_ISDIR(account_after.st_mode)
        or account_after.st_uid != effective_uid
    ):
        raise ProfileValidationError(
            "effective-UID account home must be a non-root directory owned "
            "by the effective UID"
        )

    if environment_home is not None:
        try:
            lexical_environment_home = Path(environment_home)
        except (TypeError, ValueError) as exc:
            raise ProfileValidationError("HOME is invalid") from exc
        if (
            not lexical_environment_home.is_absolute()
            or any(
                ord(character) < 32
                for character in str(lexical_environment_home)
            )
        ):
            raise ProfileValidationError(
                "HOME must be an absolute path without control characters"
            )
        try:
            canonical_environment_home = lexical_environment_home.resolve(
                strict=True
            )
        except (OSError, RuntimeError) as exc:
            raise ProfileValidationError(
                f"HOME is unavailable: {lexical_environment_home}"
            ) from exc
        if canonical_environment_home != canonical_home:
            raise ProfileValidationError(
                "HOME does not match the effective-UID account home"
            )
    return lexical_home


def _account_home_from_effective_uid() -> Path:
    effective_uid = os.geteuid()
    try:
        account_home = pwd.getpwuid(effective_uid).pw_dir
    except (AttributeError, KeyError, OSError, TypeError) as exc:
        raise ProfileValidationError(
            "effective-UID account record is unavailable"
        ) from exc
    # $HOME is intentionally NOT used to gate the account home. The passwd
    # euid record is the authoritative source, and the board runs sandboxed
    # spawns whose $HOME legitimately differs from it; requiring a match here
    # raised at module import and broke every sandboxed launch. Authority
    # paths (LOCAL_BIN_ROOT, UV_*) derive from the euid home regardless.
    return _validate_account_home(
        account_home,
        effective_uid=effective_uid,
        environment_home=None,
    )


# Evaluated once from the passwd record; the alias paths below stay lexical so
# their symlink chains can be audited separately from resolved executables.
HOST_HOME = _account_home_from_effective_uid()
LOCAL_BIN_ROOT = HOST_HOME / ".local" / "bin"
GROK_BIN_ROOT = HOST_HOME / ".grok" / "bin"
UV_ROOT = HOST_HOME / ".local" / "share" / "uv"
UV_TOOLS_ROOT = UV_ROOT / "tools"
UV_PYTHON_ROOT = UV_ROOT / "python"
DEFAULT_LANE_PATH = os.pathsep.join(
    (
        str(GROK_BIN_ROOT),
        str(LOCAL_BIN_ROOT),
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    )
)


CANONICAL_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
KNOWN_MACOS_BUILDS = frozenset({"25E253"})
# This canary proves only that the pinned sandbox-exec binary still compiles a
# profile and launches a harmless binary. Enforcement is proven separately by
# the deny-default effect probes; keeping the compatibility canary permissive
# avoids coupling availability detection to undocumented bootstrap services.
_COMPAT_CANARY = """(version 1)
(allow default)
"""

# Fixed, reviewed runtime roots for the currently admitted macOS build. The
# build gate prevents silently reusing these grants on an unknown host image.
RUNTIME_READ_PATHS = (
    Path("/System/Library"),
    Path("/usr/lib"),
    Path("/usr/bin"),
    Path("/bin"),
    Path("/Library/Apple/System/Library"),
    Path("/private/var/db/timezone"),
    Path("/private/var/select"),
    Path("/dev/null"),
)
RUNTIME_READ_LITERALS = (Path("/"),)

# Exact, host-pinned lane entrypoints. These are resolved and inode-audited at
# compile time; process-exec is emitted only for the resulting regular files
# and their exact shebang interpreters. No directory/subpath exec grant exists.
LANE_CLI_PATHS = {
    "claude": LOCAL_BIN_ROOT / "claude",
    "codex": Path("/opt/homebrew/bin/codex"),
    # The routing identifier remains ``gemini``; Antigravity's native CLI is
    # now the executable vehicle for that lane.
    "gemini": LOCAL_BIN_ROOT / "agy",
    "grok": GROK_BIN_ROOT / "grok",
    "kimi": LOCAL_BIN_ROOT / "kimi",
}
CODEX_NATIVE_EXECUTABLE = Path(
    "/opt/homebrew/lib/node_modules/@openai/codex/node_modules/"
    "@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex"
)
OFFLINE_LAUNCH_EXECUTABLES = (Path("/usr/bin/false"), Path("/usr/bin/true"))
BROKER_RELAY_PYTHON = Path("/usr/bin/python3")
NODE_OPENSSL_CONFIG = Path("/opt/homebrew/etc/openssl@3/openssl.cnf")


@dataclass(frozen=True)
class _LaneLaunchSelection:
    lane: str | None
    offline_probe: bool
    broker_relay: bool
    denied_subtrees: tuple[Path, ...]


_LANE_LAUNCH_SELECTION: ContextVar[_LaneLaunchSelection | None] = ContextVar(
    "seatbelt_lane_launch_selection", default=None
)


@contextmanager
def scoped_lane_launch_profile(
    *,
    lane: str | None = None,
    offline_probe: bool = False,
    broker_relay: bool = False,
    denied_subtrees: Iterable[Path] = (),
):
    """Add one controller-selected lane's exact grants to one compile call.

    Ordinary Stage-1/F2 profile compilation remains unchanged. The context is
    process-local and reset even on failure; board-supervisor enters it only
    after authenticating and validating launch authority.
    """

    if lane is not None and lane not in LANE_CLI_PATHS:
        raise ProfileValidationError(f"unknown lane launch profile: {lane}")
    if not isinstance(offline_probe, bool) or (lane is None) == (not offline_probe):
        raise ProfileValidationError(
            "select exactly one lane launch or the offline probe profile"
        )
    if not isinstance(broker_relay, bool) or (broker_relay and lane is None):
        raise ProfileValidationError("broker relay requires one selected lane")
    denied = tuple(Path(path) for path in denied_subtrees)
    token = _LANE_LAUNCH_SELECTION.set(
        _LaneLaunchSelection(
            lane=lane,
            offline_probe=offline_probe,
            broker_relay=broker_relay,
            denied_subtrees=denied,
        )
    )
    try:
        yield
    finally:
        _LANE_LAUNCH_SELECTION.reset(token)


@dataclass(frozen=True)
class HostCompatibility:
    sandbox_exec: Path
    macos_build: str
    canary_sha256: str


@dataclass(frozen=True)
class NormalizedPath:
    path: Path
    device: int
    inode: int
    mode: int
    is_directory: bool


@dataclass(frozen=True)
class ProfileSpec:
    read_paths: tuple[Path, ...] = ()
    lane_read_literal_paths: tuple[Path, ...] = ()
    lane_read_alias_paths: tuple[Path, ...] = ()
    lane_library_paths: tuple[Path, ...] = ()
    write_paths: tuple[Path, ...] = ()
    executable_paths: tuple[Path, ...] = ()
    lane_executable_paths: tuple[Path, ...] = ()
    allow_fork: bool = False
    allow_sysctl_read: bool = False
    broker_port: int | None = None
    denied_subtrees: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CompiledProfile:
    text: str
    sha256: str
    compatibility: HostCompatibility


def _read_macos_build() -> str:
    try:
        completed = subprocess.run(
            ["/usr/bin/sw_vers", "-buildVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxCompatibilityError(
            f"cannot read macOS build: {exc}"
        ) from exc
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise SandboxCompatibilityError(f"cannot read macOS build: {detail}")
    return completed.stdout.strip()


def verify_sandbox_compatibility(
    *,
    sandbox_exec: Path = CANONICAL_SANDBOX_EXEC,
    allowed_builds: frozenset[str] = KNOWN_MACOS_BUILDS,
    build_reader: Callable[[], str] = _read_macos_build,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HostCompatibility:
    """Verify the canonical binary, exact host build, and a harmless canary."""

    candidate = Path(sandbox_exec)
    if platform.system() != "Darwin":
        raise SandboxCompatibilityError("Seatbelt profiles require macOS/Darwin")
    if candidate != CANONICAL_SANDBOX_EXEC:
        raise SandboxCompatibilityError(
            f"sandbox-exec must be {CANONICAL_SANDBOX_EXEC}, got {candidate}"
        )
    try:
        resolved = candidate.resolve(strict=True)
        canonical = CANONICAL_SANDBOX_EXEC.resolve(strict=True)
    except OSError as exc:
        raise SandboxCompatibilityError(
            f"sandbox-exec is absent or inaccessible: {exc}"
        ) from exc
    if (
        resolved != canonical
        or not candidate.is_file()
        or not os.access(candidate, os.X_OK)
    ):
        raise SandboxCompatibilityError(
            "sandbox-exec is absent, renamed, or not executable"
        )

    try:
        binary_before = os.stat(candidate)
    except OSError as exc:
        raise SandboxCompatibilityError(
            f"sandbox-exec disappeared before compatibility canary: {exc}"
        ) from exc
    try:
        macos_build = build_reader().strip()
    except SandboxCompatibilityError:
        raise
    except Exception as exc:
        raise SandboxCompatibilityError(
            f"cannot read macOS build: {exc}"
        ) from exc
    if macos_build not in allowed_builds:
        raise SandboxCompatibilityError(
            f"unrecognized macOS build {macos_build!r}; refusing sandbox launch"
        )

    try:
        completed = runner(
            [str(candidate), "-p", _COMPAT_CANARY, "/usr/bin/true"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxCompatibilityError(
            f"sandbox-exec compatibility canary could not run: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise SandboxCompatibilityError(
            f"sandbox-exec compatibility canary failed: {detail}"
        )
    try:
        binary_after = os.stat(candidate)
    except OSError as exc:
        raise SandboxCompatibilityError(
            f"sandbox-exec disappeared after compatibility canary: {exc}"
        ) from exc
    if (binary_before.st_dev, binary_before.st_ino) != (
        binary_after.st_dev,
        binary_after.st_ino,
    ):
        raise SandboxCompatibilityError(
            "sandbox-exec changed identity during compatibility verification"
        )
    return HostCompatibility(
        sandbox_exec=candidate,
        macos_build=macos_build,
        canary_sha256=hashlib.sha256(_COMPAT_CANARY.encode("utf-8")).hexdigest(),
    )


def normalize_realpath(
    path: Path,
    *,
    stat_fn: Callable[[os.PathLike[str] | str], os.stat_result] = os.stat,
    realpath_fn: Callable[[os.PathLike[str] | str], str] = os.path.realpath,
) -> NormalizedPath:
    """Resolve one absolute existing path and reject audit-time identity drift."""

    raw = Path(path)
    if not raw.is_absolute():
        raise ProfileValidationError(f"declared path is not absolute: {raw}")
    if any(ord(character) < 32 for character in str(raw)):
        raise ProfileValidationError(
            f"declared path contains a control character: {raw!s}"
        )
    try:
        before = stat_fn(raw)
        resolved = Path(realpath_fn(raw))
        after = stat_fn(resolved)
    except OSError as exc:
        raise ProfileValidationError(
            f"declared path is unavailable: {raw}: {exc}"
        ) from exc
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise PathIdentityError(f"declared path changed identity: {raw}")
    return NormalizedPath(
        path=resolved,
        device=after.st_dev,
        inode=after.st_ino,
        mode=after.st_mode,
        is_directory=stat.S_ISDIR(after.st_mode),
    )


def _normalize_many(paths: Iterable[Path]) -> tuple[NormalizedPath, ...]:
    by_path: dict[Path, NormalizedPath] = {}
    for raw in paths:
        normalized = normalize_realpath(Path(raw))
        previous = by_path.get(normalized.path)
        if previous is not None and (
            previous.device,
            previous.inode,
        ) != (normalized.device, normalized.inode):
            raise PathIdentityError(
                f"canonical path has conflicting identities: {normalized.path}"
            )
        by_path[normalized.path] = normalized
    return tuple(by_path[path] for path in sorted(by_path, key=str))


def _shebang_interpreter(path: Path) -> Path | None:
    try:
        with path.open("rb") as stream:
            first_line = stream.readline(512)
    except OSError as exc:
        raise ProfileValidationError(f"lane CLI is unreadable: {path}") from exc
    if not first_line.startswith(b"#!"):
        return None
    try:
        words = first_line[2:].decode("utf-8").strip().split()
    except UnicodeDecodeError as exc:
        raise ProfileValidationError(f"lane CLI has an invalid shebang: {path}") from exc
    if not words:
        raise ProfileValidationError(f"lane CLI has an empty shebang: {path}")
    interpreter = Path(words[0])
    if interpreter == Path("/usr/bin/env"):
        if len(words) != 2 or words[1] != "node":
            raise ProfileValidationError(f"lane CLI uses an unreviewed env shebang: {path}")
        node = Path("/opt/homebrew/bin/node")
        if not node.exists():
            raise ProfileValidationError("reviewed Homebrew node runtime is unavailable")
        return Path(os.path.realpath(node))
    if not interpreter.is_absolute():
        raise ProfileValidationError(f"lane CLI interpreter is not absolute: {path}")
    return Path(os.path.realpath(interpreter))


def _symlink_chain(path: Path) -> tuple[Path, ...]:
    chain: list[Path] = []
    current = Path(path)
    for _ in range(16):
        try:
            state = os.lstat(current)
        except OSError as exc:
            raise ProfileValidationError(f"lane runtime alias is unavailable: {current}") from exc
        chain.append(current)
        if not stat.S_ISLNK(state.st_mode):
            return tuple(chain)
        target = Path(os.readlink(current))
        current = target if target.is_absolute() else current.parent / target
        current = Path(os.path.normpath(current))
    raise ProfileValidationError("lane runtime alias chain is too deep")


def installed_lane_cli_executable_paths(
    *,
    lanes: Iterable[str] | None = None,
    include_offline: bool = True,
    include_broker_relay: bool = False,
) -> tuple[Path, ...]:
    """Return exact executable files needed for the five installed lane CLIs."""

    selected = set(LANE_CLI_PATHS if lanes is None else lanes)
    if not selected.issubset(LANE_CLI_PATHS):
        raise ProfileValidationError("unknown lane executable selection")
    paths: set[Path] = (
        {Path(os.path.realpath(path)) for path in OFFLINE_LAUNCH_EXECUTABLES}
        if include_offline
        else set()
    )
    if include_broker_relay:
        # Every board lane reaches chrono-vault through the same stdlib-only
        # relay.  Grant the exact system interpreter, never a Python directory
        # or PATH pattern; the relay script itself remains bounded by the
        # attempt worktree read grant.
        paths.add(Path(os.path.realpath(BROKER_RELAY_PYTHON)))
    if "codex" in selected:
        paths.add(Path(os.path.realpath(CODEX_NATIVE_EXECUTABLE)))
    for lane, alias in sorted(LANE_CLI_PATHS.items()):
        if lane not in selected:
            continue
        if not alias.exists():
            raise ProfileValidationError(f"required {lane} CLI is unavailable: {alias}")
        entrypoint = Path(os.path.realpath(alias))
        paths.add(entrypoint)
        interpreter = _shebang_interpreter(entrypoint)
        if interpreter is not None:
            with entrypoint.open("rb") as stream:
                uses_env_node = stream.readline(512).startswith(b"#!/usr/bin/env node")
            if uses_env_node:
                paths.add(Path("/usr/bin/env"))
            paths.add(interpreter)
    return tuple(sorted(paths, key=str))


def installed_lane_cli_executable_aliases(
    resolved_executables: Sequence[NormalizedPath],
    *,
    lanes: Iterable[str] | None = None,
) -> tuple[Path, ...]:
    """Audit fixed lexical CLI aliases while retaining them for exec matching."""

    allowed_targets = {item.path for item in resolved_executables}
    aliases: set[Path] = set()
    selected = set(LANE_CLI_PATHS if lanes is None else lanes)
    if not selected.issubset(LANE_CLI_PATHS):
        raise ProfileValidationError("unknown lane alias selection")
    for lane, alias in sorted(LANE_CLI_PATHS.items()):
        if lane not in selected:
            continue
        try:
            before = os.lstat(alias)
            resolved = Path(os.path.realpath(alias))
            target = os.stat(resolved)
        except OSError as exc:
            raise ProfileValidationError(f"required {lane} CLI alias is unavailable") from exc
        if (
            resolved not in allowed_targets
            or not stat.S_ISREG(target.st_mode)
            or target.st_mode & 0o022
            or not os.access(resolved, os.X_OK)
        ):
            raise PathIdentityError(f"required {lane} CLI alias is not bound to an audited executable")
        # A lane path may itself be the audited native executable (``agy`` is
        # installed this way). There is no lexical alias to grant in that case;
        # retain the same regular-file, mode, and executable checks above.
        if stat.S_ISREG(before.st_mode):
            continue
        if not stat.S_ISLNK(before.st_mode):
            raise PathIdentityError(
                f"required {lane} CLI path is neither a regular file nor a symlink"
            )
        aliases.update(
            item for item in _symlink_chain(alias)
            if Path(os.path.realpath(item)) != item
        )
        with resolved.open("rb") as stream:
            first_line = stream.readline(512)
        words = (
            first_line[2:].decode("utf-8", errors="strict").strip().split()
            if first_line.startswith(b"#!")
            else []
        )
        if words:
            if words[0] == "/usr/bin/env" and words[1:] == ["node"]:
                aliases.update(
                    item for item in _symlink_chain(Path("/opt/homebrew/bin/node"))
                    if Path(os.path.realpath(item)) != item
                )
            elif words[0].startswith("/"):
                aliases.update(
                    item for item in _symlink_chain(Path(words[0]))
                    if Path(os.path.realpath(item)) != item
                )
    for alias in tuple(aliases):
        try:
            resolved = Path(os.path.realpath(alias))
            state = os.stat(resolved)
        except OSError as exc:
            raise ProfileValidationError(f"lane runtime alias is unavailable: {alias}") from exc
        if (
            resolved not in allowed_targets
            or not stat.S_ISREG(state.st_mode)
            or state.st_mode & 0o022
            or not os.access(resolved, os.X_OK)
        ):
            raise PathIdentityError(f"lane runtime alias is not bound to an audited executable: {alias}")
    return tuple(sorted(aliases, key=str))


def _homebrew_native_dependencies(
    executable: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    """Resolve exact Homebrew dylib files, versioned roots, and opt aliases."""

    executable = Path(executable)
    runtime_root = executable.parents[1]
    pending = [executable]
    audited: set[Path] = set()
    dependencies: set[Path] = set()
    roots: set[Path] = set()
    aliases: set[Path] = set()
    while pending:
        binary = pending.pop()
        if binary in audited:
            continue
        audited.add(binary)
        completed = subprocess.run(
            ["/usr/bin/otool", "-L", str(binary)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if completed.returncode != 0:
            raise ProfileValidationError("unable to audit Homebrew lane runtime dependencies")
        for line in completed.stdout.splitlines()[1:]:
            reference = line.strip().split(" ", 1)[0]
            if not reference or reference.startswith(("/usr/lib/", "/System/Library/")):
                continue
            if reference.startswith("/opt/homebrew/"):
                alias = Path(reference)
            elif reference.startswith("@loader_path/"):
                alias = binary.parent / reference.removeprefix("@loader_path/")
            elif reference.startswith("@executable_path/"):
                alias = executable.parent / reference.removeprefix("@executable_path/")
            elif reference.startswith("@rpath/"):
                name = reference.removeprefix("@rpath/")
                choices = (
                    binary.parent / name,
                    binary.parent.parent / "lib" / name,
                    runtime_root / "lib" / name,
                )
                alias = next((path for path in choices if path.exists()), Path())
                if alias == Path():
                    raise ProfileValidationError("unresolved lane runtime rpath dependency")
            else:
                raise ProfileValidationError("unreviewed lane runtime dependency origin")
            candidate = Path(os.path.realpath(alias))
            if alias.is_relative_to(Path("/opt/homebrew/opt")):
                parent = alias
                while parent != Path("/opt/homebrew/opt"):
                    aliases.add(parent)
                    parent = parent.parent
            if not candidate.is_relative_to(Path("/opt/homebrew/Cellar")):
                raise ProfileValidationError("lane runtime dependency escaped Homebrew Cellar")
            relative = candidate.relative_to(Path("/opt/homebrew/Cellar"))
            if len(relative.parts) < 3:
                raise ProfileValidationError("lane runtime dependency has no pinned Cellar version")
            root = Path("/opt/homebrew/Cellar") / relative.parts[0] / relative.parts[1]
            root = Path(os.path.realpath(root))
            state = os.stat(root)
            if not stat.S_ISDIR(state.st_mode) or state.st_mode & 0o022:
                raise ProfileValidationError("lane runtime dependency root is mutable")
            roots.add(root)
            dependencies.add(candidate)
            pending.append(candidate)
    return (
        tuple(sorted((*roots, *dependencies), key=str)),
        tuple(sorted(aliases, key=str)),
        tuple(sorted(dependencies, key=str)),
    )


def installed_lane_cli_library_grants(
    *, lanes: Iterable[str] | None = None,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    selected = set(LANE_CLI_PATHS if lanes is None else lanes)
    if not selected.issubset(LANE_CLI_PATHS):
        raise ProfileValidationError("unknown lane library selection")
    if "codex" not in selected:
        return (), (), ()
    node = Path(os.path.realpath(Path("/opt/homebrew/bin/node")))
    return _homebrew_native_dependencies(node)


def installed_lane_cli_read_paths(
    *,
    lanes: Iterable[str] | None = None,
    include_offline: bool = True,
) -> tuple[Path, ...]:
    """Return bounded runtime/package roots needed by the exact CLI files."""

    selected = set(LANE_CLI_PATHS if lanes is None else lanes)
    dependency_reads, _aliases, _libraries = installed_lane_cli_library_grants(
        lanes=selected
    )
    reads: set[Path] = {
        *installed_lane_cli_executable_paths(
            lanes=selected, include_offline=include_offline
        ),
        *dependency_reads,
    }
    if "codex" in selected:
        reads.add(NODE_OPENSSL_CONFIG)
    for alias in LANE_CLI_PATHS.values():
        lane = next(name for name, value in LANE_CLI_PATHS.items() if value == alias)
        if lane not in selected:
            continue
        entrypoint = Path(os.path.realpath(alias))
        if entrypoint.is_relative_to(Path("/opt/homebrew/lib/node_modules")):
            parts = entrypoint.relative_to(Path("/opt/homebrew/lib/node_modules")).parts
            package_depth = 2 if parts and parts[0].startswith("@") else 1
            reads.add(
                Path("/opt/homebrew/lib/node_modules").joinpath(*parts[:package_depth])
            )
        elif entrypoint.is_relative_to(UV_TOOLS_ROOT):
            relative = entrypoint.relative_to(UV_TOOLS_ROOT)
            if len(relative.parts) < 2:
                raise ProfileValidationError(
                    "UV lane entrypoint has no bounded tool distribution root"
                )
            reads.add(UV_TOOLS_ROOT / relative.parts[0])
        interpreter = _shebang_interpreter(entrypoint)
        if interpreter is not None:
            if interpreter.is_relative_to(Path("/opt/homebrew/Cellar")):
                relative = interpreter.relative_to(Path("/opt/homebrew/Cellar"))
                reads.add(Path("/opt/homebrew/Cellar") / relative.parts[0] / relative.parts[1])
            elif interpreter.is_relative_to(UV_PYTHON_ROOT):
                relative = interpreter.relative_to(UV_PYTHON_ROOT)
                if len(relative.parts) < 2:
                    raise ProfileValidationError(
                        "UV lane interpreter has no versioned Python "
                        "distribution root"
                    )
                reads.add(UV_PYTHON_ROOT / relative.parts[0])
            elif interpreter.is_relative_to(UV_ROOT):
                raise ProfileValidationError(
                    "UV lane interpreter is outside the reviewed Python subtree"
                )
    return tuple(sorted(reads, key=str))


def installed_lane_cli_read_literals(
    *,
    lanes: Iterable[str] | None = None,
    include_offline: bool = True,
) -> tuple[Path, ...]:
    literals: set[Path] = set()
    for path in installed_lane_cli_read_paths(
        lanes=lanes, include_offline=include_offline
    ):
        parent = Path(path).parent
        while parent != Path("/"):
            literals.add(parent)
            parent = parent.parent
    return tuple(sorted(literals, key=str))


def _assert_identity_stable(paths: Sequence[NormalizedPath]) -> None:
    for normalized in paths:
        try:
            current = os.stat(normalized.path)
        except OSError as exc:
            raise PathIdentityError(
                f"declared path disappeared before profile render: {normalized.path}"
            ) from exc
        if (current.st_dev, current.st_ino, current.st_mode) != (
            normalized.device,
            normalized.inode,
            normalized.mode,
        ):
            raise PathIdentityError(
                f"declared path changed identity before profile render: {normalized.path}"
            )


def _quote(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ProfileValidationError("SBPL strings may not contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _path_filters(paths: Sequence[NormalizedPath]) -> list[str]:
    filters: list[str] = []
    for item in paths:
        quoted = _quote(str(item.path))
        filters.append(f"  (literal {quoted})")
        if item.is_directory:
            if item.path == Path("/"):
                raise ProfileValidationError("root subpath grants are forbidden")
            filters.append(f"  (subpath {quoted})")
    return filters


def _normalize_denied_subtrees(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Preserve each lexical spelling and its canonical filesystem spelling.

    Denies are allowed to name a currently absent path: aperture ``none`` must
    remain launchable on a host with no vault.  Existing spellings are still
    inode-checked against their realpath so a symlink alias cannot be swapped
    while the profile is compiled.
    """

    denied: set[Path] = set()
    for value in paths:
        raw = Path(value)
        if (
            not raw.is_absolute()
            or raw == Path("/")
            or any(ord(character) < 32 for character in str(raw))
        ):
            raise ProfileValidationError(
                "denied subtree must be an absolute non-root path without "
                "control characters"
            )
        lexical = Path(os.path.normpath(raw))
        canonical = Path(os.path.realpath(lexical))
        if lexical == Path("/") or canonical == Path("/"):
            raise ProfileValidationError("root subtree deny is forbidden")
        try:
            before = os.stat(lexical)
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise ProfileValidationError(
                f"denied subtree is not auditable: {lexical}: {exc}"
            ) from exc
        if before is not None:
            try:
                after = os.stat(canonical)
            except OSError as exc:
                raise ProfileValidationError(
                    f"denied subtree changed during validation: {lexical}"
                ) from exc
            if (
                (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or not stat.S_ISDIR(after.st_mode)
            ):
                raise PathIdentityError(
                    f"denied subtree alias is not bound to one directory: {lexical}"
                )
        denied.update((lexical, canonical))
    return tuple(sorted(denied, key=str))


def _denied_path_filters(paths: Sequence[Path]) -> list[str]:
    filters: list[str] = []
    for path in paths:
        quoted = _quote(str(path))
        filters.extend((f"  (literal {quoted})", f"  (subpath {quoted})"))
    return filters


def _lane_read_aliases(
    paths: Sequence[Path],
    *,
    resolved_reads: Sequence[NormalizedPath],
) -> tuple[Path, ...]:
    """Audit exact Homebrew dependency aliases while retaining lexical names."""

    allowed_targets = {item.path for item in resolved_reads}
    aliases: set[Path] = set()
    alias_root = Path("/opt/homebrew/opt")
    for value in paths:
        raw = Path(value)
        if (
            not raw.is_absolute()
            or any(ord(character) < 32 for character in str(raw))
            or (raw != alias_root and not raw.is_relative_to(alias_root))
        ):
            raise ProfileValidationError("lane read alias must be below Homebrew opt")
        try:
            before = os.stat(raw)
            resolved = Path(os.path.realpath(raw))
            after = os.stat(resolved)
        except OSError as exc:
            raise ProfileValidationError(f"lane read alias is unavailable: {raw}") from exc
        target_is_bound = resolved in allowed_targets or (
            stat.S_ISDIR(after.st_mode)
            and any(target.is_relative_to(resolved) for target in allowed_targets)
        )
        if (
            (before.st_dev, before.st_ino, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_mode)
            or not (stat.S_ISREG(after.st_mode) or stat.S_ISDIR(after.st_mode))
            or not target_is_bound
        ):
            raise PathIdentityError("lane read alias is not bound to an audited file")
        aliases.add(raw)
    return tuple(sorted(aliases, key=str))


def _render_rule(
    effect: str,
    operation: str,
    filters: Sequence[str],
) -> list[str]:
    if not filters:
        return []
    if effect not in {"allow", "deny"}:
        raise ProfileValidationError("Seatbelt rule effect is invalid")
    return [f"({effect} {operation}", *filters[:-1], filters[-1] + ")"]


def _render_grant(operation: str, filters: Sequence[str]) -> list[str]:
    return _render_rule("allow", operation, filters)


def _render_profile(
    *,
    read_paths: Sequence[NormalizedPath],
    lane_read_literal_paths: Sequence[NormalizedPath],
    lane_read_alias_paths: Sequence[Path],
    lane_library_paths: Sequence[NormalizedPath],
    write_paths: Sequence[NormalizedPath],
    executable_paths: Sequence[NormalizedPath],
    executable_alias_paths: Sequence[Path],
    allow_fork: bool,
    allow_sysctl_read: bool,
    broker_port: int | None,
    denied_subtrees: Sequence[Path],
) -> str:
    lines = ["(version 1)", "(deny default)"]
    read_filters = [
        f"  (literal {_quote(str(path))})" for path in RUNTIME_READ_LITERALS
    ]
    read_filters.extend(_path_filters(read_paths))
    # Traversing a canonical writable scope (for example one rooted below
    # /private/var) needs metadata reads for its exact ancestors. These are
    # literal grants only; they do not expose sibling contents.
    for writable in write_paths:
        for parent in writable.path.parents:
            if parent == Path("/"):
                break
            read_filters.append(f"  (literal {_quote(str(parent))})")
    read_filters.extend(
        f"  (literal {_quote(str(item.path))})"
        for item in lane_read_literal_paths
    )
    for alias in executable_alias_paths:
        read_filters.append(f"  (literal {_quote(str(alias))})")
        for parent in alias.parents:
            if parent == Path("/"):
                break
            read_filters.append(f"  (literal {_quote(str(parent))})")
    for path in lane_read_alias_paths:
        read_filters.append(f"  (literal {_quote(str(path))})")
        if path.is_dir():
            read_filters.append(f"  (subpath {_quote(str(path))})")
    lines.extend(_render_grant("file-read*", read_filters))
    library_filters = _path_filters(lane_library_paths)
    for path in lane_read_alias_paths:
        library_filters.append(f"  (literal {_quote(str(path))})")
        if path.is_dir():
            library_filters.append(f"  (subpath {_quote(str(path))})")
    lines.extend(_render_grant("file-map-executable", library_filters))
    lines.extend(_render_grant("file-write*", _path_filters(write_paths)))
    for executable in executable_paths:
        lines.append(
            f"(allow process-exec (literal {_quote(str(executable.path))}))"
        )
    for alias in executable_alias_paths:
        lines.append(f"(allow process-exec (literal {_quote(str(alias))}))")
    if allow_fork:
        lines.append("(allow process-fork)")
    if allow_sysctl_read:
        lines.append("(allow sysctl-read)")
    if broker_port is not None:
        lines.append(
            "(allow network-outbound "
            f'(remote tcp "localhost:{broker_port}"))'
        )
    # Seatbelt resolves conflicts by the last matching rule.  Keep private
    # subtree denials after every broad runtime/worktree grant so an allowed
    # ancestor can never reopen the vault through its canonical or lexical
    # spelling.
    denied_filters = _denied_path_filters(denied_subtrees)
    lines.extend(_render_rule("deny", "file-read*", denied_filters))
    lines.extend(_render_rule("deny", "file-write*", denied_filters))
    return "\n".join(lines) + "\n"


def compile_profile(
    spec: ProfileSpec,
    *,
    compatibility_verifier: Callable[
        [], HostCompatibility
    ] = verify_sandbox_compatibility,
) -> CompiledProfile:
    """Compile a deterministic profile only after the host gate succeeds."""

    compatibility = compatibility_verifier()
    if not isinstance(compatibility, HostCompatibility):
        raise SandboxCompatibilityError("compatibility verifier returned no attestation")
    if not isinstance(spec.allow_fork, bool):
        raise ProfileValidationError("allow_fork must be a boolean")
    if not isinstance(spec.allow_sysctl_read, bool):
        raise ProfileValidationError("allow_sysctl_read must be a boolean")
    if spec.broker_port is not None and (
        isinstance(spec.broker_port, bool)
        or not isinstance(spec.broker_port, int)
        or not 1 <= spec.broker_port <= 65535
    ):
        raise ProfileValidationError(
            f"broker port must be an integer in 1..65535, got {spec.broker_port!r}"
        )

    selection = _LANE_LAUNCH_SELECTION.get()
    selected_lanes = (() if selection is None or selection.lane is None else (selection.lane,))
    include_offline = bool(selection and selection.offline_probe)
    lane_cli_executables = (
        installed_lane_cli_executable_paths(
            lanes=selected_lanes,
            include_offline=include_offline,
            include_broker_relay=bool(selection and selection.broker_relay),
        )
        if selection is not None
        else ()
    )
    dependency_reads, dependency_aliases, dependency_libraries = (
        installed_lane_cli_library_grants(lanes=selected_lanes)
        if selection is not None
        else ((), (), ())
    )
    lane_runtime_reads = (
        installed_lane_cli_read_paths(
            lanes=selected_lanes, include_offline=include_offline
        )
        if selection is not None
        else ()
    )
    runtime = _normalize_many(RUNTIME_READ_PATHS)
    normalized_lane_runtime_reads = _normalize_many(lane_runtime_reads)
    if any(
        item.path == Path("/")
        for item in normalized_lane_runtime_reads
    ):
        raise ProfileValidationError("lane runtime read scope may not be root")
    declared_reads = _normalize_many(spec.read_paths)
    read_literals = _normalize_many(
        (
            *spec.lane_read_literal_paths,
            *(
                installed_lane_cli_read_literals(
                    lanes=selected_lanes, include_offline=include_offline
                )
                if selection is not None
                else ()
            ),
        )
    )
    if any(item.path == Path("/") for item in read_literals):
        raise ProfileValidationError("lane read literal scope may not be root")
    writes = _normalize_many(spec.write_paths)
    denied_subtrees = _normalize_denied_subtrees(
        (
            *spec.denied_subtrees,
            *(selection.denied_subtrees if selection is not None else ()),
        )
    )
    executables = _normalize_many(
        (*spec.executable_paths, *spec.lane_executable_paths, *lane_cli_executables)
    )
    executable_aliases = (
        installed_lane_cli_executable_aliases(
            executables, lanes=selected_lanes
        )
        if selection is not None and selected_lanes
        else ()
    )
    libraries = _normalize_many((*spec.lane_library_paths, *dependency_libraries))
    if any(item.path == Path("/") for item in declared_reads):
        raise ProfileValidationError("root read scope is forbidden")
    if any(item.path == Path("/") for item in writes):
        raise ProfileValidationError("root write scope is forbidden")
    if any(
        not stat.S_ISREG(item.mode)
        or item.mode & 0o022
        or not os.access(item.path, os.X_OK)
        for item in executables
    ):
        raise ProfileValidationError(
            "executable grants must name executable regular files"
        )

    reads = _normalize_many(
        tuple(item.path for item in runtime)
        + tuple(item.path for item in normalized_lane_runtime_reads)
        + tuple(item.path for item in declared_reads)
        + tuple(item.path for item in writes)
        + tuple(item.path for item in executables)
        + tuple(item.path for item in libraries)
    )
    if any(
        item.path not in {read.path for read in reads}
        and not any(read.path.is_relative_to(item.path) for read in reads)
        for item in read_literals
    ):
        raise ProfileValidationError(
            "lane read literal must bind an audited read path ancestor"
        )
    lane_read_aliases = _lane_read_aliases(
        (*spec.lane_read_alias_paths, *dependency_aliases),
        resolved_reads=reads,
    )
    if any(not stat.S_ISREG(item.mode) for item in libraries):
        raise ProfileValidationError("lane libraries must name regular files")
    _assert_identity_stable(
        (*reads, *read_literals, *writes, *executables, *libraries)
    )
    text = _render_profile(
        read_paths=reads,
        lane_read_literal_paths=read_literals,
        lane_read_alias_paths=lane_read_aliases,
        lane_library_paths=libraries,
        write_paths=writes,
        executable_paths=executables,
        executable_alias_paths=executable_aliases,
        # Codex's reviewed Node wrapper, native agy, and Grok need to fork
        # bounded child processes. Ordinary profiles continue to honor their
        # requested policy.
        allow_fork=(
            spec.allow_fork
            or bool(set(selected_lanes) & {"codex", "gemini", "grok"})
            or bool(selection and selection.broker_relay)
        ),
        allow_sysctl_read=spec.allow_sysctl_read,
        broker_port=spec.broker_port,
        denied_subtrees=denied_subtrees,
    )
    return CompiledProfile(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        compatibility=compatibility,
    )


__all__ = [
    "CANONICAL_SANDBOX_EXEC",
    "BROKER_RELAY_PYTHON",
    "CODEX_NATIVE_EXECUTABLE",
    "DEFAULT_LANE_PATH",
    "GROK_BIN_ROOT",
    "HOST_HOME",
    "KNOWN_MACOS_BUILDS",
    "LANE_CLI_PATHS",
    "LOCAL_BIN_ROOT",
    "OFFLINE_LAUNCH_EXECUTABLES",
    "UV_PYTHON_ROOT",
    "UV_ROOT",
    "UV_TOOLS_ROOT",
    "CompiledProfile",
    "HostCompatibility",
    "NormalizedPath",
    "PathIdentityError",
    "ProfileSpec",
    "ProfileValidationError",
    "SandboxCompatibilityError",
    "compile_profile",
    "installed_lane_cli_executable_paths",
    "installed_lane_cli_executable_aliases",
    "installed_lane_cli_library_grants",
    "installed_lane_cli_read_paths",
    "installed_lane_cli_read_literals",
    "scoped_lane_launch_profile",
    "normalize_realpath",
    "verify_sandbox_compatibility",
]
