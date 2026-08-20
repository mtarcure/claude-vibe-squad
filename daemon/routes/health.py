from fastapi import APIRouter
from daemon.watcher import WATCHER

router = APIRouter()

@router.get("/health")
def health():
    # Was a hardcoded {"status": "ok"} regardless of whether the outbox watcher
    # ever started or had since crashed -- reflect its actual state instead.
    if WATCHER.last_error is not None:
        return {"status": "error", "version": "0.1.0", "watcher_error": WATCHER.last_error}
    if not WATCHER.running:
        return {"status": "starting", "version": "0.1.0"}
    return {"status": "ok", "version": "0.1.0"}
