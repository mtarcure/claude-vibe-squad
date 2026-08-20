#!/usr/bin/env python3
"""Spawn-centric board snapshot for the board-native dashboard.

Sources the active set from REAL board-dispatch state: an exact v2 descriptor,
matching live process birth/argv/group identity, and no exact terminal receipt.
Registry flags and file mtimes never decide whether a card is running. Emits:

  @SPAWN <task_id> <lane> <specialist> <started_epoch> <pid> <log_path>
  @SUMMARY <one-line task title>
  @DONE <ended_epoch> <task_id> <lane> <specialist> <status> <duration_s> <memory_id>
  @DEFECT <task_id> <attempt_id> <generation> <reason>

The board remains authoritative.
"""
import os
import re
import sys
from pathlib import Path

_VAULT_ROOT_ENV = os.environ.get("VAULT_ROOT")
if not _VAULT_ROOT_ENV:
    # Fail loud -- no maintainer-path default. Run via bin/vs-dashboard-loop.sh
    # (or another caller that sources shared/repo-root.sh) rather than directly.
    sys.exit("VAULT_ROOT not set. Run via a caller that exports VAULT_ROOT.")
VAULT = Path(_VAULT_ROOT_ENV)
BOARD = VAULT / "_state" / "board-dispatch"
HISTORY_LIMIT = int(os.environ.get("VS_BOARD_HISTORY", "20"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "python"))
from board_process_truth import (  # noqa: E402
    context_matches,
    descriptor_error,
    load_json,
    process_truth,
    timestamp_epoch,
    terminal_outcome,
)

_TITLE_RE = re.compile(r"^#[ \t]+(.+)$", re.M)


def _clean(text, limit=72):
    text = " ".join(str(text).split())
    return text[:limit]


def _summary(context):
    if not context:
        return ""
    prompt = context.get("task_prompt", "")
    match = _TITLE_RE.search(prompt if isinstance(prompt, str) else "")
    return _clean(match.group(1)) if match else ""


def main():
    if not BOARD.is_dir():
        return 0
    active, done, defects = [], [], []
    for dispatch_path in BOARD.glob("*.dispatch.json"):
        dispatch = load_json(dispatch_path)
        if not dispatch:
            defects.append((_clean(dispatch_path.name, 200), "?", "?", "descriptor_json_invalid"))
            continue
        task_id = _clean(dispatch.get("task_id", dispatch_path.name), 200)
        attempt_id = _clean(dispatch.get("attempt_id", "?"), 200)
        generation = dispatch.get("generation", "?")
        error = descriptor_error(dispatch_path, dispatch)
        if error:
            defects.append((task_id, attempt_id, generation, error))
            continue
        context = load_json(dispatch["context_path"])
        if not context_matches(dispatch, context):
            defects.append((task_id, attempt_id, generation, "context_identity_mismatch"))
            continue
        receipt = load_json(dispatch["receipt_path"])
        outcome = terminal_outcome(receipt, dispatch)
        started = timestamp_epoch(dispatch.get("created_at")) or 0
        authority = (context or {}).get("authority") or {}
        lane = authority.get("lane") or "?"
        specialist = authority.get("specialist") or "?"
        lane_args = authority.get("lane_args") or []
        lane_args = lane_args if isinstance(lane_args, list) else []
        try:
            model = lane_args[lane_args.index("--model") + 1]
        except (ValueError, IndexError):
            model = lane

        truth = process_truth(dispatch_path, dispatch) if outcome is None else None
        if outcome is None and truth["state"] == "live":
            active.append({"task_id": task_id, "lane": lane, "specialist": specialist,
                           "started": started, "pid": dispatch.get("pid", 0),
                           "log": dispatch["log_path"], "summary": _summary(context), "model": model})
        elif outcome is not None:
            ended = timestamp_epoch(receipt.get("completed_at")) or 0
            done.append({"ended": ended, "task_id": task_id, "lane": lane,
                         "specialist": specialist, "status": outcome,
                         "duration": max(0, ended - started) if ended and started else 0,
                         "memory_id": receipt.get("memory_id") or "-"})
        else:
            defects.append((task_id, attempt_id, generation, truth["reason"]))

    active.sort(key=lambda item: item["started"])
    done.sort(key=lambda item: item["ended"], reverse=True)
    out = []
    for spawn in active:
        out.append("@SPAWN\t{task_id}\t{lane}\t{specialist}\t{started}\t{pid}\t{log}\t{model}".format(**spawn))
        out.append("@SUMMARY\t{}".format(spawn["summary"]))
    for entry in done[:HISTORY_LIMIT]:
        out.append("@DONE\t{ended}\t{task_id}\t{lane}\t{specialist}\t{status}\t{duration}\t{memory_id}".format(**entry))
    for task_id, attempt_id, generation, reason in defects:
        out.append("@DEFECT\t{}\t{}\t{}\t{}".format(task_id, attempt_id, generation, _clean(reason, 160)))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
