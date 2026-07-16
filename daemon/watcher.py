import asyncio
from pathlib import Path
from watchfiles import awatch, Change
import os

class OutboxWatcher:
    def __init__(self):
        self.subscribers: list[asyncio.Queue] = []

    def _state_dir(self) -> Path:
        vault_root = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
        return Path(os.environ.get("VIBESQUAD_STATE_DIR", str(vault_root / "daemon" / "state")))

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def run(self):
        outbox = self._state_dir() / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        async for changes in awatch(str(outbox)):
            for change_type, path in changes:
                if change_type == Change.added and path.endswith(".md"):
                    p = Path(path)
                    event = {"type": "task_complete", "task_id": p.stem, "path": str(p)}
                    for q in self.subscribers:
                        await q.put(event)

WATCHER = OutboxWatcher()
