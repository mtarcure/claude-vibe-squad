#!/usr/bin/env python3
"""Deterministic compiler for the role context given to a fresh model CLI.

The compiler deliberately hashes content rather than source paths.  A role can
therefore be materialized in a per-task worktree without changing its identity,
while any change to the canonical role, lane overlay, or launch metadata does.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata


ROLE_CONTEXT_SCHEMA = "compiled-role-context/v1"


class RoleContextError(ValueError):
    """Role inputs or a compiled role-context packet are invalid."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _normalize_markdown(raw: bytes, label: str) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RoleContextError(f"{label} is not UTF-8") from exc
    if "\x00" in text:
        raise RoleContextError(f"{label} contains a NUL byte")
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def _read_stable(path: Path, label: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    try:
        before = candidate.stat()
        raw = candidate.read_bytes()
        after = candidate.stat()
    except OSError as exc:
        raise RoleContextError(f"cannot read {label}: {candidate}: {exc}") from exc
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RoleContextError(f"{label} changed while it was compiled")
    return _normalize_markdown(raw, label)


def _validate_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in ("\x00", "\n", "\r"))
    ):
        raise RoleContextError(f"invalid {label}")


@dataclass(frozen=True)
class CompiledRoleContext:
    schema: str
    specialist: str
    lane: str
    mode_profile: str
    canonical_role: str
    lane_overlay: str
    canonical_role_sha256: str
    lane_overlay_sha256: str
    prompt: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "specialist": self.specialist,
            "lane": self.lane,
            "mode_profile": self.mode_profile,
            "canonical_role": self.canonical_role,
            "lane_overlay": self.lane_overlay,
            "canonical_role_sha256": self.canonical_role_sha256,
            "lane_overlay_sha256": self.lane_overlay_sha256,
            "prompt": self.prompt,
            "sha256": self.sha256,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict()).decode("ascii")


def _unsigned_payload(context: CompiledRoleContext) -> dict[str, str]:
    payload = context.to_dict()
    payload.pop("sha256")
    return payload


def compile_role_context(
    canonical_role_path: Path,
    lane_overlay_path: Path,
    *,
    specialist: str,
    lane: str,
    mode_profile: str = "project",
) -> CompiledRoleContext:
    """Compile canonical role and lane overlay into one deterministic packet."""

    _validate_identifier(specialist, "specialist")
    _validate_identifier(lane, "lane")
    _validate_identifier(mode_profile, "mode/profile")
    canonical_role = _read_stable(Path(canonical_role_path), "canonical role")
    lane_overlay = _read_stable(Path(lane_overlay_path), "lane overlay")
    prompt = (
        f"<!-- {ROLE_CONTEXT_SCHEMA} -->\n"
        f"<!-- specialist:{specialist} lane:{lane} mode:{mode_profile} -->\n\n"
        "## Canonical specialist role\n\n"
        f"{canonical_role}\n"
        "## Lane overlay\n\n"
        f"{lane_overlay}"
    )
    partial = CompiledRoleContext(
        schema=ROLE_CONTEXT_SCHEMA,
        specialist=specialist,
        lane=lane,
        mode_profile=mode_profile,
        canonical_role=canonical_role,
        lane_overlay=lane_overlay,
        canonical_role_sha256=_sha256(canonical_role),
        lane_overlay_sha256=_sha256(lane_overlay),
        prompt=prompt,
        sha256="",
    )
    digest = hashlib.sha256(_canonical_json(_unsigned_payload(partial))).hexdigest()
    return CompiledRoleContext(**{**partial.__dict__, "sha256": digest})


def verify_role_context(context: CompiledRoleContext) -> CompiledRoleContext:
    """Reject a role-context packet if any content or binding was changed."""

    if not isinstance(context, CompiledRoleContext):
        raise RoleContextError("compiled role context has the wrong type")
    if context.schema != ROLE_CONTEXT_SCHEMA:
        raise RoleContextError("unsupported role-context schema")
    for value, label in (
        (context.specialist, "specialist"),
        (context.lane, "lane"),
        (context.mode_profile, "mode/profile"),
    ):
        _validate_identifier(value, label)
    if context.canonical_role_sha256 != _sha256(context.canonical_role):
        raise RoleContextError("canonical role hash mismatch")
    if context.lane_overlay_sha256 != _sha256(context.lane_overlay):
        raise RoleContextError("lane overlay hash mismatch")
    expected_prompt = (
        f"<!-- {ROLE_CONTEXT_SCHEMA} -->\n"
        f"<!-- specialist:{context.specialist} lane:{context.lane} mode:{context.mode_profile} -->\n\n"
        "## Canonical specialist role\n\n"
        f"{context.canonical_role}\n"
        "## Lane overlay\n\n"
        f"{context.lane_overlay}"
    )
    if context.prompt != expected_prompt:
        raise RoleContextError("compiled prompt hash input mismatch")
    expected_hash = hashlib.sha256(_canonical_json(_unsigned_payload(context))).hexdigest()
    if context.sha256 != expected_hash:
        raise RoleContextError("compiled role-context hash mismatch")
    return context


__all__ = [
    "ROLE_CONTEXT_SCHEMA",
    "RoleContextError",
    "CompiledRoleContext",
    "compile_role_context",
    "verify_role_context",
]
