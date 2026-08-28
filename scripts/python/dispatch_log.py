#!/usr/bin/env python3
"""Persist skill-invocation telemetry in the standing dispatch log.

Worker transcripts are mixed JSONL: model stream events are JSON objects, while
controller diagnostics may be plain text.  A skill invocation is the exact
event shape ``{"type": "tool_use", "name": "Skill"}``, wherever that object is
nested in a JSON line.

The dispatch log predates this telemetry.  Historical rows therefore keep an
absent ``skills`` field; a measured run always receives an integer, including
zero.  Updating one run preserves every unrelated JSONL row byte-for-byte.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_TRANSCRIPT_RETENTION_DAYS = 30
QUEUED_APPEND_TIMEOUT_SECONDS = 2.0
LIVE_STATUSES = {"in-flight"}
DESCRIPTOR_SUFFIX = ".dispatch.json"
DESCRIPTOR_SCHEMAS = {"board-dispatch-process/v1", "board-dispatch-process/v2"}


class DispatchLogError(RuntimeError):
    """The telemetry source or destination failed its integrity contract."""


@dataclass(frozen=True)
class SkillTelemetryResult:
    task_id: str
    skills: Optional[int]
    descriptor: Optional[Path]
    transcript: Optional[Path]
    updated: bool
    status: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skills": self.skills,
            "descriptor": str(self.descriptor) if self.descriptor else None,
            "transcript": str(self.transcript) if self.transcript else None,
            "updated": self.updated,
            "status": self.status,
        }


@dataclass(frozen=True)
class TranscriptRetentionSummary:
    retention_days: int
    descriptors: int
    retained_live: int
    retained_recent: int
    expired: int
    removed: int
    missing: int
    invalid: int
    duplicate: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "retention_days": self.retention_days,
            "descriptors": self.descriptors,
            "retained_live": self.retained_live,
            "retained_recent": self.retained_recent,
            "expired": self.expired,
            "removed": self.removed,
            "missing": self.missing,
            "invalid": self.invalid,
            "duplicate": self.duplicate,
        }


def _load_json_object(path: Path, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DispatchLogError(f"{label} is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DispatchLogError(f"invalid {label} at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DispatchLogError(f"{label} must contain a JSON object: {path}")
    return value


def _load_registry(repo_root: Path) -> Dict[str, Any]:
    path = repo_root / "_state" / "active-tasks.json"
    if not path.exists():
        return {}
    return _load_json_object(path, "active-task registry")


def _descriptor_rows(
    repo_root: Path, task_id: Optional[str] = None
) -> Tuple[List[Tuple[Path, Dict[str, Any]]], int]:
    dispatch_dir = repo_root / "_state" / "board-dispatch"
    if not dispatch_dir.is_dir():
        return [], 0
    rows: List[Tuple[Path, Dict[str, Any]]] = []
    invalid = 0
    for path in sorted(dispatch_dir.glob(f"*{DESCRIPTOR_SUFFIX}")):
        if task_id is not None and not path.name.startswith(f"{task_id}."):
            continue
        if path.is_symlink() or not path.is_file():
            if task_id is not None:
                raise DispatchLogError(
                    f"board dispatch descriptor is not a regular file: {path}"
                )
            invalid += 1
            continue
        try:
            payload = _load_json_object(path, "board dispatch descriptor")
        except DispatchLogError:
            if task_id is None:
                invalid += 1
                continue
            raise
        if payload.get("schema") not in DESCRIPTOR_SCHEMAS:
            if task_id is not None:
                raise DispatchLogError(f"unsupported descriptor schema: {path}")
            invalid += 1
            continue
        if task_id is None or payload.get("task_id") == task_id:
            rows.append((path, payload))
    return rows, invalid


def _select_descriptor(
    repo_root: Path, task_id: str
) -> Optional[Tuple[Path, Dict[str, Any]]]:
    rows, _invalid = _descriptor_rows(repo_root, task_id)
    if not rows:
        return None

    registry = _load_registry(repo_root)
    entry = registry.get(task_id)
    attempt_id = entry.get("delivery_attempt_id") if isinstance(entry, dict) else None
    if isinstance(attempt_id, str) and attempt_id:
        exact = [row for row in rows if row[1].get("attempt_id") == attempt_id]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise DispatchLogError(
                f"multiple descriptors match {task_id} attempt {attempt_id}"
            )

    # A settled entry may already have aged out of the active registry.  The
    # newest exact-task descriptor is then the only durable attempt ordering.
    return max(rows, key=lambda row: row[0].stat().st_mtime_ns)


def _transcript_path(
    repo_root: Path,
    descriptor_path: Path,
    payload: Dict[str, Any],
    *,
    require_exists: bool,
) -> Path:
    raw = payload.get("log_path")
    if not isinstance(raw, str) or not raw.strip():
        raise DispatchLogError(f"descriptor has no log_path: {descriptor_path}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if candidate.is_symlink():
        raise DispatchLogError(f"transcript must not be a symlink: {candidate}")

    expected_name = descriptor_path.name[: -len(DESCRIPTOR_SUFFIX)] + ".log"
    expected = descriptor_path.with_name(expected_name).resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved != expected:
        raise DispatchLogError(
            f"descriptor log_path escapes its attempt identity: {candidate}"
        )
    if require_exists and not resolved.is_file():
        raise DispatchLogError(f"worker transcript is missing: {resolved}")
    return resolved


def _count_events(value: Any) -> int:
    count = 0
    pending: List[Any] = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if current.get("type") == "tool_use" and current.get("name") == "Skill":
                count += 1
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return count


def count_skill_invocations(transcript: Path) -> int:
    """Count exact Skill tool-use events, refusing an unreadable zero."""

    parsed_lines = 0
    skill_events = 0
    try:
        with transcript.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parsed_lines += 1
                skill_events += _count_events(value)
    except OSError as exc:
        raise DispatchLogError(f"cannot read worker transcript {transcript}: {exc}") from exc
    if parsed_lines == 0:
        raise DispatchLogError(
            f"worker transcript has no parseable JSON events; refusing false zero: {transcript}"
        )
    return skill_events


def _line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    return b""


def _render_dispatch_log_update(data: bytes, task_id: str, skills: int) -> bytes:
    lines = data.splitlines(keepends=True)
    target_index: Optional[int] = None
    target_row: Optional[Dict[str, Any]] = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DispatchLogError(
                f"dispatch log line {index + 1} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise DispatchLogError(
                f"dispatch log line {index + 1} is not a JSON object"
            )
        if row.get("task_id") == task_id:
            target_index = index
            target_row = row
    if target_index is None or target_row is None:
        raise DispatchLogError(f"dispatch log has no record for {task_id}")

    target_row["skills"] = skills
    ending = _line_ending(lines[target_index])
    lines[target_index] = (
        json.dumps(target_row, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        + ending
    )
    return b"".join(lines)


def _dispatch_task_counts(data: bytes) -> Counter[str]:
    counts: Counter[str] = Counter()
    for index, line in enumerate(data.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DispatchLogError(
                f"dispatch log line {index} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise DispatchLogError(f"dispatch log line {index} is not a JSON object")
        row_task_id = row.get("task_id")
        if isinstance(row_task_id, str):
            counts[row_task_id] += 1
    return counts


def _wait_for_registered_appends(repo_root: Path, dispatch_log: Path) -> None:
    """Drain senders that registered before the registry lock was acquired.

    ``send-task.sh`` registers a queued delivery generation under the registry
    lock, releases it, then appends that generation's dispatch-log row.  The
    telemetry updater holds the same registry lock while this function runs:
    later senders cannot register, and earlier queued senders can finish their
    already-authorized append.  Requiring one row per generation closes the
    otherwise destructive append-vs-replace race without changing the sender.
    """

    registry = _load_registry(repo_root)
    required: Dict[str, int] = {}
    for task_id, entry in registry.items():
        if not isinstance(task_id, str) or not isinstance(entry, dict):
            continue
        if entry.get("status") != "in-flight" or entry.get("delivery_state") != "queued":
            continue
        generation = entry.get("delivery_generation", 1)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise DispatchLogError(
                f"queued registry entry has invalid delivery_generation: {task_id}"
            )
        required[task_id] = generation
    if not required:
        return

    deadline = time.monotonic() + QUEUED_APPEND_TIMEOUT_SECONDS
    while True:
        counts = _dispatch_task_counts(dispatch_log.read_bytes())
        missing = {
            task_id: generation - counts[task_id]
            for task_id, generation in required.items()
            if counts[task_id] < generation
        }
        if not missing:
            return
        if time.monotonic() >= deadline:
            details = ", ".join(
                f"{task_id} needs {remaining} row(s)" for task_id, remaining in sorted(missing.items())
            )
            raise DispatchLogError(
                f"timed out waiting for registered dispatch-log append(s): {details}"
            )
        time.sleep(0.01)


def _atomic_replace(path: Path, content: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.skills.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def update_dispatch_log(repo_root: Path, task_id: str, skills: int) -> bool:
    """Set ``skills`` on the newest matching row; preserve all other bytes."""

    path = repo_root / "_state" / "dispatch-log.jsonl"
    if path.is_symlink() or not path.is_file():
        raise DispatchLogError(f"dispatch log is not a regular file: {path}")
    registry_lock_path = repo_root / "_state" / "active-tasks.json.lock"
    lock_path = path.with_name(path.name + ".skills.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_lock_path.open("a+b") as registry_lock:
        fcntl.flock(registry_lock.fileno(), fcntl.LOCK_EX)
        try:
            _wait_for_registered_appends(repo_root, path)
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                try:
                    before = path.read_bytes()
                    after = _render_dispatch_log_update(before, task_id, skills)
                    if after == before:
                        return False
                    mode = stat.S_IMODE(path.stat().st_mode)
                    _atomic_replace(path, after, mode)
                    return True
                finally:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        finally:
            fcntl.flock(registry_lock.fileno(), fcntl.LOCK_UN)


def record_skill_telemetry(repo_root: Path, task_id: str) -> SkillTelemetryResult:
    repo_root = repo_root.resolve()
    selected = _select_descriptor(repo_root, task_id)
    if selected is None:
        # Legacy dispatches have no descriptor or transcript.  Leaving their
        # field absent is the explicit "unmeasured" state, not a fabricated 0.
        return SkillTelemetryResult(
            task_id=task_id,
            skills=None,
            descriptor=None,
            transcript=None,
            updated=False,
            status="legacy-unmeasured",
        )
    descriptor, payload = selected
    transcript = _transcript_path(
        repo_root, descriptor, payload, require_exists=True
    )
    skills = count_skill_invocations(transcript)
    updated = update_dispatch_log(repo_root, task_id, skills)
    return SkillTelemetryResult(
        task_id=task_id,
        skills=skills,
        descriptor=descriptor,
        transcript=transcript,
        updated=updated,
        status="measured",
    )


def enforce_transcript_retention(
    repo_root: Path,
    *,
    retention_days: int = DEFAULT_TRANSCRIPT_RETENTION_DAYS,
    apply: bool = False,
    now: Optional[float] = None,
) -> TranscriptRetentionSummary:
    """Retain live/recent transcripts and expire settled ones by age.

    Descriptor-referenced logs are deliberately independent of worktree and
    per-attempt-home cleanup.  A settled transcript is eligible only after the
    age cap; an entry still present with a nonterminal status is never eligible.
    """

    if isinstance(retention_days, bool) or retention_days < 1:
        raise DispatchLogError("transcript retention days must be a positive integer")
    repo_root = repo_root.resolve()
    registry = _load_registry(repo_root)
    cutoff = (time.time() if now is None else now) - retention_days * 86400
    rows, invalid = _descriptor_rows(repo_root)
    seen: set[Path] = set()
    retained_live = retained_recent = expired = removed = 0
    missing = duplicate = 0

    for descriptor, payload in rows:
        try:
            transcript = _transcript_path(
                repo_root, descriptor, payload, require_exists=False
            )
        except DispatchLogError:
            invalid += 1
            continue
        if transcript in seen:
            duplicate += 1
            continue
        seen.add(transcript)
        if not transcript.is_file():
            missing += 1
            continue

        task_id = payload.get("task_id")
        entry = registry.get(task_id) if isinstance(task_id, str) else None
        status_value = entry.get("status") if isinstance(entry, dict) else None
        if status_value in LIVE_STATUSES:
            retained_live += 1
            continue
        if transcript.stat().st_mtime >= cutoff:
            retained_recent += 1
            continue

        expired += 1
        if apply:
            transcript.unlink()
            removed += 1

    return TranscriptRetentionSummary(
        retention_days=retention_days,
        descriptors=len(rows) + invalid,
        retained_live=retained_live,
        retained_recent=retained_recent,
        expired=expired,
        removed=removed,
        missing=missing,
        invalid=invalid,
        duplicate=duplicate,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record-skills", help="measure one completed worker transcript"
    )
    record.add_argument("--repo-root", type=Path, required=True)
    record.add_argument("--task-id", required=True)

    retain = subparsers.add_parser(
        "prune-transcripts", help="apply or report the bounded transcript policy"
    )
    retain.add_argument("--repo-root", type=Path, required=True)
    retain.add_argument(
        "--retention-days", type=int, default=DEFAULT_TRANSCRIPT_RETENTION_DAYS
    )
    retain.add_argument("--apply", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "record-skills":
            result = record_skill_telemetry(args.repo_root, args.task_id)
            print(json.dumps(result.as_dict(), sort_keys=True))
        else:
            summary = enforce_transcript_retention(
                args.repo_root,
                retention_days=args.retention_days,
                apply=args.apply,
            )
            print(json.dumps(summary.as_dict(), sort_keys=True))
    except (DispatchLogError, OSError) as exc:
        print(f"dispatch_log.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
