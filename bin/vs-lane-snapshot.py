#!/usr/bin/env python3
"""Fast per-lane snapshot for the Chrono sidebar.

Replaces the sidebar's old approach of re-scanning 117 outbox files per card per
frame (~11s/frame). Reads the cheap sources — panel records + active-tasks.json —
every call, and the expensive outbox "last result" scan only every LAST_TTL
seconds (cached). Emits a compact, tab-separated, @-prefixed line format that the
bash renderer parses directly.

Output grammar (one lane block per model lane, in order):
    @LANE <lane> <state> <started_epoch>
    @WORK <specialist> <state> <started_epoch>      (0..N, the specialists on it)
    @TASK <title>                                    (0..1, what's being worked)
    @LAST <specialist> <result-title>                (0..1, most recent completion)

state ∈ running | queued | blocked | idle
"""
import glob
import json
import os
import re
import time
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
LANES = ["gpt-codex", "claude", "gemini", "kimi"]
NOW = int(time.time())
LANE_ACT = VAULT / "_state/runtime/lane-activity"
ACTIVE_TASKS = VAULT / "_state/active-tasks.json"
DEPTS = VAULT / "departments"
LAST_CACHE = Path(os.environ.get("VIBESQUAD_STATUS_DIR", "/tmp")) / "vs-lane-lastresult.json"
LAST_TTL = int(os.environ.get("VS_LAST_TTL", "20"))

_ctrl = re.compile(r"[\x00-\x1f\x7f]")


def clean(s):
    return _ctrl.sub("", str(s)).strip() if s is not None else ""


def load_json(path, default):
    try:
        v = json.loads(Path(path).read_text())
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


# ---- working specialists per lane: panels (members) + single active tasks ----
work = {l: [] for l in LANES}          # (specialist, state, started_epoch)
task_title = {l: "" for l in LANES}
has_queued = {l: False for l in LANES}
has_blocked = {l: False for l in LANES}

def panel_task_title(task_id):
    if not task_id:
        return ""
    for tf in glob.glob(str(DEPTS / f"*/*/{task_id}.md")):
        try:
            body = Path(tf).read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"^#\s+(.+)$", body.split("\n---", 2)[-1], re.M)
        if m:
            return clean(m.group(1))
    return ""


for p in glob.glob(str(LANE_ACT / "*.json")):
    r = load_json(p, {})
    if r.get("dispatch_kind") != "panel" or r.get("state") != "running":
        continue
    lane = r.get("lane")
    if lane not in LANES:
        continue
    # Skip orphaned/stale panels — a running record that stopped being updated
    # (crashed lane, killed session) past its ttl + grace. Mirrors the poller.
    updated = r.get("updated_at_epoch") or r.get("started_at_epoch") or 0
    ttl = r.get("stale_ttl_seconds", 60)
    try:
        if updated and NOW - int(updated) > int(ttl) + 30:
            continue
    except (TypeError, ValueError):
        pass
    for m in r.get("members", []):
        if isinstance(m, dict) and m.get("specialist"):
            st = m.get("state", "running")
            work[lane].append((clean(m["specialist"]), st, int(m.get("started_at_epoch") or 0)))
            if st == "queued":
                has_queued[lane] = True
    if not task_title[lane]:
        task_title[lane] = panel_task_title(r.get("task_id"))

at = load_json(ACTIVE_TASKS, {})
for tid, t in (at.items() if isinstance(at, dict) else []):
    if not isinstance(t, dict):
        continue
    lane = t.get("to_model")
    if lane not in LANES:
        continue
    # Dispatched epoch (also the running timer's start).
    de = 0
    try:
        from datetime import datetime
        da = t.get("dispatched_at")
        if da:
            de = int(datetime.fromisoformat(da.replace("Z", "+00:00")).timestamp())
    except Exception:
        de = 0
    # Skip stale registry cruft: the registry never expires entries, so a task
    # dispatched long ago (a day-old "blocked"/"in-flight") is NOT the lane's
    # current state. 4h is well beyond any real task.
    if de and NOW - de > 4 * 3600:
        continue
    # Normalize status (values vary: "in-flight", "In_Flight", "active", …).
    st = str(t.get("status", "")).strip().lower().replace("_", "-")
    spec = clean(t.get("specialist"))
    if st in ("active", "running", "dispatched", "in-flight", "inflight"):
        # The registry lags: it only reconciles on the NEXT dispatch, so a task
        # that just finished still reads "in-flight". If its response already
        # landed in outbox, the task is actually DONE — don't show it as running.
        if glob.glob(str(DEPTS / f"*/outbox/{tid}-response.md")):
            continue
        if spec and not any(w[0] == spec for w in work[lane]):
            work[lane].append((spec, "running", de))
        if not task_title[lane]:
            task_title[lane] = panel_task_title(tid)
    elif st in ("queued", "new", "pending"):
        has_queued[lane] = True
    elif st in ("blocked", "failed", "error", "needs-human"):
        has_blocked[lane] = True
    # complete / cancelled / done → not active, skipped

# ---- last result per lane: expensive outbox scan, cached with a TTL ----
cache = load_json(LAST_CACHE, {})
cache_ts = cache.get("_ts", 0) if isinstance(cache, dict) else 0
if not isinstance(cache, dict) or NOW - int(cache_ts or 0) > LAST_TTL:
    fresh = {"_ts": NOW}
    best = {l: (0, "", "") for l in LANES}   # (mtime, specialist, title)
    for resp in glob.glob(str(DEPTS / "*/outbox/TASK-*-response.md")):
        try:
            mtime = int(os.stat(resp).st_mtime)
        except OSError:
            continue
        tid = os.path.basename(resp)[:-len("-response.md")]
        ns = Path(resp).parent.parent.name
        # locate the task packet to read to_model + specialist
        lane = spec = None
        for d in ("inbox", "active", "archive"):
            tf = DEPTS / ns / d / f"{tid}.md"
            if tf.exists():
                head = tf.read_text(errors="replace").split("\n---", 1)[0]
                mm = re.search(r"^to_model:\s*(\S+)", head, re.M)
                ms = re.search(r"^specialist:\s*(\S+)", head, re.M)
                lane = mm.group(1) if mm else None
                spec = ms.group(1) if ms else None
                break
        if lane in LANES and mtime > best[lane][0]:
            # title = first H1 in the response body
            title = ""
            try:
                body = resp_text = Path(resp).read_text(errors="replace")
                mt = re.search(r"^#\s+(.+)$", body.split("\n---", 2)[-1], re.M)
                if mt:
                    title = clean(mt.group(1))
            except Exception:
                title = ""
            best[lane] = (mtime, clean(spec or ""), title)
    for l in LANES:
        fresh[l] = [best[l][1], best[l][2]]
    try:
        LAST_CACHE.write_text(json.dumps(fresh))
    except Exception:
        pass
    cache = fresh

# ---- emit ----
out = []
for lane in LANES:
    ws = work[lane]
    running = [w for w in ws if w[1] == "running"]
    if running:
        state = "running"
        started = min((w[2] for w in running if w[2] > 0), default=0)
    elif has_queued[lane] or any(w[1] == "queued" for w in ws):
        state = "queued"; started = 0
    elif has_blocked[lane]:
        state = "blocked"; started = 0
    else:
        state = "idle"; started = 0
    out.append(f"@LANE\t{lane}\t{state}\t{started}")
    for spec, st, s_ep in ws:
        out.append(f"@WORK\t{spec}\t{st}\t{s_ep}")
    if task_title[lane]:
        out.append(f"@TASK\t{task_title[lane]}")
    last = cache.get(lane) if isinstance(cache, dict) else None
    if isinstance(last, list) and (last[0] or (len(last) > 1 and last[1])):
        out.append(f"@LAST\t{last[0]}\t{last[1] if len(last) > 1 else ''}")

print("\n".join(out))
