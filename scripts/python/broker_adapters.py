#!/usr/bin/env python3
"""Provider-compatible task-local wrappers for the credential broker."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import shlex
import stat
from urllib import parse


SUPPORTED_LANES = {"claude", "kimi", "codex", "gemini"}


@dataclass(frozen=True)
class AdapterBundle:
    lane: str
    task_home: Path
    base_environment: dict[str, str]
    files: dict[Path, str]
    argv: tuple[str, ...]


def _validated_broker_url(value: str) -> str:
    parsed = parse.urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("broker URL must be loopback HTTP")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("broker URL must use a literal loopback address") from exc
    if not address.is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("broker URL must be loopback-only")
    if parsed.path not in ("", "/"):
        raise ValueError("broker URL must not contain a path")
    return value.rstrip("/")


def _validated_home(task_home: Path) -> Path:
    home = Path(task_home)
    if not home.is_absolute() or Path(os.path.realpath(home)) != home:
        raise ValueError("task HOME must be canonical and absolute")
    state = os.lstat(home)
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ValueError("task HOME must be a no-follow directory")
    return home


def build_adapter(
    lane: str,
    broker_url: str,
    opaque_handle: str,
    task_home: Path,
    executable: Path,
) -> AdapterBundle:
    if lane not in SUPPORTED_LANES:
        raise ValueError("unsupported broker lane")
    base_url = _validated_broker_url(broker_url)
    if (
        not isinstance(opaque_handle, str)
        or not opaque_handle.startswith("cb1.")
        or len(opaque_handle) > 256
        or any(character in opaque_handle for character in ("\n", "\r", "\x00"))
    ):
        raise ValueError("invalid opaque handle")
    home = _validated_home(task_home)
    program = Path(executable)
    if not program.is_absolute():
        raise ValueError("provider executable must be absolute")

    adapter_dir = home / ".broker-adapter"
    handle_path = adapter_dir / f"{lane}.handle"
    wrapper_path = adapter_dir / f"{lane}-launch.sh"
    endpoint = f"{base_url}/v1/model/{lane}"
    exports: dict[str, str]
    files: dict[Path, str] = {handle_path: opaque_handle + "\n"}

    if lane == "claude":
        exports = {"ANTHROPIC_BASE_URL": endpoint, "ANTHROPIC_API_KEY": "$BROKER_HANDLE"}
    elif lane == "kimi":
        exports = {
            "KIMI_BASE_URL": endpoint,
            "KIMI_API_KEY": "$BROKER_HANDLE",
            "OPENAI_BASE_URL": endpoint,
            "OPENAI_API_KEY": "$BROKER_HANDLE",
        }
    elif lane == "codex":
        codex_home = home / ".codex"
        config_path = codex_home / "config.toml"
        files[config_path] = (
            'model_provider = "v2_broker"\n'
            '[model_providers.v2_broker]\n'
            f'base_url = "{endpoint}"\n'
            'env_key = "CODEX_BROKER_HANDLE"\n'
            'wire_api = "responses"\n'
        )
        exports = {"CODEX_HOME": str(codex_home), "CODEX_BROKER_HANDLE": "$BROKER_HANDLE"}
    else:
        gemini_home = home / ".gemini"
        exports = {
            "GEMINI_API_KEY": "$BROKER_HANDLE",
            "GEMINI_CLI_HOME": str(gemini_home),
            "GEMINI_CLI_NO_RELAUNCH": "true",
            "GOOGLE_GEMINI_BASE_URL": endpoint,
        }

    lines = [
        "#!/bin/sh",
        "set -eu",
        f"IFS= read -r BROKER_HANDLE < {shlex.quote(str(handle_path))}",
        "export BROKER_HANDLE",
    ]
    for key, value in exports.items():
        rendered = '"$BROKER_HANDLE"' if value == "$BROKER_HANDLE" else shlex.quote(value)
        lines.append(f"export {key}={rendered}")
    lines.append(f"exec {shlex.quote(str(program))} \"$@\"")
    files[wrapper_path] = "\n".join(lines) + "\n"
    return AdapterBundle(
        lane=lane,
        task_home=home,
        base_environment={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        files=files,
        argv=("/bin/sh", str(wrapper_path)),
    )


def _open_parent_dir(
    root: Path,
    relative_parent: Path,
    expected_root: tuple[int, int],
) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    try:
        opened_root = os.fstat(descriptor)
        if (opened_root.st_dev, opened_root.st_ino) != expected_root:
            raise RuntimeError("task HOME identity changed before materialization")
        for part in relative_parent.parts:
            if part in ("", ".", ".."):
                raise RuntimeError("invalid adapter path component")
            try:
                os.mkdir(part, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def materialize_adapter(bundle: AdapterBundle) -> None:
    home = _validated_home(bundle.task_home)
    home_state = os.lstat(home)
    root_identity = (home_state.st_dev, home_state.st_ino)
    for path, content in sorted(bundle.files.items(), key=lambda item: str(item[0])):
        if not path.is_absolute() or not path.is_relative_to(home):
            raise RuntimeError("adapter file escapes task HOME")
        parent_fd = _open_parent_dir(home, path.parent.relative_to(home), root_identity)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            os.close(parent_fd)
            raise RuntimeError(f"exclusive no-follow adapter write failed: {path}: {exc}") from exc
        try:
            payload = content.encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o700 if path.name.endswith("-launch.sh") else 0o600)
        finally:
            os.close(descriptor)
            os.close(parent_fd)
