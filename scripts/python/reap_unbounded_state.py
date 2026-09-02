#!/usr/bin/env python3
"""Bound unbounded squad state with fail-closed selection and receipts.

The default/``--preserve`` mode is a dry run.  Only ``--apply`` removes data.
An apply receipt is published with ``status=in_progress`` before the first
removal, then atomically replaced with the exact completed/partial result.  A
crash therefore cannot make a reaper that fired look like one that never ran.

Rescued worker artifacts receive the strictest rule: a regular file must be at
least seven days old and byte-identical to a regular-file blob in the current
Git index.  Names, extensions, directories, symlinks, and rescue-to-rescue
duplicates are never deletion evidence.

``bin/prune-board-worktrees.sh`` is the sole owner of board worktrees, their
per-attempt Codex homes, and build scratch.  This general retention reaper owns
only the longer-lived state produced after that lifecycle cleanup, plus
notification receipts, long-running markers, and vault snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "unbounded-state-reaper-receipt/v1"
NOTIFICATION_DAYS = 30
NOTIFICATION_KEEP = 1000
MARKER_DAYS = 30
SNAPSHOT_KEEP = 7
RESCUE_GRACE_DAYS = 7


@dataclass
class Candidate:
    category: str
    path: Path
    display_path: str
    logical_bytes: int
    allocated_bytes: int
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    fingerprint: tuple[Any, ...] = ()

    def public(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "category": self.category,
            "path": self.display_path,
            "logical_bytes": self.logical_bytes,
            "allocated_bytes": self.allocated_bytes,
            "reason": self.reason,
        }
        if self.evidence:
            item["evidence"] = self.evidence
        return item


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return value.astimezone(timezone.utc)


def allocated_bytes(metadata: os.stat_result) -> int:
    return int(getattr(metadata, "st_blocks", 0)) * 512


def file_fingerprint(path: Path) -> tuple[Any, ...]:
    metadata = path.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def file_metrics(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    return metadata.st_size, allocated_bytes(metadata)


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def direct_regular_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for path in directory.iterdir():
        if stat.S_ISREG(path.lstat().st_mode):
            files.append(path)
    return files


def observed_file_bytes(paths: Iterable[Path]) -> tuple[int, int]:
    logical = 0
    allocated = 0
    for path in paths:
        item_logical, item_allocated = file_metrics(path)
        logical += item_logical
        allocated += item_allocated
    return logical, allocated


def candidate_for_file(
    *,
    category: str,
    path: Path,
    root: Path,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> Candidate:
    logical, allocated = file_metrics(path)
    return Candidate(
        category=category,
        path=path,
        display_path=display_path(path, root),
        logical_bytes=logical,
        allocated_bytes=allocated,
        reason=reason,
        evidence=evidence or {},
        fingerprint=file_fingerprint(path),
    )


def plan_notifications(root: Path, now: datetime) -> tuple[list[Candidate], dict[str, Any]]:
    directory = root / "_state" / "chrono-notify-receipts"
    files = direct_regular_files(directory)
    files.sort(key=lambda path: (-path.stat().st_mtime_ns, path.name))
    protected = set(files[:NOTIFICATION_KEEP])
    cutoff = (now - timedelta(days=NOTIFICATION_DAYS)).timestamp()
    candidates = [
        candidate_for_file(
            category="notification_receipts",
            path=path,
            root=root,
            reason=(
                f"older than {NOTIFICATION_DAYS} days and outside newest "
                f"{NOTIFICATION_KEEP} receipt floor"
            ),
        )
        for path in files
        if path not in protected and path.stat().st_mtime <= cutoff
    ]
    logical, allocated = observed_file_bytes(files)
    summary = {
        "policy": (
            f"expire after {NOTIFICATION_DAYS} days while always retaining newest "
            f"{NOTIFICATION_KEEP}"
        ),
        "observed_items": len(files),
        "observed_logical_bytes": logical,
        "observed_allocated_bytes": allocated,
        "retained_newest_floor": min(len(files), NOTIFICATION_KEEP),
        "retained_recent_outside_floor": sum(
            1
            for path in files[NOTIFICATION_KEEP:]
            if path.stat().st_mtime > cutoff
        ),
        "planned_items": len(candidates),
    }
    return candidates, summary


def plan_markers(root: Path, now: datetime) -> tuple[list[Candidate], dict[str, Any]]:
    directory = root / "_state" / "long-running-noted"
    files = direct_regular_files(directory)
    cutoff = (now - timedelta(days=MARKER_DAYS)).timestamp()
    candidates = [
        candidate_for_file(
            category="long_running_markers",
            path=path,
            root=root,
            reason=f"marker mtime older than {MARKER_DAYS} days",
        )
        for path in files
        if not path.name.startswith(".") and path.stat().st_mtime <= cutoff
    ]
    logical, allocated = observed_file_bytes(files)
    summary = {
        "policy": f"expire non-structural markers after {MARKER_DAYS} days",
        "observed_items": len(files),
        "observed_logical_bytes": logical,
        "observed_allocated_bytes": allocated,
        "retained_structural": sum(1 for path in files if path.name.startswith(".")),
        "retained_recent": sum(
            1
            for path in files
            if not path.name.startswith(".") and path.stat().st_mtime > cutoff
        ),
        "planned_items": len(candidates),
    }
    return candidates, summary


def plan_snapshots(
    root: Path, snapshot_directory: Path
) -> tuple[list[Candidate], dict[str, Any]]:
    files = [
        path
        for path in direct_regular_files(snapshot_directory)
        if path.name.startswith("chrono-vault-") and path.name.endswith(".tar.gz")
    ]
    files.sort(key=lambda path: (-path.stat().st_mtime_ns, path.name))
    candidates = [
        candidate_for_file(
            category="vault_snapshots",
            path=path,
            root=root,
            reason=f"older snapshot outside newest {SNAPSHOT_KEEP}",
        )
        for path in files[SNAPSHOT_KEEP:]
    ]
    logical, allocated = observed_file_bytes(files)
    summary = {
        "policy": f"retain newest {SNAPSHOT_KEEP} complete snapshot archives",
        "observed_items": len(files),
        "observed_logical_bytes": logical,
        "observed_allocated_bytes": allocated,
        "retained_newest": min(len(files), SNAPSHOT_KEEP),
        "planned_items": len(candidates),
    }
    return candidates, summary


def git_index_regular_blobs(root: Path) -> tuple[str, dict[str, list[str]]]:
    format_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-object-format"],
        capture_output=True,
        text=True,
        check=False,
    )
    if format_result.returncode != 0:
        raise RuntimeError(format_result.stderr.strip() or "cannot read Git object format")
    object_format = format_result.stdout.strip()
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError(f"unsupported Git object format: {object_format!r}")

    index_result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"],
        capture_output=True,
        check=False,
    )
    if index_result.returncode != 0:
        message = index_result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(message or "cannot read Git index")

    blobs: dict[str, list[str]] = {}
    for record in index_result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("malformed git ls-files --stage record")
        mode = fields[0]
        if mode not in {b"100644", b"100755"}:
            continue
        blob = fields[1].decode("ascii")
        tracked_path = raw_path.decode("utf-8", "surrogateescape")
        blobs.setdefault(blob, []).append(tracked_path)
    return object_format, blobs


def git_blob_digest(path: Path, object_format: str) -> str:
    metadata = path.lstat()
    digest = hashlib.new(object_format)
    digest.update(f"blob {metadata.st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_rescue(
    root: Path, now: datetime, warnings: list[str]
) -> tuple[list[Candidate], dict[str, Any]]:
    directory = root / "_state" / "rescued-worker-artifacts"
    cutoff = (now - timedelta(days=RESCUE_GRACE_DAYS)).timestamp()
    candidates: list[Candidate] = []
    summary: dict[str, Any] = {
        "policy": (
            "regular files only; retain for at least "
            f"{RESCUE_GRACE_DAYS} days; then require exact content identity "
            "with a regular-file blob in the current Git index"
        ),
        "classifier": (
            "git blob identity; never path name, extension, or rescue-to-rescue duplication"
        ),
        "observed_items": 0,
        "observed_logical_bytes": 0,
        "observed_allocated_bytes": 0,
        "retained_unmatched": 0,
        "retained_recent_exact_match": 0,
        "retained_non_regular": 0,
        "planned_items": 0,
    }
    if not directory.is_dir():
        return candidates, summary

    try:
        object_format, indexed_blobs = git_index_regular_blobs(root)
    except RuntimeError as exc:
        warnings.append(f"rescued_worker_artifacts retained all: {exc}")
        summary["classifier_status"] = "unavailable_retained_all"
        return candidates, summary

    summary["classifier_status"] = "available"
    summary["indexed_regular_blobs"] = len(indexed_blobs)
    for current, directory_names, file_names in os.walk(directory, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            try:
                if path.is_symlink():
                    summary["retained_non_regular"] += 1
            except OSError:
                summary["retained_non_regular"] += 1
        for name in file_names:
            path = current_path / name
            try:
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    summary["retained_non_regular"] += 1
                    continue
                summary["observed_items"] += 1
                summary["observed_logical_bytes"] += metadata.st_size
                summary["observed_allocated_bytes"] += allocated_bytes(metadata)
                blob = git_blob_digest(path, object_format)
                tracked_paths = indexed_blobs.get(blob)
                if not tracked_paths:
                    summary["retained_unmatched"] += 1
                    continue
                if metadata.st_mtime > cutoff:
                    summary["retained_recent_exact_match"] += 1
                    continue
                candidates.append(
                    Candidate(
                        category="rescued_worker_artifacts",
                        path=path,
                        display_path=display_path(path, root),
                        logical_bytes=metadata.st_size,
                        allocated_bytes=allocated_bytes(metadata),
                        reason=(
                            f"older than {RESCUE_GRACE_DAYS} days and byte-identical "
                            "to a current indexed regular-file blob"
                        ),
                        evidence={
                            "kind": "exact_git_index_blob",
                            "object_format": object_format,
                            "blob": blob,
                            "tracked_paths": sorted(tracked_paths),
                        },
                        fingerprint=file_fingerprint(path) + (blob,),
                    )
                )
            except OSError as exc:
                warnings.append(f"rescued_worker_artifacts retained unreadable {path}: {exc}")
                summary["retained_unmatched"] += 1
    summary["planned_items"] = len(candidates)
    return candidates, summary


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def totals(planned: list[Candidate], removed: list[Candidate]) -> dict[str, int]:
    return {
        "planned_items": len(planned),
        "planned_logical_bytes": sum(item.logical_bytes for item in planned),
        "planned_allocated_bytes": sum(item.allocated_bytes for item in planned),
        "removed_items": len(removed),
        "removed_logical_bytes": sum(item.logical_bytes for item in removed),
        "removed_allocated_bytes": sum(item.allocated_bytes for item in removed),
    }


def verify_candidate(candidate: Candidate) -> None:
    current = file_fingerprint(candidate.path)
    expected = candidate.fingerprint[: len(current)]
    if current != expected:
        raise RuntimeError("file changed after planning")
    if candidate.category == "rescued_worker_artifacts":
        object_format = str(candidate.evidence["object_format"])
        if git_blob_digest(candidate.path, object_format) != candidate.evidence["blob"]:
            raise RuntimeError("rescued file content changed after planning")


def remove_candidate(candidate: Candidate) -> None:
    candidate.path.unlink()


def receipt_path(receipt_dir: Path, mode: str) -> Path:
    if mode == "preserve":
        return receipt_dir / "latest-preserve.json"
    return receipt_dir / "latest-apply.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preserve", action="store_true", help="dry run (default)")
    modes.add_argument("--apply", action="store_true", help="remove planned items")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root",
    )
    parser.add_argument(
        "--vault-snapshot-dir",
        type=Path,
        default=Path(os.environ.get("VAULT_SNAPSHOT_DEST", Path.home() / "vault-snapshots")),
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        help="receipt directory (default: ROOT/_state/retention-receipts)",
    )
    parser.add_argument("--now", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        now = parse_now(arguments.now)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    root = arguments.root.resolve()
    snapshot_directory = arguments.vault_snapshot_dir.resolve()
    receipt_dir = (
        arguments.receipt_dir.resolve()
        if arguments.receipt_dir
        else root / "_state" / "retention-receipts"
    )
    mode = "apply" if arguments.apply else "preserve"
    started_at = utc_text(now)
    receipt_id = uuid.uuid4().hex
    warnings: list[str] = []
    category_names = (
        "notification_receipts",
        "long_running_markers",
        "vault_snapshots",
        "rescued_worker_artifacts",
    )
    policy_receipt = {
        "notification_days": NOTIFICATION_DAYS,
        "notification_keep_newest": NOTIFICATION_KEEP,
        "long_marker_days": MARKER_DAYS,
        "snapshot_keep_newest": SNAPSHOT_KEEP,
        "rescue_grace_days": RESCUE_GRACE_DAYS,
        "rescue_classifier": "exact current Git-index regular-file blob identity",
    }
    output_receipt = receipt_path(receipt_dir, mode)
    errors: list[dict[str, str]] = []

    # Publish before scanning.  A process killed during a large rescue census
    # leaves status=planning instead of becoming indistinguishable from a job
    # that never fired.
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "receipt_id": receipt_id,
        "mode": mode,
        "status": "planning",
        "started_at": started_at,
        "completed_at": None,
        "root": str(root),
        "vault_snapshot_dir": str(snapshot_directory),
        "policies": policy_receipt,
        "categories": {},
        "planned": [],
        "removed": [],
        "warnings": warnings,
        "errors": errors,
        "totals": totals([], []),
    }
    atomic_write_json(output_receipt, receipt)

    planner_specs = (
        ("notification_receipts", lambda: plan_notifications(root, now)),
        ("long_running_markers", lambda: plan_markers(root, now)),
        ("vault_snapshots", lambda: plan_snapshots(root, snapshot_directory)),
        ("rescued_worker_artifacts", lambda: plan_rescue(root, now, warnings)),
    )
    planners: list[tuple[list[Candidate], dict[str, Any]]] = []
    for name, planner in planner_specs:
        try:
            planners.append(planner())
        except Exception as exc:  # noqa: BLE001 - receipt boundary must fail closed
            message = f"{type(exc).__name__}: {exc}"
            errors.append({"category": name, "error": message})
            planners.append(
                (
                    [],
                    {
                        "policy": "planning failed; category retained in full",
                        "status": "planning_failure",
                        "observed_items": 0,
                        "observed_logical_bytes": 0,
                        "observed_allocated_bytes": 0,
                        "planned_items": 0,
                    },
                )
            )

    planned = [candidate for candidates, _ in planners for candidate in candidates]
    planned.sort(key=lambda item: (item.category, item.display_path))
    categories = {
        name: summary for name, (_, summary) in zip(category_names, planners, strict=True)
    }
    removed: list[Candidate] = []
    receipt["categories"] = categories
    receipt["planned"] = [candidate.public() for candidate in planned]
    receipt["warnings"] = warnings
    receipt["errors"] = errors
    receipt["totals"] = totals(planned, removed)
    if errors:
        receipt["status"] = "planning_failure"
        receipt["completed_at"] = utc_text(datetime.now(timezone.utc))
    elif mode == "apply":
        receipt["status"] = "in_progress"
    else:
        receipt["status"] = "complete"
        receipt["completed_at"] = utc_text(now)

    # Publish the full plan before the first removal. If this durability step
    # fails, no removal is attempted.
    atomic_write_json(output_receipt, receipt)

    if mode == "apply" and not errors:
        for candidate in planned:
            try:
                verify_candidate(candidate)
                remove_candidate(candidate)
                removed.append(candidate)
            except (OSError, RuntimeError) as exc:
                errors.append({"path": candidate.display_path, "error": str(exc)})
        receipt["status"] = "partial_failure" if errors else "complete"
        receipt["completed_at"] = utc_text(datetime.now(timezone.utc))
        receipt["removed"] = [candidate.public() for candidate in removed]
        receipt["errors"] = errors
        receipt["totals"] = totals(planned, removed)
        atomic_write_json(output_receipt, receipt)

    print(f"unbounded-state-reaper mode={mode} status={receipt['status']}")
    for name in category_names:
        summary = categories[name]
        category_candidates = [item for item in planned if item.category == name]
        print(
            f"{name}: observed={summary['observed_items']} "
            f"planned={len(category_candidates)} "
            f"planned_logical_bytes={sum(item.logical_bytes for item in category_candidates)} "
            f"planned_allocated_bytes={sum(item.allocated_bytes for item in category_candidates)}"
        )
    final_totals = receipt["totals"]
    print(
        f"totals: planned={final_totals['planned_items']} "
        f"planned_logical_bytes={final_totals['planned_logical_bytes']} "
        f"planned_allocated_bytes={final_totals['planned_allocated_bytes']} "
        f"removed={final_totals['removed_items']} "
        f"removed_logical_bytes={final_totals['removed_logical_bytes']}"
    )
    print(f"receipt={output_receipt}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
