#!/usr/bin/env python3
"""Shared publication path-policy matcher for the gate and tree projector."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class PolicyError(ValueError):
    """The canonical policy is absent, malformed, or internally unsafe."""


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a small, anchored POSIX glob language with real globstar support."""
    if not pattern or pattern.startswith("/") or "\0" in pattern or "\\" in pattern:
        raise PolicyError(f"invalid policy pattern: {pattern!r}")

    parts: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    parts.append("(?:.*/)?")
                    index += 1
                else:
                    parts.append(".*")
                continue
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(char))
        index += 1
    parts.append("$")
    return re.compile("".join(parts))


def _normalize_path(path: str) -> str:
    if not path or path.startswith("/") or "\0" in path:
        raise PolicyError(f"invalid tracked path: {path!r}")
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise PolicyError(f"non-canonical tracked path: {path!r}")
    return path


@dataclass(frozen=True)
class Policy:
    version: int
    public_bounty_status: str
    public_bounty_notice: str
    public_bounty_withheld: tuple[str, ...]
    public_exceptions: tuple[str, ...]
    deny: tuple[str, ...]
    public: tuple[str, ...]
    _exception_regexes: tuple[re.Pattern[str], ...]
    _deny_regexes: tuple[re.Pattern[str], ...]
    _public_regexes: tuple[re.Pattern[str], ...]

    def decision(self, path: str) -> "PathDecision":
        """Return the classification and the exact policy rule that decided it."""
        normalized = _normalize_path(path)
        for pattern, regex in zip(self.public_exceptions, self._exception_regexes):
            if regex.fullmatch(normalized):
                return PathDecision("public", "public_exceptions", pattern)
        for pattern, regex in zip(self.deny, self._deny_regexes):
            if regex.fullmatch(normalized):
                return PathDecision("private", "deny", pattern)
        for pattern, regex in zip(self.public, self._public_regexes):
            if regex.fullmatch(normalized):
                return PathDecision("public", "public", pattern)
        return PathDecision("unknown", "default_deny", "<no matching rule>")

    def classify(self, path: str) -> str:
        return self.decision(path).classification


@dataclass(frozen=True)
class PathDecision:
    classification: str
    policy_section: str
    policy_pattern: str


def _string_list(document: object, key: str) -> tuple[str, ...]:
    if not isinstance(document, dict) or key not in document:
        raise PolicyError(f"policy is missing {key!r}")
    value = document[key]
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise PolicyError(f"policy {key!r} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise PolicyError(f"policy {key!r} contains duplicate patterns")
    return tuple(value)


def _public_bounty_state(document: object) -> tuple[str, str, tuple[str, ...]]:
    if not isinstance(document, dict):
        raise PolicyError("policy document must be an object")
    state = document.get("public_capability_state")
    if not isinstance(state, dict) or not isinstance(state.get("bounty"), dict):
        raise PolicyError("policy is missing public_capability_state.bounty")
    bounty = state["bounty"]
    status = bounty.get("status")
    notice = bounty.get("notice")
    withheld = bounty.get("withheld")
    if not isinstance(status, str) or not status.strip():
        raise PolicyError("public bounty capability status must be a non-empty string")
    if not isinstance(notice, str) or not notice.strip():
        raise PolicyError("public bounty capability notice must be a non-empty string")
    if (
        not isinstance(withheld, list)
        or not withheld
        or not all(isinstance(item, str) and item.strip() for item in withheld)
        or len(withheld) != len(set(withheld))
    ):
        raise PolicyError("public bounty withheld components must be unique non-empty strings")
    return status, notice, tuple(withheld)


def load_policy(path: Path | str) -> Policy:
    policy_path = Path(path)
    try:
        document = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot load policy {policy_path}: {error}") from error

    if not isinstance(document, dict) or document.get("version") != 1:
        raise PolicyError("policy version must be exactly 1")
    exceptions = _string_list(document, "public_exceptions")
    deny = _string_list(document, "deny")
    public = _string_list(document, "public")
    bounty_status, bounty_notice, bounty_withheld = _public_bounty_state(document)
    return Policy(
        version=1,
        public_bounty_status=bounty_status,
        public_bounty_notice=bounty_notice,
        public_bounty_withheld=bounty_withheld,
        public_exceptions=exceptions,
        deny=deny,
        public=public,
        _exception_regexes=tuple(_glob_regex(item) for item in exceptions),
        _deny_regexes=tuple(_glob_regex(item) for item in deny),
        _public_regexes=tuple(_glob_regex(item) for item in public),
    )


def read_nul_paths(path: Path | str) -> list[str]:
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise PolicyError(f"cannot read tracked-path list {path}: {error}") from error
    if raw and not raw.endswith(b"\0"):
        raise PolicyError("tracked-path list is not NUL terminated")
    chunks = raw.split(b"\0")
    if chunks and chunks[-1] == b"":
        chunks.pop()
    return [chunk.decode("utf-8", errors="surrogateescape") for chunk in chunks]


def audit_paths(policy: Policy, paths: Iterable[str]) -> tuple[list[str], list[str]]:
    denied: list[str] = []
    unknown: list[str] = []
    for path in paths:
        classification = policy.classify(path)
        if classification == "private":
            denied.append(path)
        elif classification == "unknown":
            unknown.append(path)
    return denied, unknown


def _json_path(path: str) -> str:
    return json.dumps(path, ensure_ascii=True)


def _audit_command(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    denied, unknown = audit_paths(policy, read_nul_paths(args.tracked_nul))
    print(f"Policy version: {policy.version}")
    print(f"Denied tracked paths: {len(denied)}")
    for path in denied:
        decision = policy.decision(path)
        print(
            f"- path={_json_path(path)} classification={decision.classification} "
            f"policy_section={decision.policy_section} "
            f"policy_pattern={_json_path(decision.policy_pattern)}"
        )
    print(f"Unknown tracked paths: {len(unknown)}")
    for path in unknown:
        decision = policy.decision(path)
        print(
            f"- path={_json_path(path)} classification={decision.classification} "
            f"policy_section={decision.policy_section} "
            f"policy_pattern={_json_path(decision.policy_pattern)}"
        )
    return 1 if denied or unknown else 0


def _classify_command(args: argparse.Namespace) -> int:
    print(load_policy(args.policy).classify(args.path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="audit a NUL-delimited tracked path list")
    audit.add_argument("--policy", required=True)
    audit.add_argument("--tracked-nul", required=True)
    audit.set_defaults(handler=_audit_command)

    classify = subparsers.add_parser("classify", help="classify one repository-relative path")
    classify.add_argument("--policy", required=True)
    classify.add_argument("path")
    classify.set_defaults(handler=_classify_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except PolicyError as error:
        print(f"path-policy error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
