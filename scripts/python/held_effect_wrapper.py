#!/usr/bin/env python3
"""Right-sized wrappers for the four operator-held effect families.

This module is intentionally not a generic command executor.  Each public
entrypoint derives a semantic target from structured arguments, calls the
settled ``held_action_gate.authorize()`` immediately before its effect, and
then invokes only that effect.  The one-shot token is therefore consumed even
when the external operation subsequently fails.

These wrappers are the integration boundary for trusted tasks; they do not
claim that an arbitrary trusted local process is technically unable to bypass
them.  The strict/full-executor launch mode remains available for untrusted
inputs that require that stronger property.
"""

from __future__ import annotations

import argparse
from dataclasses import fields
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
from typing import Callable, TypeVar

from held_action_gate import (
    HeldActionDenied,
    HeldActionStore,
    HeldActionToken,
    authorize,
)


T = TypeVar("T")
GIT = Path("/usr/bin/git")


def _single_line(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        raise ValueError(f"invalid {label}")
    return value


def _git_atom(value: str, label: str) -> str:
    result = _single_line(value, label)
    if result.startswith("-") or any(character.isspace() for character in result):
        raise ValueError(f"invalid {label}")
    return result


def _repo_root(repo: Path) -> Path:
    resolved = Path(repo).resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("repository path is not a directory")
    return resolved


def git_push_target(*, repo: Path, remote: str, refspec: str) -> str:
    """Return the exact approval target used by :func:`git_push`."""

    return f"{_repo_root(repo)}:{_git_atom(remote, 'remote')}:{_git_atom(refspec, 'refspec')}"


def git_push(
    *,
    repo: Path,
    remote: str,
    refspec: str,
    task_id: str,
    attempt_id: str,
    token: HeldActionToken | None,
    store: HeldActionStore,
    signing_key: bytes,
    now: int,
    runner: Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Authorize and perform exactly one structured ``git push``."""

    repository = _repo_root(repo)
    remote_name = _git_atom(remote, "remote")
    ref = _git_atom(refspec, "refspec")
    target = f"{repository}:{remote_name}:{ref}"
    command = (
        str(GIT),
        "-C",
        str(repository),
        "push",
        "--",
        remote_name,
        ref,
    )
    authorize(
        category="public-push",
        target=target,
        task_id=task_id,
        attempt_id=attempt_id,
        token=token,
        store=store,
        signing_key=signing_key,
        now=now,
    )
    effect_runner = runner or (
        lambda argv: subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    )
    return effect_runner(command)


def _delete_target(*, repo: Path, relative_path: str) -> tuple[Path, str]:
    repository = _repo_root(repo)
    relative = PurePosixPath(_single_line(relative_path, "relative path"))
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        raise ValueError("delete path must be a repository-relative file")
    candidate = repository.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise ValueError("delete target must not be a symlink")
    resolved_parent = candidate.parent.resolve(strict=True)
    if os.path.commonpath((str(resolved_parent), str(repository))) != str(repository):
        raise ValueError("delete target escapes the repository")
    return candidate, f"{repository}:refs/heads/main:{relative.as_posix()}"


def delete_from_main(
    *,
    repo: Path,
    relative_path: str,
    task_id: str,
    attempt_id: str,
    token: HeldActionToken | None,
    store: HeldActionStore,
    signing_key: bytes,
    now: int,
    remover: Callable[[Path], T] | None = None,
) -> T | None:
    """Authorize deletion of one exact path from the ``main`` ref."""

    candidate, target = _delete_target(repo=repo, relative_path=relative_path)
    authorize(
        category="delete-from-main",
        target=target,
        task_id=task_id,
        attempt_id=attempt_id,
        token=token,
        store=store,
        signing_key=signing_key,
        now=now,
    )
    effect = remover or (lambda path: path.unlink())
    return effect(candidate)


def provider_billing(
    *,
    provider: str,
    account: str,
    operation: str,
    task_id: str,
    attempt_id: str,
    token: HeldActionToken | None,
    store: HeldActionStore,
    signing_key: bytes,
    now: int,
    performer: Callable[[], T],
) -> T:
    """Authorize one named provider/account billing or spend operation."""

    target = ":".join(
        (
            _single_line(provider, "provider"),
            _single_line(account, "account"),
            _single_line(operation, "billing operation"),
        )
    )
    authorize(
        category="spend",
        target=target,
        task_id=task_id,
        attempt_id=attempt_id,
        token=token,
        store=store,
        signing_key=signing_key,
        now=now,
    )
    return performer()


def outreach(
    *,
    channel: str,
    recipient: str,
    campaign: str,
    task_id: str,
    attempt_id: str,
    token: HeldActionToken | None,
    store: HeldActionStore,
    signing_key: bytes,
    now: int,
    performer: Callable[[], T],
) -> T:
    """Authorize one exact recipient/campaign outreach operation."""

    target = ":".join(
        (
            _single_line(channel, "channel"),
            _single_line(recipient, "recipient"),
            _single_line(campaign, "campaign"),
        )
    )
    authorize(
        category="outreach",
        target=target,
        task_id=task_id,
        attempt_id=attempt_id,
        token=token,
        store=store,
        signing_key=signing_key,
        now=now,
    )
    return performer()


def _read_exact_fd(fd: int, *, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(fd, min(4096, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    os.close(fd)
    payload = b"".join(chunks)
    if not payload or len(payload) > maximum:
        raise HeldActionDenied("held-action credential FD has invalid content")
    return payload


def _token_from_fd(fd: int | None) -> HeldActionToken | None:
    if fd is None:
        return None
    try:
        payload = json.loads(_read_exact_fd(fd, maximum=8192).decode("utf-8"))
        allowed = {field.name for field in fields(HeldActionToken)}
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise ValueError("wrong token fields")
        return HeldActionToken(**payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HeldActionDenied(f"held-action token FD is invalid: {exc}") from exc


def _key_from_fd(fd: int | None, *, token_present: bool) -> bytes:
    if fd is None:
        if token_present:
            raise HeldActionDenied("held-action signing-key FD is required with a token")
        # Missing-token denial occurs before signature verification.  This
        # inert value is never authority and is not used to authorize.
        return b"\x00" * 32
    try:
        key = _read_exact_fd(fd, maximum=64)
    except OSError as exc:
        raise HeldActionDenied(f"held-action signing-key FD is invalid: {exc}") from exc
    if len(key) < 16:
        raise HeldActionDenied("held-action signing-key FD is too short")
    return key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operator-held effect wrapper (structured git-push CLI)"
    )
    subparsers = parser.add_subparsers(dest="effect", required=True)
    push = subparsers.add_parser("git-push")
    push.add_argument("--repo", required=True, type=Path)
    push.add_argument("--remote", required=True)
    push.add_argument("--refspec", required=True)
    push.add_argument("--task-id", required=True)
    push.add_argument("--attempt-id", required=True)
    push.add_argument("--state-dir", required=True, type=Path)
    push.add_argument("--token-fd", type=int)
    push.add_argument("--signing-key-fd", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    category = "public-push"
    try:
        token = _token_from_fd(args.token_fd)
        signing_key = _key_from_fd(
            args.signing_key_fd, token_present=token is not None
        )
        completed = git_push(
            repo=args.repo,
            remote=args.remote,
            refspec=args.refspec,
            task_id=args.task_id,
            attempt_id=args.attempt_id,
            token=token,
            store=HeldActionStore(args.state_dir),
            signing_key=signing_key,
            now=int(time.time()),
        )
    except (HeldActionDenied, ValueError, OSError) as exc:
        print(
            json.dumps(
                {"status": "denied", "category": category, "reason": str(exc)},
                sort_keys=True,
            )
        )
        return 74
    print(
        json.dumps(
            {
                "status": "executed",
                "category": category,
                "returncode": completed.returncode,
            },
            sort_keys=True,
        )
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "delete_from_main",
    "git_push",
    "git_push_target",
    "outreach",
    "provider_billing",
]
