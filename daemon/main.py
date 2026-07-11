from fastapi import FastAPI
from daemon.routes import health, task, mcp, events
from daemon.watcher import WATCHER
import asyncio

app = FastAPI(title="vibe-squad daemon", version="0.1.0")
app.include_router(health.router)
app.include_router(task.router)
app.include_router(mcp.router)
app.include_router(events.router)

@app.on_event("startup")
async def start_watcher():
    asyncio.create_task(WATCHER.run())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9876)
