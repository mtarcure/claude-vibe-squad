#!/usr/bin/env python3
"""Enforce declarations for byte-identical tracked files.

The census is derived only from the Git index via ``git ls-files -s -z``.
Near-duplicate content is deliberately outside this check.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


REGISTRY_COLUMNS = (
    "blob_group",
    "winner_path",
    "member_paths",
    "enforced_by",
    "disposition",
    "reason",
)
VALID_DISPOSITIONS = frozenset({"intentional", "known_defect"})
GROUP_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENTITY_ENFORCER = "scripts/python/check_duplicate_blobs.py"


class DuplicateCheckError(RuntimeError):
    """Raised when the index cannot be censused safely."""


class RegistryError(ValueError):
    """Raised when a declaration cannot enforce the rule it records."""


@dataclass(frozen=True)
class RegistryEntry:
    blob_group: str
    winner_path: str
    member_paths: tuple[str, ...]
    enforced_by: tuple[str, ...]
    disposition: str
    reason: str
    line_number: int


@dataclass(frozen=True)
class IndexCensus:
    tracked_paths: frozenset[str]
    index_objects: dict[str, str]
    duplicate_groups: dict[str, tuple[str, ...]]


def _repo_path(value: object, *, field: str, line_number: int) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"line {line_number}: {field} must contain a path")
    if "\x00" in value or value.startswith("/"):
        raise RegistryError(
            f"line {line_number}: {field} must be a repo-relative path: {value!r}"
        )
    parsed = PurePosixPath(value)
    if parsed.as_posix() != value or any(part in {"", ".", ".."} for part in parsed.parts):
        raise RegistryError(
            f"line {line_number}: {field} is not a canonical repo path: {value!r}"
        )
    return value


def _json_path_list(
    raw: str,
    *,
    field: str,
    line_number: int,
    minimum: int,
) -> tuple[str, ...]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RegistryError(
            f"line {line_number}: {field} is not a JSON path list: {error.msg}"
        ) from error
    if not isinstance(values, list):
        raise RegistryError(f"line {line_number}: {field} must be a JSON list")
    paths = tuple(
        _repo_path(value, field=field, line_number=line_number) for value in values
    )
    if len(paths) < minimum:
        raise RegistryError(
            f"line {line_number}: {field} must contain at least {minimum} path(s)"
        )
    if len(set(paths)) != len(paths):
        raise RegistryError(f"line {line_number}: {field} contains a duplicate path")
    if paths != tuple(sorted(paths)):
        raise RegistryError(f"line {line_number}: {field} must be sorted")
    return paths


def _json_path(raw: str, *, field: str, line_number: int) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RegistryError(
            f"line {line_number}: {field} is not a JSON path string: {error.msg}"
        ) from error
    return _repo_path(value, field=field, line_number=line_number)


def load_registry_bytes(data: bytes, *, source: str) -> list[RegistryEntry]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RegistryError(f"registry {source} is not UTF-8: {error}") from error
    handle = io.StringIO(text, newline="")

    with handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != REGISTRY_COLUMNS:
            raise RegistryError(
                "registry header must be exactly: " + "\\t".join(REGISTRY_COLUMNS)
            )
        entries: list[RegistryEntry] = []
        seen_ids: set[str] = set()
        seen_members: set[frozenset[str]] = set()
        for row in reader:
            line_number = reader.line_num
            if None in row:
                raise RegistryError(f"line {line_number}: unexpected extra TSV field")
            values = {column: (row.get(column) or "").strip() for column in REGISTRY_COLUMNS}
            blob_group = values["blob_group"]
            if not GROUP_ID.fullmatch(blob_group):
                raise RegistryError(
                    f"line {line_number}: blob_group must be lowercase kebab-case"
                )
            if blob_group in seen_ids:
                raise RegistryError(
                    f"line {line_number}: duplicate blob_group {blob_group!r}"
                )
            members = _json_path_list(
                values["member_paths"],
                field="member_paths",
                line_number=line_number,
                minimum=2,
            )
            member_set = frozenset(members)
            if member_set in seen_members:
                raise RegistryError(
                    f"line {line_number}: duplicate member_paths declaration"
                )
            winner = _json_path(
                values["winner_path"],
                field="winner_path",
                line_number=line_number,
            )
            if winner not in member_set:
                raise RegistryError(
                    f"line {line_number}: winner_path is not present in member_paths"
                )
            enforcers = _json_path_list(
                values["enforced_by"],
                field="enforced_by",
                line_number=line_number,
                minimum=1,
            )
            if IDENTITY_ENFORCER not in enforcers:
                raise RegistryError(
                    f"line {line_number}: enforced_by must include "
                    f"{IDENTITY_ENFORCER!r}"
                )
            disposition = values["disposition"]
            if disposition not in VALID_DISPOSITIONS:
                raise RegistryError(
                    f"line {line_number}: disposition must be one of "
                    + ", ".join(sorted(VALID_DISPOSITIONS))
                )
            reason = values["reason"]
            if not reason:
                raise RegistryError(f"line {line_number}: reason must not be blank")
            entries.append(
                RegistryEntry(
                    blob_group=blob_group,
                    winner_path=winner,
                    member_paths=members,
                    enforced_by=enforcers,
                    disposition=disposition,
                    reason=reason,
                    line_number=line_number,
                )
            )
            seen_ids.add(blob_group)
            seen_members.add(member_set)
    return entries


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(variable, None)
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    return environment


def census_index(repo: Path) -> IndexCensus:
    if not repo.is_dir():
        raise DuplicateCheckError(f"repository directory does not exist: {repo}")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-s", "-z", "--"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=git_environment(),
        )
    except OSError as error:
        raise DuplicateCheckError(f"cannot execute git ls-files: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise DuplicateCheckError(
            f"git ls-files failed with exit {result.returncode}: {detail or 'no stderr'}"
        )

    tracked_paths: set[str] = set()
    index_objects: dict[str, str] = {}
    paths_by_blob: dict[str, set[str]] = {}
    unmerged_paths: set[str] = set()
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or not raw_path:
            raise DuplicateCheckError("git ls-files returned a malformed stage record")
        try:
            mode, blob, stage = (field.decode("ascii") for field in fields)
        except UnicodeDecodeError as error:
            raise DuplicateCheckError(
                "git ls-files returned non-ASCII index metadata"
            ) from error
        path = os.fsdecode(raw_path)
        tracked_paths.add(path)
        if stage != "0":
            unmerged_paths.add(path)
            continue
        index_objects[path] = blob
        # A gitlink records a commit object, not file bytes. Counting two equal
        # gitlink object IDs as duplicate files would be a false positive.
        if mode == "160000":
            continue
        paths_by_blob.setdefault(blob, set()).add(path)
    if unmerged_paths:
        rendered = ", ".join(repr(path) for path in sorted(unmerged_paths))
        raise DuplicateCheckError(
            f"index contains unmerged paths; duplicate census is undefined: {rendered}"
        )
    duplicate_groups = {
        blob: tuple(sorted(paths))
        for blob, paths in paths_by_blob.items()
        if len(paths) >= 2
    }
    return IndexCensus(
        tracked_paths=frozenset(tracked_paths),
        index_objects=index_objects,
        duplicate_groups=duplicate_groups,
    )


def read_registry_snapshot(
    repo: Path,
    registry: Path,
    census: IndexCensus,
) -> bytes:
    try:
        relative = registry.relative_to(repo).as_posix()
    except ValueError as error:
        raise RegistryError(
            f"registry must live inside the censused repository: {registry}"
        ) from error
    expected = census.index_objects.get(relative)
    if expected is None:
        raise RegistryError(f"registry is not tracked at stage 0: {relative}")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", expected],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=git_environment(),
        )
    except OSError as error:
        raise RegistryError(f"cannot read staged registry {relative}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RegistryError(
            f"cannot read staged registry {relative}: {detail or 'git cat-file failed'}"
        )
    return result.stdout


def policy_violations(
    census: IndexCensus,
    entries: Sequence[RegistryEntry],
) -> list[str]:
    violations: list[str] = []
    declared = {frozenset(entry.member_paths): entry for entry in entries}
    actual = {
        frozenset(paths): blob for blob, paths in census.duplicate_groups.items()
    }

    for members, blob in sorted(actual.items(), key=lambda item: sorted(item[0])):
        if members in declared:
            continue
        violations.append(f"undeclared identical-blob group {blob}:")
        violations.extend(f"  {path!r}" for path in sorted(members))

    for members, entry in sorted(
        declared.items(), key=lambda item: item[1].blob_group
    ):
        if members not in actual:
            violations.append(
                f"stale declaration {entry.blob_group!r}: member_paths are no longer "
                "one exact current blob group"
            )
        for enforcer in entry.enforced_by:
            if enforcer not in census.tracked_paths:
                violations.append(
                    f"declaration {entry.blob_group!r} names an untracked enforcer: "
                    f"{enforcer!r}"
                )
    return violations


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    default_repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=default_repo,
        help="Git worktree to census (default: this repository)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="declaration registry (default: <repo>/shared/registries/identical-blobs.tsv)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo = args.repo.resolve()
    registry = (
        args.registry.resolve()
        if args.registry is not None
        else repo / "shared/registries/identical-blobs.tsv"
    )
    try:
        census = census_index(repo)
    except DuplicateCheckError as error:
        print(f"ONE-FACT-ONE-HOME ERROR: {error}", file=sys.stderr)
        return 2
    try:
        registry_bytes = read_registry_snapshot(repo, registry, census)
        entries = load_registry_bytes(registry_bytes, source=str(registry))
    except RegistryError as error:
        print(f"ONE-FACT-ONE-HOME FAIL: {error}", file=sys.stderr)
        return 1

    violations = policy_violations(census, entries)
    if violations:
        print(
            f"ONE-FACT-ONE-HOME FAIL: {len(violations)} policy issue(s)",
            file=sys.stderr,
        )
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1

    path_count = sum(len(paths) for paths in census.duplicate_groups.values())
    intentional = sum(entry.disposition == "intentional" for entry in entries)
    known_defects = sum(entry.disposition == "known_defect" for entry in entries)
    for entry in entries:
        if entry.disposition == "known_defect":
            print(
                f"ONE-FACT-ONE-HOME KNOWN_DEFECT: {entry.blob_group}: "
                f"winner={entry.winner_path!r}; {entry.reason}"
            )
    print(
        "ONE-FACT-ONE-HOME PASS: "
        f"checked {len(census.duplicate_groups)} identical-blob groups across "
        f"{path_count} tracked paths; registry entries={len(entries)} "
        f"(intentional={intentional}, known_defect={known_defects})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
