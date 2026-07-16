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


def load_registry() -> dict[str, Any]:
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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


def registry_status(raw: str) -> str:
    """Preserve truthful response states while retaining the historical close alias."""
    status = raw.strip()
    if status in {"complete", "completed"}:
        return "complete"
    if status == "canceled":
        return "cancelled"
    return status


def response_status(path: Path) -> str:
    return registry_status(strip_frontmatter(read_text(path)).get("status", ""))


def valid_response_status(status: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", status)) and status != "in-flight"


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


def landed_response(task_id: str) -> tuple[Path | None, str]:
    for candidate in response_candidates(task_id):
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
            if current_status not in {"in-flight", SETTLED_WITHOUT_ENVELOPE}:
                if task_id_filter:
                    messages.append(f"already-settled {task_id} -> {current_status}")
                continue
            response, status = landed_response(task_id)
            if response is not None:
                namespace = response_namespace(response)
                if current_status == SETTLED_WITHOUT_ENVELOPE:
                    raw_entry["prior_missing_envelope_status"] = current_status
                raw_entry["status"] = status
                raw_entry["completed_at"] = datetime.fromtimestamp(
                    response.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                raw_entry["reconciled_at"] = now.isoformat()
                raw_entry["auto_reconciled_at"] = now.isoformat()
                raw_entry["response_path"] = str(response.relative_to(VAULT_ROOT))
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if bool(args.register_task) != bool(args.entry_json):
        parser.error("--register-task and --entry-json must be used together")
    if args.register_task:
        if args.dry_run or args.task_id:
            parser.error("--register-task cannot be combined with --task-id or --dry-run")
        try:
            entry = json.loads(args.entry_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--entry-json is not valid JSON: {exc}")
        if not isinstance(entry, dict):
            parser.error("--entry-json must decode to an object")
        register_task(args.register_task, entry)
        print(f"registry-reconciler register: task={args.register_task}")
        return 0
    changed, messages = reconcile(args.task_id, args.dry_run)
    mode = "dry-run" if args.dry_run else "write"
    print(f"registry-reconciler {mode}: changes={changed}")
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
