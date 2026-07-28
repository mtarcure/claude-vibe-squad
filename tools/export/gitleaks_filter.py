#!/usr/bin/env python3
"""Filter gitleaks JSON by exact rule, repository path, and secret SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class FilterError(RuntimeError):
    """The raw scanner report or exact-fingerprint policy is unsafe to use."""


@dataclass(frozen=True)
class Fingerprint:
    rule_id: str
    path: str
    secret_sha256: str


def _load_allowlist(path: Path) -> set[Fingerprint]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FilterError(f"cannot load gitleaks fingerprint allowlist {path}: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise FilterError("gitleaks fingerprint allowlist version must be exactly 1")
    entries = document.get("allowed")
    if not isinstance(entries, list):
        raise FilterError("gitleaks fingerprint allowlist 'allowed' must be a list")
    allowed: set[Fingerprint] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FilterError(f"gitleaks fingerprint entry {index} must be an object")
        rule_id = entry.get("rule_id")
        relative_path = entry.get("path")
        digest = entry.get("sha256")
        reason = entry.get("reason")
        if (
            not isinstance(rule_id, str)
            or not rule_id
            or not isinstance(relative_path, str)
            or not relative_path
            or PurePosixPath(relative_path).is_absolute()
            or ".." in PurePosixPath(relative_path).parts
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise FilterError(f"gitleaks fingerprint entry {index} is malformed")
        fingerprint = Fingerprint(rule_id, relative_path, digest)
        if fingerprint in allowed:
            raise FilterError(f"duplicate gitleaks fingerprint entry {index}")
        allowed.add(fingerprint)
    return allowed


def _relative_finding_path(root: Path, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise FilterError("gitleaks finding has no file path")
    finding_path = Path(value)
    if finding_path.is_absolute():
        try:
            finding_path = finding_path.resolve().relative_to(root)
        except (OSError, ValueError) as error:
            raise FilterError(f"gitleaks finding escapes scan root: {value}") from error
    normalized = PurePosixPath(finding_path.as_posix())
    if normalized.is_absolute() or ".." in normalized.parts:
        raise FilterError(f"gitleaks finding path is non-canonical: {value}")
    return normalized.as_posix()


def filter_report(
    *,
    root: Path,
    report_path: Path,
    allowlist_path: Path,
) -> tuple[list[dict[str, object]], int, int]:
    allowed = _load_allowlist(allowlist_path)
    try:
        findings = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FilterError(f"cannot load raw gitleaks report {report_path}: {error}") from error
    if not isinstance(findings, list):
        raise FilterError("raw gitleaks report must be a JSON list")

    unresolved: list[dict[str, object]] = []
    allowed_count = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise FilterError(f"gitleaks finding {index} must be an object")
        rule_id = finding.get("RuleID")
        secret = finding.get("Secret")
        if not isinstance(rule_id, str) or not rule_id or not isinstance(secret, str) or not secret:
            raise FilterError(f"gitleaks finding {index} omits rule or secret")
        relative_path = _relative_finding_path(root, finding.get("File"))
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        fingerprint = Fingerprint(rule_id, relative_path, digest)
        if fingerprint in allowed:
            allowed_count += 1
            continue
        unresolved.append(
            {
                "RuleID": rule_id,
                "Description": finding.get("Description", ""),
                "StartLine": finding.get("StartLine"),
                "EndLine": finding.get("EndLine"),
                "File": relative_path,
                "SecretSHA256": digest,
                "Fingerprint": finding.get("Fingerprint", ""),
            }
        )
    return unresolved, allowed_count, len(findings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = Path(args.root).resolve(strict=True)
        unresolved, allowed_count, total = filter_report(
            root=root,
            report_path=Path(args.report),
            allowlist_path=Path(args.allowlist),
        )
        Path(args.output).write_text(
            json.dumps(unresolved, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"Gitleaks findings: total={total} exact_fingerprint_allowed={allowed_count} "
            f"unresolved={len(unresolved)}"
        )
        return 1 if unresolved else 0
    except (OSError, FilterError) as error:
        print(f"gitleaks-filter error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
