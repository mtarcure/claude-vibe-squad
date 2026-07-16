import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from daemon.routes import catalog, events, health, mcp, summarize, task
from daemon.watcher import WATCHER
from daemon.auth import BearerTokenAuth

@asynccontextmanager
async def lifespan(_app: FastAPI):
    watcher_task = asyncio.create_task(WATCHER.run())
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
