#!/usr/bin/env bash
# Atomic lifecycle helper for panel-v1 activity records.
set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
ACTIVITY_ROOT="${PANEL_ACTIVITY_DIR:-${VAULT_ROOT}/_state/runtime/lane-activity}"

usage() {
    cat >&2 <<'EOF'
Usage:
  panel-activity.sh create --task-id ID --lane claude|gpt-codex --coordinator NAME --members a,b [--ttl SECONDS]
  panel-activity.sh update --task-id ID --member NAME --state running|done|failed|refused|timed_out [--detail TEXT]
  panel-activity.sh close --task-id ID --state done|failed|timed_out [--detail TEXT]
  panel-activity.sh sweep-stale [--ttl SECONDS]
  panel-activity.sh show --task-id ID
EOF
    exit 2
}

[[ $# -gt 0 ]] || usage

python3 - "$ACTIVITY_ROOT" "$@" <<'PY'
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

root = Path(sys.argv[1])
argv = sys.argv[2:]
name_re = re.compile(r"^[a-z0-9][a-z0-9-]*$")
task_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
member_terminal = {"done", "failed", "refused", "timed_out"}
member_transitions = {
    "queued": {"running", "failed", "refused", "timed_out"},
    "running": member_terminal,
    "done": set(),
    "failed": set(),
    "refused": set(),
    "timed_out": set(),
}


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


parser = argparse.ArgumentParser(add_help=False)
sub = parser.add_subparsers(dest="command", required=True)

create = sub.add_parser("create")
create.add_argument("--task-id", required=True)
create.add_argument("--lane", required=True, choices=("claude", "gpt-codex"))
create.add_argument("--coordinator", required=True)
create.add_argument("--members", required=True)
create.add_argument("--ttl", type=positive_int, default=300)

update = sub.add_parser("update")
update.add_argument("--task-id", required=True)
update.add_argument("--member", required=True)
update.add_argument("--state", required=True, choices=("running", "done", "failed", "refused", "timed_out"))
update.add_argument("--detail", default="")

close = sub.add_parser("close")
close.add_argument("--task-id", required=True)
close.add_argument("--state", required=True, choices=("done", "failed", "timed_out"))
close.add_argument("--detail", default="")

sweep = sub.add_parser("sweep-stale")
sweep.add_argument("--ttl", type=positive_int)

show = sub.add_parser("show")
show.add_argument("--task-id", required=True)

args = parser.parse_args(argv)
root.mkdir(parents=True, exist_ok=True)
archive = root / "archive"


def validate_task_id(task_id: str) -> None:
    if not task_re.fullmatch(task_id):
        raise SystemExit(f"invalid task id: {task_id}")


def active_path(task_id: str) -> Path:
    validate_task_id(task_id)
    return root / f"{task_id}.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"activity record not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid activity JSON {path}: {exc}")
    if data.get("schema_version") != 1:
        raise SystemExit(f"unsupported activity schema in {path}")
    return data


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


now = int(time.time())

if args.command == "create":
    validate_task_id(args.task_id)
    if not name_re.fullmatch(args.coordinator):
        raise SystemExit(f"invalid coordinator: {args.coordinator}")
    members = [item.strip() for item in args.members.split(",") if item.strip()]
    if not 2 <= len(members) <= 3:
        raise SystemExit("panel-v1 requires 2-3 members")
    if len(set(members)) != len(members):
        raise SystemExit("panel members must be unique")
    invalid = [member for member in members if not name_re.fullmatch(member)]
    if invalid:
        raise SystemExit(f"invalid panel members: {','.join(invalid)}")
    path = active_path(args.task_id)
    if path.exists() or (archive / path.name).exists():
        raise SystemExit(f"activity record already exists: {args.task_id}")
    data = {
        "schema_version": 1,
        "task_id": args.task_id,
        "panel_id": "PANEL-" + args.task_id.removeprefix("TASK-"),
        "lane": args.lane,
        "dispatch_kind": "panel",
        "coordinator": args.coordinator,
        "state": "running",
        "started_at_epoch": now,
        "updated_at_epoch": now,
        "stale_ttl_seconds": args.ttl,
        "members": [
            {"specialist": member, "state": "queued", "queued_at_epoch": now}
            for member in members
        ],
    }
    atomic_write(path, data)
    print(json.dumps(data, sort_keys=True))

elif args.command == "update":
    path = active_path(args.task_id)
    data = load(path)
    target = next((item for item in data["members"] if item["specialist"] == args.member), None)
    if target is None:
        raise SystemExit(f"member not found: {args.member}")
    previous = target["state"]
    if args.state == previous:
        print(json.dumps(data, sort_keys=True))
        raise SystemExit(0)
    if args.state not in member_transitions.get(previous, set()):
        raise SystemExit(f"invalid member transition: {previous} -> {args.state}")
    target["state"] = args.state
    if args.state == "running":
        target["started_at_epoch"] = now
    if args.state in member_terminal:
        target["ended_at_epoch"] = now
    if args.detail:
        target["detail"] = args.detail
    data["updated_at_epoch"] = now
    atomic_write(path, data)
    print(json.dumps(data, sort_keys=True))

elif args.command == "close":
    path = active_path(args.task_id)
    archived_path = archive / path.name
    if not path.exists() and archived_path.exists():
        print(archived_path)
        raise SystemExit(0)
    data = load(path)
    data["state"] = args.state
    data["ended_at_epoch"] = now
    data["updated_at_epoch"] = now
    if args.detail:
        data["detail"] = args.detail
    atomic_write(path, data)
    archive.mkdir(parents=True, exist_ok=True)
    if archived_path.exists():
        raise SystemExit(f"archive record already exists: {archived_path}")
    os.replace(path, archived_path)
    print(archived_path)

elif args.command == "sweep-stale":
    changed = []
    for path in sorted(root.glob("*.json")):
        data = load(path)
        ttl = args.ttl or int(data.get("stale_ttl_seconds", 300))
        if data.get("state") != "running" or now - int(data.get("updated_at_epoch", 0)) <= ttl:
            continue
        data["state"] = "stale"
        data["stale_at_epoch"] = now
        data["updated_at_epoch"] = now
        for member in data.get("members", []):
            if member.get("state") in {"queued", "running"}:
                member["state"] = "timed_out"
                member["ended_at_epoch"] = now
                member["detail"] = "coordinator activity TTL expired"
        atomic_write(path, data)
        changed.append(data["task_id"])
    print(json.dumps({"stale": changed}, sort_keys=True))

elif args.command == "show":
    path = active_path(args.task_id)
    if not path.exists():
        path = archive / path.name
    print(json.dumps(load(path), indent=2, sort_keys=True))
PY
