"""Capture bounded mailbox response summaries as candidate learning notes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from notes import record
from vaultroot import resolve_vault_root


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SUMMARY_CHARS = 1500
MAX_TITLE_CHARS = 240
MAX_FIELD_CHARS = 1000
RESPONSE_NAME = re.compile(r"^(TASK-[A-Za-z0-9-]+)-response\.md$")
FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
KNOWN_NAMESPACES = frozenset(
    {"coding", "security", "content", "content-engineer", "sysmgmt", "research"}
)
KNOWN_INTERNAL_MODES = frozenset(
    {"build", "content", "plan", "research", "review", "sysmgmt"}
)


class CaptureError(RuntimeError):
    """A response cannot be captured safely."""


def _result(
    captured: bool,
    note_id: str | None,
    reason: str,
) -> dict[str, bool | str | None]:
    return {"captured": captured, "note_id": note_id, "reason": reason}


def _read_response(path: Path) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CaptureError("unsafe_response")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RESPONSE_BYTES:
            raise CaptureError("unsafe_response")
        chunks: list[bytes] = []
        remaining = MAX_RESPONSE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > MAX_RESPONSE_BYTES or (
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
            raise CaptureError("unsafe_response")
        return raw
    except CaptureError:
        raise
    except (OSError, ValueError) as exc:
        raise CaptureError("unsafe_response") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _scalar(raw_value: str) -> str:
    value = raw_value.strip()
    if not value or len(value) > MAX_FIELD_CHARS:
        raise CaptureError("malformed_frontmatter")
    if value[0] == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CaptureError("malformed_frontmatter") from exc
        if not isinstance(parsed, str):
            raise CaptureError("malformed_frontmatter")
        return parsed
    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'":
            raise CaptureError("malformed_frontmatter")
        return value[1:-1].replace("''", "'")
    if value[0] in "[{!&*|>" or "\t" in value:
        raise CaptureError("malformed_frontmatter")
    return value


def _artifact_list(raw_value: str) -> list[str]:
    value = raw_value.strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CaptureError("malformed_frontmatter") from exc
    if (
        not isinstance(parsed, list)
        or len(parsed) > 32
        or any(not isinstance(item, str) for item in parsed)
    ):
        raise CaptureError("malformed_frontmatter")
    return parsed


def _parse_response(raw: bytes) -> tuple[dict[str, Any], str]:
    if b"\x00" in raw:
        raise CaptureError("malformed_frontmatter")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaptureError("malformed_frontmatter") from exc
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise CaptureError("malformed_frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise CaptureError("malformed_frontmatter") from exc

    fields: dict[str, Any] = {}
    active_list: str | None = None
    for line in lines[1:closing]:
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and active_list == "artifacts":
            fields["artifacts"].append(_scalar(line[4:]))
            continue
        active_list = None
        if line[:1].isspace() or "\t" in line:
            raise CaptureError("malformed_frontmatter")
        key, separator, raw_value = line.partition(":")
        if not separator or not FIELD_NAME.fullmatch(key) or key in fields:
            raise CaptureError("malformed_frontmatter")
        if key == "artifacts":
            fields[key] = _artifact_list(raw_value)
            if not raw_value.strip():
                active_list = key
        else:
            fields[key] = _scalar(raw_value)

    body = "\n".join(lines[closing + 1 :]).strip()
    return fields, body


def _source_namespace(path: Path) -> str | None:
    parts = path.parts
    namespace: str | None = None
    for index in range(len(parts) - 2):
        if parts[index] == "departments" and parts[index + 2] == "outbox":
            namespace = parts[index + 1]
    return namespace


DEFAULT_MODES = {
    "coding": "build",
    "security": "bounty",
    "content": "content",
    "content-engineer": "content",
    "research": "research",
    "sysmgmt": "sysmgmt",
}


def _resolve_packet_fields(response_path: Path, source_task: str) -> dict[str, str]:
    """Return capture-relevant metadata from the matching source packet."""
    department = response_path.parent.parent  # departments/<namespace>
    for mailbox in ("archive", "active", "inbox"):
        packet = department / mailbox / f"{source_task}.md"
        try:
            text = packet.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if not lines or lines[0] != "---":
            continue
        try:
            closing = lines.index("---", 1)
        except ValueError:
            continue
        frontmatter = "\n".join(lines[1:closing])
        resolved: dict[str, str] = {}
        for field in ("specialist", "mode"):
            match = re.search(rf"(?m)^{field}:[ \t]*(\S.*?)[ \t]*$", frontmatter)
            if match and match.group(1).strip():
                resolved[field] = match.group(1).strip().strip("'\"")
        return resolved
    return {}


def _resolve_specialist(fields: dict[str, Any], packet_fields: dict[str, str]) -> str:
    """Specialist from the envelope, else the source packet, else a safe default.

    The canonical completion envelope (shared/protocol.md) does not carry a
    `specialist` field, so a hard requirement on it silently dropped
    correctly-formatted completions. When the envelope omits it, derive it from
    the original task packet (departments/<ns>/{archive,active,inbox}/<id>.md) to
    preserve recall quality; fall back to a stable placeholder only if neither
    source has it.
    """
    envelope_value = fields.get("specialist")
    if isinstance(envelope_value, str) and envelope_value.strip():
        return _slug(envelope_value, "unknown-specialist")
    packet_value = packet_fields.get("specialist")
    if packet_value:
        return _slug(packet_value, "unknown-specialist")
    return "unknown-specialist"


def _clean_one_line(value: str) -> str:
    cleaned = " ".join(value.replace("\x00", "").split())
    return "".join(character for character in cleaned if ord(character) >= 32)


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return cleaned[:120] or fallback


def _bounded_summary(body: str, verdict: str, artifacts: list[str]) -> str:
    body_lines: list[str] = []
    for raw_line in body.splitlines():
        line = _clean_one_line(raw_line)
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if line.casefold() in {"verdict", "summary", "result", "findings"}:
                continue
        if line:
            body_lines.append(line)

    pieces: list[str] = []
    clean_verdict = _clean_one_line(verdict)
    if clean_verdict:
        pieces.append(clean_verdict)
    normalized_body = "\n".join(body_lines)
    if normalized_body and normalized_body != clean_verdict:
        pieces.append(normalized_body)
    safe_artifacts: list[str] = []
    for item in artifacts:
        cleaned = _clean_one_line(item).replace("\\", "/")
        parts = cleaned.split("/")
        if (
            not cleaned
            or len(cleaned) > 240
            or cleaned.startswith(("/", "~"))
            or ".." in parts
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", cleaned)
        ):
            continue
        safe_artifacts.append(cleaned)
    if safe_artifacts:
        pieces.append("Artifacts: " + ", ".join(safe_artifacts))
    summary = "\n\n".join(pieces).strip()
    if not summary:
        raise CaptureError("missing_summary")
    return summary[:MAX_SUMMARY_CHARS].rstrip()


def _canonical_key(path: Path) -> tuple[str, str, str]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CaptureError("dedupe_scan_failed")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CaptureError("dedupe_scan_failed")
        raw = os.read(descriptor, 65536).decode("utf-8")
    except CaptureError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise CaptureError("dedupe_scan_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    values: dict[str, Any] = {}
    lines = raw.splitlines()
    if not lines or lines[0] != "---":
        raise CaptureError("dedupe_scan_failed")
    for line in lines[1:]:
        if line == "---":
            break
        key, separator, value = line.partition(": ")
        if key not in {"id", "source_task", "source_artifact_hash"}:
            continue
        if not separator:
            raise CaptureError("dedupe_scan_failed")
        try:
            values[key] = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CaptureError("dedupe_scan_failed") from exc
    if not isinstance(values.get("id"), str) or any(
        values.get(key) is not None and not isinstance(values.get(key), str)
        for key in ("source_task", "source_artifact_hash")
    ):
        raise CaptureError("dedupe_scan_failed")
    return (
        values.get("source_task") or "",
        values.get("source_artifact_hash") or "",
        values.get("id") or "",
    )


@contextmanager
def _dedupe_lock(root: Path) -> Iterator[None]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CaptureError("dedupe_lock_failed")
    descriptor = -1
    try:
        descriptor = os.open(
            root / ".autocapture.lock",
            os.O_RDWR
            | os.O_CREAT
            | nofollow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CaptureError("dedupe_lock_failed")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except CaptureError:
        raise
    except OSError as exc:
        raise CaptureError("dedupe_lock_failed") from exc
    finally:
        if descriptor >= 0:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _find_duplicate(root: Path, source_task: str, artifact_hash: str) -> str | None:
    directory = root / "notes" / "learning"
    if not directory.exists():
        return None
    if directory.is_symlink() or not directory.is_dir():
        raise CaptureError("dedupe_scan_failed")
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.endswith(".md") or not entry.is_file(
                follow_symlinks=False
            ):
                continue
            existing_task, existing_hash, note_id = _canonical_key(Path(entry.path))
            if existing_task == source_task and existing_hash == artifact_hash:
                return note_id
    return None


def capture_response(response_path: str) -> dict[str, bool | str | None]:
    """Capture one valid task response, or return a stable skip reason."""
    if not isinstance(response_path, str):
        return _result(False, None, "not_response")
    path = Path(response_path)
    name_match = RESPONSE_NAME.fullmatch(path.name)
    if name_match is None:
        return _result(False, None, "not_response")

    try:
        raw = _read_response(path)
        fields, body = _parse_response(raw)
        source_task = name_match.group(1)
        for field_name in ("in_response_to", "in_reply_to", "task_id"):
            declared_task = fields.get(field_name)
            if declared_task is not None:
                if not isinstance(declared_task, str):
                    raise CaptureError("malformed_frontmatter")
                if declared_task != source_task:
                    raise CaptureError("task_mismatch")

        # `status` is the only always-present field in the canonical envelope
        # (shared/protocol.md); `specialist` is optional and derived below.
        if not isinstance(fields.get("status"), str) or not fields["status"].strip():
            raise CaptureError("missing_metadata")
        packet_fields = _resolve_packet_fields(path, source_task)
        specialist = _resolve_specialist(fields, packet_fields)
        status_value = _slug(fields["status"], "unknown")
        namespace = _source_namespace(path)
        raw_mode = fields.get("mode") or packet_fields.get("mode") or DEFAULT_MODES.get(
            namespace, "unknown"
        )
        if not isinstance(raw_mode, str):
            raise CaptureError("malformed_frontmatter")
        mode = _slug(raw_mode, "unknown")
        verdict = fields.get("verdict", "")
        if not isinstance(verdict, str):
            raise CaptureError("malformed_frontmatter")
        artifacts = fields.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise CaptureError("malformed_frontmatter")
        summary = _bounded_summary(body, verdict, artifacts)
        title_summary = _clean_one_line(verdict) or _clean_one_line(summary)
        title = f"{specialist}: {title_summary}"[:MAX_TITLE_CHARS].rstrip()

        known_route = namespace in KNOWN_NAMESPACES and mode in KNOWN_INTERNAL_MODES
        declared_sensitivity = fields.get("sensitivity")
        if declared_sensitivity is not None and not isinstance(
            declared_sensitivity, str
        ):
            raise CaptureError("malformed_frontmatter")
        sensitivity = (
            "internal"
            if known_route
            and namespace != "security"
            and mode != "bounty"
            and declared_sensitivity in {None, "internal"}
            else "restricted"
        )
        target_value = fields.get("target")
        target = (
            _slug(target_value, mode)
            if isinstance(target_value, str) and target_value.strip()
            else mode
        )
        artifact_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        root = resolve_vault_root()
        with _dedupe_lock(root):
            duplicate = _find_duplicate(root, source_task, artifact_hash)
            if duplicate is not None:
                return _result(False, duplicate, "duplicate")
            created = record(
                "learning",
                {
                    "title": title,
                    "body": summary,
                    "status": "candidate",
                    "target": target,
                    "component": namespace,
                    "attack_class": _slug(
                        f"{mode}-{specialist}",
                        "task-outcome",
                    ),
                    "sensitivity": sensitivity,
                    "source_task": source_task,
                    "source_artifact_hash": artifact_hash,
                    "keywords": [
                        f"specialist-{specialist}",
                        f"status-{status_value}",
                    ],
                },
            )
        return _result(True, created["id"], "captured")
    except CaptureError as exc:
        return _result(False, None, str(exc))
    except Exception:
        return _result(False, None, "capture_failed")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: autocapture.py <TASK-...-response.md>", file=sys.stderr)
        return 64
    result = capture_response(arguments[0])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["reason"] in {"captured", "duplicate", "not_response"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
