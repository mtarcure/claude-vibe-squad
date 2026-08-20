import asyncio
from pathlib import Path
from watchfiles import awatch, Change
import os

class OutboxWatcher:
    def __init__(self):
        self.subscribers: list[asyncio.Queue] = []
        # /health reports these instead of a hardcoded "ok" (daemon/main.py
        # wires the watcher task's done-callback to last_error).
        self.running = False
        self.last_error: str | None = None

    def _state_dir(self) -> Path:
        override = os.environ.get("VIBESQUAD_STATE_DIR")
        if override:
            return Path(override)
        vault_root = os.environ.get("VAULT_ROOT")
        if not vault_root:
            # Fail loud -- no silent default. A guessed maintainer path here,
            # plus this module's own mkdir(parents=True) below, would otherwise
            # watch a phantom directory nothing writes to: /health ok, /events
            # never fires. Start via bin/daemon-launcher.sh, which sources
            # shared/repo-root.sh and exports VAULT_ROOT before this runs.
            raise RuntimeError(
                "VAULT_ROOT not set. Start via bin/daemon-launcher.sh, or set "
                "VAULT_ROOT / VIBESQUAD_STATE_DIR explicitly."
            )
        return Path(vault_root) / "daemon" / "state"

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
        self.running = True
        try:
            async for changes in awatch(str(outbox)):
                for change_type, path in changes:
                    if change_type == Change.added and path.endswith(".md"):
                        p = Path(path)
                        event = {"type": "task_complete", "task_id": p.stem, "path": str(p)}
                        for q in self.subscribers:
                            await q.put(event)
        finally:
            self.running = False

WATCHER = OutboxWatcher()
