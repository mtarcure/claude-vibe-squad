#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Reconcile `_state/active-tasks.json` from landed task responses."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Obsidian-Claude-Vibe-Squad"))
STATE_DIR = Path(os.environ.get("STATE_DIR", VAULT_ROOT / "_state"))
REGISTRY_PATH = STATE_DIR / "active-tasks.json"
CHRONO_QUEUE_PATH = STATE_DIR / "chrono-queue.md"
LONG_RUNNING_NOTED_DIR = STATE_DIR / "long-running-noted"
LONG_RUNNING_MIN_AGE = timedelta(minutes=15)
LONG_RUNNING_DEBOUNCE = timedelta(minutes=15)
LONG_RUNNING_STALE_AGE = timedelta(hours=12)
SQUAD_SESSION = os.environ.get("SQUAD_SESSION", "squad")
TMUX_BIN = os.environ.get("TMUX_BIN", "tmux")
CHRONO_TMUX_TARGET = os.environ.get("CHRONO_TMUX_TARGET", f"{SQUAD_SESSION}:chrono")
RESPONSE_MIN_AGE = timedelta(seconds=float(os.environ.get("RESPONSE_MIN_AGE_SECONDS", "5")))
NO_ENVELOPE_GRACE = timedelta(
    seconds=float(
        os.environ.get(
            "NO_ENVELOPE_GRACE_SECONDS",
            str(float(os.environ.get("NO_ENVELOPE_GRACE_MINUTES", "10")) * 60),
        )
    )
)
NO_ENVELOPE_MIN_DISPATCH_AGE = timedelta(
    seconds=float(os.environ.get("NO_ENVELOPE_MIN_DISPATCH_AGE_SECONDS", "60"))
)
SETTLED_WITHOUT_ENVELOPE = "work-done-no-envelope"
REVIEW_REQUIRED = "review-required"
RUNTIME_MAP_PATH = VAULT_ROOT / "shared" / "specialist-runtime-map.tsv"

# Executing lane -> review lanes it can run IN-LANE (same-family), per
# shared/protocol.md "Mandatory Review Behavior". Only gpt-codex can invoke
# Claude as an in-lane tool today; every OTHER cross-lane pair needs a separate
# reviewer response, which is exactly what this enforcement requires. Lanes are
# normalized to the registry spelling ("gpt-codex", not the map's "codex").
IN_LANE_REVIEW_CAPABLE = {"gpt-codex": {"claude"}}

# Read-only review packets performed by verdict-producing roles must not require
# a review of their own review. The explicit empty write scope is essential:
# reviewer specialists doing implementation work still follow the normal gate.
REVIEW_VERDICT_SPECIALISTS = frozenset({"code-reviewer", "security-analyst"})


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


@contextmanager
def lockdir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    while not acquired:
        try:
            path.mkdir()
            acquired = True
            (path / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            break
        except FileExistsError:
            owner_text = read_text(path / "owner.pid").strip()
            if owner_text.isdigit():
                try:
                    os.kill(int(owner_text), 0)
                    time.sleep(0.1)
                    continue
                except ProcessLookupError:
                    try:
                        (path / "owner.pid").unlink(missing_ok=True)
                        path.rmdir()
                    except OSError:
                        time.sleep(0.1)
                    continue
                except PermissionError:
                    time.sleep(0.1)
                    continue
            try:
                age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                time.sleep(0.1)
                continue
            if age > timedelta(minutes=5):
                try:
                    (path / "owner.pid").unlink(missing_ok=True)
                    path.rmdir()
                except OSError:
                    time.sleep(0.1)
                continue
            time.sleep(0.1)
    try:
        yield
    finally:
        if acquired:
            try:
                (path / "owner.pid").unlink(missing_ok=True)
                path.rmdir()
            except OSError:
                pass


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def append_chrono_queue(status: str, task_ref: str, summary: str) -> None:
    safe_summary = re.sub(r"\s+", " ", summary or "").strip().replace("|", "/")
    if not safe_summary:
        safe_summary = "(no pane snippet)"
    safe_summary = safe_summary[:200]
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | {status} | {task_ref} | {safe_summary}\n"
    with lockdir(CHRONO_QUEUE_PATH.with_suffix(CHRONO_QUEUE_PATH.suffix + ".lockdir")):
        existing = read_text(
            CHRONO_QUEUE_PATH,
            "# Chrono Queue\n# timestamp | status | namespace/task-id | summary\n\n",
        )
        atomic_write(CHRONO_QUEUE_PATH, existing + line)


def nudge_chrono(message: str) -> bool:
    """Send a literal mid-session nudge to the tmux window named ``chrono``."""
    try:
        session = subprocess.run(
            [TMUX_BIN, "has-session", "-t", SQUAD_SESSION],
            capture_output=True,
            timeout=5,
        )
        if session.returncode != 0:
            return False
        literal = subprocess.run(
            [TMUX_BIN, "send-keys", "-l", "-t", CHRONO_TMUX_TARGET, message],
            capture_output=True,
            timeout=5,
        )
        if literal.returncode != 0:
            return False
        submit = subprocess.run(
            [TMUX_BIN, "send-keys", "-t", CHRONO_TMUX_TARGET, "Enter"],
            capture_output=True,
            timeout=5,
        )
        return submit.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def emit_event(status: str, task_ref: str, summary: str, nudge: str) -> bool:
    append_chrono_queue(status, task_ref, summary)
    return nudge_chrono(nudge)


class RegistryCorruptError(RuntimeError):
    """active-tasks.json exists but is malformed or is not a JSON object."""


def _preserve_corrupt_registry(raw: bytes) -> None:
    """Best-effort timestamped diagnostic copy of a corrupt registry.

    Writes the raw bytes byte-for-byte (binary) so an invalid-UTF-8 registry is
    preserved exactly, not lossily re-encoded.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    diagnostic = REGISTRY_PATH.with_name(f"{REGISTRY_PATH.name}.corrupt.{stamp}")
    try:
        if not diagnostic.exists():
            with diagnostic.open("xb") as handle:
                handle.write(raw)
    except OSError:
        pass


def load_registry() -> dict[str, Any]:
    """Load the active-task registry.

    An ABSENT file is a legitimate empty registry ({}). A file that EXISTS but is
    not valid UTF-8, not valid JSON, or is valid JSON that is not an object, is a
    HARD corruption error: we refuse to write (a subsequent register/reconcile
    write would erase every in-flight task), preserve a timestamped diagnostic copy
    (byte-for-byte), and surface the failure — we never silently reset the registry
    to empty.
    """
    try:
        raw_bytes = REGISTRY_PATH.read_bytes()
    except FileNotFoundError:
        return {}
    # MED4 (wave-2): read BYTES first. read_text(encoding="utf-8") raises
    # UnicodeDecodeError BEFORE the JSON branch, which would escape uncaught (no
    # exit-2, no diagnostic). Decode explicitly and translate the failure.
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            f"active-tasks.json is not valid UTF-8 ({exc}); refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            f"active-tasks.json is not valid JSON ({exc}); refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        ) from exc
    if not isinstance(data, dict):
        _preserve_corrupt_registry(raw_bytes)
        raise RegistryCorruptError(
            "active-tasks.json is not a JSON object; refusing to write and "
            "preserving a diagnostic copy — will not reset the registry to empty"
        )
    return data


def locked_registry():
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".lock")
    lock_fh = lock_path.open("w", encoding="utf-8")
    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    return lock_fh


def register_task(task_id: str, entry: dict[str, Any]) -> None:
    """Add or replace one dispatch entry under the reconciler's registry lock."""
    with locked_registry() as _lock:
        registry = load_registry()
        registry[task_id] = entry
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def strip_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


# FIX 3 (wave-2): ONE canonical settleable-status vocabulary — the single source
# of truth for which response statuses may settle a task. A landed response may
# settle a task only to a status here; empty / unknown / typo statuses canonicalize
# to "" and are rejected, so a misspelling can NEVER settle a task with a bogus
# state (fail closed → the task stays open). `bin/outbox-watcher.sh` delegates ALL
# settlement to this module and never settles on its own, so this is the sole
# settle authority. `review-required` / `work-done-no-envelope` are reconciler
# registry states, not response statuses, and are intentionally not settleable here.
_STATUS_ALIASES = {"completed": "complete", "canceled": "cancelled"}
SETTLEABLE_STATUSES = frozenset(
    {"complete", "needs_review", "blocked", "needs_human", "cancelled"}
)


def registry_status(raw: str) -> str:
    """Canonicalize a landed response status; '' for empty/unknown (fail closed)."""
    status = (raw or "").strip()
    status = _STATUS_ALIASES.get(status, status)
    return status if status in SETTLEABLE_STATUSES else ""


def response_status(path: Path) -> str:
    return registry_status(strip_frontmatter(read_text(path)).get("status", ""))


def valid_response_status(status: str) -> bool:
    """True only for a canonical settleable status (rejects '', 'in-flight', typos)."""
    return status in SETTLEABLE_STATUSES


def response_ready(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age >= RESPONSE_MIN_AGE


def response_candidates(task_id: str) -> list[Path]:
    departments = VAULT_ROOT / "departments"
    candidates: list[Path] = []
    for state in ("outbox", "archive"):
        candidates.extend(departments.glob(f"*/{state}/{task_id}-response.md"))
    return sorted(
        set(candidates),
        key=lambda path: (path.stat().st_mtime, str(path)),
        reverse=True,
    )


def landed_response(
    task_id: str, candidates: list[Path] | None = None
) -> tuple[Path | None, str]:
    for candidate in candidates if candidates is not None else response_candidates(task_id):
        if not response_ready(candidate):
            continue
        status = response_status(candidate)
        if valid_response_status(status):
            return candidate, status
    return None, ""


def response_namespace(path: Path) -> str:
    try:
        index = path.parts.index("departments")
        return path.parts[index + 1]
    except (ValueError, IndexError):
        return "unknown"


def response_summary(path: Path) -> str:
    text = read_text(path)
    match = re.match(r"^---\s*\n.*?\n---\s*(?:\n|$)(.*)$", text, re.S)
    body = match.group(1) if match else text
    for paragraph in re.split(r"\n\s*\n", body):
        summary = re.sub(r"\s+", " ", paragraph.strip().lstrip("#").strip())
        if summary:
            return summary[:200]
    return "response envelope landed"


def task_packet_candidates(task_id: str) -> list[Path]:
    departments = VAULT_ROOT / "departments"
    candidates: list[Path] = []
    for state in ("inbox", "active", "archive"):
        candidates.extend(departments.glob(f"*/{state}/{task_id}.md"))
    return sorted(set(candidates), key=str)


def return_artifact_path(task_id: str, entry: dict[str, Any]) -> Path | None:
    raw = str(entry.get("return_artifact") or "").strip()
    if not raw:
        for packet in task_packet_candidates(task_id):
            raw = strip_frontmatter(read_text(packet)).get("return_artifact", "").strip()
            if raw:
                entry["return_artifact"] = raw
                break
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else VAULT_ROOT / path


def _lane(value: Any) -> str:
    lane = str(value or "").strip().lower()
    return "gpt-codex" if lane == "codex" else lane


def _specialist_primary_lane(specialist: str) -> str:
    """Primary lane (registry spelling) for a specialist from the runtime map."""
    if not specialist:
        return ""
    try:
        with RUNTIME_MAP_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if parts and parts[0] == specialist and len(parts) >= 7:
                    return _lane(parts[6])
    except OSError:
        return ""
    return ""


def _is_read_only_review_task(entry: dict[str, Any]) -> bool:
    """True only for an explicitly read-only task owned by a verdict role."""
    specialist = str(entry.get("specialist") or "").strip()
    return specialist in REVIEW_VERDICT_SPECIALISTS and entry.get("write_scope") == []


def cross_family_review_pending(entry: dict[str, Any]) -> tuple[bool, str, str]:
    """Decide whether a task needs an out-of-lane review response before settling.

    Returns (pending, executing_lane, review_lane). Pending is True for a genuine
    cross-family review: mandatory_review is true, review_model names a real lane,
    and the task's ACTUAL executing lane cannot run that review in-lane.

    The exemption is based on the real execution lane (`to_model`, after dispatch
    override validation) — falling back to the specialist's mapped primary lane
    only when `to_model` is absent — so a specialist mapped to gpt-codex but
    overridden to another lane cannot inherit the gpt-codex->claude exemption.
    An indeterminate lane fails CLOSED (pending) rather than settling silently.
    """
    if str(entry.get("mandatory_review", "")).strip().lower() != "true":
        return (False, "", "")
    review_lane = _lane(entry.get("review_model"))
    if review_lane in ("", "none"):
        return (False, "", "")
    executing_lane = _lane(entry.get("to_model")) \
        or _specialist_primary_lane(str(entry.get("specialist") or ""))
    if not executing_lane:
        # Fix 6: unknown execution lane for a mandatory review with a real
        # reviewer — fail closed (open), never treat as non-pending.
        return (True, "unknown", review_lane)
    if _is_read_only_review_task(entry):
        # A review of a read-only review creates an infinite regress. The exact
        # role allowlist and explicit empty write scope keep this exemption
        # narrow; implementation-bearing reviewer tasks are not exempt.
        return (False, executing_lane, review_lane)
    if executing_lane == review_lane:
        return (False, executing_lane, review_lane)
    if review_lane in IN_LANE_REVIEW_CAPABLE.get(executing_lane, set()):
        return (False, executing_lane, review_lane)
    return (True, executing_lane, review_lane)


def _review_reference(raw: str) -> tuple[Path, str]:
    """Resolve an explicit review reference to a mailbox response file."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = VAULT_ROOT / path
    if path.is_symlink():
        raise ValueError("--review-ref must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(VAULT_ROOT.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError("--review-ref must name an existing mailbox response") from exc
    parts = relative.parts
    if (
        not resolved.is_file()
        or len(parts) != 4
        or parts[0] != "departments"
        or parts[2] not in {"outbox", "archive"}
        or not parts[3].endswith("-response.md")
    ):
        raise ValueError("--review-ref must name an outbox/archive response inside VAULT_ROOT")
    return resolved, str(relative)


def settle_review(task_id: str, review_ref: str) -> bool:
    """Explicitly settle one held cross-family review under the registry lock.

    Review files have no automatic authority. This command is the trusted Chrono
    action taken only after the controller has read the referenced review and
    decided that the task may close. Returns False for an idempotent retry.
    """
    _review_path, normalized_ref = _review_reference(review_ref)
    with locked_registry() as _lock:
        registry = load_registry()
        entry = registry.get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown registry task: {task_id}")
        if entry.get("status") == "complete" and entry.get("review_settled_by") == "chrono-explicit":
            if entry.get("cross_family_review_ref") == normalized_ref:
                return False
            raise ValueError(f"task already settled with a different review ref: {task_id}")
        if entry.get("status") != REVIEW_REQUIRED:
            raise ValueError(f"task is not {REVIEW_REQUIRED}: {task_id}")
        pending, _executing_lane, _review_lane = cross_family_review_pending(entry)
        if not pending:
            raise ValueError(f"task does not require cross-family settlement: {task_id}")
        response, status = landed_response(task_id)
        if response is None:
            raise ValueError(f"task has no landed response: {task_id}")
        if status not in {"complete", "needs_review"}:
            raise ValueError(f"task response status cannot be settled: {status or 'missing'}")
        if normalized_ref == str(response.relative_to(VAULT_ROOT)):
            raise ValueError("--review-ref must not be the task's own response")

        now = datetime.now(timezone.utc)
        entry["status"] = "complete"
        entry["completed_at"] = now.isoformat()
        entry["reconciled_at"] = now.isoformat()
        entry["review_settled_at"] = now.isoformat()
        entry["review_settled_by"] = "chrono-explicit"
        entry["cross_family_review_ref"] = normalized_ref
        entry["response_path"] = str(response.relative_to(VAULT_ROOT))
        entry.pop("review_blocking_ref", None)
        entry.pop("review_signature", None)
        atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
        namespace = str(
            entry.get("compatibility_namespace")
            or entry.get("source_namespace")
            or "coding"
        )
    append_chrono_queue(
        "REVIEW-SETTLED",
        f"{namespace}/{task_id}",
        f"explicit Chrono settlement; review={normalized_ref}",
    )
    return True


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def append_drift(task_id: str, detail: str) -> None:
    path = STATE_DIR / "cleanup-logs" / f"{utc_date()}-registry-drift.md"
    existing = read_text(path, f"# Registry Drift - {utc_date()}\n\n")
    atomic_write(path, existing + f"- {datetime.now(timezone.utc).isoformat()} {task_id}: {detail}\n")


def marker_recent(task_id: str, now: datetime) -> bool:
    marker = LONG_RUNNING_NOTED_DIR / f"{task_id}.noted"
    try:
        age = now - datetime.fromtimestamp(marker.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return False
    return age < LONG_RUNNING_DEBOUNCE


def touch_marker(task_id: str) -> None:
    LONG_RUNNING_NOTED_DIR.mkdir(parents=True, exist_ok=True)
    marker = LONG_RUNNING_NOTED_DIR / f"{task_id}.noted"
    marker.touch()


def meaningful_lines(text: str, limit: int = 3) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def pane_snapshot(to_model: str) -> tuple[str, str]:
    target = f"{SQUAD_SESSION}:{to_model}"
    try:
        result = subprocess.run(
            [TMUX_BIN, "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown", "pane unreachable"
    if result.returncode != 0:
        return "unknown", "pane unreachable"
    lines = meaningful_lines(result.stdout or "")
    snippet = " / ".join(lines)[:200] if lines else "(pane blank)"
    joined = "\n".join(lines)
    active_re = re.compile(
        r"(Working|Waiting for background|esc to interrupt|Wandering|Thinking|Brewed|Running|Applying patch)",
        re.I,
    )
    idle_re = re.compile(r"(Explain this codebase|^▶|❯|^\$|^%|^>)", re.I | re.M)
    if active_re.search(joined):
        return "active", snippet
    if idle_re.search(joined):
        return "idle", snippet
    return "unknown", snippet


def note_long_running(task_id: str, entry: dict[str, Any], now: datetime, dry_run: bool) -> str | None:
    if entry.get("chrono_reconciled") is True:
        return None
    dispatched = parse_dt(entry.get("dispatched_at"))
    if not dispatched:
        return None
    elapsed = now - dispatched
    if elapsed < LONG_RUNNING_MIN_AGE or elapsed >= LONG_RUNNING_STALE_AGE:
        return None
    if response_candidates(task_id) or marker_recent(task_id, now):
        return None
    namespace = str(entry.get("compatibility_namespace") or "coding")
    to_model = str(entry.get("to_model") or "unknown-model")
    state, snippet = pane_snapshot(to_model)
    if not dry_run:
        append_chrono_queue(f"long-running:{state}", f"{namespace}/{task_id}", snippet)
        touch_marker(task_id)
    return f"long-running:{state} {task_id}"


def reconcile(task_id_filter: str | None, dry_run: bool) -> tuple[int, list[str]]:
    events: list[tuple[str, str, str, str]] = []
    with locked_registry() as _lock:
        registry = load_registry()
        now = datetime.now(timezone.utc)
        changed = 0
        messages: list[str] = []
        for task_id, raw_entry in registry.items():
            if task_id_filter and task_id != task_id_filter:
                continue
            if not isinstance(raw_entry, dict):
                continue
            current_status = str(raw_entry.get("status", ""))
            if current_status not in {"in-flight", SETTLED_WITHOUT_ENVELOPE, REVIEW_REQUIRED}:
                if task_id_filter:
                    messages.append(f"already-settled {task_id} -> {current_status}")
                continue
            candidates = response_candidates(task_id)
            response, status = landed_response(task_id, candidates)
            if response is None and candidates:
                # BLOCK2 (wave-2): a response file may EXIST and be old enough to
                # settle yet carry a non-canonical status (typo/unknown). landed_response
                # returns None for it; without this guard execution falls through to the
                # return-artifact path and settles the task to work-done-no-envelope —
                # which, for a mandatory cross-family task, silently bypasses the Option-A
                # review-required hold. Distinguish "no response exists" from "a response
                # exists but its status is INVALID": for the latter keep the task OPEN
                # (fail closed) and flag it; never settle on an unusable status.
                # Presence alone suppresses the no-envelope backstop, including
                # during the response quiescence/min-age window. Otherwise a young
                # invalid response can be ignored once, settle through the artifact
                # backstop, and remain provisionally settled when it becomes ready.
                reopened = current_status == SETTLED_WITHOUT_ENVELOPE
                if reopened:
                    raw_entry["status"] = "in-flight"
                    raw_entry.pop("work_landed_at", None)
                    raw_entry.pop("missing_envelope_artifact", None)
                    raw_entry.pop("prior_missing_envelope_status", None)

                stray = next((cand for cand in candidates if response_ready(cand)), None)
                if stray is None:
                    if reopened:
                        raw_entry["reconciled_at"] = now.isoformat()
                        changed += 1
                        messages.append(
                            f"response-pending {task_id} -> reopened pending status validation"
                        )
                    elif task_id_filter:
                        messages.append(f"response-pending {task_id} -> awaiting status validation")
                    continue

                bad_status = strip_frontmatter(read_text(stray)).get("status", "")
                namespace = response_namespace(stray)
                response_path = str(stray.relative_to(VAULT_ROOT))
                metadata_changed = (
                    raw_entry.get("response_path") != response_path
                    or raw_entry.get("invalid_response_status") != bad_status
                )
                if reopened or metadata_changed:
                    raw_entry["invalid_response_status"] = bad_status
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    changed += 1
                    messages.append(
                        f"invalid-response-status {task_id} -> {bad_status!r} (kept open)"
                    )
                    events.append(
                        (
                            "INVALID-RESPONSE-STATUS",
                            f"{namespace}/{task_id}",
                            f"response {response_path} has non-canonical status {bad_status!r}",
                            f"INVALID RESPONSE STATUS: {task_id} response status {bad_status!r} is "
                            "not canonical; registry kept OPEN (not settled, review hold intact). "
                            "Fix the response 'status' field or re-dispatch.",
                        )
                    )
                continue
            if response is not None:
                namespace = response_namespace(response)
                # A genuine cross-family mandatory_review task may NOT settle on
                # its own response or on any parsed review file. It stays held
                # until Chrono explicitly runs --settle-review after reading the
                # review. Unknown or malformed review state is therefore inert.
                pending, executing_lane, review_lane = cross_family_review_pending(raw_entry)
                if pending:
                    newly_flagged = current_status != REVIEW_REQUIRED
                    lane_changed = raw_entry.get("review_required_by") != review_lane
                    response_path = str(response.relative_to(VAULT_ROOT))
                    response_changed = raw_entry.get("response_path") != response_path
                    obsolete_present = any(
                        key in raw_entry
                        for key in (
                            "cross_family_review_ref",
                            "review_blocking_ref",
                            "review_signature",
                            "invalid_response_status",
                        )
                    )
                    raw_entry["status"] = REVIEW_REQUIRED
                    raw_entry["review_required_by"] = review_lane
                    raw_entry["response_path"] = response_path
                    raw_entry["reconciled_at"] = now.isoformat()
                    raw_entry.pop("cross_family_review_ref", None)
                    raw_entry.pop("review_blocking_ref", None)
                    raw_entry.pop("review_signature", None)
                    raw_entry.pop("invalid_response_status", None)
                    if newly_flagged or lane_changed or response_changed or obsolete_present:
                        changed += 1
                    if newly_flagged or lane_changed:
                        reason = f"awaiting explicit Chrono settlement after {review_lane} review"
                        messages.append(f"review-required {task_id} -> {reason}")
                        events.append(
                            (
                                "REVIEW-REQUIRED",
                                f"{namespace}/{task_id}",
                                f"{executing_lane} specialist '{raw_entry.get('specialist')}' "
                                f"needs {review_lane} review; {reason}",
                                f"REVIEW-REQUIRED: {task_id} ({raw_entry.get('specialist')}, lane "
                                f"{executing_lane}) must be cross-family reviewed by {review_lane} "
                                f"before it can settle. {reason}. Dispatch/read the {review_lane} review, "
                                "then use registry_reconciler.py --settle-review with its review ref.",
                            )
                        )
                    continue
                if current_status == SETTLED_WITHOUT_ENVELOPE:
                    raw_entry["prior_missing_envelope_status"] = current_status
                raw_entry["status"] = status
                raw_entry["completed_at"] = datetime.fromtimestamp(
                    response.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry["auto_reconciled_at"] = now.isoformat()
                raw_entry["response_path"] = str(response.relative_to(VAULT_ROOT))
                raw_entry.pop("invalid_response_status", None)
                changed += 1
                messages.append(f"reconciled {task_id} -> {status} via {namespace}")
                events.append(
                    (
                        status,
                        f"{namespace}/{task_id}",
                        response_summary(response),
                        f"{status}: {task_id} response landed in departments/{namespace}/"
                        f"{response.parent.name}/{response.name}; registry reconciled. Read and surface now.",
                    )
                )
                continue
            if current_status == SETTLED_WITHOUT_ENVELOPE:
                # This is a provisional settled state: it stops counting as
                # running, but a later real envelope must still win.
                continue
            artifact = return_artifact_path(task_id, raw_entry)
            if artifact and artifact.is_file():
                pane_state, snippet = pane_snapshot(str(raw_entry.get("to_model") or "unknown-model"))
                artifact_mtime = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
                artifact_age = now - artifact_mtime
                dispatched = parse_dt(raw_entry.get("dispatched_at"))
                artifact_fresh = dispatched is None or artifact_mtime >= dispatched
                dispatch_old_enough = (
                    dispatched is not None and now - dispatched >= NO_ENVELOPE_MIN_DISPATCH_AGE
                )
                grace_elapsed = dispatch_old_enough and artifact_age >= NO_ENVELOPE_GRACE
                if artifact_fresh and pane_state != "active" and (pane_state == "idle" or grace_elapsed):
                    namespace = str(
                        raw_entry.get("compatibility_namespace")
                        or raw_entry.get("source_namespace")
                        or "coding"
                    )
                    raw_entry["status"] = SETTLED_WITHOUT_ENVELOPE
                    raw_entry["work_landed_at"] = artifact_mtime.isoformat()
                    raw_entry["reconciled_at"] = now.isoformat()
                    raw_entry["missing_envelope_artifact"] = str(artifact)
                    changed += 1
                    reason = "lane idle" if pane_state == "idle" else f"artifact grace {artifact_age}"
                    messages.append(f"flagged {task_id} -> {SETTLED_WITHOUT_ENVELOPE} ({reason})")
                    events.append(
                        (
                            SETTLED_WITHOUT_ENVELOPE,
                            f"{namespace}/{task_id}",
                            f"artifact={artifact} / pane={pane_state} / {snippet}",
                            f"WORK DONE, NO ENVELOPE: {task_id} return artifact exists and {reason}. "
                            "Registry no longer counts it as running; inspect and reconcile now.",
                        )
                    )
                    continue
            dispatched = parse_dt(raw_entry.get("dispatched_at"))
            if dispatched and now - dispatched > timedelta(hours=12):
                if not dry_run:
                    append_drift(task_id, f"no response after >12h; status={current_status}")
                messages.append(f"drift {task_id}")
            long_running_message = note_long_running(task_id, raw_entry, now, dry_run)
            if long_running_message:
                messages.append(long_running_message)
        if changed and not dry_run:
            atomic_write(REGISTRY_PATH, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    if not dry_run:
        for status, task_ref, summary, nudge in events:
            nudged = emit_event(status, task_ref, summary, nudge)
            messages.append(f"chrono-nudge {'sent' if nudged else 'queued-only'} {task_ref}")
    return changed, messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id")
    parser.add_argument("--register-task")
    parser.add_argument("--entry-json")
    parser.add_argument("--settle-review")
    parser.add_argument("--review-ref")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if bool(args.register_task) != bool(args.entry_json):
        parser.error("--register-task and --entry-json must be used together")
    if bool(args.settle_review) != bool(args.review_ref):
        parser.error("--settle-review and --review-ref must be used together")
    if args.register_task:
        if args.dry_run or args.task_id or args.settle_review:
            parser.error(
                "--register-task cannot be combined with --task-id, --settle-review, or --dry-run"
            )
        try:
            entry = json.loads(args.entry_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--entry-json is not valid JSON: {exc}")
        if not isinstance(entry, dict):
            parser.error("--entry-json must decode to an object")
        try:
            register_task(args.register_task, entry)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"registry-reconciler register: task={args.register_task}")
        return 0
    if args.settle_review:
        if args.dry_run or args.task_id:
            parser.error("--settle-review cannot be combined with --task-id or --dry-run")
        try:
            changed = settle_review(args.settle_review, args.review_ref)
        except RegistryCorruptError as exc:
            print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        outcome = "settled" if changed else "already-settled"
        print(f"registry-reconciler review: {outcome} task={args.settle_review}")
        return 0
    try:
        changed, messages = reconcile(args.task_id, args.dry_run)
    except RegistryCorruptError as exc:
        print(f"registry-reconciler ERROR: {exc}", file=sys.stderr)
        return 2
    mode = "dry-run" if args.dry_run else "write"
    print(f"registry-reconciler {mode}: changes={changed}")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
