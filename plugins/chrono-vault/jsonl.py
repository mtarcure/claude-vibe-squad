"""One answer to "append a JSONL line safely", for every writer that needs it.

There were two, written days apart for the same job.
`autocapture._spool_episodic` opened `O_NOFOLLOW | O_CLOEXEC` at an explicit
`0o600`, took `flock(LOCK_EX)`, wrote, and `fsync`'d.
`curation_queue.flag_for_curation` used `open("a")` with the process umask and
no lock at all. Both append one JSON object per line to a file under `_state/`
that concurrent processes write. Only one of them was right, and nothing said
which -- CLAUDE.md rule 10: one fact, one home.

What the careful version buys, concretely:

- `O_NOFOLLOW` -- the target is under `_state/`, which is not the vault and
  not privileged, but is world-readable on this machine; following a symlink
  planted there would write wherever it points.
- explicit `0o600` plus `fchmod` -- an inherited umask decides the mode
  otherwise, and these files carry task text.
- `flock(LOCK_EX)` -- `O_APPEND` makes a single `write()` atomic on local
  filesystems, but that guarantee is per-`write()` and not portable across
  every filesystem this repo's `_state/` can sit on. The lock makes it a
  property of this code rather than of the mount.
- `fsync` -- the episodic tier is the "nothing is lost" guarantee, and a line
  that is only in the page cache when the machine drops is lost.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path
from typing import Any


class JsonlAppendError(RuntimeError):
    """The line could not be durably appended."""


class JsonlReadError(RuntimeError):
    """A JSONL source could not be read as bounded object records."""


DEFAULT_MAX_READ_BYTES = 64 * 1024 * 1024


def read_objects(
    source: Path,
    *,
    max_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> list[dict[str, Any]]:
    """Read a bounded regular JSONL file without following symlinks.

    A spool reader has the same trust boundary as its writer: `_state/` is
    writable runtime state and may contain a replaced path or a torn/manual
    line. Fail the file closed instead of returning a partial history that a
    caller could mistake for a complete scan.
    """
    source = Path(source)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise JsonlReadError("max_bytes must be a positive integer")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise JsonlReadError("O_NOFOLLOW is unavailable on this platform")
    descriptor = -1
    try:
        descriptor = os.open(
            source,
            os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise JsonlReadError(f"not a regular file: {source}")
        if before.st_size > max_bytes:
            raise JsonlReadError(f"file exceeds {max_bytes} bytes: {source}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > max_bytes or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise JsonlReadError(f"file changed while reading: {source}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JsonlReadError(f"invalid UTF-8: {source}") from exc
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JsonlReadError(
                    f"invalid JSON at {source}:{line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise JsonlReadError(f"non-object row at {source}:{line_number}")
            rows.append(row)
        return rows
    except JsonlReadError:
        raise
    except OSError as exc:
        raise JsonlReadError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def append_line(destination: Path, payload: dict[str, Any]) -> Path:
    """Append one JSON object as a line to `destination`, durably.

    Creates the parent directory `0o700` if absent. Raises
    `JsonlAppendError` rather than returning a status: every caller treats a
    failed append as a failed operation, and a silent one would defeat the
    reason these files exist.
    """
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise JsonlAppendError("O_NOFOLLOW is unavailable on this platform")
    descriptor = -1
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_APPEND
            | nofollow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise JsonlAppendError(f"not a regular file: {destination}")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except JsonlAppendError:
        raise
    except OSError as exc:
        raise JsonlAppendError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return destination
