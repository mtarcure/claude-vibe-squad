#!/usr/bin/env python3
"""Independent entropy/token and private-identifier checks for tracked files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from path_policy import PolicyError, read_nul_paths


ENTROPY_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|credential)"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{20,})"
)


class ScanError(RuntimeError):
    """A required scan could not complete safely."""


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    detail: str


Fingerprint = tuple[str, str, str]


def _entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_generated(value: str) -> bool:
    character_classes = sum(
        bool(re.search(pattern, value))
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[_./+=-]")
    )
    return character_classes >= 3 and _entropy(value) >= 3.5


def _load_identifier_patterns(path: Path) -> list[tuple[str, re.Pattern[str]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ScanError(f"cannot read identifier denylist {path}: {error}") from error
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for line_number, line in enumerate(lines, start=1):
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        try:
            patterns.append((candidate, re.compile(candidate, flags=re.IGNORECASE)))
        except re.error as error:
            raise ScanError(
                f"invalid identifier regex at {path}:{line_number}: {error}"
            ) from error
    if not patterns:
        raise ScanError(f"identifier denylist has no active patterns: {path}")
    return patterns


def _load_fingerprint_allowlist(path: Path) -> set[Fingerprint]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScanError(f"cannot load fingerprint allowlist {path}: {error}") from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ScanError("fingerprint allowlist version must be exactly 1")
    entries = document.get("allowed")
    if not isinstance(entries, list):
        raise ScanError("fingerprint allowlist 'allowed' must be a list")
    allowed: set[Fingerprint] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ScanError(f"fingerprint entry {index} must be an object")
        kind = entry.get("kind")
        relative_path = entry.get("path")
        digest = entry.get("sha256")
        reason = entry.get("reason")
        if (
            kind != "high-entropy-token"
            or not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ScanError(f"fingerprint entry {index} is malformed")
        fingerprint = (kind, relative_path, digest)
        if fingerprint in allowed:
            raise ScanError(f"duplicate fingerprint entry {index}")
        allowed.add(fingerprint)
    return allowed


def _tracked_text(root: Path, relative_path: str) -> str | None:
    candidate = root.joinpath(*relative_path.split("/"))
    try:
        metadata = os.lstat(candidate)
    except OSError as error:
        raise ScanError(f"cannot stat tracked file {relative_path!r}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode):
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise ScanError(f"tracked path is not a regular file or symlink: {relative_path!r}")
    try:
        return candidate.read_bytes().decode("utf-8", errors="ignore")
    except OSError as error:
        raise ScanError(f"cannot read tracked file {relative_path!r}: {error}") from error


def scan(
    root: Path,
    tracked_paths: list[str],
    identifier_patterns: list[tuple[str, re.Pattern[str]]],
    allowed_fingerprints: set[Fingerprint],
) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in tracked_paths:
        text = _tracked_text(root, relative_path)
        if text is None:
            continue
        for match in ENTROPY_ASSIGNMENT.finditer(text):
            token = match.group(1)
            if _looks_generated(token):
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                if ("high-entropy-token", relative_path, digest) in allowed_fingerprints:
                    continue
                findings.append(
                    Finding(
                        kind="high-entropy-token",
                        path=relative_path,
                        detail=f"assignment value length={len(token)} entropy={_entropy(token):.2f}",
                    )
                )
        for source, regex in identifier_patterns:
            if regex.search(text):
                findings.append(
                    Finding(kind="private-identifier", path=relative_path, detail=source)
                )
    return findings


def _write_report(path: Path, findings: list[Finding]) -> None:
    try:
        with path.open("w", encoding="utf-8") as handle:
            handle.write(f"Independent content findings: {len(findings)}\n")
            for finding in findings:
                handle.write(
                    f"- {finding.kind} path={json.dumps(finding.path, ensure_ascii=True)} "
                    f"detail={json.dumps(finding.detail, ensure_ascii=True)}\n"
                )
    except OSError as error:
        raise ScanError(f"cannot write content-scan report {path}: {error}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--tracked-nul", required=True)
    parser.add_argument("--identifier-denylist", required=True)
    parser.add_argument(
        "--fingerprint-allowlist",
        default=str(Path(__file__).resolve().parent / "policy" / "content-fingerprints.json"),
    )
    parser.add_argument("--report", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = Path(args.root).resolve(strict=True)
        if not root.is_dir():
            raise ScanError(f"scan root is not a directory: {root}")
        tracked_paths = read_nul_paths(args.tracked_nul)
        patterns = _load_identifier_patterns(Path(args.identifier_denylist))
        fingerprints = _load_fingerprint_allowlist(Path(args.fingerprint_allowlist))
        findings = scan(root, tracked_paths, patterns, fingerprints)
        _write_report(Path(args.report), findings)
        return 1 if findings else 0
    except (PolicyError, ScanError) as error:
        print(f"content-scan error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
