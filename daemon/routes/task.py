from fastapi import APIRouter, HTTPException
from pathlib import Path
import os
from daemon.protocol.packet import TaskPacket
from daemon.protocol.writer import atomic_write_yaml
from daemon.circuit_breaker import get_breaker, BreakerState

router = APIRouter()

def _state_dir() -> Path:
    return Path(os.environ.get("VIBESQUAD_STATE_DIR", "/Users/user/Obsidian-Claude-Vibe-Squad/daemon/state"))

@router.post("/task")
def create_task(packet: TaskPacket):
    breaker = get_breaker(packet.lane)
    if breaker.check() == BreakerState.OPEN:
        raise HTTPException(status_code=503, detail=f"circuit open for lane {packet.lane}, refusing dispatch")
    inbox = _state_dir() / "inbox" / packet.lane
    target = inbox / f"{packet.task_id}.md"
    atomic_write_yaml(target, packet.model_dump(mode="json"))
    return {"task_id": packet.task_id, "path": str(target)}

@router.get("/tasks")
def list_tasks():
    state = _state_dir()
    tasks = []
    for lane_dir in (state / "inbox").glob("*") if (state / "inbox").exists() else []:
        for task_file in lane_dir.glob("*.md"):
            tasks.append({"task_id": task_file.stem, "lane": lane_dir.name, "state": "queued"})
    return {"tasks": tasks}

@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    state = _state_dir()
    for path in state.rglob(f"{task_id}.md"):
        return {"task_id": task_id, "path": str(path)}
    raise HTTPException(status_code=404, detail="task not found")
