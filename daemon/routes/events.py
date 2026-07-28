from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from daemon.watcher import WATCHER
import json

router = APIRouter()

@router.websocket("/events")
async def events_stream(ws: WebSocket):
    await ws.accept()
    queue = await WATCHER.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        await WATCHER.unsubscribe(queue)
