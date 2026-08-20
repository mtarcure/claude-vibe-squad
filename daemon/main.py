import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from daemon.routes import catalog, events, health, mcp, summarize, task
from daemon.watcher import WATCHER
from daemon.auth import BearerTokenAuth

log = logging.getLogger(__name__)

def _log_watcher_result(t: asyncio.Task) -> None:
    # Without this, an exception from awatch() (e.g. the outbox dir vanishing)
    # is pinned by the live watcher_task local and never garbage-collected, so
    # asyncio's "exception was never retrieved" logging never fires either --
    # nothing is ever logged. /health surfaces WATCHER.last_error too.
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        WATCHER.last_error = f"{type(exc).__name__}: {exc}"
        log.error("outbox watcher task failed", exc_info=exc)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    watcher_task = asyncio.create_task(WATCHER.run())
    watcher_task.add_done_callback(_log_watcher_result)
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="vibe-squad daemon", version="0.1.0", lifespan=lifespan)
app.add_middleware(BearerTokenAuth)
app.include_router(health.router)
app.include_router(task.router)
app.include_router(mcp.router)
app.include_router(events.router)
app.include_router(summarize.router)
app.include_router(catalog.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9876)
