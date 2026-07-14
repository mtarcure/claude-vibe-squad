#!/usr/bin/env bash
# vs-lane-status.sh — background poller that writes tmux-consumable status
# files. Runs once as a daemon (spawned by launch-squad.sh); tmux reads the
# files via #(cat /tmp/vs-lane-*.status) in pane-border-format.
#
# Why a poller instead of per-render #() calls:
#   Fable 5 flagged this: tmux runs #() once per pane per status-interval.
#   With 5 panes × 1s refresh that's 5 req/s against the daemon. This poller
#   fetches ONCE per second and writes cached files, so tmux does zero
#   network work on each render.
set -u

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
PANEL_ACTIVITY_DIR="${PANEL_ACTIVITY_DIR:-${VAULT_ROOT}/_state/runtime/lane-activity}"
VIBESQUAD_STATUS_DIR="${VIBESQUAD_STATUS_DIR:-/tmp}"
VS_DAEMON_TASKS_FILE="${VS_DAEMON_TASKS_FILE:-}"
VS_STATUS_ONCE="${VS_STATUS_ONCE:-0}"
VS_STATUS_INTERVAL="${VS_STATUS_INTERVAL:-1}"
VS_STATUS_NOW="${VS_STATUS_NOW:-}"
VS_ORPHAN_GRACE_SECONDS="${VS_ORPHAN_GRACE_SECONDS:-30}"
ROSTER_FILE="${VAULT_ROOT}/model-lanes/ROSTER.md"

if [[ -z "$VS_DAEMON_TASKS_FILE" ]]; then
    : "${VIBESQUAD_DAEMON_TOKEN:?VIBESQUAD_DAEMON_TOKEN must be exported}"
fi

FRAMES='⣷⣯⣟⡿⢿⣻⣽⣾'
FRAME_COUNT=${#FRAMES}
mkdir -p "$VIBESQUAD_STATUS_DIR"

# Colors — match Claude Code palette (colour74 cyan accent, colour252 text,
# colour240 dim, colour214 amber, colour167 red).
#
# CRITICAL: emit tmux-native #[...] markup, NOT raw \033[ ANSI. This output is
# consumed by tmux via #(cat /tmp/vs-*.status) in status/pane-border formats,
# and tmux interprets #[fg=colourNN] but renders raw ANSI escapes as literal
# garbage text (e.g. "[38;5;74m●daemon"). #[default] resets to the format's
# surrounding style.
CYAN='#[fg=colour74]'
TEXT='#[fg=colour252]'
DIM='#[fg=colour240]'
AMBER='#[fg=colour214]'
RED='#[fg=colour167]'
RESET='#[default]'

tick=0
while :; do
    tick=$((tick + 1))
    i=$((tick % FRAME_COUNT))
    spin="${FRAMES:$i:1}"

    daemon_online=1
    if [[ -n "$VS_DAEMON_TASKS_FILE" ]]; then
        json="$(timeout 3 /bin/cat "$VS_DAEMON_TASKS_FILE" 2>/dev/null)" || {
            json='{"tasks":[]}'
            daemon_online=0
        }
    else
        json="$(curl -sfm 3 \
            -H "Authorization: Bearer $VIBESQUAD_DAEMON_TOKEN" \
            http://127.0.0.1:9876/tasks 2>/dev/null)" || {
            json='{"tasks":[]}'
            daemon_online=0
        }
    fi

    now="${VS_STATUS_NOW:-$(date +%s)}"
    VS_DAEMON_JSON="$json" \
        VS_PROJECT_NOW="$now" \
        VS_PROJECT_SPIN="$spin" \
        VS_PROJECT_TICK="$tick" \
        VS_DAEMON_ONLINE="$daemon_online" \
        PANEL_ACTIVITY_DIR="$PANEL_ACTIVITY_DIR" \
        VIBESQUAD_STATUS_DIR="$VIBESQUAD_STATUS_DIR" \
        ROSTER_FILE="$ROSTER_FILE" \
        VS_ORPHAN_GRACE_SECONDS="$VS_ORPHAN_GRACE_SECONDS" \
        /usr/bin/python3 - <<'PY'
import json
import os
import re
import sys
import tempfile
from pathlib import Path

LANES = ("chrono", "gpt-codex", "claude", "gemini", "kimi")
CYAN = "#[fg=colour74]"
TEXT = "#[fg=colour252]"
DIM = "#[fg=colour240]"
AMBER = "#[fg=colour214]"
RED = "#[fg=colour167]"
RESET = "#[default]"

now = int(os.environ["VS_PROJECT_NOW"])
spin = os.environ["VS_PROJECT_SPIN"]
tick = int(os.environ["VS_PROJECT_TICK"])
daemon_online = os.environ.get("VS_DAEMON_ONLINE") == "1"
activity_root = Path(os.environ["PANEL_ACTIVITY_DIR"])
status_root = Path(os.environ["VIBESQUAD_STATUS_DIR"])
roster_path = Path(os.environ["ROSTER_FILE"])
orphan_grace = int(os.environ["VS_ORPHAN_GRACE_SECONDS"])


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def roster_names() -> set[str]:
    try:
        text = roster_path.read_text(errors="replace")
    except OSError:
        return set()
    return set(re.findall(r"^- `([a-z0-9][a-z0-9-]*)` ", text, re.MULTILINE))


allowed = roster_names()
control_re = re.compile(r"[\x00-\x1f\x7f]")
tmux_re = re.compile(r"#\[[^\]]*\]")


def safe_specialist(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = control_re.sub("", tmux_re.sub("", raw)).strip()
    return cleaned if cleaned in allowed else ""


ALIASES = {
    "ai-engineer": "ai",
    "backend-engineer": "backend",
    "code-reviewer": "review",
    "devops-engineer": "devops",
    "frontend-engineer": "frontend",
    "security-analyst": "security",
    "systems-engineer": "systems",
    "test-engineer": "test",
}


def compact_name(name: str) -> str:
    return ALIASES.get(name, name[:12])


def mmss(started: object) -> str:
    try:
        start = int(float(started))
    except (TypeError, ValueError):
        return "--:--"
    if start <= 0:
        return "--:--"
    elapsed = max(0, now - start)
    return f"{elapsed // 60:02d}:{elapsed % 60:02d}"


try:
    daemon = json.loads(os.environ.get("VS_DAEMON_JSON", ""))
except json.JSONDecodeError:
    daemon = {"tasks": []}
    daemon_online = False
if not isinstance(daemon, dict):
    daemon = {"tasks": []}
    daemon_online = False


def numeric(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

task_order = {"running": 0, "queued": 1, "done": 2}
daemon_tasks = daemon.get("tasks", [])
if not isinstance(daemon_tasks, list):
    daemon_tasks = []
daemon_by_lane: dict[str, dict] = {}
for lane in LANES:
    tasks = [
        task
        for task in daemon_tasks
        if isinstance(task, dict) and task.get("lane") == lane
    ]
    tasks.sort(key=lambda task: task_order.get(task.get("state", "idle"), 3))
    daemon_by_lane[lane] = tasks[0] if tasks else {}

active_panels: dict[str, dict] = {}
stale_panels: dict[str, dict] = {}
archive_root = activity_root / "archive"
for path in sorted(activity_root.glob("*.json")) if activity_root.exists() else []:
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        continue
    if not isinstance(record, dict):
        continue
    if record.get("schema_version") != 1 or record.get("dispatch_kind") != "panel":
        continue
    lane = record.get("lane")
    if lane not in LANES or record.get("state") != "running":
        continue
    raw_members = record.get("members", [])
    if not isinstance(raw_members, list) or not any(
        isinstance(member, dict) and safe_specialist(member.get("specialist"))
        for member in raw_members
    ):
        continue

    deadline = record.get("deadline_at_epoch")
    try:
        definitively_orphaned = deadline is not None and now > float(deadline) + orphan_grace
    except (TypeError, ValueError):
        definitively_orphaned = False
    if definitively_orphaned:
        record["state"] = "stale"
        record["orphaned_at_epoch"] = now
        record["updated_at_epoch"] = now
        record_members = record.get("members", [])
        if not isinstance(record_members, list):
            record_members = []
        for member in record_members:
            if not isinstance(member, dict):
                continue
            if member.get("state") in {"queued", "running"}:
                member["state"] = "timed_out"
                member["ended_at_epoch"] = now
                member["detail"] = "panel activity reaped after hard deadline grace"
        try:
            atomic_json(path, record)
            archive_root.mkdir(parents=True, exist_ok=True)
            destination = archive_root / path.name
            if destination.exists():
                destination = archive_root / f"{path.stem}.orphaned-{now}.json"
            os.replace(path, destination)
        except OSError:
            pass
        continue

    try:
        updated = int(float(record.get("updated_at_epoch", 0)))
        ttl = int(float(record.get("stale_ttl_seconds", 300)))
    except (TypeError, ValueError):
        updated, ttl = 0, 300
    is_stale = updated <= 0 or now - updated > max(1, ttl)
    target = stale_panels if is_stale else active_panels
    current = target.get(lane)
    if current is None or numeric(record.get("started_at_epoch")) > numeric(current.get("started_at_epoch")):
        target[lane] = record


def allowed_members(record: dict) -> list[dict]:
    result = []
    members = record.get("members", [])
    if not isinstance(members, list):
        return result
    for member in members:
        if not isinstance(member, dict):
            continue
        name = safe_specialist(member.get("specialist"))
        if name:
            result.append({**member, "specialist": name})
    return result


def panel_detail(record: dict) -> tuple[str, int]:
    members = allowed_members(record)
    count = len(members)
    prefix = f"{CYAN}{spin} {TEXT}{mmss(record.get('started_at_epoch'))}{DIM} · panel[{count}]: "
    if count > 4:
        first = members[0]["specialist"] if members else "panel"
        return prefix + f"{CYAN}×{count} ({first} +{count - 1}){RESET}", count
    rendered = []
    for member in members:
        name = member["specialist"]
        state = member.get("state")
        if state == "done":
            rendered.append(f"{DIM}{name}✓")
        elif state == "timed_out":
            rendered.append(f"{AMBER}{name}")
        elif state == "failed":
            rendered.append(f"{RED}{name}")
        elif state == "refused":
            rendered.append(f"{AMBER}{name}")
        else:
            rendered.append(f"{CYAN}{name}")
    return prefix + " ".join(rendered) + RESET, count


active_tokens = []
stale_tokens = []
swarm_members = 0
for lane in LANES:
    panel = active_panels.get(lane)
    stale = stale_panels.get(lane)
    daemon_task = daemon_by_lane[lane]
    daemon_state = daemon_task.get("state", "idle")

    if panel:
        detail, count = panel_detail(panel)
        atomic_text(status_root / f"vs-lane-{lane}.status", detail)
        active_tokens.append(
            f"{TEXT}{lane} {CYAN}{spin} {TEXT}{mmss(panel.get('started_at_epoch'))} ×{count}{RESET}"
        )
        swarm_members += count
        continue

    if stale:
        members = allowed_members(stale)
        stale_detail = f"{AMBER}stale · panel[{len(members)}]{RESET}"
        atomic_text(status_root / f"vs-lane-{lane}.status", stale_detail)
        stale_tokens.append(f"{AMBER}{lane} stale{RESET}")
        continue
    if not daemon_online:
        # Preserve the last daemon-derived lane capsule exactly as the original
        # poller did during an outage. Local panel/stale projections above still
        # render because their source of truth does not depend on the daemon.
        continue
    elif daemon_state == "running":
        atomic_text(
            status_root / f"vs-lane-{lane}.status",
            f"{CYAN}{spin} {TEXT}{mmss(daemon_task.get('started_at_epoch'))}{RESET}",
        )
    elif daemon_state == "queued":
        atomic_text(status_root / f"vs-lane-{lane}.status", f"{AMBER}◐ queued{RESET}")
    elif daemon_state == "done":
        atomic_text(status_root / f"vs-lane-{lane}.status", f"{CYAN}● done{RESET}")
    else:
        atomic_text(status_root / f"vs-lane-{lane}.status", f"{DIM}· idle{RESET}")

    if daemon_state == "running":
        specialist = safe_specialist(daemon_task.get("specialist"))
        suffix = f" {compact_name(specialist)}" if specialist else ""
        active_tokens.append(
            f"{TEXT}{lane} {CYAN}{spin} {TEXT}{mmss(daemon_task.get('started_at_epoch'))}{suffix}{RESET}"
        )
    elif daemon_state == "queued":
        active_tokens.append(f"{AMBER}{lane} queued{RESET}")

if active_tokens or stale_tokens:
    swarm = f"{DIM} · {RESET}".join(active_tokens + stale_tokens)
    if swarm_members:
        swarm += f" {DIM}· {AMBER}⚡SWARM ×{swarm_members}{RESET}"
else:
    clocks = "◴◷◶◵"
    clock_index = ((tick * 2) // 3) % len(clocks)
    breathe = (240, 245, 74, 245)[clock_index]
    swarm = f"#[fg=colour{breathe}]{clocks[clock_index]} chrono{RESET}"

atomic_text(status_root / "vs-swarm.status", swarm)
daemon_status = f"{CYAN}● daemon{RESET}" if daemon_online else f"{RED}● daemon offline{RESET}"
atomic_text(status_root / "vs-daemon.status", daemon_status)
PY

    if [[ "$VS_STATUS_ONCE" == "1" ]]; then
        break
    fi
    sleep "$VS_STATUS_INTERVAL"
done
