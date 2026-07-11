from pydantic import BaseModel, Field
from typing import Optional
import uuid
from datetime import datetime

class TaskPacket(BaseModel):
    task_id: str = Field(default_factory=lambda: f"t-{uuid.uuid4()}")
    project: Optional[str] = None
    specialist: str
    specialist_file: str
    version: str = "2.0"
    lane: str
    model: str
    model_key: str
    required_tools: list[str] = []
    preferred_tools: list[str] = []
    requires_approval: list[str] = []
    prompt: str
    context: dict = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
