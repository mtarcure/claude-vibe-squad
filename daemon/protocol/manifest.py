from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class OutboxManifest(BaseModel):
    task_id: str
    completed_at: datetime
    duration_seconds: float
    result: str
    tools_used: dict[str, int] = {}
    approvals_requested: int = 0
    tokens_used: dict[str, int] = {}
    next_actions: list[dict] = []
