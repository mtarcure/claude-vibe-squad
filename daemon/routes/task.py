"""Read-only task status routes for the optional daemon."""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import os
import yaml

router = APIRouter()

def _state_dir() -> Path:
    override = os.environ.get("VIBESQUAD_STATE_DIR")
    if override:
        return Path(override)
    vault_root = os.environ.get("VAULT_ROOT")
    if not vault_root:
        # Fail loud -- no silent default. A guessed maintainer path here meant a
        # public clone at e.g. ~/src/vibe-squad got a phantom root: /tasks always
        # empty, indistinguishable from an idle squad. Start via
        # bin/daemon-launcher.sh, which sources shared/repo-root.sh and exports
        # VAULT_ROOT before this runs.
        raise RuntimeError(
            "VAULT_ROOT not set. Start via bin/daemon-launcher.sh, or set "
            "VAULT_ROOT / VIBESQUAD_STATE_DIR explicitly."
        )
    return Path(vault_root) / "daemon" / "state"

def _read_task_meta(task_file: Path) -> dict:
    """Best-effort read of task packet or outbox manifest — returns fields UX needs."""
    default = {
        "started_at_epoch": _mtime_epoch(task_file),
        "tokens_used": 0,
    }
    try:
        data = yaml.safe_load(task_file.read_text()) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return default
    if not isinstance(data, dict):
        return default
    return {
        "started_at_epoch": data.get("started_at_epoch") or _mtime_epoch(task_file),
        "tokens_used": _sum_tokens(data.get("tokens_used", 0)),
    }

def _mtime_epoch(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except Exception:
        return 0

def _sum_tokens(value) -> int:
    """tokens_used may be int, dict of {input, output}, or missing."""
    if isinstance(value, dict):
        return sum(int(v) for v in value.values() if isinstance(v, (int, float)))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

@router.get("/tasks")
def list_tasks():
    """List tasks across inbox (queued), active (running), outbox (done).

    Each task includes lane, state, tokens_used, and started_at_epoch so the
    tmux status-bar helper can render spinners/timers/token counts without
    parsing raw markdown per pane.
    """
    state = _state_dir()
    tasks = []

    # Queued — sitting in inbox/
    for lane_dir in (state / "inbox").glob("*") if (state / "inbox").exists() else []:
        for task_file in lane_dir.glob("*.md"):
            meta = _read_task_meta(task_file)
            tasks.append({
                "task_id": task_file.stem,
                "lane": lane_dir.name,
                "state": "queued",
                "tokens_used": meta["tokens_used"],
                "started_at_epoch": meta["started_at_epoch"],
            })

    # Running — sitting in active/
    for lane_dir in (state / "active").glob("*") if (state / "active").exists() else []:
        for task_file in lane_dir.glob("*.md"):
            meta = _read_task_meta(task_file)
            tasks.append({
                "task_id": task_file.stem,
                "lane": lane_dir.name,
                "state": "running",
                "tokens_used": meta["tokens_used"],
                "started_at_epoch": meta["started_at_epoch"],
            })

    # Done — sitting in outbox/ (recent only — cap to prevent unbounded growth)
    for lane_dir in (state / "outbox").glob("*") if (state / "outbox").exists() else []:
        outbox_files = sorted(lane_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        for task_file in outbox_files:
            meta = _read_task_meta(task_file)
            tasks.append({
                "task_id": task_file.stem,
                "lane": lane_dir.name,
                "state": "done",
                "tokens_used": meta["tokens_used"],
                "started_at_epoch": meta["started_at_epoch"],
            })

    return {"tasks": tasks}

@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    state = _state_dir()
    for path in state.rglob(f"{task_id}.md"):
        return {"task_id": task_id, "path": str(path)}
    raise HTTPException(status_code=404, detail="task not found")
