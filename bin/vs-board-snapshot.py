#!/usr/bin/env python3
"""Spawn-centric board snapshot for the board-native dashboard.

Sources the active set from REAL board-dispatch state (a live detached supervisor
with an alive pid and no terminal receipt) instead of the stale active-tasks.json
in-flight flags that produced ghost "running" cards. Emits:

  @SPAWN <task_id> <lane> <specialist> <started_epoch> <pid> <log_path>
  @SUMMARY <one-line task title>
  @DONE <ended_epoch> <task_id> <lane> <specialist> <status> <duration_s> <memory_id>

@SPAWN blocks (0..N) drive the dynamic cards — a card exists only while its spawn is
live. @DONE lines (most-recent first, bounded) drive the completed-CLI history rail.

Cheap: one directory scan + small JSON reads per frame; no shelling out per card.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
BOARD = VAULT / "_state" / "board-dispatch"
NOW = int(time.time())
HISTORY_LIMIT = int(os.environ.get("VS_BOARD_HISTORY", "20"))

# A one-line, single-hash heading in the packet body is the human task title.
_TITLE_RE = re.compile(r"^#[ \t]+(.+)$", re.M)
_TERMINAL = {"complete", "completed", "blocked", "needs_review", "launched", "failed"}


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another uid
    except OSError:
        return False
    return True


def _clean(text, limit=72):
    text = " ".join(str(text).split())
    return text[:limit]


def _summary(context):
    if not context:
        return ""
    match = _TITLE_RE.search(context.get("task_prompt", ""))
    return _clean(match.group(1)) if match else ""


def main():
    if not BOARD.is_dir():
        return
    active, done = [], []
    for dispatch_path in BOARD.glob("*.dispatch.json"):
        dispatch = _load(dispatch_path)
        if not dispatch:
            continue
        task_id = dispatch.get("task_id", dispatch_path.name)
        base = str(dispatch_path)[: -len(".dispatch.json")]
        receipt = _load(base + ".receipt.json")
        receipt_file = Path(base + ".receipt.json")
        has_receipt = bool(receipt) and receipt.get("status") in _TERMINAL
        started = int(dispatch_path.stat().st_mtime)
        context = _load(base + ".context.json")
        authority = (context or {}).get("authority") or {}
        lane = authority.get("lane") or "?"
        specialist = authority.get("specialist") or "?"
        lane_args = authority.get("lane_args") or []
        model = lane_args[lane_args.index("--model") + 1] if "--model" in lane_args else lane

        if not has_receipt and _pid_alive(dispatch.get("pid")):
            active.append(
                {
                    "task_id": task_id,
                    "lane": lane,
                    "specialist": specialist,
                    "started": started,
                    "pid": dispatch.get("pid", 0),
                    "log": dispatch.get("log_path", base + ".log"),
                    "summary": _summary(context),
                    "model": model,
                }
            )
        elif has_receipt:
            ended = int(receipt_file.stat().st_mtime)
            status = receipt.get("status", "?")
            # board "launched" + a complete response == done-ok; surface response_status
            # when it refines the outcome (complete / needs_review / blocked).
            resp = receipt.get("response_status")
            if status == "launched" and resp:
                status = resp
            done.append(
                {
                    "ended": ended,
                    "task_id": task_id,
                    "lane": lane,
                    "specialist": specialist,
                    "status": status,
                    "duration": max(0, ended - started),
                    "memory_id": receipt.get("memory_id") or "-",
                }
            )

    active.sort(key=lambda item: item["started"])
    done.sort(key=lambda item: item["ended"], reverse=True)

    out = []
    for spawn in active:
        out.append(
            "@SPAWN\t{task_id}\t{lane}\t{specialist}\t{started}\t{pid}\t{log}\t{model}".format(**spawn)
        )
        out.append("@SUMMARY\t{}".format(spawn["summary"]))
    for entry in done[:HISTORY_LIMIT]:
        out.append(
            "@DONE\t{ended}\t{task_id}\t{lane}\t{specialist}\t{status}\t{duration}\t{memory_id}".format(
                **entry
            )
        )
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))


if __name__ == "__main__":
    main()
