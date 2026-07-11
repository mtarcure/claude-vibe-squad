from fastapi import FastAPI
from daemon.routes import health, task, mcp

app = FastAPI(title="vibe-squad daemon", version="0.1.0")
app.include_router(health.router)
app.include_router(task.router)
app.include_router(mcp.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9876)
